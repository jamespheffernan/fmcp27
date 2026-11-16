// Draws each run as a compact account of observed work, with the current check first.
// Ctrl+O (expanded tool output) still shows every call in full.

import { describeCall, sourceNote, summarize } from './fm-activity-copy.mjs';
export { describeCall, describeTool, summarize } from './fm-activity-copy.mjs';

/**
 * Groups the tool calls in a transcript into runs. A run ends at visible assistant text or at
 * any message that is not an assistant message or a tool result.
 */
export class ActivityLog {
  constructor() {
    this.reset();
  }

  reset() {
    this.groupOf = new Map();
    this.calls = new Map();
    this.parents = new Map();
    this.open = undefined;
  }

  rebuild(messages) {
    this.reset();
    for (const message of messages) this.ingest(message);
    // A call without a result in saved history is not still executing in this process.
    this.interrupt();
  }

  /** Accepts the same assistant message repeatedly while it streams. */
  ingest(message) {
    if (!message) return;
    if (message.role === 'toolResult') {
      this.restoreNested(message.toolCallId, message.nestedCalls);
      this.finish(message.toolCallId, message.isError === true, message);
      return;
    }
    if (message.role !== 'assistant') {
      this.open = undefined;
      return;
    }
    let cursor = this.open;
    for (const part of message.content ?? []) {
      if (part.type === 'text') {
        if (part.text?.trim()) cursor = undefined;
      } else if (part.type === 'toolCall') {
        const known = this.groupOf.get(part.id);
        if (known) {
          cursor = known;
          this.note(part.id, part.name, part.arguments);
        } else {
          cursor = this.add(part.id, part.name, part.arguments, cursor);
        }
      }
    }
    this.open = cursor;
  }

  /** A row drawn before its message was ingested joins the open run. */
  adopt(id, name, args) {
    const group = this.groupOf.get(id);
    if (group) {
      this.note(id, name, args);
      return group;
    }
    this.open = this.add(id, name, args, this.open);
    return this.open;
  }

  add(id, name, args, group) {
    const target = group ?? { ids: [] };
    const previousLast = target.ids.at(-1);
    target.ids.push(id);
    this.groupOf.set(id, target);
    this.calls.set(id, { name, args, state: 'pending', children: [] });
    if (previousLast) this.onChange?.(previousLast);
    return target;
  }

  note(id, name, args) {
    const call = this.calls.get(id);
    if (call && args !== undefined) {
      call.name = name ?? call.name;
      call.args = args;
    }
  }

  changed(id) {
    while (this.parents.has(id)) id = this.parents.get(id);
    const last = this.groupOf.get(id)?.ids.at(-1);
    if (last) this.onChange?.(last);
  }

  start({ toolCallId: id, toolName: name, args, parentToolCallId: parent }) {
    if (!parent) {
      this.adopt(id, name, args);
    } else if (this.calls.has(parent) && !this.calls.has(id)) {
      this.parents.set(id, parent);
      this.calls.get(parent).children.push(id);
      this.calls.set(id, { name, args, state: 'pending', children: [] });
    }
    this.changed(id);
  }

  restoreNested(parent, record) {
    if (!record || !this.calls.has(parent)) return;
    for (const child of record.calls ?? []) {
      const immediateParent = child.id.slice(0, child.id.lastIndexOf('/'));
      this.start({ toolCallId: child.id, toolName: child.name, args: child.arguments,
        parentToolCallId: this.calls.has(immediateParent) ? immediateParent : parent });
      // Live results carry more detail than the persisted call record. Preserve it.
      const call = this.calls.get(child.id);
      if (call?.state === 'pending') call.state = child.status === 'ok' ? 'done' : child.status === 'error' ? 'failed' : 'interrupted';
    }
    this.calls.get(parent).incomplete = record.complete === false;
  }

  finish(id, isError, result) {
    const call = this.calls.get(id);
    if (!call) return;
    const facts = resultFacts(call.name, result);
    const previousState = call.state;
    const previousNote = call.note;
    // Repeated renderer callbacks cannot turn an observed failure into a success.
    if (call.state !== 'failed' && call.state !== 'interrupted') call.state = isError || facts.failed ? 'failed' : 'done';
    if (facts.note) call.note = facts.note;
    if (previousState !== call.state || previousNote !== call.note) this.changed(id);
  }

  interrupt() {
    for (const [id, call] of this.calls) {
      if (call.state === 'pending') {
        call.state = 'interrupted';
        this.changed(id);
      }
    }
  }

  observed(id) {
    const call = this.calls.get(id);
    if (!call) return [];
    const children = call.children.flatMap(child => this.observed(child));
    // The script is a container, not proof that all the calls in its source executed.
    if (children.length && call.name === 'codemode') {
      if (call.state === 'failed' && !children.some(child => child.state === 'failed')) return [...children, call];
      return children;
    }
    return children.length ? [...children, call] : [call];
  }

  isLast(id) {
    return this.groupOf.get(id)?.ids.at(-1) === id;
  }

