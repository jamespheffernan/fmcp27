"""Offline owned-memory native TAC loader/editor/parent serializer proof utility.

No game process, file writes, donor lookup, or exact record fingerprint admission.
Full native binary identity and supported original-code execution are mandatory.
The immutable audited loader owns bounded input/allocation/memcpy primitives.
An opaque allocator service context is declared; allocator OS construction is not
claimed. Empty map headers execute original creator-constructor instructions.
"""
from pathlib import Path
import hashlib,importlib.util,os,struct,sys
from unicorn import UC_HOOK_CODE,UC_HOOK_MEM_INVALID,UC_HOOK_MEM_WRITE
from unicorn.arm64_const import *
HERE=Path(__file__).resolve().parent
if sys.flags.optimize:
 raise RuntimeError('Native authoring requires Python optimization disabled for audited bounded primitives')
# The installed game build's addresses through the reader's address map (fm_live_mcp/adviser_book.py);
# on the pinned build, and with a reader that lacks it, nothing changes.
sys.path.insert(1,os.environ.get('PI_FM_TACTIC_READER_ROOT','/Volumes/4TB Private/Offloaded/FMCP 27'))
if os.environ.get('PI_FM_NATIVE_BINARY') and not os.environ.get('FMCP_PLUGIN_PATH'):os.environ['FMCP_PLUGIN_PATH']=os.environ['PI_FM_NATIVE_BINARY']
try:from fm_live_mcp import adviser_book
except ImportError:adviser_book=None
if __name__=='__main__' and adviser_book is not None and adviser_book.rerun_as_main(__file__,globals()):raise SystemExit(0)
CORE=HERE/'fm_tactic_native_core.py'
CORE_SHA='f8b25c729557c57edaae16d65ab8f6b32f19a7dec2ab22a426fad986f97b5b4a'
assert hashlib.sha256(CORE.read_bytes()).hexdigest()==CORE_SHA
spec=importlib.util.spec_from_file_location('_generic_creator_loader',CORE,loader=adviser_book.source_loader('_generic_creator_loader',CORE) if adviser_book is not None else None);core=importlib.util.module_from_spec(spec);spec.loader.exec_module(core)
core.verify_native_binary()
CREATOR=0x100400000;STACK=0x100110000;STOP=0x100500300
ALLOCATOR_CONTEXT=0xca110ca11000
class NativeCreator:
 def __init__(self,payload,*,initialize_maps=True,allocator_context=True):
  core.verify_native_binary()
  if not isinstance(payload,bytes) or not 16<=len(payload)<=65536:raise ValueError('Bounded TAC bytes required')
  self.core=core;self.payload=payload;self.pages={};self.calls=[];self.writes=[];self.services=[];self.last_call=None
  self.segments=[];header=struct.unpack('<8I',self.native(0,32));at=32
  for _ in range(header[4]):
   command,size=struct.unpack('<II',self.native(at,8))
   if command==0x19:self.segments.append(struct.unpack_from('<4Q',self.native(at,72),24))
   at+=size
  created=[];old=core.Uc
  def construct(*args):
   machine=old(*args);created.append(machine);start=machine.emu_start
   def initial_start(begin,*args,**kwargs):
    if begin==0x4856b6c:
     if initialize_maps:
      machine.mem_map(0x484a000,4096);machine.mem_write(0x484a000,self.page_bytes(0x484a000))
      saved={reg:machine.reg_read(reg)for reg in [UC_ARM64_REG_SP,UC_ARM64_REG_PC]+[UC_ARM64_REG_X0+i for i in range(29)]+[UC_ARM64_REG_X29,UC_ARM64_REG_X30]}
      machine.reg_write(UC_ARM64_REG_X19,CREATOR)
      for init_begin,init_end in [(0x484a7f4,0x484a800),(0x484a838,0x484a844),(0x484a844,0x484a854)]:start(init_begin,init_end,count=4)
      for reg,value in saved.items():machine.reg_write(reg,value)
      assert struct.unpack('<3Q',machine.mem_read(CREATOR+0x108,24))==(CREATOR+0x110,0,0)
      assert struct.unpack('<3Q',machine.mem_read(CREATOR+0x760,24))==(CREATOR+0x768,0,0)
      assert struct.unpack('<3Q',machine.mem_read(CREATOR+0x778,24))==(CREATOR+0x780,0,0)
     if allocator_context:machine.mem_write(0x56a4a90,struct.pack('<Q',ALLOCATOR_CONTEXT))
    return start(begin,*args,**kwargs)
   machine.emu_start=initial_start
   return machine
  core.Uc=construct
  try:self.loaded=core.validate_payload(payload,controls=False)
  finally:core.Uc=old
  self.uc=created[0]
  self.initialization={'original_empty_tree_windows_executed':initialize_maps,'opaque_external_allocator_context':allocator_context,'allocator_OS_constructor_executed':False,'full_creator_constructor_executed':False}
  if not self.loaded['accepted']:raise ValueError(f'Native TAC loader rejected: {self.loaded}')
  # All following execution uses the same owned creator and loaded heap.
  self.uc.hook_add(UC_HOOK_MEM_INVALID,self._missing)
  self.uc.hook_add(UC_HOOK_CODE,self._code)
  self.uc.hook_add(UC_HOOK_MEM_WRITE,self._write)
  self.output=None;self._expect_return=False;self._observed_return=False
 def native(self,at,n):
  with core.P.open('rb')as f:f.seek(0x5ed4000+at);raw=f.read(n)
  if len(raw)!=n:raise ValueError('Native span missing')
  return raw
 def page_bytes(self,page):
  if page<4096:raise ValueError('Null native read rejected')
  segment=next((s for s in self.segments if s[0]<=page and page+4096<=s[0]+s[3]),None)
  if segment is None:raise ValueError(f'Unproved non-file-backed native page {page:x}')
  vm,ms,offset,length=segment;raw=self.native(offset+page-vm,4096)
  self.pages[hex(page)]=hashlib.sha256(raw).hexdigest();return raw
 def _missing(self,machine,access,at,n,value,data):
  page=at&~4095
  if not 4096<=page<0x6000000:return False
  try:raw=self.page_bytes(page)
  except ValueError:return False
  machine.mem_map(page,4096);machine.mem_write(page,raw);return True
 def _write(self,machine,access,at,n,value,data):
  if CREATOR<=at<CREATOR+0x800:self.writes.append({'offset':at-CREATOR,'size':n,'pc':hex(machine.reg_read(UC_ARM64_REG_PC))})
 def _code(self,machine,pc,n,data):
  self.calls.append(pc)
  if len(self.calls)>3000000:raise ValueError('Native call instruction budget exceeded')
  if self._expect_return and 4096<=pc<0x6000000:
   instruction=struct.unpack('<I',machine.mem_read(pc,4))[0]
   if instruction==0xD65F03C0 and machine.reg_read(UC_ARM64_REG_X30)==STOP and machine.reg_read(UC_ARM64_REG_SP)==STACK:self._observed_return=True
  if pc==STOP:
   if self._expect_return and (not self._observed_return or machine.reg_read(UC_ARM64_REG_SP)!=STACK):raise ValueError('Native routine did not return through an original balanced RET')
   machine.emu_stop();return
  if pc in (0x4355a04,0x4aee720,0x4aee72c,0x4aee708,0x4355ed4,0x4aeedb0,0x4aeedbc):self.services.append(hex(pc))
  if pc in (0x100500800,0x100500810,0x100500820,0x100500830):
   if self.output is None:raise ValueError('Output service outside parent serialization')
   if pc==0x100500800:
    pointer=machine.reg_read(UC_ARM64_REG_X1);n=machine.reg_read(UC_ARM64_REG_X2)
    if not 0<=n<=65536:raise ValueError('Output write budget')
    for page in range(pointer&~4095,((pointer+max(n,1)-1)&~4095)+4096,4096):
     try:machine.mem_read(page,1)
     except Exception:machine.mem_map(page,4096);machine.mem_write(page,self.page_bytes(page))
    raw=bytes(machine.mem_read(pointer,n));end=self.cursor+n
    if end>65536:raise ValueError('Parent output budget')
    self.output.extend(bytes(max(0,end-len(self.output))));self.output[self.cursor:end]=raw;self.cursor=end;machine.reg_write(UC_ARM64_REG_X0,n)
   elif pc==0x100500810:machine.reg_write(UC_ARM64_REG_X0,self.cursor)
   elif pc==0x100500820:
    self.cursor=machine.reg_read(UC_ARM64_REG_X1)
    if not 0<=self.cursor<=65536:raise ValueError('Output seek budget')
    machine.reg_write(UC_ARM64_REG_X0,0)
   else:machine.reg_write(UC_ARM64_REG_X0,len(self.output))
   machine.reg_write(UC_ARM64_REG_PC,machine.reg_read(UC_ARM64_REG_X30))
 def call(self,entry,args,*,instructions=3000000):
  self.calls.clear();self.writes.clear();self.services.clear()
  for reg,value in [(UC_ARM64_REG_SP,STACK),(UC_ARM64_REG_X30,STOP)]+[(UC_ARM64_REG_X0+i,value&((1<<64)-1))for i,value in enumerate(args)]:self.uc.reg_write(reg,value)
  self._expect_return=True;self._observed_return=False
  try:self.uc.emu_start(entry,0,count=instructions)
  finally:self._expect_return=False
  if self.uc.reg_read(UC_ARM64_REG_PC)!=STOP:raise ValueError('Original native call did not return')
  result=self.uc.reg_read(UC_ARM64_REG_X0)
  self.last_call={'entry':hex(entry),'result':result,'instructions':len(self.calls),'original_balanced_return':self._observed_return,'creator_writes':list(self.writes),'services':list(self.services)}
  return result
 def records(self):
  rows=[]
  for phase,offset in [('in_possession',0x120),('out_of_possession',0x440)]:
   for slot in range(11):
    raw=bytes(self.uc.mem_read(CREATOR+offset+72*slot,72));vectors=[]
    for at,stride in [(8,24),(40,16)]:
     first,last,capacity=struct.unpack_from('<3Q',raw,at)
     if not first<=last<=capacity or (last-first)%stride or last-first>16384:raise ValueError('Invalid owned native vector')
     vectors.append(bytes(self.uc.mem_read(first,last-first)).hex()if last>first else'')
    rows.append({'phase':phase,'slot':slot,'position_mask':struct.unpack_from('<I',raw)[0],'flags4':raw[4],'flags32':raw[32],'role':struct.unpack_from('<Q',raw,64)[0],'vectors':vectors})
  return rows
 def set_position(self,phase,old_mask,new_mask):
  if phase not in ('in_possession','out_of_possession'):raise ValueError('Unknown phase')
  return self.call(0x4857afc,[CREATOR,old_mask,new_mask,0,phase=='out_of_possession'])
 def serialize(self):
  self.output=bytearray();self.cursor=0
  self.uc.mem_write(0x100300400,struct.pack('<Q',0x100300500));self.uc.mem_write(0x100300410,bytes(4));self.uc.mem_write(0x100300600,struct.pack('<Q',0x100300400))
  for offset,target in [(0x30,0x100500800),(0x18,0x100500810),(0x20,0x100500820),(0x10,0x100500830)]:self.uc.mem_write(0x100300500+offset,struct.pack('<Q',target))
  result=self.call(0x4a8d728,[CREATOR,0x100300600,1])
  if result!=1:raise ValueError('Original parent serializer refused')
  output=self.payload[:8]+bytes(self.output);self.output=None
  return output

