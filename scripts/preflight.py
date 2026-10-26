#!/usr/bin/env python3
"""Check local accounting, private storage, and PDF processing capabilities. Development-only; never included in the plugin."""
import importlib.util
from pathlib import Path
import sys
import tempfile

SKILLS = Path(__file__).resolve().parents[1] / 'plugins/moneylens/skills'
sys.path.insert(0, str(SKILLS / 'automation'))
from moneylens.private_files import protect


def check(data_dir):
    package = SKILLS / 'automation/moneylens'
    files = [SKILLS / 'setup/SKILL.md', SKILLS / 'automation/SKILL.md',
             SKILLS / 'automation/assets/report-template.html', SKILLS / 'automation/assets/report-fonts.html', SKILLS / 'automation/scripts/moneylens.py', SKILLS / 'automation/scripts/pdf_extract.py',
             package / '__init__.py', package / 'app.py', package / 'transactions.py',
             *[package / name for name in ('accounts.py', 'alerts.py', 'ledger.py', 'dashboard.py', 'personalize.py', 'statement_coverage.py', 'pdf_extract.py', 'processing.py', 'store.py', 'credentials.py', 'private_files.py', 'windows_access.py', 'merchants.py', 'transfers.py')]]
    try: skills = all(path.is_file() and bool(path.read_bytes()) for path in files)
    except OSError: skills = False
    writable = False
    try:
        data_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        if data_dir.resolve() != Path.cwd().resolve():
            protect(data_dir, directory=True)
        with tempfile.TemporaryFile(dir=data_dir) as stream: stream.write(b'MoneyLens preflight'); stream.flush()
        writable = True
    except OSError: pass
    pdf = False
    if importlib.util.find_spec('pypdf') and importlib.util.find_spec('cryptography'):
        # Exercise encryption, decryption and text extraction without user data.
        import io
        from pypdf import PdfReader, PdfWriter
        from pypdf.generic import DictionaryObject, NameObject, DecodedStreamObject
        writer = PdfWriter(); page = writer.add_blank_page(width=200, height=200)
        font = DictionaryObject({NameObject('/Type'): NameObject('/Font'), NameObject('/Subtype'): NameObject('/Type1'), NameObject('/BaseFont'): NameObject('/Helvetica')})
        page[NameObject('/Resources')] = DictionaryObject({NameObject('/Font'): DictionaryObject({NameObject('/F1'): writer._add_object(font)})})
        content = DecodedStreamObject(); content.set_data(b'BT /F1 12 Tf 10 100 Td (MoneyLens preflight) Tj ET')
        page[NameObject('/Contents')] = writer._add_object(content)
        writer.encrypt('synthetic-preflight', algorithm='AES-256')
        stream = io.BytesIO(); writer.write(stream); stream.seek(0)
        reader = PdfReader(stream)
        pdf = bool(reader.decrypt('synthetic-preflight') and 'MoneyLens preflight' in reader.pages[0].extract_text())
    credential_storage = False
    try:
        from moneylens.credentials import PrivateFiles
        PrivateFiles(data_dir / 'credentials')
        credential_storage = True
    except (OSError, ValueError): pass
    ready = skills and writable and credential_storage and pdf
    fallbacks = []
    if not skills: fallbacks.append('Restore/install both MoneyLens skills and their shipped helpers before onboarding')
    if not pdf: fallbacks.append('Install scripts/requirements-pdf.txt in the current Python environment and rerun preflight' )
    if not writable: fallbacks.append('Choose writable private storage and rerun preflight')
    if not credential_storage: fallbacks.append('Repair owner-only access to the private credentials directory and rerun preflight')
    return {'ready': ready, 'skill_files': skills, 'writable_storage': writable, 'pdf_extraction': pdf,
            'credential_storage': credential_storage, 'credential_method': 'private-file', 'fallbacks': fallbacks}
