#!/usr/bin/env node
// A minimal MCP client for the FM reader through the harness transport (attach and session ids
// handled as in pi-fm). Used by the eval facts pre-step and for checking guide SQL.
//
//   node evals/reader-client.mjs call <tool> '<json args>'
//   node evals/reader-client.mjs sql '<SELECT ...>' [manager]
//   node evals/reader-client.mjs tools            list tool names with their declared size
//   node evals/reader-client.mjs describe <tool>...   parameters and description
//   node evals/reader-client.mjs guide-sql <file.md> [rows]   run every ```sql block of a guide
//
// The reader starts as pi-fm starts it: PI_FM_MCP_LAUNCHER (default: the main checkout's
// scripts/run_mcp.sh). For a worktree: PI_FM_MCP_LAUNCHER=evals/run_reader_from.sh FM_READER_CHECKOUT=<dir>.
// FMCP_CACHE_DIR must be set explicitly: this client never falls back to the owner's cache.
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { ReaderSession, ReaderTransport } from '../pi/fm-reader-session.mjs';

export async function connectReader({ launcher = process.env.PI_FM_MCP_LAUNCHER ?? '/Volumes/4TB Private/Offloaded/FMCP 27/scripts/run_mcp.sh', env = {}, requestTimeoutMs = 600_000 } = {}) {
  const session = new ReaderSession({ requestTimeoutMs });
  const transport = new ReaderTransport({ command: '/bin/sh', args: [launcher], env }, session);
  await transport.start();
  // A busy reader does not notice its stdin closing: never leave it running behind a killed client.
  const killChild = () => { try { transport.child?.kill('SIGKILL'); } catch { /* gone */ } };
  process.once('exit', killChild);
  for (const sig of ['SIGINT', 'SIGTERM', 'SIGHUP']) process.once(sig, () => { killChild(); process.exit(1); });
  let next = 1;
  const pending = new Map();
  transport.onMessage(m => { const p = pending.get(m.id); if (p) { pending.delete(m.id); m.error ? p.reject(new Error(m.error.message)) : p.resolve(m.result); } });
  transport.onClose(() => { for (const p of pending.values()) p.reject(new Error(`reader closed: ${transport.stderr.slice(-500)}`)); });
  const rpc = (method, params) => new Promise((resolve, reject) => { const id = next++; pending.set(id, { resolve, reject }); transport.send({ jsonrpc: '2.0', id, method, params }).catch(reject); });
  await rpc('initialize', { protocolVersion: '2025-06-18', capabilities: {}, clientInfo: { name: 'pi-fm-evals', version: '1' } });
  await transport.send({ jsonrpc: '2.0', method: 'notifications/initialized' });
  const tools = [];
  let cursor;
  do { const page = await rpc('tools/list', cursor ? { cursor } : {}); tools.push(...page.tools); cursor = page.nextCursor; } while (cursor);
  const call = async (name, args = {}) => {
    const result = await rpc('tools/call', { name, arguments: args });
    const text = (result.content ?? []).filter(c => c.type === 'text').map(c => c.text).join('');
    if (result.isError) throw new Error(`${name}: ${text}`);
    if (result.structuredContent && typeof result.structuredContent === 'object') {
      const s = result.structuredContent;
      return Object.keys(s).length === 1 && 'result' in s ? s.result : s;
    }
    try { return JSON.parse(text); } catch { return text; }
  };
  return { session, transport, tools, call, close: () => transport.close() };
}

if (process.argv[1] && fileURLToPath(import.meta.url) === path.resolve(process.argv[1])) {
  if (!process.env.FMCP_CACHE_DIR) { console.error('Set FMCP_CACHE_DIR (an eval cache, never the owner\'s).'); process.exit(2); }
  const [cmd, a, b] = process.argv.slice(2);
  const reader = await connectReader();
  try {
    if (cmd === 'tools') {
      for (const t of reader.tools) console.log(`${t.name}\t${JSON.stringify(t).length}`);
    } else if (cmd === 'guide-sql') {
      // Run every ```sql block of a guide; a block preceded by a line containing `view: "manager"`
      // runs in the manager view. `?` parameters take the values in a following <!-- params: [...] -->.
      const fs = await import('node:fs');
      const text = fs.readFileSync(a, 'utf8');
      const blocks = [...text.matchAll(/```sql\n([\s\S]*?)```(?:\n<!-- params: (.*?) -->)?/g)];
      let failed = 0;
      for (const m of blocks) {
        const [, sql, params] = m;
        // The view is named on the last non-empty line before the block.
        const before = text.slice(0, m.index).trimEnd().split('\n').at(-1) ?? '';
        const view = /view: "manager"`?$/.test(before.trim()) ? 'manager' : 'full';
        const t0 = Date.now();
        try {
          const r = await reader.call('fm_db_query', { sql, view, max_rows: 25, ...(params ? { params: JSON.parse(params) } : {}) });
          console.log(`OK ${view} ${r.row_count} rows ${Date.now() - t0} ms: ${sql.split('\n')[0].slice(0, 90)}`);
          for (const row of (r.rows ?? []).slice(0, b ? Number(b) : 3)) console.log(`   ${JSON.stringify(row).slice(0, 220)}`);
          if (!r.row_count) { failed += 1; console.log('   EMPTY'); }
        } catch (error) { failed += 1; console.log(`FAIL ${view}: ${sql.split('\n')[0]}\n   ${String(error.message).slice(0, 300)}`); }
      }
      console.log(`${blocks.length} blocks, ${failed} failed or empty`);
      process.exitCode = failed ? 1 : 0;
    } else if (cmd === 'describe') {
      for (const name of process.argv.slice(3)) {
        const t = reader.tools.find(x => x.name === name);
        console.log(`## ${name} ${JSON.stringify(t?.inputSchema?.properties ?? null)}\n${t?.description ?? '(absent)'}\n`);
      }
    } else if (cmd === 'call') {
      console.log(JSON.stringify(await reader.call(a, b ? JSON.parse(b) : {}), null, 1));
    } else if (cmd === 'sql') {
      const r = await reader.call('fm_db_query', { sql: a, view: b === 'manager' ? 'manager' : 'full', max_rows: 50 });
      console.log(JSON.stringify({ columns: r.columns, row_count: r.row_count, truncated: r.truncated, snapshot: r.snapshot, notes: r.notes }));
      for (const row of r.rows ?? []) console.log(JSON.stringify(row));
    } else {
      console.error('usage: reader-client.mjs call <tool> <json> | sql <select> [manager] | tools');
      process.exitCode = 2;
    }
  } finally { await reader.close(); }
}
