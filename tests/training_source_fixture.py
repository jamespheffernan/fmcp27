"""Reusable checked HUMAN, TEAM and resident training assignment source."""
import struct

import pytest

from fm_live_mcp import training_source
from prepared_tactics_fixture import (prepared_tactics_memory, team_memory,
                                     database_memory, memory, world_memory)


@pytest.fixture
def training_source_memory(prepared_tactics_memory):
    m = prepared_tactics_memory
    base = m['base']
    for rva, raw in training_source.NATIVE_SPANS:
        m['put'](base+rva, raw)
    manager = m['allocate'](0x100)
    m['typed_at'](manager, training_source.MANAGER_VTABLE, b'16TRAINING_MANAGER')
    m['q'](base+training_source.MANAGER_ROOT, manager)
    m['put'](base+training_source.ASSIGNMENT_MODE, b'\x01')
    owner = m['allocate'](0xA8)
    m['q'](owner+0x90, m['manager']+0x548)
    m['q'](owner+0x98, m['club'])
    m['vec'](manager+0x38, [owner])
    node = m['allocate'](0xC0)
    m['q'](node+0x10, owner+0x50)
    m['q'](node+0x20, m['team'])
    m['q'](owner+0x48, node)
    m['q'](owner+0x50, node)
    m['q'](owner+0x58, 1)

    def wrapper(day=301, year=2030, codes=None, upper_bits=0):
        address = m['allocate'](0x58)
        m['put'](address+0xC, struct.pack('<HH', day | (upper_bits << 9), year))
        rows = codes or [[108,101,104], [300,500,300], [301,300,300],
                         [3,1,2], [4,7,5], [300,500,300], [301,300,300]]
        for index, row in enumerate(rows):
            m['put'](address+0x10+index*8, b'\0\0'+struct.pack('<hhh', *row))
        return address

    def weeks(values):
        m['vec'](node+0x48, values)

    wrappers = [wrapper(301, upper_bits=61), wrapper(308)]
    weeks(wrappers)
    m.update(training_manager=manager, training_owner=owner, training_team_node=node,
             training_wrapper_addresses=wrappers, training_wrapper=wrapper,
             set_training_weeks=weeks, training_source_gate=base+training_source.ASSIGNMENT_MODE,
             training_source_root=base+training_source.MANAGER_ROOT)
    return m
