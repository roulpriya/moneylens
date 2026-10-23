import { test, expect } from 'bun:test';
import { readFileSync } from 'node:fs';
import { runInNewContext } from 'node:vm';

const html = readFileSync(new URL('../skills/moneylens-automation/assets/report-template.html', import.meta.url), 'utf8');
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
    {...row, amount_minor:2000, kind:'upi_debit', channel:'upi', status:'posted', category:'Transport'},
    {...row, amount_minor:-5000, kind:'upi_credit', channel:'upi', status:'posted'},
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
    {amount_minor:100000,kind:'transfer_out'}
  ]);
  expect(values(elements.get('metrics')!)).toEqual(['INR 130.00','INR 57.00','INR 187.00','INR 10.00']);
  expect(elements.get('transactions')!.children).toHaveLength(5);
  expect(elements.get('transactions')!.children[0].children).toHaveLength(8);
  expect(elements.get('months')!.textContent).toContain('INR 57.00');
  click(elements,'view-incoming');
  expect(values(elements.get('metrics')!)).toEqual(['INR 110.00','INR 0.00','INR 110.00','3']);
  expect(elements.get('transactions')!.textContent).not.toContain('transfer out');
});

test('transfers and review have independent views without inflating spending', () => {
  const elements = render([
    {amount_minor:5000,kind:'bank_debit',channel:'bank'},
    {amount_minor:-9000,kind:'bank_credit',channel:'bank'},
    {amount_minor:100000,kind:'transfer_out',channel:'upi'},
    {amount_minor:-100000,kind:'transfer_in',channel:'upi'},
    {amount_minor:30000,kind:'bank_debit',channel:'bank',excluded_from_spending:true},
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
  expect(elements.get('review-summary')!.textContent).toBe('Source items to review · 1');
});

test('search and payment filters apply within each view and preserve empty state', () => {
  const elements=render();
  input(elements,'search','missing');
  expect(elements.get('transactions')!.children[0].children[0].colSpan).toBe(8);
  input(elements,'search','Synthetic card');
  expect(elements.get('transactions')!.children).toHaveLength(3);
  input(elements,'search','');input(elements,'channel','upi');
  expect(values(elements.get('metrics')!)).toEqual(['INR 20.00','INR 0.00','INR 20.00','INR 0.00']);
  click(elements,'view-incoming');
  expect(values(elements.get('metrics')!)[0]).toBe('INR 50.00');
});

test('overall overview excludes transfers, refunds from receipts, repayments and blocked duplicates', () => {
  const elements=render([
    {amount_minor:-20000,kind:'bank_credit',channel:'bank',date:'2026-09-12'},
    {amount_minor:3000,kind:'purchase',status:'provisional'},
    {amount_minor:900000,kind:'transfer_out'},
    {amount_minor:-900000,kind:'transfer_in'},
    {amount_minor:-900000,kind:'bank_credit',blocked:true},
    {amount_minor:-900000,kind:'bank_credit',status:'matched',suppressed:true}
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
    {amount_minor:-100000,kind:'bank_credit',currency:'USD',date:'2026-09-12'}
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
  expect(elements.get('transactions')!.children[0].children[4].textContent).toBe('INR 120.00');
  click(elements,'sort-amount_minor');
  expect(elements.get('transactions')!.children[0].children[4].textContent).toBe('−INR 10.00');
  input(elements,'search','ref-59');
  expect(elements.get('page-info')!.textContent).toBe('1–1 of 1 · Page 1 of 1');
  elements.get('transactions')!.children[0].children[7].children[0].listeners.click();
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
  input(elements,'currency','USD');
  expect(values(elements.get('metrics')!)[0]).toBe('USD 9,999.99');
});

test('coverage and diagnostics are separate from transaction filters and review', () => {
  const elements=render([], {statements:[{id:'statement-a',account:'Test account',currency:'INR',period:'2026-09-01 – 2026-09-30',status:'imported',source:{mailbox:'box-a',message_id:'message-a',filename:'test.pdf'},checks:{issues:[],passed_checks:['balance'],unavailable_checks:['count']}}],sync:{last_run:{success:false}}});
  input(elements,'search','missing');
  expect(elements.get('statements')!.textContent).toContain('2026-09-01');
  expect(elements.get('statements')!.textContent).not.toContain('message-a');
  expect(elements.get('diagnostics')!.textContent).toContain('message-a');
  expect(elements.get('diagnostics')!.textContent).toContain('incomplete');
  expect(elements.get('diagnostics')!.textContent).toContain('balance');
});

test('release template contains no user data or external asset dependencies', () => {
  const data = JSON.parse(html.match(/<script id="data" type="application\/json">(.*?)<\/script>/s)![1]);
  expect(html).not.toContain('<th>Notes</th>');
  expect(data.rows).toEqual([]);expect(data.statements).toEqual([]);expect(data.sync).toEqual({});
  expect(html).not.toMatch(/<(?:script|link|img)\b[^>]*(?:src|href)\s*=/i);
  expect(html).toContain('<summary>Statements from your inbox</summary>');
  expect(html).toContain('<summary>Diagnostics</summary>');
});


test('monthly actuals reconcile categories, refunds and exclusions without budgets',()=>{
 const e=render([{amount_minor:3000,kind:'purchase',status:'provisional'},{amount_minor:800,kind:'purchase',status:'draft'},{amount_minor:99900,kind:'purchase',blocked:true},{amount_minor:80000,kind:'transfer_out'},{amount_minor:-80000,kind:'transfer_in'},{amount_minor:20000,kind:'repayment',status:'posted'}]);
 const summary=e.get('actuals-summary')!.children;
 expect(summary.map(r=>r.children[1].textContent).slice(1)).toEqual(['INR 50.00','INR 140.00','INR 10.00','INR 130.00','INR 38.00']);
 expect(e.get('actual-expenses')!.children.at(-1)!.children[1].textContent).toBe('INR 130.00');
 expect(e.get('actuals-note')!.textContent).toContain('not necessarily income');
 expect(e.get('actuals-panel')!.hidden).toBe(false);expect(e.get('transactions-panel')!.hidden).toBe(false);
 click(e,'tab-transactions');expect(e.get('transactions-panel')!.hidden).toBe(false);expect(e.get('actuals-panel')!.hidden).toBe(true);
 click(e,'tab-statements');expect(e.get('coverage-panel')!.hidden).toBe(false);expect(e.get('transactions-panel')!.hidden).toBe(true);
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
  {date:'2026-10-05',amount_minor:999900,kind:'transfer_out'},
  {date:'2026-10-06',amount_minor:999900,kind:'purchase',currency:'USD'}
 ],{from:'2026-10-01',to:'2026-10-23'});
 expect(e.get('hero-total')!.textContent).toBe('₹170.00');
 expect(e.get('daily-chart')!.children).toHaveLength(22);
 expect(e.get('daily-average')!.textContent).toBe('Average INR 8.18 / day');
 expect(e.get('daily-peak')!.textContent).toContain('INR 140.00');
 expect(e.get('daily-note')!.textContent).toContain('does not establish no spending');
 input(e,'from','2026-10-10');input(e,'month','2026-10');
 expect(e.get('daily-chart')!.children).toHaveLength(13);
 expect(e.get('hero-total')!.textContent).toBe('₹0.00');
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
 click(e,'tab-statements');expect(e.get('coverage-panel')!.hidden).toBe(false);
 click(e,'view-review');expect(e.get('review-panel')!.hidden).toBe(false);
 click(e,'tab-report');expect(e.get('daily-panel')!.hidden).toBe(false);
});
