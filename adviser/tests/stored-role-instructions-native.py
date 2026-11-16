"""Offline original native setter slice over actual serialized role inputs.

Native bytes are executed only inside Unicorn. It stops before the outer owner
callback; no process, game, UI, import or native live function is touched.
"""
from pathlib import Path
import hashlib
import importlib.util
import json
import struct
import sys

from unicorn import Uc, UC_ARCH_ARM64, UC_MODE_ARM, UC_HOOK_CODE, UC_HOOK_MEM_READ, UC_HOOK_MEM_WRITE, UC_HOOK_MEM_READ_UNMAPPED, UC_HOOK_MEM_FETCH_UNMAPPED
from unicorn.arm64_const import UC_ARM64_REG_PC, UC_ARM64_REG_SP, UC_ARM64_REG_X0, UC_ARM64_REG_X1, UC_ARM64_REG_X2, UC_ARM64_REG_X3, UC_ARM64_REG_X4, UC_ARM64_REG_X5, UC_ARM64_REG_X6, UC_ARM64_REG_X19, UC_ARM64_REG_X20, UC_ARM64_REG_X21, UC_ARM64_REG_LR

sys.path.append('/Users/jamesheffernan/GitHub/FM26 Deepener/.venv/lib/python3.14/site-packages')
ROOT = Path(__file__).resolve().parents[1]
PLUGIN = Path.home() / 'Library/Application Support/Steam/steamapps/common/Football Manager 27/fm.app/Contents/PlugIns/game_plugin.bundle/Contents/MacOS/game_plugin'
spec = importlib.util.spec_from_file_location('tactics', ROOT/'pi/fm-tactic-files.py')
writer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(writer)

