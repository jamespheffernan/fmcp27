// Pure renderer for fm_report: validates a model-written report spec and
// returns one self-contained HTML document (inline CSS, inline SVG, a small
// sorting script, no network). No Pi imports; every string is untrusted.
import { createHash } from 'node:crypto';

export const LIMITS = Object.freeze({
  sections: 30,
  titleChars: 120,
  subtitleChars: 200,
  summaryChars: 700,
  caveats: 12,
  sources: 16,
  noteChars: 400,
  labelChars: 120,
  shortChars: 60,
  paragraphChars: 1200,
  paragraphs: 12,
  bullets: 20,
  bulletChars: 400,
  columns: 14,
  rows: 400,
  cells: 12000,
  players: 8,
  facts: 8,
  attributesPerGroup: 16,
  tags: 6,
  entities: 4,
  metrics: 40,
  bars: 40,
  categories: 30,
  barSeries: 3,
  stackSegments: 16,
  stackBands: 5,
  lineSeries: 6,
  linePoints: 400,
  scatterPoints: 600,
  scatterGroups: 3,
  scatterLabels: 40,
  referenceLines: 6,
  shots: 150,
  positions: 30,
  links: 200,
  zones: 400,
  formationSlots: 11,
  pitchTeams: 2,
  events: 150,
  kpis: 8,
  marks: 8000,
  htmlBytes: 4 * 1024 * 1024,
});

export const SECTION_TYPES = Object.freeze(['text', 'table', 'player_cards', 'comparison', 'bar_chart', 'stacked_bar_chart', 'line_chart', 'scatter', 'pitch', 'timeline', 'kpis']);
const VALUE_TYPES = ['text', 'number', 'money', 'percent', 'rating', 'date', 'range'];
const ATTRIBUTE_GROUPS = ['technical', 'mental', 'physical', 'goalkeeping'];
const SHOT_OUTCOMES = ['goal', 'saved', 'blocked', 'off_target', 'post'];
const EVENT_KINDS = ['contract', 'fixture', 'injury', 'loan', 'transfer', 'training', 'other'];
const STATUSES = ['good', 'warning', 'critical'];
const MAX_ISSUES = 12;

export class ReportSpecError extends Error {
  constructor(issues) {
    super(`Invalid report spec:\n- ${issues.join('\n- ')}`);
    this.name = 'ReportSpecError';
    this.issues = issues;
  }
}

// ---------------------------------------------------------------- validation

class Checker {
  constructor() { this.issues = []; this.warnings = []; this.cells = 0; this.marks = 0; }
  fail(path, message) {
    this.issues.push(`${path}: ${message}`);
    if (this.issues.length >= MAX_ISSUES) throw new ReportSpecError(this.issues);
    return undefined;
  }
  // A repair that cannot change a figure (a shortened label, an ignored field, a blank cell) is
  // made and reported in the receipt instead of refusing the whole report.
  warn(path, message) {
    if (this.warnings.length < 20) this.warnings.push(`${path}: ${message}`);
  }
  done() { if (this.issues.length) throw new ReportSpecError(this.issues); }
  budget(kind, n, path) {
    this[kind] += n;
    const limit = kind === 'cells' ? LIMITS.cells : LIMITS.marks;
    if (this[kind] > limit) this.fail(path, `the report exceeds the ${limit} ${kind === 'cells' ? 'table cells' : 'chart marks'} cap; split it or summarise`);
  }
}

const describe = value => {
  if (value === null) return 'null';
  if (Array.isArray(value)) return 'an array';
  if (typeof value === 'string') return `string ${JSON.stringify(value.length > 24 ? `${value.slice(0, 24)}…` : value)}`;
  return typeof value === 'object' ? 'an object' : `${typeof value} ${String(value)}`;
};
const isPlain = value => value !== null && typeof value === 'object' && !Array.isArray(value) && Object.getPrototypeOf(value) === Object.prototype;
// C0/C1 controls (except tab/newline), bidi overrides and line/paragraph separators.
const codePointClass = ranges => ranges.map(([a, b]) => `${String.fromCodePoint(a)}-${String.fromCodePoint(b)}`).join('');
const BAD_TEXT = new RegExp(`[${codePointClass([[0x0, 0x8], [0xb, 0x1f], [0x7f, 0x9f], [0x200e, 0x200f], [0x202a, 0x202e], [0x2028, 0x2029], [0x2066, 0x2069]])}]`, 'u');

function object(c, value, path, allowed, required = []) {
  if (!isPlain(value)) return c.fail(path, `expected an object, got ${describe(value)}`), false;
  for (const key of Object.keys(value)) {
    if (!allowed.includes(key)) c.warn(`${path}.${key}`, `unknown field ignored; allowed fields are ${allowed.join(', ')}`);
  }
  for (const key of required) {
    if (value[key] === undefined) c.fail(`${path}.${key}`, 'is required');
  }
  return true;
}

function text(c, value, path, { max = LIMITS.labelChars, optional = false, multiline = false } = {}) {
  if (value === undefined && optional) return undefined;
  if (typeof value === 'number' && Number.isFinite(value)) value = String(value);
  if (typeof value !== 'string') return c.fail(path, `expected text, got ${describe(value)}`);
  let trimmed = value.trim();
  if (!trimmed) return optional ? undefined : c.fail(path, 'must not be empty');
  if (!multiline) trimmed = trimmed.replace(/[\n\t]+/g, ' ');
  if (BAD_TEXT.test(trimmed)) return c.fail(path, 'contains control or direction-override characters');
  const chars = [...trimmed];
  if (chars.length > max) {
    c.warn(path, `shortened from ${chars.length} to ${max} characters`);
    trimmed = `${chars.slice(0, max - 1).join('').trimEnd()}…`;
  }
  return trimmed;
}

// Plain numerals written as text ("1,250", "12.5", "40%") are read as numbers; nothing else is guessed.
const NUMERAL = /^[-+−]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?%?$/;
const numeral = value => (typeof value === 'string' && NUMERAL.test(value.trim()) ? Number(value.trim().replace(/[,%]/g, '').replace('−', '-')) : undefined);

function number(c, value, path, { min = -1e12, max = 1e12, integer = false, optional = false } = {}) {
  if (value === undefined && optional) return undefined;
  if (numeral(value) !== undefined) value = numeral(value);
  if (typeof value !== 'number' || !Number.isFinite(value)) return c.fail(path, `expected a finite number, got ${describe(value)}`);
  if (integer && !Number.isInteger(value)) return c.fail(path, 'expected a whole number');
  if (value < min || value > max) return c.fail(path, `must be between ${min} and ${max}`);
  return value;
}

function choice(c, value, path, values, { optional = false } = {}) {
  if (value === undefined && optional) return undefined;
  if (!values.includes(value)) return c.fail(path, `must be one of ${values.join(', ')}; got ${describe(value)}`);
  return value;
}

function list(c, value, path, { min = 0, max, optional = false } = {}) {
  if (value === undefined && optional) return [];
  if (!Array.isArray(value)) return c.fail(path, `expected an array, got ${describe(value)}`), [];
  if (value.length < min) return c.fail(path, `needs at least ${min} item${min === 1 ? '' : 's'}`), [];
  if (value.length > max) return c.fail(path, `has ${value.length} items; the cap is ${max}`), [];
  return value;
}

function boolean(c, value, path) {
  if (value === undefined) return false;
  if (typeof value !== 'boolean') return c.fail(path, `expected true or false, got ${describe(value)}`), false;
  return value;
}

export function isoDay(value) {
  if (typeof value !== 'string' || !/^\d{4}-\d{2}-\d{2}$/.test(value)) return undefined;
  const ms = Date.UTC(+value.slice(0, 4), +value.slice(5, 7) - 1, +value.slice(8, 10));
  const d = new Date(ms);
  return d.toISOString().slice(0, 10) === value ? ms / 86400000 : undefined;
}

function date(c, value, path, { optional = false } = {}) {
  if (value === undefined && optional) return undefined;
  if (isoDay(value) === undefined) return c.fail(path, `expected an ISO date YYYY-MM-DD, got ${describe(value)}`);
  return value;
}

// A fog-of-war value: exact number, {min,max}, {exact}, or null for unknown.
function rangeValue(c, value, path, scale) {
  if (value === null || value === undefined) return { kind: 'unknown' };
  if (typeof value === 'number') {
    const v = number(c, value, path, { min: scale.min, max: scale.max });
    return v === undefined ? { kind: 'unknown' } : { kind: 'exact', value: v };
  }
  if (!object(c, value, path, ['min', 'max', 'exact'])) return { kind: 'unknown' };
  if (value.exact !== undefined) {
    const v = number(c, value.exact, `${path}.exact`, { min: scale.min, max: scale.max });
    return v === undefined ? { kind: 'unknown' } : { kind: 'exact', value: v };
  }
  if (value.min === undefined || value.max === undefined) return c.fail(path, 'a range needs both min and max (or exact; null means unknown)'), { kind: 'unknown' };
  const lo = number(c, value.min, `${path}.min`, { min: scale.min, max: scale.max });
  const hi = number(c, value.max, `${path}.max`, { min: scale.min, max: scale.max });
  if (lo === undefined || hi === undefined) return { kind: 'unknown' };
  if (lo > hi) return c.fail(path, `min ${lo} is greater than max ${hi}`), { kind: 'unknown' };
  return lo === hi ? { kind: 'exact', value: lo } : { kind: 'range', min: lo, max: hi };
}

const FORMAT_FIELDS = ['unit', 'decimals', 'currency'];
function format(c, value, path) {
  return {
    unit: text(c, value.unit, `${path}.unit`, { max: 16, optional: true }),
    decimals: number(c, value.decimals, `${path}.decimals`, { min: 0, max: 3, integer: true, optional: true }),
    currency: text(c, value.currency, `${path}.currency`, { max: 3, optional: true }),
  };
}

function cell(c, value, path, type, scale) {
  // An empty string is a blank cell, like null: a table built by a tool has optional columns (a
  // deadline only some rows have), and refusing the whole report for them loses the report.
  if (value === null || value === undefined || (typeof value === 'string' && !value.trim())) return type === 'range' ? { kind: 'unknown' } : null;
  switch (type) {
    // A number in a text column (the default type) is shown as written rather than refused.
    case 'text': return typeof value === 'number' && Number.isFinite(value) ? String(value) : text(c, value, path, { max: 300 }) ?? null;
    case 'date': return date(c, value, path) ?? null;
    case 'range': return rangeValue(c, value, path, scale);
    default:
      // Words in a numeric column ("16 / 16", "n/a") would distort sorting and bars: the cell is
      // left blank and the receipt says so.
      if (typeof value === 'string' && numeral(value) === undefined) {
        c.warn(path, `${describe(value)} is not a number; the cell is shown blank (use a text column for words)`);
        return null;
      }
      return number(c, value, path) ?? null;
  }
}

function scaleSpec(c, value, path, type) {
  const fixed = type === 'rating' || type === 'range';
  if (value === undefined) return fixed ? { min: 1, max: 20, style: type === 'range' ? 'range' : undefined } : undefined;
  if (!object(c, value, path, ['min', 'max', 'style', 'better'])) return undefined;
  const style = type === 'range' ? 'range' : choice(c, value.style ?? 'bar', `${path}.style`, ['bar', 'heat']);
  const min = number(c, value.min, `${path}.min`, { optional: true }) ?? (fixed ? 1 : undefined);
  const max = number(c, value.max, `${path}.max`, { optional: true }) ?? (fixed ? 20 : undefined);
  if (min !== undefined && max !== undefined && min >= max) c.fail(path, 'min must be below max');
  return { min, max, style, better: choice(c, value.better ?? 'high', `${path}.better`, ['high', 'low']) };
}

function referenceLines(c, value, path, axes) {
  return list(c, value, path, { max: LIMITS.referenceLines, optional: true }).map((line, i) => {
    const p = `${path}[${i}]`;
    if (!object(c, line, p, ['axis', 'value', 'label'], ['value'])) return null;
    const axis = choice(c, line.axis ?? axes[0], `${p}.axis`, axes);
    const v = axis === 'x' && line.value !== undefined && typeof line.value === 'string' ? (isoDay(line.value) ?? c.fail(`${p}.value`, 'expected a number or ISO date')) : number(c, line.value, `${p}.value`);
    return { axis, value: v, label: text(c, line.label, `${p}.label`, { max: LIMITS.shortChars, optional: true }) };
  }).filter(Boolean);
}

const SECTION_FIELDS = {
  text: ['paragraphs', 'bullets'],
  table: ['columns', 'rows', 'highlight_rows'],
  player_cards: ['players'],
  comparison: ['entities', 'metrics'],
  bar_chart: ['bars', 'categories', 'series', 'value_label', 'reference_lines', ...FORMAT_FIELDS],
  stacked_bar_chart: ['bars', 'bands', 'value_label', 'target_label', 'hatched_label', 'unit', 'decimals'],
  line_chart: ['series', 'x_type', 'x_label', 'y_label', 'y_min', 'y_max', 'reference_lines', 'emphasis', ...FORMAT_FIELDS],
  scatter: ['points', 'x_label', 'y_label', 'x_unit', 'y_unit', 'reference_lines', 'label_points'],
  pitch: ['teams', 'shots', 'positions', 'links', 'zones', 'formation', 'show_zone_values'],
  timeline: ['events'],
  kpis: ['items'],
};

