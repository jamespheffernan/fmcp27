import { execFile } from 'node:child_process';
import { createHash } from 'node:crypto';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

export const SKILL_TOOL = 'fm_read_skill';
const ROOT = fileURLToPath(new URL('../skills/', import.meta.url));
const MAX_BYTES = 65536;
// One page stays well inside Code Mode's 10,000-token (40,000-character) output budget, so a
// script can return a page together with other evidence without truncation.
export const PAGE_CHARS = 12000;
const READER = fileURLToPath(new URL('./fm-skill-reader.py', import.meta.url));
const CORE_GUIDE = fileURLToPath(new URL('./fm-core.md', import.meta.url));
const GUIDES = Object.freeze([
  { id: 'fm-db', title: 'SQL over the save snapshot', when: 'Only beyond the schema card: passes, percentiles, offers, finances, loanees, two-step scouting.', requires: 'fm_db_query' },
  { id: 'fm-reports', title: 'HTML reports', when: 'Before fm_report: sections and sources.', requires: 'fm_report' },
  { id: 'fm-tools', title: 'Evidence and tool routing', when: 'Match captures, retained shots and passes, international duty, HTML match reports, file output.' },
  { id: 'fm-live-investigation', title: 'Live query protocol', when: 'Identity, halftime, period, suspension, season-scope, captured-source and archive rules.' },
  { id: 'fm-tactical-analysis', title: 'Tactical analysis', when: 'For opposition plans, roles, spacing, match adjustments and post-match diagnosis.' },
  { id: 'fm-create-tactic', title: 'Native tactic files', when: 'Before inspecting, generating or saving an importable .fmf tactic.' },
  { id: 'fm-club-finance', title: 'Club finance and FFP', when: 'For balance, current or committed wages, debt, budgets, annual stadium rent, FFP, transfer affordability or another club\'s finances.' },
  { id: 'fm-squad-planning', title: 'Squad construction', when: 'For depth, succession, recruitment priorities, contracts, loans and development pathways.' },
  { id: 'fm-training-development', title: 'Training and development', when: 'For training calendars, recovery balance, stored focus or club intensity, positional conversion projects and development pathways.' },
  { id: 'fm-playing-time-dynamics', title: 'Playing time and dynamics', when: 'For agreed roles versus observed use, rotation priorities, happiness and promises.' },
  { id: 'fm-staff-planning', title: 'Staff planning', when: 'For coaching and recruitment staff strengths, appointment priorities, staff succession and renewals.' },
  { id: 'fm-contracts-loans', title: 'Contracts and loans', when: 'For player renewals, loan costs, purchase/recall terms, wage contributions and stored offers.' },
  { id: 'fm-season-planning', title: 'Season planning', when: 'For fixture congestion, rotation windows, competition priorities and stage or standings context.' },
  { id: 'fm-recruitment', title: 'Recruitment decisions', when: 'For comparing transfer targets or successors with the incumbent, dated interest and fee/wage scenarios.' },
  { id: 'fm-set-pieces', title: 'Set pieces', when: 'For penalty order and conditional dead-ball plans.' },
  { id: 'fm-club-development', title: 'Club development', when: 'For facilities, youth pathways and long-term investment priorities.' },
]);

/**
 * The guide catalogue. With `marked`, entries that need a reader tool (`requires`) are wrapped in
 * prompt conditions that fm-exposure.mjs resolves, so the system prompt lists them only when the
 * reader offers that tool.
 */
export function skillIndex({ marked = false } = {}) {
  const entry = g => {
    const line = `- **${g.id}** — ${g.title}. ${g.when}`;
    return marked && g.requires ? `<!-- fm:if ${g.requires} -->\n${line}\n<!-- fm:end -->` : line;
  };
  return '# Football guidance\n\n' +
    'The core procedure above is always loaded. Load a guide with fm_read_skill (tools.fm_read_skill in Code Mode) only when its trigger applies, once per conversation. Long guides come in pages; each result names the next page. Guides hold procedures, not career data.\n\n' +
    GUIDES.map(entry).join('\n') + '\n';
}

/** The always-loaded core guide (pi/fm-core.md). */
export function coreGuide() {
  return readFileSync(CORE_GUIDE, 'utf8');
}

/** Text appended to the system prompt: the core guide, then the guide index. */
export function appendedPrompt() {
  return `${coreGuide().trimEnd()}\n\n${skillIndex({ marked: true })}`;
}

/**
 * Split guide text into pages of at most `size` characters whose concatenation is the original.
 * Pages break before a `## ` heading when one fits, else at a blank line, else at a line end.
 */
export function paginate(content, size = PAGE_CHARS) {
  const pages = [];
  let rest = content;
  while (rest.length > size) {
    const window = rest.slice(0, size);
    let cut = -1;
    for (const marker of ['\n## ', '\n### ', '\n\n', '\n']) {
      const at = window.lastIndexOf(marker);
      // Do not leave a page less than a third full just to reach a nicer boundary.
      if (at > size / 3) { cut = at + 1; break; }
    }
    if (cut <= 0) cut = size;
    pages.push(rest.slice(0, cut));
    rest = rest.slice(cut);
  }
  pages.push(rest);
  return pages;
}

const PAGE_HEADER = /^\[fm-[a-z-]+: page \d+ of \d+[^\n]*\]\n\n/;

