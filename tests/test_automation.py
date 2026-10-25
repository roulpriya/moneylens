"""Daily workflow invariants, with synthetic data and no live email or system credentials."""
import copy
from coverage_fixtures import observed_statement
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from test_ledger import fixture
from moneylens.ledger import connect, stage, records, import_record
from moneylens.alerts import ingest, report_records, reconcile
from moneylens.dashboard import write_report
from moneylens.store import get, save_config




class AutomationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.data = self.root / "data"
        self.db = connect(self.data)

    def tearDown(self):
        self.db.close()
        self.temp.cleanup()

    def ingest(self, p, alert=False, ok=True):
        file=self.root/'input.json';file.write_text(json.dumps(p if alert else observed_statement(p)))
        try:
            with self.db: result=(ingest if alert else stage)(self.db,file)
        except ValueError as error:
            if ok: raise
            return {'error':str(error)}
        self.assertTrue(ok,'Expected a rejected input')
        return result

    def import_statement(self,sid):
        with self.db:return import_record(self.db,sid)

    def notifications(self):return report_records(self.db,records(self.db))

    def alert(self, message="alert-1", reference=None):
        p = fixture(message, checks={})
        p["source"]["filename"] = "email-body"
        p["source"].pop("attachment_id")
        p["transactions"] = [p["transactions"][0]]
        p["transactions"][0]["row"] = "body:1"
        if reference:
            p["transactions"][0]["reference"] = reference
        return p

    def report(self):
        out = self.root / "report.html"
        write_report(self.db,out)
        html = out.read_text()
        data = json.loads(html.split('<script id="data" type="application/json">')[1].split('</script>')[0])
        return html, data

    def configure(self, **changes):
        p = {'mailboxes': [{'id': "synthetic-test", 'address': "synthetic-test", 'verified_at': "2026-10-20T09:00:00+05:30"}], 'timezone': "Asia/Kolkata", 'report_path': str(self.root / "report.html"), 'cards': [{'account_label':'Synthetic account',"account_key": "test-card-a", "issuer": "Synthetic Bank", "masked_identifier": "1234",
                        "credential_scope": "synthetic-never-used", "password_status": "verified", "verified_at": "2026-10-20T09:00:00+05:30"}]}
        p.update(changes)
        path = self.root / "config.json"; path.write_text(json.dumps(p))
        with self.db:return save_config(self.db,p)

    def test_alert_then_statement_replaces_it_only_with_unique_shared_reference(self):
        a = self.ingest(self.alert(reference="bank-ref-001"), alert=True)
        self.assertEqual(self.notifications()[0]["status"], "provisional")
        p = fixture(); p["transactions"][0]["reference"] = "bank-ref-001"
        s = self.ingest(p)
        self.import_statement(s["id"])
        self.assertEqual(self.notifications()[0]["status"], "statement_covered")
        _, data = self.report()
        eligible = [r for r in data["rows"] if not r["blocked"] and not r["suppressed"] and r["kind"] != "payment"]
        self.assertEqual(sum(r["amount_minor"] for r in eligible), 11000)
        self.assertEqual(self.ingest(self.alert(reference="bank-ref-001"), alert=True)["result"], "already_saved")
        self.assertEqual(self.ingest(self.alert("alert-copy", reference="bank-ref-001"), alert=True)["result"], "duplicate_alert")

    def test_statement_period_discards_ambiguous_notification_without_asserting_a_match(self):
        aid = self.ingest(self.alert(), alert=True)["id"]
        payload = fixture(checks={})
        repeated = copy.deepcopy(payload['transactions'][0]); repeated['row'] = '4'
        payload['transactions'].append(repeated)
        sid = self.ingest(payload)["id"]
        self.import_statement(sid)
        self.assertEqual(self.notifications()[0]["status"], "statement_covered")
        with self.db:reconcile(self.db,aid,sid,0,'Source evidence confirms the movement')
        self.assertEqual(self.notifications()[0]["status"], "statement_covered")
        self.assertEqual(reconcile(self.db,aid,sid,0,'Same evidence')["result"], "already_reconciled")

    def test_period_precedence_does_not_require_a_merchant_name_match(self):
        self.ingest(self.alert(), alert=True)
        payload = fixture(); payload['transactions'][0]['merchant'] = 'Synthetic Grocer Variant'
        sid = self.ingest(payload)['id']; self.import_statement(sid)
        self.assertEqual(self.notifications()[0]['status'], 'statement_covered')

    def test_distinct_bank_references_preserve_identical_purchases(self):
        self.ingest(self.alert('one', reference='bank-transaction-one'), alert=True)
        self.ingest(self.alert('two', reference='bank-transaction-two'), alert=True)
        self.assertEqual([a['status'] for a in self.notifications()], ['provisional', 'provisional'])

    def test_reconciled_upi_keeps_payment_channel_on_authoritative_row(self):
        alert = self.alert(reference='unique-upi-reference')
        alert['transactions'][0].update(merchant='***@example', channel='upi')
        self.ingest(alert, alert=True)
        payload = fixture(); payload['transactions'][0].update(merchant='UPI-Example Shop', reference='unique-upi-reference')
        sid = self.ingest(payload)['id']; self.import_statement(sid)
        self.assertEqual(self.notifications()[0]['status'], 'statement_covered')
        _, data = self.report()
        authoritative = next(r for r in data['rows'] if r['statement']==sid and r['index']==0)
        self.assertEqual(authoritative['channel'], 'upi')
        self.assertEqual(sum(r['amount_minor'] for r in data['rows'] if not r['suppressed'] and not r['blocked'] and r['kind']!='payment'),11000)


    def test_report_location_update_keeps_current_inventory(self):
        self.configure()
        path=self.root/'new report.html'
        with self.db:save_config(self.db,{**get(self.db,'config'),'report_path':str(path)})
        config=get(self.db,'config')
        self.assertEqual(len(config['cards']),1)
        self.assertEqual(config['report_path'],str(path))

    def test_multiple_body_movements_have_distinct_ids(self):
        p = self.alert(); first = self.ingest(p, alert=True)
        p["transactions"][0]["row"] = "body:2"
        p["transactions"][0]["merchant"] = "Another distinct merchant"
        second = self.ingest(p, alert=True)
        self.assertNotEqual(first["id"], second["id"])
        self.assertEqual(len(self.notifications()), 2)

    def test_conflicting_alert_reference_is_held(self):
        self.ingest(self.alert(reference="same-ref"), alert=True)
        p = self.alert("conflicting", reference="same-ref")
        p["transactions"][0]["amount_minor"] += 1
        self.ingest(p, alert=True)
        self.assertEqual([r["status"] for r in self.notifications()], ["needs_review", "needs_review"])

    def test_reference_with_conflicting_dates_keeps_both_notifications_for_review(self):
        self.ingest(self.alert(reference='reused-reference'),alert=True)
        other=self.alert('another-notice',reference='reused-reference')
        other['transactions'][0]['date']='2026-09-09'
        self.assertEqual(self.ingest(other,alert=True)['result'],'provisional_saved')
        self.assertEqual([r['status'] for r in self.notifications()],['needs_review','needs_review'])

    def test_partial_alerts_are_not_added_to_spending(self):
        p = self.alert(); p["complete"] = False
        self.assertIn("requires review", self.ingest(p, alert=True, ok=False)["error"])
        self.assertEqual(self.notifications(), [])

    def test_report_updates_data_and_preserves_every_other_byte(self):
        self.ingest(self.alert(), alert=True)
        old, _ = self.report()
        # Explicit developer/UI changes must survive a daily data refresh.
        old = old.replace('Your spending, in view.', 'A fixed custom heading.')
        (self.root / "report.html").write_text(old)
        self.ingest(fixture())
        new, data = self.report()
        opening = '<script id="data" type="application/json">'
        before_old, rest_old = old.split(opening)
        before_new, rest_new = new.split(opening)
        self.assertEqual(before_old, before_new)
        self.assertEqual(rest_old.split('</script>', 1)[1], rest_new.split('</script>', 1)[1])
        self.assertEqual(len(data["statements"]), 1)
        path = self.root / "report.html"
        broken = new.replace('MONEYLENS_DATA_END', 'MISSING_DATA_END'); path.write_text(broken)
        with self.assertRaises(ValueError):write_report(self.db,path)
        self.assertEqual(path.read_text(), broken)

    def test_unverified_pdf_credentials_do_not_block_accounting_configuration(self):
        card = {'account_label':'Synthetic account','account_key': 'test-card-a', 'issuer': 'Synthetic Bank', 'masked_identifier': '1234',
                'credential_scope': 'unused', 'password_status': 'unverified'}
        self.assertFalse(self.configure(cards=[card])['ready'])
        self.assertEqual(get(self.db,'config')['cards'][0]['password_status'], 'unverified')

    def test_account_settings_reject_workflow_and_secret_fields(self):
        self.configure()
        config=get(self.db,'config')
        for field,value in [('confirmed_card_count',2),('password','synthetic-placeholder')]:
            path=self.root/'bad.json';path.write_text(json.dumps({**config,field:value}))
            with self.assertRaisesRegex(ValueError,'Unsupported'),self.db:save_config(self.db,{**config,field:value})

    def test_alert_only_account_keeps_actual_pdf_credential_status(self):
        card = {'account_label':'Synthetic account','account_key': 'test-new-card', 'issuer': 'Synthetic Bank', 'masked_identifier': '5678',
                'credential_scope': 'unused', 'password_status': 'unverified', 'alerts_only': True}
        self.assertTrue(self.configure(cards=[card])['ready'])
        self.assertEqual(get(self.db,'config')['cards'][0]['password_status'], 'unverified')
        card['alerts_only'] = False
        self.assertFalse(self.configure(cards=[card])['ready'])




if __name__ == "__main__":
    unittest.main()
