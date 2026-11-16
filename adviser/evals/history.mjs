#!/usr/bin/env node
// Zero-cost baseline: analyse existing sessions/*.jsonl, one record per historical user turn.
//   node evals/history.mjs [--sessions DIR] [--out DIR]
// A "turn" = one user message through to the entry before the next user message.
import fs from 'node:fs';
import path from 'node:path';
import {
  EVALS_DIR, PROJECT_DIR, percentile, median, mean, sum, fmtSec, fmtK, fmtUsd, mdEscape, textOfContent,
  assistantText, assistantToolCalls, emptyUsage, addUsage, analyzeToolResult, asksForScreenshot,
} from './lib.mjs';

const argv = process.argv.slice(2);
const opt = (name, dflt) => { const i = argv.indexOf(name); return i >= 0 ? argv[i + 1] : dflt; };
const sessionsDir = path.resolve(opt('--sessions', path.join(PROJECT_DIR, 'sessions')));
const outDir = path.resolve(opt('--out', path.join(EVALS_DIR, 'out', 'history')));

const files = fs.readdirSync(sessionsDir).filter(f => f.endsWith('.jsonl')).sort();
const turns = [];

for (const file of files) {
  const entries = [];
  for (const line of fs.readFileSync(path.join(sessionsDir, file), 'utf8').split('\n')) {
    if (!line.trim()) continue;
    try { entries.push(JSON.parse(line)); } catch { /* skip bad line */ }
  }
  let cur = null;
  const flush = () => { if (cur) { finish(cur); turns.push(cur); cur = null; } };
  let idx = 0;
  for (const e of entries) {
    const m = e.type === 'message' ? e.message : null;
    const ts = Date.parse(e.timestamp);
    if (m?.role === 'user') {
      flush();
      cur = {
        session: file, turnIndex: idx++, question: textOfContent(m.content).trim(), startTs: ts, lastTs: ts,
        firstToolTs: null, modelTurns: 0, toolCalls: {}, nestedToolCalls: {}, errors: [], truncations: [],
        usage: emptyUsage(), finalAnswer: '', stopReason: null,
      };
      continue;
    }
    if (!cur) continue;
    if (e.type === 'compaction' || (m && m.role === 'system')) continue;
    if (Number.isFinite(ts) && ts > cur.lastTs) cur.lastTs = ts;
    if (m?.role === 'assistant') {
      cur.modelTurns += 1;
      addUsage(cur.usage, m.usage);
      const calls = assistantToolCalls(m);
      for (const c of calls) {
        cur.toolCalls[c.name] = (cur.toolCalls[c.name] || 0) + 1;
        if (cur.firstToolTs == null) cur.firstToolTs = ts;
      }
      const t = assistantText(m);
      if (t) cur.finalAnswer = t;               // keeps the last non-empty assistant text
      if (!calls.length) cur.finalAnswer = t;    // final message (no tool calls) wins even if empty
      cur.stopReason = m.stopReason ?? cur.stopReason;
    } else if (m?.role === 'toolResult') {
      const a = analyzeToolResult(m);
      for (const n of a.nested) cur.nestedToolCalls[n.name] = (cur.nestedToolCalls[n.name] || 0) + 1;
      cur.errors.push(...a.errors);
      cur.truncations.push(...a.truncations);
    }
  }
  flush();
}

function finish(t) {
  t.wallMs = t.lastTs - t.startTs;
  t.timeToFirstToolMs = t.firstToolTs != null ? t.firstToolTs - t.startTs : null;
  t.outerToolCalls = sum(Object.values(t.toolCalls));
  t.nestedToolCallCount = sum(Object.values(t.nestedToolCalls));
  t.hasAssistant = t.modelTurns > 0;
  t.askedForScreenshot = asksForScreenshot(t.finalAnswer);
  t.toolErrors = t.errors.length;
  t.truncationCount = t.truncations.length;
}

