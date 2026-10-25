// Appearance preferences only: no transaction data, account IDs, or credentials.
export const DESIGN_KEY = 'moneylens.report.appearance.v1';
export const COMPONENTS = [
  ['actuals','actuals-panel','Monthly actuals'], ['summary','summary-panel','Summary'], ['categories','spending-breakdown','Category chart'], ['daily','daily-panel','Daily spend'], ['transactions','transactions-panel','Transactions'],
  ['expenses','expenses-panel','Expenses'], ['review','review-panel','Source review'],
  ['monthly','monthly-panel','Monthly totals'],
  ['overview','overview','Overview'], ['merchants','merchant-categories','Merchant categories']
];
const PRESETS = {
  paper: {background:'#f4f5f7',cards:'#ffffff',text:'#111418',accent:'#2f4be0',header:'#ffffff',highlights:'#eef0f3',chart:['#1e2a78','#5264f2','#ed8936','#2b9d83','#a58ae8','#e9b930']},
  sage: {background:'#f4f6f1',cards:'#ffffff',text:'#233b2d',accent:'#405f44',header:'#10171b',highlights:'#e7eedf',chart:['#617e58','#c68257','#9990b8','#5c9a9b','#b89b42','#a4b2a1']},
  midnight: {background:'#17231d',cards:'#213128',text:'#f0f5ed',accent:'#b8d8a6',header:'#10171b',highlights:'#314c32',chart:['#aac798','#d7a782','#b9b1d6','#86b9ba','#d1bc79','#a4b2a1']}
};
const fields = ['background','cards','text','accent','header','highlights'];
const validColor = value => typeof value === 'string' && /^#[0-9a-f]{6}$/i.test(value);
const fresh = (theme='paper') => ({version:1,theme,colors:{...PRESETS[theme],chart:[...PRESETS[theme].chart]},order:COMPONENTS.map(c=>c[0]),components:{}});
export function normalizeDesign(input) {
  const base=fresh(Object.hasOwn(PRESETS,input?.theme)?input.theme:'paper');
  if (!input || input.version!==1) return fresh();
  for (const key of fields) if (validColor(input.colors?.[key])) base.colors[key]=input.colors[key];
  if (Array.isArray(input.colors?.chart)) base.colors.chart=base.colors.chart.map((c,i)=>validColor(input.colors.chart[i])?input.colors.chart[i]:c);
  if (Array.isArray(input.order)) base.order=[...new Set(input.order.filter(id=>base.order.includes(id)))].concat(base.order.filter(id=>!input.order.includes(id)));
  for (const [id] of COMPONENTS) if (validColor(input.components?.[id])) base.components[id]=input.components[id];
  return base;
}
function foreground(hex) {
  const rgb=hex.slice(1).match(/../g).map(v=>parseInt(v,16)/255).map(v=>v<=.04045?v/12.92:((v+.055)/1.055)**2.4);
  return rgb[0]*.2126+rgb[1]*.7152+rgb[2]*.0722>.179?'#17231d':'#f4f6f1';
}
export function initializeReportDesign(doc=document) {
  const get=id=>doc.getElementById(id), root=doc.documentElement;
  let storage=null, editing=false;
  try { storage=globalThis.localStorage; } catch {}
  let raw=null;
  try { const text=storage?.getItem(DESIGN_KEY); if(text && text.length<16384) raw=JSON.parse(text); } catch {}
  let design=normalizeDesign(raw);
  const elements=new Map(COMPONENTS.map(([id,elementId])=>[id,get(elementId)]));
  const controls=new Map();
  function message(text) { get('design-status').textContent=text; }
  function save() {
    try {
      if(!storage) throw new Error('Unavailable');
      storage.setItem(DESIGN_KEY,JSON.stringify(design));
      message('Saved in this browser.');
    } catch { message('Browser storage is unavailable. Changes last until reload.'); }
  }
  function surface(id) { return design.components[id] || (id==='highlights'?design.colors.highlights:['summary','actuals'].includes(id)?design.colors.background:design.colors.cards); }
  function syncComponentColor() { get('design-component-color').value=surface(get('design-component').value||'summary'); }
  function refresh() {
    const visible=design.order.filter(id=>!elements.get(id).hidden);
    for(const [id,bar] of controls) {
      bar.hidden=!editing;
      bar.up.disabled=visible.indexOf(id)<=0;
      bar.down.disabled=visible.indexOf(id)<0 || visible.indexOf(id)===visible.length-1;
    }
  }
  function apply() {
    const c=design.colors;
    for(const [css,key] of [['--bg','background'],['--panel','cards'],['--text','text'],['--accent','accent'],['--accent-soft','highlights'],['--header','header']]) root.style.setProperty(css,c[key]);
    root.style.setProperty('--header-text',foreground(c.header));root.style.setProperty('--accent-ink',foreground(c.accent));
    root.style.setProperty('--muted',`color-mix(in srgb, ${c.text} 74%, ${c.background})`);
    root.style.setProperty('--global-text',c.text);root.style.setProperty('--global-muted',`color-mix(in srgb, ${c.text} 74%, ${c.cards})`);root.style.setProperty('--highlight-text',foreground(c.highlights));
    root.style.setProperty('--text-2',c.text);root.style.setProperty('--panel-2',c.background);
    root.style.setProperty('--line',`color-mix(in srgb, ${c.text} 17%, ${c.cards})`);
    root.style.setProperty('--line-strong',`color-mix(in srgb, ${c.text} 30%, ${c.cards})`);
    root.style.setProperty('--credit',c.accent);root.style.setProperty('--hover',`color-mix(in srgb, ${c.accent} 10%, ${c.cards})`);
    root.style.setProperty('--stripe',c.cards);root.style.setProperty('--in',c.accent);
    root.style.setProperty('--bar-track',c.highlights);
    root.style.colorScheme=design.theme==='midnight'?'dark':'light';
    c.chart.forEach((color,i)=>root.style.setProperty('--chart-'+(i+1),color));
    for(const [id,element] of elements) {
      const bg=surface(id), text=design.components[id] || id==='highlights'?foreground(bg):c.text;
      element.style.setProperty('--surface',bg);element.style.setProperty('--text',text);element.style.setProperty('--text-2',text);
      element.style.setProperty('--muted',`color-mix(in srgb, ${text} 74%, ${bg})`);
    }
    design.order.forEach(id=>get('report-components').append(elements.get(id)));
    get('design-theme').value=design.theme;fields.forEach(key=>get('design-'+key).value=c[key]);
    c.chart.forEach((color,i)=>get('design-chart-'+(i+1)).value=color);
    syncComponentColor();refresh();
  }
  function move(id,delta,trigger) {
    const visible=design.order.filter(key=>!elements.get(key).hidden), index=visible.indexOf(id), target=visible[index+delta];
    if(!target)return;
    design.order=design.order.filter(key=>key!==id);
    const targetIndex=design.order.indexOf(target);design.order.splice(targetIndex+(delta>0?1:0),0,id);
    apply();save();trigger.focus?.({preventScroll:true});
  }
  for(const [id,,label] of COMPONENTS) {
    const bar=doc.createElement(elements.get(id).tagName==='DETAILS'?'span':'div');bar.className='layout-controls';bar.hidden=true;
    const name=doc.createElement('span');name.textContent=label;
    bar.append(name);
    for(const [delta,text] of [[-1,'↑'],[1,'↓']]) {
      const b=doc.createElement('button');b.type='button';b.textContent=text;
      b.setAttribute('aria-label','Move '+label+' '+(delta<0?'up':'down'));
      b.addEventListener('click',()=>move(id,delta,b));bar.append(b);bar[delta<0?'up':'down']=b;
    }
    if(elements.get(id).tagName==='DETAILS') elements.get(id).firstElementChild.append(bar); else elements.get(id).prepend(bar);
    controls.set(id,bar);
    const option=doc.createElement('option');option.value=id;option.textContent=label;get('design-component').append(option);
  }
  get('edit-report').addEventListener('click',()=>{
    editing=!editing;get('report-editor').hidden=!editing;get('edit-report').setAttribute('aria-expanded',String(editing));
    get('edit-report').textContent=editing?'Done':'Edit report';refresh();
  });
  get('design-theme').addEventListener('change',()=>{
    const theme=get('design-theme').value;if(!PRESETS[theme])return;
    const next=fresh(theme);design={...next,order:design.order};apply();save();
  });
  fields.forEach(key=>get('design-'+key).addEventListener('input',()=>{
    const color=get('design-'+key).value;if(!validColor(color))return;design.colors[key]=color;apply();save();
  }));
  for(let i=0;i<6;i++)get('design-chart-'+(i+1)).addEventListener('input',()=>{
    const color=get('design-chart-'+(i+1)).value;if(!validColor(color))return;design.colors.chart[i]=color;apply();save();
  });
  get('design-component').addEventListener('change',syncComponentColor);
  get('design-component-color').addEventListener('input',()=>{
    const id=get('design-component').value,color=get('design-component-color').value;
    if(!elements.has(id)||!validColor(color))return;design.components[id]=color;apply();save();
  });
  get('component-use-theme').addEventListener('click',()=>{delete design.components[get('design-component').value];apply();save();});
  get('reset-design').addEventListener('click',()=>{
    design=fresh();apply();
    try {if(!storage)throw new Error('Unavailable');storage.removeItem(DESIGN_KEY);message('Default design restored.');}
    catch {message('Defaults restored for this tab. Browser storage is unavailable.');}
  });
  apply();
  return {refresh};
}
