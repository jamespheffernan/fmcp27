import assert from 'node:assert/strict';
import { mkdirSync, mkdtempSync, readFileSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { spawnSync } from 'node:child_process';
import test from 'node:test';

const root = fileURLToPath(new URL('../', import.meta.url));
const source = process.env.PI_FM_POLICY_SOURCE || join(root, 'pi/fm.pi.ts');
for (const route of ['direct', 'codemode']) {
  test(`actual installed Pi ${route} hook permits only exact registered host writers and true FM reads`, () => {
    const evidence = join(root, 'evidence/host-write-policy-20261108');
    mkdirSync(evidence, { recursive: true });
    const scratch = mkdtempSync(join(evidence, `runtime-${route}-`));
    const receipt = join(scratch, 'fixture.json');
    const args = [
      '--no-extensions', '--no-skills', '--no-context-files', '--no-prompt-templates', '--no-builtin-tools',
      '--no-mcp', '--no-session', '--mode', 'json', '--print',
      '--session-dir', join(scratch, 'sessions'), '-e', source,
      '-e', join(root, 'tests/host-write-policy-runtime.pi.ts'),
      '--tools', 'codemode,mcp__fm_live__*,mcp__other__*',
      '--model', 'host-policy-fixture/offline', '--models', 'host-policy-fixture/offline',
      'Exercise the deterministic local policy fixture.',
    ];
    const run = spawnSync('pi', args, {
      cwd: root, encoding: 'utf8', timeout: 30000,
      env: { ...process.env, PI_CODING_AGENT_DIR: join(scratch, 'agent'), PI_OFFLINE: '1',
        PI_FM_POLICY_ROUTE: route, PI_FM_POLICY_RECEIPT: receipt,
        PI_FM_MCP_LAUNCHER: join(root, 'tests/startup-reader-fixture.sh'),
        PI_FM_TEST_READER_DIR: scratch, PI_FM_TEST_FAILED_STARTS: '0', PI_FM_TEST_FIRST_DELAY: '0' },
    });
    writeFileSync(join(scratch, 'stdout.jsonl'), run.stdout || '');
    writeFileSync(join(scratch, 'stderr.txt'), run.stderr || '');
    assert.equal(run.status, 0, run.stderr || String(run.error));
    const observed = JSON.parse(readFileSync(receipt, 'utf8'));
    const requests = readFileSync(join(scratch, 'requests.jsonl'), 'utf8').trim().split('\n').map(JSON.parse);
    assert.ok(requests.some(request => request.method === 'tools/list'));
    // The harness attaches to the game itself before the first model call (pi/fm-reader-session.mjs),
    // so its fm_attach is the one call the fixture sees. No policy tool may arrive over MCP transport.
    assert.deepEqual(requests.filter(request => request.method === 'tools/call').map(request => request.name), ['fm_attach'],
      'Only discovery and the harness attach may reach the isolated reader fixture; local policy tools do not use MCP transport');
    const allowed = observed.cases.filter(item => item.allowed).map(item => item.name);
    assert.deepEqual(observed.executed, allowed, 'Every exact writer and true FM read must execute once; other tools never execute');
    assert.equal(new Set(observed.executed).size, 7);
    const events = run.stdout.trim().split('\n').map(line => JSON.parse(line));
    const calls = events.filter(event => event.type === 'tool_execution_end');
    for (const item of observed.cases) {
      const matching = calls.filter(event => event.toolName === item.name);
      assert.equal(matching.length, 1, `${item.name}: actual dispatch event required`);
      assert.equal(Boolean(matching[0].isError), !item.allowed, item.name);
      if (!item.allowed) assert.match(JSON.stringify(matching[0]), /pi-fm permits/);
    }
    if (route === 'codemode') {
      assert.ok(calls.some(event => event.toolName === 'codemode' && !event.isError));
      // These are actual nested runtime dispatches, not manual invocation of a hook stub.
      const first = events.findIndex(event => event.type === 'tool_execution_start' && event.toolName === 'codemode');
      const last = events.findIndex(event => event.type === 'tool_execution_end' && event.toolName === 'codemode');
      assert.ok(first >= 0 && last > first);
      for (const item of observed.cases) assert.ok(events.slice(first+1, last).some(event =>
        event.type === 'tool_execution_end' && event.toolName === item.name), item.name);
    }
  });
}
