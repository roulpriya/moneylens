import json
from pathlib import Path
import sys
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'skills/moneylens-automation/scripts'))
from gmail_transactions import parse_message
from runtime_state import config_validated


class UPITests(unittest.TestCase):
    def message(self, body, subject='You have done a UPI txn.'):
        return {'id':'synthetic-email', 'from':'alerts@hdfcbank.bank.in', 'subject':subject,
                'date':'20 Oct 2026', 'body':body, 'authenticated':True}

    def test_bank_debit_uses_bank_account_and_reference(self):
        source=self.message('Rs.125.00 is debited from your account ending 5678 towards VPA ***@example (Example Shop) on 20-10-26. UPI transaction reference no.: 123456789012.')
        event,_=parse_message(source)
        self.assertEqual((event['account_type'],event['kind'],event['amount_minor']),('bank_account','upi_debit',12500))
        self.assertEqual(event['reference'],'123456789012')

    def test_bank_credit_is_receipt_not_refund(self):
        source=self.message('Rs.250.00 has been successfully credited to your HDFC Bank account ending in 5678. Transaction Details: Date: 20-10-26 Sender: Example Person (VPA: ***@example) UPI Reference No.: 123456789013',subject='View: Account update for your HDFC Bank A/c')
        event,_=parse_message(source)
        self.assertEqual((event['kind'],event['amount_minor']),('upi_credit',-25000))

    def test_card_funded_upi_keeps_card_account(self):
        source=self.message('Rs.125.00 has been debited from your RuPay Credit Card (ending 1234) Paid to ***@example Date: 20-10-26 UPI Transaction Reference Number: 123456789014')
        event,_=parse_message(source)
        self.assertEqual((event['account_type'],event['channel'],event['kind']),('credit_card','upi','purchase'))

    def test_failed_or_untrusted_notices_are_not_transactions(self):
        event,_=parse_message(self.message('Payment could not be completed.',subject='UPI transaction declined'))
        self.assertIsNone(event)
        source=self.message('Rs.125.00 is debited');source['authenticated']=False
        self.assertIsNone(parse_message(source)[0])

    def test_documents_is_default_report_location_and_upi_only_setup_works(self):
        p={'mailbox':'synthetic-test','gmail_verified_at':'2026-10-20T09:00:00+05:30','initial_start':'2026-07-20','timezone':'Asia/Kolkata','daily_time':'09:00','confirmed_card_count':0,'auto_save_validated':True,'cards':[],
           'upi_accounts':[{'account_key':'synthetic-bank','issuer':'Example Bank','last4':'5678','account_label':'Example account 5678'}]}
        result=config_validated(p)
        self.assertTrue(result['ready'])
        self.assertEqual(result['report_path'],str(Path.home()/'Documents/MoneyLens/report.html'))


if __name__=='__main__':unittest.main()
