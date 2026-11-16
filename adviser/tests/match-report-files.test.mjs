import assert from 'node:assert/strict';
import {mkdtemp,mkdir,writeFile,chmod,symlink} from 'node:fs/promises';
import {join} from 'node:path';
import {tmpdir} from 'node:os';
import test from 'node:test';
import {registerMatchReportTool,MATCH_REPORT_TOOL} from '../pi/fm-match-report.mjs';

async function root(){return await mkdtemp(join(tmpdir(),'pi-match-report-'));}
async function withLauncher(directory,call){const old=process.env.PI_FM_MCP_LAUNCHER;process.env.PI_FM_MCP_LAUNCHER=join(directory,'run_mcp.sh');try{return await call();}finally{if(old===undefined)delete process.env.PI_FM_MCP_LAUNCHER;else process.env.PI_FM_MCP_LAUNCHER=old;}}
function fixture(){const tools=[];registerMatchReportTool({registerTool:t=>tools.push(t)});return tools;}
test('report is unavailable until its fixed regular backend exists',async()=>{const directory=await root();await withLauncher(directory,async()=>{assert.deepEqual(fixture(),[]);});});
test('a symlink does not activate the backend',async()=>{const directory=await root();await writeFile(join(directory,'target.sh'),'exit 0');await symlink(join(directory,'target.sh'),join(directory,'run_match_report.sh'));await withLauncher(directory,async()=>{assert.deepEqual(fixture(),[]);});});
test('report schema exposes selectors and no source bodies or output paths',async()=>{const directory=await root();await writeFile(join(directory,'run_match_report.sh'),'exit 0');await withLauncher(directory,async()=>{const[tool]=fixture();assert.equal(tool.name,MATCH_REPORT_TOOL);assert.equal(tool.parameters.additionalProperties,false);for(const key of ['path','output','html','raw_source','fixture_ref','session_id'])assert.equal(tool.parameters.properties[key],undefined);assert.deepEqual(tool.parameters.properties.source.enum,['retained','captured','observed']);});});
test('fixed backend receives JSON only and unsuccessful receipts stay errors',async()=>{const directory=await root();await writeFile(join(directory,'run_match_report.sh'),`/usr/bin/python3 -c 'import sys,json; p=json.load(sys.stdin); print(json.dumps({"state":"ready","source":p}))'\n`);await withLauncher(directory,async()=>{const[tool]=fixture();const params={source:'captured',source_id:'selected',capture_id:'a'.repeat(64),fixture_id:'exact'};const result=await tool.execute('id',params);assert.deepEqual(result.details.source,params);assert.equal(result.isError,undefined);await writeFile(join(directory,'run_match_report.sh'),`printf '%s' '{"state":"unavailable","error":"Source pin changed"}'\nexit 1\n`);const failed=await tool.execute('id',params);assert.equal(failed.isError,true);assert.match(failed.content[0].text,/Source pin changed/);});});

test('publication failures preserve unknown and confirmed absent artifact states', async () => {
 const directory = await root();
 const backend = join(directory, 'run_match_report.sh');
 const receipt = {state:'unavailable', error:'Publication was attempted', artifact_created:null};
 await writeFile(backend, "printf '%s' '" + JSON.stringify(receipt) + "'\nexit 1\n");
 await withLauncher(directory, async () => {
  const [tool] = fixture();
  const params = {source:'captured', source_id:'selected', capture_id:'a'.repeat(64), fixture_id:'exact'};
  const unknown = await tool.execute('unknown', params);
  assert.equal(unknown.isError, true);
  assert.equal(unknown.details.artifact_created, null);
  receipt.artifact_created = false;
  receipt.error = 'Selection failed before publication';
  await writeFile(backend, "printf '%s' '" + JSON.stringify(receipt) + "'\nexit 1\n");
  const absent = await tool.execute('absent', params);
  assert.equal(absent.isError, true);
  assert.equal(absent.details.artifact_created, false);
 });
});

test('safe requested filename reaches fixed backend; unsafe leaves never dispatch',async()=>{
 const directory=await root();
 await writeFile(join(directory,'run_match_report.sh'),`/usr/bin/python3 -c 'import sys,json; p=json.load(sys.stdin); print(json.dumps({"state":"ready","source":p}))'\n`);
 await withLauncher(directory,async()=>{
  const[tool]=fixture();
  assert.equal(tool.parameters.properties.filename.type,'string');
  const params={source:'captured',source_id:'selected',capture_id:'a'.repeat(64),fixture_id:'exact',filename:'2026-11-09 — Newcastle Liverpool match report.html'};
  const result=await tool.execute('named',params);
  assert.equal(result.details.source.filename,params.filename);
  for(const filename of [null,true,'','.html','../report.html','/report.html','dir/report.html','dir\\report.html','report:other.html','report.htm',' report.html','report.html ','a\n.html','a\0.html','a\u0085.html','a\u2028.html','a\u202e.html','é'.repeat(123)+'.html']){
   const refused=await tool.execute('bad',{...params,filename});
   assert.equal(refused.isError,true,String(filename));
   assert.match(refused.content[0].text,/safe HTML filename/);
   assert.equal(refused.details.artifact_created,null);
  }
 });
});
