#!/usr/bin/env python3
"""Parse observed bank email layouts into MoneyLens alerts; never execute email HTML."""
import argparse
from collections import Counter
from datetime import datetime
from decimal import Decimal
from email.utils import parseaddr
import json
from pathlib import Path
import re
import sys
import tempfile
from ledger import connect, default_dir, hash_value, require
from alerts import ingest, report_records, similar
from ledger import records
from runtime_state import get, put


def minor(value):
    result = Decimal(value.replace(',', '')) * 100
    require(result == result.to_integral_value(), 'Amount has unsupported precision')
    return int(result)


def transaction_date(value):
    value = re.sub(r'\s+', ' ', value.strip())
    for pattern in ('%d-%m-%y', '%d-%m-%Y', '%d/%m/%Y', '%b %d, %Y', '%d %b, %Y', '%d-%b-%Y'):
        try:
            return datetime.strptime(value, pattern).date().isoformat()
        except ValueError:
            pass
    raise ValueError('Unrecognized transaction date')


def category(merchant):
    for pattern, label in [(r'grocery|market|fresh|bigbasket', 'Groceries'), (r'cafe|coffee|swiggy|zomato|restaurant', 'Dining'),
                           (r'uber|metro|fuel|taxi', 'Transport'), (r'netflix|spotify|apple|anthropic|openai', 'Subscriptions'),
                           (r'pharmacy|clinic', 'Health'), (r'hotel|airline|flight', 'Travel')]:
        if re.search(pattern, merchant, re.I):
            return label
    return 'Other'


