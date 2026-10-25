# Local account settings and agent-owned setup

The agent verifies connected email MCP access, selects mailboxes with the user, discovers sources, reads password instructions, maintains the private source inventory, and uses scheduling tools directly when authorized. Processing scripts do accounting and PDF work only. They do not verify live connections, inspect scheduler files, manage leases, or track scans/retrieval queues.

`<moneylens>` means `<python> <automation-skill>/scripts/moneylens.py`.
`<pdf-extract>` means `<python> <automation-skill>/scripts/pdf_extract.py`.
Resolve absolute paths and the installed Python 3.10+ executable for the current host. User data stays in the existing private data directory, outside skills and Git. The new-install default is the resolved project directory where the user invoked the skill, with `report.html`. Pass its absolute `--data-dir` explicitly on later calls. Do not abandon an existing ledger or silently create a replacement.

## Confirmed account settings

Read settings with `<moneylens> accounts --data-dir <directory>`. Save confirmed account/currency/source mappings through `<moneylens> accounts --data-dir <directory> --input <private-settings.json>`. Example values below are synthetic:

```json
{
  "mailboxes": [{"id":"stable-mailbox-id","address":"verified@example.invalid","verified_at":"2026-10-24T09:00:00Z"}],
  "timezone":"<user-confirmed-IANA-timezone>",
  "report_path":"<absolute-private-directory>/report.html",
  "credential_method":"private-file",
  "cards":[{"account_key":"opaque-card-key","issuer":"Example Bank","masked_identifier":"<source-masked-identifier>","account_label":"<confirmed-label>","credential_scope":"opaque-pdf-scope","password_status":"not_required","mailbox_ids":["stable-mailbox-id"]}],
  "bank_accounts":[]
}
```

Mailbox settings need only stable `id` and `address` fields. Optional `verified_at` records an agent-observed timestamp; processing does not require a profile check or establish live access. All access and routing must be verified by the agent through the connected provider's MCP tools. Stable mailbox/account keys cannot be reassigned or removed, and an account key cannot change account type. The agent supplies confirmed account keys; processing does not resolve bank aliases or identify accounts from descriptions. Account keys and labels are supplied explicitly; optional `masked_identifier` values are opaque text, not four-digit requirements. The agent resolves ambiguity from evidence, never the script. Accounts can list multiple confirmed mailbox IDs. Distinct accounts may share a verified credential scope for the same protected document.

Bank accounts use required `account_key` and `account_label`, optional `issuer` and `masked_identifier`, and `mailbox_ids`, and optional identity evidence. Statement-enabled bank accounts add `statement_enabled:true`, `credential_scope`, `password_status`, and `verified_at` when verified. Full PANs and raw password derivation inputs never belong in settings.

Timezone is optional until confirmed; scripts do not choose it. Currency and fractional precision are explicit transaction/statement inputs, independent of account-number syntax or geography.

Credential readiness is `verified` only after actual unlock and successful unattended reuse, `not_required` for an observed unprotected PDF or inline table, otherwise `unverified`. An explicit alerts-only choice may coexist with unverified credentials. Incomplete PDF setup does not block accessible accounting sources. Only the current settings schema is accepted; scheduling details belong in the agent's inventory.

## PDF capabilities and private credentials

Install `scripts/requirements.txt` in the Python environment used for processing during setup. The accounting interface uses the standard library; the standalone PDF script uses pypdf/cryptography. Resolve capabilities and writable private storage before extraction. Scripts do not need mailbox or scheduler evidence to process supplied local inputs.

Read the protected statement's actual password instructions from its enclosing email before trying anything. Use verified inputs from authorized evidence and ask only for missing attributes required by that exact recipe. The agent derives candidates from those exact instructions and passes only the candidates through `<pdf-extract> --passwords-from-stdin` as `{"passwords":["<candidate>"]}`; at most three, with no guessing or birthday enumeration. See [email and extraction](email-and-extraction.md). The PDF script does not process identity attributes or contain a recipe catalog. Store only a candidate that unlocks the real document, then reopen with `--no-prompt` to prove reuse.

Verified derived passwords live under `<directory>/credentials` with POSIX owner-only modes or protected current-user Windows ACLs. The private-file backend is plaintext at rest; it is not application encryption. Links, hardlinks, and unverifiable ownership are rejected. Normal setup authorizes the described storage; do not ask for a second approval. Never put identity inputs/passwords in argv, environment, input files, logs, source inventories, scheduler prompts, or memory.

`<pdf-extract> --data-dir <directory> --credential-status --account <scope>` reports presence without the secret. Presence alone does not verify reuse. Use the configured scope directly; do not copy credentials or inspect another credential backend.

## Source inventory and resuming

The agent maintains nonsecret source/instruction provenance in a private source inventory, such as `<directory>/source-inventory.json`. Keep explicitly selected mailbox IDs and the authorized recurring mailbox scope, confirmed account mappings, observed message/attachment IDs, statement periods, recipe/input names, verification status, unresolved access/extraction reasons, and fully completed collection dates. Store pointers and outcomes, not raw bodies, extraction dumps, identity values, or passwords.

Resume using that inventory and existing settings. Reverify live MCP access and reuse the explicitly authorized mailbox scope for this pull or recurring refreshes; ask only if that scope is missing or ambiguous. Reuse confirmed account and credential choices. The agent controls date windows, pagination, incomplete-search handling, and sources to revisit. Accounting source IDs make repeated supplied inputs idempotent. A successful import/report is not evidence that retrieval completed.

Hand off the selected inventory to the sibling automation skill for the same six-step workflow. The agent checks `merchants` for cached categories, decides cache misses, and supplies classifications to `add` or `import-statement`, then generates `report`. No begin/finish scan commands or retry queues are involved. Unresolved financial rows remain visible accounting review outcomes; inaccessible documents remain agent-owned retrieval gaps. Keep search completion, report delivery, credential readiness, and statement completeness separate.

## Scheduling through tools

Only the agent creates or repairs schedules, through the host's scheduling tools after the user has chosen mailboxes/inventory/cadence. Inspect the existing schedule ID or matching jobs before creating anything; preserve paused jobs and investigate unknown outcomes before retrying. Keep the existing authorization and avoid duplicate jobs. Default to one thread heartbeat unless standalone work is requested.

Use a short prompt referencing `$automation`, its installed absolute SKILL.md path, the private data directory, and the private inventory that records the authorized mailbox scope. Keep financial details and credentials out of it. Stay quiet while unchanged and notify only on meaningful changes, completion, failure, or required user action. A saved ID does not prove an active job; an active job does not prove a successful refresh. Verify using scheduling tools, never by reading local scheduler implementation files from processing code. Do not change existing live jobs while merely developing skills/scripts.

## Public-release schemas

Generate the report with `<moneylens> report --data-dir <directory> --output <saved-report.html>`. The release accepts database schema 1 and report template/data schema 4 only. Current report UI is preserved while refreshing its bounded data. Unsupported templates are rejected without rewriting them; generate a new report instead. No Notes column.

Initialize a clean private data directory for this public release. Processing does not search old data locations, open older databases, translate account fields, read old queues, or copy credentials. Unsupported database versions/tables and settings fields fail explicitly. Do not delete or overwrite a user's unsupported files. Source coverage follows the [ledger contract](ledger-contract.md) for every statement, including imported rows. Scripts neither declare collection complete nor advance agent workflow dates.
