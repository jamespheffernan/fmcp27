import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { mkdtemp, mkdir, readFile, writeFile, symlink, rename, realpath } from 'node:fs/promises';
import { join } from 'node:path';
import { tmpdir } from 'node:os';
import test from 'node:test';
import { appendedPrompt, paginate, PAGE_CHARS, registerSkillTool, skillIndex, stripPageHeader } from '../pi/fm-skills.mjs';

function tool(root) {
  let registered;
  registerSkillTool({ registerTool: value => { registered = value; } }, root ? { root } : undefined);
  return registered;
}

test('every indexed guide loads in full with a verifiable hash and all linked guide ids are reachable', async () => {
  const reader = tool();
  const index = await reader.execute('index', { id: 'index' });
  assert.equal(index.isError, undefined);
  assert.equal(index.details.content, skillIndex());
  const ids = new Set(index.details.guides.map(g => g.id));
  assert.equal(ids.size, 16);
  for (const id of ids) {
    assert.ok(skillIndex().includes(id));
    const result = await reader.execute(id, { id });
    assert.equal(result.isError, undefined, JSON.stringify(result));
    const original = await readFile(new URL(`../skills/${id}/SKILL.md`, import.meta.url));
    // Every page fits Code Mode's output budget; the pages rebuild the guide exactly.
    let text = stripPageHeader(result.content[0].text);
    for (let page = 2; page <= result.details.pages; page++) {
      const next = await reader.execute(id, { id, page });
      assert.equal(next.isError, undefined, JSON.stringify(next));
      assert.ok(next.content[0].text.length < 40000);
      text += stripPageHeader(next.content[0].text);
    }
    assert.equal(text, original.toString('utf8'));
    assert.ok(result.content[0].text.length <= PAGE_CHARS + 200);
    assert.equal(result.details.sha256, createHash('sha256').update(original).digest('hex'));
    assert.equal(result.details.kind, 'guidance');
    for (const match of result.details.content.matchAll(/`(fm-[a-z-]+)`/g)) {
      if (match[1].includes('_')) continue;
      assert.ok(ids.has(match[1]), `unreachable guide ${match[1]} in ${id}`);
    }
  }
  assert.ok(Buffer.byteLength(skillIndex(), "utf8") < 2500);
});

