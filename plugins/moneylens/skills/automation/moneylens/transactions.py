"""Simple transaction operations backed by the existing private accounting ledger."""
from decimal import Decimal, InvalidOperation, localcontext
import json
from pathlib import Path
import tempfile
import uuid
from .ledger import (category_name, date, integer, normalize, records, require, text, validate_currency)
from .store import get


def amount_minor(value, exponent):
    try:
        require(len(str(value))<=256,'Amount text exceeds 256 characters')
        number = Decimal(str(value))
        require(number.is_finite(),'Amount must be finite')
        require(number == 0 or (number.adjusted()+exponent<=15 and number.as_tuple().exponent+exponent>=-len(number.as_tuple().digits)), 'Amount has unsupported precision or exceeds the safe integer limit')
        with localcontext() as context:
            context.prec = max(64,len(number.as_tuple().digits)+exponent)
            amount = number * (10 ** exponent)
        require(amount.is_finite() and amount == amount.to_integral_value(), 'Amount has unsupported precision')
        return integer(int(amount), 'amount')
    except (InvalidOperation, ValueError, OverflowError):
        raise ValueError('Amount must be a finite decimal with supported precision') from None


def decimal_amount(value,exponent):
    whole,fraction=divmod(abs(value),10**exponent)
    return ('-' if value<0 else '')+str(whole)+(('.'+str(fraction).zfill(exponent)) if exponent else '')


def metadata(value):
    require(isinstance(value, dict), 'metadata must be an object')
    encoded = json.dumps(value, allow_nan=False)
    require(len(encoded.encode('utf-8')) <= 65536, 'metadata exceeds 64 KiB')
    for field,limit in (('display_description',500),('display_note',2000),('merchant',500)):
        if value.get(field) is not None: text(value[field],field,limit)
    return json.loads(encoded)


def add(db, description, amount, when, category=None, currency=None, account='manual', provisional=False, extra=None, *, currency_exponent, kind):
    from .merchants import lookup, remember
    extra = metadata({} if extra is None else extra)
    require(not {'kind','currency_exponent'} & set(extra),'Supply kind and currency_exponent as transaction fields')
    exponent = currency_exponent
    require(type(exponent) is int and 0 <= exponent <= 18, 'Invalid currency exponent')
    value = amount_minor(amount, exponent)
    description = text(description, 'description', 500)
    explicit_category = category
    name=extra.get('merchant',description)
    category=category if category is not None else lookup(db,name)
    require(category is not None,'Category required for an uncached merchant; the agent must categorize it')
    category=category_name(category)
    config=get(db,'config',{})
    known_cards=config.get('cards',[])
    known_banks=config.get('bank_accounts',[])
    known=next((a for a in known_cards+known_banks if a['account_key']==account),None)
    account_type=extra.get('account_type')
    if account_type is None:
        account_type=('credit_card' if known in known_cards else 'bank_account') if known is not None else 'manual'
    source = extra.get('source')
    if source is not None:
        require(isinstance(source, dict) and source, 'source metadata must identify a mailbox and message')
        from .accounts import require_configured
        require_configured(config)
        source = {'filename': 'email-body', **source}
    payload = normalize({'source': source or {'mailbox': 'manual', 'message_id': uuid.uuid4().hex, 'filename': 'manual-entry'},
        'account_key': text(account, 'account'), 'account_label': text(extra.get('account_label',known.get('account_label') if known else account),'account_label'), 'issuer': extra.get('issuer',known.get('issuer') if known else None),
        'period_start': date(when), 'period_end': date(when), 'currency': currency,
        'currency_exponent': exponent, 'complete': True, 'issues': [], 'checks': {},
        'account_type': account_type,
        'transactions': [{'date': when, 'merchant': description, 'amount_minor': value, 'kind': kind,
                          'category': category, 'page': extra.get('page', 1), 'row': extra.get('row', 'body:1'),
                          **{k: extra[k] for k in ('reference', 'channel', 'own_account_key', 'transfer_evidence') if k in extra}}]})
    validate_currency(db,payload)
    if source:
        # Supplied notification evidence is provisional until reconciled to a statement.
        from .alerts import ingest
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', suffix='.json', delete=False) as stream:
            path = Path(stream.name)
            try: json.dump(payload, stream)
            except Exception:
                path.unlink(missing_ok=True)
                raise
        try: outcome = ingest(db, path)
        finally: path.unlink(missing_ok=True)
        ident = outcome['id']
        previous = db.execute('SELECT payload FROM transaction_metadata WHERE id=?', (ident,)).fetchone()
        extra = {**(json.loads(previous[0]) if previous else {}), **extra}
    else:
        ident = uuid.uuid4().hex
        status = 'provisional' if provisional else 'posted'
        db.execute('INSERT INTO user_transactions VALUES (?,?)', (ident, json.dumps({'status': status, 'payload': payload, 'explicit_category': explicit_category})))
    db.execute('INSERT OR REPLACE INTO transaction_metadata VALUES (?,?)', (ident, json.dumps(extra)))
    if category != 'Other':remember(db,name,category,replace=False)
    return next(row for row in list_transactions(db, include_covered=True) if row['id'] == ident)


