import { initializeReportDesign } from './report-design.js';
'use strict';
var data = JSON.parse(document.getElementById("data").textContent);
var $ = (id) => document.getElementById(id);
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
var isTransfer = (r) => r.excluded_from_spending === true;
var unverifiedTransferOut = (r) => r.kind === "transfer_out" && !isTransfer(r);
var eligible = (r) => !r.blocked && !r.suppressed && ["imported", "posted", "provisional", "draft"].includes(r.status);
var confirmed = (r) => ["imported", "posted"].includes(r.status);
var spending = (r) => !isTransfer(r) && spendKinds.has(r.kind);
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
    reasons.push("The merchant has not been assigned a spending category.");
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
[...new Set(data.rows.map((r) => r.date.slice(0, 7)))].sort().reverse().forEach((m) => option("month", m, prettyMonth(m)));
var accounts = new Map(data.rows.map((r) => [r.account_key, r.account]));
accounts.forEach((label, key) => option("account", key, label));
$("from").value = data.from;
$("to").value = data.to;
var views = ["all", "spending", "incoming", "transfers", "review"];
var sortKeys = ["date", "merchant", "category", "kind", "amount_minor", "account"];
var view = "spending";
var screen = "report";
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
function showDetail(r, trigger) {
  detailTrigger = trigger;
  const statement = data.statements.find((s) => s.id === r.statement), sources = transactionSources(r), fmt = (n) => money(n, r.exponent, r.currency);
  const fields = [["Date", r.date], ["Merchant", r.merchant], ["Category", r.category], ["Movement", r.kind.replaceAll("_", " ")], ["Amount", fmt(r.amount_minor)], ["Account", r.account], ["State", stateLabel(r)], ["Spending treatment", !eligible(r) ? "Excluded while financial checks are unresolved" : isTransfer(r) ? "Own-account transfer · Excluded" : unverifiedTransferOut(r) ? "Outgoing movement · Transfer ownership needs review" : spending(r) ? "Included in spending" : ["payment", "repayment"].includes(r.kind) ? "Repayment · Excluded from spending" : "Incoming money · Excluded from spending"], ["Payment type", r.channel ?? "Not provided"], ["Source record", r.statement || "Unavailable"], ["Source page / row", (r.page ?? "Unavailable") + " / " + (r.row ?? "Unavailable")]];
  if (r.reference) fields.push(['Reference', r.reference]);
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
function filteredRows() {
  const code = $("currency").value, month = $("month").value, account = $("account").value, state = $("state").value, query = $("search").value.trim().toLowerCase();
  return data.rows.filter((r) => (!$("channel").value || r.channel === $("channel").value) && (!code || r.currency === code || (!r.currency && ["review", "all"].includes(view))) && (!month || r.date.startsWith(month)) && (!account || r.account_key === account) && (!state ? (view === "all" || !r.suppressed) : state === "unresolved" ? r.blocked || r.status === "needs_review" : r.status === state) && (!$("from").value || r.date >= $("from").value) && (!$("to").value || r.date <= $("to").value) && (!query || [r.merchant, r.category, r.account, r.kind, r.reference || "", stateLabel(r), ...(view === "review" ? reviewReasons(r) : [])].join(" ").toLowerCase().includes(query)));
}
var isEarning = (r) => eligible(r) && !isTransfer(r) && BigInt(r.amount_minor) < 0n && !spendKinds.has(r.kind) && !["payment", "repayment"].includes(r.kind);
var isCardPayment = (r) => eligible(r) && !isTransfer(r) && ["payment"].includes(r.kind) && BigInt(r.amount_minor) < 0n;
function renderOverview(rows, fmt) {
  const inRows = rows.filter(isEarning), outRows = rows.filter((r) => eligible(r) && spending(r));
  const moneyIn = -sum(inRows), spent = sum(outRows), net = moneyIn - spent, cardPaid = -sum(rows.filter(isCardPayment));
  const kept = moneyIn > 0n ? Number(net * 1000n / moneyIn) / 10 : null;
  const ovCard = (label, value, hint, cls) => {
    const c = node("div", undefined, "ov-card" + (cls ? " " + cls : ""));
    c.append(node("div", label, "label"), node("div", value, "value"));
    if (hint) c.append(node("div", hint, "muted"));
    return c;
  };
  $("ov-cards").replaceChildren(
    ovCard("Money in", fmt(moneyIn), inRows.length + " credits", "in"),
    ovCard("Spent", fmt(spent), outRows.length + " transactions · net of refunds", "out"),
    ovCard("Net", (net > 0n ? "+" : "") + fmt(net), kept === null ? "No money in for this selection" : net >= 0n ? "Kept " + kept.toFixed(1) + "% of money in" : "Spent more than came in", net >= 0n ? "pos" : "neg"),
    ovCard("Card bills paid", fmt(cardPaid), "Excluded from spending", "")
  );
  const month = $("month").value, dates = rows.map((r) => r.date).sort();
  $("ov-scope").textContent = month ? prettyMonth(month) : dates.length ? prettyDate(dates[0]) + " to " + prettyDate(dates[dates.length - 1]) : "No transactions in this selection";
  const byMonth = new Map;
  inRows.forEach((r) => { const k = r.date.slice(0, 7), v = byMonth.get(k) || [0n, 0n]; v[0] -= BigInt(r.amount_minor); byMonth.set(k, v); });
  outRows.forEach((r) => { const k = r.date.slice(0, 7), v = byMonth.get(k) || [0n, 0n]; v[1] += BigInt(r.amount_minor); byMonth.set(k, v); });
  let max = 0n;
  byMonth.forEach((v) => { if (v[0] > max) max = v[0]; if (v[1] > max) max = v[1]; });
  const pct = (x) => (max > 0n && x > 0n ? Math.max(1, Number(x * 1000n / max) / 10) : 0) + "%";
  $("ov-months").replaceChildren(...[...byMonth].sort((a, b) => b[0].localeCompare(a[0])).map(([m, [i, o]]) => {
    const tr = node("tr"), n = i - o;
    tr.append(node("td", prettyMonth(m)), node("td", fmt(i), "num"), node("td", fmt(o), "num"), node("td", (n > 0n ? "+" : "") + fmt(n), "num " + (n >= 0n ? "pos" : "neg")));
    const bars = node("td", undefined, "ov-bars"), b1 = node("div", undefined, "mini in"), b2 = node("div", undefined, "mini out");
    b1.style.width = pct(i); b2.style.width = pct(o);
    b1.title = "Money in " + fmt(i); b2.title = "Spent " + fmt(o);
    bars.append(b1, b2);
    tr.append(bars);
    return tr;
  }));
  if (!byMonth.size) {
    const tr = node("tr"), td = node("td", "No money in or spending for this selection.", "muted");
    td.colSpan = 5; tr.append(td); $("ov-months").append(tr);
  }
  $("ov-note").textContent = "Money in excludes refunds, repayments and own transfers. Spending includes provisional records and deducts refunds.";
}
function update() {
  const filtered = filteredRows(), code = $("currency").value, exp = filtered[0]?.exponent ?? data.rows.find((r) => r.currency === code)?.exponent ?? data.statements.find((s)=>s.currency===code)?.exponent ?? null, fmt = (n) => money(n, exp, code || "");
  const visible = filtered.filter((r) => view === "all" ? true : view === "review" ? needsReview(r) : eligible(r) && (view === "spending" ? spending(r) : view === "transfers" ? isTransfer(r) : !isTransfer(r) && r.amount_minor < 0));
  renderOverview(filtered, fmt);
  const included = visible.filter(eligible), saved = included.filter(confirmed), provisional = included.filter((r) => !confirmed(r));
  const title = { all: "All transactions", spending: "Spending overview", incoming: "Incoming money", transfers: "Own-account transfers", review: "Review" };
  $("view-title").textContent = title[view];
  $("table-title").className = ["transactions", "review"].includes(screen) ? "sr-only" : "";
  $("table-title").textContent = { all: "All transactions", spending: "Transactions", incoming: "Transactions", transfers: "Transactions", review: "Transactions to review" }[view];
  $("spending-breakdown").hidden = view !== "spending";
  $("review-panel").hidden = view !== "review";
  $("monthly-panel").hidden = view !== "spending";
  $("report-title").textContent = {all:"All transactions",spending:"Spending report",incoming:"Incoming money",transfers:"Transfers",review:"Review"}[view];
  $("report-period").textContent = [$("month").value ? prettyMonth($("month").value) : [$("from").value, $("to").value].filter(Boolean).map(prettyDate).join(" – "), currencyLabel(code)].filter(Boolean).join(" · ");
  const notes = { all: "", spending: "Includes provisional records; refunds deducted.", incoming: "Includes refunds and repayments; transfers excluded.", transfers: "Both account legs; excluded from spending.", review: "Blocked rows are excluded from totals; category decisions are included." };
  $("view-note").textContent = notes[view];
  $("view-note").hidden = !notes[view];
  if (view === "spending")
    cards([["Confirmed net", fmt(sum(saved)), ""], ["Provisional net", fmt(sum(provisional)), ""], ["Estimated net", fmt(sum(included)), ""], ["Refunds", fmt(-sum(included, (r) => r.amount_minor < 0)), ""]]);
  else if (view === "incoming")
    cards([["Confirmed money in", fmt(-sum(saved)), ""], ["Provisional money in", fmt(-sum(provisional)), ""], ["Total money in", fmt(-sum(included)), ""], ["Transactions", String(visible.length), ""]]);
  else if (view === "transfers")
    cards([["Money out", fmt(sum(included, (r) => r.amount_minor > 0)), ""], ["Money in", fmt(-sum(included, (r) => r.amount_minor < 0)), ""], ["Provisional legs", String(provisional.length), ""], ["Transactions", String(visible.length), ""]]);
  else if (view === 'all')
    cards([["Source occurrences", String(visible.length), ""], ["Repayments", String(visible.filter(r => ['payment','repayment'].includes(r.kind)).length), "Excluded from spending"], ["Review rows", String(visible.filter(needsReview).length), ""], ["Duplicate links", String(visible.filter(r => r.suppressed).length), "Excluded from totals"]]);
  else
    cards([["Transactions to review", String(visible.length), ""], ["Excluded records", String(visible.filter((r) => !eligible(r)).length), ""], ["Category decisions", String(visible.filter((r) => eligible(r) && r.category === "Other").length), ""], ["Source review items", String(sourceReviewItems.length), "Across all sources"]]);
  const category = new Map;
  included.filter((r) => spending(r) && r.amount_minor > 0).forEach((r) => category.set(r.category, (category.get(r.category) || 0n) + BigInt(r.amount_minor)));
  const gross = sum(included, (r) => spending(r) && r.amount_minor > 0), cats = [...category].sort((a, b) => a[1] > b[1] ? -1 : a[1] < b[1] ? 1 : 0);
  const reportBasis = preferredAmounts(filtered, spending), reportRows = reportBasis.rows;
  if (screen === 'report') {
    const reportCategory = new Map();
    reportRows.filter(r=>spending(r) && BigInt(r.amount_minor)>0n).forEach(r=>reportCategory.set(r.category,(reportCategory.get(r.category)||0n)+BigInt(r.amount_minor)));
    const actualCats=[...reportCategory].sort((a,b)=>a[1]>b[1]?-1:a[1]<b[1]?1:a[0].localeCompare(b[0]));
    renderCategoryVisuals(actualCats, sum(reportRows,r=>spending(r)&&BigInt(r.amount_minor)>0n), fmt, reportBasis.provisional);
  } else renderCategoryVisuals(cats, gross, fmt);
  renderActuals(filtered, fmt);
  renderDaily(filtered, fmt);
  renderCategoryChips(included);
  const monthly = new Map;
  included.filter(spending).forEach((r) => {
    const key = r.date.slice(0, 7), v = monthly.get(key) || [0n, 0n];
    v[confirmed(r) ? 0 : 1] += BigInt(r.amount_minor);
    monthly.set(key, v);
  });
  $("months").replaceChildren(...[...monthly].sort((a, b) => b[0].localeCompare(a[0])).map(([m, v]) => {
    const tr = node("tr");
    [prettyMonth(m), fmt(v[0]), fmt(v[1])].forEach((x, i) => tr.append(node("td", x, i ? "num" : undefined)));
    return tr;
  }));
  const tableRows = view === "spending" && categorySelection ? visible.filter(r => categorySelection.includes(r.category)) : visible;
  $("category-selection").hidden = !categorySelection || view !== "spending";
  $("category-selection-label").textContent = categorySelection ? categorySelection.length === 1 ? categorySelection[0] : "Other categories" : "";
  const sorted = [...tableRows].sort((a, b) => {
    if (sortKey === 'amount_minor' && (a.amount_minor == null || b.amount_minor == null))
      return a.amount_minor == null ? b.amount_minor == null ? 0 : 1 : -1;
    const x = sortKey === "amount_minor" ? BigInt(a.amount_minor) : String(a[sortKey]), y = sortKey === "amount_minor" ? BigInt(b.amount_minor) : String(b[sortKey]);
    return (typeof x === "bigint" ? x > y ? 1 : x < y ? -1 : 0 : x.localeCompare(y)) * direction;
  });
  const size = screen === "report" ? 10 : Number($("page-size").value) || 25, pages = Math.max(1, Math.ceil(sorted.length / size));
  page = Math.min(page, pages - 1);
  $("transactions").replaceChildren(...sorted.slice(page * size, (page + 1) * size).map((r) => {
    const tr = node("tr");
    const amount = amountDisplay(r, fmt, 'td', 'num' + (r.amount_minor != null && BigInt(r.amount_minor) < 0n ? ' credit' : ''));
    const merchant = node("td", undefined, "merchant");
    merchant.append(node("span", r.merchant), transactionSourceLink(r));
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
var coverageStatements = data.statements.filter((s) => !s.record_type || ["statement", "bank_statement"].includes(s.record_type));
var localTime = (value) => new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "short", ...sync.timezone ? { timeZone: sync.timezone } : {} }).format(new Date(value));
if (sync.merchant_categories?.length) {
  $("merchant-categories").hidden = false;
  $("merchant-list").replaceChildren(...sync.merchant_categories.map((merchant) => {
    const item = node("div", undefined, "source");
    item.append(node("strong", merchant.merchant), node("div", merchant.category, "muted"));
    return item;
  }));
}
$("review-summary").textContent = "Source issues · " + sourceReviewItems.length;
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
views.forEach((name) => $("view-" + name).addEventListener("click", () => {
  view = name;
  if (name === 'all') {
    ['month', 'account', 'state', 'from', 'to', 'search', 'channel'].forEach(id => $(id).value = '');
  }
  screen = name === "review" ? "review" : "transactions";
  categorySelection = null;
  page = 0;
  closeDetail();
  views.forEach((v) => $("view-" + v).setAttribute("aria-pressed", String(v === view)));
  update();
}));
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
['report','transactions'].forEach(name=>$('tab-'+name).addEventListener('click',()=>{
  screen=name;if(view==='review')view='spending';page=0;categorySelection=null;closeDetail();update();
}));
reportDesign = initializeReportDesign();
update();

function selectCategory(labels) {
  screen = "transactions";
  view = "spending";
  categorySelection = labels;
  page = 0;
  closeDetail();
  update();
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
  $('categories').replaceChildren(...groups.map(g=>{
    const button=node('button',undefined,'category-choice'),swatch=node('span',undefined,'category-swatch');
    button.type='button';swatch.style.background=g.color;
    button.setAttribute('aria-pressed',String(!!categorySelection && g.labels.every(c=>categorySelection.includes(c))));
    button.setAttribute('aria-label',g.label+': '+fmt(g.value)+'; filter transactions');
    button.title=fmt(g.value);
    const pct=percent(g.value);button.append(swatch,node('span',g.label,'category-name'),node('strong',fmt(g.value),'category-amount'),node('span',pct>0&&pct<.1?'<0.1%':pct.toFixed(1)+'%','pct'));
    button.addEventListener('click',()=>selectCategory(g.labels));return button;
  }));

}

// Actuals are computed in integer minor units, independently of transaction subviews.
function renderActuals(rows,fmt) {
  const basis=preferredAmounts(rows,spending),incomeBasis=preferredAmounts(rows,isEarning);
  const expenses=basis.rows;
  const purchases=sum(expenses,r=>BigInt(r.amount_minor)>0n),refunds=-sum(expenses,r=>BigInt(r.amount_minor)<0n);
  const incoming=-sum(incomeBasis.rows),net=purchases-refunds;
  const pendingRows=rows.filter(r=>eligible(r)&&!confirmed(r)&&spending(r)),pending=sum(pendingRows);
  const label=(name,provisional=basis.provisional)=>provisional?'Provisional '+name[0].toLowerCase()+name.slice(1):name;
  const values=[['Period',$('month').value?prettyMonth($('month').value):[$('from').value,$('to').value].filter(Boolean).map(prettyDate).join(' – ')||'Selected records'],[label('Money in',incomeBasis.provisional),fmt(incoming)],[label('Purchases'),fmt(purchases)],[label('Refunds'),fmt(refunds)],[label('Net spend'),fmt(net)]];
  if(!basis.provisional)values.push(['Provisional net',fmt(pending)]);
  $('actuals-summary').replaceChildren(...values.map(([label,value])=>{const tr=node('tr');tr.append(node('th',label),node('td',value,'num'));return tr;}));
  $('hero-label').textContent=basis.provisional?'Provisional net spend':expenses.length?'Confirmed net spend':'Net spend';
  $('hero-total').textContent=fmt(net);
  $('hero-caption').textContent=expenses.length+(basis.provisional?' provisional':'')+' transaction'+(expenses.length===1?'':'s');
  $('hero-provisional').hidden=basis.provisional||!pendingRows.length;
  $('hero-provisional').textContent=!basis.provisional&&pendingRows.length?'Provisional net '+fmt(pending):'';
  const actualCard=(label,value,hint)=>{const e=node('div',undefined,'hero-card');e.append(node('span',label,'label'),node('strong',value,'value'));if(hint)e.append(node('span',hint,'muted'));return e;};
  const {start,end}=observedPeriod(rows);
  const days=start&&end&&start<=end?Math.floor((Date.parse(end+'T00:00:00Z')-Date.parse(start+'T00:00:00Z'))/86400000)+1:0;
  $('hero-metrics').replaceChildren(actualCard(label('Money in',incomeBasis.provisional),fmt(incoming),'Excludes refunds, repayments and own transfers'),actualCard(label('Net cash flow',basis.provisional||incomeBasis.provisional),fmt(incoming-net),''),actualCard(label('Daily average'),fmt(days?net/BigInt(days):0n),days?'Over '+days+' observed day'+(days===1?'':'s'):''));
  $('actuals-note').textContent=(basis.provisional?'Provisional spending shown because no confirmed spending is available for this selection.':'Confirmed spending shown when available.')+(incomeBasis.provisional?' Money in is provisional because no confirmed money in is available.':'')+' Money in is not necessarily income; it excludes refunds, repayments and own transfers.';
  $('expenses-title').textContent=basis.provisional?'Provisional expenses by category':'Expenses by category';
  const categories=new Map();
  expenses.forEach(r=>{const v=categories.get(r.category)||[0n,0n];v[0]+=BigInt(r.amount_minor);if(BigInt(r.amount_minor)>0n)v[1]+=BigInt(r.amount_minor);categories.set(r.category,v);});
  $('actual-expenses').replaceChildren(...[...categories].sort((a,b)=>a[1][0]>b[1][0]?-1:a[1][0]<b[1][0]?1:a[0].localeCompare(b[0])).map(([label,[value,gross]])=>{
    const tr=node('tr'),td=node('td'),bar=node('div',undefined,'actual-bar');
    const share=purchases>0n?Number(gross*10000n/purchases)/100:0;
    bar.style.width=share+'%';bar.setAttribute('aria-hidden','true');td.append(node('span',share.toFixed(1)+'%','muted'),bar);
    tr.append(node('td',label),node('td',fmt(value),'num'),td);return tr;
  }));
  if(!categories.size){const tr=node('tr'),td=node('td','No confirmed expenses in this selection.','muted');td.colSpan=3;tr.append(td);$('actual-expenses').append(tr);}
  const total=node('tr',undefined,'actual-total');total.append(node('th','Total'),node('td',fmt(net),'num'),node('td',''));$('actual-expenses').append(total);
}
function routeScreen() {
  const report=screen==='report',transactions=screen==='transactions',review=screen==='review';
  const visibility={'actuals-panel':report,'expenses-panel':report,'summary-panel':transactions,'spending-breakdown':report,'daily-panel':report,'review-panel':review&&sourceReviewItems.length>0,'transactions-panel':report||transactions||(review&&(reviewCount>sourceReviewItems.length||!sourceReviewItems.length)),'monthly-panel':transactions&&view==='spending','overview':transactions,'merchant-categories':review&&!!sync.merchant_categories?.length};
  Object.entries(visibility).forEach(([id,visible])=>$(id).hidden=!visible);
  $('category-chips').hidden=review||view!=='spending';
  $('transaction-table').hidden=review;
  $('review-transactions').hidden=!review;
  $('page-size').disabled=report;
  $('page-size-control').hidden=report;
  $('movement-views').hidden=!transactions;
  ['report','transactions'].forEach(name=>$('tab-'+name).setAttribute('aria-pressed',String(name===screen)));
  views.forEach(name=>$('view-'+name).setAttribute('aria-pressed',String(name==='review'?review:transactions&&view===name)));
  const month=$('month').value || (data.from?.slice(0,7)===data.to?.slice(0,7)?data.from.slice(0,7):'');
  $('report-title').textContent=report?(month?prettyMonth(month)+' · Monthly report':'Monthly report'):{transactions:'Transactions',review:'Review'}[screen];
  const lastDate=data.rows.filter(r=>eligible(r)&&(!data.from||r.date>=data.from)&&(!data.to||r.date<=data.to)&&(!$('month').value||r.date.startsWith($('month').value))).map(r=>r.date).sort().at(-1);
  const generated=data.generated?.slice(0,10);
  const incomplete=generated&&data.to&&data.to.slice(0,7)===generated.slice(0,7);
  const statementCount=coverageStatements.filter(s=>(!data.to||s.period.slice(0,10)<=data.to)&&(!data.from||s.period.slice(-10)>=data.from)).length;
  $('coverage-note').textContent=[incomplete?'Month in progress':null,!generated?'Preview':null,lastDate?'Latest counted transaction '+prettyDate(lastDate):'No counted transactions in this period',statementCount+(statementCount===1?' statement overlaps':' statements overlap')+' this period; coverage may be incomplete',sync.pending_sources?.length?sync.pending_sources.length+' source item'+(sync.pending_sources.length===1?'':'s')+' pending':null].filter(Boolean).join(' · ');
}


function renderCategoryChips(rows) {
  const labels=[...new Set(rows.filter(r=>spending(r)&&BigInt(r.amount_minor)>0n).map(r=>r.category))].sort();
  $('category-chips').replaceChildren(...['All',...labels].map(label=>{
    const b=node('button',label);b.type='button';
    b.setAttribute('aria-pressed',String(label==='All'?!categorySelection:categorySelection?.includes(label)||false));
    b.addEventListener('click',()=>{categorySelection=label==='All'?null:[label];page=0;closeDetail();update();});return b;
  }));
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
  const total=days.reduce((v,d)=>v+d.value,0n),max=days.reduce((v,d)=>d.value>v?d.value:v,0n),average=days.length?total/BigInt(days.length):0n;
  const peak=days.find(d=>d.value===max&&max>0n);
  $('daily-average').textContent=(basis.provisional?'Provisional average ':'Average ')+fmt(average)+' / day';
  $('daily-peak').textContent=peak?(basis.provisional?'Largest provisional day · ':'Largest day · ')+prettyDate(peak.date)+' · '+fmt(peak.value):'No '+state+' purchases for this selection';
  $('daily-chart').setAttribute('aria-label','Daily '+state+' purchases');
  $('daily-chart').replaceChildren(...days.map(d=>{
    const b=node('button',undefined,'daily-bar'+(d===peak?' peak':''));b.type='button';
    b.style.height=(max>0n?Math.max(1,Number(d.value*10000n/max)/100):1)+'%';
    const tip=prettyDate(d.date)+': '+fmt(d.value)+' '+state+' purchases';b.title=tip;b.setAttribute('aria-label',tip);
    b.addEventListener('click',()=>{$('daily-peak').textContent=tip;});return b;
  }));
  $('daily-labels').replaceChildren(...[...new Set([start,end].filter(Boolean))].map(d=>node('span',prettyDate(d))));
  const weekend=days.reduce((v,d)=>[0,6].includes(new Date(d.date+'T00:00:00Z').getUTCDay())?v+d.value:v,0n);
  const fact=(label,value)=>{const n=node('div');n.append(node('span',label,'muted'),node('strong',value));return n;};
  $('daily-facts').replaceChildren(fact('Days observed',String(days.length)),fact('Days without recorded purchases',String(days.filter(d=>d.value===0n).length)),fact('Weekend share',total>0n?(Number(weekend*1000n/total)/10).toFixed(1)+'%':'—'));
  $('daily-note').textContent=(basis.provisional?'Provisional purchases shown because no confirmed spending is available. ':'')+'Missing sources can leave gaps; an empty day does not establish no spending.';
}

function observedPeriod(rows) {
  const dates=rows.filter(eligible).map(r=>r.date).sort();
  const bounds=[$('month').value?$('month').value+'-01':'',$('from').value].filter(Boolean).sort();
  return {start:bounds.at(-1)||dates[0],end:dates.at(-1)};
}
