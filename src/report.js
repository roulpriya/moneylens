import { initializeReportDesign } from './report-design.js';
'use strict';
var data = JSON.parse(document.getElementById("data").textContent);
var $ = (id) => document.getElementById(id);
let activeChartBar = null;
function hideChartTooltip(bar) {
  if (bar && activeChartBar !== bar) return;
  activeChartBar?.removeAttribute('aria-describedby');
  activeChartBar = null;
  $('chart-tooltip').hidden = true;
}
function chartTooltip(bar, text, focusable = false) {
  bar.setAttribute('aria-label', text);
  if (focusable) { bar.tabIndex = 0; bar.setAttribute('role', 'img'); }
  const show = () => {
    hideChartTooltip();
    activeChartBar = bar;
    const tooltip = $('chart-tooltip');
    tooltip.textContent = text;
    tooltip.hidden = false;
    bar.setAttribute('aria-describedby', 'chart-tooltip');
    const anchor = bar.getBoundingClientRect(), hint = tooltip.getBoundingClientRect();
    const width = globalThis.innerWidth || document.documentElement.clientWidth;
    const height = globalThis.innerHeight || document.documentElement.clientHeight;
    tooltip.style.left = Math.max(8, Math.min(anchor.left + anchor.width / 2 - hint.width / 2, width - hint.width - 8)) + 'px';
    const above = anchor.top - hint.height - 12;
    tooltip.style.top = Math.max(8, Math.min(above >= 8 ? above : anchor.bottom + 12, height - hint.height - 8)) + 'px';
  };
  bar.addEventListener('pointerenter', show);
  bar.addEventListener('pointerleave', () => hideChartTooltip(bar));
  bar.addEventListener('focus', show);
  bar.addEventListener('click', show);
  bar.addEventListener('blur', () => hideChartTooltip(bar));
  bar.addEventListener('keydown', event => { if (event.key === 'Escape') hideChartTooltip(bar); });
}
globalThis.addEventListener?.('scroll', () => hideChartTooltip(), true);
globalThis.addEventListener?.('resize', () => hideChartTooltip());
function node(tag, text, cls) {
  const e = document.createElement(tag);
  if (text !== undefined)
    e.textContent = text;
  if (cls)
    e.className = cls;
  return e;
}
function currencyLabel(code) {
  return code || "";
}
function money(amount, exp, code) {
  if (amount === null || amount === undefined || !Number.isInteger(exp) || exp<0 || exp>18 || !code) return "Unresolved";
  amount = BigInt(amount);
  const negative = amount < 0n;
  if (negative)
    amount = -amount;
  const scale = 10n ** BigInt(exp), whole = (amount / scale).toString().replace(/\B(?=(\d{3})+(?!\d))/g, ",");
  return (negative ? "−" : "") + (code + " ") + whole + (exp ? "." + (amount % scale).toString().padStart(exp, "0") : "");
}
var dateFmt = new Intl.DateTimeFormat(undefined, { day: "numeric", month: "short", year: "numeric", timeZone: "UTC" });
function prettyDate(d) {
  const t = Date.parse(d + "T00:00:00Z");
  return isNaN(t) ? d : dateFmt.format(t);
}
var monthNames = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
function prettyMonth(m) {
  const [y, mo] = String(m).split("-").map(Number);
  return y && mo >= 1 && mo <= 12 ? monthNames[mo - 1] + " - " + y : m;
}
function sum(rows, predicate = () => true) {
  return rows.reduce((total, r) => total + (predicate(r) ? BigInt(r.amount_minor) : 0n), 0n);
}
function option(id, value, label) {
  const e = node("option", label);
  e.value = value;
  $(id).append(e);
}
var spendKinds = new Set(["purchase", "debit", "fee", "interest", "cash_advance", "adjustment_debit", "refund", "adjustment_credit"]);
// The decorated exclusion carries ownership proof. Movement labels alone do not.
var isInvestment = (r) => ['investment', 'investment_withdrawal'].includes(r.accounting_treatment);
var isTransfer = (r) => r.excluded_from_spending === true && !isInvestment(r);
var unverifiedTransferOut = (r) => r.kind === "transfer_out" && !isTransfer(r);
var eligible = (r) => !r.blocked && !r.suppressed && ["imported", "posted", "provisional", "draft"].includes(r.status);
var confirmed = (r) => ["imported", "posted"].includes(r.status);
var spending = (r) => r.excluded_from_spending !== true && spendKinds.has(r.kind);
var bankMovement = (r) => r.account_type === 'bank_account';
function preferredAmounts(rows, predicate) {
  const available = rows.filter(r => eligible(r) && Number.isSafeInteger(r.amount_minor) && predicate(r));
  const saved = available.filter(confirmed);
  return { rows: saved.length ? saved : available.filter(r => !confirmed(r)), provisional: !saved.length && available.length > 0 };
}
function reviewReasons(r) {
  if (r.suppressed) return [];
  const reasons = [];
  if (r.review_reason) reasons.push(r.review_reason);
  if (r.blocked || ["draft", "needs_review"].includes(r.status)) {
    const statement = data.statements.find(s => s.id === r.statement);
    reasons.push(...(statement?.checks?.issues || []));
  }
  if (!r.review_reason && r.kind === "unknown") reasons.push("The source row's movement type could not be identified.");
  if (!r.review_reason && r.amount_minor == null) reasons.push("The source row's amount could not be read.");
  if (unverifiedTransferOut(r)) reasons.push("The receiving account has not been confirmed as yours. Resolve whether this is an own-account transfer or an expense.");
  if (r.status === "draft") reasons.push("The statement is staged and has not been imported.");
  if ((r.blocked || r.status === "needs_review") && !reasons.length)
    reasons.push("Financial validation is unresolved; this row is excluded from totals.");
  if (spending(r) && r.amount_minor > 0 && r.category === "Other")
    reasons.push("Uncategorized transaction; the validated amount still counts in spending.");
  return [...new Set(reasons.map(reason => String(reason).trim()).filter(Boolean))];
}
var needsReview = (r) => reviewReasons(r).length > 0;
function stateLabel(r) {
  return r.suppressed ? "Reconciled duplicate · Excluded" : r.blocked ? "Needs review · Excluded" : r.status === "needs_review" ? "Needs review · Excluded" : r.status === "draft" ? "Provisional · Staged statement" : r.status === "provisional" ? "Provisional · Transaction" : r.status === "posted" ? "Confirmed · Transaction" : r.status === "imported" ? "Confirmed · Saved statement" : r.status;
}
function amountDisplay(r, fmt, tag, className) {
  const full = stateLabel(r), short = full.split(" · ")[0];
  const tone = r.suppressed ? "dim" : short === "Confirmed" ? "ok" : short === "Provisional" ? "prov" : short === "Needs review" ? "warn" : "dim";
  const amount = node(tag, undefined, className);
  const indicator = node("span", {ok: "✓", prov: "◷", warn: "!", dim: "↪"}[tone], "amount-status " + tone);
  indicator.title = full;
  indicator.setAttribute("role", "img");
  indicator.setAttribute("aria-label", full);
  amount.append(node("span", fmt(r.amount_minor)), indicator);
  return amount;
}
[...new Set(data.rows.map(row=>row.channel).filter(value=>typeof value==='string' && value.trim()))].sort().forEach(value=>option('channel',value,value));
var currencies = [...new Set([...data.rows, ...data.statements].map((r) => r.currency).filter(Boolean))].sort();
currencies.forEach((c) => option("currency", c, currencyLabel(c)));
if (!currencies.length)
  option("currency", "", "No transactions");
