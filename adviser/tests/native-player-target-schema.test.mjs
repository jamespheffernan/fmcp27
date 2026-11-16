import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { homedir } from 'node:os';
import { join } from 'node:path';
import { pathToFileURL } from 'node:url';
import test from 'node:test';
import { registerTacticFileTool } from '../pi/fm-tactic-files.mjs';
import { registerSkillTool } from '../pi/fm-skills.mjs';

const { validateToolArguments } = await import(pathToFileURL(join(homedir(),
  '.bun/install/global/node_modules/@earendil-works/pi-ai/dist/utils/validation.js')).href);
const catalog = JSON.parse(await readFile(new URL('../pi/fm_tactic_role_catalog.json', import.meta.url), 'utf8'));
const fixture = JSON.parse(await readFile(new URL('./fixtures/native-authoring-plan.json', import.meta.url), 'utf8'));
let tool;
registerTacticFileTool({ registerTool: value => { tool = value; } });
const validate = arguments_ => validateToolArguments(tool, { name: tool.name, arguments: arguments_ });
const request = row => ({ ...structuredClone(fixture.request), native_authoring: { player_instructions: [row] } });
const row = () => ({ phase: 'out_of_possession', position_index: 5, instructions: [] });

test('actual Pi validator admits PI28 as a plain toggle and the40-name Boolean transport boundary', () => {
  for (const phase of ['in_possession', 'out_of_possession']) {
    const value = request({ ...row(), phase, instructions: ['PI_SWITCH_POSITION'] });
    assert.deepEqual(validate(value), value);
  }
  const names = catalog.player_instructions.filter(p => p.native_option > 0 && ![34, 35].includes(p.native_option))
    .map(p => p.metadata_name);
  assert.equal(names.length, 40);
  const boundary = request({ ...row(), instructions: names });
  assert.deepEqual(validate(boundary), boundary);
  // This is a schema boundary, not proof that all40 simultaneous selections
  // are natively available or compatible for this role/context.
});

test('goalkeeper storage target and menu None are refused as explicit PI35 targets', () => {
  for (const target of ['GK', 'None', 0]) {
    assert.throws(() => validate(request({ ...row(), mark_specific_position: target })), /Validation failed/, String(target));
  }
});

test('typed position marking represents exactly25 canonical non-GK targets in OOP rows', () => {
  const names = catalog.positions.filter(p => p.native_mask !== 1)
    .map(p => p.compiled_english_name || p.metadata_mask_components.join('+'));
  assert.equal(names.length, 25);
  const schema = tool.parameters.properties.native_authoring.properties.player_instructions.items;
  assert.deepEqual(schema.properties.mark_specific_position.enum, names);
  for (const target of names) {
    const value = request({ ...row(), mark_specific_position: target });
    assert.deepEqual(validate(value), value, target);
    value.native_authoring.player_instructions[0].instructions = ['PI_MARK_TIGHTER'];
    assert.deepEqual(validate(value), value, `${target} with Boolean selection`);
  }
});

test('typed target and Boolean controls reject malformed fields, phases, raw masks and unbound PI names', () => {
  const bad = [
    { ...row(), phase: 'in_possession', mark_specific_position: 'D(C)' },
    { ...row(), mark_specific_position: '' },
    { ...row(), mark_specific_position: 'D(X)' },
    { ...row(), mark_specific_position: '0x10' },
    { ...row(), mark_specific_position: 16 },
    { ...row(), mark_specific_position: true },
    { ...row(), mark_specific_position: { native_mask: 16 } },
    { ...row(), mark_specific_position: 'D(C)', native_target_mask: 16 },
    { phase: 'out_of_possession', position_index: 5, mark_specific_position: 'D(C)' },
    { ...row(), instructions: ['PI_NONE'] },
    { ...row(), instructions: ['PI_MARK_SPECIFIC_PLAYER'] },
    { ...row(), instructions: ['PI_MARK_SPECIFIC_POSITION'] },
    { ...row(), instructions: ['PI_MARK_SPECIFIC_POSITION'], mark_specific_position: 'D(C)' },
    { ...row(), instructions: ['PI_SWITCH_POSITION', 'PI_SWITCH_POSITION'] },
    { ...row(), instructions: Array.from({ length: 41 }, (_, i) => `PI_FAKE_${i}`) },
  ];
  for (const value of bad) assert.throws(() => validate(request(value)), /Validation failed/, JSON.stringify(value));
  const clear = request(row());
  for (const instruction_policy of ['preserve', 'native_defaults']) {
    clear.native_authoring.instruction_policy = instruction_policy;
    assert.deepEqual(validate(clear), clear);
  }
});

test('delivered guide distinguishes typed target replacement, PI28 availability and fixed player correspondence', async () => {
  let reader;
  registerSkillTool({ registerTool: value => { reader = value; } });
  const loaded = await reader.execute('typed-marking-guide', { id: 'fm-create-tactic' });
  assert.equal(loaded.isError, undefined);
  assert.equal(loaded.details.content, await readFile(new URL('../skills/fm-create-tactic/SKILL.md', import.meta.url), 'utf8'));
  const content = loaded.details.content;
  assert.match(content, /`PI_SWITCH_POSITION` \(28\) is an ordinary Boolean/);
  assert.match(content, /`mark_specific_position`/);
  assert.match(content, /clears Boolean selections; a supplied typed marking target still adds PI35/);
  assert.match(tool.parameters.properties.native_authoring.properties.player_instructions.description, /supplied mark_specific_position still adds35/);
  assert.match(content, /automatically adds/);
  assert.match(content, /omit `mark_specific_position`/);
  assert.match(content, /inactive target bytes/);
  assert.match(content, /original compiled PI35 menu builder/);
  assert.match(content, /live-rendered UI observation remains unverified/);
  assert.match(tool.parameters.properties.native_authoring.properties.player_instructions.items.properties.mark_specific_position.description, /25 admitted non-GK targets match the original compiled PI35 menu builder/);
  assert.match(content, /preserve_existing_player_correspondence/);
});
