import { test, expect } from 'bun:test';
import { readFileSync } from 'node:fs';
import { runInNewContext } from 'node:vm';
import { pythonCommand } from '../scripts/python-command';

const html = readFileSync(new URL('../skills/automation/assets/report-template.html', import.meta.url), 'utf8');
class Element {
  children: Element[] = [];
  className = ''; value = ''; hidden = true; colSpan = 0; disabled = false;
  style: Record<string,any> = {setProperty(name:string,value:string){this[name]=value;}}; attributes: Record<string,string> = {};
  listeners: Record<string,() => void> = {};
  private text = '';
  constructor(readonly id = '') {}
  set textContent(value: string) { this.text = value; this.children = []; }
  get textContent(): string { return this.text + this.children.map(child => child.textContent).join(''); }
  prepend(...children: Element[]) { this.children.unshift(...children); }
  append(...children: Element[]) {
    if (this.id === 'currency' && !this.children.length && children.length) this.value = children[0].value;
    this.children.push(...children);
  }
  replaceChildren(...children: Element[]) { this.children = []; this.text = ''; this.append(...children); }
  addEventListener(name: string, callback: () => void) { this.listeners[name] = callback; }
  setAttribute(name: string, value: string) { this.attributes[name] = value; }
}
function render(extraRows: Record<string,unknown>[] = [], extraData: Record<string,unknown> = {}) {
  const elements = new Map([...html.matchAll(/\bid="([^"]+)"/g)].map(match => [match[1], new Element(match[1])]));
  const row = { date:'2026-10-01', merchant:'Synthetic merchant', category:'Groceries', page:1, row:'1', statement:'test-statement',
    account:'Synthetic card', account_key:'synthetic', currency:'INR', exponent:2, status:'imported', blocked:false, suppressed:false, channel:'card' };
  const rows = [
    {...row, amount_minor:12000, kind:'purchase'},
    {...row, amount_minor:-1000, kind:'refund'},
    {...row, amount_minor:-5000, kind:'payment'},
    {...row, amount_minor:2000, kind:'debit', channel:'upi', status:'posted', category:'Transport'},
    {...row, amount_minor:-5000, kind:'credit', channel:'upi', status:'posted'},
    {...row, amount_minor:12000, kind:'purchase', status:'matched', suppressed:true},
    ...extraRows.map(extra=>({...row,...extra}))
  ];
  elements.get('data')!.textContent = JSON.stringify({rows, statements:[], from:'', to:'', generated:null, sync:{}, review_items:[{group:'Source checks', reason:'Synthetic review', message_id:'synthetic'}], ...extraData});
  const script = [...html.matchAll(/<script>\s*([\s\S]*?)<\/script>/g)].at(-1)![1];
  runInNewContext(script, {document:{documentElement:new Element('root'), getElementById:(id:string) => elements.get(id), createElement:() => new Element() }});
  return elements;
}
const values = (element: Element) => element.children.map(child => child.children[1].textContent);
const click = (elements: Map<string,Element>, id: string) => elements.get(id)!.listeners.click();
const input = (elements: Map<string,Element>, id: string, value: string) => { const e=elements.get(id)!;e.value=value;e.listeners.input(); };

test('spending separates confirmed, provisional, refunds and excluded records', () => {
  const elements = render([
    {amount_minor:5000,kind:'purchase',status:'provisional'},
    {amount_minor:700,kind:'purchase',status:'draft'},
    {amount_minor:99900,kind:'purchase',blocked:true},
    {amount_minor:99900,kind:'purchase',status:'needs_review'},
    {amount_minor:100000,kind:'transfer_out',excluded_from_spending:true}
  ]);
  expect(values(elements.get('metrics')!)).toEqual(['INR 130.00','INR 57.00','INR 187.00','INR 10.00']);
  expect(elements.get('transactions')!.children).toHaveLength(5);
  expect(elements.get('transactions')!.children[0].children).toHaveLength(7);
  expect(elements.get('months')!.textContent).toContain('INR 57.00');
  click(elements,'view-incoming');
  expect(values(elements.get('metrics')!)).toEqual(['INR 110.00','INR 0.00','INR 110.00','3']);
  expect(elements.get('transactions')!.textContent).not.toContain('transfer out');
});

test('transfers and review have independent views without inflating spending', () => {
  const elements = render([
    {amount_minor:5000,kind:'debit',channel:'bank'},
    {amount_minor:-9000,kind:'credit',channel:'bank'},
    {amount_minor:100000,kind:'transfer_out',excluded_from_spending:true,channel:'upi'},
    {amount_minor:-100000,kind:'transfer_in',excluded_from_spending:true,channel:'upi'},
    {amount_minor:30000,kind:'debit',channel:'bank',excluded_from_spending:true},
    {amount_minor:1000,kind:'purchase',category:'Other'},
    {amount_minor:9000,kind:'unknown',blocked:true}
  ]);
  expect(values(elements.get('metrics')!)).toEqual(['INR 190.00','INR 0.00','INR 190.00','INR 10.00']);
  click(elements,'view-transfers');
  expect(values(elements.get('metrics')!)).toEqual(['INR 1,300.00','INR 1,000.00','0','3']);
  expect(elements.get('transactions')!.children).toHaveLength(3);
  expect(elements.get('spending-breakdown')!.hidden).toBe(true);
  click(elements,'view-review');
  expect(values(elements.get('metrics')!)).toEqual(['2','1','1','1']);
  expect(elements.get('review-panel')!.hidden).toBe(false);
  expect(elements.get('review-summary')!.textContent).toBe('Source issues · 1');
});

test('search and payment filters apply within each view and preserve empty state', () => {
  const elements=render();
  input(elements,'search','missing');
  expect(elements.get('transactions')!.children[0].children[0].colSpan).toBe(7);
  input(elements,'search','Synthetic card');
  expect(elements.get('transactions')!.children).toHaveLength(3);
  input(elements,'search','');input(elements,'channel','upi');
  expect(values(elements.get('metrics')!)).toEqual(['INR 20.00','INR 0.00','INR 20.00','INR 0.00']);
  click(elements,'view-incoming');
  expect(values(elements.get('metrics')!)[0]).toBe('INR 50.00');
});

test('overall overview excludes transfers, refunds from receipts, repayments and blocked duplicates', () => {
  const elements=render([
    {amount_minor:-20000,kind:'credit',channel:'bank',date:'2026-09-12'},
    {amount_minor:3000,kind:'purchase',status:'provisional'},
    {amount_minor:900000,kind:'transfer_out',excluded_from_spending:true},
    {amount_minor:-900000,kind:'transfer_in',excluded_from_spending:true},
    {amount_minor:-900000,kind:'credit',blocked:true},
    {amount_minor:-900000,kind:'credit',status:'matched',suppressed:true}
  ]);
  expect(values(elements.get('ov-cards')!)).toEqual(['INR 250.00','INR 160.00','+INR 90.00','INR 50.00']);
  expect(elements.get('ov-months')!.children.map(row=>row.children[0].textContent)).toEqual(['Oct - 2026','Sep - 2026']);
  const overview=elements.get('ov-cards')!.textContent;
  click(elements,'view-incoming');click(elements,'view-transfers');click(elements,'view-review');
  expect(elements.get('ov-cards')!.textContent).toBe(overview);
  input(elements,'month','2026-09');
  expect(values(elements.get('ov-cards')!)).toEqual(['INR 200.00','INR 0.00','+INR 200.00','INR 0.00']);
  input(elements,'month','');input(elements,'channel','upi');
  expect(values(elements.get('ov-cards')!)).toEqual(['INR 50.00','INR 20.00','+INR 30.00','INR 0.00']);
});

test('overall overview handles empty and refund-only months without mixing currencies', () => {
  const elements=render([
    {amount_minor:-20000,kind:'refund',date:'2026-09-12'},
    {amount_minor:-100000,kind:'credit',currency:'USD',date:'2026-09-12'}
  ]);
  input(elements,'month','2026-09');
  expect(values(elements.get('ov-cards')!)).toEqual(['INR 0.00','−INR 200.00','+INR 200.00','INR 0.00']);
  input(elements,'currency','USD');
  expect(values(elements.get('ov-cards')!)[0]).toBe('USD 1,000.00');
  input(elements,'search','missing');
  expect(values(elements.get('ov-cards')!)).toEqual(['USD 0.00','USD 0.00','USD 0.00','USD 0.00']);
  expect(elements.get('ov-months')!.textContent).toContain('No money in or spending');
});

test('numeric sorting, pagination, page reset and transaction details work together', () => {
  const elements=render(Array.from({length:60},(_,i)=>({amount_minor:i+1,kind:'purchase',merchant:'Shop '+String(i).padStart(2,'0'),reference:'ref-'+i})));
  click(elements,'tab-transactions');
  expect(elements.get('transactions')!.children).toHaveLength(25);
  expect(elements.get('page-info')!.textContent).toBe('1–25 of 63 · Page 1 of 3');
  click(elements,'next-page');click(elements,'next-page');
  expect(elements.get('transactions')!.children).toHaveLength(13);
  expect(elements.get('next-page')!.disabled).toBe(true);
  click(elements,'sort-amount_minor');
  expect(elements.get('page-info')!.textContent).toContain('Page 1 of 3');
  expect(elements.get('transactions')!.children[0].children[4].children[0].textContent).toBe('INR 120.00');
  click(elements,'sort-amount_minor');
  expect(elements.get('transactions')!.children[0].children[4].children[0].textContent).toBe('−INR 10.00');
  input(elements,'search','ref-59');
  expect(elements.get('page-info')!.textContent).toBe('1–1 of 1 · Page 1 of 1');
  elements.get('transactions')!.children[0].children[6].children[0].listeners.click();
  expect(elements.get('transaction-detail')!.hidden).toBe(false);
  expect(elements.get('detail-fields')!.textContent).toContain('ref-59');
  expect(elements.get('detail-fields')!.textContent).toContain('test-statement');
  click(elements,'close-detail');expect(elements.get('transaction-detail')!.hidden).toBe(true);
  input(elements,'search','');input(elements,'page-size','50');
  expect(elements.get('transactions')!.children).toHaveLength(50);
});

test('currencies never mix, refunds can exceed charges, and unsafe text remains text', () => {
  const elements=render([
    {amount_minor:999999,kind:'purchase',currency:'USD'},
    {amount_minor:-20000,kind:'refund',status:'provisional',merchant:'<img src=x onerror=alert(1)>'}
  ]);
  expect(values(elements.get('metrics')!)).toEqual(['INR 130.00','−INR 200.00','−INR 70.00','INR 210.00']);
  expect(elements.get('transactions')!.textContent).toContain('<img src=x onerror=alert(1)>');
  expect(elements.get('currency')!.children.find(c=>c.value==='INR')!.textContent).toBe('INR');
  expect(elements.get('report-period')!.textContent).toContain('INR');
  input(elements,'currency','USD');
  expect(values(elements.get('metrics')!)[0]).toBe('USD 9,999.99');
});

test('transaction source links expose provenance and checks without a separate Statements tab', () => {
  const elements=render([], {statements:[{id:'test-statement',account:'Test account',currency:'INR',period:'2026-09-01 – 2026-09-30',status:'imported',source:{mailbox:'box-a',message_id:'message-a',attachment_id:'attachment-a',filename:'test.pdf'},checks:{issues:[],passed_checks:['balance'],unavailable_checks:['count']}}]});
  const source=elements.get('transactions')!.children[0].children[1].children[1];
  expect(source.textContent).toBe('test.pdf · p. 1, row 1');
  expect(source.attributes['aria-label']).toContain('View source for Synthetic merchant');
  source.listeners.click();
  const detail=elements.get('detail-fields')!.textContent;
  for(const value of ['test.pdf','box-a','message-a','attachment-a','2026-09-01','balance','count']) expect(detail).toContain(value);
  input(elements,'search','missing');
  expect(elements.get('coverage-note')!.textContent).toContain('coverage may be incomplete');
  expect(elements.get('coverage-note')!.textContent).not.toContain('completed scan');
  expect(elements.has('tab-statements')).toBe(false);
});

test('release template contains no user data or external asset dependencies', () => {
  const data = JSON.parse(html.match(/<script id="data" type="application\/json">(.*?)<\/script>/s)![1]);
  expect(html).not.toContain('<th>Notes</th>');
  expect(data.rows).toEqual([]);expect(data.statements).toEqual([]);expect(data.sync).toEqual({});
  expect(html).not.toMatch(/<(?:script|link|img)\b[^>]*(?:src|href)\s*=/i);
  expect(/id="(?:tab-statements|coverage-panel|sync-issues)"/.test(html)).toBe(false);
});


test('monthly actuals reconcile categories, refunds and exclusions without budgets',()=>{
 const e=render([{amount_minor:3000,kind:'purchase',status:'provisional'},{amount_minor:800,kind:'purchase',status:'draft'},{amount_minor:99900,kind:'purchase',blocked:true},{amount_minor:80000,kind:'transfer_out',excluded_from_spending:true},{amount_minor:-80000,kind:'transfer_in',excluded_from_spending:true},{amount_minor:20000,kind:'repayment',status:'posted'}]);
 const summary=e.get('actuals-summary')!.children;
 expect(summary.map(r=>r.children[1].textContent).slice(1)).toEqual(['INR 50.00','INR 140.00','INR 10.00','INR 130.00','INR 38.00']);
 expect(e.get('actual-expenses')!.children.at(-1)!.children[1].textContent).toBe('INR 130.00');
 expect(e.get('actuals-note')!.textContent).toContain('not necessarily income');
 expect(e.get('actuals-panel')!.hidden).toBe(false);expect(e.get('transactions-panel')!.hidden).toBe(false);
 click(e,'tab-transactions');expect(e.get('transactions-panel')!.hidden).toBe(false);expect(e.get('actuals-panel')!.hidden).toBe(true);
 click(e,'view-review');expect(e.get('review-panel')!.hidden).toBe(false);
 click(e,'tab-report');expect(e.get('actuals-panel')!.hidden).toBe(false);expect(e.get('review-panel')!.hidden).toBe(true);
});

test('actuals handle refund-only and empty periods and keep currencies separate',()=>{
 const e=render([{date:'2026-09-01',amount_minor:-20000,kind:'refund'},{date:'2026-09-01',amount_minor:90000,kind:'purchase',currency:'USD'}]);
 input(e,'month','2026-09');expect(e.get('actual-expenses')!.children.at(-1)!.children[1].textContent).toBe('−INR 200.00');
 input(e,'currency','USD');expect(e.get('actual-expenses')!.children.at(-1)!.children[1].textContent).toBe('USD 900.00');
 input(e,'search','missing');expect(e.get('actual-expenses')!.textContent).toContain('No confirmed expenses');
 expect(e.get('actual-expenses')!.children.at(-1)!.children[1].textContent).toBe('USD 0.00');
});

test('daily chart uses confirmed purchases and observed days without inventing coverage',()=>{
 const e=render([
  {date:'2026-10-22',amount_minor:20000,kind:'purchase',status:'provisional'},
  {date:'2026-10-03',amount_minor:4000,kind:'purchase',status:'posted'},
  {date:'2026-10-04',amount_minor:999900,kind:'purchase',blocked:true},
  {date:'2026-10-05',amount_minor:999900,kind:'transfer_out',excluded_from_spending:true},
  {date:'2026-10-06',amount_minor:999900,kind:'purchase',currency:'USD'}
 ],{from:'2026-10-01',to:'2026-10-23'});
 expect(e.get('hero-total')!.textContent).toBe('INR 170.00');
 expect(e.get('daily-chart')!.children).toHaveLength(22);
 expect(e.get('daily-average')!.textContent).toBe('Average INR 8.18 / day');
 expect(e.get('daily-peak')!.textContent).toContain('INR 140.00');
 expect(e.get('daily-note')!.textContent).toContain('does not establish no spending');
 input(e,'from','2026-10-10');input(e,'month','2026-10');
 expect(e.get('daily-chart')!.children).toHaveLength(13);
 expect(e.get('hero-total')!.textContent).toBe('INR 200.00');
 expect(e.get('hero-label')!.textContent).toBe('Provisional net spend');
 input(e,'search','no matching rows');expect(e.get('daily-chart')!.children).toHaveLength(0);
});

test('report preview, category chips, navigation and row sizing stay independent of actuals',()=>{
 const e=render(Array.from({length:30},(_,i)=>({amount_minor:100,kind:'purchase',category:i%2?'Shopping':'Groceries'})));
 const actuals=e.get('actuals-summary')!.textContent;
 expect(e.get('transactions')!.children).toHaveLength(10);expect(e.get('page-size')!.disabled).toBe(true);
 const chip=e.get('category-chips')!.children.find(c=>c.textContent==='Shopping')!;chip.listeners.click();
 expect(e.get('page-info')!.textContent).toContain('of 15');expect(e.get('actuals-summary')!.textContent).toBe(actuals);
 e.get('category-chips')!.children[0].listeners.click();
 click(e,'tab-transactions');expect(e.get('transactions')!.children).toHaveLength(25);expect(e.get('page-size')!.disabled).toBe(false);
 click(e,'view-review');expect(e.get('review-panel')!.hidden).toBe(false);
 click(e,'tab-report');expect(e.get('daily-panel')!.hidden).toBe(false);
});

test('real synthetic batch-to-ledger-to-HTML output exposes every source occurrence in All transactions', async () => {
  const { spawnSync } = await import('node:child_process');
  const [python,...prefix] = pythonCommand();
  const run = spawnSync(python, [...prefix, '-X', 'utf8', 'tests/make_completeness_report.py'], {cwd: new URL('..', import.meta.url), encoding:'utf8'});
  expect(run.status).toBe(0);
  const data=JSON.parse(run.stdout);
  const e=render([],data);
  expect(e.get('transactions')!.textContent).toContain('No transactions');
  click(e,'view-all');
  expect(e.get('from')!.value).toBe('');expect(e.get('to')!.value).toBe('');
  expect(e.get('transactions')!.children).toHaveLength(data.rows.length);
  expect(e.get('transactions')!.textContent).toContain('Card repayment');
  expect(e.get('transactions')!.textContent).toContain('Own out');
  expect(e.get('transactions')!.textContent).toContain('Own in');
  expect(e.get('transactions')!.textContent).toContain('Incoming');
  expect(e.get('transactions')!.textContent).toContain('Unreadable amount');
  expect(e.get('transactions')!.textContent).toContain('Unresolved');
  const completeness=new Set<string>();
  for(const row of e.get('transactions')!.children){
    row.children[1].children[1].listeners.click();
    completeness.add(e.get('detail-fields')!.textContent);
  }
  expect([...completeness].some(text=>text.includes('Completeness not verified'))).toBe(true);
  expect([...completeness].some(text=>text.includes('Source coverage complete'))).toBe(true);
  click(e,'view-spending');
  expect(e.get('transactions')!.textContent).not.toContain('Card repayment');
  expect(e.get('transactions')!.textContent).not.toContain('Own out');
  expect(values(e.get('metrics')!)[0]).toBe('INR 20.00');
  click(e,'view-review');expect(e.get('review-transactions')!.textContent).toContain('Unreadable amount');
});

test('All transactions includes proven duplicate occurrences while spend totals count one movement',()=>{
 const e=render([{merchant:'Bank-side repayment',amount_minor:20000,kind:'repayment',channel:'bank'},
  {merchant:'Linked duplicate occurrence',amount_minor:12000,kind:'purchase',suppressed:true,duplicate_of:{statement:'retained',index:0,evidence:'Same document row'}}]);
 click(e,'view-all');
 expect(e.get('transactions')!.children).toHaveLength(8);
 expect(e.get('transactions')!.textContent).toContain('Bank-side repayment');
 expect(e.get('transactions')!.textContent).toContain('Linked duplicate occurrence');
 click(e,'view-spending');expect(values(e.get('metrics')!)[0]).toBe('INR 130.00');
});


test('amount indicators replace the State column and distinguish status without color alone', () => {
  const e=render([
    {merchant:'Pending amount',amount_minor:3000,kind:'purchase',status:'provisional'},
    {merchant:'Unresolved amount',amount_minor:null,kind:'unknown',blocked:true},
    {merchant:'Duplicate amount',amount_minor:12000,kind:'purchase',status:'matched',suppressed:true}
  ]);
  click(e,'view-all');
  const rows=e.get('transactions')!.children;
  const indicator=(merchant:string)=>rows.find(r=>r.children[1].children[0].textContent===merchant)!.children[4].children[1];
  expect(html).not.toContain('id="head-status"');
  expect(rows.every(r=>r.children.length===7)).toBe(true);
  const confirmed=rows.find(r=>r.children[4].children[1].className==='amount-status ok')!.children[4].children[1];
  expect(confirmed.textContent).toBe('✓');
  expect(confirmed.attributes['aria-label']).toContain('Confirmed');
  expect(indicator('Pending amount').textContent).toBe('◷');
  expect(indicator('Pending amount').attributes['aria-label']).toContain('Provisional');
  expect(indicator('Unresolved amount').textContent).toBe('!');
  expect(indicator('Unresolved amount').attributes['aria-label']).toContain('Needs review');
  expect(indicator('Duplicate amount').textContent).toBe('↪');
  expect(indicator('Duplicate amount').attributes['aria-label']).toContain('Reconciled duplicate');
});


test('report drops Spending highlights and redundant labels while preserving accessible filters',()=>{
 const e=render([],{review_items:[]});
 expect(e.get('review-count')!.hidden).toBe(true);
 expect(html).not.toContain('Spending highlights');
 expect(html).not.toContain('id="top-categories-panel"');
 expect(html).toContain('<span class="sr-only">Month</span>');
 expect(html).toContain('All payment types');
 click(e,'view-all');
 expect(e.get('view-note')!.hidden).toBe(true);
 expect(e.get('table-title')!.className).toBe('sr-only');
});

test('agent-supplied display notes retain source notation in details without institutional rules',()=>{
 const e=render([{merchant:'Gym membership',original_merchant:'EMI Gym membership',metadata:{display_note:'The agent verified this prefix indicates conversion eligibility.'},category:'Health & fitness',amount_minor:8000,kind:'purchase'}]);
 click(e,'tab-transactions');input(e,'search','Gym membership');
 expect(e.get('transactions')!.textContent).not.toContain('EMI Gym membership');
 e.get('transactions')!.children[0].children[6].children[0].listeners.click();
 expect(e.get('detail-fields')!.textContent).toContain('EMI Gym membership');
 expect(e.get('detail-fields')!.textContent).toContain('conversion eligibility');
 expect(e.get('categories')!.textContent).toContain('Health & fitness');
});


test('incoming credits need ownership proof before exclusion from Money in', () => {
  const e=render([
    {merchant:'Backfilled salary credit',amount_minor:-250000,kind:'transfer_in',category:'Salary',channel:'bank'},
    {merchant:'External bank transfer',amount_minor:-40000,kind:'credit',category:'Transfers',channel:'bank'},
    {merchant:'Confirmed own transfer',amount_minor:-900000,kind:'transfer_in',excluded_from_spending:true,channel:'bank'},
    {merchant:'Unverified outgoing',amount_minor:70000,kind:'transfer_out',channel:'bank'},
    {merchant:'Blocked incoming',amount_minor:-999999,kind:'transfer_in',blocked:true,channel:'bank'}
  ]);
  expect(values(e.get('ov-cards')!)[0]).toBe('INR 2,950.00');
  expect(e.get('actuals-summary')!.textContent).toContain('INR 2,950.00');
  click(e,'view-incoming');
  expect(values(e.get('metrics')!)[0]).toBe('INR 3,010.00');
  expect(e.get('transactions')!.textContent).toContain('Backfilled salary credit');
  expect(e.get('transactions')!.textContent).toContain('External bank transfer');
  expect(e.get('transactions')!.textContent).not.toContain('Confirmed own transfer');
  expect(e.get('transactions')!.textContent).not.toContain('Blocked incoming');
  click(e,'view-transfers');
  expect(e.get('transactions')!.children).toHaveLength(1);
  expect(e.get('transactions')!.textContent).toContain('Confirmed own transfer');
  click(e,'view-review');
  expect(e.get('review-transactions')!.textContent).toContain('Unverified outgoing');
  const row=e.get('review-transactions')!.children.find(r=>r.children[0].children[0].textContent==='Unverified outgoing')!;
  row.children.at(-1)!.listeners.click();
  expect(e.get('detail-fields')!.textContent).toContain('Transfer ownership needs review');
  input(e,'month','2026-09');
  expect(values(e.get('ov-cards')!)[0]).toBe('INR 0.00');
});


test('Review uses list items with specific reasons and accessible amounts and details',()=>{
 const e=render([
  {merchant:'Unreadable row',kind:'unknown',amount_minor:null,blocked:true,review_reason:'Page 2 row 4 is blurred',statement:'problem'},
  {merchant:'Balance mismatch',kind:'purchase',amount_minor:500,blocked:true,statement:'problem'},
  {merchant:'Unknown category',kind:'purchase',amount_minor:900,category:'Other'},
  {merchant:'Staged row',kind:'purchase',amount_minor:800,status:'draft'},
  {merchant:'Outgoing review',kind:'transfer_out',amount_minor:800},
  {merchant:'Duplicate review',kind:'unknown',blocked:true,suppressed:true}
 ],{statements:[{id:'problem',account:'Synthetic card',currency:'INR',period:'Oct',status:'draft',source:{mailbox:'box',message_id:'message'},checks:{issues:['Closing balance differs by INR 5.00'],passed_checks:[],unavailable_checks:[]}}]});
 click(e,'view-review');
 expect(html).toContain('<ul id="review-transactions"');
 expect(html).toContain('<ul id="review-groups"');
 expect(e.get('transaction-table')!.hidden).toBe(true);
 expect(e.get('review-transactions')!.hidden).toBe(false);
 const items=e.get('review-transactions')!.children;
 expect(items).toHaveLength(5);
 const item=(name:string)=>items.find(r=>r.children[0].children[0].textContent===name)!;
 expect(item('Unreadable row').textContent).toContain('Page 2 row 4 is blurred');
 expect(item('Unreadable row').textContent).not.toContain("The source row's amount could not be read.");
 expect(item('Balance mismatch').textContent).toContain('Closing balance differs by INR 5.00');
 expect(item('Unknown category').textContent).toContain('not been assigned a spending category');
 expect(item('Staged row').textContent).toContain('staged and has not been imported');
 expect(item('Outgoing review').textContent).toContain('receiving account has not been confirmed');
 expect(e.get('review-transactions')!.textContent).not.toContain('Duplicate review');
 expect(items.every(r=>r.children.some(c=>c.className==='review-reason'&&c.textContent.length>0))).toBe(true);
 expect(item('Unreadable row').children[0].children[1].children[1].attributes['aria-label']).toContain('Needs review');
 item('Unreadable row').children.at(-1)!.listeners.click();
 expect(e.get('transaction-detail')!.hidden).toBe(false);
 expect(e.get('detail-fields')!.textContent).toContain('Page 2 row 4 is blurred');
 expect(e.get('review-groups')!.children[0].textContent).toContain('Synthetic review');
});

test('Review keeps pagination and supports searching the explanation',()=>{
 const e=render([
  ...Array.from({length:31},(_,i)=>({merchant:'Uncategorized '+i,kind:'purchase',amount_minor:100,category:'Other'})),
  {merchant:'Outside account',kind:'transfer_out',amount_minor:900}
 ]);
 click(e,'view-review');
 expect(e.get('review-transactions')!.children).toHaveLength(25);
 click(e,'next-page');expect(e.get('review-transactions')!.children).toHaveLength(7);
 input(e,'search','receiving account');
 expect(e.get('review-transactions')!.children).toHaveLength(1);
 expect(e.get('review-transactions')!.textContent).toContain('Outside account');
 expect(e.get('page-info')!.textContent).toBe('1–1 of 1 · Page 1 of 1');
 input(e,'search','missing reason');
 expect(e.get('review-transactions')!.textContent).toContain('No transactions need review');
 expect(e.get('review-groups')!.textContent).toContain('Synthetic review');
});

test('Review avoids repeating category issues and restores the table on navigation',()=>{
 const e=render([{merchant:'Category decision',kind:'purchase',category:'Other',amount_minor:100}],{review_items:[{group:'Categorization',reason:'Category decision needs a category'}]});
 click(e,'view-review');
 expect(e.get('review-panel')!.hidden).toBe(true);
 expect(e.get('review-transactions')!.children).toHaveLength(1);
 expect(e.get('review-count')!.textContent).toBe('1');
 click(e,'tab-report');
 expect(e.get('transaction-table')!.hidden).toBe(false);
 expect(e.get('review-transactions')!.hidden).toBe(true);
 const empty=render([],{review_items:[]});click(empty,'view-review');
 expect(empty.get('review-transactions')!.textContent).toContain('No transactions need review');
 expect(empty.get('review-count')!.hidden).toBe(true);
});


test('source review list shows the specific issue and identifiable context with source details',()=>{
 const e=render([],{review_items:[
  {group:'Source checks',account:'Synthetic bank',mailbox_id:'box-a',message_id:'source-a',reason:'Page 3 is missing; two source rows cannot be checked.'},
  {group:'Passwords',mailbox_id:'box-b',message_id:'source-b',reason:'The saved PDF password was rejected.'}
 ],statements:[{id:'statement-a',account:'Synthetic bank',currency:'INR',period:'2026-09-01 – 2026-09-30',status:'draft',source:{mailbox:'box-a',message_id:'source-a',attachment_id:'attachment-a',filename:'September statement.pdf'},checks:{issues:[],passed_checks:[],unavailable_checks:[]}}]});
 click(e,'view-review');
 const items=e.get('review-groups')!.children;
 expect(e.get('transactions-panel')!.hidden).toBe(true);
 expect(items).toHaveLength(2);
 expect(items[0].textContent).toContain('September statement.pdf');
 expect(items[0].textContent).toContain('2026-09-01 – 2026-09-30');
 expect(items[0].children.find(c=>c.className==='review-reason')!.textContent).toBe('Page 3 is missing; two source rows cannot be checked.');
 expect(items[0].children.at(-1)!.children[0].textContent).toBe('View source');
 expect(items[0].children.at(-1)!.textContent).toContain('attachment-a');
 expect(items[1].children.find(c=>c.className==='review-reason')!.textContent).toBe('The saved PDF password was rejected.');
 expect(items[1].children.at(-1)!.textContent).toContain('source-b');
 expect(items[1].textContent).not.toContain('September statement.pdf');
});

test('source review never guesses context across ambiguous mailbox sources',()=>{
 const source=(mailbox:string,account:string)=>({id:mailbox,account,currency:'INR',period:'Sep 2026',status:'draft',source:{mailbox,message_id:'same-message',filename:mailbox+'.pdf'},checks:{issues:[],passed_checks:[],unavailable_checks:[]}});
 const e=render([],{review_items:[{group:'Accounts',message_id:'same-message',reason:'The account could not be resolved.'}],statements:[source('box-a','Account A'),source('box-b','Account B')]});
 click(e,'view-review');
 const item=e.get('review-groups')!.children[0];
 expect(item.textContent).toContain('The account could not be resolved.');
 expect(item.textContent).not.toContain('Account A');
 expect(item.textContent).not.toContain('Account B');
});

test('transaction details preserve missing evidence, coverage gaps and completed coverage',()=>{
 const statement={account:'Synthetic account',currency:'INR',period:'Sep 2026',status:'imported',source:{mailbox:'box',message_id:'message',filename:'statement.pdf'},checks:{issues:[],passed_checks:[],unavailable_checks:[]}};
 const e=render(['unverified','gap','complete'].map(id=>({merchant:id,statement:id,kind:'purchase',amount_minor:100})),{statements:[
  {...statement,id:'unverified'},
  {...statement,id:'gap',coverage:{verified:false,status:'Completeness not verified',gaps:['Page 4 was not extracted.']}},
  {...statement,id:'complete',coverage:{verified:true,status:'Source coverage complete',gaps:[]},financial_review_resolved:true}
 ]});
 const detail=(merchant:string)=>{
   e.get('transactions')!.children.find(row=>row.children[1].children[0].textContent===merchant)!.children[1].children[1].listeners.click();
   return e.get('detail-fields')!.textContent;
 };
 expect(detail('unverified')).toContain('Source row coverage evidence is missing');
 expect(detail('gap')).toContain('Page 4 was not extracted.');
 expect(detail('complete')).toContain('Source coverage complete');
 expect(detail('complete')).toContain('Resolved');
});

test('inline source retains all mailbox occurrences, direct email sources and unresolved rows safely',()=>{
 const unsafe='<img src=x onerror=alert(1)>';
 const source={mailbox:'box-a',message_id:'message-a',filename:unsafe};
 const e=render([
  {merchant:'Duplicate source',statement:'multi',kind:'purchase',amount_minor:12000,suppressed:true,duplicate_of:{statement:'test-statement',index:0,evidence:'same row'}},
  {merchant:'Alert source',statement:'none',kind:'purchase',amount_minor:200,status:'provisional',source:{mailbox_id:'box-c',message_id:'alert-c',filename:'email-body'}},
  {merchant:'Unresolved source',statement:'multi',kind:'unknown',amount_minor:null,blocked:true}
 ],{statements:[{id:'multi',period:'Sep 2026',source,sources:[source,source,{mailbox:'box-b',message_id:'message-b',filename:'copy.pdf'}]}]});
 click(e,'view-all');
 const rows=e.get('transactions')!.children;
 const sourceLink=(merchant:string)=>rows.find(row=>row.children[1].children[0].textContent===merchant)!.children[1].children[1];
 expect(sourceLink('Duplicate source').textContent).toContain(unsafe+' · +1 source');
 sourceLink('Duplicate source').listeners.click();
 expect(e.get('detail-fields')!.textContent).toContain('box-a');expect(e.get('detail-fields')!.textContent).toContain('box-b');
 expect(sourceLink('Alert source').textContent).toContain('Email message');
 sourceLink('Alert source').listeners.click();expect(e.get('detail-fields')!.textContent).toContain('box-c');
 click(e,'view-review');
 const review=e.get('review-transactions')!.children.find(item=>item.textContent.includes('Unresolved source'))!;
 review.children.find(child=>child.className==='link transaction-source')!.listeners.click();
 expect(e.get('detail-fields')!.textContent).toContain('message-b');
});


test('Review shows agent-cached merchant categories without interpreting merchant names',()=>{
 const e=render([],{sync:{merchant_categories:[{merchant:'unlisted merchant',category:'Agent chosen category'}]}});
 click(e,'view-review');
 expect(e.get('merchant-categories')!.hidden).toBe(false);
 expect(e.get('merchant-list')!.textContent).toContain('unlisted merchant');
 expect(e.get('merchant-list')!.textContent).toContain('Agent chosen category');
});


function neutralRender(rows: Record<string,unknown>[], extraData: Record<string,unknown> = {}) {
  return render([], {...extraData, rows:rows.map(row=>({date:'2026-10-24',merchant:'Supplied description',category:'Agent category',
    kind:'purchase',page:1,row:'1',statement:'source',account:'Agent account',account_key:'opaque',currency:'INR',
    exponent:2,status:'imported',blocked:false,suppressed:false,channel:null,...row}))});
}

test('payment-channel filters use only opaque supplied values and never infer from merchant names', () => {
  const label='Local network / Ω';
  const e=neutralRender([{merchant:'UPI EMI Coffee Uber',channel:label,amount_minor:7777},
                  {merchant:'UPI payment',channel:null,amount_minor:3333}]);
  const choices=e.get('channel')!.children.map(child=>child.value);
  expect(choices).toContain(label);
  expect(choices).not.toContain('upi');
  expect(choices).not.toContain('bank');
  input(e,'channel',label);
  expect(values(e.get('metrics')!)[0]).toBe('INR 77.77');
});

test('zero, three, and eighteen fractional digits render from explicit precision', () => {
  const e=neutralRender([{currency:'JPY',exponent:0,amount_minor:123},
                  {currency:'BHD',exponent:3,amount_minor:1234},
                  {currency:'Opaque unit',exponent:18,amount_minor:9007199254740991}]);
  for (const [currency,expected] of [['JPY','JPY 123'],['BHD','BHD 1.234'],['Opaque unit','Opaque unit 0.009007199254740991']]) {
    input(e,'currency',currency);
    expect(values(e.get('metrics')!)[0]).toBe(expected);
  }
  expect(e.get('currency')!.children.map(child=>child.value)).toContain('Opaque unit');
});


test('unknown currency remains visible in Review beside known currencies without an invented amount', () => {
  const e=neutralRender([{merchant:'Known purchase',amount_minor:100},
    {merchant:'Unresolved currency row',currency:null,exponent:null,amount_minor:null,
     kind:'unknown',status:'needs_review',blocked:true,review_reason:'Currency missing from source'}]);
  click(e,'view-review');
  expect(e.get('review-transactions')!.textContent).toContain('Unresolved currency row');
  expect(e.get('review-transactions')!.textContent).toContain('Unresolved');
  click(e,'view-all');
  expect(e.get('transactions')!.textContent).toContain('Unresolved currency row');
});


test('the report falls back to labeled provisional spending, categories, and daily purchases', () => {
  const e=neutralRender([
    {merchant:'Pending purchase',amount_minor:12500,status:'provisional',category:'Household'},
    {merchant:'Pending refund',amount_minor:-2500,kind:'refund',status:'provisional',category:'Household'},
    {merchant:'Pending debit',amount_minor:2000,kind:'debit',status:'provisional',category:'Travel'},
    {merchant:'Pending credit',amount_minor:-30000,kind:'credit',status:'provisional'},
    {merchant:'Own transfer',amount_minor:90000,kind:'transfer_out',status:'provisional',excluded_from_spending:true},
    {merchant:'Repayment',amount_minor:80000,kind:'repayment',status:'provisional'},
    {merchant:'Blocked purchase',amount_minor:99999,status:'draft',blocked:true},
    {merchant:'Covered notice',amount_minor:77777,status:'statement_covered'},
    {merchant:'Duplicate',amount_minor:66666,status:'matched',suppressed:true}
  ]);
  expect(e.get('hero-label')!.textContent).toBe('Provisional net spend');
  expect(e.get('hero-total')!.textContent).toBe('INR 120.00');
  expect(e.get('hero-caption')!.textContent).toBe('3 provisional transactions');
  expect(e.get('hero-provisional')!.hidden).toBe(true);
  expect(e.get('actuals-note')!.textContent).toContain('no confirmed spending is available');
  expect(e.get('expenses-title')!.textContent).toBe('Provisional expenses by category');
  expect(e.get('actual-expenses')!.children.at(-1)!.textContent).toContain('INR 120.00');
  expect(e.get('category-total')!.textContent).toBe('INR 145.00');
  expect(e.get('category-caption')!.textContent).toContain('Provisional');
  expect(e.get('daily-chart')!.attributes['aria-label']).toBe('Daily provisional purchases');
  expect(e.get('daily-chart')!.children[0].attributes['aria-label']).toContain('INR 145.00 provisional purchases');
  expect(e.get('hero-metrics')!.children[0].textContent).toContain('Provisional money inINR 300.00');
  click(e,'tab-transactions');
  expect(values(e.get('metrics')!)).toEqual(['INR 0.00','INR 120.00','INR 120.00','INR 25.00']);
});

test('a confirmed net zero remains confirmed even when provisional spending exists', () => {
  const e=neutralRender([
    {amount_minor:10000,kind:'purchase'},
    {amount_minor:-10000,kind:'refund'},
    {amount_minor:50000,status:'provisional'}
  ]);
  expect(e.get('hero-label')!.textContent).toBe('Confirmed net spend');
  expect(e.get('hero-total')!.textContent).toBe('INR 0.00');
  expect(e.get('hero-provisional')!.textContent).toBe('Provisional net INR 500.00');
  expect(e.get('category-total')!.textContent).toBe('INR 100.00');
  expect(e.get('daily-chart')!.attributes['aria-label']).toBe('Daily confirmed purchases');
});

test('an explicit confirmed zero and a provisional zero both retain their evidence state', () => {
  const confirmed=neutralRender([{amount_minor:0},{amount_minor:5000,status:'provisional'}]);
  expect(confirmed.get('hero-label')!.textContent).toBe('Confirmed net spend');
  expect(confirmed.get('hero-total')!.textContent).toBe('INR 0.00');
  const provisional=neutralRender([{amount_minor:1000,status:'provisional'},
    {amount_minor:-1000,kind:'refund',status:'provisional'}]);
  expect(provisional.get('hero-label')!.textContent).toBe('Provisional net spend');
  expect(provisional.get('hero-total')!.textContent).toBe('INR 0.00');
});

test('fallback follows account and currency filters and returns to confirmed amounts when available', () => {
  const e=neutralRender([
    {account:'Account A',account_key:'a',amount_minor:1000},
    {account:'Account B',account_key:'b',amount_minor:5500,status:'provisional'},
    {account:'Account B',account_key:'b',currency:'JPY',exponent:0,amount_minor:321,status:'provisional'}
  ]);
  input(e,'currency','INR');
  expect(e.get('hero-label')!.textContent).toBe('Confirmed net spend');
  expect(e.get('hero-total')!.textContent).toBe('INR 10.00');
  input(e,'account','b');
  expect(e.get('hero-label')!.textContent).toBe('Provisional net spend');
  expect(e.get('hero-total')!.textContent).toBe('INR 55.00');
  input(e,'currency','JPY');
  expect(e.get('hero-total')!.textContent).toBe('JPY 321');
  input(e,'currency','INR');input(e,'account','a');
  expect(e.get('hero-label')!.textContent).toBe('Confirmed net spend');
  expect(e.get('hero-total')!.textContent).toBe('INR 10.00');
});

test('confirmed income does not hide provisional expenses and income fallback is labeled separately', () => {
  const e=neutralRender([{amount_minor:-10000,kind:'credit'},
    {amount_minor:2500,status:'provisional'}]);
  expect(e.get('hero-label')!.textContent).toBe('Provisional net spend');
  expect(e.get('hero-total')!.textContent).toBe('INR 25.00');
  expect(e.get('hero-metrics')!.children[0].children[0].textContent).toBe('Money in');
  expect(e.get('hero-metrics')!.children[1].children[0].textContent).toBe('Provisional net cash flow');
  const incoming=neutralRender([{amount_minor:1000},
    {amount_minor:-2000,kind:'credit',status:'provisional'}]);
  expect(incoming.get('hero-label')!.textContent).toBe('Confirmed net spend');
  expect(incoming.get('hero-metrics')!.children[0].textContent).toContain('Provisional money inINR 20.00');
});

test('blocked and statement-covered rows cannot become provisional fallback amounts', () => {
  const e=neutralRender([{amount_minor:7000,status:'draft',blocked:true},
    {amount_minor:8000,status:'statement_covered'},{amount_minor:9000,status:'matched',suppressed:true}]);
  expect(e.get('hero-label')!.textContent).toBe('Net spend');
  expect(e.get('hero-total')!.textContent).toBe('INR 0.00');
  expect(e.get('category-total')!.textContent).toBe('INR 0.00');
  expect(e.get('daily-chart')!.children).toHaveLength(0);
});


test('a reconciled account section stays confirmed while sibling document gaps remain visible', () => {
  const documentGap='Section deposit-summary: individual withdrawals and exact interest dates are unavailable';
  const coverage={verified:false,status:'Completeness not verified',gaps:[documentGap],
    section:{id:'savings',verified:true,status:'Section coverage complete',gaps:[]},
    source_row_count:44,mapped_counts:{retained:44,duplicate_linked:0,review:0}};
  const e=neutralRender([{merchant:'Reconciled savings purchase',amount_minor:1200}],{
    statements:[{id:'source',account:'Savings',currency:'INR',period:'Sep 2026',status:'imported',
      coverage,financial_review_resolved:true,source:{mailbox:'box',message_id:'combined',filename:'combined.pdf'},
      checks:{issues:[],coverage,passed_checks:['balance_reconciliation'],unavailable_checks:[]}}],
    review_items:[{group:'Source checks',account:'Savings',mailbox_id:'box',message_id:'combined',reason:documentGap}]
  });
  expect(e.get('hero-label')!.textContent).toBe('Confirmed net spend');
  expect(e.get('hero-total')!.textContent).toBe('INR 12.00');
  e.get('transactions')!.children[0].children[1].children[1].listeners.click();
  expect(e.get('detail-fields')!.textContent).toContain('Document completenessCompleteness not verified');
  expect(e.get('detail-fields')!.textContent).toContain('Account section completenessSection coverage complete');
  click(e,'view-review');
  expect(e.get('review-groups')!.textContent).toContain(documentGap);
});
