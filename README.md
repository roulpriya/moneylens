# MoneyLens

[![Validate](https://github.com/roulpriya/moneylens/actions/workflows/validate.yml/badge.svg)](https://github.com/roulpriya/moneylens/actions/workflows/validate.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

A ChatGPT and Codex plugin that turns Gmail card statements, transaction alerts, and UPI notices into a local spending report. MoneyLens keeps a persistent SQLite ledger, reconciles alerts against statements, and updates the same HTML report on each sync.

## Install the plugin

MoneyLens includes one setup skill and one automation skill in a portable `plugin.json` package. It runs in a **local macOS ChatGPT Work or Codex session** with Gmail and scheduling tools; packaging does not give a cloud-only session access to your Mac's Keychain or files.

For local testing, clone the repository and register its marketplace:

```sh
git clone https://github.com/roulpriya/moneylens.git
cd moneylens
codex plugin marketplace add .
```

Restart the ChatGPT desktop app, open the Plugins Directory, choose the **MoneyLens** source, and install MoneyLens. The repository's `.agents/plugins/marketplace.json` points to the root plugin. A clean distributable folder is also produced at `dist/moneylens` by the Bun build.

The two skills can still be installed together using the Skills CLI:

```sh
npx skills add roulpriya/moneylens --skill moneylens-setup moneylens-automation
```

Plugin installation does not connect Gmail or create a daily schedule. Run setup after installation.

## Requirements

The workflow targets **local ChatGPT Work and Codex on macOS**. The skill format is portable, but installing it into another agent does not supply its runtime capabilities.

- macOS with an accessible login Keychain and a desktop session for initial password prompts.
- Python 3.10 or later. Ledger and configuration helpers use the standard library. PDF extraction uses pypdf/cryptography; macOS Keychain and the masked prompt use PyObjC.
- Setup creates a private Python runtime under `~/Documents/MoneyLens/runtime` and installs the pinned `skills/moneylens-automation/scripts/requirements.txt`. No Swift compiler is required.
- Bun 1.4.3 is a development-only build dependency. Installed daily workflows use the committed HTML asset and Python runtime.
- A connected Gmail integration with profile, search, message, and attachment or raw-MIME access.
- A Codex host exposing the automation scheduling tool for daily updates. Installation alone does not create a schedule or connect Gmail.

Both installed skill folders must remain siblings because setup reads the automation skill's shared scripts and references. The Skills CLI's canonical skill directory preserves this layout.

## Start using MoneyLens

Ask your agent:

```text
Use $moneylens-setup to set up my spending report and daily updates.
```

Setup verifies the connected mailbox, discovers accounts from the last 30 days, asks you to confirm detected cards and bank accounts and identify any missed accounts, and verifies statement passwords locally. It then backfills the previous calendar month plus the current month, creates the report, and configures one daily update at your confirmed local time.

After setup:

```text
Use $moneylens-automation to refresh my spending report.
```

You can also ask it to save a personal transaction note or a reusable category correction and refresh the existing report.

| Skill | Purpose |
| --- | --- |
| [moneylens-setup](skills/moneylens-setup/SKILL.md) | Initial setup, account confirmation, PDF password verification, and schedule creation or repair |
| [moneylens-automation](skills/moneylens-automation/SKILL.md) | Daily or manual sync, alert reconciliation, personal category rules, and report updates |

The report defaults to `~/Documents/MoneyLens/report.html`. The ledger, nonsecret settings, runtime, and backups also live in `~/Documents/MoneyLens`, with separate data directories for different mailboxes. The default display range is the previous calendar month through today; all earlier history remains in the ledger. Account discovery uses a separate 30-day window.

## Upgrading legacy storage

Before running with the new Documents default, migrate an older installation:

```sh
python3 skills/moneylens-automation/scripts/migrate_storage.py
```

The migration refuses an existing destination ledger or active sync, verifies every SQLite table, and archives the old directory under `~/Documents/MoneyLens/backups`. It preserves personal notes, rules, source references, and transaction history. Update the existing automation to use the new data directory and Python helper, then verify Keychain access through the new runtime. Saved password service names and account scopes remain compatible.

## How data is handled

- PDF passwords stay in macOS Keychain. Passwords do not belong in chat, command arguments, environment variables, configuration, or Git.
- The local ledger stores structured transactions, masked account metadata, source references, and your personal rules. It uses file permissions rather than application-level encryption.
- Working PDFs and extraction files are temporary; the workflow removes its own copies after processing. Gmail and connector retention are separate.
- The HTML report contains private financial data. Keep generated reports and runtime data out of this public repository.
- Daily runs preserve the report layout and update its JSON data block. Ambiguous records remain available for review.

MoneyLens reads Gmail. It does not send mail, change mailbox labels, or initiate payments. It only covers evidence available in Gmail; it does not imply access to SMS or payment-app-only transactions. The optional parser covers observed HDFC/ICICI notices; other layouts require the agent to interpret actual source evidence or hold the item for review. Scanned PDFs without extractable text need separate handling.

## Development

```sh
npm ci
npm run build
python3 -m venv .venv
.venv/bin/python -m pip install -r skills/moneylens-automation/scripts/requirements.txt
.venv/bin/python -m unittest discover -s tests -v
```

The build uses Bun to bundle `src/report.js` and `src/report.css` and inline them into `src/report.html`. It commits one offline artifact at `skills/moneylens-automation/assets/report-template.html`, preserving the bounded JSON data markers used by daily updates. The distributable `dist/moneylens` includes the manifest, both skills, README, and license; it excludes runtime data and build dependencies.

Tests use synthetic records, temporary directories, and fake credential stores. PDF tests cover encrypted and unprotected documents without Gmail or the real Keychain. CI rebuilds the HTML and checks that the committed asset is current.

The portable plugin format and local marketplace follow the [official OpenAI packaging documentation](https://developers.openai.com/plugins/build/plugins).

## License

[MIT](LICENSE) — copyright 2026 Priyambada Roul.
