import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { mkdirSync, mkdtempSync, readFileSync } from 'node:fs';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';
import test from 'node:test';

const root = fileURLToPath(new URL('../', import.meta.url));

test('installed Pi supplies actual nested arguments, outcomes and resumable activity history', () => {
  mkdirSync(join(root, 'tmp'), { recursive: true });
  const dir = mkdtempSync(join(root, 'tmp', 'activity-runtime-'));
  const receipt = join(dir, 'activity.json');
  const steps = [
    { name: 'codemode', arguments: { code: `
      // A mentioned call is not an executed call.
      if (false) await tools.mcp__fm_live__fm_get_player_bans({});
      const query = tools['mcp__fm_live__fm_db_query'];
      text(await query({sql: 'SELECT name FROM m_player_view', view: 'manager'}));
    ` } },
    { name: 'codemode', arguments: { code: `
      text(await tools.mcp__fm_live__fm_db_query({sql: 'SELECT * FROM promise', view: 'full'}));
      try { await tools.mcp__fm_live__fm_set_tactic({}); } catch (_) { text('Failure handled'); }
    ` } },
  ];
  const run = spawnSync(join(root, 'bin/pi-fm'), [
    '--mode', 'json', '--print', '-e', join(root, 'tests/toolbox-provider.pi.ts'),
    '-e', join(root, 'tests/activity-observer.pi.ts'), 'Check the fixture evidence',
  ], {
    encoding: 'utf8', timeout: 60000, maxBuffer: 8 * 1024 * 1024,
    env: { ...process.env, PI_OFFLINE: '1', PI_FM_MODEL: 'toolbox-fixture/offline',
      PI_FM_MCP_LAUNCHER: join(root, 'tests/exposure-reader-fixture.sh'),
      PI_FM_SESSION_DIR: join(dir, 'sessions'), PI_FM_CARD_DIR: join(dir, 'cards'),
      PI_FM_TOOLBOX_DIR: join(dir, 'toolbox'), PI_FM_TEST_READER_DIR: dir,
      PI_FM_TEST_TOOLS: 'fm_status,fm_attach,fm_get_save,fm_db_schema,fm_db_query,fm_set_tactic',
      PI_FM_TEST_WRITERS: 'fm_set_tactic', PI_FM_TEST_STEPS: JSON.stringify(steps),
      PI_FM_ACTIVITY_RECEIPT: receipt },
  });
  assert.equal(run.status, 0, run.stderr || String(run.error));
  const data = JSON.parse(readFileSync(receipt, 'utf8'));
  assert.ok(data.snapshots.some(row => row.text === 'Reading player profiles' && row.detail === 'Using your manager’s knowledge'));
  assert.ok(data.snapshots.some(row => row.detail?.includes('2 results returned')));
  assert.equal(data.live.length, 1);
  assert.equal(data.live[0].failed, 1);
  assert.match(data.live[0].text, /Could not/);
  assert.match(data.live[0].detail, /player promises and player profiles/);
  assert.deepEqual(data.restored, data.live);
  assert.doesNotMatch(JSON.stringify(data), /suspensions|player bans/);
});
