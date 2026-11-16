// Which FM reader tools are declared to the model up front, and how the prompt adapts to the
// tools the reader offers and to the session the harness attached.
//
// The reader offers about 194 tools; declaring all of them costs about 340K characters of schemas
// before the first question. Only a small set is declared directly. Every other reader tool is
// `deferred`: the model finds it with `tool_search` (which then declares it for the next call),
// and Code Mode scripts can call it at any time.

export const SERVER = 'fm_live';
export const PREFIX = `mcp__${SERVER}__`;

/**
 * The SQL pair and the fresh read. Attachment (fm_status, fm_attach, fm_get_save) is the harness's
 * job (fm-reader-session.mjs) and fm_db_refresh is no longer needed by a question, so all four
 * are deferred.
 */
export const SQL_DIRECT = Object.freeze(['fm_db_query', 'fm_db_schema', 'fm_db_read']);

/**
 * Screens people ask for in their own words, measured over 31 eval and 139 user turns (11 November
 * 2026): board confidence, inbox, calendar, a player's status, squad happiness, club vision with
 * the board's judgement, league table and one played match. fm_get_squad_happiness replaces the
 * per-player status loop (137 calls in four sessions); fm_get_club_vision_progress carries the
 * objectives with the screen's judgement; fm_get_match reads a played match from the snapshot, and
 * the loaded match with each player's rating breakdown.
 *
 * fm_get_ui_screen joined in 1.4.0: in the 1.3.0 eval run (28 questions, 12 November 2026) seven
 * sessions spent a turn on tool_search, five of them for tactics, the team sheet or playing time
 * (fm_get_managed_tactics, fm_get_managed_tactical_assignments, fm_get_next_match_squad); the
 * screen tool reads the tactics, squad registration (registered players, rules, deadline) and
 * training screens in one declared call. Promises, happiness reasons, hierarchy and histories
 * moved to SQL, so no other screen tool was added.
 */
export const SCREEN_DIRECT = Object.freeze([
  'fm_get_board_confidence', 'fm_get_inbox', 'fm_get_calendar', 'fm_get_squad_happiness', 'fm_get_player_status',
  'fm_get_club_vision_progress', 'fm_get_league_table', 'fm_get_match', 'fm_get_ui_screen',
]);

/** "Can you see X?": the reader's own ledger of what is readable and through which tool. */
export const COVERAGE_DIRECT = Object.freeze(['fm_coverage']);

/**
 * Formerly direct and now deferred (each found through tool_search when needed):
 * fm_status, fm_attach, fm_get_save, fm_db_refresh (harness or obsolete); fm_get_club_vision
 * (fm_get_club_vision_progress has the same objectives with the judgement); fm_get_club_squads,
 * fm_get_next_match_squad, fm_get_managed_tactics, fm_get_player_injury_status (3, 0, 2 and 0 of
 * 31 eval turns; SQL and fm_get_match answer most of what they did).
 */
export const DIRECT_TOOLS = Object.freeze([...SQL_DIRECT, ...SCREEN_DIRECT, ...COVERAGE_DIRECT]);

/** Pi exposure settings for the reader server: deferred by default, the direct set declared. */
export function readerExposure(direct = DIRECT_TOOLS) {
  return {
    exposure: 'deferred',
    toolExposure: Object.fromEntries(direct.map(name => [name, 'direct'])),
  };
}

/** Local names (without the MCP prefix) of the reader tools pi has registered. */
export function offeredReaderTools(allTools) {
  return new Set((allTools ?? [])
    .map(tool => tool?.name)
    .filter(name => typeof name === 'string' && name.startsWith(PREFIX))
    .map(name => name.slice(PREFIX.length)));
}

/** The direct set narrowed to what the reader actually offers, in declaration order. */
export function offeredDirectTools(allTools, direct = DIRECT_TOOLS) {
  const offered = offeredReaderTools(allTools);
  return direct.filter(name => offered.has(name));
}

/**
 * Names a prompt condition can test: every registered tool name, plus each reader tool's local
 * name, so `fm_db_query` and `mcp__fm_live__fm_db_query` both work, plus `<tool>.<parameter>` for
 * each declared parameter (`fm_db_query.view` holds when the tool takes a `view` argument).
 */
export function promptToolNames(allTools) {
  const names = new Set();
  for (const tool of allTools ?? []) {
    if (typeof tool?.name !== 'string') continue;
    const forms = [tool.name];
    if (tool.name.startsWith(PREFIX)) forms.push(tool.name.slice(PREFIX.length));
    const params = Object.keys(tool.parameters?.properties ?? {});
    for (const form of forms) {
      names.add(form);
      for (const param of params) names.add(`${form}.${param}`);
    }
  }
  return names;
}

