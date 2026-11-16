import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { spawnSync } from 'node:child_process';
import { existsSync, mkdirSync, mkdtempSync, readFileSync, writeFileSync, symlinkSync } from 'node:fs';
import { homedir } from 'node:os';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';
import test from 'node:test';

const root = fileURLToPath(new URL('../', import.meta.url));
const hash = path => createHash('sha256').update(readFileSync(path)).digest('hex');

test('actual fresh Pi CodeMode matches registration schema and original typed PI35 preview', () => {
  const evidenceRoot = join(root, 'evidence/tactic-runtime-20261109');
  mkdirSync(evidenceRoot, { recursive: true });
  const evidence = mkdtempSync(join(evidenceRoot, 'run-'));
  mkdirSync(join(evidence, '.agents'));
  symlinkSync(join(homedir(), '.agents/skills'), join(evidence, '.agents/skills'));
  const template = '/Users/jamesheffernan/Agent Outputs/2026-11-09 — Pi FM tactic files/Newcastle v Liverpool Complete Plan — e380fd3f.fmf';
  const pin = hash(template);
  const nativeBinary = join(homedir(), 'Library/Application Support/Steam/steamapps/common/Football Manager 27/fm.app/Contents/PlugIns/game_plugin.bundle/Contents/MacOS/game_plugin');
  const nativeBinaryHash = hash(nativeBinary);
  // The existing outer writer also resolves receipt resources relative to HOME.
  // Expose the original app read-only by convention in this isolated HOME;
  // source hashes before/after prove this test did not change those inputs.
  const appParent = 'Library/Application Support/Steam/steamapps/common/Football Manager 27';
  mkdirSync(join(evidence, appParent), { recursive: true });
  symlinkSync(join(homedir(), appParent, 'fm.app'), join(evidence, appParent, 'fm.app'));
  assert.equal(pin, 'a1015820079f3ad2cb22fafd06c60073291d1d84144164ffefce59f6a95864e2');
  const seed = { template_path: template, template_sha256: pin };
  const sourceFiles = ['pi/fm-tactic-files.mjs', 'pi/fm-tactic-runtime.mjs', 'pi/fm-tactic-files.py',
    'pi/fm_tactic_native_authoring.py', 'pi/fm_tactic_native_core.py',
    'skills/fm-create-tactic/SKILL.md', 'skills/fm-tactical-analysis/SKILL.md'];
  const pins = Object.fromEntries(sourceFiles.map(path => [path, hash(join(root, path))]));
  const code = `
for (const id of ['fm-create-tactic','fm-tactical-analysis']) text({guide:id,content:await tools.fm_read_skill({id})});
const s = JSON.parse(await tools.fm_tactic_file(${JSON.stringify({ action: 'inspect', ...seed })}));
const c = JSON.parse(await tools.fm_tactic_file(${JSON.stringify({ action: 'authoring_catalog', ...seed })}));
if (!s.authoring_runtime || !c.authoring_runtime) throw new Error('Missing registration evidence');
if (s.authoring_runtime.registered.schema_sha256 !== c.authoring_runtime.registered.schema_sha256) throw new Error('Registration hash changed');
const runtime = c.authoring_runtime;
if (!runtime.registered.capabilities.mark_specific_position || runtime.registration_adapter_files_match_current_disk !== true || runtime.ui_controls_verified !== false) throw new Error('Wrong capability or scope');
const p = c.template_instruction_inspection.current_role_profiles.find(p => p.phase==='out_of_possession' && p.native_editor_availability.some(a => a.native_option===35 && a.native_available===true));
if (!p) throw new Error('No native-available OOP actor for typed marking control');
const request = ${JSON.stringify({ action: 'generate', ...seed, name: 'Registration metadata typed marking preview', preview: true })};
request.native_authoring={player_instructions:[{phase:p.phase,position_index:p.position_index,instructions:[],mark_specific_position:'AM(C)'}]};
const preview = JSON.parse(await tools.fm_tactic_file(request));
store('runtimeEvidence',{schema_sha256:runtime.registered.schema_sha256,capabilities:runtime.registered.capabilities,match:runtime.registration_adapter_files_match_current_disk});
text({control:'runtime_verified',runtime,phase:p.phase,position_index:p.position_index,preview});
`;
  writeFileSync(join(evidence, 'code.js'), code);
  const run = spawnSync(join(root, 'bin/pi-fm'), ['--no-session', '--mode', 'json', '--print',
    // fm_tactic_file is declared only on a turn whose prompt asks for a tactic (wantsTactic in
    // pi/fm-exposure.mjs), so the prompt has to name one for the script to reach the tool.
    '-e', join(root, 'tests/tactic-runtime.pi.ts'), 'Verify native tactic tool registration without game access'], {
    encoding: 'utf8', timeout: 90000, maxBuffer: 8 * 1024 * 1024,
    env: { ...process.env, HOME: evidence, PI_CODING_AGENT_DIR: join(evidence, '.pi/agent'),
      PI_FM_MODEL: 'tactic-runtime-fixture/offline', PI_OFFLINE: '1', PI_FM_RUNTIME_CODE: code,
      PI_FM_NATIVE_BINARY: nativeBinary,
      PI_FM_MCP_LAUNCHER: join(root, 'tests/startup-reader-fixture.sh'),
      PI_FM_TEST_READER_DIR: evidence, PI_FM_TEST_FAILED_STARTS: '0', PI_FM_TEST_FIRST_DELAY: '0' },
  });
  writeFileSync(join(evidence, 'runtime.jsonl'), run.stdout || '');
  writeFileSync(join(evidence, 'stderr.txt'), run.stderr || '');
  assert.equal(run.status, 0, run.stderr || String(run.error));
  const events = run.stdout.trim().split('\n').map(JSON.parse);
  const starts = events.filter(event => event.type === 'tool_execution_start');
  assert.ok(starts.every(event => ['codemode', 'fm_read_skill', 'fm_tactic_file'].includes(event.toolName)));
  const ends = events.filter(event => event.type === 'tool_execution_end');
  assert.ok(ends.every(event => !event.isError), JSON.stringify(ends.filter(event => event.isError)
    .map(event => ({ tool: event.toolName, error: JSON.stringify(event.result).slice(0, 1200) }))));
  const tactics = ends.filter(event => event.toolName === 'fm_tactic_file');
  assert.equal(tactics.length, 3);
  const inspected = tactics[0].result.details, catalog = tactics[1].result.details, preview = tactics[2].result.details;
  assert.equal(inspected.template_sha256, pin);
  assert.equal(catalog.template_sha256, pin);
  assert.equal(preview.status, 'preview');
  assert.equal(preview.files_created, false);
  assert.equal(existsSync(preview.output_path), false);
  assert.equal(existsSync(preview.receipt_path), false);
  assert.deepEqual(preview.stored_football.phase_positions_and_roles, inspected.stored_football.phase_positions_and_roles);
  assert.equal(preview.verification.native_decode_roundtrip, true);
  assert.equal(preview.verification.all_unrequested_tactic_bytes_preserved, true);
  const [mark] = preview.native_authoring.player_instructions;
  assert.equal(mark.phase, 'out_of_possession');
  assert.deepEqual(mark.instructions, []);
  assert.deepEqual(mark.after.selected_native_option_ids, [35]);
  assert.equal(mark.mark_specific_position.name, 'AM(C)');
  assert.equal(mark.mark_specific_position.native_mask, 8192);
  assert.equal(mark.mark_specific_position.native_target_setter_accessor_and_reload_verified, true);
  assert.equal(mark.mark_specific_position.rendered_target_picker_observed, false);
  for (const id of ['fm-create-tactic', 'fm-tactical-analysis']) {
    const delivered = ends.find(event => event.toolName === 'fm_read_skill' && event.result.details?.id === id);
    assert.equal(delivered.result.details.content, readFileSync(join(root, 'skills', id, 'SKILL.md'), 'utf8'));
    assert.match(delivered.result.details.content, /A role in Football Manager 27 has no duty\. Each player has one role in possession and one role out of possession/);
    assert.match(delivered.result.details.content, /UI/);
  }
  const final = events.findLast(event => event.type === 'message_end' && event.message.role === 'assistant');
  const declared = JSON.parse(final.message.content.find(item => item.type === 'text').text);
  assert.equal(declared.actual_provider_schema_sha256, inspected.authoring_runtime.registered.schema_sha256);
  assert.deepEqual(declared.actual_provider_marking_field.enum,
    inspected.authoring_runtime.registered.capabilities.mark_specific_position_targets);
  assert.equal(hash(template), pin);
  assert.equal(hash(nativeBinary), nativeBinaryHash);
  for (const path of sourceFiles) assert.equal(hash(join(root, path)), pins[path]);
  const requests = readFileSync(join(evidence, 'requests.jsonl'), 'utf8').trim().split('\n').map(JSON.parse);
  // The harness's own fm_attach before the first model call (pi/fm-reader-session.mjs) is the one
  // reader call; the tactic tool and its preview make none.
  assert.deepEqual(requests.filter(row => row.method === 'tools/call').map(row => row.name), ['fm_attach']);
  const receipt = { state: 'actual_isolated_Pi_CodeMode_schema_and_native_preview_checked',
    evidence, pins, template_sha256: pin, native_binary_sha256: nativeBinaryHash,
    schema_sha256: declared.actual_provider_schema_sha256,
    native_preview: preview, game_calls: 0, source_files_unchanged: true,
    legacy_user_session_touched: false, scope: 'Candidate only; original native authoring in isolation, no game/UI/import verification.' };
  writeFileSync(join(evidence, 'verified.json'), JSON.stringify(receipt, null, 2) + '\n');
});
