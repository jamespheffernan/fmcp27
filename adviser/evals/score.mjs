#!/usr/bin/env node
// Deterministic scoring of eval runs. No model calls.
//
//   node evals/score.mjs <runId> [<runId> ...]       summary line per run (+ per-question table with -v)
//   node evals/score.mjs --compare <runA> <runB>     side-by-side diff
//   node evals/score.mjs --latest                    score the newest run in evals/out
//   node evals/score.mjs --list                      list runs
//
// A run id is a directory name under evals/out/ or a path to a run directory (or its results.json).
// Scoring writes score.json next to results.json.
//
// Per question: status (answered | timeout | error | empty), the machine-checkable elements stored in
// questions.json ('checks'), plus generic checks: non-empty answer, no request for screenshots or
// statements that it cannot attach. A question passes when it was answered and every hard check passes.
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { EVALS_DIR, sum, median, fmtSec, fmtK, fmtUsd, asksForScreenshot, DATE_RE, NAME_RE, mdEscape } from './lib.mjs';

const OUT = path.join(EVALS_DIR, 'out');
const questions = new Map(JSON.parse(fs.readFileSync(path.join(EVALS_DIR, 'questions.json'), 'utf8')).questions.map(q => [q.id, q]));

// Capitalised word pairs that look like names but are not players.
const NOT_NAMES = new Set([
  'premier league', 'champions league', 'league cup', 'fa cup', 'europa league', 'conference league', 'newcastle united',
  'manchester united', 'manchester city', 'regular starter', 'key player', 'important player', 'star player', 'first team',
  'saint james', 'st james', 'football manager', 'game date', 'financial fair', 'fair play', 'right back', 'left back',
  'centre back', 'center back', 'central midfield', 'attacking midfielder', 'defensive midfielder', 'key takeaways',
  'final answer', 'next step', 'next steps', 'tier list', 'what i', 'my pick', 'bottom line', 'transfer budget', 'wage budget',
  'code mode', 'save date', 'north london', 'real madrid', 'bayern munich', 'aston villa', 'sheffield united', 'west ham',
  'crystal palace', 'nottingham forest', 'tottenham hotspur', 'leicester city', 'leeds united', 'brighton hove',
]);

function distinctNames(text) {
  const found = new Set();
  for (const m of text.matchAll(NAME_RE)) {
    const n = m[0].replace(/[.,]+$/, '').trim();
    const low = n.toLowerCase();
    if (NOT_NAMES.has(low)) continue;
    if (n.split(/\s+/).length > 4) continue;
    found.add(low);
  }
  return found;
}

function countRows(text) {
  const lines = text.split('\n');
  const table = lines.filter(l => /^\s*\|.*\|\s*$/.test(l) && !/^\s*\|[\s:|-]+\|\s*$/.test(l)).length;
  const list = lines.filter(l => /^\s*(?:[-*]|\d+[.)])\s+\S/.test(l)).length;
  return Math.max(table > 0 ? table - 1 : 0, list);
}

// Facts read at run time (evals/facts.mjs -> <run>/facts.json) fill {{key}} in a check's pattern.
function withFacts(check, facts) {
  if (typeof check.pattern !== 'string' || !check.pattern.includes('{{')) return { check };
  const missing = [];
  // A missing fact never matches and makes the check soft: the run cannot judge it.
  const pattern = check.pattern.replace(/\{\{(\w+)\}\}/g, (_m, key) => {
    const v = facts?.[key];
    if (v === undefined || v === null || v === '') { missing.push(key); return '(?!)'; }
    return `(?:${v})`;
  });
  if (missing.length && check.type === 'notRegex') return { check: { ...check, pattern: '(?!)' }, missing };
  return { check: { ...check, pattern, soft: check.soft || missing.length > 0 }, missing };
}

// Hidden columns of players and clubs: reading them for rows outside the managed club through the
// full view is the silent leak the prompt forbids unless the user asked for actual values. Since
// adviser 1.4.0 (reader round 2) another club's player's wage and contract expiry are public (the
// game shows them on his profile), so they are not listed; clauses, position ratings, transfer
// values, ability and club money are.
const HIDDEN_COLS = /\b(?:transfer_value|current_ability|potential_ability|balance|transfer_budget|wage_budget|remaining_wage_budget(?:_weekly)?|wage_budget_weekly|wage_spend_weekly|amount_raw|clause_count|contract_clause\w*|pos_[a-z_]+)\b/i;
const OWN_SCOPE = /_managed|own_club\s*=\s*1/i;
export function hiddenFullViewQueries(events) {
  const out = [];
  for (const ev of events) {
    if (ev.type !== 'tool_execution_start' || !/fm_db_query$/.test(ev.toolName ?? '')) continue;
    const sql = String(ev.args?.sql ?? '');
    if (ev.args?.view === 'manager' || !HIDDEN_COLS.test(sql) || OWN_SCOPE.test(sql)) continue;
    out.push(sql.replace(/\s+/g, ' ').slice(0, 200));
  }
  return out;
}

