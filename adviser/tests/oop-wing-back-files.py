"""One real FM27 OOP right-wing-back donor edit and public semantic refusals."""
import importlib.util,json,struct,sys,tempfile
from pathlib import Path
spec=importlib.util.spec_from_file_location('tactic_files',sys.argv[1]);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
root=Path(tempfile.mkdtemp(prefix='oop-wing-back-',dir=Path(__file__).resolve().parents[1]/'tmp'));m.OUTPUTS=root/'outputs'
source=m.TEMPLATES/'3421 FM27 Att.fmf';donor=m.TEMPLATES/'3421 FM27 .fmf'
_,sb,sm=m.read_template(str(source));_,db,dm=m.read_template(str(donor));st,dt=sm['.tac'],dm['.tac']
assert m.sha(sb)=='0db6aa597ebe0b826e5aefcc6e0527a5acbbd1b6a6c2a27aa1f7b5d48d8964bb'
assert m.sha(db)=='52b19d08c643f9145a59c0e17b36bb1961693ea007231dfc182a4d1232979e40'
a=m.phase_records(st)['out_of_possession'][4];b=m.phase_records(dt)['out_of_possession'][4]
assert a['native_role_word']=='0000000000402000' and b['native_role_word']=='0000000000201000'
role=dict(phase='out_of_possession',position_index=4,donor_position_index=4,donor_template_path=str(donor),donor_template_sha256=m.sha(db))
params=dict(template_path=str(source),template_sha256=m.sha(sb),name='Native OOP Right Wing Back Defend',base_role=role)
refusals=0;artifacts=[]

def refuse(request,fragment):
 global refusals
 before=sorted(m.OUTPUTS.rglob('*'))
 try:m.generate(request)
 except (ValueError,FileExistsError) as error:assert fragment in str(error),str(error)
 else:raise AssertionError('Unsupported OOP wing-back edit accepted')
 assert sorted(m.OUTPUTS.rglob('*'))==before
 refusals+=1

def raw_records(tac):
 return {(phase,i):tac[r['record_offset']:r['record_end_exclusive']] for phase,records in m.phase_records(tac).items() for i,r in enumerate(records)}

def preserve(result,members,source_name,new_name,expected_tac=None):
 _,_,out=m.read_template(result['output_path']);tac=out['.tac'];record=m.phase_records(tac)['out_of_possession'][4]
 assert tac[record['record_offset']:record['record_end_exclusive']]==dt[b['record_offset']:b['record_end_exclusive']]
 before_records=raw_records(members['.tac']);after_records=raw_records(tac)
 assert len(before_records)==len(after_records)==22
 assert sum(before_records[k]==after_records[k] for k in before_records)==21
 restored=m.replace_tac_name(tac,source_name)
 old=m.phase_records(members['.tac'])['out_of_possession'][4]['role_word_offset']
 assert struct.unpack_from('<Q',restored,old)[0]==0x201000
 restored=restored[:old]+struct.pack('<Q',0x402000)+restored[old+8:]
 assert restored==(members['.tac'] if expected_tac is None else expected_tac)
 assert set(members)==set(out) and all(members[k]==out[k] for k in members if k not in ('.tac','.aom'))
 assert m.replace_string(out['.aom'],12+len(b'TACTICS_TYPE_HANDLER'),source_name,new_name)==members['.aom']
 assert result['base_role']['before']['role']=='Pressing Wing-Back' and result['base_role']['after']['role']=='Wing-Back'
 assert result['base_role']['before']==dict(role='Pressing Wing-Back',native_role_word='0000000000402000') and result['base_role']['after']==dict(role='Wing-Back',native_role_word='0000000000201000')
 assert result['verification']['all_unrequested_tactic_bytes_preserved'] is True
 assert result['verification']['game_load_verified'] is False
 assert json.loads(Path(result['receipt_path']).read_text())==result
 artifacts.append(result['output_path'])

