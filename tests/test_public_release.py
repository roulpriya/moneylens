"""The public release accepts one schema and never upgrades pre-release data."""
from contextlib import closing
import copy
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'skills/automation'))
from moneylens.ledger import SCHEMA_VERSION, connect, normalize, records, source_id
from moneylens.store import config_validated, save_config
from moneylens.processing import process_batch
from test_ledger import fixture
from coverage_fixtures import observed_statement

SCRIPTS=Path(__file__).resolve().parents[1]/'skills/automation/scripts'


class PublicReleaseTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)

    def settings(self):
        return {'mailboxes':[{'id':'synthetic-test','address':'test@example.invalid'}],
            'report_path':str(self.root/'report.html'),
            'cards':[{'account_label':'Synthetic account','account_key':'test-card-a','issuer':'Example issuer','masked_identifier':'1234',
                'credential_scope':'scope-a','password_status':'not_required'}]}

    def invoke(self,*arguments,pdf=False):
        return subprocess.run([sys.executable,str(SCRIPTS/('pdf_extract.py' if pdf else 'moneylens.py')),*arguments],cwd=self.root,capture_output=True,text=True)

    def test_fresh_database_has_only_the_public_schema_and_reopens(self):
        with closing(connect(self.root/'data')) as db:
            self.assertEqual(db.execute('PRAGMA user_version').fetchone()[0],SCHEMA_VERSION)
            tables={r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            self.assertTrue({'settings','processing_results','user_transactions','transaction_metadata'} <= tables)
            self.assertFalse({'runtime_meta','source_dispositions','retry_sources','category_edits'} & tables)
        with closing(connect(self.root/'data')) as db:self.assertEqual(records(db),[])

    def test_unversioned_or_unsupported_databases_are_rejected_without_modification(self):
        for version in (0,99):
            with self.subTest(version=version):
                folder=self.root/str(version);folder.mkdir()
                path=folder/'ledger.sqlite3'
                with closing(sqlite3.connect(path)) as db, db:
                    db.execute('CREATE TABLE private_original (value TEXT)')
                    db.execute("INSERT INTO private_original VALUES ('retained')")
                    db.execute(f'PRAGMA user_version={version}')
                original=path.read_bytes()
                with self.assertRaisesRegex(ValueError,'Unsupported MoneyLens database schema'):connect(folder)
                self.assertEqual(path.read_bytes(),original)
                with closing(sqlite3.connect(path)) as db, db:self.assertEqual(db.execute('SELECT value FROM private_original').fetchone()[0],'retained')

    def test_obsolete_account_fields_are_rejected_instead_of_translated(self):
        for key,value in [('mailbox','old'),('upi_accounts',[]),('gmail_verified_at','2026-10-20'),('daily_time','09:00'),('automation_id','old'),('auto_save_validated',True),('confirmed_card_count',1)]:
            with self.subTest(key=key):
                with self.assertRaisesRegex(ValueError,'Unsupported account settings fields'):config_validated({**self.settings(),key:value})
        value=self.settings();value['cards'][0]['keychain_scope']=value['cards'][0].pop('credential_scope')
        with self.assertRaisesRegex(ValueError,'Unsupported account fields'):config_validated(value)

    def test_removed_commands_and_flags_fail_before_creating_data(self):
        cases=[(('accounts','--move-from',str(self.root/'old')),False),
            (('report','--upgrade-template'),False),
            (('add','--description','Coffee','--price','5','--date','2026-10-24'),False),
            (('--keychain-status',),True),(('--previous-account','old'),True),(('--derive-from-stdin',),True),(('--verify-derived-only',),True)]
        for arguments,pdf in cases:
            with self.subTest(arguments=arguments):
                result=self.invoke(*arguments,pdf=pdf)
                self.assertEqual(result.returncode,2,result.stderr)
        self.assertFalse((self.root/'ledger.sqlite3').exists())
        self.assertFalse((SCRIPTS.parent/'moneylens/migrate_storage.py').exists())

    def test_internal_modules_have_no_secondary_command_interfaces(self):
        for name in ('ledger','store','processing','transfers','preflight'):
            with self.subTest(module=name):
                module=__import__('moneylens.'+name,fromlist=['main'])
                self.assertFalse(hasattr(module,'main'))

    def test_saved_account_key_cannot_move_between_account_types(self):
        with closing(connect(self.root)) as db,db:
            original=save_config(db,self.settings())
            changed=self.settings();changed['bank_accounts']=[changed['cards'].pop()]
            with self.assertRaisesRegex(ValueError,'account type'):save_config(db,changed)
            from moneylens.store import get
            self.assertEqual(get(db,'config'),original)

    def test_unsupported_report_template_is_not_rewritten_or_upgraded(self):
        report=self.root/'report.html';original='<meta name="moneylens-template-version" content="3">Original private report'
        report.write_text(original)
        result=self.invoke('report','--data-dir',str(self.root/'data'),'--output',str(report))
        self.assertEqual(result.returncode,1,result.stderr)
        self.assertIn('Unsupported report template',json.loads(result.stderr)['error'])
        self.assertEqual(report.read_text(),original)
        self.assertFalse(list(self.root.glob('*.before-upgrade-*')))

    def test_section_identity_does_not_depend_on_import_order(self):
        first=observed_statement(fixture())
        second=copy.deepcopy(first);second['account_key']='card-b'
        second=observed_statement(second)
        expected={p['account_key']:source_id(normalize(p)) for p in (first,second)}
        actual=[]
        for i,batch in enumerate(((first,second),(second,first))):
            folder=self.root/f'order-{i}'
            config=self.settings();config['cards'].append({'account_label':'Synthetic account',**config['cards'][0],'account_key':'card-b','masked_identifier':'5678'})
            config['report_path']=str(folder/'report.html')
            with closing(connect(folder)) as db,db:save_config(db,config)
            process_batch(folder,[{'type':'statement','payload':p} for p in batch],render_report=False)
            with closing(connect(folder)) as db:actual.append({r['payload']['account_key']:r['id'] for r in records(db)})
        self.assertEqual(actual,[expected,expected])


if __name__=='__main__':unittest.main()
