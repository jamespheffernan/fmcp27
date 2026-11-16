import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import { writeFileSync } from 'node:fs';
import test from 'node:test';
import { registerTacticFileTool } from '../pi/fm-tactic-files.mjs';

test('OOP right wing-back schema names the exact second case and its limits', () => {
  let tool;
  registerTacticFileTool({ registerTool(value) { tool = value; } });
  const role = tool.parameters.properties.base_role;
  assert.deepEqual(role.properties.phase.enum, ['in_possession', 'out_of_possession']);
  assert.deepEqual(role.properties.position_index.enum, [1, 4, 5, 7, 8, 9]);
  assert.deepEqual(role.properties.donor_position_index.enum, [1, 4, 5, 7, 8, 9]);
  assert.match(role.description, /OOP slot4 WB\(R\) or OOP slot7 WB\(L\) Pressing Wing-Back to Wing-Back or reverse/);
  assert.match(role.description, /Stored-record reproduction only/);
  assert.match(role.description, /effective instructions are unverified/);
  assert.equal(role.additionalProperties, false);
});

test('actual native OOP donor role changes while all other records and payloads remain', () => {
  const result = spawnSync('/Users/jamesheffernan/GitHub/FM26 Deepener/.venv/bin/python', [
    fileURLToPath(new URL('./oop-wing-back-files.py', import.meta.url)),
    fileURLToPath(new URL('../pi/fm-tactic-files.py', import.meta.url)),
  ], { encoding: 'utf8', timeout: 180000 });
  assert.equal(result.status, 0, result.stderr || String(result.error));
  const receipt = JSON.parse(result.stdout);
  assert.equal(receipt.other_records_preserved, 21);
  assert.equal(receipt.semantic_cases.length, 22);
  assert.ok(receipt.semantic_cases.includes('target-PI-1000000000'));
  assert.ok(receipt.semantic_cases.includes('target-PI-1080000000'));
  assert.equal(receipt.native_spans, 7);
  assert.ok(receipt.public_refusals >= 60);
  assert.equal(receipt.artifacts.length, 3);
  assert.equal(receipt.game_import_verified, false);
  writeFileSync(new URL('../evidence/tactic-next-role-pair-20261108/positive-artifacts.json', import.meta.url), `${JSON.stringify(receipt, null, 2)}\n`);
});
