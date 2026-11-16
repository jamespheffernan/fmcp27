import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { spawnSync } from 'node:child_process';
import { mkdirSync, mkdtempSync, readFileSync, writeFileSync, symlinkSync } from 'node:fs';
import { homedir } from 'node:os';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';
import test from 'node:test';
import { registerTacticFileTool } from '../pi/fm-tactic-files.mjs';
import { schemaSha256 } from '../pi/fm-tactic-runtime.mjs';

const root = fileURLToPath(new URL('../', import.meta.url));
const baseline = '/Volumes/4TB Private/Offloaded/Agent Work/fm27-continuous-20261109/adviser96-release';
const hash = path => createHash('sha256').update(readFileSync(path)).digest('hex');

function isolatedRun(source, label, code, harnessCalls = []) {
  const parent = join(root, 'evidence/tactic-schema97-20261109');
  mkdirSync(parent, { recursive: true });
  const evidence = mkdtempSync(join(parent, label+'-'));
  mkdirSync(join(evidence, '.agents'));
  symlinkSync(join(homedir(), '.agents/skills'), join(evidence, '.agents/skills'));
  const sourcePaths = ['package.json', 'pi/fm-tactic-files.mjs', 'pi/fm-tactic-runtime.mjs',
    'skills/fm-tools/SKILL.md', 'skills/fm-create-tactic/SKILL.md'];
  const pins = Object.fromEntries(sourcePaths.map(path => [path, hash(join(source, path))]));
  writeFileSync(join(evidence, 'code.js'), code);
  const run = spawnSync(join(source, 'bin/pi-fm'), ['--no-session', '--mode', 'json', '--print',
    '-e', join(source, 'tests/tactic-runtime.pi.ts'), 'Check exact registered tactic JSON contract'], {
    encoding: 'utf8', timeout: 60000, maxBuffer: 8 * 1024 * 1024,
    env: { ...process.env, HOME: evidence, PI_CODING_AGENT_DIR: join(evidence, '.pi/agent'),
      PI_FM_MODEL: 'tactic-runtime-fixture/offline', PI_OFFLINE: '1', PI_FM_RUNTIME_CODE: code,
      PI_FM_TACTIC_PYTHON: '/nonexistent/schema-introspection-must-not-call-native-backend',
      PI_FM_MCP_LAUNCHER: join(source, 'tests/startup-reader-fixture.sh'),
      PI_FM_TEST_READER_DIR: evidence, PI_FM_TEST_FAILED_STARTS: '0', PI_FM_TEST_FIRST_DELAY: '0' },
  });
  writeFileSync(join(evidence, 'runtime.jsonl'), run.stdout || '');
  writeFileSync(join(evidence, 'stderr.txt'), run.stderr || '');
  assert.equal(run.status, 0, run.stderr || String(run.error));
  const events = run.stdout.trim().split('\n').map(JSON.parse);
  const starts = events.filter(event => event.type === 'tool_execution_start');
  assert.ok(starts.every(event => ['codemode', 'fm_read_skill', 'fm_tactic_file'].includes(event.toolName)));
  const ends = events.filter(event => event.type === 'tool_execution_end');
  const codeMode = ends.find(event => event.toolName === 'codemode');
  assert.ok(codeMode && !codeMode.isError, JSON.stringify(codeMode?.result).slice(0, 1200));
  const final = events.findLast(event => event.type === 'message_end' && event.message.role === 'assistant');
  const offered = JSON.parse(final.message.content.find(item => item.type === 'text').text);
  for (const path of sourcePaths) assert.equal(hash(join(source, path)), pins[path]);
  const requests = readFileSync(join(evidence, 'requests.jsonl'), 'utf8').trim().split('\n').map(JSON.parse);
  // Schema introspection makes no reader call. The only calls allowed are the harness's own
  // (`harnessCalls`): none in the adviser96 baseline, fm_attach before the first model call now.
  assert.deepEqual(requests.filter(row => row.method === 'tools/call').map(row => row.name), harnessCalls);
  return { evidence, pins, ends, offered, codeMode };
}

test('actual adviser96 CodeMode reproduces opaque declaration and missing JSON-schema action', () => {
  const code = `
const declaration = await describeTool('fm_tactic_file');
if (!declaration.includes('args: unknown')) throw new Error('Original opaque condition changed');
let refusal;
try { await tools.fm_tactic_file({action:'schema'}); } catch(error) { refusal=String(error); }
if (!refusal) throw new Error('Baseline unexpectedly has a registered schema action');
text({control:'baseline_contract_missing',declaration,refusal});
`;
  const result = isolatedRun(baseline, 'baseline96', code);
  assert.match(JSON.stringify(result.codeMode.result), /baseline_contract_missing/);
  const receipt = { state: 'actual_Pi_CodeMode_baseline96_opaque_and_schema_missing_reproduced',
    source: baseline, papercut_id: 'pc-33ade4a4', pins: result.pins,
    provider_schema_sha256: result.offered.actual_provider_schema_sha256,
    backend_unavailable_by_construction: true, game_calls: 0, user_session_touched: false };
  writeFileSync(join(result.evidence, 'verified.json'), JSON.stringify(receipt, null, 2)+'\n');
});

