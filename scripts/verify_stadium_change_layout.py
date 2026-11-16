"""Verify STADIUM_CHANGE native dispatch, dates, nulls and installed editor labels."""
from pathlib import Path
import sys,json,hashlib,re,xml.etree.ElementTree as ET
import zstandard
from datetime import datetime,timezone
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'scripts'))
from capstone import Cs,CS_ARCH_ARM64,CS_MODE_LITTLE_ENDIAN
from verify_player_profile_layout import property_case
from fm_live_mcp import players,world,stadium_changes,stadiums
from fm_live_mcp.bridge import Bridge
b=Bridge(); sid=b.attach()['session_id']
try:
 with b.lock,b._read_scope(sid):
  process=b._current(sid); layout=b._player_layout(process); base=layout[0]-players.RVA[0]
  p=Path(b.plugin_identity[0][0]); snapshot,save,_=b._world_state(process,layout)
  descriptor=world.pointer(snapshot,base+0x56d63c0); vt=world.pointer(snapshot,descriptor)
  assert vt==base+0x569ca88
  info=world.pointer(snapshot,vt-8); name=players.u64(snapshot(info+8,8))
  null_type=b'N6sicore17NULL_TYPED_TRAITSE'
  assert snapshot(name,len(null_type)+1)==null_type+b'\0'
  snapshot.verify();b._current(sid)
finally:b.detach()
cs=Cs(CS_ARCH_ARM64,CS_MODE_LITTLE_ENDIAN);spans=[]
with p.open('rb') as f:
 assert hashlib.file_digest(f,'sha256').hexdigest()==players.SHA256
 def read(a,n):f.seek(0x5ed4000+a);return f.read(n)
 def ptr(a):return int.from_bytes(read(a,8),'little')&0xffffffff
 for vt,name in ((0x55a1b98,b'N2db14DATABASE_TABLEINS_14STADIUM_CHANGEEEE'),(0x55bd8c0,b'N2db14STADIUM_CHANGEE')):
  assert read(vt-16,8)==bytes(8)
  assert read(ptr(ptr(vt-8)+8),len(name)+1)==name+b'\0'
 assert ptr(0x55bd8c0+24)==0x16d5c84
 code={i.address:f'{i.mnemonic} {i.op_str}'.strip() for i in cs.disasm(read(0x16d5c84,0x9e4),0x16d5c84)}
 fields={
  'Smot':(0x16d6014,['ldr x9, [x20, #0x18]']),
  'Sold':(0x16d6474,['ldr x9, [x20, #0x20]']),
  'Snew':(0x16d6134,['ldr x9, [x20, #0x28]']),
  'Salt':(0x16d64fc,['ldr x9, [x20, #0x48]']),
  'Slea':(0x16d640c,['bl #0x42f038c','ldrh w8, [x20, #0x30]','ldrh w9, [x20, #0x32]']),
  'Ssta':(0x16d62d8,['bl #0x42f038c','ldrh w8, [x20, #0x34]','ldrh w9, [x20, #0x36]']),
  'Slmd':(0x16d6340,['bl #0x42f038c','ldrh w8, [x20, #0x38]','ldrh w9, [x20, #0x3a]']),
  'Scap':(0x16d5db4,['ldr w20, [x20, #0x3c]']),
  'Sscp':(0x16d5d00,['ldr w20, [x20, #0x40]']),
  'Sceb':(0x16d6508,['ldr w20, [x20, #0x44]']),
  'Snxa':(0x16d6274,['ldr w20, [x20, #0x50]']),
  'Snmn':(0x16d614c,['ldr w20, [x20, #0x54]']),
  'Snmx':(0x16d5e58,['ldr w20, [x20, #0x58]']),
  'Stks':(0x16d6498,['ldr w20, [x20, #0x5c]']),
  'Scam':(0x16d63a8,['ldr w20, [x20, #0x60]']),
  'Styp':(0x16d5f90,['ldrsb w20, [x20, #0x64]']),
  'Slhm':(0x16d5efc,['ldrsb w20, [x20, #0x66]']),
  'ScTL':(0x16d604c,['ldrsb w20, [x20, #0x67]']),
  'ScYL':(0x16d61b0,['ldrsb w20, [x20, #0x68]']),
  'Scns':(0x16d60d0,['ldrsb w20, [x20, #0x69]']),
  'Scpm':(0x16d6214,['ldrb w20, [x20, #0x65]','bl #0x4403cd4','add x0, x0, #0x18','ubfx w8, w20, #2, #1'])}
 for prop,(case,instructions) in fields.items():
  assert property_case(code,prop,0x16d5ca0,'w1')==case,prop
  assert [code[case+i*4] for i in range(len(instructions))]==instructions,prop
  if prop not in ('Smot','Sold','Snew','Salt','Slea','Ssta','Slmd','Scpm'):
   assert code[case+4]=='cmn w20, #1' and code[case+8]=='b.eq #0x16d656c'
  spans.append({'property':prop,'rva':hex(case),'instructions':instructions})
 for prop in ('Slea','Ssta','Slmd'):
  case=fields[prop][0]
  assert [code[case+i*4] for i in range(3,7)]==['lsr w10, w8, #9','orr w9, w10, w9, lsl #17','bfi w9, w8, #8, #9','str w9, [sp, #8]']
 assert [code[0x16d6590+i*4] for i in range(6)]==['ldr x0, [x20]','ldr x8, [x0]','ldr x8, [x8, #0x20]','mov x1, x20','mov x2, x19','blr x8']
 assert code[0x16d656c]=='adrp x20, #0x56d6000' and code[0x16d6570]=='add x20, x20, #0x3c0'
