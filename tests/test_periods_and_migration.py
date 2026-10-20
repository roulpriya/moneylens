import datetime as dt
from contextlib import closing
import json
import io
from contextlib import redirect_stdout
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'skills/moneylens-automation/scripts'))
from ledger import connect, default_dir, main as ledger_main
from migrate_storage import migrate
from periods import windows
from runtime_state import config_validated


class PeriodAndMigrationTests(unittest.TestCase):
    def test_report_defaults_do_not_override_explicit_one_sided_ranges(self):
        bounds=windows('UTC',dt.datetime(2026,10,20,tzinfo=dt.timezone.utc))
        cases=[([],('2026-09-01','2026-10-20')),
               (['--to-date','2026-08-31'],('','2026-08-31')),
               (['--from-date','2026-07-01'],('2026-07-01',''))]
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            for flags,expected in cases:
                with self.subTest(flags=flags):
                    argv=['ledger','--data-dir',str(root/'data'),'report','--output',str(root/'report.html')]+flags
                    with patch('sys.argv',argv),patch('periods.windows',return_value=bounds),redirect_stdout(io.StringIO()):
                        ledger_main()
                    text=(root/'report.html').read_text()
                    data=json.loads(text.split('<script id="data" type="application/json">')[1].split('</script>')[0])
                    self.assertEqual((data['from'],data['to']),expected)

    def test_calendar_window_is_separate_from_recent_discovery(self):
        result=windows('Asia/Kolkata',dt.datetime(2026,10,20,8,tzinfo=dt.timezone.utc))
        self.assertEqual((result['discovery_from'],result['discovery_before']),('2026-09-20','2026-10-21'))
        self.assertEqual((result['report_from'],result['report_to']),('2026-09-01','2026-10-20'))

    def test_calendar_window_handles_timezone_year_and_leap_boundaries(self):
        cases=[('2026-01-01T00:00:00+00:00','2025-12-01','2026-01-01'),
               ('2024-03-01T00:00:00+00:00','2024-02-01','2024-03-01'),
               ('2026-09-30T23:30:00+00:00','2026-09-01','2026-10-01')]
        for value,start,end in cases:
            with self.subTest(now=value):
                result=windows('Asia/Kolkata',dt.datetime.fromisoformat(value))
                self.assertEqual((result['report_from'],result['report_to']),(start,end))

    def test_documents_is_default_and_old_data_cannot_be_silently_reset(self):
        with tempfile.TemporaryDirectory() as folder, patch('ledger.Path.home',return_value=Path(folder)):
            self.assertEqual(default_dir(),Path(folder)/'Documents/MoneyLens')
            old=Path(folder)/'Library/Application Support/MoneyLensCodex'
            db=connect(old);db.close()
            with self.assertRaisesRegex(ValueError,'migration'):connect(default_dir())
            self.assertFalse((default_dir()/'ledger.sqlite3').exists())

    def test_migration_preserves_all_tables_and_archives_old_directory(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);source=root/'legacy';target=root/'Documents/MoneyLens'
            db=connect(source)
            with db:
                db.execute("INSERT INTO runtime_meta VALUES ('personal_rules',?)",(json.dumps([{'id':'saved-personal-rule'}]),))
                db.execute("INSERT INTO transaction_annotations VALUES ('record','evidence','Shopping','Personal note')")
                db.execute("INSERT INTO retry_sources VALUES ('retry','{}')")
            db.close()
            (source/'audits').mkdir();(source/'audits'/'evidence.json').write_text('{}')
            target.mkdir(parents=True);(target/'report.html').write_text('Existing report')
            result=migrate(source,target)
            self.assertFalse(source.exists())
            self.assertTrue((Path(result['backup'])/'audits/evidence.json').exists())
            self.assertEqual((target/'report.html').read_text(),'Existing report')
            with closing(sqlite3.connect(target/'ledger.sqlite3')) as db:
                self.assertEqual(db.execute('SELECT note FROM transaction_annotations').fetchone()[0],'Personal note')
                self.assertEqual(db.execute('SELECT count(*) FROM retry_sources').fetchone()[0],1)
                self.assertEqual(db.execute("SELECT value FROM runtime_meta WHERE key='personal_rules'").fetchone()[0],json.dumps([{'id':'saved-personal-rule'}]))
            self.assertEqual((target/'ledger.sqlite3').stat().st_mode&0o777,0o600)

    def test_migration_refuses_an_existing_ledger_or_active_run(self):
        with tempfile.TemporaryDirectory() as folder:
            source=Path(folder)/'source';target=Path(folder)/'target'
            db=connect(source)
            expiry=(dt.datetime.now(dt.timezone.utc)+dt.timedelta(hours=1)).isoformat()
            with db:db.execute("INSERT INTO runtime_meta VALUES ('active_run',?)",(json.dumps({'expires_at':expiry}),))
            db.close()
            with self.assertRaisesRegex(ValueError,'active sync'):migrate(source,target)
            self.assertFalse((target/'ledger.sqlite3').exists())
            other=connect(target);other.close()
            with self.assertRaisesRegex(ValueError,'overwrite'):migrate(source,target)
            self.assertTrue(source.exists())


if __name__=='__main__':unittest.main()
