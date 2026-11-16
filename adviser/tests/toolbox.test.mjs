import assert from 'node:assert/strict';
import { existsSync, mkdtempSync, readdirSync, readFileSync, rmSync, symlinkSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import test from 'node:test';

import {
  describe, MAX_CODE_CHARS, promptListing, registerToolboxTool, Toolbox, toolboxDirectory, TOOLBOX_TOOL, withToolbox,
} from '../pi/fm-toolbox.mjs';

const AsyncFunction = Object.getPrototypeOf(async () => {}).constructor;

function scratch(t) {
  const dir = mkdtempSync(join(tmpdir(), 'pi-fm-toolbox-'));
  t.after(() => rmSync(dir, { recursive: true, force: true }));
  let tick = 0;
  return new Toolbox({ dir: join(dir, 'toolbox'), now: () => new Date(Date.UTC(2026, 10, 13, 11, 0, tick++)) });
}

/** Run a script the way Code Mode does: as the body of an async function with `tools` in scope. */
function run(code, tools = {}) {
  const output = [];
  return new AsyncFunction('tools', 'text', code)(tools, value => output.push(value)).then(value => ({ value, output }));
}

test('the store is outside the checkout unless PI_FM_TOOLBOX_DIR names another directory', () => {
  assert.equal(toolboxDirectory({ PI_FM_TOOLBOX_DIR: '/x/y' }), '/x/y');
  const fallback = toolboxDirectory({});
  assert.match(fallback, /\/\.pi\/agent\/pi-fm-toolbox$/);
  assert.ok(!fallback.startsWith(new URL('../', import.meta.url).pathname));
});

test('saves a tool as one readable file and lists, reads and removes it', t => {
  const box = scratch(t);
  assert.deepEqual(box.all(), []);
  const saved = box.save({
    name: 'squad_capacity', description: 'Minutes each position group needs against\n  what the squad can supply.',
    args: '{ availability = 0.85 }', returns: 'one row per position group',
    code: 'const { availability = 0.85 } = args;\nreturn { availability };\n\n', game_date: '2031-01-04',
  });
  assert.equal(saved.revision, 1);
  assert.equal(saved.path, join(box.dir, 'squad_capacity.js'));
  assert.equal(saved.description, 'Minutes each position group needs against what the squad can supply.');
  const file = readFileSync(saved.path, 'utf8');
  assert.match(file, /^\/\/ pi-fm saved tool\./);
  assert.ok(file.endsWith('const { availability = 0.85 } = args;\nreturn { availability };\n'));
  const [listed] = box.all();
  assert.equal(listed.game_date, '2031-01-04');
  assert.equal(listed.saved_at, '2026-11-13T11:00:00.000Z');
  assert.equal(box.get('squad_capacity').code, 'const { availability = 0.85 } = args;\nreturn { availability };\n');
  const removed = box.remove('squad_capacity');
  assert.deepEqual(box.all(), []);
  assert.ok(existsSync(removed.kept_at), 'a removed tool is kept in history');
  assert.throws(() => box.get('squad_capacity'), /No saved tool "squad_capacity"\. Saved tools: \(none\)\./);
});

test('refuses to overwrite without replace, and keeps the earlier revision when replacing', t => {
  const box = scratch(t);
  box.save({ name: 'depth', description: 'First.', code: 'return 1;' });
  assert.throws(() => box.save({ name: 'depth', description: 'Second.', code: 'return 2;' }),
    /"depth" is already saved \(revision 1: First\.\)\. Pass replace: true/);
  assert.equal(box.get('depth').code, 'return 1;\n');
  const second = box.save({ name: 'depth', description: 'Second.', code: 'return 2;', replace: true });
  assert.equal(second.revision, 2);
  assert.equal(second.replaced_revision, 1);
  assert.equal(box.get('depth').code, 'return 2;\n');
  const history = readdirSync(join(box.dir, 'history'));
  assert.equal(history.length, 1);
  assert.match(history[0], /^depth\.r1\..*\.js$/);
  assert.match(readFileSync(join(box.dir, 'history', history[0]), 'utf8'), /return 1;/);
  assert.deepEqual(readdirSync(box.dir).sort(), ['depth.js', 'history']);
});

test('edits a saved tool by exact replacement, all or nothing, keeping its description', t => {
  const box = scratch(t);
  box.save({ name: 'depth', description: 'Depth by position.', args: '{ limit = 2 }', code: 'const limit = args.limit ?? 2;\nconst cost = "$1";\nreturn limit;' });
  const edited = box.edit({ name: 'depth', edits: [
    { old: 'args.limit ?? 2', new: 'args.limit ?? 3' },
    { old: 'return limit;', new: 'return { limit, cost: "$&" };' },
  ] });
  assert.equal(edited.revision, 2);
  assert.equal(edited.description, 'Depth by position.');
  assert.equal(edited.args, '{ limit = 2 }');
  // Replacement text is literal: "$&" and "$1" are not patterns.
  assert.equal(box.get('depth').code, 'const limit = args.limit ?? 3;\nconst cost = "$1";\nreturn { limit, cost: "$&" };\n');
  assert.throws(() => box.edit({ name: 'depth', edits: [{ old: 'limit', new: 'cap' }] }), /edits\[0\]\.old occurs 3 times in "depth"; it must occur exactly once\. Include more of the surrounding code\. Nothing was changed\./);
  assert.throws(() => box.edit({ name: 'depth', edits: [{ old: 'args.limit ?? 3', new: 'args.limit ?? 4' }, { old: 'no such text', new: 'x' }] }), /edits\[1\]\.old occurs 0 times[\s\S]*Copy the exact text from fm_toolbox\(action: "read"\)/);
  assert.throws(() => box.edit({ name: 'depth', edits: [{ old: 'return {', new: 'return {{' }] }), /does not parse/);
  assert.throws(() => box.edit({ name: 'depth', edits: [] }), /Give edits/);
  assert.throws(() => box.edit({ name: 'missing_tool', edits: [{ old: 'a', new: 'b' }] }), /No saved tool "missing_tool"/);
  assert.equal(box.get('depth').revision, 2, 'a refused edit saves nothing');
  assert.equal(box.edit({ name: 'depth', description: 'Depth, capped.', edits: [{ old: '?? 3', new: '?? 4' }] }).description, 'Depth, capped.');
  // A replacing save also keeps what it is not given.
  assert.equal(box.save({ name: 'depth', code: 'return 1;', replace: true }).args, '{ limit = 2 }');
});

test('rejects names that could leave the directory, missing descriptions and code that does not parse', t => {
  const box = scratch(t);
  for (const name of ['', 'ab', 'A_tool', '../escape', 'a/b', 'a.b', '1abc', 'x'.repeat(49), 'history/x', undefined, 7]) {
    assert.throws(() => box.save({ name, description: 'd', code: 'return 1;' }), /Name the tool with/, String(name));
  }
  assert.throws(() => box.save({ name: 'tool', code: 'return 1;' }), /Give the tool a description/);
  assert.throws(() => box.save({ name: 'tool', description: 'x'.repeat(401), code: 'return 1;' }), /limited to 400 characters/);
  assert.throws(() => box.save({ name: 'tool', description: 'd' }), /Give the tool its code/);
  assert.throws(() => box.save({ name: 'tool', description: 'd', code: 'return (1;' }), /does not parse as the body of an async function/);
  assert.throws(() => box.save({ name: 'tool', description: 'd', code: '}; tools.x(); async () => {' }), /does not parse/);
  assert.throws(() => box.save({ name: 'tool', description: 'd', code: 'x'.repeat(MAX_CODE_CHARS + 1) }), /limited to 65536 characters/);
  assert.equal(existsSync(box.dir), false, 'a refused save writes nothing');
  // Parsing never runs the code.
  box.save({ name: 'tool', description: 'd', code: 'throw new Error("ran at save time");' });
});

test('ignores files that are not saved tools, including symlinks and edited headers that no longer match', t => {
  const box = scratch(t);
  box.save({ name: 'real_tool', description: 'Real.', code: 'return 1;' });
  writeFileSync(join(box.dir, 'notes.txt'), 'x');
  writeFileSync(join(box.dir, 'broken.js'), 'return 1;');
  writeFileSync(join(box.dir, 'renamed.js'), readFileSync(join(box.dir, 'real_tool.js'), 'utf8'));
  symlinkSync(join(box.dir, 'real_tool.js'), join(box.dir, 'linked.js'));
  assert.deepEqual(box.all().map(tool => tool.name), ['real_tool']);
});

test('a script that names a saved tool gets it, with arguments, defaults and return values', async t => {
  const box = scratch(t);
  box.save({ name: 'per_90', description: 'Per 90.', code: 'const { value, minutes = 90 } = args;\nreturn value * 90 / minutes;' });
  const script = 'const a = await toolbox.per_90({ value: 3, minutes: 270 });\nreturn a + await toolbox["per_90"]({ value: 2 });';
  const expanded = withToolbox(script, box.all());
  assert.notEqual(expanded, script);
  assert.deepEqual((await run(expanded)).value, 3);
  // The script's own lines keep their numbers: the object joins line 1, the functions follow the last line.
  assert.equal(expanded.split('\n')[1], script.split('\n')[1]);
  assert.ok(expanded.split('\n')[0].endsWith(script.split('\n')[0]));
});

test('saved tools reach reader tools through the script and may call each other', async t => {
  const box = scratch(t);
  box.save({ name: 'squad_rows', description: 'Squad.', code: 'const r = await tools.mcp__fm_live__fm_db_query({ sql: "SELECT 1" });\nreturn r.rows;' });
  box.save({ name: 'squad_size', description: 'Size.', code: 'return (await toolbox.squad_rows()).length;' });
  box.save({ name: 'unused', description: 'Unused.', code: 'return "unused";' });
  const calls = [];
  const tools = { mcp__fm_live__fm_db_query: async input => { calls.push(input); return { rows: [[1], [2], [3]] }; } };
  const expanded = withToolbox('return await toolbox.squad_size();', box.all());
  assert.equal((await run(expanded, tools)).value, 3);
  assert.deepEqual(calls, [{ sql: 'SELECT 1' }]);
  assert.match(expanded, /__toolbox_squad_rows/);
  assert.doesNotMatch(expanded, /__toolbox_unused/, 'only the tools a script names, and the tools those name, are added');
});

test('an unknown name fails with the saved names, and a failing tool says which tool failed', async t => {
  const box = scratch(t);
  box.save({ name: 'fails', description: 'Fails.', code: 'throw new Error("no fixtures");' });
  box.save({ name: 'outer', description: 'Outer.', code: 'return await toolbox.fails();' });
  await assert.rejects(run(withToolbox('return await toolbox.missing_tool();', box.all())),
    /No saved tool "missing_tool"\. Saved tools: fails, outer\. Save one with fm_toolbox\./);
  await assert.rejects(run(withToolbox('return await toolbox.outer();', box.all())), /^Error: toolbox\.fails: no fixtures$/);
  await assert.rejects(run(withToolbox('return await toolbox.anything();', [])), /Saved tools: \(none\)/);
});

test('leaves scripts alone when they do not use the toolbox or declare their own', t => {
  const box = scratch(t);
  box.save({ name: 'per_90', description: 'Per 90.', code: 'return 1;' });
  const tools = box.all();
  for (const script of [
    'return await tools.mcp__fm_live__fm_db_query({ sql: "SELECT 1" });',
    'return await tools.fm_toolbox({ action: "list" });',
    'const toolbox = { per_90: () => 2 };\nreturn toolbox.per_90();',
    'const mytoolbox = 1; return mytoolbox;',
    '',
  ]) assert.equal(withToolbox(script, tools), script, script);
  assert.equal(withToolbox(undefined, tools), undefined);
});

test('adds every saved tool when a script picks one by a computed name', async t => {
  const box = scratch(t);
  box.save({ name: 'one', description: 'One.', code: 'return 1;' });
  box.save({ name: 'two', description: 'Two.', code: 'return 2;' });
  const expanded = withToolbox('let total = 0;\nfor (const name of ["one", "two"]) total += await toolbox[name]();\nreturn total;', box.all());
  assert.equal((await run(expanded)).value, 3);
});

test('keeps a Code Mode options line first', async t => {
  const box = scratch(t);
  box.save({ name: 'one', description: 'One.', code: '// a comment on the last line' });
  const expanded = withToolbox('// @options: {"timeout_ms": 60000}\nreturn (await toolbox.one()) ?? "nothing";', box.all());
  assert.equal(expanded.split('\n')[0], '// @options: {"timeout_ms": 60000}');
  assert.equal((await run(expanded)).value, 'nothing');
  const only = withToolbox('// @options: {"timeout_ms": 1} toolbox', box.all());
  assert.equal(only.split('\n')[0], '// @options: {"timeout_ms": 1} toolbox');
});

test('lists saved tools for the prompt and shortens the list when it outgrows its budget', () => {
  assert.equal(promptListing([]), 'No tools saved yet.');
  const tool = { name: 'squad_capacity', description: 'Capacity by position. Second sentence.', args: '{ availability = 0.85 }', returns: 'rows' };
  assert.equal(describe(tool), '- `toolbox.squad_capacity(args)` — Capacity by position. Second sentence. Args: { availability = 0.85 } Returns: rows');
  assert.equal(promptListing([tool]), `Saved tools (1):\n${describe(tool)}`);
  const many = Array.from({ length: 60 }, (_, i) => ({ ...tool, name: `tool_${String(i).padStart(2, '0')}` }));
  const listing = promptListing(many, { budget: 1500 });
  assert.ok(listing.length < 1700);
  assert.match(listing, /^Saved tools \(60\):\n- `toolbox\.tool_00\(args\)` — Capacity by position\.\n/);
  assert.match(listing, /\d+ more, and every tool's arguments: `fm_toolbox\(action: "list"\)`\.$/);
});

test('the registered tool saves, lists, reads and removes, and reports refusals as tool errors', async t => {
  const box = scratch(t);
  const registered = [];
  registerToolboxTool({ registerTool: tool => registered.push(tool) }, { toolbox: box, gameDate: () => '2031-01-04' });
  const [tool] = registered;
  assert.equal(tool.name, TOOLBOX_TOOL);
  assert.deepEqual(tool.parameters.properties.action.enum, ['save', 'edit', 'list', 'read', 'remove']);
  assert.equal(tool.parameters.additionalProperties, false);
  const call = async params => { const result = await tool.execute('id', params); return { ...result, json: result.isError ? null : JSON.parse(result.content[0].text) }; };
  const saved = await call({ action: 'save', name: 'per_90', description: 'Per 90.', code: 'return args.value;' });
  assert.equal(saved.json.revision, 1);
  assert.equal(saved.json.game_date, '2031-01-04');
  assert.equal(saved.json.call, 'await toolbox.per_90({ ... })');
  const again = await call({ action: 'save', name: 'per_90', description: 'Per 90.', code: 'return args.value;' });
  assert.equal(again.isError, true);
  assert.match(again.content[0].text, /already saved/);
  const listed = await call({ action: 'list' });
  assert.equal(listed.json.count, 1);
  assert.equal(listed.json.tools[0].name, 'per_90');
  assert.equal(listed.json.tools[0].code, undefined);
  assert.equal((await call({ action: 'read', name: 'per_90' })).json.code, 'return args.value;\n');
  const edited = await call({ action: 'edit', name: 'per_90', edits: [{ old: 'args.value', new: 'args.value * 90 / (args.minutes ?? 90)' }] });
  assert.equal(edited.json.revision, 2);
  assert.equal(edited.json.edits_applied, 1);
  assert.equal(edited.json.description, 'Per 90.');
  assert.equal((await call({ action: 'read', name: 'per_90' })).json.code, 'return args.value * 90 / (args.minutes ?? 90);\n');
  assert.equal((await call({ action: 'remove', name: 'per_90' })).json.removed_revision, 2);
  assert.equal((await call({ action: 'read', name: 'per_90' })).isError, true);
  assert.match((await call({ action: 'run', name: 'per_90' })).content[0].text, /action must be save, edit, list, read or remove/);
});