// Aggregate over turns that actually got a model response and ended in an answer.
const answered = turns.filter(t => t.hasAssistant && t.finalAnswer);
const withTools = answered.filter(t => t.outerToolCalls > 0);
const agg = {
  sessions: files.length,
  turnsTotal: turns.length,
  turnsAnswered: answered.length,
  turnsWithTools: withTools.length,
  wallSec: { median: median(answered.map(t => t.wallMs)) / 1000, p90: percentile(answered.map(t => t.wallMs), 90) / 1000, max: Math.max(...answered.map(t => t.wallMs)) / 1000, mean: mean(answered.map(t => t.wallMs)) / 1000 },
  timeToFirstToolSec: { median: median(withTools.map(t => t.timeToFirstToolMs)) / 1000, p90: percentile(withTools.map(t => t.timeToFirstToolMs), 90) / 1000 },
  modelTurnsPerTurn: { median: median(answered.map(t => t.modelTurns)), mean: mean(answered.map(t => t.modelTurns)), p90: percentile(answered.map(t => t.modelTurns), 90) },
  outerToolCallsPerTurn: { median: median(answered.map(t => t.outerToolCalls)), mean: mean(answered.map(t => t.outerToolCalls)), p90: percentile(answered.map(t => t.outerToolCalls), 90) },
  nestedFmCallsPerTurn: { median: median(answered.map(t => t.nestedToolCallCount)), mean: mean(answered.map(t => t.nestedToolCallCount)), p90: percentile(answered.map(t => t.nestedToolCallCount), 90) },
  toolErrors: { total: sum(answered.map(t => t.toolErrors)), turnsWithError: answered.filter(t => t.toolErrors).length, turnErrorRate: answered.filter(t => t.toolErrors).length / answered.length, perToolCallRate: sum(answered.map(t => t.toolErrors)) / Math.max(1, sum(answered.map(t => t.outerToolCalls))) },
  truncations: { total: sum(answered.map(t => t.truncationCount)), turnsWithTruncation: answered.filter(t => t.truncationCount).length, turnRate: answered.filter(t => t.truncationCount).length / answered.length },
  screenshotAskTurns: answered.filter(t => t.askedForScreenshot).length,
  tokensPerTurn: {
    inputMedian: median(answered.map(t => t.usage.input)), outputMedian: median(answered.map(t => t.usage.output)),
    cacheReadMedian: median(answered.map(t => t.usage.cacheRead)), totalMedian: median(answered.map(t => t.usage.total)),
    totalP90: percentile(answered.map(t => t.usage.total), 90), totalMean: mean(answered.map(t => t.usage.total)),
    maxContextMedian: median(answered.map(t => t.usage.maxInput)),
  },
  costPerTurnUsd: { median: median(answered.map(t => t.usage.cost)), mean: mean(answered.map(t => t.usage.cost)), total: sum(answered.map(t => t.usage.cost)), note: 'provider-reported or estimated cost carried in session usage; totalFromProvider may be false' },
  toolMix: Object.entries(turns.reduce((acc, t) => { for (const [k, v] of Object.entries(t.toolCalls)) acc[k] = (acc[k] || 0) + v; return acc; }, {})).sort((a, b) => b[1] - a[1]),
  nestedToolMix: Object.entries(turns.reduce((acc, t) => { for (const [k, v] of Object.entries(t.nestedToolCalls)) acc[k] = (acc[k] || 0) + v; return acc; }, {})).sort((a, b) => b[1] - a[1]).slice(0, 15),
};

fs.mkdirSync(outDir, { recursive: true });
const slim = turns.map(t => ({
  session: t.session, turnIndex: t.turnIndex, question: t.question, wallSec: +(t.wallMs / 1000).toFixed(1),
  timeToFirstToolSec: t.timeToFirstToolMs != null ? +(t.timeToFirstToolMs / 1000).toFixed(1) : null,
  modelTurns: t.modelTurns, toolCalls: t.toolCalls, nestedToolCalls: t.nestedToolCalls,
  toolErrors: t.toolErrors, errors: t.errors, truncations: t.truncationCount,
  usage: { input: t.usage.input, output: t.usage.output, cacheRead: t.usage.cacheRead, cacheWrite: t.usage.cacheWrite, total: t.usage.total, cost: +t.usage.cost.toFixed(4), maxContext: t.usage.maxInput },
  askedForScreenshot: t.askedForScreenshot, stopReason: t.stopReason, answerChars: t.finalAnswer.length,
}));
fs.writeFileSync(path.join(outDir, 'summary.json'), JSON.stringify({ generatedAt: new Date().toISOString(), sessionsDir, aggregate: agg, turns: slim }, null, 2));

