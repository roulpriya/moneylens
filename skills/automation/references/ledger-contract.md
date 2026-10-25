# Ledger contract

In command examples, `<moneylens>` means `<python> <automation-skill>/scripts/moneylens.py`, using the installed Python 3.10+ and the absolute directory of the automation skill (the sibling `automation` directory when reading setup). Quote paths for the current shell; keep each command argument as a separate argument.

The ledger uses Python standard-library SQLite. Runtime data defaults to the current project directory where the user invokes the skill; PDF extraction has its own requirements file. Resolve that directory once and pass its absolute path with `--data-dir PATH` for subsequent helpers and scheduled refreshes; selected mailboxes share one ledger. Open only the current public-release database schema; unsupported data requires a clean directory. Skill files contain no user data. The agent supplies report date limits explicitly; without them, reports include all retained history. Scripts do not choose a timezone, currency, or analysis window.

## Import a supplied statement

Write a private temporary JSON file. All values below are synthetic; replace from actual source evidence.

```json
{
  "source": {"mailbox": "account-identifier", "message_id": "observed-id", "attachment_id": "observed-attachment-id", "filename": "statement.pdf"},
  "account_key": "opaque-stable-financial-account-id",
  "account_label": "Example Bank · 1234",
  "issuer": "Example Bank",
  "account_type": "credit_card",
  "period_start": "2026-09-01",
  "period_end": "2026-09-30",
  "currency": "<source-currency>",
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

Optional `source.sha256` is 64 hex characters of original bytes. Omit unavailable independent checks; never derive a supposed statement total from extracted rows to manufacture a passing check. Monetary checks use the statement currency/exponent. Credits are a positive magnitude. Use expected debit/credit totals only if the labeled source totals cover all account movements including payments. For credit-card liabilities, reconcile opening + all signed movements = closing. For bank cash balances (debits positive, credits negative), reconcile opening − all signed movements = closing. Self-transfers stay in those sums even though excluded from spending. Include fees and interest once, even from separate sections. Unknown types, incomplete extraction, and `issues` block import. Missing checks need source-backed unavailable reasons in the coverage manifest. New statement imports require verified source coverage; a successful write or `complete:true` alone is insufficient. If no independent source check is available, completeness remains unverified and the statement stays for review.

Each payload has one account/currency. Transaction rows may carry a bounded JSON `metadata` object, including agent-supplied canonical `merchant`, `display_description`, and `display_note`. The canonical merchant selects an exact cache key. These do not alter financial identity or original row evidence. Foreign purchases showing an original-currency amount alongside a single billing-currency amount are recorded once at the billed amount; do not count both columns. A combined PDF can yield separate payloads only for source-proven account/currency sections, with their original mailbox/message/attachment IDs and actual page/row locations. Record IDs always include source, account, and currency; never invent attachments or mix currencies. Determine the exponent from source/verified currency metadata; don't assume two decimals for every currency. Convert amounts using decimal arithmetic.

Kinds/signs: `purchase`, `fee`, `interest`, `cash_advance`, `adjustment_debit`, `debit`, `repayment`, and `transfer_out` are nonnegative; `refund`, `payment`, `adjustment_credit`, `credit`, and `transfer_in` are nonpositive. `unknown` stages but blocks import. Repayments are excluded from spending. Refunds/credit adjustments reduce net spending. Page and row locate evidence; do not store raw source text or passwords. Set `account_resolved: false` if identity is uncertain (blocks import).

```sh
<moneylens> import-statement --data-dir <directory> --input <private-statement.json>
<moneylens> list --data-dir <directory>
<moneylens> report --data-dir <directory> --output <deliverables>/moneylens.html --from-date 2026-07-20 --to-date 2026-10-20
```

Date filters are inclusive transaction dates. Whole-statement checks apply before filtering.

## Corrections and import

Prefer deterministic accounting rules and saved mappings over LLM reasoning. The agent supplies new transaction categories; omitted statement-row categories are resolved directly from the exact merchant cache, using `metadata.merchant` when supplied, otherwise the original descriptor. An explicit category takes priority, including explicit `Other`. Cache misses require an agent decision or explicit unresolved review; scripts never call a model. Category labels are stored exactly; no keyword classifier, built-in merchant list, name-shape heuristic, alias map, or conditional rule engine runs in accounting. Input validation, evidence matching, statement precedence, arithmetic, and report generation stay deterministic.

Resubmit the same source/account/currency section with `import-statement` to correct a draft from evidence. Imported financial/source evidence is immutable; identical replays are idempotent. Source identity uses mailbox/message/attachment or exact filename if no attachment ID, qualified for additional account/currency sections without changing existing IDs. Do not change IDs to bypass checks. Every retrieved source section retains its own record, rows and source link. Byte-identical documents can link matching physical source occurrences to terminal retained transactions for the same account/currency. Equal account/cycle transaction multisets alone are potential overlap, not proof of identity. Repeated-row multiplicity is preserved.

Cross-statement account/date/normalized merchant/amount/kind matches are potential overlap. Never remove a source row or omit an original whole-statement check to resolve an overlap. Keep the new occurrence and set `duplicate_of:{"statement":"retained-record-id","index":0,"evidence":"source-backed explanation"}` only when a shared unique source reference or identical original document digest and physical row proves it. Account, currency, exponent, date, amount and compatible movement must agree. Links must be one-to-one within a section and terminate at a retained imported transaction; chains/cycles and amount-only matches fail. Every duplicate occurrence still participates in its original statement arithmetic and coverage, is excluded from spending, and remains visible in All transactions with provenance. If proven distinct, use `distinct_overlap_rows` plus `resolution_notes`; if uncertain retain a review row/reason and keep it out of totals until resolved. Restaging cannot remove previously retained source locations.

```sh
<moneylens> update --data-dir <directory> --id <transaction-ID-from-list> --category Dining
```

`import-statement` stages and validates each supplied section, imports safe sections, and returns per-source outcomes to the agent. Repeated imports are idempotent. Existing draft evidence is retained; never discard rows or invent IDs to bypass validation. Category corrections preserve the original source and accounting identity. The report is read-only and does not import records. Its display filters do not affect whole-statement validation.

## Transaction alerts

Use `<moneylens> add --description <text> --amount <decimal> --date <YYYY-MM-DD> --category <category> --currency <source-currency> --currency-exponent <source-precision> --kind <movement-kind> --account <confirmed-key> --provisional --metadata <JSON>` with the configured data directory and currency. Metadata contains `source: {mailbox, message_id, filename:"email-body"}` plus optional `row` (default `body:1`), `page` (default 1), exact bank `reference`, `channel`, and `account_type`. Multiple movements in one email need distinct `row` references. The accounting layer creates the normalized single-movement payload internally; callers supply ordinary transaction fields. Payment channels must be supplied by the agent when known; description text never selects a channel. Channels are opaque labels; missing values remain unknown. Currency, fractional precision (0–18), and movement kind are required transaction fields and have no inferred defaults. Currency labels are nonempty text, not a hardcoded currency list. Source metadata may include `display_description` and `display_note` for explicit presentation guidance.

Use the confirmed setup account key. Use the source-evidenced account; a payment system does not imply an account type. Only successful movements belong in accounting; OTPs, pending holds, declines, and balance-only notices are excluded by the agent before submission. All supplied notifications remain provisional until supported by statements. A generic credit is incoming money, not an assumed refund. Use positive decimal amounts for expenses, negative for credits, and source-backed kinds for repayments/transfers. Supply the actual exponent with `--currency-exponent`; never round or guess it.

Source-plus-movement identity makes repeated reads idempotent. Shared bank references deduplicate duplicate alert emails for the same account/currency/amount/type. Conflicting or indistinguishable alerts require review instead of silently multiplying spend.

Statement-period precedence is applied before displaying or counting notifications; see **Statement precedence over notifications** below. Independently proven row-level matches may retain provenance and user corrections, but covered notifications never become extra report transactions. For a notification outside all available statement periods, the existing evidence-backed reconciliation rules still apply. A reference cannot override conflicting account/currency/amount/movement evidence. Reconciliation is computed from supplied ledger evidence. Ambiguous matches remain for review; do not fabricate a link to force confirmation.

Generic `credit` is incoming money and does not reduce net spending. `debit` contributes to outgoing spending unless source evidence classifies it as `payment` or `transfer_out`. Transfers and repayments are excluded from spending. Show incoming and outgoing movements separately; preserve both source movements of an identified self-transfer without counting them as expenses. A statement row can replace at most one independently saved alert. Covered notifications are excluded from all transaction views; their original ledger records and source links retain audit history. Outside covered periods, independently reconciled notifications may remain inspectable as provenance. Distinct identical transactions are preserved or held for review rather than guessed away.

## Fixed UI, changing data

`assets/report-template.html` is the committed source of the UI. It is a working empty preview with no account data. First report creation copies its structure and injects ledger data. Later reports replace only JSON inside the unique `MONEYLENS_DATA_START` / `MONEYLENS_DATA_END` block, preserving the rest byte for byte. Untrusted text is JSON-escaped and rendered through `textContent`. No network assets or report-side database mutations exist.

Always pass the configured stable report path. Invalid/missing/duplicate data markers or an unsupported template version cause an error without overwriting the existing file. There is no template upgrade path. Keep the data directory, generated reports, credentials, and extracted files out of Git.

Report template and data schema 4 are required. Keep provenance, completeness evidence and validation checks in transaction details and genuine unresolved sources in Review. Show the source beneath each transaction, including Review transactions. Do not add a Statements tab or standalone source/diagnostics panels.


The configured stable mailbox ID is `source.mailbox`; never substitute a connector routing ID or change an existing source identity. The agent retrieves sources through MCP and passes transaction fields to `add`, statement JSON to `import-statement`, and renders the report with `report`. Validate mailbox/account bindings against setup before supplying payloads. These commands perform accounting; they do not fetch email or coordinate scans. Scan, lease, retry-queue, and scheduler orchestration code has been removed. Duplicate statements observed in several mailboxes retain all mailbox-specific references in `source_links` and report `sources`. Same-ending cards use different confirmed account keys and cannot deduplicate together.


## Bank-account email statements

Bank statements are supported alongside card statements. Use `account_type: "bank_account"`, the confirmed bank `account_key`, and one payload per actual account/currency statement. Read every page or the actual inline-email statement table, using the same validated extraction/import pipeline as card statements. General posted outgoing movements use positive `debit`, incoming movements negative `credit`, and an optional evidenced `channel`. Source-proven purchases, fees and refunds retain their specific kinds. A bank debit paying a credit-card bill uses positive `repayment` (excluded from spending); the credit on a card statement uses negative `payment`. This avoids counting card purchases again at bill payment. `credit` is not an assumed refund or negative spending. Optional independently reported debit/credit totals and opening/closing cash balances apply to **all** movements. No invented totals. Reconciliation compares explicit movement kinds, with account/currency/amount/reference and unique matching evidence required; preserve ambiguous matches.

## Own-account transfers

Keep transfers in the ledger and statement arithmetic. Exclude them from spending, spending counts, categories, monthly totals, and spending summaries. Each source-classified `transfer_out`/`transfer_in` row carries `own_account_key` (the other confirmed owned account) and `transfer_evidence` (concise source/user confirmation). Without that evidence it stays staged for review. Never use a category alone to remove a transaction from spending. Money in excludes only evidence-backed own-account transfers; the raw `transfer_in` label and a Transfers category alone do not establish ownership. Transfer rows lacking ownership evidence remain blocked for financial review, including imported rows. For new extraction, use `credit` for external credits, including income, and reserve transfer kinds for confirmed movements between distinct owned accounts. A payment-system name or the word transfer alone never establishes an own-account transfer.

For an existing statement or alert, use its `list` ID to persist a confirmed exclusion without changing the original kind, amount, status, or matching identity:

```sh
<moneylens> update --data-dir <directory> --id <transaction-ID> --metadata '{"own_account_key":"confirmed-counterparty-key","transfer_evidence":"User or source confirms ownership and this movement"}'
```

Then refresh the same report. Exclusions are anchored to unchanged source row evidence and follow a reconciled alert onto its statement replacement. They survive future refreshes/restaging of unchanged evidence. The report also excludes uniquely paired opposite movements across two confirmed own bank accounts with an identical bank reference/currency/amount. Repeated/conflicting candidates are not automatically excluded. Amount/date/name similarity alone does not prove a self-transfer. Retained transaction rows show `Own-account transfer · Excluded`; the report has no Notes column.

## Evidence-backed source coverage (version 1)

Completeness applies to every transaction row of every retrieved statement for a confirmed account, before classification, matching, spending treatment, or date filters. Read every page and every account/currency section. All payment methods, unfamiliar movements, incoming credits, repayments and both legs of own-account transfers are in scope. No absolute guarantee is made beyond identifiable retrieved documents and observed evidence; search completion does not establish statement completeness.

A new payload adds `coverage` and optional `review_rows`. Original `transactions` retain every normalized source occurrence, including linked duplicates. Each transaction has `source_row_id`; a known movement needing review also has `review_reason`. An unnormalizable occurrence goes in `review_rows` with `source_row_id`, `page`, `row`, `reason`, and only actually readable `amount_minor`/`date` (never substitute zero or an invented date). Exactly one outcome is retained transaction, duplicate-linked occurrence, or visible review row. Unknown amounts prevent arithmetic verification. Unknown movements prevent financial review resolution.

`source.sha256` identifies the original document bytes. An inline statement uses the digest of the original retrieved body. Keep only the digest, bounded locators and normalized evidence; retain no raw source text, credentials or identity attributes. The following is a synthetic structural example (not real extraction evidence):

```json
{
  "coverage": {
    "version": 1, "section_id": "account-currency-section", "page_count": 2,
    "pages": [
      {"page":1,"status":"read","evidence":"Inspected account headings and entire transaction table"},
      {"page":2,"status":"read","evidence":"Inspected continuation table and final summary"}
    ],
    "sections": [{
      "id":"account-currency-section","account_key":"confirmed-account-key","currency":"<source-currency>",
      "pages":[1,2],"evidence":"Account and currency headings on original pages",
      "rows":[{"id":"p1-r1","page":1,"row":"1","amount_minor":2500}],
      "checks": {
        "expected_transaction_count":{"status":"stated","value":1,"page":2,"origin":"source","evidence":"Printed total transaction count"},
        "expected_debits_minor":{"status":"stated","value":2500,"page":2,"origin":"source","evidence":"Printed total debits"},
        "expected_credits_minor":{"status":"stated","value":0,"page":2,"origin":"source","evidence":"Printed total credits"},
        "opening_balance_minor":{"status":"unavailable","reason":"No opening balance printed"},
        "closing_balance_minor":{"status":"unavailable","reason":"No closing balance printed"}
      }
    }]
  }
}
```

`pages` enumerates the independently observed document page count, including blank/summary pages, with `read`, `partial`, or `unreadable` state and an inspection locator. `sections` inventories **all** account/currency sections and their physical pages and source rows, including sections whose processing remains pending. Copy the same document manifest into each section payload with its own `section_id`; all sections must exist durably and agree on the manifest/digest. Never shrink the manifest to the current extraction. Missing/unconfirmed sections remain precise gaps. Each row inventory comes from inspecting the original table, independently of the classified output; do not generate it by iterating the extracted rows.

Inventory all five check names. Every independently stated count, debit/credit total and opening/closing balance must retain its printed value, source page and label/location with `origin:"source"`. The top-level `checks` must exactly equal the stated entries. Unavailable checks require a reason; never turn a printed check into unavailable to pass a mismatch. The ledger cannot authenticate an extractor's observations; the agent must read the actual source. Do not fabricate this manifest, expected totals or page evidence from normalized rows or the `complete` flag.

The ledger compares the inventory with disjoint durable mappings and reconciles the original arithmetic across transactions **and** review rows, including duplicate occurrences, before any exclusions/filters. Offsetting omitted debits and credits can leave a balance unchanged: row inventories and all available independent counts/totals still apply. A readable zero-activity statement needs an explicit printed zero count and matching opening/closing balances plus page/section evidence. Unread pages, unenumerated rows, absent proof, mismatches, conflicting manifests, or UI visibility gaps show **Completeness not verified** with exact gaps. Imported statements must satisfy the same financial and coverage checks as drafts; imported status is not an exemption.

`coverage.verified` / **Source coverage complete** is separate from `financial_review_resolved`. A mapped row with a readable amount but uncertain movement can satisfy source coverage and still need financial review. New unresolved rows stay staged and visible. A successful report write is delivery only. The agent reports MCP collection completion separately; setup/backfill/report readiness are not source-completeness attestations. Accounting commands do not manage collection completion, workflow leases, or cursors.

All transactions clears restrictive date/state/account/search filters when selected, provides history by currency, includes positive bank repayments, incoming credits, both transfer legs, review placeholders and duplicate provenance, and supports pagination/details. Users may apply explicit filters afterward. Existing private HTML retains its UI during ordinary JSON refresh; an old UI without this route remains unverified until a current-format report is delivered. Building this template does not upgrade a private report.

For general account movements, the agent supplies a category from the exact cache or decides it from source context and user preferences. Accounting never replaces a supplied category based on account type or description. Classification does not change kinds, signs, source arithmetic, or spending exclusions. Preserve explicit row corrections. Generic incoming bank credits remain incoming money; never assume income or refund.

## Statement precedence over notifications

A retrieved statement with a resolved account identity takes precedence for its inclusive `period_start` through `period_end`, for the same account and currency. Discard **all** notification-derived financial entries in that interval from transaction views, spending/incoming totals, counts and category review, whether or not a notification can be matched to an extracted statement row. Account/currency isolation and exact statement period boundaries apply across mailboxes. Notifications outside statement periods remain provisional.

This is period-based source precedence, not proof of a one-to-one duplicate. The implementation marks these notification records `statement_covered`; originals and independently proven links remain only as audit evidence, and are not emitted as report transaction rows. Do not fabricate `alert_matches` links for unmatched notifications or remove any statement source row. Independently proven notification annotations/transfer exclusions may still follow their statement target.

An incomplete, staged or unreadable-in-part statement still owns its identified account/currency period. Its missing rows/pages/checks remain visible completeness gaps and its unresolved movements stay for review; notifications must not silently fill those holes or make the report appear verified. An unresolved account identity cannot suppress another account's notifications. Receiving a statement does not establish source coverage or financial review resolution.

## Merchant display and categories

The agent interprets source-specific notation. Optional row `metadata` may contain `display_description` and `display_note`, which accounting uses only for presentation. Preserve the original merchant description and all financial evidence. No institution-specific display cleanup or payment-channel inference runs in the scripts.

Categories come from the agent and user preferences, with no prescribed category taxonomy. Explicit row corrections retain priority over cached classifications. Unknown merchants require an agent decision or explicit `Other` for unresolved review.
