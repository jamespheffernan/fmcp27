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
from unicorn.arm64_const import UC_ARM64_REG_PC, UC_ARM64_REG_SP, UC_ARM64_REG_X0, UC_ARM64_REG_X1, UC_ARM64_REG_X2, UC_ARM64_REG_X3, UC_ARM64_REG_X4, UC_ARM64_REG_X19, UC_ARM64_REG_X20, UC_ARM64_REG_X21, UC_ARM64_REG_LR

sys.path.append('/Users/jamesheffernan/GitHub/FM26 Deepener/.venv/lib/python3.14/site-packages')
ROOT = Path(__file__).resolve().parents[1]
PLUGIN = Path.home() / 'Library/Application Support/Steam/steamapps/common/Football Manager 27/fm.app/Contents/PlugIns/game_plugin.bundle/Contents/MacOS/game_plugin'
spec = importlib.util.spec_from_file_location('tactics', ROOT/'pi/fm-tactic-files.py')
writer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(writer)

def main():
    slot = int(sys.argv[2]) if len(sys.argv) > 2 else 7
    position, mask = {7: ('AM(R)', 2048), 9: ('AM(L)', 4096)}[slot]
    source = writer.TEMPLATES/'4231 FM27 Att.fmf'
    donor = writer.TEMPLATES/'4231 FM27 .fmf'
    _, source_bytes, sm = writer.read_template(str(source))
    _, donor_bytes, dm = writer.read_template(str(donor))
    a = writer.phase_records(sm['.tac'])['in_possession'][slot]
    b = writer.phase_records(dm['.tac'])['in_possession'][slot]
    assert sm['.tac'][11] == dm['.tac'][11] == 26
    assert a['position_mask'] == b['position_mask'] == mask
    assert a['native_role_word'] == '0000000000400080' and b['native_role_word'] == '0000000008800000'
    prefix = sm['.tac'][a['record_offset']:a['role_word_offset']]
    assert prefix == dm['.tac'][b['record_offset']:b['role_word_offset']]
    entries = []
    for index in range(a['instruction_entry_count']):
        at = a['instruction_vector_offset'] + index*24
        assert sm['.tac'][at+8:at+11] == b'\2\2\2'
        entries.append((struct.unpack_from('<Q', sm['.tac'], at)[0], struct.unpack_from('<Q', sm['.tac'], at+11)[0]))
    assert entries == [(0x80, 0x2050000), (0x8000000, 0x2050000), (0x80000000000, 0x2050000), (0x200000000000, 0x2050000), (0x2000000000000, 0x2050000)]
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
        uc.mem_map(stack, 0x10000)
        uc.mem_write(record, struct.pack('<I', mask))
        uc.mem_write(record+8, struct.pack('<QQQ', vector, vector+len(entries)*24, vector+len(entries)*24))
        uc.mem_write(record+0x40, struct.pack('<Q', 0x400080))
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
            assert stack <= address and address+size <= stack+0x10000 or record <= address and address+size <= record+0x48 or vector <= address and address+size <= vector+len(original_vector), f'Unexpected emulated write {address:x}'
            writes.append((address,size,value))
        def on_code(machine, address, size, data):
            pcs.append(address)
            assert len(pcs) < 10000
        uc.hook_add(UC_HOOK_MEM_READ_UNMAPPED | UC_HOOK_MEM_FETCH_UNMAPPED, fault)
        uc.hook_add(UC_HOOK_MEM_READ, on_read)
        uc.hook_add(UC_HOOK_MEM_WRITE, on_write)
        uc.hook_add(UC_HOOK_CODE, on_code)
        uc.reg_write(UC_ARM64_REG_SP, stack+0xF000)
        uc.reg_write(UC_ARM64_REG_X19, 0)
        uc.reg_write(UC_ARM64_REG_X20, record)
        uc.reg_write(UC_ARM64_REG_X21, 0x8800000)
        uc.emu_start(0x539184, 0x5391CC, count=10000)
        assert uc.reg_read(UC_ARM64_REG_PC) == 0x5391CC
        result = struct.unpack('<Q', uc.mem_read(record+0x40,8))[0]
        assert result == 0x8800000
        assert uc.mem_read(vector,len(original_vector)) == original_vector
        assert all(stack <= address < stack+0x10000 or address == record+0x40 for address,size,value in writes)
        pinned = {offset: digest for offset, size, digest in writer.INSIDE_FORWARD_NATIVE_SPANS if size == 4096}
        assert {page: hashlib.sha256(raw).hexdigest() for page, raw in native_pages.items()} == pinned
        output = {'state':'native_inside_forward_setter_record_slice_matches_actual_donor', 'source':str(source),'source_sha256':hashlib.sha256(source_bytes).hexdigest(),
                  'donor':str(donor),'donor_sha256':hashlib.sha256(donor_bytes).hexdigest(), 'source_format_major':26,'position':position,'slot':slot,
                  'source_word':'0000000000400080','donor_word':f'{result:016x}','prefix_sha256':hashlib.sha256(prefix).hexdigest(),
                  'original_native_instructions':len(pcs),'validator_calls':pcs.count(0x4973360),'record_reconciliation_calls':pcs.count(0x4976F28),
                  'native_pages':[{ 'address':hex(p),'sha256':hashlib.sha256(raw).hexdigest()}for p,raw in sorted(native_pages.items())],
                  'PI_entries_unchanged':True,'outer_owner_callback_executed':False,'full_UI_setter_parity':False,'game_import_verified':False,
                  'native_live_calls':False,'game_reads':False,'scope':'Actual source/donor role inputs loaded into explicitly synthetic native object/vector memory; unchanged native setter/reconciliation code executes only in Unicorn.'}
        if len(sys.argv) > 1 and sys.argv[1]:
            Path(sys.argv[1]).write_text(json.dumps(output,indent=2)+'\n')
        print(json.dumps(output,indent=2))

if __name__ == '__main__':
    main()
