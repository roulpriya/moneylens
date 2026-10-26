import { basename, extname, resolve } from 'node:path';
const root = resolve(import.meta.dir, '..');
const check = Bun.argv.includes('--check');
// The skill ships fonts beside the template so each file stays inspectable; reports inline them on first render.
const fontsMarker = '<!-- MONEYLENS_FONTS -->';
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
  }
  return bundle;
}));
const [js, styles] = outputs;
const faces = styles.match(/@font-face\s*\{[^}]*\}\n?/g) ?? [];
const css = faces.reduce((rest, face) => rest.replace(face, ''), styles);
if (!faces.length || /data:font\//i.test(css)) throw new Error('Report fonts must be declared with @font-face');
const notices = await Bun.file(resolve(root, 'src/fonts/OFL.txt')).text();
if (notices.includes('*/') || /<\/style/i.test(notices)) throw new Error('Invalid font license comment');
const fonts = `<style>\n/* Bundled font licenses\n${notices}\n*/\n${faces.join('')}</style>\n`;
const source = await Bun.file(resolve(root, 'src/report.html')).text();
const html = source.replace('<!-- REPORT_STYLES -->', () => `${fontsMarker}\n<style>\n${css}</style>`)
  .replace('<!-- REPORT_SCRIPT -->', `<script>\n${js.replaceAll('</script', '<\\/script')}</script>`);
const opening = '<!-- MONEYLENS_DATA_START -->\n<script id="data" type="application/json">';
const closing = '</script>\n<!-- MONEYLENS_DATA_END -->';
if (html.split(opening).length !== 2 || html.split(closing).length !== 2) throw new Error('Lost report data markers');
if (/<(?:script|link|img)\b[^>]*(?:src|href)\s*=/i.test(html)) throw new Error('Report must be self-contained');
const data = JSON.parse(html.split(opening)[1].split(closing)[0]);
if (data.rows.length || data.statements.length || Object.keys(data.sync).length) throw new Error('Build input must contain no personal data');
if (html.split(fontsMarker).length !== 2 || /url\(\s*['"]?data:font\//i.test(html)) throw new Error('Report fonts must stay outside the template');
const assets = resolve(root, 'plugins/moneylens/skills/automation/assets');
const compiled = {'report-template.html': html, 'report-fonts.html': fonts};
if (check) {
  for (const [name, content] of Object.entries(compiled))
    if (await Bun.file(resolve(assets, name)).text() !== content) throw new Error(`Compiled skill ${name} is stale. Run bun run build:report and commit the regenerated HTML.`);
  console.log('Compiled skill template and fonts match their Bun source.');
} else {
  for (const [name, content] of Object.entries(compiled)) await Bun.write(resolve(assets, name), content);
  console.log('Built the offline skill template with inline JavaScript and CSS, and its fonts with their licenses.');
}
