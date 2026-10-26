#!/usr/bin/env python3
"""Evidence-backed exclusions for transfers between the user's confirmed accounts."""
import json
from .ledger import require, text
from .accounts import bank_accounts


def confirm(db, record_id, index, counterparty, evidence):
    from .store import get
    from .personalize import evidence_key
    config = get(db, 'config', {})
    owned = {a['account_key'] for a in config.get('cards', []) + bank_accounts(config)}
    source = None
    for table in ('statements', 'alerts'):
        found = db.execute(f'SELECT payload FROM {table} WHERE id=?', (record_id,)).fetchone()
        if found: source = json.loads(found[0]); break
    require(source is not None, 'Transfer source record not found')
    require(0 <= index < len(source['transactions']), 'Transfer row out of bounds')
    require(source['account_key'] in owned and counterparty in owned and counterparty != source['account_key'], 'Transfer must involve two distinct confirmed own accounts')
    row = source['transactions'][index]
    require(row['amount_minor'] != 0 and row['kind'] not in {'unknown', 'fee', 'interest'}, 'Resolve the movement before confirming a transfer')
    db.execute('INSERT OR REPLACE INTO transfer_exclusions VALUES (?,?,?,?)',
               (record_id, evidence_key(row), counterparty, text(evidence, 'Ownership/transfer confirmation', 1000)))


def decorate(db, records):
    from .store import get
    from .personalize import evidence_key
    config = get(db, 'config', {})
    owned = {a['account_key'] for a in config.get('cards', []) + bank_accounts(config)}
    edits = {(sid, key): (account, evidence) for sid, key, account, evidence in db.execute('SELECT * FROM transfer_exclusions')}
    indexed, candidates = {}, []
    def exclude(row, counterparty, evidence):
        row.update(excluded_from_spending=True, exclusion_reason='Own-account transfer',
                   own_account_key=counterparty, transfer_evidence=evidence)
    def owned_pair(account, counterparty, evidence):
        return account in owned and counterparty in owned and account != counterparty and bool(evidence)
    for record in records:
        p = record['payload']
        for index, row in enumerate(p['transactions']):
            indexed[(record['id'], index)] = row
            key = (record['id'], evidence_key(row))
            if key in edits:
                account, evidence = edits[key]
                if owned_pair(p['account_key'], account, evidence):
                    exclude(row, account, evidence)
            elif row['kind'] in {'transfer_in', 'transfer_out'} and owned_pair(p['account_key'], row.get('own_account_key'), row.get('transfer_evidence')):
                exclude(row, row['own_account_key'], row['transfer_evidence'])
            # Automatic pairing requires a shared bank reference and both owned accounts.
            if (not row.get('duplicate_of') and p.get('account_type') == 'bank_account' and p['account_key'] in owned and
                    record['status'] in {'imported', 'posted', 'provisional'} and
                    not record.get('validation', {}).get('issues') and not p['issues'] and p['complete'] and p['account_resolved'] and
                    row['kind'] in {'debit', 'credit', 'transfer_in', 'transfer_out'} and row.get('reference') and row['amount_minor']):
                candidates.append((p, row))
    matches = {}
    for p, row in candidates:
        peers = [(q, other) for q, other in candidates if q['account_key'] != p['account_key'] and
                 q['currency'] == p['currency'] and other['amount_minor'] == -row['amount_minor'] and
                 other['reference'] == row['reference']]
        matches[id(row)] = peers
    for p, row in candidates:
        peers = matches[id(row)]
        if len(peers) == 1 and len(matches[id(peers[0][1])]) == 1:
            exclude(row, peers[0][0]['account_key'], 'Unique opposite movements in two confirmed own bank accounts with the same bank reference')
    # A confirmed alert exclusion follows its authoritative statement replacement.
    for record in records:
        target = indexed.get(tuple(record.get('matched_to') or ()))
        if target is not None:
            row = record['payload']['transactions'][0]
            if row.get('excluded_from_spending'):
                exclude(target, row['own_account_key'], row['transfer_evidence'])
    return records
