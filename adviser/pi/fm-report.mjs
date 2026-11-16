// fm_report: turns a structured findings spec into one self-contained HTML
// report under ~/Agent Outputs. Validation and rendering live in the pure
// fm-report-render.mjs; this module owns the Pi registration and the write.
import { createHash } from 'node:crypto';
import { constants } from 'node:fs';
import { lstat, mkdir, open, realpath, unlink } from 'node:fs/promises';
import { homedir } from 'node:os';
import { dirname, join } from 'node:path';
import { LIMITS, ReportSpecError, SECTION_TYPES, renderReport, validateReportSpec } from './fm-report-render.mjs';

export const REPORT_TOOL = 'fm_report';
const MAX_FILENAME_BYTES = 200;
const MAX_SUFFIX = 50;

export function localDate(date, timeZone) {
  const parts = new Intl.DateTimeFormat('en-CA', { year: 'numeric', month: '2-digit', day: '2-digit', timeZone }).formatToParts(date);
  const get = type => parts.find(p => p.type === type).value;
  return `${get('year')}-${get('month')}-${get('day')}`;
}

const UNSAFE_NAME = /[/\\:*?"<>|\p{Cc}\p{Cf}\p{Zl}\p{Zp}]/u;

// One safe .html leaf: no directories, hidden names, control/format characters or other extensions.
export function checkFilename(name) {
  if (typeof name !== 'string') return 'filename must be text';
  if (!name || name !== name.trim()) return 'filename must not be empty or start/end with spaces';
  if (UNSAFE_NAME.test(name)) return 'filename must be a single name without folders, path separators, control characters or any of * ? " < > |';
  if (name.startsWith('.') || name.includes('..')) return 'filename must not start with a dot or contain ".."';
  if (!/\.html$/.test(name) || name.length <= 5) return 'filename must end in .html (lower case)';
  if (Buffer.byteLength(name, 'utf8') > MAX_FILENAME_BYTES) return `filename must be at most ${MAX_FILENAME_BYTES} bytes`;
  return null;
}

function titleStem(title) {
  const clean = title.normalize('NFC').replace(new RegExp(UNSAFE_NAME.source, 'gu'), ' ').replace(/\s+/g, ' ').replace(/^[.\s]+|[.\s]+$/g, '').trim();
  let stem = '';
  for (const ch of clean || 'FM report') {
    if (Buffer.byteLength(stem + ch, 'utf8') > 140) break;
    stem += ch;
  }
  return stem.trim();
}

// Dated, descriptive filename following the Agent Outputs convention: "YYYY-MM-DD — Title.html".
export function reportFilename(spec, { filename, date }) {
  if (filename !== undefined) {
    const problem = checkFilename(filename);
    if (problem) throw new ReportSpecError([`filename: ${problem}`]);
    if (/^\d{4}-\d{2}-\d{2}/.test(filename)) return { name: filename, explicit: true };
    const dated = `${date} — ${filename}`;
    if (Buffer.byteLength(dated, 'utf8') > MAX_FILENAME_BYTES) throw new ReportSpecError([`filename: with the date prefix it exceeds ${MAX_FILENAME_BYTES} bytes`]);
    return { name: dated, explicit: true };
  }
  return { name: `${date} — ${titleStem(spec.title)}.html`, explicit: false };
}

async function outputsRoot(configured) {
  const root = configured ?? join(await realpath(homedir()), 'Agent Outputs');
  try { await mkdir(root, { mode: 0o755 }); } catch (error) { if (error.code !== 'EEXIST') throw error; }
  const info = await lstat(root);
  if (!info.isDirectory() || info.isSymbolicLink()) throw new Error(`${root} is not a real directory; symlinked output folders are refused`);
  if (await realpath(root) !== root) throw new Error(`${root} resolves elsewhere; refusing to write through a linked path`);
  return root;
}

const CREATE_FLAGS = constants.O_WRONLY | constants.O_CREAT | constants.O_EXCL | (constants.O_NOFOLLOW ?? 0);

// Create the file exclusively (never overwrite, never follow a link), then confirm it is the inode written.
async function createExclusive(path, data) {
  const handle = await open(path, CREATE_FLAGS, 0o644);
  let ok = false;
  try {
    await handle.writeFile(data);
    await handle.sync();
    const written = await handle.stat();
    const named = await lstat(path);
    if (written.ino !== named.ino || written.dev !== named.dev || !named.isFile()) throw new Error('the report file changed while it was being written');
    if (await realpath(dirname(path)) !== dirname(path)) throw new Error('the output folder moved while the report was being written');
    ok = true;
  } finally {
    await handle.close();
    if (!ok) await unlink(path).catch(() => {});
  }
}

export async function writeReport(params, { outputsDir, now = new Date(), timeZone } = {}) {
  const spec = validateReportSpec(params);
  const html = renderReport(spec, { generatedAt: now, timeZone });
  const date = localDate(now, timeZone);
  const { name, explicit } = reportFilename(spec, { filename: params.filename, date });
  const root = await outputsRoot(outputsDir);
  const stem = name.slice(0, -'.html'.length);
  for (let n = 1; n <= (explicit ? 1 : MAX_SUFFIX); n++) {
    const leaf = n === 1 ? name : `${stem} (${n}).html`;
    const path = join(root, leaf);
    try {
      await createExclusive(path, html);
      const bytes = Buffer.byteLength(html, 'utf8');
      return {
        path, bytes,
        sha256: createHash('sha256').update(html).digest('hex'),
        title: spec.title, view: spec.view ?? 'unstated', game_date: spec.gameDate ?? null,
        sections: spec.sections.map(s => s.type),
        ...(spec.warnings?.length ? { repaired: spec.warnings } : {}),
      };
    } catch (error) {
      if (error.code !== 'EEXIST') throw error;
      if (explicit) throw new Error(`${path} already exists; existing files are never overwritten. Choose another filename or omit it for an automatic one.`);
    }
  }
  throw new Error(`more than ${MAX_SUFFIX} reports already use the name "${name}"; pass a distinct filename`);
}

const SECTION_HELP = [
  'Each section: {type, title?, note?, ...fields}. Types and fields:',
  'text {paragraphs?:string[], bullets?:string[]} (**bold** only);',
  'table {columns:[{key,label,type?:text|number|money|percent|rating|date|range, align?, unit?, decimals?, currency?, scale?:{min?,max?,style?:bar|heat,better?:high|low}}], rows:[{key:value}], highlight_rows?:int[]} — range cells take {min,max}, {exact}, a number (exact) or null (unknown) on a fixed 1-20 scale unless scale says otherwise;',
  'player_cards {players:[{name, subtitle?, facts?:[{label,value}], attributes?:{technical?,mental?,physical?,goalkeeping?:[{label,value:number|{min,max}|null}]}, key_attributes?:string[], use_when?, tags?}]};',
  'comparison {entities:[{name,subtitle?}] (2-4), metrics:[{label, values:[one per entity], type?, better?:high|low|none, group?, unit?, decimals?, currency?}]};',
  'bar_chart {bars:[{label,value,highlight?,note?}] or categories:string[] + series:[{name,values}] (max 3), value_label?, unit?, currency?, reference_lines?:[{value,label?}]};',
  'stacked_bar_chart {bars:[{label, target?, note?, segments:[{label,value,band?,hatched?,note?}]}], bands?:string[] (best first, max 5; each segment names one), value_label?, target_label?, hatched_label?, unit?} — one row per item split by who supplies it: segment width is the amount, band is the quality, hatched marks a compromise, target is the amount needed (a shortfall is drawn as not covered), note (up to 400 characters) runs under the bar;',
  'line_chart {series:[{name, points:[{x,y,label?}]}], x_type?:number|date|category, x_label?, y_label?, y_min?, y_max?, emphasis?, unit?, reference_lines?:[{axis?:y|x,value,label?}]};',
  'scatter {points:[{x,y,label?,group?,highlight?}], x_label, y_label, x_unit?, y_unit?, label_points?:highlighted|all|none, reference_lines?:[{axis:x|y,value,label?}]};',
  'pitch {teams?:[{id,name}] (second team attacks left), shots?:[{x,y,xg?,outcome:goal|saved|blocked|off_target|post,player?,minute?,team?}], positions?:[{id?,x,y,label(<=4 chars),name?,touches?,team?}], links?:[{from,to,count}] (position ids), zones?:[{x,y,w,h,value,label?}], show_zone_values?, formation?:{shape?, team?, slots:[FM position like "DL" or {position,name?,number?}]}} — x 0-100 from own goal line to the opponent goal, y 0-100 from the attacking team\'s left touchline;',
  'timeline {events:[{date:YYYY-MM-DD, label, subject?, detail?, kind?:contract|fixture|injury|loan|transfer|training|other, status?:good|warning|critical}]};',
  'kpis {items:[{label, value, type?:number|money|percent|rating|text, unit?, decimals?, delta?, delta_label?, better?:high|low|none, note?}]}.',
].join(' ');

export function registerReportTool(pi, options = {}) {
  pi.registerTool({
    name: REPORT_TOOL,
    label: 'Create FM HTML report',
    description: `Save findings as one self-contained offline HTML file (inline CSS/SVG) in ~/Agent Outputs. Call it only when the user asks for a report, a document or a file; give the answer in text first. Minimal spec: {"title":"Left-back shortlist","view":"manager","game_date":"2030-12-13","summary":"Sign X first: ...","sections":[{"type":"table","columns":[{"key":"name","label":"Player"},{"key":"age","label":"Age","type":"number"},{"key":"tackling","label":"Tackling","type":"range"}],"rows":[{"name":"X","age":19,"tackling":{"min":12,"max":15}}]}]}. Text columns accept numbers; numeric columns take numbers (words there are shown blank); range cells take {min,max}, a number or null. Long labels are shortened and unknown fields ignored; the receipt lists each repair. Caps: ${LIMITS.sections} sections, ${LIMITS.rows} table rows, ${LIMITS.scatterPoints} scatter points, ${LIMITS.shots} shots. Load guide fm-reports for charts, cards and pitches. Returns the absolute path. Never overwrites; no game changes.`,
    parameters: {
      type: 'object', additionalProperties: false,
      properties: {
        title: { type: 'string', maxLength: LIMITS.titleChars, description: 'Report title, e.g. "Left-back shortlist, January 2028".' },
        subtitle: { type: 'string', maxLength: LIMITS.subtitleChars },
        game_date: { type: 'string', description: 'In-game date the data describes, YYYY-MM-DD.' },
        view: { type: 'string', enum: ['manager', 'full'], description: 'manager = Manager knowledge (scouted, ranges); full = Full stored data.' },
        summary: { type: 'string', maxLength: LIMITS.summaryChars, description: 'The recommendation or answer first, 1-3 sentences.' },
        sections: {
          type: 'array', minItems: 1, maxItems: LIMITS.sections, description: SECTION_HELP,
          items: { type: 'object', required: ['type'], additionalProperties: true, properties: { type: { type: 'string', enum: SECTION_TYPES }, title: { type: 'string' }, note: { type: 'string' } } },
        },
        caveats: { type: 'array', maxItems: LIMITS.caveats, items: { type: 'string' }, description: 'Limits of the evidence, shown in the footer.' },
        sources: { type: 'array', maxItems: LIMITS.sources, items: { type: 'string' }, description: 'Tools or records the figures came from.' },
        filename: { type: 'string', description: 'Optional new .html file name only (no folders). A date prefix is added when missing; an existing name is refused.' },
      },
      required: ['title', 'summary', 'sections'],
    },
    async execute(_id, params) {
      try {
        if (!params || typeof params !== 'object') throw new ReportSpecError(['report: expected an object with title, summary and sections']);
        const details = await writeReport(params, options);
        return { content: [{ type: 'text', text: JSON.stringify(details) }], details };
      } catch (error) {
        const issues = error instanceof ReportSpecError ? error.issues : undefined;
        const message = issues ? `the spec has ${issues.length}${issues.length >= 12 ? '+' : ''} problem${issues.length === 1 ? '' : 's'}:\n- ${issues.join('\n- ')}` : error.message;
        return { content: [{ type: 'text', text: `Report not created: ${message}` }], details: { error: true, ...(issues ? { issues } : {}) }, isError: true };
      }
    },
  });
}
