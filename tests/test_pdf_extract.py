import argparse
import importlib.util
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from unittest.mock import Mock
from types import SimpleNamespace
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'skills/moneylens-automation/scripts'))
from pdf_extract import Failure, Keychain, derive_candidates, run, unlock


class FakeKeychain:
    def __init__(self,values=None):self.values=values or {};self.calls=[]
    def get(self,key,no_prompt=False):self.calls.append((key,no_prompt));return self.values.get(key)
    def save(self,key,password):self.values[key]=password


class FakeReader:
    def __init__(self):self.stream=io.BytesIO()
    def decrypt(self,password):return password=='synthetic-correct'


class CredentialFlowTests(unittest.TestCase):
    def test_unattended_queries_disable_both_login_keychain_and_authentication_ui(self):
        names=('kSecClass','kSecClassGenericPassword','kSecAttrService','kSecAttrAccount',
               'kSecUseAuthenticationContext','kSecUseAuthenticationUI','kSecUseAuthenticationUIFail')
        security=SimpleNamespace(**{name:name for name in names},errSecSuccess=0,
                                 SecKeychainSetUserInteractionAllowed=Mock(return_value=0))
        context=Mock()
        auth=Mock();auth.LAContext.alloc.return_value.init.return_value=context
        keychain=Keychain.__new__(Keychain);keychain.s=security;keychain.la=auth
        query=keychain.query('synthetic-scope',no_prompt=True)
        security.SecKeychainSetUserInteractionAllowed.assert_called_once_with(False)
        context.setInteractionNotAllowed_.assert_called_once_with(True)
        self.assertEqual(query['kSecUseAuthenticationUI'],'kSecUseAuthenticationUIFail')

    def test_daily_missing_or_wrong_password_never_prompts_or_saves(self):
        for value in (None,'synthetic-wrong'):
            keychain=FakeKeychain({'scope':value})
            with self.assertRaisesRegex(Failure,'Setup required'):
                unlock(FakeReader(),[],'scope',no_prompt=True,keychain=keychain,prompt=lambda _:self.fail('Daily job prompted'))
            self.assertEqual(keychain.calls,[('scope',True)])
            self.assertEqual(keychain.values,{'scope':value})

    def test_setup_saves_only_passwords_that_unlock_the_pdf(self):
        keychain=FakeKeychain()
        with self.assertRaisesRegex(Failure,'no replacement'):
            unlock(FakeReader(),['synthetic-wrong'],'scope',keychain=keychain,prompt=lambda _:'synthetic-wrong')
        self.assertEqual(keychain.values,{})
        unlock(FakeReader(),['synthetic-correct'],'scope',keychain=keychain,prompt=lambda _:self.fail('Derived password should unlock'))
        self.assertEqual(keychain.values,{'scope':'synthetic-correct'})

    def test_previous_scope_is_copied_only_after_successful_unlock(self):
        keychain=FakeKeychain({'previous':'synthetic-correct'})
        unlock(FakeReader(),[],'new',previous='previous',keychain=keychain)
        self.assertEqual(keychain.values['new'],'synthetic-correct')

    def test_bounded_document_supported_recipes_only(self):
        payload={'attributes':{'full_name':'Example Person','card_last4':'1234','birth_date':'2000-02-03'},
                 'recipes':['name4_upper_card_last4','name4_lower_birth_ddmm']}
        self.assertEqual(derive_candidates(io.StringIO(json.dumps(payload))),['EXAM1234','exam0302'])
        payload['recipes']=['guess-a-birthday']
        with self.assertRaises(Failure):derive_candidates(io.StringIO(json.dumps(payload)))
        with self.assertRaises(Failure):derive_candidates(io.StringIO('x'*16385))


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
        result=dict(input=path,output=output,account='synthetic-scope',previous_account=None,probe=False,no_prompt=False,
                    keychain_status=False,derive_from_stdin=False,verify_derived_only=False)
        result.update(changes);return argparse.Namespace(**result)

    def test_unprotected_pdf_never_reads_keychain_and_output_is_private(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'source.pdf';output=Path(folder)/'extraction.json';self.create(path)
            with patch('pdf_extract.Keychain',side_effect=AssertionError('Keychain must not be touched')):
                self.assertEqual(run(self.args(path,output))['page_count'],1)
            self.assertIn('Synthetic statement',json.loads(output.read_text())['pages'][0]['text'])
            self.assertEqual(output.stat().st_mode&0o777,0o600)
            with self.assertRaises(Failure):run(self.args(path,output))

    def test_encrypted_derivation_works_without_keychain_or_secret_output(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'source.pdf';self.create(path,'EXAM1234')
            payload={'attributes':{'full_name':'Example Person','card_last4':'1234'},'recipes':['name4_upper_card_last4']}
            with patch('pdf_extract.Keychain',side_effect=AssertionError('Synthetic verification accessed Keychain')):
                result=run(self.args(path,verify_derived_only=True),io.StringIO(json.dumps(payload)))
            self.assertEqual(result,{'derived_unlock':True,'attempts':1})
            self.assertNotIn('EXAM1234',json.dumps(result))

    def test_daily_extraction_uses_only_scoped_saved_password(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'source.pdf';output=Path(folder)/'extraction.json';self.create(path,'synthetic-correct')
            keychain=FakeKeychain({'synthetic-scope':'synthetic-correct'})
            with patch('pdf_extract.Keychain',return_value=keychain),patch('pdf_extract.prompt_password',side_effect=AssertionError('Daily prompt')):
                run(self.args(path,output,no_prompt=True))
            self.assertEqual(keychain.calls,[('synthetic-scope',True)])
            self.assertIn('Synthetic statement',json.loads(output.read_text())['pages'][0]['text'])


if __name__=='__main__':unittest.main()
