"""Daily workflow invariants, with synthetic data and no Gmail/Keychain access."""
import copy
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from test_ledger import fixture, SCRIPT

RUNTIME = SCRIPT.with_name("runtime_state.py")


class AutomationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.data = self.root / "data"

    def tearDown(self):
        self.temp.cleanup()

    def cli(self, *args, runtime=False, ok=True):
        result = subprocess.run([sys.executable, str(RUNTIME if runtime else SCRIPT), "--data-dir", str(self.data), *args], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0 if ok else 1, result.stderr)
        return json.loads(result.stdout if ok else result.stderr)

    def ingest(self, p, alert=False, ok=True):
        file = self.root / "input.json"
        file.write_text(json.dumps(p))
        return self.cli("alert" if alert else "stage", "--input", str(file), ok=ok)

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
        self.cli("report", "--output", str(out))
        html = out.read_text()
        data = json.loads(html.split('<script id="data" type="application/json">')[1].split('</script>')[0])
        return html, data

    def configure(self, **changes):
        p = {"mailbox": "synthetic-test", "gmail_verified_at": "2026-10-20T09:00:00+05:30",
             "initial_start": "2026-07-20", "timezone": "Asia/Kolkata", "daily_time": "09:00",
             "confirmed_card_count": 1, "auto_save_validated": True, "report_path": str(self.root / "report.html"),
             "cards": [{"account_key": "test-card-a", "issuer": "Synthetic Bank", "last4": "1234",
                        "keychain_scope": "synthetic-never-used", "password_status": "verified", "verified_at": "2026-10-20T09:00:00+05:30"}]}
        p.update(changes)
        path = self.root / "config.json"; path.write_text(json.dumps(p))
        return self.cli("configure", "--input", str(path), runtime=True)

    def test_alert_then_statement_replaces_it_only_with_unique_shared_reference(self):
        a = self.ingest(self.alert(reference="bank-ref-001"), alert=True)
        self.assertEqual(self.cli("list-alerts")[0]["status"], "provisional")
        p = fixture(); p["transactions"][0]["reference"] = "bank-ref-001"
        s = self.ingest(p)
        self.cli("import", "--statement", s["id"])
        self.assertEqual(self.cli("list-alerts")[0]["status"], "matched")
        _, data = self.report()
        eligible = [r for r in data["rows"] if not r["blocked"] and not r["suppressed"] and r["kind"] != "payment"]
        self.assertEqual(sum(r["amount_minor"] for r in eligible), 11000)
        self.assertEqual(self.ingest(self.alert(reference="bank-ref-001"), alert=True)["result"], "already_saved")
        self.assertEqual(self.ingest(self.alert("alert-copy", reference="bank-ref-001"), alert=True)["result"], "duplicate_alert")

    def test_no_reference_similarity_is_held_instead_of_double_counted(self):
        aid = self.ingest(self.alert(), alert=True)["id"]
        payload = fixture(checks={})
        repeated = copy.deepcopy(payload['transactions'][0]); repeated['row'] = '4'
        payload['transactions'].append(repeated)
        sid = self.ingest(payload)["id"]
        self.cli("import", "--statement", sid)
        self.assertEqual(self.cli("list-alerts")[0]["status"], "needs_review")
        self.cli("reconcile", "--alert", aid, "--statement", sid, "--row", "0", "--evidence", "Synthetic fixture evidence confirms the same movement")
        self.assertEqual(self.cli("list-alerts")[0]["status"], "matched")
        self.assertEqual(self.cli("reconcile", "--alert", aid, "--statement", sid, "--row", "0", "--evidence", "Same evidence")["result"], "already_reconciled")

    def test_unique_merchant_date_amount_match_does_not_need_opaque_reference(self):
        self.ingest(self.alert(), alert=True)
        payload = fixture(); payload['transactions'][0]['merchant'] = 'Synthetic Grocer Bangalore'
        sid = self.ingest(payload)['id']; self.cli('import', '--statement', sid)
        self.assertEqual(self.cli('list-alerts')[0]['status'], 'matched')

    def test_distinct_bank_references_preserve_identical_purchases(self):
        self.ingest(self.alert('one', reference='bank-transaction-one'), alert=True)
        self.ingest(self.alert('two', reference='bank-transaction-two'), alert=True)
        self.assertEqual([a['status'] for a in self.cli('list-alerts')], ['provisional', 'provisional'])

    def test_reconciled_upi_keeps_payment_channel_on_authoritative_row(self):
        alert = self.alert(reference='unique-upi-reference')
        alert['transactions'][0].update(merchant='***@example', channel='upi')
        self.ingest(alert, alert=True)
        payload = fixture(); payload['transactions'][0]['merchant'] = 'UPI-Example Shop'
        sid = self.ingest(payload)['id']; self.cli('import', '--statement', sid)
        self.assertEqual(self.cli('list-alerts')[0]['status'], 'matched')
        _, data = self.report()
        authoritative = next(r for r in data['rows'] if r['statement']==sid and r['index']==0)
        self.assertEqual(authoritative['channel'], 'upi')
        self.assertEqual(sum(r['amount_minor'] for r in data['rows'] if not r['suppressed'] and not r['blocked'] and r['kind']!='payment'),11000)

    def test_report_template_migration_preserves_old_report_backup(self):
        path = self.root / 'report.html'
        old = '<meta name="moneylens-template-version" content="2">Old report'
        path.write_text(old)
        self.cli('report', '--output', str(path), ok=False)
        self.cli('report', '--output', str(path), '--upgrade-template')
        backups = list(self.root.glob('report.before-upgrade-*.html'))
        self.assertEqual(len(backups), 1)
        self.assertEqual(backups[0].read_text(), old)
        self.assertIn('moneylens-template-version" content="3"', path.read_text())

    def test_report_location_update_preserves_schedule_and_inventory(self):
        self.configure(); self.cli('set-automation', '--id', 'existing-daily-job', runtime=True)
        path = self.root / 'Documents/MoneyLens/report.html'
        self.cli('set-report', '--path', str(path), runtime=True)
        config = self.cli('status', runtime=True)['config']
        self.assertEqual(config['automation_id'], 'existing-daily-job')
        self.assertEqual(config['confirmed_card_count'], 1)
        self.assertEqual(config['report_path'], str(path))

    def test_multiple_body_movements_have_distinct_ids(self):
        p = self.alert(); first = self.ingest(p, alert=True)
        p["transactions"][0]["row"] = "body:2"
        p["transactions"][0]["merchant"] = "Another distinct merchant"
        second = self.ingest(p, alert=True)
        self.assertNotEqual(first["id"], second["id"])
        self.assertEqual(len(self.cli("list-alerts")), 2)

    def test_conflicting_alert_reference_is_held(self):
        self.ingest(self.alert(reference="same-ref"), alert=True)
        p = self.alert("conflicting", reference="same-ref")
        p["transactions"][0]["amount_minor"] += 1
        self.ingest(p, alert=True)
        self.assertEqual([r["status"] for r in self.cli("list-alerts")], ["needs_review", "needs_review"])

    def test_partial_alerts_are_not_added_to_spending(self):
        p = self.alert(); p["complete"] = False
        self.assertIn("requires review", self.ingest(p, alert=True, ok=False)["error"])
        self.assertEqual(self.cli("list-alerts"), [])

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
        self.assertEqual(len(data["statements"]), 2)
        path = self.root / "report.html"
        broken = new.replace('MONEYLENS_DATA_END', 'MISSING_DATA_END'); path.write_text(broken)
        self.cli("report", "--output", str(path), ok=False)
        self.assertEqual(path.read_text(), broken)

    def test_unconfigured_sync_and_unverified_passwords_cannot_start(self):
        self.cli("begin-run", runtime=True, ok=False)
        card = {"account_key": "test-card-a", "issuer": "Synthetic Bank", "last4": "1234", "keychain_scope": "unused", "password_status": "unverified"}
        self.assertFalse(self.configure(cards=[card])["ready"])
        self.cli("begin-run", runtime=True, ok=False)

    def test_config_rejects_unconfirmed_count_and_password_fields(self):
        self.configure()
        config = self.cli("status", runtime=True)["config"]
        config.pop("ready"); config["confirmed_card_count"] = 2
        path = self.root / "bad.json"; path.write_text(json.dumps(config))
        self.cli("configure", "--input", str(path), runtime=True, ok=False)
        config["confirmed_card_count"] = 1; config["password"] = "synthetic-placeholder"
        path.write_text(json.dumps(config))
        self.assertIn("Unexpected setup fields", self.cli("configure", "--input", str(path), runtime=True, ok=False)["error"])

    def test_explicit_alert_only_card_can_sync_without_claiming_pdf_verification(self):
        card = {"account_key": "test-new-card", "issuer": "Synthetic Bank", "last4": "5678",
                "keychain_scope": "unused", "password_status": "unverified", "alerts_only": True}
        self.assertTrue(self.configure(cards=[card])["ready"])
        run = self.cli("begin-run", runtime=True)
        self.assertEqual(run["config"]["confirmed_card_count"], 1)
        self.assertEqual(run["config"]["cards"][0]["password_status"], "unverified")
        self.cli("finish-run", "--run-id", run["run"]["id"], "--search-complete", runtime=True)
        card["alerts_only"] = False
        self.assertFalse(self.configure(cards=[card])["ready"])
        self.cli("begin-run", runtime=True, ok=False)

    def test_failed_scan_keeps_cursor_and_durable_retries(self):
        self.configure()
        started = self.cli("begin-run", runtime=True)
        self.assertEqual(started["search_from"], "2026-07-20")
        self.cli("begin-run", runtime=True, ok=False)
        self.cli("retry-add", "--message", "synthetic-unreadable", "--reason", "Saved password requires setup", runtime=True)
        result = self.cli("finish-run", "--run-id", started["run"]["id"], "--error", "Synthetic pagination failure", runtime=True)
        self.assertFalse(result["cursor_advanced"])
        next_run = self.cli("begin-run", runtime=True)
        self.assertEqual(next_run["search_from"], "2026-07-20")
        self.assertEqual(len(next_run["retry_sources"]), 1)
        self.cli("finish-run", "--run-id", next_run["run"]["id"], "--search-complete", runtime=True)
        state = self.cli("status", runtime=True)
        self.assertEqual(state["last_success"], next_run["run"]["started_at"])
        self.assertEqual(len(state["retry_sources"]), 1)

    def test_schedule_id_is_retained_on_setup_repair(self):
        self.configure()
        self.cli("set-automation", "--id", "synthetic-automation-id", runtime=True)
        self.configure(daily_time="10:30")
        self.assertEqual(self.cli("status", runtime=True)["config"]["automation_id"], "synthetic-automation-id")


if __name__ == "__main__":
    unittest.main()
