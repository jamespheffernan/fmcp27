// Schema card generation from fm_db_schema answers, and its per-reader-version disk cache.
import assert from 'node:assert/strict';
import { mkdtempSync, readdirSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import test from 'node:test';

import { CARD_GROUPS, CARD_SPEC, columnNames, objectNames, renderSchemaCard, SchemaCards } from '../pi/fm-schema-card.mjs';

const ROOT = { game_date: '2030-12-13', tables: { player: {}, match: {}, match_player_stats: {}, club_finance: {}, weather: {}, _snapshot: {} },
  views: { player_view: {}, player_labelled: {}, contract_view: {} } };
const COLUMNS = {
  player_view: ['idx', 'name', 'age', 'club', 'team_idx', 'wage', 'pace', 'pos_striker'],
  match: ['idx', 'date', 'home_team_idx', 'away_team_idx', 'home_goals', 'away_goals'],
  match_player_stats: ['match_idx', 'person_idx', 'rating', 'minutes'],
  club_finance: [],
  contract_view: ['person_idx', 'weekly_wage', 'expires_date'],
};

function fakeReader() {
  const calls = [];
  const call = async (name, args) => {
    calls.push([name, args]);
    if (args.view === 'manager') return { views: { m_player_view: {}, m_scouted_player_view: {} } };
    if (args.table) return { table: args.table, columns: (COLUMNS[args.table] ?? []).map(column => ({ column })) };
    return ROOT;
  };
  return { calls, call };
}

test('the card lists the views the snapshot has, with only the columns it has', () => {
  const text = renderSchemaCard({ objects: objectNames(ROOT), columnsOf: n => (COLUMNS[n] ? new Set(COLUMNS[n]) : null),
    managerObjects: new Set(['m_player_view']), readerVersion: '9.9', gameDate: '2030-12-13' });
  assert.match(text, /reader 9\.9; card built on game date 2030-12-13/);
  assert.match(text, /`player_view` \(player\): idx, name, age, club, team_idx, wage;/);
  assert.doesNotMatch(text, /`player_view`[^\n]*current_ability, /);
  assert.match(text, /`match` \(played match\): idx, date, home_team_idx, away_team_idx, home_goals, away_goals/);
  assert.match(text, /`contract_view`[^\n]*person_idx, weekly_wage, expires_date/);
  // A view the reader lacks and a table with no known columns drop out of the main list.
  assert.doesNotMatch(text, /`fixture_view`|`club_finance` \(club/);
  // Tables outside the card are named only from the short allowlist, never internal or raw ones.
  const also = text.split('\n').find(l => l.startsWith('Also'));
  assert.ok(also, 'an Also line points at fm_db_schema');
  assert.doesNotMatch(also, /player_labelled|_snapshot|weather|club_finance/);
  assert.match(text, /Manager view \(`view: "manager"`\)[^\n]*`<attr>_min >= 15`/);
  assert.match(text, /\(SELECT team_idx FROM _managed\)/);
  assert.match(text, /wages are pounds a week/);
  assert.ok(text.length < 8000, `${text.length} characters`);
});

test('tables are grouped by what a manager asks, with statement-dependent and own-club tables marked', () => {
  const objects = new Set([...CARD_SPEC.map(s => s.name), 'team', 'native_scoreline', 'squad_manager_entry', 'player_labelled']);
  const text = renderSchemaCard({ objects, columnsOf: () => null, managerObjects: new Set(['m_player_view', 'm_promise']) });
  const headers = [...text.matchAll(/^\*\*(.+)\*\*$/gm)].map(m => m[1]);
  assert.deepEqual(headers, [...CARD_GROUPS]);
  assert.match(text, /`person_season_statistics` \([^)]*name the rows\)/);
  assert.match(text, /`agent_demand` \([^)]*name the rows\)/);
  assert.match(text, /`promise` \([^)]*your club\)/);
  assert.match(text, /`match_rating_component` \([^)]*loaded match only\)/);
  assert.match(text, /more than 400 people is refused/);
  assert.match(text, /every table above is `m_<name>`[^\n]*bare names are refused, except `_managed`/);
  assert.match(text, /wages and contract expiry are public/);
  const also = text.split('\n').find(l => l.startsWith('Also'));
  assert.match(also, /\bteam\b/);
  assert.doesNotMatch(also, /native_scoreline|squad_manager_entry|player_labelled/);
  // The whole surface stays about the size of the 1.3.0 card (6.2K characters on its reader).
  assert.ok(text.length < 8200, `${text.length} characters`);
});