# Public authoring transport accepts names and owned slot indices, never native
# addresses or caller-selected machine code. All mutations remain inside Unicorn.
import base64
import json
from fm_tactic_role_catalog import catalog as role_catalog
from fm_tactic_role_catalog import validate_role_request, validate_loaded_selection, instruction_availability, legal_roles
from fm_tactic_team_instructions import apply_team_instructions, catalog as team_catalog

PHASE_OFFSETS = {'in_possession': 0x120, 'out_of_possession': 0x440}
SOURCE_FILES = ('fm_tactic_native_authoring.py', 'fm_tactic_native_core.py',
                'fm_tactic_role_catalog.py', 'fm_tactic_role_catalog.json',
                'fm_tactic_team_instructions.py')
UNBOUND_PLAYER_OPTIONS = {34, 35}


def _need(condition, message):
    if not condition:
        raise ValueError(message)


class NativeAuthoringRequestError(ValueError):
    def __init__(self, message, diagnostic):
        super().__init__(message)
        self.diagnostic = diagnostic


def _diagnostic_value(value):
    if type(value) is str:
        return value[:120]
    if value is None or type(value) in (bool, int):
        return value
    return repr(value)[:120]


def _role_request_error(creator, row, reason):
    phase, slot = row['phase'], row['position_index']
    diagnostic = {'operation': 'roles', 'phase': _diagnostic_value(phase),
                  'position_index': _diagnostic_value(slot),
                  'requested': {'role': _diagnostic_value(row['role'])},
                  'rejection_reason': str(reason)[:240], 'legal_phases': list(PHASE_OFFSETS),
                  'legal_position_indices': list(range(11)), 'automatic_substitution_applied': False}
    location = f'{diagnostic["phase"]} slot {diagnostic["position_index"]}'
    if type(phase) is str and phase in PHASE_OFFSETS and type(slot) is int and 0 <= slot < 11:
        records_before = creator.records()
        raw_before = bytes(creator.uc.mem_read(CREATOR, 0x800))
        serialized_before = creator.serialize()
        choices = legal_roles(creator, phase, slot)
        _need(creator.records() == records_before and bytes(creator.uc.mem_read(CREATOR, 0x800)) == raw_before
              and creator.serialize() == serialized_before, 'Native diagnostic queries unexpectedly changed the creator')
        diagnostic.update(choices)
        diagnostic['diagnostic_queries_mutated_creator'] = False
        diagnostic['legal_choices_provenance'] = 'original_position_role_mask_and_flag0_predicates'
        location += f' ({choices["position_name"]})'
        legal = ', '.join(choices['legal_roles'])
    else:
        legal = 'use a listed phase and position index0..10'
    diagnostic['native_binary_sha256'] = verify_assets()['plugin_sha256']
    return NativeAuthoringRequestError(
        f'Cannot author {location}: requested {diagnostic["requested"]["role"]}. '
        f'{diagnostic["rejection_reason"]}. Legal roles: {legal}.', diagnostic)


