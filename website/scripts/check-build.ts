import { readdir, readFile, lstat } from 'node:fs/promises';
import { dirname, extname, resolve, relative, sep } from 'node:path';
import { fileURLToPath } from 'node:url';

// Check the exact directory CI uploads, including project-site relative links.
const output = fileURLToPath(new URL('../dist/', import.meta.url));
const allowedExtensions = new Set(['.html', '.css', '.js', '.svg', '.woff2', '.txt']);
const files: string[] = [];
async function walk(directory: string) {
  for (const name of await readdir(directory)) {
    const candidate = resolve(directory, name);
    const info = await lstat(candidate);
    if (info.isSymbolicLink()) throw new Error(`Symlink in public output: ${candidate}`);
    if (info.isDirectory()) await walk(candidate);
    else {
      if (!info.isFile() || !allowedExtensions.has(extname(name))) {
        throw new Error(`Unexpected file in public output: ${candidate}`);
      }
      if (['ledger', 'credential', 'statement', 'source-inventory', 'report.html'].some(term => name.includes(term))) {
        throw new Error(`Possible private file in public output: ${name}`);
      }
      files.push(candidate);
    }
  }
}
await walk(output);

for (const required of ['index.html', 'policy.html', 'favicon.svg', 'robots.txt']) {
  if (!files.includes(resolve(output, required))) throw new Error(`Missing public page: ${required}`);
}

const htmlFiles = new Map<string, string>();
for (const file of files.filter(file => extname(file) === '.html')) htmlFiles.set(file, await readFile(file, 'utf8'));
let references = 0;
function checkReference(raw: string, file: string) {
  if (/^(?:[a-z][a-z\d+.-]*:|\/\/)/i.test(raw)) return;
  if (raw.startsWith('/')) throw new Error(`Root-relative URL will break project Pages: ${raw}`);
  const [pathname, fragment] = raw.split('#');
  const clean = decodeURIComponent(pathname.split('?')[0]);
  let target = clean ? resolve(dirname(file), clean) : file;
  if (clean.endsWith('/')) target = resolve(target, 'index.html');
  const relativeTarget = relative(output, target);
  if (relativeTarget.startsWith(`..${sep}`) || relativeTarget === '..') throw new Error(`URL escapes site: ${raw}`);
  if (!files.includes(target)) throw new Error(`Broken reference in ${relative(output, file)}: ${raw}`);
  if (fragment && htmlFiles.has(target)) {
    const id = decodeURIComponent(fragment);
    const ids = [...htmlFiles.get(target)!.matchAll(/\bid=["']([^"']+)["']/g)].map(match => match[1]);
    if (!ids.includes(id)) throw new Error(`Missing anchor: ${raw}`);
  }
  references++;
}

for (const [file, html] of htmlFiles) {
  if (!/<html[^>]+lang="en"/.test(html) || !/<title>.+?<\/title>/.test(html)) throw new Error(`Missing page metadata: ${file}`);
  for (const match of html.matchAll(/\b(?:href|src)=["']([^"']+)["']/g)) checkReference(match[1], file);
}
for (const file of files.filter(file => extname(file) === '.css')) {
  const css = await readFile(file, 'utf8');
  for (const match of css.matchAll(/url\(["']?([^\s)"']+)["']?\)/g)) checkReference(match[1], file);
}
console.log(`Public site verified: ${htmlFiles.size} pages, ${files.length} files, ${references} local references. No private data paths are included.`);