var availableMonths=[...new Set(data.rows.map(r=>r.date.slice(0,7)).filter(m=>/^\d{4}-(0[1-9]|1[0-2])$/.test(m)))].sort();
[...availableMonths].reverse().forEach(m=>option('month',m,prettyMonth(m)));
var latestMonth=availableMonths.filter(m=>data.rows.some(r=>r.currency===$('currency').value&&r.date.startsWith(m))).at(-1)||'';
$('month').value=latestMonth;
var accounts = new Map(data.rows.map((r) => [r.account_key, r.account]));
accounts.forEach((label, key) => option("account", key, label));
$("from").value = data.from;
$("to").value = data.to;
var categoryExpanded = false;
var categoryColors = new Map();
var sortKeys = ["date", "merchant", "category", "kind", "amount_minor", "account"];
var view = "spending";
var screen = "glance";
var categorySelection = null;
var reportDesign;
var sortKey = "date";
var direction = -1;
var page = 0;
var detailTrigger;
var sync = data.sync || {};
var reviewItems = data.review_items || [];
var sourceReviewItems = reviewItems.filter(r => r.group !== "Categorization");
function sourceDetails(sources, fields = []) {
  const details = node("details", undefined, "review-source-details");
  details.append(node("summary", "View source"));
  const pairs = [...fields];
  sources.forEach(source => {
    if (source.filename) pairs.push(["File", source.filename]);
    if (source.mailbox || source.mailbox_id) pairs.push(["Mailbox", source.mailbox || source.mailbox_id]);
    if (source.message_id) pairs.push(["Message", source.message_id]);
    if (source.attachment_id) pairs.push(["Attachment", source.attachment_id]);
  });
  const dl = node("dl");
  pairs.forEach(([label, value]) => dl.append(node("dt", label), node("dd", String(value))));
  if (pairs.length) details.append(dl);
  else details.append(node("p", "Source identifiers were not recorded for this item.", "muted"));
  return details;
}
function transactionSources(r) {
  const statement = data.statements.find(s => s.id === r.statement);
  const sources = [...(statement?.sources || []), statement?.source, r.source];
  const seen = new Set();
  return sources.filter(source => {
    if (!source) return false;
    const key = JSON.stringify(source);
    if (seen.has(key)) return false;
    seen.add(key); return true;
  });
}
function sourceName(source) {
  return source?.filename && source.filename !== "email-body" ? source.filename : source ? "Email message" : "Source not recorded";
}
function transactionSourceLink(r) {
  const sources = transactionSources(r), first = sources[0];
  const location = [r.page != null ? "p. " + r.page : null, r.row != null ? "row " + r.row : null].filter(Boolean).join(", ");
  const caption = [sourceName(first), sources.length > 1 ? "+" + (sources.length - 1) + (sources.length === 2 ? " source" : " sources") : null, first && location].filter(Boolean).join(" · ");
  const button = node("button", caption, "link transaction-source");
  button.type = "button";
  button.setAttribute("aria-label", "View source for " + r.merchant + " on " + r.date);
  button.addEventListener("click", () => showDetail(r, button));
  return button;
}
function spendingTreatment(r) {
  if (r.suppressed) return 'Duplicate-linked occurrence · Excluded from totals';
  if (!eligible(r)) return 'Validation-blocked transaction · Excluded from totals';
  if (isInvestment(r)) return 'Investment principal · Excluded from spending and ordinary income';
  if (isTransfer(r)) return 'Own-account transfer · Excluded from spending';
  if (unverifiedTransferOut(r)) return 'Outgoing movement · Transfer ownership needs review';
  if (spending(r)) return 'Included in spending';
  return ['payment','repayment'].includes(r.kind) ? 'Repayment · Excluded from spending' : 'Incoming money · Excluded from spending';
}
function showDetail(r, trigger) {
  detailTrigger = trigger;
  const statement = data.statements.find((s) => s.id === r.statement), sources = transactionSources(r), fmt = (n) => money(n, r.exponent, r.currency);
  const fields = [["Date", r.date], ["Merchant", r.merchant], ["Category", r.category], ["Movement", r.kind.replaceAll("_", " ")], ["Amount", fmt(r.amount_minor)], ["Account", r.account], ["State", stateLabel(r)], ["Spending treatment", spendingTreatment(r)], ["Payment type", r.channel ?? "Not provided"], ["Source record", r.statement || "Unavailable"], ["Source page / row", (r.page ?? "Unavailable") + " / " + (r.row ?? "Unavailable")]];
  if (r.reference) fields.push(['Reference', r.reference]);
  if (r.accounting_reason) fields.push(['Accounting treatment', r.accounting_reason]);
  fields.push(['Cashflow treatment', !eligible(r) ? 'Excluded while validation is unresolved or the occurrence is duplicate-linked' : bankMovement(r) ? 'Included in bank cashflow' : 'Outside bank cashflow scope']);
  if (eligible(r) && spending(r) && r.category === 'Other') fields.push(['Category review', 'Uncategorized; amount still counts']);
  if (r.duplicate_of || r.review_reason)
    fields.push(['Source row mapping', r.duplicate_of ? 'Duplicate linked to ' + r.duplicate_of.statement + ' / row ' + r.duplicate_of.index + ': ' + r.duplicate_of.evidence : r.review_reason]);
  if (r.original_merchant && r.original_merchant !== r.merchant)
    fields.push(['Original descriptor', r.original_merchant]);
  if (r.metadata?.display_note) fields.push(['Source note', r.metadata.display_note]);
  if (needsReview(r)) fields.push(['Review reasons', reviewReasons(r).join(' · ')]);
  fields.push(['Document completeness', r.coverage_status || statement?.coverage?.status || statement?.checks?.coverage?.status || 'Completeness not verified']);
  sources.forEach(source => {
    fields.push(["Source", sourceName(source)]);
    if (source.mailbox || source.mailbox_id) fields.push(["Mailbox", source.mailbox || source.mailbox_id]);
    if (source.message_id) fields.push(["Message", source.message_id]);
    if (source.attachment_id) fields.push(["Attachment", source.attachment_id]);
  });
  if (!sources.length) fields.push(["Source", "Source identifiers were not recorded for this transaction."]);
  if (r.transfer_evidence)
    fields.push(["Transfer evidence", r.transfer_evidence]);
  if (statement) {
    fields.push(["Statement period", statement.period]);
    const coverage = statement.coverage || statement.checks?.coverage;
    if (coverage?.section) {
      fields.push(['Account section completeness', coverage.section.status]);
      if (coverage.section.gaps?.length) fields.push(['Account section gaps', coverage.section.gaps.join(' · ')]);
    }
    if (!coverage) fields.push(["Coverage evidence", "Source row coverage evidence is missing, so completeness cannot be verified."]);
    const gaps = [...new Set(coverage?.gaps || [])];
    if (gaps.length) fields.push(["Coverage gaps", gaps.join(" · ")]);
    if (coverage?.mapped_counts) fields.push(["Source rows", coverage.source_row_count + " total · " + coverage.mapped_counts.retained + " retained · " + coverage.mapped_counts.duplicate_linked + " duplicate linked · " + coverage.mapped_counts.review + " for review"]);
    if (statement.financial_review_resolved !== undefined) fields.push(["Financial review", statement.financial_review_resolved ? "Resolved" : "Unresolved"]);
    const checks = statement.checks || {};
    if (checks.issues?.length) fields.push(["Validation issues", checks.issues.join(" · ")]);
    fields.push(["Passed checks", checks.passed_checks?.length ? checks.passed_checks.map(check => check.replaceAll("_", " ")).join(" · ") : "No independent checks recorded"]);
    if (checks.unavailable_checks?.length) fields.push(["Unavailable checks", checks.unavailable_checks.map(check => check.replaceAll("_", " ")).join(" · ")]);
    if (statement.resolution_notes) fields.push(["Resolution", statement.resolution_notes]);
  }
  $("detail-fields").replaceChildren(...fields.flatMap(([label, value]) => [node("dt", label), node("dd", String(value))]));
  $("transaction-detail").hidden = false;
  $("close-detail").focus?.();
  $("transaction-detail").scrollIntoView?.({ behavior: "smooth", block: "nearest" });
}
function closeDetail() {
  $("transaction-detail").hidden = true;
  detailTrigger?.focus?.();
}
$("close-detail").addEventListener("click", closeDetail);
function cards(items) {
  $("metrics").replaceChildren(...items.map(([label, value, hint]) => {
    const card = node("div", undefined, "card");
    card.append(node("div", label, "label"), node("div", value, "value"));
    if (hint) card.append(node("div", hint, "muted"));
    return card;
  }));
}
function effectiveMonth() { return screen==='glance'?$('month').value:''; }
function filteredRows() {
  const glance=screen==='glance';
  const code = $("currency").value, month = effectiveMonth(), account = $("account").value, state = glance?'':$("state").value, query = glance?'':$("search").value.trim().toLowerCase();
  return data.rows.filter((r) => (!$("channel").value || r.channel === $("channel").value) && (!code || r.currency === code || (!r.currency && ["review", "all"].includes(view))) && (!month || r.date.startsWith(month)) && (!account || r.account_key === account) && (!state ? (view === "all" || !r.suppressed) : state === "unresolved" ? r.blocked || r.status === "needs_review" : r.status === state) && (glance || !$("from").value || r.date >= $("from").value) && (glance || !$("to").value || r.date <= $("to").value) && (!query || [r.merchant, r.category, r.account, r.kind, r.reference || "", stateLabel(r), ...(view === "review" ? reviewReasons(r) : [])].join(" ").toLowerCase().includes(query)));
}
var isEarning = (r) => eligible(r) && !isTransfer(r) && !r.excluded_from_income && BigInt(r.amount_minor) < 0n && !spendKinds.has(r.kind) && !["payment", "repayment"].includes(r.kind);
var isCardPayment = (r) => eligible(r) && !isTransfer(r) && ["payment"].includes(r.kind) && BigInt(r.amount_minor) < 0n;
function renderExclusions() {
  const withinDates = r => (!$('from').value || r.date >= $('from').value) && (!$('to').value || r.date <= $('to').value) && (!effectiveMonth() || r.date.startsWith(effectiveMonth()));
  const scope = data.rows.filter(r => (!$('currency').value || r.currency === $('currency').value) && (!$('account').value || r.account_key === $('account').value) && (!$('channel').value || r.channel === $('channel').value));
  const rows = scope.filter(withinDates);
  const covered = (data.covered_alerts || []).filter(r => (!$('currency').value || r.currency === $('currency').value) && (!$('account').value || r.account_key === $('account').value) && withinDates(r));
  const items = [
    [rows.filter(r => r.blocked || r.status === 'needs_review').length, 'Validation-blocked transactions: excluded from all totals until source checks are resolved.'],
    [rows.filter(r => eligible(r) && spending(r) && r.category === 'Other').length, 'Uncategorized transactions: validated amounts still count in spending.'],
    [rows.filter(r => eligible(r) && (isTransfer(r) || ['payment','repayment'].includes(r.kind))).length, 'Transfers and repayments: excluded from spending; eligible bank movements remain in cashflow.'],
    [rows.filter(r => eligible(r) && isInvestment(r)).length, 'Investment principal movements: excluded from spending and ordinary income; included in bank cashflow.'],
    [rows.filter(r => r.suppressed).length, 'Duplicate-linked occurrences: evidence retained; excluded from totals.'],
    [covered.length, 'Alerts covered by statements: excluded from financial rows; original evidence retained. Count uses account, currency and dates.'],
    [scope.filter(r => r.date && !withinDates(r)).length, 'Transactions outside selected dates: retained in the ledger; excluded from this date selection.']
  ];
  $('accounting-exclusions')?.replaceChildren(node('li', 'Counts use account, currency, payment type and dates, independently of search, record state and transaction view.'), ...items.map(([count, explanation]) => node('li', count + ' · ' + explanation)));
}

