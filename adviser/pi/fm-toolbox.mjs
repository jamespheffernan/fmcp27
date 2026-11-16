// Tools the adviser builds for itself.
//
// A saved tool is a Code Mode function kept on disk: a name, a description, and the body of
// `async (args) => { ... }`. `fm_toolbox` saves, edits, lists, reads and removes them. Every later Code
// Mode script, in any session, calls one as `await toolbox.<name>(args)`: the harness adds the
// functions a script names to that script before it runs (`withToolbox`, called from the
// `tool_call` hook in fm.pi.ts).
//
// A saved tool runs inside the same Code Mode sandbox as the script that calls it. It has no file
// system, network or shell, and each reader call it makes passes the same `tool_call` gate as a
// call the model makes itself, so saving a tool grants no access the adviser did not already have.
import {
  lstatSync, mkdirSync, readdirSync, readFileSync, renameSync, writeFileSync,
} from 'node:fs';
import { homedir } from 'node:os';
import { join } from 'node:path';

export const TOOLBOX_TOOL = 'fm_toolbox';
/** The global a Code Mode script reaches saved tools through. */
export const GLOBAL = 'toolbox';
export const NAME = /^[a-z][a-z0-9_]{2,47}$/;
export const MAX_CODE_CHARS = 65536;
export const MAX_TOOLS = 200;
const LIMITS = { description: 400, args: 800, returns: 400 };
const HEADER = '// @toolbox ';
const AsyncFunction = Object.getPrototypeOf(async () => {}).constructor;

/**
 * Where saved tools live: PI_FM_TOOLBOX_DIR, else ~/.pi/agent/pi-fm-toolbox. It is outside the
 * pi-fm checkout on purpose: installing a new adviser revision copies over the checkout with
 * `rsync --delete`, which would remove anything the adviser had saved inside it.
 */
export function toolboxDirectory(env = process.env) {
  return env.PI_FM_TOOLBOX_DIR || join(homedir(), '.pi', 'agent', 'pi-fm-toolbox');
}

function fail(message) {
  const error = new Error(message);
  error.toolbox = true;
  return error;
}

function checkName(name) {
  if (typeof name !== 'string' || !NAME.test(name)) {
    throw fail('Name the tool with 3 to 48 characters: a lowercase letter, then lowercase letters, digits or underscores (for example "squad_capacity").');
  }
  return name;
}

function checkText(field, value, { required = false } = {}) {
  if (value === undefined || value === null || value === '') {
    if (required) throw fail(`Give the tool a ${field}.`);
    return undefined;
  }
  if (typeof value !== 'string') throw fail(`"${field}" must be text.`);
  const text = value.replace(/\s+/g, ' ').trim();
  if (text.length > LIMITS[field]) throw fail(`"${field}" is limited to ${LIMITS[field]} characters; this one has ${text.length}.`);
  return text || undefined;
}

/** Parse the code as the function body it will run as. Nothing is executed. */
export function checkCode(code) {
  if (typeof code !== 'string' || !code.trim()) throw fail('Give the tool its code: the body of `async (args) => { ... }`.');
  if (code.length > MAX_CODE_CHARS) throw fail(`Tool code is limited to ${MAX_CODE_CHARS} characters; this one has ${code.length}.`);
  try {
    new AsyncFunction('args', code);
  } catch (error) {
    throw fail(`The code does not parse as the body of an async function: ${error.message}. Save the script that ran in Code Mode, reading its inputs from \`args\`.`);
  }
  return code.replace(/\s+$/, '') + '\n';
}

function parse(source) {
  const lines = source.split('\n');
  const at = lines.findIndex(line => line.startsWith(HEADER));
  if (at < 0) return null;
  let meta;
  try { meta = JSON.parse(lines[at].slice(HEADER.length)); } catch { return null; }
  if (!meta || typeof meta !== 'object' || typeof meta.name !== 'string') return null;
  return { ...meta, code: lines.slice(at + 1).join('\n') };
}

function render(tool) {
  const { code, ...meta } = tool;
  return `// pi-fm saved tool. Code Mode runs the lines below the header as the body of \`async (args) => { ... }\`;\n` +
    `// scripts call it as \`await ${GLOBAL}.${meta.name}(args)\`. Edit the code freely; keep the header on one line.\n` +
    `${HEADER}${JSON.stringify(meta)}\n${code}`;
}