test('actual adviser97 CodeMode discovers the full immutable registration contract without backend or template', () => {
  const code = `
const declaration = await describeTool('fm_tactic_file');
if (!declaration.includes('action:"schema"')) throw new Error('Opaque declaration has no discovery route');
for (const id of ['fm-tools','fm-create-tactic']) text({guide:id,content:await tools.fm_read_skill({id})});
const first = JSON.parse(await tools.fm_tactic_file({action:'schema'}));
if (first.tool_name!=='fm_tactic_file' || !first.registered_parameters || first.schema_sha256!==first.authoring_runtime.registered.schema_sha256) throw new Error('Incomplete registered contract');
store('registeredTacticContract',first);
const row=first.registered_parameters.properties.native_authoring.properties.player_instructions.items;
if (row.additionalProperties!==false || !row.properties.mark_specific_position.enum.includes('AM(C)')) throw new Error('Missing strict typed marking contract');
first.registered_parameters.additionalProperties=true;
row.properties.mark_specific_position.enum.length=0;
const again=JSON.parse(await tools.fm_tactic_file({action:'schema'}));
if (again.registered_parameters.additionalProperties!==false || again.registered_parameters.properties.native_authoring.properties.player_instructions.items.properties.mark_specific_position.enum.length!==25) throw new Error('Caller mutation changed registered schema');
text({control:'full_registered_contract_discovered',opaque:declaration.includes('args: unknown'),schema_sha256:again.schema_sha256,ui_controls_verified:again.authoring_runtime.ui_controls_verified});
`;
  const result = isolatedRun(root, 'candidate97', code, ['fm_attach']);
  assert.ok(result.ends.every(event => !event.isError));
  const schemas = result.ends.filter(event => event.toolName === 'fm_tactic_file');
  assert.equal(schemas.length, 2);
  let actual;
  registerTacticFileTool({ registerTool: value => { actual = value; } });
  for (const event of schemas) {
    const details = event.result.details;
    assert.deepEqual(details.registered_parameters, actual.parameters);
    assert.equal(details.schema_sha256, schemaSha256(details.registered_parameters));
    assert.equal(details.schema_sha256, result.offered.actual_provider_schema_sha256);
    const p = details.registered_parameters;
    assert.equal(p.additionalProperties, false);
    assert.deepEqual(p.required, ['action']);
    assert.equal(p.allOf.length, 5);
    const roles = p.properties.native_authoring.properties.roles.items;
    assert.deepEqual(roles.required, ['phase', 'position_index', 'role']);
    assert.deepEqual(Object.keys(roles.properties), ['phase', 'position_index', 'role']);
    const row = p.properties.native_authoring.properties.player_instructions.items;
    assert.equal(row.additionalProperties, false);
    assert.equal(row.properties.mark_specific_position.enum.length, 25);
    assert.ok(row.properties.mark_specific_position.enum.includes('AM(C)'));
    assert.equal(row.allOf[0].anyOf[1].properties.phase.const, 'out_of_possession');
    assert.equal(details.authoring_runtime.ui_controls_verified, false);
    assert.match(details.scope, /do not attest executed JS or loaded Python/);
  }
  for (const id of ['fm-tools', 'fm-create-tactic']) {
    const guide = result.ends.find(event => event.toolName === 'fm_read_skill' && event.result.details.id === id);
    assert.equal(guide.result.details.content, readFileSync(join(root, 'skills', id, 'SKILL.md'), 'utf8'));
    assert.ok(guide.result.details.content.includes('action:"schema"') || guide.result.details.content.includes('"action":"schema"'));
  }
  const receipt = { state: 'actual_Pi_CodeMode_full_registered_JSON_schema_discovery_passed',
    source: root, version: '1.0.97', papercut_id: 'pc-33ade4a4', pins: result.pins,
    schema_sha256: schemas[0].result.details.schema_sha256, full_schema_chars: JSON.stringify(actual.parameters).length,
    actual_provider_schema_equal: true, client_mutation_did_not_change_registration: true,
    role_entries_are_phase_index_and_role_only: true, typed_AM_C_OOP_and_strict_constraints_preserved: true,
    backend_unavailable_by_construction: true, game_calls: 0, user_session_touched: false,
    scope: 'Private candidate discovery, no model-understanding/UI/native-execution or installed-acceptance claim.' };
  writeFileSync(join(result.evidence, 'verified.json'), JSON.stringify(receipt, null, 2)+'\n');
});