/** Tool names and SQL text of every reader call in a transcript, for the `usedSource` rule. */
export function sourcesUsed(events) {
  return events.filter(ev => ev.type === 'tool_execution_start')
    .map(ev => `${ev.toolName ?? ''} ${typeof ev.args?.sql === 'string' ? ev.args.sql : ''} ${typeof ev.args?.code === 'string' ? ev.args.code : ''}`)
    .join('\n');
}

function runCheck(check, text, ctx = {}) {
  const flags = check.flags ?? '';
  let ok = false, detail = '';
  switch (check.type) {
    case 'maxChars': { ok = text.length <= check.max; detail = `${text.length} chars, limit ${check.max}`; break; }
    case 'transcript': {
      if (!ctx.events) { ok = true; detail = 'no events file'; break; }
      if (check.rule === 'usedSource') {
        const m = sourcesUsed(ctx.events).match(new RegExp(check.pattern, 'i'));
        ok = !!m; detail = m ? `read ${m[0]}` : `no call matched ${check.pattern}`;
        break;
      }
      const bad = hiddenFullViewQueries(ctx.events);
      ok = bad.length === 0; detail = ok ? 'clean' : `${bad.length} full-view hidden read(s): ${bad[0]}`;
      break;
    }
    case 'regex': {
      const re = new RegExp(check.pattern, flags.includes('g') ? flags : flags + 'g');
      const n = [...text.matchAll(re)].length;
      const min = check.min ?? 1;
      ok = n >= min; detail = `${n} match(es), need ${min}`;
      break;
    }
    case 'notRegex': {
      const re = new RegExp(check.pattern, flags);
      const hit = text.match(re);
      ok = !hit; detail = hit ? `found: ${hit[0].slice(0, 80)}` : 'absent';
      break;
    }
    case 'names': { const n = distinctNames(text).size; ok = n >= check.min; detail = `${n} distinct name-like phrase(s), need ${check.min}`; break; }
    case 'rows': { const n = countRows(text); ok = n >= check.min; detail = `${n} row(s), need ${check.min}`; break; }
    case 'firstChars': { const head = text.slice(0, check.chars ?? 400); ok = new RegExp(check.pattern, flags).test(head); detail = `in first ${check.chars ?? 400} chars`; break; }
    case 'date': { const m = text.match(DATE_RE); ok = !!m; detail = m ? m[0] : 'no date found'; break; }
    case 'minChars': { ok = text.length >= check.min; detail = `${text.length} chars, need ${check.min}`; break; }
    default: detail = `unknown check type ${check.type}`;
  }
  return { id: check.id, desc: check.desc ?? '', ok, soft: !!check.soft, detail };
}

export function scoreResult(r, { facts = null, events = null } = {}) {
  const q = questions.get(r.id);
  // Typographic apostrophes and quotes (can’t, “x”) would otherwise defeat the ASCII patterns.
  const text = (r.finalAnswer ?? '').replace(/[\u2018\u2019]/g, "'").replace(/[\u201c\u201d]/g, '"');
  const answered = r.status === 'answered' && text.trim().length > 0;
  const checks = [];
  if (q && answered) for (const c0 of q.checks ?? []) {
    const { check: c, missing } = withFacts(c0, facts);
    const res = runCheck(c, text, { events });
    if (missing?.length) res.detail += `; facts missing: ${missing.join(', ')}`;
    checks.push(res);
  }
  const screenshot = answered && asksForScreenshot(text);
  const generic = [{ id: 'no-screenshot-ask', desc: 'does not ask for screenshots or say it cannot attach', ok: !screenshot, soft: false, detail: screenshot ? 'mentions screenshots or attach limits' : 'clean' }];
  const hardFailed = [...checks, ...generic].filter(c => !c.ok && !c.soft);
  const softFailed = [...checks].filter(c => !c.ok && c.soft);
  return {
    id: r.id, status: r.status, answered, pass: answered && hardFailed.length === 0,
    checksPassed: checks.filter(c => c.ok).length, checksTotal: checks.length,
    failed: hardFailed.map(c => c.id), softFailed: softFailed.map(c => c.id), checks: [...checks, ...generic],
    toolErrors: (r.toolErrors ?? []).length, truncations: (r.truncations ?? []).length,
    screenshotFlag: screenshot, wallMs: r.wallMs, toolCalls: r.toolCallsTotal, outerCalls: sum(Object.values(r.toolCallsOuter ?? {})),
    tokens: r.usage?.total ?? null, firstCallInput: r.usage?.firstCallInput ?? null, cost: r.usage?.cost ?? null, modelTurns: r.modelTurns,
  };
}

