import assert from 'node:assert/strict';
import test from 'node:test';

import { ActivityLog, describeCall, describeTool, registerActivityDisplay, summarize } from '../pi/fm-activity.mjs';

const theme = { fg: (_color, text) => text };
const tick = () => new Promise(resolve => setImmediate(resolve));

function harness() {
  const handlers = new Map();
  let resolver;
  const working = [];
  const pi = {
    registerToolRenderer: fn => { resolver = fn; },
    on: (event, handler) => handlers.set(event, handler),
  };
  const { log, rebuild } = registerActivityDisplay(pi);
  const redraws = [];
  const ctx = { hasUI: true, ui: { setWorkingMessage: message => working.push(message) } };
  const renderers = name => resolver(name, () => undefined);
  const context = (id, extra = {}) => ({ toolCallId: id, outputPad: 1, expanded: false, isError: false, invalidate: () => redraws.push(id), ...extra });
  const draw = (name, id, args, extra) => renderers(name).renderCall(args, theme, context(id, extra)).render(80);
  return { handlers, log, rebuild, ctx, working, redraws, renderers, context, draw };
}

const assistant = (...content) => ({ role: 'assistant', content });
const call = (id, name, args = {}) => ({ type: 'toolCall', id, name, arguments: args });
const text = value => ({ type: 'text', text: value });

test('names FM reader tools as plain activities', () => {
  assert.deepEqual(describeTool('mcp__fm_live__fm_get_managed_squad'), { verb: 'read', object: 'your squad' });
  assert.deepEqual(describeTool('mcp__fm_live__fm_find_save_players'), { verb: 'search', object: 'players in the saved career' });
  assert.deepEqual(describeTool('mcp__fm_live__fm_attach'), { verb: 'connect', object: 'your running career' });
  assert.deepEqual(describeTool('fm_tactic_file', { action: 'generate' }), { verb: 'write', object: 'your tactic file' });
  assert.deepEqual(describeTool('mcp__fm_live__fm_compare_team_league_performance'), { verb: 'compare', object: 'team performance against the league' });
});

test('does not claim that calls mentioned in script source actually ran', () => {
  const code = '// tools.mcp__fm_live__fm_get_player_bans({})\nif(false) await tools.mcp__fm_live__fm_get_managed_squad({});';
  assert.deepEqual(describeCall('codemode', { code }), [{ verb: 'analyse', object: 'the available evidence' }]);
});

test('summarises a run by verb, in present tense while running and past tense when done', () => {
  const parts = [
    { verb: 'connect', object: 'FM' }, { verb: 'read', object: 'save' }, { verb: 'read', object: 'squad' },
    { verb: 'search', object: 'players' }, { verb: 'read', object: 'squad' },
  ];
  assert.equal(summarize(parts, { done: false }), 'Connecting to FM · reading save and squad · searching players');
  assert.equal(summarize(parts, { done: true }), 'Connected to FM · read save and squad · searched players');
  const many = ['a', 'b', 'c', 'd', 'e', 'f'].map(object => ({ verb: 'read', object }));
  assert.equal(summarize(many, { done: true }), 'Read a, b, c, d and 2 more');
});

test('groups consecutive calls until visible text or another message', () => {
  const log = new ActivityLog();
  log.rebuild([
    { role: 'user', content: 'How is the squad?' },
    assistant({ type: 'thinking', thinking: 'plan' }, call('a', 'codemode')),
    { role: 'toolResult', toolCallId: 'a', isError: false },
    assistant(text('  '), call('b', 'codemode')),
    { role: 'toolResult', toolCallId: 'b', isError: true },
    assistant(text('First look done.'), call('c', 'codemode')),
    { role: 'user', content: 'and?' },
    assistant(call('d', 'codemode')),
  ]);
  assert.deepEqual(log.groupOf.get('a').ids, ['a', 'b']);
  assert.deepEqual(log.groupOf.get('c').ids, ['c']);
  assert.deepEqual(log.groupOf.get('d').ids, ['d']);
  assert.equal(log.isLast('a'), false);
  assert.equal(log.isLast('b'), true);
  assert.equal(log.line('b').failed, 1);
  assert.equal(log.line('d').done, true);
});

