import { cp, mkdir, rm } from 'node:fs/promises';
import { resolve } from 'node:path';
const root = resolve(import.meta.dir, '..');
const target = resolve(root, 'dist/moneylens');
await rm(target, {recursive: true, force: true});
await mkdir(target, {recursive: true});
for (const name of ['plugin.json', 'skills', 'LICENSE', 'README.md']) {
  await cp(resolve(root, name), resolve(target, name), {recursive: true,
    filter: source => !source.includes('__pycache__') && !source.endsWith('.pyc')});
}
console.log('Packaged MoneyLens at dist/moneylens with setup and automation skills.');