def _is_role_request_rejection(error):
    reason = str(error)
    return reason in {'Unknown tactic phase', 'Position index must be an integer from0 through10',
                      'Explicit compiled role name required',
                      'Known legacy role is removed by the native phase filter',
                      'Native position role mask refuses requested role',
                      'Native role-word predicate refuses requested role',
                      'The game offers more than one stored word for this role at this position; none is chosen'} \
        or reason.startswith('Unknown compiled role:')


def source_hashes():
    return {name: hashlib.sha256((HERE/name).read_bytes()).hexdigest() for name in SOURCE_FILES}


def verify_assets():
    core.verify_native_binary()
    data = role_catalog()
    paths = [(core.P.parents[4]/'Resources/data/il2cpp_data/Metadata/global-metadata.dat', data['metadata_sha256']),
             (core.P.parent.parent/'Resources/data/game_simulation/templates/user_folder/languages/example.ltf', data['english_resource_sha256'])]
    for path, digest in paths:
        with path.open('rb') as handle:
            _need(hashlib.file_digest(handle, 'sha256').hexdigest() == digest,
                  'Native authoring metadata or English definitions changed')
    return data


def _pointer(phase, slot):
    _need(type(phase) is str and phase in PHASE_OFFSETS, 'Unknown tactic phase')
    _need(type(slot) is int and 0 <= slot < 11, 'Position index must be an integer from0 through10')
    return CREATOR + PHASE_OFFSETS[phase] + 72*slot


