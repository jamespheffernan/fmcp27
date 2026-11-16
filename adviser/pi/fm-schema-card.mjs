// The schema card: a compact description of the SQL snapshot that goes into the system prompt, so
// SQL questions start with a query instead of a guide load and an fm_db_schema call.
//
// It is generated from the live reader (fm_db_schema) the first time a reader version is seen and
// cached on disk per reader version, so it cannot drift from the snapshot it describes: a column
// the reader does not have is left out, and a view it lacks drops its line.
import { createHash } from 'node:crypto';
import { mkdir, readFile, rename, writeFile } from 'node:fs/promises';
import { join } from 'node:path';

export const CARD_VERSION = 11;

/**
 * The card's groups, in the order a manager asks: one line per table, key columns only. `tag`
 * marks a table whose rows a statement must name (`name`: the people, a club, a competition or an
 * award, so the reader computes only those) or whose rows are the managed club's only (`own`), or
 * that holds the match loaded in the game (`loaded`). `note` follows the columns. Columns the
 * reader lacks drop out; a table it lacks drops its line.
 */
export const CARD_GROUPS = Object.freeze([
  'Squad and morale', 'Contracts and money', 'Scouting and transfers', 'Matches and ratings', 'Histories', 'Competitions and registration',
]);

const TAGS = { name: 'name the rows', own: 'your club', loaded: 'loaded match only' };

