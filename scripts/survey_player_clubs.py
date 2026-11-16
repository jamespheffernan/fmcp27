"""Census checked club relationships/native On Loan state for supported players."""
from collections import Counter
from datetime import datetime, timezone
import json
from pathlib import Path
import struct
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from fm_live_mcp import database,players,world
from fm_live_mcp.bridge import Bridge


def main():
    b=Bridge();sid=b.attach()['session_id'];counts=Counter();samples={};errors=[];seen=0;total=None
    try:
        for lower in range(0,200000,1000):
            with b.lock,b._read_scope(sid):
                tables=b._player_layout(b.process);base=tables[0]-players.RVA[0]
                snap,_,_=b._world_state(b.process,tables)
                info=database.table(snap,base,'people');total=info['count']
                if lower>=total:break
                batch_counts=Counter();batch_samples={};batch_errors=[];cache={}
                layouts={tables[2]:0x388,base+players.STAFF_RVA[2]:0x480}
                n=min(1000,total-lower)
                for index,person in enumerate(struct.unpack(f'<{n}Q',snap(info['start']+lower*8,n*8)),lower):
                    offset=layouts.get(players.u64(snap(person,8)))
                    if offset is None:
                        batch_counts['other_person_type']+=1;continue
                    address=person-offset
                    database.player_membership(snap,base,info,index,address)
                    player=players.decode(snap,address,tables)[0]
                    try:clubs=world.player_clubs(snap,base,address,cache,player_staff=offset==0x480)
                    except ValueError as exc:
                        batch_errors.append({'name':player['name'],'birth_date':player['birth_date'],'index':index,'error':str(exc)})
                        batch_counts['rejected']+=1;continue
                    batch_counts['decoded']+=1
                    keys=[clubs['loan_status_reason'],'parent_club_' + clubs['contract_club_state'],
                          'on_loan' if clubs['on_loan'] else 'not_on_loan']
                    if offset==0x480:keys.append('combined')
                    if clubs['current_club'] is None:keys.append('no_current_team')
                    if clubs['current_club']!=clubs['contract_club']:keys.append('current_and_parent_names_differ')
                    if clubs['loan_club'] and clubs['current_club']!=clubs['loan_club']:keys.append('current_and_loan_names_differ')
                    main=players.u64(snap(person-0x98,8))
                    if main:
                        one,two=struct.unpack('<QQ',snap(main+0x10,16))
                        if one!=two:keys.append('different_main_teams_same_club')
                    sample={'name':player['name'],'birth_date':player['birth_date'],'database_index':index,'clubs':clubs}
                    for key in keys:
                        batch_counts[key]+=1;batch_samples.setdefault(key,sample)
                snap.verify()
                counts.update(batch_counts);errors.extend(batch_errors)
                for key,sample in batch_samples.items():samples.setdefault(key,sample)
                seen+=n
            if lower%10000==0:print('scanned',seen,'decoded',counts['decoded'],'rejected',counts['rejected'],flush=True)
    finally:
        b.detach()
        receipt={'observed_at':datetime.now(timezone.utc).isoformat(),'seen':seen,'native_person_count':total,
            'complete_native_table_scan':seen==total,'counts':dict(counts),'samples':samples,'errors':errors,
            'scope':'Supported regular/combined player club links and native On Loan getter; each batch rechecks save, membership and consumed bytes. Non-atomic census; no UI.'}
        (ROOT/'evidence/player-club-survey.json').write_text(json.dumps(receipt,indent=2)+'\n')
    print(json.dumps(receipt['counts']))
    assert counts['decoded'] + counts['rejected'] + counts['other_person_type'] == seen


if __name__=='__main__':main()
