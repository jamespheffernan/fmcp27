import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import test from 'node:test';
import { registerTacticFileTool } from '../pi/fm-tactic-files.mjs';

test('base-role variants retain the original cases within the finite catalogue and require an inspected matching donor', () => {
  let tool;
  registerTacticFileTool({ registerTool(value) { tool = value; } });
  const field = tool.parameters.properties.base_role;
  assert.deepEqual(field.properties.phase.enum, ['in_possession', 'out_of_possession']);
  assert.deepEqual(field.properties.position_index.enum, [1, 4, 5, 7, 8, 9]);
  assert.deepEqual(field.properties.donor_position_index.enum, [1, 4, 5, 7, 8, 9]);
  assert.match(field.description, /matching inspected donor/);
  assert.match(field.description, /complete proved companion prefix/);
  assert.match(field.description, /Stored-record reproduction only/);
});

test('different native archives reproduce the same role record and reject public semantic mutations', () => {
  const result = spawnSync('/Users/jamesheffernan/GitHub/FM26 Deepener/.venv/bin/python', [
    fileURLToPath(new URL('./base-role-variants.py', import.meta.url)),
    fileURLToPath(new URL('../pi/fm-tactic-files.py', import.meta.url)),
  ], { encoding: 'utf8', timeout: 60000 });
  assert.equal(result.status, 0, result.stderr || String(result.error));
  const receipt = JSON.parse(result.stdout);
  assert.equal(receipt.positive_variants.length, 4);
  for (const variant of receipt.positive_variants) {
    assert.notEqual(variant.source_sha256, '52b19d08c643f9145a59c0e17b36bb1961693ea007231dfc182a4d1232979e40');
    assert.notEqual(variant.donor_sha256, '0f9859c551cd94eee9f2781323ef5b8447f081090e59e88d0502517e2e563135');
    assert.equal(variant.other_phase_records_preserved, 21);
  }
  assert.equal(receipt.public_refusal_count, 20);
  assert.equal(receipt.new_role_pairs, 0);
  assert.equal(receipt.game_import_verified, false);
});
