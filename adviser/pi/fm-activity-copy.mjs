// Activity text describes observable work, never an inferred finding or an unexecuted plan.
const FM_PREFIX = 'mcp__fm_live__';
const part = (verb, object) => ({ verb, object });

export const VERBS = {
  read: ['Reading', 'Read', 'read'],
  search: ['Searching', 'Searched', 'search'],
  compare: ['Comparing', 'Compared', 'compare'],
  check: ['Checking', 'Checked', 'check'],
  connect: ['Connecting to', 'Connected to', 'connect to'],
  disconnect: ['Disconnecting from', 'Disconnected from', 'disconnect from'],
  write: ['Writing', 'Wrote', 'write'],
  build: ['Building', 'Built', 'build'],
  record: ['Recording', 'Recorded', 'record'],
  log: ['Logging', 'Logged', 'log'],
  refresh: ['Refreshing', 'Refreshed', 'refresh'],
  save: ['Saving', 'Saved', 'save'],
  update: ['Updating', 'Updated', 'update'],
  remove: ['Removing', 'Removed', 'remove'],
  analyse: ['Working through', 'Processed', 'process'],
};

// Only known table names become claims about the subject of a query. SQL literals,
// comments, aliases and unknown identifiers never become user-facing prose.
const TABLES = {
  player: 'player attributes', player_view: 'player profiles', scouted_player_view: 'scouted players',
  person: 'player and staff records', staff_view: 'staff profiles', team: 'team records',
  promise: 'player promises', player_happiness_reason: 'reasons for player happiness',
  player_concern: 'player concerns', squad_hierarchy: 'squad hierarchy', social_group: 'social groups',
  player_attribute_history: 'attribute development', player_injury_view: 'current injuries',
  contract_view: 'contracts and wages', contract_clause_view: 'contract clauses',
  club_finance: 'wage and transfer budgets', club_finance_breakdown: 'income and expenditure',
  club_finance_month: 'monthly finances', club_sponsorship: 'sponsorship deals', club_debt_loan: 'club debts',
  club_view: 'club profiles', agent_demand: 'agent demands', transfer_offer_view: 'transfer offers',
  scout_player_assignment: 'scouting assignments', match: 'match records',
  match_player_stats: 'individual match performances', match_team_stats: 'team match statistics',
  match_shot: 'shots and expected goals', match_pass: 'match passes',
  match_rating_component: 'the components behind player ratings', match_momentum: 'match momentum',
  player_season_stats: 'season performances', player_season_rates: 'per-90 performances',
  team_season_stats: 'team season performances', person_season_statistics: 'past season performances',
  person_playing_history: 'playing history', person_career_spells: 'career history',
  person_career_totals: 'career totals', player_injury_history: 'injury history',
  club_league_history: 'past league finishes', club_transfer_history: 'past transfers',
  competition_history: 'competition history', award_history: 'past award winners',
  fixture_view: 'fixtures and results', fixture_history_view: 'past fixtures and results',
  standing_view: 'league standings', competition_view: 'competitions',
  competition_registration: 'competition registrations', news_item: 'inbox news',
  training_camp: 'training camps', club_affiliation: 'club affiliations', match_event: 'match events',
};

const SCREENS = {
  player_comparison: 'the player comparison screen', staff_comparison: 'the staff comparison screen',
  tactics: 'the tactics screen', squad_registration: 'the squad registration screen',
  training: 'the training screen', contract_negotiation: 'the contract negotiation screen',
  transfer_negotiation: 'the transfer negotiation screen', competition_rules: 'competition rules',
  team_analytics: 'team Data Hub charts', player_analytics: 'squad Data Hub charts',
  person_analytics: 'individual Data Hub charts', opposition_analytics: 'the opposition report',
  match_analytics: 'match Data Hub charts',
};

