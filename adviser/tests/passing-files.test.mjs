import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import test from 'node:test';
import { registerTacticFileTool } from '../pi/fm-tactic-files.mjs';

test('passing directness exposes exact stored selections and omission inheritance', () => {
  let tool;
  registerTacticFileTool({ registerTool(value) { tool = value; } });
  const field = tool.parameters.properties.passing_directness;
  assert.equal(field.type, 'string');
  assert.deepEqual(field.enum, ['No explicit selection', 'Much More Direct Passing',
    'More Direct Passing', 'Shorter Passing', 'Much Shorter Passing']);
  assert.ok(!tool.parameters.required.includes('passing_directness'));
  assert.match(field.description, /Omit to inherit/);
  assert.match(field.description, /Conflicting source/);
  assert.match(field.description, /game import are unverified/);
});

test('native passing edits change selected FM26/FM27 sources, preserve bytes and refuse conflicts', () => {
  const result = spawnSync('/Users/jamesheffernan/GitHub/FM26 Deepener/.venv/bin/python', [
    fileURLToPath(new URL('./passing-files.py', import.meta.url)),
    fileURLToPath(new URL('../pi/fm-tactic-files.py', import.meta.url)),
  ], { encoding: 'utf8', timeout: 60000 });
  assert.equal(result.status, 0, result.stderr || String(result.error));
  const receipt = JSON.parse(result.stdout);
  assert.ok(receipt.templates_checked >= 6);
  assert.deepEqual(receipt.versions, [26, 27]);
  assert.equal(receipt.passing_variants_per_template, 5);
  assert.equal(receipt.archives_generated, 10);
  assert.deepEqual(receipt.changed_controls.map(({ source_major, before, after }) =>
    ({ source_major, before, after })), [26, 27].map(source_major =>
    ({ source_major, before: 'More Direct Passing', after: 'Shorter Passing' })));
});