// ---------- markdown ----------
const f1 = n => (n == null || !Number.isFinite(n) ? '-' : n.toFixed(1));
let md = `# pi-fm historical baseline\n\nGenerated ${new Date().toISOString()} from \`${sessionsDir}\` (${agg.sessions} sessions, ${agg.turnsTotal} user turns, ${agg.turnsAnswered} answered).\n\nA turn runs from a user message to the entry before the next user message. Wall time is therefore model + tool time inside the turn (the user's thinking time between turns is excluded). Aggregates cover answered turns only.\n\n## Aggregates\n\n`;
md += `| Metric | Median | p90 | Mean |\n|---|---:|---:|---:|\n`;
md += `| Wall time per turn (s) | ${f1(agg.wallSec.median)} | ${f1(agg.wallSec.p90)} | ${f1(agg.wallSec.mean)} |\n`;
md += `| Time to first tool call (s) | ${f1(agg.timeToFirstToolSec.median)} | ${f1(agg.timeToFirstToolSec.p90)} | - |\n`;
md += `| Model turns per turn | ${f1(agg.modelTurnsPerTurn.median)} | ${f1(agg.modelTurnsPerTurn.p90)} | ${f1(agg.modelTurnsPerTurn.mean)} |\n`;
md += `| Outer tool calls per turn | ${f1(agg.outerToolCallsPerTurn.median)} | ${f1(agg.outerToolCallsPerTurn.p90)} | ${f1(agg.outerToolCallsPerTurn.mean)} |\n`;
md += `| Nested FM calls per turn (inside codemode) | ${f1(agg.nestedFmCallsPerTurn.median)} | ${f1(agg.nestedFmCallsPerTurn.p90)} | ${f1(agg.nestedFmCallsPerTurn.mean)} |\n`;
md += `| Total tokens per turn | ${fmtK(agg.tokensPerTurn.totalMedian)} | ${fmtK(agg.tokensPerTurn.totalP90)} | ${fmtK(agg.tokensPerTurn.totalMean)} |\n`;
md += `| Uncached input tokens per turn | ${fmtK(agg.tokensPerTurn.inputMedian)} | - | - |\n`;
md += `| Output tokens per turn | ${fmtK(agg.tokensPerTurn.outputMedian)} | - | - |\n`;
md += `| Cache-read tokens per turn | ${fmtK(agg.tokensPerTurn.cacheReadMedian)} | - | - |\n`;
md += `| Largest context seen in a turn | ${fmtK(agg.tokensPerTurn.maxContextMedian)} | - | - |\n`;
md += `| Cost per turn | ${fmtUsd(agg.costPerTurnUsd.median)} | - | ${fmtUsd(agg.costPerTurnUsd.mean)} |\n`;
md += `\n- Tool errors: ${agg.toolErrors.total} total; ${agg.toolErrors.turnsWithError}/${agg.turnsAnswered} turns (${(agg.toolErrors.turnErrorRate * 100).toFixed(0)}%) had at least one; ${(agg.toolErrors.perToolCallRate * 100).toFixed(1)}% of outer tool calls.\n`;
md += `- Truncation notices: ${agg.truncations.total} total; ${agg.truncations.turnsWithTruncation}/${agg.turnsAnswered} turns (${(agg.truncations.turnRate * 100).toFixed(0)}%).\n`;
md += `- Answers mentioning screenshots or being unable to attach: ${agg.screenshotAskTurns}.\n`;
md += `- Outer tool mix: ${agg.toolMix.map(([k, v]) => `${k} ${v}`).join(', ')}.\n`;
md += `- Top nested FM calls: ${agg.nestedToolMix.map(([k, v]) => `${k.replace('mcp__fm_live__', '')} ${v}`).join(', ')}.\n`;
md += `\n## Turns\n\n| Session | # | Question | Wall | 1st tool | Model turns | Tool calls (outer/nested) | Errors | Trunc | Tokens | Cost |\n|---|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|\n`;
for (const t of turns) {
  md += `| ${t.session.slice(5, 16)} | ${t.turnIndex} | ${mdEscape(t.question.slice(0, 90))} | ${fmtSec(t.wallMs)} | ${fmtSec(t.timeToFirstToolMs)} | ${t.modelTurns} | ${t.outerToolCalls}/${t.nestedToolCallCount} | ${t.toolErrors} | ${t.truncationCount} | ${fmtK(t.usage.total)} | ${fmtUsd(t.usage.cost)} |\n`;
}
fs.writeFileSync(path.join(outDir, 'summary.md'), md);

console.log(JSON.stringify({ outDir, ...agg }, null, 2));
