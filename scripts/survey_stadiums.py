"""Bounded read-only stadium census for independent field-decoder verification."""
from collections import Counter
from datetime import datetime, timezone
import json
import math
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
    rows, identity, start = [], None, 0
    types = {}
    try:
        while True:
            with bridge.lock, bridge._read_scope(sid):
                process = bridge._current(sid)
                layout = bridge._player_layout(process)
                base = layout[0]-players.RVA[0]
                read, save, _ = bridge._world_state(process, layout)
                info = database.table(read, base, 'stadiums')
                assert info['count'] <= 100000
                assert identity is None or identity == info['identity']
                identity = info['identity']
                end = min(start+200, info['count'])
                batch = []
                for index in range(start, end):
                    address = world.pointer(read, info['start']+index*8)
                    raw = read(address, 0xC0)
                    assert players.u64(raw) == base+0x55BD7B0
                    assert int.from_bytes(raw[8:12], 'little') == index
                    assert world.pointer(read, base+0x55BD7B0+24) == base+0x16C8BC8
                    vt = base+0x55BD7B0
                    assert int.from_bytes(read(vt-16, 8), 'little', signed=True) == 0
                    ti = world.pointer(read, vt-8)
                    text = players.u64(read(ti+8, 8))
                    assert read(text, len(b'N2db7STADIUME')+1) == b'N2db7STADIUME\0'
                    row = {'address':hex(address), 'database_index':index,
                           'native_id':int.from_bytes(raw[12:16], 'little'),
                           'random_id':int.from_bytes(raw[16:20], 'little'), 'raw':raw.hex()}
                    for field, offset in (('name',0x40),('continental_name',0x48)):
                        pointer = players.u64(raw, offset)
                        value = None
                        if pointer:
                            size = int.from_bytes(read(pointer,4),'little')
                            assert size <= 512
                            data = read(pointer+4,size+1)
                            assert data[-1] == 0
                            value = data[:-1].decode('utf-8')
                            assert all(ord(c)>=32 and ord(c)!=127 for c in value)
                        row[field] = value
                    row['capacity'] = dict(zip(('capacity','seating','used','all_seater','expansion'),
                                                struct.unpack_from('<5i',raw,0x7C)))
                    row['pitch_dimensions_raw'] = list(struct.unpack_from('<8h',raw,0x98))
                    row['coordinates'] = list(struct.unpack_from('<2f',raw,0x70))
                    assert all(math.isfinite(n) for n in row['coordinates'])
                    row['dates_raw'] = {hex(o):int.from_bytes(raw[o:o+4],'little') for o in (0x28,0x2C,0x30,0x34)}
                    row['codes'] = {hex(o):struct.unpack_from('<b',raw,o)[0] for o in (0xAA,0xAC,0xAD,0xAE,0xAF,0xB0,0xB1,0xB2,0xB3,0xB4)}
                    row['pitch_condition'] = struct.unpack_from('<h',raw,0xA8)[0]
                    row['flags'] = {'ab':raw[0xAB], 'b6':int.from_bytes(raw[0xB6:0xB8],'little')}
                    row['links'] = {}
                    for field, offset in (('city',0x60),('nearby_stadium',0x68),('owner',0x90)):
                        pointer = players.u64(raw,offset)
                        link = None
                        if pointer:
                            vtable = world.pointer(read,pointer)
                            assert base+0x5400000 <= vtable < base+0x56A4000
                            typeinfo = world.pointer(read,vtable-8)
                            label = players.u64(read(typeinfo+8,8))
                            name = read(label,128).split(b'\0')[0].decode()
                            key = hex(vtable-base)
                            types[key] = name
                            linked_index, native_id, random_id = struct.unpack('<III',read(pointer+8,12))
                            link = {'address':hex(pointer), 'vtable':key, 'index':linked_index,
                                    'native_id':native_id, 'random_id':random_id}
                            if field == 'nearby_stadium':
                                assert linked_index < info['count'] and world.pointer(read,info['start']+linked_index*8)==pointer
                        row['links'][field] = link
                    batch.append(row)
                read.verify()
                bridge._current(sid)
            rows.extend(batch)
            start = end
            if start % 2000 == 0: print(f'{start}/{info["count"]}',flush=True)
            if end == info['count']:break
    finally:
        bridge.detach()
    receipt = {'verified':True, 'observed_at':datetime.now(timezone.utc).isoformat(),
               'count':len(rows), 'stadiums':rows, 'linked_types':types,
               'foreground_ui_used':False, 'native_execution':False,
               'scope':'Independent raw stored stadium census; no active-match suitability or computed pitch dimensions'}
    (ROOT/'evidence/stadium-survey.json').write_text(json.dumps(receipt,indent=2)+'\n')
    print(json.dumps({'count':len(rows), 'linked_types':types,
                     'names':{field:dict(Counter('null' if r[field] is None else 'empty' if not r[field] else 'text' for r in rows)) for field in ('name','continental_name')},
                     'codes':{hex(offset):dict(Counter(r['codes'][hex(offset)] for r in rows)) for offset in (0xAC,0xAD,0xAF,0xB0,0xB4)}},indent=2))


if __name__ == '__main__':
    survey()
