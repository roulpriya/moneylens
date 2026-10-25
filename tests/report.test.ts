import { test, expect } from 'bun:test';
import { readFileSync } from 'node:fs';
import { runInNewContext } from 'node:vm';
import { pythonCommand } from '../scripts/python-command';

const html = readFileSync(new URL('../skills/automation/assets/report-template.html', import.meta.url), 'utf8');
class Element {
  children: Element[] = [];
  className = ''; value = ''; hidden = true; colSpan = 0; disabled = false; open = false;
  parentElement?: Element;
  style: Record<string,any> = {setProperty(name:string,value:string){this[name]=value;}}; attributes: Record<string,string> = {};
  listeners: Record<string,(event?: any) => void> = {};
  clientWidth = 320; clientHeight = 800;
  private text = '';
  constructor(readonly id = '') {}
  set textContent(value: string) { this.text = value; this.children = []; }
  get textContent(): string { return this.text + this.children.map(child => child.textContent).join(''); }
  prepend(...children: Element[]) { this.children.unshift(...children); }
  append(...children: Element[]) {
    if (this.id === 'currency' && !this.children.length && children.length) this.value = children[0].value;
    for (const child of children) {
      if(child.parentElement) child.parentElement.children=child.parentElement.children.filter(e=>e!==child);
      child.parentElement=this;this.children.push(child);
    }
  }
  replaceChildren(...children: Element[]) { this.children = []; this.text = ''; this.append(...children); }
  addEventListener(name: string, callback: (event?: any) => void) { this.listeners[name] = callback; }
  click() { this.listeners.click?.(); }
  showModal() { this.open=true; }
  close() { this.open=false; this.listeners.close?.(); }
  setAttribute(name: string, value: string) { this.attributes[name] = value; }
  removeAttribute(name: string) { delete this.attributes[name]; }
  getBoundingClientRect() { return {left:20,top:100,right:40,bottom:120,width:20,height:20}; }
}
function render(extraRows: Record<string,unknown>[] = [], extraData: Record<string,unknown> = {}, storage?: Map<string,string>) {
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
  runInNewContext(script, {document:{documentElement:new Element('root'), getElementById:(id:string) => elements.get(id), createElement:() => new Element() },...(storage?{localStorage:{getItem:(key:string)=>storage.get(key)??null,setItem:(key:string,value:string)=>storage.set(key,value),removeItem:(key:string)=>storage.delete(key)}}:{})});
  return elements;
}
const values = (element: Element) => element.children.map(child => child.children[1].textContent);
const click = (elements: Map<string,Element>, id: string) => elements.get(id)!.listeners.click();
const input = (elements: Map<string,Element>, id: string, value: string) => { const e=elements.get(id)!;e.value=value;e.listeners.input(); };

test('At a glance opens with the same filtered actuals and daily chart as the detailed report', () => {
  const e=render([{amount_minor:5000,kind:'purchase',status:'provisional'},{amount_minor:999900,kind:'purchase',blocked:true},{amount_minor:80000,kind:'transfer_out',excluded_from_spending:true}]);
  expect(e.get('tab-glance')!.attributes['aria-pressed']).toBe('true');
  expect(e.get('report-title')!.textContent).toBe('At a glance');
  for(const id of ['actuals-panel','daily-panel','glance-panel'])expect(e.get(id)!.hidden).toBe(false);
  for(const id of ['transactions-panel','expenses-panel','cashflow-panel'])expect(e.get(id)!.hidden).toBe(true);
  expect(e.get('hero-total')!.textContent).toBe('INR 130.00');
  const before=e.get('actuals-summary')!.children.slice(1).map(row=>row.textContent);
  click(e,'glance-report');expect(e.get('glance-panel')!.hidden).toBe(true);
  expect(e.get('actuals-summary')!.children.slice(1).map(row=>row.textContent)).toEqual(before);
  expect(e.get('transactions-panel')!.hidden).toBe(false);
  click(e,'tab-glance');input(e,'channel','upi');
  expect(e.get('hero-total')!.textContent).toBe('INR 20.00');
  expect(e.get('hero-in-total')!.textContent).toBe('INR 50.00');
  expect(e.get('glance-activity')!.children).toHaveLength(2);
});

test('glance recent activity excludes duplicates and blocked or other-currency rows and opens source details', () => {
  const e=render([
    {date:'2026-10-23',merchant:'Latest receipt',amount_minor:-4500,kind:'credit'},
    {date:'2026-10-24',merchant:'Blocked',amount_minor:99900,kind:'purchase',blocked:true},
    {date:'2026-10-25',merchant:'Duplicate',amount_minor:99900,kind:'purchase',suppressed:true},
    {date:'2026-10-26',merchant:'Other currency',amount_minor:99900,kind:'purchase',currency:'USD'}
  ]);
  const activity=e.get('glance-activity')!;
  expect(activity.children).toHaveLength(5);
  expect(activity.children[0].textContent).toContain('Latest receipt');
  for(const label of ['Blocked','Duplicate','Other currency'])expect(activity.textContent).not.toContain(label);
  activity.children[0].children[0].listeners.click();
  expect(e.get('transactions-panel')!.hidden).toBe(false);
  expect(e.get('transaction-detail')!.hidden).toBe(false);
  expect(e.get('detail-fields')!.textContent).toContain('Latest receipt');
  click(e,'tab-glance');click(e,'glance-review');expect(e.get('review-panel')!.hidden).toBe(false);
  click(e,'tab-glance');click(e,'glance-transactions');expect(e.get('transaction-type')!.value).toBe('all');
});

test('glance labels provisional activity and handles empty months without inventing confirmation', () => {
  const e=render([{date:'2026-11-22',amount_minor:20000,kind:'purchase',status:'provisional'}]);
  input(e,'month','2026-11');
  expect(e.get('hero-label')!.textContent).toBe('Provisional');
  const amount=e.get('glance-activity')!.children[0].children[0].children[2];
  expect(amount.children[1].attributes['aria-label']).toContain('Provisional');
  expect(e.get('daily-chart')!.children.at(-1)!.attributes['aria-label']).toContain('INR 200.00 provisional spending');
  input(e,'month','2026-12');expect(e.get('glance-activity')!.textContent).toContain('No transactions');
  const empty=render([],{rows:[],review_items:[]});
  expect(empty.get('glance-review')!.disabled).toBe(true);
  expect(empty.get('glance-review')!.textContent).toBe('Nothing needs review');
});

