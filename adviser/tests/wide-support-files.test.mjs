import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import { mkdirSync, writeFileSync } from 'node:fs';
import test from 'node:test';
import { registerTacticFileTool } from '../pi/fm-tactic-files.mjs';

test('wide support accepts distinct native selections and an explicit empty list', () => {
  let tool; registerTacticFileTool({ registerTool(t) { tool = t; } });
  const field = tool.parameters.properties.wide_support;
  assert.equal(field.type, 'array');
  assert.equal(field.uniqueItems, true);
  assert.equal(field.maxItems, 3);
  assert.deepEqual(field.items.enum, ['Look For Overlap', 'Overlap Left', 'Overlap Right', 'Look For Underlap', 'Underlap Left', 'Underlap Right']);
  assert.ok(!tool.parameters.required.includes('wide_support'));
});

test('wide support preserves real archives and refuses conflicts and drift', () => {
  const result = spawnSync('/Users/jamesheffernan/GitHub/FM26 Deepener/.venv/bin/python', [fileURLToPath(new URL('./wide-support-files.py', import.meta.url)), fileURLToPath(new URL('../pi/fm-tactic-files.py', import.meta.url))], { encoding: 'utf8', timeout: 300000 });
  assert.equal(result.status, 0, result.stderr || String(result.error));
  const value = JSON.parse(result.stdout);
  assert.ok(value.templates_checked >= 9);
  assert.ok(value.artifacts.length >= 153);
  assert.ok(value.negative_controls >= 700);
  assert.equal(value.native_spans, 15);
  assert.equal(value.game_import_verified, false);
  const folder = new URL('../evidence/wide-support-20261109/', import.meta.url);
  mkdirSync(folder, { recursive: true });
  writeFileSync(new URL('artifacts.json', folder), JSON.stringify(value, null, 2) + '\n');
});
