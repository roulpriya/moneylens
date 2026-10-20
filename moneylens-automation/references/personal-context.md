# Personal context and corrections

Use `scripts/personalize.py` when the user provides a personal note, category correction, or recurring categorization rule. Notes are added through Codex and displayed/searchable in the local report; the standalone HTML does not write to SQLite.

```sh
python3 <skill-dir>/scripts/personalize.py --data-dir <private-data-dir> show
python3 <skill-dir>/scripts/personalize.py --data-dir <private-data-dir> annotate --record <statement-or-alert-ID> --row <zero-based-index> --note 'User supplied context' --category 'Household help'
python3 <skill-dir>/scripts/personalize.py --data-dir <private-data-dir> rules --input <private-rules.json>
```

`annotate` accepts either `--note` or `--category`, or both. An empty note clears it. Exact row evidence anchors the annotation across restaging; a reconciled alert's note/correction follows its statement replacement. Do not modify source merchant, date, amount, reference, or movement kind to personalize a row.

`rules` replaces the entire private rule list: read `show`, merge requested changes while preserving unrelated rules, then write the combined list. Use a temporary private file and delete it afterward. The list lives in SQLite `runtime_meta.personal_rules`; annotations live in `transaction_annotations`, never in committed assets. Reports apply these at read time to both existing and future records while preserving original categories. Explicit per-row corrections outrank rules. A rule does not validate an ambiguous transaction or release it into spending totals.

Each rule has `id`, `label`, `category`, `note` (user context, at most 2000 characters), and `when`. Rules use first-match priority, so specific merchants precede fallbacks. Conditions are ANDed:

- `merchant_contains`: any listed substring, case insensitive.
- `merchant_contains_all`: all listed substrings.
- `merchant_excludes`: none of the listed substrings.
- `name_like: true`: limit an explicitly requested personal-payee assumption to letter-based names; reject merchant IDs, digits, and common business words. This is a shape heuristic, not proof of identity. Add known business-name exceptions to `merchant_excludes`, and preserve a note stating the user's assumption.
- `category_in`: source category is in this list; use this to scope a personal fallback to unknown/Other merchants.
- `channel`, `currency`: exact values; `kinds`: accepted movement types.
- `amount_eq`, `amount_gt`, `amount_lte`: absolute integer minor units. Amount rules require currency. Scope spending rules to debit kinds so credits and repayments retain their meaning.

For example, an amount of ₹1,000 is `100000` minor units in INR. Prefer explicit merchant/service identity before a user-specified amount fallback. Do not infer that incoming UPI money is income or a refund from a personal spending note. Show assumptions as personal context instead of claiming a proven merchant identity. Ask one focused input question if the user's rule has a material ambiguity that cannot be resolved from the records.

After saving context, run the usual `ledger.py report` command at the configured Documents path, retaining its display date range. This refreshes all historical classifications without changing financial identity, imported status, duplicate detection, or totals across all categories. A new Notes column is a one-time explicit development template upgrade; daily runs continue changing only data.
