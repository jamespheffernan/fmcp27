// A role in Football Manager 27 is its name: one in possession, one out of possession.
// These checks run the real backend on the 4-2-3-1 template and hold three things:
//   1. no result of any action names the field the earlier interface carried beside a role,
//      or carries one of its values;
//   2. a role edit by name stores the word the earlier interface stored for that role;
//   3. a request that still carries the removed field is accepted and the field ignored.
// Outputs go to a temporary Tactics directory that is removed afterwards. No game is touched.
import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync } from 'node:fs';
import { homedir, tmpdir } from 'node:os';
import { join } from 'node:path';
import test from 'node:test';
import { dropLegacyRoleFields, registerTacticFileTool, runTacticFile } from '../pi/fm-tactic-files.mjs';

const fixture = JSON.parse(readFileSync(new URL('./fixtures/role-words-4231-fm27.json', import.meta.url), 'utf8'));
const template = join(homedir(), 'Library/Application Support/Sports Interactive/Football Manager 27/Tactics', fixture.template);
const python = process.env.PI_FM_TACTIC_PYTHON || '/Users/jamesheffernan/GitHub/FM26 Deepener/.venv/bin/python';
const sha = bytes => createHash('sha256').update(bytes).digest('hex');
const unusable = !existsSync(python) ? 'the codec Python is not on this machine'
  : !existsSync(template) ? `${fixture.template} is not in the Tactics folder`
    : sha(readFileSync(template)) !== fixture.template_sha256 ? `${fixture.template} differs from the one the fixture was taken from`
      : false;

let tool;
registerTacticFileTool({ registerTool: value => { tool = value; } });

const LEGACY_FIELD = /dut(y|ies)/i;
const LEGACY_VALUES = new Set(['Defend', 'Stopper', 'Cover', 'Support', 'Attack', 'Automatic']);

// Every place a result names the removed field or carries one of its values.
function legacyWording(value, path = 'result') {
  if (Array.isArray(value)) return value.flatMap((item, index) => legacyWording(item, `${path}[${index}]`));
  if (value && typeof value === 'object') {
    return Object.entries(value).flatMap(([key, item]) =>
      [...(LEGACY_FIELD.test(key) ? [`${path}.${key}`] : []), ...legacyWording(item, `${path}.${key}`)]);
  }
  if (typeof value === 'string' && (LEGACY_VALUES.has(value) || /\bdut(y|ies)\b|Duty/.test(value))) {
    return [`${path}=${JSON.stringify(value.slice(0, 80))}`];
  }
  return [];
}

test('the wording check itself finds the removed field, its values and its metadata names', () => {
  assert.deepEqual(legacyWording({ roles: [{ role: 'Full-Back', duty: 'Defend' }], duties: [{ metadata_name: 'SupportDuty' }],
    scope: 'native duty normalization', kept: ['Supporting Runs', 'Attacking Midfielder', 'Wide Covering Defensive Midfielder'] }), [
    'result.roles[0].duty', 'result.roles[0].duty="Defend"', 'result.duties', 'result.duties[0].metadata_name="SupportDuty"',
    'result.scope="native duty normalization"']);
});

test('dropping the removed field changes nothing else and mutates nothing', () => {
  const request = { action: 'generate', name: 'x', native_authoring: { instruction_policy: 'preserve', roles: [
    { phase: 'in_possession', position_index: 10, role: 'Deep-Lying Forward', duty: 'Defend' },
    { phase: 'out_of_possession', position_index: 1, role: 'Pressing Full-Back' }] } };
  const before = structuredClone(request);
  assert.deepEqual(dropLegacyRoleFields(request), { action: 'generate', name: 'x', native_authoring: { instruction_policy: 'preserve', roles: [
    { phase: 'in_possession', position_index: 10, role: 'Deep-Lying Forward' },
    { phase: 'out_of_possession', position_index: 1, role: 'Pressing Full-Back' }] } });
  assert.deepEqual(request, before);
});

