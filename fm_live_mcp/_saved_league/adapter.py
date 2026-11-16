"""Static composition of bounded competition-stat children."""
from . import suffix as old, stats_extended as stats, inline1260 as inline, statrow as leaf
from . import comp390 as parent, embedded, comp390rows as row
CTX=stats.CTX

def parse(data,start,*,limit=None,version=173,reference_context):
 children={0xf2f2d4:leaf.parse,0xf90a50:stats.parse}
 out=old.parse_prefix(data,start,limit=limit,version=version,reference_context=reference_context,child_readers=children)
 if out['complete']:return out
 if out['next_native_reader']!='0x11019a0' or out['stop_reason']!='Positive +1260 TEAM-bearing inline row':raise old.UnsupportedSuffix(int(out['next_native_reader'],16),out['end'],out['stop_reason'],out)
 limit=len(data)if limit is None else limit;at=out['end'];parts=out['parts']
 def take(n):
  nonlocal at
  if n<0 or at+n>limit:raise ValueError('Truncated suffix tail')
  q=at;at+=n;return bytes(data[q:at])
 def count(name):
  q=at;n=int.from_bytes(take(4),'little')
  if n>4096:raise ValueError('Suffix work budget exceeded')
  out['count_'+name]=n;out['count_'+name+'_offset']=q;return n
 for i in range(out['count_1260']):
  row=inline.parse(data,at,limit=limit,reference_context=reference_context)
  if type(row.get('end'))is not int or not at<row['end']<=limit:raise ValueError('Invalid inline row endpoint')
  parts.append(dict(native_field='1260',ordinal=i,start=at,end=row['end'],child=row));at=row['end']
 q=at;raw=take(11);parts.append(dict(native_fields='1308/1258/1317/130a/130c',start=q,end=at,raw_hex=raw.hex()))
 n=count('12c0');q=at;raw=take(n*17);parts.append(dict(native_field='12c0',start=q,end=at,count=n,raw17_rows_hex=raw.hex()))
 n=count('12d8')
 for i in range(n):
  q=at;person=take(4)
  if at>=limit:raise ValueError('Truncated TEAM marker')
  if data[at]!=0:raise old.UnsupportedSuffix(0x11019a0,at,'Positive +12D8 TEAM outside marker0 subset',out)
  team=take(5);raw=take(27);parts.append(dict(native_field='12d8',ordinal=i,start=q,end=at,person_hex=person.hex(),team_hex=team.hex(),raw27_hex=raw.hex()))
 n=count('12f0')
 for i in range(n):
  row=leaf.parse(data,at,limit=limit,version=version,reference_context=reference_context)
  if type(row.get('end'))is not int or not at<row['end']<=limit:raise ValueError('Invalid row endpoint')
  parts.append(dict(native_field='12f0',ordinal=i,start=at,end=row['end'],child=row));at=row['end']
 out.update(end=at,state='complete',complete=True,next_native_reader=None,stop_reason=None)
 return out

def make_reader():
 from functools import partial
 return partial(parent.parse,reference_context=CTX,owner_factory='game_comp_manager',embedded_reader=embedded.parse,row_reader=row.parse,suffix_reader=parse)
