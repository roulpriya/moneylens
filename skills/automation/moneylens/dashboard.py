"""Standalone local dashboard; no external assets, network requests, or mutations."""
import copy
import datetime as dt
import json
from pathlib import Path


def render(records, from_date=None, to_date=None, existing=None, sync=None):
    statements, rows = [], []
    for record in records:
        if record['status'] == 'statement_covered': continue
        p = record["payload"]
        validation = record["validation"]
        statements.append({"id": record["id"], "status": record["status"], "account": p["account_label"],
                           "currency": p["currency"], "exponent": p["currency_exponent"], "period": p["period_start"] + " – " + p["period_end"],
                           "checks": copy.deepcopy(validation), "coverage": copy.deepcopy(validation.get("coverage")), "financial_review_resolved": validation.get("financial_review_resolved"), "source": p["source"], "sources": record.get("sources", [p["source"]]), "record_type": record.get("record_type", "bank_statement" if p.get("account_type")=="bank_account" else "statement"), "resolution_notes": p.get("resolution_notes", "")})
        visible_rows = list(p['transactions']) + [
            {'date': r.get('date', ''), 'merchant': 'Unresolved source row: ' + r['reason'],
             'category': 'Review', 'kind': 'unknown', 'amount_minor': r.get('amount_minor'),
             'page': r['page'], 'row': r['row'], 'source_row_id': r['source_row_id'],
             'review_reason': r['reason'], 'channel': None}
            for r in p.get('review_rows', [])]
        from .statement_coverage import duplicate_problem
        for index, row in enumerate(visible_rows):
            rows.append({**row, "merchant": row.get("display_merchant", row["merchant"]), "original_merchant": row["merchant"], "index": index, "statement": record["id"], "status": record["status"],
                         "account": p["account_label"], "account_key": p["account_key"], "mailbox_id": p["source"]["mailbox"],
                         "currency": p["currency"], "exponent": p["currency_exponent"],
                         "account_type": p["account_type"],
                         "channel": row.get("channel"),
                         "blocked": bool(validation["issues"]) or bool(row.get('review_reason')) or row['kind'] == 'unknown',
                         "source": p['source'], "suppressed": record["status"] == "matched" or bool(row.get('duplicate_of') and not duplicate_problem(record, row, records)),
                         "coverage_status": validation.get('coverage', {}).get('status', 'Completeness not verified')})
    visibility_supported = existing is None or 'id="view-all"' in existing
    supplied_channels={tuple(record['matched_to']):record['payload']['transactions'][0].get('channel') for record in records if record.get('matched_to')}
    for row in rows:
        if row['channel'] is None:row['channel']=supplied_channels.get((row['statement'],row['index']))
    reviews = {}
    def add_review(message_id, account, reason, mailbox_id=""):
        if not mailbox_id: mailbox_id = "unspecified"
        lowered = reason.lower()
        if any(w in lowered for w in ('password', 'unlock')): group = 'Passwords'
        elif any(w in lowered for w in ('overlap', 'match', 'reconcil', 'indistinguishable')): group = 'Transaction matching'
        elif any(w in lowered for w in ('account', 'identity', 'new card')): group = 'Accounts'
        else: group = 'Source checks'
        key = (mailbox_id, message_id, account, group)
        reviews.setdefault(key, {'mailbox_id': mailbox_id, 'group': group, 'message_id': message_id, 'account': account, 'reason': reason})
        if reason not in reviews[key]['reason']: reviews[key]['reason'] += ' · ' + reason
    for statement in statements:
        for issue in statement['checks']['issues']:
            add_review(statement['source']['message_id'], statement['account'], issue, statement['source']['mailbox'])
        coverage = statement.get('coverage') or {}
        for gap in coverage.get('gaps', []):
            account = 'Combined document' if coverage.get('section_count',0)>1 else statement['account']
            add_review(statement['source']['message_id'], account, 'Document completeness: '+gap, statement['source']['mailbox'])
    for pending in (sync or {}).get('pending_sources', []):
        for index, review in enumerate(pending.get('review_rows', [])):
            rows.append({**review, 'date': review.get('date', ''), 'merchant': 'Unresolved source row: ' + review['reason'],
                         'amount_minor': review.get('amount_minor'), 'kind': 'unknown', 'category': 'Review',
                         'index': index, 'statement': 'review-' + pending['key'], 'status': 'needs_review',
                         'account': pending.get('account_label', pending.get('account_key', 'Unresolved account')),
                         'account_key': pending.get('account_key', ''), 'mailbox_id': pending.get('mailbox_id', ''),
                         'currency': pending.get('currency', ''), 'exponent': pending.get('currency_exponent'),
                         'channel': pending.get('channel'), 'account_type': pending.get('account_type'),
                         'blocked': True, 'suppressed': False, 'review_reason': review['reason'],
                         'source': {'mailbox': pending.get('mailbox_id'), 'message_id': pending['message_id'], 'attachment_id': pending.get('attachment_id'), 'filename': pending.get('filename')},
                         'coverage_status': 'Completeness not verified'})
        add_review(pending['message_id'], pending.get('account_label', ''), pending['reason'], pending.get('mailbox_id', ''))
    for row in rows:
        if not row.get('excluded_from_spending') and row['category'] == 'Other' and (row['amount_minor'] or 0) > 0 and row['kind'] in {'purchase', 'debit', 'fee', 'interest', 'cash_advance', 'adjustment_debit'} and not row['suppressed']:
            key = (row['mailbox_id'], row['statement'], row['index'])
            reviews[key] = {'group': 'Categorization', 'mailbox_id': row['mailbox_id'], 'message_id': row['statement'],
                            'account': row['account'], 'reason': 'Merchant category needs review: ' + row['merchant']}
    data = {"statements": statements, "rows": rows, "from": from_date or "", "to": to_date or "",
            "generated": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"), "sync": sync or {}, "schema_version": 4,
            "review_items": list(reviews.values()), "report_visibility_complete": visibility_supported}
    # Untrusted merchant/subject strings cannot close the script element.
    encoded = json.dumps(data, ensure_ascii=True).replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
    opening = '<!-- MONEYLENS_DATA_START -->\n<script id="data" type="application/json">'
    closing = '</script>\n<!-- MONEYLENS_DATA_END -->'
    original = existing if existing is not None else (Path(__file__).resolve().parents[1] / "assets/report-template.html").read_text(encoding='utf-8')
    if '<meta name="moneylens-template-version" content="4">' not in original:
        raise ValueError("Unsupported report template. Generate this release's report at a new output path.")
    if not visibility_supported: raise ValueError('Unsupported report template: All transactions view is required')
    if original.count(opening) != 1 or original.count(closing) != 1:
        raise ValueError("Report has no unique MoneyLens data block; UI left unchanged")
    before, rest = original.split(opening)
    _, after = rest.split(closing)
    return before + opening + encoded + closing + after


