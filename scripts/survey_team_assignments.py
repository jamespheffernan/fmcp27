"""Read every canonical TEAM_BASE slot and recheck each bounded batch."""
from collections import Counter
from datetime import datetime, timezone
import json
from pathlib import Path
import struct
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from fm_live_mcp.bridge import Bridge
from fm_live_mcp import database, players, teams, world


def survey():
    bridge=Bridge();sid=bridge.attach()['session_id'];rows=[];identity=None;start=0
    try:
        while True:
            with bridge.lock,bridge._read_scope(sid):
                process=bridge._current(sid);tables=bridge._player_layout(process);base=tables[0]-players.RVA[0]
                read,save,_=bridge._world_state(process,tables);info=teams.lookup(read,base)
                if identity is not None:assert identity==(info['identity'],info['lookup_identity'])
                identity=(info['identity'],info['lookup_identity'])
                assert info['lookup_identity'][0]==1,'Census comparisons require the canonical lookup mode'
                end=min(start+1000,info['count']);batch=[]
                addresses=struct.unpack(f'<{end-start}Q',read(info['start']+start*8,(end-start)*8))
                for index,address in enumerate(addresses,start):
                    raw=read(address,0x78);vtable=players.u64(raw)
                    kind=next(kind for kind in ('team','national_team') if vtable==base+world.TYPES[kind][0])
                    world.typed(read,base,address,kind)
                    native_index,native_id,random_id=struct.unpack_from('<III',raw,8)
                    assert native_index==index and native_id
                    links=[]
                    for offset in (0x50,0x58,0x68,0x70):
                        pointer=players.u64(raw,offset)
                        if pointer:
                            world.typed(read,base,pointer,'competition');comp=read(pointer+8,12)
                            links.append({'index':struct.unpack_from('<I',comp)[0],
                                          'native_id':struct.unpack_from('<I',comp,4)[0]})
                        else:links.append(None)
                    owner=players.u64(raw,0x30)
                    batch.append({'index':index,'native_index':native_index,'native_id':native_id,
                        'raw_random_id':random_id,'kind':kind,'team_type_code':struct.unpack_from('<b',raw,0x28)[0],
                        'has_club':bool(owner),'club_id':struct.unpack('<I',read(owner+12,4))[0] if owner else None,
                        'owner_vtable':hex(world.pointer(read,owner)-base) if owner else None,'links':links})
                read.verify()
            rows.extend(batch);start=end
            print(f'Checked {start}/{info["count"]} teams',flush=True)
            if start==info['count']:break
        result={'observed_at':datetime.now(timezone.utc).isoformat(),'complete_native_table_scan':True,
                'save':bridge._public_save(save),'rows':rows,'counts':dict(Counter(r['kind'] for r in rows)),
                'unequal_id_fields':sum(r['native_id']!=r['raw_random_id'] for r in rows),
                'nonnull_assignments':[sum(r['links'][i] is not None for r in rows) for i in range(4)],
                'foreground_ui_used':False}
        (ROOT/'evidence/team-assignment-survey.json').write_text(json.dumps(result,indent=2)+'\n')
        print(json.dumps({k:v for k,v in result.items() if k not in ('rows','save')},indent=2))
    finally:bridge.detach()


if __name__=='__main__':survey()
