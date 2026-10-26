"""Native private storage behavior, exercised by each CI OS."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'plugins/moneylens/skills/automation'))
from moneylens.credentials import PrivateFiles
from moneylens.private_files import check_private, protect, regular


def broaden_access(path):
    if os.name == 'nt':
        subprocess.run(['icacls', str(path), '/grant', '*S-1-1-0:(R)'], check=True, capture_output=True)
    else: path.chmod(0o644)


class PortableStorageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.root = Path(self.temp.name)
    def tearDown(self): self.temp.cleanup()

    def test_native_private_store_round_trip_rejects_broader_read_access(self):
        store = PrivateFiles(self.root/'credentials')
        store.save('scope', 'synthetic-value')
        self.assertEqual(store.get('scope'), 'synthetic-value')
        path = store.path('scope'); check_private(path)
        broaden_access(path)
        with self.assertRaisesRegex(ValueError, 'owner-only'): store.get('scope')
        protect(path)
        self.assertEqual(store.get('scope'), 'synthetic-value')

    def test_existing_directory_with_broad_access_is_not_silently_trusted(self):
        path = self.root/'credentials';path.mkdir();protect(path, directory=True)
        broaden_access(path)
        with self.assertRaises(ValueError): PrivateFiles(path)

    def test_hardlinked_credentials_are_rejected_before_read_or_write(self):
        store = PrivateFiles(self.root/'credentials');store.save('scope', 'synthetic-value')
        os.link(store.path('scope'), self.root/'linked')
        with self.assertRaises(ValueError): store.get('scope')
        with self.assertRaises(ValueError): store.save('scope', 'replacement')

    @unittest.skipIf(os.name == 'nt', 'POSIX symlink case; Windows reparse attributes are checked separately')
    def test_symlinked_credentials_and_directories_are_rejected(self):
        store = PrivateFiles(self.root/'credentials')
        target = self.root/'target';target.write_text('synthetic-value', encoding='utf-8')
        store.path('scope').symlink_to(target)
        with self.assertRaises(ValueError): store.get('scope')
        alias = self.root/'alias';alias.symlink_to(store.root, target_is_directory=True)
        with self.assertRaises(ValueError): PrivateFiles(alias)

    def test_reparse_points_are_rejected_before_platform_access_checks(self):
        # The attribute is present on Windows junctions as well as symlinks.
        class Reparse:
            st_mode = 0o40700; st_file_attributes = 0x400; st_nlink = 1
        with patch('moneylens.private_files.Path.lstat', return_value=Reparse()):
            with self.assertRaisesRegex(ValueError, 'reparse'): regular(self.root, directory=True)

    def test_timezone_database_is_available_even_without_system_zoneinfo(self):
        from zoneinfo import ZoneInfo, reset_tzpath
        import datetime as dt
        try:
            reset_tzpath([]);ZoneInfo.clear_cache()
            self.assertEqual(dt.datetime(2026, 1, 1, tzinfo=ZoneInfo('Asia/Kolkata')).utcoffset(), dt.timedelta(hours=5, minutes=30))
        finally: reset_tzpath();ZoneInfo.clear_cache()
