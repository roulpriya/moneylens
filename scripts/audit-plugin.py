#!/usr/bin/env python3
"""Create or audit a review ZIP. Development-only; never included in the plugin."""
import argparse
import ast
import hashlib
import json
from pathlib import Path, PurePosixPath
import posixpath
import re
import stat
import zipfile

ROOT = Path(__file__).resolve().parents[1]
ENTRYPOINTS = (
    'skills/automation/scripts/moneylens.py',
    'skills/automation/scripts/pdf_extract.py',
    'skills/setup/scripts/setup_server.py',
)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def local_imports(data, package=False):
    deps = set()
    for node in ast.walk(ast.parse(data)):
        if isinstance(node, ast.ImportFrom):
            if node.level and package:
                deps.update([node.module.split('.')[0]] if node.module else [a.name for a in node.names])
            elif node.module and node.module.startswith('moneylens.'):
                deps.add(node.module.split('.')[1])
        elif isinstance(node, ast.Import):
            deps.update(a.name.split('.')[1] for a in node.names if a.name.startswith('moneylens.'))
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == 'run_module':
            if node.args and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str):
                name = node.args[0].value
                if name.startswith('moneylens.'):
                    deps.add(name.split('.')[1])
    return deps


def purpose(name):
    if name == 'plugin.json': return 'Plugin identity and host metadata'
    if name == 'LICENSE': return 'Required MIT license notice'
    if name == 'README.md': return 'Installation and usage information; not executable code'
    if name in ENTRYPOINTS: return 'Maintained skill runtime entry point'
    if '/moneylens/' in name: return 'Required transitive runtime import'
    if name.endswith('/SKILL.md'): return 'Agent workflow instructions'
    if '/agents/' in name: return 'Skill display metadata'
    if '/references/' in name: return 'Referenced runtime contract or workflow guidance'
    if '/assets/' in name: return 'Self-contained runtime UI with embedded fonts and license notices'
    if name.endswith('.txt'): return 'Pinned runtime installation requirements'
    raise ValueError(f'File has no required package role: {name}')


