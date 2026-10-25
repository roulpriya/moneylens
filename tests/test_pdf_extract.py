import argparse
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'skills/automation'))
from moneylens.private_files import check_private
from moneylens.pdf_extract import Failure, password_candidates, run, unlock


class FakeStore:
    def __init__(self,values=None):self.values=values or {};self.calls=[]
    def get(self,key,no_prompt=False):self.calls.append((key,no_prompt));return self.values.get(key)
    def save(self,key,password):self.values[key]=password


class FakeReader:
    def __init__(self):self.stream=io.BytesIO()
    def decrypt(self,password):return password=='synthetic-correct'


class CredentialFlowTests(unittest.TestCase):
    def test_unattended_and_inspection_modes_never_read_candidate_input(self):
        class NoRead:
            def read(self,*args):raise AssertionError('Unexpected password input')
        for options in ({'no_prompt':True,'verify_passwords_only':True},
                        {'probe':True,'passwords_from_stdin':True}):
            args=PDFExtractionTests().args(Path('unused.pdf'),**options)
            with self.subTest(options=options),self.assertRaises(Failure):run(args,NoRead())

    def test_daily_missing_or_wrong_password_never_prompts_or_saves(self):
        for value in (None,'synthetic-wrong'):
            store=FakeStore({'scope':value})
            with self.assertRaisesRegex(Failure,'Setup required'):
                unlock(FakeReader(),[],'scope',no_prompt=True,store=store)
            self.assertEqual(store.calls,[('scope',True)])
            self.assertEqual(store.values,{'scope':value})

    def test_setup_saves_only_passwords_that_unlock_the_pdf(self):
        store=FakeStore()
        with self.assertRaisesRegex(Failure,'did not unlock'):
            unlock(FakeReader(),['synthetic-wrong'],'scope',store=store)
        self.assertEqual(store.values,{})
        unlock(FakeReader(),['synthetic-correct'],'scope',store=store)
        self.assertEqual(store.values,{'scope':'synthetic-correct'})


    def test_password_input_preserves_arbitrary_agent_supplied_values(self):
        values=['Å short/opaque password!', 'not-four-digits', 'one']
        self.assertEqual(password_candidates(io.StringIO(json.dumps({'passwords':values}))),values)

    def test_password_input_is_bounded_and_has_no_recipe_catalog(self):
        for payload in ({'passwords':[]}, {'passwords':['a']*4}, {'passwords':[123]},
                        {'passwords':['']}, {'attributes':{},'recipes':[]}):
            with self.subTest(payload=payload), self.assertRaises(Failure):
                password_candidates(io.StringIO(json.dumps(payload)))
        with self.assertRaises(Failure): password_candidates(io.StringIO('x'*16385))


