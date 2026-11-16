import {chromium} from 'playwright';
import {pathToFileURL,fileURLToPath} from 'node:url';
import {mkdir,writeFile,stat,readFile} from 'node:fs/promises';
const report = process.argv[2];
const evidence = process.argv[3];
await mkdir(evidence,{recursive:true});
const browser = await chromium.launch({headless:true,executablePath:'/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'});
const context=await browser.newContext({viewport:{width:1440,height:1100},acceptDownloads:true});
const page=await context.newPage();const errors=[],requests=[];
page.on('pageerror',error=>errors.push(String(error)));
page.on('request',r=>requests.push(r.url()));
const started=Date.now();await page.goto(pathToFileURL(report).href);await page.waitForFunction(()=>window.__REPORT_READY__===true,null,{timeout:7000});
const metrics=await page.evaluate(()=>({decode_ms:window.__REPORT_DECODE_MS__,render_ms:window.__REPORT_RENDER_MS__,shot_count:window.__REPORT_DATA__.shots.length,player_rows:window.__REPORT_DATA__.players.length,average_nodes:window.__REPORT_DATA__.average_nodes.length}));
await page.screenshot({path:evidence+'/desktop.png',fullPage:true});
const tests=[];
for(const name of ['Pass network','Average positions','Heat map','Shot map']){
 await page.getByRole('button',{name,exact:true}).click();await page.waitForTimeout(80);if(await page.locator('#match-pitch').count()!==1)throw new Error('Pitch disappeared in '+name);if(name==='Heat map'&&await page.locator('#match-pitch rect').count()<100)throw new Error('Default clean heatmap is empty');tests.push({view:name,svg:await page.locator('#match-pitch').count(),text:(await page.locator('.details').innerText()).slice(0,400)});
}
const expected=await page.evaluate(()=>({shots:window.__REPORT_DATA__.shots,players:window.__REPORT_DATA__.players.length,halves:window.__REPORT_DATA__.half_split_available!==false,attempts:window.__REPORT_DATA__.pass_attempt_coverage?.attempt_count}));
if(expected.halves){
 await page.getByRole('combobox',{name:'Period',exact:true}).selectOption('FirstHalf');
 await page.waitForFunction(n=>document.querySelectorAll('#match-pitch .shot').length===n,expected.shots.filter(s=>s.side===0&&s.period==='FirstHalf').length);
 const first=await page.locator('#match-pitch .shot').count();if(first!==expected.shots.filter(s=>s.side===0&&s.period==='FirstHalf').length)throw new Error('First-half home shots mismatch');
 await page.getByRole('combobox',{name:'Team',exact:true}).first().selectOption('both');
 await page.waitForFunction(n=>document.querySelectorAll('#match-pitch .shot').length===n,expected.shots.filter(s=>s.period==='FirstHalf').length);
 if(await page.locator('#match-pitch .shot').count()!==expected.shots.filter(s=>s.period==='FirstHalf').length)throw new Error('First-half total mismatch');
 await page.getByRole('combobox',{name:'Period',exact:true}).selectOption('SecondHalf');
 await page.waitForFunction(n=>document.querySelectorAll('#match-pitch .shot').length===n,expected.shots.filter(s=>s.period==='SecondHalf').length);
 if(await page.locator('#match-pitch .shot').count()!==expected.shots.filter(s=>s.period==='SecondHalf').length)throw new Error('Second-half total mismatch');
}else{
 if(await page.getByRole('combobox',{name:'Period',exact:true}).locator('option').count()!==1)throw new Error('Unverified half filters exposed');
 if(!await page.getByText('Half-by-half statistics are unavailable.',{exact:false}).count())throw new Error('Missing period limitation');
}
if(await page.getByRole('checkbox',{name:/Include .* source-observed attempts/}).count()){
 await page.getByRole('combobox',{name:'Team',exact:true}).first().selectOption('both');
 await page.getByRole('checkbox',{name:/Include .* source-observed attempts/}).check();
 const observedCount=await page.evaluate(()=>window.__REPORT_DATA__.source_observed_shots.length);
 if(await page.locator('#match-pitch .shot').count()!==expected.shots.length+observedCount)throw new Error('Observed lane toggle count mismatch');
 await page.screenshot({path:evidence+'/observed-shots.png',fullPage:false});
 await page.getByRole('checkbox',{name:/Include .* source-observed attempts/}).uncheck();
}
const [download]=await Promise.all([page.waitForEvent('download'),page.getByRole('button',{name:/Download report data/}).click()]);await download.saveAs(evidence+'/downloaded-report-data.json');const exported=JSON.parse(await readFile(evidence+'/downloaded-report-data.json','utf8'));if(exported.shots.length!==expected.shots.length||exported.players.length!==expected.players)throw new Error('Downloaded JSON data mismatch');if(exported.players.some(p=>p.rating_state!=='qualified'&&p.match_rating!==null))throw new Error('Unqualified ratings were rendered as values');if(exported.pass_attempt_coverage?.attempt_count!==expected.attempts)throw new Error('Attempt coverage mismatch');
await page.getByRole('button',{name:'Average positions',exact:true}).click();await page.getByRole('combobox',{name:'Possession phase',exact:true}).selectOption('in_possession');await page.getByRole('combobox',{name:'Tracking coverage',exact:true}).selectOption('unpadded');
await page.screenshot({path:evidence+'/averages.png',fullPage:false});
await page.getByRole('button',{name:'Compare both teams side by side',exact:true}).click();if(await page.locator('.paired-pitches article').count()!==2)throw new Error('Paired team comparison missing');await page.locator('.paired-pitches').screenshot({path:evidence+'/paired-averages.png'});
await page.getByRole('button',{name:'Hide paired comparison',exact:true}).click();
await page.getByRole('combobox',{name:'Sort by',exact:true}).selectOption('possession_lost');if(await page.locator('#player-table tbody tr').count()!==expected.players)throw new Error('Full player table missing rows');
await page.getByText('All available numeric team fields',{exact:true}).click();
await page.getByRole('button',{name:'Heat map',exact:true}).click();await page.getByRole('combobox',{name:'Period',exact:true}).selectOption('Full');await page.locator('#match-pitch').focus();await page.keyboard.press('ArrowRight');if(!(await page.locator('.pitch-status').innerText()).includes('intensity'))throw new Error('Heatmap keyboard inspection failed');await page.screenshot({path:evidence+'/heatmap.png',fullPage:false});
await page.getByRole('button',{name:'Compare both teams side by side',exact:true}).click();await page.locator('.paired-pitches').screenshot({path:evidence+'/paired-heat.png'});await page.getByRole('button',{name:'Hide paired comparison',exact:true}).click();
await page.setViewportSize({width:390,height:844});await page.getByRole('combobox',{name:'Pitch zoom',exact:true}).selectOption('3');await page.getByRole('button',{name:'Shot map',exact:true}).click();await page.screenshot({path:evidence+'/mobile.png',fullPage:true});
const overflow=await page.evaluate(()=>({viewport:innerWidth,body:document.documentElement.scrollWidth,table:document.querySelector('.table-scroll').scrollWidth}));
if(overflow.body>overflow.viewport+1)throw new Error('Page has horizontal overflow '+JSON.stringify(overflow));
const result={state:errors.length?'failed':'passed',elapsed_ms:Date.now()-started,file_bytes:(await stat(report)).size,metrics,errors,network_requests:requests.filter(u=>/^https?:/.test(u)),tests,mobile:overflow,download_name:download.suggestedFilename()};
await writeFile(evidence+'/browser-verification.json',JSON.stringify(result,null,2));await browser.close();console.log(JSON.stringify(result,null,2));
