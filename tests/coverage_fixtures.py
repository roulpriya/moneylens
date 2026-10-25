"""Synthetic source observations. Never use for real extraction or runtime proof."""
import copy
import hashlib
CHECK_NAMES = {'expected_transaction_count','expected_debits_minor','expected_credits_minor','opening_balance_minor','closing_balance_minor'}


def source_evidence(payload, checks=None):
    """Snapshot fixture observations BEFORE exercising omissions/mutations.

    This helper represents a separately read synthetic source; production code
    never computes expected totals/row inventory from extraction results.
    """
    p = copy.deepcopy(payload)
    p['source'].setdefault('sha256', hashlib.sha256(('synthetic document '+p['source']['message_id']).encode()).hexdigest())
    for i, r in enumerate(p['transactions']): r.setdefault('source_row_id', 'tx-'+str(i))
    observations = copy.deepcopy(p['checks'] if checks is None else checks)
    pages = sorted({r['page'] for r in p['transactions']} or {1})
    section = {'id':p['account_key']+'-'+p['currency'], 'account_key':p['account_key'], 'currency':p['currency'],
               'pages':pages, 'evidence':'Synthetic document account/currency heading',
               'rows':[{'id':r['source_row_id'], 'page':r['page'], 'row':r['row'], 'amount_minor':r['amount_minor']} for r in p['transactions']],
               'checks':{key:({'status':'stated', 'value':observations[key], 'page':pages[0], 'origin':'source', 'evidence':'Synthetic printed '+key} if key in observations else {'status':'unavailable','reason':'Not printed on synthetic source'}) for key in CHECK_NAMES}}
    p['coverage']={'version':1, 'section_id':section['id'], 'page_count':max(pages),
                   'pages':[{'page':n,'status':'read','evidence':'Synthetic page inspected including all headings and tables'} for n in range(1,max(pages)+1)], 'sections':[section]}
    return p


def observed_statement(payload):
    """Complete synthetic source used by pre-contract regression journeys.

    Those tests construct the entire source table as their fixture. When no
    checks are specified, the fixture explicitly prints its transaction count.
    Missing-evidence tests use source_evidence directly or no manifest instead.
    """
    p = copy.deepcopy(payload)
    if not p['checks']: p['checks'] = {'expected_transaction_count': len(p['transactions'])}
    return source_evidence(p)
