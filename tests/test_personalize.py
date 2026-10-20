"""Personal context persists without changing evidence or accounting."""
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'moneylens-automation/scripts'))
from ledger import connect, normalize, records, semantic_key, stage
from personalize import annotate, decorate, validate_rules, name_like
from test_ledger import fixture


class PersonalizationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.db = connect(self.root)

    def tearDown(self):
        self.db.close()
        self.temp.cleanup()

    def set_rules(self, rules):
        self.db.execute("INSERT OR REPLACE INTO runtime_meta VALUES ('personal_rules',?)", (json.dumps(validate_rules(rules)),))

    def test_current_and_future_rows_use_rules_without_changing_source(self):
        self.set_rules([{'id':'shop', 'label':'Example store', 'category':'Shopping', 'note':'Personal shopping rule', 'when':{'merchant_contains':['Example store']}}])
        for amount, message in enumerate(('old', 'new'), 12000):
            p=fixture(message);p['transactions'][0].update(merchant='Example Store', category='Other')
            p['transactions'][0]['amount_minor']=amount
            path=self.root/'input.json';path.write_text(json.dumps(p));stage(self.db,path)
        before=records(self.db)
        after=decorate(self.db,before)
        self.assertEqual([r['payload']['transactions'][0]['category'] for r in after],['Shopping','Shopping'])
        self.assertEqual(records(self.db),before)
        self.assertEqual([semantic_key(r['payload']) for r in before],[semantic_key(r['payload']) for r in after])

    def test_service_identity_wins_then_amount_boundary_then_unknown_upi(self):
        def rule(i, category, when): return {'id':i,'label':i,'category':category,'note':i,'when':when}
        self.set_rules([
            rule('explicit-food','Dining',{'merchant_contains_all':['swiggy','food']}),
            rule('explicit-grocery','Groceries',{'merchant_contains_all':['swiggy','instamart']}),
            rule('small','Groceries',{'merchant_contains':['swiggy'],'currency':'INR','amount_lte':100000}),
            rule('large','Dining',{'merchant_contains':['swiggy'],'currency':'INR','amount_gt':100000}),
            rule('unknown-upi','Transport',{'channel':'upi','kinds':['upi_debit','purchase'],'category_in':['Other']})])
        cases=[('Swiggy Food',50000,'INR','Other','purchase','card','Dining'),('Swiggy Instamart',150000,'INR','Other','purchase','card','Groceries'),
               ('Swiggy',100000,'INR','Other','purchase','card','Groceries'),('Swiggy',100001,'INR','Other','purchase','card','Dining'),
               ('Swiggy',100,'USD','Other','purchase','card','Other'),('Unknown Person',50000,'INR','Other','upi_debit','upi','Transport'),
               ('Known Pharmacy',50000,'INR','Health','upi_debit','upi','Health'),('Unknown Sender',-50000,'INR','Other','upi_credit','upi','Other')]
        for merchant,amount,currency,category,kind,channel,expected in cases:
            p=fixture();p['currency']=currency;p['transactions']=p['transactions'][:1]
            p['transactions'][0].update(merchant=merchant,amount_minor=amount,category=category,kind=kind,channel=channel)
            effective=decorate(self.db,[{'id':'test','payload':p}])[0]['payload']['transactions'][0]
            self.assertEqual(effective['category'],expected,merchant)

    def test_notes_and_manual_categories_survive_restage_and_rule_changes(self):
        p=fixture();path=self.root/'input.json';path.write_text(json.dumps(p));sid=stage(self.db,path)['id']
        annotate(self.db,sid,0,category='Household help',note='Monthly help <script>example</script>')
        self.set_rules([{'id':'fallback','label':'Fallback','category':'Transport','note':'Personal assumption','when':{'merchant_contains':['Synthetic']}}])
        p['transactions'][0]['category']='Other';path.write_text(json.dumps(p));stage(self.db,path)
        row=decorate(self.db,records(self.db))[0]['payload']['transactions'][0]
        self.assertEqual(row['category'],'Household help')
        self.assertIn('<script>',row['note'])
        self.assertNotIn('personal_context',row)
        annotate(self.db,sid,0,note='')
        self.assertEqual(decorate(self.db,records(self.db))[0]['payload']['transactions'][0]['note'],'')

    def test_annotation_follows_reconciled_alert_without_double_counting(self):
        p=normalize(fixture());p['transactions']=p['transactions'][:1]
        self.db.execute('INSERT INTO alerts VALUES (?,?,?)',('alert',json.dumps(p),'now'))
        annotate(self.db,'alert',0,category='Household help',note='Cook and maid')
        source=[{'id':'statement','payload':copy.deepcopy(p),'status':'imported'}, {'id':'alert','payload':p,'status':'matched','matched_to':('statement',0)}]
        result=decorate(self.db,source)
        row=result[0]['payload']['transactions'][0]
        self.assertEqual((row['category'],row['note']),('Household help','Cook and maid'))
        self.assertEqual(result[1]['status'],'matched')

    def test_payments_and_currency_are_guarded(self):
        p=fixture();path=self.root/'input.json';path.write_text(json.dumps(p));sid=stage(self.db,path)['id']
        with self.assertRaises(ValueError): annotate(self.db,sid,2,category='Shopping')
        with self.assertRaises(ValueError): validate_rules([{'id':'bad','label':'bad','category':'Dining','note':'bad','when':{'amount_gt':100000}}])

    def test_personal_payee_filter_excludes_businesses_and_opaque_ids(self):
        for value in ('Example Person', 'Mr A Kumar', 'R K', 'Singleperson'):
            self.assertTrue(name_like(value),value)
        for value in ('Example Retail Company','Example Mutual Funds Autopay','Indian Railways','Example Mall','paytm.123@example','Q123456','TEST'):
            self.assertFalse(name_like(value),value)

    def test_personal_note_is_safe_in_standalone_html(self):
        from dashboard import render
        from ledger import assessment
        p=normalize(fixture());path=self.root/'input.json';path.write_text(json.dumps(p));sid=stage(self.db,path)['id']
        note='Personal context </script><script>alert(1)</script>'
        annotate(self.db,sid,0,note=note)
        enriched=[{**r,'validation':assessment(r,records(self.db))} for r in records(self.db)]
        html=render(decorate(self.db,enriched))
        self.assertNotIn(note,html)
        encoded=html.split('<script id="data" type="application/json">')[1].split('</script>')[0]
        self.assertEqual(json.loads(encoded)['rows'][0]['note'],note)


if __name__=='__main__': unittest.main()
