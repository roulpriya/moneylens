"""Portable derived-password flow, with no live identity or system credentials."""
import argparse
import builtins
import contextlib
import copy
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'skills/automation'))
from moneylens.private_files import check_private
from moneylens.credentials import PrivateFiles, selected
from moneylens.ledger import connect
from moneylens.pdf_extract import Failure, password_candidates, run
from moneylens.store import config_validated, put

SCRIPTS = Path(__file__).resolve().parents[1] / 'skills/automation/scripts'
STAMP = '2026-10-24T00:30:00+05:30'


class LocalCredentialTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.root = Path(self.temp.name)
    def tearDown(self): self.temp.cleanup()

    def raw_config(self):
        return {'mailboxes': [{'id': 'synthetic-mail', 'address': 'synthetic-mail', 'verified_at': STAMP}], 'timezone': 'Asia/Kolkata', 'report_path': str(self.root/'report.html'), 'cards': [{'account_label':'Synthetic account','account_key':'synthetic-card','issuer':'Synthetic bank','masked_identifier':'1234',
                          'credential_scope':'synthetic-scope','password_status':'not_required'}]}

    def test_private_store_is_default_without_an_extra_storage_checkpoint(self):
        config=config_validated(self.raw_config())
        self.assertEqual(config['credential_method'],'private-file')
        self.assertNotIn('credential_approved_at',config)
        self.assertIsInstance(selected(self.root),PrivateFiles)
        check_private(self.root/'credentials', directory=True)

    def test_account_settings_require_the_current_credential_scope_field(self):
        raw=self.raw_config();raw['cards'][0]['keychain_scope']=raw['cards'][0].pop('credential_scope')
        with self.assertRaisesRegex(ValueError,'Unsupported account fields'):config_validated(raw)

    def test_account_settings_allow_only_the_private_file_backend(self):
        raw=self.raw_config();raw['credential_method']='keychain'
        with self.assertRaisesRegex(ValueError,'private-file'):config_validated(raw)

    def test_arbitrary_password_input_is_never_derived_from_identity_fields(self):
        values=['one arbitrary value','another value']
        self.assertEqual(password_candidates(io.StringIO(json.dumps({'passwords':values}))),values)
        with self.assertRaises(Failure): password_candidates(io.StringIO(json.dumps({'full_account_number':'invalid'})))

    def test_status_cli_reports_existence_without_returning_values(self):
        store=selected(self.root);store.save('synthetic-scope','synthetic-status-value')
        for flag in ('--credential-status',):
            command=[sys.executable,str(SCRIPTS/'pdf_extract.py'),'--data-dir',str(self.root),flag,'--account','synthetic-scope']
            result=subprocess.run(command,capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertEqual(json.loads(result.stdout),{'credential_present':True})
            self.assertNotIn('synthetic-status-value',result.stdout+result.stderr)

    @unittest.skipUnless(importlib.util.find_spec('pypdf'),'Install PDF test dependencies')
    def test_real_password_unlock_and_unattended_reuse_without_system_apis_or_identity_persistence(self):
        import test_pdf_extract as support
        path=self.root/'statement.pdf';support.PDFExtractionTests().create(path,'EXAM5678')
        args=argparse.Namespace(data_dir=self.root,input=path,output=self.root/'first.json',account='synthetic-scope',
                                probe=False,no_prompt=False,credential_status=False,
                                passwords_from_stdin=True,verify_passwords_only=False)
        payload={'passwords':['EXAM5678']}
        original_import=builtins.__import__
        def portable_import(name,*positional,**keywords):
            if name.split('.')[0] in {'Security','LocalAuthentication','AppKit','getpass'}:
                raise AssertionError('System credential or password prompt dependency was invoked')
            return original_import(name,*positional,**keywords)
        captured=io.StringIO()
        with patch('builtins.__import__',side_effect=portable_import),patch('builtins.input',side_effect=AssertionError('Password prompt')),contextlib.redirect_stdout(captured),contextlib.redirect_stderr(captured):
            first=run(args,io.StringIO(json.dumps(payload)))
            args.no_prompt=True;args.passwords_from_stdin=False;args.output=self.root/'second.json'
            second=run(args)
        self.assertEqual(first['result'],second['result'])
        self.assertIn('Synthetic statement',args.output.read_text())
        self.assertEqual(selected(self.root).get('synthetic-scope',True),'EXAM5678')
        stored=selected(self.root).path('synthetic-scope')
        check_private(stored)
        self.assertNotIn('Example Person',stored.read_text())
        self.assertNotIn('EXAM5678',json.dumps(first)+json.dumps(second)+captured.getvalue())
        self.assertFalse((self.root/'ledger.sqlite3').exists())
