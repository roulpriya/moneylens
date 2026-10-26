"""Accounting consumes supplied inputs without touching collection or scheduler state."""
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'plugins/moneylens/skills/automation'))
from moneylens.ledger import connect, records
from moneylens.processing import process_batch
from moneylens.store import get, put, save_config, reviews
from moneylens.transactions import add, update, remove, list_transactions
from coverage_fixtures import observed_statement
from test_ledger import fixture


class ProcessingBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name); self.db = connect(self.root); self.addCleanup(self.db.close)
        self.config = {'mailboxes': [{'id': 'synthetic-test', 'address': 'synthetic-test', 'verified_at': '2026-10-24T00:00:00+00:00'}], 'report_path': str(self.root/'report.html'), 'cards': [{'account_label':'Synthetic account','account_key': 'test-card-a',
                'issuer': 'Synthetic Bank', 'masked_identifier': '1234', 'credential_scope': 'test-scope', 'password_status': 'not_required'}]}
        with self.db: save_config(self.db, self.config)

    def test_processing_keeps_only_accounting_schema_tables(self):
        with patch('socket.create_connection',side_effect=AssertionError('Accounting must stay local')):
            result=process_batch(self.root,[{'type':'statement','payload':observed_statement(fixture())}])
        self.assertEqual(result['outcomes'][0]['result'],'imported')
        names={r[0] for r in self.db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        self.assertFalse(names & {'runtime_meta','retry_sources','source_dispositions'})
        self.assertIsNone(get(self.db,'active_run'))

    def test_supplied_notifications_are_idempotent_provisional_and_replaced_by_statement(self):
        metadata={'source':{'mailbox':'synthetic-test','message_id':'notification','filename':'email-body'}, 'reference':'bank-ref'}
        with self.db:
            first=add(self.db,'Synthetic Grocer','120','2026-09-08','Groceries',account='test-card-a',extra=metadata, currency_exponent=2, kind='purchase', currency='INR')
            second=add(self.db,'Synthetic Grocer','120','2026-09-08','Groceries',account='test-card-a',extra=metadata, currency_exponent=2, kind='purchase', currency='INR')
        self.assertEqual(first['id'],second['id']); self.assertEqual(first['status'],'provisional')
        self.assertEqual(len(list_transactions(self.db)),1)
        p=fixture();p['transactions'][0]['reference']='bank-ref'
        result=process_batch(self.root,[{'type':'statement','payload':observed_statement(p)}],render_report=False)
        self.assertEqual(result['outcomes'][0]['result'],'imported')
        current=list_transactions(self.db)
        self.assertEqual(len(current),3);self.assertTrue(all(r['status']=='confirmed' for r in current))
        original=copy.deepcopy(records(self.db))
        with self.db: update(self.db,current[0]['id'],{'category':'Work expenses','metadata':{'project':'A'}})
        self.assertEqual(records(self.db),original)
        with self.assertRaises(ValueError): update(self.db,current[0]['id'],{'amount':'999'})
        with self.assertRaises(ValueError): remove(self.db,current[0]['id'])

    def test_failed_statement_produces_local_financial_review_and_no_retrieval_queue(self):
        p=observed_statement(fixture());p['transactions'][0]['amount_minor']='invalid'
        result=process_batch(self.root,[{'type':'statement','payload':p}],render_report=False)
        self.assertEqual(result['outcomes'][0]['result'],'needs_review')
        self.assertEqual(len(reviews(self.db)),1)
        self.assertIsNone(get(self.db,'active_run'));self.assertIsNone(get(self.db,'last_success'))

    def test_explicit_manual_category_and_metadata_override_cache_and_survive_reports(self):
        with self.db:
            from moneylens.merchants import remember
            remember(self.db,'Coffee','Dining')
            item=add(self.db,'Coffee','120.50','2026-10-24','Work expenses',extra={'project':'A'}, currency_exponent=2, kind='purchase', currency='INR')
        self.assertEqual(item['category'],'Work expenses')
        process_batch(self.root,[])
        html=(self.root/'report.html').read_text()
        data=json.loads(html.split('<script id="data" type="application/json">')[1].split('</script>')[0])
        self.assertEqual(data['rows'][0]['category'],'Work expenses')
        self.assertEqual(data['rows'][0]['metadata'],{'project':'A'})

    def test_concurrent_supplied_notification_adds_count_once_without_workflow_leases(self):
        import subprocess
        command=[sys.executable,str(Path(__file__).resolve().parents[1]/'plugins/moneylens/skills/automation/scripts/moneylens.py'),
            'add','--currency','INR','--currency-exponent','2','--kind','purchase','--data-dir',str(self.root),'--description','Coffee','--amount','120','--date','2026-10-24',
            '--account','test-card-a','--category','Dining','--metadata',json.dumps({'source':{'mailbox':'synthetic-test','message_id':'same-notice'}})]
        children=[subprocess.Popen(command,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True) for _ in range(2)]
        outcomes=[]
        for child in children:
            out,err=child.communicate(timeout=30)
            self.assertEqual(child.returncode,0,err);outcomes.append(json.loads(out))
        self.assertEqual(outcomes[0]['id'],outcomes[1]['id'])
        self.assertEqual(len(list_transactions(self.db)),1)
        self.assertIsNone(get(self.db,'active_run'))


if __name__ == '__main__': unittest.main()
