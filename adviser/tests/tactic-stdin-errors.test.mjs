import assert from 'node:assert/strict';
import { mkdirSync, mkdtempSync, readFileSync, writeFileSync, symlinkSync, realpathSync, existsSync } from 'node:fs';
import { homedir, tmpdir } from 'node:os';
import { join } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { spawnSync } from 'node:child_process';
import { setTimeout as delay } from 'node:timers/promises';
import test from 'node:test';
import { runTacticFile, registerTacticFileTool } from '../pi/fm-tactic-files.mjs';

const root = fileURLToPath(new URL('../', import.meta.url));
const { Compile } = await import(pathToFileURL(join(homedir(),
  '.bun/install/global/node_modules/typebox/build/compile/index.mjs')).href);
let tool;
registerTacticFileTool({ registerTool: value => { tool = value; } });
const request = { action: 'list_templates', name: 'x'.repeat(2 * 1024 * 1024) };
assert.equal(Compile(tool.parameters).Check(request), true);
mkdirSync(join(root, 'evidence'), { recursive: true });

function executable(scratch, closeInput) {
  const path = join(scratch, 'owned-child.py');
  const pidFile = join(scratch, 'owned-child.pid');
  writeFileSync(path, '#!/usr/bin/python3\nimport os,signal,sys,time,json\n' +
    `open(${JSON.stringify(pidFile)},'w').write(str(os.getpid()))\n` +
    'signal.signal(signal.SIGTERM,signal.SIG_IGN)\n' +
    (closeInput ? 'os.close(0)\nsys.stdout.write(json.dumps({"fixture":"early-input-close"}));sys.stdout.flush()\n' : '') +
    'time.sleep(10)\n', { mode: 0o700 });
  return { path, pidFile };
}

function assertReaped(pidFile) {
  assert.ok(existsSync(pidFile), 'Owned child actually started before closing stdin');
  const pid = Number(readFileSync(pidFile, 'utf8'));
  assert.throws(() => process.kill(pid, 0), error => error.code === 'ESRCH', 'Input failure must reap the owned child');
}

test('large schema-valid input rejects safely through direct and registered calls and reaps a SIGTERM-ignoring child', async () => {
  const previous = process.env.PI_FM_TACTIC_PYTHON;
  try {
    for (const route of ['direct', 'registered']) {
      const scratch = mkdtempSync(join(root, 'evidence', `stdin-${route}-`));
      const fixture = executable(scratch, true);
      process.env.PI_FM_TACTIC_PYTHON = fixture.path;
      if (route === 'direct') {
        await assert.rejects(runTacticFile(request, AbortSignal.timeout(2000)), error =>
          error.code === 'EPIPE' && error.diagnostic === undefined);
      } else {
        const result = await tool.execute('early-close', request, AbortSignal.timeout(2000));
        assert.equal(result.isError, true);
        assert.equal(result.details.diagnostic, undefined);
        assert.match(result.content[0].text, /write EPIPE/);
      }
      assertReaped(fixture.pidFile);
    }
  } finally {
    if (previous === undefined) delete process.env.PI_FM_TACTIC_PYTHON;
    else process.env.PI_FM_TACTIC_PYTHON = previous;
  }
});

test('programmatic circular serialization fails before any child is spawned', async () => {
  const scratch = mkdtempSync(join(root, 'evidence', 'stdin-serialization-'));
  const fixture = executable(scratch, false);
  const previous = process.env.PI_FM_TACTIC_PYTHON;
  process.env.PI_FM_TACTIC_PYTHON = fixture.path;
  try {
    const circular = { action: 'list_templates' };
    circular.self = circular;
    await assert.rejects(runTacticFile(circular), /circular/i);
    const result = await tool.execute('circular-programmatic-call', circular);
    assert.equal(result.isError, true);
    assert.equal(result.details.diagnostic, undefined);
    await delay(100);
    assert.equal(existsSync(fixture.pidFile), false);
  } finally {
    if (previous === undefined) delete process.env.PI_FM_TACTIC_PYTHON;
    else process.env.PI_FM_TACTIC_PYTHON = previous;
  }
});

