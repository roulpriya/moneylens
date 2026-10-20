"""Provisional Gmail alerts and evidence-based reconciliation with statements."""
import datetime as dt
import json
import re
from ledger import (assessment, find, hash_value, normalize, records, require, row_key,
                    source_id, text)


def ingest(db, path):
    require(path.stat().st_size <= 1024 * 1024, "Alert payload exceeds 1 MiB")
    p = normalize(json.loads(path.read_text()))
    require(len(p["transactions"]) == 1, "One alert payload must contain exactly one movement")
    checked = assessment({"id": source_id(p), "status": "provisional", "payload": p}, [])
    require(not checked["issues"], "Alert requires review: " + "; ".join(checked["issues"]))
    # The extraction workflow must exclude declined transactions, OTPs,
    # authorizations, balance-only notices, and reversed attempts before this call.
    movement = p["transactions"][0]
    sid = hash_value([source_id(p), movement["page"], movement["row"]])[:24]
    for record in records(db):
        q = record["payload"]
        require(p["currency"] != q["currency"] or p["currency_exponent"] == q["currency_exponent"], "Currency exponent conflicts with existing records")
    for aid, raw in db.execute("SELECT id,payload FROM alerts"):
        q = json.loads(raw)
        require(p["currency"] != q["currency"] or p["currency_exponent"] == q["currency_exponent"], "Currency exponent conflicts with existing alerts")
        if aid == sid:
            old = q['transactions'][0]
            if old['amount_minor'] == movement['amount_minor'] and old['date'] == movement['date']:
                if movement.get('channel') == 'upi': old['channel'] = 'upi'
                if movement.get('reference') and not old.get('reference'): old['reference'] = movement['reference']
                q.setdefault('account_type', p['account_type'])
                db.execute('UPDATE alerts SET payload=? WHERE id=?', (json.dumps(q, ensure_ascii=False), aid))
            return {"result": "already_saved", "id": sid}
        a, b = p["transactions"][0], q["transactions"][0]
        if p["account_key"] == q["account_key"] and p["currency"] == q["currency"] and a.get("reference") and a.get("reference") == b.get("reference") and a["amount_minor"] == b["amount_minor"] and a["kind"] == b["kind"]:
            return {"result": "duplicate_alert", "id": aid}
    db.execute("INSERT INTO alerts VALUES (?,?,?)", (sid, json.dumps(p, ensure_ascii=False), dt.datetime.now(dt.timezone.utc).isoformat()))
    return {"result": "provisional_saved", "id": sid}


def similar(a, b):
    days = abs((dt.date.fromisoformat(a["date"]) - dt.date.fromisoformat(b["date"])).days)
    def merchant(row):
        value = row['merchant'].casefold()
        for location in ('bangalore', 'bengaluru', 'mumbai'):
            value = value.replace(location, '')
        words = re.findall(r'\w+', value)
        return ''.join(w for w in words if w not in {'limited','ltd','private','pvt','india','in','e','commerce','com'})
    left, right = merchant(a), merchant(b)
    consistent = left == right or (min(len(left), len(right)) >= 6 and (left.startswith(right) or right.startswith(left)))
    return days <= 3 and consistent and a['amount_minor'] == b['amount_minor'] and a['kind'] == b['kind']


