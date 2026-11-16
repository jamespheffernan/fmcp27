"""Real archives for finite native position edits; private folders only."""
import importlib.util,json,struct,sys,tempfile
from pathlib import Path
spec=importlib.util.spec_from_file_location('writer',sys.argv[1]);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
scratch=Path(__file__).resolve().parents[1]/'tmp';scratch.mkdir(exist_ok=True);root=Path(tempfile.mkdtemp(prefix='phase-position-files-',dir=scratch));m.OUTPUTS=root/'outputs'
source=m.TEMPLATES/'4231 FM27 .fmf';donor=m.TEMPLATES/'4231 FM27 Att.fmf'
_,sb,sm=m.read_template(str(source));_,db,dm=m.read_template(str(donor));artifacts=[];refusals=0

def role(slot):return dict(phase='out_of_possession',position_index=slot,donor_position_index=slot,donor_template_path=str(donor),donor_template_sha256=m.sha(db))
def request(path,blob,slot,name):return dict(template_path=str(path),template_sha256=m.sha(blob),name=name,phase_position=role(slot))
def records(tac):return {(p,i):tac[r['record_offset']:r['record_end_exclusive']] for p,rows in m.phase_records(tac).items() for i,r in enumerate(rows)}
def files():return sorted(str(p) for p in m.OUTPUTS.rglob('*') if p.is_file())
def refuse(params):
    global refusals
    before=files()
    try:m.generate(params)
    except (ValueError,FileExistsError):refusals+=1
    else:raise AssertionError('Unproved public position edit accepted')
    assert files()==before

def preserve(result,before,old_name,slot):
    _,blob,after=m.read_template(result['output_path']);before_records=records(before['.tac']);after_records=records(after['.tac'])
    assert [key for key in before_records if before_records[key]!=after_records[key]]==[('out_of_possession',slot)]
    assert after_records['out_of_possession',slot]==records(dm['.tac'])['out_of_possession',slot]
    restored=m.replace_tac_name(after['.tac'],old_name);r=m.phase_records(before['.tac'])['out_of_possession'][slot];a,b=r['record_offset'],r['record_end_exclusive']
    assert restored[:a]+before['.tac'][a:b]+restored[b:]==before['.tac']
    assert m.replace_string(after['.aom'],12+len(b'TACTICS_TYPE_HANDLER'),old_name,result['name'])==before['.aom']
    assert set(after)==set(before) and all(after[k]==before[k] for k in before if k not in ('.tac','.aom'))
    assert result['phase_position_mode']=='explicit_change' and result['phase_position']['donor_template_sha256']==m.sha(db)
    assert result['source_game_major']==26 and result['phase_position']['source_game_major']==26
    assert result['edits']==['name','phase_position'] and result['verification']['all_unrequested_tactic_bytes_preserved']
    assert 'formations' not in result['preserved'] and 'unrequested phase positions' in result['preserved']
    assert json.loads(Path(result['receipt_path']).read_text())==result
    return Path(result['output_path']),blob,after

for order in [(7,8),(8,7)]:
    path,blob,before=source,sb,sm
    for slot in order:
        params=request(path,blob,slot,f'Native Position {order[0]} Then {slot}')
        preview=m.generate(params|dict(preview=True));assert preview['status']=='preview' and preview['files_created'] is False
        original=files();old_name=m.summarize(str(path))['name'];result=m.generate(params)
        assert len(files())==len(original)+2
        path,blob,before=preserve(result,before,old_name,slot);artifacts.append(result['output_path'])
        refuse(request(path,blob,slot,'Refuse Position No Op'))
    assert m.summarize(str(path))['phase_position_cases']==[]
