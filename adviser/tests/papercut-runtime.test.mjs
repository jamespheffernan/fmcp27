import assert from 'node:assert/strict';
import { mkdirSync, mkdtempSync, readFileSync, symlinkSync } from 'node:fs';
import { homedir } from 'node:os';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { spawnSync } from 'node:child_process';
import test from 'node:test';

const root = fileURLToPath(new URL('../', import.meta.url));
for (const route of ['direct', 'codemode']) {
  test(`installed Pi logs a papercut through ${route} with FM attribution`, () => {
    mkdirSync(join(root, 'evidence'), { recursive: true });
    const scratch = mkdtempSync(join(root, 'evidence', `papercut-${route}-`));
    mkdirSync(join(scratch, '.agents'));
    symlinkSync(join(homedir(), '.agents', 'skills'), join(scratch, '.agents', 'skills'));
    const run = spawnSync(join(root, 'bin/pi-fm'), [
      '-e', join(root, 'tests/papercut-provider.pi.ts'), '--no-mcp', '--mode', 'json', '--print', 'Verify logging',
    ], {
      encoding: 'utf8', timeout: 30000,
      env: { ...process.env, HOME: scratch, PI_CODING_AGENT_DIR: join(scratch, '.pi', 'agent'),
        PI_FM_SESSION_DIR: join(scratch, 'sessions'), PI_FM_MODEL: 'papercut-fixture/offline',
        PI_FM_TEST_ROUTE: route, PI_OFFLINE: '1', PI_HARNESS: 'wrong-inherited-harness' },
    });
    assert.equal(run.status, 0, run.stderr || String(run.error));
    const events = run.stdout.trim().split('\n').map(line => JSON.parse(line));
    const calls = events.filter(e => e.type === 'tool_execution_end');
    assert.ok(calls.some(e => e.toolName === 'papercut' && !e.isError));
    if (route === 'codemode') assert.ok(calls.some(e => e.toolName === 'codemode' && !e.isError));
    const dir = join(scratch, '.pi', 'agent', 'papercuts');
    const rows = readFileSync(join(dir, 'history.jsonl'), 'utf8').trim().split('\n').map(JSON.parse);
    assert.equal(rows.length, 1);
    assert.equal(rows[0].harness, 'pi-fm');
    // papercut attributes the git top level when the adviser sits inside a repository (the reader
    // checkout or a worktree), and the adviser folder itself when installed standalone.
    const top = spawnSync('git', ['rev-parse', '--show-toplevel'], { cwd: root, encoding: 'utf8' });
    const repoDir = top.status === 0 ? top.stdout.trim() : root;
    assert.equal(rows[0].repo, repoDir.split('/').filter(Boolean).at(-1));
    assert.equal(rows[0].event, 'logged');
    assert.match(rows[0].id, /^pc-[0-9a-f]{8}$/);
    assert.ok(readFileSync(join(dir, 'open.md'), 'utf8').includes(rows[0].id));
  });
}
