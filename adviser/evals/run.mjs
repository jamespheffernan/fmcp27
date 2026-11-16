#!/usr/bin/env node
// Headless pi-fm evaluation runner.
//
//   node evals/run.mjs --smoke                 5 cheapest/most representative questions
//   node evals/run.mjs --ids gk-succession,ffp-room
//   node evals/run.mjs --all                   every question (16 model runs: spends quota)
//   node evals/run.mjs --smoke --dry-run       print the plan, spend nothing
//
// Options:
//   --timeout SEC        per-question timeout (default 420)
//   --model ID           sets PI_FM_MODEL for the run
//   --env KEY=VAL        extra environment variable (repeatable), e.g. PI_FM_MCP_LAUNCHER=/path; to serve the
//                        reader from a worktree: --env PI_FM_MCP_LAUNCHER=<adviser>/evals/run_reader_from.sh
//                        --env FM_READER_CHECKOUT=<worktree>
//   --launcher PATH      launcher to run (default: this checkout's adviser/bin/pi-fm, not the installed copy)
//   --label NAME         suffix for the run id (default: smoke | all | ids)
//   --run-id ID          explicit run id (default: <UTC timestamp>-<label>)
//   --concurrency N      parallel questions (default 1; the FM reader is shared, keep at 1)
//   --no-session         pass --no-session (default: save sessions to the private dir)
//   --max-invocations N  refuse to start more than N pi-fm runs in this process (default: no limit)
//   --out DIR            parent directory for run folders (default: evals/out); sessions go inside the run folder
//   --reparse RUNID      recompute metrics for an existing run from its events files (no model calls)
//   --continue-on-attach-failure   do not abort the batch when the first run fails to attach to the game
//   --no-facts           skip the ground-truth pre-step (evals/facts.mjs writes <run>/facts.json from the reader)
//
// Each question is one `pi-fm --mode json --print "<prompt>"` with stdin closed.
import fs from 'node:fs';
import path from 'node:path';
import { spawn, spawnSync } from 'node:child_process';
import { StringDecoder } from 'node:string_decoder';
import {
  EVALS_DIR, PROJECT_DIR, median, sum, fmtSec, fmtK, fmtUsd, mdEscape, assistantText, emptyUsage, addUsage,
  EventAccumulator, clipDeep,
} from './lib.mjs';

// ---------------- args ----------------
const argv = process.argv.slice(2);
const flags = new Set();
const opts = {};
const envPairs = [];
for (let i = 0; i < argv.length; i++) {
  const a = argv[i];
  if (!a.startsWith('--')) continue;
  const key = a.slice(2);
  if (['smoke', 'all', 'dry-run', 'no-session', 'continue-on-attach-failure', 'help', 'no-facts'].includes(key)) { flags.add(key); continue; }
  const val = argv[++i];
  if (key === 'env') envPairs.push(val); else opts[key] = val;
}
const OUT_ROOT = opts.out ? path.resolve(opts.out) : path.join(EVALS_DIR, 'out');
// --reparse RUNID: recompute metrics for an existing run from its saved events files (no model calls).
if (opts.reparse) {
  const dir = path.join(OUT_ROOT, opts.reparse);
  const doc = JSON.parse(fs.readFileSync(path.join(dir, 'results.json'), 'utf8'));
  for (const r of doc.results) {
    const file = path.join(dir, 'events', `${r.id}.jsonl`);
    if (!fs.existsSync(file)) continue;
    const acc = new EventAccumulator();
    for (const line of fs.readFileSync(file, 'utf8').split('\n')) {
      if (!line.trim()) continue;
      try { const ev = JSON.parse(line); acc.handle(ev, ev.t ?? 0); } catch { /* skip */ }
    }
    Object.assign(r, { timeToFirstEventMs: acc.timeToFirstEventMs, timeToFirstToolMs: acc.timeToFirstToolMs, modelTurns: acc.modelTurns, eventCount: acc.eventCount, toolCallsOuter: acc.toolCallsOuter, toolCallsNested: acc.toolCallsNested, toolErrors: acc.toolErrors, truncations: acc.truncations });
    r.usage = acc.usageSummary();
    r.toolCallsTotal = acc.toolCallsTotal();
    if (acc.lastAssistant) { r.finalAnswer = assistantText(acc.lastAssistant); r.stopReason = acc.lastAssistant.stopReason ?? r.stopReason; }
  }
  doc.aggregate = aggregateOf(doc.results);
  doc.reparsedAt = new Date().toISOString();
  fs.writeFileSync(path.join(dir, 'results.json'), JSON.stringify(doc, null, 2));
  fs.writeFileSync(path.join(dir, 'report.md'), renderReport(doc));
  console.log(`Reparsed ${doc.results.length} result(s) in ${dir}`);
  process.exit(0);
}

