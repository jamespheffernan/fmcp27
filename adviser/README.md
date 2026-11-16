# pi-fm

Adviser 1.4.0 follows the round-2 reader (`r2/integration` 965275e: about forty new tables, the `m_` manager view over every table). The schema card groups the tables by what a manager asks (squad and morale, contracts and money, scouting and transfers, matches and ratings, histories, competitions and registration), one line each with the key columns, marks the tables a statement must name ("name the rows", refused over 400 people), your-club tables and the loaded-match tables, and states the `m_` rule; it is about 1.9K tokens where the 1.3.0 card would grow to 2.6K on this reader by listing every table. The prompt follows the reader's manager-view policy: another club's player's wage and contract expiry are public (the game shows them on his profile); clauses, a club's money, offers, registration and scouting stay own-club; attributes are ranges, ability is stars; transfer values, position ratings, traits and condition stay hidden. The answer contract adds three fixed first reads: a rating is explained from its components (`match_rating_component`, the match loaded in the game), playing-time advice starts from the `promise` table, and agent demands are quoted as ranges against the budget; money is pounds, wages per week. `fm_get_ui_screen` joins the declared set (13 tools) for the tactics, squad registration and training screens. The `fm-db` guide is rewritten: 29 statements, every one executed on the reader in the view it names, with worked examples for ratings, momentum, promises, happiness, hierarchy and social groups, careers, agent demands, the finance breakdown, Champions League registration, attribute progress, past winners and public wages. The recruitment, playing-time and season-planning guides are rewritten for the new data; tactical analysis gains rating components and momentum, training gains attribute progress. Eval set version 4 (39 questions) adds eleven questions on the new surface with facts read at run time and a `usedSource` transcript rule.

Measured on 12 November 2026 against `r2/integration` 965275e (197 tools, game date 13 December 2030): on the 28 version-3 questions, 3.07M tokens (110K an answer) and $11.08 against 2.96M and $9.97 for 1.3.0, median 61 s against 73 s, 5.9 model turns against 6.0, 197 tool calls against 159, 8 tool errors against 15; on the 22 older questions 5.8 turns and 108K tokens an answer (6.0 and 109K). The first model call is 11.9K input tokens (10.0K). The eleven new questions take a median 37 s, 3.6 turns and 50K tokens. 37 of 39 pass the deterministic checks after one rerun; see `evals/README.md`.

Adviser 1.3.0 spends its turns on the question. The harness attaches to the game before the first model call (`pi/fm-reader-session.mjs`): it calls `fm_attach` and `fm_get_save` itself, removes `session_id` from every reader tool schema, writes the current id into every reader call (direct, Code Mode or found with `tool_search`), re-attaches once when the reader no longer knows the session, and compacts JSON results to one row per line. The prompt carries the attached save (save, manager, club, game date, re-read before each question) or, when attaching fails, the reader's exact error and the one fix. A schema card generated from the live `fm_db_schema` and cached per reader version (`pi/fm-schema-card.mjs`, in `tmp/schema-cards/`) replaces the guide load and schema call that every SQL session made. Twelve reader tools are declared (`fm_db_query`, `fm_db_schema`, `fm_db_read`, `fm_get_board_confidence`, `fm_get_inbox`, `fm_get_calendar`, `fm_get_squad_happiness`, `fm_get_player_status`, `fm_get_club_vision_progress`, `fm_get_league_table`, `fm_get_match`, `fm_coverage`); attachment, `fm_db_refresh` and the former match tools are deferred. `fm_report` and `fm_tactic_file` are declared only on turns that ask for a file or a tactic; the report validator repairs safe problems (long labels, unknown fields, numerals written as text, words in numeric cells) and lists the repairs instead of refusing the file. The answer contract leads with the decision, then a compact evidence table with benchmarks (per 90, league percentile, squad average), then what would change the call. Hidden facts about other clubs (attributes, ability, wages, contracts, values, balances) come from the manager's knowledge unless the user asks for actual values. The `fm-db` guide is rewritten for the collection and match tables; every query in it ran on the merged reader. The eval set is version 3 (28 questions), with ground truth read at run time.

Measured on 12 November 2026 against the merged reader (`p1/integration` bbc47be with on-demand columns, 194 tools, game date 13 December 2030), on the 22 questions the 1.2.0 run used: mean model turns per answer 10.4 → 6.0, median wall time 85 s → 73 s, tokens 5.64M → 2.41M (mean 256K → 109K per answer), cost $17.41 → $8.06, tool calls 308 → 126, tool errors 19 → 13; the first model call is 10.0K input tokens (12.1K before). No session spent a turn on attachment (31 of 31 did before). All 28 version-3 questions answered; see `evals/README.md` for the run and its reruns.

