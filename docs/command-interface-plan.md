# MoneyLens public-release interface

The agent retrieves email/attachments through MCP, interprets sources, keeps its
source inventory, and handles schedules through tools. Local scripts perform
accounting and PDF work only. The two entry scripts are the only command parsers;
private modules expose accounting functions and reporting runs directly.

Prefer deterministic rules and saved mappings to LLM reasoning. Scripts perform
validation, arithmetic, source matching, statement precedence, reporting, and PDF
extraction without model calls. LLM judgment is a fallback for unfamiliar source
semantics and new uncached merchants. Statement rows may omit category when an
exact cached merchant mapping exists; explicit labels retain priority.

## Interface

- `scripts/moneylens.py`: `add`, `list`, `update`, `remove`, `import-statement`,
  `report`, `accounts`, and `merchants`.
- `scripts/pdf_extract.py`: independent PDF extraction and exact-scope credential reuse.
- PDF credentials: literal document-supported candidates via transient stdin; no issuer recipes or identity-format assumptions.
- Transactions: description, decimal amount, date, category, explicit currency/precision and movement kind, account, and
  JSON metadata. Source interpretation is supplied by the agent. Manual records may
  be edited/removed; source-backed financial evidence remains immutable.

## Release boundary

- Database schema 1 initializes all current tables atomically. Other database versions
  or table sets are rejected without modification. There is no older-data discovery,
  database conversion, credential copying, template upgrade, or alternate field-name
  support.
- Settings use `mailboxes`, `bank_accounts`, and `credential_scope`. Collection and
  scheduling fields are outside the accounting schema.
- Every account/currency section uses the same coverage/ownership validation, whether draft or imported. Section eligibility is independent of sibling gaps; whole-document completeness and its review reasons remain visible.
  IDs include source/account/currency from the start and do not depend on import order.
- Reports use template/data schema 4; unsupported HTML is rejected without rewriting.
  Appearance preferences use a new release-specific browser-storage key.
- Category labels are supplied by the agent and cached by exact merchant key. Cache
  misses require an agent decision; scripts do not classify merchants using built-in
  lists, keyword rules, aliases, or conditional rules. Explicit row overrides are
  separate from reusable cache decisions. `Other` stays uncached for review.

- No geography, currency, payment-method, merchant, category-taxonomy, account-suffix,
  or timezone assumptions. Report dates are explicit; missing channels remain unknown.
  Currency precision is supplied (0–18); filters derive from observed data.

The release package uses a file allowlist. Old category-edit storage, internal
command parsers, workflow scan status, and runtime queue code are absent.

## Verification

Tests cover current money-management operations, rejected formats/flags, untouched
unsupported database/report files, deterministic account/currency source identity,
source coverage and reconciliation, concurrent accounting writes, and separate PDF
extraction. Validate both skills and links, run Python/report suites, rebuild the
plugin, and smoke-test packaged scripts with fresh synthetic inputs. Do not access
live mailboxes, schedules, or private financial data while developing the release.
