"""Stable mailbox and financial-account identity shared by all import paths."""
from .ledger import require


def mailboxes(config):
    return config['mailboxes']


def mailbox_id(config, value=None):
    boxes = mailboxes(config)
    require(isinstance(value, str), 'A configured mailbox ID is required')
    matches = [b['id'] for b in boxes if value == b['id'] or value.casefold() == b['address'].casefold()]
    require(len(matches) == 1, 'Mailbox must match one configured source identity')
    return matches[0]


def bank_accounts(config):
    return config.get('bank_accounts', [])


def require_configured(config):
    """Require confirmed identities for supplied financial sources, independent of PDF readiness."""
    require(config and (config.get('cards') or bank_accounts(config)), 'Configure and confirm accounts before processing supplied sources')


def validate_source(config, payload):
    mid = mailbox_id(config, payload['source']['mailbox'])
    require(mid == payload['source']['mailbox'], 'Use the stored stable mailbox ID in source.mailbox')
    candidates = config['cards'] + bank_accounts(config)
    account = next((c for c in candidates if c['account_key'] == payload['account_key']), None)
    require(account is not None, 'Account identity needs setup confirmation')
    require(mid in account.get('mailbox_ids', [b['id'] for b in mailboxes(config)]), 'Account is not confirmed for this mailbox')

    expected_type = 'credit_card' if account in config['cards'] else 'bank_account'
    require(payload.get('account_type') == expected_type, 'Source account type must match the confirmed account')
    for row in payload.get('transactions', []):
        if row.get('own_account_key'):
            require(row['own_account_key'] != account['account_key'] and any(c['account_key'] == row['own_account_key'] for c in candidates), 'Own-transfer counterparty must be another confirmed account')
