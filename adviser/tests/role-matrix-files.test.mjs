import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { readFileSync, mkdtempSync, mkdirSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { join } from 'node:path';
import test from 'node:test';
import { registerTacticFileTool } from '../pi/fm-tactic-files.mjs';

test('role schema bounds26 directed changes to nine complete native prefixes', () => {
  let tool;
  registerTacticFileTool({ registerTool(value) { tool = value; } });
  const role = tool.parameters.properties.base_role;
  assert.deepEqual(role.properties.position_index.enum, [1, 4, 5, 7, 8, 9]);
  assert.deepEqual(role.properties.donor_position_index.enum, [1, 4, 5, 7, 8, 9]);
  assert.equal(role.additionalProperties, false);
  assert.match(role.description, /26 proved directed changes across nine complete companion prefixes/);
  assert.match(role.description, /Full-Back and Holding Full-Back/);
  assert.match(role.description, /No-op or unproved word\/format\/position\/companion combinations refuse/);
  assert.match(role.description, /Stored-record reproduction only/);
});

test('all26 actual archive role edits preserve their other records and refuse unproved cases', () => {
  const result = spawnSync('/Users/jamesheffernan/GitHub/FM26 Deepener/.venv/bin/python', [
    fileURLToPath(new URL('./role-matrix-files.py', import.meta.url)),
    fileURLToPath(new URL('../pi/fm-tactic-files.py', import.meta.url)),
  ], { encoding: 'utf8', timeout: 300000 });
  assert.equal(result.status, 0, result.stderr || String(result.error));
  const receipt = JSON.parse(result.stdout);
  assert.equal(receipt.artifacts.length, 26);
  assert.equal(receipt.variant_artifacts.length, 9);
  assert.ok(receipt.public_refusals >= 180);
  assert.equal(receipt.exact_prefixes, 9);
  assert.equal(receipt.directed_changes, 26);
  assert.equal(receipt.game_import_verified, false);
});

test('all26 actual source/donor pairs match original native setter execution offline', () => {
  const scratch = fileURLToPath(new URL('../tmp/', import.meta.url));
  mkdirSync(scratch, { recursive: true });
  const receiptPath = join(mkdtempSync(join(scratch, 'native-role-matrix-')), 'receipt.json');
  const result = spawnSync('/Volumes/4TB Private/Offloaded/FMCP 27/.venv/bin/python', [
    fileURLToPath(new URL('./role-matrix-native.py', import.meta.url)), receiptPath,
  ], { encoding: 'utf8', timeout: 120000 });
  assert.equal(result.status, 0, result.stderr || result.stdout || String(result.error));
  const rows = JSON.parse(readFileSync(receiptPath, 'utf8'));
  assert.equal(rows.length, 26);
  for (const row of rows) {
    assert.equal(row.matches_donor, true);
    assert.equal(row.PI_preserved, true);
    assert.equal(row.native_live_calls, false);
    assert.equal(row.game_import_verified, false);
    assert.equal(row.error, null);
  }
});

test('parent phase-order native drift refuses matrix preview before and after packing', () => {
  const result = spawnSync('/Users/jamesheffernan/GitHub/FM26 Deepener/.venv/bin/python', [
    fileURLToPath(new URL('./role-matrix-guard.py', import.meta.url)),
    fileURLToPath(new URL('../pi/fm-tactic-files.py', import.meta.url)),
  ], { encoding: 'utf8', timeout: 60000 });
  assert.equal(result.status, 0, result.stderr || String(result.error));
  const receipt = JSON.parse(result.stdout);
  assert.equal(receipt.parent_pin_refused, true);
  assert.equal(receipt.postpack_refused, true);
  assert.equal(receipt.preview_no_files, true);
  assert.equal(receipt.game_import_verified, false);
});
