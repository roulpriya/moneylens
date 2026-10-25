#!/usr/bin/env python3
"""Process supplied accounting payloads and render the configured report."""
import json
from pathlib import Path
import tempfile
from .ledger import connect, require, stage, records, find, import_record, hash_value, normalize
from .store import get, record_outcome
from .accounts import validate_source, require_configured
from .merchants import remember_rows, with_cached_categories


def failed_row_mappings(config, payload, reason):
    """Keep bounded, safe review occurrences when statement normalization fails.

    Do not persist arbitrary input or unconfirmed financial identities. Batch
    slot references denote unresolved locations, never invented source rows.
    """
    try:
        validate_source(config, {**payload, 'transactions': []})
    except (ValueError, KeyError, TypeError):
        return {}
    coverage = payload.get('coverage')
    if isinstance(coverage, dict) and isinstance(coverage.get('sections'), list):
        selected = next((section for section in coverage['sections'] if isinstance(section, dict) and section.get('id') == coverage.get('section_id')), {})
        if selected.get('type') == 'balance_snapshot' and selected.get('rows') == []:
            # A rejected attempt to turn balances into movements remains a
            # document-level review, never invented financial placeholders.
            return {}
    rows = payload.get('transactions', [])
    if not isinstance(rows, list) or len(rows) > 20000: return {}
    safe = []
    code = payload.get('currency')
    currency = code if isinstance(code,str) and 0 < len(code.strip()) <= 32 else None
    exponent = payload.get('currency_exponent')
    exponent_ok = type(exponent) is int and 0 <= exponent <= 18
    for i, raw in enumerate(rows + (payload.get('review_rows', []) if isinstance(payload.get('review_rows'), list) else [])):
        raw = raw if isinstance(raw, dict) else {}
        row = {'source_row_id': 'unresolved-input-' + str(i), 'page': None, 'row': 'unresolved-input-' + str(i), 'reason': reason[:1000]}
        if type(raw.get('page')) is int and 0 < raw['page'] <= 10000: row['page'] = raw['page']
        for field in ('row', 'source_row_id'):
            if isinstance(raw.get(field), str) and 0 < len(raw[field]) <= 100: row[field] = raw[field]
        if currency and exponent_ok and type(raw.get('amount_minor')) is int and abs(raw['amount_minor']) <= 9007199254740991:
            row['amount_minor'] = raw['amount_minor']
        try:
            from .ledger import date
            row['date'] = date(raw.get('date'))
        except (ValueError, TypeError): pass
        safe.append(row)
    return {'review_rows': safe, 'account_key': payload['account_key'], 'account_label': payload['account_key'],
            'currency': currency, 'currency_exponent': exponent if exponent_ok else None,
            'account_type': payload.get('account_type'),
            'channel': None}


def process_batch(data_dir, batch, render_report=True):
    require(isinstance(batch, list) and len(batch) <= 20000, 'Batch must be a list of statement/alert entries')
    db = connect(data_dir)
    outcomes = []
    try:
        config = get(db, 'config')
        require_configured(config)
        for entry in batch:
            payload = entry.get('payload', {}) if isinstance(entry, dict) else {}
            payload = payload if isinstance(payload, dict) else {}
            source = payload.get('source', {})
            source = source if isinstance(source, dict) else {}
            source = {k: source[k] for k in ('mailbox', 'message_id', 'attachment_id', 'filename') if isinstance(source.get(k), str)}
            source.setdefault('message_id', 'unresolved-entry-' + hash_value(entry)[:24])
            kind = entry.get('type') if isinstance(entry, dict) else None
            rows = payload.get('transactions')
            movement = [(r.get('page'), r.get('row')) for r in rows if isinstance(r, dict)] if kind == 'alert' and isinstance(rows, list) else []
            qualifier = hash_value([kind, payload.get('account_key'), payload.get('currency'), movement])[:24]
            try:
                # Commit each source independently. A later failure cannot undo
                # safe imports or erase another mailbox's progress.
                with db:
                    db.execute("BEGIN IMMEDIATE")
                    require(isinstance(entry, dict) and set(entry) == {'type', 'payload'} and kind in {'statement', 'alert'}, 'Invalid batch entry')
                    payload = normalize(with_cached_categories(db, payload))
                    validate_source(config, payload)
                    with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=data_dir, suffix='.json', delete=False) as stream:
                        temporary = Path(stream.name)
                        try: json.dump(payload, stream)
                        except Exception:
                            temporary.unlink(missing_ok=True)
                            raise
                    try:
                        if kind == 'alert':
                            from .alerts import ingest
                            outcome = ingest(db, temporary)
                        else:
                            outcome = stage(db, temporary)
                            if outcome['result'] == 'staged' and not outcome['issues']:
                                outcome.update(import_record(db,outcome['id']))
                        if kind=='statement' and outcome['result'] in {'imported','already_imported'}:remember_rows(db,payload)
                        record_outcome(db, source, outcome, qualifier)
                    finally: temporary.unlink(missing_ok=True)
            except (ValueError, KeyError, TypeError, OSError) as error:
                outcome = {'result': 'needs_review', 'reason': str(error), **(failed_row_mappings(config, payload, str(error)) if kind == 'statement' else {})}
                with db: record_outcome(db, source, outcome, qualifier)
            outcomes.append({**outcome, 'mailbox_id': source.get('mailbox'), 'message_id': source['message_id']})
        # Reassess touched sections after the batch so returned document coverage
        # includes siblings supplied later, without blocking healthy sections.
        from .ledger import assessment
        for outcome in outcomes:
            if outcome.get('result') not in {'staged','imported','already_imported'}: continue
            with db:
                db.execute("BEGIN IMMEDIATE")
                current = records(db)
                record = find(current, outcome['id'])
                checked = assessment(record, current)
                outcome.update(checked)
                if record['status']=='draft' and not checked['issues']:
                    outcome.update(import_record(db,record['id']))
                record_outcome(db, record['payload']['source'], outcome,
                               hash_value(['statement', record['payload']['account_key'], record['payload']['currency'], []])[:24])
        if render_report:
            from .dashboard import write_report
            try:
                with db:
                    db.execute('BEGIN IMMEDIATE')
                    report = write_report(db)
            except (ValueError,OSError) as error:
                raise ValueError('Report generation failed; accounting entries remain saved. Run moneylens.py report to inspect the failure') from error
            return {'outcomes':outcomes,'report':report}
        return {'outcomes':outcomes}
    finally: db.close()