const SECTION_VALIDATORS = {
  text(c, s, p) {
    const paragraphs = list(c, s.paragraphs, `${p}.paragraphs`, { max: LIMITS.paragraphs, optional: true }).map((v, i) => text(c, v, `${p}.paragraphs[${i}]`, { max: LIMITS.paragraphChars, multiline: true })).filter(Boolean);
    const bullets = list(c, s.bullets, `${p}.bullets`, { max: LIMITS.bullets, optional: true }).map((v, i) => text(c, v, `${p}.bullets[${i}]`, { max: LIMITS.bulletChars })).filter(Boolean);
    if (!paragraphs.length && !bullets.length && s.paragraphs === undefined && s.bullets === undefined) c.fail(p, 'a text section needs paragraphs or bullets');
    return { paragraphs, bullets };
  },
  table(c, s, p) {
    const keys = new Set();
    const columns = list(c, s.columns, `${p}.columns`, { min: 1, max: LIMITS.columns }).map((col, i) => {
      const cp = `${p}.columns[${i}]`;
      if (!object(c, col, cp, ['key', 'label', 'type', 'align', 'scale', ...FORMAT_FIELDS], ['key', 'label'])) return null;
      const key = text(c, col.key, `${cp}.key`, { max: 40 });
      if (key && keys.has(key)) c.fail(`${cp}.key`, `duplicate column key "${key}"`);
      if (key) keys.add(key);
      const type = choice(c, col.type ?? 'text', `${cp}.type`, VALUE_TYPES);
      return { key, label: text(c, col.label, `${cp}.label`, { max: 60 }), type, align: choice(c, col.align ?? (['text', 'date'].includes(type) ? 'left' : 'right'), `${cp}.align`, ['left', 'right', 'center']), scale: scaleSpec(c, col.scale, `${cp}.scale`, type), ...format(c, col, cp) };
    }).filter(Boolean);
    const rawRows = list(c, s.rows, `${p}.rows`, { max: LIMITS.rows });
    c.budget('cells', rawRows.length * columns.length, `${p}.rows`);
    const rows = rawRows.map((row, r) => {
      const rp = `${p}.rows[${r}]`;
      if (!object(c, row, rp, columns.map(col => col.key))) return null;
      return Object.fromEntries(columns.map(col => [col.key, cell(c, row[col.key], `${rp}.${col.key}`, col.type, col.scale ?? {})]));
    }).filter(Boolean);
    const highlight = list(c, s.highlight_rows, `${p}.highlight_rows`, { max: LIMITS.rows, optional: true }).map((v, i) => number(c, v, `${p}.highlight_rows[${i}]`, { min: 0, max: Math.max(0, rawRows.length - 1), integer: true }));
    return { columns, rows, highlight: new Set(highlight) };
  },
  player_cards(c, s, p) {
    const players = list(c, s.players, `${p}.players`, { min: 1, max: LIMITS.players }).map((pl, i) => {
      const pp = `${p}.players[${i}]`;
      if (!object(c, pl, pp, ['name', 'subtitle', 'facts', 'attributes', 'key_attributes', 'use_when', 'tags'], ['name'])) return null;
      const facts = list(c, pl.facts, `${pp}.facts`, { max: LIMITS.facts, optional: true }).map((f, j) => {
        const fp = `${pp}.facts[${j}]`;
        if (!object(c, f, fp, ['label', 'value'], ['label', 'value'])) return null;
        const value = typeof f.value === 'number' ? (number(c, f.value, `${fp}.value`) ?? 0).toLocaleString('en-GB') : text(c, f.value, `${fp}.value`, { max: 80 });
        return { label: text(c, f.label, `${fp}.label`, { max: 40 }), value };
      }).filter(Boolean);
      const attributes = [];
      if (pl.attributes !== undefined && object(c, pl.attributes, `${pp}.attributes`, ATTRIBUTE_GROUPS)) {
        for (const group of ATTRIBUTE_GROUPS) {
          const items = list(c, pl.attributes[group], `${pp}.attributes.${group}`, { max: LIMITS.attributesPerGroup, optional: true }).map((a, j) => {
            const ap = `${pp}.attributes.${group}[${j}]`;
            if (!object(c, a, ap, ['label', 'value'], ['label'])) return null;
            return { label: text(c, a.label, `${ap}.label`, { max: 32 }), value: rangeValue(c, a.value, `${ap}.value`, { min: 1, max: 20 }) };
          }).filter(Boolean);
          if (items.length) attributes.push({ group, items });
        }
      }
      c.budget('marks', attributes.reduce((n, g) => n + g.items.length, 0), pp);
      return {
        name: text(c, pl.name, `${pp}.name`, { max: 80 }),
        subtitle: text(c, pl.subtitle, `${pp}.subtitle`, { max: 120, optional: true }),
        facts, attributes,
        key: new Set(list(c, pl.key_attributes, `${pp}.key_attributes`, { max: 20, optional: true }).map((v, j) => text(c, v, `${pp}.key_attributes[${j}]`, { max: 32 })).filter(Boolean).map(v => v.toLowerCase())),
        useWhen: text(c, pl.use_when, `${pp}.use_when`, { max: 300, optional: true }),
        tags: list(c, pl.tags, `${pp}.tags`, { max: LIMITS.tags, optional: true }).map((v, j) => text(c, v, `${pp}.tags[${j}]`, { max: 32 })).filter(Boolean),
      };
    }).filter(Boolean);
    return { players };
  },
  comparison(c, s, p) {
    const entities = list(c, s.entities, `${p}.entities`, { min: 2, max: LIMITS.entities }).map((e, i) => {
      const ep = `${p}.entities[${i}]`;
      if (!object(c, e, ep, ['name', 'subtitle'], ['name'])) return null;
      return { name: text(c, e.name, `${ep}.name`, { max: 80 }), subtitle: text(c, e.subtitle, `${ep}.subtitle`, { max: 120, optional: true }) };
    }).filter(Boolean);
    const metrics = list(c, s.metrics, `${p}.metrics`, { min: 1, max: LIMITS.metrics }).map((m, i) => {
      const mp = `${p}.metrics[${i}]`;
      if (!object(c, m, mp, ['label', 'values', 'type', 'better', 'group', 'scale', ...FORMAT_FIELDS], ['label', 'values'])) return null;
      const type = choice(c, m.type ?? 'number', `${mp}.type`, VALUE_TYPES);
      const scale = scaleSpec(c, m.scale, `${mp}.scale`, type) ?? {};
      const values = list(c, m.values, `${mp}.values`, { min: entities.length, max: entities.length });
      if (Array.isArray(m.values) && m.values.length !== entities.length) c.fail(`${mp}.values`, `needs exactly one value per entity (${entities.length})`);
      return {
        label: text(c, m.label, `${mp}.label`, { max: 60 }), type, scale,
        better: choice(c, m.better ?? (['text', 'date'].includes(type) ? 'none' : 'high'), `${mp}.better`, ['high', 'low', 'none']),
        group: text(c, m.group, `${mp}.group`, { max: 40, optional: true }),
        values: values.map((v, j) => cell(c, v, `${mp}.values[${j}]`, type, scale)),
        ...format(c, m, mp),
      };
    }).filter(Boolean);
    c.budget('cells', metrics.length * entities.length, p);
    return { entities, metrics };
  },
  bar_chart(c, s, p) {
    const fmt = format(c, s, p);
    const refs = referenceLines(c, s.reference_lines, `${p}.reference_lines`, ['value']);
    const valueLabel = text(c, s.value_label, `${p}.value_label`, { max: 60, optional: true });
    if (s.bars !== undefined && (s.categories !== undefined || s.series !== undefined)) c.fail(p, 'use either bars (one series) or categories with series (grouped), not both');
    if (s.bars !== undefined || s.categories === undefined) {
      const bars = list(c, s.bars, `${p}.bars`, { min: 1, max: LIMITS.bars }).map((b, i) => {
        const bp = `${p}.bars[${i}]`;
        if (!object(c, b, bp, ['label', 'value', 'highlight', 'note'], ['label', 'value'])) return null;
        return { label: text(c, b.label, `${bp}.label`, { max: 60 }), value: number(c, b.value, `${bp}.value`) ?? 0, highlight: boolean(c, b.highlight, `${bp}.highlight`), note: text(c, b.note, `${bp}.note`, { max: 40, optional: true }) };
      }).filter(Boolean);
      c.budget('marks', bars.length, p);
      return { ...fmt, valueLabel, refs, categories: bars.map(b => b.label), series: [{ name: valueLabel ?? 'Value', values: bars.map(b => b.value) }], highlight: bars.map(b => b.highlight), notes: bars.map(b => b.note) };
    }
    const categories = list(c, s.categories, `${p}.categories`, { min: 1, max: LIMITS.categories }).map((v, i) => text(c, v, `${p}.categories[${i}]`, { max: 60 }) ?? '');
    const series = list(c, s.series, `${p}.series`, { min: 1, max: LIMITS.barSeries }).map((se, i) => {
      const sp = `${p}.series[${i}]`;
      if (!object(c, se, sp, ['name', 'values'], ['name', 'values'])) return null;
      const values = list(c, se.values, `${sp}.values`, { min: categories.length, max: categories.length });
      if (Array.isArray(se.values) && se.values.length !== categories.length) c.fail(`${sp}.values`, `needs one value per category (${categories.length})`);
      return { name: text(c, se.name, `${sp}.name`, { max: 40 }), values: values.map((v, j) => number(c, v, `${sp}.values[${j}]`) ?? 0) };
    }).filter(Boolean);
    c.budget('marks', categories.length * series.length, p);
    return { ...fmt, valueLabel, refs, categories, series, highlight: categories.map(() => false), notes: [] };
  },
  // One bar per row, split into labelled segments (who supplies how much), each in an ordered band
  // (how good), optionally hatched (a compromise), against the row's target (how much is needed).
  stacked_bar_chart(c, s, p) {
    const fmt = { unit: text(c, s.unit, `${p}.unit`, { max: 16, optional: true }), decimals: number(c, s.decimals, `${p}.decimals`, { min: 0, max: 3, integer: true, optional: true }) };
    const valueLabel = text(c, s.value_label, `${p}.value_label`, { max: 60, optional: true });
    const targetLabel = text(c, s.target_label, `${p}.target_label`, { max: 40, optional: true });
    const hatchedLabel = text(c, s.hatched_label, `${p}.hatched_label`, { max: 40, optional: true });
    const bands = list(c, s.bands, `${p}.bands`, { max: LIMITS.stackBands, optional: true }).map((v, i) => text(c, v, `${p}.bands[${i}]`, { max: 40 }) ?? '');
    if (new Set(bands).size !== bands.length) c.fail(`${p}.bands`, 'band names must differ');
    let marks = 0;
    const bars = list(c, s.bars, `${p}.bars`, { min: 1, max: LIMITS.categories }).map((b, i) => {
      const bp = `${p}.bars[${i}]`;
      if (!object(c, b, bp, ['label', 'note', 'target', 'segments'], ['label', 'segments'])) return null;
      const segments = list(c, b.segments, `${bp}.segments`, { max: LIMITS.stackSegments }).map((g, j) => {
        const gp = `${bp}.segments[${j}]`;
        if (!object(c, g, gp, ['label', 'value', 'band', 'hatched', 'note'], ['label', 'value'])) return null;
        let band = -1;
        if (bands.length) band = bands.indexOf(choice(c, g.band, `${gp}.band`, bands));
        else if (g.band !== undefined) c.fail(`${gp}.band`, 'name the bands, best first, in the section\'s bands list');
        return { label: text(c, g.label, `${gp}.label`, { max: 60 }) ?? '', value: number(c, g.value, `${gp}.value`, { min: 0 }) ?? 0, band,
          hatched: boolean(c, g.hatched, `${gp}.hatched`), note: text(c, g.note, `${gp}.note`, { max: 80, optional: true }) };
      }).filter(Boolean);
      marks += segments.length + 1;
      return { label: text(c, b.label, `${bp}.label`, { max: 60 }) ?? '', note: text(c, b.note, `${bp}.note`, { max: LIMITS.noteChars, optional: true }),
        target: number(c, b.target, `${bp}.target`, { min: 0, optional: true }), segments };
    }).filter(Boolean);
    c.budget('marks', marks, p);
    return { ...fmt, valueLabel, targetLabel, hatchedLabel, bands, bars };
  },
  line_chart(c, s, p) {
    const xType = choice(c, s.x_type ?? 'number', `${p}.x_type`, ['number', 'date', 'category']);
    let total = 0;
    const categories = [];
    const series = list(c, s.series, `${p}.series`, { min: 1, max: LIMITS.lineSeries }).map((se, i) => {
      const sp = `${p}.series[${i}]`;
      if (!object(c, se, sp, ['name', 'points'], ['name', 'points'])) return null;
      const points = list(c, se.points, `${sp}.points`, { min: 1, max: LIMITS.linePoints }).map((pt, j) => {
        const pp = `${sp}.points[${j}]`;
        if (!object(c, pt, pp, ['x', 'y', 'label'], ['x', 'y'])) return null;
        let x;
        if (xType === 'date') x = isoDay(pt.x) ?? c.fail(`${pp}.x`, `expected an ISO date, got ${describe(pt.x)}`);
        else if (xType === 'category') {
          const label = text(c, String(pt.x ?? ''), `${pp}.x`, { max: 40 });
          if (label !== undefined && !categories.includes(label)) categories.push(label);
          x = categories.indexOf(label);
        } else x = number(c, pt.x, `${pp}.x`);
        const y = pt.y === null ? null : number(c, pt.y, `${pp}.y`);
        if (x === undefined || x < 0 && xType === 'category' || y === undefined) return null;
        return { x, y, label: text(c, pt.label, `${pp}.label`, { max: 40, optional: true }) };
      }).filter(Boolean);
      total += points.length;
      return { name: text(c, se.name, `${sp}.name`, { max: 40 }), points: points.sort((a, b) => a.x - b.x) };
    }).filter(Boolean);
    c.budget('marks', total, p);
    const emphasis = text(c, s.emphasis, `${p}.emphasis`, { max: 40, optional: true });
    if (emphasis && !series.some(se => se.name === emphasis)) c.fail(`${p}.emphasis`, 'must equal one series name');
    return {
      xType, categories, series, emphasis,
      xLabel: text(c, s.x_label, `${p}.x_label`, { max: 60, optional: true }),
      yLabel: text(c, s.y_label, `${p}.y_label`, { max: 60, optional: true }),
      yMin: number(c, s.y_min, `${p}.y_min`, { optional: true }), yMax: number(c, s.y_max, `${p}.y_max`, { optional: true }),
      refs: referenceLines(c, s.reference_lines, `${p}.reference_lines`, ['y', 'x']),
      ...format(c, s, p),
    };
  },
  scatter(c, s, p) {
    const groups = [];
    const points = list(c, s.points, `${p}.points`, { min: 1, max: LIMITS.scatterPoints }).map((pt, i) => {
      const pp = `${p}.points[${i}]`;
      if (!object(c, pt, pp, ['x', 'y', 'label', 'group', 'highlight'], ['x', 'y'])) return null;
      const group = text(c, pt.group, `${pp}.group`, { max: 40, optional: true });
      if (group !== undefined && !groups.includes(group)) {
        if (groups.length >= LIMITS.scatterGroups) c.fail(`${pp}.group`, `at most ${LIMITS.scatterGroups} groups keep colours distinguishable; fold the rest into one group`);
        else groups.push(group);
      }
      return { x: number(c, pt.x, `${pp}.x`) ?? 0, y: number(c, pt.y, `${pp}.y`) ?? 0, label: text(c, pt.label, `${pp}.label`, { max: 40, optional: true }), group, highlight: boolean(c, pt.highlight, `${pp}.highlight`) };
    }).filter(Boolean);
    c.budget('marks', points.length, p);
    return {
      points, groups,
      xLabel: text(c, s.x_label, `${p}.x_label`, { max: 60 }), yLabel: text(c, s.y_label, `${p}.y_label`, { max: 60 }),
      xUnit: text(c, s.x_unit, `${p}.x_unit`, { max: 16, optional: true }), yUnit: text(c, s.y_unit, `${p}.y_unit`, { max: 16, optional: true }),
      refs: referenceLines(c, s.reference_lines, `${p}.reference_lines`, ['x', 'y']),
      labelPoints: choice(c, s.label_points ?? 'highlighted', `${p}.label_points`, ['highlighted', 'all', 'none']),
    };
  },
  pitch(c, s, p) {
    const teams = list(c, s.teams, `${p}.teams`, { max: LIMITS.pitchTeams, optional: true }).map((t, i) => {
      const tp = `${p}.teams[${i}]`;
      if (!object(c, t, tp, ['id', 'name'], ['id', 'name'])) return null;
      return { id: text(c, t.id, `${tp}.id`, { max: 24 }), name: text(c, t.name, `${tp}.name`, { max: 60 }) };
    }).filter(Boolean);
    if (!teams.length) teams.push({ id: 'team', name: 'Team' });
    const teamIds = teams.map(t => t.id);
    const team = (v, path) => v === undefined ? teamIds[0] : choice(c, v, path, teamIds);
    const coord = (v, path) => number(c, v, path, { min: 0, max: 100 }) ?? 0;
    const shots = list(c, s.shots, `${p}.shots`, { max: LIMITS.shots, optional: true }).map((sh, i) => {
      const sp = `${p}.shots[${i}]`;
      if (!object(c, sh, sp, ['x', 'y', 'xg', 'outcome', 'player', 'minute', 'team'], ['x', 'y', 'outcome'])) return null;
      return { x: coord(sh.x, `${sp}.x`), y: coord(sh.y, `${sp}.y`), xg: number(c, sh.xg ?? 0.05, `${sp}.xg`, { min: 0, max: 1 }) ?? 0.05, outcome: choice(c, sh.outcome, `${sp}.outcome`, SHOT_OUTCOMES), player: text(c, sh.player, `${sp}.player`, { max: 60, optional: true }), minute: number(c, sh.minute, `${sp}.minute`, { min: 0, max: 130, integer: true, optional: true }), team: team(sh.team, `${sp}.team`) };
    }).filter(Boolean);
    const ids = new Map();
    const positions = list(c, s.positions, `${p}.positions`, { max: LIMITS.positions, optional: true }).map((pos, i) => {
      const pp = `${p}.positions[${i}]`;
      if (!object(c, pos, pp, ['id', 'x', 'y', 'label', 'name', 'touches', 'team'], ['x', 'y', 'label'])) return null;
      const node = { x: coord(pos.x, `${pp}.x`), y: coord(pos.y, `${pp}.y`), label: text(c, pos.label, `${pp}.label`, { max: 4 }), name: text(c, pos.name, `${pp}.name`, { max: 40, optional: true }), touches: number(c, pos.touches, `${pp}.touches`, { min: 0, max: 1000, optional: true }), team: team(pos.team, `${pp}.team`) };
      const id = text(c, pos.id ?? pos.label, `${pp}.id`, { max: 40 });
      if (id && ids.has(id)) c.fail(`${pp}.id`, `duplicate position id "${id}"; give each node a unique id`);
      if (id) ids.set(id, node);
      return node;
    }).filter(Boolean);
    const links = list(c, s.links, `${p}.links`, { max: LIMITS.links, optional: true }).map((l, i) => {
      const lp = `${p}.links[${i}]`;
      if (!object(c, l, lp, ['from', 'to', 'count'], ['from', 'to', 'count'])) return null;
      const from = ids.get(l.from), to = ids.get(l.to);
      if (!from) c.fail(`${lp}.from`, `unknown position id ${describe(l.from)}; links reference positions[].id (or label)`);
      if (!to) c.fail(`${lp}.to`, `unknown position id ${describe(l.to)}`);
      const count = number(c, l.count, `${lp}.count`, { min: 0, max: 10000 });
      return from && to && count !== undefined ? { from, to, count } : null;
    }).filter(Boolean);
    const zones = list(c, s.zones, `${p}.zones`, { max: LIMITS.zones, optional: true }).map((z, i) => {
      const zp = `${p}.zones[${i}]`;
      if (!object(c, z, zp, ['x', 'y', 'w', 'h', 'value', 'label'], ['x', 'y', 'w', 'h', 'value'])) return null;
      const x = coord(z.x, `${zp}.x`), y = coord(z.y, `${zp}.y`);
      const w = number(c, z.w, `${zp}.w`, { min: 0.5, max: 100 - x }) ?? 0, h = number(c, z.h, `${zp}.h`, { min: 0.5, max: 100 - y }) ?? 0;
      return { x, y, w, h, value: number(c, z.value, `${zp}.value`) ?? 0, label: text(c, z.label, `${zp}.label`, { max: 24, optional: true }) };
    }).filter(Boolean);
    let formation;
    if (s.formation !== undefined && object(c, s.formation, `${p}.formation`, ['shape', 'slots', 'team'], ['slots'])) {
      const fp = `${p}.formation`;
      const slots = list(c, s.formation.slots, `${fp}.slots`, { min: 1, max: LIMITS.formationSlots }).map((slot, i) => {
        const sp = `${fp}.slots[${i}]`;
        const raw = typeof slot === 'string' ? { position: slot } : slot;
        if (!object(c, raw, sp, ['position', 'name', 'number'], ['position'])) return null;
        const position = String(raw.position ?? '').toUpperCase().replace(/\s+/g, '');
        if (!FORMATION_SPOTS[position]) return c.fail(`${sp}.position`, `unknown position ${describe(raw.position)}; use FM labels such as ${Object.keys(FORMATION_SPOTS).join(', ')}`), null;
        return { position, name: text(c, raw.name, `${sp}.name`, { max: 40, optional: true }), number: number(c, raw.number, `${sp}.number`, { min: 1, max: 99, integer: true, optional: true }) };
      }).filter(Boolean);
      formation = { shape: text(c, s.formation.shape, `${fp}.shape`, { max: 20, optional: true }), team: team(s.formation.team, `${fp}.team`), slots };
    }
    if (!shots.length && !positions.length && !zones.length && !formation) c.fail(p, 'a pitch needs at least one of shots, positions, zones or formation');
    c.budget('marks', shots.length + positions.length + links.length + zones.length + (formation?.slots.length ?? 0), p);
    return { teams, shots, positions, links, zones, formation, showZoneValues: boolean(c, s.show_zone_values, `${p}.show_zone_values`) };
  },
  timeline(c, s, p) {
    const events = list(c, s.events, `${p}.events`, { min: 1, max: LIMITS.events }).map((e, i) => {
      const ep = `${p}.events[${i}]`;
      if (!object(c, e, ep, ['date', 'label', 'detail', 'kind', 'subject', 'status'], ['date', 'label'])) return null;
      return { date: date(c, e.date, `${ep}.date`), label: text(c, e.label, `${ep}.label`, { max: 120 }), detail: text(c, e.detail, `${ep}.detail`, { max: 240, optional: true }), kind: choice(c, e.kind ?? 'other', `${ep}.kind`, EVENT_KINDS), subject: text(c, e.subject, `${ep}.subject`, { max: 60, optional: true }), status: choice(c, e.status, `${ep}.status`, STATUSES, { optional: true }) };
    }).filter(e => e && e.date);
    c.budget('marks', events.length, p);
    return { events: events.map((e, i) => ({ ...e, order: i })).sort((a, b) => isoDay(a.date) - isoDay(b.date) || a.order - b.order) };
  },
  kpis(c, s, p) {
    const items = list(c, s.items, `${p}.items`, { min: 1, max: LIMITS.kpis }).map((k, i) => {
      const kp = `${p}.items[${i}]`;
      if (!object(c, k, kp, ['label', 'value', 'type', 'delta', 'delta_label', 'better', 'note', ...FORMAT_FIELDS], ['label', 'value'])) return null;
      const type = choice(c, k.type ?? (typeof k.value === 'string' ? 'text' : 'number'), `${kp}.type`, ['text', 'number', 'money', 'percent', 'rating']);
      const value = type === 'text' ? text(c, k.value, `${kp}.value`, { max: 24 }) : number(c, k.value, `${kp}.value`);
      return {
        label: text(c, k.label, `${kp}.label`, { max: 60 }), type, value,
        delta: number(c, k.delta, `${kp}.delta`, { optional: true }),
        deltaLabel: text(c, k.delta_label, `${kp}.delta_label`, { max: 40, optional: true }),
        better: choice(c, k.better ?? 'high', `${kp}.better`, ['high', 'low', 'none']),
        note: text(c, k.note, `${kp}.note`, { max: 120, optional: true }),
        ...format(c, k, kp),
      };
    }).filter(Boolean);
    return { items };
  },
};

