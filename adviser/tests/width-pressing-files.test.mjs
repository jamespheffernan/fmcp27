import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import test from 'node:test';
import { registerTacticFileTool } from '../pi/fm-tactic-files.mjs';

test('native width and pressing schema exposes exact labels and bounded stored semantics', () => {
  let tool;
  registerTacticFileTool({ registerTool(value) { tool = value; } });
  for (const [field, labels] of Object.entries({
    team_width: ['No explicit selection', 'Much Wider', 'Wider', 'Narrower', 'Much Narrower'],
    pressing_frequency: ['No explicit selection', 'Trigger Press Much More Often', 'Trigger Press More Often',
      'Trigger Press Less Often', 'Trigger Press Much Less Often'],
  })) {
    const parameter = tool.parameters.properties[field];
    assert.equal(parameter.type, 'string');
    assert.deepEqual(parameter.enum, labels);
    assert.ok(!tool.parameters.required.includes(field));
    assert.match(parameter.description, /Omit to inherit/);
    assert.match(parameter.description, /Conflicting source/);
    assert.match(parameter.description, /Native UI clearing, effective default, phase applicability and game import are unverified/);
  }
});

test('native archives support width and pressing changes with exact preservation and refusal checks', () => {
  const result = spawnSync('/Users/jamesheffernan/GitHub/FM26 Deepener/.venv/bin/python', [
    fileURLToPath(new URL('./width-pressing-files.py', import.meta.url)),
    fileURLToPath(new URL('../pi/fm-tactic-files.py', import.meta.url)),
  ], { encoding: 'utf8', timeout: 120000 });
  assert.equal(result.status, 0, result.stderr || String(result.error));
  const receipt = JSON.parse(result.stdout);
  assert.ok(receipt.templates_checked >= 9);
  assert.deepEqual(receipt.versions, [26, 27]);
  assert.equal(receipt.selections_per_control, 5);
  assert.deepEqual(receipt.controls, ['team_width', 'pressing_frequency']);
  assert.equal(receipt.single_control_archives, receipt.templates_checked * 10);
  assert.equal(receipt.combined_controls.length, 2);
  for (const control of receipt.combined_controls) {
    assert.deepEqual(control.after, { team_width: 'Wider', pressing_frequency: 'Trigger Press Less Often' });
    assert.notEqual(control.before.team_width, control.after.team_width);
    assert.notEqual(control.before.pressing_frequency, control.after.pressing_frequency);
  }
});
