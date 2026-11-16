import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import test from 'node:test';
import { registerTacticFileTool } from '../pi/fm-tactic-files.mjs';
const codecPython='/Users/jamesheffernan/GitHub/FM26 Deepener/.venv/bin/python';
const nativePython='/Volumes/4TB Private/Offloaded/FMCP 27/.venv/bin/python';
const writer=fileURLToPath(new URL('../pi/fm-tactic-files.py',import.meta.url));
function run(python,file,args=[],input){
  const result=spawnSync(python,[fileURLToPath(new URL(file,import.meta.url)),...args],{encoding:'utf8',timeout:120000,input});
  assert.equal(result.status,0,result.stderr||String(result.error));
  return JSON.parse(result.stdout);
}
test('phase-position schema names source26 wide-midfield cases with same-format donor bounds',()=>{
  let tool;registerTacticFileTool({registerTool(value){tool=value;}});
  const field=tool.parameters.properties.phase_position;
  assert.equal(field.additionalProperties,false);
  assert.deepEqual(field.properties.phase.enum,['out_of_possession']);
  assert.deepEqual(field.properties.position_index.enum,[4,7,8]);
  assert.deepEqual(field.properties.donor_position_index.enum,[4,7,8]);
  assert.deepEqual(field.required,['phase','position_index','donor_template_path','donor_template_sha256','donor_position_index']);
  assert.match(field.description,/Source-format26 additionally supports OOP slot7 M\(R\) to AM\(R\) or slot8 M\(L\) to AM\(L\)/);
  assert.match(field.description,/Source\/donor formats must match; source version remains inherited/);
  assert.match(field.description,/reverse directions, no-ops and arbitrary position masks refuse/);
  assert.match(field.description,/game import remain unverified/);
});
test('finite source26 position payloads preserve other records and refuse full-phase or native drift',()=>{
  const result=run(codecPython,'./phase-position-26-memory.py',[writer]);
  assert.equal(result.actual_payload_positives,6);
  assert.ok(result.refusals>=227);
  assert.equal(result.native_spans,11);
  assert.equal(result.archive_fixtures_created,0);
  assert.equal(result.native_fixture_files_created,0);
  assert.equal(result.game_import_verified,false);
});
test('original creator setter and serializer reproduce four source26 native transitions',()=>{
  const rows=run(nativePython,'./phase-position-26-native.py');
  assert.equal(rows.length,4);
  assert.deepEqual(rows.map(row=>[row.preconverted_slot,row.slot]),[[null,7],[null,8],[7,8],[8,7]]);
  for(const row of rows){
    assert.equal(row.native_result,1);assert.equal(row.native_stop,'0x100500300');
    assert.ok(row.original_setter_instructions>=6000);assert.equal(row.original_serializer_instructions,2050);
    assert.equal(row.OOP_reconciliation_calls,13);assert.equal(row.matches_donor,true);
    assert.equal(row.serialized_record_matches_donor,true);assert.equal(row.creator_outside_target_record_unchanged,true);
    assert.equal(row.patched_22_records_match,true);assert.equal(row.patched_full_native_loader.accepted,true);
    assert.equal(row.patched_full_native_loader.consumed_exact_eof,true);
    assert.deepEqual(row.changed_records,[`out_of_possession:${row.slot}`]);
    assert.equal(row.error,null);assert.equal(row.serializer_error,null);assert.equal(row.native_live_calls,false);
    assert.equal(row.game_reads,false);assert.equal(row.game_import_verified,false);
  }
});
test('real source26 position archives compose with independent edits and pass original full-body native readback',()=>{
  const result=run(codecPython,'./phase-position-26-files.py',[writer]);
  assert.equal(result.artifacts.length,6);assert.ok(result.public_refusals>=15);
  assert.equal(result.records_preserved_per_single_edit,21);assert.equal(result.native_fixture_files_created,0);
  const rows=run(nativePython,'./phase-position-loader.py',[],JSON.stringify(result.artifacts));
  assert.equal(rows.length,6);
  for(const row of rows){assert.equal(row.native_body_accepted,true);assert.equal(row.records_compared,22);assert.equal(row.all_primary_PI_vectors_match,true);assert.equal(row.game_import_verified,false);}
});
