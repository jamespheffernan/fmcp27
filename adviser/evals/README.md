# pi-fm evals

A headless harness that measures how pi-fm answers FM27 questions: latency, tool use, errors, tokens and a
deterministic answer check. Everything lives in `evals/`; nothing in the launcher, prompt, skills or config is touched.

**Budget warning.** Every question is one real `pi-fm` invocation that spends model quota (a typical answer
reads 100k to 500k tokens, mostly cached). `--smoke` is 5 invocations, `--all` is 39. Use `--dry-run` to see
the plan, `--max-invocations N` as a hard cap, and prefer `history.mjs` and `--reparse` (both free) when you
only need numbers.

## Files

| File | Purpose |
|---|---|
| `questions.json` | 39 questions (version 4): id, prompt, category, required content, `smoke` flag, deterministic `checks`. 22 come from real sessions; three test management decisions against the answer contract; three test the manager view (a rival's balance stays hidden; other clubs' wages and contract expiry are public since 1.4.0); eleven exercise the round-2 reader (rating components, promises, hierarchy, histories, agent demands, finance breakdown, registration, attribute history, past winners, public wages). |
| `facts.mjs` | Ground truth for a run, read from the reader when the run starts (board grade, inbox subjects, next opponents, last Premier League result, top scorers, squad names, contract expiries, a scouted player's stars, rivals' money for the leak checks). Writes `<run>/facts.json`. |
| `reader-client.mjs` | The harness transport without pi: `call <tool> <json>`, `sql <select> [manager]`, `describe <tool>`, `guide-sql <guide.md>` (runs every SQL block of a guide). Needs `FMCP_CACHE_DIR`. |
| `run.mjs` | Runs a selected set, one headless `pi-fm --mode json --print` per question, stdin closed. |
| `score.mjs` | Deterministic checks and run-to-run comparison. No model calls. |
| `history.mjs` | Same metrics over `sessions/*.jsonl`, for a free baseline. |
| `lib.mjs` | Shared stats, event accumulator and detectors. |
| `out/` | Git-ignored output: `out/<run-id>/{results.json,report.md,score.json,events/,sessions/}` and `out/history/`. |

## Run

```sh
node evals/run.mjs --smoke --dry-run                 # show the plan, spend nothing
node evals/run.mjs --smoke                           # 5 questions, installed configuration
node evals/run.mjs --ids gk-succession,ffp-room      # chosen questions
node evals/run.mjs --all --label full                # all 39 (expensive)
node evals/run.mjs --smoke --model openai-codex/other --label model-b
node evals/run.mjs --smoke --launcher /path/to/variant-pi-fm --env PI_FM_MCP_LAUNCHER=/path/run_mcp.sh --label variant
node evals/run.mjs --smoke --env PI_FM_MCP_LAUNCHER="$PWD/evals/run_reader_from.sh" \
  --env FM_READER_CHECKOUT=/path/to/reader-worktree --label worktree-reader
node evals/run.mjs --reparse <run-id>                # recompute metrics from saved events, free
node evals/score.mjs --latest -v                     # score the newest run
node evals/score.mjs --compare <runA> <runB>         # latency, tokens, calls, pass/fail per question
node evals/history.mjs                               # baseline from existing sessions
```

