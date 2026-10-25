"""Accounting accepts agent-classified payment channels without parsing notifications."""
from pathlib import Path
import sys
import tempfile
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'skills/automation'))
from moneylens.ledger import connect, normalize
from moneylens.store import config_validated, save_config
from moneylens.transactions import add
from test_ledger import fixture


class PaymentChannelTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.db=connect(self.root);self.addCleanup(self.db.close)
        self.config={'mailboxes': [{'id':'source-a','address':'source@example.invalid'}], 'cards': [{'account_label':'Synthetic account','account_key':'card-a','issuer':'Unlisted issuer','masked_identifier':'1234','credential_scope':'scope','password_status':'not_required'}], 'bank_accounts': [{'account_key':'bank-a','issuer':'Another issuer','masked_identifier':'5678','account_label':'Savings'}]}
        with self.db:save_config(self.db,self.config)

    def movement(self, amount, kind, account='bank-a', account_type='bank_account'):
        return add(self.db,'Agent supplied description',amount,'2026-10-24','Other',account=account,extra={
            'source':{'mailbox':'source-a','message_id':kind},'channel':'Local network / Ω',
            'account_type':account_type,'reference':'observed-'+kind}, currency_exponent=2, kind=kind, currency='INR')

    def test_debit_uses_supplied_account_channel_and_reference(self):
        with self.db:row=self.movement('125','debit')
        self.assertEqual((row['account'],row['amount_minor'],row['status']),('bank-a',12500,'provisional'))
        self.assertEqual(row['metadata']['reference'],'observed-debit')

    def test_credit_is_incoming_without_inventing_refund(self):
        with self.db:row=self.movement('-250','credit')
        self.assertEqual(row['amount_minor'],-25000)
        self.assertEqual(row['kind'],'credit')

    def test_card_backed_payment_uses_supplied_card_key(self):
        with self.db:row=self.movement('125','purchase','card-a','credit_card')
        self.assertEqual(row['account'],'card-a');self.assertEqual(row['metadata']['channel'],'Local network / Ω')

    def test_description_does_not_determine_channel(self):
        p=fixture(account_type='bank_account')
        p['transactions'][0]['merchant']='EMI UPI bank text'
        self.assertEqual(normalize(p)['transactions'][0]['channel'],None)
        p['transactions'][0]['channel']='Another arbitrary rail'
        self.assertEqual(normalize(p)['transactions'][0]['channel'],'Another arbitrary rail')

    def test_bank_only_settings_need_no_provider_specific_fields(self):
        config=dict(self.config,cards=[])
        saved=config_validated(config)
        self.assertTrue(saved['ready'])
        self.assertEqual(saved['cards'],[])
        self.assertEqual(saved['report_path'],str(Path.cwd().resolve()/'report.html'))


if __name__=='__main__':unittest.main()
