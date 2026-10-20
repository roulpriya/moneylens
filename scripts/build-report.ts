import { resolve } from 'node:path';
const root = resolve(import.meta.dir, '..');
const outputs = await Promise.all(['js', 'css'].map(async extension => {
  const result = await Bun.build({entrypoints: [resolve(root, `src/report.${extension}`)], target: 'browser',
    ...(extension === 'js' ? {format: 'iife' as const} : {}), minify: false, write: false});
  if (!result.success) throw new AggregateError(result.logs, `Report ${extension} build failed`);
  if (result.outputs.length !== 1) throw new Error('Report build must have no external assets');
  return result.outputs[0].text();
}));
const source = await Bun.file(resolve(root, 'src/report.html')).text();
const [js, css] = outputs;
const html = source.replace('<!-- REPORT_STYLES -->', `<style>\n${css}</style>`)
  .replace('<!-- REPORT_SCRIPT -->', `<script>\n${js.replaceAll('</script', '<\\/script')}</script>`);
const opening = '<!-- MONEYLENS_DATA_START -->\n<script id="data" type="application/json">';
const closing = '</script>\n<!-- MONEYLENS_DATA_END -->';
if (html.split(opening).length !== 2 || html.split(closing).length !== 2) throw new Error('Lost report data markers');
if (/<(?:script|link|img)\b[^>]*(?:src|href)\s*=/i.test(html)) throw new Error('Report must be self-contained');
const data = JSON.parse(html.split(opening)[1].split(closing)[0]);
if (data.rows.length || data.statements.length || Object.keys(data.sync).length) throw new Error('Build input must contain no personal data');
await Bun.write(resolve(root, 'skills/moneylens-automation/assets/report-template.html'), html);
console.log('Built a single offline HTML template with inline JavaScript and CSS.');
