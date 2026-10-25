import { cp, lstat, mkdir, rm } from 'node:fs/promises';
import { dirname, resolve } from 'node:path';
const root = resolve(import.meta.dir, '..');
const target = resolve(root, 'dist/moneylens');
await rm(target, {recursive: true, force: true});
await mkdir(target, {recursive: true});
const modules = ['__init__', 'accounting', 'accounts', 'alerts', 'app', 'credentials', 'dashboard',
  'ledger', 'merchants', 'pdf_extract', 'personalize', 'private_files',
  'processing', 'statement_coverage', 'store', 'transactions', 'transfers', 'windows_access'];
const files = ['plugin.json', 'LICENSE', 'README.md', 'assets/moneylens.svg',
  ...['setup', 'automation'].flatMap(skill => [`skills/${skill}/SKILL.md`, `skills/${skill}/agents/openai.yaml`]),
  'skills/automation/assets/report-template.html',
  'skills/setup/assets/setup.html', 'skills/setup/scripts/setup_server.py',
  ...['collection-progress', 'email-and-extraction', 'ledger-contract', 'personal-context', 'setup-contract'].map(name => `skills/automation/references/${name}.md`),
  ...['moneylens.py', 'pdf_extract.py', 'requirements.txt', 'requirements-pdf.txt'].map(name => `skills/automation/scripts/${name}`),
  ...modules.map(name => `skills/automation/moneylens/${name}.py`)];
// Ship only maintained release files; private state and retired helpers cannot enter the bundle.
for (const name of files) {
  if (!(await lstat(resolve(root, name))).isFile()) throw new Error(`Release source must be a regular file: ${name}`);
  const destination = resolve(target, name);
  await mkdir(dirname(destination), {recursive: true});
  await cp(resolve(root, name), destination, {dereference: false});
}
// Keep the review inventory outside the plugin so it cannot become runtime content.
await Bun.write(resolve(root, 'dist/moneylens-files.json'), JSON.stringify(files, null, 2) + '\n');
console.log('Packaged MoneyLens at dist/moneylens with setup and automation skills.');