test('glance shows month plus a filter disclosure and moves account and payment controls back to detailed views', () => {
  const e=render();
  expect(e.get('glance-filters')!.hidden).toBe(false);
  expect(e.get('report-period')!.hidden).toBe(true);
  for(const id of ['primary-filters','secondary-filters','accounting-filters','actuals-breakdown'])expect(e.get(id)!.hidden).toBe(true);
  expect(e.get('month-filter')!.parentElement!.id).toBe('primary-filters');
  expect(e.get('account-filter')!.parentElement!.id).toBe('glance-filter-fields');
  expect(e.get('channel-filter')!.parentElement!.id).toBe('glance-filter-fields');
  expect(e.get('glance-filter-menu')!.open).toBe(false);
  input(e,'account','synthetic');input(e,'channel','upi');
  expect(e.get('glance-filter-count')!.textContent).toBe('2');
  expect(e.get('hero-total')!.textContent).toBe('INR 20.00');
  e.get('glance-filter-menu')!.open=true;
  e.get('glance-filter-menu')!.listeners.keydown({key:'Escape',preventDefault(){}});
  expect(e.get('glance-filter-menu')!.open).toBe(false);
  click(e,'tab-report');
  expect(e.get('glance-filters')!.hidden).toBe(true);
  expect(e.get('report-period')!.hidden).toBe(true);
  expect(e.get('report-date-range')!.hidden).toBe(false);
  for(const id of ['primary-filters','accounting-filters','actuals-breakdown'])expect(e.get(id)!.hidden).toBe(false);
  expect(e.get('secondary-filters')!.hidden).toBe(true);
  expect(e.get('glance-filter-menu')!.parentElement!.id).toBe('report-heading');
  expect(e.get('secondary-filter-fields')!.parentElement!.id).toBe('glance-filter-fields');
  for(const id of ['account-filter','channel-filter'])expect(e.get(id)!.parentElement!.id).toBe('glance-filter-fields');
  expect(e.get('account')!.value).toBe('synthetic');expect(e.get('channel')!.value).toBe('upi');
});

test('detailed search, state and date filters cannot silently narrow glance and are restored in Report', () => {
  const e=render([{date:'2026-09-05',amount_minor:90000,kind:'purchase',currency:'USD'}]);
  click(e,'tab-report');input(e,'search','missing');input(e,'state','provisional');input(e,'from','2027-01-01');input(e,'to','2027-01-31');
  expect(e.get('hero-total')!.textContent).toBe('INR 0.00');
  click(e,'tab-glance');
  expect(e.get('hero-total')!.textContent).toBe('INR 130.00');
  expect(e.get('report-period')!.textContent).not.toContain('2027');
  click(e,'tab-report');expect(e.get('hero-total')!.textContent).toBe('INR 0.00');
  expect(e.get('search')!.value).toBe('missing');expect(e.get('state')!.value).toBe('provisional');
  input(e,'currency','USD');input(e,'month','2026-09');click(e,'tab-glance');
  expect(e.get('hero-total')!.textContent).toBe('USD 900.00');
  input(e,'month','2026-10');expect(e.get('hero-total')!.textContent).toBe('USD 0.00');
});

test('month chevrons handle year boundaries, empty months and the detailed Report selection', () => {
  const e=render([{date:'2026-12-31',amount_minor:100,kind:'purchase'},{date:'2027-01-01',amount_minor:200,kind:'purchase'}]);
  expect(e.get('month')!.value).toBe('2027-01');
  expect(e.get('glance-month-label')!.textContent).toBe('January 2027');
  expect(e.get('hero-total')!.textContent).toBe('INR 2.00');
  click(e,'previous-month');expect(e.get('month')!.value).toBe('2026-12');
  expect(e.get('hero-total')!.textContent).toBe('INR 1.00');
  click(e,'previous-month');expect(e.get('month')!.value).toBe('2026-11');
  expect(e.get('hero-total')!.textContent).toBe('INR 0.00');
  expect(e.get('glance-activity')!.textContent).toContain('No transactions');
  click(e,'next-month');click(e,'tab-report');
  expect(e.get('month')!.value).toBe('2026-12');
  expect(e.get('hero-total')!.textContent).toBe('INR 133.00');
  click(e,'tab-glance');expect(e.get('glance-month-label')!.textContent).toBe('December 2026');
});

test('month pager handles an empty ledger and an All months selection', () => {
  const empty=render([],{rows:[],review_items:[]});
  expect(empty.get('previous-month')!.disabled).toBe(true);expect(empty.get('next-month')!.disabled).toBe(true);
  expect(empty.get('glance-month-label')!.textContent).toBe('No months');
  const e=render();input(e,'month','');click(e,'next-month');
  expect(e.get('month')!.value).toBe('2026-10');
  expect(e.get('month')!.children.filter(option=>option.value==='2026-10')).toHaveLength(1);
});

test('Report uses an applied date range independently of the glance month and rejects reversed ranges', () => {
  const e=render([{date:'2026-09-15',amount_minor:9000,kind:'purchase'}]);click(e,'tab-report');
  expect(e.get('report-title')!.textContent).toBe('Report');
  expect(e.get('daily-panel')!.hidden).toBe(true);
  expect(e.get('month-filter')!.hidden).toBe(true);
  expect(e.get('from-filter')!.hidden).toBe(true);expect(e.get('to-filter')!.hidden).toBe(true);
  e.get('range-from')!.value='2026-09-01';e.get('range-to')!.value='2026-09-30';
  click(e,'range-apply');
  expect(e.get('hero-total')!.textContent).toBe('INR 90.00');
  expect(e.get('month')!.value).toBe('2026-10');
  expect(e.get('date-range-label')!.textContent).toContain('2026');
  e.get('report-date-range')!.open=true;
  e.get('range-from')!.value='2026-11-01';e.get('range-to')!.value='2026-10-01';
  click(e,'range-apply');expect(e.get('range-error')!.hidden).toBe(false);
  expect(e.get('from')!.value).toBe('2026-09-01');expect(e.get('hero-total')!.textContent).toBe('INR 90.00');
  click(e,'range-cancel');expect(e.get('report-date-range')!.open).toBe(false);
  click(e,'tab-glance');expect(e.get('hero-total')!.textContent).toBe('INR 130.00');
  expect(e.get('daily-panel')!.hidden).toBe(false);
});

