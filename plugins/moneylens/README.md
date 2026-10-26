# MoneyLens

MoneyLens turns your bank and card emails into a clear picture of your money. It reads transaction alerts and statements through an email connector you choose, keeps a SQLite ledger on your own machine, matches alerts against statements, and updates one offline HTML spending report covering spending, money in, cashflow and transfers.

MoneyLens is a reporting tool, not financial, investment, tax or legal advice. Coverage depends on the emails and statements available, so check items in Review and the original sources before relying on a total.

## Skills

| Skill | Purpose |
| --- | --- |
| [setup](skills/setup/SKILL.md) | First-time setup: confirm mailboxes and accounts, verify access to password-protected statement PDFs, build the first report, then offer recurring refreshes |
| [automation](skills/automation/SKILL.md) | Manual or scheduled refreshes, alert and statement reconciliation, merchant categories, and transaction corrections |

Start with:

```text
Set up MoneyLens and my daily spending report.
```

Later, ask Claude to update your MoneyLens report or to correct a transaction's category.

## Requirements

- A local session that can run commands and write files. Cloud-only sessions can't reach your local ledger.
- Python 3.10 or later.
- A connected email MCP provider with search, message and attachment access.
- A scheduling tool in your host if you want automatic refreshes. Installing the plugin doesn't connect email or create a schedule.

## What the plugin runs, reads, stores and sends

- **Email:** reads only the mailboxes you authorize, through your own email connector. It never sends mail, changes labels or initiates payments.
- **Local scripts:** runs the bundled Python scripts in `skills/automation/scripts` and `skills/setup/scripts`. They make no network requests.
- **Package install:** setup installs the pinned packages in `skills/automation/scripts/requirements.txt` (`pypdf`, `cryptography`, `tzdata`) from PyPI into the Python environment it uses.
- **Web search:** during setup or password repair, Claude searches the web for the card or bank issuer's official guidance on its statement PDF password format, and reads that public page to confirm the format described in the email. Searches use only public issuer and product names, never your name, birthdate, account numbers, password candidates or email content. The results only corroborate the instructions; only a successful local unlock confirms them.
- **Local form:** if a statement password can't be derived from details you already gave, setup can open a one-time form served only on `127.0.0.1`. It never returns submitted values in responses or logs.
- **Local storage:** the ledger, report, settings and verified statement PDF passwords stay in the data directory you choose. They're protected by owner-only file permissions (or Windows ACLs) and aren't encrypted at rest. Working copies of PDFs are deleted after processing.
- **Sent elsewhere:** MoneyLens has no server and sends no data to its developer. Apart from the web searches and the PyPI install above, your AI host and email connector are the only services involved: they process the email content used to build and update the report, under their own terms.

The report contains private financial data. Keep it, and the data directory, out of version control.

## Support

- Website: https://roulpriya.github.io/moneylens/
- Issues: https://github.com/roulpriya/moneylens/issues
- Privacy policy: https://roulpriya.github.io/moneylens/policy.html
- Terms: https://roulpriya.github.io/moneylens/terms.html

## License

[MIT](LICENSE). Copyright 2026 Priyambada Roul.
