"""Public money-management CLI and separate PDF extraction, using only local data."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / 'plugins/moneylens/skills/automation/scripts'
COMMANDS = ('add', 'list', 'update', 'remove', 'import-statement', 'report', 'accounts', 'merchants')


class CommandInterfaceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='moneylens cli ')
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.data = self.root / 'private data'

    def invoke(self, command, *args, input=None, pdf=False):
        prefix = [str(SCRIPTS / ('pdf_extract.py' if pdf else 'moneylens.py'))]
        if command: prefix.append(command)
        if command=='add': prefix += ['--currency','INR','--currency-exponent','2','--kind','purchase']
        environment = os.environ.copy(); environment.pop('PYTHONPATH', None)
        return subprocess.run([sys.executable, *prefix, *args], cwd=self.root,
                              env=environment, input=input, text=True, capture_output=True)

    def output(self, command, *args, **kwargs):
        result = self.invoke(command, *args, **kwargs)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr, '')
        return json.loads(result.stdout)

    def test_accounting_and_pdf_have_separate_entry_points(self):
        self.assertEqual(sorted(path.name for path in SCRIPTS.glob('*.py')), ['moneylens.py', 'pdf_extract.py'])
        result = self.invoke('--help')
        self.assertEqual(result.returncode, 0)
        for command in COMMANDS: self.assertIn(command, result.stdout)
        for command in ('runtime', 'refresh', 'extract', 'preflight', 'begin-run', 'finish-run', 'schedule-attempt'):
            with self.subTest(command=command):
                self.assertNotIn(command, result.stdout)
                self.assertEqual(self.invoke(command).returncode, 2)

    def test_commands_expose_help_and_parser_errors(self):
        for command in COMMANDS:
            with self.subTest(command=command):
                result = self.invoke(command, '--help')
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn(f'usage: moneylens.py {command}', result.stdout)
                self.assertEqual(self.invoke(command, '--unknown-cli-option').returncode, 2)

    def test_partial_flags_and_conflicting_pdf_modes_fail_without_creating_data(self):
        self.assertEqual(self.invoke('report','--data-d',str(self.data)).returncode,2)
        self.assertEqual(self.invoke(None,'--probe','--credential-status',pdf=True).returncode,2)
        self.assertFalse(self.data.exists())

    def test_notification_sources_require_confirmed_accounts(self):
        result=self.invoke('add','--data-dir',str(self.data),'--description','Item','--amount','5',
            '--date','2026-10-24','--category','Supplied category',
            '--metadata',json.dumps({'source':{'mailbox':'unconfirmed','message_id':'notice'}}))
        self.assertEqual(result.returncode,1,result.stderr)
        self.assertIn('confirm accounts',json.loads(result.stderr)['error'])
        self.assertEqual(self.output('list','--data-dir',str(self.data)),[])

    def test_add_update_list_remove_and_report_from_another_directory(self):
        options = ('--data-dir', str(self.data))
        transaction = self.output('add', *options, '--description', 'Coffee', '--amount', '120.50',
                                  '--date', '2026-10-24', '--category', 'Dining', '--metadata', '{"location":"Cafe"}')
        self.assertEqual(transaction['amount_minor'], 12050)
        self.assertEqual(transaction['metadata'], {'location': 'Cafe'})
        changed = self.output('update', *options, '--id', transaction['id'], '--amount', '125', '--category', 'Work expenses')
        self.assertEqual(changed['amount_minor'], 12500)
        self.assertEqual(changed['metadata'], {'location': 'Cafe'})
        self.assertEqual(self.output('list', *options)[0], changed)
        report = self.output('report', *options)
        html = Path(report['output']).read_text()
        data = json.loads(html.split('<script id="data" type="application/json">')[1].split('</script>')[0])
        self.assertEqual(data['rows'][0]['merchant'], 'Coffee')
        self.assertEqual(data['rows'][0]['amount_minor'], 12500)
        self.output('remove', *options, '--id', transaction['id'])
        self.assertEqual(self.output('list', *options), [])

    def test_default_storage_uses_invocation_project_and_preserves_directory_access(self):
        if os.name != 'nt': self.root.chmod(0o755)
        mode = self.root.stat().st_mode
        # Isolate discovery of older installations from the developer's home.
        with patch.dict(os.environ, {'HOME': str(self.root), 'USERPROFILE': str(self.root)}):
            self.output('add', '--description', 'Coffee', '--amount', '120', '--date', '2026-10-24','--category','Dining')
            report = self.output('report')
        self.assertTrue((self.root/'ledger.sqlite3').is_file())
        self.assertEqual(Path(report['output']), self.root.resolve()/'report.html')
        self.assertTrue((self.root/'report.html').is_file())
        self.assertFalse((self.root/'Documents').exists())
        self.assertEqual(self.root.stat().st_mode, mode)

    def test_bad_amount_date_and_metadata_do_not_save_partial_transactions(self):
        options = ('--data-dir', str(self.data), '--description', 'Coffee', '--amount', '120', '--date', '2026-10-24','--category','Dining')
        for flags in (('--amount', 'NaN'), ('--amount', '1.001'), ('--date', '2026-02-30'), ('--metadata', '[1]')):
            result = self.invoke('add', *options, *flags)
            self.assertEqual(result.returncode, 1, result.stderr)
            self.assertIn('error', json.loads(result.stderr))
        self.assertEqual(self.output('list', '--data-dir', str(self.data)), [])

    def test_pdf_failure_keeps_redaction_and_exit_status(self):
        missing = self.root / 'synthetic-private-marker.pdf'
        result = self.invoke(None, '--data-dir', str(self.data), '--input', str(missing), pdf=True)
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stdout, '')
        self.assertEqual(json.loads(result.stderr), {'error': 'PDF processing failed; check the source, output, runtime, and local access'})
        self.assertNotIn('synthetic-private-marker', result.stderr)
        self.assertNotIn('Traceback', result.stderr)

    @unittest.skipUnless(importlib.util.find_spec('pypdf'), 'Install PDF test dependencies')
    def test_pdf_script_derives_and_reuses_credentials_without_accounting_commands(self):
        import test_pdf_extract as support
        pdf = self.root / 'synthetic statement.pdf'
        support.PDFExtractionTests().create(pdf, 'EXAM5678')
        attributes = json.dumps({'passwords':['EXAM5678']})
        options = ('--data-dir', str(self.data), '--input', str(pdf), '--account', 'synthetic-scope')
        first = self.output(None, *options, '--passwords-from-stdin', '--output', str(self.root / 'first.json'), input=attributes, pdf=True)
        second = self.output(None, *options, '--no-prompt', '--output', str(self.root / 'second.json'), pdf=True)
        self.assertEqual(first['result'], 'extracted'); self.assertEqual(second['result'], 'extracted')
        self.assertTrue(json.loads((self.root/'second.json').read_text())['encrypted'])
        self.assertNotIn('EXAM5678', json.dumps(first)); self.assertNotIn('Example Person', json.dumps(first))


if __name__ == '__main__': unittest.main()
