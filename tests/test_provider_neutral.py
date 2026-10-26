"""Source interpretation belongs to the agent; accounting consumes explicit fields."""
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'plugins/moneylens/skills/automation'))
from moneylens.ledger import connect, records, normalize
from moneylens.store import save_config, get, config_validated
from moneylens.processing import process_batch
from moneylens.transactions import add, update, list_transactions
from coverage_fixtures import observed_statement
from test_ledger import fixture


class ProviderNeutralTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.db=connect(self.root);self.addCleanup(self.db.close)
        self.settings={'mailboxes': [{'id':'source-x','address':'anything@example.invalid'}], 'report_path': str(self.root/'report.html'), 'cards': [{'account_label':'Synthetic account','account_key':'test-card-a',
            'issuer':'Unknown institution with no parser','masked_identifier':'1234','credential_scope':'opaque','password_status':'not_required'}]}
        with self.db:save_config(self.db,self.settings)

    def test_unknown_provider_and_institution_need_only_explicit_financial_fields(self):
        with self.db:
            row=add(self.db,'Unfamiliar descriptor','42.15','2026-10-24','Other',account='test-card-a',extra={
                'source':{'mailbox':'source-x','message_id':'observed-42'},'provider':'Unlisted provider','channel':'card'}, currency_exponent=2, kind='purchase', currency='INR')
        self.assertEqual(row['amount_minor'],4215);self.assertEqual(row['status'],'provisional')
        self.assertEqual(row['source']['message_id'],'observed-42')
        self.assertEqual(row['metadata']['provider'],'Unlisted provider')
        self.assertNotIn('verified_at',get(self.db,'config')['mailboxes'][0])

    def test_provider_timestamp_alias_is_rejected(self):
        settings=copy.deepcopy(self.settings)
        settings['mailboxes'][0]['gmail_verified_at']='2026-10-20T00:00:00+00:00'
        with self.assertRaisesRegex(ValueError,'Unsupported mailbox fields'):config_validated(settings)

    def test_agent_supplied_statement_presentation_preserves_financial_evidence(self):
        p=fixture();p['source']['mailbox']='source-x'
        p['transactions'][0].update(merchant='EMI UPI ORIGINAL DESCRIPTION',metadata={
            'display_description':'Readable description','display_note':'Interpretation supplied by the agent.'})
        original=observed_statement(p)
        result=process_batch(self.root,[{'type':'statement','payload':original}])
        self.assertEqual(result['outcomes'][0]['result'],'imported')
        raw=copy.deepcopy(records(self.db))
        self.assertEqual(raw[0]['payload']['transactions'][0]['merchant'],'EMI UPI ORIGINAL DESCRIPTION')
        html=(self.root/'report.html').read_text()
        data=json.loads(html.split('<script id="data" type="application/json">')[1].split('</script>')[0])
        row=data['rows'][0]
        self.assertEqual(row['merchant'],'Readable description')
        self.assertEqual(row['original_merchant'],'EMI UPI ORIGINAL DESCRIPTION')
        self.assertEqual(row['metadata']['display_note'],'Interpretation supplied by the agent.')
        self.assertIsNone(row['channel'])
        with self.db:update(self.db,row['statement']+':0',{'metadata':{'display_description':'Corrected label'}})
        process_batch(self.root,[])
        self.assertEqual(records(self.db),raw)

    def test_bad_display_metadata_does_not_break_report_after_import(self):
        p=fixture();p['transactions'][0]['metadata']={'display_description':123}
        with self.assertRaises(ValueError):normalize(p)


class ExplicitMoneyInputsTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.db=connect(self.root);self.addCleanup(self.db.close)

    def add(self,currency,exponent,amount,kind='purchase',**fields):
        return add(self.db,'UPI EMI Coffee Uber',''+amount,'2026-10-24','Agent chosen category',
                   currency=currency,currency_exponent=exponent,kind=kind,**fields)

    def test_currencies_and_fractional_precision_are_explicit_and_exact(self):
        for currency,exponent,amount,minor in [('JPY',0,'123',123),('BHD',3,'1.234',1234),
            ('EUR',2,'12.34',1234),('Opaque local units',5,'0.12345',12345),
            ('Token',18,'0.009007199254740991',9007199254740991)]:
            with self.subTest(currency=currency),self.db:
                row=self.add(currency,exponent,amount)
                self.assertEqual((row['amount_minor'],row['amount'],row['currency_exponent']),(minor,amount,exponent))
                self.assertEqual(row['currency'],currency)
                self.assertIsNone(row['channel']);self.assertEqual(row['account_type'],'manual')
                self.assertEqual(row['description'],'UPI EMI Coffee Uber')
                self.assertEqual(row['category'],'Agent chosen category')

    def test_missing_money_fields_do_not_guess_currency_precision_or_kind(self):
        values={'currency':'EUR','currency_exponent':2,'kind':'purchase'}
        for field in values:
            args={key:value for key,value in values.items() if key!=field}
            with self.subTest(field=field),self.assertRaises((ValueError,TypeError)),self.db:
                add(self.db,'Item','1.25','2026-10-24','Agent category',**args)
        self.assertEqual(list_transactions(self.db),[])

    def test_excess_precision_and_conflicting_units_are_rejected_without_rounding(self):
        with self.db:self.add('unit',0,'1')
        for exponent,amount in [(2,'1.00'),(0,'0.001'),(0,'1e-999999999'),(0,'1e999999999'),(18,'0.0000000000000000001')]:
            with self.subTest(exponent=exponent,amount=amount),self.assertRaises(ValueError),self.db:
                self.add('unit',exponent,amount)
        self.assertEqual(len(list_transactions(self.db)),1)

    def test_sign_edits_cannot_silently_reclassify_a_movement(self):
        with self.db:row=self.add('EUR',2,'5')
        with self.assertRaises(ValueError),self.db:update(self.db,row['id'],{'amount':'-5'})
        with self.db:changed=update(self.db,row['id'],{'amount':'-5','kind':'credit'})
        self.assertEqual((changed['kind'],changed['amount_minor']),('credit',-500))

    def test_account_identifiers_and_timezone_are_not_derived(self):
        settings={'mailboxes':[{'id':'opaque','address':'example@example.invalid'}],
                  'cards':[],'bank_accounts':[{'account_key':'alpha','account_label':'Agent account',
                                             'masked_identifier':'prefix ••• suffix-longer-than-four'}]}
        config=config_validated(settings)
        self.assertNotIn('timezone',config)
        self.assertNotIn('issuer',config['bank_accounts'][0])
        self.assertEqual(config['bank_accounts'][0]['masked_identifier'],'prefix ••• suffix-longer-than-four')

    def test_missing_statement_fields_remain_errors_instead_of_defaults(self):
        for field in ('account_type','currency','currency_exponent'):
            p=fixture();del p[field]
            with self.subTest(field=field),self.assertRaises(ValueError):normalize(p)


if __name__=='__main__':unittest.main()
