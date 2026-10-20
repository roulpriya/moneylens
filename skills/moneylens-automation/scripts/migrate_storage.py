#!/usr/bin/env python3
"""Move legacy runtime state to Documents, preserving and verifying every table."""
import argparse
from contextlib import closing
import datetime as dt
import json
import os
from pathlib import Path
import shutil
import sqlite3
import sys
import tempfile

from ledger import default_dir, legacy_dir, require


def snapshot(db):
    tables = [r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
    return {table: sorted(db.execute('SELECT * FROM "' + table.replace('"', '""') + '"').fetchall(), key=repr) for table in tables}


def migrate(source, destination):
    os.umask(0o077)
    source, destination = source.resolve(), destination.resolve()
    require(source != destination and source not in destination.parents and destination not in source.parents, 'Source and destination must be separate directories')
    require((source / 'ledger.sqlite3').is_file(), 'Legacy ledger not found')
    require(not (destination / 'ledger.sqlite3').exists(), 'Destination already has a ledger; refusing to overwrite it')
    destination.mkdir(parents=True, exist_ok=True, mode=0o700)
    lock = sqlite3.connect(source / 'ledger.sqlite3', timeout=20)
    temporary = None
    try:
        lock.execute('BEGIN IMMEDIATE')
        active = lock.execute("SELECT value FROM runtime_meta WHERE key='active_run'").fetchone()
        if active:
            expiry = dt.datetime.fromisoformat(json.loads(active[0])['expires_at'])
            require(expiry < dt.datetime.now(dt.timezone.utc), 'Wait for the active sync before migrating storage')
        with tempfile.NamedTemporaryFile(dir=destination, prefix='.ledger-migration-', delete=False) as f:
            temporary = Path(f.name)
        with closing(sqlite3.connect((source / 'ledger.sqlite3').as_uri() + '?mode=ro', uri=True)) as reader, closing(sqlite3.connect(temporary)) as target:
            before = snapshot(reader)
            reader.backup(target)
            require(target.execute('PRAGMA integrity_check').fetchone()[0] == 'ok', 'Copied ledger failed integrity verification')
            require(snapshot(target) == before, 'Copied ledger differs from source')
        os.chmod(temporary, 0o600)
        backups = destination / 'backups'
        backups.mkdir(exist_ok=True, mode=0o700)
        archive = backups / ('legacy-data-' + dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%S%f'))
        os.replace(temporary, destination / 'ledger.sqlite3')
        temporary = None
        try:
            shutil.move(str(source), str(archive))
        except OSError:
            (destination / 'ledger.sqlite3').unlink()
            raise
        return {'result': 'storage_migrated', 'data_dir': str(destination), 'backup': str(archive),
                'table_counts': {name: len(rows) for name, rows in before.items()}}
    finally:
        lock.rollback()
        lock.close()
        if temporary is not None: temporary.unlink(missing_ok=True)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source', type=Path, default=legacy_dir())
    p.add_argument('--destination', type=Path, default=default_dir())
    args = p.parse_args()
    print(json.dumps(migrate(args.source, args.destination)))


if __name__ == '__main__':
    try: main()
    except (ValueError, OSError, sqlite3.Error, KeyError, TypeError) as exc:
        print(json.dumps({'error': str(exc)}), file=sys.stderr)
        sys.exit(1)
