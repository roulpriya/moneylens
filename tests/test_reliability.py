"""Regressions for the six review findings; no live mail, secrets, data, or jobs."""
import copy
from coverage_fixtures import observed_statement
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

SCRIPTS = Path(os.environ.get('MONEYLENS_TEST_SCRIPTS',
                            str(Path(__file__).resolve().parents[1] / 'skills/automation/scripts')))
sys.path.insert(0, str(SCRIPTS.parent))
from moneylens.store import reviews
from moneylens.alerts import ingest, report_records
from moneylens.ledger import connect, records, stage, save, hash_value, source_id
from moneylens.processing import process_batch
from moneylens.store import config_validated, get, put, source_key
from test_ledger import fixture

STAMP = '2026-10-20T09:00:00+05:30'


class ReliabilityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / 'data'; self.db = connect(self.root)
        self.codex = Path(self.temp.name) / 'codex'
        self.env = patch.dict(os.environ, {'CODEX_HOME': str(self.codex)})
        self.env.start()
        self.config = config_validated({'mailboxes': [{'id': m, 'address': m + '@example.invalid', 'verified_at': STAMP} for m in ('mail-a', 'mail-b')], 'timezone': 'Asia/Kolkata', 'report_path': str(self.root / 'report.html'), 'cards': [{'account_label':'Synthetic account','account_key': 'test-card-a', 'issuer': 'Institution A', 'masked_identifier': '1234',
                       'credential_scope': 'scope-a', 'password_status': 'not_required'}]})
        with self.db: put(self.db, 'config', self.config)

    def tearDown(self):
        self.db.close(); self.env.stop(); self.temp.cleanup()

    def payload(self, message='statement', mailbox='mail-a', account='test-card-a', **changes):
        p = fixture(message, **changes)
        p['source']['mailbox'] = mailbox; p.update(account_key=account, issuer='Institution A')
        return observed_statement(p)

    def alert(self, message='alert', **changes):
        p = self.payload(message, checks={})
        p['source'] = {**p['source'], 'filename': 'email-body'}; p['source'].pop('attachment_id')
        p.pop('coverage', None); p['checks'] = {}
        p['transactions'] = [p['transactions'][0]]
        p['transactions'][0].update(row='body:1', **changes)
        return p

    def stage(self, p, imported=False):
        path = self.root / 'input.json'; path.write_text(json.dumps(observed_statement(p)))
        with self.db:
            result = stage(self.db, path)
            if imported:
                record = next(r for r in records(self.db) if r['id'] == result['id'])
                record['status'] = 'imported'; save(self.db, record)
        return result

    def ingest(self, p):
        path = self.root / 'alert.json'; path.write_text(json.dumps(p))
        with self.db: return ingest(self.db, path)


    def second_account(self, password='not_required'):
        config = copy.deepcopy(self.config); config.pop('ready')
        config['cards'][0].update(identity='personal', identity_evidence='Confirmed first account')
        config['cards'].append({**config['cards'][0], 'account_key': 'card-b', 'credential_scope': 'scope-b',
                                'identity': 'work', 'identity_evidence': 'Confirmed second account', 'password_status': password})
        self.config = config_validated(config)
        with self.db: put(self.db, 'config', self.config)

    def test_shared_reference_never_overrides_amount_or_movement_conflicts(self):
        p = self.payload(); p['transactions'][0]['reference'] = 'shared'
        self.stage(p, imported=True)
        for change in ({'amount_minor': 99900}, {'kind': 'fee'}, {'kind': 'refund', 'amount_minor': -12000}):
            with self.subTest(change=change):
                self.db.execute('DELETE FROM alerts'); self.db.commit()
                self.ingest(self.alert(reference='shared', **change))
                result = report_records(self.db, records(self.db))[0]
                self.assertEqual(result['status'], 'statement_covered')
                self.assertIsNone(result['matched_to']); self.assertFalse(result['validation']['issues'])
                self.assertTrue(result['covered_by_statements'])
        self.assertEqual(records(self.db)[0]['payload']['transactions'][0]['amount_minor'], 12000)

    def test_valid_shared_reference_still_reconciles(self):
        p = self.payload(); p['transactions'][0]['reference'] = 'shared'
        sid = self.stage(p, imported=True)['id']; self.ingest(self.alert(reference='shared'))
        self.assertEqual(report_records(self.db, records(self.db))[0]['matched_to'], (sid, 0))

    def test_conflicting_reextraction_keeps_original_alert_and_queues_review(self):
        p = self.alert(); self.ingest(p)
        changed = copy.deepcopy(p); changed['transactions'][0]['amount_minor'] = 99900
        result = process_batch(self.root, [{'type': 'alert', 'payload': changed}])
        self.assertEqual(result['outcomes'][0]['result'], 'needs_review')
        raw = self.db.execute('SELECT payload FROM alerts').fetchone()[0]
        self.assertEqual(json.loads(raw)['transactions'][0]['amount_minor'], 12000)
        self.assertEqual(len(reviews(self.db)), 1)





    def test_combined_pdf_keeps_same_ending_accounts_and_existing_ids_and_provenance(self):
        self.second_account()
        first = self.payload(); first['source']['sha256'] = 'a' * 64
        sid = self.stage(first, imported=True)['id']
        self.assertEqual(sid, source_id(first))
        # A new section must retain the first section's independent provenance.
        with self.db:
            self.assertEqual(self.db.execute('SELECT count(*) FROM source_links').fetchone()[0], 1)
        second = copy.deepcopy(first); second['account_key'] = 'card-b'
        second['transactions'][0]['merchant'] = 'Another merchant'
        other = self.stage(second, imported=True)['id']
        self.assertNotEqual(sid, other)
        self.assertEqual(self.stage(first)['id'], sid); self.assertEqual(self.stage(second)['id'], other)
        self.assertEqual({r['payload']['account_key'] for r in records(self.db)}, {'test-card-a', 'card-b'})
        self.assertEqual(set(r[0] for r in self.db.execute('SELECT record_id FROM source_links')), {sid, other})
        process_batch(self.root, [])
        html = (self.root / 'report.html').read_text()
        data = json.loads(html.split('<script id="data" type="application/json">')[1].split('</script>')[0])
        self.assertEqual({r['account_key'] for r in data['rows']}, {'test-card-a', 'card-b'})

    def test_same_pdf_resend_deduplicates_only_within_account(self):
        self.second_account()
        first = self.payload(); first['source']['sha256'] = 'b' * 64
        sid = self.stage(first)['id']
        resend = copy.deepcopy(first); resend['source']['message_id'] = 'resent'
        self.assertNotEqual(self.stage(resend)['id'], sid)
        resend['account_key'] = 'card-b'
        self.assertEqual(self.stage(resend)['result'], 'staged')
        self.assertEqual(len(records(self.db)), 3)

    def test_combined_draft_sections_never_overwrite_each_other(self):
        self.second_account()
        a = self.payload(); sid = self.stage(a)['id']
        b = copy.deepcopy(a); b['account_key'] = 'card-b'; b['transactions'][0]['amount_minor'] = 15000; b['checks'] = {}
        bid = self.stage(b)['id']
        self.assertNotEqual(sid, bid)
        self.assertEqual(next(r for r in records(self.db) if r['id'] == sid)['payload']['transactions'][0]['amount_minor'], 12000)
        self.assertEqual(self.stage(b)['id'], bid)

    def test_genuine_currency_sections_keep_distinct_ids_and_source_links(self):
        p = self.payload(); p['source']['sha256'] = 'c' * 64
        first = self.stage(p, imported=True)['id']
        p['currency'] = 'USD'
        second = self.stage(p, imported=True)['id']
        self.assertNotEqual(first, second)
        self.assertEqual(self.stage(p)['id'], second)
        self.assertEqual({r['payload']['currency'] for r in records(self.db)}, {'INR', 'USD'})
        self.assertEqual(set(r[0] for r in self.db.execute('SELECT record_id FROM source_links')), {first, second})

    def test_batch_keeps_valid_sources_before_and_after_failure_and_reports_once(self):
        bad = self.alert('bad'); bad['complete'] = False
        unknown = self.payload('unknown', account='unconfirmed')
        later = self.alert('later'); later['source']['mailbox'] = 'mail-b'; later['transactions'][0]['amount_minor'] = 45000
        batch = [{'type': 'statement', 'payload': self.payload()}, {'type': 'alert', 'payload': bad},
                 {'type': 'statement', 'payload': unknown}, {'type': 'alert', 'payload': later}]
        from moneylens.dashboard import write_report
        with patch('moneylens.dashboard.write_report', wraps=write_report) as calls:
            result = process_batch(self.root, batch)
        self.assertEqual(calls.call_count, 1)
        self.assertEqual([r['result'] for r in result['outcomes']], ['imported', 'needs_review', 'needs_review', 'statement_covered'])
        self.assertEqual(records(self.db)[0]['status'], 'imported')
        self.assertEqual(self.db.execute('SELECT count(*) FROM alerts').fetchone()[0], 1)
        self.assertEqual(len(reviews(self.db)), 2)
        self.assertTrue((self.root / 'report.html').is_file())
        self.assertFalse(list(self.root.glob('tmp*.json')))

    def test_attachment_filename_fallback_keeps_each_review_and_clears_only_the_corrected_source(self):
        first=self.payload();second=self.payload()
        for payload,name in ((first,'first.pdf'),(second,'second.pdf')):
            payload['source'].pop('attachment_id')
            payload['source']['filename']=name
            payload['transactions'][0]['amount_minor']='unreadable'
        process_batch(self.root,[{'type':'statement','payload':p} for p in (first,second)],render_report=False)
        self.assertEqual({r['filename'] for r in reviews(self.db)},{'first.pdf','second.pdf'})
        first['transactions'][0]['amount_minor']=12000
        result=process_batch(self.root,[{'type':'statement','payload':first}],render_report=False)
        self.assertEqual(result['outcomes'][0]['result'],'imported')
        self.assertEqual([r['filename'] for r in reviews(self.db)],['second.pdf'])

    def test_corrected_batch_alert_clears_its_review_without_erasing_another_source(self):
        a = self.alert('a'); a['complete'] = False
        b = self.alert('b'); b['complete'] = False
        process_batch(self.root, [{'type': 'alert', 'payload': p} for p in (a, b)])
        a['complete'] = True
        process_batch(self.root, [{'type': 'alert', 'payload': a}])
        pending = reviews(self.db)
        self.assertEqual([p['message_id'] for p in pending], ['b'])

    def test_malformed_entry_is_reviewed_without_stopping_later_valid_source(self):
        bad = self.alert('malformed'); bad['transactions'] = ['invalid row']
        result = process_batch(self.root, [{'type': 'alert', 'payload': bad}, {'type': 'statement', 'payload': self.payload()}])
        self.assertEqual([r['result'] for r in result['outcomes']], ['needs_review', 'imported'])
        self.assertEqual(records(self.db)[0]['status'], 'imported')
        self.assertEqual(len(reviews(self.db)), 1)

    def test_draft_statement_and_duplicate_draft_remain_in_durable_review(self):
        p = self.payload(); p['checks']['closing_balance_minor'] += 1
        for _ in range(2): process_batch(self.root, [{'type': 'statement', 'payload': p}])
        self.assertEqual(records(self.db)[0]['status'], 'draft')
        self.assertEqual(len(reviews(self.db)), 1)

    def test_missing_pdf_password_does_not_block_healthy_imports_or_alerts(self):
        self.second_account(password='unverified')
        self.assertFalse(self.config['ready'])
        result = process_batch(self.root, [{'type': 'statement', 'payload': self.payload()}])
        self.assertEqual(result['outcomes'][0]['result'], 'imported')
        notice=self.alert('notice');notice['account_key']='card-b'
        result=process_batch(self.root,[{'type':'alert','payload':notice}])
        self.assertEqual(result['outcomes'][0]['result'], 'provisional_saved')











if __name__ == '__main__': unittest.main()