function update() {
  hideChartTooltip();
  const filtered = filteredRows(), code = $("currency").value, exp = filtered[0]?.exponent ?? data.rows.find((r) => r.currency === code)?.exponent ?? data.statements.find((s)=>s.currency===code)?.exponent ?? null, fmt = (n) => money(n, exp, code || "");
  const visible = filtered.filter((r) => view === "all" ? true : view === "review" ? needsReview(r) : eligible(r) && (view === "spending" ? spending(r) : view === "cashflow" ? bankMovement(r) : view === "transfers" ? isTransfer(r) : !isTransfer(r) && !isInvestment(r) && r.amount_minor < 0));
  renderExclusions();
  const included = visible.filter(eligible), saved = included.filter(confirmed), provisional = included.filter((r) => !confirmed(r));
  const title = { all: "All transactions", spending: "Spending overview", incoming: "Incoming money", cashflow: "Bank cashflow", transfers: "Own-account transfers", review: "Review" };
  $("view-title").textContent = title[view];
  $("table-title").className = screen === 'review' ? "sr-only" : "";
  $("table-title").textContent = { all: "All transactions", spending: "Transactions", incoming: "Transactions", cashflow: "Bank movements", transfers: "Transactions", review: "Transactions to review" }[view];
  $("spending-breakdown").hidden = view !== "spending";
  $("review-panel").hidden = view !== "review";
  $("report-title").textContent = {all:"All transactions",spending:"Spending report",incoming:"Incoming money",cashflow:"Bank cashflow",transfers:"Transfers",review:"Review"}[view];
  const dates=screen==='glance'?filtered.map(r=>r.date).filter(Boolean).sort():[$('from').value,$('to').value].filter(Boolean);
  const periodDates=screen==='glance'?[...new Set([dates[0],dates.at(-1)].filter(Boolean))]:dates;
  $("report-period").textContent = [$("month").value ? prettyMonth($("month").value) : periodDates.map(prettyDate).join(" – "), currencyLabel(code)].filter(Boolean).join(" · ");
  const notes = { all: "", spending: "", incoming: "Includes refunds and repayments; own transfers and investment principal excluded.", cashflow: "All eligible bank movements, including Investment, Investment withdrawal, repayments and own transfers. Card entries are outside this scope. Principal is excluded from spending and ordinary income; posted interest stays separate.", transfers: "Both account legs; excluded from spending.", review: "Blocked rows are excluded from totals; category decisions are included." };
  $("view-note").textContent = notes[view];
  $("view-note").hidden = !notes[view];
  if (view === "spending")
    cards([["Confirmed net", fmt(sum(saved)), ""], ["Provisional net", fmt(sum(provisional)), ""], ["Estimated net", fmt(sum(included)), ""], ["Refunds", fmt(-sum(included, (r) => r.amount_minor < 0)), ""]]);
  else if (view === "incoming")
    cards([["Confirmed money in", fmt(-sum(saved)), ""], ["Provisional money in", fmt(-sum(provisional)), ""], ["Total money in", fmt(-sum(included)), ""], ["Transactions", String(visible.length), ""]]);
  else if (view === "transfers")
    cards([["Money out", fmt(sum(included, (r) => r.amount_minor > 0)), ""], ["Money in", fmt(-sum(included, (r) => r.amount_minor < 0)), ""], ["Provisional legs", String(provisional.length), ""], ["Transactions", String(visible.length), ""]]);
  else if (view === 'cashflow')
    cards([["Bank inflows", fmt(-sum(included, r => r.amount_minor < 0)), "Includes investment withdrawals"], ["Bank outflows", fmt(sum(included, r => r.amount_minor > 0)), "Includes investments and repayments"], ["Confirmed net cashflow", fmt(-sum(saved)), "Across selected bank accounts"], ["Provisional net cashflow", fmt(-sum(provisional)), ""]]);
  else if (view === 'all')
    cards([["Source occurrences", String(visible.length), ""], ["Repayments", String(visible.filter(r => ['payment','repayment'].includes(r.kind)).length), "Excluded from spending"], ["Review rows", String(visible.filter(needsReview).length), ""], ["Duplicate links", String(visible.filter(r => r.suppressed).length), "Excluded from totals"]]);
  else
    cards([["Transactions to review", String(visible.length), ""], ["Excluded records", String(visible.filter((r) => !eligible(r)).length), ""], ["Category decisions", String(visible.filter((r) => eligible(r) && r.category === "Other").length), ""], ["Source review items", String(sourceReviewItems.length), "Across all sources"]]);
  const category = new Map;
  included.filter((r) => spending(r) && r.amount_minor > 0).forEach((r) => category.set(r.category, (category.get(r.category) || 0n) + BigInt(r.amount_minor)));
  const gross = sum(included, (r) => spending(r) && r.amount_minor > 0), cats = [...category].sort((a, b) => a[1] > b[1] ? -1 : a[1] < b[1] ? 1 : 0);
  const reportBasis = preferredAmounts(filtered, spending), reportRows = reportBasis.rows;
  if (screen === 'report' || screen === 'glance') {
    const reportCategory = new Map();
    reportRows.filter(r=>spending(r) && BigInt(r.amount_minor)>0n).forEach(r=>reportCategory.set(r.category,(reportCategory.get(r.category)||0n)+BigInt(r.amount_minor)));
    const actualCats=[...reportCategory].sort((a,b)=>a[1]>b[1]?-1:a[1]<b[1]?1:a[0].localeCompare(b[0]));
    renderCategoryVisuals(actualCats, sum(reportRows,r=>spending(r)&&BigInt(r.amount_minor)>0n), fmt, reportBasis.provisional);
  } else renderCategoryVisuals(cats, gross, fmt);
  renderActuals(filtered, fmt);
  renderDaily(filtered, fmt);
  renderGlance(filtered, fmt);
  renderCategoryChips(included);
  const tableRows = view === "spending" && categorySelection ? visible.filter(r => categorySelection.includes(r.category)) : visible;
  $("category-selection").hidden = !categorySelection || view !== "spending";
  $("category-selection-label").textContent = categorySelection ? categorySelection.length === 1 ? categorySelection[0] : "Other categories" : "";
  const sorted = [...tableRows].sort((a, b) => {
    if (sortKey === 'amount_minor' && (a.amount_minor == null || b.amount_minor == null))
      return a.amount_minor == null ? b.amount_minor == null ? 0 : 1 : -1;
    const x = sortKey === "amount_minor" ? BigInt(a.amount_minor) : String(a[sortKey]), y = sortKey === "amount_minor" ? BigInt(b.amount_minor) : String(b[sortKey]);
    return (typeof x === "bigint" ? x > y ? 1 : x < y ? -1 : 0 : x.localeCompare(y)) * direction;
  });
  const size = Number($("page-size").value) || 25, pages = Math.max(1, Math.ceil(sorted.length / size));
  page = Math.min(page, pages - 1);
  $("transactions").replaceChildren(...sorted.slice(page * size, (page + 1) * size).map((r) => {
    const tr = node("tr");
    const amount = amountDisplay(r, fmt, 'td', 'num' + (r.amount_minor != null && BigInt(r.amount_minor) < 0n ? ' credit' : ''));
    const merchant = node("td", undefined, "merchant");
    merchant.append(node("span", r.merchant));
    tr.append(node("td", prettyDate(r.date), "date"), merchant, node("td", r.category), node("td", r.kind.replaceAll("_", " "), "kind"), amount, node("td", r.account, "acct"));
    const td = node("td"), button = node("button", "View", "link");
    button.type = "button";
    button.setAttribute("aria-label", "Details for " + r.merchant + " on " + r.date);
    button.addEventListener("click", () => showDetail(r, button));
    td.append(button);
    tr.append(td);
    return tr;
  }));
  $("review-transactions").replaceChildren(...(view === "review" ? sorted.slice(page * size, (page + 1) * size) : []).map(r => {
    const item = node("li", undefined, "review-item");
    const heading = node("div", undefined, "review-item-heading");
    heading.append(node("strong", r.merchant), amountDisplay(r, fmt, "span", "review-amount"));
    item.append(heading, node("div", [prettyDate(r.date), r.account].filter(Boolean).join(" · "), "muted"), transactionSourceLink(r));
    reviewReasons(r).forEach(reason => item.append(node("p", reason, "review-reason")));
    const button = node("button", "View details", "link");
    button.type = "button";
    button.setAttribute("aria-label", "Details for " + r.merchant + " on " + r.date);
    button.addEventListener("click", () => showDetail(r, button));
    item.append(button);
    return item;
  }));
  if (!tableRows.length) {
    $("review-transactions").append(node("li", "No transactions need review for this selection.", "muted review-empty"));
    const tr = node("tr"), td = node("td", "No transactions.");
    td.colSpan = 7;
    tr.append(td);
    $("transactions").append(tr);
  }
  $("page-info").textContent = tableRows.length ? `${page * size + 1}–${Math.min((page + 1) * size, tableRows.length)} of ${tableRows.length} · Page ${page + 1} of ${pages}` : "0 transactions";
  $("previous-page").disabled = page === 0;
  $("next-page").disabled = page >= pages - 1;
  sortKeys.forEach((key) => $("head-" + key).setAttribute("aria-sort", key === sortKey ? direction === 1 ? "ascending" : "descending" : "none"));
  routeScreen();
  reportDesign?.refresh();
}
var localTime = (value) => new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "short", ...sync.timezone ? { timeZone: sync.timezone } : {} }).format(new Date(value));
if (sync.merchant_categories?.length) {
  $("merchant-categories").hidden = false;
  $("merchant-list").replaceChildren(...sync.merchant_categories.map((merchant) => {
    const item = node("div", undefined, "source");
    item.append(node("strong", merchant.merchant), node("div", merchant.category, "muted"));
    return item;
  }));
}
$("review-summary").textContent = "Issues to review";
const reviewCount = data.rows.filter(needsReview).length + sourceReviewItems.length;
$("review-count").textContent = String(reviewCount);
$("review-count").hidden = reviewCount === 0;
sourceReviewItems.forEach(item => {
  const line = node("li", undefined, "review-item");
  const matchingSources = data.statements.flatMap(s => (s.sources || [s.source]).filter(source => source?.message_id === item.message_id && (!item.mailbox_id || source.mailbox === item.mailbox_id)).map(source => ({statement:s, source})));
  const match = matchingSources.length === 1 ? matchingSources[0] : null;
  const heading = node("div", undefined, "review-item-heading");
  heading.append(node("strong", item.account || match?.statement.account || match?.source.filename || "Source awaiting review"));
  if (item.group) heading.append(node("span", item.group, "muted"));
  line.append(heading);
  const context = [match?.source.filename, match?.statement.period].filter(Boolean).join(" · ");
  if (context) line.append(node("div", context, "muted"));
  line.append(node("p", item.reason || "This source has an unresolved validation issue; a specific reason was not recorded.", "review-reason"));
  line.append(sourceDetails(match ? [match.source] : [item], match ? [["Account", match.statement.account], ["Statement period", match.statement.period]] : []));
  $("review-groups").append(line);
});
$("footer").textContent = data.generated ? "Updated " + localTime(data.generated) : "Template preview · No account data.";
function changeTransactionType(name) {
  view = name;
  if (name === 'all') {
    ['month', 'account', 'state', 'from', 'to', 'search', 'channel'].forEach(id => $(id).value = '');
  }
  screen = name === "review" ? "review" : "report";
  categorySelection = null;
  page = 0;
  closeDetail();
  update();
}
$("transaction-type").addEventListener("input",()=>changeTransactionType($("transaction-type").value));
$("view-review").addEventListener("click",()=>changeTransactionType("review"));
$("transaction-category").addEventListener("input",()=>{categorySelection=$("transaction-category").value?[$("transaction-category").value]:null;page=0;closeDetail();update();});
$("expenses-title").addEventListener("click",()=>{categoryExpanded=!categoryExpanded;renderCategoryExpansion();});
sortKeys.forEach((key) => $("sort-" + key).addEventListener("click", () => {
  direction = sortKey === key ? -direction : key === "date" || key === "amount_minor" ? -1 : 1;
  sortKey = key;
  page = 0;
  closeDetail();
  update();
}));
["currency", "month", "account", "state", "from", "to", "search", "channel", "page-size"].forEach((id) => $(id).addEventListener("input", () => {
  if (id !== "page-size") categorySelection = null;
  page = 0;
  closeDetail();
  update();
}));
$("previous-page").addEventListener("click", () => {
  if (page > 0)
    page--;
  closeDetail();
  update();
});
$("next-page").addEventListener("click", () => {
  page++;
  closeDetail();
  update();
});
$("clear-category").addEventListener("click", () => {categorySelection = null; page = 0; closeDetail(); update();});
['glance','report'].forEach(name=>$('tab-'+name).addEventListener('click',()=>{
  screen=name;if(view==='review')view='spending';page=0;categorySelection=null;closeDetail();update();
}));
$('glance-report').addEventListener('click',()=>$('tab-report').click());
$('glance-transactions').addEventListener('click',()=>{openReportTransactions();jumpToTransactions();});
$('glance-review').addEventListener('click',()=>$('view-review').click());
function moveMonth(direction) {
  const current=$('month').value||latestMonth||availableMonths.at(-1);
  if(!current)return;
  const date=new Date(current+'-01T00:00:00Z');if($('month').value)date.setUTCMonth(date.getUTCMonth()+direction);
  const month=date.toISOString().slice(0,7);
  if(!availableMonths.includes(month)){option('month',month,prettyMonth(month));availableMonths.push(month);availableMonths.sort();}
  $('month').value=month;page=0;categorySelection=null;closeDetail();update();
}
$('previous-month').addEventListener('click',()=>moveMonth(-1));
$('next-month').addEventListener('click',()=>moveMonth(1));
function rangeText(from,to) {
  return from&&to?prettyDate(from)+' – '+prettyDate(to):from?'From '+prettyDate(from):to?'Through '+prettyDate(to):'All time';
}
function applyDateRange(from,to) {
  const valid=value=>!value||/^\d{4}-\d{2}-\d{2}$/.test(value)&&!isNaN(Date.parse(value+'T00:00:00Z'))&&new Date(value+'T00:00:00Z').toISOString().slice(0,10)===value;
  if(!valid(from)||!valid(to)||(from&&to&&from>to)){
    $('range-error').textContent='Choose valid dates with From on or before Through.';$('range-error').hidden=false;return;
  }
  $('from').value=from;$('to').value=to;$('range-error').hidden=true;
  $('report-date-range').open=false;page=0;categorySelection=null;closeDetail();update();$('date-range-toggle').focus?.();
}
function fitReportPopover(triggerId,panelId) {
  const height=globalThis.innerHeight||document.documentElement.clientHeight;
  const nav=$('report-navigation');
  const reserve=globalThis.getComputedStyle?.(nav)?.position==='fixed'?nav.getBoundingClientRect().height:0;
  const available=height-reserve-$(triggerId).getBoundingClientRect().bottom-8-16;
  $(panelId).style.maxHeight=Math.max(0,Math.floor(available/4)*4)+'px';
}
function fitOpenReportPopovers() {
  if($('report-date-range').open)fitReportPopover('date-range-toggle','date-range-popover');
  if($('glance-filter-menu').open)fitReportPopover('glance-filter-toggle','glance-filter-fields');
}
globalThis.addEventListener?.('resize',fitOpenReportPopovers);
globalThis.addEventListener?.('scroll',fitOpenReportPopovers,true);
$('date-range-toggle').addEventListener('click',()=>{
  if(!$('report-date-range').open){fitReportPopover('date-range-toggle','date-range-popover');$('glance-filter-menu').open=false;$('range-from').value=$('from').value;$('range-to').value=$('to').value;$('range-error').hidden=true;}
});
$('range-apply').addEventListener('click',()=>applyDateRange($('range-from').value,$('range-to').value));
$('range-cancel').addEventListener('click',()=>{$('report-date-range').open=false;$('date-range-toggle').focus?.();});
$('report-date-range').addEventListener('keydown',event=>{if(event.key==='Escape'){event.preventDefault();$('report-date-range').open=false;$('date-range-toggle').focus?.();}});
['last7','last30','thismonth','lastmonth','thisyear','all'].forEach(preset=>$('range-'+preset).addEventListener('click',()=>{
  const now=new Date(),year=now.getFullYear(),month=now.getMonth();
  const today=new Date(Date.UTC(year,month,now.getDate())),iso=date=>date.toISOString().slice(0,10);
  let from='',to='';
  if(preset==='last7'||preset==='last30'){const start=new Date(today);start.setUTCDate(start.getUTCDate()-(preset==='last7'?6:29));from=iso(start);to=iso(today);}
  if(preset==='thismonth'||preset==='lastmonth'){const offset=preset==='lastmonth'?-1:0;from=iso(new Date(Date.UTC(year,month+offset,1)));to=iso(new Date(Date.UTC(year,month+offset+1,0)));}
  if(preset==='thisyear'){from=iso(new Date(Date.UTC(year,0,1)));to=iso(today);}
  applyDateRange(from,to);
}));
$('glance-filter-toggle').addEventListener('click',()=>{if(!$('glance-filter-menu').open){fitReportPopover('glance-filter-toggle','glance-filter-fields');$('report-date-range').open=false;}});
$('glance-filter-menu').addEventListener('keydown',event=>{
  if(event.key!=='Escape')return;
  event.preventDefault();$('glance-filter-menu').open=false;$('glance-filter-toggle').focus?.();
});
reportDesign = initializeReportDesign();
update();