def parse_message(message):
    sender = parseaddr(message['from'])[1].lower()
    domain = sender.rsplit('@', 1)[-1]
    banks = {'hdfcbank.bank.in': 'HDFC Bank', 'hdfcbank.net': 'HDFC Bank', 'hdfcbank.com': 'HDFC Bank',
             'icici.bank.in': 'ICICI Bank', 'icicibank.com': 'ICICI Bank'}
    if domain not in banks or not message.get('authenticated'):
        return None, 'Not an authenticated supported bank notification'
    body = re.sub(r'\s+', ' ', message['body'])
    subject = message['subject'].lower()
    if re.search(r'\b(?:declined|unsuccessful|otp|one.time.password|authorization hold)\b', subject):
        return None, 'Not a completed transaction'
    issuer = banks[domain]
    money = r'([\d,]+\.\d{2})'
    info = None
    # An explicit successful bank debit or credit, not a generic mention in a footer.
    m = re.search(r'Rs\.?\s*'+money+r'\s+(?:is|has been)\s+(?:successfully\s+)?(debited|credited)\s+(?:from|to) your (?:HDFC Bank )?account ending (?:in )?(\d{4})(.*)', body, re.I)
    if m and re.search(r'UPI (?:transaction )?reference', body, re.I):
        amount, direction, last4, rest = m.groups()
        date_match = re.search(r'(?:\bon\s+|Date:\s*)(\d{2}-\d{2}-\d{2,4})', rest, re.I)
        ref_match = re.search(r'UPI (?:transaction )?reference (?:number|no\.?)\s*:?\s*(\d{6,})', body, re.I)
        merchant = re.search(r'towards VPA\s+\S+\s*\((.*?)\)\s+on\b', rest, re.I)
        if not merchant:
            merchant = re.search(r'Sender:\s*(.*?)\s*\(VPA:', rest, re.I)
        if not merchant:
            merchant = re.search(r'towards VPA\s+(\S+)', rest, re.I)
        require(date_match and ref_match and merchant, 'UPI notification is missing movement evidence')
        info = {'account_type': 'bank_account', 'last4': last4, 'issuer': issuer, 'currency': 'INR',
                'date': transaction_date(date_match[1]), 'merchant': merchant[1].strip(), 'amount_minor': minor(amount)*(1 if direction.lower()=='debited' else -1),
                'kind': 'upi_debit' if direction.lower()=='debited' else 'upi_credit', 'channel': 'upi', 'reference': ref_match[1]}
    elif 'upi txn' in subject and ('credit card' in body.lower()):
        m = re.search(r'Rs\.?\s*'+money+r'\s+(?:is|has been)\s+(debited|credited)\s+(?:from|to) your (?:HDFC Bank )?(?:RuPay )?Credit Card\s*\(?ending\s+(\d{4})\)?(.*)', body, re.I)
        require(m, 'Unrecognized successful UPI card notification')
        amount, direction, last4, rest = m.groups()
        date_match = re.search(r'(?:\bon\s+|Date:\s*)(\d{2}-\d{2}-\d{2,4})', rest, re.I)
        merchant = re.search(r'towards VPA\s+\S+\s*\((.*?)\)\s+on\b', rest, re.I) or re.search(r'Paid to\s+(.*?)\s+Date:', rest, re.I) or re.search(r'towards VPA\s+(\S+)', rest, re.I)
        ref_match = re.search(r'UPI (?:transaction )?reference (?:number|no\.?)\s*:?\s*(\d{6,})', body, re.I)
        require(date_match and merchant and ref_match, 'UPI card notification is missing movement evidence')
        info = {'account_type': 'credit_card', 'last4': last4, 'issuer': issuer, 'currency': 'INR', 'date': transaction_date(date_match[1]),
                'merchant': merchant[1].strip(), 'amount_minor': minor(amount)*(1 if direction.lower()=='debited' else -1),
                'kind': 'purchase' if direction.lower()=='debited' else 'refund', 'channel': 'upi', 'reference': ref_match[1]}
    elif subject == 'transaction alert for your icici bank credit card':
        m = re.search(r'Credit Card\s+[Xx* ]*(\d{4})\s+has been used for a transaction of\s+([A-Z]{3})\s+'+money+r'\s+on\s+(.*?)\s+at\s+\d{2}:\d{2}:\d{2}\.\s*Info:\s*(.*?)\.\s+The Available', body, re.I)
        require(m, 'Unrecognized ICICI card transaction')
        last4, currency, amount, when, merchant = m.groups()
        info = {'account_type': 'credit_card', 'last4': last4, 'issuer': issuer, 'currency': currency.upper(), 'date': transaction_date(when), 'merchant': merchant, 'amount_minor': minor(amount), 'kind': 'purchase', 'channel': 'card'}
    elif subject == 'a payment was made using your credit card':
        m = re.search(r'Rs\.?\s*'+money+r'\s+has been debited from your HDFC Bank Credit Card ending\s+(\d{4})\s+towards\s+(.*?)\s+on\s+(.*?)\s+at\s+\d{2}:\d{2}:\d{2}', body, re.I)
        require(m, 'Unrecognized HDFC card transaction')
        amount, last4, merchant, when = m.groups()
        info = {'account_type': 'credit_card', 'last4': last4, 'issuer': issuer, 'currency': 'INR', 'date': transaction_date(when), 'merchant': merchant, 'amount_minor': minor(amount), 'kind': 'purchase', 'channel': 'card'}
    elif subject.startswith('payment received on your icici bank credit card'):
        m = re.search(r'received payment of INR\s+'+money+r'\s+on your ICICI Bank Credit Card account\s+[\dXx* ]*(\d{4})\s+on\s+(\d{2}-[A-Za-z]{3}-\d{4})', body, re.I)
        require(m, 'Unrecognized card repayment')
        amount, last4, when = m.groups()
        info = {'account_type': 'credit_card', 'last4': last4, 'issuer': issuer, 'currency': 'INR', 'date': transaction_date(when), 'merchant': 'Payment received', 'amount_minor': -minor(amount), 'kind': 'payment', 'channel': 'card'}
    elif 'standing instruction' in subject:
        return None, 'Secondary standing-instruction notification; needs correlation to the direct debit, not another spending row'
    else:
        return None, 'Not a supported successful transaction notification'
    return info, None


