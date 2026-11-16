"""Final-third delivery edits through actual native archives; no game access."""
import importlib.util,json,struct,sys,tempfile
from pathlib import Path
spec=importlib.util.spec_from_file_location('writer',sys.argv[1]);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
root=Path(tempfile.mkdtemp(prefix='final-third-',dir=Path(__file__).resolve().parents[1]/'tmp'));m.OUTPUTS=root/'outputs'
choices={'No explicit selection':None,'Hit Early Crosses':9,'Work Ball Into Box':17};mask=(1<<9)|(1<<17);artifacts=[];negatives=0

def vector(raw):
 s=m.parse_tac_plaintext(raw)['pre_style_setup'];a=s['team_instruction_vector_candidate_offset'];assert s['team_instruction_vector_candidate_size']==12 and raw[a-1]==3
 return a,int.from_bytes(raw[a:a+12],'little')

def preserve(result,before,original_name,requested_name,expected):
 _,_,after=m.read_template(result['output_path']);new=m.replace_tac_name(after['.tac'],original_name);a,flags=vector(before['.tac'])
 assert vector(new)==(a,expected)
 assert new[:a]+before['.tac'][a:a+12]+new[a+12:]==before['.tac']
 assert m.inspect_stored_football(after['.tac'])['phase_positions_and_roles']==m.inspect_stored_football(before['.tac'])['phase_positions_and_roles']
 assert after['.img']==before['.img']
 assert m.replace_string(after['.aom'],12+len(b'TACTICS_TYPE_HANDLER'),original_name,requested_name)==before['.aom']
 assert json.loads(Path(result['receipt_path']).read_text())==result
 assert result['verification']['all_unrequested_tactic_bytes_preserved'] and not result['verification']['game_load_verified']

def refuse(params,reason):
 global negatives
 files=sorted(m.OUTPUTS.rglob('*'))
 try:m.generate(params)
 except (ValueError,FileExistsError) as ex:assert reason in str(ex),(reason,str(ex));negatives+=1
 else:raise AssertionError('Invalid final-third edit accepted')
 assert sorted(m.OUTPUTS.rglob('*'))==files

def generate(source,label,name='Final Third Delivery Verification'):
 _,raw,members=m.read_template(str(source));summary=m.summarize(str(source));a,flags=vector(members['.tac']);bit=choices[label]
 params=dict(template_path=str(source),template_sha256=m.sha(raw),name=name,final_third_delivery=label)
 result=m.generate(params);expected=(flags&~mask)|(0 if bit is None else 1<<bit)
 assert result['edits']==['name','final_third_delivery'] and result['final_third_delivery_mode']=='explicit_change' and result['final_third_delivery']==label
 preserve(result,members,summary['name'],name,expected)
 artifacts.append(dict(source=str(source),source_sha256=m.sha(raw),output=result['output_path'],output_sha256=result['output_sha256'],selection=label,requested_name=name,original_name=summary['name']))
 assert source.read_bytes()==raw
 return result

templates=sorted(m.TEMPLATES.glob('*.fmf'));assert len(templates)>=9;changed={}
for source in templates:
 _,raw,members=m.read_template(str(source));summary=m.summarize(str(source));a,flags=vector(members['.tac'])
 assert summary['final_third_delivery_state']=='known'
 for label,bit in choices.items():
  target=0 if bit is None else 1<<bit
  sent=((1<<96)-1)&~mask;tac=members['.tac'][:a]+sent.to_bytes(12,'little')+members['.tac'][a+12:]
  assert vector(m.replace_stored_control(tac,'final_third_delivery',label))==(a,sent|target)
  result=generate(source,label)
  if members['.tac'][11]==27 and flags&mask!=target:changed.setdefault(label,result['output_path'])
 params=dict(template_path=str(source),template_sha256=m.sha(raw),name='Preview Delivery',preview=True)
 before=sorted(m.OUTPUTS.rglob('*'));preview=m.generate(params|dict(final_third_delivery='Work Ball Into Box'));inherited=m.generate(params)
 assert not preview['files_created'] and not inherited['files_created'] and inherited['final_third_delivery']==summary['final_third_delivery'] and inherited['final_third_delivery_mode']=='inherit'
 assert before==sorted(m.OUTPUTS.rglob('*'))
# A generated opposite source supplies changed positive coverage if templates agree.
for label in choices:
 if label not in changed:
  opposite=next(v for k,v in changed.items() if k!=label);changed[label]=generate(Path(opposite),label)['output_path']
assert set(changed)==set(choices)
source=m.TEMPLATES/'3421 FM27 Att.fmf';_,raw,members=m.read_template(str(source));summary=m.summarize(str(source));a,flags=vector(members['.tac'])
base=dict(template_path=str(source),template_sha256=m.sha(raw),name='Delivery Negative',final_third_delivery='Work Ball Into Box')
# Independent group edits coexist: selecting box delivery must not clear Low Crosses or Mid Block.
combined=m.generate(base|dict(name='Combined Delivery',crossing_style='Low Crosses',pressing_block='Mid Block'))
_,_,after=m.read_template(combined['output_path']);combined_mask=mask|(7<<10)|(7<<61)
preserve(combined,members,summary['name'],'Combined Delivery',(flags&~combined_mask)|(1<<17)|(1<<12)|(1<<62))
for value in [None,True,False,1,[],{},'Standard','Work Ball into Box','Hit Early Crosses ']:refuse(base|dict(final_third_delivery=value),'Unsupported stored final_third_delivery')
refuse(base|dict(template_sha256='0'*64),'Template hash changed')
for bit in [9,17]:
 old=m.OPTION_NAMES[bit]
 try:m.OPTION_NAMES[bit]='Changed label';refuse(base,'option labels changed')
 finally:m.OPTION_NAMES[bit]=old
