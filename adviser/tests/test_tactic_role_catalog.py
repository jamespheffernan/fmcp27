"""Original native refusal and availability checks over full-loader-owned data."""
from pathlib import Path
import importlib.util
import json
import struct
import sys
import pytest
sys.path.append('/Users/jamesheffernan/GitHub/FM26 Deepener/.venv/lib/python3.14/site-packages')
ROOT=Path(__file__).resolve().parents[1]
def module(name,path):
 spec=importlib.util.spec_from_file_location(name,path);value=importlib.util.module_from_spec(spec);spec.loader.exec_module(value);return value
helper=module('tested_tactic_role_catalog',ROOT/'pi/fm_tactic_role_catalog.py')
writer=module('catalog_fixture_reader',ROOT/'pi/fm-tactic-files.py')
# The production native authoring utility has the same .native/.call/.uc API.
creator_path=ROOT/'pi/fm_tactic_native_authoring.py'
if not creator_path.exists():creator_path=Path('/Volumes/4TB Private/Offloaded/Agent Work/fm27-continuous-20261109/spatial/evidence/generic-tactic-serialization/native_creator.py')
creator=module('catalog_full_loader',creator_path)
@pytest.fixture
def native():
 _,_,members=writer.read_template(str(writer.TEMPLATES/'3421 FM27 .fmf'))
 return creator.NativeCreator(members['.tac'])

def record(native,phase,slot):return helper.CREATOR+helper.PHASES[phase][0]+72*slot

@pytest.mark.parametrize('phase',helper.PHASES)
def test_loaded_selection_preserves_all_records(native,phase):
 before=native.records()
 for slot in range(11):assert helper.validate_loaded_selection(native,phase,slot)['native_word_valid']
 assert native.records()==before

@pytest.mark.parametrize('index',range(len(helper.NATIVE_GUARDS)))
def test_every_altered_native_source_span_refuses_before_execution(native,index):
 original=native.native;at,size,_=helper.NATIVE_GUARDS[index];called=[]
 def altered(address,length):
  raw=original(address,length)
  return bytes([raw[0]^1])+raw[1:]if(address,length)==(at,size)else raw
 native.native=altered;native.call=lambda *args:called.append(args)
 with pytest.raises(ValueError,match='source changed'):helper.validate_role_request(native,'in_possession',0,'Goalkeeper')
 assert not called

@pytest.mark.parametrize('phase',helper.PHASES)
@pytest.mark.parametrize('bad',['no_role','two_roles','no_fixed_bit','two_fixed_bits','unknown_bit'])
def test_ambiguous_or_unknown_loaded_words_refuse(native,phase,bad):
 at=record(native,phase,0)+64;word=struct.unpack('<Q',native.uc.mem_read(at,8))[0];data=helper.catalog();roles=sum(r['word']for r in data['roles'][phase]);fixed=sum(d['word']for d in helper._fixed_bits(data));rolebit=word&roles;fixedbit=word&fixed
 if bad=='no_role':word &=~roles
 elif bad=='two_roles':word |=next(r['word']for r in data['roles'][phase]if r['word']!=rolebit)
 elif bad=='no_fixed_bit':word &=~fixed
 elif bad=='two_fixed_bits':word |=next(d['word']for d in helper._fixed_bits(data)if d['word']!=fixedbit)
 else:word|=1<<63
 native.uc.mem_write(at,struct.pack('<Q',word));before=native.records()
 with pytest.raises(ValueError,match='exactly one'):helper.validate_loaded_selection(native,phase,0)
 assert native.records()==before

@pytest.mark.parametrize('index',range(5))
def test_goalkeeper_word_with_another_fixed_bit_refuses_without_normalizing(native,index):
 at=record(native,'in_possession',0)+64;word=struct.unpack('<Q',native.uc.mem_read(at,8))[0];bits=helper._fixed_bits(helper.catalog())
 own=next(bit for bit in bits if word&bit['word']);other=[bit for bit in bits if bit is not own][index]
 native.uc.mem_write(at,struct.pack('<Q',(word&~own['word'])|other['word']));before=native.records()
 with pytest.raises(ValueError,match='role-word predicate refuses'):helper.validate_loaded_selection(native,'in_possession',0)
 assert native.records()==before

def test_goalkeeper_has_exactly_one_stored_word_and_it_is_found_not_supplied(native):
 before=native.records();pointer=record(native,'in_possession',0);raw=bytes(native.uc.mem_read(pointer,72));data=helper.catalog()
 role=next(r for r in data['roles']['in_possession']if r['compiled_english_name']=='Goalkeeper')
 assert helper._legal_words(native,'in_possession',pointer,raw,data,role)==[0x200001]
 found=helper.validate_role_request(native,'in_possession',0,'Goalkeeper')
 assert found['native_word']==0x200001 and found['native_word_valid'] and set(found)=={'phase','role','native_word','legality_evaluated','position_mask','native_position_role_mask','native_word_valid','creator_mutated'}
 assert native.records()==before