export const CARD_SPEC = Object.freeze([
  // Squad and morale
  { group: 0, name: 'player_view', grain: 'player', cols: ['idx', 'name', 'age', 'position', 'club', 'club_idx', 'team_idx', 'contracted_club_idx', 'on_loan', 'wage', 'contract_expires', 'transfer_value', 'current_ability', 'potential_ability', 'is_injured', 'condition', 'morale', 'form'],
    note: '1-20 attributes by name (`pace`, `passing`, `decisions`, ...); position ratings 1-20, 15+ natural: `pos_` + `goalkeeper`, `defender_left|central|right`, `wing_back_left|right`, `defensive_midfielder`, `midfielder_left|central|right`, `attacking_midfielder_left|central|right`, `striker`; a loanee\'s `club_idx` is the loan club' },
  { group: 0, name: 'promise', grain: 'Promises screen', tag: 'own', cols: ['player_idx', 'list', 'title', 'made_on', 'deadline', 'status_text', 'days_left'], note: '`list` \'active\' or \'completed\'' },
  { group: 0, name: 'player_happiness_reason', grain: 'happiness line', tag: 'name', cols: ['person_idx', 'sign', 'reason_text', 'happiness_level', 'morale'], note: '`sign` \'positive\', \'negative\' or \'playing_time\'' },
  { group: 0, name: 'player_concern', grain: 'concern', tag: 'name', cols: ['person_idx', 'started', 'ongoing'] },
  { group: 0, name: 'squad_hierarchy', grain: 'player in the hierarchy', cols: ['team_idx', 'person_idx', 'tier', 'influence', 'key_personnel'] },
  { group: 0, name: 'social_group', grain: 'group member', cols: ['team_idx', 'group_name', 'person_idx', 'reasons', 'dressing_room_atmosphere'] },
  { group: 0, name: 'player_attribute_history', grain: 'monthly snapshot', tag: 'name', cols: ['person_idx', 'month', 'attributes'], note: '`attributes` is JSON on the 1-100 scale (`ROUND(json_extract(attributes, \'$.passing\') / 5.0)` is the 1-20 value)' },
  { group: 0, name: 'player_injury_view', grain: 'current injury', cols: ['person_idx', 'person_name', 'injury', 'started'] },
  // Contracts and money
  { group: 1, name: 'contract_view', grain: 'contract', cols: ['person_idx', 'person_name', 'role', 'club_idx', 'team_idx', 'weekly_wage', 'expires_date', 'clause_count', 'loan_playing_monthly_fee'] },
  { group: 1, name: 'club_finance', grain: 'club', tag: 'own', cols: ['idx', 'wage_budget_weekly', 'wage_spend_weekly', 'remaining_wage_budget_weekly', 'transfer_budget_finance_Cntb'] },
  { group: 1, name: 'club_finance_breakdown', grain: 'income or expense category', tag: 'own', cols: ['direction', 'period', 'category', 'amount', 'percent_of_operating_total'], note: '`period` \'this_month\', \'last_month\', \'this_season\', \'last_season\'' },
  { group: 1, name: 'club_finance_month', grain: 'month', tag: 'own', cols: ['series', 'month', 'amount'], note: '`series` \'balance\', \'income\', \'expenditure\'' },
  { group: 1, name: 'club_sponsorship', grain: 'deal', tag: 'own', cols: ['name', 'total_value', 'end_date'] },
  { group: 1, name: 'club_debt_loan', grain: 'loan', tag: 'own', cols: ['name', 'amount', 'remaining_debt', 'payable_per_month', 'end_date'] },
  { group: 1, name: 'club_view', grain: 'club', cols: ['idx', 'name', 'reputation', 'balance', 'transfer_budget', 'division', 'nation'] },
  // Scouting and transfers
  { group: 2, name: 'agent_demand', grain: 'line of the agent\'s answer', tag: 'name', cols: ['person_idx', 'interest', 'fee_min', 'fee_max', 'wage_min', 'wage_max', 'contract_end', 'line'], note: 'what he and his club would want from you; one row per line, the numbers repeat' },
  { group: 2, name: 'transfer_offer_view', grain: 'offer', cols: ['offer_type', 'person_idx', 'person_name', 'team1_idx', 'team2_idx', 'state_code', 'amount_raw'] },
  { group: 2, name: 'scout_player_assignment', grain: 'player being scouted', tag: 'own', cols: ['person_idx', 'scout_idx', 'date_a'] },
  // Matches and ratings
  { group: 3, name: 'match', grain: 'played match', cols: ['idx', 'date', 'competition_idx', 'home_team_idx', 'away_team_idx', 'home_goals', 'away_goals', 'detail_level'] },
  { group: 3, name: 'match_player_stats', grain: 'player x match', cols: ['match_idx', 'team_idx', 'person_idx', 'started', 'minutes', 'rating', 'goals', 'assists', 'expected_goals', 'key_passes', 'progressive_passes', 'tackles_completed', 'interceptions', 'possession_lost'] },
  { group: 3, name: 'match_team_stats', grain: 'team x match', cols: ['match_idx', 'team_idx', 'shots', 'shots_on_target', 'expected_goals', 'possession_pct'] },
  { group: 3, name: 'match_shot', grain: 'shot', cols: ['match_idx', 'person_idx', 'outcome', 'expected_goals', 'x', 'y'] },
  { group: 3, name: 'match_pass', grain: 'pass, full-detail matches', cols: ['match_idx', 'person_idx', 'completed', 'outcome'] },
  { group: 3, name: 'match_rating_component', grain: 'rating term', tag: 'loaded', cols: ['person_idx', 'team_idx', 'label', 'count', 'contribution', 'stored_rating'], note: 'no match idx: `fm_get_match(team: ...)` names the loaded match' },
  { group: 3, name: 'match_momentum', grain: '5-minute segment', tag: 'loaded', cols: ['segment', 'end_minute', 'home_value', 'away_value'] },
  { group: 3, name: 'player_season_stats', grain: 'player x competition season', cols: ['person_idx', 'competition_idx', 'season', 'team_idx', 'appearances', 'starting_appearances', 'minutes', 'goals', 'assists', 'expected_goals', 'expected_assists', 'average_rating', 'key_passes', 'progressive_passes', 'tackles_won', 'interceptions_made', 'pressures_completed'],
    note: '64 statistics; per 90 = `x * 90.0 / minutes`' },
  // Histories
  { group: 4, name: 'person_season_statistics', grain: 'season x scope', tag: 'name', cols: ['person_idx', 'year', 'scope_name', 'team_idx', 'appearances', 'goals', 'assists', 'average_rating'], note: '`scope_name` \'League\', \'Cup\', \'Continental\', \'International\', \'Overall (Club)\'' },
  { group: 4, name: 'person_playing_history', grain: 'club season', tag: 'name', cols: ['person_idx', 'year', 'team_idx', 'apps', 'goals', 'on_loan', 'transfer_fee'] },
  { group: 4, name: 'person_career_spells', grain: 'job spell', tag: 'name', cols: ['person_idx', 'team_idx', 'started', 'ended', 'job'] },
  { group: 4, name: 'person_career_totals', grain: 'person', tag: 'name', cols: ['person_idx', 'total_apps', 'total_goals', 'club_apps', 'most_significant_milestone'] },
  { group: 4, name: 'player_injury_history', grain: 'past injury', tag: 'name', cols: ['person_idx', 'injury_date', 'description', 'duration_days'] },
  { group: 4, name: 'club_league_history', grain: 'club season', tag: 'name', cols: ['club_idx', 'season', 'competition_name', 'position', 'teams'] },
  { group: 4, name: 'club_transfer_history', grain: 'past transfer', tag: 'name', cols: ['club_idx', 'year', 'direction', 'person_idx', 'fee', 'buying_team_idx', 'selling_team_idx'] },
  { group: 4, name: 'competition_history', grain: 'past season', tag: 'name', cols: ['competition_idx', 'season', 'first_team_idx', 'second_team_idx'] },
  { group: 4, name: 'award_history', grain: 'award winner', tag: 'name', cols: ['award_idx', 'season', 'place', 'person_idx', 'team_idx'] },
  // Competitions and registration
  { group: 5, name: 'fixture_view', grain: 'fixture or result, resident seasons', cols: ['idx', 'date', 'competition_idx', 'competition_name', 'home_team_idx', 'home_team', 'away_team_idx', 'away_team', 'home_goals', 'away_goals'],
    note: 'older seasons: `fixture_history_view` (its first use takes minutes)' },
  { group: 5, name: 'standing_view', grain: 'team in a league stage', cols: ['competition_idx', 'position', 'team_idx', 'team_name', 'played', 'won', 'drawn', 'lost', 'goal_difference', 'points'] },
  { group: 5, name: 'competition_view', grain: 'competition', cols: ['idx', 'name', 'nation', 'last_winner'] },
  { group: 5, name: 'competition_registration', grain: 'player x competition, current season', cols: ['person_idx', 'team_idx', 'competition_idx', 'registered'], note: 'a player with no registration marker has no row' },
]);

