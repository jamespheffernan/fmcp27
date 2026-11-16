import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import test from 'node:test';
import { registerTacticFileTool } from '../pi/fm-tactic-files.mjs';

test('base-role schema declares the two bounded OOP tracking-midfielder cases', () => {
  let tool;
  registerTacticFileTool({ registerTool(value) { tool = value; } });
  const role = tool.parameters.properties.base_role;
  assert.deepEqual(role.properties.position_index.enum, [1, 4, 5, 7, 8, 9]);
  assert.deepEqual(role.properties.donor_position_index.enum, [1, 4, 5, 7, 8, 9]);
  assert.match(role.description, /OOP slot8 AM\(CR\) and slot9 AM\(CL\)/);
  assert.match(role.description, /Attacking Midfielder to Tracking Attacking Midfielder/);
  assert.match(role.description, /zero-PI target/);
  assert.match(role.description, /Stored-record reproduction only/);
});

for (const [slot, position] of [[8, 'AM(CR)'], [9, 'AM(CL)']]) {
  test(`actual OOP ${position} tracking-midfielder edit preserves every unrequested byte`, () => {
    const result = spawnSync('/Users/jamesheffernan/GitHub/FM26 Deepener/.venv/bin/python', [
      fileURLToPath(new URL('./oop-tracking-midfielder-files.py', import.meta.url)),
      fileURLToPath(new URL('../pi/fm-tactic-files.py', import.meta.url)), String(slot),
    ], { encoding: 'utf8', timeout: 120000 });
    assert.equal(result.status, 0, result.stderr || String(result.error));
    const receipt = JSON.parse(result.stdout);
    assert.equal(receipt.stored_before, 'Attacking Midfielder');
    assert.equal(receipt.stored_after, 'Tracking Attacking Midfielder');
    assert.equal(receipt.source_format_major, 27);
    assert.equal(receipt.position_index, slot);
    assert.equal(receipt.position, position);
    assert.equal(receipt.other_records_preserved, 21);
    assert.equal(receipt.positive_artifacts.length, 4);
    assert.ok(receipt.refusals >= 40);
    assert.equal(receipt.game_import_verified, false);
  });

  test(`original native OOP ${position} setter takes the proved zero-PI reconciliation path`, () => {
    const result = spawnSync('/Volumes/4TB Private/Offloaded/FMCP 27/.venv/bin/python', [
      fileURLToPath(new URL('./oop-tracking-midfielder-native.py', import.meta.url)), '', String(slot),
    ], { encoding: 'utf8', timeout: 120000 });
    assert.equal(result.status, 0, result.stderr || String(result.error));
    const receipt = JSON.parse(result.stdout);
    assert.equal(receipt.slot, slot);
    assert.equal(receipt.position, position);
    assert.equal(receipt.original_native_instructions, 113);
    assert.equal(receipt.validator_calls, 0);
    assert.equal(receipt.record_reconciliation_calls, 1);
    assert.equal(receipt.PI_entries_unchanged, true);
    assert.equal(receipt.outer_owner_callback_executed, false);
    assert.equal(receipt.native_live_calls, false);
    assert.equal(receipt.game_reads, false);
    assert.equal(receipt.game_import_verified, false);
  });
}
