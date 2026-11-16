import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { homedir } from 'node:os';
import { join } from 'node:path';
import { pathToFileURL } from 'node:url';
import test from 'node:test';
import { dropLegacyRoleFields, registerTacticFileTool } from '../pi/fm-tactic-files.mjs';
import { registerSkillTool } from '../pi/fm-skills.mjs';

// Use the actual installed Pi argument validator, including its documented
// coercion; no local schema facsimile or native execution is involved.
const { validateToolArguments } = await import(pathToFileURL(join(homedir(),
  '.bun/install/global/node_modules/@earendil-works/pi-ai/dist/utils/validation.js')).href);
const fixture = JSON.parse(await readFile(new URL('./fixtures/native-authoring-plan.json', import.meta.url), 'utf8'));
let tool;
registerTacticFileTool({ registerTool: value => { tool = value; } });
const validate = arguments_ => validateToolArguments(tool, { name: tool.name, arguments: arguments_ });
const copy = () => structuredClone(fixture.request);

test('actual Pi schema accepts the full requested two-phase Liverpool plan', () => {
  const request = copy();
  assert.equal(request.native_authoring.roles.length, 22);
  assert.equal(request.native_authoring.positions.in_possession.length, 11);
  assert.equal(request.native_authoring.positions.out_of_possession.length, 11);
  assert.deepEqual(validate(request), request);
  // Explicit row replacement, including a clear, remains representable after
  // either inheritance policy. Native context legality belongs to the backend.
  request.native_authoring.player_instructions = [
    { phase: 'in_possession', position_index: 0, instructions: [] },
    { phase: 'in_possession', position_index: 9, instructions: ['PI_ROAM_FROM_POSITION', 'PI_MOVE_INTO_CHANNELS'] },
  ];
  for (const instruction_policy of ['preserve', 'native_defaults']) {
    request.native_authoring.instruction_policy = instruction_policy;
    assert.deepEqual(validate(request), request);
  }
});

test('catalog discovery and existing actions/legacy donor requests remain representable', () => {
  for (const request of [{ action: 'authoring_catalog' },
    { action: 'authoring_catalog', template_path: fixture.request.template_path },
    { action: 'list_templates' }, { action: 'inspect', template_path: fixture.request.template_path },
    { action: 'generate', template_path: fixture.request.template_path, template_sha256: fixture.request.template_sha256,
      name: 'Legacy scalar fixture', tempo: 'Higher Tempo' }]) {
    assert.deepEqual(validate(request), request);
  }
  const source = copy();
  delete source.native_authoring;
  const donor = { phase: 'out_of_possession', position_index: 8, donor_position_index: 8,
    donor_template_path: 'inspected-donor.fmf', donor_template_sha256: 'a'.repeat(64) };
  assert.deepEqual(validate({ ...source, base_role: donor }), { ...source, base_role: donor });
});

test('a role entry is phase, position_index and role; a request carrying the removed field still reaches the backend without it', () => {
  const items = tool.parameters.properties.native_authoring.properties.roles.items;
  assert.deepEqual(Object.keys(items.properties), ['phase', 'position_index', 'role']);
  assert.deepEqual(items.required, ['phase', 'position_index', 'role']);
  assert.equal(items.additionalProperties, false);
  // Nothing the model is shown names the removed field: not the schema, not a description.
  assert.doesNotMatch(JSON.stringify(tool.parameters) + tool.description, /dut(y|ies)|\/(Defend|Support|Attack)\b|\((Defend|Support|Attack)\)/i);
  assert.equal(tool.prepareArguments, dropLegacyRoleFields);
  for (const value of ['Defend', 'Support', 'Attack', 'Stopper', 'Cover', 'Automatic', 'never a value', '', null, 7]) {
    const legacy = copy();
    for (const row of legacy.native_authoring.roles) row.duty = value;
    // The strict schema alone refuses the unknown field ...
    assert.throws(() => validate(legacy), /Validation failed/);
    // ... so Pi's argument preparation, which runs before validation, drops it unread.
    const prepared = tool.prepareArguments(legacy);
    assert.deepEqual(prepared, fixture.request);
    assert.deepEqual(validate(prepared), fixture.request);
    assert.equal(legacy.native_authoring.roles[0].duty, value, 'the caller\'s object is not mutated');
  }
  // Requests without the field pass through as the same object; other unknown fields stay refused.
  const plain = copy();
  assert.equal(tool.prepareArguments(plain), plain);
  for (const untouched of [{ action: 'schema' }, { action: 'inspect', template_path: 'x.fmf' }, null, 'text',
    { action: 'generate', native_authoring: { roles: 'not a list' } }, { action: 'generate', native_authoring: { roles: [null, 3, []] } }]) {
    assert.equal(dropLegacyRoleFields(untouched), untouched);
  }
  const extra = copy();
  extra.native_authoring.roles[0] = { ...extra.native_authoring.roles[0], duty: 'Defend', native_word: '0000000000200001' };
  assert.throws(() => validate(tool.prepareArguments(extra)), /Validation failed/);
});