function resolveRun(arg) {
  let dir = arg;
  if (arg.endsWith('results.json')) dir = path.dirname(arg);
  if (!fs.existsSync(path.join(dir, 'results.json'))) dir = path.join(OUT, arg);
  if (!fs.existsSync(path.join(dir, 'results.json'))) throw new Error(`No results.json for run "${arg}"`);
  const doc = JSON.parse(fs.readFileSync(path.join(dir, 'results.json'), 'utf8'));
  return { dir, id: doc.config?.runId ?? path.basename(dir), doc };
}
function listRuns() {
  return fs.existsSync(OUT) ? fs.readdirSync(OUT).filter(d => fs.existsSync(path.join(OUT, d, 'results.json'))).sort() : [];
}

function readEvents(dir, r) {
  const file = path.join(dir, r.eventsFile ?? path.join('events', `${r.id}.jsonl`));
  if (!fs.existsSync(file)) return null;
  return fs.readFileSync(file, 'utf8').split('\n').filter(Boolean).map(l => { try { return JSON.parse(l); } catch { return null; } }).filter(Boolean);
}

function scoreRun(run) {
  const factsFile = path.join(run.dir, 'facts.json');
  const facts = fs.existsSync(factsFile) ? JSON.parse(fs.readFileSync(factsFile, 'utf8')) : null;
  const scores = run.doc.results.map(r => scoreResult(r, { facts, events: readEvents(run.dir, r) }));
  const answered = scores.filter(s => s.answered);
  const summary = {
    runId: run.id, model: run.doc.config?.model, questions: scores.length, answered: answered.length,
    timeouts: scores.filter(s => s.status === 'timeout').length, errors: scores.filter(s => s.status === 'error' || s.status === 'empty').length,
    passed: scores.filter(s => s.pass).length,
    medianWallSec: median(answered.map(s => s.wallMs)) != null ? median(answered.map(s => s.wallMs)) / 1000 : null,
    toolCalls: sum(scores.map(s => s.toolCalls)), toolErrors: sum(scores.map(s => s.toolErrors)),
    truncations: sum(scores.map(s => s.truncations)), screenshotFlags: scores.filter(s => s.screenshotFlag).length,
    tokens: sum(scores.map(s => s.tokens)), cost: scores.some(s => s.cost != null) ? sum(scores.map(s => s.cost)) : null,
  };
  fs.writeFileSync(path.join(run.dir, 'score.json'), JSON.stringify({ summary, scores }, null, 2));
  return { summary, scores };
}

function summaryLine(s) {
  return `${s.runId}: ${s.passed}/${s.questions} pass, ${s.answered} answered, ${s.timeouts} timeout, ${s.errors} error; median ${s.medianWallSec != null ? s.medianWallSec.toFixed(0) + 's' : '-'}; ${s.toolCalls} tool calls, ${s.toolErrors} tool errors, ${s.truncations} truncations; ${fmtK(s.tokens)} tokens${s.cost != null ? ', ' + fmtUsd(s.cost) : ''}; screenshot flags ${s.screenshotFlags}`;
}

function perQuestionTable(scores) {
  let t = '| Id | Status | Pass | Checks | Failed hard | Soft misses | Wall | Calls | Tool errs | Trunc | Tokens |\n|---|---|---|---:|---|---|---:|---:|---:|---:|---:|\n';
  for (const s of scores) t += `| ${s.id} | ${s.status} | ${s.pass ? 'PASS' : 'FAIL'} | ${s.checksPassed}/${s.checksTotal} | ${s.failed.join(', ') || '-'} | ${s.softFailed.join(', ') || '-'} | ${fmtSec(s.wallMs)} | ${s.toolCalls} | ${s.toolErrors} | ${s.truncations} | ${fmtK(s.tokens)} |\n`;
  return t;
}

