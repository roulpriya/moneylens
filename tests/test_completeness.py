"""Full synthetic source -> batch -> durable ledger -> report regressions."""
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'skills/automation'))
from moneylens.ledger import connect, records, assessment, normalize, stage, find, save
from moneylens.processing import process_batch
from moneylens.store import config_validated, put, get
from coverage_fixtures import source_evidence
from test_ledger import fixture


class CompletenessTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.root=Path(self.temp.name); self.db=connect(self.root)
        cfg=config_validated({'mailboxes': [{'id': 'synthetic-test', 'address': 'synthetic-test', 'verified_at': '2026-10-20T09:00:00+05:30'}], 'timezone': 'Asia/Kolkata', 'report_path': str(self.root/'report.html'), 'cards': [{'account_label':'Synthetic account','account_key':'test-card-a','issuer':'Synthetic Bank','masked_identifier':'1234','credential_scope':'test-only','password_status':'not_required'}], 'bank_accounts': [{'account_key':'bank-a','issuer':'Synthetic Bank','masked_identifier':'2222','account_label':'Synthetic savings','statement_enabled':True,'credential_scope':'test-bank','password_status':'not_required'},
                           {'account_key':'bank-b','issuer':'Synthetic Bank','masked_identifier':'3333','account_label':'Synthetic second savings','statement_enabled':True,'credential_scope':'test-bank-b','password_status':'not_required'}]})
        with self.db: put(self.db,'config',cfg)

    def tearDown(self): self.db.close();self.temp.cleanup()
    def batch(self,*payloads): return process_batch(self.root,[{'type':'statement','payload':p} for p in payloads])
    def data(self): return json.loads((self.root/'report.html').read_text().split('<script id="data" type="application/json">')[1].split('</script>')[0])
    def checked(self):
        saved=records(self.db);return [assessment(r,saved) for r in saved]

    def test_complete_source_imports_and_every_occurrence_reaches_report(self):
        p=source_evidence(fixture());out=self.batch(p)
        self.assertEqual(out['outcomes'][0]['result'],'imported')
        c=self.checked()[0]['coverage'];self.assertTrue(c['verified']);self.assertEqual(c['source_row_count'],3)
        self.assertEqual(c['mapped_counts'],{'retained':3,'duplicate_linked':0,'review':0})
        data=self.data();self.assertEqual(len(data['rows']),3);self.assertTrue(data['report_visibility_complete'])
        self.assertTrue(data['statements'][0]['financial_review_resolved'])

    def test_offsetting_omissions_fail_even_when_balance_reconciles(self):
        p=fixture();p['transactions'][1]['amount_minor']=-12000;p['transactions'][2]['amount_minor']=0
        p['checks']={'opening_balance_minor':10000,'closing_balance_minor':10000,'expected_transaction_count':3,'expected_debits_minor':12000,'expected_credits_minor':12000}
        p=source_evidence(p);p['transactions']=p['transactions'][2:]
        out=self.batch(p)['outcomes'][0];self.assertEqual(out['result'],'staged')
        self.assertFalse(out['coverage']['verified']);self.assertIn('balance_reconciliation',out['passed_checks'])
        self.assertIn('missing from extraction',str(out['coverage']['gaps']))
        self.assertEqual(len(self.data()['rows']),3) # enumerated omissions have visible review placeholders

    def test_partial_pages_and_complete_boolean_do_not_prove_coverage(self):
        p=source_evidence(fixture());p['coverage']['page_count']=2
        p['coverage']['sections'][0]['pages'].append(2)
        out=self.batch(p)['outcomes'][0];self.assertIn('pages: 2',str(out['coverage']['gaps']))
        p['coverage']['pages'].append({'page':2,'status':'partial','evidence':'Bottom table unreadable'})
        out=self.batch(p)['outcomes'][0];self.assertFalse(out['coverage']['verified'])
        p.pop('coverage');out=self.batch(p)['outcomes'][0];self.assertFalse(out['coverage']['verified'])

    def test_checks_cannot_be_removed_changed_or_derived(self):
        for variant in ('omitted','changed','derived','unavailable'):
            with self.subTest(variant=variant):
                p=source_evidence(fixture(variant))
                if variant=='omitted':p['checks']={}
                elif variant=='changed':p['checks']['expected_debits_minor']=1
                elif variant=='derived':p['coverage']['sections'][0]['checks']['expected_debits_minor']['origin']='extracted_rows'
                else:
                    p['checks']={}
                    for k in p['coverage']['sections'][0]['checks']:p['coverage']['sections'][0]['checks'][k]={'status':'unavailable','reason':'No independent proof'}
                out=self.batch(p)['outcomes'][0];self.assertNotEqual(out['result'],'imported')

    def test_combined_document_sections_import_independently_and_coverage_is_reassessed(self):
        p=source_evidence(fixture());q=source_evidence(fixture(account_key='bank-a',account_type='bank_account'))
        q['checks']['closing_balance_minor']=-q['checks']['closing_balance_minor']+20000
        q=source_evidence(q);q['coverage']['sections'][0]['checks']['closing_balance_minor']['value']=4000
        q['source']=copy.deepcopy(p['source'])
        manifest=copy.deepcopy(p['coverage']);manifest['sections'].append(copy.deepcopy(q['coverage']['sections'][0]))
        p['coverage']=copy.deepcopy(manifest);q['coverage']=copy.deepcopy(manifest);q['coverage']['section_id']='bank-a-INR'
        out=self.batch(p)['outcomes'][0];self.assertIn('Missing or repeated',str(out['coverage']['gaps']))
        self.assertEqual(out['result'],'imported');self.assertTrue(out['coverage']['section']['verified'])
        self.assertFalse(out['coverage']['verified']);self.assertFalse(any(r['blocked'] for r in self.data()['rows']))
        result=self.batch(p,q)
        self.assertEqual([r['result'] for r in result['outcomes']],['already_imported','imported'])
        self.assertTrue(all(r['coverage']['verified'] for r in result['outcomes']))
        self.assertTrue(all(r['coverage']['verified'] for r in self.checked()));self.assertEqual(len(self.data()['rows']),6)

    def test_unreadable_source_row_is_visible_review_with_separate_coverage_state(self):
        p=source_evidence(fixture());original=p['transactions'].pop(1)
        p['review_rows']=[{k:original[k] for k in ('source_row_id','page','row','amount_minor','date')} | {'reason':'Merchant/movement unreadable'}]
        out=self.batch(p)['outcomes'][0];self.assertEqual(out['result'],'staged')
        self.assertTrue(out['coverage']['verified']);self.assertFalse(out['financial_review_resolved'])
        rows=self.data()['rows'];self.assertEqual(len(rows),3);self.assertTrue(rows[-1]['blocked']);self.assertEqual(rows[-1]['review_reason'],'Merchant/movement unreadable')
        p['review_rows'][0].pop('amount_minor')
        out=self.batch(p)['outcomes'][0];self.assertFalse(out['coverage']['verified']);self.assertIsNone(self.data()['rows'][-1]['amount_minor'])

    def test_cross_statement_overlap_links_preserve_original_totals_and_provenance(self):
        p=source_evidence(fixture());p['transactions'][0]['reference']='source-ref-1';sid=self.batch(p)['outcomes'][0]['id']
        q=source_evidence(fixture('later',period_end='2026-10-01'))
        for i,r in enumerate(q['transactions']):
            r['reference']='source-ref-'+str(i+1)
            r['duplicate_of']={'statement':sid,'index':i,'evidence':'Shared original transaction reference'}
        # Persist the independent references to the synthetic original before staging.
        with self.db:
            rec=find(records(self.db),sid)
            for i,r in enumerate(rec['payload']['transactions']):r['reference']='source-ref-'+str(i+1)
            save(self.db,rec)
        out=self.batch(q)['outcomes'][0];self.assertEqual(out['result'],'imported');self.assertEqual(out['coverage']['mapped_counts']['duplicate_linked'],3)
        rows=self.data()['rows'];self.assertEqual(len(rows),6);self.assertEqual(sum(r['suppressed'] for r in rows),3)
        self.assertEqual(len({r['source']['message_id'] for r in rows}),2)
        self.assertEqual(out['coverage']['source_row_count'],3)

    def test_amount_only_duplicate_and_conflicting_same_digest_extraction_remain_review(self):
        p=source_evidence(fixture());sid=self.batch(p)['outcomes'][0]['id']
        q=source_evidence(fixture('uncertain',period_end='2026-10-01'))
        q['transactions'][0]['duplicate_of']={'statement':sid,'index':0,'evidence':'Same amount'}
        out=self.batch(q)['outcomes'][0];self.assertNotEqual(out['result'],'imported');self.assertIn('amount alone',str(out['issues']))
        self.assertFalse(self.data()['rows'][3]['suppressed'])
        q=source_evidence(fixture('conflict'));q['source']['sha256']=p['source']['sha256'];q['transactions'][0]['amount_minor']+=1
        out=self.batch(q)['outcomes'][0];self.assertNotEqual(out['result'],'imported');self.assertEqual(len(records(self.db)[-1]['payload']['transactions']),3)

    def test_same_document_resend_preserves_every_occurrence_and_replay_is_idempotent(self):
        p=source_evidence(fixture());sid=self.batch(p)['outcomes'][0]['id']
        q=copy.deepcopy(p);q['source']['message_id']='resend'
        out=self.batch(q)['outcomes'][0];self.assertEqual(out['result'],'imported');self.assertNotEqual(out['id'],sid)
        self.assertEqual(len(self.data()['rows']),6);self.assertEqual(out['coverage']['mapped_counts']['duplicate_linked'],3)
        self.assertEqual(self.batch(q)['outcomes'][0]['result'],'already_imported');self.assertEqual(len(self.data()['rows']),6)

    def test_restage_cannot_silently_remove_a_previous_occurrence(self):
        p=source_evidence(fixture(complete=False));self.batch(p);p['transactions'].pop()
        out=self.batch(p)['outcomes'][0]
        self.assertEqual(out['result'],'staged')
        self.assertFalse(out['coverage']['verified'])
        saved=records(self.db)[0]['payload']
        self.assertEqual(len(saved['transactions'])+len(saved['review_rows']),3)
        self.assertIn('no extraction mapping',saved['review_rows'][0]['reason'])

    def test_non_upi_repayments_credits_and_transfer_legs_survive(self):
        p=fixture(account_type='bank_account',account_key='bank-a',checks={})
        p['transactions']=[dict(date='2026-09-08',merchant=name,amount_minor=amount,kind=kind,category='Other',page=1,row=str(i),**extra)
          for i,(name,amount,kind,extra) in enumerate([
            ('NEFT vendor',2000,'debit',{}),('Incoming',-5000,'credit',{}),('Card repayment',3000,'repayment',{}),
            ('Own out',700,'transfer_out',{'own_account_key':'bank-b','transfer_evidence':'Confirmed ownership/source'}),
            ('Own in',-700,'transfer_in',{'own_account_key':'bank-b','transfer_evidence':'Confirmed ownership/source'})])]
        p['checks']={'expected_transaction_count':5,'expected_debits_minor':5700,'expected_credits_minor':5700}
        p['transactions'][0]['category']='Non-UPI bank movements'
        out=self.batch(source_evidence(p))['outcomes'][0];self.assertEqual(out['result'],'imported')
        rows=self.data()['rows'];self.assertEqual(len(rows),5);self.assertEqual(rows[0]['category'],'Non-UPI bank movements');self.assertEqual(rows[1]['kind'],'credit')
        self.assertEqual(rows[2]['kind'],'repayment');self.assertTrue(all(r['excluded_from_spending'] for r in rows[-2:]))

    def test_imported_statement_without_source_evidence_is_blocked(self):
        p=normalize(fixture());before=copy.deepcopy(p)
        with self.db:self.db.execute('INSERT INTO statements VALUES (?,?,?,?)',('invalid','imported',json.dumps(p),'2026-01-01'))
        self.batch();checked=self.checked()[0]
        self.assertTrue(checked['issues']);self.assertFalse(checked['coverage']['verified'])
        self.assertEqual(records(self.db)[0]['payload'],before)
        self.assertTrue(all(r['blocked'] for r in self.data()['rows']))

    def test_report_missing_the_required_all_transactions_view_is_rejected(self):
        template=Path(__file__).resolve().parents[1]/'skills/automation/assets/report-template.html'
        original=template.read_text().replace('id="view-all"','id="missing-view-all"')
        (self.root/'report.html').write_text(original)
        with self.assertRaisesRegex(ValueError,'Report generation failed'):self.batch(source_evidence(fixture()))
        self.assertEqual((self.root/'report.html').read_text(),original)

    def test_malformed_confirmed_statement_keeps_visible_durable_review_occurrences(self):
        p=source_evidence(fixture());p['coverage']['sections'][0]['checks']['expected_debits_minor']['origin']='derived'
        out=self.batch(p)['outcomes'][0];self.assertEqual(out['result'],'needs_review')
        self.assertEqual(len(out['review_rows']),3)
        data=self.data();self.assertEqual(len(data['rows']),3)
        self.assertTrue(all(r['blocked'] and r['review_reason'] for r in data['rows']))
        self.batch();self.assertEqual(len(self.data()['rows']),3) # durable after report-only refresh

    def test_duplicate_occurrences_do_not_disrupt_unique_own_transfer_pairing(self):
        def leg(account, amount, message):
            p=fixture(message,account_key=account,account_type='bank_account',checks={'expected_transaction_count':1})
            p['transactions']=[dict(date='2026-09-08',merchant='Own bank movement',amount_minor=amount,
              kind='debit' if amount>0 else 'credit',category='Other',page=1,row='1',reference='own-transfer-ref')]
            return source_evidence(p)
        p=leg('bank-a',2000,'out');q=leg('bank-b',-2000,'in');self.batch(p,q)
        resend=copy.deepcopy(p);resend['source']['message_id']='resent-out';self.batch(resend)
        rows=self.data()['rows'];self.assertEqual(len(rows),3)
        self.assertTrue(all(r['excluded_from_spending'] for r in rows if not r['suppressed']))
        self.assertEqual(sum(r['suppressed'] for r in rows),1)

    def test_combined_currency_section_omission_blocks_only_the_affected_section(self):
        p=source_evidence(fixture());q=source_evidence(fixture(currency='USD'))
        q['source']=copy.deepcopy(p['source'])
        manifest=copy.deepcopy(p['coverage']);manifest['sections']+=q['coverage']['sections']
        p['coverage']=copy.deepcopy(manifest);q['coverage']=copy.deepcopy(manifest);q['coverage']['section_id']='test-card-a-USD'
        q['transactions'].pop() # original independent inventory is preserved
        self.batch(p,q)
        checked=self.checked();self.assertTrue(all(not r['coverage']['verified'] for r in checked))
        self.assertEqual({r['payload']['currency']:r['status'] for r in records(self.db)}, {'INR':'imported','USD':'draft'})
        self.assertTrue(next(r for r in checked if r['coverage']['section']['id']=='test-card-a-INR')['coverage']['section']['verified'])
        self.assertTrue(all(not r['blocked'] for r in self.data()['rows'] if r['currency']=='INR'))
        self.assertTrue(all(r['blocked'] for r in self.data()['rows'] if r['currency']=='USD'))
        self.assertEqual(len(self.data()['rows']),6)

    def test_unknown_amount_does_not_turn_into_zero_for_independent_checks(self):
        p=source_evidence(fixture());row=p['transactions'].pop(0)
        p['review_rows']=[{'source_row_id':row['source_row_id'],'page':row['page'],'row':row['row'],'reason':'Unreadable amount'}]
        out=self.batch(p)['outcomes'][0]
        self.assertNotIn('balance_reconciliation',out['passed_checks'])
        self.assertNotIn('expected_debits_minor',out['passed_checks'])
        self.assertFalse(out['coverage']['verified'])

    def test_duplicate_link_cannot_hide_conflicting_currency_or_form_a_chain(self):
        p=source_evidence(fixture());sid=self.batch(p)['outcomes'][0]['id']
        q=copy.deepcopy(p);q['source']['message_id']='resend';qid=self.batch(q)['outcomes'][0]['id']
        third=source_evidence(fixture('chain',period_end='2026-10-01'))
        for i,row in enumerate(third['transactions']):row['duplicate_of']={'statement':qid,'index':i,'evidence':'Shared document'}
        out=self.batch(third)['outcomes'][0];self.assertEqual(out['result'],'staged');self.assertIn('terminal retained',str(out['issues']))
        conflict=source_evidence(fixture('currency-conflict',currency='USD'))
        conflict['transactions'][0]['duplicate_of']={'statement':sid,'index':0,'evidence':'Same amount'}
        out=self.batch(conflict)['outcomes'][0];self.assertEqual(out['result'],'staged');self.assertIn('currency conflicts',str(out['issues']))
        self.assertEqual(len(self.data()['rows']),12)


    def savings_and_summary(self):
        savings=fixture('combined-summary',account_key='bank-a',account_type='bank_account',account_label='Synthetic savings')
        savings['transactions']=[{'date':'2026-09-08','merchant':'Observed sweep credit' if i==0 else 'Savings movement '+str(i),
            'amount_minor':-5000 if i==0 else 100,'kind':'credit' if i==0 else 'debit',
            'category':'Agent category','page':1,'row':str(i+1)} for i in range(44)]
        savings['checks']={'expected_transaction_count':44,'expected_debits_minor':4300,'expected_credits_minor':5000,
                           'opening_balance_minor':10000,'closing_balance_minor':10700}
        savings=source_evidence(savings)
        summary=fixture('combined-summary',account_key='bank-b',account_type='bank_account',account_label='Deposit summary',
            transactions=[],checks={},issues=['Individual deposit withdrawals, exact interest dates, and movement reconciliation evidence are absent'])
        summary=source_evidence(summary)
        summary['source']=copy.deepcopy(savings['source'])
        summary['coverage']['sections'][0]['pages']=[2]
        manifest=copy.deepcopy(savings['coverage']);manifest['page_count']=2
        manifest['pages'].append({'page':2,'status':'read','evidence':'Read summary balances and cumulative interest; no movement table printed'})
        manifest['sections'].append(copy.deepcopy(summary['coverage']['sections'][0]))
        for payload,section in ((savings,'bank-a-INR'),(summary,'bank-b-INR')):
            payload['coverage']=copy.deepcopy(manifest);payload['coverage']['section_id']=section
        return savings,summary

    def test_44_reconciled_savings_rows_import_despite_unreconcilable_summary_section(self):
        savings,summary=self.savings_and_summary()
        result=self.batch(savings,summary)
        self.assertEqual([r['result'] for r in result['outcomes']],['imported','staged'])
        checked={r['coverage']['section']['id']:r for r in self.checked()}
        healthy=checked['bank-a-INR'];gap=checked['bank-b-INR']
        self.assertEqual(healthy['issues'],[]);self.assertTrue(healthy['financial_review_resolved'])
        self.assertTrue(healthy['coverage']['section']['verified']);self.assertFalse(healthy['coverage']['verified'])
        self.assertEqual(healthy['coverage']['section']['source_row_count'],44)
        self.assertEqual(len(healthy['passed_checks']),4)
        self.assertFalse(gap['coverage']['section']['verified'])
        report=self.data();self.assertEqual(len(report['rows']),44)
        self.assertTrue(all(r['status']=='imported' and not r['blocked'] for r in report['rows']))
        self.assertTrue(any('Individual deposit withdrawals' in item['reason'] for item in report['review_items']))
        self.assertFalse(any(item['account']=='Synthetic savings' for item in report['review_items']))
        self.assertTrue(any(item['account']=='Combined document' for item in report['review_items']))
        self.assertEqual(next(r for r in records(self.db) if r['payload']['account_key']=='bank-b')['payload']['transactions'],[])

    def test_own_section_omission_still_blocks_savings_even_with_a_valid_balance(self):
        savings,summary=self.savings_and_summary();savings['transactions'].pop()
        result=self.batch(savings,summary)
        self.assertEqual(result['outcomes'][0]['result'],'staged')
        self.assertFalse(result['outcomes'][0]['coverage']['section']['verified'])
        self.assertTrue(all(r['blocked'] for r in self.data()['rows']))
        self.assertEqual(len(self.data()['rows']),44)

    def test_unread_sibling_page_is_a_document_gap_without_blocking_read_savings_pages(self):
        savings,summary=self.savings_and_summary()
        savings['coverage']['pages'][1].update(status='unreadable',evidence='Summary page could not be read')
        result=self.batch(savings)['outcomes'][0]
        self.assertEqual(result['result'],'imported')
        self.assertTrue(result['coverage']['section']['verified']);self.assertFalse(result['coverage']['verified'])
        self.assertIn('document pages: 2',str(result['coverage']['gaps']))
        self.assertTrue(all(not r['blocked'] for r in self.data()['rows']))

    def test_conflicting_document_manifests_remain_an_integrity_block(self):
        savings,summary=self.savings_and_summary();self.batch(savings)
        summary['coverage']['sections'][1]['evidence']='A conflicting observation of the same document'
        self.batch(summary)
        healthy=next(r for r in self.checked() if r['coverage']['section']['id']=='bank-a-INR')
        self.assertFalse(healthy['coverage']['section']['verified'])
        self.assertIn('Conflicting document manifest',str(healthy['issues']))
        self.assertTrue(all(r['blocked'] for r in self.data()['rows']))