test('Pi rejects malformed native plan shapes and transport bounds before dispatch', () => {
  const bad = [];
  const mutate = (label, edit) => { const request = copy(); edit(request); bad.push([label, request]); };
  mutate('more than22 roles', r => r.native_authoring.roles.push(r.native_authoring.roles[0]));
  mutate('negative role index', r => { r.native_authoring.roles[0].position_index = -1; });
  mutate('role index11', r => { r.native_authoring.roles[0].position_index = 11; });
  mutate('unknown phase key', r => { r.native_authoring.roles[0].phase = 'in_attack'; });
  mutate('empty role', r => { r.native_authoring.roles[0].role = ''; });
  mutate('native pointer field', r => { r.native_authoring.roles[0].address = '0x100400000'; });
  mutate('stored word field', r => { r.native_authoring.roles[0].native_word = '0000000000200001'; });
  mutate('missing role', r => { delete r.native_authoring.roles[0].role; });
  mutate('short phase layout', r => { r.native_authoring.positions.in_possession.pop(); });
  mutate('long phase layout', r => { r.native_authoring.positions.in_possession.push('D(C)'); });
  mutate('duplicate position label', r => { r.native_authoring.positions.in_possession[2] = 'GK'; });
  mutate('unknown layout phase', r => { r.native_authoring.positions.extra = r.native_authoring.positions.in_possession; });
  mutate('unknown authoring field', r => { r.native_authoring.native_word = '0x20'; });
  mutate('unknown policy', r => { r.native_authoring.instruction_policy = 'effective_defaults'; });
  mutate('duplicate team instruction', r => { r.native_authoring.team_instructions.push('Counter'); });
  mutate('more than79 team instructions', r => { r.native_authoring.team_instructions = Array.from({ length: 80 }, (_, i) => `Named option ${i}`); });
  mutate('unbound team recipient', r => { r.native_authoring.team_instructions = ['Distribute To Specific Team-Mate']; });
  for (const instruction of ['PI_NONE', 'PI_MARK_SPECIFIC_PLAYER', 'PI_MARK_SPECIFIC_POSITION', 'Roam From Position']) {
    mutate(`unsupported PI transport ${instruction}`, r => { r.native_authoring.player_instructions = [
      { phase: 'in_possession', position_index: 9, instructions: [instruction] },
    ]; });
  }
  mutate('too many PI rows', r => { r.native_authoring.player_instructions = Array.from({ length: 23 }, (_, i) =>
    ({ phase: 'in_possession', position_index: i, instructions: [] })); });
  mutate('PI index11', r => { r.native_authoring.player_instructions = [{ phase: 'in_possession', position_index: 11, instructions: [] }]; });
  mutate('duplicate PI label', r => { r.native_authoring.player_instructions = [{ phase: 'in_possession', position_index: 9,
    instructions: ['PI_ROAM_FROM_POSITION', 'PI_ROAM_FROM_POSITION'] }]; });
  mutate('too many PI labels', r => { r.native_authoring.player_instructions = [{ phase: 'in_possession', position_index: 9,
    instructions: Array.from({ length: 41 }, (_, i) => `PI_FAKE_${i}`) }]; });
  mutate('unknown PI target field', r => { r.native_authoring.player_instructions = [{ phase: 'in_possession', position_index: 9,
    instructions: [], player_ref: 'unbound-person' }]; });
  for (const [label, request] of bad) assert.throws(() => validate(request), /Validation failed/, label);
});

test('complete replacement excludes competing legacy edits while mentality and omitted-team scalar edits remain valid', () => {
  const donor = { phase: 'out_of_possession', position_index: 4, donor_position_index: 4,
    donor_template_path: 'inspected-donor.fmf', donor_template_sha256: 'a'.repeat(64) };
  for (const field of ['base_role', 'phase_position', 'stored_role_instructions']) {
    const request = copy();
    request[field] = field === 'stored_role_instructions'
      ? { ...donor, phase: 'in_possession', position_index: 9, donor_position_index: 9 } : donor;
    assert.throws(() => validate(request), /Validation failed/, field);
  }
  const selectionFields = { team_tackling: 'Stay On Feet', defensive_line: 'Higher Defensive Line', tempo: 'Higher Tempo',
    passing_directness: 'Shorter Passing', team_width: 'Wider', pressing_frequency: 'Trigger Press More Often',
    goal_kick_length: 'Short Goal Kicks', crossing_style: 'Low Crosses', final_third_delivery: 'Work Ball Into Box',
    pressing_block: 'Mid Block', focus_play: [], wide_support: [], possession_loss: 'Regroup', possession_gain: 'Counter' };
  for (const [field, value] of Object.entries(selectionFields)) {
    const request = { ...copy(), [field]: value };
    assert.throws(() => validate(request), /Validation failed/, field);
    delete request.native_authoring.team_instructions;
    assert.deepEqual(validate(request), request, `${field} without complete replacement`);
  }
  const clear = copy();
  clear.native_authoring.team_instructions = [];
  assert.deepEqual(validate(clear), clear);
  const catalog = { ...copy(), action: 'authoring_catalog' };
  assert.throws(() => validate(catalog), /Validation failed/, 'native authoring is a generate operation');
});

test('actual guidance delivery routes whole plans through native authoring with explicit clean/inherited semantics', async () => {
  let reader;
  registerSkillTool({ registerTool: value => { reader = value; } });
  const result = await reader.execute('native-plan-guide', { id: 'fm-create-tactic' });
  assert.equal(result.isError, undefined);
  const original = await readFile(new URL('../skills/fm-create-tactic/SKILL.md', import.meta.url), 'utf8');
  assert.equal(result.details.content, original);
  for (const field of ['authoring_catalog', 'native_authoring', 'positions', 'roles', 'team_instructions', 'instruction_policy', 'player_instructions']) {
    assert.ok(original.includes('`' + field + '`'), field);
  }
  assert.match(original, /explicitly supply all22/);
  assert.match(original, /native_defaults/);
  assert.match(original, /preserve/);
  assert.match(original, /does not require a donor fingerprint/);
  assert.match(original, /actual archive exists with a successful receipt/);
});