def _record(creator, phase, slot):
    _pointer(phase, slot)
    return next(row for row in creator.records() if row['phase'] == phase and row['slot'] == slot)


def current_instructions(creator, phase, slot):
    row = _record(creator, phase, slot)
    key = row['role'] & 0xFFFBFFFFF91FFFFF
    entries = bytes.fromhex(row['vectors'][0])
    matches = [entries[at:at+24] for at in range(0, len(entries), 24)
               if struct.unpack_from('<Q', entries, at)[0] == key]
    _need(len(matches) <= 1, 'Duplicate current-role native instruction key')
    bits = struct.unpack_from('<Q', matches[0], 8)[0] if matches else 0
    return {'phase': phase, 'position_index': slot, 'native_role_word': f'{row["role"]:016x}',
            'current_role_key': f'{key:016x}', 'entry_present': bool(matches),
            'stored_bits': f'{bits:016x}', 'selected_native_option_ids': [i for i in range(43) if bits & (1 << i)]}


def _role_slice(creator, phase, slot, word):
    pointer = _pointer(phase, slot)
    start, end = (0x539184, 0x5391CC) if phase == 'in_possession' else (0x539508, 0x53954C)
    creator.calls.clear(); creator.writes.clear(); creator.services.clear()
    for register, value in [(UC_ARM64_REG_SP, STACK), (UC_ARM64_REG_X19, 0),
                            (UC_ARM64_REG_X20, pointer), (UC_ARM64_REG_X21, word)]:
        creator.uc.reg_write(register, value)
    creator.uc.emu_start(start, end, count=300000)
    _need(creator.uc.reg_read(UC_ARM64_REG_PC) == end, 'Original native role edit did not finish')
    return {'original_native_start': hex(start), 'original_native_stop': hex(end),
            'instructions': len(creator.calls), 'scope': 'Original role mask setter, native role-word normalization and instruction reconciliation; owner UI notification excluded.'}


def _position_names(data):
    names = {}
    for row in data['positions']:
        aliases = [row['compiled_english_name'], '+'.join(row['metadata_mask_components'])]
        for name in aliases:
            if name:
                _need(name not in names or names[name] == row['native_mask'], 'Ambiguous native position name')
                names[name] = row['native_mask']
    return names


def _set_positions(creator, requested, data):
    _need(type(requested) is dict and set(requested) <= set(PHASE_OFFSETS), 'Positions require named complete phase layouts')
    names = _position_names(data); desired = {}
    for phase, labels in requested.items():
        _need(type(labels) is list and len(labels) == 11 and all(type(name) is str and name in names for name in labels),
              'Each requested phase requires exactly11 known canonical position names')
        masks = [names[name] for name in labels]
        _need(len(set(masks)) == 11 and masks[0] == 1 and masks.count(1) == 1,
              'A phase requires11 distinct canonical positions with goalkeeper in slot0')
        desired[phase] = masks
    changes = []
    for phase, masks in desired.items():
        for slot, mask in enumerate(masks):
            before = _record(creator, phase, slot)
            if before['position_mask'] == mask:
                continue
            _need(creator.set_position(phase, before['position_mask'], mask) == 1, 'Original native position setter refused')
            changes.append({'phase': phase, 'position_index': slot, 'before_mask': before['position_mask'], 'requested_mask': mask})
        actual = [_record(creator, phase, slot)['position_mask'] for slot in range(11)]
        _need(actual == masks, 'Original native position normalization does not reproduce the requested layout')
    return changes


# Requests written for the earlier interface carried a fourth field beside the role. It is
# accepted so those requests keep working, then dropped unread: it selects nothing and is
# never echoed. The stored word comes from the game's own legal set for the named role.
IGNORED_LEGACY_ROLE_FIELDS = frozenset({'duty'})


