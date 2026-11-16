"""Actual payload position edits and bounded in-memory refusal controls."""
import importlib.util,json,struct,sys
from pathlib import Path
spec=importlib.util.spec_from_file_location('writer',sys.argv[1]);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
source=m.TEMPLATES/'3421 FM27 .fmf';donor=m.TEMPLATES/'3421 FM27 Def.fmf'
_,sb,sm=m.read_template(str(source));_,db,dm=m.read_template(str(donor));positives=refusals=0

def request(slot):
    return dict(phase='out_of_possession',position_index=slot,donor_position_index=slot,donor_template_path=str(donor),donor_template_sha256=m.sha(db))

def refuse(call):
    global refusals
    try:call()
    except ValueError:refusals+=1
    else:raise AssertionError('Unproved position edit accepted')

def records(tac):
    return {(p,i):tac[r['record_offset']:r['record_end_exclusive']] for p,rows in m.phase_records(tac).items() for i,r in enumerate(rows)}

for order in [(4,7),(7,4)]:
    tac=sm['.tac']
    for slot in order:
        before=records(tac);changed,receipt,path,blob=m.prepare_phase_position(tac,request(slot));after=records(changed)
        assert [key for key in before if before[key]!=after[key]]==[('out_of_possession',slot)]
        assert after['out_of_possession',slot]==records(dm['.tac'])['out_of_possession',slot]
        assert receipt['before']['position_mask']==(32 if slot==4 else 64)
        assert receipt['after']['position_mask']==(4 if slot==4 else 8)
        assert receipt['before']['role']=='Wing-Back' and receipt['after']['role']=='Full-Back'
        assert path==donor and blob==db
        refuse(lambda changed=changed,slot=slot:m.prepare_phase_position(changed,request(slot)))
        tac=changed;positives+=1
    assert m.describe_phase_position(tac)['phase_position_cases']==[]
# Changes outside the OOP phase do not weaken its exact source guard.
for slot in [4,7]:
    tac=m.replace_tempo(m.replace_tac_name(sm['.tac'],'Another Native Name'),'Lower Tempo')
    tac=m.prepare_base_role(tac,dict(phase='in_possession',position_index=5,donor_position_index=5,donor_template_path=str(donor),donor_template_sha256=m.sha(db)))[0]
    assert m.prepare_phase_position(tac,request(slot))[1]['after']['role']=='Full-Back';positives+=1
for bad in [None,True,4,'D(R)',[],{},request(4)|dict(position_mask=4),request(4)|dict(role='Full-Back')]:
    refuse(lambda bad=bad:m.prepare_phase_position(sm['.tac'],bad))
for change in [dict(phase='in_possession'),dict(phase=None),dict(position_index=True),dict(position_index=9),dict(donor_position_index=True),dict(donor_position_index=7),dict(donor_template_path=True),dict(donor_template_sha256='0'*64)]:
    refuse(lambda change=change:m.prepare_phase_position(sm['.tac'],request(4)|change))
for slot in [4,7]:
    for record in m.phase_records(sm['.tac'])['out_of_possession']:
        for offset in [record['record_offset'],record['record_offset']+2,record['record_offset']+3,record['record_offset']+7,record['record_offset']+9,record['instruction_vector_offset']+8,record['instruction_vector_offset']+11,record['role_word_offset']]:
            altered=bytearray(sm['.tac']);altered[offset]^=1
            refuse(lambda altered=altered,slot=slot:m.prepare_phase_position(bytes(altered),request(slot)))
    altered=bytearray(sm['.tac']);altered[11]=26
    refuse(lambda altered=altered,slot=slot:m.prepare_phase_position(bytes(altered),request(slot)))
    # Both correctly structured phase and donor records still require exact observed bytes.
    original_read=m.read_template
    for relative in [0,2,3,7,9,14+8,14+11,-1]:
        r=m.phase_records(dm['.tac'])['out_of_possession'][slot];altered=bytearray(dm['.tac'])
        at=r['record_offset']+relative if relative>=0 else r['record_end_exclusive']+relative;altered[at]^=1
        m.read_template=lambda path,altered=altered:(donor,db,dm|{'.tac':bytes(altered)})
        try:refuse(lambda slot=slot:m.prepare_phase_position(sm['.tac'],request(slot)))
        finally:m.read_template=original_read
class Native:
    def __init__(self,values):self.values=values
    def open(self,mode):assert mode=='rb';return NativeFile(self.values)
class NativeFile:
    def __init__(self,values):self.values=values
    def __enter__(self):return self
    def __exit__(self,*args):return False
    def seek(self,at):self.at=at
    def read(self,size):value=self.values[self.at];assert len(value)==size;return value
original=m.ROLE_NATIVE_PLUGIN;values={}
with original.open('rb') as stream:
    for at,size,_ in m.PHASE_POSITION_NATIVE_SPANS:stream.seek(0x5ed4000+at);values[0x5ed4000+at]=stream.read(size)
for at,_,_ in m.PHASE_POSITION_NATIVE_SPANS:
    changed=dict(values);key=0x5ed4000+at;changed[key]=bytes([changed[key][0]^1])+changed[key][1:];m.ROLE_NATIVE_PLUGIN=Native(changed)
    try:refuse(lambda:m.prepare_phase_position(sm['.tac'],request(4)))
    finally:m.ROLE_NATIVE_PLUGIN=original
class BadResource:
    def read_bytes(self):return b'Changed native definitions'
original=m.LOSS_ENGLISH_RESOURCE;m.LOSS_ENGLISH_RESOURCE=BadResource()
try:refuse(lambda:m.prepare_phase_position(sm['.tac'],request(4)))
finally:m.LOSS_ENGLISH_RESOURCE=original
original=m.decode_word
def changed_label(word,phase):
    value=original(word,phase)
    if word==0x200200 and phase=='out_of_possession':value['compiled_english_name']='Changed label'
    return value
m.decode_word=changed_label
try:refuse(lambda:m.prepare_phase_position(sm['.tac'],request(4)))
finally:m.decode_word=original
assert source.read_bytes()==sb and donor.read_bytes()==db
print(json.dumps(dict(actual_payload_positives=positives,refusals=refusals,native_spans=len(m.PHASE_POSITION_NATIVE_SPANS),archive_fixtures_created=0,native_fixture_files_created=0,game_import_verified=False)))
