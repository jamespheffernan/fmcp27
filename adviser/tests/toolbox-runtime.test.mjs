// The toolbox through the real launcher and the installed Pi: the adviser saves a tool, a later
// script runs it inside Pi's Code Mode sandbox, and a second pi-fm process finds it in its prompt.
import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { mkdtempSync, readFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import test from 'node:test';
import { fileURLToPath } from 'node:url';

const root = fileURLToPath(new URL('../', import.meta.url));
const READER_TOOLS = ['fm_status', 'fm_attach', 'fm_get_save', 'fm_db_schema', 'fm_db_query', 'fm_db_read', 'fm_set_tactic'];

function session(directory, steps) {
  const reader = mkdtempSync(join(directory, 'reader-'));
  const result = spawnSync(join(root, 'bin/pi-fm'), [
    '--no-session', '--mode', 'json', '--print', '-e', join(root, 'tests/toolbox-provider.pi.ts'), 'Build a reusable squad model',
  ], {
    encoding: 'utf8', timeout: 90000, maxBuffer: 8 * 1024 * 1024,
    env: { ...process.env, PI_OFFLINE: '1', PI_FM_MODEL: 'toolbox-fixture/offline',
      PI_FM_MCP_LAUNCHER: join(root, 'tests/exposure-reader-fixture.sh'), PI_FM_CARD_DIR: join(directory, 'cards'),
      PI_FM_TOOLBOX_DIR: join(directory, 'toolbox'), PI_FM_TEST_READER_DIR: reader,
      PI_FM_TEST_TOOLS: READER_TOOLS.join(','), PI_FM_TEST_WRITERS: 'fm_set_tactic', PI_FM_TEST_STEPS: JSON.stringify(steps) },
  });
  assert.equal(result.status, 0, result.stderr || String(result.error));
  const events = result.stdout.trim().split('\n').map(line => JSON.parse(line));
  const final = events.findLast(event => event.type === 'message_end' && event.message.role === 'assistant');
  const seen = JSON.parse(final.message.content.find(content => content.type === 'text').text);
  const requests = readFileSync(join(reader, 'requests.jsonl'), 'utf8').trim().split('\n').map(JSON.parse)
    .filter(request => request.method === 'tools/call');
  return { seen, requests };
}

const TOOL_CODE = [
  'const { times = 1 } = args;',
  'const read = await tools.mcp__fm_live__fm_db_query({ sql: "SELECT idx, name FROM player_view" });',
  'const data = read.structuredContent ?? JSON.parse(read.content[0].text);',
  'return { players: data.rows.length * times, names: data.rows.map(row => row[1]) };',
].join('\n');

test('actual Pi: the adviser saves a tool, runs it from Code Mode, and a later session is told about it', () => {
  const directory = mkdtempSync(join(tmpdir(), 'pi-fm-toolbox-runtime-'));
  try {
    const first = session(directory, [
      { name: 'fm_toolbox', arguments: { action: 'save', name: 'squad_count', description: 'Counts the first team, times a factor.',
        args: '{ times = 1 }', returns: '{ players, names }', code: TOOL_CODE } },
      { name: 'codemode', arguments: { code: 'const out = await toolbox.squad_count({ times: 21 });\nreturn out;' } },
      { name: 'codemode', arguments: { code: 'return await toolbox.transfer_budget();' } },
      { name: 'fm_toolbox', arguments: { action: 'save', name: 'change_game', description: 'Tries a write.',
        code: 'return await tools.mcp__fm_live__fm_set_tactic({});' } },
      { name: 'codemode', arguments: { code: 'return await toolbox.change_game();' } },
    ]);
    assert.ok(first.seen.declared.includes('fm_toolbox'), 'fm_toolbox is declared to the model');
    assert.equal(first.seen.promptHasMarkers, false);
    assert.match(first.seen.toolboxSection, /You build tools for yourself/);
    assert.match(first.seen.toolboxSection, /No tools saved yet\./);

    const [saved, ran, missing, , blocked] = first.seen.results;
    assert.equal(saved.isError, false, saved.text);
    const receipt = JSON.parse(saved.text);
    assert.equal(receipt.revision, 1);
    assert.equal(receipt.game_date, '2030-12-13', 'the save records the game date it was built on');
    assert.equal(receipt.path, join(directory, 'toolbox', 'squad_count.js'));

    // Pi's own sandbox ran the saved function: two fixture rows, times 21.
    assert.equal(ran.isError, false, ran.text);
    assert.match(ran.text, /^Script completed/);
    assert.match(ran.text, /"players":\s*42/);
    assert.match(ran.text, /"names":\s*\[\s*"A",\s*"B"\s*\]/);
    // Its reader call went through the harness like any other: the model passed no session id.
    const query = first.requests.find(request => request.name === 'fm_db_query' && /FROM player_view$/.test(request.args.sql));
    assert.ok(query, 'the saved tool reached the reader');
    assert.equal(query.args.session_id, 'S1');

    assert.match(missing.text, /^Script failed/);
    assert.match(missing.text, /No saved tool "transfer_budget"\. Saved tools: squad_count\./);

    // Saving a tool grants nothing: a saved tool that calls a tool the adviser may not call is refused
    // by the same gate, and the call never reaches the reader.
    assert.match(blocked.text, /^Script failed/);
    assert.match(blocked.text, /toolbox\.change_game: [\s\S]*pi-fm permits/);
    assert.equal(first.requests.some(request => request.name === 'fm_set_tactic'), false);

    const second = session(directory, [
      { name: 'codemode', arguments: { code: 'return (await toolbox.squad_count()).players;' } },
    ]);
    assert.match(second.seen.toolboxSection, /Saved tools \(2\):/);
    assert.match(second.seen.toolboxSection,
      /- `toolbox\.squad_count\(args\)` — Counts the first team, times a factor\. Args: \{ times = 1 \} Returns: \{ players, names \}/);
    assert.match(second.seen.results[0].text, /^Script completed[\s\S]*\b2\b/);
  } finally {
    rmSync(directory, { recursive: true, force: true });
  }
});
