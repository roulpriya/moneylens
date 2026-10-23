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
function money(amount, exp, code) {
  amount = BigInt(amount);
  const negative = amount < 0n;
  if (negative)
    amount = -amount;
  const scale = 10n ** BigInt(exp), whole = (amount / scale).toString().replace(/\B(?=(\d{3})+(?!\d))/g, ",");
  return (negative ? "−" : "") + code + " " + whole + (exp ? "." + (amount % scale).toString().padStart(exp, "0") : "");
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
var spendKinds = new Set(["purchase", "bank_debit", "fee", "interest", "cash_advance", "adjustment_debit", "upi_debit", "refund", "adjustment_credit"]);
var isTransfer = (r) => r.excluded_from_spending || ["transfer_in", "transfer_out"].includes(r.kind);
var eligible = (r) => !r.blocked && !r.suppressed && ["imported", "posted", "provisional", "draft"].includes(r.status);
var confirmed = (r) => ["imported", "posted"].includes(r.status);
var spending = (r) => !isTransfer(r) && spendKinds.has(r.kind);
var needsReview = (r) => !r.suppressed && (r.blocked || ["draft", "needs_review"].includes(r.status) || r.kind === "unknown" || spending(r) && r.amount_minor > 0 && r.category === "Other");
function stateLabel(r) {
  return r.suppressed ? "Reconciled duplicate · Excluded" : r.blocked ? "Needs review · Excluded" : r.status === "needs_review" ? "Needs review · Excluded" : r.status === "draft" ? "Provisional · Staged statement" : r.status === "provisional" ? "Provisional · Card alert" : r.status === "posted" ? "Confirmed · Bank alert" : r.status === "imported" ? "Confirmed · Saved statement" : r.status;
}
var currencies = [...new Set([...data.rows, ...data.statements].map((r) => r.currency))].sort();
currencies.forEach((c) => option("currency", c, c));
if (!currencies.length)
  option("currency", "", "No transactions");
[...new Set(data.rows.map((r) => r.date.slice(0, 7)))].sort().reverse().forEach((m) => option("month", m, prettyMonth(m)));
var accounts = new Map(data.rows.map((r) => [r.account_key, r.account]));
accounts.forEach((label, key) => option("account", key, label));
$("from").value = data.from;
$("to").value = data.to;
var views = ["spending", "incoming", "transfers", "review"];
var sortKeys = ["date", "merchant", "category", "kind", "amount_minor", "account", "status"];
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
function showDetail(r, trigger) {
  detailTrigger = trigger;
  const statement = data.statements.find((s) => s.id === r.statement), fmt = (n) => money(n, r.exponent, r.currency);
  const fields = [["Date", r.date], ["Merchant", r.merchant], ["Category", r.category], ["Movement", r.kind.replaceAll("_", " ")], ["Amount", fmt(r.amount_minor)], ["Account", r.account], ["State", stateLabel(r)], ["Spending treatment", !eligible(r) ? "Excluded while financial checks are unresolved" : isTransfer(r) ? "Own-account transfer · Excluded" : spending(r) ? "Included in spending" : "Incoming money · Excluded from spending"], ["Payment type", r.channel], ["Reference", r.reference || "Unavailable"], ["Source record", r.statement || "Unavailable"], ["Source page / row", (r.page ?? "Unavailable") + " / " + (r.row ?? "Unavailable")]];
  if (r.transfer_evidence)
    fields.push(["Transfer evidence", r.transfer_evidence]);
  if (statement) {
    fields.push(["Statement period", statement.period]);
    for (const source of statement.sources || [statement.source])
      fields.push(["Gmail source", source.mailbox + " · message " + source.message_id + " · " + (source.filename || "Email body")]);
    fields.push(["Validation issues", (statement.checks.issues || []).join(" · ") || "None"]);
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
    card.append(node("div", label, "label"), node("div", value, "value"), node("div", hint, "muted"));
    card.title = hint;
    return card;
  }));
}
function filteredRows() {
  const code = $("currency").value, month = $("month").value, account = $("account").value, state = $("state").value, query = $("search").value.trim().toLowerCase();
  return data.rows.filter((r) => (!$("channel").value || r.channel === $("channel").value) && (!code || r.currency === code) && (!month || r.date.startsWith(month)) && (!account || r.account_key === account) && (!state ? !r.suppressed : state === "unresolved" ? r.blocked || r.status === "needs_review" : r.status === state) && (!$("from").value || r.date >= $("from").value) && (!$("to").value || r.date <= $("to").value) && (!query || [r.merchant, r.category, r.account, r.kind, r.reference || "", stateLabel(r)].join(" ").toLowerCase().includes(query)));
}
var isEarning = (r) => eligible(r) && !isTransfer(r) && BigInt(r.amount_minor) < 0n && !spendKinds.has(r.kind) && !["payment", "repayment"].includes(r.kind);
var isCardPayment = (r) => eligible(r) && !isTransfer(r) && ["payment"].includes(r.kind) && BigInt(r.amount_minor) < 0n;
function renderOverview(rows, fmt) {
  const inRows = rows.filter(isEarning), outRows = rows.filter((r) => eligible(r) && spending(r));
  const moneyIn = -sum(inRows), spent = sum(outRows), net = moneyIn - spent, cardPaid = -sum(rows.filter(isCardPayment));
  const kept = moneyIn > 0n ? Number(net * 1000n / moneyIn) / 10 : null;
  const ovCard = (label, value, hint, cls) => {
    const c = node("div", undefined, "ov-card" + (cls ? " " + cls : ""));
    c.append(node("div", label, "label"), node("div", value, "value"), node("div", hint, "muted"));
    return c;
  };
  $("ov-cards").replaceChildren(
    ovCard("Money in", fmt(moneyIn), inRows.length + " credits · UPI receipts, bank credits", "in"),
    ovCard("Spent", fmt(spent), outRows.length + " transactions · net of refunds", "out"),
    ovCard("Net", (net > 0n ? "+" : "") + fmt(net), kept === null ? "No money in for this selection" : net >= 0n ? "Kept " + kept.toFixed(1) + "% of money in" : "Spent more than came in", net >= 0n ? "pos" : "neg"),
    ovCard("Card bills paid", fmt(cardPaid), "Not counted again: purchases already in Spent", "")
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
  $("ov-note").textContent = "Money in excludes refunds (already netted from Spent), card bill payments and own-account transfers. Spent includes provisional records. Follows the filters above, whichever tab is open.";
}
function update() {
  const filtered = filteredRows(), code = $("currency").value, exp = filtered[0]?.exponent ?? data.rows.find((r) => r.currency === code)?.exponent ?? 2, fmt = (n) => money(n, exp, code || "");
  const visible = filtered.filter((r) => view === "review" ? needsReview(r) : eligible(r) && (view === "spending" ? spending(r) : view === "transfers" ? isTransfer(r) : !isTransfer(r) && r.amount_minor < 0));
  renderOverview(filtered, fmt);
  const included = visible.filter(eligible), saved = included.filter(confirmed), provisional = included.filter((r) => !confirmed(r));
  const title = { spending: "Spending overview", incoming: "Incoming money", transfers: "Own-account transfers", review: "Review" };
  $("view-title").textContent = title[view];
  $("table-title").textContent = { spending: "Transactions", incoming: "Transactions", transfers: "Transactions", review: "Transactions to review" }[view];
  $("spending-breakdown").hidden = view !== "spending";
  $("review-panel").hidden = view !== "review";
  $("top-categories-panel").hidden = view !== "spending";
  $("monthly-panel").hidden = view !== "spending";
  $("report-title").textContent = {spending:"Spending report",incoming:"Incoming money",transfers:"Transfers",review:"Review"}[view];
  $("report-period").textContent = [$("month").value ? prettyMonth($("month").value) : [$("from").value, $("to").value].filter(Boolean).map(prettyDate).join(" – "), code].filter(Boolean).join(" · ");
  const notes = { spending: "Includes provisional records; refunds deducted.", incoming: "Includes refunds and repayments; transfers excluded.", transfers: "Both account legs; excluded from spending.", review: "Blocked rows excluded. Category-only decisions remain in totals." };
  $("view-note").textContent = notes[view];
  if (view === "spending")
    cards([["Confirmed net", fmt(sum(saved)), "Validated saved records"], ["Provisional net", fmt(sum(provisional)), "Awaiting statement confirmation"], ["Estimated net", fmt(sum(included)), "Confirmed + provisional"], ["Refunds", fmt(-sum(included, (r) => r.amount_minor < 0)), "Already deducted from net spending"]]);
  else if (view === "incoming")
    cards([["Confirmed money in", fmt(-sum(saved)), "Validated saved records"], ["Provisional money in", fmt(-sum(provisional)), "Awaiting statement confirmation"], ["Total money in", fmt(-sum(included)), "Includes refunds and repayments"], ["Transactions", String(visible.length), "Matching incoming records"]]);
  else if (view === "transfers")
    cards([["Money out", fmt(sum(included, (r) => r.amount_minor > 0)), "Own-account transfer legs"], ["Money in", fmt(-sum(included, (r) => r.amount_minor < 0)), "Own-account transfer legs"], ["Provisional legs", String(provisional.length), "Awaiting statement confirmation"], ["Transactions", String(visible.length), "All excluded from spending"]]);
  else
    cards([["Transactions to review", String(visible.length), "Matching current filters"], ["Excluded records", String(visible.filter((r) => !eligible(r)).length), "Not counted in totals"], ["Category decisions", String(visible.filter((r) => eligible(r) && r.category === "Other").length), "Amounts remain in totals"], ["Source review items", String(reviewItems.length), "All sources; independent of filters"]]);
  const category = new Map;
  included.filter((r) => spending(r) && r.amount_minor > 0).forEach((r) => category.set(r.category, (category.get(r.category) || 0n) + BigInt(r.amount_minor)));
  const gross = sum(included, (r) => spending(r) && r.amount_minor > 0), cats = [...category].sort((a, b) => a[1] > b[1] ? -1 : a[1] < b[1] ? 1 : 0);
  const reportRows = filtered.filter(r => eligible(r) && confirmed(r));
  if (screen === 'report') {
    const reportCategory = new Map();
    reportRows.filter(r=>spending(r) && BigInt(r.amount_minor)>0n).forEach(r=>reportCategory.set(r.category,(reportCategory.get(r.category)||0n)+BigInt(r.amount_minor)));
    const actualCats=[...reportCategory].sort((a,b)=>a[1]>b[1]?-1:a[1]<b[1]?1:a[0].localeCompare(b[0]));
    renderCategoryVisuals(actualCats, sum(reportRows,r=>spending(r)&&BigInt(r.amount_minor)>0n), fmt);
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
    const x = sortKey === "amount_minor" ? BigInt(a.amount_minor) : sortKey === "status" ? stateLabel(a) : String(a[sortKey]), y = sortKey === "amount_minor" ? BigInt(b.amount_minor) : sortKey === "status" ? stateLabel(b) : String(b[sortKey]);
    return (typeof x === "bigint" ? x > y ? 1 : x < y ? -1 : 0 : x.localeCompare(y)) * direction;
  });
  const size = screen === "report" ? 10 : Number($("page-size").value) || 25, pages = Math.max(1, Math.ceil(sorted.length / size));
  page = Math.min(page, pages - 1);
  $("transactions").replaceChildren(...sorted.slice(page * size, (page + 1) * size).map((r) => {
    const tr = node("tr");
    const full = stateLabel(r), short = full.split(" · ")[0], tone = r.suppressed ? "dim" : short === "Confirmed" ? "ok" : short === "Provisional" ? "prov" : short === "Needs review" ? "warn" : "dim";
    tr.append(node("td", prettyDate(r.date), "date"), node("td", r.merchant, "merchant"), node("td", r.category), node("td", r.kind.replaceAll("_", " ").replace(/^upi/, "UPI"), "kind"), node("td", fmt(r.amount_minor), "num" + (BigInt(r.amount_minor) < 0n ? " credit" : "")), node("td", r.account, "acct"));
    const stTd = node("td"), pill = node("span", short, "pill " + tone);
    pill.title = full;
    stTd.append(pill);
    tr.append(stTd);
    const td = node("td"), button = node("button", "View", "link");
    button.type = "button";
    button.setAttribute("aria-label", "Details for " + r.merchant + " on " + r.date);
    button.addEventListener("click", () => showDetail(r, button));
    td.append(button);
    tr.append(td);
    return tr;
  }));
  if (!tableRows.length) {
    const tr = node("tr"), td = node("td", "No transactions match these filters.");
    td.colSpan = 8;
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
$("statements").replaceChildren(...coverageStatements.map((s) => {
  const div = node("div", undefined, "source");
  div.append(node("strong", s.account + " · " + s.currency), node("div", s.period + " · " + s.status.replaceAll("_", " "), "muted"));
  return div;
}));
if (!coverageStatements.length)
  $("statements").append(node("p", "No statements staged or imported. Alerts alone do not establish statement coverage.", "muted"));
var localTime = (value) => new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "short", ...sync.timezone ? { timeZone: sync.timezone } : {} }).format(new Date(value));
if (sync.last_run)
  $("diagnostics").append(node("p", sync.last_run.success ? "Latest scan completed for its selected accounts." : "The latest scan was incomplete. Saved history is still available.", sync.last_run.success ? "muted" : "warn"));