/** Remove the page header that fm_read_skill puts before a page of a multi-page guide. */
export function stripPageHeader(text) {
  return text.replace(PAGE_HEADER, '');
}

function pageText(id, body, page, pages) {
  if (pages === 1) return body;
  const next = page < pages
    ? ` Continue with fm_read_skill {"id":"${id}","page":${page + 1}} only if you need the rest.`
    : ' End of guide.';
  return `[${id}: page ${page} of ${pages}.${next}]\n\n${body}`;
}

export function validGuideIdentity(content, id) {
  if (typeof content !== 'string' || typeof id !== 'string' || !content.startsWith('---\n')) return false;
  // Bundled guides use LF and printable text. Alternate separators/control
  // bytes must not hide another metadata line from this flat-format parser.
  if (/[\u0000-\u0009\u000b-\u001f\u007f-\u009f\u2028\u2029]/.test(content)) return false;
  const lines = content.split('\n');
  const end = lines.indexOf('---', 1);
  if (end < 0) return false;
  const names = [];
  // Bundled frontmatter uses flat, unquoted keys. Reject ambiguous YAML forms
  // rather than interpret aliases, quoted keys or multiline identity fields.
  for (const line of lines.slice(1, end)) {
    if (line === '' || line.startsWith('#')) continue;
    const field = /^([a-z][a-z0-9_-]*):(?: ([^\n]*))?$/.exec(line);
    if (!field) return false;
    const value = (field[2] ?? '').replace(/^ +/, '');
    // Canonical plain scalars start with an ASCII letter/digit, so quoted,
    // block, flow, tag, anchor and hidden-prefix forms cannot open a scalar.
    if (value && !/^[A-Za-z0-9]/.test(value)) return false;
    if (/:(?: |$)/.test(value)) return false;
    if (field[1] === 'name') names.push(field[2]);
  }
  return names.length === 1 && names[0] === id;
}

async function readGuide(id, root) {
  const guide = GUIDES.find(g => g.id === id);
  if (!guide) throw new Error('Unknown guide id; use index to list approved guides.');
  // The fixed catalogue is the user API. root is trusted registration config;
  // the helper opens every directory and SKILL.md relative to held no-follow FDs.
  const result = await new Promise((accept, reject) => {
    execFile('/usr/bin/python3', ['-I', '-S', '-B', READER, resolve(root), guide.id],
      { encoding: 'utf8', maxBuffer: MAX_BYTES * 8, timeout: 5000 }, (error, stdout) => {
        if (error) return reject(new Error('Guide unavailable or changed during reading.'));
        try { accept(JSON.parse(stdout)); }
        catch { reject(new Error('Guide reader returned an invalid response.')); }
      });
  });
  const content = result.content;
  if (typeof content !== 'string') throw new Error('Guide reader returned no content.');
  const bytes = Buffer.from(content, 'utf8');
  const digest = createHash('sha256').update(bytes).digest('hex');
  if (bytes.length > MAX_BYTES || digest !== result.sha256 || !validGuideIdentity(content, id)) {
    throw new Error('Guide identity, size or hash does not match its catalogue id.');
  }
  return { id, title: guide.title, source: `skills/${id}/SKILL.md`, kind: 'guidance', content, sha256: digest };
}

export function registerSkillTool(pi, { root = ROOT } = {}) {
  pi.registerTool({
    name: SKILL_TOOL, label: 'Read football guidance',
    description: `Read approved football and MCP guidance by exact id, or index for the connected catalogue. Use for finance/FFP, squad construction, recruitment, contracts, training, playing-time concerns, facilities, set pieces, tactics and match investigations. Returns Markdown in pages of at most ${PAGE_CHARS} characters; a multi-page result starts with a header naming the next page. The content hash covers the whole guide. These are procedures, not live career facts. Reads only the fixed bundled guide files, with no arbitrary paths, shell, network or game access. Available directly and through tools.fm_read_skill in Code Mode.`,
    parameters: { type: 'object', additionalProperties: false,
      properties: {
        id: { type: 'string', enum: ['index', ...GUIDES.map(g => g.id)], description: 'Exact guide id from the football guidance index.' },
        page: { type: 'integer', minimum: 1, description: 'Page of a long guide, from 1 (default). The result header gives the page count.' },
      }, required: ['id'] },
    async execute(_id, params) {
      try {
        if (!params || Object.keys(params).some(k => k !== 'id' && k !== 'page') || typeof params.id !== 'string') throw new Error('Supply only an exact guide id and optional page.');
        const page = params.page ?? 1;
        if (!Number.isInteger(page) || page < 1) throw new Error('page must be a whole number from 1.');
        if (params.id === 'index') {
          const details = { id: 'index', kind: 'guidance_index', content: skillIndex(), guides: GUIDES };
          return { content: [{ type: 'text', text: details.content }], details };
        }
        const guide = await readGuide(params.id, root);
        const pages = paginate(guide.content);
        if (page > pages.length) throw new Error(`${params.id} has ${pages.length} page(s); page ${page} does not exist.`);
        const details = { ...guide, page, pages: pages.length };
        return { content: [{ type: 'text', text: pageText(params.id, pages[page - 1], page, pages.length) }], details };
      } catch (error) {
        return { content: [{ type: 'text', text: `Football guidance unavailable: ${error.message}` }], details: { error: true, id: params?.id ?? null }, isError: true };
      }
    },
  });
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url) && process.argv[2] === '--index') {
  process.stdout.write(appendedPrompt());
}
