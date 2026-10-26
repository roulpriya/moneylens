"""Exercise the plugin folder outside the repository and reject unlisted files."""
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from coverage_fixtures import observed_statement
from test_ledger import fixture

ROOT=Path(__file__).resolve().parents[1]
PLUGIN=ROOT/'plugins/moneylens'
BUN=ROOT/'node_modules/bun/bin/bun.exe'


class PackagedReleaseTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='moneylens release ');self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.plugin=self.root/'installed plugin'
        shutil.copytree(PLUGIN,self.plugin,ignore=shutil.ignore_patterns('__pycache__','*.pyc','.DS_Store'))
        self.scripts=self.plugin/'skills/automation/scripts'
        self.data=self.root/'private data'
        self.environment=os.environ.copy();self.environment.pop('PYTHONPATH',None)
        self.environment['PYTHONDONTWRITEBYTECODE']='1'

    def command(self,*args,pdf=False,input=None):
        result=subprocess.run([sys.executable,str(self.scripts/('pdf_extract.py' if pdf else 'moneylens.py')),
            '--data-dir',str(self.data),*args] if pdf else
            [sys.executable,str(self.scripts/'moneylens.py'),args[0],'--data-dir',str(self.data),*args[1:]],
            cwd=self.root,env=self.environment,input=input,capture_output=True,text=True,timeout=30)
        self.assertEqual(result.returncode,0,result.stderr)
        return json.loads(result.stdout)

    def test_packaged_accounting_and_pdf_work_without_repository_imports(self):
        unit=['--currency','INR','--currency-exponent','2','--kind','purchase']
        row=self.command('add',*unit,'--description','Vendor','--amount','1.25','--date','2026-10-24',
            '--category','Agent category','--metadata','{"context":"synthetic"}')
        self.assertEqual(self.command('merchants','--merchant','VENDOR')['category'],'Agent category')
        settings={'mailboxes':[{'id':'synthetic-test','address':'example@example.invalid'}],
            'cards':[{'account_key':'test-card-a','account_label':'Confirmed account',
                      'credential_scope':'pdf-scope','password_status':'not_required'}]}
        path=self.root/'settings.json';path.write_text(json.dumps(settings))
        self.command('accounts','--input',str(path))
        notice=self.command('add',*unit,'--description','Synthetic Grocer','--amount','120','--date','2026-09-08',
            '--category','Groceries','--account','test-card-a','--metadata',json.dumps({
            'source':{'mailbox':'synthetic-test','message_id':'notice'},'reference':'exact-reference'}))
        self.assertEqual(notice['status'],'provisional')
        statement=fixture();statement['transactions'][0]['reference']='exact-reference'
        path=self.root/'statement.json';path.write_text(json.dumps(observed_statement(statement)))
        result=self.command('import-statement','--input',str(path))
        self.assertEqual(result['outcomes'][0]['result'],'imported')
        listed=self.command('list')
        self.assertEqual(len(listed),4);self.assertNotIn(notice['id'],{r['id'] for r in listed})
        self.assertFalse((self.data/'report.html').exists())
        report=Path(self.command('report')['output'])
        payload=json.loads(report.read_text().split('<script id="data" type="application/json">')[1].split('</script>')[0])
        self.assertEqual((payload['schema_version'],len(payload['rows'])),(4,4))
        self.command('update','--id',row['id'],'--amount','2.50')
        self.command('remove','--id',row['id'])
        self.assertEqual(len(self.command('list')),3)
        if importlib.util.find_spec('pypdf'):
            from test_pdf_extract import PDFExtractionTests
            pdf=self.root/'statement.pdf';PDFExtractionTests().create(pdf,'synthetic supplied password')
            first=self.command('--input',str(pdf),'--output',str(self.root/'first.json'),'--account','pdf-scope',
                '--passwords-from-stdin',pdf=True,input=json.dumps({'passwords':['synthetic supplied password']}))
            second=self.command('--input',str(pdf),'--output',str(self.root/'second.json'),'--account','pdf-scope','--no-prompt',pdf=True)
            self.assertEqual((first['result'],second['result']),('extracted','extracted'))
            self.assertNotIn('synthetic supplied password',json.dumps([first,second]))

    @unittest.skipUnless(BUN.is_file(),'Install build dependencies with npm ci first')
    def test_plugin_allowlist_rejects_private_state_and_retired_helpers(self):
        repo=self.root/'repository';shutil.copytree(self.plugin,repo/'plugins/moneylens')
        (repo/'scripts').mkdir()
        for name in ('check-plugin.ts','plugin-files.json'):shutil.copy2(ROOT/'scripts'/name,repo/'scripts'/name)
        def check():
            return subprocess.run([str(BUN),str(repo/'scripts/check-plugin.ts')],cwd=repo,capture_output=True,text=True,timeout=30)
        cache=repo/'plugins/moneylens/skills/automation/moneylens/__pycache__/orphan.pyc'
        cache.parent.mkdir(parents=True,exist_ok=True);cache.write_text('synthetic interpreter cache')
        result=check();self.assertEqual(result.returncode,0,result.stderr)
        self.assertFalse((repo/'plugins/moneylens/skills/automation/moneylens/preflight.py').exists())
        self.assertEqual(sorted(p.name for p in (repo/'plugins/moneylens/skills/automation/scripts').glob('*.py')),
                         ['moneylens.py','pdf_extract.py'])
        unlisted=['skills/automation/source-inventory.json','skills/automation/scripts/retired.py',
                  'skills/automation/assets/private-report.html','skills/retired/SKILL.md']
        for name in unlisted:
            path=repo/'plugins/moneylens'/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_text('synthetic private state')
        result=check();self.assertNotEqual(result.returncode,0)
        for name in unlisted:self.assertIn(name,result.stderr)
        for name in unlisted:(repo/'plugins/moneylens'/name).unlink()
        (repo/'plugins/moneylens/LICENSE').unlink()
        result=check();self.assertNotEqual(result.returncode,0);self.assertIn('missing=["LICENSE"]',result.stderr)


if __name__=='__main__':unittest.main()
