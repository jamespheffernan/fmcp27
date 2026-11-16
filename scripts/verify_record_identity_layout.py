"""Verify affected world records inherit the independently identified DATABASE_RECORD."""
import json
from pathlib import Path
import struct
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from fm_live_mcp import players, virtual, world
from fm_live_mcp.bridge import Bridge
from verify_person_identity_layout import verify


def main():
    verify()
    bridge = Bridge()
    sid = bridge.attach()['session_id']
    chains = {}
    try:
        with bridge._read_scope(sid):
            tables = bridge._player_layout(bridge.process)
            base = tables[0] - players.RVA[0]
            snapshot = world.ReadSet(lambda a, n: bridge._read_memory(bridge.process, a, n))
            record = base + 0x55A3DC8
            simple_type = players.u64(snapshot(record, 8))

            def name(info):
                pointer = players.u64(snapshot(info+8, 8))
                result = bytearray()
                for offset in range(128):
                    byte = snapshot(pointer+offset, 1)
                    if byte == b'\0':
                        return result.decode('ascii')
                    result.extend(byte)
                raise AssertionError('Unterminated RTTI name')

            assert name(record) == 'N2db15DATABASE_RECORDE'
            for kind in ('club', 'competition', 'nation', 'continent', 'language',
                         'local_region', 'weather', 'injury', 'currency', 'stadium_change'):
                info = players.u64(snapshot(base+world.TYPES[kind][0]-8, 8))
                assert name(info).encode() == world.TYPES[kind][1]
                chain = []
                for _ in range(5):
                    chain.append(name(info))
                    if info == record:
                        break
                    # __si_class_type_info has a single nonvirtual base at +16.
                    assert players.u64(snapshot(info, 8)) == simple_type, (kind, chain)
                    info = players.u64(snapshot(info+16, 8))
                assert info == record, (kind, chain)
                chains[kind] = chain
            # VIRTUAL_PLAYER uses virtual inheritance through PLAYER. Its
            # secondary PERSON vtable identifies the subobject at +0x20.
            info = players.u64(snapshot(base+world.TYPES['virtual_player'][0]-8, 8))
            assert name(info).encode() == world.TYPES['virtual_player'][1]
            assert players.u64(snapshot(info, 8)) == simple_type
            player = players.u64(snapshot(info+16, 8))
            assert name(player) == 'N2db6PLAYERE'
            assert struct.unpack('<II', snapshot(player+16, 8)) == (0, 1)
            parent, offset_flags = struct.unpack('<Qq', snapshot(player+24, 16))
            assert offset_flags == -0x17FD and name(parent) == 'N2db6PERSONE'
            chain = [name(info), name(player)]
            for _ in range(4):
                chain.append(name(parent))
                if parent == record:
                    break
                assert players.u64(snapshot(parent, 8)) == simple_type
                parent = players.u64(snapshot(parent+16, 8))
            assert parent == record and 'N2db6PERSONE' in chain
            displacement, person_info = struct.unpack('<qQ', snapshot(base+virtual.PERSON_RVA-16, 16))
            assert displacement == -32 and person_info == info
            chains['virtual_player'] = chain
            snapshot.verify()
    finally:
        bridge.detach()
    receipt = {'verified': True, 'plugin_sha256': players.SHA256, 'inheritance': chains,
               'scope': 'Build-pinned RTTI inheritance plus DATABASE_RECORD property disassembly; read-only.'}
    (ROOT/'evidence/record-identity-layout-verification.json').write_text(json.dumps(receipt, indent=2)+'\n')
    print(json.dumps(receipt, indent=2))


if __name__ == '__main__':
    main()