if (flags.has('help') || (!flags.has('smoke') && !flags.has('all') && !opts.ids)) {
  console.log(fs.readFileSync(new URL(import.meta.url), 'utf8').split('\n').filter(l => l.startsWith('//')).map(l => l.slice(3)).join('\n'));
  process.exit(flags.has('help') ? 0 : 2);
}

const timeoutMs = Number(opts.timeout ?? 420) * 1000;
const concurrency = Math.max(1, Number(opts.concurrency ?? 1));
const maxInvocations = opts['max-invocations'] != null ? Number(opts['max-invocations']) : Infinity;
const launcher = path.resolve(opts.launcher ?? path.join(PROJECT_DIR, 'bin', 'pi-fm'));

const all = JSON.parse(fs.readFileSync(path.join(EVALS_DIR, 'questions.json'), 'utf8')).questions;
let selected;
if (flags.has('all')) selected = all;
else if (opts.ids) {
  const want = opts.ids.split(',').map(s => s.trim()).filter(Boolean);
  const missing = want.filter(id => !all.some(q => q.id === id));
  if (missing.length) { console.error(`Unknown question id(s): ${missing.join(', ')}`); process.exit(2); }
  selected = want.map(id => all.find(q => q.id === id));
} else selected = all.filter(q => q.smoke);

const label = opts.label ?? (flags.has('all') ? 'all' : opts.ids ? 'ids' : 'smoke');
const stamp = new Date().toISOString().replace(/[:.]/g, '-').replace(/-\d{3}Z$/, 'Z');
const runId = opts['run-id'] ?? `${stamp}-${label}`;
const runDir = path.join(OUT_ROOT, runId);
const sessionDir = path.join(runDir, 'sessions');
const eventsDir = path.join(runDir, 'events');

const extraEnv = {};
for (const p of envPairs) {
  const i = p.indexOf('=');
  if (i < 1) { console.error(`--env expects KEY=VAL, got: ${p}`); process.exit(2); }
  extraEnv[p.slice(0, i)] = p.slice(i + 1);
}
if (opts.model) extraEnv.PI_FM_MODEL = opts.model;

const config = {
  runId, label, startedAt: new Date().toISOString(), launcher, timeoutSec: timeoutMs / 1000, concurrency,
  model: extraEnv.PI_FM_MODEL ?? process.env.PI_FM_MODEL ?? '(launcher default)',
  envOverrides: extraEnv, noSession: flags.has('no-session'), questions: selected.map(q => q.id),
};

console.log(`Run ${runId}: ${selected.length} question(s), launcher ${launcher}, timeout ${timeoutMs / 1000}s, model ${config.model}`);
if (flags.has('dry-run')) {
  for (const q of selected) console.log(` - ${q.id} [${q.category}]: ${q.prompt}`);
  console.log('Dry run: nothing executed.');
  process.exit(0);
}
if (selected.length > maxInvocations) {
  console.error(`Refusing: ${selected.length} invocations requested but --max-invocations is ${maxInvocations}.`);
  process.exit(2);
}
fs.mkdirSync(sessionDir, { recursive: true });
fs.mkdirSync(eventsDir, { recursive: true });

// Ground truth for this run, read from the same reader the questions use (no model calls).
if (!flags.has('no-facts')) {
  const t0 = Date.now();
  const facts = spawnSync(process.execPath, [path.join(EVALS_DIR, 'facts.mjs'), '--out', runDir], {
    env: { ...process.env, ...extraEnv }, encoding: 'utf8', timeout: 900_000, maxBuffer: 16 * 1024 * 1024,
  });
  const file = path.join(runDir, 'facts.json');
  console.log(fs.existsSync(file) ? `Facts: ${file} (${((Date.now() - t0) / 1000).toFixed(0)} s; errors: ${Object.keys(JSON.parse(fs.readFileSync(file, 'utf8')).errors ?? {}).join(', ') || 'none'})` : `Facts pre-step failed: ${(facts.stderr || String(facts.error)).slice(-400)}`);
}

