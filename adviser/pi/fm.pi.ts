import { createCodemodeExtension, createMcpExtension, createToolSearchExtension, type ExtensionAPI } from '@earendil-works/pi-coding-agent';

import { registerSkillTool, SKILL_TOOL } from './fm-skills.mjs';
import { registerTacticFileTool, TACTIC_TOOL } from './fm-tactic-files.mjs';
import { registerTextFileTool, TEXT_TOOL } from './fm-text-files.mjs';
import { promptListing, registerToolboxTool, TOOLBOX_TOOL, withToolbox } from './fm-toolbox.mjs';
import { registerMatchReportTool, MATCH_REPORT_TOOL } from './fm-match-report.mjs';
import { registerReportTool, REPORT_TOOL } from './fm-report.mjs';
import { registerActivityDisplay } from './fm-activity.mjs';
import { readerCommand } from './fm-desktop-reader.mjs';
import { assemblePrompt, PREFIX, readerExposure, SERVER, wantsReport, wantsTactic } from './fm-exposure.mjs';
import { ReaderSession, readerTransportFactory } from './fm-reader-session.mjs';
import { SchemaCards } from './fm-schema-card.mjs';
import { cardDirectory, prepareTurn } from './fm-turn.mjs';

const HOST_WRITERS = new Set([
  `${PREFIX}fm_record_current_match`,
  `${PREFIX}fm_get_current_match`,
  `${PREFIX}fm_get_current_match_shot_origins`,
  `${PREFIX}fm_report_retained_match_periods`,
  `${PREFIX}fm_report_retained_pass_network_by_period`,
  `${PREFIX}fm_report_retained_possession_by_period`,
]);
// Loads deferred reader schemas so the model can call them; it reads no game or file data.
const TOOL_SEARCH = 'tool_search';
// Match tables and position text are computed on first use in a reader process (up to about two
// minutes); a shorter deadline fails the call while the reader keeps computing.
const REQUEST_TIMEOUT_SECONDS = 180;
// MCP initialization and the first tools/list each have their own request deadline.
const DISCOVERY_TIMEOUT_MS = (2 * REQUEST_TIMEOUT_SECONDS + 5) * 1000;

async function changeRegistration(pi: ExtensionAPI, change: () => void, timeoutMs: number) {
  const changed = Promise.withResolvers<void>();
  // Pi runs handlers in order. Its MCP integration finishes closing or opening the
  // changed server before this listener runs.
  const unsubscribe = pi.on('mcp_servers_change', () => changed.resolve());
  const timer = setTimeout(() => changed.resolve(), timeoutMs);
  try {
    change();
    await changed.promise;
  } finally {
    clearTimeout(timer);
    unsubscribe();
  }
}

