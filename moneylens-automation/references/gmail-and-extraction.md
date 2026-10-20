# Gmail discovery and secure extraction

Use connected Gmail tools, not the unfinished Electron OAuth adapter. Discover tool names at runtime. Do not provision OAuth or extract browser credentials. Scheduling belongs to the setup skill's scheduling handoff.

## Search and attachments

Subtract three calendar months in the user's timezone, clamping the day if needed. On 20 October 2026 the start is 20 July 2026. Use a receipt-date buffer when needed and report the actual analysis dates. Initial heuristic:

```text
after:YYYY/MM/DD before:YYYY/MM/DD has:attachment {"credit card statement" "card statement" "credit card e-statement"}
```

Refine using actual sender/subject terms, including e-statement/account statement where relevant. Verify content; exclude bank-account statements unless scope expands. Do not follow email sign-in, payment, or download links automatically. Report link-only statements as unavailable through attachment tools.

For daily transaction alerts, search separately without `has:attachment`, using discovered issuer senders plus terms such as transaction, spent, debited, credited, purchase, and successful. Inspect actual content: a transaction alert is evidence of a movement, while an OTP, declined attempt, balance reminder, or authorization hold is not a completed spending row. Search both sources and read every result page. Failed/reversed attempts are not invented refunds. Capture the exact bank transaction reference when available and the card's confirmed masked identity. A message containing multiple distinct successful movements may yield multiple one-row alert payloads, each with a unique source row reference; do not mark that source processed until all its movements have dispositions.

- Consume search pages and deduplicate message IDs. Disclose partial coverage/tool failures.
- Read the parent message. Use its exact full attachment ID; when absent/truncated, use the exact filename if the connector supports it. Never invent IDs.
- For Gmail attachment-read, require `read_attachment_supported: true`. Unsupported attachments are reported, not repeatedly retried.
- `file_uri` may not be a local file. Use only a supported retrieval mechanism; never invent an endpoint or map a URI to a guessed path. Read `extraction_file_uri` when inline extracted content is truncated. If complete content/bytes cannot be obtained, report the gap.
- Obtain original bytes for local unlocking only through an authorized connector-returned route. Hash original PDF bytes with SHA-256; never hash extracted text as a substitute. If bytes are unavailable, omit `sha256` and use source/semantic deduplication.

## Native helper (macOS)

Compile into a private cache in the ledger data directory (create cache with mode 0700):

```sh
swiftc -module-cache-path <data-dir>/cache/modules <skill-dir>/scripts/pdf_extract.swift -o <data-dir>/cache/pdf-extract
<data-dir>/cache/pdf-extract --input <temporary.pdf> --output <temporary-extraction.json> --account <opaque-scope>
```

Arguments contain no passwords. The helper retrieves service `com.moneylens.codex.pdf-password` with the supplied scope. Missing or failed saved passwords cause one native masked prompt offering to save a replacement. Save occurs only after successful unlock. A failed new password or cancellation stops that document. Keychain errors stop it without plaintext fallback. Do not invoke this on private documents merely to test installation.

The prompting behavior above is **setup only**. Daily extraction must add `--no-prompt`; this disables both native password dialogs and Keychain authentication UI. A missing, inaccessible, or incorrect saved credential then fails that source promptly so the run can queue it and continue. `--previous-account` migration is forbidden with `--no-prompt`. `--keychain-status --account <scope>` reports credential existence without retrieving its value or displaying authentication UI. Confirm readiness by an actual setup-time unlock and a subsequent noninteractive extraction; existence alone is insufficient.

Use a SHA-256 scope of mailbox identifier + normalized issuer + observed last four card digits, never a full card number. If card identity is unknown, use a document-specific scope derived from observed mailbox/message/attachment. Never try all saved credentials. After extraction verifies the card, rerun the same temporary PDF with `--account <verified-card-scope> --previous-account <document-scope>` to copy a successfully used credential to the verified scope. This does not print passwords or delete old entries.

Output JSON has `pages: [{page: 1, text: "..."}], page_count, encrypted`. Empty text can mean a scanned page, not an empty statement. The helper limits input to 20 MiB and 100 pages. Apply an execution timeout while allowing time for visible user prompts. It is not a hardened document sandbox.

Delete temporary PDFs, extraction JSON, and staging input JSON in `finally`. Delete only your own copies. Do not promise deletion from Gmail, connector caches, swap, or chat history. The ledger retains structured records, not raw statement text or passwords.
