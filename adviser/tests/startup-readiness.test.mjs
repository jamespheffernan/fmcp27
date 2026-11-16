import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { mkdtempSync, readFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import test from 'node:test';
import { fileURLToPath } from 'node:url';

const root = fileURLToPath(new URL('../', import.meta.url));
const readerFixture = join(root, 'tests/startup-reader-fixture.sh');
const providerFixture = join(root, 'tests/papercut-provider.pi.ts');

for (const failedStarts of [0, 1, 2]) {
  test(`reads after ${failedStarts} failed reader starts or reports exhausted recovery`, () => {
    const directory = mkdtempSync(join(tmpdir(), 'pi-fm-readiness-'));
    try {
      const result = spawnSync(join(root, 'bin/pi-fm'), [
        '--no-session', '--mode', 'json', '--print', '-e', providerFixture, 'Check reader discovery',
      ], {
        encoding: 'utf8', timeout: 90000, maxBuffer: 4 * 1024 * 1024,
        env: { ...process.env, PI_OFFLINE: '1', PI_FM_MODEL: 'papercut-fixture/offline',
          PI_FM_TEST_ROUTE: 'reader', PI_FM_MCP_LAUNCHER: readerFixture,
          PI_FM_TEST_FAILED_STARTS: String(failedStarts), PI_FM_TEST_READER_DIR: directory },
      });
      assert.equal(result.status, 0, result.stderr || String(result.error));
      const events = result.stdout.trim().split('\n').map(line => JSON.parse(line));
      const requests = readFileSync(join(directory, 'requests.jsonl'), 'utf8').trim().split('\n').map(line => JSON.parse(line));
      const reachable = failedStarts < 2;
      assert.equal(requests.filter(r => r.method === 'initialize').length, Math.min(failedStarts + 1, 2));
      // A reachable reader gets the harness's own fm_attach before the first model call
      // (pi/fm-reader-session.mjs), then the one read the model makes. An unreachable one gets neither.
      assert.deepEqual(requests.filter(r => r.method === 'tools/call').map(r => r.name), reachable ? ['fm_attach', 'fm_status'] : []);
      const final = events.findLast(e => e.type === 'message_end' && e.message.role === 'assistant');
      const declared = JSON.parse(final.message.content.find(c => c.type === 'text').text).declaredTools;
      // fm_status is a deferred reader tool (pi/fm-exposure.mjs): it is never declared to the model
      // directly, and the model's script finds and calls it exactly when the reader is up.
      assert.equal(declared.includes('mcp__fm_live__fm_status'), false);
      const status = events.filter(e => e.type === 'tool_execution_end' && e.toolName === 'mcp__fm_live__fm_status');
      assert.equal(status.length, reachable ? 1 : 0);
      if (reachable) assert.equal(Boolean(status[0].isError), false);
      const script = events.find(e => e.type === 'tool_execution_end' && e.toolName === 'codemode');
      assert.equal(JSON.stringify(script.result).includes('reader absent'), !reachable);
      const unavailable = events.some(e => e.type === 'message_end' && e.message.customType === 'fm-reader-unavailable');
      assert.equal(unavailable, !reachable);
    } finally {
      rmSync(directory, { recursive: true, force: true });
    }
  });
}
