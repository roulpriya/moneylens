"""Standalone local dashboard; no external assets, network requests, or mutations."""
import datetime as dt
import json
import re
from pathlib import Path


def render(records, from_date=None, to_date=None, existing=None, sync=None):
    statements, rows = [], []
    for record in records:
        p = record["payload"]
        validation = record["validation"]
        statements.append({"id": record["id"], "status": record["status"], "account": p["account_label"],
                           "currency": p["currency"], "period": p["period_start"] + " – " + p["period_end"],
                           "checks": validation, "source": p["source"], "record_type": record.get("record_type", "statement"), "resolution_notes": p.get("resolution_notes", "")})
        for index, row in enumerate(p["transactions"]):
            rows.append({**row, "index": index, "statement": record["id"], "status": record["status"],
                         "account": p["account_label"], "account_key": p["account_key"],
                         "currency": p["currency"], "exponent": p["currency_exponent"],
                         "account_type": p.get("account_type", "credit_card"),
                         "channel": row.get("channel", "upi" if p.get('account_type')=='bank_account' or re.match(r'^(?:EMI\s+)?UPI\b', row['merchant'], re.I) else 'card'),
                         "blocked": bool(validation["issues"]), "suppressed": record["status"] == "matched"})
    upi_matches = {tuple(record['matched_to']) for record in records if record.get('matched_to') and record['payload']['transactions'][0].get('channel')=='upi'}
    for row in rows:
        if (row['statement'], row['index']) in upi_matches:
            row['channel'] = 'upi'
    reviews = {}
    def add_review(message_id, account, reason):
        lowered = reason.lower()
        if any(w in lowered for w in ('password', 'keychain', 'unlock')): group = 'Passwords'
        elif any(w in lowered for w in ('overlap', 'match', 'reconcil', 'indistinguishable')): group = 'Transaction matching'
        elif any(w in lowered for w in ('account', 'identity', 'new card')): group = 'Accounts'
        else: group = 'Source checks'
        reviews.setdefault((message_id, group), {'group': group, 'message_id': message_id, 'account': account, 'reason': reason})
    for statement in statements:
        for issue in statement['checks']['issues']:
            add_review(statement['source']['message_id'], statement['account'], issue)
    for pending in (sync or {}).get('pending_sources', []):
        add_review(pending['message_id'], pending.get('account_label', ''), pending['reason'])
    data = {"statements": statements, "rows": rows, "from": from_date or "", "to": to_date or "",
            "generated": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"), "sync": sync or {}, "schema_version": 3,
            "review_items": list(reviews.values())}
    # Untrusted merchant/subject strings cannot close the script element.
    encoded = json.dumps(data, ensure_ascii=True).replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
    opening = '<!-- MONEYLENS_DATA_START -->\n<script id="data" type="application/json">'
    closing = '</script>\n<!-- MONEYLENS_DATA_END -->'
    original = existing if existing is not None else (Path(__file__).resolve().parents[1] / "assets/report-template.html").read_text()
    if '<meta name="moneylens-template-version" content="3">' not in original:
        raise ValueError("Report template version is incompatible; run setup to select or initialize a compatible report")
    if original.count(opening) != 1 or original.count(closing) != 1:
        raise ValueError("Report has no unique MoneyLens data block; UI left unchanged")
    before, rest = original.split(opening)
    _, after = rest.split(closing)
    return before + opening + encoded + closing + after
