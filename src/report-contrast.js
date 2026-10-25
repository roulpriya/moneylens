// WCAG relative luminance and contrast for opaque sRGB theme colors.
function rgb(hex) { return hex.slice(1).match(/../g).map(value=>parseInt(value,16)/255); }
function luminance(hex) {
  return rgb(hex).map(value=>value<=.04045?value/12.92:((value+.055)/1.055)**2.4)
    .reduce((sum,value,index)=>sum+value*[.2126,.7152,.0722][index],0);
}
export function contrastRatio(first,second) {
  const a=luminance(first),b=luminance(second);
  return (Math.max(a,b)+.05)/(Math.min(a,b)+.05);
}
function mix(first,second,weight) {
  const a=rgb(first),b=rgb(second);
  return '#'+a.map((value,index)=>Math.round((value*weight+b[index]*(1-weight))*255).toString(16).padStart(2,'0')).join('');
}
function ink(background) { return contrastRatio('#17231d',background)>=contrastRatio('#ffffff',background)?'#17231d':'#ffffff'; }
export function contrastTokens(colors) {
  let border=mix(colors.text,colors.cards,.65);
  if(contrastRatio(border,colors.cards)<3)border=ink(colors.cards);
  const accentVisible=[colors.cards,colors.background].every(bg=>contrastRatio(colors.accent,bg)>=3);
  return {
    '--control-border':border,
    '--header-focus':ink(colors.header),
    '--control-ink':ink(border),
    '--focus-ring':accentVisible?colors.accent:ink(colors.cards),
    '--chart-ink':contrastRatio(colors.accent,colors.cards)>=3?colors.accent:ink(colors.cards),
    '--error':luminance(colors.cards)>.179?'#9a2f24':'#ffb4ab'
  };
}