# A proved independent IP role and team tempo compose with the OOP position edit.
params=request(source,sb,7,'Native26 Position With IP Role And Tempo')|dict(tempo='Lower Tempo',base_role=dict(phase='in_possession',position_index=7,donor_position_index=7,donor_template_path=str(donor),donor_template_sha256=m.sha(db)))
result=m.generate(params);artifacts.append(result['output_path']);_,_,out=m.read_template(result['output_path']);changed=[k for k,v in records(sm['.tac']).items() if records(out['.tac'])[k]!=v]
assert changed==[('in_possession',7),('out_of_possession',7)]
restored=m.replace_tac_name(out['.tac'],m.summarize(str(source))['name']);r=m.phase_records(sm['.tac'])['out_of_possession'][7];a,b=r['record_offset'],r['record_end_exclusive'];restored=restored[:a]+sm['.tac'][a:b]+restored[b:]
r=m.phase_records(sm['.tac'])['in_possession'][7];a=r['role_word_offset'];restored=restored[:a]+sm['.tac'][a:a+8]+restored[a+8:]
restored=m.replace_tempo(restored,m.tempo_selection(sm['.tac'])[1]);assert restored==sm['.tac']
# Inheritance remains explicit.
inherited=m.generate(dict(template_path=str(source),template_sha256=m.sha(sb),name='Inherited Native Positions',preview=True));assert inherited['phase_position'] is None and inherited['phase_position_mode']=='inherit'
# Public semantic controls use genuinely repacked, freshly hash-pinned files.
for index,(which,offset) in enumerate([('source',11),('donor',11),('source',m.phase_records(sm['.tac'])['out_of_possession'][2]['role_word_offset']),('donor',m.phase_records(dm['.tac'])['out_of_possession'][7]['instruction_vector_offset']+11)]):
    template=source if which=='source' else donor;members=sm if which=='source' else dm;raw=bytearray(members['.tac']);raw[offset]=27 if offset==11 else raw[offset]^1
    path=root/f'changed-{index}.fmf';m.repack_native_fmf(template,path,plaintext_overrides={'.tac':bytes(raw)});params=request(source,sb,7,'Refuse Repacked Semantic Drift')
    if which=='source':params|=dict(template_path=str(path),template_sha256=m.sha(path.read_bytes()))
    else:params['phase_position']|=dict(donor_template_path=str(path),donor_template_sha256=m.sha(path.read_bytes()))
    refuse(params)
# Exact source/donor identities are rechecked after packing and final native verification.
original_repack=m.repack_native_fmf;original_verify=m.verify_phase_position_native
for stage in ['postpack','delivery']:
    for which in ['source','donor']:
        sp=root/f'{stage}-{which}-source.fmf';dp=root/f'{stage}-{which}-donor.fmf';sp.write_bytes(sb);dp.write_bytes(db);params=request(sp,sb,7,'Refuse Identity Drift');params['phase_position']|=dict(donor_template_path=str(dp));calls=0
        def change():
            path=sp if which=='source' else dp;path.write_bytes(path.read_bytes()+b'drift')
        def repack(*args,**kwargs):
            original_repack(*args,**kwargs)
            if stage=='postpack':change()
        def verify():
            global calls
            original_verify();calls+=1
            if stage=='delivery' and calls==3:change()
        m.repack_native_fmf=repack;m.verify_phase_position_native=verify
        try:refuse(params)
        finally:m.repack_native_fmf=original_repack;m.verify_phase_position_native=original_verify
# Real altered native bytes at both boundaries, without sparse fixture files.
class Native:
    def __init__(self,values):self.values=values
    def open(self,mode):assert mode=='rb';return NativeFile(self.values)
class NativeFile:
    def __init__(self,values):self.values=values
    def __enter__(self):return self
    def __exit__(self,*args):return False
    def seek(self,at):self.at=at
    def read(self,size):value=self.values[self.at];assert len(value)==size;return value
native=m.ROLE_NATIVE_PLUGIN;values={}
with native.open('rb') as stream:
    for at,size,_ in m.PHASE_POSITION_NATIVE_SPANS:stream.seek(0x5ed4000+at);values[0x5ed4000+at]=stream.read(size)
key=0x5ed4000+m.PHASE_POSITION_NATIVE_SPANS[0][0];values[key]=bytes([values[key][0]^1])+values[key][1:]
for stage in ['postpack','delivery']:
    calls=0
    def repack(*args,**kwargs):
        original_repack(*args,**kwargs)
        if stage=='postpack':m.ROLE_NATIVE_PLUGIN=Native(values)
    def verify():
        global calls
        original_verify();calls+=1
        if stage=='delivery' and calls==2:m.ROLE_NATIVE_PLUGIN=Native(values)
    m.repack_native_fmf=repack;m.verify_phase_position_native=verify
    try:refuse(request(source,sb,4,'Refuse Late Native Drift'))
    finally:m.repack_native_fmf=original_repack;m.verify_phase_position_native=original_verify;m.ROLE_NATIVE_PLUGIN=native
# A private directory exercises the actual FM27-folder collision contract.
folder=root/'FM27 Tactics';folder.mkdir();params=request(source,sb,8,'Native26 Private Position')|dict(fm27_folder=True,tactics_directory=str(folder));result=m.generate(params);artifacts.append(result['output_path']);saved=Path(result['output_path']).read_bytes();refuse(params);assert Path(result['output_path']).read_bytes()==saved
assert source.read_bytes()==sb and donor.read_bytes()==db
print(json.dumps(dict(artifacts=artifacts,public_refusals=refusals,records_preserved_per_single_edit=21,native_fixture_files_created=0,game_import_verified=False)))
