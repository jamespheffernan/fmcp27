import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { mkdtemp, mkdir, readFile, writeFile } from 'node:fs/promises';
import { join } from 'node:path';
import test from 'node:test';
import { registerSkillTool, skillIndex, stripPageHeader } from '../pi/fm-skills.mjs';

const id = 'fm-training-development';
const source = new URL(`../skills/${id}/SKILL.md`, import.meta.url);
const heading = '## Compare positional conversion projects\n';
function tool(root) {
  let reader;
  registerSkillTool({ registerTool: value => { reader = value; } }, root ? { root } : undefined);
  return reader;
}
// A guide longer than one page (12,000 characters) is read a page at a time, each under a header;
// the pages without their headers join to the source file.
async function guideText(reader, first) {
  let text = stripPageHeader(first.content[0].text);
  for (let page = 2; page <= first.details.pages; page += 1) {
    text += stripPageHeader((await reader.execute(`page-${page}`, { id, page })).content[0].text);
  }
  return text;
}
function conversionBranch(content) {
  const start = content.indexOf(heading);
  assert.ok(start >= 0, 'Loaded guide must include the positional-conversion decision branch');
  const end = content.indexOf('\n## ', start + heading.length);
  return content.slice(start, end < 0 ? undefined : end);
}

test('conversion request reaches the full actual training guide without another guide or a larger index budget', async () => {
  const reader = tool();
  const index = await reader.execute('index', { id: 'index' });
  assert.equal(index.details.guides.length, 16);
  assert.match(index.details.guides.find(g => g.id === id).when, /positional conversion projects/);
  assert.ok(Buffer.byteLength(skillIndex(), 'utf8') < 2500);
  const result = await reader.execute('training', { id });
  const bytes = await readFile(source);
  assert.equal(result.isError, undefined);
  assert.equal(await guideText(reader, result), bytes.toString('utf8'));
  assert.equal(result.details.content, bytes.toString('utf8'));
  assert.equal(result.details.sha256, createHash('sha256').update(bytes).digest('hex'));
  const branch = conversionBranch(result.details.content);
  for (const linked of ['fm-live-investigation', 'fm-tactical-analysis', 'fm-playing-time-dynamics',
                        'fm-squad-planning', 'fm-staff-planning']) {
    assert.ok(branch.includes('`' + linked + '`'));
    assert.equal((await reader.execute(linked, { id: linked })).isError, undefined);
  }
});

test('loader detects missing and wrong-identity training sources and recovers the exact actual branch', async () => {
  const scratch = await mkdtemp(new URL('../evidence/training-source-controls-', import.meta.url));
  const reader = tool(scratch);
  const missing = await reader.execute('missing', { id });
  assert.equal(missing.isError, true);
  assert.equal(missing.details.content, undefined);
  await mkdir(join(scratch, id));
  const path = join(scratch, id, 'SKILL.md');
  const bytes = await readFile(source);
  await writeFile(path, bytes.toString('utf8').replace(`name: ${id}`, 'name: fm-staff-planning'));
  const wrong = await reader.execute('wrong', { id });
  assert.equal(wrong.isError, true);
  assert.equal(wrong.details.content, undefined);
  assert.equal(wrong.details.sha256, undefined);
  await writeFile(path, bytes);
  const recovered = await reader.execute('restored', { id });
  assert.equal(await guideText(reader, recovered), bytes.toString('utf8'));
  assert.equal(recovered.details.sha256, createHash('sha256').update(bytes).digest('hex'));
  assert.ok(conversionBranch(recovered.details.content));
});

test('omitting the decision branch causally fails its content-delivery control while the guide remains readable', async () => {
  // This is an instruction-delivery regression, not a simulated model judgment.
  const scratch = await mkdtemp(new URL('../evidence/training-omitted-branch-', import.meta.url));
  await mkdir(join(scratch, id));
  const path = join(scratch, id, 'SKILL.md');
  const actual = await readFile(source, 'utf8');
  const branch = conversionBranch(actual);
  await writeFile(path, actual.replace(branch, ''));
  const reader = tool(scratch);
  const omitted = await reader.execute('omitted', { id });
  assert.equal(omitted.isError, undefined);
  assert.throws(() => conversionBranch(omitted.details.content), /positional-conversion decision branch/);
  await writeFile(path, actual);
  const restored = await reader.execute('restored', { id });
  assert.ok(conversionBranch(restored.details.content));
  assert.notEqual(omitted.details.sha256, restored.details.sha256);
});
