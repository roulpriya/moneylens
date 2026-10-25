import {spawnSync} from 'node:child_process';
import {existsSync} from 'node:fs';
import {resolve} from 'node:path';

// Build/test tooling only. Installed workflows use the installed Python command.
export function pythonCommand(): string[] {
  const override=process.env.MONEYLENS_TEST_PYTHON;
  const local=resolve(import.meta.dir,'..','.venv',process.platform === 'win32' ? 'Scripts/python.exe' : 'bin/python');
  const candidates=override ? [[override]] : process.platform === 'win32'
    ? [['python'],['py','-3'],['python3']] : [['python3'],['python']];
  if(!override && existsSync(local))candidates.unshift([local]);
  for(const [command,...prefix] of candidates){
    const probe=spawnSync(command,[...prefix,'-c','import sys;sys.exit(sys.version_info < (3,10))'],{encoding:'utf8'});
    if(probe.status===0)return [command,...prefix];
  }
  throw new Error('Python 3.10+ is required; set MONEYLENS_TEST_PYTHON to its executable path.');
}
