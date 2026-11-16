"""Read-only census of record identities and supported person decoding."""
from collections import Counter
from datetime import datetime, timezone
import json
from pathlib import Path
import struct
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from fm_live_mcp import database,players,staff,world
from fm_live_mcp.bridge import Bridge


def main():
    b=Bridge(); sid=b.attach()['session_id']; counts=Counter(); tables_summary={}; failures=[]; samples={}; seen=0
    receipt={'observed_at':datetime.now(timezone.utc).isoformat()}
    try:
        with b._read_scope(sid):
            layouts=b._player_layout(b.process); base=layouts[0]-players.RVA[0]
            snap,save,_=b._world_state(b.process,layouts); receipt['save']=b._public_save(save)
            infos={kind:database.table(snap,base,kind) for kind in database.TABLES}; snap.verify()
        for kind,info in infos.items():
            summary=Counter(); different=[]
            for start in range(0,info['count'],500):
                with b._read_scope(sid):
                    # Memoize within one batch, then verify every consumed byte against memory.
                    raw_read=lambda a,n:b._read_memory(b.process,a,n)
                    memo={}
                    def read(a,n):
                        key=(a,n)
                        if key not in memo:memo[key]=raw_read(a,n)
                        return memo[key]
                    snap=world.ReadSet(read)
                    current=database.table(snap,base,kind)
                    assert current['identity']==info['identity'], 'table changed'
                    n=min(500,info['count']-start)
                    entries=struct.unpack(f'<{n}Q',snap(info['start']+start*8,n*8))
                    for index,address in enumerate(entries,start):
                        raw=snap(address,20); vt,stored_index,first,second=struct.unpack('<QIII',raw)
                        assert stored_index==index,(kind,index,'index mismatch')
                        summary['records']+=1
                        summary['equal_ids' if first==second else 'different_ids']+=1
                        if not first:summary['zero_primary']+=1
                        if first!=second and len(different)<5:different.append({'index':index,'primary':first,'secondary':second})
                        if kind!='people':continue
                        seen+=1
                        types={layouts[2]:('player',0x388),base+players.STAFF_RVA[2]:('player_staff',0x480),
                               base+staff.LAYOUTS['staff'][1]:('staff',staff.LAYOUTS['staff'][2]),
                               base+staff.LAYOUTS['human_manager'][1]:('human_manager',staff.LAYOUTS['human_manager'][2])}
                        if vt not in types:counts['other_person_types']+=1;continue
                        typ,offset=types[vt]; counts[typ]+=1
                        key='equal_ids' if first==second else 'different_ids'
                        counts[typ+'_'+key]+=1
                        try:
                            if typ in ('player','player_staff'):
                                row,identity=players.decode(snap,address-offset,layouts,include_profile=True)
                            else:row,identity=staff.decode(snap,base,address-offset)
                            counts[typ+'_decoded']+=1
                            if first!=second:samples.setdefault(typ,{'name':row['name'],'birth_date':row['birth_date'],'index':index})
                        except Exception as exc:
                            counts[typ+'_rejected']+=1
                            failures.append({'kind':typ,'index':index,'error':str(exc)})
                    for (a,n),data in memo.items():
                        assert raw_read(a,n)==data, f'{kind} batch changed'
                if kind=='people' and start%10000==0:print('people',seen,'failures',len(failures),flush=True)
            tables_summary[kind]={'counts':dict(summary),'different_samples':different}
            print(kind,dict(summary),flush=True)
        receipt['complete']=True
    finally:
        b.detach()
        receipt.update(person_counts=dict(counts),person_failures=failures,person_samples=samples,tables=tables_summary,
                       scope='Native typed tables; all supported regular/combined player profiles and staff identities. Read-only, batch rechecks; no UI or game functions.')
        (ROOT/'evidence/reader-assumptions-survey.json').write_text(json.dumps(receipt,indent=2)+'\n')
    print('complete',len(failures),'person decode failures',flush=True)


if __name__=='__main__':main()