function jumpToTransactions() {
  $('transactions-panel').focus?.({preventScroll:true});
  $('transactions-panel').scrollIntoView?.({block:'start'});
}
function openReportTransactions() {
  if(screen==='glance') {
    const month=$('month').value;
    $('from').value=month?month+'-01':'';
    $('to').value=month?new Date(Date.UTC(Number(month.slice(0,4)),Number(month.slice(5,7)),0)).toISOString().slice(0,10):'';
    $('search').value=$('state').value='';
  }
  screen='report';view='all';categorySelection=null;page=0;closeDetail();update();
}
function selectCategory(labels) {
  if(screen==='report')$('month').value='';
  screen = "report";
  view = "spending";
  categorySelection = labels;
  page = 0;
  closeDetail();
  update();
  jumpToTransactions();
}
function renderCategoryVisuals(cats, gross, fmt, provisional = false) {
  const allCategories = [...new Set(data.rows.map(r=>r.category))].sort();
  const usedColors = new Set();
  const color = label => {
    let index = allCategories.indexOf(label) % 6;
    while (usedColors.has(index)) index = (index + 1) % 5;
    usedColors.add(index);
    return 'var(--chart-' + (index + 1) + ')';
  };
  const percent = value => gross > 0n ? Number(value * 100000n / gross) / 1000 : 0;
  const groups = cats.slice(0,5).map(([label,value])=>({label,value,labels:[label],color:color(label)}));
  if (cats.length>5) groups.push({label:'Other categories',value:cats.slice(5).reduce((a,c)=>a+c[1],0n),labels:cats.slice(5).map(c=>c[0]),color:'var(--chart-6)'});
  let position = 0;
  const segments = groups.map(g=>{const start=position;position+=percent(g.value);return g.color+' '+start+'% '+position+'%';});
  // Last stop closes the circle despite integer-ratio rounding.
  if(groups.length) segments.push(groups.at(-1).color+' '+position+'% 100%');
  $('category-chart').style.background = groups.length ? 'conic-gradient('+segments.join(', ')+')' : 'var(--bar-track)';
  $('category-chart').setAttribute('aria-label', cats.length ? (provisional?'Provisional purchases: ':'Purchases: ')+fmt(gross)+'. '+cats.map(([label,value])=>label+' '+fmt(value)).join('; ') : 'No purchases for these filters');
  $('category-total').textContent = fmt(gross);
  $('category-caption').textContent = (provisional?'Provisional · ':'')+'before refunds';
  categoryColors=new Map(groups.flatMap(g=>g.labels.map(label=>[label,g.color])));

}