def _set_roles(creator, requested):
    _need(type(requested) is list and len(requested) <= 22, 'Roles require a bounded list of up to22 named selections')
    proposals = []; seen = set()
    for row in requested:
        _need(type(row) is dict and set(row) - IGNORED_LEGACY_ROLE_FIELDS == {'phase', 'position_index', 'role'},
              'Each role requires exact phase, position_index and role fields')
        key = (row['phase'], row['position_index'])
        try:
            _pointer(*key)
            proposal = validate_role_request(creator, *key, row['role'])
        except ValueError as error:
            if _is_role_request_rejection(error):
                raise _role_request_error(creator, row, error) from error
            raise
        _need(key not in seen, 'Duplicate requested role slot'); seen.add(key)
        proposals.append((row, proposal))
    changes = []
    for row, proposal in proposals:
        phase, slot = row['phase'], row['position_index']; before = _record(creator, phase, slot)
        changed = before['role'] != proposal['native_word']
        trace = _role_slice(creator, phase, slot, proposal['native_word']) if changed else None
        after = _record(creator, phase, slot)
        _need(after['role'] == proposal['native_word'], 'Native role normalization did not reproduce the requested role')
        validate_loaded_selection(creator, phase, slot)
        changes.append({'phase': phase, 'position_index': slot, 'role': row['role'],
                        'before_word': f'{before["role"]:016x}', 'after_word': f'{after["role"]:016x}',
                        'changed': changed, 'native_execution': trace})
    return changes


def _reset_current(creator, phase, slot):
    validate_loaded_selection(creator, phase, slot)
    before = current_instructions(creator, phase, slot)
    word = _record(creator, phase, slot)['role']
    creator.call(0x4976430 if phase == 'in_possession' else 0x4976930, [_pointer(phase, slot), word])
    after = current_instructions(creator, phase, slot)
    _need(not after['selected_native_option_ids'], 'Original native current-role instruction reset did not clear stored selections')
    return {'before': before, 'after': after}


def _set_player_instructions(creator, requested, data):
    _need(type(requested) is list and len(requested) <= 22, 'Player instructions require a bounded list of up to22 records')
    by_name = {row['metadata_name']: row['native_option'] for row in data['player_instructions']}
    plans = []; seen = set()
    for row in requested:
        _need(type(row) is dict and {'phase', 'position_index', 'instructions'} <= set(row)
              and set(row) <= {'phase', 'position_index', 'instructions', 'mark_specific_position'},
              'Player instructions require phase, position_index, instructions and an optional named mark_specific_position target')
        key = (row['phase'], row['position_index']); _pointer(*key)
        _need(key not in seen, 'Duplicate player-instruction slot'); seen.add(key)
        labels = row['instructions']
        _need(type(labels) is list and len(labels) <= 40 and all(type(label) is str and label in by_name for label in labels), 'Unknown or oversized compiled player instruction selection')
        _need(len(set(labels)) == len(labels), 'Duplicate player instruction')
        ids = [by_name[label] for label in labels]
        _need(all(1 <= option <= 42 and option not in UNBOUND_PLAYER_OPTIONS for option in ids), 'PI0 is a sentinel; PI34/35 require typed marking targets')
        availability = [instruction_availability(creator, *key, option) for option in ids]
        _need(all(row['native_available'] for row in availability), 'Requested player instruction is unavailable in the original native editor context: '+str(availability))
        target = None
        if 'mark_specific_position' in row:
            _need(row['phase'] == 'out_of_possession', 'Specific-position marking is supported only in the proved out-of-possession setter context')
            names = _position_names(data); label = row['mark_specific_position']
            _need(type(label) is str and label in names, 'Specific-position marking requires an exact canonical target position name')
            _need(names[label] != 1, 'The original specific-position target menu excludes goalkeeper targets')
            target_availability = instruction_availability(creator, *key, 35)
            _need(target_availability['native_available'], 'Specific-position marking is unavailable in this original native editor context')
            target = {'name': label, 'native_mask': names[label], 'native_availability': target_availability,
                      'target_domain': '25_canonical_non_goalkeeper_position_masks',
                      'native_target_setter_accessor_and_reload_verified': True,
                      'native_editor_target_picker_offering_verified': True,
                      'target_picker_proof_scope': 'Compiled original menu control flow and typed append emit exactly25 non-goalkeeper canonical targets; rendered UI not observed',
                      'rendered_target_picker_observed': False}
        plans.append((row, ids, availability, target))
    results = []
    for row, ids, availability, target in plans:
        phase, slot = row['phase'], row['position_index']; reset = _reset_current(creator, phase, slot)
        pointer = _pointer(phase, slot); word = _record(creator, phase, slot)['role']
        for option in ids:
            if phase == 'in_possession':
                creator.call(0x4ADF614, [pointer, option, 0, 0, 0, 0, word])
            else:
                creator.call(0x4ADF4EC, [pointer, option, 0, 0, word])
        if target is not None:
            # Explicit target-mode selection: the original opposition table does
            # not clear specific-player marking when specific-position is set.
            creator.call(0x4ADF894, [pointer, 34, word])
            creator.call(0x4976154, [pointer, 35, 0, 0, target['native_mask'], 0, word])
            _need(creator.call(0x4975AD0, [pointer]) == target['native_mask'], 'Original specific-position target accessor mismatch')
            _need(creator.call(0x4975978, [pointer]) & 255 == 255, 'Specific-player target remains active after position target-mode selection')
        after = current_instructions(creator, phase, slot)
        _need(after['selected_native_option_ids'] == sorted(ids + ([35] if target is not None else [])), 'Conflicting or coupled native player instructions do not reproduce the exact requested selection')
        results.append({'phase': phase, 'position_index': slot, 'instructions': row['instructions'],
                        'mark_specific_position': target,
                        'native_availability': availability, 'before': reset['before'], 'after': after})
    return results


