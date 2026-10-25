---
name: automation
description: Keep an existing MoneyLens ledger and spending report up to date from the financial emails and accounts confirmed during setup. Collect transaction notices and statement PDFs through email MCP, reuse cached merchant categories or classify new merchants, and reconcile provisional transactions against authoritative statements. Refresh spending, incoming money, transfers, and items needing review. Use for scheduled or manual updates and transaction/category corrections; use setup for new accounts, PDF access repair, or schedule changes.
---

# Update MoneyLens

The agent pulls data through the connected email MCP provider. The accounting script accepts local transaction data and manages the ledger and report. The agent interprets institutions, message layouts, sender evidence, account identity, transaction kinds, payment channels, source-specific notation, and new merchant categories before supplying fields; scripts have no bank or email-provider parser catalog. PDF extraction is a separate script. Use the current release's private data directory, confirmed accounts, source history, categories, and report. Pre-release databases and input formats are unsupported; do not convert them or silently replace their files.

Command shorthands use the installed Python 3.10+ executable and absolute skill directory:

- `<moneylens>`: `<python> <automation-skill>/scripts/moneylens.py`
- `<pdf-extract>`: `<python> <automation-skill>/scripts/pdf_extract.py`

Quote paths and JSON for the current shell. No script pulls email, calls MCP, acquires workflow leases, manages scan runs/cursors/retry queues, or schedules work. The agent handles selection, collection dates, pagination, source inventories, unresolved retrievals, and scheduling through the appropriate tools. SQLite transactions protect local accounting writes only.

Prefer static rules and saved decisions whenever the inputs determine the result. Reuse explicit user choices, confirmed account mappings, exact merchant categories, and verified credentials. Use scripts for PDF text extraction, decimal conversion, validation, source identity, reconciliation, statement precedence, totals, and report generation. Do not request LLM classification or recomputation for these operations. Use LLM judgment only for unfamiliar source semantics or uncached merchants that require interpretation; cache resolved merchant decisions for later reuse. Retrieval remains agent-owned through MCP, and deterministic rules must use explicit data rather than embedded country, institution, payment-system, or merchant assumptions.

For a transaction correction, skip collection: use `list`, then `update --id <ID>` with the requested category or metadata and regenerate the report. See [personal context](references/personal-context.md).

## 1. Search for the emails inventoried during setup

Read the saved setup/source inventory and `<moneylens> accounts --data-dir <directory>`. Reuse confirmed opaque account keys, mailbox/source IDs, credential scopes, and report path. Missing or ambiguous account identities go to `$setup`; never silently add accounts.

Verify email MCP access and documented routing. Reuse the user's explicit mailbox selection for this run or the saved mailbox scope authorized for recurring refreshes. When that scope is missing or ambiguous and multiple mailboxes are available, ask which to use. Never expand the selection to all configured or newly available mailboxes. Before collecting each selected mailbox, state “Pulling information from <email address>.” Leave unselected content untouched.

Use MCP directly to search inventoried message IDs and new statements/notifications from the observed institutions and senders. Initial backfill covers the previous calendar month through today. Later collections overlap the last fully completed collection by three days; without reliable dates, repeat the backfill window. Revisit unresolved older sources. The agent records collection progress in the private source inventory, outside scripts and Git.

Search card statements, bank statements, and debit/credit alerts separately; include inline statement tables and all configured account activity. Read every result page and actual source content. Exclude OTPs, promotions, declines, reminders, balance-only notices, and authorization holds. Unsupported financial messages remain for review. See [email and extraction](references/email-and-extraction.md).

## 2. Read, categorize, and add notifications as provisional transactions

Before assigning a category, check the exact merchant cache:

```sh
<moneylens> merchants --data-dir <directory> --merchant 'Example Grocer'
```

A cached category is reused. If `needs_category:true`, the agent decides the category from source context and the user's preferences, then supplies it with `add --category`. There are no built-in merchant lists, keyword classifiers, aliases, or rule engine. The cache matches case/whitespace-normalized exact keys only. For source-name variants, the agent can explicitly supply the same canonical name as `metadata.merchant`; original descriptions stay intact.

For each successful movement, extract description, decimal amount, transaction date, currency and its fractional precision, category, confirmed account key, and metadata with observed source IDs and any exact bank reference. Expenses are positive; incoming money is negative. Choose the movement kind from source evidence: credits are not automatically refunds. Multiple movements need distinct source-row metadata.

Use the simple transaction interface:

```sh
<moneylens> add --data-dir <directory> --description 'Example Grocer' --amount 120.50 --date 2026-10-24 --category Groceries --currency <source-currency> --currency-exponent <source-precision> --kind purchase --account <confirmed-account-key> --provisional --metadata '<source-metadata-JSON>'
```

Metadata is a JSON object. For email notifications, include `source: {mailbox, message_id, filename:"email-body"}`, with optional `reference`, `row`, `channel`, and `account_type`. Supply `--kind`, `--currency`, and `--currency-exponent` as explicit transaction fields. Supply an optional payment-channel label in metadata exactly as evidenced; missing channels stay unknown. There is no currency, precision, country, timezone, or payment-system default. Do not encode kind or precision in metadata. Interpret actual channels and kinds from source evidence; the script does not infer them from descriptions or issuer names. Use stable mailbox IDs from setup. Supplied notification sources remain provisional until statements support them. Repeated source/movement identities are idempotent; do not invent source IDs or references. See the notification fields in the [ledger contract](references/ledger-contract.md).

