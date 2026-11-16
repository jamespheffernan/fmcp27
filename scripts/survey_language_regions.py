"""Independent raw language and local-region census; no native execution or UI."""
from pathlib import Path
from datetime import datetime,timezone
from collections import Counter
import json,struct,sys,time
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'scripts'))
from fm_live_mcp.bridge import Bridge,BridgeError
from fm_live_mcp import world,players,database,competition_stages
from survey_city_linked_records import TABLES,stored_string

b=Bridge();sid=b.attach()['session_id'];result={};dates=set()
try:
    for kind,table_kind in (('language','languages'),('local_region','local_regions')):
        rows=[];identity=None
        while True:
            for attempt in range(5):
                try:
                    with b.lock,b._read_scope(sid):
                        p=b._current(sid);layout=b._player_layout(p);base=layout[0]-players.RVA[0]
                        read,save,_=b._world_state(p,layout);table=database.table(read,base,table_kind)
                        assert identity is None or identity==table['identity'];identity=table['identity'];batch=[]
                        def target(a,target_kind):
                            if not a:return None
                            rva,tv,tn,rv,rn,getter,fields=TABLES[target_kind]
                            competition_stages.typed(read,base,a,(rv,rn))
                            assert players.u64(read(base+rv+24,8))==base+getter
                            root=world.pointer(read,base+rva);competition_stages.typed(read,base,root,(tv,tn))
                            h=world.pointer(read,root+0x88);start,end,cap=struct.unpack('<QQQ',read(h,24))
                            assert 4096<=start<=end<=cap and all(p%8==0 for p in (start,end,cap)) and cap-start<=80000
                            index,nid,dup=struct.unpack('<III',read(a+8,12))
                            assert nid==dup and nid and index<(end-start)//8 and world.pointer(read,start+index*8)==a
                            return {'address':hex(a),'native_id':nid,'database_index':index,
                                **{field:stored_string(read,players.u64(read(a+offset,8))) for field,offset in fields}}
                        for index in range(len(rows),min(len(rows)+100,table['count'])):
                            a=world.pointer(read,table['start']+index*8);row=target(a,kind);assert row['database_index']==index
                            raw=read(a,0x40 if kind=='language' else 0x60);row['raw']=raw.hex()
                            if kind=='language':
                                row.update(family=struct.unpack_from('<h',raw,0x34)[0],group=struct.unpack_from('<h',raw,0x36)[0],
                                    subgroup=struct.unpack_from('<h',raw,0x38)[0],influence=struct.unpack_from('<b',raw,0x3b)[0],
                                    difficulty=struct.unpack_from('<b',raw,0x3c)[0],nation=target(players.u64(raw,0x28),'nation'))
                            else:
                                row.update(population=struct.unpack_from('<i',raw,0x58)[0],nation=target(players.u64(raw,0x48),'nation'),weather=target(players.u64(raw,0x50),'weather'))
                                start,end,cap=struct.unpack_from('<QQQ',raw,0x30)
                                if not(start or end or cap):entries=[]
                                else:
                                    assert 4096<=start<=end<=cap and all(p%8==0 for p in (start,end,cap)) and (cap-start)%16==0 and (end-start)%16==0 and (cap-start)//16<=1000
                                    entries=[]
                                    for pos in range(start,end,16):
                                        entry=read(pos,16)
                                        entries.append({'raw':entry.hex(),'language':target(players.u64(entry),'language'),'percentage_native':struct.unpack_from('<b',entry,8)[0]})
                                row['languages']=entries
                            batch.append(row)
                        read.verify();b._current(sid)
                    break
                except (ValueError,BridgeError) as exc:
                    if 'changed during read' not in str(exc) or attempt==4:raise
                    time.sleep(.2)
            rows.extend(batch);dates.add(save['current_date'])
            if len(rows)==table['count']:break
        result[kind]=rows;print(kind,len(rows),flush=True)
finally:b.detach()
receipt={'verified':True,'observed_at':datetime.now(timezone.utc).isoformat(),'records':result,'save_dates':sorted(dates),
    'foreground_ui_used':False,'native_execution':False,'scope':'Independent typed/canonical raw census of language fields and region language entries; compare public results separately.'}
(ROOT/'evidence/language-region-detail-survey.json').write_text(json.dumps(receipt,indent=2)+'\n')
for key in ('family','group','subgroup','difficulty','influence'):
    print('language',key,dict(Counter(r[key] for r in result['language'])))
print('region language count',dict(Counter(len(r['languages']) for r in result['local_region'])))
print('region language percentage',dict(Counter(e['percentage_native'] for r in result['local_region'] for e in r['languages'])))
print('region population',min(r['population'] for r in result['local_region']),max(r['population'] for r in result['local_region']))