test('every action names roles only; a role edit by name stores the word it stored before; the removed field is ignored',
  { skip: unusable, timeout: 600_000 }, async () => {
    const scratch = mkdtempSync(join(tmpdir(), 'pi-fm-roles-by-name-'));
    const tactics = join(scratch, 'Tactics');
    mkdirSync(tactics);
    const templateSha = fixture.template_sha256;
    const word = (phase, index, role) => fixture.slots
      .find(slot => slot.phase === phase && slot.position_index === index).stored_word_by_role[role];
    const edits = [{ phase: 'in_possession', position_index: 10, role: 'Deep-Lying Forward' },
      { phase: 'out_of_possession', position_index: 1, role: 'Pressing Full-Back' }];
    const expected = edits.map(edit => [edit.phase, edit.position_index, edit.role, word(edit.phase, edit.position_index, edit.role)]);
    assert.deepEqual(expected.map(row => row[3]), ['0000000000800400', '0000000000400400']);
    // The same edits as a request written for the earlier interface, with values the game never
    // accepted for these roles: if the field were read, these would be refused.
    const carrying = edits.map((edit, index) => ({ ...edit, duty: ['Defend', 'Attack'][index] }));
    const base = { action: 'generate', template_path: template, template_sha256: templateSha };
    const results = {};
    try {
      results.inspect = await runTacticFile({ action: 'inspect', template_path: template });
      results.catalog = await runTacticFile({ action: 'authoring_catalog' });
      results.template_catalog = await runTacticFile({ action: 'authoring_catalog', template_path: template, template_sha256: templateSha });
      const listed = await runTacticFile({ action: 'list_templates' });
      // Tactic names, paths and styles are the owner's free text; everything else is checked.
      results.list_templates = { ...listed, templates: listed.templates
        .map(({ name, template_path, tactical_style, ...rest }) => rest) };
      assert.ok(listed.templates.some(row => row.template_sha256 === templateSha));

      // The catalog lists the legal roles of each position by name, the same roles in the same order as before.
      assert.equal(results.catalog.legal_roles_for_current_positions, null);
      assert.deepEqual(results.template_catalog.legal_roles_for_current_positions.map(row =>
        [row.phase, row.position_index, row.position_name, row.legal_roles, row.roles_refused_for_more_than_one_stored_word]),
      fixture.slots.map(slot => [slot.phase, slot.position_index, slot.position_name, Object.keys(slot.stored_word_by_role), []]));
      for (const rows of Object.values(results.inspect.stored_football.phase_positions_and_roles)) {
        for (const row of rows) assert.deepEqual(Object.keys(row), ['slot', 'position', 'native_position_mask', 'role', 'native_role_word']);
      }

      results.preview = await runTacticFile({ ...base, name: 'Roles by name preview', preview: true, native_authoring: { roles: edits } });
      assert.equal(results.preview.status, 'preview');
      results.written = await runTacticFile({ ...base, name: 'Roles by name written', fm27_folder: true,
        tactics_directory: tactics, native_authoring: { roles: edits } });
      assert.equal(results.written.status, 'native_archive_written_and_roundtrip_verified');
      // The earlier request shape through the registered tool, the way Pi calls it: prepare, then execute.
      const viaTool = await tool.execute('earlier-request-shape', tool.prepareArguments({ ...base, name: 'Roles by name earlier request',
        fm27_folder: true, tactics_directory: tactics, native_authoring: { roles: carrying } }));
      assert.equal(viaTool.isError, undefined, viaTool.content[0].text);
      results.earlier_request_through_tool = viaTool.details;
      assert.deepEqual(JSON.parse(viaTool.content[0].text), viaTool.details);
      // And straight to the backend, as one of the adviser's saved scripts would send it.
      results.earlier_request_to_backend = await runTacticFile({ ...base, name: 'Roles by name earlier backend', preview: true,
        native_authoring: { roles: carrying } });

      for (const label of ['preview', 'written', 'earlier_request_through_tool', 'earlier_request_to_backend']) {
        const authored = results[label].native_authoring;
        assert.deepEqual(authored.roles.map(row => [row.phase, row.position_index, row.role, row.after_word]), expected, label);
        for (const row of authored.roles) {
          assert.deepEqual(Object.keys(row).sort(),
            ['after_word', 'before_word', 'changed', 'native_execution', 'phase', 'position_index', 'role'], label);
        }
        assert.equal(authored.all22_position_role_selections_legal, true, label);
        assert.equal(authored.native_complete_serializer_and_reload_verified, true, label);
        assert.equal(authored.all22_typed_records_verified, true, label);
        assert.deepEqual(authored.native_records, results.written.native_authoring.native_records, label);
        for (const [phase, index, role, stored] of expected) {
          const row = results[label].stored_football.phase_positions_and_roles[phase][index];
          assert.deepEqual([row.role, row.native_role_word], [role, stored], label);
        }
      }
      assert.equal(results.written.native_authoring.postpack_verification.all22_typed_records_verified, true);

      // The file on disk reads back with the requested roles and the earlier words; its receipt names roles only.
      results.receipt = JSON.parse(readFileSync(results.written.receipt_path, 'utf8'));
      results.earlier_request_receipt = JSON.parse(readFileSync(results.earlier_request_through_tool.receipt_path, 'utf8'));
      results.read_back = await runTacticFile({ action: 'inspect', template_path: results.written.output_path });
      for (const [phase, index, role, stored] of expected) {
        const row = results.read_back.stored_football.phase_positions_and_roles[phase][index];
        assert.deepEqual([row.role, row.native_role_word], [role, stored]);
      }

      // A role the game does not offer at the position refuses with the legal roles, by name.
      const refused = { ...base, name: 'Roles by name refusal', preview: true,
        native_authoring: { roles: [{ phase: 'in_possession', position_index: 10, role: 'Full-Back', duty: 'Support' }] } };
      await assert.rejects(runTacticFile(refused), error => {
        results.refusal = { message: error.message, diagnostic: error.diagnostic };
        return true;
      });
      assert.deepEqual(results.refusal.diagnostic.requested, { role: 'Full-Back' });
      assert.deepEqual(results.refusal.diagnostic.legal_roles,
        Object.keys(fixture.slots.find(slot => slot.phase === 'in_possession' && slot.position_index === 10).stored_word_by_role));
      assert.match(results.refusal.message, /requested Full-Back\. Native position role mask refuses requested role\. Legal roles: /);
      const refusedByTool = await tool.execute('refused-role', tool.prepareArguments(refused));
      assert.equal(refusedByTool.isError, true);
      results.refusal_through_tool = { text: JSON.parse(refusedByTool.content[0].text), details: refusedByTool.details };
      results.schema = (await tool.execute('schema', { action: 'schema' })).details;

      for (const [label, value] of Object.entries(results)) assert.deepEqual(legacyWording(value), [], label);
      assert.equal(sha(readFileSync(template)), templateSha);
    } finally {
      rmSync(scratch, { recursive: true, force: true });
    }
  });