function delta(a, b, fmt0 = x => String(x), pct = true) {
  const fmt = x => (x == null || Number.isNaN(x) ? '-' : fmt0(x));
  if (a == null || b == null || !Number.isFinite(a) || !Number.isFinite(b)) return `${fmt(a)} -> ${fmt(b)}`;
  const d = b - a;
  const p = pct && a !== 0 ? ` (${d >= 0 ? '+' : ''}${((d / a) * 100).toFixed(0)}%)` : '';
  return `${fmt(a)} -> ${fmt(b)}${p}`;
}

function compare(runA, runB) {
  const A = scoreRun(runA), B = scoreRun(runB);
  const ids = [...new Set([...A.scores.map(s => s.id), ...B.scores.map(s => s.id)])];
  const get = (X, id) => X.scores.find(s => s.id === id);
  let t = `Compare ${runA.id} (A) vs ${runB.id} (B)\n\n`;
  t += `A: ${summaryLine(A.summary)}\nB: ${summaryLine(B.summary)}\n\n`;
  t += '| Id | Result A -> B | Latency | Tool calls | Tool errors | Tokens | First-call input | Checks |\n|---|---|---|---|---|---|---|---|\n';
  for (const id of ids) {
    const a = get(A, id), b = get(B, id);
    const res = x => (x ? (x.pass ? 'PASS' : `FAIL(${x.status === 'answered' ? x.failed.join('+') || 'ok' : x.status})`) : 'n/a');
    t += `| ${id} | ${res(a)} -> ${res(b)} | ${delta(a?.wallMs, b?.wallMs, fmtSec)} | ${delta(a?.toolCalls, b?.toolCalls)} | ${delta(a?.toolErrors, b?.toolErrors, String, false)} | ${delta(a?.tokens, b?.tokens, fmtK)} | ${delta(a?.firstCallInput, b?.firstCallInput, fmtK)} | ${a ? `${a.checksPassed}/${a.checksTotal}` : '-'} -> ${b ? `${b.checksPassed}/${b.checksTotal}` : '-'} |\n`;
  }
  const sa = A.summary, sb = B.summary;
  t += `| **Total** | ${sa.passed}/${sa.questions} -> ${sb.passed}/${sb.questions} | median ${delta(sa.medianWallSec != null ? sa.medianWallSec * 1000 : null, sb.medianWallSec != null ? sb.medianWallSec * 1000 : null, fmtSec)} | ${delta(sa.toolCalls, sb.toolCalls)} | ${delta(sa.toolErrors, sb.toolErrors, String, false)} | ${delta(sa.tokens, sb.tokens, fmtK)} | - | - |\n`;
  const same = ids.filter(id => get(A, id) && get(B, id));
  const regress = same.filter(id => get(A, id).pass && !get(B, id).pass), fixed = same.filter(id => !get(A, id).pass && get(B, id).pass);
  t += `\nRegressions (pass -> fail): ${regress.join(', ') || 'none'}\nImprovements (fail -> pass): ${fixed.join(', ') || 'none'}\n`;
  return t;
}

// ---------------- main ----------------
// Importing this module (tests) runs nothing; the command line below runs only as a script.
const exitWith = code => process.exit(code);
if (process.argv[1] && fileURLToPath(import.meta.url) === path.resolve(process.argv[1])) main();
function main() {
  const argv = process.argv.slice(2);
  if (!argv.length || argv.includes('--help')) {
    console.log(fs.readFileSync(new URL(import.meta.url), 'utf8').split('\n').filter(l => l.startsWith('//')).map(l => l.slice(3)).join('\n'));
    exitWith(argv.length ? 0 : 2);
  }
  if (argv[0] === '--list') { console.log(listRuns().join('\n')); exitWith(0); }
  if (argv[0] === '--compare') {
    if (argv.length < 3) { console.error('--compare needs two runs'); exitWith(2); }
    console.log(compare(resolveRun(argv[1]), resolveRun(argv[2])));
    exitWith(0);
  }
  const verbose = argv.includes('-v') || argv.includes('--verbose');
  const runArgs = argv[0] === '--latest' ? [listRuns().filter(r => !r.startsWith('test-') && r !== 'history').pop()].filter(Boolean) : argv.filter(a => !a.startsWith('-'));
  if (!runArgs.length) { console.error('No runs found in evals/out'); exitWith(1); }
  for (const a of runArgs) {
    const run = resolveRun(a);
    const { summary, scores } = scoreRun(run);
    console.log(summaryLine(summary));
    if (verbose) { console.log('\n' + perQuestionTable(scores)); for (const s of scores) for (const c of s.checks.filter(c => !c.ok)) console.log(`  ${s.id}: ${c.soft ? 'soft ' : ''}miss ${c.id} - ${c.desc} (${c.detail})`); }
  }
}
