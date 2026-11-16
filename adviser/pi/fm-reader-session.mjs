// The FM reader connection as the harness sees it: one stdio MCP transport that pi's MCP client
// uses, with the attachment managed here instead of by the model.
//
// - Attach: the harness calls fm_attach and fm_get_save itself (ReaderSession.ensureAttached), so a
//   session never spends model turns on fm_status / fm_attach / fm_get_save.
// - session_id: tools/list responses lose their `session_id` parameter, and every tools/call for a
//   tool that had one gets the current id written in. Model calls, Code Mode calls and tool_search
//   calls all pass through here, so the model never sees or manages the id.
// - Re-attach: a call refused for an unknown or expired session is re-sent once after a fresh
//   attach, under the same request id, so the caller sees only the second answer.
// - Compact results: JSON text results are re-serialised without indentation, one array element
//   per line (the reader pretty-prints, one cell per line).
//
// No pi imports: the transport implements pi-mcp's McpTransport interface structurally
// (start/send/close/onMessage/onError/onClose), so tests drive it with a fake reader process.
import { spawn } from 'node:child_process';

export const SESSION_PARAM = 'session_id';
const HARNESS_ID = 'pifm:';
const RETRY_RE = /Unknown session|Attach again|attach again|reattach/;
const STDERR_TAIL = 4000;

/** The one fix for an attach failure, from the reader's exact message. */
export function attachFix(message) {
  const m = String(message ?? '');
  if (/task_for_pid|not permitted|Developer Tools/i.test(m)) return 'Run `node pi/fm-desktop-reader.mjs install` once from a Terminal in the Mac\'s desktop login (in the pi-fm folder), then restart pi-fm.';
  if (/Found 0 games/.test(m)) return 'Start Football Manager 27, load the career, then ask again.';
  if (/Found \d+ games/.test(m)) return 'More than one Football Manager is running: quit the extra copy, then ask again.';
  if (/incompatible|build_helper/i.test(m)) return 'Rebuild the native reader with scripts/build_helper.sh in the reader checkout, then restart pi-fm.';
  if (/not a supported|other builds fail closed|unsupported build/i.test(m)) return 'This Football Manager build is not supported by the installed reader: update the reader, then restart pi-fm.';
  if (/did not start|exited|ENOENT|spawn/i.test(m)) return 'Check that the reader launcher (PI_FM_MCP_LAUNCHER) exists and runs, then restart pi-fm.';
  if (/timed out/i.test(m)) return 'The game may be busy processing; ask again in a minute.';
  return 'Ask again; the harness re-attaches on every question. If the same error repeats, restart pi-fm.';
}

/** Remove `session_id` from one MCP tool declaration. Returns true when the tool had it. */
export function stripSessionParam(tool) {
  const schema = tool?.inputSchema;
  if (!schema?.properties || !Object.hasOwn(schema.properties, SESSION_PARAM)) return false;
  delete schema.properties[SESSION_PARAM];
  if (Array.isArray(schema.required)) schema.required = schema.required.filter(name => name !== SESSION_PARAM);
  return true;
}

const isPlain = v => v !== null && typeof v === 'object' && !Array.isArray(v);
function compactJson(value) {
  if (Array.isArray(value)) {
    // Arrays of rows or records: one element per line, so a model can scan rows.
    if (value.length > 1 && value.every(x => x !== null && typeof x === 'object')) return `[\n${value.map(x => JSON.stringify(x)).join(',\n')}\n]`;
    return JSON.stringify(value);
  }
  if (isPlain(value)) return `{${Object.entries(value).map(([k, v]) => `${JSON.stringify(k)}:${compactJson(v)}`).join(',')}}`;
  return JSON.stringify(value);
}

/** Pretty-printed JSON text becomes compact JSON with one row per line; other text is unchanged. */
export function compactToolText(text) {
  if (typeof text !== 'string' || text.length < 64) return text;
  const head = text.trimStart()[0];
  if (head !== '{' && head !== '[') return text;
  try { return compactJson(JSON.parse(text)); } catch { return text; }
}

