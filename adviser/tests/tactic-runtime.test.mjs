import assert from 'node:assert/strict';
import { mkdirSync, mkdtempSync, readFileSync, writeFileSync, copyFileSync, chmodSync } from 'node:fs';
import { join } from 'node:path';
import { homedir } from 'node:os';
import { pathToFileURL, fileURLToPath } from 'node:url';
import test from 'node:test';
import { captureRegistration, runtimeInfo, schemaSha256, snapshotParameters } from '../pi/fm-tactic-runtime.mjs';
import { registerTacticFileTool } from '../pi/fm-tactic-files.mjs';

const root = fileURLToPath(new URL('../', import.meta.url));
let tool;
registerTacticFileTool({ registerTool: value => { tool = value; } });
const { validateToolArguments } = await import(pathToFileURL(join(homedir(),
  '.bun/install/global/node_modules/@earendil-works/pi-ai/dist/utils/validation.js')).href);

test('schema discovery returns the exact frozen registration contract without a native backend', async () => {
  const originalPython = process.env.PI_FM_TACTIC_PYTHON;
  process.env.PI_FM_TACTIC_PYTHON = '/nonexistent/schema-discovery-must-not-dispatch-python';
  try {
    const result = await tool.execute('registered-schema', { action: 'schema' });
    assert.equal(result.isError, undefined);
    assert.equal(result.details.tool_name, tool.name);
    assert.strictEqual(result.details.registered_parameters, tool.parameters);
    assert.equal(result.details.schema_sha256, schemaSha256(tool.parameters));
    assert.equal(result.details.schema_sha256, result.details.authoring_runtime.registered.schema_sha256);
    const row = result.details.registered_parameters.properties.native_authoring.properties.player_instructions.items;
    assert.equal(row.additionalProperties, false);
    assert.ok(row.properties.mark_specific_position.enum.includes('AM(C)'));
    assert.deepEqual(row.required, ['phase', 'position_index', 'instructions']);
    assert.throws(() => { row.properties.mark_specific_position.enum[0] = 'tamper'; }, TypeError);
    assert.throws(() => { result.details.registered_parameters.additionalProperties = true; }, TypeError);
    for (const params of [{ action: 'schema', template_path: 'unused' }, { action: 'schema', native_authoring: {} }]) {
      const refused = await tool.execute('extra-schema-fields', params);
      assert.equal(refused.isError, true);
      assert.match(refused.content[0].text, /schema accepts only action/);
    }
    const again = await tool.execute('registered-schema-again', { action: 'schema' });
    assert.equal(again.details.schema_sha256, schemaSha256(again.details.registered_parameters));
  } finally {
    if (originalPython === undefined) delete process.env.PI_FM_TACTIC_PYTHON;
    else process.env.PI_FM_TACTIC_PYTHON = originalPython;
  }
});

test('schema snapshot is detached from producer mutation and recursively immutable', () => {
  const producer = { type: 'object', properties: { action: { enum: ['schema'] } } };
  const snapshot = snapshotParameters(producer);
  producer.properties.action.enum.push('later-producer-mutation');
  producer.properties.extra = { type: 'string' };
  assert.deepEqual(snapshot, { type: 'object', properties: { action: { enum: ['schema'] } } });
  assert.throws(() => { snapshot.properties.action.enum.push('tamper'); }, TypeError);
});

test('registration fingerprints the actual schema object, preserving every typed target', () => {
  const registered = captureRegistration(tool.parameters);
  assert.equal(registered.schema_sha256, schemaSha256(tool.parameters));
  assert.equal(registered.capabilities.mark_specific_position, true);
  assert.deepEqual(registered.capabilities.mark_specific_position_targets,
    tool.parameters.properties.native_authoring.properties.player_instructions.items.properties.mark_specific_position.enum);
  assert.equal(registered.capabilities.mark_specific_position_targets.length, 25);
  assert.throws(() => { registered.capabilities.mark_specific_position = false; }, TypeError);
  assert.equal(runtimeInfo(registered).registration_adapter_files_match_current_disk, true);
  assert.equal(runtimeInfo(registered).ui_controls_verified, false);
});

test('missing schema capability stays absent and schema hashes are key-order independent', () => {
  const legacy = structuredClone(tool.parameters);
  delete legacy.properties.native_authoring.properties.player_instructions.items.properties.mark_specific_position;
  const registered = captureRegistration(legacy);
  assert.equal(registered.capabilities.mark_specific_position, false);
  assert.equal(registered.capabilities.mark_specific_position_targets, null);
  assert.notEqual(registered.schema_sha256, schemaSha256(tool.parameters));
  assert.equal(schemaSha256({ b: { z: 1, a: 2 }, a: [1, 2] }),
    schemaSha256({ a: [1, 2], b: { a: 2, z: 1 } }));
});

