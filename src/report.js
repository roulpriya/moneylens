'use strict';
const data=JSON.parse(document.getElementById('data').textContent), $=id=>document.getElementById(id);
function node(tag,text,cls){const e=document.createElement(tag);if(text!==undefined)e.textContent=text;if(cls)e.className=cls;return e}
function money(amount,exp,code){amount=BigInt(amount);const negative=amount<0n;if(negative)amount=-amount;const scale=10n**BigInt(exp),whole=(amount/scale).toString().replace(/\B(?=(\d{3})+(?!\d))/g,',');return (negative?'−':'')+code+' '+whole+(exp?'.'+(amount%scale).toString().padStart(exp,'0'):'')}
function sum(rows,predicate=()=>true){return rows.reduce((total,r)=>total+(predicate(r)?BigInt(r.amount_minor):0n),0n)}
function option(id,value,label){const e=node('option',label);e.value=value;$(id).append(e)}
const currencies=[...new Set(data.rows.map(r=>r.currency))].sort();currencies.forEach(c=>option('currency',c,c));if(!currencies.length)option('currency','','No transactions');
[...new Set(data.rows.map(r=>r.date.slice(0,7)))].sort().reverse().forEach(m=>option('month',m,m));
const accounts=new Map(data.rows.map(r=>[r.account_key,r.account]));accounts.forEach((label,key)=>option('account',key,label));
$('from').value=data.from;$('to').value=data.to;
function update(){
 const code=$('currency').value,month=$('month').value,account=$('account').value,state=$('state').value,query=$('search').value.toLowerCase();
 const visible=data.rows.filter(r=>(!$('channel').value||r.channel===$('channel').value)&&(!code||r.currency===code)&&(!month||r.date.startsWith(month))&&(!account||r.account_key===account)&&(!state?!r.suppressed:(state==='unresolved'?r.blocked:r.status===state))&&(!$('from').value||r.date>=$('from').value)&&(!$('to').value||r.date<=$('to').value)&&(!query||(r.merchant+' '+r.category+' '+(r.note||'')+' '+(r.personal_context||'')).toLowerCase().includes(query)));
 const included=visible.filter(r=>!r.blocked&&!r.suppressed),exp=visible[0]?.exponent??data.rows.find(r=>r.currency===code)?.exponent??2,fmt=n=>money(n,exp,code||'');
 const gross=sum(included,r=>['purchase','fee','interest','cash_advance','adjustment_debit','upi_debit'].includes(r.kind)),refunds=-sum(included,r=>['refund','adjustment_credit'].includes(r.kind));
 const metrics=[['Spending',gross,'Before refunds'],['Refunds and credits',refunds,'Returned to you'],['Net spending',gross-refunds,'After refunds'],['Transactions',BigInt(included.length),'In this view']];
 $('metrics').replaceChildren(...metrics.map(([label,value,hint],i)=>{const card=node('div',undefined,'card');card.append(node('div',label,'label'),node('div',i===3?value.toString():fmt(value),'value'),node('div',hint,'muted'));return card}));
 const upiRows=included.filter(r=>r.channel==='upi');
 $('upi-metrics').replaceChildren(...[['UPI debits',sum(upiRows,r=>r.amount_minor>0),'Money out'],['UPI credits',-sum(upiRows,r=>r.amount_minor<0),'Money in']].map(([label,value,hint])=>{const card=node('div',undefined,'card');card.append(node('div',label,'label'),node('div',fmt(value),'value'),node('div',hint,'muted'));return card}));
 const category=new Map();included.filter(r=>r.amount_minor>0&&['purchase','fee','interest','cash_advance','adjustment_debit','upi_debit'].includes(r.kind)).forEach(r=>category.set(r.category,(category.get(r.category)||0n)+BigInt(r.amount_minor)));
 const cats=[...category].sort((a,b)=>a[1]>b[1]?-1:a[1]<b[1]?1:0);$('categories').replaceChildren(...cats.map(([label,value])=>{const item=node('div',undefined,'barrow'),line=node('div',undefined,'barline'),track=node('div',undefined,'track'),fill=node('div',undefined,'fill');line.append(node('span',label),node('span',fmt(value)));fill.style.width=(gross>0n?Number(value*10000n/gross)/100:0)+'%';track.append(fill);item.append(line,track);return item}));if(!cats.length)$('categories').append(node('p','No eligible spending in this view.','muted'));
 const monthly=new Map();included.filter(r=>['purchase','fee','interest','cash_advance','adjustment_debit','upi_debit','refund','adjustment_credit'].includes(r.kind)).forEach(r=>{const key=r.date.slice(0,7),amount=BigInt(r.amount_minor),v=monthly.get(key)||[0n,0n];if(amount>0n)v[0]+=amount;v[1]+=amount;monthly.set(key,v)});
 $('months').replaceChildren(...[...monthly].sort((a,b)=>b[0].localeCompare(a[0])).map(([m,v])=>{const tr=node('tr');[m,fmt(v[0]),fmt(v[1])].forEach(x=>tr.append(node('td',x)));return tr}));
 $('transactions').replaceChildren(...[...visible].sort((a,b)=>b.date.localeCompare(a.date)).map(r=>{const tr=node('tr');[r.date,r.merchant,r.category,[r.note,r.personal_context].filter(Boolean).filter((x,i,a)=>a.indexOf(x)===i).join(' · '),r.kind.replaceAll('_',' '),fmt(r.amount_minor),r.account,r.blocked?'Needs review':r.status==='provisional'?'Provisional alert':r.status==='matched'?'Reconciled':r.status==='draft'?'Staged':'Saved'].forEach((x,i)=>tr.append(node('td',x,i===1||i===3?'merchant':undefined)));return tr}));
 if(!visible.length){const tr=node('tr'),td=node('td','No transactions match these filters.');td.colSpan=8;tr.append(td);$('transactions').append(tr)}
}
$('statements').replaceChildren(...data.statements.map(s=>{const div=node('div',undefined,'source');div.append(node('strong',s.account+' · '+s.currency+' · '+s.period+(s.record_type==='upi'?' · UPI bank activity':s.record_type==='alert'?' · Card alert':' · Statement')),node('div',s.status.toUpperCase()+' · '+s.id,'muted'),node('div','Source: Gmail message '+s.source.message_id+' / '+s.source.filename,'muted'));if(s.checks.issues.length)div.append(node('div',s.checks.issues.join(' · '),'warn'));div.append(node('div','Passed: '+(s.checks.passed_checks.join(', ')||'No independent checks')+'. Unavailable: '+(s.checks.unavailable_checks.join(', ')||'None')+'.','muted'));if(s.resolution_notes)div.append(node('div','Resolution: '+s.resolution_notes,'muted'));return div}));
if(!data.statements.length)$('statements').append(node('p','No statements staged or imported.','muted'));
const sync=data.sync||{};
if(sync.personal_rules?.length){$('personal-rules').hidden=false;$('rule-list').replaceChildren(...sync.personal_rules.map(rule=>{const item=node('div',undefined,'source');item.append(node('strong',rule.label),node('div',rule.note,'muted'));return item}));}
const localTime=value=>new Intl.DateTimeFormat(undefined,{dateStyle:'medium',timeStyle:'short',...(sync.timezone?{timeZone:sync.timezone}:{})}).format(new Date(value));
const reviewItems=data.review_items||[];
const failedScan=sync.last_run?.success===false;
if(reviewItems.length||failedScan){$('sync-issues').hidden=false;$('review-summary').textContent=reviewItems.length?'Items to review · '+reviewItems.length:'Items to review';
 if(failedScan)$('review-groups').append(node('p','The latest scan was incomplete. Saved history is still available.','muted'));
 const groups=new Map();reviewItems.forEach(r=>{const list=groups.get(r.group)||[];list.push(r);groups.set(r.group,list)});
 groups.forEach((items,name)=>{const section=node('details',undefined,'source');section.append(node('summary',name+' · '+items.length));items.forEach(item=>section.append(node('div',(item.account?item.account+': ':'')+item.reason+' · Gmail '+item.message_id,'muted')));$('review-groups').append(section)});
}
$('footer').textContent=data.generated?'Updated '+localTime(data.generated):'Template preview · No account data.';
['currency','month','account','state','from','to','search','channel'].forEach(id=>$(id).addEventListener('input',update));update();