test('accepts the same streaming message repeatedly without regrouping', () => {
  const log = new ActivityLog();
  log.ingest(assistant(call('a', 'codemode')));
  log.ingest(assistant(text('Checking.')));
  log.ingest(assistant(text('Checking.'), call('b', 'codemode')));
  log.ingest(assistant(text('Checking.'), call('b', 'codemode'), call('c', 'codemode')));
  assert.deepEqual(log.groupOf.get('a').ids, ['a']);
  assert.deepEqual(log.groupOf.get('b').ids, ['b', 'c']);
  log.ingest(assistant(call('d', 'codemode')));
  assert.deepEqual(log.groupOf.get('b').ids, ['b', 'c', 'd']);
});

test('draws only the newest row and updates an already-created component', async () => {
  const h = harness();
  const old = h.renderers('codemode').renderCall({}, theme, h.context('a'));
  h.handlers.get('tool_execution_end')({ toolCallId: 'a', toolName: 'codemode', isError: false });
  const row = h.renderers('mcp__fm_live__fm_get_managed_squad').renderCall({}, theme, h.context('b'));
  assert.deepEqual(old.render(80), []);
  assert.deepEqual(row.render(80)[0], ' • Reading your squad');
  h.handlers.get('tool_execution_end')({ toolCallId: 'b', toolName: 'mcp__fm_live__fm_get_managed_squad', isError: true });
  await tick();
  assert.ok(h.redraws.includes('a') && h.redraws.includes('b'));
  assert.equal(row.render(80)[0], ' • Could not read your squad');
  // A later render callback must not erase the observed failure.
  h.renderers('mcp__fm_live__fm_get_managed_squad').renderResult({ content: [] }, { isPartial: false }, theme, h.context('b'));
  assert.equal(h.log.line('b').failed, 1);
});

test('fits narrow terminals, including failed rows and tiny widths', () => {
  const h = harness();
  const row = h.renderers('mcp__fm_live__fm_get_ui_screen').renderCall({ screen: 'team_analytics', chart: 'possession gained across the whole season' }, theme, h.context('w'));
  for (const width of [0, 1, 2, 3, 8, 30, 80]) {
    const lines = row.render(width);
    assert.ok(lines.length <= 2);
    assert.ok(lines.every(line => line.length <= width), JSON.stringify(lines));
  }
});

test('Ctrl+O expansion shows every call with its script and output', () => {
  const h = harness();
  h.draw('codemode', 'a', { code: 'return 1' });
  h.draw('codemode', 'b', { code: 'return 2' });
  const expanded = { expanded: true };
  assert.deepEqual(h.draw('codemode', 'a', { code: 'return 1' }, expanded), [' codemode', ' return 1']);
  const result = h.renderers('codemode').renderResult({ content: [{ type: 'text', text: 'Script completed\n2' }] }, { expanded: true, isPartial: false }, theme, h.context('b', expanded));
  assert.deepEqual(result.render(80), [' Script completed', ' 2']);
});

test('resumed sessions regroup history and redraw rows already on screen', async () => {
  const h = harness();
  h.draw('codemode', 'a', {});
  h.draw('codemode', 'b', {});
  const branch = [
    { type: 'message', message: assistant(call('a', 'codemode')) },
    { type: 'message', message: assistant(text('Here is the squad.')) },
    { type: 'model_change' },
    { type: 'message', message: assistant(call('b', 'codemode')) },
  ];
  h.rebuild({ sessionManager: { getBranch: () => branch } });
  await tick();
  assert.ok(h.redraws.includes('a') && h.redraws.includes('b'));
  assert.equal(h.log.isLast('a'), true);
  assert.equal(h.log.isLast('b'), true);
});

test('the working indicator names the FM read in progress inside a script', () => {
  const h = harness();
  h.handlers.get('tool_execution_start')({ toolCallId: 'a', toolName: 'codemode', args: {} }, h.ctx);
  h.handlers.get('tool_execution_start')({ toolCallId: 'n', toolName: 'mcp__fm_live__fm_get_club_finances', args: {}, parentToolCallId: 'a' }, h.ctx);
  h.handlers.get('agent_end')({}, h.ctx);
  assert.deepEqual(h.working, ['Working through the available evidence…', 'Reading club finances…', undefined]);
});

const fm = name => `mcp__fm_live__fm_${name}`;
const result = data => ({ content: [{ type: 'text', text: JSON.stringify(data) }] });
const start = (h, id, name, args = {}, parent) => h.handlers.get('tool_execution_start')({ toolCallId: id, toolName: name, args, parentToolCallId: parent }, h.ctx);
const finish = (h, id, name, data = {}, isError = false) => h.handlers.get('tool_execution_end')({ toolCallId: id, toolName: name, result: result(data), isError }, h.ctx);

