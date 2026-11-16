import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import test from 'node:test';
import { registerTacticFileTool } from '../pi/fm-tactic-files.mjs';

test('base-role schema exposes all finite format-qualified donor slots', () => {
  let tool;
  registerTacticFileTool({ registerTool(value) { tool = value; } });
  const role = tool.parameters.properties.base_role;
  assert.equal(role.type, 'object');
  assert.equal(role.additionalProperties, false);
  assert.deepEqual(role.properties.phase.enum, ['in_possession', 'out_of_possession']);
  assert.deepEqual(role.properties.position_index.enum, [1, 4, 5, 7, 8, 9]);
  assert.deepEqual(role.properties.donor_position_index.enum, [1, 4, 5, 7, 8, 9]);
  assert.deepEqual(role.required, ['phase', 'position_index', 'donor_template_path', 'donor_template_sha256', 'donor_position_index']);
  assert.ok(!tool.parameters.required.includes('base_role'));
  assert.match(role.description, /Omit to inherit/);
  assert.match(role.description, /Stored-record reproduction only/);
});

test('native base-role change reproduces donor record and preserves all other native bytes', () => {
  const result = spawnSync('/Users/jamesheffernan/GitHub/FM26 Deepener/.venv/bin/python', [
    fileURLToPath(new URL('./base-role-files.py', import.meta.url)),
    fileURLToPath(new URL('../pi/fm-tactic-files.py', import.meta.url)),
  ], { encoding: 'utf8', timeout: 60000 });
  assert.equal(result.status, 0, result.stderr || String(result.error));
  const receipt = JSON.parse(result.stdout);
  assert.equal(receipt.stored_before, 'Box-To-Box Midfielder');
  assert.equal(receipt.stored_after, 'Defensive Midfielder');
  assert.equal(receipt.other_records_preserved, 21);
  assert.equal(receipt.game_import_verified, false);
});
