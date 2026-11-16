"""Read-only city census for the next stadium-geography milestone."""
from pathlib import Path
from collections import Counter
from datetime import datetime,timezone
import json,struct,sys,time
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from fm_live_mcp.bridge import Bridge,BridgeError
from fm_live_mcp import world,players,database,competition_stages
b=Bridge();sid=b.attach()['session_id'];rows=[];identity=None;dates=set()
try:
 while True:
  for attempt in range(5):
   try:
    with b.lock,b._read_scope(sid):
     p=b._current(sid);layout=b._player_layout(p);base=layout[0]-players.RVA[0];read,save,_=b._world_state(p,layout)
     root=world.pointer(read,base+0x56D2D20)
     competition_stages.typed(read,base,root,(0x55A1490,b'N2db14DATABASE_TABLEINS_4CITYEEE'))
     header=world.pointer(read,root+0x88);start,end,cap=struct.unpack('<QQQ',read(header,24))
     assert 4096<=start<=end<=cap and all(v%8==0 for v in (start,end,cap)) and (cap-start)//8<=200000
     current=(root,header,start,end,cap);assert identity is None or identity==current
     identity=current;count=(end-start)//8;limit=min(len(rows)+200,count)
     nations=database.table(read,base,'nations');batch=[]
     for index in range(len(rows),limit):
      address=world.pointer(read,start+index*8)
      competition_stages.typed(read,base,address,(0x559C558,b'N2db4CITYE'))
      assert players.u64(read(base+0x559C558+24,8))==base+0xDD548C
      raw=read(address,0x58);stored_index,native_id,duplicate_id=struct.unpack_from('<III',raw,8)
      assert stored_index==index and native_id
      ptr=players.u64(raw,0x18);name=None
      if ptr:
       size=int.from_bytes(read(ptr,4),'little');assert size<=512
       value=read(ptr+4,size+1);assert value[-1]==0
       name=value[:-1].decode('utf-8');assert all(ord(c)>=32 and ord(c)!=127 for c in name)
      nation=players.u64(raw,0x20);country=None
      if nation:
       world.typed(read,base,nation,'nation')
       ni,nid=struct.unpack('<II',read(nation+8,8));assert ni<nations['count'] and world.pointer(read,nations['start']+ni*8)==nation
       country={'address':hex(nation),'database_index':ni,'native_id':nid}
      batch.append({'address':hex(address),'database_index':index,'native_id':native_id,'duplicate_id':duplicate_id,
                    'name':name,'nation':country,'raw':raw.hex(),'population_code':struct.unpack_from('<b',raw,0x52)[0],
                    'attraction':struct.unpack_from('<b',raw,0x54)[0],'altitude_native':struct.unpack_from('<h',raw,0x50)[0]})
     read.verify();b._current(sid)
    break
   except (ValueError,BridgeError) as exc:
    if 'changed during read' not in str(exc) or attempt==4:raise
    time.sleep(0.2)
  rows.extend(batch);dates.add(save['current_date'])
  if len(rows)%4000==0:print(f'Cities: {len(rows)}/{count}',flush=True)
  if len(rows)==count:break
finally:b.detach()
receipt={'verified':True,'observed_at':datetime.now(timezone.utc).isoformat(),'count':len(rows),'cities':rows,
 'save_dates_observed':sorted(dates),'foreground_ui_used':False,'native_execution':False,
 'scope':'Independent raw city census with canonical nation membership; other city links and altitude units remain unresolved'}
(ROOT/'evidence/city-survey.json').write_text(json.dumps(receipt,indent=2)+'\n')
print(json.dumps({'count':len(rows),'population_codes':dict(Counter(r['population_code'] for r in rows)),
 'null_nations':sum(r['nation'] is None for r in rows),'null_names':sum(r['name'] is None for r in rows),'save_dates':sorted(dates)},indent=2))
