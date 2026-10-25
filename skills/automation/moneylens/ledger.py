#!/usr/bin/env python3
"""MoneyLens deterministic staging, import, validation, and local reporting."""
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
from .private_files import protect

DEBITS = {"purchase", "fee", "interest", "cash_advance", "adjustment_debit", "debit", "repayment", "transfer_out"}
CREDITS = {"refund", "payment", "adjustment_credit", "credit", "transfer_in"}
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


def category_name(value):
    return text(value, 'category', 80)


def normalize(payload):
    require(isinstance(payload, dict), "Statement input must be an object")
    allowed = {"source", "account_key", "account_label", "issuer", "period_start", "period_end", "currency",
               "currency_exponent", "complete", "issues", "checks", "transactions", "account_resolved",
               "distinct_overlap_rows", "resolution_notes", "account_type", "coverage", "review_rows"}
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
    for key in ("account_key", "account_label"):
        p[key] = text(p.get(key), key)
    if p.get("issuer") is not None: p["issuer"] = text(p["issuer"], "issuer")
    require("account_type" in p, "account_type is required")
    require(p["account_type"] in {"credit_card", "bank_account", "manual"}, "Invalid account type")
    date(p.get("period_start")); date(p.get("period_end"))
    require(p["period_start"] <= p["period_end"], "Statement period is reversed")
    p["currency"] = text(p.get("currency"), "currency", 32)
    exponent = integer(p.get("currency_exponent"), "currency_exponent")
    require(0 <= exponent <= 18, "Currency exponent must be between 0 and 18")
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
        require(not (set(row) - {"date", "merchant", "amount_minor", "kind", "category", "page", "row", "reference", "channel", "own_account_key", "transfer_evidence", "source_row_id", "review_reason", "duplicate_of", "metadata"}), "Unexpected transaction fields")
        date(row.get("date"))
        row["merchant"] = text(row.get("merchant"), "merchant", 500)
        amount = integer(row.get("amount_minor"), "amount_minor")
        require(row.get("kind") in KINDS, "Unknown transaction kind")
        row.setdefault("channel", None)
        if row["channel"] is not None: row["channel"] = text(row["channel"], "channel", 120)
        require(row["kind"] not in DEBITS or amount >= 0, "Debit amounts cannot be negative")
        require(row["kind"] not in CREDITS or amount <= 0, "Credit amounts cannot be positive")
        if 'metadata' in row:
            require(isinstance(row['metadata'], dict), 'Transaction metadata must be an object')
            require(len(json.dumps(row['metadata'], allow_nan=False).encode('utf-8')) <= 65536, 'Transaction metadata exceeds 64 KiB')
            for field,limit in (('display_description',500),('display_note',2000),('merchant',500)):
                if row['metadata'].get(field) is not None: text(row['metadata'][field],field,limit)
        row["category"] = category_name(text(row.get("category"), "category", 80))
        require(integer(row.get("page"), "page") > 0, "Page must be positive")
        row["row"] = text(row.get("row"), "row reference", 100)
        for key in ('own_account_key', 'transfer_evidence', 'source_row_id', 'review_reason'):
            if key in row: row[key] = text(row[key], key, 1000)
        if row.get("reference"):
            row["reference"] = text(row["reference"], "bank transaction reference", 200)
    for row in p['transactions']:
        if row['kind'] == 'unknown' and not row.get('review_reason'): row['review_reason'] = 'Unknown transaction movement type'
        if row.get('duplicate_of') is not None:
            link = row['duplicate_of']
            require(isinstance(link, dict) and set(link) == {'statement', 'index', 'evidence'}, 'Invalid duplicate link')
            text(link['statement'], 'duplicate statement'); text(link['evidence'], 'duplicate evidence', 2000)
            require(type(link['index']) is int and link['index'] >= 0, 'Invalid duplicate target index')
            require(not row.get('review_reason') and row['kind'] != 'unknown', 'Duplicate and review outcomes must be disjoint')
    review = p.setdefault('review_rows', [])
    require(isinstance(review, list) and len(review) <= 20000, 'Invalid review rows')
    for row in review:
        require(isinstance(row, dict) and {'source_row_id', 'page', 'row', 'reason'} <= set(row) and not set(row) - {'source_row_id', 'page', 'row', 'reason', 'date', 'amount_minor'}, 'Invalid visible review row')
        for key in ('source_row_id', 'row', 'reason'): text(row[key], key, 1000)
        require(integer(row['page'], 'review page') > 0, 'Invalid review page')
        if 'date' in row: date(row['date'])
        if 'amount_minor' in row: integer(row['amount_minor'], 'review amount')
    from .statement_coverage import normalize_coverage
    normalize_coverage(p)
    if p.get('coverage'):
        section = next(s for s in p['coverage']['sections'] if s['id'] == p['coverage']['section_id'])
        mapped_ids = {r.get('source_row_id') for r in p['transactions'] + review}
        for observed in section['rows']:
            if observed['id'] not in mapped_ids:
                # Preserve an identified occurrence even if extraction omitted it.
                # The missing extraction remains an explicit completeness gap.
                review.append({'source_row_id': observed['id'], 'page': observed['page'], 'row': observed['row'],
                               'reason': 'Source inventory row has no extraction mapping',
                               **({'amount_minor': observed['amount_minor']} if 'amount_minor' in observed else {})})
    locations = [(r["page"], r["row"]) for r in p["transactions"] + review]
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
    return hash_value([s["mailbox"], s["message_id"], s.get("attachment_id") or s["filename"], p["account_key"], p["currency"]])[:24]


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
    zero_activity = (p.get('account_type') == 'bank_account' and p['complete'] and p['account_resolved'] and
                     not p['issues'] and p['checks'].get('expected_transaction_count') == 0 and
                     'opening_balance_minor' in p['checks'] and 'closing_balance_minor' in p['checks'] and
                     p['checks']['opening_balance_minor'] == p['checks']['closing_balance_minor'])
    if not p["transactions"] and not zero_activity:
        issues.append("No transaction rows")
    if any(r['kind'] in {'transfer_in', 'transfer_out'} and not (r.get('own_account_key') and r.get('transfer_evidence')) for r in p['transactions']):
        issues.append('Own-account transfer needs a confirmed counterparty and ownership evidence')
    if any(r["kind"] == "unknown" for r in p["transactions"]):
        issues.append("Unknown transaction movement type")
    rows, checks = p["transactions"] + p.get('review_rows', []), p["checks"]
    financial_issues = []
    if p.get('review_rows') or any(r.get('review_reason') for r in p['transactions']):
        financial_issues.append('Source rows retained for unresolved financial review')
    from .statement_coverage import assess, duplicate_problem
    coverage = assess(record, all_records)
    for row in p['transactions']:
        problem = duplicate_problem(record, row, all_records)
        if problem: financial_issues.append(problem)
        if row.get('duplicate_of'):
            target = next((r for r in all_records if r['id'] == row['duplicate_of']['statement']), None)
            if target and target['status'] != 'imported': financial_issues.append('Duplicate target is not imported')
    links = [(r['duplicate_of']['statement'], r['duplicate_of']['index']) for r in p['transactions'] if r.get('duplicate_of')]
    if len(links) != len(set(links)): financial_issues.append('Duplicate mappings must be one-to-one within a source section')
    issues.extend(financial_issues)
    amounts_known = all(type(r.get('amount_minor')) is int for r in rows)
    actual = {"expected_transaction_count": len(rows)}
    if amounts_known:
        actual.update(expected_debits_minor=sum(max(r['amount_minor'], 0) for r in rows),
                      expected_credits_minor=-sum(min(r['amount_minor'], 0) for r in rows))
    else:
        issues.append('Source row amount unavailable; monetary checks cannot be evaluated')
    passed = []
    for key, value in actual.items():
        if key in checks:
            if value != checks[key]:
                issues.append(f"{key} mismatch: extracted {value}, source {checks[key]}")
            else:
                passed.append(key)
    if "opening_balance_minor" in checks and p["account_type"] == "manual":
        issues.append("Balance arithmetic requires an explicit financial account type")
    if "opening_balance_minor" in checks and amounts_known and p["account_type"] != "manual":
        # Bank cash balances decrease on debits; credit-card liabilities increase.
        direction = -1 if p['account_type'] == 'bank_account' else 1
        closing = checks["opening_balance_minor"] + direction * sum(r["amount_minor"] for r in rows)
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
        overlaps = [i for i, r in enumerate(p["transactions"]) if row_key(r) in peers and i not in p["distinct_overlap_rows"] and not r.get("duplicate_of")]
        if overlaps:
            issues.append("Potential cross-statement overlap at zero-based rows: " + ",".join(map(str, overlaps)))
    financial_review_resolved = not issues
    if record['status'] in {'draft','imported'} and not coverage['verified']:
        issues.extend('Completeness not verified: ' + gap for gap in coverage['gaps'])
    return {"issues": list(dict.fromkeys(issues)), "coverage": coverage,
            "financial_review_resolved": financial_review_resolved, "passed_checks": passed,
            "unavailable_checks": sorted(CHECKS - set(checks))}


