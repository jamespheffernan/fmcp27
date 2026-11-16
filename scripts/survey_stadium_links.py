"""Check current stadium city, nearby-stadium and owner-club memberships."""
from pathlib import Path
from datetime import datetime,timezone
import json,struct,sys,time
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from fm_live_mcp.bridge import Bridge,BridgeError
from fm_live_mcp import world,players,database,competition_stages
from survey_city_linked_records import stored_string
b=Bridge();sid=b.attach()['session_id'];rows=[];identity=None;dates=set()
try:
 while True:
  for attempt in range(5):
   try:
    with b.lock,b._read_scope(sid):
     p=b._current(sid);layout=b._player_layout(p);base=layout[0]-players.RVA[0];read,save,_=b._world_state(p,layout)
     stadiums=database.table(read,base,'stadiums');clubs=database.table(read,base,'clubs')
     root=world.pointer(read,base+0x56D2D20);competition_stages.typed(read,base,root,(0x55A1490,b'N2db14DATABASE_TABLEINS_4CITYEEE'))
     header=world.pointer(read,root+0x88);start,end,cap=struct.unpack('<QQQ',read(header,24))
     assert 4096<=start<=end<=cap and all(v%8==0 for v in (start,end,cap)) and (cap-start)//8<=200000
     cities={'start':start,'count':(end-start)//8}
     current=(stadiums['identity'],clubs['identity'],root,header,start,end,cap)
     assert identity is None or identity==current;identity=current
     def link(address,kind,table):
      if not address:return None
      if kind=='city':competition_stages.typed(read,base,address,(0x559C558,b'N2db4CITYE'))
      else:world.typed(read,base,address,kind)
      index,native_id,duplicate_id=struct.unpack('<III',read(address+8,12))
      assert index<table['count'] and world.pointer(read,table['start']+index*8)==address
      assert native_id
      return {'address':hex(address),'database_index':index,'native_id':native_id,'duplicate_id':duplicate_id}
     limit=min(len(rows)+200,stadiums['count']);batch=[]
     for i in range(len(rows),limit):
      a=world.pointer(read,stadiums['start']+i*8);parent=link(a,'stadium',stadiums);assert parent['database_index']==i
      row={**parent}
      for field,off,kind,table in (('city',0x60,'city',cities),('nearby_stadium',0x68,'stadium',stadiums),('owner_club',0x90,'club',clubs)):
       pointer=players.u64(read(a+off,8))
       row[field]=link(pointer,kind,table)
       if field=='owner_club' and pointer:
        row[field]['name']=stored_string(read,players.u64(read(pointer+0xC0,8)))
        row[field]['short_name']=stored_string(read,players.u64(read(pointer+0xC8,8)))
      batch.append(row)
     read.verify();b._current(sid)
    break
   except (ValueError,BridgeError) as exc:
    if 'changed during read' not in str(exc) or attempt==4:raise
    time.sleep(0.2)
  rows.extend(batch);dates.add(save['current_date'])
  if len(rows)%4000==0:print(f'Stadium links: {len(rows)}/{stadiums["count"]}',flush=True)
  if len(rows)==stadiums['count']:break
finally:b.detach()
receipt={'verified':True,'observed_at':datetime.now(timezone.utc).isoformat(),'count':len(rows),'stadiums':rows,
 'linked_counts':{k:sum(r[k] is not None for r in rows) for k in ('city','nearby_stadium','owner_club')},
 'save_dates_observed':sorted(dates),'foreground_ui_used':False,'native_execution':False,
 'scope':'Current typed canonical linked records; does not interpret legal ownership, proximity, ground sharing or historical locations'}
(ROOT/'evidence/stadium-links-survey.json').write_text(json.dumps(receipt,indent=2)+'\n')
print(json.dumps({k:v for k,v in receipt.items() if k!='stadiums'},indent=2))
