import {expect,test} from 'bun:test';
import {PRESETS} from '../src/report-design.js';
import {contrastRatio,contrastTokens} from '../src/report-contrast.js';

test('WCAG reference ratios and symmetry',()=>{
 expect(contrastRatio('#000000','#ffffff')).toBe(21);
 expect(contrastRatio('#123456','#123456')).toBe(1);
 expect(contrastRatio('#17231d','#ffffff')).toBe(contrastRatio('#ffffff','#17231d'));
});
for(const [name,colors] of Object.entries(PRESETS))test(name+' maintains text, error, focus, chart and switch contrast',()=>{
 const tokens=contrastTokens(colors);
 expect(contrastRatio(colors.text,colors.cards)).toBeGreaterThanOrEqual(4.5);
 expect(contrastRatio(colors.text,colors.background)).toBeGreaterThanOrEqual(4.5);
 expect(contrastRatio(tokens['--error'],colors.cards)).toBeGreaterThanOrEqual(4.5);
 for(const token of ['--control-border','--focus-ring','--chart-ink'])expect(contrastRatio(tokens[token],colors.cards)).toBeGreaterThanOrEqual(3);
 expect(contrastRatio(tokens['--focus-ring'],colors.background)).toBeGreaterThanOrEqual(3);
 expect(contrastRatio(tokens['--header-focus'],colors.header)).toBeGreaterThanOrEqual(3);
 expect(contrastRatio(tokens['--control-ink'],tokens['--control-border'])).toBeGreaterThanOrEqual(3);
});
test('low contrast custom accents still get visible focus and chart boundaries',()=>{
 const tokens=contrastTokens({...PRESETS.moneylens,accent:'#fffefa'});
 expect(contrastRatio(tokens['--focus-ring'],PRESETS.moneylens.cards)).toBeGreaterThanOrEqual(3);
 expect(contrastRatio(tokens['--chart-ink'],PRESETS.moneylens.cards)).toBeGreaterThanOrEqual(3);
});
