"""Exact merchant-category cache. New classification decisions come from the agent."""
from collections import defaultdict
import copy
from .ledger import category_name, records, require, text


def merchant_key(value):
    return ' '.join(text(value,'merchant',500).casefold().split())


def lookup(db, merchant):
    row=db.execute('SELECT category FROM merchant_categories WHERE merchant=?',(merchant_key(merchant),)).fetchone()
    return row[0] if row else None


def entries(db):
    return [{'merchant':name,'category':category} for name,category in db.execute('SELECT merchant,category FROM merchant_categories ORDER BY merchant')]


def remember(db, merchant, category, replace=True):
    name=merchant_key(merchant);category=category_name(category)
    require(category != 'Other','Other is unresolved; leave the merchant uncached for agent review')
    operation='INSERT OR REPLACE' if replace else 'INSERT OR IGNORE'
    db.execute(operation+' INTO merchant_categories VALUES (?,?)',(name,category))
    return {'merchant':name,'category':lookup(db,name),'needs_category':False}


def remember_rows(db, payload):
    """Cache supplied classifications; never invent categories or rewrite decisions."""
    for row in payload['transactions']:
        if row['category'] != 'Other':
            remember(db,row.get('metadata',{}).get('merchant',row['merchant']),row['category'],replace=False)


def with_cached_categories(db, payload):
    """Resolve omitted categories by exact saved mapping before input validation."""
    result = copy.deepcopy(payload)
    rows = result.get('transactions')
    if not isinstance(rows, list) or len(rows) > 20000: return result
    for row in rows:
        if not isinstance(row, dict) or 'category' in row: continue
        metadata = row.get('metadata', {})
        if not isinstance(metadata, dict): continue
        category = lookup(db, metadata.get('merchant', row.get('merchant')))
        require(category is not None, 'Category required for an uncached merchant; the agent must categorize it')
        row['category'] = category
    return result


def review(db, effective=None):
    from .alerts import report_records
    from .personalize import decorate
    if effective is None:
        saved = records(db)
        from .transactions import enrich, manual_records
        effective = enrich(db, decorate(db, saved + report_records(db, saved) + manual_records(db)))
    groups = defaultdict(lambda: {'count': 0, 'spending_minor': 0, 'merchants': {}})
    for record in effective:
        if record['status'] in {'matched', 'statement_covered'}: continue
        payload = record['payload']
        for index, row in enumerate(payload['transactions']):
            if row.get('excluded_from_spending') or row['category'] != 'Other' or row['kind'] not in {'purchase', 'debit', 'fee', 'interest', 'cash_advance', 'adjustment_debit'}: continue
            group = groups[payload['currency']]
            group['count'] += 1
            group['spending_minor'] += max(0, row['amount_minor'])
            name = row['normalized_merchant'] if 'normalized_merchant' in row else merchant_key(row.get('metadata', {}).get('merchant', row['merchant']))
            item = group['merchants'].setdefault(name, {'merchant': name, 'count': 0, 'spending_minor': 0, 'rows': []})
            item['count'] += 1; item['spending_minor'] += max(0, row['amount_minor'])
            item['rows'].append({'record': record['id'], 'row': index, 'mailbox_id': payload['source']['mailbox'],
                                 'status': record['status'], 'needs_source_review': bool(record.get('validation', {}).get('issues') or payload['issues']) or not payload['complete'] or not payload['account_resolved']})
    return {'currencies': [{'currency': code, 'count': group['count'], 'spending_minor': group['spending_minor'],
                            'merchants': sorted(group['merchants'].values(), key=lambda m: (-m['spending_minor'], -m['count'], m['merchant']))}
                           for code, group in sorted(groups.items())]}
