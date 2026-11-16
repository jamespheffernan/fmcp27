import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import test from 'node:test';
import { registerTacticFileTool } from '../pi/fm-tactic-files.mjs';

const writer = fileURLToPath(new URL('../pi/fm-tactic-files.py', import.meta.url));
const codecPython = '/Users/jamesheffernan/GitHub/FM26 Deepener/.venv/bin/python';
const nativePython = '/Volumes/4TB Private/Offloaded/FMCP 27/.venv/bin/python';

test('stored-role instruction schema exposes only the observed pinned IP9 profiles', () => {
  let tool;
  registerTacticFileTool({ registerTool(value) { tool = value; } });
  const field = tool.parameters.properties.stored_role_instructions;
  assert.equal(field.additionalProperties, false);
  assert.deepEqual(field.properties.phase.enum, ['in_possession']);
  assert.deepEqual(field.properties.position_index.enum, [9]);
  assert.deepEqual(field.properties.donor_position_index.enum, [9]);
  assert.deepEqual(field.required, ['phase', 'position_index', 'donor_template_path', 'donor_template_sha256', 'donor_position_index']);
  assert.match(field.description, /native-format27/);
  assert.match(field.description, /PI_ROAM_FROM_POSITION and PI_MOVE_INTO_CHANNELS/);
  assert.match(field.description, /effective instructions.*unverified/);
});

test('actual PI payload variants and memory-only controls refuse unproved records and native definitions', () => {
  const result = spawnSync(codecPython, [fileURLToPath(new URL('./stored-role-instructions-memory.py', import.meta.url)), writer], { encoding: 'utf8', timeout: 60000 });
  assert.equal(result.status, 0, result.stderr || String(result.error));
  const receipt = JSON.parse(result.stdout);
  assert.equal(receipt.actual_payload_positives, 7);
  assert.ok(receipt.refusals >= 100);
  assert.equal(receipt.archive_fixtures_created, 0);
  assert.equal(receipt.native_fixture_files_created, 0);
  assert.equal(receipt.game_import_verified, false);

});

test('original native clear and available option setters exactly reproduce both real donor profiles', () => {
  const result = spawnSync(nativePython, [fileURLToPath(new URL('./stored-role-instructions-native.py', import.meta.url))], { encoding: 'utf8', timeout: 60000 });
  assert.equal(result.status, 0, result.stderr || String(result.error));
  const rows = JSON.parse(result.stdout);
  assert.equal(rows.length, 2);
  assert.equal(rows[0].original_native_instructions, 73);
  assert.equal(rows[0].native_clear_calls, 1);
  assert.deepEqual(rows[0].selected_after, []);
  assert.equal(rows[1].original_native_instructions, 842);
  assert.equal(rows[1].native_PI_setter_calls, 2);
  assert.equal(rows[1].native_conflict_setter_calls, 2);
  assert.equal(rows[1].validator_calls, 2);
  assert.deepEqual(rows[1].availability_checks, [{ option: 24, allowed: true, state: 0 }, { option: 27, allowed: true, state: 0 }]);
  assert.deepEqual(rows[1].selected_after, [24, 27]);
  for (const row of rows) {
    assert.equal(row.non_target_PI_entries_unchanged, true);
    assert.equal(row.native_live_calls, false);
    assert.equal(row.game_reads, false);
    assert.equal(row.full_UI_setter_parity, false);
    assert.equal(row.game_import_verified, false);
  }
});

test('public PI archives compose with role/team edits and refuse post-pack or delivery drift', () => {
  const result = spawnSync(codecPython, [fileURLToPath(new URL('./stored-role-instructions-files.py', import.meta.url)), writer], { encoding: 'utf8', timeout: 120000 });
  assert.equal(result.status, 0, result.stderr || String(result.error));
  const receipt = JSON.parse(result.stdout);
  assert.equal(receipt.artifacts.length, 3);
  assert.ok(receipt.public_refusals >= 10);
  assert.equal(receipt.native_fixture_files_created, 0);
  assert.equal(receipt.game_import_verified, false);
  const native = spawnSync(nativePython, [fileURLToPath(new URL('./stored-role-instructions-loader.py', import.meta.url))], { input: JSON.stringify(receipt.artifacts), encoding: 'utf8', timeout: 120000 });
  assert.equal(native.status, 0, native.stderr || String(native.error));
  const loaded = JSON.parse(native.stdout);
  assert.equal(loaded.length, 3);
  for (const row of loaded) {
    assert.equal(row.native_body_accepted, true);
    assert.equal(row.records_compared, 22);
    assert.equal(row.all_primary_PI_vectors_match, true);
    assert.equal(row.game_import_verified, false);
  }
});
