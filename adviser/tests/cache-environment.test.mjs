import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { mkdtempSync, readFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import test from 'node:test';
import { fileURLToPath } from 'node:url';

const root = fileURLToPath(new URL('../', import.meta.url));
const defaultDirectory = '/Volumes/4TB Private/Offloaded/Agent Work/fmcp-source-cache';

for (const [label, override] of [['unset', undefined], ['custom', '/tmp/fm custom cache'], ['empty', '']]) {
  test(`forwards the ${label} cache setting to the reader child`, () => {
    const directory = mkdtempSync(join(tmpdir(), 'pi-fm-cache-env-'));
    try {
      const env = {
        ...process.env, PI_OFFLINE: '1', PI_FM_MODEL: 'papercut-fixture/offline',
        PI_FM_TEST_ROUTE: 'reader', PI_FM_MCP_LAUNCHER: join(root, 'tests/startup-reader-fixture.sh'),
        PI_FM_TEST_READER_DIR: directory,
      };
      if (override === undefined) delete env.FMCP_CACHE_DIR;
      else env.FMCP_CACHE_DIR = override;
      const result = spawnSync(join(root, 'bin/pi-fm'), [
        '--no-session', '--mode', 'json', '--print', '-e', join(root, 'tests/papercut-provider.pi.ts'), 'Check cache forwarding',
      ], { encoding: 'utf8', env, timeout: 90000, maxBuffer: 4 * 1024 * 1024 });
      assert.equal(result.status, 0, result.stderr || String(result.error));
      const actual = JSON.parse(readFileSync(join(directory, 'cache-env.json'), 'utf8'));
      assert.equal(actual, override ?? defaultDirectory);
    } finally {
      rmSync(directory, { recursive: true, force: true });
    }
  });
}