def manual_records(db):
    items = [{'id': ident, **json.loads(raw), 'record_type': 'transaction',
             'validation': {'issues': [], 'passed_checks': [], 'unavailable_checks': []}}
            for ident, raw in db.execute('SELECT id,payload FROM user_transactions ORDER BY id')]
    from .alerts import statement_coverage
    saved = records(db)
    for record in items:
        if record['status'] == 'provisional' and statement_coverage(record['payload'], saved):
            record['status'] = 'statement_covered'
    return items



def enrich(db, effective):
    """Apply user metadata without changing original source rows or their identity."""
    extras = {ident: json.loads(raw) for ident, raw in db.execute('SELECT id,payload FROM transaction_metadata')}
    for record in effective:
        if record.get('matched_to') and record['id'] in extras:
            statement, index = record['matched_to']
            target = f'{statement}:{index}'
            extras[target] = {**extras[record['id']], **extras.get(target, {})}
    for record in effective:
        for index, row in enumerate(record['payload']['transactions']):
            if record.get('explicit_category'):
                row['category'] = category_name(record['explicit_category'])
                row['category_origin'] = 'user_entry'
            row['metadata'] = {**row.get('metadata', {}), **extras.get(f"{record['id']}:{index}", extras.get(record['id'], {}))}
            if row['metadata'].get('display_description') is not None:
                row['display_merchant'] = text(row['metadata']['display_description'], 'display_description', 500)
            if row['metadata'].get('display_note') is not None:
                text(row['metadata']['display_note'], 'display_note', 2000)
    from .accounting import decorate as accounting_treatment
    return accounting_treatment(db, effective)


def list_transactions(db, include_covered=False):
    from .alerts import report_records
    from .personalize import decorate
    saved = records(db)
    effective = enrich(db, decorate(db, saved + report_records(db, saved) + manual_records(db)))
    result = []
    statement_ids = {r['id'] for r in saved}
    for record in effective:
        if record['status'] == 'statement_covered' and not include_covered: continue
        for index, row in enumerate(record['payload']['transactions']):
            ident = f"{record['id']}:{index}" if record['id'] in statement_ids else record['id']
            exponent = record['payload']['currency_exponent']
            result.append({'id': ident, 'description': row['merchant'], 'amount': decimal_amount(row['amount_minor'],exponent),
                'amount_minor': row['amount_minor'], 'currency': record['payload']['currency'], 'currency_exponent': exponent, 'date': row['date'],
                'kind': row['kind'], 'channel': row.get('channel'), 'account_type': record['payload']['account_type'],
                'accounting_treatment': row.get('accounting_treatment', 'ordinary'),
                'excluded_from_spending': row.get('excluded_from_spending', False),
                'excluded_from_income': row.get('excluded_from_income', False),
                'category': row['category'], 'account': record['payload']['account_key'],
                'status': 'confirmed' if record['status'] in {'posted', 'imported'} else record['status'],
                'metadata': row.get('metadata', {}), 'source': record['payload']['source']})
    return sorted(result, key=lambda r: (r['date'], r['id']))


def update(db, ident, changes):
    require(changes, 'Supply at least one field to update')
    manual = db.execute('SELECT payload FROM user_transactions WHERE id=?', (ident,)).fetchone()
    if manual:
        record = json.loads(manual[0]); payload = record['payload']; row = payload['transactions'][0]
        if 'description' in changes: row['merchant'] = text(changes['description'], 'description', 500)
        if 'amount' in changes:
            row['amount_minor'] = amount_minor(changes['amount'], payload['currency_exponent'])
        if 'kind' in changes:row['kind']=changes['kind']
        if 'date' in changes:
            row['date'] = date(changes['date']); payload['period_start'] = payload['period_end'] = row['date']
        if 'category' in changes:
            row['category'] = text(changes['category'], 'category', 80)
            record['explicit_category'] = row['category']
        record['payload'] = normalize(payload)
        db.execute('UPDATE user_transactions SET payload=? WHERE id=?', (json.dumps(record), ident))
    else:
        current = next((r for r in list_transactions(db, include_covered=True) if r['id'] == ident), None)
        require(current is not None, 'Transaction not found')
        require(not set(changes) - {'category', 'metadata'}, 'Source-backed amounts, descriptions, and dates retain their original evidence; edit category or metadata')
        if 'category' in changes:
            from .personalize import annotate
            source, _, index = ident.partition(':')
            annotate(db, source, int(index) if index else 0, category=changes['category'])
    if not manual and 'metadata' in changes:
        extra = metadata(changes['metadata'])
        if 'own_account_key' in extra or 'transfer_evidence' in extra:
            from .transfers import confirm
            source, _, index = ident.partition(':')
            confirm(db, source, int(index) if index else 0, extra.get('own_account_key'), extra.get('transfer_evidence'))
    if 'metadata' in changes:
        db.execute('INSERT OR REPLACE INTO transaction_metadata VALUES (?,?)', (ident, json.dumps(metadata(changes['metadata']))))
    return next(r for r in list_transactions(db, include_covered=True) if r['id'] == ident)


def remove(db, ident):
    require(db.execute('SELECT 1 FROM user_transactions WHERE id=?', (ident,)).fetchone(), 'Only manually added transactions can be removed; source-backed entries retain their audit evidence')
    db.execute('DELETE FROM user_transactions WHERE id=?', (ident,))
    db.execute('DELETE FROM transaction_metadata WHERE id=?', (ident,))
    return {'result': 'removed', 'id': ident}
