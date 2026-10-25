import { contrastTokens } from './report-contrast.js';
// Appearance preferences only: no transaction data, account IDs, or credentials.
export const DESIGN_KEY = 'moneylens.report.appearance.v1';
export const COMPONENTS = [
  ['actuals','actuals-panel','Monthly actuals'], ['summary','summary-panel','Summary'], ['categories','spending-breakdown','Category chart'], ['daily','daily-panel','Daily spend'], ['transactions','transactions-panel','Transactions'],
  ['review','review-panel','Source review'],
  ['merchants','merchant-categories','Merchant categories'], ['glance','glance-panel','Recent activity']
];
export const PRESETS = {
  moneylens: {background:'#f7f8f2',cards:'#fffefa',text:'#283b33',accent:'#2d483b',header:'#f7f8f2',highlights:'#eaf0e0',chart:['#9daf7b','#c3d0a7','#78946b','#b9a47a','#91a69b','#b4acbd']},
  paper: {background:'#f4f5f7',cards:'#ffffff',text:'#111418',accent:'#2f4be0',header:'#ffffff',highlights:'#eef0f3',chart:['#1e2a78','#5264f2','#ed8936','#2b9d83','#a58ae8','#e9b930']},
  sage: {background:'#f4f6f1',cards:'#ffffff',text:'#233b2d',accent:'#405f44',header:'#10171b',highlights:'#e7eedf',chart:['#617e58','#c68257','#9990b8','#5c9a9b','#b89b42','#a4b2a1']},
  midnight: {background:'#17231d',cards:'#213128',text:'#f0f5ed',accent:'#b8d8a6',header:'#10171b',highlights:'#314c32',chart:['#aac798','#d7a782','#b9b1d6','#86b9ba','#d1bc79','#a4b2a1']}
};
const fields = ['background','cards','text','accent','header','highlights'];
const editableFields = ['background','cards','text','accent'];
const validColor = value => typeof value === 'string' && /^#[0-9a-f]{6}$/i.test(value);
const fresh = (theme='moneylens') => ({version:1,theme,colors:{...PRESETS[theme],chart:[...PRESETS[theme].chart]},order:COMPONENTS.map(c=>c[0]),components:{}});
export function normalizeDesign(input) {
  const base=fresh(Object.hasOwn(PRESETS,input?.theme)?input.theme:'moneylens');
  if (!input || input.version!==1) return fresh();
  for (const key of fields) if (validColor(input.colors?.[key])) base.colors[key]=input.colors[key];
  if (Array.isArray(input.colors?.chart)) base.colors.chart=base.colors.chart.map((c,i)=>validColor(input.colors.chart[i])?input.colors.chart[i]:c);
  if (Array.isArray(input.order)) base.order=[...new Set(input.order.filter(id=>base.order.includes(id)))].concat(base.order.filter(id=>!input.order.includes(id)));
  for (const [id] of COMPONENTS) if (validColor(input.components?.[id])) base.components[id]=input.components[id];
  for(const key of ['lightAppearance','darkAppearance']) {
    const saved=input[key];
    if(!saved || typeof saved!=='object')continue;
    const theme=key==='darkAppearance'?'midnight':saved.theme==='midnight'?'moneylens':saved.theme;
    const palette=normalizeDesign({version:1,theme,colors:saved.colors,components:saved.components});
    base[key]={theme:palette.theme,colors:palette.colors,components:palette.components};
  }
  return base;
}
function foreground(hex) {
  const rgb=hex.slice(1).match(/../g).map(v=>parseInt(v,16)/255).map(v=>v<=.04045?v/12.92:((v+.055)/1.055)**2.4);
  return rgb[0]*.2126+rgb[1]*.7152+rgb[2]*.0722>.179?'#17231d':'#f4f6f1';
}
export function initializeReportDesign(doc=document) {
  const get=id=>doc.getElementById(id), root=doc.documentElement;
  let storage=null;
  try { storage=globalThis.localStorage; } catch {}
  let raw=null;
  try { const text=storage?.getItem(DESIGN_KEY); if(text && text.length<16384) raw=JSON.parse(text); } catch {}
  let design=normalizeDesign(raw);
  const elements=new Map(COMPONENTS.map(([id,elementId])=>[id,get(elementId)]));
  function message(text) { get('design-status').textContent=text; }
  function save() {
    try {
      if(!storage) throw new Error('Unavailable');
      storage.setItem(DESIGN_KEY,JSON.stringify(design));
      message('Saved in this browser.');
    } catch { message('Browser storage is unavailable. Changes last until reload.'); }
  }
  function surface(id) { return design.components[id] || (id==='highlights'?design.colors.highlights:id==='summary'?design.colors.background:design.colors.cards); }
  function refresh() {}
  function apply() {
    const c=design.colors;
    for(const [key,value] of Object.entries(contrastTokens(c)))root.style.setProperty(key,value);
    for(const [css,key] of [['--bg','background'],['--panel','cards'],['--text','text'],['--accent','accent'],['--accent-soft','highlights'],['--header','header']]) root.style.setProperty(css,c[key]);
    root.style.setProperty('--header-text',foreground(c.header));root.style.setProperty('--accent-ink',foreground(c.accent));
    root.style.setProperty('--muted',`color-mix(in srgb, ${c.text} 78%, ${c.background})`);
    root.style.setProperty('--global-text',c.text);root.style.setProperty('--global-muted',`color-mix(in srgb, ${c.text} 78%, ${c.cards})`);root.style.setProperty('--highlight-text',foreground(c.highlights));
    root.style.setProperty('--text-2',c.text);root.style.setProperty('--panel-2',c.background);
    root.style.setProperty('--line',`color-mix(in srgb, ${c.text} 17%, ${c.cards})`);
    root.style.setProperty('--line-strong',`color-mix(in srgb, ${c.text} 30%, ${c.cards})`);
    root.style.setProperty('--credit',c.accent);root.style.setProperty('--hover',`color-mix(in srgb, ${c.accent} 10%, ${c.cards})`);
    root.style.setProperty('--stripe',c.cards);root.style.setProperty('--in',c.accent);
    root.style.setProperty('--bar-track',c.highlights);
    root.style.colorScheme=design.theme==='midnight'?'dark':'light';
    get('design-dark-mode').setAttribute('aria-checked',String(design.theme==='midnight'));
    c.chart.forEach((color,i)=>root.style.setProperty('--chart-'+(i+1),color));
    for(const [id,element] of elements) {
      const bg=surface(id), text=design.components[id] || id==='highlights'?foreground(bg):c.text;
      element.style.setProperty('--surface',bg);element.style.setProperty('--text',text);element.style.setProperty('--text-2',text);
      element.style.setProperty('--muted',`color-mix(in srgb, ${text} 78%, ${bg})`);
    }
    design.order.forEach(id=>get('report-components').append(elements.get(id)));
    get('design-theme').value=design.theme;editableFields.forEach(key=>get('design-'+key).value=c[key]);

  }
  get('edit-report').addEventListener('click',()=>{
    get('edit-report').setAttribute('aria-expanded','true');
    get('report-editor').showModal();
  });
  get('close-customize').addEventListener('click',()=>get('report-editor').close());
  get('report-editor').addEventListener('close',()=>{
    get('edit-report').setAttribute('aria-expanded','false');
    get('edit-report').focus?.({preventScroll:true});
  });
  const paletteSnapshot=()=>({theme:design.theme,colors:{...design.colors,chart:[...design.colors.chart]},components:{...design.components}});
  get('design-dark-mode').addEventListener('click',()=>{
    const dark=design.theme!=='midnight';
    design[dark?'lightAppearance':'darkAppearance']=paletteSnapshot();
    const saved=design[dark?'darkAppearance':'lightAppearance'];
    const next=normalizeDesign({version:1,theme:dark?'midnight':'moneylens',...saved,order:design.order});
    design={...design,...next};apply();save();
  });
  get('design-theme').addEventListener('change',()=>{
    const theme=get('design-theme').value;if(!PRESETS[theme])return;
    if((theme==='midnight')!==(design.theme==='midnight'))design[design.theme==='midnight'?'darkAppearance':'lightAppearance']=paletteSnapshot();
    const next=fresh(theme);design={...design,...next,order:design.order};apply();save();
  });
  editableFields.forEach(key=>get('design-'+key).addEventListener('input',()=>{
    const color=get('design-'+key).value;if(!validColor(color))return;design.colors[key]=color;apply();save();
  }));
  get('reset-design').addEventListener('click',()=>{
    design=fresh();apply();
    try {if(!storage)throw new Error('Unavailable');storage.removeItem(DESIGN_KEY);message('Default design restored.');}
    catch {message('Defaults restored for this tab. Browser storage is unavailable.');}
  });
  apply();
  return {refresh};
}