test('Report quick ranges apply inclusive calendar dates and All time removes date restrictions', () => {
  const e=render();click(e,'tab-report');click(e,'range-last7');
  const days=(Date.parse(e.get('to')!.value)-Date.parse(e.get('from')!.value))/86400000;
  expect(days).toBe(6);
  click(e,'range-last30');expect((Date.parse(e.get('to')!.value)-Date.parse(e.get('from')!.value))/86400000).toBe(29);
  click(e,'range-thismonth');expect(e.get('from')!.value.endsWith('-01')).toBe(true);
  click(e,'range-lastmonth');expect(e.get('from')!.value<e.get('to')!.value).toBe(true);
  click(e,'range-all');expect(e.get('from')!.value).toBe('');expect(e.get('to')!.value).toBe('');
  expect(e.get('date-range-label')!.textContent).toBe('All time');
  expect(e.get('hero-total')!.textContent).toBe('INR 130.00');
});

test('Report category drilldown keeps the applied date range without a hidden month restriction', () => {
  const e=render([{date:'2026-09-15',merchant:'September shop',amount_minor:9000,kind:'purchase'}]);click(e,'tab-report');
  e.get('range-from')!.value='2026-09-01';e.get('range-to')!.value='2026-09-30';click(e,'range-apply');
  e.get('categories')!.children[0].listeners.click();
  expect(e.get('month')!.value).toBe('');
  expect(e.get('from')!.value).toBe('2026-09-01');expect(e.get('to')!.value).toBe('2026-09-30');
  expect(e.get('transactions')!.children).toHaveLength(1);
  expect(e.get('transactions')!.textContent).toContain('September shop');
});

test('daily chart amounts appear on hover and focus and dismiss on leave, Escape, or filtering', () => {
  const e=render(), bar=e.get('daily-chart')!.children[0], tooltip=e.get('chart-tooltip')!;
  expect(tooltip.hidden).toBe(true);
  bar.listeners.pointerenter();
  expect(tooltip.hidden).toBe(false);expect(tooltip.textContent).toBe(bar.attributes['aria-label']);
  expect(tooltip.textContent).toContain('INR 140.00 confirmed spending');
  expect(bar.attributes['aria-describedby']).toBe('chart-tooltip');
  bar.listeners.pointerleave();expect(tooltip.hidden).toBe(true);
  expect(bar.attributes['aria-describedby']).toBeUndefined();
  bar.listeners.focus();expect(tooltip.hidden).toBe(false);
  bar.listeners.keydown({key:'Escape'});expect(tooltip.hidden).toBe(true);
  bar.listeners.focus();input(e,'search','no matching rows');expect(tooltip.hidden).toBe(true);
});

test('category tooltips identify amounts without confusing purchases and net refunds', () => {
  const e=render(), tooltip=e.get('chart-tooltip')!;
  const categoryBar=e.get('categories')!.children.find(row=>row.children[1].textContent==='Groceries')!;
  categoryBar.listeners.focus();
  expect(tooltip.textContent).toContain('Spending INR 120.00');
  expect(tooltip.textContent).toContain('Net spending INR 110.00');

});

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
  expect(elements.get('hero-provisional')!.textContent).toContain('INR 57.00');
  input(elements,'transaction-type','incoming');
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
  input(elements,'transaction-type','transfers');
  expect(values(elements.get('metrics')!)).toEqual(['INR 1,300.00','INR 1,000.00','0','3']);
  expect(elements.get('transactions')!.children).toHaveLength(3);
  expect(elements.get('spending-breakdown')!.hidden).toBe(false);
  click(elements,'view-review');
  expect(values(elements.get('metrics')!)).toEqual(['2','1','1','1']);
  expect(elements.get('review-panel')!.hidden).toBe(false);
  expect(elements.get('review-summary')!.textContent).toBe('Needs review');
});

test('search and payment filters apply within each view and preserve empty state', () => {
  const elements=render();
  click(elements,'tab-report');
  input(elements,'search','missing');
  expect(elements.get('transactions')!.children[0].children[0].colSpan).toBe(7);
  input(elements,'search','Synthetic card');
  expect(elements.get('transactions')!.children).toHaveLength(3);
  input(elements,'search','');input(elements,'channel','upi');
  expect(values(elements.get('metrics')!)).toEqual(['INR 20.00','INR 0.00','INR 20.00','INR 0.00']);
  input(elements,'transaction-type','incoming');
  expect(values(elements.get('metrics')!)[0]).toBe('INR 50.00');
});

