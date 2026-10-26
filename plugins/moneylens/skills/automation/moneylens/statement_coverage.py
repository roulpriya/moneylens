"""Source coverage, independent of classification, spend treatment and scan success.

The manifest records observations from the original document; it is not a PDF
parser or an attestation that an extractor told the truth. Missing observations
fail closed. Original source occurrences are never removed by reconciliation.
"""
from collections import Counter
from .ledger import CHECKS, require, text, integer, hash_value


def normalize_coverage(p):
    c = p.get('coverage')
    if c is None:
        return
    require(isinstance(c, dict) and set(c) == {'version', 'section_id', 'page_count', 'pages', 'sections'}, 'Invalid coverage manifest fields')
    require(c['version'] == 1, 'Unsupported coverage manifest version')
    text(c['section_id'], 'coverage.section_id')
    require(0 < integer(c['page_count'], 'page_count') <= 10000, 'Invalid document page count')
    require(isinstance(c['pages'], list) and isinstance(c['sections'], list) and 0 < len(c['sections']) <= 1000, 'Coverage needs page and section inventories')
    for page in c['pages']:
        require(isinstance(page, dict) and set(page) == {'page', 'status', 'evidence'}, 'Invalid page evidence')
        require(1 <= integer(page['page'], 'page') <= c['page_count'], 'Page outside document')
        require(page['status'] in {'read', 'unreadable', 'partial'}, 'Invalid page status')
        text(page['evidence'], 'page inventory evidence', 1000)
    require(len({v['page'] for v in c['pages']}) == len(c['pages']), 'Repeated coverage page')
    for section in c['sections']:
        required = {'id', 'account_key', 'currency', 'pages', 'rows', 'checks', 'evidence'}
        require(isinstance(section, dict) and required <= set(section) and not set(section) - required - {'type', 'limitations'}, 'Invalid section inventory')
        require(section.get('type', 'transactions') in {'transactions', 'balance_snapshot'}, 'Invalid section type')
        limitations = section.get('limitations', [])
        require(isinstance(limitations, list) and len(limitations) <= 100, 'Invalid section limitations')
        for limitation in limitations: text(limitation, 'section limitation', 1000)
        for field in ('id', 'account_key', 'currency', 'evidence'):
            text(section[field], 'section.' + field, 1000)
        require(isinstance(section['pages'], list) and section['pages'] and all(type(n) is int and 1 <= n <= c['page_count'] for n in section['pages']), 'Invalid section pages')
        require(isinstance(section['rows'], list) and len(section['rows']) <= 20000, 'Invalid source row inventory')
        require(section.get('type') != 'balance_snapshot' or not section['rows'], 'Balance snapshots cannot inventory transaction rows')
        for row in section['rows']:
            require(isinstance(row, dict) and not set(row) - {'id', 'page', 'row', 'amount_minor'} and {'id', 'page', 'row'} <= set(row), 'Invalid source row inventory entry')
            text(row['id'], 'source row id'); text(row['row'], 'source row location', 100)
            require(type(row['page']) is int and row['page'] in section['pages'], 'Source row outside section pages')
            if 'amount_minor' in row: integer(row['amount_minor'], 'source amount')
        require(len({r['id'] for r in section['rows']}) == len(section['rows']), 'Repeated source row identity')
        require(len({(r['page'], r['row']) for r in section['rows']}) == len(section['rows']), 'Repeated source row location')
        require(isinstance(section['checks'], dict) and set(section['checks']) == CHECKS, 'Inventory every applicable check, including unavailable checks')
        for key, observed in section['checks'].items():
            require(isinstance(observed, dict) and observed.get('status') in {'stated', 'unavailable'}, 'Invalid check evidence status')
            if observed['status'] == 'stated':
                require(set(observed) == {'status', 'value', 'page', 'evidence', 'origin'}, 'Stated check needs original source evidence')
                require(observed['origin'] == 'source', 'Checks must come from the original source, never extracted-row arithmetic')
                integer(observed['value'], key)
                require(type(observed['page']) is int and observed['page'] in section['pages'], 'Check outside section')
                text(observed['evidence'], 'check label/location', 1000)
            else:
                require(set(observed) == {'status', 'reason'}, 'Unavailable check needs a reason')
                text(observed['reason'], 'unavailable check reason', 1000)
    require(len({s['id'] for s in c['sections']}) == len(c['sections']), 'Repeated section identity')
    section = next((s for s in c['sections'] if s['id'] == c['section_id']), None)
    require(section is not None and (section['account_key'], section['currency']) == (p['account_key'], p['currency']), 'Coverage section binding mismatch')


