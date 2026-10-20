# Gmail discovery and secure extraction

Use connected Gmail tools, not the unfinished Electron OAuth adapter. Discover tool names at runtime. Do not provision OAuth or extract browser credentials. Scheduling belongs to the setup skill's scheduling handoff.

## Search and attachments

Use `runtime_state.py windows --timezone <user-timezone>`. During setup, discover accounts only within its rolling 30-day discovery bounds, then explicitly ask which additional accounts may be missing. After confirming the inventory, backfill those accounts from the first day of the previous calendar month through today (for example, 1 September–20 October 2026). These are separate search windows. Daily runs use checkpoint overlap and the retry queue. Use a receipt-date buffer when needed and report the actual analysis dates. Initial heuristic:

```text
after:YYYY/MM/DD before:YYYY/MM/DD has:attachment {"credit card statement" "card statement" "credit card e-statement"}
```

Refine using actual sender/subject terms, including e-statement/account statement where relevant. Verify content; keep bank-account UPI notices in scope, while unrelated bank statement rows require their own scope. Do not follow email sign-in, payment, or download links automatically. Report link-only statements as unavailable through attachment tools.

For daily transaction alerts, search separately without `has:attachment`, using discovered issuer senders plus terms such as transaction, spent, debited, credited, purchase, and successful. Inspect actual content: a transaction alert is evidence of a movement, while an OTP, declined attempt, balance reminder, or authorization hold is not a completed spending row. Search both sources and read every result page. Failed/reversed attempts are not invented refunds. Capture the exact bank transaction reference when available and the card's confirmed masked identity. A message containing multiple distinct successful movements may yield multiple one-row alert payloads, each with a unique source row reference; do not mark that source processed until all its movements have dispositions.

- Consume search pages and deduplicate message IDs. Disclose partial coverage/tool failures.
- Read the parent message. Use its exact full attachment ID; when absent/truncated, use the exact filename if the connector supports it. Never invent IDs.
- For Gmail attachment-read, require `read_attachment_supported: true`. Unsupported attachments are reported, not repeatedly retried.
- `file_uri` may not be a local file. Use only a supported retrieval mechanism; never invent an endpoint or map a URI to a guessed path. Read `extraction_file_uri` when inline extracted content is truncated. If attachment extraction fails, call the supported parent-message reader with `format: "raw"`. Decode its returned RFC 2822 MIME with Python's `email` parser and extract the observed PDF part. This is an authorized original-byte route, not a guessed download endpoint. Only report an attachment gap after the available raw-MIME route also fails.
- Obtain original bytes for local unlocking only through an authorized connector-returned route. Hash original PDF bytes with SHA-256; never hash extracted text as a substitute. If bytes are unavailable, omit `sha256` and use source/semantic deduplication.

## Python PDF and Keychain helper (macOS)

Install `scripts/requirements.txt` once into the private `<data-dir>/runtime` virtual environment described in the setup contract. Invoke:

```sh
<data-dir>/runtime/bin/python <skill-dir>/scripts/pdf_extract.py --input <temporary.pdf> --output <new-extraction.json> --account <opaque-scope>
```

The helper uses pypdf for decryption/text extraction and PyObjC's Security APIs for macOS Keychain. Credentials keep service `com.moneylens.codex.pdf-password` and the saved opaque scope. Nothing needs compiling. Only passwords belong in Keychain; nonsecret configuration stays in SQLite. The helper never prints retrieved, entered, or derived passwords. It saves only after the PDF unlocks successfully. The masked prompt is setup-only; daily extraction must add `--no-prompt`, which disables both the local password dialog and Keychain authentication UI. Missing, inaccessible, or incorrect credentials are queued for setup repair. Daily runs never install packages.

`--keychain-status --account <scope>` reports existence without reading the password value. Verify readiness with a real unlock followed by successful `--no-prompt` extraction. `--probe --input <PDF>` inspects encryption without Keychain access; an encrypted/locked PDF may report zero pages until unlocked. Unprotected PDFs never read Keychain. All output JSON files are new, private files; existing files are never overwritten.

Use the existing SHA-256 mailbox/issuer/card-ending scope. Never try every saved password. A setup-only `--previous-account <document-scope>` can copy a credential to a confirmed card scope after that credential actually unlocks the same PDF. It is forbidden with `--no-prompt`.

The extraction schema remains `pages: [{page: 1, text: "..."}], page_count, encrypted`, with a 20 MiB / 100-page limit. Empty text may mean a scanned page. Apply a process timeout. Remove your temporary PDFs, extraction JSON, and staging input files in `finally`; do not retain raw text or passwords in the ledger.

### Infer a documented password locally

Read the issuer's actual password recipe and use already verified attributes before asking for missing information. Never use an issuer's example identity or enumerate birthdays. Pass a small stdin JSON object with `attributes` (`full_name`, `card_last4`, and only when known `birth_ddmm` or ISO `birth_date`) and one to three evidenced `recipes`. With `--derive-from-stdin`, the Python process constructs and verifies candidates internally, then saves a successful candidate to Keychain. Supported recipes are `name4_upper_card_last4`, `name4_lower_birth_ddmm`, and `name4_upper_birth_ddmm`. Passwords never go in argv, environment, chat, files, or logs. `--verify-derived-only` verifies synthetic fixtures without Keychain access. Missing attributes require a focused request-input question or the local masked prompt.

## UPI sources

Search Gmail separately for successful bank-account debit **and** credit notices, including `UPI`, `debited`, `credited`, `received`, `paid`, and bank-provided UTR/reference terms. Include archived messages and paginate completely. Infer the user-owned bank account from the bank's explicit “your account ending …” evidence, not from a merchant VPA or the last digits of a card. Retain only masked account metadata in `upi_accounts`. Bank-backed UPI and card-backed UPI are separate accounts; preserve shared transaction references to deduplicate notifications. Generic UPI receipts are not automatically refunds, salary, or self-transfers. Mark own-account transfers only from supporting ownership evidence. This skill reads Gmail; it does not imply access to SMS or payment-app-only activity.

For covered HDFC/ICICI notification layouts, normalize each Gmail result to `{id, from, subject, date, body, authenticated}` and feed a private JSON list to `scripts/gmail_transactions.py --input <file> --include-upi`. Set `authenticated` from actual Gmail authentication headers for the sender, not from the visible From name. The helper parses successful movements and preserves source provenance. Unknown layouts must still be interpreted from source or held for review; they are not silently counted or dropped. Remove the private normalized mail input and outcomes file in `finally` after importing records and saving dispositions.