test('columns the game computes on demand are starred, with the rule for using them', () => {
  const cols = new Map([['idx', 'ready'], ['name', 'ready'], ['age', 'ready'], ['wage', 'ready'], ['form', 'on_demand'], ['morale', 'on_demand']]);
  const text = renderSchemaCard({ objects: new Set(['player_view']), columnsOf: () => cols });
  assert.match(text, /`player_view` \(player\): idx, name, age, wage, morale\*, form\*;/);
  assert.match(text, /`\*` = computed by the game when a statement names it/);
  // A table that is wholly built on first use is not starred column by column.
  const lazy = renderSchemaCard({ objects: new Set(['match']), columnsOf: () => new Map([['idx', 'lazy'], ['date', 'lazy']]) });
  assert.doesNotMatch(lazy, /idx\*|date\*|computed by the game/);
});

test('column and object names are read from every answer shape the reader uses', () => {
  assert.deepEqual([...columnNames({ columns: [{ column: 'a', status: 'on_demand' }, { name: 'b' }, 'c'] }).keys()], ['a', 'b', 'c']);
  assert.equal(columnNames({ columns: [{ column: 'a', status: 'on_demand' }] }).get('a'), 'on_demand');
  assert.deepEqual([...columnNames({ columns: { x: {}, y: {} } }).keys()], ['x', 'y']);
  assert.equal(columnNames({}), null);
  assert.deepEqual([...objectNames({ tables: [{ name: 't' }], views: ['v'] })], ['t', 'v']);
});

test('generated once per reader version, then served from disk without reader calls', async () => {
  const dir = mkdtempSync(join(tmpdir(), 'pi-fm-cards-'));
  try {
    const a = fakeReader();
    const first = await new SchemaCards({ dir, call: a.call }).get('1.29.0');
    assert.match(first, /`player_view` \(player\)/);
    const tableCalls = a.calls.filter(([, args]) => args.table).map(([, args]) => args.table);
    assert.deepEqual(tableCalls, CARD_SPEC.map(s => s.name).filter(n => n in ROOT.tables || n in ROOT.views));
    assert.equal(readdirSync(dir).length, 1);

    const b = fakeReader();
    const cached = await new SchemaCards({ dir, call: b.call }).get('1.29.0');
    assert.equal(cached, first);
    assert.equal(b.calls.length, 0);

    const c = fakeReader();
    await new SchemaCards({ dir, call: c.call }).get('1.30.0');
    assert.ok(c.calls.length > 0);
    assert.equal(readdirSync(dir).length, 2);
  } finally { rmSync(dir, { recursive: true, force: true }); }
});

test('no snapshot yet: no card, nothing cached, the next question tries again', async () => {
  const dir = mkdtempSync(join(tmpdir(), 'pi-fm-cards-'));
  try {
    const cards = new SchemaCards({ dir, call: async () => ({ snapshot: null, tables: { person: {} } }) });
    assert.equal(await cards.get('1'), null);
    assert.equal(readdirSync(dir).length, 0);
    const slow = new SchemaCards({ dir, timeoutMs: 20, call: () => new Promise(() => {}) });
    assert.equal(await slow.get('2'), null);
  } finally { rmSync(dir, { recursive: true, force: true }); }
});
