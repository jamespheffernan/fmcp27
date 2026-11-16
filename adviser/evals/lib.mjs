// Shared helpers for the pi-fm evaluation harness. No dependencies beyond Node.
import { fileURLToPath } from 'node:url';
import path from 'node:path';

export const EVALS_DIR = path.dirname(fileURLToPath(import.meta.url));
export const PROJECT_DIR = path.dirname(EVALS_DIR);

// ---------- statistics ----------
export function percentile(values, p) {
  const v = values.filter(x => typeof x === 'number' && Number.isFinite(x)).sort((a, b) => a - b);
  if (!v.length) return null;
  if (v.length === 1) return v[0];
  const idx = (p / 100) * (v.length - 1);
  const lo = Math.floor(idx), hi = Math.ceil(idx);
  return v[lo] + (v[hi] - v[lo]) * (idx - lo);
}
export const median = values => percentile(values, 50);
export const mean = values => {
  const v = values.filter(x => typeof x === 'number' && Number.isFinite(x));
  return v.length ? v.reduce((a, b) => a + b, 0) / v.length : null;
};
export const sum = values => values.reduce((a, b) => a + (typeof b === 'number' ? b : 0), 0);

export function fmtSec(ms) {
  if (ms == null || !Number.isFinite(ms)) return '-';
  return (ms / 1000).toFixed(ms < 10000 ? 1 : 0) + 's';
}
export function fmtNum(n, digits = 0) {
  if (n == null || !Number.isFinite(n)) return '-';
  return n.toLocaleString('en-GB', { maximumFractionDigits: digits, minimumFractionDigits: digits });
}
export function fmtK(n) {
  if (n == null || !Number.isFinite(n)) return '-';
  return n >= 10000 ? (n / 1000).toFixed(0) + 'k' : n >= 1000 ? (n / 1000).toFixed(1) + 'k' : String(Math.round(n));
}
export function fmtUsd(n) {
  if (n == null || !Number.isFinite(n)) return '-';
  return '$' + n.toFixed(n < 1 ? 3 : 2);
}
export function mdEscape(s) {
  return String(s ?? '').replace(/\|/g, '\\|').replace(/\n/g, ' ');
}

// ---------- content helpers ----------
export function textOfContent(content) {
  if (typeof content === 'string') return content;
  if (!Array.isArray(content)) return '';
  return content.map(c => (typeof c === 'string' ? c : c?.type === 'text' || c?.text ? c.text ?? '' : '')).join('');
}
export function assistantText(message) {
  const c = message?.content;
  if (typeof c === 'string') return c;
  if (!Array.isArray(c)) return '';
  return c.filter(b => b?.type === 'text').map(b => b.text ?? '').join('\n').trim();
}
export function assistantToolCalls(message) {
  const c = message?.content;
  return Array.isArray(c) ? c.filter(b => b?.type === 'toolCall') : [];
}

// ---------- usage ----------
export function emptyUsage() {
  return { input: 0, output: 0, cacheRead: 0, cacheWrite: 0, reasoning: 0, total: 0, cost: 0, maxInput: 0, calls: 0, hasCost: false };
}
export function addUsage(acc, usage) {
  if (!usage) return acc;
  acc.calls += 1;
  acc.input += usage.input || 0;
  acc.output += usage.output || 0;
  acc.cacheRead += usage.cacheRead || 0;
  acc.cacheWrite += usage.cacheWrite || 0;
  acc.reasoning += usage.reasoning || 0;
  acc.total += usage.totalTokens || (usage.input || 0) + (usage.output || 0) + (usage.cacheRead || 0) + (usage.cacheWrite || 0);
  const ctx = (usage.input || 0) + (usage.cacheRead || 0) + (usage.cacheWrite || 0);
  if (ctx > acc.maxInput) acc.maxInput = ctx;
  const c = usage.cost?.total;
  if (typeof c === 'number') { acc.cost += c; acc.hasCost = true; }
  return acc;
}

// ---------- tool result analysis ----------
const TRUNC_RE = /truncated output \(original token count: (\d+)\)/gi;

/**
 * Inspect one finished tool result (from a session toolResult message or a
 * tool_execution_end event). Returns nested calls, error messages and truncation notices.
 */
export function analyzeToolResult({ toolName, content, isError, details, nestedCalls }) {
  const text = textOfContent(content);
  const callsRaw = nestedCalls?.calls ?? details?.calls ?? [];
  const nested = Array.isArray(callsRaw) ? callsRaw.map(c => ({ name: c.name, status: c.status ?? 'ok', durationMs: c.durationMs ?? null })) : [];
  const errors = [];
  const scriptFailed = /^\s*Script failed/.test(text);
  if (isError || scriptFailed) {
    const m = text.match(/Script error:\s*([\s\S]{0,300})/);
    errors.push({ tool: toolName, message: (m ? m[1] : text).replace(/\s+/g, ' ').trim().slice(0, 300) });
  }
  for (const n of nested) {
    if (n.status && n.status !== 'ok' && n.status !== 'success') {
      errors.push({ tool: n.name, nestedIn: toolName, message: `nested call status: ${n.status}` });
    }
  }
  const truncations = [];
  for (const m of text.matchAll(TRUNC_RE)) truncations.push({ tool: toolName, tokens: m[1] ? Number(m[1]) : null });
  return { nested, errors, truncations, text };
}

