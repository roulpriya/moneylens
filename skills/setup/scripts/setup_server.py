#!/usr/bin/env python3
"""Last-resort local form. Submitted values are never returned in HTTP responses or logs."""
import argparse
import hashlib
import hmac
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import io
import logging
import os
from pathlib import Path
import secrets
import sys
import time
from urllib.parse import urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'automation'))
from moneylens.private_files import check_private, protect
from moneylens.credentials import selected

FIELDS = {
    'name': {'id': 'name', 'label': 'Name on the statement', 'type': 'text', 'maxLength': 256,
             'help': 'Use the name and spelling required by the statement’s unlocking instructions.'},
    'phone': {'id': 'phone', 'label': 'Phone number', 'type': 'tel', 'maxLength': 128,
              'help': 'Enter only the number or digits the statement’s instructions require.'},
    'date_of_birth': {'id': 'date_of_birth', 'label': 'Date of birth', 'type': 'text', 'maxLength': 64,
                      'help': 'Use the exact format stated in the unlocking instructions.'},
    'password': {'id': 'password', 'label': 'PDF password', 'type': 'password', 'maxLength': 4096,
                 'help': 'For this statement document only. Never enter a bank-login password, PIN, or one-time code.'},
}
CONFIG_MARKER = '<script id="setup-config" type="application/json">{"fields":[],"scope":"","context":"","token":""}</script>'
CSP = "default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; font-src data:; img-src data:; connect-src 'self'; form-action 'none'; base-uri 'none'; frame-ancestors 'none'"


class UnlockFailed(ValueError):
    pass


def request_details(request):
    """Only descriptive metadata goes to the browser, never recipe known-values."""
    allowed = {'bank', 'statement_type', 'period', 'account_hint', 'filename', 'email_subject', 'email_date', 'email_url', 'instructions'}
    result = {}
    for key in allowed:
        value = request.get(key, '')
        if not isinstance(value, str) or len(value) > 3000:
            raise ValueError('Invalid statement context')
        if value:
            result[key] = value
    if result.get('email_url'):
        url = urlsplit(result['email_url'])
        if url.scheme != 'https' or not url.hostname or url.username or url.password:
            raise ValueError('Use the actual HTTPS email link supplied by the connector')
    return result


def validate_recipe(recipe, fields):
    if not isinstance(recipe, dict) or set(recipe) - {'parts', 'known_values'}:
        raise ValueError('Invalid observed recipe')
    known = recipe.get('known_values', {})
    parts = recipe.get('parts')
    if not isinstance(known, dict) or set(known) & set(fields) or set(known) - set(FIELDS):
        raise ValueError('Do not ask again for known inputs')
    if any(not isinstance(v, str) or not v.strip() or len(v) > FIELDS[k]['maxLength'] for k, v in known.items()):
        raise ValueError('Invalid known inputs')
    if not isinstance(parts, list) or not 1 <= len(parts) <= 16:
        raise ValueError('Supply the exact observed recipe parts')
    used = set()
    for part in parts:
        if not isinstance(part, dict):
            raise ValueError('Invalid recipe part')
        if set(part) == {'literal'}:
            if not isinstance(part['literal'], str) or len(part['literal']) > 128:
                raise ValueError('Invalid recipe literal')
            continue
        if set(part) - {'field', 'slice', 'case', 'remove_whitespace', 'digits_only'} or 'field' not in part:
            raise ValueError('Unsupported recipe operation')
        if part['field'] not in set(fields) | set(known):
            raise ValueError('Recipe depends on an unavailable input')
        used.add(part['field'])
        bounds = part.get('slice', [None, None])
        if not isinstance(bounds, list) or len(bounds) != 2 or any(v is not None and (type(v) is not int or abs(v) > 4096) for v in bounds):
            raise ValueError('Invalid recipe slice')
        if part.get('case', 'preserve') not in ('preserve', 'upper', 'lower'):
            raise ValueError('Invalid recipe case')
        if any(type(part[key]) is not bool for key in ('remove_whitespace', 'digits_only') if key in part):
            raise ValueError('Invalid recipe transformation')
    if used != set(fields) | set(known):
        raise ValueError('Request only inputs used by the observed recipe')


def derive_password(recipe, values):
    merged = {**recipe.get('known_values', {}), **values}
    output = []
    for part in recipe['parts']:
        if 'literal' in part:
            output.append(part['literal'])
            continue
        value = merged[part['field']]
        if part.get('remove_whitespace'):
            value = ''.join(value.split())
        if part.get('digits_only'):
            value = ''.join(c for c in value if '0' <= c <= '9')
        start, stop = part.get('slice', [None, None])
        value = value[start:stop]
        if part.get('case') == 'upper':
            value = value.upper()
        elif part.get('case') == 'lower':
            value = value.lower()
        output.append(value)
    result = ''.join(output)
    if not 0 < len(result) <= 4096:
        raise ValueError('Recipe produced an invalid candidate')
    return result