function parseResult(result) {
  if (result?.structuredContent !== undefined && result.structuredContent !== null) {
    const s = result.structuredContent;
    // FastMCP wraps non-object returns as {result: ...}.
    return isPlain(s) && Object.keys(s).length === 1 && 'result' in s ? s.result : s;
  }
  const text = (result?.content ?? []).filter(c => c?.type === 'text').map(c => c.text).join('');
  try { return JSON.parse(text); } catch { return text; }
}
const resultText = result => (result?.content ?? []).filter(c => c?.type === 'text').map(c => c.text).join('\n');

/**
 * What the harness knows about the attachment. One instance lives for the pi process; each new
 * transport (a reconnect) registers itself here.
 */
export class ReaderSession {
  constructor({ requestTimeoutMs = 90_000, clock = () => Date.now() } = {}) {
    this.requestTimeoutMs = requestTimeoutMs;
    this.clock = clock;
    this.transport = null;
    this.sessionId = null;
    this.save = null;          // {name, current_date, coaches:[{name, club}], ...} from fm_get_save
    this.saveReadAt = null;
    this.error = null;         // {message, fix} of the last failed attach
    this.sessionTools = new Set();
    this.attaching = null;
    this.attachCount = 0;
    this.listeners = new Set();
  }

  /** Called with no argument whenever the save summary or error changes. */
  onChange(listener) { this.listeners.add(listener); return () => this.listeners.delete(listener); }
  changed() { for (const l of this.listeners) { try { l(); } catch { /* listener errors are not ours */ } } }

  bind(transport) { this.transport = transport; }

  /** A tool call as the harness makes it (never seen by the model). Rejects on transport failure. */
  async call(name, args = {}) {
    const t = this.transport;
    if (!t) throw new Error('the reader did not start');
    await t.ready;
    if (this.sessionTools.has(name) && args[SESSION_PARAM] === undefined && this.sessionId) args = { ...args, [SESSION_PARAM]: this.sessionId };
    return t.request('tools/call', { name, arguments: args }, this.requestTimeoutMs);
  }

  /** Attach once (shared by concurrent callers). Resolves to the session id or null with this.error set. */
  ensureAttached({ force = false } = {}) {
    if (this.sessionId && !force) return Promise.resolve(this.sessionId);
    if (force) this.sessionId = null;
    this.attaching ??= this.attach().finally(() => { this.attaching = null; });
    return this.attaching;
  }

  async attach() {
    this.attachCount += 1;
    try {
      const attached = await this.call('fm_attach', {});
      if (attached?.isError) throw new Error(resultText(attached));
      const id = parseResult(attached)?.session_id;
      if (typeof id !== 'string' || !id) throw new Error(`fm_attach returned no session id: ${resultText(attached).slice(0, 300)}`);
      this.sessionId = id;
      this.error = null;
      await this.refreshSave();
      return id;
    } catch (error) {
      const tail = this.transport?.stderr?.trim().split('\n').slice(-3).join(' | ');
      const message = String(error?.message ?? error).replace(/^Error executing tool \w+: /, '');
      this.sessionId = null;
      this.error = { message: tail && /did not start|exited|closed/.test(message) ? `${message} (reader stderr: ${tail.slice(-400)})` : message, fix: attachFix(message) };
      this.changed();
      return null;
    }
  }

  /**
   * Before each question: attach if needed, then re-read the save so the summary follows the game
   * date. A session the reader no longer knows (game restarted, save loaded) is replaced.
   */
  async refresh() {
    const attaching = !this.sessionId;
    if (!(await this.ensureAttached())) return null;
    if (attaching) return this.save;   // attach() has just read the save
    try {
      return await this.refreshSave();
    } catch (error) {
      if (!error.retry) throw error;
      if (!(await this.ensureAttached({ force: true }))) return null;
      return this.save;
    }
  }

  /** Read the loaded save again (cheap, about 0.3 s). */
  async refreshSave() {
    if (!this.sessionId) return null;
    const before = JSON.stringify(this.save);
    const result = await this.call('fm_get_save', { [SESSION_PARAM]: this.sessionId });
    if (result?.isError) {
      const text = resultText(result);
      throw Object.assign(new Error(text.replace(/^Error executing tool \w+: /, '')), { retry: RETRY_RE.test(text) });
    }
    const parsed = parseResult(result);
    this.save = parsed?.save ?? null;
    this.saveReadAt = this.clock();
    if (JSON.stringify(this.save) !== before) this.changed();
    return this.save;
  }

