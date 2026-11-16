"""Original creator OOP position mutation on genuine loaded source records, offline."""
from pathlib import Path
import hashlib, importlib.util, json, struct, sys
from unicorn import UC_HOOK_CODE, UC_HOOK_MEM_INVALID
from unicorn.arm64_const import *
sys.path.append('/Users/jamesheffernan/GitHub/FM26 Deepener/.venv/lib/python3.14/site-packages')
ROOT=Path(__file__).resolve().parents[1]
def module(name,path):
    spec=importlib.util.spec_from_file_location(name,path);value=importlib.util.module_from_spec(spec);spec.loader.exec_module(value);return value
core_path=ROOT/'tests/native_body_validator.py'
assert hashlib.sha256(core_path.read_bytes()).hexdigest()=='f8b25c729557c57edaae16d65ab8f6b32f19a7dec2ab22a426fad986f97b5b4a'
core=module('core',core_path);w=module('writer',ROOT/'pi/fm-tactic-files.py')
PLUGIN=w.ROLE_NATIVE_PLUGIN;ARM=0x5ed4000
with PLUGIN.open('rb') as stream:
    assert hashlib.file_digest(stream,'sha256').hexdigest()=='774cacde63567fd3901c47719e7a6ed94cc3a0a62e9b94989dcac6b4890ec0e1'
    stream.seek(ARM);header=struct.unpack('<8I',stream.read(32));at=ARM+32;segments=[]
    for _ in range(header[4]):
        stream.seek(at);cmd,size=struct.unpack('<II',stream.read(8))
        if cmd==0x19:
            name=stream.read(16).rstrip(b'\0').decode();address,memsize,fileoff,filesize=struct.unpack('<4Q',stream.read(32));segments.append((name,address,memsize,fileoff,filesize))
        at+=size
    def page_bytes(page):
        seg=next((s for s in segments if s[1]<=page and page+4096<=s[1]+s[4]),None)
        assert seg is not None,f'Unproved native/BSS dependency {page:x}'
        stream.seek(ARM+seg[3]+page-seg[1]);raw=stream.read(4096);assert len(raw)==4096;return raw
    def load(payload):
        created=[];old=core.Uc
        def constructor(*args):
            machine=old(*args);created.append(machine)
            return machine
        core.Uc=constructor
        try:result=core.validate_payload(payload,controls=False)
        finally:core.Uc=old
        assert result['accepted'] and result['consumed_exact_eof'],result
        return created[0],result
    def record(machine,phase,index):
        pointer=0x100400000+dict(in_possession=0x120,out_of_possession=0x440)[phase]+72*index
        raw=bytes(machine.mem_read(pointer,72));primary=[];secondary=[]
        for offset,step,out in [(8,24,primary),(40,16,secondary)]:
            start,end,capacity=struct.unpack_from('<3Q',raw,offset)
            assert start<=end<=capacity and (end-start)%step==0 and end-start<=8192
            out.extend(bytes(machine.mem_read(at,step)).hex() for at in range(start,end,step))
        return dict(position=struct.unpack_from('<I',raw)[0],byte4=raw[4],byte32=raw[32],role=struct.unpack_from('<Q',raw,64)[0],primary=primary,secondary=secondary)
    source=w.TEMPLATES/'3421 FM27 .fmf';donor=w.TEMPLATES/'3421 FM27 Def.fmf'
    _,source_bytes,sm=w.read_template(str(source));_,donor_bytes,dm=w.read_template(str(donor));donor_machine,donor_load=load(dm['.tac'])
    rows=[]
    for preconverted,slot,new_mask in [(None,4,4),(None,7,8),(4,7,8),(7,4,4)]:
        source_tac=sm['.tac']
        if preconverted is not None:
            a=w.phase_records(source_tac)['out_of_possession'][preconverted];b=w.phase_records(dm['.tac'])['out_of_possession'][preconverted]
            source_tac=source_tac[:a['record_offset']]+dm['.tac'][b['record_offset']:b['record_end_exclusive']]+source_tac[a['record_end_exclusive']:]
        machine,source_load=load(source_tac);creator_before=bytes(machine.mem_read(0x100400000,0x800));before={(phase,i):record(machine,phase,i) for phase in ['in_possession','out_of_possession'] for i in range(11)}
        expected=record(donor_machine,'out_of_possession',slot);old_mask=before['out_of_possession',slot]['position'];pages={};pcs=[];serialized=[]
        def missing(uc,access,address,size,value,data):
            page=address&~4095
            if not 4096<=page<0x6000000:return False
            try:raw=page_bytes(page)
            except AssertionError:return False
            uc.mem_map(page,4096);uc.mem_write(page,raw);pages[hex(page)]=w.sha(raw);return True
        def observe(uc,address,size,data):
            pcs.append(address)
            if address==0x100500300:uc.emu_stop()
            elif address==0x100500800:
                count=uc.reg_read(UC_ARM64_REG_X2);assert 0<=count<=8192
                pointer=uc.reg_read(UC_ARM64_REG_X1)
                for page in range(pointer&~4095,((pointer+max(count,1)-1)&~4095)+4096,4096):
                    try:uc.mem_read(page,1)
                    except Exception:
                        raw=page_bytes(page);uc.mem_map(page,4096);uc.mem_write(page,raw);pages[hex(page)]=w.sha(raw)
                serialized.append(bytes(uc.mem_read(pointer,count)))
                uc.reg_write(UC_ARM64_REG_X0,count);uc.reg_write(UC_ARM64_REG_PC,uc.reg_read(UC_ARM64_REG_X30))
            assert len(pcs)<200000
        machine.hook_add(UC_HOOK_MEM_INVALID,missing);machine.hook_add(UC_HOOK_CODE,observe)
        for reg,value in [(UC_ARM64_REG_SP,0x100110000),(UC_ARM64_REG_X0,0x100400000),(UC_ARM64_REG_X1,old_mask),(UC_ARM64_REG_X2,new_mask),(UC_ARM64_REG_X3,0),(UC_ARM64_REG_X4,1),(UC_ARM64_REG_X30,0x100500300)]:machine.reg_write(reg,value)
        error=None
        try:machine.emu_start(0x4857afc,0,count=200000)
        except Exception as exc:error=str(exc)
        after={(phase,i):record(machine,phase,i) for phase in ['in_possession','out_of_possession'] for i in range(11)}
        changed=[f'{phase}:{i}' for (phase,i),value in before.items() if after[phase,i]!=value]
        creator_after=bytearray(machine.mem_read(0x100400000,0x800));start=0x440+72*slot
        creator_after[start:start+72]=creator_before[start:start+72]
        assert bytes(creator_after)==creator_before
        setter_result=machine.reg_read(UC_ARM64_REG_X0);setter_stop=hex(machine.reg_read(UC_ARM64_REG_PC));setter_instructions=len(pcs)
        # Original serializer writes through a bounded in-memory output stream.
        machine.mem_write(0x100300400,struct.pack('<Q',0x100300500));machine.mem_write(0x100300410,b'\0'*4)
        machine.mem_write(0x100300530,struct.pack('<Q',0x100500800));machine.mem_write(0x100300600,struct.pack('<Q',0x100300400))
        for reg,value in [(UC_ARM64_REG_SP,0x100110000),(UC_ARM64_REG_X0,0x100400440+72*slot),(UC_ARM64_REG_X1,0x100300600),(UC_ARM64_REG_X30,0x100500300)]:machine.reg_write(reg,value)
        serializer_error=None
        try:machine.emu_start(0x4ade568,0,count=200000)
        except Exception as exc:serializer_error=str(exc)
        donor_record=w.phase_records(dm['.tac'])['out_of_possession'][slot];donor_wire=dm['.tac'][donor_record['record_offset']:donor_record['record_end_exclusive']]
        source_record=w.phase_records(source_tac)['out_of_possession'][slot]
        serialized_bytes=b''.join(serialized)
        patched=source_tac[:source_record['record_offset']]+serialized_bytes+source_tac[source_record['record_end_exclusive']:]
        patched_machine,patched_load=load(patched)
        patched_records={(phase,i):record(patched_machine,phase,i) for phase in ['in_possession','out_of_possession'] for i in range(11)}
        assert patched_records==after
        phase_rows=w.phase_records(source_tac)['out_of_possession']
        phase_sha=w.sha(b''.join(source_tac[r['record_offset']:r['record_end_exclusive']] for r in phase_rows))
        native_pins={hex(page):w.sha(page_bytes(page)) for page in sorted({at&~4095 for at in pcs if 4096<=at<0x6000000})}
        native_pins.update(pages)
        row=dict(slot=slot,preconverted_slot=preconverted,source_OOP_phase_sha256=phase_sha,source_record_sha256=w.sha(source_tac[source_record['record_offset']:source_record['record_end_exclusive']]),creator_outside_target_record_unchanged=True,native_pins=native_pins,source=str(source),source_sha256=w.sha(source_bytes),donor=str(donor),donor_sha256=w.sha(donor_bytes),before=before['out_of_possession',slot],after=after['out_of_possession',slot],expected_donor=expected,changed_records=changed,native_position_setter='0x4857afc',native_result=setter_result,native_stop=setter_stop,original_setter_instructions=setter_instructions,native_serializer='0x4ade568',original_serializer_instructions=len(pcs)-setter_instructions,serialized_sha256=w.sha(serialized_bytes),donor_record_sha256=w.sha(donor_wire),serialized_record_matches_donor=serialized_bytes==donor_wire,serializer_error=serializer_error,patched_full_native_loader=patched_load,patched_22_records_match=True,OOP_reconciliation_calls=pcs.count(0x497970c),matches_donor=after['out_of_possession',slot]==expected,error=error,extra_native_pages=pages,native_live_calls=False,game_reads=False,game_import_verified=False)
        rows.append(row)

    (ROOT/'evidence/roles-20261109').mkdir(parents=True,exist_ok=True)
    (ROOT/'evidence/roles-20261109/phase-position-native-proof.json').write_text(json.dumps(rows,indent=2)+'\n')
    observed_pins={int(key,16):value for row in rows for key,value in row['native_pins'].items()}
    assert observed_pins=={at:digest for at,size,digest in w.PHASE_POSITION_NATIVE_SPANS if size==4096}
    assert {slot for major,slot in w.PHASE_POSITION_CASES if major==27}=={4,7}
    for (major,slot),(before_mask,after_mask,source_sha,donor_sha,phases) in w.PHASE_POSITION_CASES.items():
        if major!=27:continue
        cases=[row for row in rows if row['slot']==slot]
        assert {row['source_OOP_phase_sha256'] for row in cases}==set(phases)
        assert all(row['before']['position']==before_mask and row['after']['position']==after_mask and row['source_record_sha256']==source_sha and row['donor_record_sha256']==donor_sha for row in cases)
    w.verify_phase_position_native()
    print(json.dumps(rows,indent=2))
    assert all(r['error'] is None and r['native_result']==1 and r['native_stop']=='0x100500300' and r['matches_donor'] and r['serialized_record_matches_donor'] and r['serializer_error'] is None and r['patched_22_records_match'] and r['changed_records']==[f"out_of_possession:{r['slot']}"] for r in rows)
