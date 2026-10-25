"""Core accounting invariants on synthetic data, through Python accounting functions."""
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'skills/automation'))
from coverage_fixtures import observed_statement
from moneylens.ledger import connect, stage, records, find, import_record, assessment
from moneylens.private_files import check_private
from moneylens.personalize import annotate
from moneylens.transactions import list_transactions, remove
from moneylens.dashboard import write_report


def fixture(message="msg-1", **overrides):
    p = {"source": {"mailbox": "synthetic-test", "message_id": message, "attachment_id": "pdf-part", "filename": "synthetic.pdf"},
         "account_key": "test-card-a", "account_type": "credit_card", "account_label": "Synthetic Bank · 1234", "issuer": "Synthetic Bank",
         "period_start": "2026-09-01", "period_end": "2026-09-30", "currency": "INR", "currency_exponent": 2,
         "complete": True, "issues": [],
         "checks": {"expected_transaction_count": 3, "expected_debits_minor": 12000, "expected_credits_minor": 6000,
                    "opening_balance_minor": 10000, "closing_balance_minor": 16000},
         "transactions": [
             {"date": "2026-09-08", "merchant": "Synthetic Grocer", "amount_minor": 12000, "kind": "purchase", "category": "Groceries", "page": 1, "row": "1"},
             {"date": "2026-09-10", "merchant": "Synthetic refund", "amount_minor": -1000, "kind": "refund", "category": "Groceries", "page": 1, "row": "2"},
             {"date": "2026-09-15", "merchant": "Payment received", "amount_minor": -5000, "kind": "payment", "category": "Credit card payments", "page": 1, "row": "3"}]}
    p.update(overrides)
    return p


class LedgerTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.data=self.root/'data';self.db=connect(self.data)
    def tearDown(self): self.db.close()

    def stage(self,p,observed=True):
        path=self.root/'input.json';path.write_text(json.dumps(observed_statement(p) if observed else p))
        with self.db:return stage(self.db,path)

    def payload(self,sid): return find(records(self.db),sid)['payload']
    def accept(self,sid):
        with self.db:return import_record(self.db,sid)

    def test_staging_and_validated_import_survive_reopening(self):
        result=self.stage(fixture());sid=result['id']
        self.assertEqual(result['issues'],[]);self.assertEqual(len(result['passed_checks']),4)
        self.assertEqual(records(self.db)[0]['status'],'draft')
        self.assertEqual(self.accept(sid)['result'],'imported')
        self.assertEqual(self.accept(sid)['result'],'already_imported')
        self.db.close();self.db=connect(self.data)
        self.assertEqual(self.stage(fixture())['result'],'already_imported')
        with self.assertRaises(ValueError):remove(self.db,sid+':0')
        check_private(self.data/'ledger.sqlite3')

    def test_duplicate_multisets_preserve_row_multiplicity(self):
        first=self.stage(fixture());p=fixture('msg-2');p['transactions'].reverse()
        self.assertNotEqual(self.stage(p)['id'],first['id'])
        repeated=copy.deepcopy(p['transactions'][0]);repeated['row']='4'
        p['transactions'].append(repeated);p['checks']={}
        result=self.stage(p)
        self.assertTrue(any('overlap' in issue for issue in result['issues']))
        self.assertEqual(len(self.payload(result['id'])['transactions']),4)

    def test_cross_statement_overlap_requires_explicit_resolution(self):
        self.stage(fixture());p=fixture('msg-2',period_end='2026-10-05',checks={})
        sid=self.stage(p)['id'];self.assertEqual(len(self.payload(sid)['transactions']),3)
        with self.assertRaisesRegex(ValueError,'overlap'):self.accept(sid)
        p['distinct_overlap_rows']=[0,1,2];p['resolution_notes']='User confirms distinct movements'
        self.stage(p);self.assertEqual(self.accept(sid)['result'],'imported')

    def test_mismatches_unknown_rows_and_incomplete_extraction_block_import(self):
        p=fixture(complete=False);p['checks']['closing_balance_minor']+=1;p['transactions'][0]['kind']='unknown'
        result=self.stage(p);self.assertGreaterEqual(len(result['issues']),3)
        with self.assertRaisesRegex(ValueError,'Import blocked'):self.accept(result['id'])

    def test_digest_does_not_hide_conflicting_rows_and_currencies_stay_separate(self):
        p=fixture();p['source']['sha256']='a'*64;self.stage(p)
        q=fixture('msg-2');q['source']['sha256']='a'*64;q['transactions'][0]['merchant']='Different extraction'
        self.assertEqual(self.stage(q)['result'],'staged')
        self.assertEqual(self.stage(fixture('msg-3',account_key='test-usd',currency='USD'))['issues'],[])
        self.assertEqual(len(records(self.db)),3)
        with self.assertRaisesRegex(ValueError,'exponent conflicts'):self.stage(fixture('msg-4',currency_exponent=0))

    def test_row_annotations_survive_restage_without_changing_source_categories(self):
        p=fixture();sid=self.stage(p)['id']
        with self.db:annotate(self.db,sid,0,category='Dining')
        p['transactions'][0]['category']='Other';self.stage(p)
        self.assertEqual(self.payload(sid)['transactions'][0]['category'],'Other')
        self.assertEqual(next(r for r in list_transactions(self.db) if r['id']==sid+':0')['category'],'Dining')
        self.assertEqual(self.payload(sid)['transactions'][2]['kind'],'payment')

    def test_invalid_dates_minor_units_and_signs_fail_without_partial_writes(self):
        for key,value in [('date','2026-02-30'),('amount_minor',2.5),('amount_minor',-100)]:
            with self.subTest(key=key,value=value),self.assertRaises(ValueError):
                p=fixture();p['transactions'][0][key]=value;self.stage(p)
        self.assertEqual(records(self.db),[])

    def test_duplicate_locations_fail_but_distinct_source_rows_remain(self):
        p=fixture(checks={});p['transactions'].append(copy.deepcopy(p['transactions'][0]))
        with self.assertRaisesRegex(ValueError,'source row location'):self.stage(p)
        p['transactions'][-1]['row']='4';sid=self.stage(p)['id']
        self.assertEqual(len(self.payload(sid)['transactions']),4)

    def test_report_escapes_source_text_and_does_not_import(self):
        p=fixture();p['transactions'][0]['merchant']='</script><img src=x onerror="alert(1)">'
        self.stage(p);output=self.root/'report.html';write_report(self.db,output,'2026-09-01','2026-09-30')
        html=output.read_text();self.assertNotIn(p['transactions'][0]['merchant'],html)
        self.assertIn('\\u003c/script',html);self.assertIn("connect-src 'none'",html)
        self.assertEqual(records(self.db)[0]['status'],'draft')
        with self.assertRaises(ValueError):write_report(self.db,output,'2026-10-01','2026-09-01')

    def test_missing_independent_checks_block_import_and_are_disclosed(self):
        sid=self.stage(fixture(checks={}),observed=False)['id']
        checked=assessment(find(records(self.db),sid),records(self.db))
        self.assertEqual(checked['passed_checks'],[]);self.assertEqual(len(checked['unavailable_checks']),5)
        with self.assertRaises(ValueError):self.accept(sid)

    def test_empty_report_needs_no_accounts_or_collection_state(self):
        output=self.root/'empty.html';write_report(self.db,output)
        self.assertTrue(output.is_file());self.assertEqual(records(self.db),[])


if __name__=='__main__':unittest.main()
