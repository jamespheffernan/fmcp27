import assert from 'node:assert/strict';
import { registerHooks } from 'node:module';
import { mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import test from 'node:test';
import { calls, codemodeCalls } from './mcp-stub.mjs';

registerHooks({
  resolve(specifier, context, nextResolve) {
    if (specifier === '@earendil-works/pi-coding-agent') {
      return { url: new URL('./mcp-stub.mjs', import.meta.url).href, shortCircuit: true };
    }
    return nextResolve(specifier, context);
  },
});
const { default: fmExtension } = await import('../pi/fm.pi.ts');

function fixture() {
  const handlers = new Map();
  const servers = [];
  const tools = [];
  const pi = {
    registerTool: tool => tools.push(tool),
    registerMcpServer: (...args) => servers.push(args),
    on: (event, handler) => handlers.set(event, handler),
    getAllTools: () => tools,
  };
  fmExtension(pi);
  return { handlers, servers, tools, call: name => handlers.get('tool_call')({ toolName: name }) };
}

test('registers only the FM server and ignores global and project MCP configuration', () => {
  const { servers } = fixture();
  assert.equal(servers.length, 1);
  assert.equal(servers[0][0], 'fm_live');
  assert.equal(servers[0][1].command, '/bin/sh');
  // Lean surface: the reader is deferred and only the small direct set is declared up front.
  assert.equal(servers[0][1].exposure, 'deferred');
  assert.equal(servers[0][1].toolExposure.fm_db_query, 'direct');
  assert.equal(servers[0][1].toolExposure.fm_get_retained_shot_map, undefined);
  assert.deepEqual(calls.at(-1).options.loadConfig({}), {
    servers: [], errors: [], autoEnableCodemode: false,
  });
});

test('checks the current annotation at every dispatch and rejects missing or revoked access', () => {
  const f = fixture();
  const name = 'mcp__fm_live__fm_get_save';
  assert.equal(f.call(name).block, true);
  f.tools.push({ name, annotations: { readOnlyHint: true } });
  assert.equal(f.call(name), undefined);
  f.tools.find(tool => tool.name === name).annotations.readOnlyHint = false;
  assert.equal(f.call(name).block, true);
  delete f.tools.find(tool => tool.name === name).annotations;
  assert.equal(f.call(name).block, true);
  f.tools.length = 0;
  assert.equal(f.call(name).block, true);
});

test('enables native Code Mode without model access and allows its outer dispatch', () => {
  const f = fixture();
  assert.deepEqual(codemodeCalls.at(-1).options, { mode: 'on', models: false });
  assert.equal(f.call('codemode'), undefined);
  assert.equal(f.call('papercut'), undefined);
  assert.ok(f.tools.some(tool => tool.name === 'fm_write_text'));
  assert.equal(f.call('fm_write_text'), undefined);
  assert.equal(f.call('fm_write_text_other').block, true);
  assert.ok(f.tools.some(tool => tool.name === 'fm_read_skill'));
  assert.equal(f.call('fm_read_skill'), undefined);
  assert.equal(f.call('fm_read_skill_other').block, true);
});

test('registers the toolbox, permits only its exact name and gives scripts the saved tools they name', async t => {
  const dir = mkdtempSync(join(tmpdir(), 'pi-fm-extension-toolbox-'));
  t.after(() => rmSync(dir, { recursive: true, force: true }));
  const before = process.env.PI_FM_TOOLBOX_DIR;
  process.env.PI_FM_TOOLBOX_DIR = dir;
  t.after(() => { if (before === undefined) delete process.env.PI_FM_TOOLBOX_DIR; else process.env.PI_FM_TOOLBOX_DIR = before; });
  const f = fixture();
  const tool = f.tools.find(tool => tool.name === 'fm_toolbox');
  assert.ok(tool);
  assert.equal(f.call('fm_toolbox'), undefined);
  assert.equal(f.call('fm_toolbox_other').block, true);
  const hook = f.handlers.get('tool_call');
  // Nothing saved: a script that does not name the toolbox is passed through untouched.
  const plain = { toolName: 'codemode', input: { code: 'return 1;' } };
  assert.equal(hook(plain), undefined);
  assert.equal(plain.input.code, 'return 1;');
  const saved = await tool.execute('id', { action: 'save', name: 'double_it', description: 'Doubles n.', code: 'return args.n * 2;' });
  assert.equal(saved.isError, undefined);
  // Saved a moment ago, usable by the next script without a restart.
  const script = { toolName: 'codemode', input: { code: 'return await toolbox.double_it({ n: 21 });' } };
  assert.equal(hook(script), undefined);
  assert.match(script.input.code, /async function __toolbox_double_it\(args = \{\}\) \{\nreturn args\.n \* 2;\n\n\}$/);
  const AsyncFunction = Object.getPrototypeOf(async () => {}).constructor;
  assert.equal(await new AsyncFunction(script.input.code)(), 42);
  // The gate for what a saved tool may call is the same hook, unchanged.
  assert.equal(f.call('mcp__fm_live__fm_set_tactic').block, true);
  assert.equal(f.call('bash').block, true);
});

test('rejects generic tools and other MCP servers even when marked read-only', () => {
  const f = fixture();
  for (const name of ['bash', 'read', 'write', 'edit', 'codemode_other', 'tool_search_other', 'computer', 'mcp__other__read', 'fm_report_other']) {
    f.tools.push({ name, annotations: { readOnlyHint: true } });
    assert.equal(f.call(name).block, true, name);
  }
});


test('permits the registered tool_search, which only declares deferred reader schemas', () => {
  const f = fixture();
  assert.ok(f.tools.some(tool => tool.name === 'tool_search'));
  assert.equal(f.call('tool_search'), undefined);
  f.tools.splice(f.tools.findIndex(tool => tool.name === 'tool_search'), 1);
  assert.equal(f.call('tool_search').block, true);
});

test('the read-only gate is unchanged for deferred reader tools found through tool_search', () => {
  const f = fixture();
  const name = 'mcp__fm_live__fm_get_retained_shot_map';
  assert.equal(f.call(name).block, true);
  f.tools.push({ name, annotations: { readOnlyHint: true } });
  assert.equal(f.call(name), undefined);
  f.tools.find(tool => tool.name === name).annotations.readOnlyHint = false;
  assert.equal(f.call(name).block, true);
});

test('registers fm_report and permits only that exact registered name', () => {
  const f = fixture();
  const tool = f.tools.find(tool => tool.name === 'fm_report');
  assert.ok(tool);
  assert.equal(f.call('fm_report'), undefined);
  assert.equal(f.call('fm_report_other').block, true);
  f.tools.splice(f.tools.indexOf(tool), 1);
  assert.equal(f.call('fm_report').block, true);
});

test('registers standalone tactic authoring while retaining the game read-only boundary', () => {
  const f = fixture();
  const tool = f.tools.find(tool => tool.name === 'fm_tactic_file');
  assert.ok(tool);
  assert.equal(f.call('fm_tactic_file'), undefined);
  assert.deepEqual(tool.parameters.properties.action.enum, ['list_templates', 'inspect', 'authoring_catalog', 'generate', 'schema']);
  assert.equal(tool.parameters.additionalProperties, false);
  assert.match(tool.description, /both full eleven-position layouts/);
  assert.match(tool.parameters.properties.native_authoring.properties.positions.description, /Omitted phases inherit/);
  assert.equal(f.call('fm_tactic_file_other').block, true);
});


test('permits only the exact registered host recorder exception, including nested dispatch', () => {
  const f = fixture();
  const name = 'mcp__fm_live__fm_record_current_match';
  assert.equal(f.call(name).block, true);
  f.tools.push({ name, annotations: { readOnlyHint: false } });
  assert.equal(f.call(name), undefined);
  // Nested Code Mode calls use this same hook, rather than bypassing it.
  assert.equal(f.handlers.get('tool_call')({ toolName: name, input: { session_id: 's' } }), undefined);
  delete f.tools.find(t => t.name === name).annotations;
  assert.equal(f.call(name).block, true);
  f.tools.length = 0;
  for (const other of [
    'mcp__fm_live__fm_record_current_match_extra',
    'mcp__fm_live__fm_record_current_match_delete',
    'mcp__fm_live__fm_set_tactic',
    'mcp__fm_live__fm_write_save',
    'mcp__other__fm_record_current_match',
  ]) {
    f.tools.push({ name: other, annotations: { readOnlyHint: false } });
    assert.equal(f.call(other).block, true, other);
  }
});
