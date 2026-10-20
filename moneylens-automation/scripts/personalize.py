#!/usr/bin/env python3
"""Private user categorization rules and transaction notes; source rows stay intact."""
import argparse
import copy
import json
from pathlib import Path
import re
import sqlite3
import sys

from ledger import connect, default_dir, hash_value, integer, require, row_key, text


def evidence_key(row):
    return hash_value([row_key(row), row['page'], row['row']])


def rules(db):
    result = db.execute("SELECT value FROM runtime_meta WHERE key='personal_rules'").fetchone()
    return json.loads(result[0]) if result else []


def validate_rules(items):
    require(isinstance(items, list) and len(items) <= 200, 'Rules must be a list of at most 200 entries')
    ids = set()
    for rule in items:
        require(isinstance(rule, dict) and not set(rule) - {'id', 'label', 'category', 'note', 'when'}, 'Unexpected rule fields')
        for key in ('id', 'label', 'category'):
            rule[key] = text(rule.get(key), key, 120 if key != 'category' else 80)
        require(rule['id'] not in ids, 'Rule IDs must be unique')
        ids.add(rule['id'])
        rule['note'] = text(rule.get('note'), 'rule note', 2000)
        condition = rule.get('when')
        allowed = {'merchant_contains', 'merchant_contains_all', 'merchant_excludes', 'name_like', 'category_in', 'channel', 'kinds', 'currency', 'amount_eq', 'amount_gt', 'amount_lte'}
        require(isinstance(condition, dict) and condition and not set(condition) - allowed, 'Invalid rule conditions')
        for key, value in condition.items():
            if key in {'merchant_contains', 'merchant_contains_all', 'merchant_excludes', 'category_in', 'kinds'}:
                require(isinstance(value, list) and value and all(isinstance(v, str) and v.strip() for v in value), key + ' must be a nonempty text list')
            elif key == 'name_like':
                require(type(value) is bool, 'name_like must be boolean')
            elif key.startswith('amount_'):
                require(integer(value, key) >= 0, 'Rule amounts must be nonnegative minor units')
            else:
                text(value, key, 80)
        require(not any(k.startswith('amount_') for k in condition) or 'currency' in condition, 'Amount rules require a currency')
    return items


def name_like(merchant):
    """Conservative shape filter for a user-authorized assumption, not identity proof."""
    business = r'\b(shop|store|mall|company|limited|ltd|pvt|private|retail|market|beverages|vending|railways|funds|autopay|committee|development|collection|payments|bank|hotel|cafe|restaurant|hospital|clinic|wellness|test)\b'
    return (any(ch.isalpha() for ch in merchant) and
            all(ch.isalpha() or ch in " .'-" for ch in merchant) and
            not re.search(business, merchant, re.I))


def matches(rule, row, payload):
    c = rule['when']
    merchant = row['merchant'].casefold()
    # A rule's list of merchant names is an OR; separate conditions are AND.
    if 'merchant_contains' in c and not any(v.casefold() in merchant for v in c['merchant_contains']): return False
    if not all(v.casefold() in merchant for v in c.get('merchant_contains_all', [])): return False
    if any(v.casefold() in merchant for v in c.get('merchant_excludes', [])): return False
    if 'name_like' in c and name_like(row['merchant']) != c['name_like']: return False
    if 'category_in' in c and row['category'] not in c['category_in']: return False
    channel = row.get('channel', 'upi' if payload.get('account_type') == 'bank_account' or re.match(r'^(?:EMI\s+)?UPI\b', row['merchant'], re.I) else 'card')
    if 'channel' in c and channel != c['channel']: return False
    if 'kinds' in c and row['kind'] not in c['kinds']: return False
    if 'currency' in c and payload['currency'] != c['currency']: return False
    amount = abs(row['amount_minor'])
    return (('amount_eq' not in c or amount == c['amount_eq']) and
            ('amount_gt' not in c or amount > c['amount_gt']) and
            ('amount_lte' not in c or amount <= c['amount_lte']))