// ---------------- one invocation ----------------
const ATTACH_FAIL_RE = /task_for_pid[_ ]?failed|task_for_pid|FM live reader missing|Operation not permitted.*task/i;

function runOne(q) {
  return new Promise(resolve => {
    const startedAtIso = new Date().toISOString();
    const t0 = Date.now();
    const args = ['--mode', 'json', '--print'];
    if (flags.has('no-session')) args.push('--no-session');
    args.push(q.prompt);
    const env = { ...process.env, ...extraEnv, PI_FM_SESSION_DIR: sessionDir };

    const m = {
      id: q.id, category: q.category, prompt: q.prompt, startedAt: startedAtIso, status: 'error', timedOut: false,
      exitCode: null, signal: null, wallMs: null, timeToFirstEventMs: null, timeToFirstToolMs: null, modelTurns: 0,
      toolCallsOuter: {}, toolCallsNested: {}, toolCallsTotal: 0, toolErrors: [], truncations: [],
      usage: null, finalAnswer: '', stopReason: null, errorMessage: null, attachFailure: false, stderrTail: '',
      eventCount: 0, eventsFile: path.relative(runDir, path.join(eventsDir, `${q.id}.jsonl`)),
    };
    const acc = new EventAccumulator();
    const eventsStream = fs.createWriteStream(path.join(eventsDir, `${q.id}.jsonl`));
    const decoder = new StringDecoder('utf8');
    let buf = '';
    let stderr = '';
    let settled = false;
    let timer = null;

    let child;
    try {
      child = spawn(launcher, args, { env, stdio: ['ignore', 'pipe', 'pipe'], detached: true, cwd: PROJECT_DIR });
    } catch (err) {
      m.errorMessage = `spawn failed: ${err.message}`;
      m.wallMs = Date.now() - t0;
      eventsStream.end();
      return resolve(m);
    }

    const killGroup = sig => { try { process.kill(-child.pid, sig); } catch { try { child.kill(sig); } catch { /* gone */ } } };
    timer = setTimeout(() => {
      m.timedOut = true;
      killGroup('SIGTERM');
      setTimeout(() => killGroup('SIGKILL'), 5000).unref();
    }, timeoutMs);

    function handleEvent(ev) {
      const now = Date.now() - t0;
      acc.handle(ev, now);
      if (ev.type !== 'message_update') eventsStream.write(JSON.stringify({ t: now, ...clipDeep(ev) }) + '\n');
    }

    child.stdout.on('data', chunk => {
      buf += decoder.write(chunk);
      let nl;
      while ((nl = buf.indexOf('\n')) >= 0) {
        let line = buf.slice(0, nl);
        buf = buf.slice(nl + 1);
        if (line.endsWith('\r')) line = line.slice(0, -1);
        if (!line.trim()) continue;
        try { handleEvent(JSON.parse(line)); } catch { /* non-JSON noise */ }
      }
    });
    child.stderr.on('data', chunk => { stderr += chunk.toString('utf8'); if (stderr.length > 200000) stderr = stderr.slice(-100000); });

    const finish = (code, signal, spawnErr) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      const rest = buf + decoder.end();
      if (rest.trim()) { try { handleEvent(JSON.parse(rest)); } catch { /* ignore */ } }
      eventsStream.end();
      m.exitCode = code; m.signal = signal;
      m.wallMs = Date.now() - t0;
      Object.assign(m, { timeToFirstEventMs: acc.timeToFirstEventMs, timeToFirstToolMs: acc.timeToFirstToolMs, modelTurns: acc.modelTurns, eventCount: acc.eventCount, toolCallsOuter: acc.toolCallsOuter, toolCallsNested: acc.toolCallsNested, toolErrors: acc.toolErrors, truncations: acc.truncations });
      m.usage = acc.usageSummary();
      m.toolCallsTotal = acc.toolCallsTotal();
      m.stderrTail = stderr.slice(-4000);
      if (spawnErr) m.errorMessage = `spawn error: ${spawnErr.message}`;
      if (acc.lastAssistant) {
        m.finalAnswer = assistantText(acc.lastAssistant);
        m.stopReason = acc.lastAssistant.stopReason ?? null;
        if (acc.lastAssistant.errorMessage) m.errorMessage = acc.lastAssistant.errorMessage;
      }
      const hay = `${stderr}\n${m.errorMessage ?? ''}\n${m.toolErrors.map(e => e.message).join('\n')}`;
      m.attachFailure = ATTACH_FAIL_RE.test(hay);
      if (m.timedOut) m.status = 'timeout';
      else if (m.finalAnswer && m.stopReason !== 'error' && m.stopReason !== 'aborted' && code === 0) m.status = 'answered';
      else if (m.finalAnswer && code === 0) m.status = 'error';
      else m.status = m.finalAnswer ? 'error' : (code === 0 && acc.sawAgentEnd ? 'empty' : 'error');
      if (m.status !== 'answered' && !m.errorMessage) {
        m.errorMessage = m.status === 'timeout' ? `timed out after ${timeoutMs / 1000}s` : `exit ${code ?? signal}; ${stderr.trim().split('\n').slice(-3).join(' | ').slice(0, 300)}`;
      }
      resolve(m);
    };
    child.on('error', err => finish(null, null, err));
    child.on('close', (code, signal) => finish(code, signal));
  });
}