// Specs returned by validateReportSpec; anything else is validated before rendering.
const VALIDATED = new WeakSet();

export function validateReportSpec(input) {
  const c = new Checker();
  try {
    if (!object(c, input, 'report', ['title', 'subtitle', 'game_date', 'view', 'summary', 'sections', 'caveats', 'sources', 'filename'], ['title', 'summary', 'sections'])) c.done();
    const spec = {
      title: text(c, input.title, 'title', { max: LIMITS.titleChars }),
      subtitle: text(c, input.subtitle, 'subtitle', { max: LIMITS.subtitleChars, optional: true }),
      gameDate: date(c, input.game_date, 'game_date', { optional: true }),
      view: choice(c, input.view, 'view', ['manager', 'full'], { optional: true }),
      summary: text(c, input.summary, 'summary', { max: LIMITS.summaryChars, multiline: true }),
      caveats: list(c, input.caveats, 'caveats', { max: LIMITS.caveats, optional: true }).map((v, i) => text(c, v, `caveats[${i}]`, { max: LIMITS.noteChars })).filter(Boolean),
      sources: list(c, input.sources, 'sources', { max: LIMITS.sources, optional: true }).map((v, i) => text(c, v, `sources[${i}]`, { max: 300 })).filter(Boolean),
      sections: [],
    };
    list(c, input.sections, 'sections', { min: 1, max: LIMITS.sections }).forEach((raw, i) => {
      const type = isPlain(raw) ? raw.type : undefined;
      const p = `sections[${i}]${typeof type === 'string' && SECTION_TYPES.includes(type) ? `:${type}` : ''}`;
      if (!isPlain(raw)) return c.fail(p, `expected a section object, got ${describe(raw)}`);
      if (!SECTION_TYPES.includes(type)) return c.fail(`${p}.type`, `must be one of ${SECTION_TYPES.join(', ')}; got ${describe(type)}`);
      if (!object(c, raw, p, ['type', 'title', 'note', ...SECTION_FIELDS[type]])) return;
      spec.sections.push({
        type, index: spec.sections.length,
        title: text(c, raw.title, `${p}.title`, { max: LIMITS.labelChars, optional: true }),
        note: text(c, raw.note, `${p}.note`, { max: LIMITS.noteChars, optional: true, multiline: true }),
        ...SECTION_VALIDATORS[type](c, raw, p),
      });
    });
    c.done();
    spec.warnings = c.warnings;
    VALIDATED.add(spec);
    return spec;
  } catch (error) {
    if (error instanceof ReportSpecError) throw error;
    throw new ReportSpecError([...c.issues, `report: ${error.message}`]);
  }
}

// ---------------------------------------------------------------- formatting

