import { test, expect } from 'bun:test';
import { readFileSync } from 'node:fs';
import { runInNewContext } from 'node:vm';

const html = readFileSync(new URL('../skills/moneylens-automation/assets/report-template.html', import.meta.url), 'utf8');
class Element {
  children: Element[] = [];
  className = ''; value = ''; hidden = true; colSpan = 0;
  style: Record<string,string> = {};
  listeners: Record<string,() => void> = {};
  private text = '';
  constructor(readonly id = '') {}
  set textContent(value: string) { this.text = value; this.children = []; }
  get textContent(): string { return this.text + this.children.map(child => child.textContent).join(''); }
  append(...children: Element[]) {
    if (this.id === 'currency' && !this.children.length && children.length) this.value = children[0].value;
    this.children.push(...children);
  }
  replaceChildren(...children: Element[]) { this.children = []; this.text = ''; this.append(...children); }
  addEventListener(name: string, callback: () => void) { this.listeners[name] = callback; }
}
function render() {
  const elements = new Map([...html.matchAll(/\bid="([^"]+)"/g)].map(match => [match[1], new Element(match[1])]));
  const row = { date:'2026-10-01', merchant:'Synthetic merchant', category:'Groceries', page:1, row:'1',
    account:'Synthetic card', account_key:'synthetic', currency:'INR', exponent:2, status:'imported', blocked:false, suppressed:false, channel:'card' };
  const rows = [
    {...row, amount_minor:12000, kind:'purchase', note:'Personal test note'},
    {...row, amount_minor:-1000, kind:'refund'},
    {...row, amount_minor:-5000, kind:'payment'},
    {...row, amount_minor:2000, kind:'upi_debit', channel:'upi', status:'posted', category:'Transport'},
    {...row, amount_minor:-5000, kind:'upi_credit', channel:'upi', status:'posted'},
    {...row, amount_minor:12000, kind:'purchase', status:'matched', suppressed:true}
  ];
  elements.get('data')!.textContent = JSON.stringify({rows, statements:[], from:'', to:'', generated:null, sync:{}, review_items:[{group:'Source checks', reason:'Synthetic review', message_id:'synthetic'}]});
  const script = [...html.matchAll(/<script>\s*([\s\S]*?)<\/script>/g)].at(-1)![1];
  runInNewContext(script, {document:{ getElementById:(id:string) => elements.get(id), createElement:() => new Element() }});
  return elements;
}
const values = (element: Element) => element.children.map(child => child.children[1].textContent);

test('compiled single-file report preserves spend, refund and UPI accounting', () => {
  const elements = render();
  expect(values(elements.get('metrics')!)).toEqual(['INR 140.00','INR 10.00','INR 130.00','5']);
  expect(values(elements.get('upi-metrics')!)).toEqual(['INR 20.00','INR 50.00']);
  expect(elements.get('transactions')!.children).toHaveLength(5);
  expect(elements.get('transactions')!.children[0].children).toHaveLength(8);
  expect(elements.get('review-summary')!.textContent).toBe('Items to review · 1');
});

test('bundled report keeps notes searchable and filters responsive', () => {
  const elements = render();
  const search=elements.get('search')!;
  search.value='Personal test note';search.listeners.input();
  expect(elements.get('transactions')!.children).toHaveLength(1);
  expect(values(elements.get('metrics')!)[0]).toBe('INR 120.00');
  search.value='missing';search.listeners.input();
  expect(elements.get('transactions')!.children[0].children[0].colSpan).toBe(8);
  search.value='';search.listeners.input();
  const channel=elements.get('channel')!;channel.value='upi';channel.listeners.input();
  expect(values(elements.get('metrics')!)).toEqual(['INR 20.00','INR 0.00','INR 20.00','2']);
});

test('release template contains no user data or external asset dependencies', () => {
  const data = JSON.parse(html.match(/<script id="data" type="application\/json">(.*?)<\/script>/s)![1]);
  expect(data.rows).toEqual([]);expect(data.statements).toEqual([]);expect(data.sync).toEqual({});
  expect(html).not.toMatch(/<(?:script|link|img)\b[^>]*(?:src|href)\s*=/i);
  expect(html).not.toContain('Source page / row');expect(html).not.toContain('Included rows:');
  expect(html.indexOf('id="sync-issues"')).toBeGreaterThan(html.indexOf('id="statements"'));
});
