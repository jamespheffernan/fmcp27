import assert from 'node:assert/strict';
import { mkdirSync, mkdtempSync, readFileSync, symlinkSync, writeFileSync, existsSync, rmSync, realpathSync } from 'node:fs';
import { homedir, tmpdir } from 'node:os';
import { join, relative } from 'node:path';
import { fileURLToPath } from 'node:url';
import { spawnSync } from 'node:child_process';
import test from 'node:test';
import { registerTextFileTool } from '../pi/fm-text-files.mjs';

const root = fileURLToPath(new URL('../', import.meta.url));
mkdirSync(join(root, 'evidence'), { recursive: true });
let tool;
registerTextFileTool({ registerTool(value) { tool = value; } });
const write = (path, content = 'Tactical notes — café\n') => tool.execute('test', { path, content });

test('text writer creates UTF-8 project files and protects existing content and path boundaries', async () => {
  const scratch = mkdtempSync(join(root, 'evidence/text-boundary-'));
  try {
    const path = join(scratch, 'notes', 'report.md');
    const result = await write(relative(root, path));
    assert.equal(result.isError, undefined);
    assert.equal(result.details.path, path);
    assert.equal(readFileSync(path, 'utf8'), 'Tactical notes — café\n');
    assert.equal(result.details.bytes, Buffer.byteLength('Tactical notes — café\n'));
    assert.equal((await write(path, 'replace')).isError, true);
    assert.equal(readFileSync(path, 'utf8'), 'Tactical notes — café\n');

    const sentinel = join(scratch, 'sentinel.txt');
    writeFileSync(sentinel, 'untouched');
    symlinkSync(sentinel, join(scratch, 'linked.txt'));
    symlinkSync(join(scratch, 'notes'), join(scratch, 'linked-dir'));
    for (const path of [
      join(scratch, 'linked.txt'), join(scratch, 'linked-dir', 'new.md'),
      '/tmp/pi-fm-forbidden.txt', join(root, '..', 'fm-advisor-sibling', 'new.txt'),
      join(scratch, '.git', 'config.txt'), join(scratch, 'node_modules', 'new.md'),
      join(scratch, 'script.sh'), join(scratch, 'tactic.fmf'),
    ]) {
      assert.equal((await write(path)).isError, true, path);
    }
    assert.equal(readFileSync(sentinel, 'utf8'), 'untouched');
    assert.equal(existsSync(join(scratch, 'notes', 'new.md')), false);
    assert.equal((await write(join(scratch, 'binary.txt'), '\0binary')).isError, true);
    assert.equal((await write(join(scratch, 'large.txt'), 'é'.repeat(524289))).isError, true);
    assert.equal(existsSync(join(scratch, 'large.txt')), false);
    assert.equal((await write(join(scratch, 'empty.txt'), '')).isError, undefined);
    const racePath = join(scratch, 'race.csv');
    const outcomes = await Promise.all([write(racePath, 'one'), write(racePath, 'two')]);
    assert.equal(outcomes.filter(result => !result.isError).length, 1);
    assert.ok(['one', 'two'].includes(readFileSync(racePath, 'utf8')));
  } finally {
    rmSync(scratch, { recursive: true, force: true });
  }
});