def _preserve_header(payload, source):
    # The original current-game writer normalizes version/build bytes11..14.
    # This file API preserves the inspected supported source format instead.
    return payload[:11] + source[11:15] + payload[15:]


def _phase_correspondence(creator):
    """Original bounded forward/inverse accessors, including FF fallback."""
    raw = list(creator.uc.mem_read(CREATOR+0x7B4, 11))
    forward = [creator.call(0x48578F0, [CREATOR, slot]) for slot in range(11)]
    inverse = [creator.call(0x4857908, [CREATOR, slot]) for slot in range(11)]
    return {'stored': raw, 'forward': forward, 'inverse': inverse}



def validate_complete_selection(creator, data):
    canonical = {row['native_mask'] for row in data['positions']}
    for phase in PHASE_OFFSETS:
        records = [_record(creator, phase, slot) for slot in range(11)]
        masks = [row['position_mask'] for row in records]
        _need(all(mask in canonical for mask in masks) and len(set(masks)) == 11
              and masks[0] == 1 and masks.count(1) == 1,
              'Every output phase requires11 distinct canonical positions and one goalkeeper in slot0')
        for slot in range(11):
            validate_loaded_selection(creator, phase, slot)

def author(payload, request):
    _need(type(request) is dict and set(request) <= {'positions', 'roles', 'player_instructions', 'instruction_policy', 'team_instructions'}, 'Unsupported native authoring fields')
    _need(payload[:11] == bytes.fromhex('03016361742e2200224400') and payload[11] in (26, 27), 'Native authoring requires supported v68 source26 or27')
    data = verify_assets(); hashes = source_hashes(); creator = NativeCreator(payload); creator.core = core
    baseline = _preserve_header(creator.serialize(), payload)
    _need(baseline == payload, 'Source is not an unchanged canonical whole-native serialization')
    before = creator.records()
    correspondence_before = _phase_correspondence(creator)
    positions = _set_positions(creator, request.get('positions', {}), data)
    roles = _set_roles(creator, request.get('roles', []))
    team = None
    if 'team_instructions' in request:
        _need(type(request['team_instructions']) is list, 'Team instructions require a list of exact names')
        _need('Distribute To Specific Team-Mate' not in request['team_instructions'], 'Team instruction41 requires an explicit team-mate target binding')
        team = apply_team_instructions(creator, request['team_instructions'])
    policy = request.get('instruction_policy', 'preserve')
    _need(policy in ('preserve', 'native_defaults'), 'Unknown native player-instruction policy')
    defaults = [_reset_current(creator, phase, slot) for phase in PHASE_OFFSETS for slot in range(11)] if policy == 'native_defaults' else []
    instructions = _set_player_instructions(creator, request.get('player_instructions', []), data)
    validate_complete_selection(creator, data)
    expected = creator.records(); output = _preserve_header(creator.serialize(), payload)
    reloaded = NativeCreator(output)
    _need(reloaded.records() == expected, 'Whole native serializer/reloader typed record mismatch')
    for instruction in instructions:
        target = instruction.get('mark_specific_position')
        if target is not None:
            pointer = _pointer(instruction['phase'], instruction['position_index'])
            _need(reloaded.call(0x4975AD0, [pointer]) == target['native_mask'], 'Reloaded specific-position target accessor mismatch')
            _need(reloaded.call(0x4975978, [pointer]) & 255 == 255, 'Reloaded specific-player target mode remains active')
    _need(bytes(reloaded.uc.mem_read(CREATOR+0xE0, 16)) == bytes(creator.uc.mem_read(CREATOR+0xE0, 16)), 'Whole native serializer/reloader team selection mismatch')
    correspondence_after = _phase_correspondence(creator)
    if positions:
        forward, inverse = correspondence_before['forward'], correspondence_before['inverse']
        _need(sorted(forward) == list(range(11)) and all(inverse[forward[slot]] == slot for slot in range(11)),
              'Layout edits require an unambiguous existing phase/player correspondence')
        _need(correspondence_after == correspondence_before,
              'Original position normalization changed phase/player correspondence; the preserve-existing policy cannot reproduce this layout')
    _need(_phase_correspondence(reloaded) == correspondence_after, 'Whole native serializer/reloader phase correspondence mismatch')
    _need(_preserve_header(reloaded.serialize(), payload) == output, 'Native authoring export is not stable after reload')
    verify_assets(); _need(source_hashes() == hashes, 'Native authoring sources changed during execution')
    changed = [{'phase': row['phase'], 'position_index': row['slot']} for row, old in zip(expected, before) if row != old]
    return output, {'mode': 'original_owned_creator_authoring', 'positions': positions, 'roles': roles,
                    'team_instructions': team,
                    'team_instruction_policy': 'exact_validated_replacement' if team is not None else 'preserve_inherited_without_whole_selection_legality_claim',
                    'instruction_policy': policy, 'current_role_resets': defaults,
                    'player_instructions': instructions, 'current_role_instructions': [current_instructions(reloaded, phase, slot) for phase in PHASE_OFFSETS for slot in range(11)],
                    'changed_records': changed, 'native_records': expected, 'native_team_flags_hex': bytes(creator.uc.mem_read(CREATOR+0xE0, 16)).hex(), 'native_binary_sha256': data['plugin_sha256'],
                    'phase_correspondence': {'before': correspondence_before['stored'], 'after': correspondence_after['stored'],
                                             'original_accessors_before': correspondence_before,
                                             'original_accessors_after': correspondence_after,
                                             'policy': 'preserve_existing_player_correspondence',
                                             'native_reload_verified': True, 'scope': 'Original source cross-phase player identity correspondence is retained. Layout edits target the explicit phase records; creating or rebinding player identity correspondence is unavailable. Independent of optional player instructions.'},
                    'source_hashes': hashes, 'source_header_preserved': output[:15] == payload[:15],
                    'source_game_major': payload[11], 'native_complete_loader_accepted': True,
                    'native_complete_serializer_and_reload_verified': True, 'all22_typed_records_verified': True, 'all22_position_role_selections_legal': True,
                    'native_initialization': creator.initialization, 'native_pages': creator.pages,
                    'scope': 'Original native positions, role-word normalization, instruction reset/setters and whole parent serialization in isolated owned memory. Inactive role instruction profiles remain preserved unless native reconciliation changes them. Raw editor availability states2/3 are not classified as mandatory/on. Effective behavior, player lineup assignment, full UI parity and FM import are unverified.'}


