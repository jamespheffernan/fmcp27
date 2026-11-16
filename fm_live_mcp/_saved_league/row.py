"""Complete bounded league-row transport, current521 conditional profile."""
import struct
from . import row_prefix as P
CTX=P.CTX

def parse(data,start,*,limit=None,reference_context,version=521,max_items=4096,_depth=0):
 if type(max_items)is not int or not 0<=max_items<=4096 or _depth>16:raise ValueError('Row work budget exceeded')
 out=P.parse_prefix(data,start,limit=limit,reference_context=reference_context,version=version);at=out['end'];limit=len(data)if limit is None else limit;parts=[]
 def take(n):
  nonlocal at
  if n<0 or n>limit-at:raise ValueError('Truncated league row')
  raw=bytes(data[at:at+n]);at+=n;return raw
 def num(fmt):return struct.unpack('<'+fmt,take(struct.calcsize('<'+fmt)))[0]
 def statsblock():
  p=at;marker=num('B')
  if marker not in(0,1):raise P.UnsupportedRow(0x11019a0,p,'Unsupported paired-stat reference')
  index=num('i')
  if marker==1 and index!=-1:take(4)
  take(12);return dict(start=p,end=at,raw_hex=bytes(data[p:at]).hex())
 flag=num('B');paired=[];paircount=None
 if flag:
  paircount=num('b')
  for i in range(max(paircount,0)):
   paired.append([statsblock(),statsblock()])
 #521>=514 includes EB; earlier-version synthesis is deliberately unsupported.
 raw_tail=take(13)
 common_end=at
 n=num('h')
 if n>max_items:raise ValueError('History byte count exceeds budget')
 history=take(max(n,0));recordcount=num('b');records=take(max(recordcount,0)*8)
 optional=num('B');optional_rows=[]
 if optional==1:
  count=num('I')
  if count>max_items:raise ValueError('Optional B0 vector exceeds budget')
  optional_rows=[take(4).hex()for _ in range(count)]
 controls=take(10);nested_marker=num('B');nested=None
 if nested_marker==1:
  nested=parse(data,at,limit=limit,reference_context=reference_context,version=version,max_items=max_items,_depth=_depth+1);at=nested['end']
 out.update(end=at,state='complete_row',complete=True,complete_stage=False,next_native_reader=None,stop_reason=None,common_end=common_end,paired_statistics_marker=flag,paired_statistics_count=paircount,paired_statistics=paired,unmapped_common_tail_hex=raw_tail.hex(),history_byte_count_i16=n,history_raw_hex=history.hex(),unmapped_record_count_i8=recordcount,unmapped_records_hex=records.hex(),optional_b0_marker=optional,optional_b0_rows=optional_rows,unmapped_control_bytes_hex=controls.hex(),nested_row_marker=nested_marker,nested_row=nested)
 return out