class SetupServer(HTTPServer):
    allow_reuse_address = False

    def __init__(self, output, fields, scope, context='', port=0, lifetime=1800,
                 request=None, pdf=None, data_dir=None):
        output = Path(output).absolute()
        if not fields or len(set(fields)) != len(fields) or any(key not in FIELDS for key in fields):
            raise ValueError('Choose only the missing supported fields, without duplicates')
        if not scope.strip() or len(scope) > 200 or len(context) > 2000:
            raise ValueError('Use a short nonsecret scope and explanation')
        if output.exists() or output.is_symlink():
            raise ValueError('Output already exists; choose a new private file')
        if not output.parent.exists():
            output.parent.mkdir(parents=True, mode=0o700)
            protect(output.parent, directory=True)
        check_private(output.parent, directory=True)
        self.output, self.fields, self.scope = output, fields, scope
        request = request or {}
        if not isinstance(request, dict):
            raise ValueError('Invalid request context')
        details = request_details(request)
        self.pdf = Path(pdf).resolve() if pdf else None
        self.data_dir = Path(data_dir).resolve() if data_dir else None
        self.recipe = request.get('recipe')
        self.attempts = 0
        if self.pdf:
            details.setdefault('filename', self.pdf.name)
            if not self.data_dir:
                raise ValueError('Verification requires the private data directory')
            if self.recipe is not None:
                validate_recipe(self.recipe, fields)
            elif fields != ['password']:
                raise ValueError('Attribute verification needs the exact observed local recipe')
            if self.pdf.stat().st_size > 20 * 1024 * 1024:
                raise ValueError('PDF exceeds 20 MiB')
            from pypdf import PdfReader
            logging.getLogger('pypdf').setLevel(logging.CRITICAL)
            raw = self.pdf.read_bytes()
            reader = PdfReader(io.BytesIO(raw), strict=False)
            if not reader.is_encrypted or reader.decrypt(''):
                raise ValueError('Statement is already open; no private inputs are needed')
            self.pdf_digest = hashlib.sha256(raw).digest()
        self.saved = False
        self.token = secrets.token_urlsafe(32)
        self.expires_at = time.monotonic() + lifetime
        field_definitions = []
        help_text = request.get('field_help', {})
        if not isinstance(help_text, dict) or set(help_text) - set(fields):
            raise ValueError('Describe only requested fields')
        for key in fields:
            field = dict(FIELDS[key])
            if key in help_text:
                if not isinstance(help_text[key], str) or len(help_text[key]) > 1000:
                    raise ValueError('Invalid field explanation')
                field['help'] = help_text[key]
            field_definitions.append(field)
        config = json.dumps({'fields': field_definitions, 'scope': scope, 'request': details,
                             'verification': bool(self.pdf), 'context': context, 'token': self.token},
                            ensure_ascii=True).replace('<', chr(92) + 'u003c')
        template = (Path(__file__).resolve().parents[1] / 'assets/setup.html').read_text(encoding='utf-8')
        if template.count(CONFIG_MARKER) != 1:
            raise ValueError('Setup template configuration marker is missing')
        self.page = template.replace(CONFIG_MARKER, f'<script id="setup-config" type="application/json">{config}</script>').encode()
        super().__init__(('127.0.0.1', port), SetupHandler)
        self.origin = f'http://127.0.0.1:{self.server_port}'
        self.timeout = 1

    def handle_error(self, _request, _client_address):
        # Never emit request diagnostics or tracebacks from a private-input server.
        pass

    def write_values(self, values):
        if self.saved or self.output.exists() or self.output.is_symlink():
            raise FileExistsError('Already saved')
        if not isinstance(values, dict) or set(values) != set(self.fields):
            raise ValueError('Unexpected fields')
        if any(not isinstance(value, str) or not value.strip() or len(value) > FIELDS[key]['maxLength']
               for key, value in values.items()):
            raise ValueError('Invalid values')
        candidate = None
        if self.pdf:
            if self.attempts >= 5:
                raise UnlockFailed('attempts_exhausted')
            self.attempts += 1
            from pypdf import PdfReader
            raw = self.pdf.read_bytes()
            if hashlib.sha256(raw).digest() != self.pdf_digest:
                raise ValueError('Source changed; restart setup')
            candidate = derive_password(self.recipe, values) if self.recipe else values['password']
            reader = PdfReader(io.BytesIO(raw), strict=False)
            if not reader.decrypt(candidate):
                raise UnlockFailed('unlock_failed')
            if not 1 <= len(reader.pages) <= 100:
                raise ValueError('Unsupported statement page count')
            if not PdfReader(io.BytesIO(raw), strict=False).decrypt(candidate):
                raise UnlockFailed('unlock_failed')
        check_private(self.output.parent, directory=True)
        descriptor = os.open(self.output, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, 'O_NOFOLLOW', 0), 0o600)
        try:
            with os.fdopen(descriptor, 'w', encoding='utf-8') as stream:
                protect(self.output)
                if self.pdf:
                    store = selected(self.data_dir)
                    store.save(self.scope, candidate)
                    # Prove that the saved value, rather than a transient candidate, reopens it.
                    if not PdfReader(io.BytesIO(raw), strict=False).decrypt(store.get(self.scope, True)):
                        raise UnlockFailed('unlock_failed')
                    json.dump({'schema_version': 1, 'scope': self.scope, 'verified': True, 'credential_saved': True}, stream)
                else:
                    json.dump({'schema_version': 1, 'scope': self.scope, 'values': values}, stream)
                stream.flush()
                os.fsync(stream.fileno())
            self.saved = True
        except BaseException:
            self.output.unlink(missing_ok=True)
            raise

    def status(self):
        return {'saved': self.saved, **({'verified': self.saved} if self.pdf else {})}