Options: `--timeout SEC` (default 420), `--concurrency N` (default 1; the FM reader is shared, keep it at 1),
`--no-session` (default is to save each session JSONL in the run's private `sessions/`), `--env KEY=VAL`
(repeatable), `--model` (sets `PI_FM_MODEL`), `--launcher` (default: the `bin/pi-fm` next to this `evals/`
directory, that is the checkout under test, not the installed copy), `--run-id`, `--label`. Run the commands from the
`adviser/` directory.

## Reader from a worktree

A git worktree of the reader repository has no `.venv`. `run_reader_from.sh` runs the main checkout's
`.venv/bin/python -m fm_live_mcp.server` with `PYTHONPATH` and the working directory set to another checkout. pi-fm
starts its reader as `/bin/sh "$PI_FM_MCP_LAUNCHER"` with no arguments, so name the checkout with
`FM_READER_CHECKOUT` (or pass it as the first argument when running the script by hand). With neither, it serves the
checkout that contains the script. `FM_READER_PYTHON` overrides the interpreter.

Sessions are written to `evals/out/<run-id>/sessions` through `PI_FM_SESSION_DIR`, so the project's `sessions/`
history is not polluted. If the first invocation fails to attach to the game (`task_for_pid_failed`, reader
missing) the batch stops immediately and no further quota is spent; the error is in `results.json` and
`report.md`. A timeout, crash or empty answer is recorded and the batch continues.

## Metrics per question

- `status`: `answered`, `timeout`, `error` (non-zero exit, provider error or aborted) or `empty` (finished without text).
- `wallMs`, `timeToFirstToolMs` (from process start, so it includes pi and reader start-up), `timeToFirstEventMs`.
- `modelTurns`: assistant messages. `toolCallsOuter`: calls the model made (`codemode`, `fm_read_skill`, ...).
  `toolCallsNested`: FM calls made inside Code Mode scripts, which the JSON stream reports as their own events with
  ids `<outer id>/<n>`. `toolCallsTotal` = nested calls + direct non-codemode calls.
- `toolErrors`: outer or nested calls with `isError`, or a Code Mode script that failed, with the message.
- `truncations`: "truncated output (original token count: N)" notices seen in tool results.
- `usage`: input (uncached), output, cacheRead, cacheWrite, total, cost when the provider reports it, the largest context seen,
  and `firstCallInput`: the prompt size of the first model call (system prompt, tool declarations and question).
- `finalAnswer`: text of the last assistant message. `stopReason`, `exitCode`, `signal`, `attachFailure`.

`events/<id>.jsonl` keeps every non-delta event with long strings clipped to 3000 characters, so `--reparse` can
recompute everything without a model call.

## Scoring

Before the first question `run.mjs` runs `facts.mjs` against the same reader (`--no-facts` skips it). A check whose
pattern contains `{{key}}` takes that value from the run's `facts.json`, so checks follow the game date as the owner
plays; a missing fact turns the check soft and the detail names it.

`score.mjs` runs only deterministic checks from each question's `checks` list: regex counts, distinct name-like
phrases (a heuristic for named players: capitalised multi-word phrases minus a stop list), table or list rows,
first-N-character cues, a stated game date, minimum and maximum length (`minChars`, `maxChars`), forbidden patterns,
and `transcript` (rule `noHiddenFullView`: no `fm_db_query` outside the manager view that reads transfer values,
ability, clauses, position ratings or club money without scoping to the managed club; other clubs' wages and contract
expiry are public since 1.4.0. Rule `usedSource`: some reader call's tool name, SQL or Code Mode script matches
`pattern`, so an answer that guessed instead of reading fails). Soft checks are reported but do not
fail a question. A generic check fails any answer that asks for screenshots or says it cannot attach files. A
question passes when it was answered and no hard check fails. These checks find structural gaps (no ages, no date,
invented board confidence); they do not judge whether the football advice is right. Read `report.md` for that.

The `required` text in `questions.json` is the human rubric for the parts a regex cannot decide. Player names in
prompts (Kobel, Hjulmand) come from the real Newcastle career and may need updating as the save moves on.

## History baseline

`history.mjs` splits each session into turns (user message through to the next user message) and computes wall
time, time to first tool call, model turns, tool calls, errors, truncations and tokens. Wall time excludes the
user's thinking time between turns. Output: `out/history/summary.json` and `summary.md`.

## Run of 12 November 2026 (adviser 1.3.0)

Reader `p1/integration` bbc47be (on-demand columns, match tables), game date 13 December 2030, private cache
`fmdb-20261111/cache-pifm`, model `openai-codex/gpt-6-astra`. Run `2026-11-12T01-38-01Z-full-v3b` (28 questions) and
rerun `2026-11-12T02-22-30Z-rerun-v3b` under `fmdb-20261111/evals-out/`.

| | 1.2.0 (`full-v2`, 22 questions) | 1.3.0, same 22 | 1.3.0, all 28 |
|---|---:|---:|---:|
| Mean model turns per answer | 10.4 | 6.0 | 6.0 |
| Median wall time | 85 s | 73 s | 71 s |
| Tokens (mean per answer) | 5.64M (256K) | 2.41M (109K) | 2.96M (106K) |
| Cost | $17.41 | $8.06 | $9.97 |
| Tool calls / errors | 308 / 19 | 126 / 13 | 159 / 15 |
| First model call | 12.1K | 10.0K | 10.0K |

25 of 28 passed on the first run after three check cues were corrected (decision-first accepted "Prioritise"; the
match-day XI counts squad surnames; benchmarks accept a named peer). Two real failures passed on rerun: the opposition
scout (reader calls timed out while the owner played the match) and the report question (the final message held only
the file path; the prompt now requires the full answer with the path). `club-vision` still fails: the
`fm_get_club_vision_progress` result carries objective importance only as a number (`importance_value`), not the
screen's words. The three fog-of-war questions read nothing hidden through the full view.

## Run of 12 November 2026 (adviser 1.4.0, eval set version 4)

Reader `r2/integration` 965275e (round 2: `m_` manager view over every table, histories, people, market and
match-state tables, `fm_get_ui_screen`; 197 tools), game date 13 December 2030 with West Ham v Newcastle loaded,
private cache `fmdb-20261111/cache-r5-pifm2`, model `openai-codex/gpt-6-astra`. Runs under `fmdb-20261111/evals-out/`:
`2026-11-12T06-35-08Z-v4-first` (rating-why), `2026-11-12T06-38-01Z-v4-full` (the other 38),
`2026-11-12T07-17-18Z-v4-rerun` and `2026-11-12T07-19-51Z-v4-rerun2` (rating-why). 41 invocations.

| | 1.3.0 (`full-v3b`), 28 questions | 1.4.0, same 28 | 1.4.0, 11 new | 1.4.0, all 39 |
|---|---:|---:|---:|---:|
| Mean model turns | 6.0 | 5.9 | 3.6 | 5.2 |
| Median wall time | 73 s | 61 s | 37 s | 48 s |
| Tokens (per answer) | 2.96M (106K) | 3.07M (110K) | 0.55M (50K) | 3.61M (93K) |
| Cost | $9.97 | $11.08 | $1.93 | $13.01 |
| Tool calls / errors | 159 / 15 | 197 / 8 | 29 / 0 | 226 / 8 |
| First model call | 10.1K | 11.9K | 11.8K | 11.9K |
| Passing checks | 27 of 28 (25 first run) | 26 of 28 | 11 of 11 (10 first run) | 37 of 39 |

On the 22 older questions: 5.8 turns and 108K tokens an answer (1.3.0: 6.0 and 109K).

The first rating-why answer explained the latest archived match because `fm_get_match(team: "Newcastle")` failed
(reader: "SQL is longer than 20000 characters") and `match_rating_component` carries no match identity; the prompt now
says the loaded match is the latest until archived and names the full club name, and the rerun explained Karetsas's
6.26 at West Ham from its components. Three check fixes, applied to the saved run before rescoring: `first[- ]choice`
in gk-succession, case-insensitive first words for the finance categories, and the rating facts aggregated in SQL
(the 100-row cap had dropped players; the old value regex matched "6.55" for "6.5"). The two remaining failures are
check heuristics on good answers: last-match-review names players by surname only (the `names` check counts
multi-word phrases) and sell-to-fund-lb has a two-row table (the check wants three). club-vision now passes (the
reader returns the importance words).
