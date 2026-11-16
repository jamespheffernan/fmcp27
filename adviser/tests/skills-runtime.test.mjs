import assert from 'node:assert/strict';
import { mkdtempSync, mkdirSync, symlinkSync, readFileSync, writeFileSync, realpathSync } from 'node:fs';
import { homedir, tmpdir } from 'node:os';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { createHash } from 'node:crypto';
import { spawnSync } from 'node:child_process';
import test from 'node:test';

const root = fileURLToPath(new URL('../', import.meta.url));
for (const route of ['skills-direct', 'skills-dynamics-direct', 'skills-codemode']) {
  test(`isolated Pi fixture loads complete approved guidance through ${route}`, () => {
    const scratch = mkdtempSync(join(root, 'evidence', `${route}-`));
    const home = realpathSync(mkdtempSync(join(tmpdir(), 'pi-fm-skills-home-')));
    mkdirSync(join(home, '.agents'));
    symlinkSync(join(homedir(), '.agents', 'skills'), join(home, '.agents', 'skills'));
    const run = spawnSync(join(root, 'bin/pi-fm'), [
      '-e', join(root, 'tests/papercut-provider.pi.ts'), '--no-mcp', '--mode', 'json', '--print', 'Verify guidance loading',
    ], { encoding: 'utf8', timeout: 30000, env: {
      ...process.env, HOME: home, PI_CODING_AGENT_DIR: join(scratch, '.pi', 'agent'),
      PI_FM_SESSION_DIR: join(scratch, 'sessions'), PI_FM_MODEL: 'papercut-fixture/offline',
      PI_FM_TEST_ROUTE: route, PI_OFFLINE: '1',
      PI_FM_MCP_LAUNCHER: join(root, 'tests/startup-reader-fixture.sh'), PI_FM_TEST_READER_DIR: scratch,
      PI_FM_TEST_FAILED_STARTS: '0', PI_FM_TEST_FIRST_DELAY: '0',
    } });
    writeFileSync(join(scratch, 'runtime.jsonl'), run.stdout);
    writeFileSync(join(scratch, 'stderr.txt'), run.stderr);
    assert.equal(run.status, 0, run.stderr || String(run.error));
    const events = run.stdout.trim().split('\n').map(line => JSON.parse(line));
    const calls = events.filter(e => e.type === 'tool_execution_end' && e.toolName === 'fm_read_skill');
    const loaded = calls.filter(e => e.result?.details?.kind === 'guidance');
    const expected = route === 'skills-direct' ? ['fm-recruitment']
      : route === 'skills-dynamics-direct' ? ['fm-playing-time-dynamics'] : [
      'fm-tools', 'fm-live-investigation', 'fm-tactical-analysis', 'fm-create-tactic',
      'fm-club-finance', 'fm-squad-planning', 'fm-training-development', 'fm-staff-planning', 'fm-contracts-loans', 'fm-season-planning', 'fm-recruitment', 'fm-playing-time-dynamics', 'fm-set-pieces', 'fm-club-development',
    ];
    assert.deepEqual(loaded.map(e => e.result.details.id).sort(), expected.sort());
    for (const event of loaded) {
      assert.equal(event.isError, false);
      const { id, content, sha256 } = event.result.details;
      const original = readFileSync(join(root, 'skills', id, 'SKILL.md'));
      assert.equal(content, original.toString('utf8'));
      assert.equal(sha256, createHash('sha256').update(original).digest('hex'));
    }
    if (route === 'skills-codemode') {
      assert.ok(events.some(e => e.type === 'tool_execution_end' && e.toolName === 'codemode' && !e.isError));
      const invalid = events.find(e => e.type === 'tool_execution_start' && e.toolName === 'fm_read_skill' && e.args?.id === '../../etc/passwd');
      assert.ok(invalid);
      assert.ok(calls.some(e => e.toolCallId === invalid.toolCallId && e.isError));
    }
    const final = events.filter(e => e.type === 'message_end' && e.message?.role === 'assistant').at(-1);
    const receipt = JSON.parse(final.message.content.find(c => c.type === 'text').text);
    assert.equal(receipt.guidanceIndexLoaded, true);
    assert.deepEqual(receipt.loadedGuides, []);
    for (const name of ['bash', 'read', 'write', 'edit']) assert.ok(!receipt.declaredTools.includes(name));
  });
}
