"""Synthetic, isolated behavioral checks; never Gmail or the real Keychain."""
import copy
import importlib.util
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "moneylens-automation/scripts/ledger.py"
SPEC = importlib.util.spec_from_file_location("dashboard", SCRIPT.with_name("dashboard.py"))
DASH = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(DASH)


def fixture(message="msg-1", **overrides):
    p = {"source": {"mailbox": "synthetic-test", "message_id": message, "attachment_id": "pdf-part", "filename": "synthetic.pdf"},
         "account_key": "test-card-a", "account_label": "Synthetic Bank · 1234", "issuer": "Synthetic Bank",
         "period_start": "2026-09-01", "period_end": "2026-09-30", "currency": "INR", "currency_exponent": 2,
         "complete": True, "issues": [],
         "checks": {"expected_transaction_count": 3, "expected_debits_minor": 12000, "expected_credits_minor": 6000,
                    "opening_balance_minor": 10000, "closing_balance_minor": 16000},
         "transactions": [
             {"date": "2026-09-08", "merchant": "Synthetic Grocer", "amount_minor": 12000, "kind": "purchase", "category": "Groceries", "page": 1, "row": "1"},
             {"date": "2026-09-10", "merchant": "Synthetic refund", "amount_minor": -1000, "kind": "refund", "category": "Groceries", "page": 1, "row": "2"},
             {"date": "2026-09-15", "merchant": "Payment received", "amount_minor": -5000, "kind": "payment", "category": "Other", "page": 1, "row": "3"}]}
    p.update(overrides)
    return p


class LedgerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.data = self.root / "data"

    def tearDown(self):
        self.temp.cleanup()

    def cli(self, *args, ok=True):
        result = subprocess.run([sys.executable, str(SCRIPT), "--data-dir", str(self.data), *args], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0 if ok else 1, result.stderr)
        return json.loads(result.stdout if ok else result.stderr)

    def stage(self, p, **kwargs):
        file = self.root / "input.json"
        file.write_text(json.dumps(p))
        return self.cli("stage", "--input", str(file), **kwargs)

    def payload(self, sid):
        db = sqlite3.connect(self.data / "ledger.sqlite3")
        try:
            return json.loads(db.execute("SELECT payload FROM statements WHERE id=?", (sid,)).fetchone()[0])
        finally:
            db.close()

    def test_stage_requires_separate_import_and_survives_restart(self):
        result = self.stage(fixture()); sid = result["id"]
        self.assertEqual(result["issues"], [])
        self.assertEqual(len(result["passed_checks"]), 4)
        self.assertEqual(self.cli("list")[0]["status"], "draft")
        self.assertEqual(self.cli("import", "--statement", sid)["result"], "imported")
        self.assertEqual(self.cli("import", "--statement", sid)["result"], "already_imported")
        self.assertEqual(self.stage(fixture())["result"], "already_imported")
        self.assertIn("Only drafts", self.cli("discard", "--statement", sid, ok=False)["error"])
        self.assertEqual((self.data / "ledger.sqlite3").stat().st_mode & 0o777, 0o600)

    def test_duplicate_multisets_ignore_row_order_but_preserve_multiplicity(self):
        first = self.stage(fixture())
        p = fixture("msg-2"); p["transactions"].reverse()
        self.assertEqual(self.stage(p)["id"], first["id"])
        repeated=copy.deepcopy(p["transactions"][0]); repeated["row"]="4"
        p["transactions"].append(repeated); p["checks"] = {}
        result = self.stage(p)
        self.assertEqual(result["result"], "staged")
        self.assertTrue(any("overlap" in issue for issue in result["issues"]))

    def test_cross_statement_overlap_is_not_silently_removed(self):
        self.stage(fixture())
        p = fixture("msg-2", period_end="2026-10-05", checks={})
        result = self.stage(p); sid = result["id"]
        self.assertEqual(len(self.payload(sid)["transactions"]), 3)
        self.assertIn("overlap", self.cli("import", "--statement", sid, ok=False)["error"])
        p["distinct_overlap_rows"] = [0, 1, 2]
        p["resolution_notes"] = "Synthetic user confirms all three are distinct movements."
        self.stage(p)
        self.assertEqual(self.cli("import", "--statement", sid)["result"], "imported")

    def test_mismatched_totals_unknown_rows_and_incomplete_extraction_block(self):
        p = fixture(complete=False)
        p["checks"]["closing_balance_minor"] += 1
        p["transactions"][0]["kind"] = "unknown"
        result = self.stage(p)
        self.assertGreaterEqual(len(result["issues"]), 3)
        self.assertIn("Import blocked", self.cli("import", "--statement", result["id"], ok=False)["error"])

    def test_source_hash_duplicate_and_currency_isolation(self):
        p = fixture(); p["source"]["sha256"] = "a" * 64
        self.stage(p)
        q = fixture("msg-2"); q["source"]["sha256"] = "a" * 64
        q["transactions"][0]["merchant"] = "Different extraction"
        self.assertEqual(self.stage(q)["result"], "duplicate")
        q = fixture("msg-3", account_key="test-usd", currency="USD")
        self.assertEqual(self.stage(q)["issues"], [])
        self.assertEqual(len(self.cli("list")), 2)
        q = fixture("msg-4", currency_exponent=0)
        self.assertIn("exponent conflicts", self.stage(q, ok=False)["error"])

    def test_category_edit_survives_restage_and_payment_stays_excluded(self):
        p = fixture(); sid = self.stage(p)["id"]
        self.cli("categorize", "--statement", sid, "--row", "0", "--category", "Dining")
        p["transactions"][0]["category"] = "Other"
        self.stage(p)
        self.assertEqual(self.payload(sid)["transactions"][0]["category"], "Dining")
        self.assertEqual(self.payload(sid)["transactions"][2]["category"], "Credit card payments")
        self.cli("categorize", "--statement", sid, "--row", "2", "--category", "Dining", ok=False)

    def test_invalid_dates_fractional_minor_units_and_wrong_signs_fail(self):
        for key, value in [("date", "2026-02-30"), ("amount_minor", 2.5), ("amount_minor", -100)]:
            with self.subTest(key=key, value=value):
                p = fixture(); p["transactions"][0][key] = value
                self.stage(p, ok=False)
        self.assertEqual(self.cli("list"), [])

    def test_repeated_source_location_is_rejected_but_distinct_rows_are_kept(self):
        p = fixture(checks={})
        repeated = copy.deepcopy(p["transactions"][0])
        p["transactions"].append(repeated)
        self.assertIn("extracted more than once", self.stage(p, ok=False)["error"])
        p["transactions"][-1]["row"] = "4"
        sid = self.stage(p)["id"]
        self.assertEqual(len(self.payload(sid)["transactions"]), 4)

    def test_report_escapes_untrusted_source_and_does_not_import(self):
        p = fixture(); p["transactions"][0]["merchant"] = '</script><img src=x onerror="alert(1)">'
        self.stage(p)
        output = self.root / "dashboard.html"
        self.cli("report", "--output", str(output), "--from-date", "2026-09-01", "--to-date", "2026-09-30")
        html = output.read_text()
        self.assertNotIn(p["transactions"][0]["merchant"], html)
        self.assertIn("\\u003c/script", html)
        self.assertIn("connect-src 'none'", html)
        self.assertEqual(self.cli("list")[0]["status"], "draft")
        self.cli("report", "--output", str(output), "--from-date", "2026-10-01", "--to-date", "2026-09-01", ok=False)

    def test_missing_checks_are_disclosed_and_user_can_import(self):
        p = fixture(checks={}); sid = self.stage(p)["id"]
        record = self.cli("list")[0]
        self.assertEqual(record["passed_checks"], [])
        self.assertEqual(len(record["unavailable_checks"]), 5)
        self.cli("import", "--statement", sid)

    def test_empty_report_and_discard_draft(self):
        self.cli("report", "--output", str(self.root / "empty.html"))
        sid = self.stage(fixture())["id"]
        self.cli("discard", "--statement", sid)
        self.assertEqual(self.cli("list"), [])


if __name__ == "__main__":
    unittest.main()
