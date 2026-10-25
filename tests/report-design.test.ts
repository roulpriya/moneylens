import {test,expect} from 'bun:test';
import {readFileSync} from 'node:fs';
import {normalizeDesign,COMPONENTS} from '../src/report-design.js';

test('new reports default to the website typography and palette',()=>{
 const d=normalizeDesign(null);
 expect(d.theme).toBe('moneylens');
 const shared=readFileSync(new URL('../src/brand.css',import.meta.url),'utf8');
 for(const [key,token] of [['background','paper'],['cards','surface'],['text','ink'],['accent','accent'],['highlights','highlight']]) {
  expect(shared).toContain(`--moneylens-${token}: ${d.colors[key]};`);
 }
 expect(d.colors.header).toBe(d.colors.background);
 expect(d.order).toEqual(COMPONENTS.map(c=>c[0]));
 expect(d.components).toEqual({});
});
test('saved layout is deduplicated, unknown sections ignored, new sections retained',()=>{
 const d=normalizeDesign({version:1,order:['transactions','transactions','unknown','summary']});
 expect(d.order.slice(0,2)).toEqual(['transactions','summary']);
 expect(d.order).toHaveLength(COMPONENTS.length);expect(new Set(d.order).size).toBe(COMPONENTS.length);
});
test('saved colours accept hex only and ignore financial or arbitrary fields',()=>{
 const d=normalizeDesign({version:1,account:'sensitive',colors:{background:'url(https://example.invalid)',accent:'#AA3300',chart:['red','#123456']},components:{transactions:'#334455',categories:'var(--anything)',unknown:'#123456'}});
 expect(d.colors.background).toBe('#f7f8f2');expect(d.colors.accent).toBe('#AA3300');
 expect(d.colors.chart[0]).toBe('#9daf7b');expect(d.colors.chart[1]).toBe('#123456');
 expect(d.components).toEqual({transactions:'#334455'});expect('account' in d).toBe(false);
});
test('unsupported settings reset safely and presets never share mutable colour arrays',()=>{
 expect(normalizeDesign({version:99,theme:'midnight'}).theme).toBe('moneylens');
 const d=normalizeDesign({version:1,theme:'midnight'});d.colors.chart[0]='#000000';
 expect(normalizeDesign({version:1,theme:'midnight'}).colors.chart[0]).toBe('#aac798');
});

test('supported themes retain colours and section order',()=>{
 const d=normalizeDesign({version:1,theme:'sage',colors:{accent:'#123456'},order:['expenses','actuals','categories'],components:{actuals:'#abc123'}});
 expect(d.theme).toBe('sage');expect(d.colors.background).toBe('#f4f6f1');expect(d.colors.accent).toBe('#123456');
 expect(d.order.slice(0,3)).toEqual(['expenses','actuals','categories']);expect(d.order).toContain('daily');expect(d.components.actuals).toBe('#abc123');
});
test('malformed preset names cannot access inherited object properties',()=>{
 expect(normalizeDesign({version:1,theme:'__proto__'}).theme).toBe('moneylens');
 expect(normalizeDesign({version:1,theme:'constructor'}).theme).toBe('moneylens');
});

test('saved Paper preferences retain their theme, colours, and order',()=>{
 const d=normalizeDesign({version:1,theme:'paper',colors:{accent:'#123456'},order:['daily','transactions']});
 expect(d.theme).toBe('paper');expect(d.colors.background).toBe('#f4f5f7');
 expect(d.colors.accent).toBe('#123456');expect(d.order.slice(0,2)).toEqual(['daily','transactions']);
});


test('unknown layout components are rejected without losing valid preferences',()=>{
 const d=normalizeDesign({version:1,order:['highlights','transactions','actuals'],components:{highlights:'#abcdef',transactions:'#123456'}});
 expect(d.order).not.toContain('highlights');
 expect(d.components).toEqual({transactions:'#123456'});
 expect(d.order.slice(0,2)).toEqual(['transactions','actuals']);
});


test('unknown component colours do not alter valid appearance settings',()=>{
 const d=normalizeDesign({version:1,theme:'sage',order:['coverage','transactions','diagnostics','actuals'],components:{coverage:'#abcdef',diagnostics:'#fedcba',transactions:'#123456'}});
 expect(d.theme).toBe('sage');expect(d.order.slice(0,2)).toEqual(['transactions','actuals']);
 expect(d.order).not.toContain('coverage');expect(d.order).not.toContain('diagnostics');
 expect(d.components).toEqual({transactions:'#123456'});
});
