"""Current accounting identity, category, and personal-rule invariants."""
import copy
from coverage_fixtures import observed_statement
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

SCRIPTS = Path(os.environ.get('MONEYLENS_TEST_SCRIPTS',
    str(Path(__file__).resolve().parents[1] / 'plugins/moneylens/skills/automation/scripts')))
sys.path.insert(0, str(SCRIPTS.parent))
from moneylens.merchants import remember, lookup
from moneylens import personalize
from moneylens.accounts import validate_source
from moneylens.dashboard import render
from moneylens.ledger import assessment, connect, hash_value, normalize, records
from moneylens.processing import process_batch
from moneylens.store import config_validated, get, put, source_key, reviews, record_outcome
from test_ledger import fixture

STAMP = '2026-10-20T09:00:00+05:30'


class AccountingRuleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.db = connect(self.root)
        self.config = config_validated({'mailboxes': [{'id': 'mail-a', 'address': 'mail-a', 'verified_at': STAMP}], 'timezone': 'Asia/Kolkata', 'report_path': str(self.root / 'report.html'), 'cards': [{'account_label':'Synthetic account','account_key': 'test-card-a', 'issuer': 'Institution A', 'masked_identifier': '1234',
                       'password_status': 'not_required', 'credential_scope': 'shared'}]})
        with self.db: put(self.db, 'config', self.config)

    def tearDown(self):
        self.db.close()
        self.temp.cleanup()










    def test_explicit_account_keys_do_not_infer_identity_from_institution_names(self):
        payload=fixture(issuer='An unfamiliar institution')
        payload['source']['mailbox']='mail-a'
        validate_source(self.config,payload)
        payload['account_key']='unconfirmed'
        with self.assertRaisesRegex(ValueError,'confirmation'):validate_source(self.config,payload)
        payload['account_key']='test-card-a';payload['source']['mailbox']='unknown'
        with self.assertRaises(ValueError):validate_source(self.config,payload)

    def test_cached_categories_do_not_change_credit_repayment_or_transfer_accounting(self):
        with self.db:remember(self.db,'Employer','Salary')
        for kind in ('credit','credit','repayment','transfer_in','transfer_out','payment'):
            p=normalize(fixture());p['transactions']=[{**p['transactions'][0],'merchant':'Employer','category':'Other','kind':kind,'amount_minor':100 if kind in {'repayment','transfer_out'} else -100}]
            source=[{'id':'row','payload':p,'status':'imported'}];before=copy.deepcopy(source)
            row=personalize.decorate(self.db,source)[0]['payload']['transactions'][0]
            self.assertEqual(row['category'],'Salary')
            self.assertEqual((row['kind'],row['amount_minor']),(kind,p['transactions'][0]['amount_minor']))
            self.assertEqual(source,before)

    def test_shared_statement_password_scope_is_valid_for_distinct_accounts(self):
        raw = copy.deepcopy(self.config); raw.pop('ready')
        raw['cards'].append({'account_label':'Synthetic account',**raw['cards'][0], 'account_key': 'second', 'masked_identifier': '5678'})
        raw['bank_accounts'] = [{'account_key': 'bank', 'issuer': 'Institution A', 'masked_identifier': '4321',
            'account_label': 'Savings', 'statement_enabled': True, 'credential_scope': 'shared', 'password_status': 'not_required'}]
        self.assertTrue(config_validated(raw)['ready'])
        raw['cards'][1]['account_key'] = raw['cards'][0]['account_key']
        with self.assertRaisesRegex(ValueError, 'Duplicate account'): config_validated(raw)



    def test_missing_payment_channel_remains_unknown(self):
        p = fixture(account_type='bank_account', checks={})
        p['transactions'] = [{**p['transactions'][0], 'merchant': merchant, 'row': str(index)}
                             for index, merchant in enumerate(('NEFT employer', 'UPI coffee', 'EMI UPI payment'))]
        data = json.loads(render([{'id': 'bank', 'status': 'imported', 'payload': p, 'validation': {'issues': []}}])
                          .split('<script id="data" type="application/json">')[1].split('</script>')[0])
        self.assertEqual([r['channel'] for r in data['rows']], [None, None, None])
        self.assertEqual([r['channel'] for r in data['rows']], [r['channel'] for r in normalize(p)['transactions']])


if __name__ == '__main__': unittest.main()
