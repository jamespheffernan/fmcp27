"""Verify native label dispatch/accessor offline; optional capstone dependency, no game attachment."""
from pathlib import Path
import hashlib,json,re,struct
from capstone import Cs,CS_ARCH_ARM64,CS_MODE_LITTLE_ENDIAN
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from fm_live_mcp import playing_time,players
HERE=Path(sys.argv[1]) if len(sys.argv)>1 else Path('evidence/batches/live-playing-time-promises-162')
HERE.mkdir(parents=True,exist_ok=True)
from fm_live_mcp import build_paths
P=build_paths.pinned_path(build_paths.PLUGIN_IN_APP)  # the pinned build
raw=P.read_bytes();code=raw[0x5ed4000:]
cs=Cs(CS_ARCH_ARM64,CS_MODE_LITTLE_ENDIAN)
resource=P.parent.parent/'Resources/data/game_simulation/templates/user_folder/languages/example.ltf'
labels={int(m[1]):m[2] for m in re.finditer(r'^KEY-(\d+): (.*)',resource.read_text(),re.M)}
def ins(at,n=48):return list(cs.disasm(code[at:at+n],at))
def immediate(at,reg,initial=0):
 value=initial
 for i in ins(at):
  parts=i.op_str.split(', ')
  if i.mnemonic=='mov' and parts[0]==reg and parts[1].startswith('#'):value=int(parts[1][1:],0)
  elif i.mnemonic=='movk' and parts[0]==reg:
   shift=int(parts[2].split('#')[1],0)if len(parts)>2 else 0
   value=(value&~(65535<<shift))|(int(parts[1][1:],0)<<shift)
  elif i.mnemonic=='bl':return value
  elif i.mnemonic=='b':return value
 return value
out=[]
for native in range(25):
 target=0x172ad94+4*code[0x53a1560+native]
 record=immediate(target,'w1',0xc80)
 row={'native_code':native,'playing_time_dispatch':hex(target)}
 if target!=0x172ad9c:
  row['player_type_id']=record
  if 0xc80<=record<=0xc95:
   dest=0x15594f4+4*struct.unpack_from('<H',code,0x539d01c+2*(record-0xc80))[0]
   translation=immediate(dest,'w1');text=labels.get(translation)
   row.update(player_type_label_dispatch=hex(dest),translation_id=translation,english_text=text)
 else:row['state']='contextual_direct_label_branch'
 out.append(row)
assert hashlib.sha256(raw).hexdigest()==players.SHA256, 'Unsupported native build'
assert hashlib.sha256(resource.read_bytes()).hexdigest()==playing_time.ENGLISH_RESOURCE_SHA256, 'English resource changed'
assert [(i.mnemonic,i.op_str) for i in ins(0x1005c78,8)]==[('ldrb','w0, [x0, #0x54]'),('ret','')]
assert struct.unpack_from('<Q',code,0x55abd68+32*8)[0]&0xffffffff==0x1005c78
for native,(player_type,translation,title) in playing_time.LABELS.items():
 row=out[native]
 assert row['player_type_id']==player_type and row['translation_id']==translation
 assert row['english_text'].split('[')[0]==title
result={'verified':True,'plugin_sha256':hashlib.sha256(raw).hexdigest(),'english_resource_sha256':hashlib.sha256(resource.read_bytes()).hexdigest(),'rows':out}
(HERE/'official-label-map.json').write_text(json.dumps(result,indent=2,ensure_ascii=False)+'\n')
for row in out:print(row['native_code'],row.get('player_type_id'),row.get('translation_id'),(row.get('english_text')or row.get('state')or'').split('[COMMENT')[0])
