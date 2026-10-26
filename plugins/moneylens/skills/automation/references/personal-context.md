# Transaction corrections and metadata

`<moneylens>` means `<python> <automation-skill>/scripts/moneylens.py`.

Use the public money-management interface for user-requested corrections:

```sh
<moneylens> list --data-dir <directory>
<moneylens> update --data-dir <directory> --id <transaction-ID> --category 'Household help'
<moneylens> update --data-dir <directory> --id <transaction-ID> --metadata '{"context":"User supplied context"}'
<moneylens> report --data-dir <directory> --output <saved-report.html>
```

Use IDs returned by `list`; statement rows use a statement ID plus row index. Metadata is a JSON object and `update --metadata` replaces that transaction's metadata object: read and merge existing values first when preserving unrelated fields. It does not rewrite the original email/statement evidence. Do not put passwords or raw identity inputs in metadata.

Manual entries can have their description, amount, date, category, and metadata updated, or be removed. Email/statement-backed rows retain original description, amount, date, reference, and movement evidence; only categories and user metadata are editable. Source-bound category corrections follow reconciled alerts onto their statement replacements. A category correction does not resolve ambiguous financial evidence or make an unvalidated transaction count in spending.

For a confirmed own-account transfer on a source-backed row, pass `own_account_key` and `transfer_evidence` together in metadata. Accounting validates that the counterparty is another confirmed owned account and preserves the original row. Amount/date/name similarity alone is insufficient.

## Accounting preferences and report scope

`<moneylens> preferences --data-dir <directory>` reads durable accounting choices.
Save a partial preferences object using `--input <private-preferences.json>`:

```json
{
  "category_treatments": {
    "Investment": "investment",
    "Investment withdrawal": "investment_withdrawal"
  },
  "report_from": "2026-09-01",
  "report_to": "2026-10-25"
}
```

The category map replaces the previous map when supplied; read and merge it to
retain other choices. `ordinary` explicitly uses normal movement-kind treatment.
Only bank-account rows use investment treatment. Labels are user/agent supplied,
not inferred from descriptions. Preserve separate salary and posted-interest
categories. Never classify cumulative-interest snapshots as dated credits.
Principal is visible in Cashflow and All transactions while excluded from
spending and ordinary money-in metrics. No reciprocal deposit movement or owned
counterparty is required. Source values and row annotations remain untouched.

Ordinary report refreshes reuse preferences and saved date scope. Explicit report
bounds replace the scope only after a successful write; empty strings clear it.
Rolling schedules must pass their newly computed dates. Cashflow and the
collapsed exclusion audit are built into the report template and survive JSON
refreshes alongside other views. Private reports keep their existing UI; to
adopt newly added features, generate this release's report at a new output path,
verify it, and save that path in account settings. Never hand-edit private HTML.

## Merchant cache and new classifications

```sh
<moneylens> merchants --data-dir <directory>
<moneylens> merchants --data-dir <directory> --merchant 'Example merchant'
<moneylens> merchants --data-dir <directory> --merchant 'Example merchant' --category Groceries
```

The agent checks the cache before categorizing. A miss returns `category:null` and `needs_category:true`; the agent decides the category using actual merchant/source context and user preferences. Scripts never classify new merchants using keywords, built-in lists, name shapes, or conditional rules.

`add --category` remembers a resolved supplied category for a new merchant. `add` without `--category` requires a cache hit. Statement imports can omit a row's `category` to apply its exact cached mapping automatically; missing categories without a cache hit remain for review. Validated statement imports remember supplied resolved categories too. Existing cache entries are retained when a transaction supplies a different one-off category. Deliberately update the reusable decision through `merchants --category`; row corrections remain separate. Historical explicit labels are preserved, while unresolved source rows can display an exact cached classification without rewriting evidence.

These saved mappings are deterministic rules: apply them without asking an LLM to classify the merchant again. Explicit transaction choices take priority over reusable mappings. Only a new uncached merchant or genuinely ambiguous source meaning needs agent interpretation. Scripts make no model calls.

Cache keys normalize case and whitespace only. There is no substring/fuzzy/alias matching. The agent can supply `metadata.merchant` as an explicit canonical key for source-description variants; raw descriptions and financial identity remain unchanged.

Leave ambiguous merchants as `Other` and uncached for review. Do not cache `Other` or guess a category to make the review disappear. Category uncertainty does not affect amount validation, reconciliation, or imported status. Scripts store category labels exactly as supplied.

Regenerate the same report after corrections, retaining its intended date range and UI. The report shows cached merchant decisions in Review. No Notes column; context belongs in metadata and private transaction annotations.
