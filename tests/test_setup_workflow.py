"""Synthetic onboarding/resume journeys; no live email, credentials, or scheduler writes."""
import argparse
import copy
from coverage_fixtures import observed_statement
import io
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'skills/automation'))
from moneylens.store import reviews
from moneylens.private_files import check_private
from moneylens.accounts import mailbox_id, validate_source
from moneylens.merchants import review, remember, merchant_key
from moneylens.credentials import PrivateFiles, selected
from moneylens.ledger import connect, records, stage, save, find, semantic_key
from moneylens.processing import process_batch
from moneylens.personalize import decorate, annotate
from moneylens.preflight import check
from moneylens.store import config_validated, get, put
from test_ledger import fixture

SCRIPTS = Path(__file__).resolve().parents[1] / 'skills/automation/scripts'
STAMP = '2026-10-20T09:00:00+05:30'


class SetupWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.root = Path(self.temp.name)
        self.db = connect(self.root)
        self.config = config_validated({'mailboxes': [
            {'id': 'mail-a', 'address': 'a@example.invalid', 'verified_at': STAMP},
            {'id': 'mail-b', 'address': 'b@example.invalid', 'verified_at': STAMP}], 'timezone': 'Asia/Kolkata', 'report_path': str(self.root / 'report.html'), 'cards': [{'account_label':'Synthetic account','account_key': 'test-card-a', 'issuer': 'Synthetic Bank', 'masked_identifier': '1234',
                       'credential_scope': 'scope-a', 'password_status': 'not_required', 'mailbox_ids': ['mail-a', 'mail-b']}]})
        with self.db: put(self.db, 'config', self.config)

    def tearDown(self):
        self.db.close(); self.temp.cleanup()

    def payload(self, mailbox='mail-a', message='same-local-message-id', account='test-card-a'):
        p = fixture(message); p['source']['mailbox'] = mailbox; p['account_key'] = account
        return observed_statement(p)

    def stage(self, p):
        path = self.root / 'input.json'; path.write_text(json.dumps(observed_statement(p)))
        with self.db: return stage(self.db, path)

    def test_source_identity_uses_explicit_current_mailbox_id(self):
        with self.assertRaises(ValueError):mailbox_id(self.config)
        self.assertEqual(mailbox_id(self.config,'mail-b'),'mail-b')




    def test_cross_mailbox_duplicate_retains_both_sources_once(self):
        first = self.stage(self.payload())
        duplicate = self.stage(self.payload('mail-b'))
        self.assertEqual(duplicate['result'], 'staged')
        self.assertNotEqual(duplicate['id'], first['id'])
        self.assertEqual(len(records(self.db)), 2)
        self.assertEqual(self.db.execute('SELECT count(*) FROM source_links').fetchone()[0], 2)
        self.db.commit(); process_batch(self.root, [])
        html = (self.root/'report.html').read_text()
        data = json.loads(html.split('<script id="data" type="application/json">')[1].split('</script>')[0])
        self.assertEqual({s['mailbox'] for st in data['statements'] for s in st['sources']}, {'mail-a', 'mail-b'})

    def test_distinct_cards_with_same_ending_never_select_first_or_dedupe(self):
        cfg = copy.deepcopy(self.config); cfg.pop('ready')
        first = cfg['cards'][0]; first.update(identity='visa-personal', identity_evidence='User confirmed statement A')
        second = {**first, 'account_key': 'card-b', 'credential_scope': 'scope-b', 'identity': 'rupay-work', 'identity_evidence': 'User confirmed statement B'}
        cfg['cards'].append(second)
        config = config_validated(cfg)
        validate_source(config, self.payload(account='card-b'))
        with self.assertRaisesRegex(ValueError, 'confirmation'): validate_source(config, self.payload(account='unconfirmed'))
        with self.db: put(self.db, 'config', config)
        self.assertNotEqual(self.stage(self.payload())['id'], self.stage(self.payload('mail-b', account='card-b'))['id'])
        self.assertEqual(len(records(self.db)), 2)
        del cfg['cards'][1]['identity']
        self.assertEqual(config_validated(cfg)['cards'][1]['account_key'],'card-b')



    def test_agent_canonical_merchant_cache_and_row_corrections_preserve_evidence(self):
        p=self.payload();p['transactions'][0].update(merchant='RAW GROCERY PROVIDER',category='Other',metadata={'merchant':'Grocery provider'})
        p['transactions'][1].update(merchant='Unclear merchant',category='Other',kind='purchase',amount_minor=1000)
        p['checks']={};sid=self.stage(p)['id'];original=records(self.db)
        with self.db:remember(self.db,'Grocery provider','Groceries')
        effective=decorate(self.db,original)
        self.assertEqual(effective[0]['payload']['transactions'][0]['category'],'Groceries')
        self.assertEqual(review(self.db)['currencies'][0]['count'],1)
        self.assertEqual(review(self.db)['currencies'][0]['spending_minor'],1000)
        self.assertEqual(records(self.db),original)
        with self.db:annotate(self.db,sid,0,category='Work expenses')
        self.assertEqual(decorate(self.db,records(self.db))[0]['payload']['transactions'][0]['category'],'Work expenses')

    def test_private_file_default_enforces_permissions_and_no_secret_output(self):
        store = selected(self.root)
        self.assertIsNone(store.get('scope'))
        store.save('scope', 'synthetic-pdf-password')
        self.assertTrue(store.present('scope')); self.assertEqual(store.get('scope', True), 'synthetic-pdf-password')
        path = store.path('scope'); check_private(path)
        check_private(path.parent, directory=True)
        from test_portability import broaden_access
        broaden_access(path)
        with self.assertRaisesRegex(ValueError, 'owner-only'): store.get('scope', True)
        path.unlink(); target = self.root/'target'; target.write_text('synthetic')
        os.link(target, path)
        with self.assertRaises(ValueError): store.get('scope', True)

    def test_preflight_checks_only_local_processing_capabilities(self):
        result = check(self.root)
        self.assertTrue(result['skill_files']); self.assertTrue(result['writable_storage'])
        self.assertNotIn('gmail_accounts', result); self.assertNotIn('scheduler_available', result)
        self.assertEqual(result['ready'], result['pdf_extraction'] and result['credential_storage'])

    def test_batch_reports_once_and_rejects_unconfirmed_mailbox(self):
        result = process_batch(self.root, [{'type':'statement','payload':self.payload()}, {'type':'statement','payload':self.payload('mail-b')}])
        self.assertEqual(len(result['outcomes']), 2)
        self.assertEqual(result['report']['statements'], 2)
        self.assertEqual(records(self.db)[0]['status'], 'imported')
        result = process_batch(self.root, [{'type':'statement','payload':self.payload('unknown-mailbox')}])
        self.assertEqual(result['outcomes'][0]['result'], 'needs_review')
        self.assertEqual(len(reviews(self.db)), 1)


    def test_normalization_is_idempotent_and_category_review_stays_ambiguous(self):
        for name in ('SWIGGY*INSTAMART', 'SwiggyInstamart', 'Instamart Bangalore', 'swiggy insta mart'):
            canonical = merchant_key(name)
            self.assertEqual(merchant_key(canonical), canonical)
            self.assertEqual(canonical,' '.join(name.casefold().split()))
        p = self.payload(); p['transactions'][0].update(merchant='Unclear recipient', category='Other')
        p['issues'] = ['Identity still requires evidence']
        self.stage(p)
        summary = review(self.db)['currencies'][0]
        self.assertEqual(summary['count'], 1)
        self.assertTrue(summary['merchants'][0]['rows'][0]['needs_source_review'])

    @unittest.skipUnless(importlib.util.find_spec('pypdf'), 'Install PDF test dependencies')
    def test_encrypted_pdf_uses_selected_private_backend_without_prompt_or_secret_output(self):
        from test_pdf_extract import PDFExtractionTests
        from moneylens.pdf_extract import run
        with self.db:
            cfg = get(self.db, 'config'); cfg.update(credential_method='private-file')
            put(self.db, 'config', cfg)
        path = self.root/'encrypted.pdf'; output = self.root/'extracted.json'
        PDFExtractionTests().create(path, 'EXAM1234')
        args = argparse.Namespace(data_dir=self.root, input=path, output=output, account='scope-a',
                                  probe=False, no_prompt=False, credential_status=False, passwords_from_stdin=True, verify_passwords_only=False)
        data = {'passwords':['EXAM1234']}
        with patch('builtins.input', side_effect=AssertionError('Unexpected prompt')):
            result = run(args, io.StringIO(json.dumps(data)))
            self.assertNotIn('EXAM1234', json.dumps(result))
            self.assertEqual(selected(self.root).get('scope-a'), 'EXAM1234')
            self.assertIn('Synthetic statement', json.loads(output.read_text())['pages'][0]['text'])
            args.no_prompt = True; args.passwords_from_stdin = False; args.output = self.root/'daily.json'
            run(args)
        # Identity attributes and password do not enter SQLite or metadata output.
        self.assertNotIn('Example Person', json.dumps(get(self.db, 'config')))
        self.assertNotIn('EXAM1234', (self.root/'ledger.sqlite3').read_bytes().decode('latin1'))



if __name__ == '__main__': unittest.main()
