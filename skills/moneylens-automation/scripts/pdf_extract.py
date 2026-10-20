#!/usr/bin/env python3
"""Unlock and extract PDFs locally; secret values never enter command output."""
import argparse
import datetime as dt
import json
import logging
import os
from pathlib import Path
import sys

SERVICE = 'com.moneylens.codex.pdf-password'


class Failure(ValueError):
    pass


class Keychain:
    def __init__(self):
        if sys.platform != 'darwin': raise Failure('PDF credentials require macOS Keychain')
        try:
            import Security
            import LocalAuthentication
        except ImportError as exc:
            raise Failure('Install the PDF helper requirements in the MoneyLens runtime') from exc
        self.s, self.la = Security, LocalAuthentication

    def query(self, account, no_prompt=False):
        s = self.s
        # Login-Keychain ACL dialogs also need the legacy per-process control.
        status = s.SecKeychainSetUserInteractionAllowed(not no_prompt)
        if status != s.errSecSuccess: raise Failure('Could not set Keychain interaction policy')
        q = {s.kSecClass: s.kSecClassGenericPassword, s.kSecAttrService: SERVICE, s.kSecAttrAccount: account}
        if no_prompt:
            context = self.la.LAContext.alloc().init()
            context.setInteractionNotAllowed_(True)
            q[s.kSecUseAuthenticationContext] = context
            q[s.kSecUseAuthenticationUI] = s.kSecUseAuthenticationUIFail
        return q

    def get(self, account, no_prompt=False):
        s = self.s
        q = self.query(account, no_prompt)
        q.update({s.kSecReturnData: True, s.kSecMatchLimit: s.kSecMatchLimitOne})
        status, value = s.SecItemCopyMatching(q, None)
        if status == s.errSecItemNotFound: return None
        if status != s.errSecSuccess: raise Failure(f'Keychain access failed (status {status}); run setup to repair access')
        return bytes(value).decode('utf-8')

    def present(self, account):
        s = self.s
        q = self.query(account, True)
        q.update({s.kSecReturnAttributes: True, s.kSecMatchLimit: s.kSecMatchLimitOne})
        status, _ = s.SecItemCopyMatching(q, None)
        if status == s.errSecItemNotFound: return False
        if status != s.errSecSuccess: raise Failure(f'Keychain status unavailable without interaction (status {status})')
        return True

    def save(self, account, password):
        s = self.s
        q = self.query(account)
        status = s.SecItemUpdate(q, {s.kSecValueData: password.encode('utf-8')})
        if status == s.errSecItemNotFound:
            q.update({s.kSecValueData: password.encode('utf-8'), s.kSecAttrSynchronizable: False,
                      s.kSecAttrLabel: 'MoneyLens statement PDF password'})
            status, _ = s.SecItemAdd(q, None)
        if status != s.errSecSuccess: raise Failure(f'Could not save verified PDF password (status {status})')


def prompt_password(filename):
    try:
        import AppKit as A
    except ImportError as exc:
        raise Failure('Install the PDF helper requirements for the local masked prompt') from exc
    app = A.NSApplication.sharedApplication()
    app.setActivationPolicy_(A.NSApplicationActivationPolicyAccessory)
    alert = A.NSAlert.alloc().init()
    alert.setMessageText_('Unlock statement for MoneyLens')
    alert.setInformativeText_(f'File: {filename}\nAfter a successful unlock, the password is saved in this Mac\'s Keychain. It is not sent to chat.')
    alert.addButtonWithTitle_('Unlock and Save')
    alert.addButtonWithTitle_('Cancel')
    field = A.NSSecureTextField.alloc().initWithFrame_(A.NSMakeRect(0, 0, 320, 26))
    alert.setAccessoryView_(field)
    alert.window().setInitialFirstResponder_(field)
    app.activateIgnoringOtherApps_(True)
    if alert.runModal() != A.NSAlertFirstButtonReturn: raise Failure('Cancelled; statement was not extracted')
    return str(field.stringValue())