else
  $("diagnostics").append(node("p", "No completed scan recorded.", "muted"));
data.statements.forEach((s) => {
  const div = node("div", undefined, "source");
  div.append(node("strong", s.account + " · " + s.id), node("div", (s.sources || [s.source]).map((source) => "Gmail " + source.mailbox + " · message " + source.message_id + " / " + source.filename).join(" · "), "muted"));
  if (s.checks.issues.length)
    div.append(node("div", s.checks.issues.join(" · "), "warn"));
  div.append(node("div", "Passed: " + (s.checks.passed_checks.join(", ") || "No independent checks") + ". Unavailable: " + (s.checks.unavailable_checks.join(", ") || "None") + ".", "muted"));
  if (s.resolution_notes)
    div.append(node("div", "Resolution: " + s.resolution_notes, "muted"));
  $("diagnostics").append(div);
});
if (sync.personal_rules?.length) {
  $("personal-rules").hidden = false;
  $("rule-list").replaceChildren(...sync.personal_rules.map((rule) => {
    const item = node("div", undefined, "source");
    item.append(node("strong", rule.label), node("div", rule.note, "muted"));
    return item;
  }));
}
$("review-summary").textContent = "Source items to review · " + reviewItems.length;
$("review-count").textContent = String(data.rows.filter(needsReview).length + reviewItems.filter(r => r.group !== "Categorization").length);
var groups = new Map;
reviewItems.forEach((r) => {
  const list = groups.get(r.group) || [];
  list.push(r);
  groups.set(r.group, list);
});
groups.forEach((items, name) => {
  const section = node("details", undefined, "source");
  section.append(node("summary", name + " · " + items.length));
  items.forEach((item) => section.append(node("div", (item.account ? item.account + ": " : "") + item.reason + " · Gmail " + (item.mailbox_id ? item.mailbox_id + " / " : "") + item.message_id, "muted")));
  $("review-groups").append(section);
});
if (!reviewItems.length)
  $("review-groups").append(node("p", "No source review items.", "muted"));
