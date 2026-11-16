import {chromium} from 'playwright';
import {pathToFileURL} from 'node:url';
import {mkdir,writeFile,readFile} from 'node:fs/promises';
const [report,evidence]=process.argv.slice(2);await mkdir(evidence,{recursive:true});
const browser=await chromium.launch({headless:true,executablePath:'/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'});
const page=await browser.newPage({viewport:{width:1440,height:1080}});const errors=[],requests=[];
page.on('pageerror',e=>errors.push(String(e)));page.on('request',r=>{if(/^https?:/.test(r.url()))requests.push(r.url());});
await page.goto(pathToFileURL(report).href);await page.waitForFunction(()=>window.__REPORT_READY__===true,null,{timeout:10000});
const data=await page.evaluate(()=>window.__REPORT_DATA__);const source=data.pass_event_locations;
if(source.state!=='verified_complete_counter_reconciled_pass_event_locations'||source.points.length!==945)throw Error('Missing complete 945-event proof');
if(!data.pressure_evidence||!data.key_pass_evidence||data.players.length!==43||data.shots.length!==17||data.source_observed_shots.length!==10)throw Error('Existing Lille layers missing');
const panel=page.locator('#pass-event-map');const checked=[];
const select=(label,value)=>panel.getByRole('combobox',{name:label,exact:true}).selectOption(String(value));
async function verify(side,person='all',outcome='all',zone='all',channel='all'){
 const population=source.points.filter(p=>(side==='both'||p.side_index===Number(side))&&(person==='all'||p.person_native_id===Number(person)));
 const third=p=>p.inside_native_pitch_extents?p.analytical_pitch_third:'outside';
 const rows=population.filter(p=>(zone==='all'||third(p)===zone)&&(channel==='all'||(p.analytical_lateral_channel||'unknown')===channel));
 const shown=rows.filter(p=>outcome==='all'||p.completed===(outcome==='completed'));const plotted=shown.filter(p=>p.inside_native_pitch_extents);
 const stats=await panel.locator('[data-pass-stat]').allTextContents();
 const completed=rows.filter(p=>p.completed).length;const expected=[String(rows.length),String(completed),String(rows.length-completed),rows.length?(100*completed/rows.length).toFixed(1)+'%':'—'];
 if(JSON.stringify(stats)!==JSON.stringify(expected))throw Error(`Stats mismatch ${JSON.stringify({side,person,outcome,zone,channel,stats,expected})}`);
 if(await panel.locator('.pass-location-point').count()!==plotted.length)throw Error('Plotted count mismatch');
 const coverage=await panel.locator('#pass-location-coverage').innerText();if(!coverage.includes(`${shown.length} events`)||!coverage.includes(`${plotted.length} in-pitch points`))throw Error('Coverage mismatch');
 checked.push({side,person,outcome,zone,channel,attempts:rows.length,completed,plotted:plotted.length,outside:shown.length-plotted.length});return shown;
}
for(const side of ['0','1']){
 await select('Pass-map team',side);await select('Pass-map player','all');await select('Pass-map outcome','all');await select('Pass-map pitch third','all');await select('Pass-map channel','all');await verify(side);
 for(const p of data.players.filter(p=>p.side===Number(side))){await select('Pass-map player',p.id);await verify(side,String(p.id));}
 await select('Pass-map player','all');
 for(const outcome of ['completed','incomplete','all']){await select('Pass-map outcome',outcome);await verify(side,'all',outcome);}
 for(const zone of ['defensive','middle','attacking','outside']){await select('Pass-map pitch third',zone);await verify(side,'all','all',zone);}
 await select('Pass-map pitch third','all');for(const ch of ['central','outer','unknown','all']){await select('Pass-map channel',ch);await verify(side,'all','all','all',ch);}
}
await select('Pass-map team','both');await verify('both');
const first=source.points.find(p=>p.inside_native_pitch_extents);await select('Inspect pass event',first.event_id);
if(await panel.locator('[data-selected-pass-event]').getAttribute('data-selected-pass-event')!==String(first.event_id))throw Error('Keyboard event inspection mismatch');
await select('Pass-map team','0');await select('Pass-map pitch third','outside');const outside=await verify('0','all','all','outside');
if(outside.length!==1||await panel.locator('.pass-location-point').count()!==0)throw Error('Outside event was moved onto pitch');
await select('Inspect pass event',outside[0].event_id);if(!await panel.locator('.pass-location-aside').innerText().then(s=>s.includes('Outside pitch')))throw Error('Outside event is not inspectable');
await panel.getByRole('button',{name:'Reset pass filters'}).click();await select('Pass-map team','1');await select('Pass-map outcome','incomplete');await verify('1','all','incomplete');await panel.screenshot({path:evidence+'/newcastle-incomplete.png'});
await page.setViewportSize({width:390,height:844});await panel.screenshot({path:evidence+'/mobile.png'});const overflow=await page.evaluate(()=>({width:innerWidth,body:document.documentElement.scrollWidth}));if(overflow.body>overflow.width+1)throw Error('Mobile overflow');
const exported=await page.evaluate(()=>JSON.parse(window.__REPORT_EXPORT_JSON__));if(exported.pass_event_locations.points.length!==945||exported.pressure_evidence.raw_frame_sha256!==source.raw_frame_sha256||exported.key_pass_evidence.raw_frame_sha256!==source.raw_frame_sha256)throw Error('Export source/frame mismatch');
if(errors.length||requests.length)throw Error(JSON.stringify({errors,requests}));
const result={state:'passed',checked_filter_states:checked.length,player_rows_checked:43,source_points:945,side_coverage:source.side_coverage,errors,network_requests:requests,mobile:overflow};await writeFile(evidence+'/verification.json',JSON.stringify(result,null,2));console.log(JSON.stringify(result));await browser.close();
