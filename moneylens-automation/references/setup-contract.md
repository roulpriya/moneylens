# Setup and scheduling contract

The two skills ship together. `moneylens-setup` owns interaction, card confirmation, password provisioning, and schedule creation/repair. `moneylens-automation` owns daily data ingestion and report updates. Scripts and committed UI live only in the automation skill. All runtime state is outside the skill/repository, defaulting to `~/Library/Application Support/MoneyLensCodex`.

## Native credential verification

Compile the native helper once to `<data-dir>/cache/pdf-extract`, with private cache permissions and a local compiler module cache. Reuse that exact executable for setup and daily runs so macOS Keychain access control does not see a different executable on every run. Recompiling/upgrading can require an interactive setup pass to reauthorize Keychain access.

During setup, check the cached helper's `--help` for the required derivation options. If an older helper lacks them, rebuild once from the current source and verify Keychain access interactively. Daily runs keep using the already verified cached executable; they do not rebuild it or trigger credential dialogs.

```sh
pdf-extract --keychain-status --account <opaque-card-scope>
pdf-extract --input <temporary-statement.pdf> --output <temporary-extraction.json> --account <opaque-card-scope>
```

The first command reports metadata only and does not show system prompts; the second may show the local masked prompt. Save a password only after a successful PDF unlock. Verify a stored password by re-extracting with `--no-prompt` into a new temporary output file before declaring the card ready for unattended use. macOS may require access approval during setup. On a locked/login Keychain or unavailable desktop, report the concrete limitation; never promise jobs can unlock a locked Mac's credential store.

## Nonsecret configuration

After actual Gmail verification, user card-count/list confirmation, password checks (or an explicit alerts-only choice for a card without statements), and confirmation of the local daily time, write a private temporary JSON file:

```json
{
  "mailbox": "verified-connected-account-identifier",
  "gmail_verified_at": "2026-10-20T09:00:00+05:30",
  "initial_start": "2026-07-20",
  "timezone": "Asia/Kolkata",
  "daily_time": "09:00",
  "confirmed_card_count": 1,
  "auto_save_validated": true,
  "report_path": "/Users/example/Documents/MoneyLens/report.html",
  "upi_accounts": [],
  "cards": [{
    "account_key": "opaque-stable-card-key",
    "issuer": "Example Bank",
    "last4": "1234",
    "keychain_scope": "opaque-sha256-scope",
    "password_status": "verified",
    "verified_at": "2026-10-20T09:00:00+05:30"
  }]
}
```

These values are synthetic examples, never evidence of completed setup. `password_status` is `verified`, `not_required` (an observed unprotected statement), or `unverified`. A confirmed new card with no statement can use `alerts_only: true` while retaining `password_status: "unverified"`; it does not block the other accounts. Ask this choice through request-input instead of ending setup or requiring a nonexistent PDF. Presence of a Keychain entry alone is insufficient. Configure refuses a mismatched user-confirmed count and never accepts password fields. Configuration contains only masked card details and nonsecret metadata; it is stored in SQLite. `ready` is computed, not an input override.

```sh
python3 <automation-skill>/scripts/runtime_state.py --data-dir <data-dir> configure --input <private-config.json>
python3 <automation-skill>/scripts/runtime_state.py --data-dir <data-dir> status
```

Remove the temporary config afterward. Initial discovery may use temporary private inventories, but a final configuration is saved only after the user's confirmation. Known-card alias matching must retain the same account key. Keep a separate data directory for each mailbox. Do not silently reset an existing ledger.

## Scheduling handoff

Once ready, execute the automation skill for initial backfill in the current chat. Then discover and use Codex's `automation_update` tool, following its current schema. Use a daily **thread heartbeat** at the user's confirmed local time, unless standalone jobs were explicitly requested. The recurrence must reflect that timezone; do not expose raw recurrence strings or write cron/automation TOML files. A skill defines the workflow; the scheduling tool provides recurrence.

If backfill reveals another required password, return to interactive credential repair before enabling the daily schedule. Report missing/ambiguous card identities rather than claiming the detected card count is complete. For an incompatible existing report, preserve it and perform an explicit setup/development repair from the committed template; daily automation never replaces its UI.

Use the saved automation ID to update an existing schedule. If no ID is recorded, inspect configured automation records for a matching MoneyLens prompt/data directory before creating one. Never create duplicates. An example readable prompt:

> Use $moneylens-automation at <absolute automation-skill/SKILL.md> with <absolute data-dir>. Fetch new Gmail card alerts and statements, use existing Keychain passwords without prompts, save validated records, reconcile alerts, and update only the data in the report at the configured path. Continue other cards when one source fails and surface any setup or review issues. Stay quiet when there is no meaningful change; notify only on meaningful new data, failure, or required user action.

Do not embed passwords, card numbers, message bodies, or raw statement data in the prompt. After success:

```sh
python3 <automation-skill>/scripts/runtime_state.py --data-dir <data-dir> set-automation --id <returned-id>
```

The schedule's saved ID is metadata, not proof of readiness. If the tool fails, report the unscheduled state. Setup reruns repair the existing job. Do not start a real schedule when merely authoring or reviewing these skills.

## Daily checkpoints and retries

`begin-run` acquires a two-hour lease and returns the scan bounds, confirmed config, prior cursor, and durable retry list. Finish with its exact run ID. Queue attachment/auth/password/source errors before advancing a fully paginated scan; queued sources are retried even when their receipt dates age out of the normal window. A partial Gmail search must not advance the cursor. The cursor is the start of the completed scan, with a three-day overlap on the next run. Duplicate source IDs make retries safe.

```sh
python3 <automation-skill>/scripts/runtime_state.py begin-run
python3 <automation-skill>/scripts/runtime_state.py retry-add --message <observed-id> --attachment <observed-attachment-id> --reason 'Saved PDF password requires setup repair'
python3 <automation-skill>/scripts/runtime_state.py retry-remove --key <returned-key>
python3 <automation-skill>/scripts/runtime_state.py finish-run --run-id <run-id> --search-complete
```

Use `--data-dir` before each command for alternate locations. The ledger/report stay intact if a run fails. The report's data includes last scan status and pending sources. A crash leaves a lease that later expires; no second writer may acquire it while active.

## Documents report location

Default to `~/Documents/MoneyLens/report.html`. The ledger and credentials retain their existing private storage locations. `runtime_state.py set-report --path <absolute-Documents-path>` updates only the configured report location and preserves cards, credential status, cursor, and schedule ID. When moving an existing report, create and verify the new copy before changing the configuration and existing automation prompt; preserve the old file as a fallback. Explicit template migrations are setup/development actions. Normal daily runs only replace the new report's JSON data block.

## Complete the interview without ending early

Use request-input for card confirmation, an unknown required attribute, alert-only decisions, or the daily time. While an answer is pending, continue independent work and keep the turn open using available wait tools; do not require “continue,” treat silence as consent, or put a question in a final answer. Reuse facts already provided. Do not ask the user to upload a PDF when Gmail raw-MIME retrieval can obtain it or when the card simply has no statement yet.