def audit(archive, expected):
    inventory = []
    contents = {}
    with zipfile.ZipFile(archive) as bundle:
        entries = bundle.infolist()
        names = [item.filename for item in entries]
        if len(names) != len(set(names)) or len(names) != len({name.casefold() for name in names}):
            raise ValueError('Duplicate or case-colliding ZIP paths')
        if set(names) != set(expected):
            raise ValueError(f'ZIP allowlist mismatch: extra={sorted(set(names)-set(expected))}, missing={sorted(set(expected)-set(names))}')
        for item in entries:
            name = item.filename
            path = PurePosixPath(name)
            if path.is_absolute() or '..' in path.parts or '\\' in name or item.is_dir():
                raise ValueError(f'Unsafe ZIP member: {name}')
            mode = item.external_attr >> 16
            if stat.S_ISLNK(mode) or (stat.S_IFMT(mode) and not stat.S_ISREG(mode)):
                raise ValueError(f'ZIP member is not a regular file: {name}')
            source = ROOT / name
            built = ROOT / 'dist/moneylens' / name
            if source.is_symlink() or built.is_symlink() or not source.is_file() or not built.is_file():
                raise ValueError(f'Missing regular source/bundle file: {name}')
            source_data = source.read_bytes()
            if item.file_size != len(source_data) or item.file_size > 16 * 1024 * 1024:
                raise ValueError(f'Unexpected file size: {name}')
            data = bundle.read(item)
            if data != source_data or data != built.read_bytes():
                raise ValueError(f'ZIP differs from current source or bundle: {name}')
            contents[name] = data
            inventory.append({'path': name, 'bytes': len(data), 'sha256': digest(data), 'purpose': purpose(name)})

    modules = {PurePosixPath(name).stem: name for name in expected if name.startswith('skills/automation/moneylens/') and name.endswith('.py')}
    graph = {name: local_imports(contents[path], package=True) for name, path in modules.items()}
    missing = set().union(*graph.values()) - modules.keys()
    pending = set().union(*(local_imports(contents[path]) for path in ENTRYPOINTS))
    missing |= pending - modules.keys()
    if missing: raise ValueError(f'Missing runtime modules: {sorted(missing)}')
    reached = set()
    while pending:
        name = pending.pop()
        if name in reached: continue
        reached.add(name)
        pending.update(graph[name] - reached)
    unused = modules.keys() - reached - {'__init__'}
    if unused: raise ValueError(f'Unnecessary runtime modules: {sorted(unused)}')
    allowed_python = {modules[name] for name in reached | {'__init__'}} | set(ENTRYPOINTS)
    extra_python = {name for name in expected if name.endswith('.py')} - allowed_python
    if extra_python: raise ValueError(f'Unrelated executable code: {sorted(extra_python)}')

    # Installed skill links must resolve within the ZIP. README also documents the source checkout.
    for name, data in contents.items():
        if not name.startswith('skills/') or not name.endswith('.md'): continue
        for link in re.findall(r'\[[^\]]*\]\(([^)]+)\)', data.decode()):
            target = link.split('#')[0]
            if not target or '://' in target or target.startswith(('mailto:', '<')): continue
            resolved = posixpath.normpath(posixpath.join(posixpath.dirname(name), target))
            if resolved not in contents: raise ValueError(f'Broken packaged reference: {name} -> {link}')

    report = contents['skills/automation/assets/report-template.html'].decode()
    report_data = json.loads(re.search(r'<script id="data" type="application/json">(.*?)</script>', report, re.S).group(1))
    if any(report_data.get(key) for key in ('rows', 'statements', 'sync', 'from', 'to', 'generated')):
        raise ValueError('Compiled report contains runtime data')
    setup = contents['skills/setup/assets/setup.html'].decode()
    setup_data = json.loads(re.search(r'<script id="setup-config" type="application/json">(.*?)</script>', setup, re.S).group(1))
    if setup_data != {'fields': [], 'scope': '', 'context': '', 'token': ''}:
        raise ValueError('Compiled setup contains runtime configuration or inputs')
    forbidden = {'node_modules', '.venv', '__pycache__', 'tests', 'website', 'src', 'work', 'credentials', '.git', 'docs'}
    for name in contents:
        if forbidden & set(PurePosixPath(name).parts) or name.endswith(('.pyc', '.sqlite3', '.secret', '.pdf', '.zip')):
            raise ValueError(f'Private/development file in ZIP: {name}')
        if name.endswith(('.js', '.css', '.ts', '.tsx', '.jsx', '.sh', '.swift', '.exe', '.dll', '.so', '.node')):
            raise ValueError(f'Unexpected standalone code asset: {name}')
    return {
        'archive': str(archive), 'sha256': digest(archive.read_bytes()),
        'archive_bytes': archive.stat().st_size, 'file_count': len(inventory),
        'python_files': len(allowed_python), 'total_uncompressed_bytes': sum(item['bytes'] for item in inventory),
        'checks': ['Exact explicit allowlist', 'No unexpected code modules', 'No development or private data files',
                   'All entry-point imports present', 'Packaged skill links resolve', 'Empty report and setup data',
                   'No duplicate, traversing, linked or special-file members', 'Every byte matches source and built folder'],
        'submission_status': 'Review artifact only; branding, description, legal review and explicit user approval required before any submission',
        'inventory': sorted(inventory, key=lambda item: item['path']),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--zip', required=True, type=Path)
    parser.add_argument('--create', action='store_true', help='Create a new review ZIP; never overwrite an existing archive')
    parser.add_argument('--report', required=True, type=Path)
    args = parser.parse_args()
    expected = json.loads((ROOT / 'dist/moneylens-files.json').read_text())
    if len(expected) != len(set(expected)): raise ValueError('Duplicate build allowlist entries')
    archive = args.zip.absolute()
    if args.create:
        with zipfile.ZipFile(archive, 'x', compression=zipfile.ZIP_DEFLATED, compresslevel=9) as bundle:
            for name in sorted(expected):
                bundle.write(ROOT / 'dist/moneylens' / name, arcname=name)
    report = audit(archive, expected)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({key: value for key, value in report.items() if key != 'inventory'}, indent=2))


if __name__ == '__main__':
    main()