def process(db, messages, include_upi):
    config = get(db, 'config')
    require(config and config['ready'], 'Complete setup before importing transaction notifications')
    accounts = list(config['cards'])
    upi_accounts = config.setdefault('upi_accounts', [])
    outcomes, counts = [], Counter()
    existing = {}
    for (raw,) in db.execute('SELECT payload FROM alerts'):
        p = json.loads(raw); existing.setdefault(p['source']['message_id'], []).append(p)
    for message in messages:
        try:
            event, reason = parse_message(message)
            if event is None:
                outcome = {'id': message['id'], 'result': 'excluded', 'reason': reason}
                if 'Secondary standing-instruction' in reason:
                    body = re.sub(r'\s+', ' ', message['body'])
                    notice = re.search(r'payment of ([A-Z]{3})\s+([\d,]+\.\d{2}) towards (.*?), with Standing Instruction .*?, on (\d{2}/\d{2}/\d{4}), through your ICICI Bank Credit Card (\d{4})', body, re.I)
                    possible = []
                    if notice:
                        currency, amount, merchant, when, last4 = notice.groups()
                        account = next((c for c in accounts if c['last4']==last4 and c['issuer'].startswith('ICICI')), None)
                        if account:
                            date_value = transaction_date(when)
                            for statement in records(db):
                                q = statement['payload']
                                if statement['status']!='imported' or q['account_key']!=account['account_key'] or not(q['period_start']<=date_value<=q['period_end']):continue
                                for index, row in enumerate(q['transactions']):
                                    probe = {'date':date_value,'merchant':merchant,'amount_minor':row['amount_minor'],'kind':'purchase'}
                                    if row['kind']=='purchase' and similar(probe,row):possible.append((statement['id'],index))
                    if len(possible)==1:
                        outcome={'id':message['id'],'result':'correlated_notice','reason':'Secondary payment receipt is covered by a unique saved statement merchant/date entry','statement_id':possible[0][0],'row':possible[0][1]}
                    else:
                        outcome={'id':message['id'],'result':'needs_review','reason':'Secondary receipt needs correlation; no extra spending row created'}
            else:
                bank_account = event['account_type'] == 'bank_account'
                if bank_account and not include_upi:
                    raise ValueError('UPI bank-account scope was not enabled')
                candidates = upi_accounts if bank_account else accounts
                card = next((c for c in candidates if c['last4']==event['last4'] and c['issuer'].split()[0].lower()==event['issuer'].split()[0].lower()), None)
                if card is None and bank_account:
                    card = {'account_key': hash_value([config['mailbox'], event['issuer'], 'bank_account', event['last4']]), 'issuer': event['issuer'],
                            'last4': event['last4'], 'account_label': event['issuer']+' account · '+event['last4'], 'source_message_id': message['id']}
                    upi_accounts.append(card)
                require(card is not None, 'Card identity needs setup confirmation')
                source = {'mailbox': config['mailbox'], 'message_id': message['id'], 'filename': 'email-body'}
                row = {k: event[k] for k in ('date','merchant','amount_minor','kind','channel')}
                row.update(category='UPI receipts' if row['kind']=='upi_credit' else category(row['merchant']), page=1, row='body:1')
                if event.get('reference'): row['reference']=event['reference']
                # Retain an already processed source's row identity and review category.
                for previous in existing.get(message['id'], []):
                    old = previous['transactions'][0]
                    if old['amount_minor']==row['amount_minor'] and old['date']==row['date'] and previous['currency']==event['currency']:
                        source=previous['source']; row['row']=old['row']; row['page']=old['page']; row['category']=old['category']
                        break
                payload = {'source': source, 'account_key': card['account_key'], 'account_label': card.get('account_label', card['issuer']+' · '+card['last4']),
                           'issuer': card['issuer'], 'account_type': event['account_type'], 'period_start': row['date'], 'period_end': row['date'],
                           'currency': event['currency'], 'currency_exponent': 2, 'complete': True, 'issues': [], 'checks': {}, 'transactions': [row]}
                with tempfile.NamedTemporaryFile(mode='w',suffix='.json',delete=False,encoding='utf-8') as stream:
                    temp=Path(stream.name); json.dump(payload,stream)
                try: outcome={'id':message['id'], **ingest(db,temp)}
                finally: temp.unlink(missing_ok=True)
            outcome['message_id'] = message['id']
            counts[outcome['result']]+=1; outcomes.append(outcome)
            if outcome['result']!='excluded':
                db.execute('INSERT OR REPLACE INTO source_dispositions VALUES (?,?)',(message['id'],json.dumps(outcome)))
        except (ValueError, KeyError, TypeError) as error:
            outcomes.append({'id':message['id'],'message_id':message['id'],'result':'needs_review','reason':str(error)}); counts['needs_review']+=1
    put(db,'config',config)
    return {'counts':dict(counts),'upi_accounts':len(upi_accounts),'outcomes':outcomes}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-dir',type=Path,default=default_dir());parser.add_argument('--input',type=Path,required=True)
    parser.add_argument('--include-upi',action='store_true');parser.add_argument('--outcomes',type=Path)
    args=parser.parse_args();messages=json.loads(args.input.read_text())
    db=connect(args.data_dir)
    try:
        db.execute('BEGIN IMMEDIATE');result=process(db,messages,args.include_upi);db.commit()
        if args.outcomes:
            args.outcomes.write_text(json.dumps(result));args.outcomes.chmod(0o600)
        print(json.dumps({k:v for k,v in result.items() if k!='outcomes'}))
    finally: db.close()


if __name__=='__main__': main()