def prove(selection):
    slot = 9
    position, mask = {9: ('AM(CL)', 1056768)}[slot]
    source = writer.TEMPLATES/'3421 FM27 .fmf'
    donor = writer.TEMPLATES/'3421 FM27 Att.fmf'
    if not selection:
        source, donor = donor, source
    before_bits, after_bits = (0, 0x9000000) if selection else (0x9000000, 0)
    _, source_bytes, sm = writer.read_template(str(source))
    _, donor_bytes, dm = writer.read_template(str(donor))
    a = writer.phase_records(sm['.tac'])['in_possession'][slot]
    b = writer.phase_records(dm['.tac'])['in_possession'][slot]
    assert sm['.tac'][11] == dm['.tac'][11] == 27
    assert a['position_mask'] == b['position_mask'] == mask
    assert a['native_role_word'] == '0000000000800200' and b['native_role_word'] == '0000000000800200'
    prefix = sm['.tac'][a['record_offset']:a['role_word_offset']]
    vector_offset = a['instruction_vector_offset'] + 24 + 11
    replaced = bytearray(sm['.tac'])
    assert struct.unpack_from('<Q', replaced, vector_offset)[0] == before_bits
    struct.pack_into('<Q', replaced, vector_offset, after_bits)
    assert replaced[a['record_offset']:a['record_end_exclusive']] == dm['.tac'][b['record_offset']:b['record_end_exclusive']]
    entries = []
    for index in range(a['instruction_entry_count']):
        at = a['instruction_vector_offset'] + index*24
        assert sm['.tac'][at+8:at+11] == b'\2\2\2'
        entries.append((struct.unpack_from('<Q', sm['.tac'], at)[0], struct.unpack_from('<Q', sm['.tac'], at+11)[0]))
    assert entries == [(0x80, 0x3010000), (0x200, before_bits), (0x20000, 0x9000000), (0x8000000, 0x3010000), (0x100000000, 0x9000000), (0x20000000000, 0x9000000), (0x80000000000, 0x3010000), (0x200000000000, 0x3010000), (0x2000000000000, 0x3010000), (0x100000000000000, 0x9000000)]
    with PLUGIN.open('rb') as stream:
        assert hashlib.file_digest(stream, 'sha256').hexdigest() == '774cacde63567fd3901c47719e7a6ed94cc3a0a62e9b94989dcac6b4890ec0e1'
        stream.seek(0x5ED4000)
        header = struct.unpack('<IIIIIIII', stream.read(32))
        assert header[0] == 0xFEEDFACF
        at = 0x5ED4000+32
        segments = []
        for _ in range(header[4]):
            stream.seek(at)
            command, size = struct.unpack('<II', stream.read(8))
            if command == 0x19:
                name = stream.read(16).rstrip(b'\0').decode()
                vmaddr, vmsize, fileoff, filesize = struct.unpack('<QQQQ', stream.read(32))
                segments.append((name, vmaddr, vmsize, fileoff, filesize))
            at += size
        uc = Uc(UC_ARCH_ARM64, UC_MODE_ARM)
        record, vector, stack = 0x10000000, 0x10010000, 0x20000000
        uc.mem_map(record, 4096)
        uc.mem_map(vector, 4096)
        control = 0x10020000
        uc.mem_map(control, 4096)
        uc.mem_write(control, struct.pack('<III', mask, 0x1B000000, 0))
        uc.mem_map(stack, 0x10000)
        uc.mem_write(record, struct.pack('<I', mask))
        uc.mem_write(record+8, struct.pack('<QQQ', vector, vector+len(entries)*24, vector+len(entries)*24))
        uc.mem_write(record+0x40, struct.pack('<Q', 0x800200))
        original_vector = b''.join(struct.pack('<QQQ', key, bits, 0) for key,bits in entries)
        uc.mem_write(vector, original_vector)
        mapped = {record, vector}
        native_pages = {}
        reads, writes, pcs = [], [], []
        def fault(machine, kind, address, size, value, data):
            page = address & ~4095
            if page in mapped:
                return False
            segment = next((s for s in segments if s[1] <= page and page+4096 <= s[1]+s[4]), None)
            if segment is None:
                raise AssertionError(f'Native reads uncaptured/non-file-backed page {address:x}')
            stream.seek(0x5ED4000 + segment[3] + page-segment[1])
            raw = stream.read(4096)
            assert len(raw) == 4096
            machine.mem_map(page, 4096)
            machine.mem_write(page, raw)
            native_pages[page] = raw
            mapped.add(page)
            return True
        def on_read(machine, kind, address, size, value, data):
            reads.append((address,size))
        def on_write(machine, kind, address, size, value, data):
            assert stack <= address and address+size <= stack+0x10000 or record <= address and address+size <= record+0x48 or vector <= address and address+size <= vector+len(original_vector) or address == control+8 and size == 4, f'Unexpected emulated write {address:x}'
            writes.append((address,size,value))
        def on_code(machine, address, size, data):
            pcs.append(address)
            assert len(pcs) < 10000
        uc.hook_add(UC_HOOK_MEM_READ_UNMAPPED | UC_HOOK_MEM_FETCH_UNMAPPED, fault)
        uc.hook_add(UC_HOOK_MEM_READ, on_read)
        uc.hook_add(UC_HOOK_MEM_WRITE, on_write)
        uc.hook_add(UC_HOOK_CODE, on_code)
        uc.reg_write(UC_ARM64_REG_SP, stack+0xF000)
        availability = []
        if selection:
            for option in (24, 27):
                uc.mem_write(control+8, bytes(4))
                for reg, value in [(UC_ARM64_REG_X0, option), (UC_ARM64_REG_X1, control), (UC_ARM64_REG_X2, 0x800200), (UC_ARM64_REG_X3, control+4), (UC_ARM64_REG_X4, control+8), (UC_ARM64_REG_LR, 0x30000000)]:
                    uc.reg_write(reg, value)
                uc.emu_start(0x4973360, 0x30000000, count=10000)
                allowed = bool(uc.reg_read(UC_ARM64_REG_X0)&1)
                state = int.from_bytes(uc.mem_read(control+8, 4), 'little')
                availability.append({'option': option, 'allowed': allowed, 'state': state})
                assert allowed and state == 0
            assert uc.mem_read(vector,len(original_vector)) == original_vector
            for option in (24, 27):
                uc.reg_write(UC_ARM64_REG_X0, record)
                uc.reg_write(UC_ARM64_REG_X1, option)
                uc.reg_write(UC_ARM64_REG_X2, 0)
                uc.reg_write(UC_ARM64_REG_X3, 0)
                uc.reg_write(UC_ARM64_REG_X4, 0)
                uc.reg_write(UC_ARM64_REG_X5, 0)
                uc.reg_write(UC_ARM64_REG_X6, 0x800200)
                uc.reg_write(UC_ARM64_REG_LR, 0x30000000)
                uc.emu_start(0x4ADF614, 0x30000000, count=10000)
        else:
            uc.reg_write(UC_ARM64_REG_X0, record)
            uc.reg_write(UC_ARM64_REG_X1, 0x800200)
            uc.reg_write(UC_ARM64_REG_LR, 0x30000000)
            uc.emu_start(0x4976430, 0x30000000, count=10000)
        assert uc.reg_read(UC_ARM64_REG_PC) == 0x30000000
        result = struct.unpack('<Q', uc.mem_read(record+0x40,8))[0]
        assert result == 0x800200
        expected_vector = bytearray(original_vector)
        struct.pack_into('<Q', expected_vector, 24+8, after_bits)
        assert uc.mem_read(vector,len(original_vector)) == expected_vector
        assert all(stack <= address < stack+0x10000 or address == vector+24+8 or address == control+8 for address,size,value in writes)
        pinned = {offset:digest for offset,size,digest in writer.STORED_ROLE_PI_NATIVE_SPANS if size==4096}
        assert all(hashlib.sha256(raw).hexdigest()==pinned[page] for page,raw in native_pages.items())
        assert len(pcs)==(842 if selection else 73)
        output = {'state':'native_stored_role_PI_profile_matches_actual_donor', 'source':str(source),'source_sha256':hashlib.sha256(source_bytes).hexdigest(),
                  'donor':str(donor),'donor_sha256':hashlib.sha256(donor_bytes).hexdigest(), 'source_format_major':27,'position':position,'slot':slot,
                  'source_word':'0000000000800200','after_role_word':f'{result:016x}', 'before_PI_word':f'{before_bits:016x}', 'after_PI_word':f'{after_bits:016x}', 'selected_before':[i for i in(24,27) if before_bits&(1<<i)], 'selected_after':[i for i in(24,27) if after_bits&(1<<i)],'prefix_sha256':hashlib.sha256(prefix).hexdigest(),
                  'original_native_instructions':len(pcs),'validator_calls':pcs.count(0x4973360), 'availability_checks':availability, 'native_PI_setter_calls':pcs.count(0x4ADF614), 'native_clear_calls':pcs.count(0x4976430), 'native_conflict_setter_calls':pcs.count(0x4ADE3F8),'record_reconciliation_calls':pcs.count(0x4976F28),
                  'native_pages':[{ 'address':hex(p),'sha256':hashlib.sha256(raw).hexdigest()}for p,raw in sorted(native_pages.items())],
                  'non_target_PI_entries_unchanged':True,'outer_owner_callback_executed':False, 'native_UI_reset_binding_proved':False,'full_UI_setter_parity':False,'game_import_verified':False,
                  'native_live_calls':False,'game_reads':False,'scope':'Actual source/donor role inputs loaded into explicitly synthetic native object/vector memory; original native selection setters and full availability predicates execute only in Unicorn.'}
        return output

if __name__ == '__main__':
    writer.verify_stored_role_pi_native()
    rows = [prove(False), prove(True)]
    if len(sys.argv)>1:
        Path(sys.argv[1]).write_text(json.dumps(rows,indent=2)+'\n')
    print(json.dumps(rows,indent=2))
