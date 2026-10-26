"""Agents choose new categories; accounting only stores and reuses exact cached choices."""
import json
import copy
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'plugins/moneylens/skills/automation'))
from moneylens.ledger import connect, records, normalize
from moneylens.store import save_config
from moneylens.transactions import add, update, list_transactions
from moneylens.merchants import lookup, remember, entries, review
from moneylens.processing import process_batch
from test_ledger import fixture
from coverage_fixtures import observed_statement

SCRIPT=Path(__file__).resolve().parents[1]/'plugins/moneylens/skills/automation/scripts/moneylens.py'


class MerchantCacheTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.db=connect(self.root);self.addCleanup(self.db.close)
        with self.db:save_config(self.db,{'mailboxes':[{'id':'synthetic-test','address':'test@example.invalid'}],
            'report_path':str(self.root/'report.html'),
            'cards':[{'account_label':'Synthetic account','account_key':'test-card-a','issuer':'Any issuer','masked_identifier':'1234','credential_scope':'scope','password_status':'not_required'}]})

    def test_familiar_words_do_not_guess_a_category_on_cache_miss(self):
        for name in ('Coffee shop','Uber','Swiggy Instamart','Netflix','Gym membership','Unknown store'):
            with self.subTest(merchant=name):
                self.assertIsNone(lookup(self.db,name))
                with self.assertRaisesRegex(ValueError,'agent must categorize'):
                    with self.db:add(self.db,name,'100','2026-10-24', currency_exponent=2, kind='purchase', currency='INR')
        self.assertEqual(entries(self.db),[]);self.assertEqual(list_transactions(self.db),[])

    def test_agent_category_is_cached_and_reused_across_processes(self):
        with self.db:first=add(self.db,'Vendor One','12.50','2026-10-24','Work expenses', currency_exponent=2, kind='purchase', currency='INR')
        self.assertEqual(lookup(self.db,' VENDOR   ONE '),'Work expenses')
        result=subprocess.run([sys.executable,str(SCRIPT),'add','--data-dir',str(self.root),
            '--currency','INR','--currency-exponent','2','--kind','purchase','--description','vendor one','--amount','15','--date','2026-10-24'],capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stderr)
        second=json.loads(result.stdout)
        self.assertEqual(second['category'],'Work expenses');self.assertNotEqual(first['id'],second['id'])

    def test_cache_is_exact_without_keyword_substring_or_brand_alias_matches(self):
        with self.db:remember(self.db,'Vendor','Groceries')
        for name in ('Vendor cafe','New Vendor','SwiggyInstamart','Instamart'):
            self.assertIsNone(lookup(self.db,name))
        self.assertEqual(lookup(self.db,'vendor'),'Groceries')

    def test_agent_canonical_merchant_key_preserves_original_descriptions(self):
        with self.db:
            first=add(self.db,'BANK ORIGINAL DESCRIPTION 1','100','2026-10-24','Dining',extra={'merchant':'Canonical vendor'}, currency_exponent=2, kind='purchase', currency='INR')
            second=add(self.db,'DIFFERENT ORIGINAL DESCRIPTION 2','110','2026-10-24',extra={'merchant':'Canonical vendor'}, currency_exponent=2, kind='purchase', currency='INR')
        self.assertEqual(first['description'],'BANK ORIGINAL DESCRIPTION 1')
        self.assertEqual(second['description'],'DIFFERENT ORIGINAL DESCRIPTION 2')
        self.assertEqual(second['category'],'Dining')
        self.assertIsNone(lookup(self.db,'DIFFERENT ORIGINAL DESCRIPTION 2'))

    def test_one_off_category_overrides_do_not_overwrite_the_cache(self):
        with self.db:
            first=add(self.db,'Vendor','100','2026-10-24','Groceries', currency_exponent=2, kind='purchase', currency='INR')
            special=add(self.db,'Vendor','100','2026-10-24','Work expenses', currency_exponent=2, kind='purchase', currency='INR')
            update(self.db,first['id'],{'category':'Personal shopping'})
        self.assertEqual(special['category'],'Work expenses')
        self.assertEqual(lookup(self.db,'Vendor'),'Groceries')
        with self.db:
            remember(self.db,'Vendor','Dining')
            future=add(self.db,'Vendor','100','2026-10-24', currency_exponent=2, kind='purchase', currency='INR')
        self.assertEqual(future['category'],'Dining')
        self.assertEqual(next(r for r in list_transactions(self.db) if r['id']==first['id'])['category'],'Personal shopping')

    def test_other_remains_uncached_and_requires_agent_review(self):
        with self.db:item=add(self.db,'Unclear vendor','100','2026-10-24','Other', currency_exponent=2, kind='purchase', currency='INR')
        self.assertIsNone(lookup(self.db,'Unclear vendor'))
        self.assertEqual(item['category'],'Other')
        self.assertEqual(review(self.db)['currencies'][0]['count'],1)
        with self.assertRaises(ValueError):remember(self.db,'Unclear vendor','Other')

    def test_statement_import_caches_only_supplied_valid_classifications(self):
        p=fixture();p['transactions'][0]['category']='Agent decided category'
        process_batch(self.root,[{'type':'statement','payload':observed_statement(p)}],render_report=False)
        self.assertEqual(lookup(self.db,'Synthetic Grocer'),'Agent decided category')
        bad=fixture('invalid');bad['transactions'][0].update(merchant='Never cached',category='Groceries',amount_minor='invalid')
        result=process_batch(self.root,[{'type':'statement','payload':bad}],render_report=False)
        self.assertEqual(result['outcomes'][0]['result'],'needs_review')
        self.assertIsNone(lookup(self.db,'Never cached'))

    def test_statement_import_reuses_exact_cache_without_recategorizing_or_mutating_input(self):
        with self.db: remember(self.db,'Canonical vendor','Work expenses')
        payload=observed_statement(fixture())
        row=payload['transactions'][0]
        row.update(merchant='Original source descriptor',metadata={'merchant':' CANONICAL   VENDOR '})
        del row['category']
        original=copy.deepcopy(payload)
        result=process_batch(self.root,[{'type':'statement','payload':payload}],render_report=False)
        self.assertEqual(result['outcomes'][0]['result'],'imported')
        saved=records(self.db)[0]['payload']['transactions'][0]
        self.assertEqual(saved['category'],'Work expenses')
        self.assertEqual(saved['merchant'],'Original source descriptor')
        self.assertEqual(payload,original)

    def test_statement_explicit_category_takes_priority_over_cached_mapping(self):
        with self.db: remember(self.db,'Synthetic Grocer','Cached category')
        payload=observed_statement(fixture())
        payload['transactions'][0]['category']='Explicit one-off category'
        result=process_batch(self.root,[{'type':'statement','payload':payload}],render_report=False)
        self.assertEqual(result['outcomes'][0]['result'],'imported')
        self.assertEqual(records(self.db)[0]['payload']['transactions'][0]['category'],'Explicit one-off category')
        self.assertEqual(lookup(self.db,'Synthetic Grocer'),'Cached category')

    def test_statement_cache_miss_requires_agent_decision_instead_of_guessing(self):
        payload=observed_statement(fixture())
        del payload['transactions'][0]['category']
        result=process_batch(self.root,[{'type':'statement','payload':payload}],render_report=False)
        self.assertEqual(result['outcomes'][0]['result'],'needs_review')
        self.assertIn('agent must categorize',result['outcomes'][0]['reason'])
        self.assertEqual(records(self.db),[])
        self.assertEqual(entries(self.db),[])

    def test_source_metadata_can_select_cached_merchant_without_rewriting_financial_evidence(self):
        p=fixture();p['transactions'][0].update(merchant='Original descriptor',category='Other')
        result=process_batch(self.root,[{'type':'statement','payload':observed_statement(p)}],render_report=False)
        raw=records(self.db)
        with self.db:
            remember(self.db,'Canonical vendor','Dining')
            update(self.db,result['outcomes'][0]['id']+':0',{'metadata':{'merchant':'Canonical vendor'}})
        rows=list_transactions(self.db)
        item=next(r for r in rows if r['description']=='Original descriptor')
        self.assertEqual(item['category'],'Dining')
        self.assertEqual(records(self.db),raw)

    def test_explicit_labels_are_not_reclassified_by_descriptor_or_account_type(self):
        for kind,amount in (('debit',12000),('credit',-12000),('payment',-12000)):
            p=fixture(account_type='bank_account')
            p['transactions']=[{**p['transactions'][0],'kind':kind,'amount_minor':amount,'merchant':'Coffee pharmacy supermarket','category':'Agent chosen label'}]
            self.assertEqual(normalize(p)['transactions'][0]['category'],'Agent chosen label')

    def test_cli_merchant_lookup_and_explicit_cache_updates(self):
        prefix=[sys.executable,str(SCRIPT),'merchants','--data-dir',str(self.root),'--merchant','New store']
        missing=subprocess.run(prefix,capture_output=True,text=True)
        self.assertEqual(json.loads(missing.stdout),{'merchant':'new store','category':None,'needs_category':True})
        saved=subprocess.run(prefix+['--category','Travel'],capture_output=True,text=True)
        self.assertEqual(saved.returncode,0,saved.stderr)
        self.assertEqual(json.loads(saved.stdout)['category'],'Travel')
        found=subprocess.run(prefix,capture_output=True,text=True)
        self.assertFalse(json.loads(found.stdout)['needs_category'])


if __name__=='__main__':unittest.main()
