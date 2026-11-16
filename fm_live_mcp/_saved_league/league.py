"""Bounded saved LEAGUE_STAGE prefix and original row order; no freshness claim."""
class UnsupportedLeague(ValueError):
 def __init__(self,native,offset,reason,partial=None):
  self.native,self.offset,self.reason,self.partial=native,offset,reason,partial
  super().__init__(f'Unsupported LEAGUE_STAGE child {hex(native)} at {offset}: {reason}')

def parse_prefix(data,start,*,limit=None,child_readers=None):
 limit=len(data)if limit is None else limit
 if type(start)is not int or type(limit)is not int or not 0<=start<=limit<=len(data):raise ValueError('Invalid stage bounds')
 child_readers={}if child_readers is None else child_readers;at=start;parts=[]
 def take(n):
  nonlocal at
  if n<0 or at+n>limit:raise ValueError('Truncated league stage')
  p=at;at+=n;return bytes(data[p:at])
 def value(n):return int.from_bytes(take(n),'little')
 def raw(name,n):
  p=at;r=take(n);parts.append(dict(native_field=name,start=p,end=at,raw_hex=r.hex()));return r
 def stop(native,reason):return dict(start=start,end=at,state='stopped',complete=False,next_native_reader=hex(native),stop_reason=reason,parts=parts,native_order_view_code=view)
 def child(native,name):
  nonlocal at
  cb=child_readers.get(native)
  if cb is None:return False
  p=at;out=cb(data,at,limit=limit)
  if not isinstance(out,dict)or type(out.get('end'))is not int or not at<out['end']<=limit or out.get('state')=='stopped' or out.get('complete')is False:raise ValueError('Invalid or partial child endpoint')
  at=out['end'];parts.append(dict(native_child=hex(native),field=name,start=p,end=at,value=out));return True
 view=value(1);raw('104',1);raw('1c0',4);raw('1c8',2);raw('103',1)
 n=value(4)
 if n>4096:raise ValueError('Byte vector exceeds work budget')
 raw('a8_values',n)
 cup_flag=value(1);parts.append(dict(native_field='optional_1b8',raw=cup_flag))
 if cup_flag==1 and not child(0x3c73aa0,'1b8'):return stop(0x3c73aa0,'Optional embedded CUP_STAGE')
 settings_flag=value(1);parts.append(dict(native_field='optional_f0',raw=settings_flag))
 if settings_flag and not child(0x3ef0568,'f0'):return stop(0x3ef0568,'LEAGUE_SETTINGS needed before stored table')
 raw('102',1);count_start=at;n=int.from_bytes(take(1),'little',signed=True)
 if n<0:raise ValueError('Negative stored league-team count')
 rows=[]
 for i in range(n):
  p=at
  if not child(0x3f4ebec,f'c0_row_{i}'):
   out=stop(0x3f4ebec,'First unresolved stored league-team row');out.update(row_count=n,row_index=i,rows=rows,count_offset=count_start);return out
  rows.append(dict(native_row_index=i,start=p,end=at,value=parts[-1]['value']))
 out=stop(0x3eefa74,'Stored C0 table consumed; remaining stage body unparsed');out.update(row_count=n,rows=rows,count_offset=count_start);return out

def parse(data,start,**kwargs):
 out=parse_prefix(data,start,**kwargs)
 if out['complete']:return out
 raise UnsupportedLeague(int(out['next_native_reader'],16),out['end'],out['stop_reason'],out)
