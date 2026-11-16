import assert from 'node:assert/strict';
import { readdirSync, readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { join } from 'node:path';
import test from 'node:test';
import { LIMITS, ReportSpecError, formatValue, formationLayout, renderReport, validateReportSpec } from '../pi/fm-report-render.mjs';

const samples = fileURLToPath(new URL('../evals/report-samples/', import.meta.url));
const at = new Date('2026-11-11T10:00:00Z');
const render = spec => renderReport(spec, { generatedAt: at, timeZone: 'Europe/London' });
const base = (sections, extra = {}) => ({ title: 'Test report', summary: 'Answer first.', sections, ...extra });
const count = (html, re) => (html.match(re) ?? []).length;
const issuesOf = spec => {
  try { validateReportSpec(spec); } catch (error) { assert.ok(error instanceof ReportSpecError, error.message); return error.issues; }
  assert.fail('expected the spec to be rejected');
};

test('every sample spec validates and renders a self-contained page', () => {
  const files = readdirSync(samples).filter(f => f.endsWith('.json'));
  assert.equal(files.length, 5);
  for (const file of files) {
    const html = render(JSON.parse(readFileSync(join(samples, file), 'utf8')));
    assert.match(html, /^<!doctype html>/, file);
    assert.match(html, /<meta http-equiv="Content-Security-Policy" content="default-src 'none'/, file);
    assert.doesNotMatch(html, /(?:src|href)\s*=\s*["']?(?:https?:)?\/\//i, file);
    assert.doesNotMatch(html, /@import|url\(\s*["']?http/i, file);
    assert.equal(count(html, /<script>/g), 1, file);
    assert.ok(Buffer.byteLength(html) < 200_000, file);
  }
});

test('header shows game date, data view and generation time; footer carries sources and caveats', () => {
  const html = render(base([{ type: 'text', paragraphs: ['x'] }], { game_date: '2028-01-14', view: 'manager', sources: ['fm_get_player'], caveats: ['Ranges are partial.'] }));
  assert.match(html, /<dt>Game date<\/dt><dd><time datetime="2028-01-14">14 Jan 2028<\/time>/);
  assert.match(html, /view-manager">.*Manager knowledge<\/dd>/);
  assert.match(html, /<dt>Generated<\/dt><dd><time datetime="2026-11-11T10:00:00.000Z">11 Nov 2026, 10:00 GMT<\/time>/);
  assert.match(html, /id="sources-h">Sources<\/h2><ol><li>fm_get_player<\/li>/);
  assert.match(html, /id="caveats-h">Caveats<\/h2><ul><li>Ranges are partial.<\/li>/);
  assert.ok(html.indexOf('class="answer"') < html.indexOf('class="sec '), 'answer comes before sections');
  assert.match(render(base([{ type: 'text', bullets: ['y'] }], { view: 'full' })), /Full data<\/dd>/);
  assert.match(render(base([{ type: 'text', bullets: ['y'] }])), /view-none">Not stated/);
});

test('all model text is escaped and only **bold** is interpreted', () => {
  const evil = '<script>1</script>"><img src=x>';
  const spec = base([
    { type: 'text', title: evil, paragraphs: [`**${evil}**`], bullets: [evil] },
    { type: 'table', columns: [{ key: 'n', label: evil }, { key: 'v', label: 'V', type: 'number', unit: '<b>' }], rows: [{ n: evil, v: 1 }] },
    { type: 'player_cards', players: [{ name: evil, subtitle: evil, facts: [{ label: evil, value: evil }], tags: [evil], use_when: evil, attributes: { technical: [{ label: evil, value: { min: 3, max: 9 } }] } }] },
    { type: 'comparison', entities: [{ name: evil }, { name: 'B' }], metrics: [{ label: evil, values: [1, 2] }] },
    { type: 'bar_chart', bars: [{ label: evil, value: 3, note: '<i>' }], reference_lines: [{ value: 1, label: evil }] },
    { type: 'line_chart', series: [{ name: evil, points: [{ x: 1, y: 2, label: evil }, { x: 2, y: 3 }] }], x_label: evil, y_label: evil },
    { type: 'scatter', x_label: evil, y_label: evil, points: [{ x: 1, y: 1, label: evil, highlight: true }] },
    { type: 'pitch', teams: [{ id: 'a', name: evil }], positions: [{ x: 10, y: 10, label: '<b>', name: evil }], shots: [{ x: 90, y: 50, outcome: 'goal', player: evil }] },
    { type: 'timeline', events: [{ date: '2028-01-01', label: evil, detail: evil, subject: evil }] },
    { type: 'kpis', items: [{ label: evil, value: evil.slice(0, 20), note: evil.slice(0, 100) }] },
  ], { title: evil, subtitle: evil, sources: [evil], caveats: [evil] });
  const html = render(spec);
  assert.equal(count(html, /<script/g), 1);
  assert.doesNotMatch(html, /<img|<b>|<i>/);
  assert.match(html, /&lt;script&gt;1&lt;\/script&gt;&quot;&gt;&lt;img src=x&gt;/);
  assert.match(html, /<strong>&lt;script&gt;/);
});

test('control and direction-override characters are rejected, not rendered', () => {
  for (const title of ['Bad\u0007bell', 'Mirror\u202eevil', 'sep\u2028line']) {
    const issues = issuesOf(base([{ type: 'text', paragraphs: ['ok'] }], { title }));
    assert.match(issues[0], /^title: contains control or direction-override characters/);
  }
  // A newline or tab in a one-line field is folded into a space instead of refusing the report.
  const oneLine = title => validateReportSpec(base([{ type: 'text', paragraphs: ['ok'] }], { title })).title;
  assert.equal(oneLine('two\nlines'), 'two lines');
  assert.equal(oneLine('tab\t\tstop'), 'tab stop');
  assert.doesNotMatch(render(base([{ type: 'text', paragraphs: ['ok'] }], { title: 'two\nlines' })), /two\nlines/);
  // A multi-line field keeps its newline.
  assert.equal(validateReportSpec(base([{ type: 'text', paragraphs: ['Line one\nLine two'] }])).sections[0].paragraphs[0], 'Line one\nLine two');
});

test('validation names the section, field and allowed values', () => {
  const issues = issuesOf({
    title: '', summary: 'x', colour: 'red',
    sections: [
      { type: 'tabel' },
      { type: 'table', columns: [{ key: 'age', label: 'Age', type: 'number' }], rows: [{ age: '19 years' }, { agee: 3 }] },
      { type: 'table', columns: [{ key: 'pace', label: 'Pace', type: 'range' }], rows: [{ pace: { min: 15, max: 12 } }, { pace: { min: 3 } }, { pace: 25 }] },
      { type: 'comparison', entities: [{ name: 'A' }, { name: 'B' }], metrics: [{ label: 'Goals', values: [1] }] },
      { type: 'pitch', positions: [{ id: 'a', x: 1, y: 2, label: 'GK' }], links: [{ from: 'a', to: 'zz', count: 3 }] },
    ],
  });
  const text = issues.join('\n');
  assert.match(text, /title: must not be empty/);
  assert.match(text, /sections\[0\]\.type: must be one of text, table, player_cards/);
  assert.match(text, /sections\[2\]:table\.rows\[0\]\.pace: min 15 is greater than max 12/);
  assert.match(text, /sections\[2\]:table\.rows\[1\]\.pace: a range needs both min and max/);
  assert.match(text, /sections\[2\]:table\.rows\[2\]\.pace: must be between 1 and 20/);
  assert.ok(issues.length <= 12);
  // An unknown field and words in a number column cannot change a figure, so they are not refusals.
  assert.doesNotMatch(text, /colour|agee|19 years/);
  const more = issuesOf(base([
    { type: 'comparison', entities: [{ name: 'A' }, { name: 'B' }], metrics: [{ label: 'Goals', values: [1] }] },
    { type: 'pitch', positions: [{ id: 'a', x: 1, y: 2, label: 'GK' }], links: [{ from: 'a', to: 'zz', count: 3 }], formation: { slots: ['XX'] } },
    { type: 'timeline', events: [{ date: '2028-02-30', label: 'Bad date' }] },
  ])).join('\n');
  assert.match(more, /sections\[0\]:comparison\.metrics\[0\]\.values: needs at least 2 items/);
  assert.match(more, /sections\[1\]:pitch\.links\[0\]\.to: unknown position id string "zz"/);
  assert.match(more, /sections\[1\]:pitch\.formation\.slots\[0\]\.position: unknown position string "XX"; use FM labels such as GK, DL/);
  assert.match(more, /sections\[2\]:timeline\.events\[0\]\.date: expected an ISO date YYYY-MM-DD/);
  assert.throws(() => validateReportSpec(null), ReportSpecError);
  assert.throws(() => validateReportSpec(base([])), /sections: needs at least 1 item/);
});

test('repairs that cannot change a figure are made and named in the warnings', () => {
  const spec = validateReportSpec({
    title: 'T', summary: 'x', colour: 'red',
    sections: [{ type: 'table', columns: [{ key: 'age', label: 'Age', type: 'number' }], rows: [{ age: '19 years' }, { age: 3, agee: 3 }] }],
  });
  assert.deepEqual(spec.warnings, [
    'report.colour: unknown field ignored; allowed fields are title, subtitle, game_date, view, summary, sections, caveats, sources, filename',
    'sections[0]:table.rows[0].age: string "19 years" is not a number; the cell is shown blank (use a text column for words)',
    'sections[0]:table.rows[1].agee: unknown field ignored; allowed fields are age',
  ]);
  assert.equal('colour' in spec, false);
  assert.deepEqual(spec.sections[0].rows, [{ age: null }, { age: 3 }]);
});

test('an empty string in a table cell is a blank cell, in any column type', () => {
  const html = render(base([{ type: 'table', columns: [{ key: 'name', label: 'Name' }, { key: 'departure', label: 'Departure' }, { key: 'mins', label: 'Minutes', type: 'number' }, { key: 'due', label: 'Due', type: 'date' }],
    rows: [{ name: 'Miley', departure: '4 February', mins: 120, due: '2031-02-04' }, { name: 'Neves', departure: '', mins: '', due: '  ' }] }]));
  assert.match(html, /Miley/);
  assert.match(html, /Neves/);
  assert.doesNotThrow(() => validateReportSpec(base([{ type: 'table', columns: [{ key: 'a', label: 'A' }], rows: [{ a: '' }] }])));
});

test('numbers in text columns are shown as written instead of refused', () => {
  const spec = { title: 'T', summary: 'S', sections: [{ type: 'table', columns: [{ key: 'name', label: 'Name' }, { key: 'age', label: 'Age' }], rows: [{ name: 'A', age: 19 }, { name: 'B', age: 20.5 }] }] };
  const html = renderReport(validateReportSpec(spec));
  assert.match(html, />19</);
  assert.match(html, />20\.5</);
});

test('size caps stop runaway specs before rendering', () => {
  const text = { type: 'text', paragraphs: ['x'] };
  assert.match(issuesOf(base(Array(LIMITS.sections + 1).fill(text)))[0], /sections: has 31 items; the cap is 30/);
  const rows = Array.from({ length: LIMITS.rows + 1 }, (_, i) => ({ n: i }));
  assert.match(issuesOf(base([{ type: 'table', columns: [{ key: 'n', label: 'N', type: 'number' }], rows }]))[0], /rows: has 401 items; the cap is 400/);
  const points = Array.from({ length: LIMITS.scatterPoints + 1 }, (_, i) => ({ x: i, y: i }));
  assert.match(issuesOf(base([{ type: 'scatter', x_label: 'x', y_label: 'y', points }]))[0], /points: has 601 items/);
  // Text over its limit is cut to the limit with an ellipsis and named in the warnings, not refused.
  const long = validateReportSpec(base([{ type: 'text', paragraphs: ['é'.repeat(LIMITS.paragraphChars + 1)] }]));
  assert.equal(long.sections[0].paragraphs[0], `${'é'.repeat(LIMITS.paragraphChars - 1)}…`);
  assert.deepEqual(long.warnings, ['sections[0]:text.paragraphs[0]: shortened from 1201 to 1200 characters']);
  // Three full-width 400-row tables exceed the per-report cell budget.
  const columns = Array.from({ length: LIMITS.columns }, (_, i) => ({ key: `c${i}`, label: `C${i}`, type: 'number' }));
  const full = Array.from({ length: LIMITS.rows }, () => Object.fromEntries(columns.map(c => [c.key, 1])));
  const table = { type: 'table', columns, rows: full };
  assert.match(issuesOf(base([table, table, table])).join('\n'), /exceeds the 12000 table cells cap/);
  // The largest spec the caps allow still renders under the byte cap.
  const longText = 'Wide text cell for the byte budget '.repeat(8).slice(0, 280);
  const textColumns = columns.map(c => ({ ...c, type: 'text' }));
  const wide = Array.from({ length: LIMITS.rows }, () => Object.fromEntries(textColumns.map(c => [c.key, longText])));
  try {
    const html = render(base([{ type: 'table', columns: textColumns, rows: wide }, { type: 'table', columns: textColumns, rows: wide.slice(0, 457) }]));
    assert.ok(Buffer.byteLength(html) <= LIMITS.htmlBytes);
  } catch (error) {
    assert.ok(error instanceof ReportSpecError);
    assert.match(error.message, /MiB; the cap is 4 MiB/);
  }
});

test('table renders sortable headers, range bars, unknown dashes, heat and highlight', () => {
  const html = render(base([{
    type: 'table', title: 'Pool',
    columns: [
      { key: 'name', label: 'Player' }, { key: 'fee', label: 'Fee', type: 'money' }, { key: 'ends', label: 'Ends', type: 'date' },
      { key: 'pace', label: 'Pace', type: 'range' }, { key: 'ca', label: 'CA', type: 'number', scale: { min: 100, max: 160, style: 'heat' } },
      { key: 'share', label: 'Share', type: 'percent', scale: { max: 100 } },
    ],
    rows: [
      { name: 'A', fee: 6500000, ends: '2029-06-30', pace: { min: 15, max: 17 }, ca: 150, share: 40 },
      { name: 'B', fee: 950, ends: null, pace: 14, ca: 100, share: 0 },
      { name: 'C', fee: null, ends: '2028-06-30', pace: null, ca: 160, share: 100 },
    ],
    highlight_rows: [0],
  }]));
  assert.equal(count(html, /<th scope="col" class="a-\w+"><button type="button" data-col="\d"/g), 6);
  assert.match(html, /<table class="data" data-sortable>/);
  assert.match(html, /data-sort="16">.*15–17.*between 15 and 17.*class="rb-band" style="left:73\.7%;width:10\.5%"/s);
  assert.match(html, /14, exact<\/span><span class="rb "[^>]*><span class="rb-tick" style="left:68\.4%"/);
  assert.match(html, /<span class="sr">Unknown<\/span><span class="rb  rb-unknown"/);
  assert.match(html, /£6\.5M/);
  assert.match(html, /£950/);
  assert.match(html, /30 Jun 2029/);
  assert.match(html, /class="a-right num heat" data-sort="150" style="--t:0\.458"/);
  assert.match(html, /<tr class="hl"><th scope="row"/);
  assert.match(html, /exact value<\/span>/, 'range key appears with range columns');
  assert.match(render(base([{ type: 'table', columns: [{ key: 'a', label: 'A' }], rows: [] }])), /class="empty"/);
});

test('player cards group attributes, mark key ones and support ranges', () => {
  const html = render(base([{ type: 'player_cards', players: [
    { name: 'Ferreira', subtitle: 'LB · 20', facts: [{ label: 'Value', value: '£6.5M' }, { label: 'Age', value: 20 }], key_attributes: ['pace'],
      attributes: { technical: [{ label: 'Passing', value: { min: 12, max: 15 } }], physical: [{ label: 'Pace', value: 16 }, { label: 'Stamina', value: null }] }, use_when: 'You need **recovery pace**.' },
    { name: 'Verbeek' },
  ] }]));
  assert.equal(count(html, /<article class="player">/g), 2);
  assert.match(html, /<h4>Technical<\/h4>.*<h4>Physical<\/h4>/s);
  assert.doesNotMatch(html, /<h4>Mental<\/h4>/);
  assert.match(html, /<li class="key"><span class="an">Pace<span class="sr"> \(key for the role\)/);
  assert.match(html, /between 12 and 15/);
  assert.match(html, /Use when<\/strong> You need <strong>recovery pace<\/strong>\./);
  assert.match(html, /key attribute for the role/);
});

test('comparison marks the better value only where the difference is certain', () => {
  const html = render(base([{ type: 'comparison', entities: [{ name: 'A' }, { name: 'B' }, { name: 'C' }], metrics: [
    { label: 'Goals', values: [5, 9, 7] },
    { label: 'Wage', type: 'money', values: [40000, 30000, 50000], better: 'low' },
    { label: 'Pace', type: 'range', values: [{ min: 12, max: 15 }, { min: 14, max: 16 }, 10] },
    { label: 'Finishing', type: 'range', values: [{ min: 16, max: 18 }, 14, null] },
    { label: 'Equal', values: [3, 3, 3] },
    { label: 'Age', values: [20, 25, 30], better: 'none' },
  ] }]));
  const rows = html.split('<tr>').filter(r => r.includes('scope="row"'));
  const bestCols = r => [...r.matchAll(/<td class="(best)?">/g)].map((m, i) => m[1] ? i : -1).filter(i => i >= 0);
  assert.deepEqual(bestCols(rows[0]), [1]);
  assert.deepEqual(bestCols(rows[1]), [1]);
  assert.deepEqual(bestCols(rows[2]), [], 'overlapping ranges are not marked');
  assert.deepEqual(bestCols(rows[3]), [0], 'a range wholly above the others wins');
  assert.deepEqual(bestCols(rows[4]), [], 'a full tie marks nothing');
  assert.deepEqual(bestCols(rows[5]), []);
  assert.match(html, /<span class="sr"> \(better\)<\/span>/);
  assert.match(html, /lower is better/);
});

test('bar chart draws one bar per value with direct labels and reference lines', () => {
  const html = render(base([
    { type: 'bar_chart', bars: [{ label: 'A', value: 8.1, highlight: true }, { label: 'B', value: -2 }, { label: 'C', value: 6 }], reference_lines: [{ value: 6.9, label: 'Average' }], decimals: 1 },
    { type: 'bar_chart', categories: ['xG', 'Shots'], series: [{ name: 'One', values: [1, 2] }, { name: 'Two', values: [3, 4] }] },
  ]));
  assert.equal(count(html, /<span class="bar s1/g), 3 + 2);
  assert.equal(count(html, /<span class="bar s2/g), 2);
  assert.match(html, /class="bar s1 hl"/);
  assert.match(html, /class="bar s1 dim neg"/);
  assert.match(html, /<span class="bv" style="left:[\d.]+%">8\.1<\/span>/);
  assert.match(html, /<span class="bv bv-neg" style="right:[\d.]+%">−2\.0<\/span>/);
  assert.match(html, /<span class="ref-label">Average<\/span>/);
  assert.match(html, /<span class="zero"/);
  assert.match(html, /<ul class="legend"[^>]*><li><span class="key key-bar s1"[^>]*><\/span>One<\/li>/);
});

test('stacked bar chart draws who covers a requirement, how well, the compromises and the shortfall', () => {
  const section = {
    type: 'stacked_bar_chart', title: 'Cover by position', value_label: 'Minutes', unit: 'min', target_label: 'Minutes needed', hatched_label: 'Doing a job',
    bands: ['Strong', 'Rotation', 'Lower'],
    bars: [
      { label: 'Midfield', target: 1620, note: 'Blended 15.1', segments: [
        { label: 'Neves', value: 700, band: 'Strong' }, { label: 'Chema', value: 500, band: 'Strong' },
        { label: 'Finneran', value: 250, band: 'Rotation', note: 'Squad Player' }, { label: 'Charles', value: 100, band: 'Lower', hatched: true },
        { label: 'Unused', value: 0, band: 'Lower' } ] },
      { label: 'Striker', target: 810, segments: [{ label: '<b>Woltemade</b>', value: 600, band: 'Strong' }, { label: 'Konaté', value: 300, band: 'Strong' }] },
    ],
  };
  const html = render(base([section]));
  assert.equal(count(html, /<span class="seg b1of3"/g), 4);
  assert.equal(count(html, /<span class="seg b2of3"/g), 1);
  assert.equal(count(html, /<span class="seg b3of3 hatched"/g), 1, 'a zero-width segment is not drawn');
  // Midfield supplies 1,550 of 1,620: the shortfall is drawn and said; the striker row is covered.
  assert.equal(count(html, /<span class="seg seg-gap" style/g), 1);
  assert.match(html, /Not covered: 70[^<]*min\./);
  assert.match(html, /<span class="stack-total short">1,550 of 1,620.min · 70 not covered<\/span>/u);
  assert.match(html, /<span class="stack-total">900 of 810.min<\/span>/u, 'the unit is said once');
  assert.equal(count(html, /<span class="seg-target"/g), 2);
  assert.match(html, /title="Charles: 100[^"]*min, Lower, doing a job"/);
  assert.match(html, /title="Finneran: 250[^"]*min, Rotation \(Squad Player\)"/);
  assert.match(html, /<span class="stack-note">Blended 15\.1<\/span>/);
  const long = 'Promise: Robinson by 23 January. '.repeat(10).trim();
  assert.ok(render(base([{ ...section, bars: [{ label: 'A', note: long, segments: [] }] }])).includes(long), 'a 330-character note is kept whole');
  // Key: the three bands, the hatch, the target and the shortfall. Colour is never the only carrier.
  for (const key of ['Strong', 'Rotation', 'Lower', 'Doing a job', 'Minutes needed', 'Not covered']) assert.match(html, new RegExp(`aria-hidden="true"></span>${key}</li>`), key);
  assert.match(html, /<th scope="col">Bar<\/th><th scope="col">Segment<\/th><th scope="col">Minutes<\/th><th scope="col">Band<\/th><th scope="col">Doing a job<\/th>/);
  assert.match(html, /<td>Midfield<\/td><td>Total<\/td><td>1,550 of 1,620.min · 70 not covered<\/td>/u);
  assert.doesNotMatch(html, /<b>Woltemade/);
  assert.match(html, /&lt;b&gt;Woltemade&lt;\/b&gt;/);

  const plain = render(base([{ type: 'stacked_bar_chart', bars: [{ label: 'A', segments: [{ label: 'x', value: 2 }, { label: 'y', value: 1 }] }] }]));
  assert.equal(count(plain, /<span class="seg b1of1"/g), 2);
  assert.doesNotMatch(plain, /class="legend"/);
  assert.doesNotMatch(plain, /class="seg-target"|class="seg seg-gap"/);

  assert.throws(() => validateReportSpec(base([{ ...section, bars: [{ label: 'A', segments: [{ label: 'x', value: 1, band: 'Elite' }] }] }])), /segments\[0\]\.band: must be one of Strong, Rotation, Lower/);
  assert.throws(() => validateReportSpec(base([{ type: 'stacked_bar_chart', bars: [{ label: 'A', segments: [{ label: 'x', value: 1, band: 'Strong' }] }] }])), /name the bands, best first/);
  assert.throws(() => validateReportSpec(base([{ type: 'stacked_bar_chart', bars: [{ label: 'A', segments: [{ label: 'x', value: -1 }] }] }])), /must be between 0 and/);
  assert.throws(() => validateReportSpec(base([{ type: 'stacked_bar_chart', bands: ['a', 'a'], bars: [{ label: 'A', segments: [] }] }])), /band names must differ/);
});

test('line chart and scatter render wide and narrow SVGs with direct labels and a data table', () => {
  const html = render(base([
    { type: 'line_chart', x_type: 'date', series: [{ name: 'xG for', points: [{ x: '2028-01-01', y: 1 }, { x: '2028-02-01', y: 2 }] }, { name: 'xG against', points: [{ x: '2028-01-01', y: 1.1 }, { x: '2028-02-01', y: null }, { x: '2028-03-01', y: 1.5 }] }], reference_lines: [{ value: 1.35, label: 'League' }] },
    { type: 'scatter', x_label: 'Value', y_label: 'Readiness', points: [{ x: 1, y: 2, label: 'Alpha', highlight: true, group: 'G1' }, { x: 3, y: 4, label: 'Beta', group: 'G2' }] },
  ]));
  assert.equal(count(html, /<svg class="chart line-chart"/g), 2);
  assert.equal(count(html, /<path class="line"/g), 2 * 3, 'a null splits the second series into two paths');
  assert.equal(count(html, /class="end-label"/g), 4);
  assert.match(html, />League<\/text>/);
  assert.equal(count(html, /<svg class="chart scatter"/g), 2);
  assert.equal(count(html, /<circle class="dot"/g), 2 * 4 + 2 * 2, 'line dots (series of 14 points or fewer) plus scatter dots');
  assert.equal(count(html, />Alpha<\/text>/g), 2, 'only highlighted points are labelled by default');
  assert.match(html, /<title>Beta \(G2\): Value 3, Readiness 4<\/title>/);
  assert.equal(count(html, /<details class="data-view">/g), 2);
  assert.match(html, /<li><span class="key key-dot s2" aria-hidden="true"><\/span>G2<\/li>/);
});

test('pitch draws markings, shots by outcome, nodes, links, zones, formation and attack direction', () => {
  const html = render(base([{ type: 'pitch', teams: [{ id: 'h', name: 'Home' }, { id: 'a', name: 'Away' }],
    shots: SHOTS, positions: [{ id: 'gk', x: 5, y: 50, label: '1', name: 'Keeper', touches: 30 }, { id: 'cb', x: 25, y: 40, label: '5', touches: 60 }],
    links: [{ from: 'gk', to: 'cb', count: 9 }], zones: [{ x: 0, y: 0, w: 50, h: 50, value: 3 }, { x: 50, y: 0, w: 50, h: 50, value: 9, label: 'Hot' }], show_zone_values: true,
    formation: { shape: '4-4-2', team: 'a', slots: ['GK', 'DL', 'DC', 'DC', 'DR', 'ML', 'MC', 'MC', 'MR', 'ST', { position: 'ST', name: 'Nine', number: 9 }] } }]));
  assert.equal(count(html, /<svg class="chart pitch pitch-h"/g), 1);
  assert.equal(count(html, /<svg class="chart pitch pitch-v"/g), 1);
  assert.equal(count(html, /<g class="markings">/g), 2);
  assert.equal(count(html, /class="shot goal t1"/g), 2 + 1, 'goal in both orientations plus the legend key');
  assert.equal(count(html, /class="shot blocked t2"/g), 2);
  assert.equal(count(html, /<path class="shot post/g), 2 + 1);
  assert.equal(count(html, /<g class="node t1">/g), 2 * 2);
  assert.equal(count(html, /<g class="node t2">/g), 2 * 11);
  assert.equal(count(html, /<line class="link t1"/g), 2 + 2, 'one link per orientation plus two legend keys');
  assert.equal(count(html, /<rect class="zone"/g), 2 * 2);
  assert.equal(count(html, />Hot<\/text>/g), 2);
  assert.match(html, /Home attack<\/text>/);
  assert.match(html, /Away attack<\/text>/);
  assert.match(html, /<span class="label">Shape<\/span> 4-4-2/);
  assert.match(html, /Size = xG/);
  assert.match(html, /<caption>Shots<\/caption>/);
  // The pitch keeps FIFA proportions: 105 x 68 at 6 px per metre plus padding.
  assert.match(html, /viewBox="0 0 658 466"/);
});

const SHOTS = [
  { x: 90, y: 50, xg: 0.4, outcome: 'goal', player: 'Nine', minute: 12, team: 'h' },
  { x: 85, y: 30, outcome: 'post', team: 'h' },
  { x: 80, y: 60, xg: 0.1, outcome: 'blocked', team: 'a' },
];

test('formation layout puts the left side on the attacking team’s left and spreads duplicates', () => {
  const layout = formationLayout([{ position: 'DL' }, { position: 'DC' }, { position: 'DC' }, { position: 'DR' }, { position: 'ST' }]);
  assert.ok(layout[0].y < layout[1].y && layout[1].y < layout[2].y && layout[2].y < layout[3].y);
  assert.equal(layout[1].y, 40);
  assert.equal(layout[2].y, 60);
  assert.ok(layout[4].x > layout[0].x);
});

test('timeline groups by month, marks the game date and shows relative time and status', () => {
  const html = render(base([{ type: 'timeline', events: [
    { date: '2028-03-01', label: 'Later', kind: 'fixture' },
    { date: '2027-12-20', label: 'Earlier', kind: 'contract', status: 'critical', subject: 'Sule' },
    { date: '2028-01-14', label: 'Same day', kind: 'injury' },
  ] }], { game_date: '2028-01-14' }));
  assert.deepEqual([...html.matchAll(/<h3 class="tl-month">([^<]+)<\/h3>/g)].map(m => m[1]), ['December 2027', 'January 2028', 'March 2028']);
  const today = html.indexOf('<li class="tl-today"');
  assert.ok(html.indexOf('Earlier') < today && today < html.indexOf('Same day'));
  assert.match(html, /4 weeks ago/);
  assert.match(html, /on the game date/);
  assert.match(html, /in 7 weeks/);
  assert.match(html, /class="status st-critical">.*Act now/);
  assert.match(html, /<strong class="tl-subject">Sule<\/strong>/);
});

test('kpis format values and colour deltas by whether up is good, with text backup', () => {
  const html = render(base([{ type: 'kpis', items: [
    { label: 'xG', value: 1.84, decimals: 2, delta: 0.3, delta_label: 'vs avg' },
    { label: 'Wage bill', value: 96, type: 'percent', delta: 4, better: 'low' },
    { label: 'Budget', value: 9000000, type: 'money' },
    { label: 'Score', value: '2–1' },
  ] }]));
  assert.equal(count(html, /<div class="kpi">/g), 4);
  assert.match(html, /class="kpi-value">1\.84</);
  assert.match(html, /d-good">.*\+0\.30 <span class="delta-label">vs avg<\/span><span class="sr"> \(better\)/);
  assert.match(html, /d-bad">.*\+4%<span class="sr"> \(worse\)/);
  assert.match(html, />£9M</);
  assert.match(html, />2–1</);
});

test('number formatting', () => {
  assert.equal(formatValue(12500000, 'money'), '£12.5M');
  assert.equal(formatValue(850000, 'money'), '£850K');
  assert.equal(formatValue(-1200000, 'money', { currency: '€' }), '−€1.2M');
  assert.equal(formatValue(14500, 'money', { unit: 'p/w' }), '£14.5K\u00a0p/w');
  assert.equal(formatValue(62.5, 'percent'), '62.5%');
  assert.equal(formatValue(1234.5, 'number', { decimals: 1 }), '1,234.5');
  assert.equal(formatValue('2029-06-30', 'date'), '30 Jun 2029');
});