Roles by name only (15 November 2026, not yet released). Football Manager 27 gives a player one role in possession and one role out of possession; the Defend, Support and Attack level of earlier games does not exist. The adviser had asked for, chosen and printed one with every role. A role edit in `fm_tactic_file` is now `{phase, position_index, role}`. The writer runs the game's own legality check at that position, finds the one stored word the game accepts for the named role and writes it; a role the game does not offer there refuses with the legal roles, and a role with more than one accepted word refuses instead of choosing. `inspect`, `list_templates`, `authoring_catalog`, `generate`, receipts and refusal diagnostics name roles only: `legal_roles_for_current_positions[].legal_roles` is a list of names, and the receipt flag is `all22_position_role_selections_legal`. A request that still carries the removed field beside a role is accepted and the field is dropped unread. The stored words are unchanged: for all 101 legal roles of the 4-2-3-1 template the writer stores the word it stored before (`tests/fixtures/role-words-4231-fm27.json`). The system prompt and the tactic guides state the rule.

Adviser 1.7.0 (13 November 2026): the adviser reads the Data Hub and corrects its saved tools in place. Asked that afternoon to interpret the team analytics "Possession Gained" chart, the adviser had no route to it. With reader 0.170.0 it reads the chart: `fm_get_ui_screen(screen: "team_analytics")` returns the game's zone maps, scatter graphs, polygons and summary sentences; the screens `player_analytics`, `person_analytics`, `opposition_analytics` and `match_analytics` cover the squad's graphs, one player, an opponent's report and a recent match; and `fm_get_retained_possession_events` says which players won the ball, in which match and which half. The core guide routes Data Hub questions to "Read a Data Hub chart" in the `fm-tools` guide. `fm_toolbox` gains `action: "edit"`: exact text replacements in a saved tool, all applied or none, so the adviser corrects a 30 KB tool without sending it again. In `fm_report`, a `stacked_bar_chart` prints each bar's total under its label with the unit said once and runs a note of up to 400 characters under the bar, and an empty string in a table cell is a blank cell where it was a refusal. The prompt states the `store()` limit of 262,144 characters a value. Seventeen stale tests follow the harness again (the attach before the first model call, the deferred `fm_status`, a tactic tool declared only on a turn that asks for a tactic, guides read a page at a time, the report repairs). The 33 native tactic-file tests that pin the 27.0.0 game plugin by hash fail on a Mac with 27.0.1 installed.

Adviser 1.6.0 (13 November 2026): the adviser builds tools for itself. In a session that morning the user asked for "a reusable model" of squad capacity and got the method described in prose: the harness gave the adviser Code Mode scripts that end with the call and nowhere to keep one. `fm_toolbox` saves a script that ran correctly as a named tool (the body of `async (args) => { ... }`, with a description and its arguments), and every later Code Mode script, in any session, calls it as `await toolbox.<name>(args)`. The prompt tells the adviser when to build one (the user asks for something reusable, or it is writing the same multi-step script a second time), lists the saved tools, and says to answer from a run of the tool. See "The adviser's own tools" below.