`add` requires a category on a cache miss and remembers resolved supplied categories for new merchants. For a known merchant, omit `--category` to reuse the cache. Valid statement imports also remember supplied resolved categories. Explicit transaction labels/corrections take priority and do not overwrite an existing cache entry. Use `merchants --merchant <name> --category <category>` only when deliberately changing the reusable merchant decision.

For genuine ambiguity, supply `Other`, keep the merchant uncached, and retain category review for the agent. `Other` is never learned as a reusable decision. Categorization uncertainty does not invalidate a readable amount. Preserve original evidence and use the user's category labels, without imposing a default category taxonomy.

## 3. Retrieve statements through MCP and extract PDFs separately

The agent reads the enclosing email and retrieves original PDF bytes through supported MCP attachment operations. If retrieval fails, use the provider's documented raw-message/MIME fallback where available. Never invent endpoints or automatically follow statement-download, sign-in, or payment links.

Pass the retrieved local PDF to the separate extraction script:

```sh
<pdf-extract> --data-dir <directory> --account <saved-credential-scope> --input <temporary.pdf> --output <new-extraction.json> --no-prompt
```

Unprotected PDFs need no password. Reuse only the verified credential for the confirmed scope. During automation, do not prompt, guess/derive passwords, try unrelated credentials, or install dependencies. The agent records inaccessible/encrypted/unreadable documents and precise nonsecret gaps in its private inventory, routes credential repair to `$setup`, and continues accessible sources. Never claim failed extraction succeeded.

Read all pages and account/currency sections, or the actual inline statement table. Include every source occurrence: all movements, repayments, credits, fees, withdrawals, and both own-transfer legs. Preserve original-byte digest, page/row locations, and independently printed checks in the statement payload's coverage metadata. Never manufacture expected totals from extracted rows. Use the [ledger contract](references/ledger-contract.md). Interpret unfamiliar notation from actual source instructions; unexplained markers do not establish financing or other financial semantics. Preserve original descriptions and supply optional `display_description` / `display_note` metadata when the agent has source-backed display guidance.

The agent deletes temporary PDFs, extraction dumps, and input files after processing. Keep credentials and raw identity inputs out of arguments, logs, skills, and general memory.

## 4. Import statements and reconcile saved transactions

For statement rows with cached merchants, omit `category` to let accounting apply the exact saved mapping directly. An explicit supplied category takes priority. Only uncached merchants need an agent decision; supply their category in the local JSON or explicit `Other` for unresolved cases. A missing uncached category remains for review without invoking an LLM from the script. Then pass the observed source data to accounting:

```sh
<moneylens> import-statement --data-dir <directory> --input <private-statement.json>
<moneylens> list --data-dir <directory>
```

The input may contain one statement or a list of account/currency sections. Accounting validates and saves each source independently, imports safe statements, and leaves incomplete/conflicting evidence for review. Inspect every outcome; one invalid source must not block independent valid ones. Import does not pull data or generate a report.

Match statement rows against saved provisional transactions and existing entries for the same account, currency, and period, including previously supplied mailbox sources. Confirmation requires a validated imported statement row and unique, consistent account/currency/amount/movement evidence. A reference cannot override conflicts; amount/date/merchant similarity alone is insufficient. Preserve user corrections and duplicate provenance. Never clear validation issues to force import.

## 5. Use only statement transactions for covered periods

For an available statement with a resolved account/currency and evidenced inclusive start/end dates, exclude **all** notification-derived entries in that interval from transaction views, totals, counts, and category review. Use only statement transactions for the interval, even when an alert has no individual row match. Keep alerts outside it provisional and isolate other accounts/currencies.

Preserve original alerts as audit evidence; suppression is not proof of a row-level duplicate. Apply the same precedence to later-arriving alerts. Partial statements keep their gaps: alerts must not fill missing rows/pages or imply completeness. An unreadable PDF or unresolved identity cannot establish a period by guesswork.

Every statement occurrence must be retained, proven duplicate-linked, or visibly held for review. Show **Completeness not verified** for missing pages, sections, rows, independent checks, or report visibility. All statements, including imported ones, must meet the current source-evidence checks.

## 6. Update the report from the included template

After accounting is updated, generate the existing report once:

```sh
<moneylens> report --data-dir <directory> --output <saved-report.html> --from-date <analysis-start> --to-date <analysis-end>
```

Date limits are agent-owned: pass `--from-date` / `--to-date` for the intended period; omitting them leaves history unfiltered.

Use the included [report template](assets/report-template.html). Existing reports retain their UI; ordinary runs replace only the bounded JSON data block. Unsupported report templates are rejected; generate a report at a new path. There is no template upgrade command.

Keep Spending, Incoming money, Transfers, All transactions, and Review distinct, with no Notes column. Show confirmed and provisional amounts separately. Refunds reduce spending; repayments do not. Exclude own-account transfers only with ownership evidence, retaining both legs. Keep currencies separate and all account movements visible. Keep checks/provenance in transaction details and unresolved financial/source issues in Review.

The agent reports collection gaps separately from accounting results. Successful imports or report generation do not prove complete MCP pagination or statement completeness. Do not advance the agent's completed collection date after partial retrievals. Report-write failure leaves saved entries intact; regenerate without fetching them again.

Stay quiet when unchanged. Notify on meaningful new data, initial backfill completion, failure, or required user action, with a short delta and report link. Do not change mailbox state, send email, initiate payments, edit helpers/Git, or create schedules during a refresh. Scheduling belongs to the agent's `$setup` workflow.
