"""Source-period precedence and issuer/category refinements; synthetic data only."""
import copy
import json
import unittest
import test_completeness as support
from test_ledger import fixture
from coverage_fixtures import source_evidence
from moneylens.ledger import records, category_name, assessment
from moneylens.alerts import report_records
from moneylens.store import get, put
from moneylens.personalize import annotate, decorate
from moneylens.merchants import remember, lookup, review


class StatementPreferenceTests(unittest.TestCase):
    def setUp(self):
        self.case=support.CompletenessTests();self.case.setUp()
        self.db=self.case.db

    def tearDown(self):self.case.tearDown()

    def alert(self,message='notice',day='2026-09-09',account='test-card-a',currency='INR',kind='purchase'):
        p=fixture(message,account_key=account,currency=currency,checks={})
        p['transactions']=[dict(p['transactions'][0],date=day,merchant=message,amount_minor=98765,kind=kind,reference='ref-'+message)]
        p['source'].pop('attachment_id');p['source']['filename']='email-body'
        p['period_start']=p['period_end']=day
        if account.startswith('bank-'):p['account_type']='bank_account'
        return p

    def alerts(self,*payloads):
        from moneylens.processing import process_batch
        return process_batch(self.case.root,[{'type':'alert','payload':p} for p in payloads])

    def test_unmatched_notification_is_discarded_from_report_without_inventing_duplicate_link(self):
        self.alerts(self.alert())
        self.assertEqual(len(self.case.data()['rows']),1)
        self.case.batch(source_evidence(fixture()))
        self.assertEqual(len(self.case.data()['rows']),3)
        audit=report_records(self.db,records(self.db))[0]
        self.assertEqual(audit['status'],'statement_covered');self.assertIsNone(audit['matched_to'])
        self.assertTrue(audit['covered_by_statements'])
        self.assertEqual(self.db.execute('SELECT count(*) FROM alert_matches').fetchone()[0],0)
        self.assertEqual(self.db.execute('SELECT count(*) FROM alerts').fetchone()[0],1) # audit, not a financial row
        self.assertEqual(review(self.db)['currencies'],[])
        self.assertEqual(len(self.case.data()['statements']),1)

    def test_inclusive_period_boundaries_preserve_notifications_before_and_after(self):
        self.case.batch(source_evidence(fixture()))
        self.alerts(*(self.alert(message=day,day=day) for day in ['2026-08-31','2026-09-01','2026-09-30','2026-10-01']))
        states={r['payload']['transactions'][0]['date']:r['status'] for r in report_records(self.db,records(self.db))}
        self.assertEqual(states,{'2026-08-31':'provisional','2026-09-01':'statement_covered','2026-09-30':'statement_covered','2026-10-01':'provisional'})
        self.assertEqual(len(self.case.data()['rows']),5)

    def test_account_and_currency_isolation(self):
        self.case.batch(source_evidence(fixture()))
        self.alerts(self.alert('other-currency',currency='USD'),self.alert('bank-notice',account='bank-a',kind='debit'))
        self.assertEqual([r['status'] for r in report_records(self.db,records(self.db))],['provisional','provisional'])
        self.assertEqual(len(self.case.data()['rows']),5)

    def test_incomplete_statement_remains_unverified_and_notifications_cannot_fill_its_gaps(self):
        self.case.batch(source_evidence(fixture(complete=False)))
        self.alerts(self.alert())
        data=self.case.data();self.assertEqual(len(data['rows']),3)
        self.assertTrue(all(r['blocked'] for r in data['rows']))
        self.assertFalse(data['statements'][0]['coverage']['verified'])
        self.assertEqual(report_records(self.db,records(self.db))[0]['status'],'statement_covered')

    def test_unresolved_account_statement_cannot_suppress_notifications(self):
        self.case.batch(source_evidence(fixture(account_resolved=False)))
        self.alerts(self.alert())
        self.assertEqual(report_records(self.db,records(self.db))[0]['status'],'provisional')
        self.assertEqual(len(self.case.data()['rows']),4)

    def test_preference_crosses_mailboxes_for_the_same_confirmed_account(self):
        cfg=get(self.db,'config')
        cfg['mailboxes'].append({'id':'other-mail','address':'other@example.invalid','verified_at':'2026-10-23T09:00:00+05:30'})
        cfg['cards'][0]['mailbox_ids'].append('other-mail')
        with self.db:put(self.db,'config',cfg)
        self.case.batch(source_evidence(fixture()))
        p=self.alert();p['source']['mailbox']='other-mail';self.alerts(p)
        self.assertEqual(report_records(self.db,records(self.db))[0]['status'],'statement_covered')
        self.assertEqual(len(self.case.data()['rows']),3)

    def test_source_descriptions_are_not_reinterpreted_from_institution_or_markers(self):
        payload=fixture(issuer='Any institution')
        payload['transactions'][0]['merchant']='EMI Gym membership'
        self.case.batch(source_evidence(payload))
        row=self.case.data()['rows'][0]
        self.assertEqual(row['merchant'],'EMI Gym membership')
        self.assertEqual(row['original_merchant'],'EMI Gym membership')
        self.assertNotIn('bank_quirk',row)
        self.assertEqual(row['kind'],'purchase')

    def test_display_cleanup_preserves_originals_and_annotation_evidence(self):
        p=fixture(issuer='Institution A');p['transactions'][0].update(merchant='EMI Gym membership',category='Health & fitness')
        p['transactions'][0]['metadata']={'display_description':'Gym membership','display_note':'Agent verified the source notation.'}
        result=self.case.batch(source_evidence(p))['outcomes'][0];sid=result['id'];before=copy.deepcopy(records(self.db))
        row=self.case.data()['rows'][0]
        self.assertEqual(row['merchant'],'Gym membership');self.assertEqual(row['original_merchant'],'EMI Gym membership')
        self.assertEqual(row['kind'],'purchase');self.assertEqual(row['category'],'Health & fitness')
        with self.db:annotate(self.db,sid,0,category='Personal fitness',note='Preserved correction')
        self.case.batch()
        self.assertEqual(self.case.data()['rows'][0]['category'],'Personal fitness')
        self.assertEqual(records(self.db),before)

    def test_health_and_fitness_aliases_and_clear_merchants_are_top_level(self):
        for label in ['Health','Fitness','Healthcare','Health & fitness']:
            self.assertEqual(category_name(label),label)
        self.assertIsNone(lookup(self.db,'Gym membership'))
        with self.db:remember(self.db,'Gym membership','Health & fitness')
        self.assertEqual(lookup(self.db,'Gym membership'),'Health & fitness')
        self.assertIsNone(lookup(self.db,'Unrecognized merchant'))

    def test_bank_fitness_purchase_can_use_specific_health_category(self):
        p=fixture(account_key='bank-a',account_type='bank_account',checks={'expected_transaction_count':1})
        p['transactions']=[dict(p['transactions'][0],merchant='Gym membership',kind='debit',category='Health & fitness')]
        self.case.batch(source_evidence(p))
        self.assertEqual(self.case.data()['rows'][0]['category'],'Health & fitness')

    def test_zero_activity_bank_statement_still_discards_all_covered_notifications(self):
        p=fixture(account_key='bank-a',account_type='bank_account',transactions=[],checks={'expected_transaction_count':0,'opening_balance_minor':10000,'closing_balance_minor':10000})
        result=self.case.batch(source_evidence(p))['outcomes'][0]
        self.assertEqual(result['result'],'imported')
        self.alerts(self.alert('bank-zero-period-notice',account='bank-a',kind='debit'))
        self.assertEqual(self.case.data()['rows'],[])
        self.assertEqual(report_records(self.db,records(self.db))[0]['status'],'statement_covered')

    def test_covered_notifications_do_not_signal_new_financial_data_or_reset_setup_review(self):
        self.case.batch(source_evidence(fixture()))
        previous=self.case.data()['rows']
        out=self.alerts(self.alert('covered-unmatched'))['outcomes'][0]
        self.assertEqual(out['result'],'statement_covered')
        self.assertEqual(self.case.data()['rows'],previous)
        self.alerts(self.alert('outside','2026-10-05'))
        self.assertNotEqual(self.case.data()['rows'],previous)