// Actuals are computed in integer minor units, independently of transaction subviews.
function renderActuals(rows,fmt) {
  const basis=preferredAmounts(rows,spending),incomeBasis=preferredAmounts(rows,isEarning);
  const expenses=basis.rows;
  const purchases=sum(expenses,r=>BigInt(r.amount_minor)>0n),refunds=-sum(expenses,r=>BigInt(r.amount_minor)<0n);
  const incoming=-sum(incomeBasis.rows),net=purchases-refunds;
  const bankBasis=preferredAmounts(rows,bankMovement);
  const cashflows=[
    ['Bank inflows',-sum(bankBasis.rows,r=>r.amount_minor<0)],
    ['Bank outflows',sum(bankBasis.rows,r=>r.amount_minor>0)],
    ['Investment',sum(bankBasis.rows,r=>isInvestment(r)&&r.amount_minor>0)],
    ['Investment withdrawal',-sum(bankBasis.rows,r=>isInvestment(r)&&r.amount_minor<0)],
    ['Net bank cashflow',-sum(bankBasis.rows)]
  ];
  $('cashflow-summary')?.replaceChildren(...cashflows.map(([name,value])=>{const tr=node('tr');tr.append(node('th',(bankBasis.provisional?'Provisional ':'')+name),node('td',fmt(value),'num'));return tr;}));
  const pendingRows=rows.filter(r=>eligible(r)&&!confirmed(r)&&spending(r)),pending=sum(pendingRows);
  const label=(name,provisional=basis.provisional)=>provisional?'Provisional '+name[0].toLowerCase()+name.slice(1):name;
  const values=[['Period',effectiveMonth()?prettyMonth(effectiveMonth()):rangeText($('from').value,$('to').value)],[label('Money in',incomeBasis.provisional),fmt(incoming)],[label('Purchases'),fmt(purchases)],[label('Refunds'),fmt(refunds)],[label('Net spend'),fmt(net)]];
  if(!basis.provisional)values.push(['Provisional net',fmt(pending)]);
  $('actuals-summary').replaceChildren(...values.map(([label,value])=>{const tr=node('tr');tr.append(node('th',label),node('td',value,'num'));return tr;}));
  $('hero-in-label').textContent='Money in';
  $('hero-out-label').textContent='Money out';
  $('hero-in-total').textContent=fmt(incoming);
  $('hero-in-status').textContent=incomeBasis.provisional?'Provisional':'';
  $('hero-in-status').hidden=!incomeBasis.provisional;
  const pendingIncoming=rows.filter(r=>eligible(r)&&!confirmed(r)&&isEarning(r));
  $('hero-in-provisional').hidden=incomeBasis.provisional||!pendingIncoming.length;
  $('hero-in-provisional').textContent=!incomeBasis.provisional&&pendingIncoming.length?'Provisional money in '+fmt(-sum(pendingIncoming)):'';
  $('hero-label').textContent=basis.provisional?'Provisional':'';
  $('hero-label').hidden=!basis.provisional;
  $('hero-total').textContent=fmt(net);
  $('hero-provisional').hidden=basis.provisional||!pendingRows.length;
  $('hero-provisional').textContent=!basis.provisional&&pendingRows.length?'Provisional net '+fmt(pending):'';
  const actualCard=(label,value)=>{const e=node('div',undefined,'hero-card');e.append(node('span',label,'label'),node('strong',value,'value'));return e;};
  const {start,end}=observedPeriod(rows);
  const days=start&&end&&start<=end?Math.floor((Date.parse(end+'T00:00:00Z')-Date.parse(start+'T00:00:00Z'))/86400000)+1:0;
  $('hero-metrics').replaceChildren(actualCard(label('Refunds'),fmt(refunds)),actualCard(label('Net bank cashflow',bankBasis.provisional),fmt(-sum(bankBasis.rows))),actualCard(label('Daily average'),fmt(days?net/BigInt(days):0n)));
  const categories=new Map();
  expenses.forEach(r=>{const v=categories.get(r.category)||[0n,0n];v[0]+=BigInt(r.amount_minor);if(BigInt(r.amount_minor)>0n)v[1]+=BigInt(r.amount_minor);categories.set(r.category,v);});
  const categoryRows=[...categories].sort((a,b)=>a[1][0]>b[1][0]?-1:a[1][0]<b[1][0]?1:a[0].localeCompare(b[0])).map(([name,[value,gross]])=>{
    const button=node('button',undefined,'category-choice'),swatch=node('span',undefined,'category-swatch');
    button.type='button';swatch.style.background=categoryColors.get(name)||'var(--chart-6)';
    const share=purchases>0n?Number(gross*10000n/purchases)/100:0;
    button.append(swatch,node('span',name,'category-name'),node('strong',fmt(value),'category-amount'),node('span',share.toFixed(1)+'%','pct'));
    button.setAttribute('aria-pressed',String(!!categorySelection&&categorySelection.includes(name)));
    const tip=name+' · '+(basis.provisional?'Provisional purchases ':'Purchases ')+fmt(gross)+' ('+share.toFixed(1)+'%) · Net spending '+fmt(value);
    button.title=tip;chartTooltip(button,tip);
    button.addEventListener('click',()=>selectCategory([name]));return button;
  });
  $('categories').replaceChildren(...categoryRows.slice(0,3));
  if(!categoryRows.length)$('categories').append(node('p','No expenses in this selection.','muted'));
  $('actual-expenses').replaceChildren(...categoryRows.slice(3));
  $('expenses-title').hidden=categoryRows.length<=3;

}
function routeScreen() {
  const glance=screen==='glance',report=screen==='report',review=screen==='review',detailed=!glance;
  $('report-components').setAttribute('data-screen',screen);
  $('glance-filters').hidden=!glance;
  $('report-period').hidden=true;
  $('report-date-range').hidden=!detailed;
  $('date-range-label').textContent=rangeText($('from').value,$('to').value);
  $('month-filter').hidden=detailed;
  $('from-filter').hidden=$('to-filter').hidden=detailed;
  $('primary-filters').className=detailed?'filters report-filters':'filters';
  $('secondary-filter-fields').className=detailed?'filters secondary report-secondary':'filters secondary';
  if(!detailed)$('report-date-range').open=false;
  for(const id of ['primary-filters','accounting-filters','actuals-breakdown'])$(id).hidden=glance;
  $('secondary-filters').hidden=true;
  const mount=(container,ids)=>ids.forEach(id=>{if($(id).parentElement!==$(container))$(container).append($(id));});
  mount('primary-filters',['month-filter']);
  mount(detailed?'report-heading':'glance-filters',['glance-filter-menu']);
  mount(detailed?'glance-filter-fields':'secondary-filters',['secondary-filter-fields']);
  $('secondary-filter-fields').hidden=glance;
  $('secondary-filter-fields').className=detailed?'filters secondary report-secondary':'filters secondary';
  const monthValue=$('month').value;
  $('glance-month-label').textContent=monthValue?new Intl.DateTimeFormat(undefined,{month:'long',year:'numeric',timeZone:'UTC'}).format(new Date(monthValue+'-01T00:00:00Z')):availableMonths.length?'All months':'No months';
  $('previous-month').disabled=$('next-month').disabled=!monthValue&&!availableMonths.length;
  mount('glance-filter-fields',['account-filter','channel-filter']);
  for(const name of ['account','channel'])$(name+'-filter-caption').className='';
  const filterCount=[$('account').value,$('channel').value,...(detailed?[$('state').value]:[])].filter(Boolean).length;
  $('glance-filter-count').hidden=!filterCount;$('glance-filter-count').textContent=String(filterCount);
  $('glance-filter-toggle').setAttribute('aria-label',filterCount?'Filters, '+filterCount+' active':'Filters');

  $('glance-filter-menu').hidden=false;
  const visibility={'actuals-panel':glance||report,'glance-panel':glance,'expenses-panel':report&&categoryExpanded,'cashflow-panel':report,'summary-panel':false,'spending-breakdown':report,'daily-panel':glance,'review-panel':review,'transactions-panel':report,'merchant-categories':review&&!!sync.merchant_categories?.length};
  Object.entries(visibility).forEach(([id,visible])=>$(id).hidden=!visible);
  $('transaction-type').value=review?'all':view;
  $('transaction-category').disabled=view!=='spending';
  renderCategoryExpansion();
  mount(review?'review-transaction-section':'transactions-panel',['review-transactions','transaction-pagination','transaction-detail']);
  $('review-source-section').hidden=!sourceReviewItems.length;
  $('view-note').hidden=review||!$('view-note').textContent;
  $('transaction-table').hidden=review;
  $('review-transactions').hidden=!review;
  $('page-size').disabled=false;
  $('page-size-control').hidden=review;
  $('movement-views').hidden=!report;
  ['glance','report'].forEach(name=>$('tab-'+name).setAttribute('aria-pressed',String(name===screen)));
  $('view-review').setAttribute('aria-pressed',String(review));
  $('report-title').textContent=glance?'At a glance':report?'Report':'Review';
}