archive=(p.parent.parent/'Resources/shared/data/editor.fmf').read_bytes(); definitions={}
for match in re.finditer(re.escape(bytes.fromhex('28b52ffd')),archive):
 try:root=ET.fromstring(zstandard.ZstdDecompressor().decompress(archive[match.start():],max_output_size=10000000))
 except(zstandard.ZstdError,ET.ParseError):continue
 for row in root.iter('record'):
  field=row.find("flags[@id='field']")
  if field is not None and field.get('value') in fields:definitions[field.get('value')]=row
# Smot is supplied by the native owner relationship, not the editor's change subrecord.
assert set(definitions)==set(fields)-{'Smot'}
def label(row):return row.find("translation[@id='name']").get('value').split('[COMMENT')[0]
def enum(prop):return {int(r.get('enum')):label(r) for r in definitions[prop].find("list[@id='enum_values']")}
assert enum('Styp')==stadium_changes.TYPES
assert enum('Scns')==stadiums.CONDITIONS
for prop,expected in (('Slea','Start Date'),('Ssta','Leave Date'),('Slmd','Latest Move Date'),('Stks','Expected Season Tickets Sold')):
 assert label(definitions[prop])==expected
for prop in ('Stks','Scam'):
 assert definitions[prop].find("boolean[@id='store_pence']").get('value')=='true'
assert definitions['Sceb'].find("boolean[@id='store_pence']") is None
for prop,lo,hi in (('Slhm',1,100),('ScTL',0,20),('ScYL',0,20)):
 assert definitions[prop].find("integer[@id='min_value']").get('value')==str(lo)
 assert definitions[prop].find("integer[@id='max_value']").get('value')==str(hi)
receipt={'verified':True,'plugin_sha256':players.SHA256,'observed_at':datetime.now(timezone.utc).isoformat(),
 'fields':spans,'type_labels':enum('Styp'),'condition_labels':enum('Scns'),'sentinel_type':null_type.decode(),
 'editor_sha256':hashlib.sha256(archive).hexdigest(),'editor_labels':{prop:label(row) for prop,row in definitions.items()},
 'unknown_units':['rental_cash','future_development_fund','expected_season_tickets_sold'],
 'scope':'Native getter dispatch, signed fields, date packing, null descriptor, type/table RTTI and installed editor labels. No native getter execution. Currency units, season-ticket scale, type-2 label and contextual activity/completion remain unverified.',
 'foreground_ui_used':False,'native_execution':False}
(ROOT/'evidence/stadium-change-layout-verification.json').write_text(json.dumps(receipt,indent=2)+'\n')
print('Verified',len(fields),'stadium-change properties, signed -1 null routes, date packing and editor labels.')