@unittest.skipUnless(importlib.util.find_spec('pypdf'),'Install PDF helper requirements')
class PDFExtractionTests(unittest.TestCase):
    def create(self,path,password=None):
        from pypdf import PdfWriter
        from pypdf.generic import DictionaryObject,NameObject,DecodedStreamObject
        writer=PdfWriter();page=writer.add_blank_page(width=200,height=200)
        font=DictionaryObject({NameObject('/Type'):NameObject('/Font'),NameObject('/Subtype'):NameObject('/Type1'),NameObject('/BaseFont'):NameObject('/Helvetica')})
        page[NameObject('/Resources')]=DictionaryObject({NameObject('/Font'):DictionaryObject({NameObject('/F1'):writer._add_object(font)})})
        content=DecodedStreamObject();content.set_data(b'BT /F1 12 Tf 10 100 Td (Synthetic statement) Tj ET')
        page[NameObject('/Contents')]=writer._add_object(content)
        if password:writer.encrypt(password,algorithm='AES-256')
        writer.write(path)

    def args(self,path,output=None,**changes):
        result=dict(data_dir=path.parent,input=path,output=output,account='synthetic-scope',probe=False,no_prompt=False,
                    credential_status=False,passwords_from_stdin=False,verify_passwords_only=False)
        result.update(changes);return argparse.Namespace(**result)

    def test_unprotected_pdf_never_reads_store_and_output_is_private(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'source.pdf';output=Path(folder)/'extraction.json';self.create(path)
            with patch('moneylens.credentials.selected',side_effect=AssertionError('Credential storage must not be touched')):
                result=run(self.args(path,output))
                self.assertEqual(result['page_count'],1)
                self.assertEqual(result['sha256'],hashlib.sha256(path.read_bytes()).hexdigest())
            self.assertIn('Synthetic statement',json.loads(output.read_text())['pages'][0]['text'])
            check_private(output)
            with self.assertRaises(Failure):run(self.args(path,output))

    def test_failed_output_write_removes_only_its_new_partial_file(self):
        with tempfile.TemporaryDirectory() as folder:
            source=Path(folder)/'source.pdf';output=Path(folder)/'extraction.json';self.create(source)
            with patch('moneylens.pdf_extract.json.dump',side_effect=OSError('Synthetic write failure')):
                with self.assertRaises(OSError):run(self.args(source,output))
            self.assertFalse(output.exists());self.assertTrue(source.exists())

    def test_encrypted_derivation_works_without_store_or_secret_output(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'source.pdf';self.create(path,'EXAM1234')
            payload={'passwords':['EXAM1234']}
            with patch('moneylens.credentials.selected',side_effect=AssertionError('Synthetic verification accessed storage')):
                result=run(self.args(path,verify_passwords_only=True),io.StringIO(json.dumps(payload)))
            self.assertEqual(result,{'password_unlock':True,'attempts':1})
            self.assertNotIn('EXAM1234',json.dumps(result))

    def test_supplied_candidate_is_reused_from_storage_on_reopened_pdf(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'source.pdf';output=Path(folder)/'extraction.json';self.create(path,'synthetic-correct')
            backend=FakeStore()
            with patch('moneylens.credentials.selected',return_value=backend):
                result=run(self.args(path,output,passwords_from_stdin=True),io.StringIO('{"passwords":["synthetic-correct"]}'))
            self.assertEqual(backend.calls,[('synthetic-scope',False),('synthetic-scope',True)])
            self.assertEqual(result['result'],'extracted');self.assertNotIn('synthetic-correct',json.dumps(result))
            class BrokenStore(FakeStore):
                def save(self,key,password): pass
            output.unlink()
            with patch('moneylens.credentials.selected',return_value=BrokenStore()),self.assertRaisesRegex(Failure,'Setup required'):
                run(self.args(path,output,passwords_from_stdin=True),io.StringIO('{"passwords":["synthetic-correct"]}'))
            self.assertFalse(output.exists())

    def test_parser_limit_uses_private_unlocked_fallback_without_password_arguments(self):
        from pypdf import PdfReader
        from pypdf.errors import LimitReachedError
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'source.pdf';output=Path(folder)/'extraction.json';self.create(path,'synthetic-correct')
            backend=FakeStore({'synthetic-scope':'synthetic-correct'})
            temporary=[]
            def poppler(command, **kwargs):
                self.assertEqual(command[:2],['/supported/pdftotext','-layout'])
                self.assertNotIn('synthetic-correct',str(command))
                unlocked=Path(command[2]);temporary.append(unlocked.parent)
                self.assertFalse(PdfReader(unlocked).is_encrypted)
                check_private(unlocked.parent, directory=True)
                check_private(unlocked)
                Path(command[3]).write_text('Synthetic statement\n\f')
            with patch('moneylens.credentials.selected',return_value=backend), patch('pypdf._page.PageObject.extract_text',side_effect=LimitReachedError('Synthetic decode limit')), patch('moneylens.pdf_extract.shutil.which',return_value='/supported/pdftotext'), patch('moneylens.pdf_extract.subprocess.run',side_effect=poppler):
                result=run(self.args(path,output,no_prompt=True))
            self.assertEqual(result['extraction_method'],'pdftotext')
            self.assertIn('Synthetic statement',json.loads(output.read_text())['pages'][0]['text'])
            self.assertTrue(all(not path.exists() for path in temporary))

    def test_daily_extraction_uses_only_scoped_saved_password(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'source.pdf';output=Path(folder)/'extraction.json';self.create(path,'synthetic-correct')
            store=FakeStore({'synthetic-scope':'synthetic-correct'})
            with patch('moneylens.credentials.selected',return_value=store):
                run(self.args(path,output,no_prompt=True))
            self.assertEqual(store.calls,[('synthetic-scope',True)])
            self.assertIn('Synthetic statement',json.loads(output.read_text())['pages'][0]['text'])


if __name__=='__main__':unittest.main()