def document_key(p):
    s = p['source']
    return (s['mailbox'], s['message_id'], s.get('attachment_id') or s['filename'])


def manifest_key(p):
    c = p['coverage']
    return hash_value({k: v for k, v in c.items() if k != 'section_id'})


def duplicate_problem(record, row, all_records):
    """Only terminal retained targets; cycles/chains and amount-only links fail."""
    link = row.get('duplicate_of')
    if not link:
        return None
    target = next((r for r in all_records if r['id'] == link['statement']), None)
    if target is None or target['id'] == record['id']:
        return 'Duplicate link has no distinct retained statement target'
    p, q = record['payload'], target['payload']
    index = link['index']
    if not 0 <= index < len(q['transactions']):
        return 'Duplicate target row does not exist'
    other = q['transactions'][index]
    if other.get('duplicate_of') or other.get('review_reason') or other['kind'] == 'unknown':
        return 'Duplicate target must be a terminal retained transaction'
    if (p['account_key'], p['currency'], p['currency_exponent']) != (q['account_key'], q['currency'], q['currency_exponent']):
        return 'Duplicate account/currency conflicts with target'
    from .alerts import movement_family
    if (row['amount_minor'], movement_family(row['kind']), row['date']) != (other['amount_minor'], movement_family(other['kind']), other['date']):
        return 'Duplicate financial evidence conflicts with target'
    shared_reference = row.get('reference') and row.get('reference') == other.get('reference')
    # Exact bytes plus physical source location proves the same occurrence.
    same_location = (p['source'].get('sha256') and p['source'].get('sha256') == q['source'].get('sha256') and
                     (row['page'], row['row']) == (other['page'], other['row']))
    if not (shared_reference or same_location):
        return 'Duplicate needs a shared source reference or identical document row; amount alone is insufficient'
    if shared_reference:
        for payload in (p, q):
            if sum(r.get('reference') == row['reference'] for r in payload['transactions']) != 1:
                return 'Duplicate reference is ambiguous within a statement'
    return None


