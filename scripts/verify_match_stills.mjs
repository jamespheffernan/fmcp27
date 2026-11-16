// Dependency-free Chrome check for a completed match-stills packet.
import {spawn} from 'node:child_process';
import {mkdir, writeFile} from 'node:fs/promises';
import {resolve} from 'node:path';
import {pathToFileURL} from 'node:url';
import assert from 'node:assert/strict';

const [packetArg, evidenceArg] = process.argv.slice(2);
if (!packetArg || !evidenceArg) throw Error('Usage: node scripts/verify_match_stills.mjs PACKET EVIDENCE');
const packet = resolve(packetArg), evidence = resolve(evidenceArg);
await mkdir(evidence, {recursive:true});
const chrome = spawn('/Applications/Google Chrome.app/Contents/MacOS/Google Chrome', [
  '--headless', '--disable-gpu', '--no-first-run', '--no-default-browser-check',
  '--remote-debugging-port=0', `--user-data-dir=${evidence}/browser`, 'about:blank',
], {stdio:['ignore','ignore','pipe']});
let socket;
try {
  const endpoint = await new Promise((yes,no) => {
    const timer = setTimeout(()=>no(Error('Chrome startup timed out')), 20000);
    let output = '';
    chrome.stderr.on('data', chunk => {
      output += chunk.toString();
      const match = output.match(/DevTools listening on (ws:\/\/[^\s]+)/);
      if (match) {clearTimeout(timer);yes(match[1]);}
    });
    chrome.on('error', err=>{clearTimeout(timer);no(err);});
    chrome.on('exit', code=>{clearTimeout(timer);no(Error(`Chrome exited ${code}`));});
  });
  const base = new URL(endpoint);
  const target = await (await fetch(`http://${base.host}/json/new?about:blank`, {method:'PUT'})).json();
  socket = new WebSocket(target.webSocketDebuggerUrl);
  await new Promise((yes,no)=>{socket.onopen=yes;socket.onerror=no;});
  let sequence = 0;
  const pending = new Map();
  socket.onmessage = ({data}) => {
    const message = JSON.parse(data);
    if (!pending.has(message.id)) return;
    const {yes,no,timer} = pending.get(message.id);
    pending.delete(message.id);clearTimeout(timer);
    if (message.error) no(Error(JSON.stringify(message.error))); else yes(message.result);
  };
  const call = (method,params={}) => new Promise((yes,no)=>{
    const id=++sequence;
    const timer=setTimeout(()=>{pending.delete(id);no(Error(`${method} timed out`));},20000);
    pending.set(id,{yes,no,timer});socket.send(JSON.stringify({id,method,params}));
  });
  await call('Page.enable');
  const results=[];
  for (const [name,width,height] of [['desktop',1400,1100],['mobile',390,844]]) {
    await call('Emulation.setDeviceMetricsOverride',{width,height,deviceScaleFactor:1,mobile:name==='mobile'});
    await call('Page.navigate',{url:pathToFileURL(`${packet}/index.html`).href});
    const result=await call('Runtime.evaluate', {awaitPromise:true,returnByValue:true,expression:`(async()=>{
      if(document.readyState!=='complete') await new Promise(r=>window.addEventListener('load',r,{once:true}));
      await Promise.all([...document.images].map(i=>i.decode()));
      return {width:innerWidth,scrollWidth:document.documentElement.scrollWidth,
        images:[...document.images].map(i=>({width:i.naturalWidth,height:i.naturalHeight})),
        title:document.title, disclosure:document.body.innerText.includes('AI reconstruction')};
    })()`});
    assert(!result.exceptionDetails,JSON.stringify(result.exceptionDetails));
    const value=result.result.value;
    assert.equal(value.width,width);
    assert(value.scrollWidth<=width,`${name} overflows: ${value.scrollWidth}/${width}`);
    assert.equal(value.images.length,2);
    assert(value.images.every(i=>i.width>0&&i.height>0));
    assert(value.disclosure);
    const screenshot=await call('Page.captureScreenshot',{format:'png',captureBeyondViewport:false});
    await writeFile(`${evidence}/${name}.png`,Buffer.from(screenshot.data,'base64'));
    results.push({name,...value});
  }
  await writeFile(`${evidence}/verification.json`,JSON.stringify(results,null,2));
  console.log(JSON.stringify(results));
} finally {
  socket?.close();
  chrome.kill('SIGTERM');
}