# Conflict is a genuine archive with valid outer hash; inheritance remains possible.
conflict=root/'conflicting.fmf';ct=members['.tac'][:a]+(flags|mask).to_bytes(12,'little')+members['.tac'][a+12:]
m.repack_native_fmf(source,conflict,plaintext_overrides={'.tac':ct});cs=m.summarize(str(conflict));assert cs['final_third_delivery_state']=='conflicting_stored_selections' and 'final_third_delivery' not in cs['supported_edits']
cp=dict(template_path=str(conflict),template_sha256=m.sha(conflict.read_bytes()),name='Inherited Delivery Conflict')
r=m.generate(cp);preserve(r,m.read_template(str(conflict))[2],cs['name'],cp['name'],flags|mask)
for label in choices:refuse(cp|dict(final_third_delivery=label),'contradictory')
for prefix in [0,1,2,4,255]:
 path=root/f'prefix-{prefix}.fmf';m.repack_native_fmf(source,path,plaintext_overrides={'.tac':members['.tac'][:a-1]+bytes([prefix])+members['.tac'][a:]})
 for label in choices:refuse(base|dict(template_path=str(path),template_sha256=m.sha(path.read_bytes()),final_third_delivery=label),'Unsupported native team instruction vector')
# Valid unknown option64 survives an edit without being assigned a made-up label.
u=root/'unknown-option.fmf';m.repack_native_fmf(source,u,plaintext_overrides={'.tac':members['.tac'][:a]+(flags|(1<<64)).to_bytes(12,'little')+members['.tac'][a+12:]})
assert {'native_option_id':64,'name':None} in m.summarize(str(u))['stored_football']['stored_team_instructions'];generate(u,'Work Ball Into Box')
native=m.FINAL_THIRD_NATIVE_PLUGIN
for index in range(len(m.FINAL_THIRD_NATIVE_SPANS)):
 path=root/f'changed-native-{index}.bin'
 with native.open('rb') as src,path.open('wb') as dst:
  for j,(at,n,h) in enumerate(m.FINAL_THIRD_NATIVE_SPANS):
   src.seek(0x5ed4000+at);b=src.read(n)
   if j==index:b=bytes([b[0]^1])+b[1:]
   dst.seek(0x5ed4000+at);dst.write(b)
 try:m.FINAL_THIRD_NATIVE_PLUGIN=path;refuse(base,'Native final-third-delivery source changed')
 finally:m.FINAL_THIRD_NATIVE_PLUGIN=native
resource=m.FINAL_THIRD_ENGLISH_RESOURCE;bad=root/'bad-English';bad.write_text('Changed')
try:m.FINAL_THIRD_ENGLISH_RESOURCE=bad;refuse(base,'English definitions changed')
finally:m.FINAL_THIRD_ENGLISH_RESOURCE=resource
# Source/native drift after repacking and immediately before publication refuse delivery.
original=m.repack_native_fmf;copy=root/'source-changing.fmf';copy.write_bytes(raw)
def repack_source(*args,**kwargs):original(*args,**kwargs);copy.write_bytes(raw+b'drift')
try:m.repack_native_fmf=repack_source;refuse(base|dict(template_path=str(copy)),'Template changed during generation')
finally:m.repack_native_fmf=original
def repack_native(*args,**kwargs):original(*args,**kwargs);m.FINAL_THIRD_NATIVE_PLUGIN=root/'changed-native-0.bin'
try:m.repack_native_fmf=repack_native;refuse(base|dict(preview=True),'Native final-third-delivery source changed')
finally:m.repack_native_fmf=original;m.FINAL_THIRD_NATIVE_PLUGIN=native
verify=m.verify_final_third_native;calls=0;copy.write_bytes(raw)
def change_at_delivery():
 global calls
 verify();calls+=1
 if calls==3:copy.write_bytes(raw+b'delivery drift')
try:m.verify_final_third_native=change_at_delivery;refuse(base|dict(template_path=str(copy)),'Template changed before delivery')
finally:m.verify_final_third_native=verify
folder=root/'Tactics';folder.mkdir();params=base|dict(name='Final Third Destination',fm27_folder=True,tactics_directory=str(folder));r=m.generate(params);before=Path(r['output_path']).read_bytes()
refuse(params,'already exists');assert Path(r['output_path']).read_bytes()==before
refuse(params|dict(name='../Escape'),'single filename component')
print(json.dumps(dict(templates_checked=len(templates),artifacts=artifacts,changed_fm27=changed,negative_controls=negatives,native_spans=len(m.FINAL_THIRD_NATIVE_SPANS),fixtures_directory=str(root),game_import_verified=False)))
