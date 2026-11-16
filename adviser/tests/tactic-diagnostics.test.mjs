import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { mkdirSync, mkdtempSync, readFileSync, writeFileSync, symlinkSync, realpathSync, existsSync } from 'node:fs';
import { homedir, tmpdir } from 'node:os';
import { join } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { spawnSync } from 'node:child_process';
import test from 'node:test';
import { runTacticFile, registerTacticFileTool } from '../pi/fm-tactic-files.mjs';
import { registerSkillTool } from '../pi/fm-skills.mjs';

const root = fileURLToPath(new URL('../', import.meta.url));
const globalModules = join(homedir(), '.bun/install/global/node_modules');
const { Compile } = await import(pathToFileURL(join(globalModules, 'typebox/build/compile/index.mjs')).href);
const { validateToolArguments } = await import(pathToFileURL(join(globalModules, '@earendil-works/pi-ai/dist/utils/validation.js')).href);
const template = join(homedir(), 'Library/Application Support/Sports Interactive/Football Manager 27/Tactics/4231 FM27 .fmf');
const nativeBinary = join(homedir(), 'Library/Application Support/Steam/steamapps/common/Football Manager 27/fm.app/Contents/PlugIns/game_plugin.bundle/Contents/MacOS/game_plugin');
const sourceBytes = readFileSync(template);
const sourceSha = createHash('sha256').update(sourceBytes).digest('hex');
const request = { action: 'generate', template_path: template, template_sha256: sourceSha,
  name: 'Bounded native role diagnostic only', preview: true,
  native_authoring: { roles: [{ phase: 'in_possession', position_index: 0, role: 'Centre-Back' }] } };
mkdirSync(join(root, 'evidence'), { recursive: true });
let tool;
registerTacticFileTool({ registerTool: value => { tool = value; } });
const argumentsValidator = Compile(tool.parameters);
const diagnosticValidator = Compile({ type: 'object', required: ['operation', 'phase', 'position_index', 'requested',
  'rejection_reason', 'automatic_substitution_applied'], properties: {
    operation: { const: 'roles' }, phase: { type: ['string', 'boolean', 'null', 'integer'] },
    position_index: { type: ['string', 'boolean', 'null', 'integer'] },
    requested: { type: 'object', required: ['role'], additionalProperties: false,
      properties: { role: {} } }, rejection_reason: { type: 'string' },
    automatic_substitution_applied: { const: false }, position_name: { type: 'string' }, position_mask: { type: 'integer' },
    legal_roles: { type: 'array', items: { type: 'string' } },
    roles_refused_for_more_than_one_stored_word: { type: 'array', items: { type: 'string' } },
  } });

function verifyDiagnostic(value) {
  assert.equal(diagnosticValidator.Check(value), true);
  assert.equal(value.phase, 'in_possession');
  assert.equal(value.position_index, 0);
  assert.equal(value.position_name, 'GK');
  assert.deepEqual(value.requested, { role: 'Centre-Back' });
  assert.equal(value.rejection_reason, 'Native position role mask refuses requested role');
  assert.deepEqual(value.legal_roles, ['Goalkeeper', 'Ball-Playing Goalkeeper', 'No-Nonsense Goalkeeper']);
  assert.deepEqual(value.roles_refused_for_more_than_one_stored_word, []);
  assert.doesNotMatch(JSON.stringify(value), /dut(y|ies)/i);
  assert.equal(value.automatic_substitution_applied, false);
  assert.equal(value.diagnostic_queries_mutated_creator, false);
}

test('actual TypeBox and Pi validators admit the structural request but reject malformed slot input', () => {
  assert.equal(argumentsValidator.Check(request), true);
  assert.deepEqual(validateToolArguments(tool, { name: tool.name, arguments: request }), request);
  const malformed = structuredClone(request);
  malformed.native_authoring.roles[0].position_index = 11;
  assert.equal(argumentsValidator.Check(malformed), false);
  assert.throws(() => validateToolArguments(tool, { name: tool.name, arguments: malformed }), /Validation failed/);
});

