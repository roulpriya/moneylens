#!/usr/bin/env python3
"""MoneyLens deterministic staging, import, validation, and local reporting."""
import argparse
import collections
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import sys
import tempfile

DEBITS = {"purchase", "fee", "interest", "cash_advance", "adjustment_debit"}
CREDITS = {"refund", "payment", "adjustment_credit"}
KINDS = DEBITS | CREDITS | {"unknown"}
CHECKS = {"expected_transaction_count", "expected_debits_minor", "expected_credits_minor",
          "opening_balance_minor", "closing_balance_minor"}
LIMIT = 9_007_199_254_740_991


def require(condition, message):
    if not condition:
        raise ValueError(message)


def integer(value, label):
    require(type(value) is int and abs(value) <= LIMIT, label + " must be a safe integer")
    return value


def text(value, label, limit=300):
    require(isinstance(value, str) and 0 < len(value.strip()) <= limit, label + " must be nonempty text")
    return value.strip()


def date(value):
    require(isinstance(value, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", value), "Dates must be YYYY-MM-DD")
    dt.date.fromisoformat(value)
    return value


def hash_value(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()


def normalize(payload):
    require(isinstance(payload, dict), "Statement input must be an object")
    allowed = {"source", "account_key", "account_label", "issuer", "period_start", "period_end", "currency",
               "currency_exponent", "complete", "issues", "checks", "transactions", "account_resolved",
               "distinct_overlap_rows", "resolution_notes"}
    require(not (set(payload) - allowed), "Unexpected statement fields; use the documented schema")
    p = json.loads(json.dumps(payload))
    source = p.get("source")
    require(isinstance(source, dict), "source is required")
    require(not (set(source) - {"mailbox", "message_id", "attachment_id", "filename", "sha256"}), "Unexpected source fields")
    for key in ("mailbox", "message_id", "filename"):
        source[key] = text(source.get(key), "source." + key)
    if source.get("attachment_id"):
        source["attachment_id"] = text(source["attachment_id"], "attachment_id", 2000)
    if source.get("sha256"):
        require(bool(re.fullmatch(r"[a-fA-F0-9]{64}", source["sha256"])), "Invalid original PDF SHA-256")
        source["sha256"] = source["sha256"].lower()
    for key in ("account_key", "account_label", "issuer"):
        p[key] = text(p.get(key), key)
    date(p.get("period_start")); date(p.get("period_end"))
    require(p["period_start"] <= p["period_end"], "Statement period is reversed")
    require(isinstance(p.get("currency"), str) and re.fullmatch(r"[A-Z]{3}", p["currency"]), "Currency needs a three-letter code")
    exponent = integer(p.get("currency_exponent"), "currency_exponent")
    require(0 <= exponent <= 4, "Currency exponent must be between 0 and 4")
    require(type(p.get("complete")) is bool, "complete must be boolean")
    p.setdefault("account_resolved", True)
    require(type(p["account_resolved"]) is bool, "account_resolved must be boolean")
    p.setdefault("issues", [])
    require(isinstance(p["issues"], list) and all(isinstance(x, str) and x.strip() for x in p["issues"]), "issues must be text entries")
    p.setdefault("checks", {})
    require(isinstance(p["checks"], dict) and not (set(p["checks"]) - CHECKS), "Unknown validation checks")
    for key, value in p["checks"].items():
        integer(value, key)
        if key.startswith("expected_"):
            require(value >= 0, key + " must be nonnegative")
    require(("opening_balance_minor" in p["checks"]) == ("closing_balance_minor" in p["checks"]), "Balance reconciliation needs both opening and closing balances")
    require(isinstance(p.get("transactions"), list) and len(p["transactions"]) <= 20000, "transactions must be a list of at most 20000 rows")
    for index, row in enumerate(p["transactions"]):
        require(isinstance(row, dict), "Each transaction must be an object")
        require(not (set(row) - {"date", "merchant", "amount_minor", "kind", "category", "page", "row", "reference"}), "Unexpected transaction fields")
        date(row.get("date"))
        row["merchant"] = text(row.get("merchant"), "merchant", 500)
        amount = integer(row.get("amount_minor"), "amount_minor")
        require(row.get("kind") in KINDS, "Unknown transaction kind")
        require(row["kind"] not in DEBITS or amount >= 0, "Debit amounts cannot be negative")
        require(row["kind"] not in CREDITS or amount <= 0, "Credit amounts cannot be positive")
        row["category"] = text(row.get("category"), "category", 80)
        if row["kind"] == "payment":
            row["category"] = "Credit card payments"
        require(integer(row.get("page"), "page") > 0, "Page must be positive")
        row["row"] = text(row.get("row"), "row reference", 100)
        if row.get("reference"):
            row["reference"] = text(row["reference"], "bank transaction reference", 200)
    locations = [(r["page"], r["row"]) for r in p["transactions"]]
    require(len(set(locations)) == len(locations), "A source page/row location was extracted more than once")
    distinct = p.setdefault("distinct_overlap_rows", [])
    require(isinstance(distinct, list) and all(type(i) is int and 0 <= i < len(p["transactions"]) for i in distinct), "Invalid distinct-overlap row indices")
    if "resolution_notes" in p:
        p["resolution_notes"] = text(p["resolution_notes"], "resolution_notes", 3000)
    require(not distinct or bool(p.get("resolution_notes")), "Distinct-overlap resolutions need evidence notes")
    # Aggregate arithmetic must remain exact in the browser, too.
    require(sum(abs(r["amount_minor"]) for r in p["transactions"]) <= LIMIT, "Statement total exceeds supported integer range")
    return p


def row_key(row):
    return (row["date"], " ".join(row["merchant"].casefold().split()), row["amount_minor"], row["kind"])


def semantic_key(p):
    return hash_value([p["account_key"], p["period_start"], p["period_end"], p["currency"], p["currency_exponent"],
                       sorted(row_key(r) for r in p["transactions"])])


def source_id(p):
    s = p["source"]
    return hash_value([s["mailbox"], s["message_id"], s.get("attachment_id") or s["filename"]])[:24]


def records(db):
    return [{"id": row[0], "status": row[1], "payload": json.loads(row[2])}
            for row in db.execute("SELECT id,status,payload FROM statements ORDER BY created,id")]


def assessment(record, all_records):
    p = record["payload"]
    issues = list(p["issues"])
    if not p["complete"]:
        issues.append("Extraction incomplete")
    if not p["account_resolved"]:
        issues.append("Account identity unresolved")
    if not p["transactions"]:
        issues.append("No transaction rows")
    if any(r["kind"] == "unknown" for r in p["transactions"]):
        issues.append("Unknown transaction movement type")
    rows, checks = p["transactions"], p["checks"]
    actual = {"expected_transaction_count": len(rows),
              "expected_debits_minor": sum(max(r["amount_minor"], 0) for r in rows),
              "expected_credits_minor": -sum(min(r["amount_minor"], 0) for r in rows)}
    passed = []
    for key, value in actual.items():
        if key in checks:
            if value != checks[key]:
                issues.append(f"{key} mismatch: extracted {value}, source {checks[key]}")
            else:
                passed.append(key)
    if "opening_balance_minor" in checks:
        closing = checks["opening_balance_minor"] + sum(r["amount_minor"] for r in rows)
        if closing != checks["closing_balance_minor"]:
            issues.append(f"Balance mismatch: calculated {closing}, source {checks['closing_balance_minor']}")
        else:
            passed.append("balance_reconciliation")
    if record["status"] == "draft":
        peers = set()
        for other in all_records:
            q = other["payload"]
            if other["id"] != record["id"] and q["account_key"] == p["account_key"] and q["currency"] == p["currency"]:
                peers.update(row_key(r) for r in q["transactions"])
        overlaps = [i for i, r in enumerate(rows) if row_key(r) in peers and i not in p["distinct_overlap_rows"]]
        if overlaps:
            issues.append("Potential cross-statement overlap at zero-based rows: " + ",".join(map(str, overlaps)))
    return {"issues": list(dict.fromkeys(issues)), "passed_checks": passed,
            "unavailable_checks": sorted(CHECKS - set(checks))}


def connect(data_dir):
    os.umask(0o077)
    data_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    path = data_dir / "ledger.sqlite3"
    db = sqlite3.connect(path, timeout=20)
    os.chmod(path, 0o600)
    db.execute("CREATE TABLE IF NOT EXISTS statements (id TEXT PRIMARY KEY, status TEXT NOT NULL CHECK(status IN ('draft','imported')), payload TEXT NOT NULL, created TEXT NOT NULL)")
    db.execute("CREATE TABLE IF NOT EXISTS category_edits (statement_id TEXT NOT NULL, evidence_key TEXT NOT NULL, category TEXT NOT NULL, PRIMARY KEY(statement_id,evidence_key))")
    db.execute("CREATE TABLE IF NOT EXISTS alerts (id TEXT PRIMARY KEY, payload TEXT NOT NULL, created TEXT NOT NULL)")
    db.execute("CREATE TABLE IF NOT EXISTS alert_matches (alert_id TEXT PRIMARY KEY, statement_id TEXT NOT NULL, row_index INTEGER NOT NULL, evidence TEXT NOT NULL, UNIQUE(statement_id,row_index))")
    db.execute("CREATE TABLE IF NOT EXISTS runtime_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
    db.execute("CREATE TABLE IF NOT EXISTS retry_sources (source_key TEXT PRIMARY KEY, payload TEXT NOT NULL)")
    db.commit()
    return db


def find(all_records, statement_id):
    match = next((r for r in all_records if r["id"] == statement_id), None)
    require(match is not None, "Statement ID not found")
    return match


def save(db, record):
    db.execute("UPDATE statements SET status=?,payload=? WHERE id=?",
               (record["status"], json.dumps(record["payload"], ensure_ascii=False), record["id"]))


def stage(db, path):
    require(path.stat().st_size <= 20 * 1024 * 1024, "Staging JSON exceeds 20 MiB")
    p = normalize(json.loads(path.read_text()))
    sid = source_id(p)
    all_records = records(db)
    for (raw,) in db.execute("SELECT payload FROM alerts"):
        q = json.loads(raw)
        require(p["currency"] != q["currency"] or p["currency_exponent"] == q["currency_exponent"], "Currency exponent conflicts with existing alerts")
    for r in all_records:
        q = r["payload"]
        require(p["currency"] != q["currency"] or p["currency_exponent"] == q["currency_exponent"], "Currency exponent conflicts with existing records")
        if r["id"] == sid:
            if r["status"] == "imported":
                return {"result": "already_imported", "id": sid}
            continue
        same_bytes = p["source"].get("sha256") and p["source"].get("sha256") == q["source"].get("sha256") and p["source"]["mailbox"] == q["source"]["mailbox"]
        if same_bytes or semantic_key(p) == semantic_key(q):
            return {"result": "duplicate", "id": r["id"], "status": r["status"]}
    record = {"id": sid, "status": "draft", "payload": p}
    previous = next((r for r in all_records if r["id"] == sid), None)
    if previous:
        # Preserve existing review edits for unchanged evidence rows.
        edits = dict(db.execute("SELECT evidence_key,category FROM category_edits WHERE statement_id=?", (sid,)))
        for row in p["transactions"]:
            evidence_key = hash_value([row_key(row), row["page"], row["row"]])
            if evidence_key in edits:
                row["category"] = edits[evidence_key]
        save(db, record)
    else:
        db.execute("INSERT INTO statements VALUES (?,?,?,?)", (sid, "draft", json.dumps(p, ensure_ascii=False), dt.datetime.now(dt.timezone.utc).isoformat()))
    updated = [r for r in all_records if r["id"] != sid] + [record]
    return {"result": "staged", "id": sid, **assessment(record, updated)}


def default_dir():
    if sys.platform == "darwin":
        return Path.home() / "Library/Application Support/MoneyLensCodex"
    return Path(os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local/share"))) / "moneylens-codex"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=default_dir())
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("stage", help="Persist a draft; never import")
    p.add_argument("--input", type=Path, required=True)
    p = sub.add_parser("alert", help="Save one validated transaction-alert email as provisional")
    p.add_argument("--input", type=Path, required=True)
    p = sub.add_parser("reconcile", help="Link an alert to an authoritative statement row using evidence")
    p.add_argument("--alert", required=True)
    p.add_argument("--statement", required=True)
    p.add_argument("--row", type=int, required=True)
    p.add_argument("--evidence", required=True)
    sub.add_parser("list")
    sub.add_parser("list-alerts")
    for name in ("import", "discard", "categorize"):
        p = sub.add_parser(name)
        p.add_argument("--statement", required=True)
        if name == "categorize":
            p.add_argument("--row", type=int, required=True)
            p.add_argument("--category", required=True)
    p = sub.add_parser("report")
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--from-date", type=date)
    p.add_argument("--to-date", type=date)
    args = parser.parse_args()
    db = connect(args.data_dir)
    try:
        # Lock the read/assess/write sequence to avoid concurrent duplicate imports.
        db.execute("BEGIN IMMEDIATE")
        if args.command == "stage":
            result = stage(db, args.input)
        elif args.command == "alert":
            from alerts import ingest
            result = ingest(db, args.input)
        elif args.command == "reconcile":
            from alerts import reconcile
            result = reconcile(db, args.alert, args.statement, args.row, args.evidence)
        else:
            all_records = records(db)
            if args.command == "list":
                result = [{"id": r["id"], "status": r["status"], "account": r["payload"]["account_label"], "account_key": r["payload"]["account_key"],
                           "period": [r["payload"]["period_start"], r["payload"]["period_end"]],
                           "currency": r["payload"]["currency"], "rows": len(r["payload"]["transactions"]),
                           **assessment(r, all_records)} for r in all_records]
            elif args.command == "list-alerts":
                from alerts import report_records
                result = [{"id": r["id"], "status": r["status"], "account": r["payload"]["account_label"],
                           "source": r["payload"]["source"], "transaction": r["payload"]["transactions"][0],
                           **r["validation"]} for r in report_records(db, all_records)]
            elif args.command == "report":
                from dashboard import render
                require(not (args.from_date and args.to_date) or args.from_date <= args.to_date, "Report date range reversed")
                enriched = [{**r, "validation": assessment(r, all_records)} for r in all_records]
                from alerts import report_records
                enriched.extend(report_records(db, all_records))
                require(args.output.suffix.lower() == ".html", "Report output must end in .html")
                args.output.parent.mkdir(parents=True, exist_ok=True)
                meta = {key: json.loads(value) for key, value in db.execute("SELECT key,value FROM runtime_meta")}
                retry = [json.loads(r[0]) for r in db.execute("SELECT payload FROM retry_sources")]
                sync = {"last_success": meta.get("last_success"), "last_run": meta.get("last_run"),
                        "cards": len(meta.get("config", {}).get("cards", [])), "pending_sources": retry,
                        "timezone": meta.get("config", {}).get("timezone")}
                page = render(enriched, args.from_date, args.to_date, existing=args.output.read_text() if args.output.exists() else None, sync=sync)
                with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=args.output.parent, delete=False) as f:
                    temp_path = Path(f.name)
                    f.write(page)
                try:
                    os.replace(temp_path, args.output)
                    os.chmod(args.output, 0o600)
                finally:
                    temp_path.unlink(missing_ok=True)
                result = {"result": "report_created", "output": str(args.output.resolve()), "statements": len(enriched)}
            else:
                record = find(all_records, args.statement)
                if args.command == "import":
                    if record["status"] == "imported":
                        result = {"result": "already_imported", "id": record["id"]}
                    else:
                        checked = assessment(record, all_records)
                        require(not checked["issues"], "Import blocked: " + "; ".join(checked["issues"]))
                        record["status"] = "imported"
                        save(db, record)
                        result = {"result": "imported", "id": record["id"]}
                elif args.command == "discard":
                    require(record["status"] == "draft", "Only drafts may be discarded")
                    db.execute("DELETE FROM statements WHERE id=?", (record["id"],))
                    db.execute("DELETE FROM category_edits WHERE statement_id=?", (record["id"],))
                    result = {"result": "discarded", "id": record["id"]}
                else:
                    rows = record["payload"]["transactions"]
                    require(0 <= args.row < len(rows), "Row index out of bounds")
                    require(rows[args.row]["kind"] != "payment" or args.category == "Credit card payments", "Payments retain their accounting category")
                    rows[args.row]["category"] = text(args.category, "category", 80)
                    evidence_key = hash_value([row_key(rows[args.row]), rows[args.row]["page"], rows[args.row]["row"]])
                    db.execute("INSERT OR REPLACE INTO category_edits VALUES (?,?,?)", (record["id"], evidence_key, rows[args.row]["category"]))
                    save(db, record)
                    result = {"result": "category_updated", "id": record["id"], "row": args.row}
        db.commit()
        print(json.dumps(result, ensure_ascii=False))
    finally:
        db.close()


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError, sqlite3.Error, KeyError, TypeError) as exc:
        # Never dump input payloads, which may contain private data.
        print(json.dumps({"error": str(exc)}), file=sys.stderr)
        sys.exit(1)