// Tables worth naming beyond the card's lines (joins and rarer questions); the rest are internal,
// labelled duplicates or raw native records, which fm_db_schema() still lists.
const ALSO = ['team', 'injury', 'nation', 'news_item', 'staff_view', 'person_non_playing_history', 'interaction_item_view', 'job_advert', 'training_camp', 'contract_clause_view', 'club_affiliation', 'team_season_stats', 'player_season_rates', 'match_event', 'hall_of_fame_view'];

/**
 * Columns of a fm_db_schema(table=...) answer as a Map of name -> status ('ready', 'on_demand',
 * ...; '' when the answer gives none), whatever the answer's exact shape.
 */
export function columnNames(answer) {
  const cols = answer?.columns ?? answer?.table?.columns ?? answer?.view?.columns;
  if (Array.isArray(cols)) return new Map(cols.map(c => (typeof c === 'string' ? [c, ''] : [c?.column ?? c?.name, c?.status ?? ''])).filter(([n]) => n));
  if (cols && typeof cols === 'object') return new Map(Object.entries(cols).map(([n, c]) => [n, c?.status ?? '']));
  return null;
}
const ON_DEMAND = /on_demand|lazy|pending/;

/** Table and view names of a fm_db_schema() answer. */
export function objectNames(answer) {
  const names = new Set();
  for (const key of ['tables', 'views']) {
    const v = answer?.[key];
    if (Array.isArray(v)) for (const x of v) names.add(typeof x === 'string' ? x : x?.name);
    else if (v && typeof v === 'object') for (const k of Object.keys(v)) names.add(k);
  }
  names.delete(undefined);
  return names;
}

/**
 * The card text from the snapshot's object names and the columns of each card view. Pure: tests
 * call it with fixtures. `columnsOf(name)` returns a Map (name -> status), a Set or null. A column
 * the game computes when a statement names it is marked with `*`.
 */
