// The harness's reader connection with a fake reader process: attach, session_id injection,
// re-attach, attach failure, compact results and the per-question refresh.
import assert from 'node:assert/strict';
import { mkdtempSync, readFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import test from 'node:test';
import { fileURLToPath } from 'node:url';

import { attachFix, compactToolText, ReaderSession, ReaderTransport, stripSessionParam } from '../pi/fm-reader-session.mjs';
import { prepareTurn } from '../pi/fm-turn.mjs';

const FIXTURE = fileURLToPath(new URL('./exposure-reader-fixture.py', import.meta.url));
const TOOLS = 'fm_status,fm_attach,fm_get_save,fm_db_query,fm_get_inbox';

/** A pi-like client over the harness transport: initialize, list, then model calls. */
async function connect(env = {}) {
  const dir = mkdtempSync(join(tmpdir(), 'pi-fm-reader-'));
  const session = new ReaderSession({ requestTimeoutMs: 10_000 });
  const transport = new ReaderTransport({ command: 'python3', args: ['-B', FIXTURE], env: { PI_FM_TEST_READER_DIR: dir, PI_FM_TEST_TOOLS: TOOLS, ...env } }, session);
  await transport.start();
  const pending = new Map();
  let next = 1;
  transport.onMessage(m => { const p = pending.get(m.id); if (p) { pending.delete(m.id); p(m); } });
  const rpc = (method, params) => new Promise(resolve => { const id = next++; pending.set(id, resolve); transport.send({ jsonrpc: '2.0', id, method, params }); });
  await rpc('initialize', { protocolVersion: '2025-06-18', capabilities: {}, clientInfo: { name: 't', version: '1' } });
  await transport.send({ jsonrpc: '2.0', method: 'notifications/initialized' });
  const tools = (await rpc('tools/list', {})).result.tools;
  const requests = () => readFileSync(join(dir, 'requests.jsonl'), 'utf8').trim().split('\n').map(JSON.parse).filter(r => r.method === 'tools/call');
  const close = async () => { await transport.close(); rmSync(dir, { recursive: true, force: true }); };
  return { session, transport, tools, rpc, requests, close };
}

test('tools/list loses session_id; a model call without one is attached and filled in', async () => {
  const r = await connect();
  try {
    const query = r.tools.find(t => t.name === 'fm_db_query');
    assert.equal('session_id' in query.inputSchema.properties, false);
    assert.deepEqual(query.inputSchema.required, ['sql']);
    assert.deepEqual([...r.session.sessionTools].sort(), ['fm_db_query', 'fm_get_save']);
    const answer = await r.rpc('tools/call', { name: 'fm_db_query', arguments: { sql: 'SELECT 1' } });
    assert.equal(answer.result.isError, undefined);
    const text = answer.result.content[0].text;
    // Compact: one row per line, no indentation.
    assert.equal(text, '{"columns":["idx","name"],"rows":[\n[1,"A"],\n[2,"B"]\n],"row_count":2,"truncated":false,"session_seen":"S1"}');
    assert.deepEqual(r.requests().map(q => q.name), ['fm_attach', 'fm_get_save', 'fm_db_query']);
    // A screen tool without session_id is passed through untouched.
    await r.rpc('tools/call', { name: 'fm_get_inbox', arguments: {} });
    assert.deepEqual(r.requests().at(-1).args, {});
  } finally { await r.close(); }
});

test('a session the reader no longer knows is replaced and the call re-sent under the same id', async () => {
  const r = await connect({ PI_FM_TEST_EXPIRE_ON: 'fm_db_query' });
  try {
    const answer = await r.rpc('tools/call', { name: 'fm_db_query', arguments: { sql: 'SELECT 1' } });
    assert.equal(answer.result.isError, undefined);
    assert.match(answer.result.content[0].text, /"session_seen":"S2"/);
    assert.equal(r.requests().filter(q => q.name === 'fm_attach').length, 2);
    assert.equal(r.session.sessionId, 'S2');
  } finally { await r.close(); }
});

test('an attach failure answers reader calls with the exact reason and the one fix', async () => {
  const r = await connect({ PI_FM_TEST_ATTACH_ERROR: 'task_for_pid failed: (os/kern) failure (5)' });
  try {
    const answer = await r.rpc('tools/call', { name: 'fm_db_query', arguments: { sql: 'SELECT 1' } });
    assert.equal(answer.result.isError, true);
    assert.match(answer.result.content[0].text, /could not attach to the game: task_for_pid failed: \(os\/kern\) failure \(5\)\nFix: Run `node pi\/fm-desktop-reader\.mjs install`/);
    const turn = await prepareTurn({ session: r.session, cards: null });
    assert.equal(turn.save, null);
    assert.match(turn.attachError.message, /^task_for_pid failed/);
    assert.match(turn.notice, /Fix: Run `node pi\/fm-desktop-reader/);
  } finally { await r.close(); }
});

test('each question re-reads the save, so the summary follows the game date', async () => {
  const r = await connect();
  try {
    const cards = { get: async version => `card for ${version}` };
    const first = await prepareTurn({ session: r.session, cards });
    assert.match(first.save, /- Save: Fixture Career/);
    assert.match(first.save, /- Manager: Test Manager \(your club: Fixture United\)/);
    assert.match(first.save, /- Game date: 2030-12-13/);
    assert.equal(first.schemaCard, 'card for 1');
    assert.equal(first.attachError, null);
    await prepareTurn({ session: r.session, cards });
    // One attach, two save reads.
    const names = r.requests().map(q => q.name);
    assert.equal(names.filter(n => n === 'fm_attach').length, 1);
    assert.equal(names.filter(n => n === 'fm_get_save').length, 2);
  } finally { await r.close(); }
});

test('helpers: compact JSON, schema stripping and the fix for each attach failure', () => {
  assert.equal(compactToolText('{\n  "a": 1,\n  "rows": [\n    {"x": 1},\n    {"x": 2}\n  ],\n  "padding": "................................"\n}'),
    '{"a":1,"rows":[\n{"x":1},\n{"x":2}\n],"padding":"................................"}');
  assert.equal(compactToolText('Error executing tool x: plain text that is long enough to be considered for compaction'), 'Error executing tool x: plain text that is long enough to be considered for compaction');
  const tool = { inputSchema: { properties: { session_id: {}, sql: {} }, required: ['session_id', 'sql'] } };
  assert.equal(stripSessionParam(tool), true);
  assert.deepEqual(tool.inputSchema, { properties: { sql: {} }, required: ['sql'] });
  assert.equal(stripSessionParam({ inputSchema: { properties: {} } }), false);
  assert.match(attachFix('Found 0 games. Use fm_status and select a PID explicitly.'), /Start Football Manager 27/);
  assert.match(attachFix('Found 2 games.'), /quit the extra copy/);
  assert.match(attachFix('Native reader is incompatible. Rebuild with scripts/build_helper.sh.'), /build_helper/);
  assert.match(attachFix('task_for_pid failed'), /fm-desktop-reader\.mjs install/);
  assert.doesNotMatch(Object.values({ a: attachFix('anything') }).join(''), /screenshot/i);
});
