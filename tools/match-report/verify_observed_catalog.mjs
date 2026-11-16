import {chromium} from 'playwright';
import {pathToFileURL} from 'node:url';
import {mkdir,writeFile,readFile} from 'node:fs/promises';
const [file,directory]=process.argv.slice(2);await mkdir(directory,{recursive:true});
const browser=await chromium.launch({headless:true,executablePath:'/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'});
try{
 const page=await browser.newPage({viewport:{width:1440,height:1000},acceptDownloads:true}),errors=[],network=[];
 page.on('pageerror',e=>errors.push(String(e)));page.on('request',r=>{if(/^https?:/.test(r.url()))network.push(r.url());});
 await page.goto(pathToFileURL(file).href);await page.waitForFunction(()=>window.__REPORT_READY__,null,{timeout:10000});
 const data=await page.evaluate(()=>window.__REPORT_DATA__),checks=[];
 if(data.report_kind!=='registered_observed_run')throw Error('Wrong report kind');
 for(const [name,rows]of Object.entries(data.observed_tables)){
  await page.getByRole('combobox',{name:'Observed section',exact:true}).selectOption(name);
  if(await page.locator('#observed-records tbody tr').count()!==rows.length)throw Error('Wrong captured row count for '+name);
  checks.push({table:name,rows:rows.length});
 }
 if(data.observed_scope==='partial_prefix'){
  const text=await page.locator('body').innerText();
  if(data.score.home===null&&!text.includes('score Unavailable'))throw Error('Unknown score promoted');
  if(!data.observed_tables.shots&&!text.includes('shots: unavailable'))throw Error('Missing shot scope absent');
  if(!data.observed_tables.match_periods?.length&&await page.getByRole('combobox',{name:'Recorded period',exact:true}).count())throw Error('Unknown period promoted');
 }
 if(data.observed_shot_map){await page.getByRole('button',{name:'Recorded shot map',exact:true}).click();if(await page.locator('.observed-shot').count()!==data.observed_shot_map.points.length)throw Error('Recorded shot scope changed');await page.getByRole('button',{name:'Sample-density heat map',exact:true}).click();}
 await page.getByRole('combobox',{name:'Observed section',exact:true}).selectOption('completed_pass_events');
 for(const side of [0,1]){
  await page.getByRole('combobox',{name:'Team',exact:true}).selectOption(String(side));
  const count=data.observed_tables.completed_pass_events.filter(r=>r.side_index===side).length;
  if(await page.locator('#observed-records tbody tr').count()!==count)throw Error('Team filter changed source denominator');
 }
 await page.getByRole('combobox',{name:'Team',exact:true}).selectOption('both');
 if(data.observed_density&&await page.locator('.density-cell').count()===0)throw Error('Captured density empty');
 const [download]=await Promise.all([page.waitForEvent('download'),page.getByRole('button',{name:'Download report data',exact:true}).click()]);
 await download.saveAs(directory+'/downloaded.json');const exported=JSON.parse(await readFile(directory+'/downloaded.json','utf8'));
 if(exported.report_source.capture_id!==data.report_source.capture_id)throw Error('Downloaded source pin changed');
 await page.screenshot({path:directory+'/desktop.png',fullPage:false});
 await page.setViewportSize({width:390,height:844});await page.screenshot({path:directory+'/mobile.png',fullPage:true});
 const width=await page.evaluate(()=>({viewport:innerWidth,body:document.documentElement.scrollWidth}));if(width.body>width.viewport+1)throw Error('Mobile overflow '+JSON.stringify(width));
 const text=await page.locator('body').innerText();if(text.includes('undefined'))throw Error('Undefined value leaked');
 if(errors.length||network.length)throw Error(JSON.stringify({errors,network}));
 const result={state:'passed',source_id:data.report_source.source_id,capture_id:data.report_source.capture_id,scope:data.observed_scope,checks,width,errors,network};await writeFile(directory+'/verified.json',JSON.stringify(result,null,2));console.log(JSON.stringify(result));
}finally{await browser.close();}