test('real outer/native CLI rejection retains exact legal choices on Error and tool details without output', async () => {
  const catalog = await runTacticFile({ action: 'authoring_catalog' });
  assert.equal(catalog.positions.length, 26);
  assert.equal(catalog.output_path, undefined);
  await assert.rejects(runTacticFile(request), error => {
    verifyDiagnostic(error.diagnostic);
    assert.match(error.message, /requested Centre-Back\. Native position role mask refuses requested role\./);
    assert.match(error.message, /Legal roles: Goalkeeper, Ball-Playing Goalkeeper, No-Nonsense Goalkeeper\./);
    return true;
  });
  const result = await tool.execute('diagnostic-real-cli', request);
  assert.equal(result.isError, true);
  assert.equal(result.details.error, true);
  verifyDiagnostic(result.details.diagnostic);
  assert.deepEqual(JSON.parse(result.content[0].text).diagnostic, result.details.diagnostic);
  assert.equal(result.details.output_path, undefined);
  assert.equal(readFileSync(template).equals(sourceBytes), true);
});

test('trusted CLI bad-context diagnostics preserve domains when the exported adapter bypasses client schema', async () => {
  const bad = structuredClone(request);
  bad.native_authoring.roles[0].phase = 'unknown_phase';
  assert.equal(argumentsValidator.Check(bad), false);
  await assert.rejects(runTacticFile(bad), error => {
    assert.equal(diagnosticValidator.Check(error.diagnostic), true);
    assert.deepEqual(error.diagnostic.legal_phases, ['in_possession', 'out_of_possession']);
    assert.deepEqual(error.diagnostic.legal_position_indices, Array.from({ length: 11 }, (_, i) => i));
    assert.equal(error.diagnostic.legal_roles, undefined);
    assert.equal(error.diagnostic.automatic_substitution_applied, false);
    return true;
  });
});

test('delivered creation and tactical guides require native checks before exact file-compatible recommendations', async () => {
  let reader;
  registerSkillTool({ registerTool: value => { reader = value; } });
  for (const id of ['fm-create-tactic', 'fm-tactical-analysis']) {
    const loaded = await reader.execute(id, { id });
    assert.equal(loaded.isError, undefined);
    const source = readFileSync(join(root, 'skills', id, 'SKILL.md'), 'utf8');
    assert.equal(loaded.details.content, source);
    assert.match(source, /before finalizing/i);
    assert.match(source, /[Pp]review/);
    assert.match(source, /[Cc]onceptual football advice/);
    assert.match(source, /Source\/native failures|Native\/source failures/);
  }
});

test('ordinary/non-object/oversized/spawn/abort failures remain fatal without a request diagnostic', async () => {
  const scratch = mkdtempSync(join(root, 'evidence', 'diagnostic-errors-'));
  const executable = join(scratch, 'stderr-fixture');
  const previous = process.env.PI_FM_TACTIC_PYTHON;
  const script = body => {
    writeFileSync(executable, '#!/usr/bin/python3\nimport sys\nsys.stdin.read()\n' + body + '\n', { mode: 0o700 });
    process.env.PI_FM_TACTIC_PYTHON = executable;
  };
  try {
    for (const message of ['ordinary native failure — unchanged', '{broken JSON',
      JSON.stringify({ error: 'Source guard failed', type: 'ValueError' }),
      JSON.stringify({ error: 'Bad diagnostic type', diagnostic: [] }),
      JSON.stringify({ error: 'Missing diagnostic', diagnostic: null })]) {
      script(`sys.stderr.write(${JSON.stringify(message)});sys.exit(1)`);
      await assert.rejects(runTacticFile(request), error => {
        assert.equal(error.message, message);
        assert.equal(error.diagnostic, undefined);
        return true;
      });
      const result = await tool.execute('ordinary-error', request);
      assert.equal(result.isError, true);
      assert.equal(result.details.diagnostic, undefined);
      assert.equal(result.content[0].text, `Native tactic file operation failed: ${message}`);
    }
    script('sys.stderr.write("x"*2097152);sys.exit(1)');
    await assert.rejects(runTacticFile(request), error => {
      assert.equal(error.code, 'ERR_CHILD_PROCESS_STDIO_MAXBUFFER');
      assert.equal(error.diagnostic, undefined);
      return true;
    });
    const envelope = JSON.stringify({ error: 'Role refusal', diagnostic: { operation: 'roles', automatic_substitution_applied: false } });
    script(`sys.stderr.write(${JSON.stringify(envelope)});sys.exit(2)`);
    await assert.rejects(runTacticFile(request), error => {
      assert.equal(error.message, envelope);
      assert.equal(error.diagnostic, undefined);
      return true;
    });
    script(`sys.stderr.write(${JSON.stringify(envelope)});sys.stdout.write("x"*2097152)`);
    await assert.rejects(runTacticFile(request), error => {
      assert.equal(error.code, 'ERR_CHILD_PROCESS_STDIO_MAXBUFFER');
      assert.equal(error.diagnostic, undefined);
      return true;
    });
    script(`sys.stderr.write(${JSON.stringify(envelope)});sys.stdout.write('{"status":"fixture-success"}')`);
    assert.deepEqual(await runTacticFile(request), { status: 'fixture-success' });
    process.env.PI_FM_TACTIC_PYTHON = join(scratch, 'missing-executable');
    await assert.rejects(runTacticFile(request), error => error.code === 'ENOENT' && error.diagnostic === undefined);
    process.env.PI_FM_TACTIC_PYTHON = executable;
    const controller = new AbortController();
    controller.abort();
    await assert.rejects(runTacticFile(request, controller.signal), error =>
      error.name === 'AbortError' && error.diagnostic === undefined);
  } finally {
    if (previous === undefined) delete process.env.PI_FM_TACTIC_PYTHON;
    else process.env.PI_FM_TACTIC_PYTHON = previous;
  }
});

