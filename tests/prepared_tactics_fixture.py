"""Reusable typed source-to-fields memory fixture for prepared tactics tests."""
import struct

import pytest

from fm_live_mcp import prepared_tactics_fields, prepared_tactics_source, world
from test_database import database_memory
from test_players import memory
from test_teams import team_memory
from test_world import world_memory


@pytest.fixture
def prepared_tactics_memory(team_memory):
    m = team_memory
    base = m['base']
    for module in (prepared_tactics_source, prepared_tactics_fields):
        for rva, raw in module.NATIVE_SPANS:
            m['put'](base+rva, raw)

    def typed_at(address, rva, name, displacement=0):
        info = m['allocate'](16)
        text = m['allocate'](len(name)+1)
        m['put'](text, name+b'\0')
        m['q'](info+8, text)
        m['put'](base+rva-16, struct.pack('<qQ', displacement, info))
        m['q'](address, base+rva)

    human = m['manager']
    team = m['team_addresses'][0]
    m['team'] = team
    m['q'](team+0x80, human)
    m['q'](m['contract']+0x10, team)
    m['q'](m['contract']+0x18, team)
    m['put'](base+world.TYPES['manager'][0]-0x20, struct.pack('<q', 0x548))
    typed_at(human+0x548, prepared_tactics_source.PERSON_VTABLE,
             world.TYPES['manager'][1], -0x548)
    m['q'](base+prepared_tactics_source.PERSON_VTABLE+0x1B0, base+0x1300058)
    m['q'](base+prepared_tactics_source.PERSON_VTABLE+0x6F0, base+0x1300074)
    m['put'](base+prepared_tactics_source.PERSON_VTABLE-0x700, struct.pack('<q', -0x548))
    tactics_manager = m['allocate'](0x70)
    typed_at(tactics_manager, prepared_tactics_source.MANAGER_VTABLE, b'15TACTICS_MANAGER')
    m['q'](base+prepared_tactics_source.MANAGER_ROOT, tactics_manager)
    container = m['allocate'](0xD0)
    m['q'](container+0x98, human)
    m['vec'](tactics_manager+0x20, [container])
    node = m['allocate'](0x28+0x11B8)
    m['q'](node+0x10, container+8)
    m['put'](node+0x20, struct.pack('<i', 0))
    m['q'](container, node)
    m['q'](container+8, node)
    m['q'](container+0x10, 1)
    payload = node+0x28
    typed_at(payload+0xFF8, prepared_tactics_source.PREPARED_VTABLE,
             b'N7simatch30PREPARED_TACTICS_CREATOR_ARRAYE')
    masks = [1,4,2097168,1048592,8,2097280,1048704,2048,8192,4096,16384]
    creators = []
    for name in ('Same tactic', 'Same tactic', 'Attacking'):
        creator = m['allocate'](0x7C0)
        m['q'](creator+0x790, m['text'](name))
        for offset in (0x120, 0x440):
            for index, mask in enumerate(masks):
                m['put'](creator+offset+0x48*index, struct.pack('<I', mask))
        creators.append(creator)
    m['vec'](payload+0x1000, creators)
    m['put'](payload+0x1018, b'\x00')
    coach = world.loaded(m['read'], base)[0]['coaches'][0]
    m.update(coach=coach, tactics_manager=tactics_manager, owner_container=container,
             team_node=node, tactics_payload=payload, creator_addresses=creators,
             prepared_wrapper=payload+0xFF8, typed_at=typed_at)
    return m
