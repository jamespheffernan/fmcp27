// Eval scoring rules that follow the reader's manager-view policy (1.4.0) and the usedSource rule.
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

import { hiddenFullViewQueries, scoreResult, sourcesUsed } from '../evals/score.mjs';

const query = (sql, view = 'full') => ({ type: 'tool_execution_start', toolName: 'mcp__fm_live__fm_db_query', args: { sql, view } });

test('another club\'s wages and contract expiry are public; clauses, values, ability, position ratings and money are not', () => {
  assert.deepEqual(hiddenFullViewQueries([
    query("SELECT name, wage, contract_expires FROM player_view WHERE club_idx = 12 ORDER BY wage DESC"),
    query("SELECT person_name, weekly_wage, expires_date FROM contract_view WHERE club_idx = 12"),
  ]), []);
  const leaks = hiddenFullViewQueries([
    query('SELECT name, transfer_value FROM player_view WHERE club_idx = 12'),
    query('SELECT person_name, clause_count FROM contract_view WHERE club_idx = 12'),
    query('SELECT * FROM contract_clause_view WHERE club_idx = 12'),
    query('SELECT name FROM player_view WHERE pos_striker >= 15 AND age < 24'),
    query("SELECT balance FROM club_view WHERE name = 'Arsenal'"),
  ]);
  assert.equal(leaks.length, 5);
  // The managed club and the manager view are never leaks.
  assert.deepEqual(hiddenFullViewQueries([
    query('SELECT name, transfer_value, pos_striker FROM player_view WHERE team_idx = (SELECT team_idx FROM _managed)'),
    query('SELECT name, transfer_value FROM m_player_view', 'manager'),
  ]), []);
});

test('usedSource matches tool names, SQL and Code Mode scripts, including nested calls', () => {
  const events = [
    { type: 'tool_execution_start', toolName: 'codemode', args: { code: 'await tools.mcp__fm_live__fm_get_match({team: "Newcastle"})' } },
    query("SELECT label, contribution FROM match_rating_component WHERE person_idx = 1"),
    { type: 'tool_execution_end', toolName: 'mcp__fm_live__fm_db_query', result: 'promise' },
  ];
  const text = sourcesUsed(events);
  assert.match(text, /match_rating_component/);
  assert.match(text, /fm_get_match/);
  assert.doesNotMatch(text, /\bpromise\b/, 'results are not sources');
});

test('version-4 questions score from run-time facts: the usedSource rule passes and fails on the transcript', () => {
  const questions = JSON.parse(readFileSync(new URL('../evals/questions.json', import.meta.url), 'utf8'));
  assert.equal(questions.version, 4);
  const ids = questions.questions.map(q => q.id);
  for (const id of ['rating-why', 'promises-at-risk', 'dressing-room', 'career-seasons', 'agent-demand-afford', 'income-expenditure',
    'ucl-registration', 'young-improvers', 'league-winners', 'rival-top-earners', 'rival-contract-expiry']) assert.ok(ids.includes(id), id);
  const facts = { promise_re: 'Miley|Andrés|Robinson|Diouf' };
  const answer = 'Two of your four promises are at risk: Robinson (deadline 23 Jan 2031) and Diouf; Miley and Andrés are on track.';
  const r = { id: 'promises-at-risk', status: 'answered', finalAnswer: answer };
  const read = scoreResult(r, { facts, events: [query("SELECT * FROM promise WHERE list = 'active'")] });
  assert.equal(read.pass, true, JSON.stringify(read.checks));
  const guessed = scoreResult(r, { facts, events: [query('SELECT name FROM player_view')] });
  assert.deepEqual(guessed.failed, ['source']);
});