test('actual Pi validator reproduces schema-only marking rejection and accepts unchanged exact request in current schema', () => {
  const legacy = { ...tool, parameters: structuredClone(tool.parameters) };
  delete legacy.parameters.properties.native_authoring.properties.player_instructions.items.properties.mark_specific_position;
  const arguments_ = { action: 'generate', native_authoring: { player_instructions: [
    { phase: 'out_of_possession', position_index: 5, instructions: [], mark_specific_position: 'AM(C)' },
  ] } };
  assert.throws(() => validateToolArguments(legacy, { name: tool.name, arguments: arguments_ }), /mark_specific_position: unknown field/);
  assert.deepEqual(validateToolArguments(tool, { name: tool.name, arguments: arguments_ }), arguments_);
  // Causal control only: the linked historical session did not preserve its schema.
});

test('missing filesystem evidence stays unknown; observed adapter change is false', () => {
  const registered = captureRegistration(tool.parameters);
  const missing = structuredClone(registered.filesystem_at_registration);
  missing.files['pi/fm-tactic-files.mjs'] = { state: 'unavailable', reason: 'ENOENT' };
  assert.equal(runtimeInfo(registered, missing).registration_adapter_files_match_current_disk, null);
  const changed = structuredClone(registered.filesystem_at_registration);
  changed.files['pi/fm-tactic-runtime.mjs'].sha256 = '0'.repeat(64);
  assert.equal(runtimeInfo(registered, changed).registration_adapter_files_match_current_disk, false);
});

test('actual registered adapter refuses changed disk before backend; inspect retains registration evidence', async () => {
  // Transport-only fixture. It runs in an owned external tmp copy, never installed files.
  mkdirSync(join(root, 'tmp'), { recursive: true });
  const directory = mkdtempSync(join(root, 'tmp', 'registration-drift-'));
  mkdirSync(join(directory, 'pi'));
  writeFileSync(join(directory, 'package.json'), '{"type":"module","version":"test-registration"}');
  for (const name of ['fm-tactic-files.mjs', 'fm-tactic-runtime.mjs'])
    copyFileSync(join(root, 'pi', name), join(directory, 'pi', name));
  // Node is the explicit fixture backend; no native executable or game process is invoked.
  const calls = join(directory, 'backend-calls.txt');
  const backend = join(directory, 'backend.mjs');
  writeFileSync(join(directory, 'pi/fm-tactic-files.py'), '# transport metadata fixture only\n');
  writeFileSync(backend,
    `#!${process.execPath}\nimport {appendFileSync} from 'node:fs'; process.stdin.resume(); process.stdin.on('end', () => { appendFileSync(${JSON.stringify(calls)}, 'call\\n'); console.log(JSON.stringify({transport_fixture:true})); });`);
  chmodSync(backend, 0o700);
  const { registerTacticFileTool: register } = await import(pathToFileURL(join(directory, 'pi/fm-tactic-files.mjs')));
  let captured;
  register({ registerTool: value => { captured = value; } });
  const expected = schemaSha256(captured.parameters);
  const originalPython = process.env.PI_FM_TACTIC_PYTHON;
  process.env.PI_FM_TACTIC_PYTHON = backend;
  try {
    const first = await captured.execute('inspect-before', { action: 'inspect' });
    assert.equal(first.details.transport_fixture, true);
    assert.equal(Object.hasOwn(first.details, 'registered_parameters'), false);
    assert.equal(Object.hasOwn(first.details.authoring_runtime.registered, 'registered_parameters'), false);
    assert.equal(readFileSync(calls, 'utf8'), 'call\n');
    assert.equal(first.details.authoring_runtime.registered.schema_sha256, expected);
    const registeredFiles = first.details.authoring_runtime.registered.filesystem_at_registration;
    const module = join(directory, 'pi/fm-tactic-files.mjs');
    writeFileSync(module, `${readFileSync(module, 'utf8')}\n// simulated installed source update\n`);
    writeFileSync(join(directory, 'package.json'), '{"type":"module","version":"test-current"}');
    const rejected = await captured.execute('changed-generation', { action: 'generate', preview: true });
    assert.equal(rejected.isError, true);
    assert.equal(readFileSync(calls, 'utf8'), 'call\n');
    assert.equal(rejected.details.diagnostic.kind, 'tactic_registration_filesystem_mismatch');
    assert.equal(rejected.details.diagnostic.automatic_substitution_applied, false);
    assert.match(rejected.content[0].text, /test-registration.*test-current/);
    assert.match(rejected.content[0].text, new RegExp(expected));
    for (const action of ['inspect', 'authoring_catalog']) {
      const result = await captured.execute(`after-${action}`, { action });
      assert.equal(result.details.transport_fixture, true);
      const info = result.details.authoring_runtime;
      assert.equal(info.registration_adapter_files_match_current_disk, false);
      assert.equal(info.registered.schema_sha256, expected);
      assert.deepEqual(info.registered.filesystem_at_registration, registeredFiles);
      assert.equal(info.current_filesystem.adviser_version, 'test-current');
      assert.match(info.current_filesystem.scope, /not proof of executed JS/);
    }
  } finally {
    if (originalPython === undefined) delete process.env.PI_FM_TACTIC_PYTHON;
    else process.env.PI_FM_TACTIC_PYTHON = originalPython;
  }
});