test('actual isolated Pi survives a registered2MiB input failure without an unhandled socket error', () => {
  const scratch = mkdtempSync(join(root, 'evidence', 'stdin-actual-pi-'));
  const fixture = executable(scratch, true);
  const provider = join(scratch, 'stdin-provider.pi.mjs');
  writeFileSync(provider, `
import {createAssistantMessageEventStream} from '@earendil-works/pi-ai';
export default function(pi){pi.registerProvider('stdin-fixture',{
 api:'stdin-fixture',baseUrl:'https://fixture.invalid',apiKey:'local-only',
 models:[{id:'offline',name:'Offline stdin fixture',reasoning:false,input:['text'],
 cost:{input:0,output:0,cacheRead:0,cacheWrite:0},contextWindow:2000000,maxTokens:4096}],
 streamSimple(model,context){const stream=createAssistantMessageEventStream();
 const output={role:'assistant',provider:model.provider,model:model.id,api:model.api,timestamp:Date.now(),
 stopReason:'pending',content:[],usage:{input:0,output:0,cacheRead:0,cacheWrite:0,totalTokens:0,
 cost:{input:0,output:0,cacheRead:0,cacheWrite:0,total:0}}};
 stream.push({type:'start',partial:output});
 if(!context.messages.some(m=>m.role==='toolResult')){
 const call={type:'toolCall',id:'stdin-call',name:'fm_tactic_file',arguments:{action:'list_templates',name:'x'.repeat(2097152)}};
 output.content.push(call);stream.push({type:'toolcall_start',contentIndex:0,partial:output});
 stream.push({type:'toolcall_end',contentIndex:0,toolCall:call,partial:output});output.stopReason='toolUse';
 }else{output.content.push({type:'text',text:'Controlled input failure returned.'});output.stopReason='stop';}
 stream.push({type:'done',reason:output.stopReason,message:output});stream.end();return stream;
 }});}
`);
  const home = realpathSync(mkdtempSync(join(tmpdir(), 'pi-fm-stdin-home-')));
  mkdirSync(join(home, '.agents'));
  symlinkSync(join(homedir(), '.agents/skills'), join(home, '.agents/skills'));
  const run = spawnSync(join(root, 'bin/pi-fm'), [
    '-e', provider, '--no-mcp', '--no-session', '--mode', 'json', '--print', 'Verify tactic tool input failure containment',
  ], { encoding: 'utf8', timeout: 10000, maxBuffer: 64 * 1024 * 1024, env: {
    ...process.env, HOME: home, PI_CODING_AGENT_DIR: join(scratch, '.pi/agent'), PI_FM_SESSION_DIR: join(scratch, 'sessions'),
    PI_FM_MODEL: 'stdin-fixture/offline', PI_FM_TACTIC_PYTHON: fixture.path, PI_OFFLINE: '1',
    PI_FM_MCP_LAUNCHER: join(root, 'tests/startup-reader-fixture.sh'), PI_FM_TEST_READER_DIR: scratch,
    PI_FM_TEST_FAILED_STARTS: '0', PI_FM_TEST_FIRST_DELAY: '0',
  } });
  writeFileSync(join(scratch, 'runtime.jsonl'), run.stdout);
  writeFileSync(join(scratch, 'stderr.txt'), run.stderr);
  assert.equal(run.status, 0, run.stderr || String(run.error));
  const events = run.stdout.trim().split('\n').map(line => JSON.parse(line));
  const call = events.find(e => e.type === 'tool_execution_end' && e.toolName === 'fm_tactic_file');
  assert.ok(call);
  assert.equal(call.isError, true);
  assert.equal(call.result.details.diagnostic, undefined);
  assert.match(call.result.content[0].text, /write EPIPE/);
  assert.ok(events.some(e => e.type === 'agent_settled'));
  assert.ok(!events.some(e => e.type === 'tool_execution_start' && e.toolName.startsWith('mcp__fm_live__')));
  assertReaped(fixture.pidFile);
});
