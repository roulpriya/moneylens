"""Bank-statement cash accounting and evidence-backed own-transfer exclusions."""
import copy
from coverage_fixtures import observed_statement
import json
from pathlib import Path
import sys
import subprocess
import tempfile
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'skills/automation'))
from moneylens.ledger import connect, stage, records, assessment, find, save
from moneylens.store import config_validated, put, get
from moneylens.processing import process_batch
from moneylens.personalize import decorate
from moneylens.transfers import confirm
from moneylens.alerts import ingest, report_records


class BankStatementTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.root = Path(self.temp.name); self.db = connect(self.root)
        self.input = self.root/'input.json'
        self.raw = {'mailboxes': [{'id': 'test-mail', 'address': 'test-mail', 'verified_at': '2026-10-20T09:00:00+05:30'}], 'timezone': 'Asia/Kolkata', 'cards': [], 'report_path': str(self.root/'report.html'), 'bank_accounts': [{'account_key':key,'issuer':issuer,'masked_identifier':ending,'account_label':key,
                                      'statement_enabled':True,'credential_scope':key+'-pdf','password_status':'not_required'}
                                     for key, issuer, ending in [('own-a','Bank A','1234'),('own-b','Bank B','5678')]]}
        self.config = config_validated(self.raw)
        with self.db: put(self.db, 'config', self.config)

    def tearDown(self): self.db.close(); self.temp.cleanup()

    def payload(self, account='own-a', amount=20000, reference=None, kind=None, message=None):
        row = {'date':'2026-10-02','merchant':'Bank transfer','amount_minor':amount,
               'kind':kind or ('debit' if amount>=0 else 'credit'), 'category':'Other', 'page':1,'row':'1'}
        if reference: row['reference'] = reference
        return {'source':{'mailbox':'test-mail','message_id':message or account,'filename':'statement.pdf'},
                'account_key':account,'account_label':account,'issuer':'Bank A' if account=='own-a' else 'Bank B',
                'account_type':'bank_account','period_start':'2026-10-01','period_end':'2026-10-20',
                'currency':'INR','currency_exponent':2,'complete':True,'issues':[], 'checks':{}, 'transactions':[row]}

    def save_statement(self, p):
        self.input.write_text(json.dumps(observed_statement(p)))
        with self.db:
            result = stage(self.db, self.input)
            if not result.get('issues'):
                record = find(records(self.db), result['id']); record['status']='imported'; save(self.db,record)
        return result

    def effective(self):
        statements = records(self.db)
        return decorate(self.db, statements + report_records(self.db, statements))

    def test_bank_statement_credentials_report_current_readiness(self):
        raw=copy.deepcopy(self.raw);raw['bank_accounts'][0]['password_status']='unverified'
        cfg=config_validated(raw)
        self.assertFalse(cfg['ready'])
        self.assertEqual(cfg['bank_accounts'][0]['account_key'],'own-a')

    def test_bank_cash_balance_uses_debits_out_and_credits_in(self):
        p=self.payload(); credit=copy.deepcopy(p['transactions'][0]);credit.update(amount_minor=-5000,kind='credit',row='2')
        p['transactions'].append(credit)
        p['checks']={'opening_balance_minor':100000,'closing_balance_minor':85000,'expected_debits_minor':20000,'expected_credits_minor':5000}
        result=self.save_statement(p)
        self.assertEqual(result['issues'],[]);self.assertIn('balance_reconciliation',result['passed_checks'])
        self.assertIsNone(records(self.db)[0]['payload']['transactions'][0]['channel'])
        repayment=self.payload(kind='repayment',message='card-bill-payment')
        self.assertEqual(self.save_statement(repayment)['issues'],[])
        p=self.payload(message='wrong-balance');p['checks']={'opening_balance_minor':100000,'closing_balance_minor':120000}
        self.assertTrue(any('Balance mismatch' in x for x in self.save_statement(p)['issues']))

    def test_owned_pair_excluded_with_shared_reference_and_keeps_all_source_amounts(self):
        self.save_statement(self.payload(reference='bank-ref-001'))
        self.save_statement(self.payload('own-b',-20000,'bank-ref-001'))
        original=records(self.db); rows=[r['payload']['transactions'][0] for r in self.effective()]
        self.assertTrue(all(row['excluded_from_spending'] for row in rows))
        self.assertEqual([row['amount_minor'] for row in rows],[r['payload']['transactions'][0]['amount_minor'] for r in original])
        self.assertEqual(records(self.db),original)
        process_batch(self.root,[])
        html=(self.root/'report.html').read_text();data=json.loads(html.split('<script id="data" type="application/json">')[1].split('</script>')[0])
        self.assertEqual(len(data['rows']),2);self.assertTrue(all(row['excluded_from_spending'] for row in data['rows']))
        self.assertTrue(all(s['record_type']=='bank_statement' for s in data['statements']))
        self.assertEqual(data['review_items'],[])

    def test_amount_similarity_and_conflicting_reference_do_not_hide_spending(self):
        self.save_statement(self.payload())
        self.save_statement(self.payload('own-b',-20000))
        self.assertFalse(any(row.get('excluded_from_spending') for r in self.effective() for row in r['payload']['transactions']))
        # A duplicated opposite-leg candidate cannot establish a unique self-transfer.
        self.save_statement(self.payload(reference='repeated',message='debit'))
        p=self.payload('own-b',-20000,'repeated',message='credit')
        second=copy.deepcopy(p['transactions'][0]);second['row']='2';p['transactions'].append(second)
        self.save_statement(p)
        self.assertFalse(any(row.get('excluded_from_spending') for r in self.effective() for row in r['payload']['transactions']))


    def test_manual_exclusion_follows_upi_alert_to_generic_bank_statement(self):
        alert=self.payload(amount=20000,reference='own-ref',kind='debit',message='alert')
        alert['source']['filename']='email-body';alert['transactions'][0]['channel']='upi'
        alert['period_start']=alert['period_end']='2026-10-02'
        self.input.write_text(json.dumps(alert))
        with self.db:
            result=ingest(self.db,self.input)
            confirm(self.db,result['id'],0,'own-b','User confirms transfer to their Bank B savings account')
        sid=self.save_statement(self.payload(reference='own-ref'))['id']
        effective=self.effective();statement=next(r for r in effective if r['id']==sid)
        self.assertTrue(statement['payload']['transactions'][0]['excluded_from_spending'])
        matched=next(r for r in effective if r['id']==result['id'])
        self.assertEqual(matched['status'],'statement_covered')
        self.assertEqual(statement['payload']['transactions'][0]['kind'],'debit')
        with self.assertRaises(ValueError):confirm(self.db,sid,0,'unknown-account','Unverified owner')
        # A cached merchant category cannot release an excluded transfer into spending.
        from moneylens.merchants import remember
        with self.db:remember(self.db,'Bank transfer','Shopping')
        self.assertTrue(next(r for r in self.effective() if r['id']==sid)['payload']['transactions'][0]['excluded_from_spending'])

    def test_explicit_transfer_requires_ownership_evidence_and_bank_type_matches(self):
        p=self.payload(kind='transfer_out')
        self.assertTrue(any('ownership evidence' in x for x in self.save_statement(p)['issues']))
        p['transactions'][0].update(own_account_key='own-b',transfer_evidence='User confirms destination account')
        self.assertEqual(self.save_statement(p)['issues'],[])
        self.assertTrue(self.effective()[0]['payload']['transactions'][0]['excluded_from_spending'])
        bad=self.payload(message='wrong-type');bad['account_type']='credit_card'
        with self.assertRaisesRegex(ValueError,'account type'):self.save_statement(bad)





    def test_bank_zero_activity_requires_explicit_count_and_unchanged_balances(self):
        p=self.payload(message='zero-activity');p['transactions']=[]
        p['checks']={'expected_transaction_count':0,'opening_balance_minor':0,'closing_balance_minor':0}
        result=self.save_statement(p)
        self.assertEqual(result['issues'],[])
        self.assertEqual(records(self.db)[0]['status'],'imported')
        self.assertEqual(records(self.db)[0]['payload']['transactions'],[])
        p['account_type']='credit_card';p['account_resolved']=True
        self.assertIn('No transaction rows',assessment({'id':'empty-card','status':'draft','payload':p},[])['issues'])
        p['account_type']='bank_account';p['checks'].pop('expected_transaction_count')
        self.assertIn('No transaction rows',assessment({'id':'unverified-empty-bank','status':'draft','payload':p},[])['issues'])

if __name__=='__main__':unittest.main()