export function renderSchemaCard({ objects, columnsOf, managerObjects = new Set(), readerVersion = '?', gameDate = '?' }) {
  const lines = [];
  lines.push(`Snapshot of the whole save (reader ${readerVersion}; card built on game date ${gameDate}). \`fm_db_query\` runs one SELECT; name the columns, return only the rows the answer needs (no \`OFFSET\` paging) and aggregate in SQL. Money is in pounds; wages are pounds a week.`);
  const listed = new Set();
  let starred = false;
  let tagged = false;
  let group = -1;
  for (const spec of CARD_SPEC) {
    if (!objects.has(spec.name)) continue;
    const have = columnsOf(spec.name);
    const cols = have ? spec.cols.filter(c => have.has(c)) : spec.cols;
    if (!cols.length) continue;
    listed.add(spec.name);
    if (spec.group !== group) {
      group = spec.group ?? group;
      lines.push('', `**${CARD_GROUPS[group] ?? 'Other'}**`);
    }
    const status = c => (have instanceof Map ? have.get(c) : '');
    // A whole table built when first named is not "computed per column": mark only mixed tables.
    const mixed = have instanceof Map && [...have.values()].some(v => !ON_DEMAND.test(v));
    const shown = cols.map(c => (mixed && ON_DEMAND.test(status(c) ?? '') ? `${c}*` : c));
    if (shown.some(c => c.endsWith('*'))) starred = true;
    if (spec.tag === 'name') tagged = true;
    const grain = spec.tag ? `${spec.grain}; ${TAGS[spec.tag]}` : spec.grain;
    lines.push(`- \`${spec.name}\` (${grain}): ${shown.join(', ')}${spec.note ? `; ${spec.note}` : ''}`);
  }
  lines.push('');
  if (starred) lines.push('`*` = computed by the game when a statement names it: filter and sort on unmarked columns first, name starred columns only for the rows you return; `SELECT *` leaves them NULL.');
  if (tagged) lines.push('"name the rows": the statement must name its people, club, competition or award (`WHERE person_idx = 123`, `IN (...)`, or `IN (SELECT idx FROM player_view WHERE team_idx = ...)`); more than 400 people is refused. "your club": rows of your club only.');
  lines.push('Joins: `(SELECT team_idx FROM _managed)` is your first team, `(SELECT club_idx FROM _managed)` your club (reserves and youth too); `(SELECT game_date FROM _snapshot)` today. `<x>_idx` is the `idx` of that table (`person_idx` and `player_idx` = `player_view.idx`); `team.club_idx` joins teams to clubs; a `team_idx` is never a `club_idx`. Resolve a named person or club to its `idx` once. `fm_db_read(table, idx, fields)` reads base tables fresh: names, wages and contracts are fields of `person`; attributes, `is_injured` and `condition_stored` of `player`.');
  if (managerObjects.has('m_player_view') || objects.has('m_player_view')) {
    lines.push('');
    lines.push('Manager view (`view: "manager"`): every table above is `m_<name>` (`m_contract_view`); bare names are refused, except `_managed` (your own players are also `own_club = 1`). Other clubs\' wages and contract expiry are public; their clauses, money, offers, registration, transfer values, `pos_*` and condition are NULL or absent. `m_player_view` (known players) and `m_scouted_player_view` (scouted) give each attribute as `<attr>` (exact, else NULL) and `<attr>_min`/`<attr>_max`: "at least 15 for sure" is `<attr>_min >= 15`. Ability is stars: `current_ability_stars_min`/`_max`, `potential_ability_stars_min`/`_max` (0.5-5). Also `scouted`, `own_club`, `unknown_n`, `knowledge_date`.');
  }
  const others = ALSO.filter(n => objects.has(n) && !listed.has(n));
  lines.push('');
  lines.push(`Also${others.length ? `: ${others.join(', ')}` : ''}. \`fm_db_schema(table=...)\` gives any table's columns and meanings; \`native_*\` tables are raw records for investigation, not for answers.`);
  return lines.join('\n');
}

/** Card for this reader, from the disk cache or generated with `call(name, args)` and cached. */
export class SchemaCards {
  constructor({ dir, call, timeoutMs = 45_000 }) {
    this.dir = dir;
    this.call = call;
    this.timeoutMs = timeoutMs;
    this.memo = new Map();
    this.stats = { hits: 0, generated: 0, failures: 0 };
  }

  keyFor(readerVersion) {
    return createHash('sha256').update(`${CARD_VERSION}\0${readerVersion}\0${JSON.stringify(CARD_SPEC)}`).digest('hex').slice(0, 16);
  }

  pathFor(readerVersion) { return join(this.dir, `schema-card-${this.keyFor(readerVersion)}.md`); }

  async get(readerVersion) {
    const key = this.keyFor(readerVersion);
    if (this.memo.has(key)) return this.memo.get(key);
    try {
      const text = await readFile(this.pathFor(readerVersion), 'utf8');
      this.stats.hits += 1;
      this.memo.set(key, text);
      return text;
    } catch { /* not cached yet */ }
    let timer;
    const timeout = new Promise(resolve => { timer = setTimeout(() => resolve(null), this.timeoutMs); });
    const text = await Promise.race([this.generate(readerVersion).catch(() => null), timeout]).finally(() => clearTimeout(timer));
    if (!text) { this.stats.failures += 1; return null; }
    this.memo.set(key, text);
    return text;
  }

  async generate(readerVersion) {
    const root = await this.call('fm_db_schema', {});
    const objects = objectNames(root);
    // No snapshot yet (a new save or the first build): nothing to describe; try again next question.
    if (!CARD_SPEC.some(s => objects.has(s.name))) return null;
    const columns = new Map();
    for (const spec of CARD_SPEC) {
      if (!objects.has(spec.name)) continue;
      try { columns.set(spec.name, columnNames(await this.call('fm_db_schema', { table: spec.name, include_pending: true }))); } catch { columns.set(spec.name, null); }
    }
    let managerObjects = new Set();
    try { managerObjects = objectNames(await this.call('fm_db_schema', { view: 'manager' })); } catch { /* full view only */ }
    const gameDate = root?.game_date ?? root?.snapshot?.game_date ?? '?';
    const text = renderSchemaCard({ objects, columnsOf: n => columns.get(n) ?? null, managerObjects, readerVersion, gameDate });
    await mkdir(this.dir, { recursive: true });
    const path = this.pathFor(readerVersion);
    const tmp = `${path}.${process.pid}.tmp`;
    await writeFile(tmp, text);
    await rename(tmp, path);
    this.stats.generated += 1;
    return text;
  }
}