const ESC = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' };
export const esc = value => String(value ?? '').replace(/[&<>"']/g, ch => ESC[ch]);
// Escaped text with **bold** spans; no other markup is interpreted.
const inline = value => esc(value).replace(/\*\*([^*]+?)\*\*/g, '<strong>$1</strong>');
const MINUS = String.fromCodePoint(0x2212);
const NBSP = String.fromCodePoint(0xa0);
const NNBSP = String.fromCodePoint(0x202f);
const nf = (decimals, min = decimals) => new Intl.NumberFormat('en-GB', { maximumFractionDigits: decimals, minimumFractionDigits: min });
const autoDecimals = v => Number.isInteger(v) ? 0 : Math.abs(v) >= 100 ? 0 : Math.abs(v) >= 10 ? 1 : 2;
const signed = (v, text) => (v < 0 ? MINUS : '') + text;

export function formatValue(value, type, fmt = {}) {
  if (value === null || value === undefined) return '';
  const unit = fmt.unit ? `${type === 'money' ? NBSP : NNBSP}${fmt.unit}` : '';
  switch (type) {
    case 'text': return String(value);
    case 'date': return formatDate(value);
    case 'percent': return signed(value, nf(fmt.decimals ?? autoDecimals(value)).format(Math.abs(value)) + '%');
    case 'money': {
      const cur = fmt.currency ?? '£';
      const a = Math.abs(value);
      if (fmt.decimals !== undefined && a < 1000) return signed(value, cur + nf(fmt.decimals).format(a)) + unit;
      const [div, suffix] = a >= 1e9 ? [1e9, 'B'] : a >= 1e6 ? [1e6, 'M'] : a >= 1e3 ? [1e3, 'K'] : [1, ''];
      const n = a / div;
      return signed(value, cur + nf(n >= 100 ? 0 : n >= 10 ? 1 : 2, 0).format(n) + suffix) + unit;
    }
    default: return signed(value, nf(fmt.decimals ?? autoDecimals(value)).format(Math.abs(value))) + unit;
  }
}

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
const MONTHS_LONG = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December'];
export function formatDate(iso) { return `${+iso.slice(8, 10)} ${MONTHS[+iso.slice(5, 7) - 1]} ${iso.slice(0, 4)}`; }
const dayToIso = day => new Date(day * 86400000).toISOString().slice(0, 10);

function formatRange(v, decimals = 0) {
  if (!v || v.kind === 'unknown') return { text: '—', sr: 'Unknown', sort: '' };
  const f = n => nf(decimals ?? autoDecimals(n)).format(n);
  if (v.kind === 'exact') return { text: f(v.value), sr: `${f(v.value)}, exact`, sort: v.value };
  return { text: `${f(v.min)}–${f(v.max)}`, sr: `between ${f(v.min)} and ${f(v.max)}`, sort: (v.min + v.max) / 2 };
}

const clamp01 = v => Math.max(0, Math.min(1, v));
const pct = v => `${(clamp01(v) * 100).toFixed(1)}%`;
const r1 = v => Math.round(v * 10) / 10;

// Fixed-scale fog-of-war bar: tick for exact, band for a range, nothing for unknown.
function rangeBar(v, scale, cls = '') {
  const span = scale.max - scale.min;
  const at = n => (n - scale.min) / span;
  let mark = '';
  if (v.kind === 'exact') mark = `<span class="rb-tick" style="left:${pct(at(v.value))}"></span>`;
  else if (v.kind === 'range') mark = `<span class="rb-band" style="left:${pct(at(v.min))};width:${pct(at(v.max) - at(v.min))}"></span>`;
  return `<span class="rb ${cls}${v.kind === 'unknown' ? ' rb-unknown' : ''}" aria-hidden="true">${mark}</span>`;
}

// ---------------------------------------------------------------- sections

function sectionValue(col, value, row) {
  if (col.type === 'range') {
    const r = formatRange(value, col.decimals ?? 0);
    return { html: `<span class="rv${value.kind === 'unknown' ? ' muted' : ''}" aria-hidden="true">${esc(r.text)}</span><span class="sr">${esc(r.sr)}</span>${rangeBar(value, col.scale)}`, sort: r.sort };
  }
  if (value === null) return { html: '<span class="muted" aria-hidden="true">—</span><span class="sr">No value</span>', sort: '' };
  const label = esc(formatValue(value, col.type, col));
  const sort = col.type === 'date' ? isoDay(value) : value;
  if (col.scale && typeof value === 'number' && col.scale.max !== undefined) {
    const t = clamp01((value - col.scale.min) / (col.scale.max - col.scale.min));
    if (col.scale.style === 'heat') return { html: label, sort, heat: col.scale.better === 'low' ? 1 - t : t };
    return { html: `<span class="cell-bar"><span class="cb-v">${label}</span><span class="cb" aria-hidden="true"><span style="width:${pct(t)}"></span></span></span>`, sort };
  }
  return { html: label, sort };
}

function resolveScales(sec) {
  for (const col of sec.columns) {
    if (!col.scale || col.type === 'range') continue;
    const nums = sec.rows.map(r => r[col.key]).filter(v => typeof v === 'number');
    if (col.scale.min === undefined) col.scale.min = Math.min(0, ...nums);
    if (col.scale.max === undefined) col.scale.max = Math.max(col.scale.min + 1, ...nums);
  }
}

const SORT_ICON = '<svg class="sort-icon" viewBox="0 0 10 14" aria-hidden="true"><path class="up" d="M5 1 9 6H1z"/><path class="down" d="M5 13 1 8h8z"/></svg>';

function renderTable(sec) {
  resolveScales(sec);
  const hasRange = sec.columns.some(c => c.type === 'range');
  if (!sec.rows.length) return `<p class="empty">No rows matched. The table is empty rather than missing.</p>`;
  const head = sec.columns.map((col, i) => {
    const numeric = !['text'].includes(col.type);
    return `<th scope="col" class="a-${col.align}"><button type="button" data-col="${i}" data-kind="${numeric ? 'num' : 'text'}">${esc(col.label)}${SORT_ICON}</button></th>`;
  }).join('');
  const body = sec.rows.map((row, r) => `<tr${sec.highlight.has(r) ? ' class="hl"' : ''}>${sec.columns.map((col, i) => {
    const v = sectionValue(col, row[col.key], row);
    const tag = i === 0 ? 'th scope="row"' : 'td';
    const cls = [`a-${col.align}`, col.type !== 'text' ? 'num' : '', col.type === 'range' ? 'rng' : '', v.heat !== undefined ? 'heat' : ''].filter(Boolean).join(' ');
    const style = v.heat !== undefined ? ` style="--t:${(v.heat * 0.55).toFixed(3)}"` : '';
    return `<${tag} class="${cls}" data-sort="${esc(v.sort)}"${style}>${v.html}${i === 0 && sec.highlight.has(r) ? '<span class="sr"> (highlighted)</span>' : ''}</${tag.split(' ')[0]}>`;
  }).join('')}</tr>`).join('\n');
  const label = sec.title ?? 'Table';
  return `<div class="table-wrap" role="region" aria-label="${esc(label)} (scrolls sideways)" tabindex="0"><table class="data" data-sortable><thead><tr>${head}</tr></thead><tbody>\n${body}\n</tbody></table></div>${hasRange ? RANGE_KEY : ''}<p class="table-meta">${sec.rows.length} row${sec.rows.length === 1 ? '' : 's'} · select a column heading to sort</p>`;
}

const RANGE_KEY = `<p class="range-key"><span class="rk"><span class="rb rb-key" aria-hidden="true"><span class="rb-tick" style="left:60%"></span></span> exact value</span><span class="rk"><span class="rb rb-key" aria-hidden="true"><span class="rb-band" style="left:45%;width:30%"></span></span> range: the true value lies inside</span><span class="rk"><span class="muted" aria-hidden="true">—</span> unknown to the manager</span><span class="rk-scale">Bars on a fixed 1–20 scale unless the column says otherwise.</span></p>`;

function renderText(sec) {
  return `<div class="prose">${sec.paragraphs.map(p => `<p>${inline(p).replace(/\n+/g, '<br>')}</p>`).join('')}${sec.bullets.length ? `<ul>${sec.bullets.map(b => `<li>${inline(b)}</li>`).join('')}</ul>` : ''}</div>`;
}

const GROUP_LABEL = { technical: 'Technical', mental: 'Mental', physical: 'Physical', goalkeeping: 'Goalkeeping' };
function renderPlayerCards(sec) {
  const anyRange = sec.players.some(p => p.attributes.some(g => g.items.some(a => a.value.kind !== 'exact')));
  const cards = sec.players.map(p => {
    const facts = p.facts.length ? `<dl class="facts">${p.facts.map(f => `<div><dt>${esc(f.label)}</dt><dd>${esc(f.value)}</dd></div>`).join('')}</dl>` : '';
    const groups = p.attributes.map(g => `<div class="attr-group"><h4>${GROUP_LABEL[g.group]}</h4><ul class="attrs">${g.items.map(a => {
      const r = formatRange(a.value, 0);
      const key = p.key.has(a.label.toLowerCase());
      return `<li class="${key ? 'key' : ''}"><span class="an">${esc(a.label)}${key ? '<span class="sr"> (key for the role)</span>' : ''}</span>${rangeBar(a.value, { min: 1, max: 20 }, 'rb-attr')}<span class="av${a.value.kind === 'unknown' ? ' muted' : ''}" aria-hidden="true">${esc(r.text)}</span><span class="sr">${esc(r.sr)}</span></li>`;
    }).join('')}</ul></div>`).join('');
    const tags = p.tags.length ? `<ul class="tags">${p.tags.map(t => `<li>${esc(t)}</li>`).join('')}</ul>` : '';
    return `<article class="player"><header><h3>${esc(p.name)}</h3>${p.subtitle ? `<p class="sub">${esc(p.subtitle)}</p>` : ''}${tags}</header>${facts}${groups ? `<div class="attr-groups">${groups}</div>` : ''}${p.useWhen ? `<p class="use-when"><strong>Use when</strong> ${inline(p.useWhen)}</p>` : ''}</article>`;
  }).join('');
  const keyNote = sec.players.some(p => p.key.size) ? '<span class="rk"><span class="swatch-key" aria-hidden="true"></span> key attribute for the role</span>' : '';
  return `<div class="players">${cards}</div>${anyRange || keyNote ? `<p class="range-key">${keyNote}${anyRange ? RANGE_KEY.slice(RANGE_KEY.indexOf('>') + 1, RANGE_KEY.lastIndexOf('<span class="rk-scale">')) : ''}<span class="rk-scale">Attributes on the 1–20 scale.</span></p>` : ''}`;
}

function comparable(v, type) {
  if (v === null || v === undefined) return null;
  if (type === 'range') return v.kind === 'exact' ? { lo: v.value, hi: v.value } : v.kind === 'range' ? { lo: v.min, hi: v.max } : null;
  if (typeof v === 'number') return { lo: v, hi: v };
  return null;
}

function bestIndexes(metric) {
  if (metric.better === 'none') return new Set();
  const vals = metric.values.map(v => comparable(v, metric.type));
  const best = new Set();
  vals.forEach((v, i) => {
    if (!v) return;
    const others = vals.filter((o, j) => j !== i && o);
    if (!others.length) return;
    const wins = metric.better === 'high' ? others.every(o => v.lo > o.hi || (v.lo === v.hi && o.lo === o.hi && v.lo >= o.lo)) : others.every(o => v.hi < o.lo || (v.lo === v.hi && o.lo === o.hi && v.hi <= o.hi));
    if (wins) best.add(i);
  });
  // A tie across every entity marks nothing.
  return best.size === vals.filter(Boolean).length ? new Set() : best;
}

const BEST_ICON = '<svg class="best-icon" viewBox="0 0 12 12" aria-hidden="true"><circle cx="6" cy="6" r="5"/><path d="M3.4 6.2 5.2 8 8.7 4.3"/></svg>';
function renderComparison(sec) {
  const head = `<tr><th scope="col" class="a-left">Metric</th>${sec.entities.map(e => `<th scope="col" class="ent">${esc(e.name)}${e.subtitle ? `<span class="ent-sub">${esc(e.subtitle)}</span>` : ''}</th>`).join('')}</tr>`;
  let group;
  const rows = sec.metrics.map(m => {
    const best = bestIndexes(m);
    const nums = m.values.map(v => comparable(v, m.type)).filter(Boolean);
    const lo = m.scale.min ?? Math.min(0, ...nums.map(v => v.lo)), hi = m.scale.max ?? Math.max(lo + 1e-9, ...nums.map(v => v.hi));
    const groupRow = m.group && m.group !== group ? `<tr class="grp"><th scope="colgroup" colspan="${sec.entities.length + 1}">${esc(m.group)}</th></tr>` : '';
    group = m.group ?? group;
    const cells = m.values.map((v, i) => {
      const isBest = best.has(i);
      let body;
      if (m.type === 'range') {
        const r = formatRange(v, m.decimals ?? 0);
        body = `<span class="cv${v.kind === 'unknown' ? ' muted' : ''}" aria-hidden="true">${esc(r.text)}</span><span class="sr">${esc(r.sr)}</span>${rangeBar(v, { min: m.scale.min ?? 1, max: m.scale.max ?? 20 }, 'rb-cmp')}`;
      } else if (v === null) body = '<span class="muted" aria-hidden="true">—</span><span class="sr">No value</span>';
      else {
        body = `<span class="cv">${esc(formatValue(v, m.type, m))}</span>`;
        if (typeof v === 'number' && m.type !== 'date' && m.better !== 'none' && hi > lo) body += `<span class="cmp-bar" aria-hidden="true"><span style="width:${pct((v - lo) / (hi - lo))}"></span></span>`;
      }
      return `<td class="${isBest ? 'best' : ''}">${isBest ? BEST_ICON : ''}${body}${isBest ? '<span class="sr"> (better)</span>' : ''}</td>`;
    }).join('');
    const dir = m.better === 'high' ? 'higher is better' : m.better === 'low' ? 'lower is better' : '';
    return `${groupRow}<tr><th scope="row" class="a-left">${esc(m.label)}${dir ? `<span class="dir">${dir}</span>` : ''}</th>${cells}</tr>`;
  }).join('\n');
  const anyRange = sec.metrics.some(m => m.type === 'range');
  return `<div class="table-wrap compare-wrap-${sec.entities.length}" role="region" aria-label="${esc(sec.title ?? 'Comparison')} (scrolls sideways)" tabindex="0"><table class="data compare compare-${sec.entities.length}"><thead>${head}</thead><tbody>${rows}</tbody></table></div><p class="range-key"><span class="rk">${BEST_ICON} better value where the difference is certain</span>${anyRange ? '<span class="rk-scale">Overlapping ranges are not marked.</span>' : ''}</p>`;
}

function renderBarChart(sec) {
  const all = sec.series.flatMap(s => s.values).concat(sec.refs.map(r => r.value));
  const lo = Math.min(0, ...all), hi = Math.max(0, ...all);
  const span = hi - lo || 1;
  const left = lo < 0 ? 0.14 : 0, right = 0.16;
  const at = v => left + (1 - left - right) * (v - lo) / span;
  const zero = at(0);
  const fmt = v => formatValue(v, sec.currency ? 'money' : 'number', sec);
  const grouped = sec.series.length > 1;
  const rows = sec.categories.map((cat, i) => {
    const bars = sec.series.map((s, k) => {
      const v = s.values[i];
      const a = at(Math.min(0, v)), b = at(Math.max(0, v));
      const neg = v < 0;
      const cls = `bar s${k + 1}${sec.highlight[i] ? ' hl' : ''}${!grouped && sec.highlight.some(Boolean) && !sec.highlight[i] ? ' dim' : ''}${neg ? ' neg' : ''}`;
      return `<span class="${cls}" style="left:${pct(a)};width:${pct(b - a)}" title="${esc(`${cat}${grouped ? ` · ${s.name}` : ''}: ${fmt(v)}`)}"></span><span class="bv${neg ? ' bv-neg' : ''}" style="${neg ? `right:${pct(1 - a)}` : `left:${pct(b)}`}">${esc(fmt(v))}${grouped ? `<span class="sr"> ${esc(s.name)}</span>` : ''}</span>`;
    }).map((bar, k) => `<span class="bar-line">${bar}</span>`).join('');
    const note = sec.notes[i] ? `<span class="bar-note">${esc(sec.notes[i])}</span>` : '';
    return `<div class="bar-row${grouped ? ' grouped' : ''}" role="listitem"><span class="bar-label">${esc(cat)}${sec.highlight[i] ? '<span class="sr"> (highlighted)</span>' : ''}${note}</span><span class="bar-track">${bars}</span></div>`;
  }).join('');
  const refs = sec.refs.map(r => `<span class="ref${at(r.value) > 0.6 ? ' ref-end' : ''}" style="left:${pct(at(r.value))}" aria-hidden="true"><span class="ref-label">${esc(r.label ?? fmt(r.value))}</span></span>`).join('');
  const legend = grouped ? `<ul class="legend" aria-label="Series, top to bottom within each row">${sec.series.map((s, k) => `<li><span class="key key-bar s${k + 1}" aria-hidden="true"></span>${esc(s.name)}</li>`).join('')}</ul>` : '';
  const axis = sec.valueLabel ? `<p class="axis-label">${esc(sec.valueLabel)}${sec.unit ? ` (${esc(sec.unit)})` : ''}</p>` : '';
  const refText = sec.refs.length ? `<p class="sr">Reference lines: ${sec.refs.map(r => `${esc(r.label ?? '')} at ${esc(fmt(r.value))}`).join('; ')}.</p>` : '';
  const layer = refs || lo < 0 ? `<div class="ref-layer" aria-hidden="true"><span></span><span class="ref-col">${lo < 0 ? `<span class="zero" style="left:${pct(zero)}"></span>` : ''}${refs}</span></div>` : '';
  return `${legend}<div class="bars${refs ? ' has-ref' : ''}"><div class="bar-rows" role="list">${rows}</div>${layer}</div>${axis}${refText}`;
}

function renderStackedBarChart(sec) {
  const fmt = v => formatValue(v, 'number', sec);
  const totals = sec.bars.map(b => b.segments.reduce((sum, g) => sum + g.value, 0));
  const hi = Math.max(1e-9, ...totals, ...sec.bars.map(b => b.target ?? 0));
  const bare = v => formatValue(v, 'number', { decimals: sec.decimals });
  // "1,520 of 1,620 minutes · 100 not covered": the unit is said once, and the total sits under the
  // row's label so that the bar can use the whole track at any width.
  const totalText = i => {
    const b = sec.bars[i];
    if (b.target === undefined) return fmt(totals[i]);
    return `${bare(totals[i])} of ${fmt(b.target)}${b.target > totals[i] ? ` · ${bare(b.target - totals[i])} not covered` : ''}`;
  };
  // A sliver is kept so that a target at the far end stays inside the track.
  const at = v => 0.985 * v / hi;
  const banded = sec.bands.length > 0;
  const hatchedLabel = sec.hatchedLabel ?? 'Hatched';
  const targetLabel = sec.targetLabel ?? 'Target';
  const anyHatched = sec.bars.some(b => b.segments.some(g => g.hatched));
  const anyTarget = sec.bars.some(b => b.target !== undefined);
  const anyGap = sec.bars.some((b, i) => b.target !== undefined && b.target > totals[i]);
  const rows = sec.bars.map((b, i) => {
    let x = 0;
    const segs = b.segments.filter(g => g.value > 0).map(g => {
      const left = at(x);
      x += g.value;
      const width = at(x) - left;
      const said = `${g.label}: ${fmt(g.value)}${banded ? `, ${sec.bands[g.band]}` : ''}${g.hatched ? `, ${hatchedLabel.toLowerCase()}` : ''}${g.note ? ` (${g.note})` : ''}`;
      return `<span class="seg b${banded ? g.band + 1 : 1}of${banded ? sec.bands.length : 1}${g.hatched ? ' hatched' : ''}" style="left:${pct(left)};width:${pct(width)}" title="${esc(said)}">${width >= 0.07 ? `<span class="seg-name" aria-hidden="true">${esc(g.label)}</span>` : ''}<span class="sr">${esc(said)}. </span></span>`;
    }).join('');
    const gap = b.target !== undefined && b.target > totals[i]
      ? `<span class="seg seg-gap" style="left:${pct(at(totals[i]))};width:${pct(at(b.target) - at(totals[i]))}" title="${esc(`Not covered: ${fmt(b.target - totals[i])}`)}"><span class="sr">Not covered: ${esc(fmt(b.target - totals[i]))}. </span></span>` : '';
    const mark = b.target !== undefined ? `<span class="seg-target" style="left:${pct(at(b.target))}" title="${esc(`${targetLabel}: ${fmt(b.target)}`)}"></span>` : '';
    const total = `<span class="stack-total${b.target !== undefined && b.target > totals[i] ? ' short' : ''}">${esc(totalText(i))}</span>`;
    // The note (warnings, the blend) runs under the bar at the track's width, where a long one wraps.
    const note = b.note ? `<span class="stack-note">${esc(b.note)}</span>` : '';
    return `<div class="bar-row stack-row" role="listitem"><span class="bar-label">${esc(b.label)}${total}</span><span class="bar-track"><span class="bar-line stack-line">${segs}${gap}${mark}</span>${note}</span></div>`;
  }).join('');
  const keys = [
    ...sec.bands.map((name, k) => `<li><span class="key key-bar seg b${k + 1}of${sec.bands.length}" aria-hidden="true"></span>${esc(name)}</li>`),
    anyHatched ? `<li><span class="key key-bar seg b1of1 hatched" aria-hidden="true"></span>${esc(hatchedLabel)}</li>` : '',
    anyTarget ? `<li><span class="key key-target" aria-hidden="true"></span>${esc(targetLabel)}</li>` : '',
    anyGap ? '<li><span class="key key-bar seg seg-gap" aria-hidden="true"></span>Not covered</li>' : '',
  ].join('');
  const legend = keys ? `<ul class="legend" aria-label="Key">${keys}</ul>` : '';
  const axis = sec.valueLabel ? `<p class="axis-label">${esc(sec.valueLabel)}${sec.unit ? ` (${esc(sec.unit)})` : ''}</p>` : '';
  const headers = ['Bar', 'Segment', sec.valueLabel ?? 'Value', ...(banded ? ['Band'] : []), ...(anyHatched ? [hatchedLabel] : []), 'Note'];
  const table = sec.bars.flatMap((b, i) => [
    ...b.segments.map(g => [b.label, g.label, fmt(g.value), ...(banded ? [sec.bands[g.band]] : []), ...(anyHatched ? [g.hatched ? 'Yes' : ''] : []), g.note ?? '']),
    [b.label, 'Total', totalText(i), ...(banded ? [''] : []), ...(anyHatched ? [''] : []), b.note ?? ''],
  ]);
  return `${legend}<div class="bars stacked"><div class="bar-rows" role="list">${rows}</div></div>${axis}${dataView(dataTable(headers, table))}`;
}

// ---------------------------------------------------------------- SVG charts

function niceTicks(min, max, count = 5) {
  if (min === max) { min -= 1; max += 1; }
  const raw = (max - min) / count;
  const mag = 10 ** Math.floor(Math.log10(raw));
  const err = raw / mag;
  const step = (err >= 7.5 ? 10 : err >= 3.5 ? 5 : err >= 1.5 ? 2 : 1) * mag;
  const lo = Math.floor(min / step + 1e-9) * step, hi = Math.ceil(max / step - 1e-9) * step;
  const ticks = [];
  for (let v = lo; v <= hi + step / 2; v += step) ticks.push(Math.round(v / step) * step);
  return { lo, hi, ticks, step };
}

function dateTicks(lo, hi) {
  const span = hi - lo;
  if (span <= 70) {
    const step = span <= 14 ? 2 : 7;
    const ticks = [];
    for (let d = Math.ceil(lo / step) * step; d <= hi; d += step) ticks.push(d);
    return ticks.map(d => ({ v: d, label: (iso => `${+iso.slice(8)} ${MONTHS[+iso.slice(5, 7) - 1]}`)(dayToIso(d)) }));
  }
  const months = [];
  const start = new Date(lo * 86400000);
  let y = start.getUTCFullYear(), m = start.getUTCMonth() + 1;
  if (m === 12) { m = 0; y += 1; }
  for (; ; m++) {
    if (m === 12) { m = 0; y += 1; }
    const d = Date.UTC(y, m, 1) / 86400000;
    if (d > hi) break;
    months.push({ d, y, m });
  }
  const every = Math.max(1, Math.ceil(months.length / 7));
  return months.filter((_, i) => i % every === 0).map(({ d, y, m }, i) => ({ v: d, label: i === 0 || m === 0 ? `${MONTHS[m]} ${y}` : MONTHS[m] }));
}

const stepDecimals = step => step >= 1 ? 0 : Math.min(3, Math.ceil(-Math.log10(step) - 1e-9));
const textWidth = (s, size = 11) => [...String(s)].length * size * 0.56;
const truncate = (s, max) => [...s].length > max ? `${[...s].slice(0, max - 1).join('')}…` : s;

function svgOpen(w, h, label, cls) {
  return `<svg class="chart ${cls}" viewBox="0 0 ${w} ${h}" width="${w}" height="${h}" role="img" aria-label="${esc(label)}" preserveAspectRatio="xMinYMin meet">`;
}

function lineChartSvg(sec, W, label) {
  const narrow = W < 500;
  const H = narrow ? 280 : 360;
  const allY = sec.series.flatMap(s => s.points.map(p => p.y)).filter(v => v !== null).concat(sec.refs.filter(r => r.axis === 'y').map(r => r.value));
  const yt = niceTicks(sec.yMin ?? Math.min(...allY), sec.yMax ?? Math.max(...allY), narrow ? 4 : 5);
  const xs = sec.series.flatMap(s => s.points.map(p => p.x));
  let xlo = Math.min(...xs), xhi = Math.max(...xs);
  if (sec.xType === 'category') { xlo = 0; xhi = Math.max(1, sec.categories.length - 1); }
  if (xlo === xhi) { xlo -= 1; xhi += 1; }
  const fmtY = v => formatValue(v, sec.currency ? 'money' : 'number', { ...sec, unit: undefined, decimals: stepDecimals(yt.step) });
  const yTickW = Math.max(...yt.ticks.map(t => textWidth(fmtY(t)))) + 10;
  const labelMax = narrow ? 12 : 20;
  const names = sec.series.map(s => truncate(s.name, labelMax));
  const rightPad = Math.min(narrow ? 100 : 170, Math.max(...names.map(n => textWidth(n, 12) * 1.08 + 30)));
  const m = { t: sec.yLabel ? 26 : 12, r: rightPad, b: sec.xLabel ? 44 : 28, l: yTickW + 4 };
  const pw = W - m.l - m.r, ph = H - m.t - m.b;
  const X = v => m.l + (v - xlo) / (xhi - xlo) * pw;
  const Y = v => m.t + (1 - (v - yt.lo) / (yt.hi - yt.lo)) * ph;
  let out = svgOpen(W, H, label, 'line-chart');
  out += yt.ticks.map(t => `<line class="grid" x1="${m.l}" x2="${m.l + pw}" y1="${r1(Y(t))}" y2="${r1(Y(t))}"/><text class="tick" x="${m.l - 8}" y="${r1(Y(t))}" dy="0.32em" text-anchor="end">${esc(fmtY(t))}</text>`).join('');
  let xticks;
  if (sec.xType === 'date') xticks = dateTicks(xlo, xhi);
  else if (sec.xType === 'category') {
    const every = Math.max(1, Math.ceil(sec.categories.length / (narrow ? 5 : 10)));
    xticks = sec.categories.map((c, i) => ({ v: i, label: truncate(c, 10) })).filter((_, i) => i % every === 0);
  } else xticks = niceTicks(xlo, xhi, narrow ? 4 : 6).ticks.filter(t => t >= xlo && t <= xhi).map(t => ({ v: t, label: formatValue(t, 'number', {}) }));
  out += `<line class="axis" x1="${m.l}" x2="${m.l + pw}" y1="${m.t + ph}" y2="${m.t + ph}"/>`;
  out += xticks.map(t => `<text class="tick" x="${r1(X(t.v))}" y="${m.t + ph + 16}" text-anchor="middle">${esc(t.label)}</text>`).join('');
  if (sec.xLabel) out += `<text class="axis-title" x="${m.l + pw / 2}" y="${H - 8}" text-anchor="middle">${esc(sec.xLabel)}</text>`;
  if (sec.yLabel) out += `<text class="axis-title" x="${m.l - yTickW + 4}" y="14">${esc(sec.yLabel)}${sec.unit ? ` (${esc(sec.unit)})` : ''}</text>`;
  for (const r of sec.refs) {
    if (r.axis === 'y') out += `<line class="refline" x1="${m.l}" x2="${m.l + pw}" y1="${r1(Y(r.value))}" y2="${r1(Y(r.value))}"/><text class="ref-text" x="${m.l + 4}" y="${r1(Y(r.value)) - 5}">${esc(r.label ?? fmtY(r.value))}</text>`;
    else if (r.value >= xlo && r.value <= xhi) {
      const atEnd = X(r.value) > m.l + pw - textWidth(r.label ?? '') - 8;
      out += `<line class="refline" x1="${r1(X(r.value))}" x2="${r1(X(r.value))}" y1="${m.t}" y2="${m.t + ph}"/><text class="ref-text" x="${r1(X(r.value)) + (atEnd ? -4 : 4)}" y="${m.t + 10}" text-anchor="${atEnd ? 'end' : 'start'}">${esc(r.label ?? '')}</text>`;
    }
  }
  const ends = [];
  sec.series.forEach((s, k) => {
    const dim = sec.emphasis && sec.emphasis !== s.name;
    const cls = dim ? 'muted-series' : `s${(k % 6) + 1}`;
    const segs = [];
    let cur = [];
    for (const p of s.points) { if (p.y === null) { if (cur.length) segs.push(cur); cur = []; } else cur.push(p); }
    if (cur.length) segs.push(cur);
    out += `<g class="series ${cls}">`;
    out += segs.map(seg => `<path class="line" d="${seg.map((p, i) => `${i ? 'L' : 'M'}${r1(X(p.x))} ${r1(Y(p.y))}`).join('')}"/>`).join('');
    const pts = s.points.filter(p => p.y !== null);
    if (pts.length <= 14) out += pts.map(p => `<circle class="dot" cx="${r1(X(p.x))}" cy="${r1(Y(p.y))}" r="3.5"/>`).join('');
    out += pts.map(p => {
      const xl = sec.xType === 'date' ? formatDate(dayToIso(p.x)) : sec.xType === 'category' ? sec.categories[p.x] : formatValue(p.x, 'number', {});
      return `<circle class="hit" cx="${r1(X(p.x))}" cy="${r1(Y(p.y))}" r="9"><title>${esc(`${s.name} · ${xl}: ${formatValue(p.y, sec.currency ? 'money' : 'number', sec)}${p.label ? ` — ${p.label}` : ''}`)}</title></circle>`;
    }).join('');
    const last = pts[pts.length - 1];
    if (last) {
      out += `<circle class="end" cx="${r1(X(last.x))}" cy="${r1(Y(last.y))}" r="4"/>`;
      ends.push({ y: Y(last.y), x: X(last.x), name: names[k], full: s.name, cls, value: formatValue(last.y, sec.currency ? 'money' : 'number', sec) });
    }
    out += '</g>';
  });
  // Direct end labels; collisions are spread with leader lines rather than stacked blindly.
  ends.sort((a, b) => a.y - b.y);
  const gap = 13;
  for (let i = 1; i < ends.length; i++) ends[i].ly = Math.max(ends[i].y, (ends[i - 1].ly ?? ends[i - 1].y) + gap);
  if (ends[0]) ends[0].ly = ends[0].ly ?? ends[0].y;
  const overflow = (ends.at(-1)?.ly ?? 0) - (m.t + ph + 6);
  if (overflow > 0) ends.forEach(e => { e.ly -= overflow; });
  for (let i = ends.length - 2; i >= 0; i--) ends[i].ly = Math.min(ends[i].ly, ends[i + 1].ly - gap);
  const lx = m.l + pw + 10;
  out += ends.map(e => `${Math.abs(e.ly - e.y) > 3 ? `<path class="leader" d="M${r1(e.x + 5)} ${r1(e.y)}L${lx - 2} ${r1(e.ly)}"/>` : ''}<g class="${e.cls}"><line class="key-line" x1="${lx}" x2="${lx + 10}" y1="${r1(e.ly)}" y2="${r1(e.ly)}"/></g><text class="end-label" x="${lx + 14}" y="${r1(e.ly)}" dy="0.32em">${esc(e.name)}<title>${esc(`${e.full}: ${e.value}`)}</title></text>`).join('');
  return `${out}</svg>`;
}

function scatterSvg(sec, W, label) {
  const narrow = W < 500;
  const H = narrow ? 320 : 440;
  const xt = niceTicks(Math.min(...sec.points.map(p => p.x), ...sec.refs.filter(r => r.axis === 'x').map(r => r.value)), Math.max(...sec.points.map(p => p.x), ...sec.refs.filter(r => r.axis === 'x').map(r => r.value)), narrow ? 4 : 6);
  const yt = niceTicks(Math.min(...sec.points.map(p => p.y), ...sec.refs.filter(r => r.axis === 'y').map(r => r.value)), Math.max(...sec.points.map(p => p.y), ...sec.refs.filter(r => r.axis === 'y').map(r => r.value)), narrow ? 4 : 5);
  const fx = v => formatValue(v, 'number', { decimals: stepDecimals(xt.step) });
  const fy = v => formatValue(v, 'number', { decimals: stepDecimals(yt.step) });
  const yTickW = Math.max(...yt.ticks.map(t => textWidth(fy(t)))) + 10;
  const m = { t: 26, r: 16, b: 44, l: yTickW + 4 };
  const pw = W - m.l - m.r, ph = H - m.t - m.b;
  const X = v => m.l + (v - xt.lo) / (xt.hi - xt.lo) * pw;
  const Y = v => m.t + (1 - (v - yt.lo) / (yt.hi - yt.lo)) * ph;
  let out = svgOpen(W, H, label, 'scatter');
  out += yt.ticks.map(t => `<line class="grid" x1="${m.l}" x2="${m.l + pw}" y1="${r1(Y(t))}" y2="${r1(Y(t))}"/><text class="tick" x="${m.l - 8}" y="${r1(Y(t))}" dy="0.32em" text-anchor="end">${esc(fy(t))}</text>`).join('');
  out += xt.ticks.map(t => `<line class="grid" y1="${m.t}" y2="${m.t + ph}" x1="${r1(X(t))}" x2="${r1(X(t))}"/><text class="tick" x="${r1(X(t))}" y="${m.t + ph + 16}" text-anchor="middle">${esc(fx(t))}</text>`).join('');
  out += `<text class="axis-title" x="${m.l + pw / 2}" y="${H - 8}" text-anchor="middle">${esc(sec.xLabel)}${sec.xUnit ? ` (${esc(sec.xUnit)})` : ''}</text>`;
  out += `<text class="axis-title" x="${m.l - yTickW + 4}" y="14">${esc(sec.yLabel)}${sec.yUnit ? ` (${esc(sec.yUnit)})` : ''}</text>`;
  for (const r of sec.refs) {
    if (r.axis === 'y') out += `<line class="refline" x1="${m.l}" x2="${m.l + pw}" y1="${r1(Y(r.value))}" y2="${r1(Y(r.value))}"/><text class="ref-text" x="${m.l + pw - 4}" y="${r1(Y(r.value)) - 5}" text-anchor="end">${esc(r.label ?? fy(r.value))}</text>`;
    else {
      const atEnd = X(r.value) > m.l + pw - textWidth(r.label ?? fx(r.value)) - 8;
      out += `<line class="refline" x1="${r1(X(r.value))}" x2="${r1(X(r.value))}" y1="${m.t}" y2="${m.t + ph}"/><text class="ref-text" x="${r1(X(r.value)) + (atEnd ? -4 : 4)}" y="${m.t + 10}" text-anchor="${atEnd ? 'end' : 'start'}">${esc(r.label ?? fx(r.value))}</text>`;
    }
  }
  const cls = p => p.group ? `s${sec.groups.indexOf(p.group) + 1}` : 's1';
  const ordered = [...sec.points].sort((a, b) => Number(a.highlight) - Number(b.highlight));
  const anyHighlight = sec.points.some(p => p.highlight);
  out += ordered.map(p => `<g class="pt ${cls(p)}${anyHighlight && !p.highlight && !sec.groups.length ? ' dim' : ''}${p.highlight ? ' hl' : ''}"><circle class="dot" cx="${r1(X(p.x))}" cy="${r1(Y(p.y))}" r="${p.highlight ? 5.5 : 4.5}"/><circle class="hit" cx="${r1(X(p.x))}" cy="${r1(Y(p.y))}" r="12"><title>${esc(`${p.label ?? 'Point'}${p.group ? ` (${p.group})` : ''}: ${sec.xLabel} ${formatValue(p.x, 'number', {})}, ${sec.yLabel} ${formatValue(p.y, 'number', {})}`)}</title></circle></g>`).join('');
  // Greedy label placement: try four offsets, skip a label that would collide.
  const boxes = [];
  const want = sec.points.filter(p => p.label && (sec.labelPoints === 'all' || (sec.labelPoints === 'highlighted' && p.highlight))).slice(0, LIMITS.scatterLabels);
  const labels = [];
  for (const p of want) {
    const name = truncate(p.label, narrow ? 14 : 22);
    const w = textWidth(name), h = 12, cx = X(p.x), cy = Y(p.y);
    const options = [[cx + 8, cy - h / 2, 'start'], [cx - 8 - w, cy - h / 2, 'end'], [cx + 6, cy - 6 - h, 'start'], [cx - w / 2, cy - 8 - h, 'middle'], [cx - w / 2, cy + 8, 'middle']];
    // Labels may run into the margins but never over the axis titles or another label.
    const spot = options.find(([x, y]) => x >= 2 && x + w <= W - 2 && y >= 2 && y + h <= m.t + ph + 2 && !boxes.some(b => x < b.x + b.w && x + w > b.x && y < b.y + b.h && y + h > b.y));
    if (!spot) continue;
    boxes.push({ x: spot[0], y: spot[1], w, h });
    const tx = spot[2] === 'start' ? spot[0] : spot[2] === 'end' ? spot[0] + w : spot[0] + w / 2;
    labels.push(`<text class="pt-label" x="${r1(tx)}" y="${r1(spot[1] + h / 2)}" dy="0.32em" text-anchor="${spot[2]}">${esc(name)}</text>`);
  }
  return `${out}${labels.join('')}</svg>`;
}

// ---------------------------------------------------------------- pitch

// FM position labels -> [length %, width % from the team's left touchline].
const FORMATION_SPOTS = {
  GK: [5, 50],
  DL: [21, 13], DCL: [18, 34], DC: [18, 50], DCR: [18, 66], DR: [21, 87],
  WBL: [35, 10], DML: [34, 32], DM: [34, 50], DMR: [34, 68], WBR: [35, 90],
  ML: [53, 11], MCL: [50, 33], MC: [50, 50], MCR: [50, 67], MR: [53, 89],
  AML: [70, 14], AMCL: [67, 36], AMC: [67, 50], AMCR: [67, 64], AMR: [70, 86],
  STCL: [84, 38], ST: [85, 50], STC: [85, 50], STCR: [84, 62],
};
const SPREAD = { 1: [0], 2: [-10, 10], 3: [-16, 0, 16] };

export function formationLayout(slots) {
  const counts = {}, seen = {};
  for (const s of slots) counts[s.position] = (counts[s.position] ?? 0) + 1;
  return slots.map(s => {
    const [x, y] = FORMATION_SPOTS[s.position];
    const n = counts[s.position];
    const i = seen[s.position] = (seen[s.position] ?? -1) + 1;
    const offsets = SPREAD[n] ?? Array.from({ length: n }, (_, k) => (k - (n - 1) / 2) * 12);
    return { ...s, x, y: Math.max(6, Math.min(94, y + offsets[i])) };
  });
}

const PITCH_L = 105, PITCH_W = 68;
function pitchSvg(sec, vertical, label) {
  const s = vertical ? 5 : 6;
  const pad = 14;
  const arrowBand = 30;
  const W = vertical ? PITCH_W * s + 2 * pad + arrowBand : PITCH_L * s + 2 * pad;
  const H = vertical ? PITCH_L * s + 2 * pad : PITCH_W * s + 2 * pad + arrowBand;
  const ox = vertical ? pad + arrowBand : pad;
  // Data coordinates: x 0..100 along the length toward the opponent goal, y 0..100 from the left touchline.
  const mirror = team => sec.teams.length > 1 && team === sec.teams[1].id;
  const P = (x, y, team) => {
    const L = (mirror(team) ? 100 - x : x) / 100 * PITCH_L, Wd = (mirror(team) ? 100 - y : y) / 100 * PITCH_W;
    return vertical ? [ox + Wd * s, pad + (PITCH_L - L) * s] : [ox + L * s, pad + Wd * s];
  };
  const matrix = vertical ? `matrix(0 ${-s} ${s} 0 ${ox} ${pad + PITCH_L * s})` : `matrix(${s} 0 0 ${s} ${ox} ${pad})`;
  const teamCls = team => `t${Math.max(0, sec.teams.findIndex(t => t.id === team)) + 1}`;
  let out = svgOpen(W, H, label, `pitch ${vertical ? 'pitch-v' : 'pitch-h'}`);
  out += `<g transform="${matrix}">`;
  out += `<rect class="turf" x="0" y="0" width="${PITCH_L}" height="${PITCH_W}"/>`;
  if (sec.zones.length) {
    const vals = sec.zones.map(z => z.value);
    const zlo = Math.min(...vals), zhi = Math.max(...vals);
    out += sec.zones.map(z => {
      const t = zhi > zlo ? (z.value - zlo) / (zhi - zlo) : 1;
      const zx = z.x / 100 * PITCH_L, zy = z.y / 100 * PITCH_W, zw = z.w / 100 * PITCH_L, zh = z.h / 100 * PITCH_W;
      return `<rect class="zone" x="${r1(zx)}" y="${r1(zy)}" width="${r1(zw)}" height="${r1(zh)}" style="--t:${(0.06 + t * 0.66).toFixed(3)}"><title>${esc(`${z.label ? `${z.label}: ` : ''}${formatValue(z.value, 'number', {})}`)}</title></rect>`;
    }).join('');
  }
  const L = PITCH_L, Wd = PITCH_W, c = Wd / 2;
  const box = (x0, dir) => {
    const pa = `M${x0} ${c - 20.16}h${dir * 16.5}v40.32h${-dir * 16.5}`;
    const six = `M${x0} ${c - 9.16}h${dir * 5.5}v18.32h${-dir * 5.5}`;
    const spot = x0 + dir * 11;
    // Arc of radius 9.15 around the spot, outside the penalty area (16.5 - 11 = 5.5 from spot).
    const dy = Math.sqrt(9.15 ** 2 - 5.5 ** 2);
    const arc = `M${x0 + dir * 16.5} ${r1(c - dy)}A9.15 9.15 0 0 ${dir > 0 ? 1 : 0} ${x0 + dir * 16.5} ${r1(c + dy)}`;
    const goal = `M${x0} ${c - 3.66}h${-dir * 1.6}v7.32h${dir * 1.6}`;
    return `<path d="${pa}"/><path d="${six}"/><path d="${arc}"/><path d="${goal}"/><circle class="spot" cx="${spot}" cy="${c}" r="0.35"/>`;
  };
  out += `<g class="markings"><rect x="0" y="0" width="${L}" height="${Wd}"/><path d="M${L / 2} 0V${Wd}"/><circle cx="${L / 2}" cy="${c}" r="9.15"/><circle class="spot" cx="${L / 2}" cy="${c}" r="0.35"/>${box(0, 1)}${box(L, -1)}<path d="M0 1A1 1 0 0 0 1 0M${L - 1} 0A1 1 0 0 0 ${L} 1M${L} ${Wd - 1}A1 1 0 0 0 ${L - 1} ${Wd}M1 ${Wd}A1 1 0 0 0 0 ${Wd - 1}"/></g>`;
  out += '</g>';
  if (sec.showZoneValues) {
    out += sec.zones.map(z => {
      const [zx, zy] = P(z.x + z.w / 2, z.y + z.h / 2, sec.teams[0].id);
      return `<text class="zone-value" x="${r1(zx)}" y="${r1(zy)}" dy="0.32em" text-anchor="middle">${esc(z.label ?? formatValue(z.value, 'number', {}))}</text>`;
    }).join('');
  }
  // Pass links under nodes, width by volume.
  if (sec.links.length) {
    const maxc = Math.max(...sec.links.map(l => l.count), 1);
    out += `<g class="links">${[...sec.links].sort((a, b) => a.count - b.count).map(l => {
      const [x1, y1] = P(l.from.x, l.from.y, l.from.team), [x2, y2] = P(l.to.x, l.to.y, l.to.team);
      const w = 1 + 7 * Math.sqrt(l.count / maxc);
      return `<line class="link ${teamCls(l.from.team)}" x1="${r1(x1)}" y1="${r1(y1)}" x2="${r1(x2)}" y2="${r1(y2)}" stroke-width="${r1(w)}"><title>${esc(`${l.from.name ?? l.from.label} ↔ ${l.to.name ?? l.to.label}: ${l.count} passes`)}</title></line>`;
    }).join('')}</g>`;
  }
  const nodes = [...sec.positions];
  if (sec.formation) nodes.push(...formationLayout(sec.formation.slots).map(slot => ({ x: slot.x, y: slot.y, label: slot.number !== undefined ? String(slot.number) : slot.position, name: slot.name ?? (slot.number !== undefined ? slot.position : undefined), team: sec.formation.team, position: slot.position })));
  if (nodes.length) {
    const maxT = Math.max(...nodes.map(n => n.touches ?? 0));
    out += `<g class="nodes">${nodes.map(n => {
      const [x, y] = P(n.x, n.y, n.team);
      const r = n.touches !== undefined && maxT > 0 ? 8 + 8 * Math.sqrt(n.touches / maxT) : 11;
      const fs = n.label.length > 2 ? 8.5 : 10;
      const title = `${n.name ? `${n.name} · ` : ''}${n.position ?? n.label}${n.touches !== undefined ? ` · ${n.touches} touches` : ''}`;
      return `<g class="node ${teamCls(n.team)}"><circle cx="${r1(x)}" cy="${r1(y)}" r="${r1(r)}"><title>${esc(title)}</title></circle><text class="node-label" x="${r1(x)}" y="${r1(y)}" dy="0.34em" text-anchor="middle" style="font-size:${fs}px">${esc(n.label)}</text>${n.name ? `<text class="node-name" x="${r1(x)}" y="${r1(y + r + 11)}" text-anchor="middle">${esc(truncate(n.name, 14))}</text>` : ''}</g>`;
    }).join('')}</g>`;
  }
  if (sec.shots.length) {
    out += `<g class="shots">${[...sec.shots].sort((a, b) => b.xg - a.xg).map(sh => {
      const [x, y] = P(sh.x, sh.y, sh.team);
      const r = Math.max(3, Math.sqrt(sh.xg) * 17);
      const title = `${sh.player ?? 'Shot'}${sh.minute !== undefined ? ` ${sh.minute}′` : ''} · xG ${sh.xg.toFixed(2)} · ${OUTCOME_LABEL[sh.outcome]}`;
      return shotMark(sh.outcome, x, y, r, teamCls(sh.team), title);
    }).join('')}</g>`;
  }
  // Attack direction, drawn outside the pitch.
  if (vertical) {
    const ax = pad + 8, top = pad, len = PITCH_L * s;
    const arrow = (y0, y1, name, cls) => {
      const dir = Math.sign(y1 - y0), lx = ax + 6;
      // Rotated label beside its own arrow, reading upward from the arrow's lower end.
      return `<path class="attack-arrow ${cls}" d="M${lx} ${r1(y0)}V${r1(y1)}M${lx - 5} ${r1(y1 - dir * 7)}L${lx} ${r1(y1)}L${lx + 5} ${r1(y1 - dir * 7)}"/><text class="attack-text" transform="translate(${ax - 2} ${r1(Math.max(y0, y1))}) rotate(-90)" text-anchor="start">${esc(name)} attack</text>`;
    };
    out += '<g class="attack">';
    out += sec.teams[1] ? arrow(top + len * 0.46, top + len * 0.2, sec.teams[0].name, '') + arrow(top + len * 0.54, top + len * 0.8, sec.teams[1].name, '') : arrow(top + len * 0.62, top + len * 0.38, sec.teams[0].name, '');
    out += '</g>';
  } else {
    const ay = pad + PITCH_W * s + 18;
    const mid = ox + PITCH_L * s / 2;
    out += `<g class="attack"><path class="attack-arrow" d="M${mid + 14} ${ay}H${mid + 74}M${mid + 67} ${ay - 5}L${mid + 74} ${ay}L${mid + 67} ${ay + 5}"/><text class="attack-text" x="${mid + 80}" y="${ay}" dy="0.32em">${esc(sec.teams[0].name)} attack</text>`;
    if (sec.teams[1]) out += `<path class="attack-arrow t2a" d="M${mid - 14} ${ay}H${mid - 74}M${mid - 67} ${ay - 5}L${mid - 74} ${ay}L${mid - 67} ${ay + 5}"/><text class="attack-text" x="${mid - 80}" y="${ay}" dy="0.32em" text-anchor="end">${esc(sec.teams[1].name)} attack</text>`;
    out += '</g>';
  }
  return `${out}</svg>`;
}

const OUTCOME_LABEL = { goal: 'Goal', saved: 'Saved', blocked: 'Blocked', off_target: 'Off target', post: 'Hit the woodwork' };
function shotMark(outcome, x, y, r, cls, title) {
  const t = title ? `<title>${esc(title)}</title>` : '';
  const X = r1(x), Y = r1(y), R = r1(r);
  switch (outcome) {
    case 'goal': return `<circle class="shot goal ${cls}" cx="${X}" cy="${Y}" r="${R}">${t}</circle>`;
    case 'saved': return `<circle class="shot saved ${cls}" cx="${X}" cy="${Y}" r="${R}">${t}</circle>`;
    case 'blocked': { const d = r1(r * 0.886); return `<rect class="shot blocked ${cls}" x="${r1(x - d)}" y="${r1(y - d)}" width="${r1(2 * d)}" height="${r1(2 * d)}">${t}</rect>`; }
    case 'post': { const d = r1(r * 1.15); return `<path class="shot post ${cls}" d="M${X} ${r1(y - d)}L${r1(x + d)} ${Y}L${X} ${r1(y + d)}L${r1(x - d)} ${Y}Z">${t}</path>`; }
    default: return `<circle class="shot off ${cls}" cx="${X}" cy="${Y}" r="${R}">${t}</circle>`;
  }
}

function pitchLegend(sec) {
  const parts = [];
  if (sec.teams.length > 1) parts.push(...sec.teams.map((t, i) => `<li><span class="key key-dot t${i + 1}" aria-hidden="true"></span><span>${esc(t.name)} (attacking <span class="dir-h">${i === 0 ? 'right' : 'left'}</span><span class="dir-v">${i === 0 ? 'up' : 'down'}</span>)</span></li>`));
  if (sec.shots.length) {
    const used = SHOT_OUTCOMES.filter(o => sec.shots.some(s => s.outcome === o));
    parts.push(...used.map(o => `<li><svg class="key-svg" viewBox="0 0 20 20" aria-hidden="true">${shotMark(o, 10, 10, 6, 't1')}</svg>${OUTCOME_LABEL[o]}</li>`));
    parts.push(`<li class="xg-key"><svg class="key-svg wide" viewBox="0 0 64 24" aria-hidden="true">${[0.05, 0.2, 0.5].map((xg, i) => `<circle class="shot off t1" cx="${[6, 22, 46][i]}" cy="12" r="${r1(Math.max(3, Math.sqrt(xg) * 17) * 0.75)}"/>`).join('')}</svg>Size = xG (0.05, 0.2, 0.5)</li>`);
  }
  if (sec.links.length) parts.push(`<li><svg class="key-svg wide" viewBox="0 0 64 20" aria-hidden="true"><line class="link t1" x1="2" y1="6" x2="62" y2="6" stroke-width="1.5"/><line class="link t1" x1="2" y1="15" x2="62" y2="15" stroke-width="6"/></svg>Line width = passes between the pair</li>`);
  if (sec.positions.some(p => p.touches !== undefined)) parts.push('<li>Circle size = touches</li>');
  if (sec.zones.length) {
    const vals = sec.zones.map(z => z.value);
    parts.push(`<li><span class="ramp" aria-hidden="true"></span>Shading: ${esc(formatValue(Math.min(...vals), 'number', {}))} (light) to ${esc(formatValue(Math.max(...vals), 'number', {}))} (dark)</li>`);
  }
  return parts.length ? `<ul class="legend pitch-legend">${parts.join('')}</ul>` : '';
}

function pitchTable(sec) {
  const blocks = [];
  if (sec.shots.length) blocks.push(dataTable(['Team', 'Player', 'Minute', 'xG', 'Outcome', 'Position (x, y)'], sec.shots.map(s => [teamName(sec, s.team), s.player ?? '', s.minute ?? '', s.xg.toFixed(2), OUTCOME_LABEL[s.outcome], `${s.x}, ${s.y}`]), 'Shots'));
  const nodes = [...sec.positions.map(p => [teamName(sec, p.team), p.label, p.name ?? '', p.touches ?? '', `${p.x}, ${p.y}`])];
  if (sec.formation) nodes.push(...sec.formation.slots.map(s => [teamName(sec, sec.formation.team), s.position, s.name ?? '', s.number ?? '', '']));
  if (nodes.length) blocks.push(dataTable(['Team', 'Label', 'Name', sec.formation ? 'Number / touches' : 'Touches', 'Position (x, y)'], nodes, 'Players'));
  if (sec.links.length) blocks.push(dataTable(['From', 'To', 'Passes'], [...sec.links].sort((a, b) => b.count - a.count).map(l => [l.from.name ?? l.from.label, l.to.name ?? l.to.label, l.count]), 'Pass links'));
  if (sec.zones.length) blocks.push(dataTable(['Zone', 'Value', 'Area (x, y, w, h)'], sec.zones.map(z => [z.label ?? '', formatValue(z.value, 'number', {}), `${z.x}, ${z.y}, ${z.w}, ${z.h}`]), 'Zones'));
  return blocks.join('');
}
const teamName = (sec, id) => sec.teams.find(t => t.id === id)?.name ?? '';

function dataTable(headers, rows, caption) {
  return `<table class="data mini">${caption ? `<caption>${esc(caption)}</caption>` : ''}<thead><tr>${headers.map(h => `<th scope="col">${esc(h)}</th>`).join('')}</tr></thead><tbody>${rows.map(r => `<tr>${r.map(v => `<td>${esc(v)}</td>`).join('')}</tr>`).join('')}</tbody></table>`;
}

function dataView(inner) {
  return `<details class="data-view"><summary>Show the data as a table</summary><div class="table-wrap">${inner}</div></details>`;
}

function renderLineChart(sec) {
  const label = `Line chart${sec.title ? `: ${sec.title}` : ''}. ${sec.series.map(s => s.name).join(', ')}.`;
  const xl = p => sec.xType === 'date' ? formatDate(dayToIso(p.x)) : sec.xType === 'category' ? sec.categories[p.x] : formatValue(p.x, 'number', {});
  const xs = [...new Set(sec.series.flatMap(s => s.points.map(p => p.x)))].sort((a, b) => a - b);
  const rows = xs.map(x => [xl({ x }), ...sec.series.map(s => { const p = s.points.find(q => q.x === x); return p && p.y !== null ? formatValue(p.y, sec.currency ? 'money' : 'number', sec) : ''; })]);
  return `<figure class="chart-fig"><div class="viz wide">${lineChartSvg(sec, 960, label)}</div><div class="viz narrow">${lineChartSvg(sec, 360, label)}</div></figure>${dataView(dataTable([sec.xLabel ?? 'x', ...sec.series.map(s => s.name)], rows))}`;
}

function renderScatter(sec) {
  const label = `Scatter plot of ${sec.yLabel} against ${sec.xLabel}, ${sec.points.length} points.`;
  const legend = sec.groups.length > 1 ? `<ul class="legend">${sec.groups.map((g, i) => `<li><span class="key key-dot s${i + 1}" aria-hidden="true"></span>${esc(g)}</li>`).join('')}</ul>` : '';
  const rows = sec.points.map(p => [p.label ?? '', ...(sec.groups.length ? [p.group ?? ''] : []), formatValue(p.x, 'number', {}), formatValue(p.y, 'number', {})]);
  return `${legend}<figure class="chart-fig"><div class="viz wide">${scatterSvg(sec, 960, label)}</div><div class="viz narrow">${scatterSvg(sec, 360, label)}</div></figure>${dataView(dataTable(['Label', ...(sec.groups.length ? ['Group'] : []), sec.xLabel, sec.yLabel], rows))}`;
}

function renderPitch(sec) {
  const what = [sec.shots.length && `${sec.shots.length} shots`, sec.positions.length && `${sec.positions.length} average positions`, sec.links.length && `${sec.links.length} pass links`, sec.zones.length && `${sec.zones.length} zones`, sec.formation && `formation ${sec.formation.shape ?? ''}`].filter(Boolean).join(', ');
  const label = `Pitch diagram${sec.title ? `: ${sec.title}` : ''}, ${what}. ${sec.teams[0].name} attack ${sec.teams[1] ? `right, ${sec.teams[1].name} attack left` : 'toward the opponent goal'}.`;
  const shape = sec.formation?.shape ? `<p class="formation-shape"><span class="label">Shape</span> ${esc(sec.formation.shape)}</p>` : '';
  return `${shape}<figure class="chart-fig pitch-fig"><div class="viz pitch-wide">${pitchSvg(sec, false, label)}</div><div class="viz pitch-narrow">${pitchSvg(sec, true, label)}</div></figure>${pitchLegend(sec)}${dataView(pitchTable(sec))}`;
}

const KIND_LABEL = { contract: 'Contract', fixture: 'Fixture', injury: 'Injury', loan: 'Loan', transfer: 'Transfer', training: 'Training', other: 'Event' };
const KIND_ICON = {
  contract: '<rect x="3" y="2" width="10" height="12" rx="1.5"/><path d="M5.5 6h5M5.5 9h5"/>',
  fixture: '<circle cx="8" cy="8" r="5.5"/><path d="M8 4.5 10.5 6.5 9.5 9.5h-3L5.5 6.5z"/>',
  injury: '<path d="M6 2.5h4v3.5h3.5v4H10v3.5H6V10H2.5V6H6z"/>',
  loan: '<path d="M2.5 6h9M9 3.5 11.5 6 9 8.5M13.5 10h-9M7 7.5 4.5 10 7 12.5"/>',
  transfer: '<path d="M2.5 8h10M9.5 4.5 13 8l-3.5 3.5"/>',
  training: '<circle cx="8" cy="8" r="5.5"/><path d="M8 5v3l2 1.5"/>',
  other: '<circle cx="8" cy="8" r="2.5"/>',
};
const STATUS_TEXT = { good: 'On track', warning: 'Watch', critical: 'Act now' };
const STATUS_ICON = {
  good: '<circle cx="6" cy="6" r="5"/><path class="ink" d="M3.5 6.2 5.2 7.9 8.6 4.4"/>',
  warning: '<path d="M6 1 11.2 10.5H.8z"/><path class="ink" d="M6 4.5v2.8M6 8.6v.2"/>',
  critical: '<rect x="1" y="1" width="10" height="10" rx="2"/><path class="ink" d="M6 3.4v3.6M6 8.5v.2"/>',
};

function relativeDays(diff) {
  if (diff === 0) return 'on the game date';
  const n = Math.abs(diff);
  const span = n >= 60 ? `${Math.round(n / 30.44)} months` : n >= 14 ? `${Math.round(n / 7)} weeks` : `${n} day${n === 1 ? '' : 's'}`;
  return diff > 0 ? `in ${span}` : `${span} ago`;
}

function renderTimeline(sec, spec) {
  const today = spec.gameDate ? isoDay(spec.gameDate) : undefined;
  let month = '', out = '';
  const items = [];
  const flush = () => { if (items.length) { out += `<ol class="tl-list">${items.join('')}</ol>`; items.length = 0; } };
  // The game date is a marker sorted before same-day events.
  const entries = today === undefined ? sec.events : [...sec.events, { date: spec.gameDate, today: true }].sort((a, b) => isoDay(a.date) - isoDay(b.date) || Number(Boolean(b.today)) - Number(Boolean(a.today)) || a.order - b.order);
  for (const e of entries) {
    const d = isoDay(e.date);
    const key = e.date.slice(0, 7);
    if (key !== month) {
      flush();
      month = key;
      out += `<h3 class="tl-month">${MONTHS_LONG[+key.slice(5) - 1]} ${key.slice(0, 4)}</h3>`;
    }
    if (e.today) {
      items.push(`<li class="tl-today"><span class="tl-date"><time datetime="${esc(e.date)}">${+e.date.slice(8)} ${MONTHS[+e.date.slice(5, 7) - 1]}</time></span><span class="tl-today-label">Game date: events above have passed</span></li>`);
      continue;
    }
    const rel = today !== undefined ? `<span class="tl-rel">${relativeDays(d - today)}</span>` : '';
    const status = e.status ? `<span class="status st-${e.status}"><svg viewBox="0 0 12 12" aria-hidden="true">${STATUS_ICON[e.status]}</svg>${STATUS_TEXT[e.status]}</span>` : '';
    items.push(`<li class="tl-item${today !== undefined && d < today ? ' past' : ''}"><span class="tl-date"><time datetime="${esc(e.date)}">${+e.date.slice(8)} ${MONTHS[+e.date.slice(5, 7) - 1]}</time>${rel}</span><span class="tl-kind"><svg viewBox="0 0 16 16" aria-hidden="true">${KIND_ICON[e.kind]}</svg>${KIND_LABEL[e.kind]}</span><span class="tl-body">${e.subject ? `<strong class="tl-subject">${esc(e.subject)}</strong> ` : ''}${esc(e.label)}${e.detail ? `<span class="tl-detail">${esc(e.detail)}</span>` : ''}</span>${status}</li>`);
  }
  flush();
  return `<div class="timeline">${out}</div>`;
}

const DELTA_ICON = { up: '<path d="M6 2 10.5 8h-9z"/>', down: '<path d="M6 10 1.5 4h9z"/>', flat: '<rect x="1.5" y="5" width="9" height="2" rx="1"/>' };
function renderKpis(sec) {
  return `<dl class="kpis kpis-n${sec.items.length}">${sec.items.map(k => {
    const value = k.type === 'text' ? esc(k.value) : esc(formatValue(k.value, k.type === 'rating' ? 'number' : k.type, { ...k, unit: undefined }));
    const unit = k.unit && k.type !== 'text' ? `<span class="kpi-unit">${esc(k.unit)}</span>` : '';
    let delta = '';
    if (k.delta !== undefined) {
      const dir = k.delta > 0 ? 'up' : k.delta < 0 ? 'down' : 'flat';
      const good = k.better === 'none' || dir === 'flat' ? 'neutral' : (dir === 'up') === (k.better === 'high') ? 'good' : 'bad';
      const amount = (k.delta > 0 ? '+' : '') + formatValue(k.delta, k.type === 'rating' || k.type === 'text' ? 'number' : k.type, { ...k, unit: undefined });
      const word = good === 'good' ? 'better' : good === 'bad' ? 'worse' : '';
      delta = `<span class="delta d-${good}"><svg viewBox="0 0 12 12" aria-hidden="true">${DELTA_ICON[dir]}</svg>${esc(amount)}${k.deltaLabel ? ` <span class="delta-label">${esc(k.deltaLabel)}</span>` : ''}${word ? `<span class="sr"> (${word})</span>` : ''}</span>`;
    }
    return `<div class="kpi"><dt>${esc(k.label)}</dt><dd><span class="kpi-value">${value}${unit}</span>${delta}${k.note ? `<span class="kpi-note">${esc(k.note)}</span>` : ''}</dd></div>`;
  }).join('')}</dl>`;
}

const RENDERERS = { text: renderText, table: renderTable, player_cards: renderPlayerCards, comparison: renderComparison, bar_chart: renderBarChart, stacked_bar_chart: renderStackedBarChart, line_chart: renderLineChart, scatter: renderScatter, pitch: renderPitch, timeline: renderTimeline, kpis: renderKpis };
const TYPE_LABEL = { text: 'Notes', table: 'Table', player_cards: 'Players', comparison: 'Comparison', bar_chart: 'Bar chart', stacked_bar_chart: 'Stacked bar chart', line_chart: 'Line chart', scatter: 'Scatter plot', pitch: 'Pitch', timeline: 'Timeline', kpis: 'Key numbers' };

function renderSection(sec, spec) {
  const id = `s${sec.index + 1}`;
  const heading = sec.title ? `<h2 id="${id}-h">${esc(sec.title)}</h2>` : '';
  const labelled = sec.title ? `aria-labelledby="${id}-h"` : `aria-label="${TYPE_LABEL[sec.type]}"`;
  return `<section class="sec sec-${sec.type.replace('_', '-')}" id="${id}" ${labelled}>${heading}${sec.note ? `<p class="note">${inline(sec.note)}</p>` : ''}${RENDERERS[sec.type](sec, spec)}</section>`;
}

// ---------------------------------------------------------------- document

const VIEW = {
  manager: { label: 'Manager knowledge', explain: 'Values as the manager’s scouting shows them. Partly known attributes appear as ranges and unknown ones as a dash.' },
  full: { label: 'Full data', explain: 'Stored game values, including ones the manager cannot see in the game.' },
};
const VIEW_ICON = {
  manager: '<svg viewBox="0 0 16 16" aria-hidden="true"><path d="M1.5 8S4 3.5 8 3.5 14.5 8 14.5 8 12 12.5 8 12.5 1.5 8 1.5 8z"/><circle cx="8" cy="8" r="2.2"/></svg>',
  full: '<svg viewBox="0 0 16 16" aria-hidden="true"><ellipse cx="8" cy="4" rx="5.5" ry="2"/><path d="M2.5 4v8c0 1.1 2.5 2 5.5 2s5.5-.9 5.5-2V4M2.5 8c0 1.1 2.5 2 5.5 2s5.5-.9 5.5-2"/></svg>',
};

export function formatGenerated(date, timeZone) {
  const parts = new Intl.DateTimeFormat('en-GB', { day: 'numeric', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit', hour12: false, timeZone, timeZoneName: 'short' }).formatToParts(date);
  const get = t => parts.find(p => p.type === t)?.value ?? '';
  return `${get('day')} ${get('month')} ${get('year')}, ${get('hour')}:${get('minute')} ${get('timeZoneName')}`.trim();
}

const SCRIPT = `(()=>{for(const t of document.querySelectorAll('table[data-sortable]')){const b=t.tBodies[0];const orig=[...b.rows];for(const btn of t.querySelectorAll('thead button[data-col]')){btn.addEventListener('click',()=>{const th=btn.closest('th');const i=+btn.dataset.col;const num=btn.dataset.kind==='num';const cur=th.getAttribute('aria-sort');let dir=cur===null?(num?'descending':'ascending'):cur==='descending'?'ascending':cur==='ascending'&&num?'none':'descending';if(!num&&cur==='descending')dir='none';for(const h of t.querySelectorAll('thead th'))h.removeAttribute('aria-sort');let rows;if(dir==='none'){rows=orig;}else{th.setAttribute('aria-sort',dir);const s=dir==='ascending'?1:-1;rows=[...b.rows].sort((x,y)=>{const a=x.cells[i].dataset.sort,c=y.cells[i].dataset.sort;if(a===''||c==='')return a===c?0:a===''?1:-1;return num?(a-c)*s:a.localeCompare(c,'en-GB',{sensitivity:'base'})*s;});}for(const r of rows)b.appendChild(r);});}}})();`;
const SCRIPT_HASH = createHash('sha256').update(SCRIPT).digest('base64');

export function renderReport(input, { generatedAt = new Date(), timeZone } = {}) {
  const spec = VALIDATED.has(input) ? input : validateReportSpec(input);
  const view = spec.view ? VIEW[spec.view] : null;
  const generated = formatGenerated(generatedAt, timeZone);
  const titled = spec.sections.filter(s => s.title);
  const contents = titled.length >= 4 ? `<nav class="contents" aria-label="Contents"><h2>Contents</h2><ol>${titled.map(s => `<li><a href="#s${s.index + 1}">${esc(s.title)}</a></li>`).join('')}</ol></nav>` : '';
  const meta = [
    spec.gameDate ? `<div><dt>Game date</dt><dd><time datetime="${spec.gameDate}">${formatDate(spec.gameDate)}</time></dd></div>` : '',
    `<div><dt>Data view</dt><dd class="view ${spec.view ? `view-${spec.view}` : 'view-none'}">${view ? `${VIEW_ICON[spec.view]}${view.label}` : 'Not stated'}</dd></div>`,
    `<div><dt>Generated</dt><dd><time datetime="${generatedAt.toISOString()}">${esc(generated)}</time></dd></div>`,
  ].join('');
  const footer = [
    spec.caveats.length ? `<section class="foot-block" aria-labelledby="caveats-h"><h2 id="caveats-h">Caveats</h2><ul>${spec.caveats.map(c => `<li>${inline(c)}</li>`).join('')}</ul></section>` : '',
    spec.sources.length ? `<section class="foot-block" aria-labelledby="sources-h"><h2 id="sources-h">Sources</h2><ol>${spec.sources.map(s => `<li>${esc(s)}</li>`).join('')}</ol></section>` : '',
  ].join('');
  const html = `<!doctype html>
<html lang="en-GB">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; img-src data:; script-src 'sha256-${SCRIPT_HASH}'; base-uri 'none'; form-action 'none'">
<meta name="color-scheme" content="light dark">
<meta name="generator" content="pi-fm fm_report">
<title>${esc(spec.title)}</title>
<style>${CSS}</style>
</head>
<body>
<a class="skip" href="#main">Skip to the report</a>
<header class="masthead">
<div class="wrap">
<h1>${esc(spec.title)}</h1>
${spec.subtitle ? `<p class="subtitle">${esc(spec.subtitle)}</p>` : ''}
<dl class="meta">${meta}</dl>
${view ? `<p class="view-explain">${esc(view.explain)}</p>` : ''}
</div>
</header>
<main id="main" class="wrap">
<section class="answer" aria-labelledby="answer-h"><h2 id="answer-h">Answer</h2><p>${inline(spec.summary).replace(/\n+/g, '<br>')}</p></section>
${contents}
${spec.sections.map(s => renderSection(s, spec)).join('\n')}
</main>
<footer class="colophon">
<div class="wrap">
${footer}
<p class="made">Made by pi-fm from ${view ? view.label.toLowerCase() : 'an unstated data view'}${spec.gameDate ? ` at game date ${formatDate(spec.gameDate)}` : ''}. Generated ${esc(generated)}. Figures come from the save as read; football judgement is the adviser’s.</p>
</div>
</footer>
<script>${SCRIPT}</script>
</body>
</html>
`;
  const bytes = Buffer.byteLength(html, 'utf8');
  if (bytes > LIMITS.htmlBytes) throw new ReportSpecError([`report: the rendered page is ${(bytes / 1048576).toFixed(1)} MiB; the cap is ${LIMITS.htmlBytes / 1048576} MiB. Cut rows or chart points.`]);
  return html;
}

// ---------------------------------------------------------------- styles

const CSS = String.raw`
:root{
  color-scheme:light;
  --page:#f4f4f1;--surface:#fcfcfb;--surface-2:#ecebe6;--surface-3:#e3e2dc;
  --ink:#121211;--ink-2:#4b4a46;--ink-3:#65635e;
  --line:#e1e0d9;--line-2:#c9c8bf;--ring:rgba(11,11,11,.10);
  --s1:#2a78d6;--s2:#eb6834;--s3:#1baf7a;--s4:#6250d6;--s5:#e87ba4;--s6:#008300;
  --muted-mark:#a9a7a0;--accent-ink:#1c5cab;--focus:#1c5cab;
  --good:#006300;--bad:#b42323;--warn:#fab219;--crit:#d03b3b;--ok:#0ca30c;
  --hl:#fff6d6;--heat:#2a78d6;
  --turf:#e6ede3;--turf-line:#a2b39c;--node-ink:#ffffff;
  --sel:#cde2fb;
}
@media (prefers-color-scheme:dark){:root:not([data-theme=light]){
  color-scheme:dark;
  --page:#0f0f0e;--surface:#1a1a19;--surface-2:#262624;--surface-3:#30302d;
  --ink:#f0efec;--ink-2:#c3c2b7;--ink-3:#a19f97;
  --line:#2c2c2a;--line-2:#45453f;--ring:rgba(255,255,255,.10);
  --s1:#3987e5;--s2:#d95926;--s3:#199e70;--s4:#9085e9;--s5:#d55181;--s6:#008300;
  --muted-mark:#5c5b56;--accent-ink:#86b6ef;--focus:#86b6ef;
  --good:#3fbf3f;--bad:#f07a7a;
  --hl:#2d2a1a;--heat:#3987e5;
  --turf:#18221b;--turf-line:#3b4f40;
  --sel:#184f95;
}}
:root[data-theme=dark]{color-scheme:dark;--page:#0f0f0e;--surface:#1a1a19;--surface-2:#262624;--surface-3:#30302d;--ink:#f0efec;--ink-2:#c3c2b7;--ink-3:#a19f97;--line:#2c2c2a;--line-2:#45453f;--ring:rgba(255,255,255,.10);--s1:#3987e5;--s2:#d95926;--s3:#199e70;--s4:#9085e9;--s5:#d55181;--muted-mark:#5c5b56;--accent-ink:#86b6ef;--focus:#86b6ef;--good:#3fbf3f;--bad:#f07a7a;--hl:#2d2a1a;--heat:#3987e5;--turf:#18221b;--turf-line:#3b4f40;--sel:#184f95}
*,*::before,*::after{box-sizing:border-box}
html{-webkit-text-size-adjust:100%;text-size-adjust:100%}
body{margin:0;background:var(--page);color:var(--ink);font:15px/1.5 system-ui,-apple-system,"Segoe UI",Roboto,"Helvetica Neue",Arial,sans-serif;-webkit-font-smoothing:antialiased;font-kerning:normal}
::selection{background:var(--sel);color:var(--ink)}
a{color:var(--accent-ink);text-underline-offset:.18em;text-decoration-thickness:1px}
:focus-visible{outline:2px solid var(--focus);outline-offset:2px;border-radius:3px}
.wrap{max-width:1180px;margin:0 auto;padding:0 24px}
.skip{position:absolute;left:-9999px;top:8px;background:var(--surface);padding:8px 12px;border-radius:6px;z-index:2}
.skip:focus{left:8px}
.sr{position:absolute;width:1px;height:1px;overflow:hidden;clip-path:inset(50%);white-space:nowrap}
.muted{color:var(--ink-3)}
h1,h2,h3,h4{text-wrap:balance;margin:0}

.masthead{background:var(--surface);border-bottom:1px solid var(--line);padding:36px 0 24px}
.masthead h1{font-size:1.875rem;line-height:1.15;font-weight:700;letter-spacing:-.018em;max-width:28em}
.subtitle{margin:.5rem 0 0;color:var(--ink-2);font-size:1.0625rem;max-width:60ch}
.meta{display:flex;flex-wrap:wrap;gap:6px 28px;margin:20px 0 0}
.meta div{display:flex;gap:8px;align-items:baseline}
.meta dt{color:var(--ink-3);font-size:.8125rem}
.meta dd{margin:0;font-weight:600;font-size:.875rem;font-variant-numeric:tabular-nums}
.view{display:inline-flex;align-items:center;gap:6px}
.view svg{width:15px;height:15px;fill:none;stroke:currentColor;stroke-width:1.4;align-self:center}
.view-manager{color:var(--accent-ink)}
.view-none{color:var(--ink-3);font-weight:500}
.view-explain{margin:8px 0 0;color:var(--ink-3);font-size:.8125rem;max-width:72ch}

main.wrap{padding-top:28px;padding-bottom:40px}
.answer{background:var(--surface);border:1px solid var(--line);border-radius:10px;padding:20px 24px;margin:0 0 32px}
.answer h2{font-size:.8125rem;font-weight:600;color:var(--ink-2);margin-bottom:6px}
.answer p{margin:0;font-size:1.1875rem;line-height:1.45;max-width:68ch;font-weight:450}
.answer strong{font-weight:650}

.contents{margin:0 0 36px}
.contents h2{font-size:.8125rem;font-weight:600;color:var(--ink-2);margin-bottom:6px}
.contents ol{margin:0;padding:0;list-style:none;display:flex;flex-wrap:wrap;gap:4px 6px;counter-reset:c}
.contents li{counter-increment:c}
.contents a{display:inline-block;padding:4px 10px;border:1px solid var(--line);border-radius:999px;background:var(--surface);text-decoration:none;font-size:.875rem;color:var(--ink)}
.contents a:hover{border-color:var(--line-2);background:var(--surface-2)}

.sec{margin:0 0 48px}
.sec>h2{font-size:1.25rem;line-height:1.25;font-weight:650;letter-spacing:-.01em;margin-bottom:6px}
.note{margin:0 0 14px;color:var(--ink-2);max-width:72ch;font-size:.9375rem}
.sec>h2+:not(.note){margin-top:12px}
.prose{max-width:70ch}
.prose p{margin:0 0 .8em}
.prose ul{margin:0;padding-left:1.2em}
.prose li{margin:.3em 0}
.prose li::marker{color:var(--ink-3)}
.empty{color:var(--ink-3);font-style:italic}

.table-wrap{overflow-x:auto;border:1px solid var(--line);border-radius:10px;background:var(--surface);-webkit-overflow-scrolling:touch;overscroll-behavior-x:contain}
.table-wrap:focus-visible{outline-offset:3px}
table.data{border-collapse:separate;border-spacing:0;width:100%;font-size:.875rem;font-variant-numeric:tabular-nums lining-nums}
.data th,.data td{padding:8px 12px;border-bottom:1px solid var(--line);white-space:nowrap;vertical-align:middle}
.data tbody tr:last-child>*{border-bottom:0}
.data thead th{position:sticky;top:0;background:var(--surface);font-weight:600;font-size:.8125rem;color:var(--ink-2);border-bottom:1px solid var(--line-2);z-index:1}
.data thead th:first-child{left:0;z-index:2}
.data tbody th{font-weight:600;text-align:left;position:sticky;left:0;background:var(--surface);z-index:0}
.data tbody tr:hover>*{background:var(--surface-2)}
.data tr.hl>*{background:var(--hl)}
.data tr.hl>th{box-shadow:inset 3px 0 0 var(--s1)}
.a-left{text-align:left}.a-right{text-align:right}.a-center{text-align:center}
.data thead th button{all:unset;cursor:pointer;display:inline-flex;align-items:center;gap:5px;border-radius:4px;padding:2px 0}
.data thead th.a-right button{flex-direction:row-reverse}
.data thead th button:focus-visible{outline:2px solid var(--focus);outline-offset:2px}
.data thead th button:hover{color:var(--ink)}
.sort-icon{width:8px;height:12px;flex:none}
.sort-icon path{fill:var(--line-2)}
th[aria-sort=ascending] .sort-icon .up,th[aria-sort=descending] .sort-icon .down{fill:var(--ink)}
.table-meta{margin:6px 2px 0;font-size:.75rem;color:var(--ink-3)}
.data tbody tr>td.heat{background:color-mix(in oklab,var(--heat) calc(var(--t)*100%),var(--surface))}
.data tbody tr:hover>td.heat{background:color-mix(in oklab,var(--heat) calc(var(--t)*100%),var(--surface-2))}
.cell-bar{display:inline-flex;align-items:center;gap:8px;justify-content:flex-end}
.cb{display:inline-block;width:52px;height:6px;border-radius:3px;background:var(--surface-3);overflow:hidden}
.cb span{display:block;height:100%;background:var(--s1);border-radius:0 3px 3px 0}
td.rng{text-align:right}
.rv{display:inline-block;min-width:3.2em;text-align:right;margin-right:8px}
.rb{position:relative;display:inline-block;vertical-align:middle;width:56px;height:10px;border-radius:2px;background:linear-gradient(var(--surface-3),var(--surface-3)) center/100% 4px no-repeat}
.rb-band{position:absolute;top:1px;bottom:1px;min-width:3px;border-radius:2px;background:color-mix(in oklab,var(--s1) 42%,transparent);box-shadow:inset 0 0 0 1.5px var(--s1)}
.rb-tick{position:absolute;top:-1px;bottom:-1px;width:3px;margin-left:-1.5px;border-radius:1.5px;background:var(--s1)}
.rb-unknown{opacity:.7}
.range-key{display:flex;flex-wrap:wrap;gap:6px 20px;margin:10px 2px 0;font-size:.8125rem;color:var(--ink-2);align-items:center}
.rk{display:inline-flex;align-items:center;gap:8px}
.rb-key{width:40px}
.rk-scale{color:var(--ink-3)}
.swatch-key{display:inline-block;width:18px;height:6px;border-radius:3px;background:var(--s1)}

.players{display:grid;grid-template-columns:repeat(auto-fill,minmax(min(100%,330px),1fr));gap:16px}
.player{background:var(--surface);border:1px solid var(--line);border-radius:10px;padding:18px 18px 16px;display:flex;flex-direction:column;gap:14px;break-inside:avoid}
.player header h3{font-size:1.0625rem;font-weight:650}
.player .sub{margin:2px 0 0;color:var(--ink-2);font-size:.875rem}
.tags{list-style:none;margin:8px 0 0;padding:0;display:flex;flex-wrap:wrap;gap:6px}
.tags li{font-size:.75rem;padding:2px 8px;border-radius:999px;background:var(--surface-2);color:var(--ink-2)}
.facts{display:grid;grid-template-columns:repeat(auto-fill,minmax(120px,1fr));gap:8px 16px;margin:0;padding:12px 0;border-block:1px solid var(--line)}
.facts dt{font-size:.75rem;color:var(--ink-3)}
.facts dd{margin:0;font-weight:600;font-size:.9375rem;font-variant-numeric:tabular-nums}
.attr-groups{display:grid;gap:14px}
.attr-group h4{font-size:.75rem;font-weight:600;color:var(--ink-2);margin-bottom:4px}
.attrs{list-style:none;margin:0;padding:0;display:grid;gap:1px}
.attrs li{display:grid;grid-template-columns:minmax(0,1fr) 110px 3.6em;align-items:center;gap:10px;font-size:.8125rem;min-height:22px}
.attrs .an{color:var(--ink-2);overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.attrs .av{white-space:nowrap;text-align:right;font-variant-numeric:tabular-nums;font-weight:500}
.attrs li.key .an{color:var(--ink);font-weight:600}
.rb-attr{width:100%}
.attrs li:not(.key) .rb-band{background:color-mix(in oklab,var(--muted-mark) 45%,transparent);box-shadow:inset 0 0 0 1.5px var(--muted-mark)}
.attrs li:not(.key) .rb-tick{background:var(--muted-mark)}
.use-when{margin:auto 0 0;padding-top:12px;border-top:1px solid var(--line);font-size:.875rem;color:var(--ink-2)}
.use-when strong{color:var(--ink);font-weight:600;margin-right:4px}

.compare-wrap-2{max-width:760px}.compare-wrap-3{max-width:960px}
.compare th.ent{text-align:right;vertical-align:bottom;white-space:normal;min-width:9em}
.ent-sub{display:block;font-weight:400;color:var(--ink-3);font-size:.75rem}
.compare td{text-align:right;position:relative}
.compare tbody th{white-space:normal;min-width:11em}
.dir{display:block;font-weight:400;font-size:.75rem;color:var(--ink-3)}
.compare .cv{font-variant-numeric:tabular-nums}
.compare td.best .cv{font-weight:700}
.cmp-bar{display:block;margin:5px 0 0 auto;width:min(100%,120px);height:4px;border-radius:2px;background:var(--surface-3)}
.cmp-bar span{display:block;height:100%;border-radius:2px;background:var(--muted-mark);margin-left:0}
.compare td.best .cmp-bar span{background:var(--s1)}
.rb-cmp{display:block;margin:5px 0 0 auto;width:min(100%,120px)}
.best-icon{width:13px;height:13px;vertical-align:-2px;margin-right:6px}
.best-icon circle{fill:var(--s1)}
.best-icon path{fill:none;stroke:#fff;stroke-width:1.6;stroke-linecap:round;stroke-linejoin:round}
.compare tr.grp th{background:var(--surface-2);font-size:.75rem;font-weight:600;color:var(--ink-2);padding-block:6px;position:static}

.bars{position:relative;background:var(--surface);border:1px solid var(--line);border-radius:10px;padding:14px 16px 10px}
.bar-rows{display:grid;gap:6px}
.bar-row{display:grid;grid-template-columns:minmax(7rem,12rem) 1fr;gap:12px;align-items:center;min-height:24px}
.bar-label{font-size:.875rem;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.bar-note{display:block;font-size:.75rem;color:var(--ink-3)}
.bar-track{position:relative;display:grid;gap:3px;align-content:center}
.bar-line{position:relative;display:block;height:16px}
.bar-row.grouped .bar-line{height:9px}
.bar{position:absolute;top:0;bottom:0;border-radius:0 4px 4px 0;background:var(--s1)}
.bar.neg{border-radius:4px 0 0 4px}
.bar.s2{background:var(--s2)}.bar.s3{background:var(--s3)}
.bar.dim{background:color-mix(in oklab,var(--s1) 38%,var(--surface))}
.bv{position:absolute;top:50%;transform:translateY(-50%);z-index:2;margin-left:4px;padding:1px 3px;border-radius:3px;background:var(--surface);font-size:.8125rem;font-variant-numeric:tabular-nums;color:var(--ink-2);white-space:nowrap;line-height:1}
.bv-neg{margin:0 4px 0 0}
.stack-total{display:block;font-size:.8125rem;font-variant-numeric:tabular-nums;color:var(--ink-2)}
.stack-total.short{color:var(--bad);font-weight:600}
.stack-note{display:block;margin:2px 0 4px;font-size:.75rem;line-height:1.35;color:var(--ink-3);max-width:75ch}
.stack-row{align-items:start;min-height:30px}
.stack-row .bar-label{white-space:normal;overflow:visible;line-height:1.25;padding-top:2px}
.stack-line{height:22px}
.seg{position:absolute;top:0;bottom:0;box-sizing:border-box;overflow:hidden;--fill:var(--s1);--on:#fff;background-color:var(--fill);color:var(--on);border-right:1.5px solid var(--surface)}
.seg.b2of2,.seg.b2of3,.seg.b2of4,.seg.b3of5{--fill:color-mix(in oklab,var(--s1) 58%,var(--surface));--on:var(--ink)}
.seg.b2of5{--fill:color-mix(in oklab,var(--s1) 78%,var(--surface))}
.seg.b3of3,.seg.b3of4,.seg.b4of5{--fill:color-mix(in oklab,var(--s1) 30%,var(--surface));--on:var(--ink)}
.seg.b4of4,.seg.b5of5{--fill:color-mix(in oklab,var(--s1) 14%,var(--surface));--on:var(--ink)}
.seg.hatched{background-image:repeating-linear-gradient(135deg,transparent 0 5px,color-mix(in oklab,var(--on) 55%,transparent) 5px 6.5px)}
.seg-name{display:block;padding:0 5px;font-size:.6875rem;line-height:22px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.seg.hatched .seg-name{width:max-content;max-width:calc(100% - 4px);margin:3px 2px;padding:0 4px;line-height:16px;border-radius:3px;background:var(--fill)}
.seg-gap{background:none;border:1.5px dashed var(--crit)}
.seg-target{position:absolute;top:-4px;bottom:-4px;width:0;border-left:2px solid var(--ink);z-index:1}
.key-bar.seg{position:static;border-right:0;width:16px;height:10px;background:var(--fill)}
.key-bar.seg.hatched{background-image:repeating-linear-gradient(135deg,transparent 0 3px,color-mix(in oklab,var(--on) 60%,transparent) 3px 4.5px)}
.key-bar.seg-gap{background:none;border:1.5px dashed var(--crit)}
.key-target{width:0;height:14px;border-left:2px solid var(--ink)}
.bar-row.grouped .bv{font-size:.6875rem}
.ref-layer{position:absolute;z-index:1;left:16px;right:16px;top:12px;bottom:8px;display:grid;grid-template-columns:minmax(7rem,12rem) 1fr;column-gap:12px;pointer-events:none}
.bars.has-ref .ref-layer{top:30px}
.ref-col{position:relative}
.ref,.zero{position:absolute;top:0;bottom:0;width:0;border-left:1px dashed var(--ink-3)}
.zero{border-left:1px solid var(--line-2)}
.ref-label{position:absolute;top:-19px;left:4px;font-size:.6875rem;color:var(--ink-2);background:var(--surface);padding:0 3px;white-space:nowrap;line-height:1.2}
.bars.has-ref{padding-top:32px}
.ref-end .ref-label{left:auto;right:4px}
.dir-v{display:none}
.axis-label{margin:6px 2px 0;font-size:.75rem;color:var(--ink-3)}
.legend{list-style:none;margin:0 0 10px;padding:0;display:flex;flex-wrap:wrap;gap:6px 18px;font-size:.8125rem;color:var(--ink-2)}
.legend li{display:inline-flex;align-items:center;gap:7px}
.key{display:inline-block;flex:none}
.key-bar{width:14px;height:8px;border-radius:2px;background:var(--s1)}
.key-bar.s2{background:var(--s2)}.key-bar.s3{background:var(--s3)}
.key-dot{width:10px;height:10px;border-radius:50%;background:var(--s1)}
.key-dot.s2,.key-dot.t2{background:var(--s2)}.key-dot.s3{background:var(--s3)}
.key-svg{width:20px;height:20px;overflow:visible}
.key-svg.wide{width:64px;height:24px}
.ramp{display:inline-block;width:56px;height:10px;border-radius:2px;background:linear-gradient(90deg,color-mix(in oklab,var(--s1) 8%,var(--turf)),color-mix(in oklab,var(--s1) 72%,var(--turf)))}

.chart-fig{margin:0;background:var(--surface);border:1px solid var(--line);border-radius:10px;padding:12px}
.viz svg{display:block;width:100%;height:auto;max-width:100%}
.viz.narrow,.viz.pitch-narrow{display:none}
.viz.pitch-wide svg{max-width:820px;margin:0 auto}
.chart{font-family:inherit;font-variant-numeric:tabular-nums}
.chart .grid{stroke:var(--line);stroke-width:1}
.chart .axis{stroke:var(--line-2);stroke-width:1}
.chart .tick{fill:var(--ink-3);font-size:11px}
.chart .axis-title{fill:var(--ink-2);font-size:11.5px;font-weight:600}
.chart .refline{stroke:var(--ink-3);stroke-width:1;stroke-dasharray:4 3}
.chart .ref-text{fill:var(--ink-2);font-size:11px;paint-order:stroke;stroke:var(--surface);stroke-width:3px;stroke-linejoin:round}
.chart .line{fill:none;stroke:var(--c);stroke-width:2;stroke-linejoin:round;stroke-linecap:round}
.chart .dot{fill:var(--c);stroke:var(--surface);stroke-width:2}
.chart .end{fill:var(--c);stroke:var(--surface);stroke-width:2}
.chart .hit{fill:transparent;stroke:none}
.chart .hit:hover{fill:color-mix(in oklab,var(--c,var(--s1)) 18%,transparent)}
.chart .key-line{stroke:var(--c);stroke-width:2.5;stroke-linecap:round}
.chart .end-label{fill:var(--ink);font-size:12px;font-weight:550}
.chart .leader{stroke:var(--line-2);stroke-width:1;fill:none}
.s1{--c:var(--s1)}.s2{--c:var(--s2)}.s3{--c:var(--s3)}.s4{--c:var(--s4)}.s5{--c:var(--s5)}.s6{--c:var(--s6)}
.muted-series{--c:var(--muted-mark)}
.chart .pt.dim{--c:var(--muted-mark)}
.chart .pt.hl .dot{stroke-width:2.5}
.chart .pt-label{fill:var(--ink);font-size:11px;font-weight:550;paint-order:stroke;stroke:var(--surface);stroke-width:3px;stroke-linejoin:round}
.data-view{margin-top:10px}
.data-view summary{cursor:pointer;font-size:.8125rem;color:var(--accent-ink);width:max-content;border-radius:4px;padding:2px 0}
.data-view[open] summary{margin-bottom:8px}
.data.mini{font-size:.8125rem}
.data.mini caption{text-align:left;font-weight:600;padding:8px 12px 4px;font-size:.8125rem;color:var(--ink-2)}
.data.mini td,.data.mini th{padding:5px 12px;text-align:left}

.pitch-fig{padding:10px}
.pitch .turf{fill:var(--turf)}
.pitch .markings *{fill:none;stroke:var(--turf-line);stroke-width:1.3;vector-effect:non-scaling-stroke}
.pitch .markings .spot{fill:var(--turf-line)}
.pitch .zone{fill:var(--s1);fill-opacity:var(--t);stroke:var(--turf);stroke-width:.4}
.pitch .zone-value{fill:var(--ink);font-size:11px;font-weight:600;paint-order:stroke;stroke:var(--turf);stroke-width:3px}
.pitch .t1,.pitch-legend .t1{--c:var(--s1)}.pitch .t2,.pitch-legend .t2{--c:var(--s2)}
.link{stroke:var(--c);stroke-opacity:.5;stroke-linecap:round}
.node circle{fill:var(--c);stroke:var(--turf);stroke-width:2}
.node-label{fill:var(--node-ink);font-weight:700;letter-spacing:-.02em}
.node-name{fill:var(--ink);font-size:10.5px;font-weight:550;paint-order:stroke;stroke:var(--turf);stroke-width:3px;stroke-linejoin:round}
.shot{stroke:var(--c);stroke-width:1.6}
.shot.goal{fill:var(--c);stroke:var(--surface);stroke-width:1.5}
.pitch .shot.goal{stroke:var(--turf)}
.shot.saved{fill:color-mix(in oklab,var(--c) 30%,transparent);stroke-width:2}
.shot.blocked{fill:none;stroke-width:1.6}
.shot.post{fill:none;stroke-width:1.6}
.shot.off{fill:none;stroke-width:1.3;stroke-opacity:.85}
.attack-arrow{fill:none;stroke:var(--ink-3);stroke-width:1.5;stroke-linecap:round;stroke-linejoin:round}
.attack-text{fill:var(--ink-2);font-size:11.5px;font-weight:550}
.formation-shape{margin:0 0 8px;font-size:.875rem;font-weight:600}
.formation-shape .label{color:var(--ink-3);font-weight:400;margin-right:4px}
.pitch-legend{margin-top:10px}

.timeline{background:var(--surface);border:1px solid var(--line);border-radius:10px;padding:6px 18px 14px}
.tl-month{font-size:.8125rem;font-weight:650;color:var(--ink-2);margin:14px 0 4px;padding-bottom:4px;border-bottom:1px solid var(--line)}
.tl-list{list-style:none;margin:0;padding:0}
.tl-item,.tl-today{display:grid;grid-template-columns:6.5rem 7rem minmax(0,1fr) auto;gap:4px 14px;align-items:baseline;padding:7px 0;border-bottom:1px solid var(--line)}
.tl-list li:last-child{border-bottom:0}
.tl-date{font-variant-numeric:tabular-nums;font-weight:600;font-size:.875rem}
.tl-rel{display:block;font-weight:400;color:var(--ink-3);font-size:.75rem}
.tl-kind{display:inline-flex;align-items:center;gap:6px;color:var(--ink-2);font-size:.8125rem}
.tl-kind svg{width:15px;height:15px;flex:none;fill:none;stroke:var(--ink-3);stroke-width:1.3;stroke-linejoin:round;stroke-linecap:round;align-self:center}
.tl-body{font-size:.9375rem}
.tl-detail{display:block;color:var(--ink-2);font-size:.8125rem}
.tl-item.past{color:var(--ink-3)}
.tl-item.past .tl-body,.tl-item.past .tl-date{color:var(--ink-2)}
.tl-today{border-bottom:2px solid var(--s1);padding:6px 0}
.tl-today .tl-date{color:var(--accent-ink)}
.tl-today-label{grid-column:2 / -1;font-size:.8125rem;font-weight:650;color:var(--accent-ink)}
.status{display:inline-flex;align-items:center;gap:5px;font-size:.75rem;font-weight:600;white-space:nowrap;color:var(--ink)}
.status svg{width:12px;height:12px;align-self:center}
.status .ink{fill:none;stroke-width:1.6;stroke-linecap:round;stroke-linejoin:round}
.st-good svg :not(.ink){fill:var(--ok)}.st-good .ink{stroke:#fff}
.st-warning svg :not(.ink){fill:var(--warn)}.st-warning .ink{stroke:#0b0b0b}
.st-critical svg :not(.ink){fill:var(--crit)}.st-critical .ink{stroke:#fff}

.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,160px),1fr));margin:0;background:var(--surface);border:1px solid var(--line);border-radius:10px;overflow:hidden}
.kpi{padding:14px 18px 16px;border-right:1px solid var(--line);border-bottom:1px solid var(--line);margin:0 -1px -1px 0}
.kpi dt{font-size:.8125rem;color:var(--ink-2)}
.kpi dd{margin:4px 0 0}
.kpi-value{display:block;font-size:1.75rem;font-weight:650;line-height:1.15;letter-spacing:-.015em}
.kpi-unit{font-size:.875rem;font-weight:500;color:var(--ink-2);margin-left:4px;letter-spacing:0}
.delta{display:inline-flex;align-items:center;gap:4px;margin-top:4px;font-size:.8125rem;font-weight:600;font-variant-numeric:tabular-nums}
.delta svg{width:10px;height:10px;fill:currentColor}
.d-good{color:var(--good)}.d-bad{color:var(--bad)}.d-neutral{color:var(--ink-2)}
.delta-label{font-weight:400;color:var(--ink-3)}
.kpi-note{display:block;margin-top:4px;font-size:.75rem;color:var(--ink-3)}

.colophon{border-top:1px solid var(--line);background:var(--surface);padding:28px 0 36px;font-size:.875rem;color:var(--ink-2)}
.foot-block{margin-bottom:20px;max-width:80ch}
.foot-block h2{font-size:.875rem;font-weight:650;color:var(--ink);margin-bottom:6px}
.foot-block ul,.foot-block ol{margin:0;padding-left:1.25em}
.foot-block li{margin:.25em 0}
.made{margin:0;color:var(--ink-3);font-size:.8125rem;max-width:80ch}

@media (max-width:640px){
  body{font-size:15px}
  .wrap{padding:0 16px}
  .masthead{padding:24px 0 18px}
  .masthead h1{font-size:1.5rem}
  .meta{gap:4px 18px}
  .answer{padding:16px;border-radius:8px}
  .answer p{font-size:1.0625rem}
  .sec{margin-bottom:36px}
  .viz.wide,.viz.pitch-wide{display:none}
  .viz.narrow,.viz.pitch-narrow{display:block}
  .dir-h{display:none}.dir-v{display:inline}
  .viz.pitch-narrow svg{max-width:360px;margin:0 auto}
  .chart-fig{padding:8px}
  .bar-row{grid-template-columns:minmax(5.5rem,38%) 1fr;gap:8px}
  .ref-layer{grid-template-columns:minmax(5.5rem,38%) 1fr;column-gap:8px}
  .tl-item,.tl-today{grid-template-columns:5.2rem minmax(0,1fr);gap:2px 12px}
  .tl-kind{grid-column:2}
  .tl-body{grid-column:2}
  .status{grid-column:2}
  .tl-today-label{grid-column:2}
  .data th,.data td{padding:7px 10px}
  .players{gap:12px}
  .attrs li{grid-template-columns:minmax(0,1fr) 84px 3.6em;gap:8px}
  .kpi-value{font-size:1.5rem}
  .compare tbody th{min-width:7.5em}
  .compare th.ent{min-width:6em}
  .compare-2 th,.compare-2 td{padding-inline:8px}
  .ent-sub{display:none}
}
@media (prefers-reduced-motion:no-preference){.contents a,.data tbody tr>*{transition:background-color .15s ease-out}}
@media (forced-colors:active){.seg{border:1px solid CanvasText}.rb-band,.rb-tick,.bar,.cb span,.cmp-bar span{forced-color-adjust:none;background:CanvasText}.best-icon circle{fill:CanvasText}}
@page{size:A4;margin:14mm 12mm 16mm}
@media print{
  :root,:root:not([data-theme=light]){color-scheme:light;--page:#fff;--surface:#fff;--surface-2:#f1f0ec;--surface-3:#e3e2dc;--ink:#000;--ink-2:#3d3c39;--ink-3:#57554f;--line:#d9d8d1;--line-2:#b9b8af;--s1:#2a78d6;--s2:#eb6834;--s3:#1baf7a;--muted-mark:#a9a7a0;--accent-ink:#1c5cab;--good:#006300;--bad:#b42323;--hl:#fff6d6;--heat:#2a78d6;--turf:#eef3ec;--turf-line:#9fb09a}
  body{font-size:10pt;background:#fff;-webkit-print-color-adjust:exact;print-color-adjust:exact}
  .wrap{max-width:none;padding:0}
  .skip,.contents,.data-view,.table-meta{display:none}
  .masthead{padding:0 0 10pt;border-bottom:1px solid #000;background:#fff}
  .masthead h1{font-size:18pt}
  main.wrap{padding:12pt 0 0}
  .answer{padding:10pt 12pt;border-color:#999;break-inside:avoid}
  .answer p{font-size:12pt}
  .sec{margin-bottom:18pt}
  .sec>h2{font-size:13pt;break-after:avoid}
  .note{break-after:avoid}
  .table-wrap{overflow:visible;border-color:#bbb}
  .data thead{display:table-header-group}
  .data tr,.player,.kpi,.chart-fig,.bars,.tl-item,.foot-block{break-inside:avoid}
  .data thead th{position:static}.data tbody th{position:static}
  table.data{font-size:7.5pt}
  .data th,.data td{padding:3pt 4pt;white-space:normal}
  .sort-icon{display:none}
  .rb{width:30px}.rv{min-width:0;margin-right:3px}.cb{width:28px}.cell-bar{gap:4px}
  td.rng{white-space:nowrap}
  .viz.narrow,.viz.pitch-narrow{display:none!important}
  .viz.wide,.viz.pitch-wide{display:block!important}
  .viz svg{max-height:120mm;width:auto;max-width:100%;margin:0 auto}
  .players{grid-template-columns:repeat(2,1fr);gap:8pt}
  .kpis-n2{grid-template-columns:repeat(2,1fr)}.kpis-n3{grid-template-columns:repeat(3,1fr)}.kpis-n4,.kpis-n7,.kpis-n8{grid-template-columns:repeat(4,1fr)}.kpis-n5{grid-template-columns:repeat(5,1fr)}.kpis-n6{grid-template-columns:repeat(3,1fr)}
  .kpi{padding:8pt 10pt}.kpi-value{font-size:16pt}
  .colophon{background:#fff;padding:12pt 0 0;break-inside:avoid}
  a{color:inherit;text-decoration:none}
}
`;