def derive_candidates(stream):
    raw = stream.read(16385)
    if len(raw) > 16384: raise Failure('Password recipe input exceeds 16 KiB')
    data = json.loads(raw)
    attrs, recipes = data.get('attributes'), data.get('recipes')
    if not isinstance(attrs, dict) or not all(isinstance(v, str) for v in attrs.values()): raise Failure('Known attributes must be text values')
    if not isinstance(recipes, list) or not 1 <= len(recipes) <= 3: raise Failure('Provide one to three document-supported password recipes')
    prefix = ''.join(ch for ch in attrs.get('full_name', '') if ch.isalpha())[:4]
    card, birthday = attrs.get('card_last4', ''), attrs.get('birth_ddmm', '')
    if not birthday and attrs.get('birth_date'): birthday = dt.date.fromisoformat(attrs['birth_date']).strftime('%d%m')
    values = []
    for recipe in recipes:
        value = None
        if recipe == 'name4_upper_card_last4':
            if len(prefix) == 4 and len(card) == 4 and card.isdigit(): value = prefix.upper() + card
        elif recipe in ('name4_lower_birth_ddmm', 'name4_upper_birth_ddmm'):
            if len(prefix) == 4 and len(birthday) == 4 and birthday.isdigit():
                value = (prefix.lower() if 'lower' in recipe else prefix.upper()) + birthday
        else: raise Failure('Unsupported password recipe; use the issuer instructions or the masked prompt')
        if value is not None and value not in values: values.append(value)
    return values


def unlock(reader, candidates, account, no_prompt=False, previous=None, keychain=None, prompt=None):
    keychain = keychain if keychain is not None else Keychain()
    saved = keychain.get(account, no_prompt)
    copy = False
    if saved is None and previous:
        saved = keychain.get(previous, no_prompt)
        copy = saved is not None
    if saved is not None and reader.decrypt(saved):
        if copy: keychain.save(account, saved)
        return
    for candidate in candidates:
        if reader.decrypt(candidate):
            keychain.save(account, candidate)
            return
    if no_prompt: raise Failure('Setup required: saved password is missing or no longer unlocks this PDF')
    password = (prompt or prompt_password)(Path(reader.stream.name).name if hasattr(reader.stream, 'name') else 'statement.pdf')
    if not reader.decrypt(password): raise Failure('Password did not unlock this PDF; no replacement was saved')
    keychain.save(account, password)


def run(args, stream=None):
    os.umask(0o077)
    if args.no_prompt and (args.previous_account or args.derive_from_stdin): raise Failure('Credential migration and derivation are setup-only')
    if args.keychain_status:
        if not args.account: raise Failure('--account is required')
        return {'credential_present': Keychain().present(args.account)}
    if args.input is None: raise Failure('--input is required')
    path = args.input.resolve()
    if path.stat().st_size > 20 * 1024 * 1024: raise Failure('Input exceeds 20 MiB')
    try:
        from pypdf import PdfReader
    except ImportError as exc: raise Failure('Install the PDF helper requirements in the MoneyLens runtime') from exc
    logging.getLogger('pypdf').setLevel(logging.CRITICAL)
    reader = PdfReader(path, strict=False)
    locked = bool(reader.is_encrypted and not reader.decrypt(''))
    if args.probe:
        return {'encrypted': reader.is_encrypted, 'locked': locked, 'page_count': 0 if locked else len(reader.pages)}
    candidates = derive_candidates(stream or sys.stdin) if args.derive_from_stdin or args.verify_derived_only else []
    if args.verify_derived_only:
        if not locked: raise Failure('Derivation verification needs a locked PDF')
        for index, candidate in enumerate(candidates, 1):
            if reader.decrypt(candidate): return {'derived_unlock': True, 'attempts': index}
        raise Failure('Known attributes did not unlock the PDF; request missing or corrected information')
    if not args.account or args.output is None: raise Failure('--account and --output are required')
    output = args.output.resolve()
    if output == path or output.exists(): raise Failure('Output must be a new file separate from the PDF')
    if locked: unlock(reader, candidates, args.account, args.no_prompt, args.previous_account)
    candidates.clear()
    if not 1 <= len(reader.pages) <= 100: raise Failure('PDF must contain 1–100 pages')
    payload = {'pages': [{'page': i + 1, 'text': page.extract_text() or ''} for i, page in enumerate(reader.pages)],
               'page_count': len(reader.pages), 'encrypted': reader.is_encrypted}
    with output.open('x', encoding='utf-8') as f: json.dump(payload, f)
    os.chmod(output, 0o600)
    return {'result': 'extracted', 'page_count': len(reader.pages)}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--input', type=Path)
    p.add_argument('--output', type=Path)
    p.add_argument('--account')
    p.add_argument('--previous-account')
    for flag in ('probe', 'no-prompt', 'keychain-status', 'derive-from-stdin', 'verify-derived-only'):
        p.add_argument('--' + flag, action='store_true')
    print(json.dumps(run(p.parse_args())))


if __name__ == '__main__':
    try: main()
    except Failure as exc:
        print(json.dumps({'error': str(exc)}), file=sys.stderr)
        sys.exit(1)
    except Exception:
        # Library/OS exception messages can contain document text or secret values.
        print(json.dumps({'error': 'PDF processing failed; check the source, output, runtime, and local access'}), file=sys.stderr)
        sys.exit(1)