  /** The line shown for the run that contains this call. */
  line(id) {
    const group = this.groupOf.get(id);
    if (!group) return undefined;
    const roots = group.ids.map(callId => this.calls.get(callId)).filter(Boolean);
    const calls = group.ids.flatMap(callId => this.observed(callId));
    const pending = calls.filter(call => call.state === 'pending');
    const failures = calls.filter(call => call.state === 'failed');
    const stopped = calls.filter(call => call.state === 'interrupted');
    const completed = calls.filter(call => call.state === 'done');
    const done = roots.every(call => call.state !== 'pending');
    const parts = items => items.flatMap(call => describeCall(call.name, call.args));
    // Recent work leads; connection/discovery/guide reads do not crowd out football evidence.
    const evidence = completed.filter(call => isEvidence(call.name));
    const recent = (evidence.length ? evidence : completed).slice(-4).reverse();
    let text, detail;
    if (pending.length) {
      const current = pending.at(-1);
      text = summarize(parts([current]));
      if (pending.length > 1) text += ` · ${pending.length - 1} other ${pending.length === 2 ? 'check' : 'checks'} running`;
      detail = sourceNote(current.name, current.args);
    } else if (failures.length) {
      text = summarize(parts(failures.slice(-2)), { failed: true });
    } else if (stopped.length) {
      text = summarize(parts(stopped.slice(-2)), { interrupted: true });
    } else {
      text = summarize(parts(recent), { done: true });
      const last = recent[0];
      detail = [last?.note, last && sourceNote(last.name, last.args)].filter(Boolean).join(' · ');
      // Counts and visibility belong to this read, not every read in the group.
      if (detail && completed.length > 1) detail = `Latest check: ${detail}`;
    }
    if (pending.length && failures.length) detail = summarize(parts(failures.slice(-1)), { failed: true });
    if ((failures.length || stopped.length) && !pending.length && recent.length) detail = summarize(parts(recent), { done: true });
    if (!detail && !done && recent.length) detail = summarize(parts(recent), { done: true });
    if (roots.some(call => call.incomplete)) detail = [detail, 'Some earlier checks are unavailable'].filter(Boolean).join(' · ');
    return { text, detail, done, failed: failures.length, interrupted: stopped.length };
  }
}

function isEvidence(name) {
  return name.startsWith('mcp__fm_live__') && !/fm_(?:status|attach|detach|coverage|db_schema|ui_schema)$/.test(name);
}

function resultFacts(name, result) {
  let data = result;
  // Pi may wrap the whole MCP response in structuredContent; FastMCP may wrap its
  // value in result. Read the payload without mistaking either envelope for data.
  for (let depth = 0; depth < 5 && data && typeof data === 'object'; depth++) {
    if (data.isError === true) return { failed: true };
    if (data.structuredContent) data = data.structuredContent;
    else if (Array.isArray(data.content)) {
      try { data = JSON.parse(plainResult(data)); } catch { return {}; }
    } else if (Object.keys(data).length === 1 && 'result' in data) data = data.result;
    else break;
  }
  if (!data || typeof data !== 'object') return {};
  if (data.ok === false || data.success === false || data.isError === true || typeof data.error === 'string' && data.error.length > 0) return { failed: true };
  if (name.endsWith('fm_db_query') && Array.isArray(data.rows)) {
    const count = data.rows.length;
    // Rows may be aggregates or joined records, so never call this a player/match count.
    return { note: data.truncated ? `${count} results returned · more available`
      : count === 0 ? 'No matching results' : `${count} ${count === 1 ? 'result' : 'results'} returned` };
  }
  return {};
}

function fit(text, width) {
  if (width <= 0) return '';
  return text.length <= width ? text : `${text.slice(0, Math.max(0, width - 1))}…`;
}

function compactLines(text, width, maxLines = 2) {
  if (width <= 0) return [];
  const lines = [];
  let rest = text;
  while (rest.length > width && lines.length < maxLines - 1) {
    const space = rest.lastIndexOf(' ', width);
    const end = space > width / 2 ? space : width;
    lines.push(rest.slice(0, end));
    rest = rest.slice(end).trimStart();
  }
  return [...lines, fit(rest, width)];
}

function lineComponent(draw) {
  return { render: width => draw(width), invalidate() {} };
}

const EMPTY = lineComponent(() => []);

function plainArgs(toolName, args) {
  if (toolName === 'codemode' && typeof args?.code === 'string') return args.code;
  try {
    return JSON.stringify(args ?? {}, null, 2);
  } catch {
    return String(args);
  }
}

function plainResult(result) {
  return (result?.content ?? []).filter(part => part.type === 'text').map(part => part.text).join('\n');
}

function wrapLines(text, width, style) {
  const lines = [];
  for (const raw of text.split('\n')) {
    if (raw.length === 0) lines.push('');
    for (let start = 0; start < raw.length; start += Math.max(1, width)) lines.push(raw.slice(start, start + Math.max(1, width)));
  }
  return lines.map(style);
}

