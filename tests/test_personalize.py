"""Personal context persists without changing evidence or accounting."""
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'plugins/moneylens/skills/automation'))
from moneylens.ledger import connect, normalize, records, semantic_key, stage
from moneylens.personalize import annotate, decorate
from moneylens.merchants import remember
from test_ledger import fixture


class PersonalizationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.db = connect(self.root)

    def tearDown(self):
        self.db.close()
        self.temp.cleanup()


    def test_current_and_future_rows_reuse_agent_cached_category_without_changing_source(self):
        remember(self.db,'Example store','Shopping')
        for amount,message in enumerate(('first','second'),12000):
            p=fixture(message);p['transactions'][0].update(merchant='Example Store',category='Other',amount_minor=amount)
            path=self.root/'input.json';path.write_text(json.dumps(p));stage(self.db,path)
        before=records(self.db);after=decorate(self.db,before)
        self.assertEqual([r['payload']['transactions'][0]['category'] for r in after],['Shopping','Shopping'])
        self.assertEqual(records(self.db),before)
        self.assertEqual([semantic_key(r['payload']) for r in before],[semantic_key(r['payload']) for r in after])


    def test_notes_and_manual_categories_survive_restage_and_cache_changes(self):
        p=fixture();path=self.root/'input.json';path.write_text(json.dumps(p));sid=stage(self.db,path)['id']
        annotate(self.db,sid,0,category='Household help',note='Monthly help <script>example</script>')
        remember(self.db,'Synthetic Grocer','Transport')
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

    def test_category_edits_do_not_change_payment_accounting(self):
        p=fixture();path=self.root/'input.json';path.write_text(json.dumps(p));sid=stage(self.db,path)['id']
        annotate(self.db,sid,2,category='Repayments')
        row=decorate(self.db,records(self.db))[0]['payload']['transactions'][2]
        self.assertEqual(row['category'],'Repayments');self.assertEqual(row['kind'],'payment')





    def test_personal_note_is_safe_in_standalone_html(self):
        from moneylens.dashboard import render
        from moneylens.ledger import assessment
        p=normalize(fixture());path=self.root/'input.json';path.write_text(json.dumps(p));sid=stage(self.db,path)['id']
        note='Personal context </script><script>alert(1)</script>'
        annotate(self.db,sid,0,note=note)
        enriched=[{**r,'validation':assessment(r,records(self.db))} for r in records(self.db)]
        html=render(decorate(self.db,enriched))
        self.assertNotIn(note,html)
        encoded=html.split('<script id="data" type="application/json">')[1].split('</script>')[0]
        self.assertEqual(json.loads(encoded)['rows'][0]['note'],note)


if __name__=='__main__': unittest.main()