function renderGlance(rows,fmt) {
  const recent=rows.filter(r=>eligible(r)&&Number.isSafeInteger(r.amount_minor)).sort((a,b)=>b.date.localeCompare(a.date)).slice(0,5);
  $('glance-activity').replaceChildren(...recent.map(r=>{
    const item=node('li'),button=node('button',undefined,'glance-transaction');button.type='button';
    const icon=node('span',(r.merchant||'?').slice(0,1).toUpperCase(),'glance-merchant-icon');icon.setAttribute('aria-hidden','true');
    const description=node('span',undefined,'glance-description');
    description.append(node('strong',r.merchant),node('span',[r.category,prettyDate(r.date)].join(' · '),'muted'));
    button.append(icon,description,amountDisplay(r,fmt,'span','glance-amount'));
    button.setAttribute('aria-label','Details for '+r.merchant+' on '+r.date);
    button.addEventListener('click',()=>{openReportTransactions();showDetail(r,$('tab-glance'));$('transaction-detail').scrollIntoView?.({block:'start'});});
    item.append(button);return item;
  }));
  if(!recent.length)$('glance-activity').append(node('li','No transactions for these filters.','glance-empty muted'));
  const count=rows.filter(needsReview).length;
  const issues=[count?count+' transaction'+(count===1?'':'s'):'',sourceReviewItems.length?sourceReviewItems.length+' source issue'+(sourceReviewItems.length===1?'':'s'):''].filter(Boolean);
  $('glance-review').textContent=issues.length?issues.join(' and ')+' to review ↗':'No items needing review';
  $('glance-review').disabled=!count&&!sourceReviewItems.length;
}