test('long guides are paged with a next-page header and no lost text', async () => {
  const reader = tool();
  const first = await reader.execute('p1', { id: 'fm-live-investigation' });
  assert.ok(first.details.pages > 1);
  assert.match(first.content[0].text, /^\[fm-live-investigation: page 1 of \d+\. Continue with fm_read_skill \{"id":"fm-live-investigation","page":2\}/);
  const last = await reader.execute('pn', { id: 'fm-live-investigation', page: first.details.pages });
  assert.match(last.content[0].text, /End of guide\.\]/);
  assert.equal(last.details.sha256, first.details.sha256);
  const beyond = await reader.execute('px', { id: 'fm-live-investigation', page: first.details.pages + 1 });
  assert.equal(beyond.isError, true);
  for (const page of [0, -1, 1.5, '2']) assert.equal((await reader.execute('bad', { id: 'fm-tools', page })).isError, true, String(page));
  const short = await reader.execute('short', { id: 'fm-set-pieces' });
  assert.equal(short.details.pages, 1);
  assert.doesNotMatch(short.content[0].text, /^\[fm-set-pieces: page/);
});

test('paginate breaks at headings and keeps every character', () => {
  const text = Array.from({ length: 40 }, (_, i) => `## Section ${i}\n\n${'word '.repeat(80)}\n`).join('\n');
  const pages = paginate(text, 2000);
  assert.ok(pages.length > 1);
  assert.equal(pages.join(''), text);
  assert.ok(pages.every(page => page.length <= 2000));
  assert.ok(pages.slice(1).every(page => page.startsWith('## ')));
  assert.deepEqual(paginate('x'.repeat(5000), 2000).map(p => p.length), [2000, 2000, 1000]);
});

test('the appended prompt holds the core guide and a marked fm-db entry', () => {
  const prompt = appendedPrompt();
  assert.match(prompt, /^# Core procedure/);
  assert.match(prompt, /<!-- fm:if fm_db_query -->\n- \*\*fm-db\*\*/);
  assert.doesNotMatch(skillIndex(), /<!-- fm:/);
});

test('training guide is selectable and connected to squad planning in both directions', async () => {
  const reader = tool();
  assert.ok(reader.parameters.properties.id.enum.includes('fm-training-development'));
  const index = await reader.execute('index', { id: 'index' });
  const trainingEntry = index.details.guides.find(g => g.id === 'fm-training-development');
  assert.ok(trainingEntry);
  assert.match(trainingEntry.when, /training calendars/);
  const training = await reader.execute('training', { id: trainingEntry.id });
  const squad = await reader.execute('squad', { id: 'fm-squad-planning' });
  assert.equal(training.isError, undefined);
  assert.equal(training.details.source, 'skills/fm-training-development/SKILL.md');
  assert.match(training.details.content, /`fm-squad-planning`/);
  assert.match(squad.details.content, /`fm-training-development`/);
});

test('only approved ids are readable, including when schema validation is bypassed', async () => {
  const reader = tool();
  for (const params of [{ id: '../pi/system.md' }, { id: '/etc/passwd' }, { id: 'fm-tools/SKILL.md' }, { id: 'fm-tools', path: '/etc/passwd' }, { id: null }, null]) {
    const result = await reader.execute('invalid', params);
    assert.equal(result.isError, true, JSON.stringify(params));
    assert.equal(result.details.content, undefined);
  }
});

test('reads current bundled content without retaining a stale guide after edits', async () => {
  const root = await realpath(await mkdtemp(join(tmpdir(), 'fm-skills-')));
  await mkdir(join(root, 'fm-tools'));
  const file = join(root, 'fm-tools', 'SKILL.md');
  const first = '---\nname: fm-tools\n---\nFirst procedure.\n';
  const second = '---\nname: fm-tools\n---\nRevised procedure.\n';
  await writeFile(file, first);
  const reader = tool(root);
  const a = await reader.execute('a', { id: 'fm-tools' });
  assert.equal(a.content[0].text, first);
  await writeFile(file, second);
  const b = await reader.execute('b', { id: 'fm-tools' });
  assert.equal(b.content[0].text, second);
  assert.notEqual(a.details.sha256, b.details.sha256);
});

test('missing, oversized, invalid UTF8, mismatched and symlinked guides produce explicit errors', async () => {
  const root = await realpath(await mkdtemp(join(tmpdir(), 'fm-skills-bad-')));
  const reader = tool(root);
  assert.equal((await reader.execute('missing', { id: 'fm-tools' })).isError, true);
  const dir = join(root, 'fm-tools');
  await mkdir(dir);
  const file = join(dir, 'SKILL.md');
  for (const content of ['x'.repeat(65537), Buffer.from([255, 255]), '---\nname: wrong-guide\n---\nWrong guide.']) {
    await writeFile(file, content);
    const result = await reader.execute('bad', { id: 'fm-tools' });
    assert.equal(result.isError, true);
    assert.equal(result.details.sha256, undefined);
  }
  await rename(file, join(root, 'elsewhere.md'));
  await symlink(join(root, 'elsewhere.md'), file);
  assert.equal((await reader.execute('symlink-file', { id: 'fm-tools' })).isError, true);
  await rename(dir, join(root, 'moved'));
  await symlink(join(root, 'moved'), dir);
  assert.equal((await reader.execute('symlink-dir', { id: 'fm-tools' })).isError, true);
});

test('the public reader withholds a valid-looking outside guide behind a replaced ancestor', async () => {
  const scratch = await realpath(await mkdtemp(join(tmpdir(), 'fm-skills-lineage-')));
  const checked = join(scratch, 'checked');
  const root = join(checked, 'skills');
  await mkdir(join(root, 'fm-tools'), { recursive: true });
  await writeFile(join(root, 'fm-tools', 'SKILL.md'), '---\nname: fm-tools\n---\nApproved.\n');
  const reader = tool(root);
  assert.equal((await reader.execute('approved', { id: 'fm-tools' })).isError, undefined);
  const outside = join(scratch, 'outside');
  await mkdir(join(outside, 'skills', 'fm-tools'), { recursive: true });
  const marker = 'OUTSIDE_CONTENT_MUST_NOT_BE_READ';
  await writeFile(join(outside, 'skills', 'fm-tools', 'SKILL.md'), `---\nname: fm-tools\n---\n${marker}\n`);
  await rename(checked, join(scratch, 'original'));
  await symlink(outside, checked);
  const result = await reader.execute('replaced', { id: 'fm-tools' });
  assert.equal(result.isError, true);
  assert.equal(result.details.content, undefined);
  assert.equal(result.details.sha256, undefined);
  assert.ok(!JSON.stringify(result).includes(marker));
});


test('playing-time guide is selectable and connected to a loadable squad/season decision route', async () => {
  const reader = tool();
  assert.ok(reader.parameters.properties.id.enum.includes('fm-playing-time-dynamics'));
  const index = await reader.execute('index', { id: 'index' });
  const entry = index.details.guides.find(g => g.id === 'fm-playing-time-dynamics');
  assert.match(entry.when, /agreed roles versus observed use/);
  const guide = await reader.execute('dynamics', { id: entry.id });
  const squad = await reader.execute('squad', { id: 'fm-squad-planning' });
  assert.equal(guide.isError, undefined);
  assert.equal(guide.details.source, 'skills/fm-playing-time-dynamics/SKILL.md');
  assert.match(squad.details.content, /`fm-playing-time-dynamics`/);
  for (const id of ['fm-season-planning', 'fm-squad-planning', 'fm-contracts-loans', 'fm-staff-planning']) {
    assert.ok(guide.details.content.includes('`' + id + '`'));
    assert.equal((await reader.execute(id, { id })).isError, undefined);
  }
});

test('playing-time reader detects a removed source and a planted guide identity mismatch', async () => {
  const root = await realpath(await mkdtemp(join(tmpdir(), 'fm-playing-time-controls-')));
  const reader = tool(root);
  assert.equal((await reader.execute('absent', { id: 'fm-playing-time-dynamics' })).isError, true);
  await mkdir(join(root, 'fm-playing-time-dynamics'));
  const file = join(root, 'fm-playing-time-dynamics', 'SKILL.md');
  const wrong = '---\nname: fm-staff-planning\n---\nWrong guide identity.\n';
  await writeFile(file, wrong);
  const rejected = await reader.execute('wrong', { id: 'fm-playing-time-dynamics' });
  assert.equal(rejected.isError, true);
  assert.equal(rejected.details.content, undefined);
  const right = '---\nname: fm-playing-time-dynamics\n---\nReview the agreement and observed use.\n';
  await writeFile(file, right);
  const loaded = await reader.execute('right', { id: 'fm-playing-time-dynamics' });
  assert.equal(loaded.isError, undefined);
  assert.equal(loaded.content[0].text, right);
  assert.equal(loaded.details.sha256, createHash('sha256').update(right).digest('hex'));
});


test('set-piece and club-development decisions have distinct connected loadable routes', async () => {
  const reader = tool();
  const routes = [
    ['fm-set-pieces', 'fm-tactical-analysis', /penalty order/, ['fm-tools', 'fm-live-investigation', 'fm-tactical-analysis']],
    ['fm-club-development', 'fm-training-development', /facilities/, ['fm-tools', 'fm-live-investigation', 'fm-training-development', 'fm-squad-planning', 'fm-staff-planning', 'fm-club-finance']],
  ];
  const index = await reader.execute('index', { id: 'index' });
  for (const [id, parent, trigger, dependencies] of routes) {
    assert.ok(reader.parameters.properties.id.enum.includes(id));
    const entry = index.details.guides.find(g => g.id === id);
    assert.match(entry.when, trigger);
    const guide = await reader.execute(id, { id });
    assert.equal(guide.isError, undefined);
    assert.match((await reader.execute(parent, { id: parent })).details.content, new RegExp('`' + id + '`'));
    for (const dependency of dependencies) {
      assert.ok(guide.details.content.includes('`' + dependency + '`'));
      assert.equal((await reader.execute(dependency, { id: dependency })).isError, undefined);
    }
  }
});