Adviser 1.5.0 (12 November 2026): `fm_tactic_file` follows the installed game build. On a build the reader has mapped (27.0.1), its native authoring runs against that build's code through the reader's address map (reader 0.169.0; run the reader's `scripts/fm_update_build.py --installed` after a game update). `list_templates` reports `native_build` with the functions that refuse on the build. On 27.0.1 the older single-setting team edits refuse; use `native_authoring.team_instructions`.

Adviser 1.4.1 (12 November 2026) follows a session held during a live match. The tactical guide gains "During a match": read the tactic in use (`fm_get_ui_screen(screen: "tactics")`, `fields.tactic.in_match`, reader 0.168.2), the substitutions made and the condition now before advising, and do not list them as unknown. The core guide routes "a match I am playing now" there. The playing-time guide names the contracts and staff guides again (a guide test had been failing since the round-2 rewrite).

### Install a reviewed revision

```sh
src="/Volumes/4TB Private/Offloaded/Agent Work/fmdb-20261111/r5-pifm2/adviser/"   # the reviewed worktree
dst="/Volumes/4TB Private/Offloaded/Agent Work/fm-advisor/"
rsync -a --exclude sessions/ --exclude evidence/ --exclude tmp/ --exclude evals/out/ \
  --exclude node_modules/ --exclude __pycache__/ "$src" "$dst"
zsh -n "$dst/bin/pi-fm" && node "$dst/pi/fm-skills.mjs" --index > /dev/null
node -e 'console.log(require(process.argv[1]).version)' "$dst/package.json"   # 1.4.0
```

1.4.0 removes no files, so `rsync` runs without `--delete` (the install keeps anything only it has). The reader that `PI_FM_MCP_LAUNCHER` starts (default: the main checkout's `scripts/run_mcp.sh`) must contain the round-2 reader (`r2/integration` 965275e or later: the `m_` manager view over every table, the history, people, market and match-state tables, `fm_get_ui_screen`). The schema card is generated on the first question after an install or reader update and cached in `tmp/schema-cards/` under a key that includes the card version (10), so 1.4.0 builds a new card without deleting the old one. The first query after a reader upgrade rebuilds the snapshot (about 20 s). Restart open sessions (`pi-fm --continue`).

Adviser 1.2.0 reads what the game's own screens show. Six runtime tools join the declared set: `fm_get_board_confidence` (overall and per-area board grades, highlights, criticisms, signing feedback), `fm_get_inbox`, `fm_get_calendar`, `fm_get_player_status` (happiness, morale, promises, transfer interest), `fm_get_club_vision` (board and supporter objectives, wage summary, board members) and `fm_get_league_table` (table, top scorers, xG table). The other screen tools (finance projections, scouting, transfers, squad dynamics, training, medical centre, youth intake, season expectations, manager profile), the generic `fm_ui_schema` / `fm_ui_read`, the per-player `fm_get_manager_visible_attributes`, `fm_get_team_squad` and `fm_query_match_scope` are deferred and named in the core guide's routing table. The prompt routes questions: the SQL snapshot for players, clubs, staff and competitions across the save; the manager view (masked attributes as ranges, ability as stars) for other clubs' players and scouting; full data for the user's own squad or when actual values are asked for; runtime tools for board, inbox, calendar, happiness and club vision; specialised tools for match data, tactics, finance projections and rules; and `fm_report` for shortlists, comparisons, reviews and answers over about a dozen rows. While manager knowledge or pending snapshot columns are still building, the adviser answers from what is covered and says what is not. `fm_report` is now always registered, with its guide `fm-reports` in the index. The `fm-db` guide covers stars, `scouted`, range filters, season statistics, pending columns and club joins. The eval set has 22 questions (`evals/questions.json` version 2).

Measured on 11 November 2026 against the merged reader (integration `21c6928`, 189 tools, game date 10 December 2030): 22 of 22 answered and 21 of 22 passed the deterministic checks on the first run (5.6M tokens, $17.41, median 85 s per question); the remaining failure and three quality problems were fixed and their reruns passed. The model is declared 17 reader tools; the first model call is 10.8K input tokens (61K before the lean surface). On the five smoke questions the adviser used 1.36M tokens against the 2.89M baseline. `evals/run.mjs --out DIR` keeps run folders and sessions outside the checkout.

Adviser 1.1.0 answers through a small tool surface. The model is declared 14 reader tools instead of about 170 (first model call about 8K tokens instead of 61K), finds the rest with `tool_search`, and answers save-wide questions with SQL over the reader's save snapshot when the reader offers `fm_db_query`. Questions about scouting and other clubs' players default to the manager's knowledge. One short core guide replaces the three guides the model had to read before every first answer; other guides load on demand in pages. The `evals/` harness measures each change.

Adviser 1.0.97 adds `fm_tactic_file({action:"schema"})` to discover its exact immutable registered JSON parameters and matching fingerprint, including when CodeMode renders the TypeScript arguments as unknown. The full contract is returned only on this local discovery action; native authoring behavior and validation constraints remain unchanged. Existing sessions are not reloaded.

Adviser 1.0.96 exposes the registered tactic schema fingerprint and separately labelled current-file observations on inspection and catalog results. Generation refuses observed adapter drift; a legacy session without registration evidence remains unknown. Guides distinguish native role and instruction encoding from actual FM27 menu controls and effective behavior. Native tactic encoding is unchanged.

This release includes the safe requested report filename and separate qualified-shot receipt counts introduced in the private95 candidate. Offline tactic tests now use the explicit reader fixture; bounded child diagnostics retain status, signal and launch errors.

Adviser 1.0.95 adds an optional exact HTML filename under Agent Outputs. Report receipts separately count qualified source-observed attempts and retain their unreconciled xG scope. Different existing content is refused.

Adviser 1.0.94 routes retained shot questions through qualified observed attempts when strict xG reconciliation withholds a side. The guides preserve fixture and source pins, require complete player-count and canonical-actor checks, and distinguish observed native attempt values from official aggregate xG. Truncated or unqualified coverage stays explicit. Own-goal markers and strict xG totals and rankings retain their separate scope.

Adviser 1.0.93 keeps native catalogs in a local Code Mode variable and stores a compact source-bound projection for the requested slots. The delivered example preserves the exact legal roles and instruction inspection while fitting the per-value storage limit. Tactic encoding and native validation remain unchanged.

Adviser 1.0.92 returns exact phase/slot/position and native legal role alternatives when a concrete request is invalid. Structured diagnostics survive direct and Code Mode calls; source, execution and transport failures remain fatal. Creation and tactical-analysis guides validate complete file-compatible roles before finalizing a concrete plan and identify any role change as a revision. Invalid requests produce no tactic or automatic substitution.

Adviser 1.0.91 adds native-gated `PI_SWITCH_POSITION` and typed out-of-possession position marking. New marking targets use the original compiled picker’s 25 non-goalkeeper positions; named-player marking remains context-dependent and unavailable as a portable file parameter. Template authoring inspection now returns current-role optional profiles, raw editor availability and source phase correspondence, checked without changing the creator or serialized file. Raw state values remain separate from effective/mandatory instructions and live UI behavior.

Adviser 1.0.90 adds complete native tactic authoring: both phase layouts, up to 22 roles, complete named team selections and available current-role player instructions. It runs the original isolated creator, setters and whole serializer, then reloads the actual archive. Formation changes preserve the source’s cross-phase player correspondence. Whole plans no longer require matching role donors. Game import, player assignment and effective match behavior remain separately unverified.

This release also adds connected set-piece and club-development guidance, routes supported financial obligations and exact-fixture suspension checks, and binds guide reads through held no-follow directory descriptors. All 14 fixed guide IDs remain available directly and through Code Mode. These procedures preserve decoded source limits and do not establish effective facilities, complete set-piece routines, payments or full fixture clearance.

A dedicated Pi adviser for your running Football Manager career. Ask for a specific saved file, backup or offline catalog to use the dated archive instead. It loads a football guidance index and the local read-only FM MCP reader automatically; specialist guides load when needed.

Version **1.0.88** expands donor-based role editing to 26 directed changes across nine exact native record prefixes. It retains the seven previous cases, adds their proved reverse directions, and adds source-format26 OOP full-back changes among Pressing Full-Back, Full-Back and Holding Full-Back. It also transfers two proved stored instruction profiles for native-format27 IP slot9 AM(CL), Attacking Midfielder: no stored options, or Roam From Position together with Move Into Channels. Both features require matching inspected donors, pinned source hashes and unchanged native definitions. Original ARM routines and full native body readback were verified offline; the instruction availability context was synthetic. Personal overrides, role-derived selections, effective instructions, full UI setter parity and game import remain unverified.

Version **1.0.87** adds three bounded source-format27 stored role edits: OOP slot8 AM(CR) and slot9 AM(CL), Attacking Midfielder to Tracking Attacking Midfielder, and OOP slot7 WB(L), Pressing Wing-Back to Wing-Back. Each requires an inspected matching donor, its separately proved complete companion prefix and native code checks. The tracking cases require the exact zero-instruction target; the wing-back case retains its proved target PI31. Local readback and offline native execution leave game import, full UI setter parity and effective instructions unverified.

Version **1.0.86** adds two bounded stored role edits: source-format26 IP slot7 AM(R) and slot9 AM(L), Winger to an inspected Inside Forward donor record. Each requires its own proved complete companion prefix and native setter/reconciliation checks. The file retains source format26; local artifact readback and offline native execution do not establish FM27 import, effective instructions or a recreation of a historical team tactic.

Version **1.0.85** adds stored career morale queries with explicit unknowns, keeping happiness and concerns separate. It reconstructs native default training intensity from existing manager policy when requested, while keeping applied workload unknown. It routes selected-club current and committed weekly wage questions through explicit host recomputation, keeping unsupported monetary branches unknown. Stored Hit Early Crosses / Work Ball Into Box file edits, including clearing both selections, remain supported. It also strengthens tactical guidance on tracking averages, native clocks and box-attacking plans. It separates measured shots and pass connections from unobserved runs, and proposed attacking cover from out-of-possession roles. Stored pressing-block, crossing-style and eligible role file edits remain supported. Goal-kick length and recorded annual stadium-rent queries remain supported. It routes current international-duty gates and native estimated returns through the selected-roster reader. It can compare player possession won/lost in independently witnessed retained periods, and its training guide walks through positional-conversion proposals, incumbent minutes and familiar-role costs. Duty is one availability input; missing period witnesses and unproved retraining assignments remain unknown. The exact host-effect allowlist covers the recorder, two current-match observation reads and three retained period reports. Game access stays read-only; native file import and match behaviour remain unverified.

```sh
pi-fm
pi-fm "Assess my squad and the positions most in need of recruitment"
pi-fm --continue
pi-fm --resume
```

`--continue` reopens the latest FM conversation. `--resume` opens Pi's session picker. You can browse local FM27 saves offline with reader 0.45.0 or later. Reader 0.48.0 adds saved club searches. Reader 0.49.0 adds saved competition searches and currency rate histories. Reader 0.50.0 lets you compare a club’s teams and roster sizes across two files. Reader 0.51.0 finds teams whose saved rosters share a PERSON reference within one file. Reader 0.52.0 identifies their national owners and supplies installed English country labels where available. Reader 0.53.0 follows saved roster references to candidate names and shows how nearby records support each match. Reader 0.54.0 can rank a saved roster by stored current and potential ability where a candidate player start is supported. Cross-date comparisons check the identity and membership in each selected file. Reader 0.55.0 reads the dates, goals, assists and ratings recorded in a player’s saved form groups. Reader 0.56.0 compares saved player attributes and positions, and checks primary contract expiries and stored club options. Reader 0.57.0 can search a pinned save by first name, surname or common name and follow the resulting references to supported profiles. Live queries require a running game with a supported career loaded. The adviser reads it in the background without changing window focus or game state.

Ask about squad depth, recruitment candidates, contracts, loans, wages and budgets, staff, competitions or fixtures. The reader's current schemas determine available fields. Missing and unmapped data remain explicit, and long queries must finish pagination before claiming completeness. A resumed conversation refreshes its attachment and relevant evidence before giving current advice.

Code Mode is enabled by default. The adviser can compose FM queries in JavaScript, paginate results, compare players and calculate summaries before returning the relevant evidence. Direct FM calls remain available. Reader 0.87.0 adds projected match-data tables. Reader 0.88.0 adds a team/date/competition scoped query, compact field discovery and one shared capture for fixture, team and player rows, allowing season comparisons in JavaScript with explicit missing-match coverage. Restart an existing session with `pi-fm --continue` to load the update.

## Installation

This checkout is installed through:

```text
/Users/jamesheffernan/.local/bin/pi-fm
  → /Volumes/4TB Private/Offloaded/Agent Work/fm-advisor/bin/pi-fm
```

Pi 1.5.0 is installed separately and supplies the existing account login. The launcher uses `openai-codex/gpt-6-astra` with medium thinking, like `pi-ck3`. It changes no global Pi configuration or credentials.

| Override | Default |
| --- | --- |
| `PI_FM_MODEL` | `openai-codex/gpt-6-astra` |
| `PI_FM_SESSION_DIR` | This checkout's `sessions/` directory |
| `PI_FM_MCP_LAUNCHER` | `/Volumes/4TB Private/Offloaded/FMCP 27/scripts/run_mcp.sh` |
| `PI_FM_CARD_DIR` | This checkout's `tmp/schema-cards/` (schema cards, one per reader version) |
| `PI_FM_TOOLBOX_DIR` | `~/.pi/agent/pi-fm-toolbox/` (the tools the adviser has saved; outside the checkout so an install does not remove them) |
| `FMCP_CACHE_DIR` | `/Volumes/4TB Private/Offloaded/Agent Work/fmcp-source-cache`; set an existing private directory to override, or an empty value to disable the disk cache |

The external volume must be mounted. Session history remains separate from ordinary Pi and `pi-ck3` conversations. The launcher always starts in this checkout, so it works from any current directory. The shared Herdr state extension loads when installed.

### Install from the reader repository

The adviser's source lives in the reader repository under `adviser/`. To install a reviewed revision, copy it over the installed checkout, keeping the installed sessions, evidence, eval runs and dependencies:

```sh
src="/Volumes/4TB Private/Offloaded/FMCP 27/adviser/"   # or a reviewed worktree's adviser/
dst="/Volumes/4TB Private/Offloaded/Agent Work/fm-advisor/"
rsync -a --delete \
  --exclude sessions/ --exclude evidence/ --exclude tmp/ --exclude evals/out/ \
  --exclude node_modules/ --exclude __pycache__/ --exclude .git/ \
  "$src" "$dst"
zsh -n "$dst/bin/pi-fm" && node "$dst/pi/fm-skills.mjs" --index > /dev/null
```

The installed launcher starts the reader through `PI_FM_MCP_LAUNCHER` (default `/Volumes/4TB Private/Offloaded/FMCP 27/scripts/run_mcp.sh`). That checkout must:

- contain the merged reader with the tools this adviser declares directly: `fm_db_schema`, `fm_db_query` (with its `view` argument), `fm_db_read`, `fm_db_refresh`, and the runtime tools `fm_get_board_confidence`, `fm_get_inbox`, `fm_get_calendar`, `fm_get_player_status`, `fm_get_club_vision`, `fm_get_league_table` (the merged integration reader, `21c6928` or later, has them all; its `player_view.club_idx` is the club row, which the `fm-db` guide assumes). Tools it lacks are simply not declared, and the prompt drops the routes that need them;
- have its `.venv` built for that revision (`scripts/run_mcp.sh` runs it);
- have room on the cache volume (`FMCP_CACHE_DIR`) for the snapshot and the manager-knowledge store, several hundred MB per save; with a full volume `fm_db_query` fails with "database or disk is full" and the manager view with "Knowledge store unusable".

Restart open pi-fm sessions (`pi-fm --continue`) to load the new prompt and tool set.

The conversation groups consecutive checks into a compact entry of at most two lines. It names the football evidence being read—for example, `Reading the components behind player ratings` or `Reading team Data Hub charts: possession gained`—and distinguishes your manager’s knowledge from full career data. Query results show returned counts, no matches or further results; a returned row is never assumed to represent one player. Failures and interrupted checks stay explicit. Script summaries follow calls that actually execute, including saved calculations and indirect calls, rather than guessing from script text. Reopened conversations use Pi’s recorded nested calls; counts from nested results are available during the live run only. The working indicator follows active checks, then says `Weighing the evidence for your answer` when data has been gathered. Press Ctrl+O to show every call with its script and output. `pi/fm-activity-copy.mjs` holds the football wording; `pi/fm-activity.mjs` tracks execution and draws the summaries.

pi-fm also works when started over SSH or mosh. macOS lets only processes in the Mac's desktop login read FM's memory, so a reader started from a remote login fails with `task_for_pid_failed` and no password prompt appears. When `launchctl managername` is not `Aqua`, or an SSH session is detected, pi-fm sends the reader and match-report runs through the launchd agent `com.jamesheffernan.pi-fm-desktop-reader`. That agent runs in the desktop login and listens on `~/.pi/fm-desktop-reader.sock`. Load it once from a Terminal on the Mac with `node pi/fm-desktop-reader.mjs install`; it then loads at every login. `node pi/fm-desktop-reader.mjs status` reports whether it is loaded. If the agent cannot be reached, pi-fm runs the reader directly and prints a warning. Setting `PI_FM_DESKTOP_READER=0` turns the agent off and `=1` forces it on. A custom `PI_FM_MCP_LAUNCHER` always runs directly.

## Tool boundary

The launcher disables automatic extensions, skills, context files, prompt templates and built-in agent tools. It appends the core guide (`pi/fm-core.md`) and an index of approved bundled guides under `skills/`, and loads `pi/fm.pi.ts`, which registers native Code Mode, `tool_search` and only the `fm_live` server; global and project MCP files are excluded. The active tool allowlist is `codemode,tool_search,papercut,fm_tactic_file,fm_write_text,fm_read_skill,fm_toolbox,fm_report,mcp__fm_live__*` (plus `fm_match_report` when its backend is installed).

The reader server is registered with `exposure: "deferred"`. Only the tools in `pi/fm-exposure.mjs` are declared to the model up front (13, from version 1.4.0): `fm_db_query`, `fm_db_schema`, `fm_db_read`, nine screen tools (`fm_get_board_confidence`, `fm_get_inbox`, `fm_get_calendar`, `fm_get_squad_happiness`, `fm_get_player_status`, `fm_get_club_vision_progress`, `fm_get_league_table`, `fm_get_match`, `fm_get_ui_screen`) and `fm_coverage`. The harness's transport (`pi/fm-reader-session.mjs`) attaches, fills `session_id` and re-attaches, so `fm_status`, `fm_attach` and `fm_get_save` are deferred. Every other reader tool is found with `tool_search`, which declares it for the next call, and Code Mode scripts can call any reader tool. Tools the reader does not offer are simply absent. Before each run the extension resolves the prompt's conditional sections against the registered tools: the SQL workflow, the `fm-db` guide entry and the SQL routes appear only when the reader offers `fm_db_query`, the runtime routes only when it offers the runtime tools, and the HTML report section only when `fm_report` is registered. `fm_read_skill` returns long guides in pages of at most 12,000 characters.

The extension permits the outer `codemode` call, the registered `tool_search` (it loads schemas and reads no data), shared `papercut` logger, native tactic writer, bounded text writer, approved guidance reader and the adviser's own saved-tool store (`fm_toolbox`). At every FM tool call, including nested calls from scripts, it checks both the namespace and the tool's current `readOnlyHint` annotation. Missing or false annotations block execution, except for six exact registered host-effect tools: the match recorder, two current-match observation routes and three retained period reports. Code Mode runs in Pi's QuickJS sandbox with its additional model API disabled; scripts have no Node APIs, filesystem or network access. Shell, arbitrary file access, overwriting existing text files, computer control and other MCP tools are absent from the agent's exposed inventory. Pi's own user commands and explicitly supplied extensions remain trusted local code.

New reader tools are discovered at launch without a fixed tool count. The first prompt waits for FM tool discovery. If discovery yields no read-only FM tools, the advisor reconnects the reader once before submitting the prompt. A persistent failure appears in the conversation. Use `/mcp` for connection details and `/mcp reconnect fm_live` after repairing the reader. Recovery only repeats startup discovery. The reader's decoded coverage is incomplete, and live reads are non-atomic. It cannot execute transfers, tactics or other game decisions.

## Verification

Run the focused checks with Node 26 or later:

A fresh checkout first needs the existing tests' scratch and receipt directories:

```sh
mkdir -p tmp evidence/tactic-crossing-style-20261108 \
  evidence/tactic-final-third-20261109 evidence/tactic-next-role-pair-20261108 \
  evidence/tactic-pressing-block-20261108
node --test --test-concurrency=2 tests/*.test.mjs
zsh -n bin/pi-fm
```

When setting `TMPDIR`, use an external scratch directory outside this checkout so isolated fake-home path tests do not inherit the project write grant.

To inspect the actual Pi tool inventory without making a model request:

```sh
mkdir -p evidence
PI_FM_SESSION_DIR="$PWD/evidence/inventory-sessions" \
  bin/pi-fm -e "$PWD/tests/inventory.pi.ts" --mode json --print /fmverify
cat evidence/actual-tool-inventory.json
```

Verified on 6 November 2026 with Pi 1.5.0 and reader 0.32.0: 47 exposed tools, all FM-only and read-only; successful live model calls through status, attach, save, managed squad and detach; interactive startup with the skill loaded; and `--continue` recovering the previous conversation. The live career was Cesar Jules — Newcastle, dated 26 October 2030. Private verification transcripts and receipts stay in ignored `evidence/`.

Version 1.0.1 verification on 6 November 2026: six focused tests passed. The installed launcher exposed Code Mode and 49 read-only FM tools. A live model used only Code Mode for status, attachment, save, managed squad and detach; JavaScript counted 28 managed-roster players in the Newcastle career. A nested call to the harmless non-read-only fixture in `tests/codemode-boundary.pi.ts` was blocked before execution. Scripts reported `process`, `require`, `fetch` and `models` as undefined. Receipts are in `evidence/codemode-verification.json` and `evidence/codemode-live-transcript.jsonl`.

Version 1.0.2 adds the shared `papercut` tool and `/papercut <text>` command. Entries append to `~/.pi/agent/papercuts/open.md` and `history.jsonl`, tagged `pi-fm`. Code Mode can call `tools.papercut({text, kind})`. Eight tests passed, including real Pi direct and nested logging with isolated home directories; both log files and FM attribution were checked. The installed launcher inventory also passed. Test data stays under `evidence/papercut-*`; production logs were not polluted by test entries.

Version 1.0.3 adds offline browsing guidance for reader 0.45.0. A fresh Pi session listed all four local saves, identified the saved manager and date, and counted the requested archive directory using only the two saved-career tools. See `evidence/saved-careers-reader-0.45.0/verified.json`.

## Native tactic files

Ask `pi-fm` to create an actual `.fmf` from an inspected, hash-pinned native source. For a whole plan it can replace both eleven-position layouts, select a native legal role for each of the 22 phase records by name, replace the complete named team selection, reset current-role optional player instructions or select available named instructions. `authoring_catalog` exposes current choices and `native_authoring` validates the combined plan without matching role donors. Each existing player slot retains its source cross-phase correspondence when positions change; arbitrary player rebinding is outside this interface. Position marking uses the typed `mark_specific_position` field with a compiled-menu non-goalkeeper target. Named opponent identity and specific distribution recipients remain unavailable without qualified bindings; they are not encoded as bare toggles.

Small edits retain the existing mentality and scalar team controls, plus the legacy finite donor branches. The creation guide explains combination rules and inheritance. Full original native serialization and reload verify the returned stored state; import, player assignment and effective match behavior remain unverified until separately observed.

The FM27 destination derives a safe filename in the existing user-data Tactics directory, puts its receipt in `.fm-tactics-receipts/`, and refuses existing names. An explicitly supplied custom Tactics directory is supported. Other file requests retain the dated Agent Outputs destination. File creation does not import or activate the tactic in the running game.

## Halftime adjustments

Give the adviser your going-in setup, score and main first-half pattern in one message. For example: “Half-time, 0–1 down. We use 4-3-3 on the ball and 4-1-4-1 without it. Our right-back overlaps, their left winger stays high, and we have conceded three breaks behind our right-back. What one or two changes should I make, and what should I watch by 55–60 minutes?”

The adviser can coach from your supplied observations when a verified live halftime feed is unavailable. It gives phase-specific changes, their trade-offs and a short checkpoint, while keeping proposed changes separate from anything actually applied.

## The adviser's own tools

The adviser can build a tool, keep it, and use it in later sessions. Ask for something reusable ("build a reusable model of the capacity I need at each position", "make a check I can re-run after every draw") and it writes the calculation in Code Mode against the live save, saves the working code with `fm_toolbox`, runs the saved tool and answers from that run. It also saves a tool on its own when it finds itself writing the same multi-step script a second time.

- **What a tool is.** One file, `<name>.js`, in `~/.pi/agent/pi-fm-toolbox/` (`PI_FM_TOOLBOX_DIR`): a one-line JSON header (name, description, arguments, what it returns, revision, when it was saved and the game date it was built on) followed by the code, the body of `async (args) => { ... }`. You can read and edit the file; keep the header on one line.
- **How it runs.** Any Code Mode script calls `await toolbox.<name>(args)`. Before a script runs, the `tool_call` hook adds the saved functions the script names (and the ones those name) to it; the `toolbox` object joins the script's first line and the functions follow its last line, so the script's own error line numbers do not move. A tool saved a moment ago is usable by the next script, with no restart. An unknown name fails with the list of saved names, and an error inside a tool is prefixed `toolbox.<name>:`.
- **What the adviser is told.** Each turn's prompt carries the saved tools with their descriptions and arguments (first sentences only once the list passes 6,000 characters, with `fm_toolbox(action: "list")` for the rest).
- **Actions.** `save` (refuses an existing name unless `replace: true`), `edit` (exact text replacements on the saved code, each `old` occurring exactly once, all applied or none; the adviser corrects a tool without sending its whole code again), `list`, `read` and `remove`. Replacing, editing or removing a tool moves the earlier file to `history/` beside the tools; nothing is deleted. Names are 3 to 48 lowercase letters, digits and underscores; code is limited to 65,536 characters and must parse as an async function body; the store holds at most 200 tools.
- **Charts.** `fm_report` gains a `stacked_bar_chart` section: one bar per item (a position), one segment per contributor (a player's minutes), `bands` for quality (best first), `hatched` for a compromise (minutes outside his strongest position) and a `target` (minutes needed), with any shortfall drawn as not covered. A saved tool returns such sections ready to pass to `fm_report`. A message that asks for a chart, graph or plot now declares `fm_report` for that turn; before, the tool was absent on such turns and the adviser drew the chart in text.
- **What it cannot do.** A saved tool runs inside the same QuickJS sandbox as the script that calls it: no Node APIs, file system, network or shell. Every tool call it makes passes the same `tool_call` gate as a call the model makes itself, so saving a tool grants no access the adviser did not already have, and the game stays read-only. `tests/toolbox-runtime.test.mjs` runs this through the installed Pi: a saved tool that calls a reader tool without the read-only annotation is refused and the call never reaches the reader.

## Text files and bundled guides

Ask pi-fm to save a report, note or skill draft with `fm_write_text`. It creates
UTF-8 `.md`, `.txt` and `.csv` files (up to 1 MiB) in `~/Agent Outputs/` or this
project. Relative paths start at the project root; parent folders are created.
Existing filenames, symlinks, hidden paths and dependency folders are refused.
The writer requires macOS `/usr/bin/python3` and `/usr/bin/sandbox-exec`.
Directory-relative calls reject symlink redirection; the OS sandbox checks the
allowed roots when opening a new file, including through a relocated parent.
If the sandbox is unavailable, the write fails without an unsandboxed fallback.
A separate host process can still move a file after it was opened in an allowed
folder. The writer detects a changed destination before reporting success, but
cannot revoke that already-open descriptor or stop other processes moving files.
Use a new filename for a revision. There is no general file reader or editor.

For example: “Save that tactical analysis to ~/Agent Outputs/2030-10-26 — Newcastle analysis.md”.

Version 1.0.61 loads a compact index at launch. The adviser calls `fm_read_skill`
with an exact guide id to read the complete approved Markdown, directly or
through Code Mode. The tool returns a content hash and refuses arbitrary paths,
symlinks and files larger than 64 KiB. It enables no global skill discovery.

The connected guides are:

- `skills/fm-tools/SKILL.md`: tool selection, evidence sources, calculations and text output.
- `skills/fm-tactical-analysis/SKILL.md`: tactical diagnosis, trade-offs and checkpoints.
- `skills/fm-create-tactic/SKILL.md`: template selection, previews and native `.fmf` generation.
- `skills/fm-live-investigation/SKILL.md`: detailed live, captured and saved-data query rules.
- `skills/fm-club-finance/SKILL.md`: budgets, FFP, debt and combined commitment checks.
- `skills/fm-squad-planning/SKILL.md`: depth, succession, recruitment, contracts and development pathways.
- `skills/fm-training-development/SKILL.md`: dated training calendars, stored individual focus, recovery balance and conditional development pathways.
- `skills/fm-playing-time-dynamics/SKILL.md`: agreement/current-use comparisons, explicit dynamics unknowns and conditional minutes plans.
- `skills/fm-staff-planning/SKILL.md`: coaching and recruitment capabilities, appointment priorities and staff succession.
- `skills/fm-contracts-loans/SKILL.md`: main contracts, separate appearance-wage scenarios, loan terms, wage contributions and stored offers with source-specific costs and unevaluated conditions.
- `skills/fm-season-planning/SKILL.md`: dated fixture windows, competition context and conditional rotation planning.
- `skills/fm-recruitment/SKILL.md`: candidate/incumbent comparisons, dated interest and fee/wage scenarios.

Restart with `pi-fm --continue` to load these changes. Newly written skill drafts
are not automatically activated; the coding lead must add them to the launcher's
explicit catalogue in `pi/fm-skills.mjs`. Native `.fmf` generation retains its separate destinations
and never imports or activates a tactic in the game.

Stored overlap/underlap file edits accept exact compatible native selections through `wide_support`. Omission inherits; an empty list clears the group. This preserves unrequested decoded bytes and does not establish FM27 import or player movement.