export class Toolbox {
  constructor({ dir = toolboxDirectory(), now = () => new Date() } = {}) {
    this.dir = dir;
    this.now = now;
  }

  path(name) { return join(this.dir, `${name}.js`); }

  /** Every readable saved tool, by name. A file that does not parse is skipped, never fatal. */
  all() {
    let files;
    try { files = readdirSync(this.dir); } catch { return []; }
    const tools = [];
    for (const file of files.sort()) {
      if (!file.endsWith('.js')) continue;
      const name = file.slice(0, -3);
      if (!NAME.test(name)) continue;
      try {
        if (!lstatSync(join(this.dir, file)).isFile()) continue;
        const tool = parse(readFileSync(join(this.dir, file), 'utf8'));
        if (tool && tool.name === name) tools.push(tool);
      } catch { /* unreadable: leave it out */ }
    }
    return tools;
  }

  get(name) {
    checkName(name);
    const tool = this.all().find(candidate => candidate.name === name);
    if (!tool) {
      const names = this.all().map(candidate => candidate.name);
      throw fail(`No saved tool "${name}". Saved tools: ${names.join(', ') || '(none)'}.`);
    }
    return tool;
  }

  save({ name, description, args, returns, code, replace = false, game_date } = {}) {
    checkName(name);
    const existing = this.all();
    const previous = existing.find(candidate => candidate.name === name);
    // A new revision keeps the earlier description, arguments and return shape unless given new ones.
    const kept = previous && replace === true ? previous : {};
    const tool = {
      name,
      description: checkText('description', description ?? kept.description, { required: true }),
      args: checkText('args', args ?? kept.args),
      returns: checkText('returns', returns ?? kept.returns),
    };
    const body = checkCode(code);
    if (previous && replace !== true) {
      throw fail(`"${name}" is already saved (revision ${previous.revision ?? 1}: ${previous.description}). Pass replace: true to save a new revision of it (the earlier one is kept), or choose another name.`);
    }
    if (!previous && existing.length >= MAX_TOOLS) throw fail(`The toolbox holds ${MAX_TOOLS} tools, its limit. Remove one that is no longer used.`);
    mkdirSync(this.dir, { recursive: true, mode: 0o700 });
    tool.revision = (previous?.revision ?? 0) + 1;
    tool.saved_at = this.now().toISOString();
    if (typeof game_date === 'string' && game_date) tool.game_date = game_date;
    for (const key of Object.keys(tool)) if (tool[key] === undefined) delete tool[key];
    const target = this.path(name);
    const scratch = `${target}.${process.pid}.tmp`;
    // The new revision is on disk before the earlier one moves, so a failed write loses nothing.
    writeFileSync(scratch, render({ ...tool, code: body }), { mode: 0o600 });
    if (previous) this.#retire(previous);
    renameSync(scratch, target);
    return { ...tool, path: target, replaced_revision: previous ? previous.revision ?? 1 : undefined };
  }

  /**
   * Change a saved tool by exact text replacement, as a new revision. Each `old` must occur exactly
   * once in the code as it stands after the edits before it; nothing is saved unless all apply and
   * the result still parses.
   */
  edit({ name, edits, description, args, returns, game_date } = {}) {
    const tool = this.get(name);
    if (!Array.isArray(edits) || !edits.length) throw fail('Give edits: [{ old, new }], each `old` an exact piece of the saved code.');
    let code = tool.code;
    edits.forEach((change, i) => {
      if (typeof change?.old !== 'string' || !change.old || typeof change?.new !== 'string') {
        throw fail(`edits[${i}] needs old (the exact text to find) and new (its replacement).`);
      }
      const count = code.split(change.old).length - 1;
      if (count !== 1) {
        throw fail(`edits[${i}].old occurs ${count} times in "${name}"; it must occur exactly once. ` +
          (count ? 'Include more of the surrounding code.' : `Copy the exact text from ${TOOLBOX_TOOL}(action: "read").`) + ' Nothing was changed.');
      }
      code = code.replace(change.old, () => change.new);
    });
    return this.save({ name, description, args, returns, code, replace: true, game_date });
  }

