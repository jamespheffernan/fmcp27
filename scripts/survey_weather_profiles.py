"""Read-only raw census of four embedded WEATHER period records."""
from pathlib import Path
from collections import Counter
from datetime import datetime,timezone
import json,struct,sys,time
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'scripts'))
from fm_live_mcp.bridge import Bridge,BridgeError
from fm_live_mcp import world,players,competition_stages
from survey_city_linked_records import stored_string
b=Bridge();sid=b.attach()['session_id'];rows=[];identity=None;dates=set()
try:
    while True:
        for attempt in range(5):
            try:
                with b.lock,b._read_scope(sid):
                    p=b._current(sid);layout=b._player_layout(p);base=layout[0]-players.RVA[0];read,save,_=b._world_state(p,layout)
                    root=world.pointer(read,base+0x56d2db8);competition_stages.typed(read,base,root,(0x55a1d00,b'N2db14DATABASE_TABLEINS_7WEATHEREEE'))
                    header=world.pointer(read,root+0x88);start,end,cap=struct.unpack('<QQQ',read(header,24))
                    assert 4096<=start<=end<=cap and all(p%8==0 for p in (start,end,cap)) and cap-start<=80000
                    current=(root,header,start,end,cap);assert identity is None or identity==current;identity=current;count=(end-start)//8;batch=[]
                    for index in range(len(rows),min(len(rows)+100,count)):
                        a=world.pointer(read,start+index*8);competition_stages.typed(read,base,a,(0x55cc3a0,b'N2db7WEATHERE'))
                        assert players.u64(read(base+0x55cc3a0+24,8))==base+0x18b2768
                        raw=read(a,0x80);i,nid,dup=struct.unpack_from('<III',raw,8);assert i==index and nid and nid==dup
                        name=stored_string(read,players.u64(raw,0x18));periods=[]
                        for period in range(4):
                            at=0x20+period*0x18;data=raw[at:at+0x18]
                            periods.append({'native_index':period,'start_day_native':struct.unpack_from('<h',data,0)[0],
                                'wind_native':list(struct.unpack_from('<5b',data,2)),'precipitation_native':list(struct.unpack_from('<5b',data,7)),
                                'temperature_native':list(struct.unpack_from('<10b',data,12)),
                                'day_night_drop_native':struct.unpack_from('<b',data,22)[0],'raw':data.hex()})
                        batch.append({'address':hex(a),'native_id':nid,'database_index':i,'name':name,'raw':raw.hex(),'periods':periods})
                    read.verify();b._current(sid)
                break
            except (ValueError,BridgeError) as exc:
                if 'changed during read' not in str(exc) or attempt==4:raise
                time.sleep(.2)
        rows.extend(batch);dates.add(save['current_date'])
        if len(rows)==count:break
finally:b.detach()
receipt={'verified':True,'records':rows,'save_dates':sorted(dates),'observed_at':datetime.now(timezone.utc).isoformat(),
    'foreground_ui_used':False,'native_execution':False,'scope':'Exploratory raw fields with canonical WEATHER identities; current weather, probability semantics and variance unit not established.'}
(ROOT/'evidence/weather-profile-survey.json').write_text(json.dumps(receipt,indent=2)+'\n')
print('Records',len(rows),'dates',sorted(dates))
for key in ('wind_native','precipitation_native','temperature_native'):
    print(key,'totals',dict(Counter(sum(p[key]) for r in rows for p in r['periods'])),
          'range',min(v for r in rows for p in r['periods'] for v in p[key]),max(v for r in rows for p in r['periods'] for v in p[key]))
print('start day range',min(p['start_day_native'] for r in rows for p in r['periods']),max(p['start_day_native'] for r in rows for p in r['periods']))
print('drop range',min(p['day_night_drop_native'] for r in rows for p in r['periods']),max(p['day_night_drop_native'] for r in rows for p in r['periods']))