  /** The managed career in one line per fact, for the system prompt. */
  summary() {
    if (this.error) return null;
    const s = this.save;
    if (!s) return null;
    const coaches = Array.isArray(s.coaches) ? s.coaches : [];
    const lines = [];
    if (s.name) lines.push(`- Save: ${s.name}`);
    for (const c of coaches) {
      const club = typeof c.club === 'string' ? c.club : c.club?.name;
      lines.push(`- Manager: ${String(c.name ?? '').replace(/\s+/g, ' ')}${club ? ` (your club: ${club})` : ''}`);
    }
    if (s.current_date) lines.push(`- Game date: ${s.current_date} (quote it; it moves as the game is played)`);
    if (s.last_saved_date) lines.push(`- Last saved: ${s.last_saved_date}`);
    return lines.join('\n');
  }
}

/** stdio MCP transport to the reader, with the harness's attachment logic in the message path. */
export class ReaderTransport {
  constructor({ command, args = [], env, cwd }, session) {
    this.options = { command, args, env, cwd };
    this.session = session;
    this.child = null;
    this.buffer = '';
    this.stderrText = '';
    this.closed = false;
    this.messageListeners = new Set();
    this.errorListeners = new Set();
    this.closeListeners = new Set();
    this.listIds = new Set();
    this.calls = new Map();      // client request id -> {message, retried}
    this.pending = new Map();    // harness request id -> {resolve, reject, timer}
    this.nextId = 1;
    const ready = Promise.withResolvers();
    this.ready = ready.promise;
    this.markReady = ready.resolve;
    this.failReady = ready.reject;
    this.ready.catch(() => {});
    session?.bind(this);
  }

  get stderr() { return this.stderrText; }
  onMessage(l) { this.messageListeners.add(l); return () => this.messageListeners.delete(l); }
  onError(l) { this.errorListeners.add(l); return () => this.errorListeners.delete(l); }
  onClose(l) { this.closeListeners.add(l); return () => this.closeListeners.delete(l); }
  emit(set, value) { for (const l of set) l(value); }

  async start() {
    const { command, args, env, cwd } = this.options;
    const child = spawn(command, args, { cwd, env: { ...process.env, ...env }, stdio: ['pipe', 'pipe', 'pipe'] });
    this.child = child;
    child.stdout.setEncoding('utf8');
    child.stderr.setEncoding('utf8');
    child.stdout.on('data', chunk => this.readStdout(chunk));
    child.stderr.on('data', chunk => { this.stderrText = (this.stderrText + chunk).slice(-STDERR_TAIL); });
    child.on('error', error => { this.emit(this.errorListeners, error); this.finish(`the reader did not start: ${error.message}`); });
    child.on('exit', (code, signal) => this.finish(`the reader exited (${signal ?? `code ${code}`})`));
    child.stdin.on('error', () => {});
  }

  finish(reason) {
    if (this.closed) return;
    this.closed = true;
    const error = new Error(reason);
    this.failReady(error);
    for (const { reject, timer } of this.pending.values()) { clearTimeout(timer); reject(error); }
    this.pending.clear();
    this.emit(this.closeListeners);
  }

  async close() {
    if (this.closed) return;
    const child = this.child;
    try { child?.stdin.end(); } catch { /* already gone */ }
    const exited = new Promise(resolve => child ? child.once('exit', resolve) : resolve());
    const timer = setTimeout(() => { try { child?.kill('SIGTERM'); } catch { /* gone */ } }, 2000);
    const kill = setTimeout(() => { try { child?.kill('SIGKILL'); } catch { /* gone */ } }, 4000);
    await Promise.race([exited, new Promise(r => setTimeout(r, 5000))]);
    clearTimeout(timer); clearTimeout(kill);
    this.finish('closed');
  }

  write(message) {
    if (this.closed || !this.child) throw new Error('the reader connection is closed');
    this.child.stdin.write(`${JSON.stringify(message)}\n`);
  }