/** Registers the compact activity display. Returns the log for tests. */
export function registerActivityDisplay(pi) {
  const log = new ActivityLog();
  const redraw = new Map();
  log.onChange = id => {
    const invalidate = redraw.get(id);
    if (invalidate) queueMicrotask(invalidate);
  };
  const redrawAll = () => {
    for (const invalidate of redraw.values()) queueMicrotask(invalidate);
  };

  const rebuild = ctx => {
    const branch = ctx?.sessionManager?.getBranch?.() ?? [];
    // Visible non-message entries also end a run; settings changes and labels do not.
    const breaks = new Set(['custom_message', 'compaction', 'branch_summary']);
    log.rebuild(branch.flatMap(entry => entry.type === 'message' ? [entry.message] : breaks.has(entry.type) ? [{ role: entry.type }] : []));
    redrawAll();
  };

  const expandedFallback = (toolName, args, theme, outputPad) => lineComponent(width => {
    const pad = ' '.repeat(outputPad);
    const inner = Math.max(1, width - outputPad);
    return [pad + theme.fg('toolTitle', fit(toolName, inner)), ...wrapLines(plainArgs(toolName, args), inner, line => pad + theme.fg('toolOutput', line))];
  });

  pi.registerToolRenderer?.((toolName, next) => {
    const original = () => next();
    return {
      renderShell: 'self',
      renderCall(args, theme, context) {
        redraw.set(context.toolCallId, context.invalidate);
        log.adopt(context.toolCallId, toolName, args);
        if (context.expanded) {
          const renderCall = original()?.renderCall;
          return renderCall ? renderCall(args, theme, context) : expandedFallback(toolName, args, theme, context.outputPad);
        }
        return lineComponent(width => {
          if (!log.isLast(context.toolCallId) || width <= context.outputPad + 2) return [];
          const summary = log.line(context.toolCallId);
          if (!summary) return [];
          const pad = ' '.repeat(context.outputPad);
          const room = width - pad.length - 2;
          const warning = summary.failed || summary.interrupted;
          const bullet = theme.fg(warning ? 'warning' : summary.done ? 'dim' : 'accent', '•');
          const lines = compactLines(summary.text, room, summary.detail ? 1 : 2);
          if (summary.detail) lines.push(fit(summary.detail, room));
          return lines.map((line, index) => `${pad}${index ? '  ' : `${bullet} `}${theme.fg(warning ? 'warning' : 'muted', line)}`);
        });
      },
      renderResult(result, options, theme, context) {
        // Rows restored from history get their outcome here; live rows also get tool_execution_end.
        if (!options.isPartial) log.finish(context.toolCallId, context.isError, result);
        if (!context.expanded) return EMPTY;
        const renderResult = original()?.renderResult;
        if (renderResult) return renderResult(result, options, theme, context);
        const pad = ' '.repeat(context.outputPad);
        return lineComponent(width => wrapLines(plainResult(result), Math.max(1, width - context.outputPad), line => pad + theme.fg('toolOutput', line)));
      },
    };
  });

  pi.on('session_tree', (_event, ctx) => rebuild(ctx));
  pi.on('message_update', (event, ctx) => {
    log.ingest(event.message);
    if (ctx?.hasUI && event.assistantMessageEvent?.type === 'text_delta' && !active.size) ctx.ui.setWorkingMessage('Writing your answer…');
  });
  pi.on('message_end', event => log.ingest(event.message));
  const active = new Map();
  let gathered = false;
  let hadFailure = false;
  const working = ctx => {
    if (!ctx?.hasUI) return;
    const running = [...active.values()];
    const current = running.filter(event => event.toolName !== 'codemode').at(-1) ?? running.at(-1);
    if (current) {
      const parts = describeCall(current.toolName, current.args);
      const note = sourceNote(current.toolName, current.args);
      ctx.ui.setWorkingMessage(`${summarize(parts)}${note ? ` · ${note.toLowerCase()}` : ''}…`);
    } else {
      ctx.ui.setWorkingMessage(hadFailure ? 'Reviewing the available evidence and gaps…'
        : gathered ? 'Weighing the evidence for your answer…' : 'Preparing the next step…');
    }
  };
  pi.on('agent_start', () => {
    active.clear();
    gathered = false;
    hadFailure = false;
  });
  pi.on('tool_execution_end', (event, ctx) => {
    log.finish(event.toolCallId, event.isError === true, event.result);
    active.delete(event.toolCallId);
    const state = log.calls.get(event.toolCallId)?.state;
    hadFailure ||= state === 'failed';
    gathered ||= state === 'done' && isEvidence(event.toolName);
    working(ctx);
  });
  pi.on('tool_execution_start', (event, ctx) => {
    log.start(event);
    active.set(event.toolCallId, event);
    working(ctx);
  });
  pi.on('agent_end', (_event, ctx) => {
    log.interrupt();
    active.clear();
    if (ctx?.hasUI) ctx.ui.setWorkingMessage();
  });

  return { log, rebuild };
}