test('numeric sorting, pagination, page reset and transaction details work together', () => {
  const elements=render(Array.from({length:60},(_,i)=>({amount_minor:i+1,kind:'purchase',merchant:'Shop '+String(i).padStart(2,'0'),reference:'ref-'+i})));
  click(elements,'tab-report');
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

test('transaction details expose provenance and checks without inline source labels', () => {
  const elements=render([], {statements:[{id:'test-statement',account:'Test account',currency:'INR',period:'2026-09-01 – 2026-09-30',status:'imported',source:{mailbox:'box-a',message_id:'message-a',attachment_id:'attachment-a',filename:'test.pdf'},checks:{issues:[],passed_checks:['balance'],unavailable_checks:['count']}}]});
  const row=elements.get('transactions')!.children[0];
  expect(row.children[1].children).toHaveLength(1);
  row.children[6].children[0].listeners.click();
  const detail=elements.get('detail-fields')!.textContent;
  for(const value of ['test.pdf','box-a','message-a','attachment-a','2026-09-01','balance','count']) expect(detail).toContain(value);
  input(elements,'search','missing');
  expect(elements.has('coverage-note')).toBe(false);
  expect(elements.has('tab-statements')).toBe(false);
});

test('release template contains no user data or external asset dependencies', () => {
  const data = JSON.parse(html.match(/<script id="data" type="application\/json">(.*?)<\/script>/s)![1]);
  expect(html).not.toContain('<th>Notes</th>');
  expect(data.rows).toEqual([]);expect(data.statements).toEqual([]);expect(data.sync).toEqual({});
  expect(html).not.toMatch(/<(?:script|link|img)\b[^>]*(?:src|href)\s*=/i);
  expect(/id="(?:tab-statements|coverage-panel|sync-issues)"/.test(html)).toBe(false);
});

test('compiled report carries its website fonts and licenses without network dependencies', () => {
  const css = html.match(/<style>\s*([\s\S]*?)<\/style>/)![1];
  const urls = [...css.matchAll(/url\(\s*['"]?([^'"\s)]+)/g)].map(match => match[1]);
  expect(urls.every(url=>url.startsWith('data:'))).toBe(true);
  const fonts=urls.filter(url=>url.startsWith('data:font/'));
  expect(fonts).toHaveLength(3);
  expect(urls.some(url=>url.startsWith('data:image/svg+xml,'))).toBe(true);
  for (const url of fonts) expect(url).toMatch(/^data:font\/woff2;base64,[a-z\d+/=]+$/i);
  expect(css).toContain('DM Sans Variable');expect(css).toContain('Newsreader Variable');
  expect(css).toContain('SIL OPEN FONT LICENSE');expect(css).not.toContain('@import');
  expect(html).toContain('font-src data:');
  expect(html).toContain('value="moneylens">MoneyLens</option>');
});


test('monthly actuals reconcile categories, refunds and exclusions without budgets',()=>{
 const e=render([{amount_minor:3000,kind:'purchase',status:'provisional'},{amount_minor:800,kind:'purchase',status:'draft'},{amount_minor:99900,kind:'purchase',blocked:true},{amount_minor:80000,kind:'transfer_out',excluded_from_spending:true},{amount_minor:-80000,kind:'transfer_in',excluded_from_spending:true},{amount_minor:20000,kind:'repayment',status:'posted'}]);
 const summary=e.get('actuals-summary')!.children;
 expect(summary.map(r=>r.children[1].textContent).slice(1)).toEqual(['INR 50.00','INR 140.00','INR 10.00','INR 130.00','INR 38.00']);
 expect(e.get('hero-total')!.textContent).toBe('INR 130.00');
 expect(e.has('actuals-note')).toBe(false);
 expect(e.get('actuals-panel')!.hidden).toBe(false);expect(e.get('transactions-panel')!.hidden).toBe(true);
 click(e,'tab-report');expect(e.get('transactions-panel')!.hidden).toBe(false);expect(e.get('actuals-panel')!.hidden).toBe(false);
 click(e,'view-review');expect(e.get('review-panel')!.hidden).toBe(false);
 click(e,'tab-report');expect(e.get('actuals-panel')!.hidden).toBe(false);expect(e.get('review-panel')!.hidden).toBe(true);
});

test('actuals handle refund-only and empty periods and keep currencies separate',()=>{
 const e=render([{date:'2026-09-01',amount_minor:-20000,kind:'refund'},{date:'2026-09-01',amount_minor:90000,kind:'purchase',currency:'USD'}]);
 click(e,'tab-report');
 input(e,'from','2026-09-01');input(e,'to','2026-09-30');expect(e.get('hero-total')!.textContent).toBe('−INR 200.00');
 input(e,'currency','USD');expect(e.get('hero-total')!.textContent).toBe('USD 900.00');
 input(e,'search','missing');expect(e.get('categories')!.textContent).toContain('No spending');
 expect(e.get('hero-total')!.textContent).toBe('USD 0.00');
});

test('daily chart uses confirmed purchases and observed days without inventing coverage',()=>{
 const e=render([
  {date:'2026-10-22',amount_minor:20000,kind:'purchase',status:'provisional'},
  {date:'2026-10-03',amount_minor:4000,kind:'purchase',status:'posted'},
  {date:'2026-10-04',amount_minor:999900,kind:'purchase',blocked:true},
  {date:'2026-10-05',amount_minor:999900,kind:'transfer_out',excluded_from_spending:true},
  {date:'2026-10-06',amount_minor:999900,kind:'purchase',currency:'USD'}
 ],{from:'2026-10-01',to:'2026-10-23'});
 click(e,'tab-report');
 expect(e.get('hero-total')!.textContent).toBe('INR 170.00');
 expect(e.get('daily-chart')!.children).toHaveLength(22);
 expect(e.has('daily-average')).toBe(false);
 expect(e.has('daily-peak')).toBe(false);
 expect(e.has('daily-note')).toBe(false);
 input(e,'from','2026-10-10');input(e,'month','2026-10');
 expect(e.get('daily-chart')!.children).toHaveLength(13);
 expect(e.get('hero-total')!.textContent).toBe('INR 200.00');
 expect(e.get('hero-label')!.textContent).toBe('Provisional');
 input(e,'search','no matching rows');expect(e.get('daily-chart')!.children).toHaveLength(0);
});

test('report preview, category chips, navigation and row sizing stay independent of actuals',()=>{
 const e=render(Array.from({length:30},(_,i)=>({amount_minor:100,kind:'purchase',category:i%2?'Shopping':'Groceries'})));
 const actuals=e.get('actuals-summary')!.children.slice(1).map(row=>row.textContent);
 click(e,'tab-report');
 expect(e.get('transactions')!.children).toHaveLength(25);expect(e.get('page-size')!.disabled).toBe(false);
 input(e,'page-size','10');expect(e.get('transactions')!.children).toHaveLength(10);
 input(e,'transaction-category','Shopping');
 expect(e.get('page-info')!.textContent).toContain('of 15');expect(e.get('actuals-summary')!.children.slice(1).map(row=>row.textContent)).toEqual(actuals);
 input(e,'transaction-category','');
 input(e,'page-size','25');expect(e.get('transactions')!.children).toHaveLength(25);expect(e.get('page-size')!.disabled).toBe(false);
 click(e,'view-review');expect(e.get('review-panel')!.hidden).toBe(false);
 click(e,'tab-report');expect(e.get('daily-panel')!.hidden).toBe(true);
});

test('real synthetic batch-to-ledger-to-HTML output exposes every source occurrence in All transactions', async () => {
  const { spawnSync } = await import('node:child_process');
  const [python,...prefix] = pythonCommand();
  const run = spawnSync(python, [...prefix, '-X', 'utf8', 'tests/make_completeness_report.py'], {cwd: new URL('..', import.meta.url), encoding:'utf8'});
  expect(run.status).toBe(0);
  const data=JSON.parse(run.stdout);
  const e=render([],data);
  click(e,'tab-report');
  expect(e.get('transactions')!.textContent).toContain('No transactions');
  input(e,'transaction-type','all');
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
    row.children[6].children[0].listeners.click();
    completeness.add(e.get('detail-fields')!.textContent);
  }
  expect([...completeness].some(text=>text.includes('Completeness not verified'))).toBe(true);
  expect([...completeness].some(text=>text.includes('Source coverage complete'))).toBe(true);
  input(e,'transaction-type','spending');
  expect(e.get('transactions')!.textContent).not.toContain('Card repayment');
  expect(e.get('transactions')!.textContent).not.toContain('Own out');
  expect(values(e.get('metrics')!)[0]).toBe('INR 20.00');
  click(e,'view-review');expect(e.get('review-transactions')!.textContent).toContain('Unreadable amount');
});

test('All transactions includes proven duplicate occurrences while spend totals count one movement',()=>{
 const e=render([{merchant:'Bank-side repayment',amount_minor:20000,kind:'repayment',channel:'bank'},
  {merchant:'Linked duplicate occurrence',amount_minor:12000,kind:'purchase',suppressed:true,duplicate_of:{statement:'retained',index:0,evidence:'Same document row'}}]);
 input(e,'transaction-type','all');
 expect(e.get('transactions')!.children).toHaveLength(8);
 expect(e.get('transactions')!.textContent).toContain('Bank-side repayment');
 expect(e.get('transactions')!.textContent).toContain('Linked duplicate occurrence');
 input(e,'transaction-type','spending');expect(values(e.get('metrics')!)[0]).toBe('INR 130.00');
});


test('amount indicators replace the State column and distinguish status without color alone', () => {
  const e=render([
    {merchant:'Pending amount',amount_minor:3000,kind:'purchase',status:'provisional'},
    {merchant:'Unresolved amount',amount_minor:null,kind:'unknown',blocked:true},
    {merchant:'Duplicate amount',amount_minor:12000,kind:'purchase',status:'matched',suppressed:true}
  ]);
  input(e,'transaction-type','all');
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
 input(e,'transaction-type','all');
 expect(e.get('view-note')!.hidden).toBe(true);
 expect(e.get('table-title')!.className).toBe('');
});

test('agent-supplied display notes retain source notation in details without institutional rules',()=>{
 const e=render([{merchant:'Gym membership',original_merchant:'EMI Gym membership',metadata:{display_note:'The agent verified this prefix indicates conversion eligibility.'},category:'Health & fitness',amount_minor:8000,kind:'purchase'}]);
 click(e,'tab-report');input(e,'search','Gym membership');
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
  expect(e.get('hero-in-total')!.textContent).toBe('INR 2,950.00');
  expect(e.get('actuals-summary')!.textContent).toContain('INR 2,950.00');
  input(e,'transaction-type','incoming');
  expect(values(e.get('metrics')!)[0]).toBe('INR 3,010.00');
  expect(e.get('transactions')!.textContent).toContain('Backfilled salary credit');
  expect(e.get('transactions')!.textContent).toContain('External bank transfer');
  expect(e.get('transactions')!.textContent).not.toContain('Confirmed own transfer');
  expect(e.get('transactions')!.textContent).not.toContain('Blocked incoming');
  input(e,'transaction-type','transfers');
  expect(e.get('transactions')!.children).toHaveLength(1);
  expect(e.get('transactions')!.textContent).toContain('Confirmed own transfer');
  click(e,'view-review');
  expect(e.get('review-transactions')!.textContent).toContain('Unverified outgoing');
  const row=e.get('review-transactions')!.children.find(r=>r.children[0].children[0].textContent==='Unverified outgoing')!;
  row.children.at(-1)!.listeners.click();
  expect(e.get('detail-fields')!.textContent).toContain('Check if this was your own account');
  input(e,'from','2026-09-01');input(e,'to','2026-09-30');
  expect(e.get('hero-in-total')!.textContent).toBe('INR 0.00');
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
 expect(item('Unreadable row').textContent).not.toContain("Couldn’t read the amount.");
 expect(item('Balance mismatch').textContent).toContain('Closing balance differs by INR 5.00');
  expect(item('Unknown category').textContent).toContain('amount still counts as spending');
 expect(item('Staged row').textContent).toContain('statement hasn’t been imported yet');
 expect(item('Outgoing review').textContent).toContain('Is the receiving account yours?');
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
 expect(e.get('review-panel')!.hidden).toBe(false);
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
   e.get('transactions')!.children.find(row=>row.children[1].children[0].textContent===merchant)!.children[6].children[0].listeners.click();
   return e.get('detail-fields')!.textContent;
 };
 expect(detail('unverified')).toContain('couldn’t check whether this statement is complete');
 expect(detail('gap')).toContain('Page 4 was not extracted.');
 expect(detail('complete')).toContain('Source coverage complete');
 expect(detail('complete')).toContain('Resolved');
});

test('details retain all mailbox occurrences, direct email sources and unresolved rows safely',()=>{
 const unsafe='<img src=x onerror=alert(1)>';
 const source={mailbox:'box-a',message_id:'message-a',filename:unsafe};
 const e=render([
  {merchant:'Duplicate source',statement:'multi',kind:'purchase',amount_minor:12000,suppressed:true,duplicate_of:{statement:'test-statement',index:0,evidence:'same row'}},
  {merchant:'Alert source',statement:'none',kind:'purchase',amount_minor:200,status:'provisional',source:{mailbox_id:'box-c',message_id:'alert-c',filename:'email-body'}},
  {merchant:'Unresolved source',statement:'multi',kind:'unknown',amount_minor:null,blocked:true}
 ],{statements:[{id:'multi',period:'Sep 2026',source,sources:[source,source,{mailbox:'box-b',message_id:'message-b',filename:'copy.pdf'}]}]});
 input(e,'transaction-type','all');
 const rows=e.get('transactions')!.children;
 const sourceLink=(merchant:string)=>rows.find(row=>row.children[1].children[0].textContent===merchant)!.children[6].children[0];
 expect(rows.find(row=>row.children[1].textContent==='Duplicate source')!.children[1].children).toHaveLength(1);
 sourceLink('Duplicate source').listeners.click();
 expect(e.get('detail-fields')!.textContent).toContain(unsafe);
 expect(e.get('detail-fields')!.textContent).toContain('box-a');expect(e.get('detail-fields')!.textContent).toContain('box-b');
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
  input(e,'transaction-type','all');
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
  expect(e.get('hero-label')!.textContent).toBe('Provisional');
  expect(e.get('hero-total')!.textContent).toBe('INR 120.00');
  expect(e.has('hero-caption')).toBe(false);
  expect(e.get('hero-provisional')!.hidden).toBe(true);
  expect(e.has('actuals-note')).toBe(false);
  expect(e.get('expenses-title')!.textContent).toBe('Show more');
  expect(e.get('categories')!.children.map(row=>row.children[2].textContent)).toEqual(['INR 100.00','INR 20.00']);
  expect(e.get('category-total')!.textContent).toBe('INR 145.00');
  expect(e.get('category-caption')!.textContent).toContain('Provisional');
  expect(e.get('daily-chart')!.attributes['aria-label']).toBe('Daily provisional spending');
  expect(e.get('daily-chart')!.children.some(bar=>bar.attributes['aria-label'].includes('INR 145.00 provisional spending'))).toBe(true);
  expect(e.get('hero-in-status')!.textContent).toBe('Provisional');
  expect(e.get('hero-in-total')!.textContent).toBe('INR 300.00');
  click(e,'tab-report');
  expect(values(e.get('metrics')!)).toEqual(['INR 0.00','INR 120.00','INR 120.00','INR 25.00']);
});

test('a confirmed net zero remains confirmed even when provisional spending exists', () => {
  const e=neutralRender([
    {amount_minor:10000,kind:'purchase'},
    {amount_minor:-10000,kind:'refund'},
    {amount_minor:50000,status:'provisional'}
  ]);
  expect(e.get('hero-label')!.textContent).toBe('');
  expect(e.get('hero-total')!.textContent).toBe('INR 0.00');
  expect(e.get('hero-provisional')!.textContent).toBe('Provisional net INR 500.00');
  expect(e.get('category-total')!.textContent).toBe('INR 100.00');
  expect(e.get('daily-chart')!.attributes['aria-label']).toBe('Daily confirmed spending');
});

test('an explicit confirmed zero and a provisional zero both retain their evidence state', () => {
  const confirmed=neutralRender([{amount_minor:0},{amount_minor:5000,status:'provisional'}]);
  expect(confirmed.get('hero-label')!.textContent).toBe('');
  expect(confirmed.get('hero-total')!.textContent).toBe('INR 0.00');
  const provisional=neutralRender([{amount_minor:1000,status:'provisional'},
    {amount_minor:-1000,kind:'refund',status:'provisional'}]);
  expect(provisional.get('hero-label')!.textContent).toBe('Provisional');
  expect(provisional.get('hero-total')!.textContent).toBe('INR 0.00');
});

test('fallback follows account and currency filters and returns to confirmed amounts when available', () => {
  const e=neutralRender([
    {account:'Account A',account_key:'a',amount_minor:1000},
    {account:'Account B',account_key:'b',amount_minor:5500,status:'provisional'},
    {account:'Account B',account_key:'b',currency:'JPY',exponent:0,amount_minor:321,status:'provisional'}
  ]);
  input(e,'currency','INR');
  expect(e.get('hero-label')!.textContent).toBe('');
  expect(e.get('hero-total')!.textContent).toBe('INR 10.00');
  input(e,'account','b');
  expect(e.get('hero-label')!.textContent).toBe('Provisional');
  expect(e.get('hero-total')!.textContent).toBe('INR 55.00');
  input(e,'currency','JPY');
  expect(e.get('hero-total')!.textContent).toBe('JPY 321');
  input(e,'currency','INR');input(e,'account','a');
  expect(e.get('hero-label')!.textContent).toBe('');
  expect(e.get('hero-total')!.textContent).toBe('INR 10.00');
});

test('confirmed income does not hide provisional expenses and income fallback is labeled separately', () => {
  const e=neutralRender([{amount_minor:-10000,kind:'credit'},
    {amount_minor:2500,status:'provisional'}]);
  expect(e.get('hero-label')!.textContent).toBe('Provisional');
  expect(e.get('hero-total')!.textContent).toBe('INR 25.00');
  expect(e.get('hero-in-label')!.textContent).toBe('Money in');
  expect(e.get('hero-in-total')!.textContent).toBe('INR 100.00');
  expect(e.get('hero-metrics')!.children[1].children[0].textContent).toBe('Net bank cashflow');
  const incoming=neutralRender([{amount_minor:1000},
    {amount_minor:-2000,kind:'credit',status:'provisional'}]);
  expect(incoming.get('hero-label')!.textContent).toBe('');
  expect(incoming.get('hero-in-status')!.textContent).toBe('Provisional');
  expect(incoming.get('hero-in-total')!.textContent).toBe('INR 20.00');
});

test('the two headline totals retain independent pending amounts and follow the selected currency', () => {
  const e=neutralRender([
    {amount_minor:-10000,kind:'credit'},
    {amount_minor:-2500,kind:'credit',status:'provisional'},
    {amount_minor:4000},
    {amount_minor:900,status:'provisional'},
    {amount_minor:-20000,kind:'credit',currency:'USD'},
  ]);
  input(e,'currency','INR');
  expect(e.get('hero-in-label')!.textContent).toBe('Money in');
  expect(e.get('hero-out-label')!.textContent).toBe('Money out');
  expect(e.get('hero-in-total')!.textContent).toBe('INR 100.00');
  expect(e.get('hero-total')!.textContent).toBe('INR 40.00');
  expect(e.get('hero-in-status')!.textContent).toBe('');
  expect(e.get('hero-in-provisional')!.hidden).toBe(false);
  expect(e.get('hero-in-provisional')!.textContent).toBe('Provisional money in INR 25.00');
  expect(e.get('hero-provisional')!.textContent).toBe('Provisional net INR 9.00');
  input(e,'currency','USD');
  expect(e.get('hero-in-total')!.textContent).toBe('USD 200.00');
  expect(e.get('hero-total')!.textContent).toBe('USD 0.00');
  expect(e.get('hero-in-provisional')!.hidden).toBe(true);
  expect(e.get('hero-provisional')!.hidden).toBe(true);
});

test('blocked and statement-covered rows cannot become provisional fallback amounts', () => {
  const e=neutralRender([{amount_minor:7000,status:'draft',blocked:true},
    {amount_minor:8000,status:'statement_covered'},{amount_minor:9000,status:'matched',suppressed:true}]);
  expect(e.get('hero-label')!.textContent).toBe('');
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
  expect(e.get('hero-label')!.textContent).toBe('');
  expect(e.get('hero-total')!.textContent).toBe('INR 12.00');
  e.get('transactions')!.children[0].children[6].children[0].listeners.click();
  expect(e.get('detail-fields')!.textContent).toContain('Statement coverageCompleteness not verified');
  expect(e.get('detail-fields')!.textContent).toContain('Account section completenessSection coverage complete');
  click(e,'view-review');
  expect(e.get('review-groups')!.textContent).toContain(documentGap);
});

test('44-row cashflow fixture preserves withdrawals, salary, interest, and repayments in the report', () => {
  // Normalized synthetic report data keeps UI coverage independent of runtime changes.
  const data=JSON.parse(readFileSync(new URL('./fixtures/report-investment-cashflow.json',import.meta.url),'utf8')),e=render([],data);
  expect(data.rows).toHaveLength(44);
  expect(e.get('hero-total')!.textContent).toBe('INR 29.00');
  expect(e.get('hero-in-total')!.textContent).toBe('INR 2,001.25');
  expect(e.get('hero-metrics')!.children.every(card=>card.children.length===2)).toBe(true);
  expect(e.has('cashflow-note')).toBe(false);
  expect(e.get('cashflow-summary')!.textContent).toContain('Investment withdrawalINR 1,100.00');
  expect(e.get('cashflow-summary')!.textContent).toContain('InvestmentINR 500.00');
  expect(e.get('cashflow-summary')!.textContent).toContain('Net bank cashflowINR 2,272.25');
  input(e,'transaction-type','cashflow');input(e,'page-size','100');
  expect(e.get('transactions')!.children).toHaveLength(44);
  const withdrawals=e.get('transactions')!.children.filter(r=>r.children[1].textContent.includes('FD withdrawal'));
  expect(withdrawals).toHaveLength(11);
  expect(e.get('transactions')!.textContent).toContain('Salary');
  expect(e.get('transactions')!.textContent).toContain('Posted interest');
  expect(e.get('transactions')!.textContent).toContain('Card repayment');
  expect(values(e.get('metrics')!)).toEqual(['INR 3,101.25','INR 829.00','INR 2,272.25','INR 0.00']);
  withdrawals[0].children[6].children[0].listeners.click();
  expect(e.get('detail-fields')!.textContent).toContain('Investment principal');
  expect(e.get('detail-fields')!.textContent).toContain('observed-ref-');
  expect(e.get('detail-fields')!.textContent).toContain('Section coverage complete');
  expect(e.get('detail-fields')!.textContent).toContain('Balance snapshot only');
  input(e,'transaction-type','incoming');
  expect(values(e.get('metrics')!)[0]).toBe('INR 2,001.25');
  expect(e.get('transactions')!.textContent).not.toContain('FD withdrawal');
  input(e,'transaction-type','transfers');
  expect(e.get('transactions')!.textContent).not.toContain('FD withdrawal');
});

test('bank cashflow excludes card entries and blocked duplicates while retaining repayments and principal', () => {
  const bank={account_type:'bank_account'};
  const e=neutralRender([
    {...bank,merchant:'Salary',amount_minor:-100000,kind:'credit'},
    {...bank,merchant:'Principal',amount_minor:-20000,kind:'credit',accounting_treatment:'investment_withdrawal',excluded_from_spending:true,excluded_from_income:true},
    {...bank,merchant:'Bill repayment',amount_minor:30000,kind:'repayment'},
    {...bank,merchant:'Other expense',amount_minor:1000,kind:'debit',category:'Other'},
    {...bank,merchant:'Invalid',amount_minor:-900000,kind:'credit',blocked:true},
    {...bank,merchant:'Duplicate',amount_minor:-900000,kind:'credit',suppressed:true},
    {account_type:'credit_card',merchant:'Card purchase',amount_minor:8000},
    {...bank,merchant:'Outside',amount_minor:1000,date:'2026-09-01'},
  ],{covered_alerts:[{date:'2026-10-24',currency:'INR',account_key:'opaque'}]});
  click(e,'tab-report');
  input(e,'from','2026-10-01');
  expect(e.get('hero-metrics')!.children[1].textContent).toContain('INR 890.00');
  const audit=e.get('accounting-exclusions')!.textContent;
  expect(audit).toContain('1 · Can’t be verified');
  expect(audit).toContain('1 · No category');
  expect(audit).toContain('1 · Transfers and repayments');
  expect(audit).toContain('1 · Investments');
  expect(audit).toContain('1 · Duplicates');
  expect(audit).toContain('1 · Alerts matched to a statement');
  expect(audit).toContain('1 · Outside your dates');
  input(e,'transaction-type','cashflow');
  expect(e.get('transactions')!.children).toHaveLength(4);
  expect(e.get('transactions')!.textContent).not.toContain('Card purchase');
  expect(e.get('transactions')!.textContent).not.toContain('Invalid');
  input(e,'transaction-type','spending');
  expect(values(e.get('metrics')!)[0]).toBe('INR 90.00');
});


test('category expansion continues the same rows without replacing or repeating the preview',()=>{
 const e=render(Array.from({length:7},(_,i)=>({category:'Extra '+i,amount_minor:(i+1)*10000,kind:'purchase'})));
 click(e,'tab-report');
 expect(e.get('categories')!.children).toHaveLength(3);
 const preview=e.get('categories')!.children.slice();
 expect(e.get('actual-expenses')!.children).toHaveLength(6);
 expect(new Set([...e.get('categories')!.children,...e.get('actual-expenses')!.children].map(row=>row.children[1].textContent)).size).toBe(9);
 expect(e.get('actual-expenses')!.textContent).toContain('Extra 0');
 expect(e.get('expenses-panel')!.hidden).toBe(true);
 click(e,'expenses-title');expect(e.get('expenses-panel')!.hidden).toBe(false);
 expect(e.get('categories')!.children).toEqual(preview);
 expect(e.get('categories')!.hidden).toBe(false);expect(e.get('expenses-title')!.textContent).toBe('Show less');
 click(e,'expenses-title');expect(e.get('categories')!.hidden).toBe(false);
 expect(html).toContain('aria-controls="expenses-panel"');
 expect(html).not.toContain('data-component="expenses"');
 expect(html).not.toContain('data-component="cashflow"');
 expect(e.get('cashflow-summary')!.textContent).toContain('Bank inflows');
 e.get('categories')!.children[0].listeners.click();
 expect(e.get('tab-report')!.attributes['aria-pressed']).toBe('true');
});


test('shared report filters keep values and restore controls when switching pages',()=>{
 const e=render();
 click(e,'tab-report');
 input(e,'state','provisional');
 e.get('glance-filter-menu')!.open=true;
 input(e,'account','synthetic');
 expect(e.get('glance-filter-menu')!.open).toBe(true);
 expect(e.get('glance-filter-count')!.textContent).toBe('2');
 click(e,'tab-glance');
 expect(e.get('secondary-filter-fields')!.hidden).toBe(true);
 expect(e.get('glance-filter-menu')!.parentElement!.id).toBe('glance-filters');
 click(e,'tab-report');
 expect(e.get('secondary-filter-fields')!.parentElement!.id).toBe('glance-filter-fields');
 expect(e.get('secondary-filter-fields')!.hidden).toBe(false);
 expect(e.get('account-filter')!.parentElement!.id).toBe('glance-filter-fields');
 expect(e.get('account')!.value).toBe('synthetic');
 expect(e.get('state')!.value).toBe('provisional');
});


test('three-page navigation opens all transactions in Report within the selected glance scope',()=>{
 const e=render([{date:'2026-09-20',merchant:'Earlier purchase',kind:'purchase',amount_minor:9999}]);
 expect(e.has('tab-transactions')).toBe(false);
 input(e,'month','2026-10');input(e,'account','synthetic');
 input(e,'search','stale search');input(e,'state','provisional');
 click(e,'glance-transactions');
 expect(e.get('tab-report')!.attributes['aria-pressed']).toBe('true');
 expect(e.get('report-title')!.textContent).toBe('Report');
 expect(e.get('actuals-panel')!.hidden).toBe(false);
 expect(e.get('transactions-panel')!.hidden).toBe(false);
 expect(e.get('movement-views')!.hidden).toBe(false);
 expect(e.get('transaction-type')!.value).toBe('all');
 expect(e.get('from')!.value).toBe('2026-10-01');expect(e.get('to')!.value).toBe('2026-10-31');
 expect(e.get('account')!.value).toBe('synthetic');
 expect(e.get('transactions')!.textContent).not.toContain('Earlier purchase');
 expect(e.get('search')!.value).toBe('');expect(e.get('state')!.value).toBe('');
});


test('glance keeps totals and chart tooltips without descriptive clutter',()=>{
 const e=render([{category:'Other',kind:'purchase',amount_minor:100}]);
 expect(e.get('hero-in-status')!.hidden).toBe(true);expect(e.get('hero-label')!.hidden).toBe(true);
 for(const id of ['daily-average','daily-peak','daily-facts'])expect(e.has(id)).toBe(false);
 expect(html).not.toContain('class="money-definition"');
 expect(html).not.toContain('Statement confirmation describes transaction evidence');
 expect(html).toContain('>See full report ↗</button>');
 expect(e.get('glance-review')!.textContent).toBe('1 transaction and 1 source issue to review ↗');
 const bar=e.get('daily-chart')!.children[0];bar.listeners.click();
 expect(e.get('chart-tooltip')!.hidden).toBe(false);expect(e.get('chart-tooltip')!.textContent).toBe(bar.attributes['aria-label']);
 const provisional=render([],{rows:[{date:'2026-10-01',currency:'INR',exponent:2,kind:'purchase',status:'provisional',amount_minor:9000,category:'Shopping'}]});
 expect(provisional.get('hero-label')!.hidden).toBe(false);expect(provisional.get('hero-label')!.textContent).toBe('Provisional');
});


test('Review shares report filters and combines source and transaction issues in one card',()=>{
 const e=render([{merchant:'Needs a category',category:'Other',kind:'purchase',amount_minor:9000}]);
 expect(e.has('monthly-panel')).toBe(false);expect(e.has('overview')).toBe(false);
 click(e,'view-review');
 expect(e.get('transactions-panel')!.hidden).toBe(true);expect(e.get('review-panel')!.hidden).toBe(false);
 expect(e.get('review-transactions')!.parentElement!.id).toBe('review-transaction-section');
 expect(e.get('transaction-pagination')!.parentElement!.id).toBe('review-transaction-section');
 expect(e.get('transaction-detail')!.parentElement!.id).toBe('review-transaction-section');
 expect(e.get('review-source-section')!.hidden).toBe(false);
 expect(e.get('report-date-range')!.hidden).toBe(false);expect(e.get('month-filter')!.hidden).toBe(true);
 expect(e.get('glance-filter-menu')!.parentElement!.id).toBe('report-heading');
 expect(e.get('secondary-filter-fields')!.parentElement!.id).toBe('glance-filter-fields');
 input(e,'search','Needs a category');expect(e.get('review-transactions')!.textContent).toContain('Needs a category');
 click(e,'tab-report');
 expect(e.get('transaction-pagination')!.parentElement!.id).toBe('transactions-panel');
 expect(e.get('transaction-detail')!.parentElement!.id).toBe('transactions-panel');
 expect(e.get('review-panel')!.hidden).toBe(true);expect(e.get('transaction-table')!.hidden).toBe(false);
});


test('Customize offers only basic appearance controls and closes without changing reports',()=>{
 const e=render();
 const total=e.get('hero-total')!.textContent;
 click(e,'edit-report');
 expect(e.get('report-editor')!.open).toBe(true);
 expect(e.get('edit-report')!.attributes['aria-expanded']).toBe('true');
 expect(html).toContain('<dialog id="report-editor"');
 for(const id of ['design-layout','design-component','design-component-color','design-chart-1','design-header','design-highlights'])expect(e.has(id)).toBe(false);
 expect(e.get('hero-total')!.textContent).toBe(total);
 click(e,'close-customize');
 expect(e.get('report-editor')!.open).toBe(false);
 expect(e.get('edit-report')!.attributes['aria-expanded']).toBe('false');
 expect(e.get('design-dark-mode')!.attributes['aria-checked']).toBe('false');
});


test('dark mode persists and restores both custom palettes without changing report data',()=>{
 const storage=new Map<string,string>();
 const e=render([],{},storage),total=e.get('hero-total')!.textContent;
 input(e,'design-accent','#446655');
 click(e,'design-dark-mode');
 expect(e.get('design-dark-mode')!.attributes['aria-checked']).toBe('true');
 expect(e.get('design-background')!.value).toBe('#17231d');
 expect(e.get('actuals-panel')!.style['--surface']).toBe('#213128');
 expect(e.get('hero-total')!.textContent).toBe(total);
 input(e,'design-cards','#263a30');
 click(e,'design-dark-mode');
 expect(e.get('design-dark-mode')!.attributes['aria-checked']).toBe('false');
 expect(e.get('design-accent')!.value).toBe('#446655');
 expect(e.get('design-cards')!.value).toBe('#fffefa');
 click(e,'design-dark-mode');
 const reloaded=render([],{},storage);
 expect(reloaded.get('design-dark-mode')!.attributes['aria-checked']).toBe('true');
 expect(reloaded.get('design-cards')!.value).toBe('#263a30');
 click(reloaded,'design-dark-mode');expect(reloaded.get('design-accent')!.value).toBe('#446655');
 click(reloaded,'reset-design');
 const reset=render([],{},storage);
 expect(reset.get('design-dark-mode')!.attributes['aria-checked']).toBe('false');
 expect(reset.get('design-accent')!.value).toBe('#2d483b');
});

test('date and filter popovers share the available height and never stay open together', () => {
  const e=render();click(e,'tab-report');
  e.get('glance-filter-menu')!.open=true;
  click(e,'date-range-toggle');
  expect(e.get('glance-filter-menu')!.open).toBe(false);
  expect(e.get('date-range-popover')!.style.maxHeight).toBe('656px');
  e.get('report-date-range')!.open=true;
  click(e,'glance-filter-toggle');
  expect(e.get('report-date-range')!.open).toBe(false);
  expect(e.get('glance-filter-fields')!.style.maxHeight).toBe('656px');
});
