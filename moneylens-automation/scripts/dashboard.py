"""Standalone local dashboard; no external assets, network requests, or mutations."""
import datetime as dt
import json
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
                         "blocked": bool(validation["issues"]), "suppressed": record["status"] == "matched"})
    data = {"statements": statements, "rows": rows, "from": from_date or "", "to": to_date or "",
            "generated": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"), "sync": sync or {}, "schema_version": 2}
    # Untrusted merchant/subject strings cannot close the script element.
    encoded = json.dumps(data, ensure_ascii=True).replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
    opening = '<!-- MONEYLENS_DATA_START -->\n<script id="data" type="application/json">'
    closing = '</script>\n<!-- MONEYLENS_DATA_END -->'
    original = existing if existing is not None else (Path(__file__).resolve().parents[1] / "assets/report-template.html").read_text()
    if '<meta name="moneylens-template-version" content="2">' not in original:
        raise ValueError("Report template version is incompatible; run setup to select or initialize a compatible report")
    if original.count(opening) != 1 or original.count(closing) != 1:
        raise ValueError("Report has no unique MoneyLens data block; UI left unchanged")
    before, rest = original.split(opening)
    _, after = rest.split(closing)
    return before + opening + encoded + closing + after