const GUIDES = {
  index: 'the football guidance index', 'fm-tools': 'the guide to available evidence',
  'fm-db': 'the guide to querying your career', 'fm-live-investigation': 'the live investigation guide',
  'fm-tactical-analysis': 'the tactical analysis guide', 'fm-create-tactic': 'the tactic creation guide',
  'fm-club-finance': 'the club finance guide', 'fm-squad-planning': 'the squad planning guide',
  'fm-training-development': 'the training and development guide',
  'fm-playing-time-dynamics': 'the playing time and dynamics guide',
  'fm-staff-planning': 'the staff planning guide', 'fm-contracts-loans': 'the contracts and loans guide',
  'fm-season-planning': 'the season planning guide', 'fm-recruitment': 'the recruitment guide',
  'fm-set-pieces': 'the set-piece guide', 'fm-club-development': 'the club development guide',
  'fm-reports': 'the report creation guide',
};

const FIXED = {
  codemode: part('analyse', 'the available evidence'),
  tool_search: part('search', 'the available FM data sources'),
  papercut: part('log', 'an adviser issue'),
  fm_write_text: part('write', 'your document'),
  fm_report: part('build', 'your report'),
  fm_match_report: part('build', 'your match report'),
  status: part('check', 'the connection to FM'),
  attach: part('connect', 'your running career'),
  detach: part('disconnect', 'FM'),
  get_save: part('read', 'your club and game date'),
  get_managed_squad: part('read', 'your squad'),
  get_team_squad: part('read', 'the selected team’s squad'),
  find_save_players: part('search', 'players in the saved career'),
  get_manager_visible_attributes: part('read', 'attributes visible to your manager'),
  get_player_injury_status: part('check', 'current injuries'),
  get_player_injury_return_estimates: part('check', 'estimated injury returns'),
  get_player_bans: part('check', 'player suspensions'),
  get_player_playing_time: part('read', 'agreed and actual playing time'),
  get_player_status: part('read', 'player happiness, promises and interest'),
  get_squad_happiness: part('read', 'squad happiness and concerns'),
  get_board_confidence: part('read', 'the board’s assessment'),
  get_club_vision_progress: part('read', 'progress against club objectives'),
  get_calendar: part('read', 'the club calendar'),
  get_league_table: part('read', 'league standings'),
  get_match: part('read', 'the loaded match'),
  get_retained_pass_events: part('read', 'passes from the recorded match'),
  get_retained_shot_map: part('read', 'shots from the recorded match'),
  get_retained_possession_events: part('read', 'possession won and lost in the recorded match'),
  get_retained_match_spatial: part('read', 'positions from the recorded match'),
  compare_team_league_performance: part('compare', 'team performance against the league'),
  coverage: part('check', 'which evidence the reader can provide'),
  db_refresh: part('refresh', 'the career data from FM'),
};

/** Bound dynamic labels and remove terminal control sequences and direction overrides. */
export function cleanLabel(value, limit = 64) {
  if (typeof value !== 'string') return '';
  const clean = value.replace(/\x1b\][\s\S]*?(?:\x07|\x1b\\)/g, '')
    .replace(/\x1b\[[0-?]*[ -/]*[@-~]/g, '')
    .replace(/[\x00-\x1f\x7f-\x9f\u202a-\u202e\u2066-\u2069]/g, ' ')
    .replace(/\s+/g, ' ').trim();
  const chars = Array.from(clean);
  return chars.length > limit ? `${chars.slice(0, limit - 1).join('')}…` : clean;
}

function tableLabel(name) {
  return TABLES[name?.toLowerCase().replace(/^m_/, '')];
}

