"""Background discovery of native entry kinds; fresh production decode for samples."""
from collections import Counter
from datetime import datetime, timezone
import json,struct,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from fm_live_mcp import players,staff,world,database,contract_terms,wages
from fm_live_mcp.bridge import Bridge
b=Bridge();sid=b.attach()['session_id'];counts=Counter();samples={};seen=0;errors=[];expiry_sample=None
try:
 for lower in range(0,200000,5000):
  with b.lock,b._read_scope(sid):
   p=b.process;tables=b._player_layout(p);base=tables[0]-players.RVA[0];read=lambda a,n:b._read_memory(p,a,n)
   info=database.table(read,base,'people')
   if lower>=info['count']:break
   currency=wages.base_currency(read,base)
   layouts={base+v[1]:(k,v[2]) for k,v in staff.LAYOUTS.items()};layouts[base+players.RVA[2]]=('player',0x388)
   for start in range(lower,min(lower+5000,info['count']),1000):
    count=min(1000,lower+5000-start,info['count']-start)
    for index,person in enumerate(struct.unpack(f'<{count}Q',read(info['start']+start*8,count*8)),start):
     seen+=1;table=players.u64(read(person,8))
     if table not in layouts:counts['unsupported_person_type']+=1;continue
     kind,offset=layouts[table];contract=players.u64(read(person-0x98,8))
     if not contract:counts['null_contract']+=1;continue
     ct=players.u64(read(contract,8))
     if ct==base+world.TYPES['basic_contract'][0]:counts['basic_contract']+=1;continue
     if ct!=base+world.TYPES['full_contract'][0]:counts['other_contract']+=1;continue
     raw=read(contract,0x80)
     if players.u64(raw,8)!=person:raise ValueError('owner mismatch')
     first,end,capacity=struct.unpack_from('<QQQ',raw,0x68)
     if first==end==capacity==0:entries=[]
     else:
      if first<4096 or any(v%8 for v in (first,end,capacity)) or not first<=end<=capacity or capacity-first>256*8:raise ValueError('invalid vector')
      entries=list(struct.iter_unpack('<ihBB',read(first,end-first))) if first!=end else []
     counts['full_contract']+=1
     entry_kinds={e[2] for e in entries}
     for _,_,code,flags in entries:
      counts[f'entry_{code}']+=1
      if flags:counts['entries_with_flags']+=1
     needs_sample=bool(entry_kinds-set(samples))
     has_expiry=any(code in (0,16,17,18,27,31) and parameter>=0 for _,parameter,code,_ in entries)
     if needs_sample or (has_expiry and expiry_sample is None):
      snap=world.ReadSet(read)
      database.player_membership(snap,base,info,index,person-offset) if kind=='player' else database.staff_membership(snap,base,info,index,person-offset)
      row=players.decode(snap,person-offset,tables)[0] if kind=='player' else staff.decode(snap,base,person-offset)[0]
      result=contract_terms.decode(snap,base,person,currency);snap.verify()
      sample={'name':row['name'],'birth_date':row['birth_date'],'record_kind':kind,'database_index':index,'contract_terms':result}
      fresh_kinds={r['native_kind'] for r in result['terms']+result['unmapped_entries']}
      for code in fresh_kinds:samples.setdefault(code,sample)
      if has_expiry and any(r['values'].get('expiry',{}).get('date') for r in result['terms']):expiry_sample=sample
  print('scanned',seen,'full_contracts',counts['full_contract'],'kinds',sorted(samples),flush=True)
except Exception as exc:
 errors.append(str(exc));raise
finally:
 b.detach()
 result={'observed_at':datetime.now(timezone.utc).isoformat(),'seen':seen,'complete_native_table_scan':seen==info['count'],'native_person_count':info['count'],'counts':dict(counts),'samples':samples,'expiry_sample':expiry_sample,'errors':errors,'scope':'Best-effort survey counts; sample identities and production decodes rechecked. No UI or native execution.'}
 (ROOT/'evidence/contract-term-survey.json').write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps({'seen':seen,'counts':dict(counts),'sample_kinds':sorted(samples),'expiry_sample':None if expiry_sample is None else expiry_sample['name']}))
