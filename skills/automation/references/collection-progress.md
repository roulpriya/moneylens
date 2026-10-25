# Bounded collection and recovery

Collection stays with the agent and connected email MCP tools. The accounting
CLI never pulls mail or advances collection cursors. Apply this protocol in
setup, backfill, manual refreshes, and scheduled refreshes.

Read the private source inventory before content retrieval. Reuse the authorized
mailbox scope and confirmed choices. Read `accounts`, `preferences` and `list` to
recover saved work. Do not repeat a credential question or derive a candidate
again when the exact scoped credential already works.

## Checkpoint after each durable result

Maintain `<data-dir>/source-inventory.json` outside installed skills and Git.
Keep a per-mailbox, per-search-window checkpoint with these nonsecret fields:

```json
{
  "version": 1,
  "mailboxes": {
    "opaque-mailbox-key": {
      "last_fully_completed_date": null,
      "searches": {
        "bank-statements": {
          "from": "2026-09-01", "through": "2026-10-25",
          "page_token": null, "next_page_token": null,
          "search_exhausted": false,
          "pending_message_ids": ["observed-message-id"],
          "sources": []
        }
      }
    }
  }
}
```

Create separate searches for bank statements, card statements, and alerts as
needed. Save actual provider pagination tokens and discovered message IDs after
each search page returns, before reading its messages. Keep the current page
token until all page messages have durable dispositions; then promote the
observed next token. A null token alone does not establish exhaustion. Never
invent a token or rewrite another mailbox's state.

For each source, save observed message/attachment identifiers, account/section
identifiers, accounting record IDs, disposition (`imported`, `provisional`,
`duplicate_linked`, `summary_only`, `nonfinancial`, or `review`), and precise
nonsecret retrieval/validation gaps. A message with multiple attachments,
sections, or movements is finished only after all have dispositions. Summary
sections need document limitations, not transaction placeholders. Save each
result immediately after its accounting commit; remove a pending message only
after every part is accounted for.

Use an owner-only directory/file and atomic replace for every checkpoint: write
a sibling temporary file, flush and fsync it, then replace the inventory. On
Windows use the private-files helpers for the current user ACL. Reject symlinks
and preserve the previous valid inventory on failure. Use a single checkpoint
writer; parallel message tasks must never overwrite each other's snapshots.
Merge and retain confirmed scope, instruction provenance, account choices and
prior completed dates.

Store identifiers, nonsecret recipe/input *names*, and outcomes only. Never retain
raw email/HTML/MIME, image/OCR dumps, extraction text, identity values, candidates,
passwords, authentication tokens, or full tool responses. Pagination tokens are
opaque provider search cursors, never login credentials.

## Bound reads and retries

Allow at most **three message reads in flight across the entire collection**,
including attachment/raw-MIME reads. Work one search page at a time. Commit and
checkpoint each result as it finishes, without waiting for a large batch. Limit
each source to two retrieval attempts per run, using the documented attachment
route then its supported raw-MIME fallback where useful. On throttling, reduce
concurrency to one and respect the provider's retry delay; checkpoint and end the
run as incomplete if it cannot proceed within the run. Never repeat successful
reads/imports just because a sibling failed.

After interruption, load the checkpoint, verify live MCP access, and resume the
pending page/messages and unresolved source IDs. Skip completed source sections.
For an unknown tool outcome, inspect durable ledger/source outcomes before
retrying. If a commit succeeded before checkpointing failed, repair that source's
checkpoint from the ledger instead of fetching it again. Repeated accounting
inputs remain idempotent. Regenerate failed reports from saved accounting data.

Advance `last_fully_completed_date` only when every required search in that
mailbox/window is exhausted and all discovered sources have durable outcomes.
An interrupted search or unresolved retrieval leaves it unchanged. Keep failed
source IDs and precise gaps for the next run. A saved financial review is a
durable outcome, not evidence of validated accounting or statement completeness.
Report collection completion, report delivery, credential readiness, and
document/section completeness independently.
