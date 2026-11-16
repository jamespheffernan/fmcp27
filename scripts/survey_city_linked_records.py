"""Independent raw identity/name census for geographic records linked from cities."""
from datetime import datetime,timezone
import json
from pathlib import Path
import struct
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from fm_live_mcp.bridge import Bridge,BridgeError
from fm_live_mcp import competition_stages,players,world

TABLES={
    'nation':(0x56D2D40,0x55A1670,b'N2db14DATABASE_TABLEINS_6NATIONEEE',0x55B5C40,b'N2db6NATIONE',0x13B1D14,(('short_name',0x20),('abbreviation',0x28))),
    'language':(0x56D2D68,0x55A1850,b'N2db14DATABASE_TABLEINS_8LANGUAGEEEE',0x55B5080,b'N2db8LANGUAGEE',0x1369C14,(('name',0x18),)),
    'local_region':(0x56D2D70,0x55A18C8,b'N2db14DATABASE_TABLEINS_12LOCAL_REGIONEEE',0x55B5718,b'N2db12LOCAL_REGIONE',0x137A600,(('name',0x18),)),
    'weather':(0x56D2DB8,0x55A1D00,b'N2db14DATABASE_TABLEINS_7WEATHEREEE',0x55CC3A0,b'N2db7WEATHERE',0x18B2768,(('name',0x18),)),
}


def stored_string(read,pointer):
    if not pointer:return None
    size=int.from_bytes(read(pointer,4),'little')
    assert size<=512
    raw=read(pointer+4,size+1)
    assert raw[-1]==0
    value=raw[:-1].decode('utf-8')
    assert all(ord(c)>=32 and ord(c)!=127 for c in value)
    return value


def survey():
    b=Bridge();sid=b.attach()['session_id'];result={};dates=set()
    try:
        for kind,(rva,tv,tn,rv,rn,getter,fields) in TABLES.items():
            rows=[];identity=None
            while True:
                for attempt in range(5):
                    try:
                        with b.lock,b._read_scope(sid):
                            process=b._current(sid);layout=b._player_layout(process);base=layout[0]-players.RVA[0]
                            read,save,_=b._world_state(process,layout)
                            root=world.pointer(read,base+rva)
                            competition_stages.typed(read,base,root,(tv,tn))
                            header=world.pointer(read,root+0x88);start,end,capacity=struct.unpack('<QQQ',read(header,24))
                            assert 4096<=start<=end<=capacity and all(p%8==0 for p in (start,end,capacity)) and capacity-start<=80000
                            current=(root,header,start,end,capacity)
                            assert identity is None or current==identity
                            identity=current;count=(end-start)//8;batch=[]
                            for index in range(len(rows),min(len(rows)+100,count)):
                                address=world.pointer(read,start+index*8)
                                competition_stages.typed(read,base,address,(rv,rn))
                                assert players.u64(read(base+rv+24,8))==base+getter
                                raw=read(address+8,12);i,native_id,duplicate=struct.unpack('<III',raw)
                                assert i==index and native_id and native_id==duplicate
                                names={field:stored_string(read,players.u64(read(address+offset,8))) for field,offset in fields}
                                batch.append({'address':hex(address),'database_index':index,'native_id':native_id,
                                              'identity_raw':raw.hex(),**names})
                            read.verify();b._current(sid)
                        break
                    except (ValueError,BridgeError) as exc:
                        if 'changed during read' not in str(exc) or attempt==4:raise
                        time.sleep(.2)
                rows.extend(batch);dates.add(save['current_date'])
                if len(rows)==count:break
            result[kind]={'count':count,'records':rows}
            print(f'{kind}: {count}',flush=True)
    finally:b.detach()
    receipt={'verified':True,'observed_at':datetime.now(timezone.utc).isoformat(),'tables':result,
             'native_save_dates_observed':sorted(dates),'foreground_ui_used':False,'native_execution':False}
    (ROOT/'evidence/city-linked-record-survey.json').write_text(json.dumps(receipt,indent=2)+'\n')
    return receipt


if __name__=='__main__':survey()
