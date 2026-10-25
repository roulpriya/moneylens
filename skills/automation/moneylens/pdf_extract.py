#!/usr/bin/env python3
"""Unlock and extract PDFs locally; secret values never enter command output."""
import argparse
import hashlib
import json
import logging
import os
import shutil
import subprocess
import tempfile
from .private_files import protect
from pathlib import Path
import sys

class Failure(ValueError):
    pass


def password_candidates(stream):
    raw = stream.read(16385)
    if len(raw) > 16384: raise Failure('Password input exceeds 16 KiB')
    data = json.loads(raw)
    if not isinstance(data,dict) or set(data) != {'passwords'}:
        raise Failure('Supply an object containing passwords from the agent')
    values = data['passwords']
    if not isinstance(values,list) or not 1 <= len(values) <= 3 or not all(isinstance(v,str) and 0 < len(v) <= 4096 for v in values):
        raise Failure('Supply one to three nonempty document-supported passwords')
    return list(dict.fromkeys(values))


def unlock(reader, candidates, account, no_prompt=False, store=None):
    if store is None: raise Failure("A private local credential store is required")
    saved = store.get(account, no_prompt)
    if saved is not None and reader.decrypt(saved): return
    for candidate in candidates:
        if reader.decrypt(candidate):
            store.save(account, candidate)
            return
    raise Failure('Setup required: saved or supplied candidates did not unlock this PDF; the unlock instructions and required inputs need review')



def page_texts(reader, output_parent):
    from pypdf.errors import LimitReachedError
    try:
        return [page.extract_text() or '' for page in reader.pages], 'pypdf'
    except LimitReachedError:
        # Some valid PDFs hit pypdf's decompression guard. Do not raise that
        # guard; try an installed parser on a private, already-unlocked copy.
        executable = shutil.which('pdftotext')
        if executable is None: raise Failure('PDF needs the supported pdftotext fallback; run setup to provision it')
        from pypdf import PdfWriter
        with tempfile.TemporaryDirectory(prefix='moneylens-pdf-', dir=output_parent) as folder:
            root = Path(folder); protect(root, directory=True)
            pdf, txt = root / 'unlocked.pdf', root / 'text.txt'
            writer = PdfWriter(); writer.clone_document_from_reader(reader); writer.write(pdf); protect(pdf)
            subprocess.run([executable, '-layout', str(pdf), str(txt)], capture_output=True, check=True, timeout=30)
            if txt.stat().st_size > 20 * 1024 * 1024: raise Failure('Extracted PDF text exceeds 20 MiB')
            chunks = txt.read_text(encoding='utf-8').split('\f')
            if chunks and not chunks[-1].strip(): chunks.pop()
            if len(chunks) != len(reader.pages): raise Failure('Alternate PDF extraction returned an incomplete page set')
            return chunks, 'pdftotext'

def run(args, stream=None):
    os.umask(0o077)
    if args.no_prompt and (args.passwords_from_stdin or args.verify_passwords_only): raise Failure('Password input is setup-only')
    if (args.probe or args.credential_status) and args.passwords_from_stdin: raise Failure('Inspection does not accept password input')
    from .ledger import default_dir
    data_dir = args.data_dir or default_dir()
    def store():
        from .credentials import selected
        return selected(data_dir.resolve())
    if args.credential_status:
        if not args.account: raise Failure('--account is required')
        return {'credential_present': store().present(args.account)}
    if args.input is None: raise Failure('--input is required')
    path = args.input.resolve()
    if path.stat().st_size > 20 * 1024 * 1024: raise Failure('Input exceeds 20 MiB')
    try:
        from pypdf import PdfReader
    except ImportError as exc: raise Failure('Install the PDF helper requirements in the current Python environment') from exc
    logging.getLogger('pypdf').setLevel(logging.CRITICAL)
    reader = PdfReader(path, strict=False)
    locked = bool(reader.is_encrypted and not reader.decrypt(''))
    if args.probe:
        return {'encrypted': reader.is_encrypted, 'locked': locked, 'page_count': 0 if locked else len(reader.pages)}
    candidates = password_candidates(stream or sys.stdin) if args.passwords_from_stdin or args.verify_passwords_only else []
    if args.verify_passwords_only:
        if not locked: raise Failure('Password verification needs a locked PDF')
        for index, candidate in enumerate(candidates, 1):
            if reader.decrypt(candidate): return {'password_unlock': True, 'attempts': index}
        raise Failure('Supplied passwords did not unlock the PDF; verify the source instructions')
    if not args.account or args.output is None: raise Failure('--account and --output are required')
    output = args.output.resolve()
    if output == path or output.exists(): raise Failure('Output must be a new file separate from the PDF')
    if locked:
        backend = store()
        unlock(reader, candidates, args.account, args.no_prompt, store=backend)
    candidates.clear()
    if not 1 <= len(reader.pages) <= 100: raise Failure('PDF must contain 1–100 pages')
    texts, method = page_texts(reader, output.parent)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    payload = {'sha256': digest, 'pages': [{'page': i + 1, 'text': value} for i, value in enumerate(texts)],
               'page_count': len(reader.pages), 'encrypted': reader.is_encrypted}
    created = False
    try:
        with output.open('x', encoding='utf-8') as f:
            created = True
            protect(output)
            json.dump(payload, f)
    except BaseException:
        if created: output.unlink(missing_ok=True)
        raise
    return {'result': 'extracted', 'page_count': len(reader.pages), 'extraction_method': method, 'sha256': digest}


def main():
    p = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    from .ledger import default_dir
    p.add_argument('--data-dir', type=Path, default=default_dir())
    p.add_argument('--input', type=Path)
    p.add_argument('--output', type=Path)
    p.add_argument('--account')
    modes = p.add_mutually_exclusive_group()
    for flag in ('probe','credential-status','verify-passwords-only'):
        modes.add_argument('--'+flag, action='store_true')
    for flag in ('no-prompt', 'passwords-from-stdin'):
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