  /** Removal keeps the file: it moves to history/, where a person can restore it. */
  remove(name) {
    const tool = this.get(name);
    return { name, removed_revision: tool.revision ?? 1, kept_at: this.#retire(tool) };
  }

  #retire(tool) {
    const history = join(this.dir, 'history');
    mkdirSync(history, { recursive: true, mode: 0o700 });
    const stamp = this.now().toISOString().replace(/[:.]/g, '-');
    const kept = join(history, `${tool.name}.r${tool.revision ?? 1}.${stamp}.js`);
    renameSync(this.path(tool.name), kept);
    return kept;
  }
}

/** `toolbox.squad_capacity(args)` with its description, as the prompt and `list` show it. */
export function describe(tool) {
  const parts = [`- \`${GLOBAL}.${tool.name}(args)\` — ${tool.description}`];
  if (tool.args) parts.push(`Args: ${tool.args}`);
  if (tool.returns) parts.push(`Returns: ${tool.returns}`);
  return parts.join(' ');
}

/** The saved-tools list for the system prompt, kept to `budget` characters. */
export function promptListing(tools, { budget = 6000 } = {}) {
  if (!tools.length) return 'No tools saved yet.';
  const head = `Saved tools (${tools.length}):`;
  const full = [head, ...tools.map(describe)].join('\n');
  if (full.length <= budget) return full;
  // Too many to describe in full: names with the first sentence, and `list` for the rest.
  const short = tools.map(tool => `- \`${GLOBAL}.${tool.name}(args)\` — ${tool.description.split(/(?<=\.)\s/)[0]}`);
  const lines = [head];
  let used = head.length;
  for (const line of short) {
    if (used + line.length + 1 > budget) break;
    lines.push(line);
    used += line.length + 1;
  }
  const left = tools.length - (lines.length - 1);
  lines.push(left > 0
    ? `${left} more, and every tool's arguments: \`${TOOLBOX_TOOL}(action: "list")\`.`
    : `Arguments of each: \`${TOOLBOX_TOOL}(action: "list")\`.`);
  return lines.join('\n');
}

const WORD = new RegExp(`\\b${GLOBAL}\\b`, 'g');
const DECLARED = new RegExp(`\\b(?:const|let|var|function|class)\\s+${GLOBAL}\\b`);
const MEMBER = new RegExp(`\\b${GLOBAL}\\s*(?:\\.\\s*([A-Za-z_$][\\w$]*)|\\[\\s*(['"])([^'"\\n]+)\\2\\s*\\])`, 'g');
const OPTIONS_LINE = /^\s*\/\/\s*@options:/;

/** Saved-tool names a script names, or null when it uses `toolbox` in a way that could reach any. */
function named(code) {
  const names = new Set();
  let members = 0;
  for (const match of code.matchAll(MEMBER)) {
    members += 1;
    names.add(match[1] ?? match[3]);
  }
  return (code.match(WORD) ?? []).length > members ? null : names;
}

/**
 * Give a Code Mode script the saved tools it names. Returns the script unchanged when it does not
 * mention `toolbox` or declares its own.
 *
 * The `toolbox` object goes at the start of the script's first line (after an `// @options:`
 * line, which Code Mode requires to stay first) and the functions go after its last line, so the
 * line numbers in the script's own errors do not move. Function declarations are hoisted, so the
 * object can name them before they appear.
 */
export function withToolbox(code, tools) {
  if (typeof code !== 'string' || !code.includes(GLOBAL) || DECLARED.test(code)) return code;
  const byName = new Map(tools.map(tool => [tool.name, tool]));
  const wanted = named(code);
  if (wanted && wanted.size === 0) return code;
  const include = new Set();
  const queue = wanted ? [...wanted] : [...byName.keys()];
  while (queue.length) {
    const name = queue.pop();
    const tool = byName.get(name);
    if (!tool || include.has(name)) continue;
    include.add(name);
    // A saved tool may call other saved tools.
    const inner = named(tool.code);
    queue.push(...(inner ?? byName.keys()));
  }
  const names = [...byName.keys()];
  const entries = [...include].map(name =>
    `${JSON.stringify(name)}: async (args) => { try { return await __toolbox_${name}(args); } catch (error) { ` +
    `if (error && typeof error.message === "string" && !error.message.startsWith("${GLOBAL}.")) error.message = "${GLOBAL}.${name}: " + error.message; throw error; } }`);
  const head = `const ${GLOBAL} = new Proxy({ ${entries.join(', ')} }, { get(target, key) { ` +
    `if (typeof key !== "string" || key in target || key === "then" || key === "toJSON") return target[key]; ` +
    `throw new Error("No saved tool \\"" + key + "\\". Saved tools: ${names.join(', ') || '(none)'}. Save one with ${TOOLBOX_TOOL}."); } }); `;
  const tail = [...include].map(name =>
    `\n;async function __toolbox_${name}(args = {}) {\n${byName.get(name).code}\n}`).join('');
  const lines = code.split('\n');
  const first = OPTIONS_LINE.test(lines[0]) ? 1 : 0;
  if (first === lines.length) lines.push('');
  lines[first] = head + lines[first];
  return lines.join('\n') + tail;
}