// ---------- deterministic answer flags ----------
export const SCREENSHOT_RE = new RegExp(
  [
    'screenshots?',
    'screen\\s*shots?',
    'can(?:no|\\u2019|\')?t\\s+(?:attach|see\\s+(?:the\\s+)?(?:image|screen|attachment))',
    'cannot\\s+(?:attach|see\\s+(?:the\\s+)?(?:image|screen|attachment))',
    'unable\\s+to\\s+(?:attach|view\\s+(?:the\\s+)?(?:image|attachment))',
    '(?:send|upload|paste|share|attach)\\s+(?:me\\s+)?(?:a|an|the|your)\\s+(?:image|photo|picture|file|screen)',
  ].join('|'),
  'i',
);
export function asksForScreenshot(text) {
  return SCREENSHOT_RE.test(text || '');
}

export const DATE_RE = new RegExp(
  '\\b\\d{1,2}(?:st|nd|rd|th)?\\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\\.?,?\\s+20\\d\\d\\b' +
    '|\\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\\.?\\s+\\d{1,2}(?:st|nd|rd|th)?,?\\s+20\\d\\d\\b' +
    '|\\b20\\d\\d-\\d\\d-\\d\\d\\b',
  'i',
);

export const NAME_RE = /\b[A-ZÀ-ÖØ-Þ][\p{L}'’.-]+(?:\s+(?:de|da|do|dos|di|del|van|von|der|den|ten|el|al|le|la|bin|ben|dos)?\s*[A-ZÀ-ÖØ-Þ][\p{L}'’.-]+)+/gu;

// ---------- JSON event stream accumulator (shared by run.mjs live parsing and --reparse) ----------
export function clipDeep(v, max = 3000) {
  if (typeof v === 'string') return v.length > max ? v.slice(0, max) + `...[clipped ${v.length - max} chars]` : v;
  if (Array.isArray(v)) return v.map(x => clipDeep(x, max));
  if (v && typeof v === 'object') { const o = {}; for (const [k, x] of Object.entries(v)) o[k] = clipDeep(x, max); return o; }
  return v;
}

// Calls made from inside a codemode script emit their own tool_execution_* events, with ids of the form
// "<outer id>/<n>". The outer call is the codemode (or direct tool) invocation the model made.
export const isNestedId = id => /\/\d+$/.test(String(id ?? ''));

export class EventAccumulator {
  constructor() {
    this.timeToFirstEventMs = null; this.timeToFirstToolMs = null; this.modelTurns = 0; this.eventCount = 0;
    this.toolCallsOuter = {}; this.toolCallsNested = {}; this.toolErrors = []; this.truncations = [];
    this.usage = emptyUsage(); this.lastAssistant = null; this.sawAgentEnd = false; this.sawSettled = false;
    this.toolDurations = [];
    // Prompt size of the first model call (uncached + cache read + cache write): the fixed cost of
    // the system prompt, tool declarations and question before any tool result.
    this.firstCallInput = null;
  }
  handle(ev, nowMs) {
    this.eventCount += 1;
    if (this.timeToFirstEventMs == null) this.timeToFirstEventMs = nowMs;
    switch (ev.type) {
      case 'tool_execution_start': {
        if (this.timeToFirstToolMs == null) this.timeToFirstToolMs = nowMs;
        const bucket = isNestedId(ev.toolCallId) ? this.toolCallsNested : this.toolCallsOuter;
        bucket[ev.toolName] = (bucket[ev.toolName] || 0) + 1;
        break;
      }
      case 'tool_execution_end': {
        const r = ev.result ?? {};
        const nested = isNestedId(ev.toolCallId);
        if (typeof ev.durationMs === 'number') this.toolDurations.push({ tool: ev.toolName, nested, ms: ev.durationMs });
        const a = analyzeToolResult({ toolName: ev.toolName, content: r.content, isError: ev.isError, details: undefined });
        for (const e of a.errors) this.toolErrors.push(nested ? { ...e, nestedIn: 'codemode' } : e);
        this.truncations.push(...a.truncations);
        break;
      }
      case 'message_end': {
        const msg = ev.message;
        if (msg?.role === 'assistant') {
          if (this.firstCallInput == null && msg.usage) this.firstCallInput = (msg.usage.input || 0) + (msg.usage.cacheRead || 0) + (msg.usage.cacheWrite || 0);
          addUsage(this.usage, msg.usage); this.modelTurns += 1; this.lastAssistant = msg;
        }
        break;
      }
      case 'agent_end': this.sawAgentEnd = true; break;
      case 'agent_settled': this.sawSettled = true; break;
      default: break;
    }
  }
  toolCallsTotal() {
    return sum(Object.values(this.toolCallsNested)) + sum(Object.entries(this.toolCallsOuter).filter(([k]) => k !== 'codemode').map(([, v]) => v));
  }
  usageSummary() {
    const u = this.usage;
    return { input: u.input, output: u.output, cacheRead: u.cacheRead, cacheWrite: u.cacheWrite, total: u.total, cost: u.hasCost ? u.cost : null, maxContext: u.maxInput, modelCalls: u.calls, firstCallInput: this.firstCallInput };
  }
}
