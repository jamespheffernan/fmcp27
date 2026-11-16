import assert from 'node:assert/strict';
import {mkdirSync,mkdtempSync,readFileSync,writeFileSync,symlinkSync} from 'node:fs';
import {gunzipSync} from 'node:zlib';
import {homedir} from 'node:os';
import {join} from 'node:path';
import {fileURLToPath,pathToFileURL} from 'node:url';
import {spawnSync} from 'node:child_process';
import test from 'node:test';
import {registerSkillTool} from '../pi/fm-skills.mjs';
const root=fileURLToPath(new URL('../',import.meta.url));
const fixturePath=join(root,'tests/fixtures/retained-shot-fallback.json.gz');
const fixture=JSON.parse(gunzipSync(readFileSync(fixturePath)));
const {Compile}=await import(pathToFileURL(join(homedir(),'.bun/install/global/node_modules/typebox/build/compile/index.mjs')).href);
const input=Compile(fixture.input_schema);

test('approved guide reader exposes exact qualified fallback without changing source defaults',async()=>{
 let reader;registerSkillTool({registerTool:t=>{reader=t;}});
 const guides={};
 for(const id of ['fm-tools','fm-live-investigation','fm-tactical-analysis']){
  const r=await reader.execute(id,{id});assert.ok(!r.isError);guides[id]=r.details.content;
  assert.equal(guides[id],readFileSync(join(root,'skills',id,'SKILL.md'),'utf8'));
 }
 const source=guides['fm-live-investigation'];
 for(const token of ['include_source_observed: true','available_source_observed_counts_verified_xg_unreconciled','source_observed_shots_truncated','verified_shots_promoted: false','xg_tolerance_widened: false','native_expected_goals','own_goal_markers'])assert.ok(source.includes(token),token);
 assert.ok(guides['fm-tools'].includes('include_source_observed: true'));
 assert.ok(guides['fm-tactical-analysis'].includes('qualified retained-shot fallback'));
 const request={session_id:'offline-packet',fixture_ref:fixture.strict.fixture_ref,include_source_observed:true,offset:0,limit:100};
 assert.ok(input.Check(request));assert.equal(input.Check({...request,include_source_observed:'true'}),false);
 assert.equal(fixture.input_schema.properties.include_source_observed.default,false);
});

