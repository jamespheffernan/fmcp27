import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import { writeFileSync } from 'node:fs';
import test from 'node:test';
import { registerTacticFileTool } from '../pi/fm-tactic-files.mjs';

test('pressing-block schema exposes exact stored group and inheritance', () => {
  let tool;
  registerTacticFileTool({ registerTool(value) { tool = value; } });
  const field = tool.parameters.properties.pressing_block;
  assert.equal(field.type, 'string');
  assert.deepEqual(field.enum, ['No explicit selection', 'High Press', 'Mid Block', 'Low Block']);
  assert.ok(!tool.parameters.required.includes('pressing_block'));
  assert.match(field.description, /Omit to inherit/);
  assert.match(field.description, /without claiming an effective default/);
  assert.match(field.description, /separate from stored pressing frequency and defensive-line height/);
  assert.match(field.description, /game import are unverified/);
});

test('native pressing-block group makes actual FM27 changes and preserves every other field', () => {
  const result = spawnSync('/Users/jamesheffernan/GitHub/FM26 Deepener/.venv/bin/python', [
    fileURLToPath(new URL('./pressing-block-files.py', import.meta.url)),
    fileURLToPath(new URL('../pi/fm-tactic-files.py', import.meta.url)),
  ], { encoding: 'utf8', timeout: 180000 });
  assert.equal(result.status, 0, result.stderr || String(result.error));
  const receipt = JSON.parse(result.stdout);
  assert.ok(receipt.templates_checked >= 9);
  assert.equal(receipt.selection_archives, receipt.templates_checked * 4);
  assert.deepEqual(Object.keys(receipt.changed_fm27_controls).sort(), ['High Press', 'Low Block', 'Mid Block', 'No explicit selection']);
  assert.equal(receipt.combined_previous_controls, 4);
  assert.equal(receipt.native_spans_checked, 12);
  assert.equal(receipt.valid_hash_conflict_refusals, 16);
  assert.equal(receipt.valid_hash_vector_prefix_refusals, 30);
  assert.equal(receipt.game_import_verified, false);
  writeFileSync(new URL('../evidence/tactic-pressing-block-20261108/positive-artifacts.json', import.meta.url), `${JSON.stringify(receipt, null, 2)}\n`);
});
