"""Census every competition's stored registration slots with byte rechecks."""
from collections import Counter
from datetime import datetime, timezone
import json
from pathlib import Path
import struct
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from fm_live_mcp.bridge import Bridge
from fm_live_mcp import competition_registrations, database, players, teams, world


def survey():
    bridge=Bridge();sid=bridge.attach()['session_id'];rows=[];identity=None;start=0
    try:
        while True:
            with bridge.lock,bridge._read_scope(sid):
                process=bridge._current(sid);tables=bridge._player_layout(process);base=tables[0]-players.RVA[0]
                read,save,_=bridge._world_state(process,tables);info=database.table(read,base,'competitions')
                team_info=teams.lookup(read,base)
                if identity is not None:assert identity==info['identity']
                identity=info['identity'];end=min(start+250,info['count'])
                batch=[]
                for index in range(start,end):
                    address=world.pointer(read,info['start']+index*8)
                    world.typed(read,base,address,'competition')
                    native_id=int.from_bytes(read(address+12,4),'little')
                    header=competition_registrations.vector(read,address)
                    records=[];nulls=0
                    for slot in range(header['count']):
                        pointer=players.u64(read(header['start']+slot*8,8))
                        if not pointer:nulls+=1;continue
                        row,_=competition_registrations.record(read,base,pointer,team_info=team_info)
                        # Independent raw scalar comparison, including both sentinels.
                        _,year,identifier=struct.unpack('<QHb',read(pointer,11))
                        assert row['native_year_code']==year and row['native_info_code']==identifier
                        records.append({'registration_index':slot,**row})
                    batch.append({'competition_id':native_id,'competition_index':index,
                                  'total_slots':header['count'],'null_slots':nulls,'registrations':records})
                read.verify()
            rows.extend(batch);start=end
            print(f'Checked {start}/{info["count"]} competitions',flush=True)
            if start==info['count']:break
        flat=[r for row in rows for r in row['registrations']]
        result={'verified':True,'observed_at':datetime.now(timezone.utc).isoformat(),
                'save':bridge._public_save(save),'competition_count':len(rows),
                'nonempty_competitions':sum(bool(r['total_slots']) for r in rows),
                'record_count':len(flat),'null_slots':sum(r['null_slots'] for r in rows),
                'native_year_counts':dict(Counter(r['native_year_code'] for r in flat)),
                'native_identifier_counts':dict(Counter(r['native_info_code'] for r in flat)),
                'team_kinds':dict(Counter(r['team']['kind'] if r['team'] else 'missing' for r in flat)),
                'missing_nations':sum(r['nation'] is None for r in flat),
                'competitions':rows,'foreground_ui_used':False}
        (ROOT/'evidence/competition-registration-survey.json').write_text(json.dumps(result,indent=2)+'\n')
        print(json.dumps({k:v for k,v in result.items() if k not in ('save','competitions')},indent=2))
    finally:bridge.detach()


if __name__=='__main__':survey()
