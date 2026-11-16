import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { mkdtempSync, mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';
import test from 'node:test';

const root = fileURLToPath(new URL('../', import.meta.url));
for (const state of ['missing', 'changed']) {
  test(`native release check reports unsupported_build for a ${state} binary before generation`, () => {
    mkdirSync(join(root, 'tmp'), { recursive: true });
    const scratch = mkdtempSync(join(root, 'tmp', 'native-preflight-'));
    const binary = join(scratch, 'game_plugin');
    if (state === 'changed') writeFileSync(binary, 'Different native build fixture');
    const run = spawnSync(process.execPath, [join(root, 'tests/native-tactics-release.mjs')], {
      encoding: 'utf8', timeout: 10_000, env: { ...process.env, PI_FM_NATIVE_BINARY: binary, PI_FM_TACTIC_PYTHON: '/nonexistent/codec-must-not-run' },
    });
    assert.equal(run.status, 2, run.stderr || String(run.error));
    const receipt = JSON.parse(run.stderr);
    assert.equal(receipt.state, 'unsupported_build');
    assert.equal(receipt.native_binary, binary);
    assert.match(receipt.expected_native_binary_sha256, /^[a-f0-9]{64}$/);
    assert.equal(JSON.parse(readFileSync(receipt.receipt)).state, 'unsupported_build');
    assert.equal(run.stdout, '');
  });
}