class SetupHandler(BaseHTTPRequestHandler):
    server_version = 'MoneyLens'

    def log_message(self, *_args):
        pass

    def setup(self):
        super().setup()
        self.connection.settimeout(5)

    def reply(self, code, body, content_type='application/json'):
        if not isinstance(body, bytes):
            body = json.dumps(body).encode()
        self.send_response(code)
        for key, value in {'Content-Type': content_type, 'Content-Length': str(len(body)),
                           'Cache-Control': 'no-store', 'Referrer-Policy': 'no-referrer',
                           'Content-Security-Policy': CSP, 'X-Frame-Options': 'DENY',
                           'X-Content-Type-Options': 'nosniff'}.items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(body)

    def valid_host(self):
        return self.headers.get('Host') == self.server.origin.removeprefix('http://')

    def do_GET(self):
        if not self.valid_host():
            return self.reply(403, {'error': 'Request rejected'})
        if time.monotonic() > self.server.expires_at:
            return self.reply(410, {'error': 'Session expired'})
        if self.path in ('/', '/setup.html'):
            return self.reply(200, self.server.page, 'text/html; charset=utf-8')
        if self.path == '/status':
            return self.reply(200, self.server.status())
        return self.reply(404, {'error': 'Not found'})

    def do_POST(self):
        if (not self.valid_host() or self.path != '/submit' or
                self.headers.get('Origin') != self.server.origin or
                not hmac.compare_digest(self.headers.get('X-MoneyLens-Setup', ''), self.server.token)):
            return self.reply(403, {'error': 'Request rejected'})
        if time.monotonic() > self.server.expires_at:
            return self.reply(410, {'error': 'Session expired'})
        if self.headers.get('Content-Type', '').split(';')[0].strip() != 'application/json':
            return self.reply(415, {'error': 'Expected JSON'})
        try:
            size = int(self.headers.get('Content-Length', '0'))
            if not 0 < size <= 16384:
                return self.reply(413, {'error': 'Invalid request size'})
            raw = self.rfile.read(size)
            payload = json.loads(raw)
            raw = b''
            if not isinstance(payload, dict) or set(payload) != {'values'}:
                raise ValueError('Unexpected payload')
            self.server.write_values(payload['values'])
            payload.clear()
        except FileExistsError:
            return self.reply(409, {'error': 'Already saved; existing file was not changed'})
        except UnlockFailed as exc:
            return self.reply(422, {'saved': False, 'verified': False, 'code': str(exc)})
        except (ValueError, UnicodeError):
            return self.reply(400, {'error': 'Check the requested fields'})
        except Exception:
            return self.reply(500, {'error': 'Could not save; no values returned'})
        return self.reply(200, self.server.status())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True, help='New file inside a private directory')
    parser.add_argument('--field', action='append', choices=FIELDS, required=True, help='Request only a still-missing input')
    parser.add_argument('--scope', required=True, help='Nonsecret opaque statement/account scope')
    parser.add_argument('--context', default='', help='Nonsecret explanation of the missing input; never a personal value')
    parser.add_argument('--port', type=int, default=0)
    parser.add_argument('--request-file', type=Path, help='Statement context, source email link, field help, and observed recipe JSON')
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--pdf', type=Path, help='Verify inputs against this actual protected statement before saving')
    mode.add_argument('--collect-only', action='store_true', help='Explicit unverified collection; never reports a verified credential')
    parser.add_argument('--data-dir', type=Path, help='Private MoneyLens directory for verified credential reuse')
    args = parser.parse_args()
    try:
        if args.request_file and args.request_file.stat().st_size > 65536:
            raise ValueError('Request context exceeds 64 KiB')
        request = json.loads(args.request_file.read_text(encoding='utf-8')) if args.request_file else {}
        if isinstance(request, dict) and isinstance(request.get('recipe'), dict) and request['recipe'].get('known_values'):
            check_private(args.request_file)
        with SetupServer(args.output, args.field, args.scope, args.context, args.port,
                         request=request, pdf=args.pdf, data_dir=args.data_dir) as server:
            print(json.dumps({'url': server.origin + '/setup.html', 'status_url': server.origin + '/status'}), flush=True)
            while time.monotonic() < server.expires_at:
                server.handle_request()
    except KeyboardInterrupt:
        pass
    except Exception:
        print(json.dumps({'error': 'Cannot start private setup; check the new output path and private directory permissions'}), file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
