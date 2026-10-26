import { readdir } from 'node:fs/promises';
import { relative, resolve, sep } from 'node:path';
const root = resolve(import.meta.dir, '..');
const plugin = resolve(root, 'plugins/moneylens');
const expected: string[] = await Bun.file(resolve(root, 'scripts/plugin-files.json')).json();
if (new Set(expected).size !== expected.length) throw new Error('Duplicate plugin allowlist entries');
// Interpreter caches and Finder metadata are gitignored local artifacts, never part of a release.
const ignored = (name: string) => name === '__pycache__' || name === '.DS_Store' || name.endsWith('.pyc');
const found: string[] = [];
async function walk(directory: string) {
  for (const entry of await readdir(directory, {withFileTypes: true})) {
    if (ignored(entry.name)) continue;
    const path = resolve(directory, entry.name);
    const name = relative(plugin, path).split(sep).join('/');
    if (entry.isDirectory()) await walk(path);
    else if (entry.isFile()) found.push(name);
    else throw new Error(`Plugin file must be a regular file: ${name}`);
  }
}
await walk(plugin);
// The directory and every marketplace install the plugin folder as committed, so it must hold only maintained release files.
const extra = found.filter(name => !expected.includes(name)).sort();
const missing = expected.filter(name => !found.includes(name)).sort();
if (extra.length || missing.length) throw new Error(`Plugin folder differs from scripts/plugin-files.json: extra=${JSON.stringify(extra)}, missing=${JSON.stringify(missing)}`);
console.log(`Plugin folder matches its allowlist (${expected.length} files).`);
