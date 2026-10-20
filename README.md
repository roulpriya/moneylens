# MoneyLens

[![Validate](https://github.com/roulpriya/moneylens/actions/workflows/validate.yml/badge.svg)](https://github.com/roulpriya/moneylens/actions/workflows/validate.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

Agent skills that turn Gmail card statements, transaction alerts, and UPI notices into a local spending report. MoneyLens keeps a persistent SQLite ledger, reconciles alerts against statements, and updates the same HTML report on each sync.

## Install

Requires Node.js and npm for the [Skills CLI](https://github.com/vercel-labs/skills). Install **both** skills together:

```sh
npx skills add roulpriya/moneylens --skill moneylens-setup moneylens-automation
```

Choose your agent when prompted. To install globally for Codex without prompts:

```sh
npx skills add roulpriya/moneylens --skill moneylens-setup moneylens-automation -a codex -g -y
```

Share this repository link: **https://github.com/roulpriya/moneylens**. No GitHub account or repository access invitation is needed to download these public skills.

To inspect the available skills before installing:

```sh
npx skills add roulpriya/moneylens --list
```

## Requirements

The workflow targets **Codex on macOS**. The skill format is portable, but installing it into another agent does not supply its runtime capabilities.

- macOS with an accessible login Keychain and a desktop session for initial password prompts.
- Python 3.10 or later; the Python helpers use only the standard library.
- Apple's Swift compiler / Command Line Tools for the PDFKit and Keychain helper. Install with `xcode-select --install` if needed.
- A connected Gmail integration with profile, search, message, and attachment or raw-MIME access.
- A Codex host exposing the automation scheduling tool for daily updates. Installation alone does not create a schedule or connect Gmail.

Both installed skill folders must remain siblings because setup reads the automation skill's shared scripts and references. The Skills CLI's canonical skill directory preserves this layout.

## Start using MoneyLens

Ask your agent:

```text
Use $moneylens-setup to set up my spending report and daily updates.
```

Setup verifies the connected mailbox, searches the last three calendar months, asks you to confirm detected cards, and verifies statement passwords locally. It then backfills the ledger, creates the report, and configures one daily update at your confirmed local time.

After setup:

```text
Use $moneylens-automation to refresh my spending report.
```

You can also ask it to save a personal transaction note or a reusable category correction and refresh the existing report.

| Skill | Purpose |
| --- | --- |
| [moneylens-setup](skills/moneylens-setup/SKILL.md) | Initial setup, account confirmation, PDF password verification, and schedule creation or repair |
| [moneylens-automation](skills/moneylens-automation/SKILL.md) | Daily or manual sync, alert reconciliation, personal category rules, and report updates |

The report defaults to `~/Documents/MoneyLens/report.html`. Runtime state defaults to `~/Library/Application Support/MoneyLensCodex`, with separate data directories for different mailboxes.

## How data is handled

- PDF passwords stay in macOS Keychain. Passwords do not belong in chat, command arguments, environment variables, configuration, or Git.
- The local ledger stores structured transactions, masked account metadata, source references, and your personal rules. It uses file permissions rather than application-level encryption.
- Working PDFs and extraction files are temporary; the workflow removes its own copies after processing. Gmail and connector retention are separate.
- The HTML report contains private financial data. Keep generated reports and runtime data out of this public repository.
- Daily runs preserve the report layout and update its JSON data block. Ambiguous records remain available for review.

MoneyLens reads Gmail. It does not send mail, change mailbox labels, or initiate payments. It only covers evidence available in Gmail; it does not imply access to SMS or payment-app-only transactions. The optional parser covers observed HDFC/ICICI notices; other layouts require the agent to interpret actual source evidence or hold the item for review. Scanned PDFs without extractable text need separate handling.

## Development

```sh
git clone https://github.com/roulpriya/moneylens.git
cd moneylens
python3 -m unittest discover -s tests -v
```

The tests use synthetic records and temporary data directories, without accessing Gmail or the real Keychain. CI also compiles the native PDF helper and checks its help command on macOS.

```text
skills/
  moneylens-setup/
    SKILL.md
    agents/openai.yaml
  moneylens-automation/
    SKILL.md
    agents/openai.yaml
    scripts/
    references/
    assets/report-template.html
tests/
```

To check or update installed skills:

```sh
npx skills check
npx skills update
```

## Packaging references

This repository follows the folder-based Agent Skills approach used by [Vercel Agent Skills](https://github.com/vercel-labs/agent-skills) and [Anthropic Skills](https://github.com/anthropics/skills), with named `SKILL.md` entrypoints, supporting resources, and a repository-level installation guide. Installation uses the [Vercel Skills CLI](https://github.com/vercel-labs/skills). These projects are references, not affiliations.

## License

[MIT](LICENSE) — copyright 2026 Priyambada Roul.