def inspect_current_profiles(creator, data):
    """Inspect present/absent profiles without inserting native default values.

    The original raw optional getter inserts a missing profile. We walk the
    stored vector instead, then use target getters only for existing selections.
    Full native serialization before/after fences every discovery callback.
    """
    before = creator.serialize()
    creator_before = bytes(creator.uc.mem_read(CREATOR, 0x800))
    original_records = creator.records()
    names = {row['native_option']: row['metadata_name'] for row in data['player_instructions']}
    position_names = {row['native_mask']: row['compiled_english_name'] or '+'.join(row['metadata_mask_components'])
                      for row in data['positions']}
    profiles = []
    for record in original_records:
        phase, slot = record['phase'], record['slot']
        profile = current_instructions(creator, phase, slot)
        _need(creator.call(0x4976140, [_pointer(phase, slot)]) == int(profile['current_role_key'], 16),
              'Original pure normalized-key getter disagrees with stored profile discovery')
        ids = profile['selected_native_option_ids']
        profile['selected_metadata_names'] = [names[option] for option in ids]
        profile['unclassified_stored_bits'] = [bit for bit in range(43, 64) if int(profile['stored_bits'], 16) & (1 << bit)]
        profile['native_editor_availability'] = [instruction_availability(creator, phase, slot, option) for option in range(1, 43)]
        pointer = _pointer(phase, slot)
        if 34 in ids:
            value = creator.call(0x4975978, [pointer]) & 255
            profile['specific_player_target'] = {'stored_selection_byte': value,
                                                 'signed_selection_index': value if value < 128 else value - 256,
                                                 'canonical_person_binding_verified': False}
        else:
            profile['specific_player_target'] = None
        if 35 in ids:
            mask = creator.call(0x4975AD0, [pointer])
            profile['specific_position_target'] = {'native_mask': mask, 'canonical_name': position_names.get(mask),
                                                   'known_canonical_encoding': mask in position_names,
                                                   'in_new_authoring_target_domain': mask in position_names and mask != 1,
                                                   'actor_phase_supported_by_typed_authoring': phase == 'out_of_possession',
                                                   'actor_native_editor_available': next(row['native_available'] for row in profile['native_editor_availability'] if row['native_option'] == 35)}
        else:
            profile['specific_position_target'] = None
        profiles.append(profile)
    correspondence = _phase_correspondence(creator)
    after = creator.serialize()
    _need(creator.records() == original_records and after == before
          and bytes(creator.uc.mem_read(CREATOR, 0x800)) == creator_before,
          'Native profile discovery unexpectedly changed the complete stored creator')
    return {'current_role_profiles': profiles, 'phase_correspondence': correspondence,
            'full_native_serialization_unchanged': True,
            'complete_creator_bytes_unchanged': True,
            'serialized_creator_sha256_before': hashlib.sha256(before).hexdigest(),
            'serialized_creator_sha256_after': hashlib.sha256(after).hexdigest(),
            'scope': 'Stored current-role optional selections only; absent profiles remain absent and inactive role profiles are not merged. Original editor availability states2/3 remain raw, not mandatory/on. Player target bytes are not canonical person bindings. New authoring target admission is separate from reporting inherited raw target encodings.'}