function renderCategoryExpansion() {
  $('categories').hidden=false;
  $('expenses-panel').hidden=screen!=='report'||!categoryExpanded;
  $('expenses-title').textContent=categoryExpanded?'Show less':'Show more';
  $('expenses-title').setAttribute('aria-expanded',String(categoryExpanded));
}
function renderCategoryChips(rows) {
  const labels=[...new Set(rows.filter(r=>spending(r)&&BigInt(r.amount_minor)>0n).map(r=>r.category))].sort();
  const selection=categorySelection?.length===1?categorySelection[0]:'';
  const choices=[...new Set([...labels,...(categorySelection||[])])].sort();
  $('transaction-category').replaceChildren(...[['','All categories'],...choices.map(c=>[c,c])].map(([value,label])=>{const o=node('option',label);o.value=value;return o;}));
  $('transaction-category').value=selection;
}
// Chart values use the same confirmed-first selection as actuals.
function renderDaily(rows,fmt) {
  const basis=preferredAmounts(rows,spending),state=basis.provisional?'provisional':'confirmed';
  const {start,end}=observedPeriod(rows);
  const amounts=new Map();
  basis.rows.filter(r=>BigInt(r.amount_minor)>0n).forEach(r=>amounts.set(r.date,(amounts.get(r.date)||0n)+BigInt(r.amount_minor)));
  const days=[];
  if(start&&end&&start<=end) for(let t=Date.parse(start+'T00:00:00Z');t<=Date.parse(end+'T00:00:00Z')&&days.length<3660;t+=86400000){
    const date=new Date(t).toISOString().slice(0,10);days.push({date,value:amounts.get(date)||0n});
  }
  const max=days.reduce((v,d)=>d.value>v?d.value:v,0n);
  const peak=days.find(d=>d.value===max&&max>0n);
  $('daily-chart').setAttribute('aria-label','Daily '+state+' purchases');
  $('daily-chart').replaceChildren(...days.map(d=>{
    const b=node('button',undefined,'daily-bar'+(d===peak?' peak':''));b.type='button';
    b.style.height=(max>0n?Math.max(1,Number(d.value*10000n/max)/100):1)+'%';
    const tip=prettyDate(d.date)+': '+fmt(d.value)+' '+state+' purchases';chartTooltip(b,tip);
    return b;
  }));
  $('daily-labels').replaceChildren(...[...new Set([start,end].filter(Boolean))].map(d=>node('span',prettyDate(d))));

}

function observedPeriod(rows) {
  const dates=rows.filter(eligible).map(r=>r.date).sort();
  const bounds=[effectiveMonth()?effectiveMonth()+'-01':'',screen==='glance'?'':$('from').value].filter(Boolean).sort();
  return {start:bounds.at(-1)||dates[0],end:dates.at(-1)};
}
