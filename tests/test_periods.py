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
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'skills/automation'))
from moneylens.private_files import check_private
from moneylens.ledger import connect, default_dir
from moneylens.app import main as app_main
from moneylens.store import config_validated, save_config


class PeriodTests(unittest.TestCase):
    def test_report_defaults_do_not_override_explicit_one_sided_ranges(self):
        cases=[([],('','')),
               (['--to-date','2026-08-31'],('','2026-08-31')),
               (['--from-date','2026-07-01'],('2026-07-01',''))]
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            for flags,expected in cases:
                with self.subTest(flags=flags):
                    argv=['moneylens','report','--data-dir',str(root/'data'),'--output',str(root/'report.html')]+flags
                    with patch('sys.argv',argv),redirect_stdout(io.StringIO()):
                        app_main()
                    text=(root/'report.html').read_text()
                    data=json.loads(text.split('<script id="data" type="application/json">')[1].split('</script>')[0])
                    self.assertEqual((data['from'],data['to']),expected)

    def test_configuration_defaults_report_to_selected_data_directory_and_preserves_saved_path(self):
        payload = {'mailboxes': [{'id': 'synthetic', 'address': 'synthetic', 'verified_at': '2026-10-20T09:00:00+05:30'}], 'cards': [], 'bank_accounts': [{'account_key':'synthetic-bank', 'issuer':'Example Bank', 'masked_identifier':'5678', 'account_label':'Example'}]}
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); data = root/'selected storage'
            with closing(connect(data)) as db, db:
                config = save_config(db, payload)
                self.assertEqual(config['report_path'], str(data.resolve()/'report.html'))
                saved = str(root/'custom report.html')
                save_config(db, {**payload, 'report_path': saved})
                with patch('moneylens.ledger.Path.cwd', return_value=root/'another project'):
                    self.assertEqual(save_config(db, payload)['report_path'], saved)



if __name__=='__main__':unittest.main()