test('actual isolated Pi CodeMode reaches genuine qualified rows while preserving strict xG',()=>{
 mkdirSync(join(root,'evidence'),{recursive:true});const scratch=mkdtempSync(join(root,'evidence/shot-fallback-'));
 mkdirSync(join(scratch,'.agents'));symlinkSync(join(homedir(),'.agents/skills'),join(scratch,'.agents/skills'));
 const code=`for (const id of ["fm-tools","fm-live-investigation","fm-tactical-analysis"]) await tools.fm_read_skill({id});
const args={session_id:"offline-packet",fixture_ref:${JSON.stringify(fixture.strict.fixture_ref)},offset:0,limit:100};
const first=JSON.parse(await tools.mcp__fm_live__fm_get_retained_shot_map(args));
const side=first.side_coverage.find(s=>s.side_index===0);
if(side.link_errors.length || !side.checks.shot_count_matches || !side.checks.shots_on_target_matches || side.checks.xg_sum_within_one_float32_ulp) throw new Error("Wrong fallback condition");
const p=JSON.parse(await tools.mcp__fm_live__fm_get_retained_shot_map({...args,include_source_observed:true,expected_source_id:first.source_id}));
const coverage=p.source_observed_coverage.find(s=>s.side_index===0);
if(coverage.state!=="available_source_observed_counts_verified_xg_unreconciled" || coverage.verified_shots_promoted || coverage.xg_tolerance_widened || p.source_observed_shots_truncated || p.source_id!==first.source_id) throw new Error("Unqualified or changed source");
text({strict_rows:p.shots.length,observed_rows:p.source_observed_shots.length,own_goal_markers:p.own_goal_markers.length,strict_home_xg:p.side_coverage[0].expected_goals,official_home_xg:p.side_coverage[0].official_expected_goals,ulps:p.side_coverage[0].xg_float32_ulp_distance,observed_fields_unpromoted:p.source_observed_shots.every(s=>!("expected_goals"in s)&&s.verification_scope==="source_observed_counts_actors_verified_xg_unreconciled"),canonical_actors:p.source_observed_shots.every(s=>s.actor?.canonical_person_id),observed_truncated:p.source_observed_shots_truncated});`;
 let provider=readFileSync(join(root,'tests/papercut-provider.pi.ts'),'utf8');
 const injection=`\n  const packet=JSON.parse(require("node:zlib").gunzipSync(require("node:fs").readFileSync(${JSON.stringify(fixturePath)})));\n  pi.registerTool({name:"mcp__fm_live__fm_get_retained_shot_map",label:"Offline genuine packet",description:"Fixed historical packet fixture; no game access",annotations:{readOnlyHint:true},parameters:packet.input_schema,async execute(_id,args){if(args.session_id!=="offline-packet"||args.fixture_ref!==packet.strict.fixture_ref)throw new Error("Fixture identity differs");const p=args.include_source_observed?packet.qualified:packet.strict;return {content:[{type:"text",text:JSON.stringify(p)}],details:p};}});\n`;
 provider=provider.replace('export default function fixture(pi: ExtensionAPI) {','export default function fixture(pi: ExtensionAPI) {'+injection);
 provider=provider.replace('args = { code: `text(await tools.fm_tactic_file(${JSON.stringify(args)}));` };',`args = { code: ${JSON.stringify(code)} };`);
 const providerPath=join(scratch,'provider.pi.ts');writeFileSync(providerPath,provider);
 const run=spawnSync(join(root,'bin/pi-fm'),['-e',providerPath,'--no-mcp','--mode','json','--print','Offline qualified retained-shot fallback only'],{encoding:'utf8',timeout:30000,maxBuffer:8*1024*1024,env:{...process.env,HOME:scratch,PI_CODING_AGENT_DIR:join(scratch,'.pi/agent'),PI_FM_SESSION_DIR:join(scratch,'sessions'),PI_FM_MODEL:'papercut-fixture/offline',PI_FM_TEST_ROUTE:'tactic-codemode',PI_OFFLINE:'1',PI_FM_MCP_LAUNCHER:join(root,'tests/startup-reader-fixture.sh'),PI_FM_TEST_READER_DIR:scratch,PI_FM_TEST_FAILED_STARTS:'0',PI_FM_TEST_FIRST_DELAY:'0'}});
 writeFileSync(join(scratch,'runtime.jsonl'),run.stdout||'');writeFileSync(join(scratch,'stderr.txt'),run.stderr||'');assert.equal(run.status,0,run.stderr||String(run.error));
 const events=run.stdout.trim().split('\n').map(JSON.parse),ends=events.filter(e=>e.type==='tool_execution_end');
 const calls=events.filter(e=>e.type==='tool_execution_start'&&e.toolName==='mcp__fm_live__fm_get_retained_shot_map');
 assert.equal(calls.length,2);assert.ok(!calls[0].args.include_source_observed);assert.equal(calls[1].args.include_source_observed,true);
 for(const c of calls)assert.ok(input.Check(c.args));
 const outer=ends.find(e=>e.toolName==='codemode');assert.ok(outer&&!outer.isError,JSON.stringify(outer));
 const row=outer.result.content.flatMap(b=>(b.text||'').split('\n')).find(s=>s.startsWith('{"strict_rows"'));
 const summary=JSON.parse(row);assert.deepEqual(summary,{strict_rows:11,observed_rows:6,own_goal_markers:1,strict_home_xg:null,official_home_xg:1.4353783130645752,ulps:3,observed_fields_unpromoted:true,canonical_actors:true,observed_truncated:false});
 assert.equal(ends.filter(e=>e.toolName==='fm_read_skill'&&!e.isError).length,3);
 assert.ok(!events.some(e=>e.type==='tool_execution_start'&&e.toolName.startsWith('mcp__fm_live__')&&e.toolName!=='mcp__fm_live__fm_get_retained_shot_map'));
});
