# Ledger contract

The ledger uses Python standard-library SQLite. Runtime data defaults to `~/Documents/MoneyLens` on all platforms; PDF/Keychain extraction has its own requirements file. Use `--data-dir PATH` before the command for isolation or another mailbox. Migrate legacy data with `scripts/migrate_storage.py` before using the Documents default. Skill files contain no user data. Reports default to the previous calendar month through today in the configured timezone; explicit date arguments override this without deleting older history.

## Stage a statement

Write a private temporary JSON file. All values below are synthetic; replace from actual source evidence.

```json
{
  "source": {"mailbox": "account-identifier", "message_id": "observed-id", "attachment_id": "observed-attachment-id", "filename": "statement.pdf"},
  "account_key": "opaque-stable-mailbox-issuer-card-hash",
  "account_label": "Example Bank · 1234",
  "issuer": "Example Bank",
  "period_start": "2026-09-01",
  "period_end": "2026-09-30",
  "currency": "INR",
  "currency_exponent": 2,
  "complete": true,
  "issues": [],
  "checks": {"expected_transaction_count": 3, "expected_debits_minor": 12000, "expected_credits_minor": 6000, "opening_balance_minor": 10000, "closing_balance_minor": 16000},
  "transactions": [
    {"date": "2026-09-08", "merchant": "Example Grocer", "amount_minor": 12000, "kind": "purchase", "category": "Groceries", "page": 1, "row": "1"},
    {"date": "2026-09-10", "merchant": "Grocer refund", "amount_minor": -1000, "kind": "refund", "category": "Groceries", "page": 1, "row": "2"},
    {"date": "2026-09-15", "merchant": "Payment received", "amount_minor": -5000, "kind": "payment", "category": "Credit card payments", "page": 1, "row": "3"}
  ]
}
```

Optional `source.sha256` is 64 hex characters of original bytes. Omit unavailable independent checks; never derive a supposed statement total from extracted rows to manufacture a passing check. Monetary checks use the statement currency/exponent. Credits are a positive magnitude. Use expected debit/credit totals only if the labeled source totals cover all account movements including payments. Reconcile opening + all signed movements = closing. Include fees and interest once, even from separate sections. Unknown types, incomplete extraction, and `issues` block import. Missing checks are disclosed but do not alone block an explicit import.

Each payload has one account/currency. Foreign purchases showing an original-currency amount alongside a single billing-currency amount are recorded once at the billed amount; do not count both columns. A PDF with genuinely separate billing-currency ledgers is unresolved by this one-source schema: do not invent attachments to split it or mix currencies. Separate documents in different currencies work. Determine the exponent from source/verified currency metadata; don't assume two decimals for every currency. Convert amounts using decimal arithmetic.

Kinds/signs: `purchase`, `fee`, `interest`, `cash_advance`, `adjustment_debit`, `upi_debit`, and `transfer_out` are nonnegative; `refund`, `payment`, `adjustment_credit`, `upi_credit`, and `transfer_in` are nonpositive. `unknown` stages but blocks import. Repayments are excluded from spending. Refunds/credit adjustments reduce net spending. Page and row locate evidence; do not store raw source text or passwords. Set `account_resolved: false` if identity is uncertain (blocks import).

```sh
python3 <skill-dir>/scripts/ledger.py stage --input <private-statement.json>
python3 <skill-dir>/scripts/ledger.py list
python3 <skill-dir>/scripts/ledger.py report --output <deliverables>/moneylens.html --from-date 2026-07-20 --to-date 2026-10-20
```

Date filters are inclusive transaction dates. Whole-statement checks apply before filtering.

## Corrections and import

Use `Subscriptions` as the shared category for recurring software and subscription charges. `Software and subscriptions` and `Software & subscriptions` are aliases, normalized for new extractions and existing report rows. Source categories remain available in report provenance; aliases do not create separate spending buckets or change financial identity.

Restage the same source to correct a draft from evidence. Imported sources cannot be restaged. Source identity uses mailbox/message/attachment or exact filename if no attachment ID. Do not change IDs to bypass checks. Byte-identical attachments in one mailbox and identical account/cycle transaction multisets are skipped. Multisets preserve repeated-row multiplicity and ignore category/order differences.

