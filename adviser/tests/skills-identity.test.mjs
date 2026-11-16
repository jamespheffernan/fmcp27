import assert from 'node:assert/strict';
import { readFile, mkdtemp, mkdir, writeFile } from 'node:fs/promises';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { spawnSync } from 'node:child_process';
import test from 'node:test';
import { registerSkillTool, validGuideIdentity } from '../pi/fm-skills.mjs';

const root = fileURLToPath(new URL('../', import.meta.url));
const cases = JSON.parse(await readFile(new URL('./skill-identity-cases.json', import.meta.url), 'utf8'));

test('JS independently validates the opening identity, conflicts and duplicate fields', () => {
  for (const fixture of cases) {
    assert.equal(validGuideIdentity(fixture.content, 'fm-tools'), fixture.accepted, fixture.label);
  }
});

test('Python independently validates identity before returning approved-root content', () => {
  const run = spawnSync('/usr/bin/python3', ['-I', '-S', '-B', fileURLToPath(new URL('./skills-identity.py', import.meta.url))],
    { encoding: 'utf8', timeout: 10000 });
  assert.equal(run.status, 0, run.stderr || String(run.error));
  const result = JSON.parse(run.stdout);
  assert.equal(result.controls, cases.length);
  assert.equal(result.rejected, cases.filter(c => !c.accepted).length);
});

test('public reader binds identity to one opening frontmatter name', async () => {
  const scratch = await mkdtemp(join(root, 'evidence', 'skills-identity-'));
  await mkdir(join(scratch, 'fm-tools'));
  let reader;
  registerSkillTool({ registerTool: value => { reader = value; } }, { root: scratch });
  for (const fixture of cases) {
    await writeFile(join(scratch, 'fm-tools', 'SKILL.md'), fixture.content);
    const result = await reader.execute(fixture.label, { id: 'fm-tools' });
    assert.equal(!result.isError, fixture.accepted, fixture.label);
    if (fixture.accepted) assert.equal(result.details.content, fixture.content);
    else {
      assert.equal(result.details.content, undefined, fixture.label);
      assert.equal(result.details.sha256, undefined, fixture.label);
    }
  }
});