SCHEMA_VERSION = 1
SCHEMA = (
    "CREATE TABLE statements (id TEXT PRIMARY KEY, status TEXT NOT NULL CHECK(status IN ('draft','imported')), payload TEXT NOT NULL, created TEXT NOT NULL)",
    "CREATE TABLE alerts (id TEXT PRIMARY KEY, payload TEXT NOT NULL, created TEXT NOT NULL)",
    "CREATE TABLE alert_matches (alert_id TEXT PRIMARY KEY, statement_id TEXT NOT NULL, row_index INTEGER NOT NULL, evidence TEXT NOT NULL, UNIQUE(statement_id,row_index))",
    "CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT NOT NULL)",
    "CREATE TABLE merchant_categories (merchant TEXT PRIMARY KEY, category TEXT NOT NULL)",
    "CREATE TABLE processing_results (source_key TEXT PRIMARY KEY, payload TEXT NOT NULL)",
    "CREATE TABLE transaction_annotations (record_id TEXT NOT NULL, evidence_key TEXT NOT NULL, category TEXT, note TEXT, PRIMARY KEY(record_id,evidence_key))",
    "CREATE TABLE source_links (source_key TEXT PRIMARY KEY, record_id TEXT NOT NULL, source TEXT NOT NULL)",
    "CREATE TABLE transfer_exclusions (record_id TEXT NOT NULL, evidence_key TEXT NOT NULL, counterparty_account TEXT NOT NULL, evidence TEXT NOT NULL, PRIMARY KEY(record_id,evidence_key))",
    "CREATE TABLE user_transactions (id TEXT PRIMARY KEY, payload TEXT NOT NULL)",
    "CREATE TABLE transaction_metadata (id TEXT PRIMARY KEY, payload TEXT NOT NULL)",
)