export default async function fmExtension(pi: ExtensionAPI) {
  registerSkillTool(pi);
  registerTacticFileTool(pi);
  registerTextFileTool(pi);
  registerMatchReportTool(pi);
  // Self-contained HTML reports written to ~/Agent Outputs; declared only on turns that ask for a file.
  registerReportTool(pi);
  // Each run of tool calls is drawn as one line; Ctrl+O still expands every call.
  const activity = registerActivityDisplay(pi);
  // The harness owns the attachment: it attaches, fills session_id into every reader call and
  // re-attaches when the game restarts (fm-reader-session.mjs).
  const session = new ReaderSession({ requestTimeoutMs: REQUEST_TIMEOUT_SECONDS * 1000 });
  // Tools the adviser builds for itself: saved Code Mode functions, kept between sessions and
  // called from any script as `toolbox.<name>(args)` (fm-toolbox.mjs).
  const toolbox = registerToolboxTool(pi, { gameDate: () => session.save?.current_date });
  // Scripts compose FM reads and calculations; no additional model/network surface.
  createCodemodeExtension({ mode: 'on', models: false })(pi);
  // Deferred reader tools are found and declared through tool_search (see fm-exposure.mjs).
  createToolSearchExtension()(pi);
  const cards = new SchemaCards({ dir: cardDirectory(), call: (name, args) => session.call(name, args).then(parseCall) });
  // Over SSH or mosh the reader runs in the desktop login (see fm-desktop-reader.mjs).
  const reader = readerCommand('mcp');
  const registerReader = () => pi.registerMcpServer(SERVER, {
    command: reader.command,
    args: reader.args,
    ...readerExposure(),
    timeout: REQUEST_TIMEOUT_SECONDS,
    description: 'Read-only Football Manager live-save queries: SQL over a save snapshot, game screens, matches, players, squads, contracts, finances, competitions, fixtures, tactics and linked records.',
  });
  registerReader();
  // Keep the shared Pi login/model settings, but load only this harness's MCP server.
  createMcpExtension({
    loadConfig: () => ({ servers: [], errors: [], autoEnableCodemode: false }),
    createTransport: readerTransportFactory(session, SERVER),
    startupWaitMs: DISCOVERY_TIMEOUT_MS,
  })(pi);

  let checkedStartup = false;
  pi.on('session_start', (_event, ctx) => {
    checkedStartup = false;
    activity.rebuild(ctx);
  });
  pi.on('before_agent_start', async (event, ctx) => {
    const hasReader = () => pi.getAllTools().some(tool =>
      tool.name.startsWith(PREFIX) && tool.annotations?.readOnlyHint === true);
    if (!checkedStartup) {
      checkedStartup = true;
      if (!hasReader()) {
        ctx.ui.notify('FM reader discovery returned no read-only tools. Reconnecting once.', 'warning');
        // Replace only the failed registration, before the model can make a data call.
        await changeRegistration(pi, () => pi.unregisterMcpServer(SERVER), 5000);
        await changeRegistration(pi, registerReader, DISCOVERY_TIMEOUT_MS);
      }
    }
    // Large local tools are declared only on the turns that need them.
    const prompt = typeof event.prompt === 'string' ? event.prompt : '';
    const reportRequested = wantsReport(prompt);
    const active = new Set(pi.getActiveTools());
    const want = (name: string, on: boolean) => { if (on) active.add(name); else active.delete(name); };
    want(REPORT_TOOL, reportRequested && pi.getAllTools().some(t => t.name === REPORT_TOOL));
    want(TACTIC_TOOL, wantsTactic(prompt));
    pi.setActiveTools([...active]);

    const turn = await prepareTurn({ session, cards, hasReader: hasReader() });
    if (turn.notice) ctx.ui.notify(turn.notice, 'warning');
    // Prompt sections that depend on a tool (SQL snapshot, HTML report) appear only when it exists.
    const systemPrompt = assemblePrompt(event.systemPrompt, pi.getAllTools(), {
      save: turn.save, attachError: turn.attachError, schemaCard: turn.schemaCard, reportRequested,
      toolbox: promptListing(toolbox.all()),
    });
    if (!hasReader()) {
      return { systemPrompt, message: {
        customType: 'fm-reader-unavailable', display: true,
        content: 'The FM reader currently has no read-only tools available in this session. ' +
          'Save and live data are unavailable. Use /mcp to inspect the reader and /mcp reconnect fm_live after correcting the failure.',
      } };
    }
    return { systemPrompt };
  });

  pi.on('tool_call', event => {
    // Pi dispatches nested Code Mode calls through this same hook.
    if (event.toolName === 'codemode') {
      // A script that names saved tools gets them as `toolbox.<name>`; they run inside the same
      // sandbox, and every reader call they make comes back through this hook.
      if (typeof event.input?.code === 'string') event.input.code = withToolbox(event.input.code, toolbox.all());
      return;
    }
    if (event.toolName === 'papercut' || event.toolName === TACTIC_TOOL || event.toolName === TEXT_TOOL || event.toolName === SKILL_TOOL || event.toolName === TOOLBOX_TOOL) return;
    if (event.toolName === TOOL_SEARCH && pi.getAllTools().some(tool => tool.name === TOOL_SEARCH)) return;
    if (event.toolName === MATCH_REPORT_TOOL && pi.getAllTools().some(tool => tool.name === MATCH_REPORT_TOOL)) return;
    if (event.toolName === REPORT_TOOL && pi.getAllTools().some(tool => tool.name === REPORT_TOOL)) return;
    const tool = pi.getAllTools().find(candidate => candidate.name === event.toolName);
    // These exact registered tools can persist host captures or period-link metadata, never the game.
    const hostWriter = HOST_WRITERS.has(event.toolName) && tool?.annotations?.readOnlyHint === false;
    if (!event.toolName.startsWith(PREFIX) || (!hostWriter && tool?.annotations?.readOnlyHint !== true)) {
      return { block: true, reason: 'pi-fm permits Code Mode, tool search, papercut logging, bounded football guidance, bounded text files, its own saved Code Mode tools, the exact installed HTML reporters, standalone native tactic files, read-only FM tools and the exact registered host-only match recorder, current-match observations and three retained period reports only.' };
    }
  });
}

function parseCall(result: any) {
  if (result?.isError) throw new Error((result.content ?? []).map((c: any) => c.text ?? '').join(''));
  const s = result?.structuredContent;
  if (s && typeof s === 'object') return Object.keys(s).length === 1 && 'result' in s ? s.result : s;
  const text = (result?.content ?? []).map((c: any) => c.text ?? '').join('');
  try { return JSON.parse(text); } catch { return text; }
}