/**
 * Does the user's message ask for a file? Reports cost a quarter of wall time when the model made
 * them unasked (12 of 15 in the 11 November evals), so fm_report is declared only for such turns.
 * A chart is a file request too: fm_report is the only tool that draws one (on 13 November a user
 * asked for a stacked bar chart, the tool was not declared, and the answer drew it in text).
 */
export const REPORT_REQUEST = /\b(?:report|document|file|html|export|download|save (?:it|this|that|them)|write (?:it|this|that) up|print(?:able)?|pdf|spreadsheet|one-pager|charts?|graphs?|plot|visuali[sz]e|visuali[sz]ation)\b/i;
/** "Save it as a tool" asks for a saved tool (fm-toolbox.mjs), which is not a file request. */
const TOOL_SAVE = /\bsave (?:it|this|that|them)\b[^.?!\n]{0,40}\b(?:tool|toolbox)\b/gi;
export function wantsReport(prompt) { return REPORT_REQUEST.test(String(prompt ?? '').replace(TOOL_SAVE, '')); }

/** Native tactic files: the tool's schema is the largest the harness declares (21 KB). */
export const TACTIC_REQUEST = /\btactic|\.fmf\b|formation file/i;
export function wantsTactic(prompt) { return TACTIC_REQUEST.test(String(prompt ?? '')); }

const BLOCK = /<!-- fm:(if|unless) ([A-Za-z0-9_.! ]+?) -->\n?([\s\S]*?)<!-- fm:end -->\n?/g;
const DIRECT_LIST = '<!-- fm:direct-tools -->';
const SAVE = '<!-- fm:save -->';
const CARD = '<!-- fm:schema-card -->';
const TOOLBOX = '<!-- fm:toolbox -->';

/** The prompt section for the attached save, or the exact attach failure and its one fix. */
export function sessionSection({ save, attachError } = {}) {
  if (attachError) {
    return [
      'The harness could not attach to the game, so no live data is available for this question.',
      `- Reader error: ${attachError.message}`,
      `- Fix: ${attachError.fix}`,
      'Open your answer with that error and that fix, in those words. Do not ask for screenshots and do not answer from memory.',
    ].join('\n');
  }
  if (!save) return 'The harness has not attached to the game yet; reader tools attach on first use.';
  return `The harness attached to the running game; reader tools fill in the session themselves (never pass \`session_id\`).\n${save}`;
}

/**
 * Resolve the prompt's conditional sections for the tools present in this session:
 *   <!-- fm:if A B --> ... <!-- fm:end -->      kept only when every term holds
 *   <!-- fm:unless A --> ... <!-- fm:end -->    kept only when the terms do not all hold
 *   <!-- fm:direct-tools -->                    replaced by the declared reader tools
 *   <!-- fm:save -->                            replaced by the attached save (or the attach failure)
 *   <!-- fm:schema-card -->                     replaced by the schema card (or a one-line fallback)
 *   <!-- fm:toolbox -->                         replaced by the tools the adviser has saved (fm-toolbox.mjs)
 * A term is a tool name, `tool.parameter`, or a session flag (`report_requested`, `schema_card`,
 * `attached`); `!term` negates it. Blocks do not nest. Text outside blocks is returned unchanged.
 */
export function assemblePrompt(prompt, allTools, options = {}) {
  const { direct = DIRECT_TOOLS, save = null, attachError = null, schemaCard = null, reportRequested = false, toolbox = null } = Array.isArray(options) ? { direct: options } : options;
  const names = promptToolNames(allTools);
  if (reportRequested) names.add('report_requested');
  if (schemaCard) names.add('schema_card');
  if (save && !attachError) names.add('attached');
  const holds = term => (term.startsWith('!') ? !names.has(term.slice(1)) : names.has(term));
  let resolved = prompt.replace(BLOCK, (_all, kind, terms, body) =>
    (kind === 'if') === terms.trim().split(/\s+/).every(holds) ? body : '');
  if (resolved.includes(SAVE)) resolved = resolved.split(SAVE).join(sessionSection({ save, attachError }));
  if (resolved.includes(CARD)) resolved = resolved.split(CARD).join(schemaCard ?? 'The schema card is not available yet: call `fm_db_schema` once (no arguments) before the first query.');
  if (resolved.includes(TOOLBOX)) resolved = resolved.split(TOOLBOX).join(toolbox ?? 'No tools saved yet.');
  if (!resolved.includes(DIRECT_LIST)) return resolved;
  const declared = offeredDirectTools(allTools, direct);
  return resolved.split(DIRECT_LIST).join(declared.length ? declared.map(name => `\`${name}\``).join(', ') : '(none: the reader offered no tools)');
}