def connect(data_dir):
    os.umask(0o077)
    data_dir.mkdir(parents=True,exist_ok=True,mode=0o700)
    if data_dir.resolve() != Path.cwd().resolve(): protect(data_dir,directory=True)
    path = data_dir/'ledger.sqlite3'
    fresh = not path.exists()
    db = sqlite3.connect(path,timeout=20)
    try:
        protect(path)
        db.execute('BEGIN IMMEDIATE')
        version = db.execute('PRAGMA user_version').fetchone()[0]
        tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if fresh and version == 0 and not tables:
            for statement in SCHEMA: db.execute(statement)
            db.execute(f'PRAGMA user_version={SCHEMA_VERSION}')
        else:
            expected = {statement.split()[2] for statement in SCHEMA}
            require(version == SCHEMA_VERSION and tables == expected, 'Unsupported MoneyLens database schema. Use a new data directory for this public release.')
        db.commit()
        return db
    except Exception:
        db.rollback(); db.close()
        raise


def find(all_records, statement_id):
    match = next((r for r in all_records if r["id"] == statement_id), None)
    require(match is not None, "Statement ID not found")
    return match


def save(db, record):
    db.execute("UPDATE statements SET status=?,payload=? WHERE id=?",
               (record["status"], json.dumps(record["payload"], ensure_ascii=False), record["id"]))