def decorate(db, records):
    """Apply private context to a copy, after reconciliation. Never change financial identity."""
    result = copy.deepcopy(records)
    personal_rules = rules(db)
    edits = {(sid, key): category for sid, key, category in db.execute('SELECT statement_id,evidence_key,category FROM category_edits')}
    annotations = {(sid, key): (category, note) for sid, key, category, note in db.execute('SELECT record_id,evidence_key,category,note FROM transaction_annotations')}
    indexed = {}
    for record in result:
        for i, row in enumerate(record['payload']['transactions']):
            key = (record['id'], evidence_key(row))
            row['original_category'] = row['category']
            row['category_origin'] = 'source'
            for rule in personal_rules:
                if row['kind'] != 'payment' and matches(rule, row, record['payload']):
                    row.update(category=rule['category'], personal_context=rule['note'], category_origin='personal_rule', rule_id=rule['id'])
                    break
            if key in edits:
                row.update(category=edits[key], category_origin='user')
                row.pop('personal_context', None)
                row.pop('rule_id', None)
            category, note = annotations.get(key, (None, None))
            if category is not None:
                row.update(category=category, category_origin='user')
                row.pop('personal_context', None)
                row.pop('rule_id', None)
            if note is not None: row['note'] = note
            indexed[(record['id'], i)] = row
    # Notes/corrections on an alert survive its replacement by a statement row.
    for record in result:
        target = indexed.get(tuple(record.get('matched_to') or ()))
        if target is None: continue
        row = record['payload']['transactions'][0]
        if target['category_origin'] != 'user' and (row['category_origin'] == 'user' or (target['category'] == 'Other' and row['category_origin'] == 'personal_rule')):
            for field in ('category', 'category_origin', 'personal_context', 'rule_id'):
                if field in row: target[field] = row[field]
                else: target.pop(field, None)
        if row.get('note') and not target.get('note'): target['note'] = row['note']
    return result


def annotate(db, record_id, index, category=None, note=None):
    require(category is not None or note is not None, 'Supply a category or note')
    found = None
    for table in ('statements', 'alerts'):
        found = db.execute(f'SELECT payload FROM {table} WHERE id=?', (record_id,)).fetchone()
        if found: break
    require(found is not None, 'Transaction record not found')
    rows = json.loads(found[0])['transactions']
    require(0 <= index < len(rows), 'Row index out of bounds')
    if category is not None:
        category = text(category, 'category', 80)
        require(rows[index]['kind'] != 'payment' or category == 'Credit card payments', 'Payments retain their accounting category')
    if note is not None:
        require(isinstance(note, str) and len(note) <= 2000, 'Notes must be text of at most 2000 characters')
        note = note.strip()
    key = evidence_key(rows[index])
    old = db.execute('SELECT category,note FROM transaction_annotations WHERE record_id=? AND evidence_key=?', (record_id, key)).fetchone() or (None, None)
    db.execute('INSERT OR REPLACE INTO transaction_annotations VALUES (?,?,?,?)', (record_id, key, category if category is not None else old[0], note if note is not None else old[1]))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-dir', type=Path, default=default_dir())
    sub = parser.add_subparsers(dest='command', required=True)
    p = sub.add_parser('rules', help='Replace personal rules, in first-match priority order')
    p.add_argument('--input', type=Path, required=True)
    sub.add_parser('show', help='Show private personal rules')
    p = sub.add_parser('annotate', help='Add a note and/or category to one statement or alert row')
    p.add_argument('--record', required=True)
    p.add_argument('--row', type=int, required=True)
    p.add_argument('--note')
    p.add_argument('--category')
    args = parser.parse_args()
    db = connect(args.data_dir)
    try:
        with db:
            if args.command == 'rules':
                require(args.input.stat().st_size <= 1024 * 1024, 'Rules file exceeds 1 MiB')
                items = validate_rules(json.loads(args.input.read_text()))
                db.execute("INSERT OR REPLACE INTO runtime_meta VALUES ('personal_rules',?)", (json.dumps(items),))
                result = {'result': 'rules_saved', 'count': len(items)}
            elif args.command == 'show': result = rules(db)
            else:
                annotate(db, args.record, args.row, args.category, args.note)
                result = {'result': 'annotation_saved', 'record': args.record, 'row': args.row}
        print(json.dumps(result, ensure_ascii=False))
    finally: db.close()


if __name__ == '__main__':
    try: main()
    except (ValueError, OSError, sqlite3.Error, KeyError, TypeError) as exc:
        print(json.dumps({'error': str(exc)}), file=sys.stderr)
        sys.exit(1)