def _section_assessment(record, all_records):
    p = record['payload']; c = p.get('coverage'); gaps = []
    counts = Counter(retained=0, duplicate_linked=0, review=0)
    if not p['account_resolved']: gaps.append('Account identity unresolved')
    if p['issues']: gaps.extend('Source extraction issue: ' + issue for issue in p['issues'])
    for row in p['transactions']:
        problem = duplicate_problem(record, row, all_records)
        counts['review' if problem or row.get('review_reason') or row['kind'] == 'unknown' else 'duplicate_linked' if row.get('duplicate_of') else 'retained'] += 1
        if problem: gaps.append(problem)
    counts['review'] += len(p.get('review_rows', []))
    if not c:
        gaps.append('Missing source manifest: page, section and row coverage evidence unavailable')
    else:
        if not p['source'].get('sha256'):
            gaps.append('Original document digest unavailable')
        if not p['complete']:
            gaps.append('Extractor reports incomplete source reading')
        section = next(s for s in c['sections'] if s['id'] == c['section_id'])
        if section.get('type') == 'balance_snapshot':
            gaps.append('Balance snapshot only; no transaction table or dated movements provided')
        gaps.extend(section.get('limitations', []))
        expected_pages = set(section['pages'])
        read = {v['page'] for v in c['pages'] if v['status'] == 'read'}
        if not expected_pages <= read:
            gaps.append('Unread or unenumerated section pages: ' + ', '.join(map(str, sorted(expected_pages - read))))
        related = [r for r in all_records if document_key(r['payload']) == document_key(p)]
        peers = [r for r in related if r['payload'].get('coverage', {}).get('section_id') == section['id']]
        if len(peers) != 1:
            gaps.append('Missing or repeated account/currency section: ' + section['id'])
        # Conflicting observations of the same bytes are an integrity failure,
        # unlike a sibling section's missing movements or independent checks.
        for peer in related:
            q = peer['payload']
            if q.get('coverage') and (manifest_key(q) != manifest_key(p) or q['source'].get('sha256') != p['source'].get('sha256')):
                gaps.append('Conflicting document manifest: ' + q['coverage']['section_id'])
        mapped = p['transactions'] + p.get('review_rows', [])
        if any(r['reason'] == 'Source inventory row has no extraction mapping' for r in p.get('review_rows', [])):
            gaps.append('Enumerated source rows missing from extraction; preserved as visible review mappings')
        ids = [r.get('source_row_id') for r in mapped]
        inventory = {r['id']: r for r in section['rows']}
        if len(ids) != len(set(ids)) or set(ids) != set(inventory):
            gaps.append('Source row mappings differ from enumerated inventory (missing, repeated or extra source rows)')
        for row in mapped:
            source_row = inventory.get(row.get('source_row_id'))
            if source_row and ((source_row['page'], source_row['row']) != (row['page'], row['row']) or
                               ('amount_minor' in source_row and source_row['amount_minor'] != row.get('amount_minor'))):
                gaps.append('Source row location/amount mismatch: ' + row['source_row_id'])
        # All available independent checks must survive deduplication unchanged.
        stated = {k: v['value'] for k, v in section['checks'].items() if v['status'] == 'stated'}
        if stated != p['checks']:
            gaps.append('Independent source checks omitted, changed, or invented')
        if not stated:
            gaps.append('No independently stated count, totals or balances available to reconcile')
        amounts = [r.get('amount_minor') for r in mapped]
        actual = {'expected_transaction_count': len(mapped)}
        if all(type(v) is int for v in amounts):
            actual.update(expected_debits_minor=sum(max(v, 0) for v in amounts), expected_credits_minor=-sum(min(v, 0) for v in amounts))
            if 'opening_balance_minor' in stated and 'closing_balance_minor' in stated:
                sign = -1 if p.get('account_type') == 'bank_account' else 1
                if stated['opening_balance_minor'] + sign * sum(amounts) != stated['closing_balance_minor']:
                    gaps.append('Independent opening/closing balances do not reconcile')
        else:
            gaps.append('Source row amounts unavailable; arithmetic cannot be verified')
        if ('opening_balance_minor' in stated) != ('closing_balance_minor' in stated):
            gaps.append('Independent balance pair unavailable')
        for key in CHECKS & set(actual) & set(stated):
            if actual[key] != stated[key]: gaps.append(key + ' does not reconcile against all source occurrences')
        if sum(counts.values()) != len(inventory):
            gaps.append('Source count is not the disjoint sum of retained, duplicate-linked and review mappings')
    return {'status': 'Section completeness not verified' if gaps else 'Section coverage complete',
            'verified': not gaps, 'gaps': list(dict.fromkeys(gaps)), 'source_row_count': len(section['rows']) if c else 0,
            'mapped_counts': dict(counts), 'scope': 'Selected account/currency section and observed source evidence only'}


def assess(record, all_records):
    """Keep document completeness distinct from a section's import eligibility."""
    section = _section_assessment(record, all_records)
    p = record['payload']; manifest = p.get('coverage')
    gaps = list(section['gaps'])
    if manifest:
        expected = set(range(1,manifest['page_count']+1))
        read = {page['page'] for page in manifest['pages'] if page['status']=='read'}
        if read != expected:
            gaps.append('Unread or unenumerated document pages: ' + ', '.join(map(str,sorted(expected-read))))
        related = [item for item in all_records if document_key(item['payload'])==document_key(p)]
        for observed in manifest['sections']:
            if observed.get('type') == 'balance_snapshot':
                gaps.append('Section '+observed['id']+': Balance snapshot only; movement history not provided')
                gaps.extend('Section '+observed['id']+': '+gap for gap in observed.get('limitations', []))
                continue
            peers = [item for item in related if item['payload'].get('coverage',{}).get('section_id')==observed['id']]
            if len(peers)!=1:
                gaps.append('Missing or repeated account/currency section: '+observed['id'])
            elif peers[0]['id']!=record['id']:
                checked = _section_assessment(peers[0],all_records)
                gaps.extend('Section '+observed['id']+': '+gap for gap in checked['gaps'])
    gaps=list(dict.fromkeys(gaps))
    return {'status':'Completeness not verified' if gaps else 'Source coverage complete',
            'verified':not gaps,'gaps':gaps,'section':{'id':manifest['section_id'] if manifest else None,**section},
            'section_count':len(manifest['sections']) if manifest else 0,
            'source_row_count':section['source_row_count'],'mapped_counts':section['mapped_counts'],
            'scope':'Identifiable retrieved document and observed source evidence only'}