const PARAMETERS = {
  type: 'object', additionalProperties: false,
  properties: {
    action: { type: 'string', enum: ['save', 'edit', 'list', 'read', 'remove'], description: 'save a tool, edit a saved tool\'s code, list every saved tool, read one tool\'s code, or remove one.' },
    name: { type: 'string', description: 'Tool name: lowercase letters, digits and underscores, 3 to 48 characters. Needed for save, edit, read and remove.' },
    description: { type: 'string', description: 'save: what the tool works out and when to use it, in one or two sentences (at most 400 characters). It is shown in every later session.' },
    args: { type: 'string', description: 'save: the fields of the `args` object with their defaults, for example `{ horizon_days = 42, availability = 0.85, scenarios? }`.' },
    returns: { type: 'string', description: 'save: the shape of the returned value in a few words.' },
    code: { type: 'string', description: 'save: JavaScript, the body of `async (args) => { ... }`, as it ran in Code Mode. It may use `tools`, `text`, `store`, `load` and `toolbox`, must read the save at call time, and must `return` its result.' },
    replace: { type: 'boolean', description: 'save: true to save a new revision of an existing tool. The earlier revision is kept; description, args and returns carry over unless given.' },
    edits: {
      type: 'array', minItems: 1,
      description: 'edit: exact text replacements applied in order to the saved code. Each `old` must occur exactly once. All apply or none do; the result is saved as a new revision.',
      items: { type: 'object', additionalProperties: false, required: ['old', 'new'],
        properties: { old: { type: 'string', description: 'Exact text in the saved code.' }, new: { type: 'string', description: 'Its replacement.' } } },
    },
  },
  required: ['action'],
};

export function registerToolboxTool(pi, { toolbox = new Toolbox(), gameDate = () => undefined } = {}) {
  const act = params => {
    switch (params?.action) {
      case 'save': {
        const saved = toolbox.save({ ...params, game_date: gameDate() });
        return { ...saved, call: `await ${GLOBAL}.${saved.name}({ ... })`,
          next: `Run it once from Code Mode (\`return await ${GLOBAL}.${saved.name}({ ... })\`) and answer from that run.` };
      }
      case 'edit': {
        const saved = toolbox.edit({ ...params, game_date: gameDate() });
        return { ...saved, edits_applied: params.edits.length, call: `await ${GLOBAL}.${saved.name}({ ... })` };
      }
      case 'list': {
        const tools = toolbox.all();
        return { count: tools.length, directory: toolbox.dir, tools: tools.map(({ code, ...meta }) => ({ ...meta, lines: code.split('\n').length })) };
      }
      case 'read': return toolbox.get(params.name);
      case 'remove': return toolbox.remove(params.name);
      default: throw fail('action must be save, edit, list, read or remove.');
    }
  };
  pi.registerTool({
    name: TOOLBOX_TOOL,
    label: 'FM toolbox',
    description: `Build tools for yourself. A saved tool is a Code Mode function kept between sessions; every Code Mode script calls it as \`await ${GLOBAL}.<name>(args)\`. ` +
      'save: keep a script as a tool, with its inputs read from `args`. edit: correct or extend a saved tool by exact text replacement, without sending the whole code again. list: every saved tool. read: one tool\'s code. remove: retire one (the file is kept in history). ' +
      'Saved tools read the game like any script and cannot change it.',
    parameters: PARAMETERS,
    async execute(_id, params) {
      try {
        const details = act(params);
        return { content: [{ type: 'text', text: JSON.stringify(details) }], details };
      } catch (error) {
        const message = error?.toolbox ? error.message : `Toolbox ${params?.action ?? 'call'} failed: ${error?.message ?? error}`;
        return { content: [{ type: 'text', text: message }], details: { error: true }, isError: true };
      }
    },
  });
  return toolbox;
}
