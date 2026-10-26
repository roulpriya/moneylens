# MoneyLens

[![Validate](https://github.com/roulpriya/moneylens/actions/workflows/validate.yml/badge.svg)](https://github.com/roulpriya/moneylens/actions/workflows/validate.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

A ChatGPT and Codex plugin that turns your bank and card emails into a local spending report. MoneyLens keeps a SQLite ledger on your machine, matches alerts against statements, and updates the same HTML report each time it syncs.

## Install the plugin

MoneyLens includes one setup skill and one automation skill in the `plugins/moneylens` folder, which carries both a portable `plugin.json` and a Claude Code manifest at `.claude-plugin/plugin.json`. It runs in a **local agent session** with email MCP and scheduling tools; packaging does not give a cloud-only session access to your local files.

For local testing, clone the repository and register its marketplace:

```sh
git clone https://github.com/roulpriya/moneylens.git
cd moneylens
codex plugin marketplace add .
```

Reload plugins in your host, open its plugin directory, choose the **MoneyLens** source, and install MoneyLens. The repository's `.agents/plugins/marketplace.json` points to `plugins/moneylens`. In Claude Code, load the folder directly with `claude --plugin-dir plugins/moneylens`. That folder is the complete release: hosts install it as committed.

The two skills can still be installed together using the Skills CLI:

```sh
npx skills add roulpriya/moneylens --skill setup automation
```

Plugin installation does not connect an email account or create a daily schedule. Run setup after installation.

## Python command interface

Bank categories `Investment` and `Investment withdrawal` keep principal visible
in Cashflow while excluding it from spending and ordinary incoming-money
metrics. Posted interest retains its own evidence and category. The report's
Cashflow section uses bank inflows less outflows, including repayments and
investment movements. Balance snapshots remain document limitations and never
create missing-transaction placeholders.

`preferences --data-dir <directory>` reads saved category treatments and report
dates; `preferences --input <private-preferences.json>` updates them. Successful
reports retain their date scope for refreshes that omit both bounds. Explicit
one-sided ranges clear the other bound; empty strings for both clear the scope.
Rolling schedules should pass fresh dates each run. See
[accounting preferences](plugins/moneylens/skills/automation/references/personal-context.md).

The collapsed Accounting treatment and exclusions audit separates validation
blocks, uncategorized amounts that still count, transfers/repayments, investment
principal, duplicates and rows outside selected dates. Statement-covered alert
counts remain internal unless requested. New UI
features require a report generated with the current template at a new path;
ordinary refreshes preserve existing private HTML.

Collection uses at most three in-flight message/attachment reads and checkpoints
nonsecret progress after every durable source result. See the agent's
[collection recovery protocol](plugins/moneylens/skills/automation/references/collection-progress.md).

The agent searches and retrieves email through MCP, then supplies local inputs to two scripts. Accounting uses a small money-management interface:

Prefer static rules and saved mappings over LLM calls. Accounting, reconciliation, totals, reporting, and PDF extraction are deterministic. Known merchants reuse cached categories, including statement rows whose category is omitted. LLM interpretation is reserved for unfamiliar source content and new uncached merchants; resolved decisions are cached for reuse. Explicit transaction categories take priority.

```sh
<moneylens> add --data-dir <directory> --description 'Coffee' --amount 120.50 --date 2026-10-24 --category Dining --currency <source-currency> --currency-exponent <source-precision> --kind purchase --metadata '{"location":"Cafe"}'
<moneylens> merchants --data-dir <directory> --merchant 'Coffee shop'
<moneylens> list --data-dir <directory>
<moneylens> update --data-dir <directory> --id <transaction-ID> --category 'Work expenses'
<moneylens> remove --data-dir <directory> --id <manual-transaction-ID>
<moneylens> import-statement --data-dir <directory> --input <statement.json>
<moneylens> report --data-dir <directory>
<moneylens> accounts --data-dir <directory>
```

`<moneylens>` means `<python> <automation-skill>/scripts/moneylens.py`.
Transactions have description, decimal amount, date,
category, account, explicit currency and fractional precision, explicit movement type, and optional JSON metadata. The agent supplies a category for a new merchant; known merchants reuse an exact cached decision. The scripts have no merchant keyword rules or built-in classifications. `Other` remains uncached for review. `metadata.merchant` can supply an explicit canonical merchant key while retaining the original description. Email-sourced transactions
are provisional until reconciled to statements. Source evidence is preserved when
updating categories/metadata; manual entries can also have their amount/date edited
or be removed. Statement import validates supplied JSON without generating a report;
run `report` after accounting is updated.

PDF extraction is a separate script:

```sh
<python> <automation-skill>/scripts/pdf_extract.py --data-dir <directory> --input <statement.pdf> --output <new-extraction.json> --account <saved-scope> --no-prompt
```

Resolve the installed Python 3.10+ executable and absolute automation skill directory
(`plugins/moneylens/skills/automation` in this checkout), and quote paths/JSON for your shell. Neither
script pulls data, calls MCP, manages workflow leases/scans/retry queues, or schedules
jobs. The agent owns those workflow decisions and uses MCP and scheduling tools
directly. This public release requires its current database and input schemas. Pre-release data formats are rejected without modification; start with a clean data directory. Implementation lives in the internal
`plugins/moneylens/skills/automation/moneylens` package.

## Requirements

The workflow uses local Python helpers and a browser report on macOS, Linux or Windows. The host must expose local file execution, email MCP access and scheduling for daily updates; installing the skill does not supply those capabilities.

- Private local storage for verified, derived PDF passwords (owner-only permissions or Windows ACLs, plaintext at rest). The agent uses the source's documented recipe and verified identity details, then passes literal candidates to the separate PDF script through transient stdin; no system credential service or separate password-entry dialog is required.
- Python 3.10 or later. Ledger and configuration helpers use the standard library. PDF extraction uses pypdf/cryptography; no operating-system credential framework is required.
- Setup uses the installed Python 3.10+ and installs the pinned `plugins/moneylens/skills/automation/scripts/requirements.txt`, including timezone data for systems without it. No compiler is required.
- Bun 1.4.3 is a development-only build dependency. Installed daily workflows use the committed HTML asset and installed Python.
- A connected email MCP provider with profile, search, message, and attachment or raw-MIME access.
- A Codex host exposing the automation scheduling tool for daily updates. Installation alone does not create a schedule or connect an email account.

Both installed skill folders must remain siblings because setup reads the automation skill's shared scripts and references. The Skills CLI's canonical skill directory preserves this layout.

## Start using MoneyLens

Ask your agent:

```text
Use $setup to set up my spending report and daily updates.
```

Setup first verifies connected email MCP access and stops with a Plugins connection instruction if none is available. It then searches the last 30 days for card and bank activity, local payment systems, and statements; confirms detected accounts; reads enclosing statement emails for password recipes; and asks only for missing recipe inputs. It lists source emails and instructions, checks local extraction/storage capabilities, and uses the sibling automation skill to backfill the previous calendar month plus the current month and prepare one report. Setup reviews Other by count and spending and configures recurring refreshes at your confirmed local time. The agent reuses its private source inventory and existing choices.

After setup:

```text
Use $automation to refresh my spending report.
```

You can ask it to correct a transaction category or add metadata and refresh the existing report. Check cached merchant decisions with `merchants`; the agent categorizes cache misses and saves reusable decisions. Row-specific corrections remain separate.

Before every email pull, MoneyLens states the selected email address. It reuses the mailbox scope explicitly authorized for the current pull or recurring refreshes. If that scope is missing or ambiguous and multiple accounts are available, it asks which to use; it never silently expands to all saved accounts. Only selected mailboxes are accessed; collection progress and unresolved retrievals belong to the agent's private source inventory.

The report uses confirmed spending when available; otherwise its headline, category breakdown, and daily chart show eligible provisional amounts labeled Provisional. Confirmed zero amounts stay confirmed. The transaction summary keeps confirmed net spending, provisional net spending, their combined estimate, and refunds separate. Spending, Incoming money, Cashflow, Transfers, All transactions and Review are separate views with search, sortable columns, pagination and transaction details. Source evidence is available through each transaction’s View details button. Transaction details include full provenance, statement completeness and validation checks; unresolved source issues remain in Review. Confirmation describes the transaction evidence, not complete calendar-month coverage. Current-format reports retain their UI on ordinary refresh. Unsupported templates are rejected; generate a new report instead.

| Skill | Purpose |
| --- | --- |
| [setup](plugins/moneylens/skills/setup/SKILL.md) | Initial setup, account confirmation, PDF password verification, and schedule creation or repair |
| [automation](plugins/moneylens/skills/automation/SKILL.md) | Daily or manual sync, alert reconciliation, agent-decided merchant categories, and report updates |

Run the skill in the project directory you opened. New installations default to that current directory (`Path.cwd()`), with `report.html`, `ledger.sqlite3`, settings and credentials stored there; Documents is not required. `--data-dir` selects another location. Existing installations keep their saved data directory and report path. Setup passes the resolved absolute data directory to helpers and scheduled refreshes so later working directories cannot redirect the installation. Keep generated private files out of Git. All selected email accounts feed one ledger and report through stable mailbox-specific provenance. The agent supplies the intended report date range, initially the previous calendar month through today; without date flags the script includes all retained history. Account discovery uses a separate 30-day window.

## Report appearance

Money in and Money out appear side by side with equal size and emphasis. Money out is net spending after refunds. Confirmed/provisional evidence and pending amounts are shown independently for each side; refunds, net bank cashflow, and daily average appear below.

Hover a daily, category, or monthly overview chart bar to see its amount and context. Keyboard focus shows the same tooltip; Escape dismisses it. Category tooltips distinguish purchase amounts from net spending after refunds.

New reports use the website's MoneyLens styling: cream backgrounds, sage accents, DM Sans text, and bundled Newsreader type. Choose **Edit report** to move sections with the up/down controls and change the theme, section backgrounds, or chart colours. **Done** hides the controls; **Reset to default** restores the MoneyLens theme. Existing saved Paper, Sage, and Midnight preferences remain available. Overall overview and monthly totals remain available in collapsed sections; Review remains its own tab.

Appearance settings contain only colours and component order and are saved in this browser's local storage. They survive reloads and report refreshes at the same path in that browser. A different browser or moved report may have separate settings. When storage is unavailable, the editor says that changes last only until reload. No transaction, credential, or ledger data is changed by these controls.

## Public-release formats

The release uses database schema 1 and report template/data schema 4. It opens only
its own database tables and version. It does not locate, convert, or import older
application databases, settings, reports, or browser preferences. Choose a clean
private data directory for initial setup and let the agent read original financial
sources through MCP. Existing unsupported files remain untouched.

Account settings use `mailboxes`, `bank_accounts`, and `credential_scope` only.
Scheduling and source-inventory state belong to the agent. The PDF script uses
only its scoped private-file credentials. Unsupported field names and command flags
fail explicitly; there are no storage or template upgrade commands.

## How data is handled

- PDF passwords are derived from issuer instructions and verified identity details, then remembered in an owner-only private-file store (plaintext at rest, POSIX 0700 directories / 0600 files or protected current-user Windows ACLs). Identity inputs stay transient; values do not belong in skill Markdown, general agent memory, chat output, command arguments, environment variables, configuration, or Git.
- The local ledger stores structured transactions, masked account metadata, source references, and cached merchant categories. It uses file permissions rather than application-level encryption.
- Working PDFs and extraction files are temporary; the workflow removes its own copies after processing. Email provider and connector retention are separate.
- The HTML report contains private financial data. Keep generated reports and runtime data out of this public repository.
- Daily runs preserve the report layout and update its JSON data block. Ambiguous records remain available for review.

MoneyLens reads email through a connected MCP provider. It does not send mail, change mailbox labels, or initiate payments. It only covers evidence available in email; it does not imply access to SMS or payment-app-only transactions. The agent interprets actual source evidence for every provider and institution, then passes normalized transaction fields to accounting. There are no institution-specific email parsers or sender allowlists in the scripts. Scanned PDFs without extractable text need separate handling.

Setup checks inline and attached images for instructions missing from email text and corroborates statement-unlock formats against official issuer web guidance before asking for missing details. Only successful local decryption verifies the actual PDF. User-input tools ask exactly one question requesting one value or decision at a time, then wait for the answer; related details are never combined into the single text field.

## Development

```sh
npm ci
npm run build
<python> -m venv .venv
<venv-python> -m pip install -r plugins/moneylens/skills/automation/scripts/requirements.txt
<venv-python> -m unittest discover -s tests -v
```

Use an installed Python 3.10+ executable for `<python>` (`python`, `python3` or `py -3`, as available). `<venv-python>` is `.venv/Scripts/python.exe` on Windows or `.venv/bin/python` on POSIX systems. Resolve paths locally and quote them using the current shell; activation is unnecessary. `npm test` prefers this local `.venv`; `MONEYLENS_TEST_PYTHON` can select another interpreter by absolute path.

The report source is `src/report.html`, `src/report.css`, and `src/report.js`, with shared website/report fonts and palette in `src/brand.css`. Font sources and their OFL notices live in `src/fonts`. Bun compiles the CSS and JavaScript into `plugins/moneylens/skills/automation/assets/report-template.html` and writes the fonts with their license notices to `report-fonts.html` beside it, keeping each file small enough for plugin directory review. A new report inlines the fonts at the template's `MONEYLENS_FONTS` marker, so every generated report is still one offline file. Edit the source and regenerate these compiled files; do not hand-edit the skill's HTML assets. The bounded JSON data markers remain the only daily-update boundary. Existing private reports retain their appearance on refresh; generate a new report at a new output path to use the new compiled template.

With Bun installed, use `bun run build:report` to regenerate the skill template, `bun run check:report` to verify it matches its source without writing, or `bun run build` to compile both templates. `bun run check:plugin` verifies that `plugins/moneylens` holds exactly the files listed in `scripts/plugin-files.json`: the manifests, both skills and their maintained runtime files, README, and license. It fails on any unlisted file, so source CSS, font files, build dependencies, runtime data, and development scripts stay out of the release. After `npm ci`, the corresponding `npm run` commands use the repository-pinned Bun executable. Installed workflows need Python but do not need Bun or a font service.

Tests use synthetic records, temporary directories, and fake credential stores. PDF tests cover encrypted and unprotected documents without live email access or system credential services. CI is configured to run on macOS, Linux and Windows, test the Python interface and both report suites, check the plugin folder against its allowlist, exercise a copy of it outside the repository, and verify the committed HTML asset.

The portable plugin format and local marketplace follow the [official OpenAI packaging documentation](https://developers.openai.com/plugins/build/plugins).

## License

[MIT](LICENSE) — copyright 2026 Priyambada Roul.

Setup asks about recurring refreshes only after selected data is connected, statement PDFs are decrypted and read, the initial ledger import/reconciliation is complete, and the first report link is delivered. Missing unlock/access details are resolved first; reduced coverage requires an explicit user choice and visible report gaps. Schedule questions use the available user-input tool at this final step. Report readiness and automation activation remain separate: scheduler failure preserves the report and existing authorization, and the agent checks saved job IDs before retrying. Prompts reference the skill and private data directory instead of embedding configuration. The command interface and internal package ship together in the plugin.

MoneyLens covers bank-account email statements (PDF and actual inline statement tables), including every payment method and cash-balance checks. Confirmed transfers between your own accounts remain in the ledger for reconciliation but are excluded from spending, categories, monthly totals, and spending counts.

### Statement completeness

New bank/card statement imports require a versioned page/section/source-row manifest and reconciliation of every available independently stated count, total and balance. Every source occurrence remains a retained transaction, a proven duplicate link or a visible unresolved review row. Transfers and repayments retain both account entries outside spending; generic credits are not assumed income or refunds. All transactions exposes complete retained history by currency, including positive bank repayments and unresolved rows. Every account/currency section must meet its own source-evidence checks, including sections already imported. A reconciled section can be used even when another section of the same PDF is incomplete; document completeness remains unverified and its gaps stay in Review. Balance and cumulative-interest summaries never become invented withdrawals or dated interest postings. Search completion, report delivery and financial review have separate states. See `plugins/moneylens/skills/automation/references/ledger-contract.md` for schema and evidence boundaries.

Completeness is provider-neutral; mailbox access and routing must be verified through the connected email MCP provider. Provider-specific examples do not establish support for other connectors, and custom OAuth is not an access fallback. Password derivation uses an observed issuer recipe and verified attributes; missing birthdate inputs must be requested, never guessed. Building the plugin does not modify private reports.

### Source preference and issuer notation

Resolved-account statements take precedence over all notifications for the same account, currency and inclusive period. Covered notifications are excluded from report rows, totals and category review, with originals retained only for audit; incomplete statements still show their evidence gaps. The agent can supply `display_description` and `display_note` metadata for source-specific notation while original descriptors remain in source evidence. Scripts do not infer payment channels or financial meaning from institutional text. Category names come from agent/user decisions and retain their exact labels.

Scripts have no country, default currency/precision, payment-system catalog, bank layouts, password recipes, merchant lists, or category taxonomy. Currency and precision are explicit fields; payment-channel filters come from supplied labels. Account identifiers are opaque masked text. The agent owns source interpretation, new merchant categorization, collection/report dates, timezone, and MCP retrieval.
