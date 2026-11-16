import assert from 'node:assert/strict';
import { existsSync, mkdirSync, mkdtempSync, readFileSync, readdirSync, realpathSync, rmSync, symlinkSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { basename, dirname, join } from 'node:path';
import test from 'node:test';
import { REPORT_TOOL, checkFilename, registerReportTool, reportFilename } from '../pi/fm-report.mjs';

const now = new Date('2026-11-11T10:00:00Z');
const spec = (extra = {}) => ({ title: 'Left-back shortlist', summary: 'Pursue Ferreira.', view: 'manager', game_date: '2028-01-14', sections: [{ type: 'text', paragraphs: ['Body.'] }], ...extra });

function setup() {
  const root = realpathSync(mkdtempSync(join(tmpdir(), 'fm-report-')));
  const outputs = join(root, 'Agent Outputs');
  let tool;
  registerReportTool({ registerTool(value) { tool = value; } }, { outputsDir: outputs, now, timeZone: 'Europe/London' });
  return { root, outputs, tool, run: params => tool.execute('test', params) };
}

test('registers fm_report with a strict top-level schema', () => {
  const { tool, root } = setup();
  try {
    assert.equal(REPORT_TOOL, 'fm_report');
    assert.equal(tool.name, 'fm_report');
    assert.equal(tool.parameters.additionalProperties, false);
    assert.deepEqual(tool.parameters.required, ['title', 'summary', 'sections']);
    assert.deepEqual(tool.parameters.properties.view.enum, ['manager', 'full']);
    assert.ok(tool.parameters.properties.sections.items.properties.type.enum.includes('pitch'));
    assert.ok(tool.description.length < 1200);
  } finally { rmSync(root, { recursive: true, force: true }); }
});

test('writes a dated, self-contained report and returns its absolute path', async () => {
  const { root, outputs, run } = setup();
  try {
    const result = await run(spec());
    assert.equal(result.isError, undefined, result.content[0].text);
    assert.equal(result.details.path, join(outputs, '2026-11-11 — Left-back shortlist.html'));
    const html = readFileSync(result.details.path, 'utf8');
    assert.match(html, /<title>Left-back shortlist<\/title>/);
    assert.equal(result.details.bytes, Buffer.byteLength(html));
    assert.match(result.details.sha256, /^[0-9a-f]{64}$/);
    assert.deepEqual(result.details.sections, ['text']);
    assert.equal(JSON.parse(result.content[0].text).path, result.details.path);
  } finally { rmSync(root, { recursive: true, force: true }); }
});

test('never overwrites: default names gain a suffix, explicit names are refused', async () => {
  const { root, outputs, run } = setup();
  try {
    const first = await run(spec());
    const second = await run(spec());
    assert.equal(basename(second.details.path), '2026-11-11 — Left-back shortlist (2).html');
    assert.notEqual(readFileSync(first.details.path, 'utf8'), '');
    const named = await run(spec({ filename: 'LB shortlist.html' }));
    assert.equal(basename(named.details.path), '2026-11-11 — LB shortlist.html');
    const again = await run(spec({ filename: '2026-11-11 — LB shortlist.html' }));
    assert.equal(again.isError, true);
    assert.match(again.content[0].text, /already exists; existing files are never overwritten/);
    assert.equal(readdirSync(outputs).length, 3);
  } finally { rmSync(root, { recursive: true, force: true }); }
});

test('refuses traversal, folders, hidden names, other extensions and control characters', async () => {
  const { root, outputs, run } = setup();
  try {
    for (const filename of ['../escape.html', 'sub/dir.html', 'a\\b.html', '.hidden.html', 'report.htm', 'report.html.exe', 'report.HTML', 'x..html', 'bell\u0007.html', 'rtl\u202e.html', ' padded.html', 'C:evil.html', '.html', 'x'.repeat(250) + '.html', 42]) {
      const result = await run(spec({ filename }));
      assert.equal(result.isError, true, String(filename));
      assert.match(result.content[0].text, /filename/);
    }
    assert.equal(existsSync(join(root, 'escape.html')), false);
    assert.equal(existsSync(outputs) ? readdirSync(outputs).length : 0, 0);
    assert.equal(checkFilename('2028 notes.html'), null);
  } finally { rmSync(root, { recursive: true, force: true }); }
});

test('does not follow a planted symlink at the target name or a symlinked output folder', async () => {
  const { root, outputs, run } = setup();
  try {
    mkdirSync(outputs);
    const sentinel = join(root, 'sentinel.txt');
    writeFileSync(sentinel, 'untouched');
    symlinkSync(sentinel, join(outputs, '2026-11-11 — Left-back shortlist.html'));
    const result = await run(spec());
    assert.equal(result.isError, undefined, result.content[0].text);
    assert.equal(basename(result.details.path), '2026-11-11 — Left-back shortlist (2).html');
    assert.equal(readFileSync(sentinel, 'utf8'), 'untouched');
    const explicit = await run(spec({ filename: '2026-11-11 — Left-back shortlist.html' }));
    assert.equal(explicit.isError, true);
    assert.equal(readFileSync(sentinel, 'utf8'), 'untouched');

    const real = join(root, 'elsewhere');
    mkdirSync(real);
    const linked = join(root, 'Linked Outputs');
    symlinkSync(real, linked);
    let tool;
    registerReportTool({ registerTool(value) { tool = value; } }, { outputsDir: linked, now });
    const refused = await tool.execute('t', spec());
    assert.equal(refused.isError, true);
    assert.match(refused.content[0].text, /not a real directory|resolves elsewhere/);
    assert.deepEqual(readdirSync(real), []);
  } finally { rmSync(root, { recursive: true, force: true }); }
});

test('invalid specs return every problem with its path and write nothing', async () => {
  const { root, outputs, run } = setup();
  try {
    const result = await run({ title: 'T', summary: 'S', sections: [{ type: 'table', columns: [{ key: 'a', label: 'A', type: 'number' }], rows: [{ a: true }] }, { type: 'radar' }] });
    assert.equal(result.isError, true);
    const text = result.content[0].text;
    assert.match(text, /^Report not created: the spec has 2 problems:/);
    assert.match(text, /sections\[0\]:table\.rows\[0\]\.a: expected a finite number/);
    assert.match(text, /sections\[1\]\.type: must be one of text, table/);
    assert.equal(result.details.issues.length, 2);
    for (const params of [null, undefined, 'text', []]) assert.equal((await run(params)).isError, true);
    assert.equal(existsSync(outputs) ? readdirSync(outputs).length : 0, 0);
  } finally { rmSync(root, { recursive: true, force: true }); }
});

test('specs that failed in real sessions are repaired, written and the repairs listed', async () => {
  const { root, outputs, run } = setup();
  try {
    const result = await run({
      title: 'Repairs', summary: 'S', view: 'full', extra_field: 1,
      sections: [
        { type: 'table', columns: [{ key: 'name', label: 'Player' }, { key: 'age', label: 'Age' }, { key: 'rating', label: 'Rating', type: 'rating' }, { key: 'wage', label: 'Wage', type: 'money' }],
          rows: [{ name: 'A', age: 19, rating: 7.6, wage: '45,000' }, { name: 'B', age: 21, rating: '7.1', wage: 'n/a' }] },
        { type: 'comparison', entities: [{ name: 'A' }, { name: 'B' }], metrics: [{ label: 'Starts', values: ['16 / 16', 12] }] },
        { type: 'scatter', x_label: 'x', y_label: 'y', points: [{ x: 1, y: 2, label: 'A label that is far longer than sixty characters allowed for a point', highlight: true }] },
      ],
    });
    assert.equal(result.isError, undefined, result.content[0].text);
    const receipt = JSON.parse(result.content[0].text);
    assert.ok(receipt.repaired.some(r => /extra_field: unknown field ignored/.test(r)));
    assert.ok(receipt.repaired.some(r => /rows\[1\]\.wage: string "n\/a" is not a number/.test(r)));
    assert.ok(receipt.repaired.some(r => /values\[0\]: string "16 \/ 16" is not a number/.test(r)));
    assert.ok(receipt.repaired.some(r => /points\[0\]\.label: shortened/.test(r)));
    const html = readFileSync(receipt.path, 'utf8');
    assert.match(html, /45K/);
    assert.equal(readdirSync(outputs).length, 1);
  } finally { rmSync(root, { recursive: true, force: true }); }
});

test('default filenames strip path characters from titles and stay bounded', () => {
  const name = reportFilename({ title: 'Scouting: A/B "test" <final>?' }, { date: '2026-11-11' }).name;
  assert.equal(name, '2026-11-11 — Scouting A B test final.html');
  assert.equal(checkFilename(name), null);
  const long = reportFilename({ title: 'é'.repeat(119) }, { date: '2026-11-11' }).name;
  assert.equal(checkFilename(long), null);
  assert.equal(reportFilename({ title: '...' }, { date: '2026-11-11' }).name, '2026-11-11 — FM report.html');
  assert.equal(dirname('x/' + name), 'x');
});
