import assert from 'node:assert/strict';
import { mkdtempSync, writeFileSync, readFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { spawnSync } from 'node:child_process';
import test from 'node:test';

const root = fileURLToPath(new URL('../', import.meta.url)).replace(/\/$/, '');
const launcher = join(root, 'bin/pi-fm');

test('fails clearly before Pi starts when the FM reader is missing', () => {
  const result = spawnSync(launcher, ['--help'], {
    encoding: 'utf8', env: { ...process.env, PI_FM_MCP_LAUNCHER: '/nonexistent/fm-reader-for-test.sh' },
  });
  assert.equal(result.status, 1);
  assert.equal(result.stdout, '');
  assert.match(result.stderr, /pi-fm: FM live reader missing: \/nonexistent\/fm-reader-for-test.sh/);
});

test('keeps isolation flags, paths with spaces, resume arguments and overrides intact', () => {
  const scratch = mkdtempSync(join(tmpdir(), 'pi-fm-launcher-'));
  try {
    writeFileSync(join(scratch, 'pi'), '#!/usr/bin/env python3\nimport json,os,sys\nprint(json.dumps({"args":sys.argv[1:],"cwd":os.getcwd()}))\n', { mode: 0o755 });
    const result = spawnSync(launcher, ['--continue', '--print', 'Compare Gordon and Hall'], {
      encoding: 'utf8', cwd: '/', env: {
        ...process.env, PATH: `${scratch}:${process.env.PATH}`, PI_FM_MCP_LAUNCHER: launcher,
        PI_FM_MODEL: 'example/test-model', PI_FM_SESSION_DIR: join(scratch, 'sessions with spaces'),
      },
    });
    assert.equal(result.status, 0, result.stderr);
    const { args, cwd } = JSON.parse(result.stdout);
    assert.equal(cwd, root);
    for (const flag of ['--no-extensions', '--no-skills', '--no-context-files', '--no-prompt-templates', '--no-builtin-tools']) assert.ok(args.includes(flag), flag);
    for (const [flag, value] of [
      // fm_match_report joins only when the reader ships run_match_report.sh; fm_report ships in pi/.
      ['--tools', 'codemode,tool_search,papercut,fm_tactic_file,fm_write_text,fm_read_skill,fm_toolbox,fm_report,mcp__fm_live__*'], ['--model', 'example/test-model'], ['--models', 'example/test-model'],
      ['--session-dir', join(scratch, 'sessions with spaces')],
    ]) assert.equal(args[args.indexOf(flag) + 1], value);
    const prompt = args[args.indexOf('--append-system-prompt') + 1];
    for (const name of ['fm-live-investigation', 'fm-tools', 'fm-tactical-analysis', 'fm-create-tactic', 'fm-club-finance', 'fm-squad-planning', 'fm-reports']) {
      assert.ok(prompt.includes(name), name);
      assert.ok(!prompt.includes(readFileSync(join(root, 'skills', name, 'SKILL.md'), 'utf8').trim()), `deferred ${name}`);
    }
    assert.match(prompt, /fm_read_skill/);
    assert.match(prompt, /# Core procedure/);
    // The always-loaded core guide and index stay under 2,500 tokens (about 4 characters each).
    assert.ok(prompt.length < 10000);
    assert.deepEqual(args.slice(-3), ['--continue', '--print', 'Compare Gordon and Hall']);
  } finally {
    rmSync(scratch, { recursive: true, force: true });
  }
});
