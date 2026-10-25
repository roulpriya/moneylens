"""Synthetic 44-row acceptance journey; no private HDFC data or live mailbox."""
import copy
import json
import unittest
from unittest.mock import patch
from coverage_fixtures import source_evidence
import test_completeness as support
from test_ledger import fixture
from moneylens.accounting import preferences
from moneylens.dashboard import write_report
from moneylens.ledger import records, normalize, connect
from moneylens.processing import process_batch
from moneylens.store import get, save_config
from moneylens.transactions import list_transactions


def savings_source():
    # Explicit synthetic source table and printed checks, never real extraction.
    p = fixture('synthetic-consolidated', account_key='bank-a', account_type='bank_account')
    rows = [('FD withdrawal '+str(i+1), -10000, 'credit', 'Investment withdrawal') for i in range(11)]
    rows += [('Salary', -200000, 'credit', 'Salary'), ('Posted interest', -125, 'credit', 'Interest'),
             ('Card repayment', 30000, 'repayment', 'Card bills'), ('FD placement', 50000, 'debit', 'Investment')]
    rows += [('Purchase '+str(i+1), 100, 'debit', 'Other' if i == 0 else 'Groceries') for i in range(29)]
    p['transactions'] = [{'date':'2026-09-08', 'merchant':name, 'amount_minor':amount, 'kind':kind,
                          'category':category, 'page':1, 'row':str(i+1), 'reference':'observed-ref-'+str(i+1)}
                         for i, (name,amount,kind,category) in enumerate(rows)]
    p['checks'] = {'expected_transaction_count':44, 'expected_debits_minor':82900, 'expected_credits_minor':310125,
                   'opening_balance_minor':500000, 'closing_balance_minor':727225}
    p = source_evidence(p)
    p['coverage']['page_count'] = 2
    p['coverage']['pages'].append({'page':2, 'status':'read', 'evidence':'Synthetic FD balances and cumulative interest summary; no movement table'})
    p['coverage']['sections'].append({'id':'fd-summary', 'account_key':'observed-fd-summary', 'currency':'INR',
        'type':'balance_snapshot', 'pages':[2], 'rows':[], 'evidence':'Synthetic deposit balance heading',
        'limitations':['Cumulative interest has no posting dates; deposit movement history is not supplied'],
        'checks':{name:{'status':'unavailable','reason':'Summary has no transaction reconciliation check'} for name in p['coverage']['sections'][0]['checks']}})
    return p