test('names the queried football evidence without exposing SQL or internal references', () => {
  assert.equal(describeTool(fm('db_query'), { sql: 'SELECT p.name, c.weekly_wage FROM m_player_view p JOIN m_contract_view c ON c.person_idx=p.idx' }).object, 'player profiles alongside contracts and wages');
  assert.equal(describeTool(fm('db_query'), { sql: "SELECT 'FROM club_debt_loan --x' AS name FROM promise /* JOIN match_shot */" }).object, 'player promises');
  assert.equal(describeTool(fm('db_query'), { sql: 'WITH p AS (SELECT * FROM "player_view") SELECT * FROM p JOIN `match_player_stats` m ON true' }).object, 'player profiles and individual match performances');
  assert.equal(describeTool(fm('db_query'), { sql: 'SELECT 1' }).object, 'career data');
  assert.equal(describeTool(fm('db_read'), { table: 'person', idx: [1234] }).object, 'player and staff records directly in FM');
  assert.equal(describeTool(fm('db_schema'), { table: 'match_rating_component' }).object, 'available fields for the components behind player ratings');
});

test('distinguishes screen reads, guidance, previews, writes and saved calculations', () => {
  assert.equal(describeTool(fm('get_ui_screen'), { screen: 'tactics' }).object, 'the tactics screen');
  assert.equal(describeTool(fm('get_ui_screen'), { screen: 'team_analytics', chart: 'possession gained' }).object, 'team Data Hub charts: possession gained');
  assert.equal(describeTool('fm_read_skill', { id: 'fm-recruitment' }).object, 'the recruitment guide');
  assert.equal(describeTool('fm_tactic_file', { action: 'generate', preview: true }).verb, 'check');
  assert.equal(describeTool('fm_tactic_file', { action: 'generate' }).verb, 'write');
  assert.equal(describeTool('fm_tactic_file', { action: 'inspect' }).verb, 'read');
  assert.equal(describeTool('fm_toolbox', { action: 'edit', name: 'squad_capacity' }).verb, 'update');
  assert.equal(describeTool('fm_toolbox', { action: 'read', name: 'squad_capacity' }).verb, 'read');
  assert.equal(describeTool('tool_search').object, 'the available FM data sources');
  assert.equal(describeTool('fm_report').verb, 'build');
});

test('strips control sequences and bounds dynamic labels', () => {
  const description = describeTool(fm('get_ui_screen'), { screen: 'team_analytics', chart: '\x1b[31mPossession\n\u202egained\x1b[0m' });
  assert.equal(description.object, 'team Data Hub charts: Possession gained');
  assert.ok(describeTool('fm_toolbox', { name: 'x'.repeat(200) }).object.length < 100);
});

test('uses actual nested arguments, tracks concurrent reads, then moves to synthesis', () => {
  const h = harness();
  start(h, 'a', 'codemode', { code: 'if(false) await tools.mcp__fm_live__fm_get_player_bans({});' });
  start(h, 'a/1', fm('db_query'), { sql: 'SELECT * FROM m_promise', view: 'manager' }, 'a');
  start(h, 'a/2', fm('get_ui_screen'), { screen: 'tactics' }, 'a');
  assert.match(h.log.line('a').text, /Reading the tactics screen · 1 other check running/);
  finish(h, 'a/2', fm('get_ui_screen'));
  assert.equal(h.working.at(-1), 'Reading player promises · using your manager’s knowledge…');
  finish(h, 'a/1', fm('db_query'), { rows: [{ promise: 1 }], truncated: false });
  finish(h, 'a', 'codemode');
  assert.equal(h.working.at(-1), 'Weighing the evidence for your answer…');
  assert.doesNotMatch(h.log.line('a').text, /bans|suspensions/);
  assert.match(h.log.line('a').text, /tactics screen and player promises/);
  assert.equal(h.log.line('a').done, true);
  h.handlers.get('message_update')({ message: assistant(text('Answer')), assistantMessageEvent: { type: 'text_delta' } }, h.ctx);
  assert.equal(h.working.at(-1), 'Writing your answer…');
  h.handlers.get('agent_end')({}, h.ctx);
  assert.equal(h.working.at(-1), undefined);
});

test('keeps failures visible even when the enclosing script succeeds', () => {
  const h = harness();
  start(h, 'a', 'codemode');
  start(h, 'a/1', fm('get_managed_squad'), {}, 'a');
  finish(h, 'a/1', fm('get_managed_squad'));
  start(h, 'a/2', fm('get_player_bans'), {}, 'a');
  finish(h, 'a/2', fm('get_player_bans'), {}, true);
  finish(h, 'a', 'codemode');
  assert.equal(h.log.line('a').text, 'Could not check player suspensions');
  assert.equal(h.log.line('a').detail, 'Read your squad');
  assert.equal(h.log.line('a').failed, 1);
  assert.equal(h.working.at(-1), 'Reviewing the available evidence and gaps…');
});