function querySubject(sql) {
  if (typeof sql !== 'string') return 'career data';
  // Tokenize strings/comments together so a comment marker in a string cannot expose its contents.
  const source = sql.slice(0, 20000).replace(/'(?:''|[^'])*'|--[^\n]*|\/\*[\s\S]*?\*\//g, ' ');
  const subjects = [];
  for (const match of source.matchAll(/\b(?:from|join)\s+["`\[]?([a-z_][\w]*)/gi)) {
    const label = tableLabel(match[1]);
    if (label && !subjects.includes(label)) subjects.push(label);
  }
  if (subjects.length === 2 && subjects.some(subject => subject.includes(' and '))) return subjects.join(' alongside ');
  return subjects.length ? joinWords(subjects, 3) : 'career data';
}

export function joinWords(items, limit = 4) {
  const shown = items.slice(0, limit);
  const more = items.length - shown.length;
  if (more > 0) return `${shown.join(', ')} and ${more} more`;
  if (shown.length < 2) return shown.join('');
  return `${shown.slice(0, -1).join(', ')} and ${shown.at(-1)}`;
}

/** A direct call or an observed nested call, using its actual arguments. */
export function describeTool(name, args = {}) {
  args ??= {};
  const short = String(name ?? '').replace(FM_PREFIX, '').replace(/^fm_/, '');
  if (short === 'db_query') return part('read', querySubject(args.sql));
  if (short === 'db_read') return part('check', `${tableLabel(args.table) ?? 'selected records'} directly in FM`);
  if (short === 'db_schema') return part('check', args.table && tableLabel(args.table)
    ? `available fields for ${tableLabel(args.table)}` : 'which career data is available');
  if (short === 'get_ui_screen') {
    const screen = SCREENS[args.screen] ?? 'the selected FM screen';
    const chart = args.chart !== 'all' && cleanLabel(args.chart, 48);
    return part('read', chart ? `${screen}: ${chart}` : screen);
  }
  if (name === 'fm_read_skill') return part('read', GUIDES[args.id] ?? 'football guidance');
  if (name === 'fm_tactic_file') {
    const action = {
      schema: part('check', 'the tactic file options'), list_templates: part('read', 'available tactic templates'),
      inspect: part('read', 'the tactic’s stored roles and instructions'),
      authoring_catalog: part('check', 'legal positions, roles and instructions'),
      generate: part(args.preview ? 'check' : 'write', args.preview ? 'the proposed tactic file' : 'your tactic file'),
    };
    return action[args.action] ?? part('check', 'the tactic file request');
  }
  if (name === 'fm_toolbox') {
    const verb = { save: 'save', edit: 'update', remove: 'remove', read: 'read', list: 'read' }[args.action] ?? 'check';
    return part(verb, args.name ? `the saved calculation “${cleanLabel(args.name).replaceAll('_', ' ')}”` : 'your saved calculations');
  }
  if (FIXED[name] || FIXED[short]) return FIXED[name] ?? FIXED[short];
  const words = short.split('_').filter(word => word && word !== 'managed');
  const verb = { get: 'read', read: 'read', report: 'read', describe: 'check', find: 'search',
    search: 'search', query: 'read', lookup: 'search', compare: 'compare', list: 'read', record: 'record' }[words[0]];
  // Unknown future tools still have a readable fallback; never show internal refs or arguments.
  return part(verb ?? 'check', cleanLabel((verb ? words.slice(1) : words).join(' ')) || 'the requested information');
}

export function describeCall(toolName, args) {
  return [describeTool(toolName, args)];
}

export function summarize(parts, { done = false, failed = false, interrupted = false } = {}) {
  const byVerb = new Map();
  for (const { verb, object } of parts) {
    if (!byVerb.has(verb)) byVerb.set(verb, []);
    if (object && !byVerb.get(verb).includes(object)) byVerb.get(verb).push(object);
  }
  return [...byVerb].map(([verb, objects], index) => {
    const forms = VERBS[verb] ?? VERBS.read;
    const words = failed ? `Could not ${forms[2]}` : interrupted ? `Stopped while ${forms[0].toLowerCase()}` : forms[done ? 1 : 0];
    const clause = `${words} ${joinWords(objects)}`.trim();
    return index ? clause[0].toLowerCase() + clause.slice(1) : clause;
  }).join(' · ') || (done ? 'Checks complete' : 'Gathering evidence');
}

export function sourceNote(name, args) {
  if (/\bfm_db_(?:query|read|schema)$/.test(name.replace(FM_PREFIX, ''))) {
    return args?.view === 'manager' ? 'Using your manager’s knowledge' : 'Using full career data';
  }
  return '';
}
