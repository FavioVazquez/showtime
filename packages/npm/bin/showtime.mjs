#!/usr/bin/env node
// `showtime` from the npm package: finds a Python 3.8+ (the showtime venv first) and hands off to the
// bundled skill's launcher, lib/st/launcher.py, which does all the real work. Same search order as the
// skill's own bin/showtime shims: SHOWTIME_PYTHON, <showtime home>/venv, python3/python (py -3 on
// Windows), then uv, which can provide a Python on the fly.
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { spawn, spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';

const HERE = path.dirname(fs.realpathSync(fileURLToPath(import.meta.url)));
const LAUNCHER = path.join(HERE, '..', 'skill', 'lib', 'st', 'launcher.py');
const IS_WIN = process.platform === 'win32';

function home() {
  const v = process.env.SHOWTIME_HOME;
  if (v && !v.includes('${')) return path.resolve(v.replace(/^~(?=$|[\\/])/, os.homedir()));
  return path.join(os.homedir(), '.showtime');
}

function which(name) {
  const exts = IS_WIN ? (process.env.PATHEXT || '.EXE;.CMD;.BAT').split(';').filter(Boolean) : [''];
  for (const dir of (process.env.PATH || '').split(path.delimiter)) {
    if (!dir) continue;
    for (const ext of exts) {
      const f = path.join(dir, name + ext);
      try { if (fs.statSync(f).isFile()) return f; } catch { /* keep looking */ }
    }
  }
  return null;
}

function works(exe, pre) {
  const r = spawnSync(exe, [...pre, '-c', 'import sys; sys.exit(0 if sys.version_info >= (3, 8) else 1)'],
    { stdio: 'ignore', timeout: 15000, windowsHide: true });
  return r.status === 0;
}

function findPython() {
  const h = home();
  for (const c of [process.env.SHOWTIME_PYTHON, path.join(h, 'venv', 'bin', 'python'), path.join(h, 'venv', 'Scripts', 'python.exe')]) {
    if (c && fs.existsSync(c)) return { exe: c, pre: [] };
  }
  for (const [n, pre] of IS_WIN ? [['py', ['-3']], ['python', []], ['python3', []]] : [['python3', []], ['python', []]]) {
    const exe = which(n);
    if (exe && works(exe, pre)) return { exe, pre };
  }
  const uvDirs = [path.join(os.homedir(), '.local', 'bin'), path.join(os.homedir(), '.cargo', 'bin'),
    ...(IS_WIN ? [] : ['/opt/homebrew/bin', '/usr/local/bin'])];
  const uv = which('uv') || uvDirs.map((d) => path.join(d, IS_WIN ? 'uv.exe' : 'uv')).find((f) => fs.existsSync(f));
  if (uv) return { exe: uv, pre: ['run', '--no-project', '--python', '3.12', 'python'] };
  return null;
}

const py = findPython();
if (!py) {
  process.stderr.write('showtime: no Python 3.8+ found.\n' +
    '  Install uv (https://docs.astral.sh/uv/getting-started/installation/) or Python 3, then run: showtime setup\n' +
    '  If you just installed one, open a new terminal (or restart your agent) so it sees the new PATH.\n');
  process.exit(127);
}
const child = spawn(py.exe, [...py.pre, LAUNCHER, ...process.argv.slice(2)], { stdio: 'inherit', windowsHide: false });
const forward = (sig) => { try { child.kill(sig); } catch { /* gone */ } };
for (const sig of ['SIGINT', 'SIGTERM']) process.on(sig, () => forward(sig));
child.on('error', (e) => { process.stderr.write(`showtime: could not start ${py.exe}: ${e.message}\n`); process.exit(1); });
child.on('exit', (code, signal) => process.exit(signal ? 1 : (code ?? 1)));
