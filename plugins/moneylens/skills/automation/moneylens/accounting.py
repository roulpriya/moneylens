"""Persist explicit accounting choices independently of original source evidence."""
import copy
from .ledger import date, require, text
from .store import get, put

DEFAULTS = {'category_treatments': {'Investment': 'investment', 'Investment withdrawal': 'investment_withdrawal'},
            'report_from': '', 'report_to': ''}
TREATMENTS = {'ordinary', 'investment', 'investment_withdrawal'}


def preferences(db, changes=None):
    saved = {**copy.deepcopy(DEFAULTS), **get(db, 'accounting_preferences', {})}
    if changes is None: return saved
    require(isinstance(changes, dict) and not set(changes) - set(DEFAULTS), 'Unsupported accounting preference fields')
    result = {**saved, **copy.deepcopy(changes)}
    mapping = result['category_treatments']
    require(isinstance(mapping, dict) and len(mapping) <= 1000, 'Invalid category treatments')
    for category, treatment in mapping.items():
        text(category, 'category', 80)
        require(isinstance(treatment, str) and treatment in TREATMENTS, 'Invalid accounting treatment')
    for field in ('report_from', 'report_to'):
        require(isinstance(result[field], str), 'Report bounds must be dates or empty strings')
        if result[field]: date(result[field])
    require(not (result['report_from'] and result['report_to']) or result['report_from'] <= result['report_to'], 'Report date range reversed')
    put(db, 'accounting_preferences', result)
    return result


def decorate(db, records):
    """Only explicit bank category decisions establish investment treatment.

    No guessed counterpart, ownership assertion, principal/interest split, or
    change to kind, amount, date, category or source is involved.
    """
    mapping = preferences(db)['category_treatments']
    for record in records:
        for row in record['payload']['transactions']:
            treatment = mapping.get(row['category'], 'ordinary') if record['payload']['account_type'] == 'bank_account' else 'ordinary'
            row['accounting_treatment'] = treatment
            if treatment != 'ordinary':
                row['excluded_from_spending'] = True
                row['excluded_from_income'] = True
                row['accounting_reason'] = 'Investment principal movement; included in bank cashflow, excluded from spending and ordinary income'
    return records
