"""Local account configuration and accounting outcomes; no collection lifecycle."""
import datetime as dt
import json
from pathlib import Path
from zoneinfo import ZoneInfo
from .ledger import default_dir, hash_value, require, text
from .accounts import mailboxes, bank_accounts


def get(db, key, default=None):
    row = db.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    return json.loads(row[0]) if row else default


def put(db, key, value):
    db.execute("INSERT OR REPLACE INTO settings VALUES (?,?)", (key, json.dumps(value)))


def config_validated(payload):
    allowed = {'mailboxes', 'timezone', 'report_path', 'cards', 'bank_accounts', 'credential_method', 'ready'}
    require(isinstance(payload, dict) and not set(payload) - allowed, 'Unsupported account settings fields; use the public-release schema')
    p = json.loads(json.dumps(payload))
    boxes = p.get('mailboxes')
    require(isinstance(boxes, list) and boxes, 'mailboxes must be a nonempty list')
    ids, addresses = [], []
    for box in boxes:
        require(isinstance(box, dict) and not set(box) - {'id', 'address', 'verified_at', 'connector_account_id'}, 'Unsupported mailbox fields')
        for key in ('id', 'address'): box[key] = text(box.get(key), key)
        if 'verified_at' in box: dt.datetime.fromisoformat(text(box['verified_at'], 'verified_at'))
        if 'connector_account_id' in box: box['connector_account_id'] = text(box['connector_account_id'], 'connector_account_id')
        ids.append(box['id']); addresses.append(box['address'].casefold())
    require(len(ids) == len(set(ids)) and len(addresses) == len(set(addresses)), 'Mailbox identities and addresses must be unique')
    if p.get('timezone') is not None:ZoneInfo(text(p['timezone'],'timezone'))
    p.setdefault('report_path', str(default_dir() / 'report.html'))
    require(isinstance(p['report_path'], str) and Path(p['report_path']).is_absolute() and Path(p['report_path']).suffix.lower() == '.html', 'report_path must be an absolute HTML path')
    p.setdefault('credential_method', 'private-file')
    require(p['credential_method'] == 'private-file', 'credential_method must be private-file')
    p.setdefault('cards', []); p.setdefault('bank_accounts', [])
    require(isinstance(p['cards'], list) and isinstance(p['bank_accounts'], list), 'cards and bank_accounts must be lists')
    require(p['cards'] or p['bank_accounts'], 'At least one confirmed account is required')
    keys = []
    fields = {'account_key','issuer','masked_identifier','account_label','mailbox_ids','identity','identity_evidence',
              'credential_scope','password_status','verified_at','alerts_only'}
    for collection in ('cards', 'bank_accounts'):
        for account in p[collection]:
            extras = {'network','product','holder_label'} if collection == 'cards' else {'source_message_id','statement_enabled'}
            require(isinstance(account, dict) and not set(account) - fields - extras, 'Unsupported account fields')
            for key in ('account_key','account_label'):account[key]=text(account.get(key),key)
            for key in ('issuer','masked_identifier'):
                if account.get(key) is not None:account[key]=text(account[key],key,128)
            account.setdefault('mailbox_ids', ids[:])
            require(isinstance(account['mailbox_ids'],list) and account['mailbox_ids'] and set(account['mailbox_ids']) <= set(ids), 'Account mailbox IDs must be configured')
            for key in ('identity','identity_evidence','account_label','network','product','holder_label','source_message_id'):
                if key in account: account[key] = text(account[key], key, 1000)
            require(type(account.get('alerts_only',False)) is bool, 'alerts_only must be boolean')
            if collection == 'bank_accounts':
                account['account_label'] = text(account.get('account_label'),'account_label')
                account.setdefault('statement_enabled',False)
                require(type(account['statement_enabled']) is bool,'statement_enabled must be boolean')
            needs_pdf = collection == 'cards' or account['statement_enabled']
            if needs_pdf:
                account['credential_scope'] = text(account.get('credential_scope'),'credential_scope')
                require(account.get('password_status') in {'verified','not_required','unverified'}, 'Invalid password_status')
                if account['password_status'] == 'verified': dt.datetime.fromisoformat(text(account.get('verified_at'),'verified_at'))
            keys.append(account['account_key'])
    require(len(keys) == len(set(keys)), 'Duplicate account keys')
    pdf_accounts = p['cards'] + [a for a in p['bank_accounts'] if a['statement_enabled']]
    p['ready'] = all(a.get('alerts_only',False) or a['password_status'] in {'verified','not_required'} for a in pdf_accounts)
    return p


def source_key(source, qualifier=None):
    identity = [source.get('mailbox'), source['message_id'], source.get('attachment_id') or source.get('filename') or '']
    if qualifier is not None: identity.append(qualifier)
    return hash_value(identity)[:24]


def record_outcome(db, source, outcome, qualifier=None):
    """Save an accounting result for supplied content, never enqueue collection."""
    key = source_key(source, qualifier)
    saved = {**outcome, 'key': key, 'mailbox_id': source.get('mailbox'),
             'message_id': source['message_id'], 'attachment_id': source.get('attachment_id') or '',
             'filename': source.get('filename')}
    if qualifier is not None:
        saved['qualifier'] = qualifier
        # A document result is superseded by its account/currency section results.
        db.execute('DELETE FROM processing_results WHERE source_key=?', (source_key(source),))
    db.execute('INSERT OR REPLACE INTO processing_results VALUES (?,?)', (key, json.dumps(saved)))
    return key


def reviews(db):
    """Return unresolved outcomes of supplied accounting inputs."""
    pending = []
    for (raw,) in db.execute('SELECT payload FROM processing_results ORDER BY source_key'):
        item = json.loads(raw)
        if item['result'] == 'needs_review' or item.get('issues'):
            item.setdefault('reason','; '.join(item.get('issues',[])) or 'Source requires review')
            pending.append(item)
    return pending


def save_config(db, payload):
    old = get(db, 'config', {})
    if isinstance(payload, dict) and 'report_path' not in payload:
        database = next(row[2] for row in db.execute('PRAGMA database_list') if row[1] == 'main')
        payload = {**payload, 'report_path': old.get('report_path') or str(Path(database).resolve().parent / 'report.html')}
    config = config_validated(payload)
    if old:
        require({b['id'] for b in mailboxes(old)} <= {b['id'] for b in mailboxes(config)}, 'Preserve configured mailboxes and their stable identities')
        for box in mailboxes(old):
            updated = next(b for b in mailboxes(config) if b['id'] == box['id'])
            require(updated['address'].casefold() == box['address'].casefold(), 'A stable mailbox identity cannot be reassigned')
        previous = old['cards'] + bank_accounts(old)
        updated = config['cards'] + bank_accounts(config)
        require({a['account_key'] for a in previous} <= {a['account_key'] for a in updated}, 'Preserve previously confirmed accounts')
        for collection in ('cards','bank_accounts'):
            require({a['account_key'] for a in old[collection]} <= {a['account_key'] for a in config[collection]},
                    'A stable account key cannot change its account type')
        for account in previous:
            replacement = next(a for a in updated if a['account_key'] == account['account_key'])
            require((not account.get('masked_identifier') or replacement.get('masked_identifier')==account['masked_identifier']) and
                    (not account.get('identity') or replacement.get('identity') == account['identity']),
                    'A stable account key cannot be reassigned to a different account')
    put(db, 'config', config)
    return config
