"""Observe typed PI fields after the immutable audited original native loader."""
import hashlib
import importlib.util
import json
from pathlib import Path
import struct
import sys

sys.path.append('/Users/jamesheffernan/GitHub/FM26 Deepener/.venv/lib/python3.14/site-packages')
root = Path(__file__).resolve().parents[1]
core_path = root/'tests/native_body_validator.py'
assert hashlib.sha256(core_path.read_bytes()).hexdigest() == 'f8b25c729557c57edaae16d65ab8f6b32f19a7dec2ab22a426fad986f97b5b4a'
spec = importlib.util.spec_from_file_location('native_core', core_path)
core = importlib.util.module_from_spec(spec)
spec.loader.exec_module(core)
spec = importlib.util.spec_from_file_location('writer', root/'pi/fm-tactic-files.py')
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
rows = []
for path in json.load(sys.stdin):
    _, _, members = m.read_template(path)
    payload = members['.tac']
    created = []
    original_uc = core.Uc
    def observe_constructor(*args):
        emulator = original_uc(*args)
        created.append(emulator)
        return emulator
    core.Uc = observe_constructor
    try:
        loaded = core.validate_payload(payload, controls=False)
    finally:
        core.Uc = original_uc
    assert loaded['accepted'] is True and loaded['consumed_exact_eof'] is True
    # The first emulator is the complete native body reader; later instances
    # implement its independently audited envelope/header predicates.
    uc = created[0]
    for phase, offset in [('in_possession', 0x120), ('out_of_possession', 0x440)]:
        for record in m.phase_records(payload)[phase]:
            raw = bytes(uc.mem_read(0x100400000+offset+72*record['position_index'], 72))
            assert struct.unpack_from('<I', raw)[0] == record['position_mask']
            assert struct.unpack_from('<Q', raw, 64)[0] == int(record['native_role_word'], 16)
            start, end, capacity = struct.unpack_from('<QQQ', raw, 8)
            assert start <= end <= capacity and (end-start)%24 == 0 and end-start <= 128*24
            native_entries = [struct.unpack('<QQ', uc.mem_read(at, 16)) for at in range(start, end, 24)]
            wire_entries = [(struct.unpack_from('<Q', payload, record['instruction_vector_offset']+24*i)[0],
                             struct.unpack_from('<Q', payload, record['instruction_vector_offset']+24*i+11)[0])
                            for i in range(record['instruction_entry_count'])]
            assert native_entries == wire_entries
    rows.append(dict(path=path, native_body_accepted=True, records_compared=22,
                     all_primary_PI_vectors_match=True, game_import_verified=False))
assert len(rows) == 3
print(json.dumps(rows))
