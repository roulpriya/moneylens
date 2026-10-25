import {test,expect} from 'bun:test';
import {readFileSync} from 'node:fs';

const css=readFileSync(new URL('../src/report.css',import.meta.url),'utf8');
const fixedLayout=new Set(['gap','row-gap','column-gap','width','min-width','max-width','height','min-height','max-height','top','right','bottom','left','inset','inset-inline','inset-block','flex','flex-basis','grid-template-columns','grid-template-rows','border-radius','outline-offset','transform','font-size','font','line-height','scroll-margin-top','scroll-padding-top','scroll-padding-bottom','--category-columns','--category-gap']);

test('fixed report spacing, typography and control dimensions stay on the 4px grid',()=>{
 expect(css).toContain('--layout-unit: 4px');
 // The canonical visually-hidden utility deliberately uses 1px geometry.
 const source=css.replace(/\.sr-only\{[^{}]+\}/g,'');
 const violations=[];
 for(const match of source.matchAll(/([\w-]+)\s*:\s*([^;{}]+)(?=[;}])/g)) {
  const [,property,value]=match;
  if(!fixedLayout.has(property)&&!property.startsWith('margin')&&!property.startsWith('padding'))continue;
  for(const px of value.matchAll(/(-?\d*\.?\d+)px/g))if(Number(px[1])%4!==0)violations.push(`${property}: ${value}`);
 }
 expect(violations).toEqual([]);
});
