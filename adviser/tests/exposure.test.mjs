import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { mkdtempSync, readFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import test from 'node:test';
import { fileURLToPath } from 'node:url';

import {
  assemblePrompt, COVERAGE_DIRECT, DIRECT_TOOLS, offeredDirectTools, PREFIX, readerExposure, SCREEN_DIRECT, SQL_DIRECT,
  sessionSection, wantsReport, wantsTactic,
} from '../pi/fm-exposure.mjs';
import { appendedPrompt } from '../pi/fm-skills.mjs';

const root = fileURLToPath(new URL('../', import.meta.url));
const system = readFileSync(join(root, 'pi/system.md'), 'utf8');
const prompt = `${system}\n${appendedPrompt()}`;
const tools = names => names.map(name => ({ name }));
const reader = names => tools(names.map(name => PREFIX + name));
const LOCAL = ['codemode', 'tool_search', 'papercut', 'fm_read_skill', 'fm_write_text', 'fm_tactic_file', 'fm_report'];
const SAVE = '- Save: Fixture Career\n- Manager: Test Manager (your club: Fixture United)\n- Game date: 2030-12-13';

test('declares about twelve reader tools: the SQL pair, the fresh read, the asked-for screens and coverage', () => {
  assert.deepEqual([...DIRECT_TOOLS], [...SQL_DIRECT, ...SCREEN_DIRECT, ...COVERAGE_DIRECT]);
  assert.ok(DIRECT_TOOLS.length >= 8 && DIRECT_TOOLS.length <= 13, String(DIRECT_TOOLS.length));
  for (const name of ['fm_db_query', 'fm_db_schema', 'fm_db_read', 'fm_get_board_confidence', 'fm_get_inbox', 'fm_get_calendar',
    'fm_get_squad_happiness', 'fm_get_player_status', 'fm_get_club_vision_progress', 'fm_get_league_table', 'fm_get_match',
    'fm_get_ui_screen', 'fm_coverage']) assert.ok(DIRECT_TOOLS.includes(name), name);
  // Attachment is the harness's job; the refresh, old per-screen and per-player tools are deferred.
  for (const name of ['fm_status', 'fm_attach', 'fm_get_save', 'fm_db_refresh', 'fm_get_club_vision', 'fm_get_club_squads',
    'fm_get_next_match_squad', 'fm_get_managed_tactics', 'fm_get_player_injury_status', 'fm_ui_read',
    'fm_get_manager_visible_attributes', 'fm_get_scouting']) assert.ok(!DIRECT_TOOLS.includes(name), name);
  const exposure = readerExposure();
  assert.equal(exposure.exposure, 'deferred');
  assert.deepEqual(Object.keys(exposure.toolExposure), [...DIRECT_TOOLS]);
  assert.ok(Object.values(exposure.toolExposure).every(value => value === 'direct'));
});

test('filters the direct list by the tools the reader actually offers', () => {
  const offered = [...reader(['fm_status', 'fm_db_query', 'fm_get_inbox', 'fm_get_retained_shot_map']), ...tools(LOCAL),
    // A same-named tool from another namespace does not count as offered by the reader.
    { name: 'mcp__other__fm_db_schema' }];
  assert.deepEqual(offeredDirectTools(offered), ['fm_db_query', 'fm_get_inbox']);
  assert.deepEqual(offeredDirectTools([]), []);
});

test('the prompt carries the attached save and never asks the model to attach', () => {
  const text = assemblePrompt(prompt, [...reader(DIRECT_TOOLS), ...tools(LOCAL)], { save: SAVE, schemaCard: 'CARD-TEXT' });
  assert.doesNotMatch(text, /<!-- fm:/);
  assert.match(text, /- Game date: 2030-12-13/);
  assert.match(text, /never pass `session_id`/);
  assert.doesNotMatch(text, /Start live work with `fm_status`|then `fm_attach`/);
  assert.match(text, /CARD-TEXT/);
  assert.match(text, /# How to answer[\s\S]*The decision first/);
  assert.match(text, /Never ask for screenshots/);
});

test('an attach failure is stated with its exact reason and one fix, never a screenshot request', () => {
  const attachError = { message: 'task_for_pid failed (5)', fix: 'Run `node pi/fm-desktop-reader.mjs install` once.' };
  const text = assemblePrompt(prompt, [...reader(DIRECT_TOOLS), ...tools(LOCAL)], { attachError });
  assert.match(text, /Reader error: task_for_pid failed \(5\)/);
  assert.match(text, /Fix: Run `node pi\/fm-desktop-reader\.mjs install` once\./);
  assert.match(text, /Do not ask for screenshots/);
  assert.equal(sessionSection({}).includes('attach on first use'), true);
});

test('the schema card replaces the schema call; without it the prompt says to call fm_db_schema once', () => {
  const sql = [...reader(DIRECT_TOOLS), ...tools(LOCAL)];
  assert.match(assemblePrompt(prompt, sql, { schemaCard: 'CARD-TEXT' }), /# SQL[\s\S]*CARD-TEXT/);
  assert.match(assemblePrompt(prompt, sql, {}), /call `fm_db_schema` once/);
  const without = assemblePrompt(prompt, [...reader(['fm_get_inbox']), ...tools(LOCAL)], { schemaCard: 'CARD-TEXT' });
  assert.doesNotMatch(without, /# SQL|CARD-TEXT|m_player_view/);
  assert.match(without, /`fm_query_save_players`/);
});

test('reports are offered in text and made only on turns that ask for a file', () => {
  const all = [...reader(DIRECT_TOOLS), ...tools(LOCAL)];
  const asked = assemblePrompt(prompt, all, { reportRequested: true });
  const notAsked = assemblePrompt(prompt, all, { reportRequested: false });
  assert.match(asked, /Call `fm_report` once/);
  assert.match(asked, /the file never replaces the answer/);
  assert.doesNotMatch(notAsked, /Call `fm_report`/);
  assert.match(notAsked, /offering to save it as a report file/);
  for (const q of ['Give me a shortlist report of young left-backs', 'Save this as a file', 'Can you export that?', 'write it up as a document'])
    assert.ok(wantsReport(q), q);
  for (const q of ['Who should I sell to fund a left-back?', 'Give me a shortlist of keepers', 'Who reported injured?'])
    assert.ok(!wantsReport(q), q);
  assert.ok(wantsTactic('Build me a 4-2-3-1 tactic file') && !wantsTactic('Who is unhappy?'));
});

test('offers the SQL manager view only when fm_db_query takes a view argument', () => {
  const db = params => ({ name: `${PREFIX}fm_db_query`, parameters: { type: 'object', properties: params } });
  const plain = assemblePrompt(prompt, [db({ sql: {} })]);
  const viewed = assemblePrompt(prompt, [db({ sql: {}, view: {} })]);
  for (const text of [plain, viewed]) assert.doesNotMatch(text, /<!-- fm:/);
  assert.match(plain, /the deferred `fm_get_manager_visible_attributes`/);
  assert.match(viewed, /`fm_db_query` with `view: "manager"`, where every table is `m_<name>`/);
  // Wages and contract expiry of other clubs' players are public; clauses, money and hidden values are not.
  assert.match(viewed, /another club's player's wage and contract expiry/);
  assert.match(viewed, /Never filter, rank or quote another club's players on ability, an exact hidden attribute, transfer value, position rating or release clause/);
});

test('asking for a chart declares the report tool, the only one that draws', () => {
  for (const text of ['a stacked bar chart per position based on cover quality would be good', 'Plot xG by match', 'can you visualise that', 'show me graphs of form']) {
    assert.equal(wantsReport(text), true, text);
  }
  for (const text of ['who should start at left-back?', 'is the plotting of his runs any good', 'he charted a course']) assert.equal(wantsReport(text), false, text);
});

test('asking to save something as a tool is not a request for a report file', () => {
  for (const text of ['Build a capacity model and save it as a tool', 'save this to your toolbox', 'Save that as a reusable tool for next month']) {
    assert.equal(wantsReport(text), false, text);
  }
  for (const text of ['save it', 'Save this as a report', 'Save it as a tool and write it up as a report', 'build a tool. Then save it for me']) {
    assert.equal(wantsReport(text), true, text);
  }
});

test('the toolbox section appears with fm_toolbox and lists the saved tools', () => {
  const all = [...reader(DIRECT_TOOLS), ...tools([...LOCAL, 'fm_toolbox'])];
  const empty = assemblePrompt(prompt, all);
  assert.match(empty, /# Your toolbox\n\nYou build tools for yourself\./);
  assert.match(empty, /A description of a method is not a reusable model/);
  assert.match(empty, /correct it with `action: "edit"`/);
  assert.match(empty, /No tools saved yet\./);
  const listed = assemblePrompt(prompt, all, { toolbox: 'Saved tools (1):\n- `toolbox.squad_capacity(args)` — Capacity.' });
  assert.match(listed, /They cannot change it\.\n\nSaved tools \(1\):\n- `toolbox\.squad_capacity\(args\)` — Capacity\.\n\n# SQL/);
  assert.doesNotMatch(listed, /<!-- fm:/);
  // Without the tool the adviser is not told about a toolbox it cannot use.
  assert.doesNotMatch(assemblePrompt(prompt, [...reader(DIRECT_TOOLS), ...tools(LOCAL)]), /toolbox/);
});

test('conditions combine terms, negations and session flags', () => {
  const text = '<!-- fm:if a !b -->AB\n<!-- fm:end --><!-- fm:if a.p -->P\n<!-- fm:end --><!-- fm:if report_requested -->R\n<!-- fm:end -->';
  assert.equal(assemblePrompt(text, [{ name: 'a' }]), 'AB\n');
  assert.equal(assemblePrompt(text, [{ name: 'a' }, { name: 'b' }]), '');
  assert.equal(assemblePrompt(text, [{ name: 'a', parameters: { properties: { p: {} } } }]), 'AB\nP\n');
  assert.equal(assemblePrompt(text, [{ name: 'a' }], { reportRequested: true }), 'AB\nR\n');
  assert.equal(assemblePrompt('no markers', []), 'no markers');
});

test('the always-loaded guide stays under 2,500 tokens', () => {
  assert.ok(appendedPrompt().length / 4 < 2500, `${appendedPrompt().length} characters`);
});

function runFixture(readerTools, { prompt: question = 'Show the shot map', env = {} } = {}) {
  const directory = mkdtempSync(join(tmpdir(), 'pi-fm-exposure-'));
  try {
    const result = spawnSync(join(root, 'bin/pi-fm'), [
      '--no-session', '--mode', 'json', '--print', '-e', join(root, 'tests/exposure-provider.pi.ts'), question,
    ], {
      encoding: 'utf8', timeout: 90000, maxBuffer: 8 * 1024 * 1024,
      env: { ...process.env, PI_OFFLINE: '1', PI_FM_MODEL: 'exposure-fixture/offline',
        PI_FM_MCP_LAUNCHER: join(root, 'tests/exposure-reader-fixture.sh'), PI_FM_CARD_DIR: join(directory, 'cards'),
        PI_FM_TOOLBOX_DIR: join(directory, 'toolbox'),
        PI_FM_TEST_READER_DIR: directory, PI_FM_TEST_TOOLS: readerTools.join(','), ...env },
    });
    assert.equal(result.status, 0, result.stderr || String(result.error));
    const events = result.stdout.trim().split('\n').map(line => JSON.parse(line));
    const final = events.findLast(e => e.type === 'message_end' && e.message.role === 'assistant');
    const seen = JSON.parse(final.message.content.find(c => c.type === 'text').text);
    const requests = readFileSync(join(directory, 'requests.jsonl'), 'utf8').trim().split('\n').map(JSON.parse)
      .filter(request => request.method === 'tools/call');
    return { seen, requests, calls: requests.map(r => r.name) };
  } finally {
    rmSync(directory, { recursive: true, force: true });
  }
}

const FIXTURE_TOOLS = ['fm_status', 'fm_attach', 'fm_get_save', 'fm_db_schema', 'fm_db_query', 'fm_db_read', 'fm_get_inbox',
  'fm_get_club_squads', 'fm_find_fixtures', 'fm_get_retained_shot_map'];

test('actual Pi: the harness attaches before the first model call and the model never handles session_id', () => {
  const { seen, requests, calls } = runFixture(FIXTURE_TOOLS);
  // The harness made fm_attach and fm_get_save before the model's first call; the model made none of them.
  assert.deepEqual(calls.slice(0, 2), ['fm_attach', 'fm_get_save']);
  assert.equal(seen.firstDeclared.includes(`${PREFIX}fm_attach`), false);
  assert.equal(seen.firstDeclared.includes(`${PREFIX}fm_status`), false);
  assert.deepEqual(seen.firstDeclared.filter(n => n.startsWith(PREFIX)).map(n => n.slice(PREFIX.length)).sort(),
    ['fm_db_query', 'fm_db_read', 'fm_db_schema', 'fm_get_inbox']);
  assert.equal(seen.promptHasSave, true);
  assert.equal(seen.promptHasCard, true);
  assert.equal(seen.promptHasMarkers, false);
  assert.equal(seen.declaredSessionParam, false);
  // tool_search reached the deferred shot map; the call carried no session_id from the model, the
  // harness filled it, and the reader accepted it.
  assert.ok(seen.afterSearch.includes(`${PREFIX}fm_get_retained_shot_map`));
  const shot = requests.find(r => r.name === 'fm_get_retained_shot_map');
  assert.equal(shot.args.session_id, 'S1');
  const result = seen.results.find(r => r.name === `${PREFIX}fm_get_retained_shot_map`);
  assert.equal(result.isError, false);
  // The schema card was generated from the reader (root plus each card view) once.
  assert.ok(calls.includes('fm_db_schema'));
});

test('actual Pi: an expired session is replaced and the call retried without the model noticing', () => {
  const { seen, calls } = runFixture(FIXTURE_TOOLS, { env: { PI_FM_TEST_EXPIRE_ON: 'fm_get_retained_shot_map' } });
  assert.equal(calls.filter(n => n === 'fm_attach').length, 2);
  const result = seen.results.find(r => r.name === `${PREFIX}fm_get_retained_shot_map`);
  assert.equal(result.isError, false);
  assert.match(result.text, /"session_seen":"S2"/);
});

test('actual Pi: an attach failure reaches the prompt with the reason and the fix', () => {
  const { seen, calls } = runFixture(FIXTURE_TOOLS, { env: { PI_FM_TEST_ATTACH_ERROR: 'Found 0 games. Use fm_status and select a PID explicitly.' } });
  assert.equal(calls.includes('fm_get_save'), false);
  assert.equal(seen.promptHasAttachError, true);
  assert.match(seen.attachLines, /Found 0 games/);
  assert.match(seen.attachLines, /Start Football Manager 27, load the career/);
  // A reader call answers with the same reason instead of a bare session error.
  const result = seen.results.find(r => r.name === `${PREFIX}fm_get_retained_shot_map`);
  assert.equal(result.isError, true);
  assert.match(result.text, /could not attach to the game: Found 0 games[\s\S]*Fix: Start Football Manager 27/);
});

test('actual Pi: fm_report is declared only when the question asks for a file', () => {
  const plain = runFixture(FIXTURE_TOOLS, { prompt: 'Who should I sell?' });
  const asked = runFixture(FIXTURE_TOOLS, { prompt: 'Give me a shortlist report of left-backs' });
  assert.equal(plain.seen.firstDeclared.includes('fm_report'), false);
  assert.equal(plain.seen.firstDeclared.includes('fm_tactic_file'), false);
  assert.equal(asked.seen.firstDeclared.includes('fm_report'), true);
  assert.ok(asked.seen.firstToolChars > plain.seen.firstToolChars);
});