def report_records(db, all_statements):
    alerts = [{"id": aid, "payload": json.loads(raw)} for aid, raw in db.execute("SELECT id,payload FROM alerts ORDER BY created,id")]
    explicit = {aid: (sid, idx) for aid, sid, idx in db.execute("SELECT alert_id,statement_id,row_index FROM alert_matches")}
    candidates = {}
    imported = [r for r in all_statements if r["status"] == "imported"]
    for alert in alerts:
        p, matches, strong, weak = alert["payload"], [], [], []
        a = p["transactions"][0]
        for s in imported:
            q = s["payload"]
            if p["account_key"] != q["account_key"] or p["currency"] != q["currency"]:
                continue
            for index, b in enumerate(q["transactions"]):
                if a.get("reference") and a.get("reference") == b.get("reference"):
                    matches.append((s["id"], index))
                    if a["amount_minor"] == b["amount_minor"] and a["kind"] == b["kind"]:
                        strong.append((s["id"], index))
                elif not (a.get('reference') and b.get('reference')) and similar(a, b):
                    matches.append((s["id"], index))
                elif not (a.get('reference') and b.get('reference')) and a['amount_minor'] == b['amount_minor'] and a['kind'] == b['kind'] and abs((dt.date.fromisoformat(a['date'])-dt.date.fromisoformat(b['date'])).days) <= 3:
                    opaque_recipient = '*' in a['merchant'] or '@' in a['merchant']
                    if a['date'] == b['date'] and (a['kind'] == 'payment' or (opaque_recipient and a.get('channel') == 'upi' and re.search(r'\bUPI', b['merchant'], re.I))):
                        matches.append((s['id'], index))
                    else:
                        weak.append((s['id'], index))
        candidates[alert["id"]] = (matches, strong, weak)
    # A statement row may replace at most one independently saved alert.
    strong_counts = {}
    for aid, (_, strong, _) in candidates.items():
        if len(strong) == 1:
            strong_counts[strong[0]] = strong_counts.get(strong[0], 0) + 1
    claimed = set(explicit.values())
    candidate_counts = {}
    for aid, (matches, _, _) in candidates.items():
        if aid not in explicit:
            for match in set(matches):
                candidate_counts[match] = candidate_counts.get(match, 0) + 1
    result = []
    for alert in alerts:
        aid, p = alert["id"], alert["payload"]
        matches, strong, weak = candidates[aid]
        state, issues = ("posted" if p.get('account_type') == 'bank_account' else "provisional"), []
        matched_to = None
        if aid in explicit:
            state = "matched"
            matched_to = explicit[aid]
        elif len(strong) == 1 and strong_counts[strong[0]] == 1 and strong[0] not in claimed:
            state = "matched"
            matched_to = strong[0]
        elif len(matches) == 1 and candidate_counts[matches[0]] == 1 and matches[0] not in claimed:
            # Exact account/currency/amount/movement and normalized merchant,
            # with a short posting-date window and one-to-one cardinality.
            # A shared opaque reference is helpful, but not mandatory.
            state = "matched"
            matched_to = matches[0]
        elif matches or weak:
            state, issues = "needs_review", ["Possible statement match; alert withheld to avoid double counting. Reconcile using source evidence."]
        else:
            for other in alerts:
                q = other["payload"]
                a, b = p["transactions"][0], q["transactions"][0]
                same_ref = a.get("reference") and a.get("reference") == b.get("reference")
                distinct_refs = a.get('reference') and b.get('reference') and a['reference'] != b['reference']
                if other["id"] != aid and p["account_key"] == q["account_key"] and p["currency"] == q["currency"] and not distinct_refs and (same_ref or row_key(a) == row_key(b)):
                    state, issues = "needs_review", ["Conflicting or indistinguishable alert emails; resolve whether they represent one or multiple transactions."]
                    break
        result.append({**alert, "status": state, "matched_to": matched_to, "record_type": "upi" if p.get('account_type') == 'bank_account' else "alert", "validation": {"issues": issues, "passed_checks": ["statement_match"] if state == "matched" else [], "unavailable_checks": []}})
    return result


def reconcile(db, alert_id, statement_id, index, evidence):
    raw = db.execute("SELECT payload FROM alerts WHERE id=?", (alert_id,)).fetchone()
    require(raw is not None, "Alert ID not found")
    p = json.loads(raw[0]); statement = find(records(db), statement_id)
    require(statement["status"] == "imported", "Reconcile against an imported statement")
    q = statement["payload"]
    require(0 <= index < len(q["transactions"]), "Statement row out of bounds")
    a, b = p["transactions"][0], q["transactions"][index]
    require(p["account_key"] == q["account_key"] and p["currency"] == q["currency"] and a["amount_minor"] == b["amount_minor"] and a["kind"] == b["kind"], "Account, currency, movement type, and amount must agree")
    existing = db.execute("SELECT statement_id,row_index FROM alert_matches WHERE alert_id=?", (alert_id,)).fetchone()
    if existing:
        require(existing == (statement_id, index), "Alert is already reconciled to another row")
        return {"result": "already_reconciled", "id": alert_id}
    db.execute("INSERT INTO alert_matches VALUES (?,?,?,?)", (alert_id, statement_id, index, text(evidence, "evidence", 2000)))
    return {"result": "reconciled", "id": alert_id}
