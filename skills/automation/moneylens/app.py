"""Local money management: transactions, statements, accounts, and reports."""
import argparse
import json
from pathlib import Path
import sqlite3
import sys
from .ledger import connect, default_dir, require
from . import transactions


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    commands = parser.add_subparsers(dest='command', required=True)
    def command(name, help):
        child = commands.add_parser(name, help=help, allow_abbrev=False)
        child.add_argument('--data-dir', type=Path, default=default_dir())
        return child
    def fields(child, required=False):
        child.add_argument('--description', required=required)
        child.add_argument('--amount', required=required, help='Decimal amount; expenses positive, incoming money negative')
        child.add_argument('--date', required=required, help='YYYY-MM-DD')
        child.add_argument('--category')
        child.add_argument('--kind',required=required,help='Agent-supplied movement type')
        child.add_argument('--metadata', type=json.loads, help='JSON object with extra details or source provenance')
    add = command('add', 'Add a transaction'); fields(add, True)
    add.add_argument('--currency',required=True)
    add.add_argument('--currency-exponent',required=True,type=int,help='Number of fractional digits from source/account metadata')
    add.add_argument('--account',default='manual')
    add.add_argument('--provisional', action='store_true')
    listing = command('list', 'List transactions')
    listing.add_argument('--account'); listing.add_argument('--from-date'); listing.add_argument('--to-date')
    update = command('update', 'Update a transaction'); update.add_argument('--id', required=True); fields(update)
    remove = command('remove', 'Remove a manually added transaction'); remove.add_argument('--id', required=True)
    imported = command('import-statement', 'Import supplied statement JSON and reconcile transactions')
    imported.add_argument('--input', type=Path, required=True)
    report = command('report', 'Generate or update the spending report')
    report.add_argument('--output', type=Path); report.add_argument('--from-date'); report.add_argument('--to-date')
    merchants = command('merchants', 'Look up or save agent-decided merchant categories')
    merchants.add_argument('--merchant')
    merchants.add_argument('--category')
    accounts = command('accounts', 'Show or save confirmed local account settings')
    accounts.add_argument('--input', type=Path)
    prefs = command('preferences', 'Show or save accounting treatments and report date scope')
    prefs.add_argument('--input', type=Path)
    args = parser.parse_args(argv)
    if args.command == 'import-statement':
        require(args.input.stat().st_size <= 20 * 1024 * 1024, 'Statement input exceeds 20 MiB')
        payload = json.loads(args.input.read_text(encoding='utf-8'))
        from .processing import process_batch
        result = process_batch(args.data_dir, [{'type': 'statement', 'payload': p} for p in (payload if isinstance(payload, list) else [payload])], render_report=False)
    else:
        db = connect(args.data_dir)
        try:
            with db:
                db.execute("BEGIN IMMEDIATE")
                if args.command == 'report':
                    from .dashboard import write_report
                    result = write_report(db,args.output,args.from_date,args.to_date)
                elif args.command == 'add':
                    result = transactions.add(db, args.description, args.amount, args.date, args.category, args.currency, args.account, args.provisional, args.metadata,currency_exponent=args.currency_exponent,kind=args.kind)
                elif args.command == 'list':
                    from .ledger import date
                    if args.from_date: date(args.from_date)
                    if args.to_date: date(args.to_date)
                    require(not (args.from_date and args.to_date) or args.from_date <= args.to_date, 'Date range reversed')
                    result = [r for r in transactions.list_transactions(db) if
                        (not args.account or r['account'] == args.account) and
                        (not args.from_date or r['date'] >= args.from_date) and
                        (not args.to_date or r['date'] <= args.to_date)]
                elif args.command == 'merchants':
                    from .merchants import entries, lookup, merchant_key, remember
                    if args.category is not None:
                        require(args.merchant is not None,'Supply --merchant with --category')
                        result=remember(db,args.merchant,args.category)
                    elif args.merchant is not None:
                        category=lookup(db,args.merchant)
                        result={'merchant':merchant_key(args.merchant),'category':category,'needs_category':category is None}
                    else:result=entries(db)
                elif args.command == 'update':
                    result = transactions.update(db, args.id, {k: getattr(args, k) for k in ('description', 'amount', 'date', 'category', 'metadata', 'kind') if getattr(args, k) is not None})
                elif args.command == 'remove': result = transactions.remove(db, args.id)
                elif args.command == 'preferences':
                    from .accounting import preferences
                    if args.input: require(args.input.stat().st_size <= 1024 * 1024, 'Preferences input exceeds 1 MiB')
                    result = preferences(db, json.loads(args.input.read_text(encoding='utf-8')) if args.input else None)
                else:
                    from .store import get, save_config
                    if args.input:
                        require(args.input.stat().st_size <= 1024 * 1024, 'Account settings input exceeds 1 MiB')
                        result = save_config(db, json.loads(args.input.read_text(encoding='utf-8')))
                    else: result = get(db, 'config')
        finally: db.close()
    print(json.dumps(result, ensure_ascii=False))


def run():
    try: main()
    except (ValueError, OSError, sqlite3.Error, KeyError, TypeError) as error:
        print(json.dumps({'error': str(error)}), file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__': sys.exit(run())