class InvestmentCashflowTests(unittest.TestCase):
    def setUp(self):
        self.case=support.CompletenessTests(); self.case.setUp(); self.db=self.case.db

    def tearDown(self): self.case.tearDown()

    def test_44_rows_and_11_withdrawals_survive_refresh_with_original_evidence(self):
        p=savings_source(); result=self.case.batch(p)['outcomes'][0]
        self.assertEqual(result['result'],'imported'); self.assertEqual(result['issues'],[])
        self.assertTrue(result['coverage']['section']['verified']); self.assertFalse(result['coverage']['verified'])
        self.assertIn('Balance snapshot only',str(result['coverage']['gaps']))
        original=copy.deepcopy(records(self.db)); data=self.case.data()
        self.assertEqual(len(data['rows']),44); self.assertTrue(all(not r['blocked'] for r in data['rows']))
        withdrawals=[r for r in data['rows'] if r['accounting_treatment']=='investment_withdrawal']
        self.assertEqual(len(withdrawals),11)
        self.assertTrue(all(r['excluded_from_spending'] and r['excluded_from_income'] for r in withdrawals))
        self.assertEqual([r['reference'] for r in withdrawals],[r['reference'] for r in p['transactions'][:11]])
        self.assertEqual({r['merchant']:r['kind'] for r in data['rows'][11:15]},
                         {'Salary':'credit','Posted interest':'credit','Card repayment':'repayment','FD placement':'debit'})
        self.assertFalse(data['rows'][11].get('excluded_from_income',False))
        self.assertFalse(data['rows'][12].get('excluded_from_income',False))
        self.assertTrue(any('amount still counts' in item['reason'] for item in data['review_items']))
        with self.db:
            preferences(self.db, {'report_from':'2026-09-01', 'report_to':'2026-09-30'})
            write_report(self.db)
        previous=(self.case.root/'report.html').read_text()
        self.case.batch()
        after=(self.case.root/'report.html').read_text(); refreshed=self.case.data()
        self.assertEqual((refreshed['from'],refreshed['to']),('2026-09-01','2026-09-30'))
        self.assertEqual(refreshed['rows'],data['rows']); self.assertEqual(records(self.db),original)
        self.assertEqual(previous.split('<!-- MONEYLENS_DATA_START -->')[0],after.split('<!-- MONEYLENS_DATA_START -->')[0])
        self.assertIn('value="cashflow">Cashflow</option>',after); self.assertIn('id="cashflow-summary"',after)
        # Preferences and section data remain durable after closing/reopening.
        other=connect(self.case.root)
        try:
            self.assertEqual(preferences(other)['report_from'],'2026-09-01')
            self.assertEqual(len([r for r in list_transactions(other) if r['accounting_treatment']=='investment_withdrawal']),11)
        finally: other.close()

    def test_snapshot_cannot_become_zero_activity_statement_or_suppress_alerts(self):
        p=savings_source(); summary=copy.deepcopy(p)
        summary.update(account_key='bank-b',transactions=[],checks={'expected_transaction_count':0,'opening_balance_minor':100,'closing_balance_minor':100})
        summary['coverage']['section_id']='fd-summary'
        section=summary['coverage']['sections'][1]; section['account_key']='bank-b'
        for name,value in summary['checks'].items():
            section['checks'][name]={'status':'stated','value':value,'page':2,'origin':'source','evidence':'Synthetic snapshot label'}
        result=self.case.batch(summary)['outcomes'][0]
        self.assertEqual(result['result'],'staged'); self.assertEqual(self.case.data()['rows'],[])
        from moneylens.alerts import statement_coverage
        alert=copy.deepcopy(summary); alert['transactions']=[p['transactions'][0]]
        self.assertEqual(statement_coverage(alert,records(self.db)),[])
        summary['transactions']=[p['transactions'][0]]
        with self.assertRaisesRegex(ValueError,'Balance snapshots cannot supply'): normalize(summary)
        outcome=self.case.batch(summary)['outcomes'][0]
        self.assertEqual(outcome['result'],'needs_review'); self.assertEqual(self.case.data()['rows'],[])
        self.assertIn('Balance snapshots cannot supply',str(self.case.data()['review_items']))

    def test_custom_treatment_survives_account_settings_save_and_explicit_dates_can_clear_scope(self):
        with self.db:
            preferences(self.db, {'category_treatments':{'Long-term savings':'investment'}, 'report_from':'2026-09-01','report_to':'2026-09-30'})
            save_config(self.db,get(self.db,'config'))
            write_report(self.db,from_date='',to_date='')
        self.assertEqual(preferences(self.db),{'category_treatments':{'Long-term savings':'investment'},'report_from':'','report_to':''})
        for changes in ({'password':'forbidden'},{'category_treatments':{'X':[]}},{'report_from':'2026-11-01','report_to':'2026-10-01'}):
            with self.subTest(changes=changes), self.assertRaises(ValueError): preferences(self.db,changes)

    def test_interruption_keeps_first_section_import_and_replay_does_not_duplicate(self):
        p=savings_source(); second=copy.deepcopy(p); second['source']['message_id']='second-source'
        from moneylens import processing
        original_stage=processing.stage
        def interrupted(db,path):
            if json.loads(path.read_text())['source']['message_id']=='second-source': raise KeyboardInterrupt()
            return original_stage(db,path)
        with patch('moneylens.processing.stage',side_effect=interrupted), self.assertRaises(KeyboardInterrupt):
            process_batch(self.case.root,[{'type':'statement','payload':x} for x in (p,second)])
        self.assertEqual(len(records(self.db)),1); self.assertEqual(records(self.db)[0]['status'],'imported')
        replay=self.case.batch(p)['outcomes'][0]
        self.assertEqual(replay['result'],'already_imported'); self.assertEqual(len(records(self.db)),1)
        self.assertEqual(len(self.case.data()['rows']),44)
