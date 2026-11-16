const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync(__dirname + '/../public/analytics.js','utf8');
function harness({hostname='fmcp27.com',optout=false,dnt=null,gpc=false,blocked=false}={}) {
 const events={},winEvents={}, scripts=[], calls=[],stored={}; let reloads=0;
 const button={addEventListener:(n,f)=>{button[n]=f;}},status={};
 const window={location:{hostname,reload(){reloads++;}},localStorage:{getItem(){if(blocked)throw Error();return optout?'1':null;},setItem(k,v){stored[k]=v;}},sessionStorage:{removeItem(){}},addEventListener(n,f){winEvents[n]=f;}};
 const document={getElementById(id){return id==='analytics-toggle'?button:status;},addEventListener(n,f){events[n]=f;},createElement(){return {setAttribute(k,v){this[k]=v;}};},head:{appendChild(s){scripts.push(s);}}};
 const context={window,document,navigator:{doNotTrack:dnt,globalPrivacyControl:gpc}};
 vm.runInNewContext(source,context);
 function click(extra={}){events.click?.({isTrusted:true,defaultPrevented:false,button:0,target:{closest:()=>({})},...extra});}
 return {window,button,status,scripts,calls,stored,events,winEvents,click,context,reloads:()=>reloads};
}
test('production loads one tracker; repeat initialization is idempotent',()=>{const h=harness();vm.runInNewContext(source,h.context);assert.equal(h.scripts.length,1);assert.equal(h.scripts[0].src,'https://lodd.dev/tracking/v1.js');});
test('preview, localhost, opt-out, unavailable storage and privacy signals do not load tracking',()=>{for(const options of [{hostname:'test.fmcp27.pages.dev'},{hostname:'localhost'},{optout:true},{dnt:'1'},{gpc:true},{blocked:true}])assert.equal(harness(options).scripts.length,0);});
test('one native download click queues one event without stopping navigation',()=>{const h=harness();h.click();assert.equal(h.window.ca.q.length,1);assert.equal(h.window.ca.q[0][0],'download_mac');assert.equal(h.window.ca.q[0][1].file,'FMCP27-mac.zip');});
test('synthetic, cancelled, right-button and unrelated clicks are excluded',()=>{const h=harness();h.click({isTrusted:false});h.click({defaultPrevented:true});h.click({button:2});h.click({target:{closest:()=>null}});assert.equal(h.window.ca.q.length,0);});
test('opt-out persists and reloads; another-tab change reloads too',()=>{const h=harness();h.button.click();assert.equal(h.stored['fmcp27.analytics-opt-out.v1'],'1');assert.equal(h.reloads(),1);h.winEvents.storage({key:'fmcp27.analytics-opt-out.v1'});assert.equal(h.reloads(),2);});
test('enabling analytics clears the opt-out',()=>{const h=harness({optout:true});h.button.click();assert.equal(h.stored['fmcp27.analytics-opt-out.v1'],'0');assert.equal(h.reloads(),1);});
