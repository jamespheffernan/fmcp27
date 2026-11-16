"""Add stored instruction fields and compact native guards to a typed fixture."""
import struct

from fm_live_mcp import prepared_tactic_instructions as instructions


# Independent raw selections captured from the three owned creators in batch11.
SAMPLES = (
    (3, (2, 5, 35, 43, 44, 52, 54, 58, 61, 66, 71, 78)),
    (5, (5, 13, 19, 25, 35, 44, 46, 52, 54, 58, 61, 65, 70, 76)),
    (6, (2, 5, 13, 19, 35, 42, 44, 46, 52, 54, 61, 65, 70, 76)),
)


def add_instruction_context(m):
    """Return m with instruction_samples and set_instruction_details helper.

    Required keys: base, put, creator_addresses. Existing source/phase fields
    remain intact. The setter accepts a creator address, signed mentality and
    option_ids (including opaque test bits0..127).
    """
    for rva, raw in instructions.NATIVE_SPANS:
        m['put'](m['base'] + rva, raw)

    def set_instruction_details(creator_address, mentality=5, option_ids=()):
        flags = sum(1 << index for index in set(option_ids))
        m['put'](creator_address + 0xE0, flags.to_bytes(16, 'little'))
        m['put'](creator_address + 0x105, struct.pack('<b', mentality))

    creators = m['creator_addresses']
    for index, creator in enumerate(creators):
        if creator:
            mentality, options = SAMPLES[index % len(SAMPLES)]
            set_instruction_details(creator, mentality, options)
    m.update(instruction_samples=SAMPLES, set_instruction_details=set_instruction_details)
    return m