// ---------------- batch ----------------
const results = [];
let invocations = 0;
let abortReason = null;

function writeOutputs() {
  const doc = { config, finishedAt: new Date().toISOString(), invocations, abortReason, aggregate: aggregateOf(results), results };
  fs.writeFileSync(path.join(runDir, 'results.json'), JSON.stringify(doc, null, 2));
  fs.writeFileSync(path.join(runDir, 'report.md'), renderReport(doc));
}

function aggregateOf(rs) {
  const done = rs.filter(r => r.status === 'answered');
  return {
    questions: rs.length, answered: done.length, timeouts: rs.filter(r => r.status === 'timeout').length,
    errors: rs.filter(r => r.status === 'error' || r.status === 'empty').length,
    wallSecMedian: median(done.map(r => r.wallMs)) != null ? median(done.map(r => r.wallMs)) / 1000 : null,
    wallSecTotal: sum(rs.map(r => r.wallMs)) / 1000,
    toolCallsTotal: sum(rs.map(r => r.toolCallsTotal)),
    toolErrorsTotal: sum(rs.map(r => r.toolErrors.length)),
    truncationsTotal: sum(rs.map(r => r.truncations.length)),
    tokensTotal: sum(rs.map(r => r.usage?.total)),
    costTotal: rs.some(r => r.usage?.cost != null) ? sum(rs.map(r => r.usage?.cost)) : null,
  };
}

