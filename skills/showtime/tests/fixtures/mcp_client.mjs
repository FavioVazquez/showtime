// Minimal MCP stdio client for tests/test_mcp.py (no dependencies).
// Reads a plan as JSON on stdin:
//   {"server": "<server.mjs>", "cwd": "<dir>", "env": {...}, "mode": "legacy" | "modern",
//    "steps": [{"method": "tools/call", "params": {...}, "progress": true, "raw": false}],
//    "client_name": "showtime-test"}  (the clientInfo name the client reports)
// Legacy mode performs the initialize handshake first; modern mode puts the protocol version in
// every request's _meta. Prints [{method, response, progress: [notification params...]}] as JSON.
import { spawn } from 'node:child_process';
import readline from 'node:readline';

const plan = JSON.parse(await new Promise((res) => { let s = ''; process.stdin.on('data', (c) => { s += c; }); process.stdin.on('end', () => res(s)); }));
const child = spawn(process.execPath, [plan.server, ...(plan.args || [])], { cwd: plan.cwd, env: { ...process.env, ...(plan.env || {}) }, stdio: ['pipe', 'pipe', 'pipe'] });
let stderr = '';
child.stderr.on('data', (c) => { stderr += c; });
const pending = new Map();
const progress = new Map();
const junk = [];
readline.createInterface({ input: child.stdout }).on('line', (line) => {
  let m;
  try { m = JSON.parse(line); } catch { junk.push(line); return; }
  if (m.method === 'notifications/progress') {
    const list = progress.get(m.params.progressToken);
    if (list) list.push(m.params);
    return;
  }
  const p = pending.get(m.id);
  if (p) { pending.delete(m.id); p(m); }
});
let nextId = 1;
function request(method, params = {}, { withProgress = false, timeoutMs = 240000 } = {}) {
  const id = nextId++;
  const meta = { ...(params._meta || {}) };
  if (plan.mode === 'modern') {
    meta['io.modelcontextprotocol/protocolVersion'] = meta['io.modelcontextprotocol/protocolVersion'] || '2026-07-28';
    meta['io.modelcontextprotocol/clientInfo'] = { name: plan.client_name || 'showtime-test', version: '1' };
    meta['io.modelcontextprotocol/clientCapabilities'] = {};
  }
  const token = withProgress ? `tok-${id}` : undefined;
  if (token) { meta.progressToken = token; progress.set(token, []); }
  const body = { jsonrpc: '2.0', id, method, params: { ...params, ...(Object.keys(meta).length ? { _meta: meta } : {}) } };
  return new Promise((resolve) => {
    const timer = setTimeout(() => { pending.delete(id); resolve({ timeout: true }); }, timeoutMs);
    pending.set(id, (m) => { clearTimeout(timer); resolve(m); });
    child.stdin.write(JSON.stringify(body) + '\n');
  }).then((response) => ({ method, response, progress: token ? progress.get(token) : [] }));
}

const out = [];
if (plan.mode !== 'modern') {
  const init = await request('initialize', { protocolVersion: '2025-11-25', capabilities: {}, clientInfo: { name: plan.client_name || 'showtime-test', version: '1' } });
  out.push(init);
  child.stdin.write(JSON.stringify({ jsonrpc: '2.0', method: 'notifications/initialized' }) + '\n');
}
for (const s of plan.steps || []) out.push(await request(s.method, s.params || {}, { withProgress: !!s.progress, timeoutMs: s.timeout_ms || 240000 }));
child.stdin.end();
const code = await new Promise((res) => { const t = setTimeout(() => { child.kill(); res('killed'); }, 10000); child.on('close', (c) => { clearTimeout(t); res(c); }); });
process.stdout.write(JSON.stringify({ results: out, exit: code, stderr: stderr.slice(-4000), junk }) + '\n');