def test_a_role_with_more_than_one_accepted_word_refuses_instead_of_picking(native,monkeypatch):
 before=native.records();accepted=helper._word_accepted;bits=[bit['word']for bit in helper._fixed_bits(helper.catalog())]
 # The game's predicate, altered here to accept a second word for the goalkeeper role only.
 monkeypatch.setattr(helper,'_word_accepted',lambda owned,phase,pointer,raw,word:word in(1|bits[0],1|bits[3])or accepted(owned,phase,pointer,raw,word))
 with pytest.raises(ValueError,match='more than one stored word'):helper.validate_role_request(native,'in_possession',0,'Goalkeeper')
 choices=helper.legal_roles(native,'in_possession',0)
 assert 'Goalkeeper' not in choices['legal_roles'] and choices['roles_refused_for_more_than_one_stored_word']==['Goalkeeper']
 assert native.records()==before

def test_legal_roles_are_names_with_the_stored_words_the_earlier_interface_wrote():
 expected=json.loads((ROOT/'tests/fixtures/role-words-4231-fm27.json').read_text())
 path,blob,members=writer.read_template(str(writer.TEMPLATES/expected['template']))
 if writer.sha(blob)!=expected['template_sha256']:pytest.skip('the 4231 template differs from the one the fixture was taken from')
 owned=creator.NativeCreator(members['.tac']);before=owned.records();checked=0
 for row in expected['slots']:
  choices=helper.legal_roles(owned,row['phase'],row['position_index'])
  assert choices['position_name']==row['position_name'] and choices['legal_roles']==list(row['stored_word_by_role'])
  assert choices['roles_refused_for_more_than_one_stored_word']==[] and all(type(name)is str for name in choices['legal_roles'])
  for role,word in row['stored_word_by_role'].items():
   assert helper.validate_role_request(owned,row['phase'],row['position_index'],role)['native_word']==int(word,16);checked+=1
 assert checked==101 and owned.records()==before

def test_wrong_position_refuses_despite_known_role(native):
 before=native.records()
 with pytest.raises(ValueError,match='position role mask refuses'):helper.validate_role_request(native,'in_possession',0,'Centre-Back')
 assert native.records()==before

@pytest.mark.parametrize('name',['Complete Forward','Anchor','Mezzala','Regista','Enganche'])
def test_known_legacy_roles_do_not_become_active(name):
 with pytest.raises(ValueError,match='removed by the native phase filter'):helper.resolve_role('in_possession',name)

@pytest.mark.parametrize('option',[0,43,-1,True,1.0,None,'PI_NONE','invented'])
def test_invalid_or_none_instruction_is_never_a_selection(native,option):
 before=native.records()
 with pytest.raises(ValueError):helper.instruction_availability(native,'in_possession',9,option)
 assert native.records()==before

@pytest.mark.parametrize('phase,slot',[('other',0),('in_possession',-1),('in_possession',11),('in_possession',True),('in_possession',1.0)])
def test_invalid_phase_or_slot_refuses(native,phase,slot):
 with pytest.raises(ValueError):helper.validate_role_request(native,phase,slot,'Goalkeeper')

@pytest.mark.parametrize('phase',helper.PHASES)
def test_unknown_position_is_not_canonical(native,phase):
 native.uc.mem_write(record(native,phase,0),struct.pack('<I',0x80000000));before=native.records()
 with pytest.raises(ValueError,match='26 canonical'):helper.validate_loaded_selection(native,phase,0)
 assert native.records()==before

def test_editor_wrapper_availability_is_not_always_true(native):
 before=native.records()
 yes=helper.instruction_availability(native,'in_possession',9,'PI_ROAM_FROM_POSITION')
 no=helper.instruction_availability(native,'in_possession',0,'PI_ROAM_FROM_POSITION')
 assert(yes['native_available'],yes['native_state'])==(True,0)
 assert(no['native_available'],no['native_state'])==(False,1)
 assert yes['availability_context']=='built_by_original_editor_wrapper'
 assert native.records()==before

def test_catalog_hash_mutation_refuses(monkeypatch):
 monkeypatch.setattr(helper,'CATALOG_SHA256','0'*64)
 with pytest.raises(ValueError,match='catalog source changed'):helper.catalog()

def test_compiled_metadata_and_english_names_are_distinct_exact_aliases(native):
 before=native.records()
 english=helper.validate_role_request(native,'in_possession',5,'Deep-Lying Playmaker')
 metadata=helper.validate_role_request(native,'in_possession',5,'DeepLyingPlaymaker')
 assert english==metadata and english['native_word']==0x408000
 assert native.records()==before