def import_record(db, ident):
    """Import a staged statement only after its current evidence passes validation."""
    current = records(db)
    record = find(current, ident)
    if record['status'] == 'imported': return {'result':'already_imported','id':ident}
    checked = assessment(record,current)
    require(not checked['issues'], 'Import blocked: ' + '; '.join(checked['issues']))
    record['status'] = 'imported'
    save(db,record)
    from .merchants import remember_rows
    remember_rows(db,record['payload'])
    return {'result':'imported','id':ident}


def retain_source(db, record_id, payload):
    source = payload['source']
    key = hash_value([source, record_id])
    db.execute('INSERT OR REPLACE INTO source_links VALUES (?,?,?)',
               (key, record_id, json.dumps(source)))


def validate_currency(db, payload):
    """A unit label has one explicit precision throughout the ledger."""
    for table in ('statements','alerts','user_transactions'):
        for (raw,) in db.execute('SELECT payload FROM '+table):
            other=json.loads(raw)
            if table=='user_transactions':other=other['payload']
            require(payload['currency']!=other['currency'] or payload['currency_exponent']==other['currency_exponent'],
                    'Currency exponent conflicts with existing records')


def stage(db, path):
    require(path.stat().st_size <= 20 * 1024 * 1024, "Staging JSON exceeds 20 MiB")
    p = normalize(json.loads(path.read_text(encoding='utf-8')))
    from .store import get
    config = get(db, 'config')
    if config:
        from .accounts import validate_source
        validate_source(config, p)
    validate_currency(db,p)
    sid = source_id(p)
    all_records = records(db)
    binding = (p['account_key'], p['currency'])
    for r in all_records:
        q = r['payload']
        if r['id'] == sid:
            if r['status'] == 'imported':
                require(semantic_key(p) == semantic_key(q) and
                        [(v['page'], v['row']) for v in p['transactions']] == [(v['page'], v['row']) for v in q['transactions']] and
                        p.get('coverage') == q.get('coverage') and p.get('review_rows', []) == q.get('review_rows', []),
                        'Imported source conflicts with new extraction; preserve original and queue review')
                retain_source(db, sid, p)
                return {'result': 'already_imported', 'id': sid}
            continue
        same_bytes = (binding == (q['account_key'], q['currency']) and p['source'].get('sha256') and p['source'].get('sha256') == q['source'].get('sha256'))
        if same_bytes:
            for row in p['transactions']:
                matches = [(i, v) for i, v in enumerate(q['transactions']) if
                           (v['page'], v['row']) == (row['page'], row['row']) and row_key(v) == row_key(row) and
                           not v.get('duplicate_of') and not v.get('review_reason') and v['kind'] != 'unknown']
                if len(matches) == 1 and not row.get('duplicate_of') and not row.get('review_reason'):
                    row['duplicate_of'] = {'statement': r['id'], 'index': matches[0][0], 'evidence': 'Identical original document digest and physical source row'}
    retain_source(db, sid, p)
    record = {"id": sid, "status": "draft", "payload": p}
    previous = next((r for r in all_records if r["id"] == sid), None)
    if previous:
        old_locations = {(r['page'], r['row']) for r in previous['payload']['transactions'] + previous['payload'].get('review_rows', [])}
        new_locations = {(r['page'], r['row']) for r in p['transactions'] + p.get('review_rows', [])}
        require(old_locations <= new_locations, 'Restaging cannot remove source rows; retain a duplicate link or visible review mapping')
        save(db, record)
    else:
        db.execute("INSERT INTO statements VALUES (?,?,?,?)", (sid, "draft", json.dumps(p, ensure_ascii=False), dt.datetime.now(dt.timezone.utc).isoformat()))
    updated = [r for r in all_records if r["id"] != sid] + [record]
    return {"result": "staged", "id": sid, **assessment(record, updated)}


def default_dir():
    return Path.cwd().resolve()