test('restores recorded nested calls rather than guessing from source', () => {
  const log = new ActivityLog();
  log.rebuild([
    assistant(call('a', 'codemode', { code: 'await tools.mcp__fm_live__fm_get_player_bans({})' })),
    { role: 'toolResult', toolCallId: 'a', isError: false, nestedCalls: { complete: false, calls: [
      { id: 'a/1', name: fm('db_query'), arguments: { sql: 'SELECT * FROM match_rating_component', view: 'manager' }, status: 'ok' },
      { id: 'a/2', name: fm('get_managed_squad'), arguments: {}, status: 'error' },
    ] } },
  ]);
  assert.equal(log.line('a').text, 'Could not read your squad');
  assert.match(log.line('a').detail, /Read the components behind player ratings/);
  assert.match(log.line('a').detail, /Some earlier checks are unavailable/);
  assert.doesNotMatch(log.line('a').text, /suspensions/);
});

test('distinguishes empty, truncated and failed results without calling rows players', () => {
  for (const [data, note, failed] of [
    [{ rows: [] }, 'No matching results', 0],
    [{ rows: [{ total: 28 }] }, '1 result returned', 0],
    [{ rows: [{}, {}], truncated: true }, '2 results returned · more available', 0],
    [{ ok: false, error: 'No reader' }, '', 1],
  ]) {
    const h = harness();
    start(h, 'a', fm('db_query'), { sql: 'SELECT * FROM player_view', view: 'manager' });
    finish(h, 'a', fm('db_query'), data);
    const line = h.log.line('a');
    assert.equal(line.failed, failed);
    if (!failed) assert.equal(line.detail, `${note} · Using your manager’s knowledge`);
    else assert.equal(line.text, 'Could not read player profiles');
  }
});

test('stops unfinished checks on cancellation and clears state for the next turn', () => {
  const h = harness();
  start(h, 'a', 'codemode');
  start(h, 'a/1', fm('get_managed_squad'), {}, 'a');
  h.handlers.get('agent_end')({}, h.ctx);
  assert.equal(h.log.line('a').text, 'Stopped while reading your squad');
  assert.equal(h.log.line('a').done, true);
  assert.equal(h.working.at(-1), undefined);
  h.handlers.get('agent_start')({}, h.ctx);
  start(h, 'b', fm('get_match'));
  finish(h, 'b', fm('get_match'));
  assert.equal(h.working.at(-1), 'Weighing the evidence for your answer…');
});

test('does not keep redrawing an unchanged completed result', async () => {
  const h = harness();
  h.draw(fm('db_query'), 'a', { sql: 'SELECT * FROM player_view' });
  const payload = result({ rows: [{}] });
  const render = () => h.renderers(fm('db_query')).renderResult(payload, { isPartial: false }, theme, h.context('a'));
  render();
  await tick();
  const before = h.redraws.length;
  render();
  await tick();
  assert.equal(h.redraws.length, before);
});

test('does not apply the latest query count or knowledge scope to the whole group', () => {
  const h = harness();
  start(h, 'a', fm('db_query'), { sql: 'SELECT * FROM m_player_view', view: 'manager' });
  finish(h, 'a', fm('db_query'), { rows: [{}, {}, {}] });
  start(h, 'b', fm('db_query'), { sql: 'SELECT * FROM match_rating_component', view: 'full' });
  finish(h, 'b', fm('db_query'), { rows: [{}] });
  assert.equal(h.log.line('b').detail, 'Latest check: 1 result returned · Using full career data');
});

test('unfinished history is interrupted, and deeply nested failures are counted once', () => {
  const log = new ActivityLog();
  log.rebuild([assistant(call('old', fm('get_managed_squad')))]);
  assert.equal(log.line('old').text, 'Stopped while reading your squad');
  log.rebuild([
    assistant(call('a', 'codemode')),
    { role: 'toolResult', toolCallId: 'a', isError: true, nestedCalls: { complete: true, calls: [
      { id: 'a/1', name: 'codemode', status: 'error' },
      { id: 'a/1/1', name: fm('get_managed_squad'), status: 'error' },
    ] } },
  ]);
  assert.equal(log.line('a').failed, 1);
  assert.equal(log.line('a').text, 'Could not read your squad');
});