function renderReport(doc) {
  const c = doc.config, a = doc.aggregate;
  let md = `# pi-fm eval run ${c.runId}\n\n`;
  md += `- Started ${c.startedAt}, finished ${doc.finishedAt}\n- Launcher \`${c.launcher}\`, model ${c.model}, timeout ${c.timeoutSec}s, ${doc.invocations} pi-fm invocation(s)\n`;
  if (Object.keys(c.envOverrides).length) md += `- Env overrides: ${Object.entries(c.envOverrides).map(([k, v]) => `\`${k}=${v}\``).join(', ')}\n`;
  if (doc.abortReason) md += `- **Aborted:** ${doc.abortReason}\n`;
  md += `- Answered ${a.answered}/${a.questions}; timeouts ${a.timeouts}; errors ${a.errors}; median wall ${a.wallSecMedian != null ? a.wallSecMedian.toFixed(0) + 's' : '-'}; tool calls ${a.toolCallsTotal}; tool errors ${a.toolErrorsTotal}; truncations ${a.truncationsTotal}; tokens ${fmtK(a.tokensTotal)}${a.costTotal != null ? '; cost ' + fmtUsd(a.costTotal) : ''}\n\n`;
  md += `| Id | Status | Wall | 1st tool | Model turns | Tool calls (outer/FM) | Errors | Trunc | Tokens (in/out/cache) | Cost | Answer chars |\n|---|---|---:|---:|---:|---:|---:|---:|---|---:|---:|\n`;
  for (const r of doc.results) {
    const outer = sum(Object.values(r.toolCallsOuter));
    const fm = sum(Object.values(r.toolCallsNested));
    md += `| ${r.id} | ${r.status} | ${fmtSec(r.wallMs)} | ${fmtSec(r.timeToFirstToolMs)} | ${r.modelTurns} | ${outer}/${fm} | ${r.toolErrors.length} | ${r.truncations.length} | ${r.usage ? `${fmtK(r.usage.input)}/${fmtK(r.usage.output)}/${fmtK(r.usage.cacheRead)}` : '-'} | ${fmtUsd(r.usage?.cost)} | ${r.finalAnswer.length} |\n`;
  }
  for (const r of doc.results) {
    md += `\n---\n\n## ${r.id} (${r.category}) - ${r.status}\n\n**Prompt:** ${r.prompt}\n\n`;
    const names = Object.entries({ ...r.toolCallsNested, ...Object.fromEntries(Object.entries(r.toolCallsOuter).filter(([k]) => k !== 'codemode').map(([k, v]) => [k, (r.toolCallsNested[k] || 0) + v])) }).sort((x, y) => y[1] - x[1]);
    md += `**Tools:** outer ${JSON.stringify(r.toolCallsOuter)}; FM calls inside codemode ${names.length ? names.map(([k, v]) => `${k.replace('mcp__fm_live__', '')} x${v}`).join(', ') : 'none'}\n\n`;
    if (r.toolErrors.length) md += `**Tool errors:**\n${r.toolErrors.map(e => `- ${e.tool}${e.nestedIn ? ` (in ${e.nestedIn})` : ''}: ${mdEscape(e.message)}`).join('\n')}\n\n`;
    if (r.truncations.length) md += `**Truncation notices:** ${r.truncations.map(t => `${t.tool}${t.tokens ? ` (${t.tokens} tokens)` : ''}`).join(', ')}\n\n`;
    if (r.errorMessage) md += `**Error:** ${mdEscape(r.errorMessage)}\n\n`;
    md += `**Final answer:**\n\n${r.finalAnswer ? r.finalAnswer.split('\n').map(l => '> ' + l).join('\n') : '_(none)_'}\n`;
  }
  return md;
}

async function worker(queue) {
  while (queue.length && !abortReason) {
    const q = queue.shift();
    if (invocations >= maxInvocations) { abortReason = `max-invocations ${maxInvocations} reached`; break; }
    invocations += 1;
    console.log(`[${invocations}/${selected.length}] ${q.id} ...`);
    let r;
    try { r = await runOne(q); } catch (err) {
      r = { id: q.id, category: q.category, prompt: q.prompt, status: 'error', errorMessage: `runner exception: ${err.stack || err}`, wallMs: null, timeToFirstToolMs: null, modelTurns: 0, toolCallsOuter: {}, toolCallsNested: {}, toolCallsTotal: 0, toolErrors: [], truncations: [], usage: null, finalAnswer: '' };
    }
    results.push(r);
    // keep results in question order
    results.sort((x, y) => selected.findIndex(s => s.id === x.id) - selected.findIndex(s => s.id === y.id));
    writeOutputs();
    console.log(`    ${r.status} in ${fmtSec(r.wallMs)}; ${r.modelTurns} model turns; ${r.toolCallsTotal} tool calls; ${r.toolErrors.length} tool errors; ${fmtK(r.usage?.total)} tokens${r.errorMessage ? '; ' + r.errorMessage.slice(0, 160) : ''}`);
    if (r.attachFailure && !flags.has('continue-on-attach-failure') && results.length === 1 && r.status !== 'answered') {
      abortReason = 'first invocation failed to attach to the game (task_for_pid or reader missing); remaining questions not run, no further quota spent';
      console.error(`ABORT: ${abortReason}`);
    }
  }
}

const queue = [...selected];
const pool = Array.from({ length: Math.min(concurrency, queue.length) }, () => worker(queue));
await Promise.all(pool);
writeOutputs();
console.log(`Done. ${path.join(runDir, 'report.md')}`);
console.log(`Results: ${path.join(runDir, 'results.json')}`);
