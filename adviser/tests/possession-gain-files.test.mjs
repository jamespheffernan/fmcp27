import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import test from 'node:test';
import { registerTacticFileTool } from '../pi/fm-tactic-files.mjs';

test('possession-gain schema exposes exact stored triad with inheritance and limited scope', () => {
  let tool;
  registerTacticFileTool({ registerTool(value) { tool = value; } });
  const field = tool.parameters.properties.possession_gain;
  assert.equal(field.type, 'string');
  assert.deepEqual(field.enum, ['No explicit selection', 'Counter', 'Hold Shape']);
  assert.ok(!tool.parameters.required.includes('possession_gain'));
  assert.match(field.description, /Omit to inherit/);
  assert.match(field.description, /without claiming an effective default/);
  assert.match(field.description, /does not encode space-dependent conditional countering/);
});

test('native possession-gain triad writes FM27 changes, preserves bytes and rejects guarded negatives', () => {
  const result = spawnSync('/Users/jamesheffernan/GitHub/FM26 Deepener/.venv/bin/python', [
    fileURLToPath(new URL('./possession-gain-files.py', import.meta.url)),
    fileURLToPath(new URL('../pi/fm-tactic-files.py', import.meta.url)),
  ], { encoding: 'utf8', timeout: 120000 });
  assert.equal(result.status, 0, result.stderr || String(result.error));
  const receipt = JSON.parse(result.stdout);
  assert.ok(receipt.templates_checked >= 9);
  assert.equal(receipt.triad_archives, receipt.templates_checked * 3);
  assert.deepEqual(Object.keys(receipt.changed_fm27_controls).sort(), ['Counter', 'Hold Shape', 'No explicit selection']);
  assert.equal(receipt.combined_previous_controls, 3);
  assert.equal(receipt.native_spans_checked, 10);
  assert.equal(receipt.valid_hash_conflict_refusals, 3);
  assert.equal(receipt.game_import_verified, false);
});
