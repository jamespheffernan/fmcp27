import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import test from 'node:test';
import { childFailure } from './child-result.mjs';

for (const [kind, code, options, expected] of [
  ['status', 'process.stdout.write("before failure");process.stderr.write("failure detail");process.exit(7)', {}, ['status=7 signal=null', 'before failure', 'failure detail', 'error=none']],
  ['signal', 'process.stdout.write("before signal");process.kill(process.pid,"SIGTERM")', {}, ['status=null signal=SIGTERM', 'before signal']],
  ['timeout', 'process.stdout.write("before timeout");setInterval(()=>{},1000)', {timeout:100}, ['status=null signal=SIGTERM', 'ETIMEDOUT', 'stdout(']],
]) {
  test(`child diagnostics retain ${kind}, context and bounded output`, () => {
    const result = spawnSync(process.execPath, ['-e', code], {encoding:'utf8', ...options});
    const message = childFailure(result, `controlled ${kind} failure`);
    assert.match(message, new RegExp(`context=controlled ${kind} failure`));
    for (const part of expected) assert.ok(message.includes(part), message);
    assert.notEqual(result.status, 0);
  });
}

test('child diagnostics retain launch errors and cap all diagnostic fields', () => {
  const failed = spawnSync('/nonexistent-offline-fixture-executable', [], {encoding:'utf8'});
  assert.match(childFailure(failed, 'missing test fixture'), /ENOENT/);
  const large = childFailure({status:null,signal:'SIGTERM',error:new Error('E'.repeat(20000)),stdout:'head'+'o'.repeat(20000)+'tail',stderr:'head'+'e'.repeat(20000)+'tail'}, 'C'.repeat(20000));
  assert.ok(large.length < 12000);
  assert.match(large, /truncated/);
  assert.match(large, /stdout\(20008 characters\)/);
  assert.match(large, /stderr\(20008 characters\)/);
  assert.match(large, /tail/);
});