Cross-statement account/date/normalized merchant/amount/kind matches are potential overlap. They are checked dynamically against drafts and imported history. Resolve confirmed duplicates by removing only confirmed duplicate rows from the new draft and restaging it; omit now-inapplicable whole-statement checks and explain excluded page/rows in `resolution_notes`. `complete: true` then means all intended new rows are accounted for, not that the reduced payload reproduces the original document. If matches are proven distinct purchases, put those new zero-based row indices in `distinct_overlap_rows` and explain in `resolution_notes`. Do not automatically assert either resolution. Ask the user when evidence cannot distinguish cases.

```sh
python3 <skill-dir>/scripts/ledger.py categorize --statement <ID> --row <zero-based-index> --category Dining
python3 <skill-dir>/scripts/ledger.py import --statement <ID>
python3 <skill-dir>/scripts/ledger.py discard --statement <ID>
```

After completed setup, the user's confirmed `auto_save_validated: true` policy authorizes daily imports whose issues are empty; do not ask for each import. Outside that configured daily workflow, use an explicit import request. Repeated imports are idempotent. `discard` removes only drafts. Category changes to imported records require user-requested corrections; they do not change duplicate identity. The dashboard cannot import records. It filters currency/month/account/state/search and dates; unresolved statements are withheld from totals and listed separately.

## Transaction alerts

Use `ledger.py alert --input <private-alert.json>` with the same schema, one successful movement, `checks: {}`, period dates equal to its transaction date, and source `filename: "email-body"`. The row's `row` field is a unique email-body movement reference, such as `body:1`; multiple movements in one email need distinct references. Use the confirmed setup account key, not a guessed new account. Only submit successful posted/completed movements; pending holds, declined attempts, OTPs, and balance-only notices are not spending rows. Such alerts are saved as provisional and shown separately from saved statement transactions. Optional top-level `account_type` is `credit_card` (legacy default) or `bank_account`; row `channel` is `card`, `upi`, or `bank`. UPI bank movements use the bank account key, not a credit-card key. Optional row `reference` is an exact bank-provided transaction identifier; never invent one from merchant/date/amount.

Source-plus-movement identity makes repeated reads idempotent. Shared bank references deduplicate duplicate alert emails for the same account/currency/amount/type. Conflicting or indistinguishable alerts require review instead of silently multiplying spend.

At report time, a unique one-to-one shared reference with matching account, currency, amount, and movement type lets an imported statement replace a provisional alert. The alert is retained as reconciled provenance and excluded from totals. A unique one-to-one account/currency/amount/movement/normalized-merchant match within the posting-date window can also reconcile automatically. Ignore documented merchant location/company suffixes, and preserve ambiguity when repeated rows or competing alerts exist. Opaque UPI recipients may match a unique same-card/same-amount/same-date UPI statement entry; do not fabricate a reference or merchant name. Distinct bank references establish distinct events. An ambiguous amount/date match is withheld for review; the statement stays authoritative. Resolve from evidence using:

```sh
python3 <skill-dir>/scripts/ledger.py reconcile --alert <ID> --statement <ID> --row <zero-based-index> --evidence 'Source-backed reason these are the same movement'
```

Generic `upi_credit` is incoming money and does not reduce net spending. `upi_debit` contributes to outgoing spending unless source evidence classifies it as `payment` or `transfer_out`. Transfers and repayments are excluded from spending. Show UPI debits and credits separately; preserve both source movements of an identified self-transfer without counting them as expenses. A statement row can replace at most one independently saved alert. The report hides reconciled alerts by default; a dedicated filter makes them inspectable. Distinct identical transactions are preserved or held for review rather than guessed away.

## Fixed UI, changing data

`assets/report-template.html` is the committed source of the UI. It is a working empty preview with no account data. First report creation copies its structure and injects ledger data. Later reports replace only JSON inside the unique `MONEYLENS_DATA_START` / `MONEYLENS_DATA_END` block, preserving the rest byte for byte. Untrusted text is JSON-escaped and rendered through `textContent`. No network assets or report-side database mutations exist.

Always pass the configured stable report path. Invalid/missing/duplicate data markers or incompatible template version cause an error without overwriting the existing file. A template upgrade is an explicit development/setup change, never part of daily automation. Keep the data directory, generated reports, credentials, and extracted files out of Git.

New report templates use version 3 for UPI and grouped review details. An explicit setup/development `report --upgrade-template` migration makes a private timestamped backup of the previous HTML before applying the committed UI. Daily runs never use that flag. Missing optional checks and ordinary alert/statement reconciliation are not per-email warnings: retain provenance in collapsed coverage details and group genuine unresolved sources by issue type.
