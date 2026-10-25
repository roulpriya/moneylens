import {basename, extname, resolve} from 'node:path';
const root = resolve(import.meta.dir, '..');
const outputs = await Promise.all(['js', 'css'].map(async extension => {
  const result = await Bun.build({entrypoints: [resolve(root, `src/setup.${extension}`)], target: 'browser',
    ...(extension === 'js' ? {format: 'iife' as const} : {}), minify: false, write: false});
  if (!result.success) throw new AggregateError(result.logs, `Setup ${extension} build failed`);
  const bundles = result.outputs.filter(output => extname(output.path) === `.${extension}`);
  if (bundles.length !== 1) throw new Error(`Setup must have one ${extension} bundle`);
  let bundle = await bundles[0].text();
  const fonts = new Map<string, string>();
  for (const asset of result.outputs.filter(output => output !== bundles[0])) {
    if (extension !== 'css' || extname(asset.path) !== '.woff2') throw new Error('Unexpected setup asset');
    fonts.set(basename(asset.path), `data:font/woff2;base64,${Buffer.from(await asset.arrayBuffer()).toString('base64')}`);
  }
  if (extension === 'css') {
    bundle = bundle.replace(/url\(\s*(['"]?)([^'"\s)]+)\1\s*\)/gi, (_match, _quote, reference) => {
      if (/^data:font\/woff2;base64,[a-z\d+/=]+$/i.test(reference)) return `url("${reference}")`;
      const font = fonts.get(basename(reference));
      if (!font) throw new Error('Unbundled setup font');
      return `url("${font}")`;
    });
    const licenses = await Bun.file(resolve(root, 'src/fonts/OFL.txt')).text();
    if (licenses.includes('*/') || /<\/style/i.test(licenses)) throw new Error('Invalid font license');
    bundle = `/* Bundled font licenses\n${licenses}\n*/\n${bundle}`;
  }
  return bundle;
}));
const [js, css] = outputs;
const source = await Bun.file(resolve(root, 'src/setup.html')).text();
const html = source.replace('<!-- SETUP_STYLES -->', `<style>\n${css}</style>`)
  .replace('<!-- SETUP_SCRIPT -->', `<script>\n${js.replaceAll('</script', '<\\/script')}</script>`);
if (/<(?:script|link|img)\b[^>]*(?:src|href)\s*=/i.test(html)) throw new Error('Setup must be self-contained');
const destination = resolve(root, 'skills/setup/assets/setup.html');
if (Bun.argv.includes('--check')) {
  if (await Bun.file(destination).text() !== html) throw new Error('Setup template is stale; run npm run build:setup');
  console.log('Compiled setup template matches its source.');
} else {
  await Bun.write(destination, html);
  console.log('Built the offline setup template with bundled fonts.');
}
