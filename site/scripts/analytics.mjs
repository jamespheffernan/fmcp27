#!/usr/bin/env node
// Read-only analytics CLI; the API credential stays outside the repository.
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import { spawn } from 'node:child_process';
const config=JSON.parse(await fs.readFile(path.join(os.homedir(),'.config/fmcp27/lodd.json'),'utf8'));
const command=process.argv[2] || 'summary';
if(command==='--mcp') {
  const child=spawn('npx',['-y','@lodd/mcp-server@0.1.18'],{stdio:'inherit',env:{...process.env,LODD_API_KEY:config.api_key}});
  child.on('exit',code=>process.exit(code??1));
} else {
  const days=Number(process.argv[3] || 7);
  if(!Number.isInteger(days)||days<1||days>365)throw Error('Days must be 1–365');
  const start=new Date(Date.now()-days*86400000).toISOString();
  const query=new URLSearchParams({start_date:start,end_date:new Date().toISOString(),timezone:'Europe/London'});
  async function get(endpoint){const r=await fetch('https://api.lodd.dev/v1/'+endpoint,{headers:{'X-API-Key':config.api_key}});const json=await r.json();if(!r.ok)throw Error(JSON.stringify(json.error));return json.data;}
  const base='sites/'+config.site_id+'/';
  if(command==='usage')console.log(JSON.stringify(await get('usage'),null,2));
  else if(command==='events')console.log(JSON.stringify(await get(base+'events?'+query+'&event_name=download_mac&limit=100'),null,2));
  else if(command==='summary'){
    const [analytics,downloads,sources,usage]=await Promise.all([get(base+'analytics?'+query),get(base+'event-counts?'+query),get(base+'source-conversions?'+query+'&event_name=download_mac'),get('usage')]);
    console.log(JSON.stringify({site:config.domain,period_days:days,analytics,events:downloads,download_sources:sources,usage,note:'download_mac counts button activations, not completed downloads or installations. Setup verification events are included on 2026-11-16.'},null,2));
  } else throw Error('Usage: node site/scripts/analytics.mjs [summary|events|usage|--mcp] [days]');
}
