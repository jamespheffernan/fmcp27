"""Census stored fixture-name links and strings without invoking their formatter."""
from datetime import datetime, timezone
import json
from pathlib import Path
import struct
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from fm_live_mcp import database, players, world
from fm_live_mcp.bridge import Bridge


def survey():
    bridge = Bridge()
    sid = bridge.attach()['session_id']
    result = {'verified': False, 'observed_at': datetime.now(timezone.utc).isoformat(),
              'stage_names': [], 'fixture_names': []}
    identities = {}
    try:
        for kind in ('stage_names', 'fixture_names'):
            start = 0
            while True:
                with bridge.lock, bridge._read_scope(sid):
                    process = bridge._current(sid)
                    layout = bridge._player_layout(process)
                    base = layout[0]-players.RVA[0]
                    read, save, _ = bridge._world_state(process, layout)
                    info = database.table(read, base, kind)
                    assert info['count'] <= 100000
                    assert identities.setdefault(kind, info['identity']) == info['identity']
                    end = min(start+200, info['count'])
                    batch = []
                    for index in range(start, end):
                        address = world.pointer(read, info['start']+index*8)
                        raw = read(address, 0x48 if kind == 'fixture_names' else 0x40)
                        expected_vtable = 0x55AB970 if kind == 'fixture_names' else 0x55BD9E8
                        assert players.u64(raw) == base+expected_vtable
                        vt = base+expected_vtable
                        assert int.from_bytes(read(vt-16, 8), 'little', signed=True) == 0
                        ti = players.u64(read(vt-8, 8))
                        name_pointer = players.u64(read(ti+8, 8))
                        name = b'N2db12FIXTURE_NAMEE' if kind == 'fixture_names' else b'N2db10STAGE_NAMEE'
                        assert read(name_pointer, len(name)+1) == name+b'\0'
                        assert int.from_bytes(raw[8:12], 'little') == index
                        row = {'address': hex(address), 'database_index': index,
                               'native_id': int.from_bytes(raw[12:16], 'little'), 'raw': raw.hex()}
                        if kind == 'stage_names':
                            for field, offset in (('name', 24), ('short_name', 32), ('plural_name', 40)):
                                pointer = int.from_bytes(raw[offset:offset+8], 'little')
                                value = None
                                if pointer:
                                    size = int.from_bytes(read(pointer, 4), 'little')
                                    assert 0 <= size <= 512
                                    text = read(pointer+4, size+1)
                                    assert text[-1] == 0
                                    value = text[:-1].decode('utf-8')
                                    assert all(ord(c) >= 32 and ord(c) != 127 for c in value)
                                row[field] = value
                        else:
                            for field, offset, table in (('competition', 24, 'competitions'),
                                    ('component_1', 32, 'stage_names'), ('component_2', 40, 'stage_names'),
                                    ('component_3', 48, 'stage_names'), ('secondary_competition', 64, 'competitions')):
                                pointer = int.from_bytes(raw[offset:offset+8], 'little')
                                link = None
                                if pointer:
                                    linked_index, linked_id = struct.unpack('<II', read(pointer+8, 8))
                                    linked_table = database.table(read, base, table)
                                    assert linked_index < linked_table['count']
                                    assert world.pointer(read, linked_table['start']+linked_index*8) == pointer
                                    assert world.pointer(read, pointer) == base+(0x559ED88 if table == 'competitions' else 0x55BD9E8)
                                    link = {'database_index': linked_index, 'native_id': linked_id}
                                row[field] = link
                        batch.append(row)
                    read.verify()
                    bridge._current(sid)
                result[kind].extend(batch)
                start = end
                if end == info['count']:
                    break
    finally:
        bridge.detach()
    result.update(verified=True, foreground_ui_used=False, native_execution=False)
    (ROOT/'evidence/fixture-name-survey.json').write_text(json.dumps(result, indent=2)+'\n')
    print(json.dumps({'verified': True, **{k:len(result[k]) for k in ('stage_names','fixture_names')},
          'components': {str(i):sum(r[f'component_{i}'] is not None for r in result['fixture_names']) for i in (1,2,3)},
          'secondary_competitions':sum(r['secondary_competition'] is not None for r in result['fixture_names'])}, indent=2))


if __name__ == '__main__':
    survey()
