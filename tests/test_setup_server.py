"""Synthetic browser/server boundary checks; never use real private inputs."""
import contextlib
import importlib.util
import io
import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import threading
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('private_setup_server', ROOT / 'plugins/moneylens/skills/setup/scripts/setup_server.py')
setup = importlib.util.module_from_spec(spec)
spec.loader.exec_module(setup)


class SetupServerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.output = Path(self.temp.name) / 'private inputs' / 'setup.json'
        self.context = '</script><script>throw new Error("synthetic")</script>'
        self.server = setup.SetupServer(self.output, ['name', 'phone', 'password'], 'synthetic-scope', self.context)
        self.addCleanup(self.server.server_close)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.server.shutdown)
        self.origin = self.server.origin

    def request(self, path='/', values=None, headers=None):
        body = None if values is None else json.dumps({'values': values}).encode()
        options = {'Content-Type': 'application/json', 'Origin': self.origin, 'X-MoneyLens-Setup': self.server.token}
        options.update(headers or {})
        req = Request(self.origin + path, data=body, headers=options)
        try:
            response = urlopen(req, timeout=5)
        except HTTPError as exc:
            response = exc
        with response:
            return response.status, response.headers, response.read().decode()

    def values(self):
        return {'name': 'Synthetic Example', 'phone': '+000 123 456', 'password': 'synthetic document password'}

    def test_form_submit_writes_private_file_without_echoing_values_or_logging(self):
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code, headers, body = self.request('/submit', self.values())
        self.assertEqual((code, json.loads(body)), (200, {'saved': True}))
        self.assertEqual(headers['Cache-Control'], 'no-store')
        self.assertEqual((stdout.getvalue(), stderr.getvalue()), ('', ''))
        for value in self.values().values():
            self.assertNotIn(value, body)
        setup.check_private(self.output)
        setup.check_private(self.output.parent, directory=True)
        self.assertEqual(json.loads(self.output.read_text()), {
            'schema_version': 1, 'scope': 'synthetic-scope', 'values': self.values()})
        _, _, status = self.request('/status')
        self.assertEqual(json.loads(status), {'saved': True})
        _, _, page = self.request('/setup.html')
        for value in self.values().values():
            self.assertNotIn(value, page)

    def test_cross_origin_bad_token_and_rebinding_host_never_write(self):
        for headers in ({'Origin': 'https://example.invalid'}, {'X-MoneyLens-Setup': 'wrong'},
                        {'Host': 'example.invalid'}, {'Origin': 'null'}):
            with self.subTest(headers=headers):
                code, _, _ = self.request('/submit', self.values(), headers)
                self.assertEqual(code, 403)
                self.assertFalse(self.output.exists())

    def test_extra_missing_empty_and_oversized_values_rejected_without_echo(self):
        for values in ({'name': 'Synthetic'}, {**self.values(), 'unexpected': 'synthetic'},
                       {**self.values(), 'phone': ''}, {**self.values(), 'password': 'x' * 4097}):
            with self.subTest(keys=list(values)):
                code, _, _ = self.request('/submit', values)
                self.assertEqual(code, 400)
                self.assertFalse(self.output.exists())

    def test_existing_file_is_never_overwritten_even_after_server_restart(self):
        self.assertEqual(self.request('/submit', self.values())[0], 200)
        before = self.output.read_bytes()
        self.assertEqual(self.request('/submit', {**self.values(), 'name': 'Replacement'})[0], 409)
        self.assertEqual(self.output.read_bytes(), before)
        with self.assertRaises(ValueError):
            setup.SetupServer(self.output, ['name'], 'synthetic')

    def test_template_is_offline_context_safe_and_only_requested_fields_render(self):
        code, headers, page = self.request('/setup.html')
        self.assertEqual(code, 200)
        self.assertIn("connect-src 'self'", headers['Content-Security-Policy'])
        self.assertIn("frame-ancestors 'none'", headers['Content-Security-Policy'])
        config = json.loads(re.search(r'<script id="setup-config" type="application/json">(.*?)</script>', page).group(1))
        self.assertEqual(config['context'], self.context)
        self.assertNotIn(self.context, page)
        self.assertEqual([field['id'] for field in config['fields']], ['name', 'phone', 'password'])
        self.assertNotRegex(page, r'<(?:script|link|img)\b[^>]*(?:src|href)\s*=')
        self.assertIn('data:font/woff2;base64,', page)
        self.assertNotIn('localStorage', page)
        self.assertNotIn('sessionStorage', page)

    def test_expired_session_cannot_write(self):
        self.server.expires_at = 0
        self.assertEqual(self.request('/submit', self.values())[0], 410)
        self.assertFalse(self.output.exists())

    def verification_server(self, fields, request=None):
        from pypdf import PdfWriter
        self.pdf = Path(self.temp.name) / 'protected.pdf'
        writer = PdfWriter()
        writer.add_blank_page(width=72, height=72)
        writer.encrypt('SYNT5678')
        writer.write(self.pdf)
        self.data_dir = Path(self.temp.name) / 'private ledger'
        self.output = Path(self.temp.name) / 'verification' / 'receipt.json'
        self.server = setup.SetupServer(self.output, fields, 'verified-scope', request=request,
                                        pdf=self.pdf, data_dir=self.data_dir)
        self.addCleanup(self.server.server_close)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.shutdown)
        self.origin = self.server.origin

    def test_wrong_details_never_save_inputs_credentials_or_success(self):
        self.verification_server(['password'])
        code, _, body = self.request('/submit', {'password': 'synthetic wrong candidate'})
        self.assertEqual((code, json.loads(body)), (422, {'saved': False, 'verified': False, 'code': 'unlock_failed'}))
        self.assertFalse(self.output.exists())
        self.assertFalse(list(self.data_dir.rglob('*.secret')))
        self.assertNotIn('synthetic wrong candidate', body)

    def test_local_recipe_verifies_actual_pdf_and_persists_only_working_password(self):
        request = {'bank': 'Synthetic Bank', 'statement_type': 'Savings statement',
                   'period': 'September 2026', 'account_hint': 'Synthetic masked account',
                   'email_subject': 'Synthetic statement email', 'email_date': 'October 1, 2026',
                   'email_url': 'https://example.invalid/message/synthetic-only',
                   'instructions': 'Observed synthetic fixture recipe; not an issuer default.',
                   'field_help': {'name': 'Use the statement name.', 'phone': 'Use the required phone digits.'},
                   'recipe': {'parts': [{'field': 'name', 'slice': [0, 4], 'case': 'upper'},
                                        {'field': 'phone', 'digits_only': True, 'slice': [-4, None]}]}}
        self.verification_server(['name', 'phone'], request)
        values = {'name': 'Synthetic Example', 'phone': '+000 123 45678'}
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code, _, body = self.request('/submit', values)
        self.assertEqual((code, json.loads(body)), (200, {'saved': True, 'verified': True}))
        self.assertEqual((stdout.getvalue(), stderr.getvalue()), ('', ''))
        receipt = self.output.read_text()
        self.assertEqual(json.loads(receipt), {'schema_version': 1, 'scope': 'verified-scope',
                                              'verified': True, 'credential_saved': True})
        for value in [*values.values(), 'SYNT5678']:
            self.assertNotIn(value, receipt + body)
        store = setup.selected(self.data_dir)
        self.assertEqual(store.get('verified-scope', True), 'SYNT5678')
        setup.check_private(store.path('verified-scope'))
        # Exercise the existing extraction interface without any new secret input.
        extracted = subprocess.run([sys.executable, str(ROOT / 'plugins/moneylens/skills/automation/scripts/pdf_extract.py'),
            '--data-dir', str(self.data_dir), '--input', str(self.pdf), '--output', str(self.output.parent / 'extraction.json'),
            '--account', 'verified-scope', '--no-prompt'], capture_output=True, text=True, timeout=15)
        self.assertEqual(extracted.returncode, 0, extracted.stderr)
        self.assertEqual(json.loads(extracted.stdout)['result'], 'extracted')
        self.assertNotIn('SYNT5678', extracted.stdout + extracted.stderr)

    def test_known_inputs_are_not_requested_or_exposed_in_browser_config(self):
        request = {'recipe': {'known_values': {'name': 'Synthetic Known Name'},
                             'parts': [{'field': 'name', 'slice': [0, 4], 'case': 'upper'},
                                       {'field': 'phone', 'slice': [-4, None]}]}}
        self.verification_server(['phone'], request)
        _, _, page = self.request('/setup.html')
        self.assertNotIn('Synthetic Known Name', page)
        code, _, body = self.request('/submit', {'phone': '0005678'})
        self.assertEqual((code, json.loads(body)), (200, {'saved': True, 'verified': True}))

    def test_direct_document_password_is_verified_before_storage(self):
        self.verification_server(['password'])
        code, _, body = self.request('/submit', {'password': 'SYNT5678'})
        self.assertEqual((code, json.loads(body)), (200, {'saved': True, 'verified': True}))
        self.assertNotIn('SYNT5678', self.output.read_text() + body)
        self.assertEqual(setup.selected(self.data_dir).get('verified-scope', True), 'SYNT5678')

    def test_source_email_links_reject_executable_or_credential_bearing_urls(self):
        for url in ['javascript:alert(1)', 'data:text/html,synthetic', 'https://user:password@example.invalid/mail']:
            with self.subTest(url=url), self.assertRaises(ValueError):
                setup.request_details({'email_url': url})

    def test_recipe_operations_cannot_execute_code_or_ask_for_unused_inputs(self):
        for recipe in ({'parts': [{'eval': 'synthetic'}]},
                       {'parts': [{'field': 'unknown'}]}, {'parts': [{'field': 'name', 'case': 'execute'}]},
                       {'parts': [{'literal': 'synthetic'}]}):
            with self.subTest(recipe=recipe), self.assertRaises(ValueError):
                setup.validate_recipe(recipe, ['name'])

    def test_exhausted_attempts_cannot_save(self):
        self.verification_server(['password'])
        for _ in range(5):
            self.assertEqual(self.request('/submit', {'password': 'synthetic wrong'})[0], 422)
        _, _, body = self.request('/submit', {'password': 'SYNT5678'})
        self.assertEqual(json.loads(body)['code'], 'attempts_exhausted')
        self.assertFalse(self.output.exists())

    def test_changed_pdf_cannot_be_verified_under_original_request(self):
        self.verification_server(['password'])
        self.pdf.write_bytes(self.pdf.read_bytes() + b'\n% synthetic changed source\n')
        code, _, _ = self.request('/submit', {'password': 'SYNT5678'})
        self.assertEqual(code, 400)
        self.assertFalse(self.output.exists())
        self.assertFalse(list(self.data_dir.rglob('*.secret')))


if __name__ == '__main__':
    unittest.main()