for (const route of ['text-direct', 'text-codemode']) {
  test(`installed Pi writes text through ${route} and receives the guidance index`, () => {
    const scratch = mkdtempSync(join(root, 'evidence', `${route}-`));
    const home = realpathSync(mkdtempSync(join(tmpdir(), 'pi-fm-home-')));
    mkdirSync(join(home, '.agents'));
    symlinkSync(join(homedir(), '.agents', 'skills'), join(home, '.agents', 'skills'));
    try {
      const path = route === 'text-direct' ? '~/Agent Outputs/report.md' : join(scratch, 'project-report.csv');
      const content = 'Verified text — UTF-8\n';
      const run = spawnSync(join(root, 'bin/pi-fm'), [
        '-e', join(root, 'tests/papercut-provider.pi.ts'), '--no-mcp', '--mode', 'json', '--print', 'Verify text output',
      ], {
        encoding: 'utf8', timeout: 30000,
        env: { ...process.env, HOME: home, PI_CODING_AGENT_DIR: join(scratch, '.pi', 'agent'),
          PI_FM_SESSION_DIR: join(scratch, 'sessions'), PI_FM_MODEL: 'papercut-fixture/offline',
          PI_FM_TEST_ROUTE: route, PI_FM_TEST_TEXT_PARAMS: JSON.stringify({ path, content }), PI_OFFLINE: '1',
          PI_FM_MCP_LAUNCHER: join(root, 'tests/startup-reader-fixture.sh'), PI_FM_TEST_READER_DIR: scratch,
          PI_FM_TEST_FAILED_STARTS: '0', PI_FM_TEST_FIRST_DELAY: '0' },
      });
      writeFileSync(join(scratch, 'runtime.jsonl'), run.stdout);
      writeFileSync(join(scratch, 'stderr.txt'), run.stderr);
      assert.equal(run.status, 0, run.stderr || String(run.error));
      const events = run.stdout.trim().split('\n').map(line => JSON.parse(line));
      const calls = events.filter(event => event.type === 'tool_execution_end');
      assert.ok(calls.some(event => event.toolName === 'fm_write_text' && !event.isError));
      if (route === 'text-codemode') assert.ok(calls.some(event => event.toolName === 'codemode' && !event.isError));
      assert.equal(readFileSync(route === 'text-direct' ? join(home, 'Agent Outputs/report.md') : path, 'utf8'), content);
      const final = events.filter(event => event.type === 'message_end' && event.message?.role === 'assistant').at(-1);
      const receipt = JSON.parse(final.message.content.find(block => block.type === 'text').text);
      assert.equal(receipt.loadedGuides.length, 0);
      assert.equal(receipt.guidanceIndexLoaded, true);
      assert.ok(receipt.declaredTools.includes('fm_read_skill'));
      assert.ok(receipt.declaredTools.includes('fm_write_text'));
      for (const forbidden of ['bash', 'read', 'write', 'edit']) assert.ok(!receipt.declaredTools.includes(forbidden));
    } finally {
      rmSync(home, { recursive: true, force: true });
    }
  });
}


test('Agent Outputs is an independent allowed root, not a grant to the rest of home', async () => {
  const home = realpathSync(mkdtempSync(join(tmpdir(), 'pi-fm-outputs-')));
  const previous = process.env.HOME;
  process.env.HOME = home;
  try {
    const destination = join(home, 'Agent Outputs', 'nested', 'notes.txt');
    assert.equal((await write(destination)).isError, undefined);
    assert.equal(readFileSync(destination, 'utf8'), 'Tactical notes — café\n');
    for (const path of [
      join(home, 'other.txt'), join(home, 'Agent Outputs-sibling', 'notes.txt'),
      '~/Agent Outputs/../outside.txt',
    ]) assert.equal((await write(path)).isError, true, path);
    assert.equal(existsSync(join(home, 'outside.txt')), false);
    rmSync(join(home, 'Agent Outputs'), { recursive: true });
    mkdirSync(join(home, 'elsewhere'));
    symlinkSync(join(home, 'elsewhere'), join(home, 'Agent Outputs'));
    assert.equal((await write('~/Agent Outputs/escape.txt')).isError, true);
    assert.equal(existsSync(join(home, 'elsewhere', 'escape.txt')), false);
  } finally {
    if (previous === undefined) delete process.env.HOME;
    else process.env.HOME = previous;
    rmSync(home, { recursive: true, force: true });
  }
});

test('the registered writer refuses a relocated parent and never reports a stale path as success', () => {
  const result = spawnSync('/usr/bin/python3', [join(root, 'tests/text-relocation-races.py')], { encoding: 'utf8', timeout: 30000 });
  assert.equal(result.status, 0, result.stderr || String(result.error));
  assert.deepEqual(JSON.parse(result.stdout), { checked_relocations: 2 });
});

test('concurrent parent replacement cannot redirect the text writer', () => {
  const result = spawnSync('/usr/bin/python3', [join(root, 'tests/text-path-races.py')], { encoding: 'utf8', timeout: 10000 });
  assert.equal(result.status, 0, result.stderr || String(result.error));
  assert.deepEqual(JSON.parse(result.stdout), { checked_interleavings: 3 });
});
