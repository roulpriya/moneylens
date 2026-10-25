import {spawnSync} from 'node:child_process';
import {pythonCommand} from './python-command';
const [command,...prefix]=pythonCommand();
const result=spawnSync(command,[...prefix,'-X','utf8','-m','unittest','discover','-s','tests','-v'],{stdio:'inherit'});
process.exit(result.status ?? 1);