preview=m.generate(params|dict(preview=True));assert preview['files_created'] is False and not m.OUTPUTS.exists()
summary=m.summarize(str(source));assert dict(phase='out_of_possession',position_index=4,position='WB(R)') in summary['base_role_cases']
result=m.generate(params);preserve(result,sm,summary['name'],params['name'])
positive=dict(source=str(source),source_sha256=m.sha(sb),donor=str(donor),donor_sha256=m.sha(db),output=result['output_path'],output_sha256=result['output_sha256'])
# Omission inherits this source's actual pressing role, never crediting it as changed.
inherited=m.generate({k:v for k,v in params.items() if k!='base_role'}|dict(name='Inherited OOP Right Wing Back'))
_,_,inherit_members=m.read_template(inherited['output_path'])
assert m.replace_tac_name(inherit_members['.tac'],summary['name'])==st
assert inherited['base_role_mode']=='inherit' and inherited['base_role'] is None
# Combine with current controls; assemble the exact expected non-role changes.
combined_params=params|dict(name='OOP Role With Low Crosses And Lower Tempo',crossing_style='Low Crosses',tempo='Lower Tempo')
combined=m.generate(combined_params)
expected=bytearray(st);at=m.parse_tac_plaintext(st)['pre_style_setup']['team_instruction_vector_candidate_offset'];flags=int.from_bytes(st[at:at+12],'little')
expected[at:at+12]=((flags&~((7<<10)|(15<<46)))|(1<<12)|(1<<48)).to_bytes(12,'little')
preserve(combined,sm,summary['name'],combined_params['name'],bytes(expected))
# Different archive names/other stored bytes do not imply a new role or allowlist.
variant=m.generate(dict(template_path=str(source),template_sha256=m.sha(sb),name='Unlisted OOP Native Source Variant',team_width='Narrower'))
vp=Path(variant['output_path']);_,vb,vm=m.read_template(str(vp));vr=m.generate(params|dict(template_path=str(vp),template_sha256=m.sha(vb),name='Unlisted OOP Native Variant Defend'))
preserve(vr,vm,m.summarize(str(vp))['name'],'Unlisted OOP Native Variant Defend')
assert m.sha(vb)!=m.sha(sb)
for bad in (None,True,False,1,[],{},'Wing-Back'):
 refuse(params|dict(base_role=bad),'base_role requires')
for change in (dict(phase=None),dict(phase='in_possession'),dict(phase='unknown'),dict(position_index=7),dict(position_index=5),dict(position_index=True),dict(donor_position_index=7),dict(donor_position_index=True)):
 refuse(params|dict(base_role=role|change),'supports only')
for change in (dict(role='Wing-Back'),dict(native_role_word='0000000000201000'),dict(extra=True)):
 refuse(params|dict(base_role=role|change),'exact phase')
for change in (dict(donor_template_path=True),dict(donor_template_path=''),dict(donor_template_sha256=None),dict(donor_template_sha256='0'*64)):
 refuse(params|dict(base_role=role|change),'donor')
refuse(params|dict(template_sha256='0'*64),'Template hash changed')

# Every semantic negative reaches PUBLIC generate using newly packed, valid-hash
# native archives. Mutating BOTH prefixes defeats mere equality-only validation.
case=0;semantic_cases=[]
def planted(label,edit,fragment,both=True):
 global case
 case+=1;aa,bb=bytearray(st),bytearray(dt);edit(aa,a)
 if both:edit(bb,b)
 sp=root/f'{case}-source-{label}.fmf';dp=root/f'{case}-donor-{label}.fmf'
 m.repack_native_fmf(source,sp,plaintext_overrides={'.tac':bytes(aa)})
 m.repack_native_fmf(donor,dp,plaintext_overrides={'.tac':bytes(bb)})
 request=params|dict(template_path=str(sp),template_sha256=m.sha(sp.read_bytes()),base_role=role|dict(donor_template_path=str(dp),donor_template_sha256=m.sha(dp.read_bytes())))
 refuse(request,fragment);semantic_cases.append(label)
planted('major26',lambda buf,r:buf.__setitem__(11,26),'requires native FM27')
for rel in (0,1,2,8):planted(f'record-version-{rel}',lambda buf,r,rel=rel:buf.__setitem__(r['record_offset']+rel,buf[r['record_offset']+rel]^1),'record version')
planted('position',lambda buf,r:struct.pack_into('<I',buf,r['record_offset']+3,4),'requires OOP slot4')
planted('metadata',lambda buf,r:buf.__setitem__(r['instruction_vector_offset']+8,3),'instruction metadata')
planted('missing-key',lambda buf,r:struct.pack_into('<Q',buf,r['instruction_vector_offset']+3*24,0x1001),'target key')
planted('duplicate-key',lambda buf,r:struct.pack_into('<Q',buf,r['instruction_vector_offset']+4*24,0x1000),'target key')
planted('unnormalized-key',lambda buf,r:struct.pack_into('<Q',buf,r['instruction_vector_offset']+3*24,0x201000),'target key')
planted('unsorted-key',lambda buf,r:struct.pack_into('<Q',buf,r['instruction_vector_offset'],0x800),'target key')
for bits in (0,1<<32,(1<<31)|(1<<32),1<<36,(1<<31)|(1<<36)):
 planted(f'target-PI-{bits:x}',lambda buf,r,bits=bits:struct.pack_into('<Q',buf,r['instruction_vector_offset']+3*24+11,bits),'exact PI bit31')
