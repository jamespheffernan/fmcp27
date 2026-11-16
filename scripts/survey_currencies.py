from pathlib import Path
import sys,json,struct,math
from datetime import datetime,timezone
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from fm_live_mcp.bridge import Bridge
from fm_live_mcp import database,world,players,geography
b=Bridge();sid=b.attach()['session_id'];rows=[]
try:
 with b.lock,b._read_scope(sid):
  p=b._current(sid);layout=b._player_layout(p);base=layout[0]-players.RVA[0];read,save,_=b._world_state(p,layout)
  info=database.table(read,base,'currencies');assert info['count']<512
  assert players.u64(read(base+world.TYPES['currency'][0]+24,8))==base+0x1010480
  for i in range(info['count']):
   a=world.pointer(read,info['start']+i*8);world.typed(read,base,a,'currency');raw=read(a,0x58)
   index,nid,dup=struct.unpack_from('<III',raw,8);assert index==i and nid and nid==dup
   name=geography.optional_string(read,a+0x18);rate=struct.unpack_from('<f',raw,0x38)[0]
   strings={hex(off):geography.optional_string(read,a+off) for off in (0x18,0x20,0x28,0x30)}
   start,end,capacity=struct.unpack_from('<QQQ',raw,0x40)
   assert (start,end,capacity)==(0,0,0) or start>=4096 and start%8==0 and start<=end<=capacity and (end-start)%8==0 and capacity-start<80000
   history=[]
   for at in range(start,end,8):
    data=read(at,8);value=struct.unpack_from('<f',data,4)[0];history.append({'raw':data.hex(),'year':struct.unpack_from('<H',data)[0],'float':value if math.isfinite(value) else None})
   rows.append({'strings':strings,'history':history,'database_index':i,'native_id':nid,'name':name,'rate':rate if math.isfinite(rate) else None,'raw':raw.hex()})
  read.verify();b._current(sid)
finally:b.detach()
r={'observed_at':datetime.now(timezone.utc).isoformat(),'save_date':save['current_date'],'records':rows,'foreground_ui_used':False,'native_execution':False,'verified':True,'plugin_sha256':players.SHA256,'scope':'Independent typed canonical raw currency identities, serialized text, rates and complete historical vectors. No native execution.'}
(ROOT/'evidence/currency-survey.json').write_text(json.dumps(r,indent=2)+'\n')
print('records',len(rows),'zero',sum(r['rate']==0 for r in rows),'negative',sum(r['rate'] is not None and r['rate']<0 for r in rows),'nonfinite',sum(r['rate'] is None for r in rows))
print('Historical entries',sum(len(r['history']) for r in rows),'date',save['current_date'])