$("footer").textContent = data.generated ? "Updated " + localTime(data.generated) : "Template preview · No account data.";
views.forEach((name) => $("view-" + name).addEventListener("click", () => {
  view = name;
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
['report','transactions','statements'].forEach(name=>$('tab-'+name).addEventListener('click',()=>{
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
function renderCategoryVisuals(cats, gross, fmt) {
  const knownColors = {'House & rent':0,Home:0,Shopping:1,Dining:2,Groceries:3,Travel:4,Transport:4,Subscriptions:1,Other:5};
  const allCategories = [...new Set(data.rows.map(r=>r.category))].sort();
  const usedColors = new Set();
  const color = label => {
    let index = (knownColors[label] ?? allCategories.indexOf(label)) % 5;
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
  $('category-chart').setAttribute('aria-label', cats.length ? 'Purchases: '+fmt(gross)+'. '+cats.map(([label,value])=>label+' '+fmt(value)).join('; ') : 'No purchases for these filters');
  $('category-total').textContent = fmt(gross);
  $('categories').replaceChildren(...groups.map(g=>{
    const button=node('button',undefined,'category-choice'),swatch=node('span',undefined,'category-swatch');
    button.type='button';swatch.style.background=g.color;
    button.setAttribute('aria-pressed',String(!!categorySelection && g.labels.every(c=>categorySelection.includes(c))));
    button.setAttribute('aria-label',g.label+': '+fmt(g.value)+'; filter transactions');
    button.title=fmt(g.value);
    const pct=percent(g.value);button.append(swatch,node('span',g.label,'category-name'),node('strong',fmt(g.value),'category-amount'),node('span',pct>0&&pct<.1?'<0.1%':pct.toFixed(1)+'%','pct'));
    button.addEventListener('click',()=>selectCategory(g.labels));return button;
  }));
  $('top-categories').replaceChildren(...cats.slice(0,2).map(([label,value],i)=>{
    const section=node('section',undefined,'top-category'),button=node('button','View →','link');
    section.append(node('span',String(i+1),'rank-label'),node('h3',label),node('div',fmt(value),'value'));
    button.type='button';button.setAttribute('aria-label','View '+label+' transactions');button.addEventListener('click',()=>selectCategory([label]));
    section.append(button);return section;
  }));
  if(!cats.length) {
    $('categories').append(node('p','No purchases for these filters.','muted'));
    $('top-categories').append(node('p','No categories to rank.','muted'));
  }
}

// Actuals are computed in integer minor units, independently of transaction subviews.
function renderActuals(rows,fmt) {
  const confirmedRows=rows.filter(r=>eligible(r)&&confirmed(r));
  const expenses=confirmedRows.filter(spending);
  const purchases=sum(expenses,r=>BigInt(r.amount_minor)>0n),refunds=-sum(expenses,r=>BigInt(r.amount_minor)<0n);
  const incoming=-sum(confirmedRows.filter(isEarning)),net=purchases-refunds;
  const values=[['Period',$('month').value?prettyMonth($('month').value):[$('from').value,$('to').value].filter(Boolean).map(prettyDate).join(' – ')||'Selected records'],['Money in',fmt(incoming)],['Purchases',fmt(purchases)],['Refunds',fmt(refunds)],['Net spend',fmt(net)],['Provisional net',fmt(sum(rows,r=>eligible(r)&&!confirmed(r)&&spending(r)))]];
  $('actuals-summary').replaceChildren(...values.map(([label,value])=>{const tr=node('tr');tr.append(node('th',label),node('td',value,'num'));return tr;}));
  const heroFmt=value=>fmt(value).replace(/^INR /,'₹').replace(/^−INR /,'−₹');
  $('hero-total').textContent=heroFmt(net);
  $('hero-caption').textContent='spent across '+expenses.length+' confirmed transactions · net of refunds';
  const pending=sum(rows,r=>eligible(r)&&!confirmed(r)&&spending(r));
  $('hero-provisional').textContent=pending!==0n?'Provisional net '+fmt(pending)+' · separate from actuals':'No provisional net for this selection';
  const actualCard=(label,value,hint)=>{const e=node('div',undefined,'hero-card');e.append(node('span',label,'label'),node('strong',value,'value'),node('span',hint,'muted'));return e;};
  const {start,end}=observedPeriod(rows);
  const days=start&&end&&start<=end?Math.floor((Date.parse(end+'T00:00:00Z')-Date.parse(start+'T00:00:00Z'))/86400000)+1:0;
  $('hero-metrics').replaceChildren(actualCard('Money in',heroFmt(incoming),'Confirmed credits · excludes refunds and repayments'),actualCard('Net cash flow',heroFmt(incoming-net),'Money in less confirmed spend · partial coverage'),actualCard('Daily average',heroFmt(days?net/BigInt(days):0n),days?'Net spend ÷ '+days+' observed calendar days':'No observed calendar days'));
  $('actuals-note').textContent='Confirmed records only. Provisional net is separate. Money in excludes refunds, repayments and own transfers; it is not necessarily income.';
  const categories=new Map();
  expenses.forEach(r=>{const v=categories.get(r.category)||[0n,0n];v[0]+=BigInt(r.amount_minor);if(BigInt(r.amount_minor)>0n)v[1]+=BigInt(r.amount_minor);categories.set(r.category,v);});
  $('actual-expenses').replaceChildren(...[...categories].sort((a,b)=>a[1][0]>b[1][0]?-1:a[1][0]<b[1][0]?1:a[0].localeCompare(b[0])).map(([label,[value,gross]])=>{
    const tr=node('tr'),td=node('td'),bar=node('div',undefined,'actual-bar');
    const share=purchases>0n?Number(gross*10000n/purchases)/100:0;
    bar.style.width=share+'%';bar.setAttribute('aria-hidden','true');td.append(node('span',share.toFixed(1)+'%','muted'),bar);
    tr.append(node('td',label),node('td',fmt(value),'num'),td);return tr;
  }));
  if(!categories.size){const tr=node('tr'),td=node('td','No confirmed expenses in this selection.','muted');td.colSpan=3;tr.append(td);$('actual-expenses').append(tr);}
  const total=node('tr',undefined,'actual-total');total.append(node('th','Total'),node('td',fmt(net),'num'),node('td','Net of refunds','muted'));$('actual-expenses').append(total);
}
function routeScreen() {
  const report=screen==='report',transactions=screen==='transactions',statements=screen==='statements',review=screen==='review';
  const visibility={'actuals-panel':report,'expenses-panel':report,'summary-panel':transactions||review,'spending-breakdown':report,'top-categories-panel':report,'daily-panel':report,'review-panel':review,'transactions-panel':report||transactions||review,'monthly-panel':transactions&&view==='spending','overview':transactions,'personal-rules':statements&&!!sync.personal_rules?.length,'coverage-panel':report||statements,'sync-issues':statements};
  Object.entries(visibility).forEach(([id,visible])=>$(id).hidden=!visible);
  $('coverage-panel').open=statements;
  $('category-chips').hidden=review||view!=='spending';
  $('page-size').disabled=report;
  $('page-size-control').hidden=report;
  $('movement-views').hidden=!transactions;
  $('primary-filters').hidden=statements;$('secondary-filters').hidden=statements;
  ['report','transactions','statements'].forEach(name=>$('tab-'+name).setAttribute('aria-pressed',String(name===screen)));
  views.forEach(name=>$('view-'+name).setAttribute('aria-pressed',String(name==='review'?review:transactions&&view===name)));
  const month=$('month').value || (data.from?.slice(0,7)===data.to?.slice(0,7)?data.from.slice(0,7):'');
  $('report-title').textContent=report?(month?prettyMonth(month)+' · Monthly report':'Monthly report'):{transactions:'Transactions',statements:'Statements',review:'Review'}[screen];
  const lastDate=data.rows.filter(r=>eligible(r)&&(!data.from||r.date>=data.from)&&(!data.to||r.date<=data.to)&&(!$('month').value||r.date.startsWith($('month').value))).map(r=>r.date).sort().at(-1);
  const generated=data.generated?.slice(0,10),lastSync=sync.last_success?.slice(0,10);
  const incomplete=generated&&data.to&&data.to.slice(0,7)===generated.slice(0,7);
  const statementCount=coverageStatements.filter(s=>(!data.to||s.period.slice(0,10)<=data.to)&&(!data.from||s.period.slice(-10)>=data.from)).length;
  $('coverage-note').textContent=[incomplete?'Month in progress':null,generated?'As of '+prettyDate(generated):'Preview',lastSync?'Last saved refresh '+prettyDate(lastSync):'No completed refresh recorded',lastDate?'Latest eligible transaction '+prettyDate(lastDate):'No eligible transactions in this period',statementCount+' statements overlap this period; coverage may be incomplete',sync.pending_sources?.length?sync.pending_sources.length+' source items pending':null].filter(Boolean).join(' · ');
}


function renderCategoryChips(rows) {
  const labels=[...new Set(rows.filter(r=>spending(r)&&BigInt(r.amount_minor)>0n).map(r=>r.category))].sort();
  $('category-chips').replaceChildren(...['All',...labels].map(label=>{
    const b=node('button',label);b.type='button';
    b.setAttribute('aria-pressed',String(label==='All'?!categorySelection:categorySelection?.includes(label)||false));
    b.addEventListener('click',()=>{categorySelection=label==='All'?null:[label];page=0;closeDetail();update();});return b;
  }));
}
// Chart values use the same confirmed eligibility rules as actuals; no fabricated days or projections.
function renderDaily(rows,fmt) {
  const {start,end}=observedPeriod(rows);
  const amounts=new Map();
  rows.filter(r=>eligible(r)&&confirmed(r)&&spending(r)&&BigInt(r.amount_minor)>0n).forEach(r=>amounts.set(r.date,(amounts.get(r.date)||0n)+BigInt(r.amount_minor)));
  const days=[];
  if(start&&end&&start<=end) for(let t=Date.parse(start+'T00:00:00Z');t<=Date.parse(end+'T00:00:00Z')&&days.length<3660;t+=86400000){
    const date=new Date(t).toISOString().slice(0,10);days.push({date,value:amounts.get(date)||0n});
  }
  const total=days.reduce((v,d)=>v+d.value,0n),max=days.reduce((v,d)=>d.value>v?d.value:v,0n),average=days.length?total/BigInt(days.length):0n;
  const peak=days.find(d=>d.value===max&&max>0n);
  $('daily-average').textContent='Average '+fmt(average)+' / day';
  $('daily-peak').textContent=peak?'Largest day · '+prettyDate(peak.date)+' · '+fmt(peak.value):'No confirmed purchases for this selection';
  $('daily-chart').replaceChildren(...days.map(d=>{
    const b=node('button',undefined,'daily-bar'+(d===peak?' peak':''));b.type='button';
    b.style.height=(max>0n?Math.max(1,Number(d.value*10000n/max)/100):1)+'%';
    const tip=prettyDate(d.date)+': '+fmt(d.value)+' confirmed purchases';b.title=tip;b.setAttribute('aria-label',tip);
    b.addEventListener('click',()=>{$('daily-peak').textContent=tip;});return b;
  }));
  $('daily-labels').replaceChildren(...[start,end].filter(Boolean).map(d=>node('span',prettyDate(d))));
  const weekend=days.reduce((v,d)=>[0,6].includes(new Date(d.date+'T00:00:00Z').getUTCDay())?v+d.value:v,0n);
  const fact=(label,value)=>{const n=node('div');n.append(node('span',label,'muted'),node('strong',value));return n;};
  $('daily-facts').replaceChildren(fact('Days observed',String(days.length)),fact('Days without recorded purchases',String(days.filter(d=>d.value===0n).length)),fact('Weekend share',total>0n?(Number(weekend*1000n/total)/10).toFixed(1)+'%':'—'));
  $('daily-note').textContent='Through the latest eligible transaction. Missing sources can leave gaps; an empty day does not establish no spending.';
}

function observedPeriod(rows) {
  const dates=rows.filter(eligible).map(r=>r.date).sort();
  const bounds=[$('month').value?$('month').value+'-01':'',$('from').value].filter(Boolean).sort();
  return {start:bounds.at(-1)||dates[0],end:dates.at(-1)};
}
