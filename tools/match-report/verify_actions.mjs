import {chromium} from 'playwright';
import {pathToFileURL} from 'node:url';
import {mkdir,writeFile,readFile} from 'node:fs/promises';
const [report,evidence]=process.argv.slice(2);await mkdir(evidence,{recursive:true});
const browser=await chromium.launch({headless:true,executablePath:'/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'});
const page=await browser.newPage({viewport:{width:1440,height:1100},acceptDownloads:true});const errors=[],requests=[];page.on('pageerror',e=>errors.push(String(e)));page.on('request',r=>{if(/^https?:/.test(r.url()))requests.push(r.url());});
await page.goto(pathToFileURL(report).href);await page.waitForFunction(()=>window.__REPORT_READY__,null,{timeout:7000});
const data=await page.evaluate(()=>window.__REPORT_DATA__);const panel=page.locator('#match-actions');
for(const side of data.pressure_evidence.sides){const card=panel.locator('.action-cards article').nth(side.side_index);if(!(await card.innerText()).includes(`${side.pressures_completed} completed / ${side.pressures_attempted} attempted`))throw Error('Pressure card counters wrong');}
await panel.scrollIntoViewIfNeeded();await panel.screenshot({path:evidence+'/pressing.png'});
await page.getByRole('spinbutton',{name:'Action minimum minutes'}).fill('60');if(await page.locator('#action-player-table tbody tr').count()!==data.players.filter(p=>p.minutes>=60).length)throw Error('Minutes filter wrong');
await page.getByRole('combobox',{name:'Action ranking',exact:true}).selectOption('rate');const ranked=data.players.filter(p=>p.minutes>=60).sort((a,b)=>(b.pressure_completion_percentage_computed??-Infinity)-(a.pressure_completion_percentage_computed??-Infinity)||a.name.localeCompare(b.name));if(!(await page.locator('#action-player-table tbody tr').first().innerText()).includes(ranked[0].name))throw Error('Rate sorting wrong');
await page.getByRole('button',{name:'Chance suppliers',exact:true}).click();await page.getByRole('spinbutton',{name:'Action minimum minutes'}).fill('0');
const checked=[];
for(const side of data.key_pass_evidence.sides){await page.getByRole('combobox',{name:'Action team',exact:true}).selectOption(String(side.side_index));for(const check of side.player_checks.filter(p=>p.official_key_passes>0)){
 await page.getByRole('combobox',{name:'Key-pass supplier',exact:true}).selectOption(String(check.person_native_id));
 const annotations=data.key_pass_evidence.annotations.filter(a=>a.side_index===side.side_index&&a.person_native_id===check.person_native_id);
 const pairs=side.supplied_pairs.filter(p=>p.from_person_native_id===check.person_native_id);const unknown=annotations.filter(a=>a.recipient_person_native_id==null).length;const expected=pairs.length+(unknown?1:0);
 const actual=await page.locator('#supplier-table tbody tr').count();if(actual!==expected)throw Error(`Supplier ${check.person_name}: expected ${expected} actual ${actual}`);
 if(!check.counts_match&&actual!==0)throw Error('Mismatched actor promoted');checked.push({name:check.person_name,official:check.official_key_passes,supported:annotations.length,known_recipient_events:pairs.reduce((n,p)=>n+p.key_pass_annotated_completed_pass_events,0),unknown_recipient_events:unknown,state:check.state});
}}
await page.getByRole('combobox',{name:'Action team',exact:true}).selectOption('both');await panel.screenshot({path:evidence+'/suppliers.png'});
const [download]=await Promise.all([page.waitForEvent('download'),page.getByRole('button',{name:/Download report data/}).click()]);await download.saveAs(evidence+'/downloaded-actions.json');const exported=JSON.parse(await readFile(evidence+'/downloaded-actions.json','utf8'));if(exported.players.length!==43||exported.pressure_evidence.raw_frame_sha256!==data.key_pass_evidence.raw_frame_sha256)throw Error('Download evidence mismatch');
await page.setViewportSize({width:390,height:844});await panel.screenshot({path:evidence+'/actions-mobile.png'});const overflow=await page.evaluate(()=>({width:innerWidth,body:document.documentElement.scrollWidth}));if(overflow.body>overflow.width+1)throw Error('Mobile page overflow');
if(errors.length||requests.length)throw Error(JSON.stringify({errors,requests}));const result={state:'passed',player_rows:data.players.length,pressure_sides:data.pressure_evidence.sides,creator_checks:checked,raw_frame_sha256:data.pressure_evidence.raw_frame_sha256,errors,network_requests:requests,mobile:overflow};await writeFile(evidence+'/actions-verification.json',JSON.stringify(result,null,2));console.log(JSON.stringify({state:result.state,checked_creators:checked.length,player_rows:result.player_rows}));await browser.close();