for (const route of ['tactic-direct', 'tactic-codemode']) {
  test(`actual isolated Pi preserves a native role refusal through ${route}`, () => {
    const scratch = mkdtempSync(join(root, 'evidence', `diagnostic-${route}-`));
    const home = realpathSync(mkdtempSync(join(tmpdir(), 'pi-fm-diagnostic-home-')));
    mkdirSync(join(home, '.agents'));
    symlinkSync(join(homedir(), '.agents/skills'), join(home, '.agents/skills'));
    const run = spawnSync(join(root, 'bin/pi-fm'), [
      '-e', join(root, 'tests/papercut-provider.pi.ts'), '--no-mcp', '--mode', 'json', '--print', 'Verify exact native tactic role failure',
    ], { encoding: 'utf8', timeout: 30000, maxBuffer: 4 * 1024 * 1024, env: {
      ...process.env, HOME: home, PI_CODING_AGENT_DIR: join(scratch, '.pi/agent'), PI_FM_SESSION_DIR: join(scratch, 'sessions'),
      PI_FM_MODEL: 'papercut-fixture/offline', PI_FM_TEST_ROUTE: route, PI_FM_TEST_TACTIC_PARAMS: JSON.stringify(request),
      PI_OFFLINE: '1', PI_FM_MCP_LAUNCHER: join(root, 'tests/startup-reader-fixture.sh'), PI_FM_TEST_READER_DIR: scratch,
      PI_FM_TEST_FAILED_STARTS: '0', PI_FM_TEST_FIRST_DELAY: '0', PI_FM_NATIVE_BINARY: nativeBinary,
      FM27_TACTICS_DIR: join(homedir(), 'Library/Application Support/Sports Interactive/Football Manager 27/Tactics'),
    } });
    writeFileSync(join(scratch, 'runtime.jsonl'), run.stdout);
    writeFileSync(join(scratch, 'stderr.txt'), run.stderr);
    assert.equal(run.status, 0, run.stderr || String(run.error));
    const events = run.stdout.trim().split('\n').map(line => JSON.parse(line));
    const nativeCalls = events.filter(e => e.type === 'tool_execution_end' && e.toolName === 'fm_tactic_file');
    assert.equal(nativeCalls.length, 1);
    assert.equal(nativeCalls[0].isError, true);
    verifyDiagnostic(nativeCalls[0].result.details.diagnostic);
    const packet = JSON.parse(nativeCalls[0].result.content[0].text);
    assert.deepEqual(packet.diagnostic, nativeCalls[0].result.details.diagnostic);
    if (route === 'tactic-codemode') {
      const outer = events.find(e => e.type === 'tool_execution_end' && e.toolName === 'codemode');
      assert.ok(outer);
      assert.equal(outer.isError, true);
      const errorLine = outer.result.content.flatMap(block => (block.text || '').split('\n'))
        .find(line => line.startsWith('Error: {'));
      assert.ok(errorLine, 'Complete JSON diagnostic must survive in Code Mode error content');
      assert.deepEqual(JSON.parse(errorLine.slice('Error: '.length)), packet);
    }
    assert.ok(!events.some(e => e.type === 'tool_execution_start' && e.toolName.startsWith('mcp__fm_live__')));
    assert.equal(existsSync(join(home, 'Agent Outputs')), false);
    assert.equal(readFileSync(template).equals(sourceBytes), true);
  });
}
