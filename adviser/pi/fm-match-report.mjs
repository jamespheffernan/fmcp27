import {execFile} from 'node:child_process';
import {dirname,join} from 'node:path';
import {Buffer} from 'node:buffer';
import {accessSync,constants,lstatSync} from 'node:fs';
import {readerCommand} from './fm-desktop-reader.mjs';

export const MATCH_REPORT_TOOL='fm_match_report';
const integer=(description,minimum=1)=>({type:'integer',minimum,maximum:2147483647,description});
const string=description=>({type:'string',description});

export function registerMatchReportTool(pi){
 const backend=join(dirname(process.env.PI_FM_MCP_LAUNCHER||'/Volumes/4TB Private/Offloaded/FMCP 27/scripts/run_mcp.sh'),'run_match_report.sh');
 try{accessSync(backend,constants.R_OK);if(!lstatSync(backend).isFile())return false;}catch{return false;}
 pi.registerTool({
  name:MATCH_REPORT_TOOL,label:'Create interactive FM match report',
  description:'Generate a self-contained offline HTML match report under ~/Agent Outputs from one exact verified source. source=observed reads registered observed-run source_id/capture_id and fixture_id equal to the stringified official_match_unique_id from its fixtures query. It preserves prefix/terminal and earlier spatial scopes; score, shots or retained player counters may be unavailable. source=retained re-discovers the selected RESULT in a fresh read-only attachment: supply career name/creation identity, ISO fixture date, ordered home/away native team IDs, competition native ID and expected score; native_match_key is optional. source=captured reads only a registered catalog source_id/capture_id and exact fixture_id (optional career_id). Get selectors from current reader tools, not guesses. Captured mode visibly reports its historical capture date. Returns the verified absolute HTML path, source/coverage pins and file hash. Heat maps, passing and player statistics appear only where source-backed; gaps remain unavailable. Optional filename selects one safe .html leaf within Agent Outputs; omitted filenames keep the deterministic default. No caller directories, source JSON, HTML or shell; no game changes or foreground UI. Existing unrelated reports are never overwritten.',
  parameters:{type:'object',additionalProperties:false,properties:{
   source:{type:'string',enum:['retained','captured','observed']},
   filename:{type:'string',minLength:6,maxLength:250,description:'Optional exact .html filename only, inside Agent Outputs. No directory, path separators, control characters or overwrite; different existing content is refused.'},
   fixture_date:string('Retained: exact selected fixture ISO YYYY-MM-DD.'),
   home_team_native_id:integer('Retained: verified ordered home-team native ID.'),
   away_team_native_id:integer('Retained: verified ordered away-team native ID.'),
   competition_native_id:integer('Retained: verified competition native ID.'),
   expected_home_goals:integer('Retained: exact checked final home score.',0),
   expected_away_goals:integer('Retained: exact checked final away score.',0),
   native_match_key:integer('Retained: selected native result key when returned by the reader.'),
   career_name:string('Retained: exact loaded save.name from fm_get_save.'),
   career_created_date:string('Retained: exact save.created_date.'),
   career_created_version:integer('Retained: exact save.created_version.'),
   source_id:string('Captured/observed: exact source ID from the corresponding catalog.'),
   capture_id:string('Captured/observed: exact catalog SHA256 pin.'),
   fixture_id:string('Captured: exact fixture_id; observed: stringified official_match_unique_id from that source fixtures query.'),
   career_id:string('Captured/observed: optional exact career hash from the same catalog entry.'),
  },required:['source']},
  async execute(_id,params,signal,onUpdate){
   onUpdate?.({content:[{type:'text',text:'Generating the selected source-backed interactive report; the game remains untouched.'}],details:{phase:'generating'}});
   try{
    if(Object.hasOwn(params,'filename')){
     const name=params.filename;
     if(typeof name!=='string'||!name||name!==name.trim()||name.startsWith('.')||!name.endsWith('.html')||/[\/\\:\p{Cc}\p{Cf}\p{Zl}\p{Zp}]/u.test(name)||Buffer.byteLength(name,'utf8')>250)throw new Error('filename must be one safe HTML filename under Agent Outputs');
    }
    const run=readerCommand('match-report');
    const details=await new Promise((resolve,reject)=>{
     const child=execFile(run.command,run.args,{timeout:180000,maxBuffer:131072,signal},(error,stdout,stderr)=>{
      let result;try{result=JSON.parse(stdout);}catch{}
      if(error||result?.state!=='ready'){
       const failure=new Error(result?.error||stderr.trim()||error?.message||'Report generator returned no successful receipt');
       failure.artifactCreated=typeof result?.artifact_created==='boolean'?result.artifact_created:null;
       return reject(failure);
      }
      resolve(result);
     });
     child.stdin.on('error',reject);child.stdin.end(JSON.stringify(params));
    });
    return{content:[{type:'text',text:JSON.stringify(details)}],details};
   }catch(error){return{content:[{type:'text',text:`Interactive report unavailable: ${error.message}`}],details:{error:true,artifact_created:error.artifactCreated??null},isError:true};}
  },
 });
}
