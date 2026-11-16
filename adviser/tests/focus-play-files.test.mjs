import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import { mkdirSync, writeFileSync } from 'node:fs';
import test from 'node:test';
import { registerTacticFileTool } from '../pi/fm-tactic-files.mjs';

test('focus of play accepts distinct native selections and an explicit empty list', () => {
  let tool; registerTacticFileTool({ registerTool(t) { tool = t; } });
  const field = tool.parameters.properties.focus_play;
  assert.equal(field.type, 'array');
  assert.equal(field.uniqueItems, true);
  assert.equal(field.maxItems, 2);
  assert.deepEqual(field.items.enum, ['Focus Play Down The Left', 'Focus Play Down The Right', 'Focus Play Through The Middle', 'Focus Play Down Both Flanks']);
  assert.ok(!tool.parameters.required.includes('focus_play'));
});

test('focus of play preserves real archives and refuses conflicts and drift', () => {
  const result = spawnSync('/Users/jamesheffernan/GitHub/FM26 Deepener/.venv/bin/python', [fileURLToPath(new URL('./focus-play-files.py', import.meta.url)), fileURLToPath(new URL('../pi/fm-tactic-files.py', import.meta.url))], { encoding: 'utf8', timeout: 180000 });
  assert.equal(result.status, 0, result.stderr || String(result.error));
  const value = JSON.parse(result.stdout);
  assert.ok(value.templates_checked >= 9);
  assert.ok(value.artifacts.length >= 54);
  assert.ok(value.negative_controls >= 50);
  assert.equal(value.native_spans, 13);
  assert.equal(value.game_import_verified, false);
  const folder = new URL('../evidence/tactic-focus-play-20261109/', import.meta.url);
  mkdirSync(folder, { recursive: true });
  writeFileSync(new URL('artifacts.json', folder), JSON.stringify(value, null, 2) + '\n');
});