def write_report(db, output=None, from_date=None, to_date=None):
    """Render a snapshot atomically, preserving the existing report outside its data."""
    import os
    import tempfile
    from .ledger import assessment, date, records, require
    from .store import get, reviews
    from .alerts import report_records
    from .transactions import manual_records, enrich
    from .personalize import decorate
    from .merchants import entries
    from .private_files import protect
    if from_date: date(from_date)
    if to_date: date(to_date)
    require(not (from_date and to_date) or from_date <= to_date, 'Report date range reversed')
    config = get(db,'config',{})
    if output is None:
        database = next(row[2] for row in db.execute('PRAGMA database_list') if row[1]=='main')
        output = config.get('report_path') or Path(database).resolve().parent/'report.html'
    output = Path(output)
    require(output.suffix.lower()=='.html','Report output must end in .html')
    saved = records(db)
    effective = [{**record,'validation':assessment(record,saved)} for record in saved]
    effective.extend(report_records(db,saved))
    effective.extend(manual_records(db))
    effective = enrich(db,decorate(db,effective))
    for record in effective:
        record['sources'] = [json.loads(raw) for (raw,) in db.execute(
            'SELECT source FROM source_links WHERE record_id=? ORDER BY source_key',(record['id'],))] or [record['payload']['source']]
    context = {'pending_sources':reviews(db),'merchant_categories':entries(db),'timezone':config.get('timezone')}
    previous = output.read_text(encoding='utf-8') if output.exists() else None
    page = render(effective,from_date,to_date,existing=previous,sync=context)
    output.parent.mkdir(parents=True,exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='w',encoding='utf-8',dir=output.parent,delete=False) as stream:
            temporary = Path(stream.name)
            protect(temporary)
            stream.write(page)
        os.replace(temporary,output)
        protect(output)
    finally:
        if temporary is not None: temporary.unlink(missing_ok=True)
    return {'result':'report_created','output':str(output.resolve()),'statements':len(effective)}
