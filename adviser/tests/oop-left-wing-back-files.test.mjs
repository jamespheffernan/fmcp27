import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import test from 'node:test';
import { registerTacticFileTool } from '../pi/fm-tactic-files.mjs';

test('base-role schema describes the separately proved source-format27 OOP left-wing-back case', () => {
  let tool;
  registerTacticFileTool({ registerTool(value) { tool = value; } });
  const role = tool.parameters.properties.base_role;
  assert.match(role.description, /OOP slot7 WB\(L\)/);
  assert.match(role.description, /Pressing Wing-Back to Wing-Back/);
  assert.match(role.description, /Source-format27/);
  assert.deepEqual(role.properties.position_index.enum, [1, 4, 5, 7, 8, 9]);
});

test('actual native-format27 OOP left-wing-back edit preserves unrequested records and rejects semantic drift', () => {
  const result = spawnSync('/Users/jamesheffernan/GitHub/FM26 Deepener/.venv/bin/python', [
    fileURLToPath(new URL('./oop-left-wing-back-files.py', import.meta.url)),
    fileURLToPath(new URL('../pi/fm-tactic-files.py', import.meta.url)),
  ], { encoding: 'utf8', timeout: 120000 });
  assert.equal(result.status, 0, result.stderr || String(result.error));
  const receipt = JSON.parse(result.stdout);
  assert.equal(receipt.other_records_preserved, 21);
  assert.equal(receipt.artifacts.length, 3);
  assert.ok(receipt.public_refusals >= 40);
  assert.equal(receipt.game_import_verified, false);
});

test('original native OOP left-wing-back setter retains PI31 through its complete validator', () => {
  const result = spawnSync('/Volumes/4TB Private/Offloaded/FMCP 27/.venv/bin/python', [
    fileURLToPath(new URL('./oop-left-wing-back-native.py', import.meta.url)),
  ], { encoding: 'utf8', timeout: 120000 });
  assert.equal(result.status, 0, result.stderr || String(result.error));
  const receipt = JSON.parse(result.stdout);
  assert.equal(receipt.slot, 7);
  assert.equal(receipt.position, 'WB(L)');
  assert.equal(receipt.original_native_instructions, 438);
  assert.equal(receipt.validator_calls, 1);
  assert.equal(receipt.record_reconciliation_calls, 1);
  assert.equal(receipt.PI_entries_unchanged, true);
  assert.equal(receipt.outer_owner_callback_executed, false);
  assert.equal(receipt.native_live_calls, false);
  assert.equal(receipt.game_reads, false);
  assert.equal(receipt.game_import_verified, false);
});
