import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import { writeFileSync } from 'node:fs';
import test from 'node:test';
import { registerTacticFileTool } from '../pi/fm-tactic-files.mjs';
test('final-third delivery schema preserves inheritance and exact native choices', () => {
  let tool; registerTacticFileTool({registerTool(t){tool=t;}});
  assert.deepEqual(tool.parameters.properties.final_third_delivery.enum,['No explicit selection','Hit Early Crosses','Work Ball Into Box']);
  assert.ok(!tool.parameters.required.includes('final_third_delivery'));
});
test('final-third delivery generates real archives, preserves roles and rejects changed sources', () => {
  const r=spawnSync('/Users/jamesheffernan/GitHub/FM26 Deepener/.venv/bin/python',[fileURLToPath(new URL('./final-third-files.py',import.meta.url)),fileURLToPath(new URL('../pi/fm-tactic-files.py',import.meta.url))],{encoding:'utf8',timeout:180000});
  assert.equal(r.status,0,r.stderr||String(r.error));
  const v=JSON.parse(r.stdout); assert.ok(v.templates_checked>=9); assert.ok(v.artifacts.length>=28); assert.ok(v.negative_controls>=48);
  assert.deepEqual(Object.keys(v.changed_fm27).sort(),['Hit Early Crosses','No explicit selection','Work Ball Into Box']);
  assert.equal(v.native_spans,12); assert.equal(v.game_import_verified,false);
  writeFileSync(new URL('../evidence/tactic-final-third-20261109/artifacts.json',import.meta.url),JSON.stringify(v,null,2)+'\n');
});
