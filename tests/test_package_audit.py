"""Verify the review-ZIP boundary using synthetic archive alterations."""
import importlib.util
import json
from pathlib import Path
import stat
import tempfile
import unittest
import zipfile

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('plugin_zip_audit', ROOT / 'scripts/audit-plugin.py')
audit_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit_module)


@unittest.skipUnless((ROOT / 'dist/moneylens-files.json').is_file(), 'Build the plugin first')
class PackageAuditTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.archive = Path(self.temp.name) / 'review.zip'
        self.expected = json.loads((ROOT / 'dist/moneylens-files.json').read_text())

    def create(self, changed=None, symlink=None, extra=None):
        with zipfile.ZipFile(self.archive, 'w', compression=zipfile.ZIP_DEFLATED) as bundle:
            for name in self.expected:
                data = (ROOT / 'dist/moneylens' / name).read_bytes()
                if changed == name:
                    data = (b'#' if data[:1] != b'#' else b'!') + data[1:]
                entry = zipfile.ZipInfo(name)
                entry.compress_type = zipfile.ZIP_DEFLATED
                if symlink == name:
                    entry.create_system = 3
                    entry.external_attr = (stat.S_IFLNK | 0o777) << 16
                bundle.writestr(entry, data)
            if extra:
                bundle.writestr(extra, b'synthetic unwanted code')

    def test_current_allowlisted_package_has_no_unrelated_modules(self):
        self.create()
        report = audit_module.audit(self.archive, self.expected)
        self.assertEqual(report['file_count'], len(self.expected))
        self.assertNotIn('skills/automation/moneylens/preflight.py', self.expected)
        self.assertTrue(all(item['purpose'] for item in report['inventory']))

    def test_extra_code_private_files_and_traversal_members_are_rejected(self):
        for name in ['extra.py', 'credentials/private.secret', '../escape.py']:
            with self.subTest(name=name):
                self.create(extra=name)
                with self.assertRaisesRegex(ValueError, 'allowlist mismatch'):
                    audit_module.audit(self.archive, self.expected)

    def test_modified_code_cannot_match_the_reviewed_source(self):
        self.create(changed='skills/automation/moneylens/app.py')
        with self.assertRaisesRegex(ValueError, 'differs from current source'):
            audit_module.audit(self.archive, self.expected)

    def test_symlink_member_cannot_enter_the_archive(self):
        self.create(symlink='plugin.json')
        with self.assertRaisesRegex(ValueError, 'not a regular file'):
            audit_module.audit(self.archive, self.expected)