# PI32 is native-preserved but outside this exact prefix; PI36 is actually
# cleared by the copied native validator. Neither is advertised as this case.
planted('one-side-prefix',lambda buf,r:buf.__setitem__(r['instruction_vector_offset']+3*24+11,1),'companion record bytes differ',False)
planted('other-PI-prefix',lambda buf,r:struct.pack_into('<Q',buf,r['instruction_vector_offset']+11,0),'companion prefix')
for word,is_source in ((0x202000,True),(0x802000,True),(0x401000,False),(0x201001,False)):
 aa,bb=bytearray(st),bytearray(dt);buf,r=(aa,a) if is_source else (bb,b);struct.pack_into('<Q',buf,r['role_word_offset'],word)
 case+=1;sp=root/f'{case}-wrong-role-source.fmf';dp=root/f'{case}-wrong-role-donor.fmf';m.repack_native_fmf(source,sp,plaintext_overrides={'.tac':bytes(aa)});m.repack_native_fmf(donor,dp,plaintext_overrides={'.tac':bytes(bb)})
 refuse(params|dict(template_path=str(sp),template_sha256=m.sha(sp.read_bytes()),base_role=role|dict(donor_template_path=str(dp),donor_template_sha256=m.sha(dp.read_bytes()))),'source or donor role');semantic_cases.append('wrong-role-word')
# Native label/resource/code guards are exercised through the public writer.
original_decode=m.decode_word
for word in (0x402000,0x201000):
 def changed_decode(value,phase,word=word):
  value=original_decode(value,phase)
  if value['raw_encoding']==f'0x{word:016x}':value['compiled_english_name']='Changed label'
  return value
 m.decode_word=changed_decode
 try:refuse(params,'label bindings changed')
 finally:m.decode_word=original_decode
native=m.ROLE_NATIVE_PLUGIN
for selected in range(len(m.WING_BACK_NATIVE_SPANS)):
 path=root/f'changed-native-{selected}.bin'
 with native.open('rb') as src,path.open('wb') as out:
  for index,(offset,size,_) in enumerate(m.WING_BACK_NATIVE_SPANS):
   src.seek(0x5ed4000+offset);raw=src.read(size)
   if index==selected:raw=bytes([raw[0]^1])+raw[1:]
   out.seek(0x5ed4000+offset);out.write(raw)
 m.ROLE_NATIVE_PLUGIN=path
 try:refuse(params,'Native OOP wing-back source changed')
 finally:m.ROLE_NATIVE_PLUGIN=native
resource=m.WING_BACK_ENGLISH_RESOURCE;badresource=root/'changed-English.ltf';badresource.write_text('Changed definition');m.WING_BACK_ENGLISH_RESOURCE=badresource
try:refuse(params,'English definitions changed')
finally:m.WING_BACK_ENGLISH_RESOURCE=resource
# Actual source/donor drift after packing; no original template is modified.
original_repack=m.repack_native_fmf
for kind,blob in (('source',sb),('donor',db)):
 changing=root/f'changing-{kind}.fmf';changing.write_bytes(blob)
 def drift(*args,**kwargs):original_repack(*args,**kwargs);changing.write_bytes(changing.read_bytes()+b'drift')
 m.repack_native_fmf=drift
 request=params|({ 'template_path':str(changing)} if kind=='source' else {'base_role':role|dict(donor_template_path=str(changing))})
 try:refuse(request,'changed during generation')
 finally:m.repack_native_fmf=original_repack
# A changed native source during packing must also refuse PREVIEW.
def native_drift(*args,**kwargs):original_repack(*args,**kwargs);m.ROLE_NATIVE_PLUGIN=root/'changed-native-0.bin'
m.repack_native_fmf=native_drift
try:refuse(params|dict(preview=True),'Native OOP wing-back source changed')
finally:m.repack_native_fmf=original_repack;m.ROLE_NATIVE_PLUGIN=native
fm27=root/'FM27 Tactics';fm27.mkdir();destination=params|dict(fm27_folder=True,tactics_directory=str(fm27))
saved=m.generate(destination);saved_bytes=Path(saved['output_path']).read_bytes();refuse(destination,'already exists');assert Path(saved['output_path']).read_bytes()==saved_bytes
refuse(destination|dict(name='../escape'),'single filename component')
assert source.read_bytes()==sb and donor.read_bytes()==db
print(json.dumps(dict(positive=positive,other_records_preserved=21,public_refusals=refusals,semantic_cases=semantic_cases,native_spans=len(m.WING_BACK_NATIVE_SPANS),artifacts=artifacts,fixtures_directory=str(root),game_import_verified=False)))
