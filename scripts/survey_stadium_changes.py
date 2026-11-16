"""Raw read-only stadium-change census, independent of the production field decoder."""
from pathlib import Path
import sys,json,struct
from datetime import datetime,timezone
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from fm_live_mcp.bridge import Bridge
from fm_live_mcp import players,world,database,competition_stages,teams,stadiums
b=Bridge();sid=b.attach()['session_id'];rows=[]
try:
 with b.lock,b._read_scope(sid):
  p=b._current(sid);layout=b._player_layout(p);base=layout[0]-players.RVA[0];read,save,_=b._world_state(p,layout)
  root=world.pointer(read,base+0x56d2da0)
  competition_stages.typed(read,base,root,(0x55a1b98,b'N2db14DATABASE_TABLEINS_14STADIUM_CHANGEEEE'))
  vt=world.pointer(read,root);info=world.pointer(read,vt-8);name=players.u64(read(info+8,8));rtti=read(name,100).split(b'\0',1)[0].decode()
  header=world.pointer(read,root+0x88);start,end,cap=struct.unpack('<QQQ',read(header,24))
  assert 4096<=start<=end<=cap and all(a%8==0 for a in (start,end,cap)) and cap-start<80000
  table=database.table(read,base,'teams')
  for index,pos in enumerate(range(start,end,8)):
   a=world.pointer(read,pos);competition_stages.typed(read,base,a,(0x55bd8c0,b'N2db14STADIUM_CHANGEE'))
   assert players.u64(read(base+0x55bd8c0+24,8))==base+0x16d5c84
   raw=read(a,0x70);i,nid,dup=struct.unpack_from('<III',raw,8);assert i==index and nid and nid==dup
   team=players.u64(raw,0x18);team_identity=None
   if team:
    ti,tnid,random=struct.unpack('<III',read(team+8,12));assert ti<table['count'] and world.pointer(read,table['start']+ti*8)==team
    team_row,team_binding=teams.by_index(read,base,ti);assert team_binding['address']==team
    team_identity={'address':hex(team),'database_index':ti,'native_id':tnid,'random_id':random,'vtable':hex(world.pointer(read,team)-base)}
   targets={}
   for label,off in (('current',0x20),('new',0x28),('alternative',0x48)):
    target=players.u64(raw,off)
    if target:
     summary,binding=stadiums.record(read,base,target)
     targets[label]=summary
    else:targets[label]=None
   rows.append({'address':hex(a),'database_index':i,'native_id':nid,'duplicate_id':dup,'raw':raw.hex(),
                'team':team_identity,'stadiums':targets,'type_native':struct.unpack_from('<b',raw,0x64)[0]})
  read.verify();b._current(sid)
finally:b.detach()
receipt={'observed_at':datetime.now(timezone.utc).isoformat(),'records':rows,'table_rtti':rtti,'save_date':save['current_date'],
         'foreground_ui_used':False,'native_execution':False,'verified':True,'plugin_sha256':players.SHA256,'scope':'Raw records, canonical identity/membership and checked linked targets; field interpretation verified separately.'}
(ROOT/'evidence/stadium-change-survey.json').write_text(json.dumps(receipt,indent=2)+'\n')
print('Stadium changes',len(rows),'team links',sum(r['team'] is not None for r in rows),'types',sorted(set(r['type_native'] for r in rows)))
print('Table',rtti,'vtable',hex(vt-base))