def catalog_for_payload(payload=None):
    data = verify_assets(); creator = NativeCreator(payload) if payload is not None else None
    source_serialization = creator.serialize() if creator is not None else None
    source_records = creator.records() if creator is not None else None
    source_creator = bytes(creator.uc.mem_read(CREATOR, 0x800)) if creator is not None else None
    legal = []
    for row in creator.records() if creator is not None else []:
        legal.append(legal_roles(creator, row['phase'], row['slot']))
    inspection = inspect_current_profiles(creator, data) if creator is not None else None
    if creator is not None:
        _need(creator.records() == source_records and creator.serialize() == source_serialization
              and bytes(creator.uc.mem_read(CREATOR, 0x800)) == source_creator,
              'Native catalog discovery unexpectedly changed the complete stored creator')
    verify_assets()
    return {'positions': data['positions'], 'roles': data['roles'],
            'record_legality': 'evaluated_for_supplied_template' if creator is not None else 'evaluated_during_authoring',
            'legal_roles_for_current_positions': legal if creator is not None else None, 'player_instructions': data['player_instructions'],
            'template_instruction_inspection': inspection,
            'unbound_player_instruction_ids': [0, 34, 35], 'team_instructions': team_catalog(),
            'typed_player_instruction_targets': {'mark_specific_position': {'native_option_id': 35,
                'phase': 'out_of_possession', 'target': 'canonical_position_name',
                'target_domain': '25_canonical_non_goalkeeper_position_masks',
                'excluded_target_masks': [0, 1],
                'native_editor_actor_availability_required': True,
                'native_editor_target_picker_offering_verified': True,
                'target_picker_proof_scope': 'Compiled original control flow50EA10..50EA68,512144..51237C and unconditional typed append51CEFC..51CFA0; rendered UI not observed',
                'rendered_target_picker_observed': False,
                'policy': 'replace_current_optional_selection_and_clear_specific_player_target_mode'}},
            'instruction_policies': ['preserve', 'native_defaults'], 'native_binary_sha256': data['plugin_sha256'],
            'scope': 'Source-backed named definitions with original native legality checks; no tactic file created and no game process touched.'}



def validate_authored_payload(payload, expected_records):
    verify_assets()
    creator = NativeCreator(payload)
    records = creator.records()
    validate_complete_selection(creator, role_catalog())
    _need(type(expected_records) is list and len(expected_records) == 22 and records == expected_records,
          'Post-pack native records differ from the requested authoring result')
    _need(_preserve_header(creator.serialize(), payload) == payload, 'Post-pack complete native serialization is not stable')
    core.verify_native_binary()
    return {'native_complete_loader_accepted': True, 'all22_typed_records_verified': True,
            'native_team_flags_hex': bytes(creator.uc.mem_read(CREATOR+0xE0, 16)).hex(),
            'native_mentality_id': creator.uc.mem_read(CREATOR+0x105, 1)[0],
            'payload_sha256': hashlib.sha256(payload).hexdigest()}

def main():
    try:
        text = sys.stdin.read(2000001); _need(len(text) <= 2000000, 'Native authoring request exceeds input budget')
        params = json.loads(text)
        _need(type(params) is dict and set(params) <= {'action', 'payload_base64', 'request', 'expected_records'}, 'Unsupported native authoring transport')
        payload = base64.b64decode(params['payload_base64'], validate=True) if 'payload_base64' in params else None
        if params.get('action') == 'catalog':
            result = catalog_for_payload(payload)
        elif params.get('action') == 'validate':
            result = validate_authored_payload(payload, params['expected_records'])
        elif params.get('action') == 'author':
            output, receipt = author(payload, params['request'])
            result = {'payload_base64': base64.b64encode(output).decode(), 'receipt': receipt}
        else:
            raise ValueError('Unknown native authoring action')
        print(json.dumps(result, ensure_ascii=False))
    except Exception as error:
        if isinstance(error, NativeAuthoringRequestError):
            print(json.dumps({'error': str(error), 'type': type(error).__name__, 'diagnostic': error.diagnostic}, ensure_ascii=False), file=sys.stderr)
        else:
            print('Native authoring failed: '+str(error), file=sys.stderr)
        raise SystemExit(1)


if __name__ == '__main__':
    main()
