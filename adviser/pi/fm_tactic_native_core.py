"""Execute isolated installed ARM64 loader predicates; no native process/game calls."""
from pathlib import Path
import struct,json,hashlib,os
from unicorn import Uc,UC_ARCH_ARM64,UC_MODE_ARM,UC_HOOK_CODE,UC_HOOK_MEM_INVALID,UC_MEM_FETCH_UNMAPPED
from unicorn.arm64_const import *
P=Path(os.environ.get('PI_FM_NATIVE_BINARY',str(Path.home()/'Library/Application Support/Steam/steamapps/common/Football Manager 27/fm.app/Contents/PlugIns/game_plugin.bundle/Contents/MacOS/game_plugin')))

def body(payload):
 payload=bytes(payload)
 u=Uc(UC_ARCH_ARM64,UC_MODE_ARM);u.ctl_set_cpu_model(UC_CPU_ARM64_MAX)
 for base,size in[(0x4856000,0x2000),(0x4383000,0x1000),(0x486b000,0x1000),(0x54b0000,0x1000),(0x56c1000,0x1000),(0x56a4000,0x1000),(0x56d5000,0x1000),(0x100600000,0x1000),(0x100700000,0x100000),(0x4355000,0x1000),(0x100100000,0x20000),(0x100300000,0x1000),(0x100400000,0x10000),(0x100500000,0x1000)]:u.mem_map(base,size)
 with P.open('rb')as f:f.seek(0x5ed4000+0x4856000);code=f.read(0x2000)
 u.mem_write(0x4856000,code)
 with P.open('rb')as f:
  for a in(0x4383000,0x486b000):f.seek(0x5ed4000+a);u.mem_write(a,f.read(0x1000))
 u.mem_write(0x54b05b0,struct.pack('<Q',0x100600000));u.mem_write(0x100600000,struct.pack('<Q',0x11223344));u.mem_write(0x56c1628,struct.pack('<Q',8192));u.mem_write(0x56c1910,b'\x01');u.mem_write(0x56d5f70,struct.pack('<Q',0x100780004));u.mem_write(0x100780000,struct.pack('<II',65536,0))
 u.mem_write(0x100300000,struct.pack('<Q',0x100300100));u.mem_write(0x100300200,struct.pack('<Q',0x100300000))
 for off,fn in[(0x18,0x100500000),(0x30,0x100500100),(0x20,0x100500200)]:u.mem_write(0x100300100+off,struct.pack('<Q',fn))
 u.reg_write(UC_ARM64_REG_SP,0x100110000);u.reg_write(UC_ARM64_REG_X0,0x100400000);u.reg_write(UC_ARM64_REG_X1,0x100300200);u.reg_write(UC_ARM64_REG_X2,1)
 state={'cursor':8,'reads':[],'stop':'instruction_budget_exhausted','instructions':0,'heap':0x100700000}
 def hook(uc,at,size,data):
  state['last_pc']=hex(at);state['instructions']+=1
  if at==0x4856e64:state['stop']='full_native_body_return';state['body_return']=uc.reg_read(UC_ARM64_REG_W0);uc.emu_stop()
  if at==0x486b200:state['vector_start']=state['cursor']
  if at==0x486b0c0:
   state['stage']='native_names_mentality_and_instruction_vector_loaded';state['vector_return']=uc.reg_read(UC_ARM64_REG_W0);flags=int.from_bytes(bytes(uc.mem_read(0x1004000e0,16)),'little');state['flags72']=bool(flags&(1<<72));state['flags73']=bool(flags&(1<<73));state['instruction_flag_bytes_hex']=bytes(uc.mem_read(0x1004000e0,16)).hex();state['mentality']=uc.mem_read(0x100400105,1)[0];state['names']=[]
   for offset in(0x790,0x798,0x7a0,0x7a8):
    handle=struct.unpack('<Q',uc.mem_read(0x100400000+offset,8))[0];n=struct.unpack('<I',uc.mem_read(handle,4))[0];state['names'].append(bytes(uc.mem_read(handle+4,n)).decode('utf8'))
  elif at in(0x4355a04,0x4aee720,0x4aee72c):
   size=uc.reg_read(UC_ARM64_REG_X1 if at==0x4355a04 else UC_ARM64_REG_X0);assert 0<=size<=65536;pointer=state['heap'];state['heap']+=((size+15)//16)*16;assert state['heap']<0x100780000;uc.reg_write(UC_ARM64_REG_X0,pointer);uc.reg_write(UC_ARM64_REG_PC,uc.reg_read(UC_ARM64_REG_LR))
  elif at in(0x4aeedb0,0x4aeedbc):
   dest=uc.reg_read(UC_ARM64_REG_X0);src=uc.reg_read(UC_ARM64_REG_X1);n=uc.reg_read(UC_ARM64_REG_X2);assert n<=65536
   if n:uc.mem_write(dest,bytes(uc.mem_read(src,n)))
   uc.reg_write(UC_ARM64_REG_PC,uc.reg_read(UC_ARM64_REG_LR))
  elif at in(0x4aee708,0x4355ed4):uc.reg_write(UC_ARM64_REG_PC,uc.reg_read(UC_ARM64_REG_LR))
  elif at in(0x100500000,0x100500100,0x100500200):
   if at==0x100500000:uc.reg_write(UC_ARM64_REG_X0,state['cursor'])
   elif at==0x100500200:state['cursor']=uc.reg_read(UC_ARM64_REG_X1);uc.reg_write(UC_ARM64_REG_X0,0)
   else:
    dest=uc.reg_read(UC_ARM64_REG_X1);n=uc.reg_read(UC_ARM64_REG_X2);assert n<=65536;start=state['cursor'];raw=payload[start:start+n]
    if len(raw)!=n:uc.mem_write(0x100300010,struct.pack('<I',1));raw=raw.ljust(n,b'\0')
    uc.mem_write(dest,raw);state['reads'].append({'offset':start,'length':n});state['cursor']+=n;uc.reg_write(UC_ARM64_REG_X0,n)
   uc.reg_write(UC_ARM64_REG_PC,uc.reg_read(UC_ARM64_REG_LR))
 def missing(uc,access,address,size,value,data):
  if access==UC_MEM_FETCH_UNMAPPED and 0x1000<=address<0x4af0000:
   page=address&~4095
   with P.open('rb')as f:f.seek(0x5ed4000+page);raw=f.read(4096)
   uc.mem_map(page,4096);uc.mem_write(page,raw);return True
  state['missing_dependency']=dict(access=access,address=hex(address),length=size,pc=hex(uc.reg_read(UC_ARM64_REG_PC)));return False
 u.hook_add(UC_HOOK_MEM_INVALID,missing)
 u.hook_add(UC_HOOK_CODE,hook)
 try:u.emu_start(0x4856b6c,0,count=2000000)
 except Exception as exc:state['execution_error']=str(exc);state['stop']='unavailable_dependency'
 state['schema']=struct.unpack_from('<h',payload,9)[0];state['source_sha256']=hashlib.sha256(payload).hexdigest();return state

def outer(payload):
 payload=bytes(payload)
 u=Uc(UC_ARCH_ARM64,UC_MODE_ARM);u.ctl_set_cpu_model(UC_CPU_ARM64_MAX);u.mem_map(0x485b000,0x1000);u.mem_map(0x100100000,0x1000)
 with P.open('rb')as f:f.seek(0x5ed4000+0x485b000);u.mem_write(0x485b000,f.read(0x1000))
 u.reg_write(UC_ARM64_REG_SP,0x100100100);u.mem_write(0x100100114,payload[6:8]);state={}
 def hook(uc,at,size,data):
  if at in(0x485b794,0x485b7b0):state['accepted']=at==0x485b7b0;uc.emu_stop()
 def missing(uc,access,address,size,value,data):
  if access==UC_MEM_FETCH_UNMAPPED and 0x1000<=address<0x4af0000:
   page=address&~4095
   with P.open('rb')as f:f.seek(0x5ed4000+page);raw=f.read(4096)
   uc.mem_map(page,4096);uc.mem_write(page,raw);return True
  state['missing_dependency']=dict(access=access,address=hex(address),length=size,pc=hex(uc.reg_read(UC_ARM64_REG_PC)));return False
 u.hook_add(UC_HOOK_MEM_INVALID,missing)
 u.hook_add(UC_HOOK_CODE,hook);u.emu_start(0x485b788,0,count=20);return state



def payload_header(payload):
 """Run installed generic header reader through exact signature/version reads."""
 u=Uc(UC_ARCH_ARM64,UC_MODE_ARM);u.ctl_set_cpu_model(UC_CPU_ARM64_MAX)
 for base,size in[(0x4319000,0x1000),(0x437e000,0x1000),(0x100100000,0x20000),(0x100300000,0x1000),(0x100410000,0x1000),(0x100500000,0x1000)]:u.mem_map(base,size)
 with P.open('rb')as f:f.seek(0x5ed4000+0x4319000);u.mem_write(0x4319000,f.read(0x1000))
 u.mem_write(0x100300000,struct.pack('<Q',0x100300100));u.mem_write(0x100300200,struct.pack('<Q',0x100300000));u.mem_write(0x100410000,struct.pack('<Q',0x080100004e554c4c))
 for off,fn in[(0x30,0x100500100),(0x10,0x100500300)]:u.mem_write(0x100300100+off,struct.pack('<Q',fn))
 for reg,value in[(UC_ARM64_REG_SP,0x100110000),(UC_ARM64_REG_X0,0x100410000),(UC_ARM64_REG_X1,0x100300200),(UC_ARM64_REG_X2,0x2e746163),(UC_ARM64_REG_X3,0),(UC_ARM64_REG_X8,0x100300300)]:u.reg_write(reg,value)
 state={'cursor':0,'accepted':False}
 def hook(uc,at,size,data):
  if at==0x431966c:state['reason']='native_header_rejection';uc.emu_stop()
  elif at==0x437eed0:
   state.update(accepted=True,segment_start=uc.reg_read(UC_ARM64_REG_X1),segment_length=uc.reg_read(UC_ARM64_REG_X2),version=struct.unpack('<H',uc.mem_read(0x100410004,2))[0]);uc.emu_stop()
  elif at in(0x100500100,0x100500300):
   if at==0x100500300:uc.reg_write(UC_ARM64_REG_X0,len(payload))
   else:
    dest=uc.reg_read(UC_ARM64_REG_X1);n=uc.reg_read(UC_ARM64_REG_X2);assert n<=65536;start=state['cursor'];raw=payload[start:start+n]
    if len(raw)!=n:uc.mem_write(0x100300010,struct.pack('<I',1));raw=raw.ljust(n,b'\0')
    uc.mem_write(dest,raw);state['cursor']+=n;uc.reg_write(UC_ARM64_REG_X0,n)
   uc.reg_write(UC_ARM64_REG_PC,uc.reg_read(UC_ARM64_REG_LR))
 u.hook_add(UC_HOOK_CODE,hook);u.emu_start(0x431957c,0,count=1000);return state

EXPECTED_NATIVE_SHA256='774cacde63567fd3901c47719e7a6ed94cc3a0a62e9b94989dcac6b4890ec0e1'

class UnsupportedBuildError(ValueError):pass
_VERIFIED_IDENTITY=None

def verify_native_binary():
 global _VERIFIED_IDENTITY
 try:
  status=P.stat();identity=(str(P),status.st_dev,status.st_ino,status.st_size,status.st_mtime_ns,status.st_ctime_ns)
 except OSError as exc:raise UnsupportedBuildError('FM27nativebinary unavailable')from exc
 if identity==_VERIFIED_IDENTITY:return EXPECTED_NATIVE_SHA256
 with P.open('rb')as f:actual=hashlib.file_digest(f,'sha256').hexdigest()
 if actual!=EXPECTED_NATIVE_SHA256:raise UnsupportedBuildError('Unsupported FM27nativebinary; no predicate result accepted')
 _VERIFIED_IDENTITY=identity
 return actual


def validate_payload(payload, *, controls=True):
 verify_native_binary()
 if not isinstance(payload,bytes)or not 16<=len(payload)<=1000000:raise ValueError('Expected bounded standalone .tac payload bytes')
 result=body(payload);envelope=outer(payload);header=payload_header(payload)
 accepted=result.get('stop')=='full_native_body_return'and result.get('body_return')==1 and result['cursor']==len(payload)and envelope.get('accepted')is True and header.get('accepted')is True and header.get('segment_start')==8
 compact=dict(accepted=accepted,native_body_return=result.get('body_return'),cursor=result['cursor'],payload_bytes=len(payload),consumed_exact_eof=result['cursor']==len(payload),name=(result.get('names')or[None])[0],mentality_id=result.get('mentality'),flags72=result.get('flags72'),flags73=result.get('flags73'),actual_instructions=result['instructions'],heap_bytes=result['heap']-0x100700000,stop=result['stop'],missing_dependency=result.get('missing_dependency'),payload_sha256=hashlib.sha256(payload).hexdigest(),outer_version_guard=envelope.get('accepted'),native_payload_header=header)
 if controls:
  bad=bytearray(payload);bad[9:11]=struct.pack('<h',36);low=body(bytes(bad));truncated=body(payload[:-1]);old=bytearray(payload);old[6:8]=struct.pack('<H',29)
  magic=bytearray(payload);magic[2]^=1
  compact['negative_controls']=dict(magic_rejected=payload_header(bytes(magic)).get('accepted')is False,schema36_rejected=low.get('body_return')==0,truncated_last_byte_rejected=truncated.get('body_return')==0,outer29_rejected=outer(bytes(old)).get('accepted')is False)
  if not all(compact['negative_controls'].values()):raise ValueError('Native loader negative control failed')
 return compact

def main():
 import argparse
 parser=argparse.ArgumentParser(description='Optional isolated ARM64FM27 tacticalbody load validation; no game process or UI')
 parser.add_argument('--manifest',type=Path,required=True);parser.add_argument('--output',type=Path,required=True);args=parser.parse_args()
 try:digest=verify_native_binary()
 except UnsupportedBuildError as exc:
  args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(json.dumps(dict(state='unsupported_build',reason=str(exc),expected_sha256=EXPECTED_NATIVE_SHA256),indent=2)+'\n');print('unsupported_build');raise SystemExit(2)
 source=json.loads(args.manifest.read_text());variants=source['variants']if isinstance(source,dict)else source
 if not 1<=len(variants)<=100:raise ValueError('Select1–100payloads')
 rows=[]
 for item in variants:
  payload=Path(item['payload_path']).read_bytes()
  if item.get('payload_sha256')and hashlib.sha256(payload).hexdigest()!=item['payload_sha256']:raise ValueError('Manifest payload fingerprint disagrees')
  r=validate_payload(payload);requested=item.get('requested')or{};r.update(source_path=item.get('source_path'),output_path=item.get('output_path'),payload_path=item['payload_path'],requested=requested)
  if requested:
   flags=requested.get('team_tackling_flags')
   if isinstance(flags,int):flags={'72':bool(flags&1),'73':bool(flags&2)}
   flags=flags or{}
   checks={'name':r['name']==requested['name'],'mentality':r['mentality_id']==requested['mentality_id']}
   for key,value in flags.items():
    if str(key)in('72','73'):checks['flag'+str(key)]=r['flags'+str(key)]==value
   r['requested_values_match']=checks
  rows.append(r)
  args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(json.dumps(dict(state='running',rows=rows),indent=2)+'\n')
 verify_native_binary()
 out=dict(state='passed'if all(r['accepted']and all(r.get('requested_values_match',{}).values())for r in rows)else'rejected',native_binary=str(P),native_binary_sha256=digest,validator_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),rows=rows,heap_map_bytes=1048576,instruction_limit=2000000,profile=dict(string_limit=8192,string_conversion_callback=None,creator_initial_storage='zero initialized',mocked_services=['boundedinputstreamread/seek/tell','memoryallocation/deallocation','memcpy/memmove'],native_parser_callbacks_mocked=False),scope='Actualinstallednativebodyreader4856B6C throughreturn and exactEOF plusnativegenericpayloadheader/outerversionguard; FMFarchive decoding/encryption outside this validator; no liveprocesscalls/UI/import or career mutation')
 args.output.write_text(json.dumps(out,indent=2)+'\n');print(out['state'],len(rows),'payloads;fullnativebody+EOF;independentnegativecontrols')
 if out['state']!='passed':raise SystemExit(1)

if __name__=='__main__':main()