  /** A JSON-RPC request the harness makes on its own account; its answer never reaches pi. */
  request(method, params, timeoutMs) {
    const id = `${HARNESS_ID}${this.nextId++}`;
    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => { this.pending.delete(id); reject(new Error(`${method} ${params?.name ?? ''} timed out after ${Math.round(timeoutMs / 1000)} s`)); }, timeoutMs);
      this.pending.set(id, { resolve, reject, timer });
      try { this.write({ jsonrpc: '2.0', id, method, params }); } catch (error) { clearTimeout(timer); this.pending.delete(id); reject(error); }
    });
  }

  async send(message, options = {}) {
    if (message?.method === 'tools/list' && message.id !== undefined) this.listIds.add(message.id);
    if (message?.method === 'tools/call' && message.id !== undefined) {
      const name = message.params?.name;
      if (this.session && this.session.sessionTools.has(name)) {
        const id = await this.session.ensureAttached();
        if (options.signal?.aborted) return;
        if (!id) {
          // Answer for the reader: the exact reason and the one fix, never a guess.
          const { message: reason, fix } = this.session.error ?? { message: 'attach failed', fix: attachFix('') };
          this.emit(this.messageListeners, { jsonrpc: '2.0', id: message.id, result: { isError: true, content: [{ type: 'text', text: `The FM reader could not attach to the game: ${reason}\nFix: ${fix}` }] } });
          return;
        }
        message = { ...message, params: { ...message.params, arguments: { ...(message.params.arguments ?? {}), [SESSION_PARAM]: id } } };
      }
      this.calls.set(message.id, { message, retried: false });
    }
    if (options.signal?.aborted) return;
    this.write(message);
    if (message?.method === 'notifications/initialized') this.markReady();
  }

  readStdout(chunk) {
    this.buffer += chunk;
    let nl;
    while ((nl = this.buffer.indexOf('\n')) >= 0) {
      const line = this.buffer.slice(0, nl).trim();
      this.buffer = this.buffer.slice(nl + 1);
      if (!line) continue;
      let message;
      try { message = JSON.parse(line); } catch (error) { this.emit(this.errorListeners, new Error(`unparseable reader output: ${line.slice(0, 120)}`)); continue; }
      this.receive(message).catch(error => this.emit(this.errorListeners, error));
    }
  }

  async receive(message) {
    const id = message?.id;
    if (typeof id === 'string' && id.startsWith(HARNESS_ID) && !message.method) {
      const waiter = this.pending.get(id);
      if (!waiter) return;
      this.pending.delete(id);
      clearTimeout(waiter.timer);
      if (message.error) waiter.reject(new Error(message.error.message ?? JSON.stringify(message.error)));
      else waiter.resolve(message.result);
      return;
    }
    if (message?.result?.serverInfo && this.session) this.session.serverInfo = message.result.serverInfo;
    if (id !== undefined && this.listIds.has(id) && !message.method) {
      this.listIds.delete(id);
      for (const tool of message.result?.tools ?? []) if (stripSessionParam(tool)) this.session?.sessionTools.add(tool.name);
    } else if (id !== undefined && this.calls.has(id) && !message.method) {
      const call = this.calls.get(id);
      const result = message.result;
      const name = call.message.params?.name;
      if (result?.isError && this.session?.sessionTools.has(name) && !call.retried && RETRY_RE.test(resultText(result))) {
        call.retried = true;
        const fresh = await this.session.ensureAttached({ force: true });
        if (fresh) {
          call.message = { ...call.message, params: { ...call.message.params, arguments: { ...call.message.params.arguments, [SESSION_PARAM]: fresh } } };
          this.write(call.message);
          return;
        }
      }
      this.calls.delete(id);
      if (name === 'fm_attach' && result && !result.isError) {
        const sid = parseResult(result)?.session_id;
        if (typeof sid === 'string' && sid && this.session) { this.session.sessionId = sid; this.session.error = null; }
      }
      for (const block of result?.content ?? []) if (block?.type === 'text') block.text = compactToolText(block.text);
    }
    this.emit(this.messageListeners, message);
  }
}

/** pi's McpTransportFactory for the reader server. */
export function readerTransportFactory(session, serverName) {
  return (entry, cwd) => {
    if (entry.name !== serverName || !('command' in entry.config)) throw new Error(`pi-fm connects only its reader, not "${entry.name}"`);
    const { command, args, env, cwd: dir } = entry.config;
    return new ReaderTransport({ command, args, env, cwd: dir ?? cwd }, session);
  };
}
