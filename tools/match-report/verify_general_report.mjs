import {chromium} from 'playwright';
import {pathToFileURL} from 'node:url';
import {writeFile,mkdir} from 'node:fs/promises';
const [file,directory]=process.argv.slice(2);
const browser=await chromium.launch({headless:true,executablePath:'/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'});
try{
 const page=await browser.newPage({viewport:{width:390,height:844}}),errors=[],network=[];
 page.on('pageerror',e=>errors.push(String(e)));page.on('request',r=>{if(/^https?:/.test(r.url()))network.push(r.url());});
 await page.goto(pathToFileURL(file).href);await page.waitForFunction(()=>window.__REPORT_READY__,null,{timeout:10000});
 const data=await page.evaluate(()=>window.__REPORT_DATA__),text=await page.locator('body').innerText();
 if(data.report_source?.source_mode==='captured'&&!text.includes(data.report_source.description)||data.report_source?.source_mode==='captured'&&!/historical/i.test(text))throw Error('Historical source qualification absent');
 if(data.pass_event_locations?.points?.length&&!text.includes(data.report_source.capture_id))throw Error('Captured pass source hash absent');
 if(data.average_nodes.length===0&&data.shots.length===0&&!text.includes('Match maps unavailable'))throw Error('Missing map limitation absent');
 if(text.includes('undefined'))throw Error('Undefined value leaked into report');
 if(errors.length||network.length)throw Error(JSON.stringify({errors,network}));
 const result={state:'passed',players:data.players.length,shots:data.shots.length,pass_points:data.pass_event_locations?.points?.length||0,errors,network};
 if(directory){await mkdir(directory,{recursive:true});await writeFile(directory+'/general-verification.json',JSON.stringify(result,null,2));}
 console.log(JSON.stringify(result));
}finally{await browser.close();}
