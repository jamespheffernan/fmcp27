import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { mkdtempSync, mkdirSync, readFileSync, symlinkSync, writeFileSync } from 'node:fs';
import { homedir } from 'node:os';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';
import test from 'node:test';
import { childFailure } from './child-result.mjs';

const root=fileURLToPath(new URL('../',import.meta.url));
const guard=join(root,'tests/offline-reader-launch-guard.cjs');
const realLauncher='/Volumes/4TB Private/Offloaded/FMCP 27/scripts/run_mcp.sh';

for(const explicitFixture of [false,true]){
 test(`--no-mcp still registers programmatic reader; explicit fixture=${explicitFixture}`,()=>{
  mkdirSync(join(root,'tmp'),{recursive:true});
  const scratch=mkdtempSync(join(root,'tmp','reader-launch-'));
  mkdirSync(join(scratch,'.agents'));
  symlinkSync(join(homedir(),'.agents/skills'),join(scratch,'.agents/skills'));
  const trace=join(scratch,'launches.jsonl');
  const env={...process.env,HOME:scratch,PI_CODING_AGENT_DIR:join(scratch,'.pi/agent'),PI_FM_SESSION_DIR:join(scratch,'sessions'),
   PI_FM_MODEL:'papercut-fixture/offline',PI_OFFLINE:'1',PI_FM_TEST_ROUTE:'reader',PI_FM_TEST_READER_DIR:scratch,
   PI_FM_TEST_FAILED_STARTS:'0',PI_FM_TEST_FIRST_DELAY:'0',PI_FM_TEST_PROCESS_TRACE:trace,
   NODE_OPTIONS:`${process.env.NODE_OPTIONS||''} --require=${JSON.stringify(guard)}`};
  delete env.PI_FM_MCP_LAUNCHER;
  if(explicitFixture)env.PI_FM_MCP_LAUNCHER=join(root,'tests/startup-reader-fixture.sh');
  const result=spawnSync(join(root,'bin/pi-fm'),['-e',join(root,'tests/papercut-provider.pi.ts'),'--no-mcp','--no-session','--mode','json','--print','Offline reader routing control'],
   {encoding:'utf8',timeout:30000,maxBuffer:4*1024*1024,env});
  writeFileSync(join(scratch,'offline-routing.jsonl'),result.stdout);
  writeFileSync(join(scratch,'offline-routing.stderr'),result.stderr);
  assert.equal(result.status,0,childFailure(result,`programmatic reader control; explicit fixture=${explicitFixture}`));
  const launches=readFileSync(trace,'utf8').trim().split('\n').map(JSON.parse);
  const denied=launches.filter(row=>row.denied);
  const events=result.stdout.trim().split('\n').map(JSON.parse);
  const status=events.find(e=>e.type==='tool_execution_end'&&e.toolName==='mcp__fm_live__fm_status');
  if(explicitFixture){
   assert.equal(denied.length,0,JSON.stringify(denied));
   assert.ok(launches.some(row=>row.command==='/bin/sh'&&row.args.includes(env.PI_FM_MCP_LAUNCHER)));
   const requests=readFileSync(join(scratch,'requests.jsonl'),'utf8').trim().split('\n').map(JSON.parse);
   assert.equal(requests.filter(row=>row.method==='initialize').length,1);
   // The harness's own fm_attach before the first model call (pi/fm-reader-session.mjs), then the model's read.
   assert.deepEqual(requests.filter(row=>row.method==='tools/call').map(row=>row.name),['fm_attach','fm_status']);
   assert.ok(status&&!status.isError);
  }else{
   assert.ok(denied.length>=1);
   assert.ok(denied.every(row=>row.command==='/bin/sh'&&row.args.includes(realLauncher)));
   assert.equal(status,undefined);
   assert.ok(events.some(e=>e.type==='message_end'&&e.message.customType==='fm-reader-unavailable'));
  }
 });
}

test('preload denies helper and game process commands before creating any child',()=>{
 mkdirSync(join(root,'tmp'),{recursive:true});
 const scratch=mkdtempSync(join(root,'tmp','guard-controls-'));
 const trace=join(scratch,'launches.jsonl');
 const script=`const c=require('node:child_process');for(const path of ${JSON.stringify([realLauncher,'/fixture/build/fm_live_helper','/fixture/Football Manager 27','/fixture/Football Manager 27.app/Contents/MacOS/fm','/fixture/fm'])}){try{c.spawnSync(path,[]);throw Error('guard did not refuse')}catch(e){if(e.code!=='OFFLINE_REAL_READER_LAUNCH_DENIED')throw e}}`;
 const result=spawnSync(process.execPath,['-e',script],{encoding:'utf8',env:{...process.env,PI_FM_TEST_PROCESS_TRACE:trace,NODE_OPTIONS:`--require=${JSON.stringify(guard)}`}});
 assert.equal(result.status,0,childFailure(result,'denied launcher/helper/game controls'));
 const launches=readFileSync(trace,'utf8').trim().split('\n').map(JSON.parse);
 assert.equal(launches.length,5);assert.ok(launches.every(row=>row.denied));
});
