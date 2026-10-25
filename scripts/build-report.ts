import { basename, extname, resolve } from 'node:path';
const root = resolve(import.meta.dir, '..');
const check = Bun.argv.includes('--check');
const outputs = await Promise.all(['js', 'css'].map(async extension => {
  const result = await Bun.build({entrypoints: [resolve(root, `src/report.${extension}`)], target: 'browser',
    ...(extension === 'js' ? {format: 'iife' as const} : {}), minify: false, write: false});
  if (!result.success) throw new AggregateError(result.logs, `Report ${extension} build failed`);
  const bundles = result.outputs.filter(output => extname(output.path) === `.${extension}`);
  if (bundles.length !== 1) throw new Error(`Report must have one ${extension} bundle`);
  let bundle = await bundles[0].text();
  const assets = result.outputs.filter(output => output !== bundles[0]);
  const fonts = new Map<string, string>();
  for (const asset of assets) {
    if (extension !== 'css' || extname(asset.path) !== '.woff2') throw new Error(`Unexpected report asset: ${asset.path}`);
    const key = basename(asset.path);
    if (fonts.has(key)) throw new Error(`Duplicate report font: ${key}`);
    fonts.set(key, `data:font/woff2;base64,${Buffer.from(await asset.arrayBuffer()).toString('base64')}`);
  }
  if (extension === 'css') {
    bundle = bundle.replace(/url\(\s*(['"]?)([^'"\s)]+)\1\s*\)/gi, (_match, _quote, reference) => {
      if (/^data:font\/woff2;base64,[a-z\d+/=]+$/i.test(reference)) return `url("${reference}")`;
      if (/^(?:[a-z]+:|\/\/)/i.test(reference)) throw new Error('External URL in report CSS');
      const font = fonts.get(basename(reference));
      if (!font) throw new Error(`Unbundled report CSS asset: ${reference}`);
      return `url("${font}")`;
    });
    const notices = await Bun.file(resolve(root, 'src/fonts/OFL.txt')).text();
    if (notices.includes('*/') || /<\/style/i.test(notices)) throw new Error('Invalid font license comment');
    bundle = `/* Bundled font licenses\n${notices}\n*/\n${bundle}`;
  }
  return bundle;
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
const destination = resolve(root, 'skills/automation/assets/report-template.html');
if (check) {
  if (await Bun.file(destination).text() !== html) throw new Error('Compiled skill template is stale. Run bun run build:report and commit the regenerated HTML.');
  console.log('Compiled skill template matches its Bun source.');
} else {
  await Bun.write(destination, html);
  console.log('Built the offline skill template with inline JavaScript, CSS, fonts, and font licenses.');
}
