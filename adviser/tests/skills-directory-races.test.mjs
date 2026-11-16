import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import test from 'node:test';

test('bound directory/file descriptors withhold replacements without reading outside data', () => {
  const run = spawnSync('/usr/bin/python3', ['-I', '-S', '-B', fileURLToPath(new URL('./skills-directory-races.py', import.meta.url))],
    { encoding: 'utf8', timeout: 10000 });
  assert.equal(run.status, 0, run.stderr || String(run.error));
  const result = JSON.parse(run.stdout);
  assert.equal(result.state, 'PASS');
  assert.equal(result.replacement_cases.length, 10);
  assert.ok(result.replacement_cases.every(c => c.withheld && c.outside_file_reads === 0 && c.descriptors_closed));
  assert.equal(result.short_reads_at_exact_64KiB, true);
  assert.equal(result.close_failure_withheld, true);
  assert.equal(result.outside_content_returned, false);
});
