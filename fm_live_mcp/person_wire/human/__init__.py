"""Bounded source3754/minor9 HUMAN_NON_PLAYER wire composition.

The HUMAN body forces localC98=1; inherited NON_PLAYER/common readers run after
its restoration under the existing raw64 profile. Transport globals remain a
conditional source witness, never observed runtime state. No evidence files,
filesystem imports, semantic HUMAN payloads or database-sized copies are used.
"""
from functools import lru_cache, partial
from .. import _bindings
from . import (
    prefix, properties, nation, child_12b6058, child_12ba224,
    child_12ba224_488b5ac, child_12ba224_4893974, child_138eee4,
    child_1459f20, child_145c4e4, child_151a5b4, child_1553588,
    child_1557180, child_1637acc, child_1637acc_111988c,
    child_1637acc_184d150, child_1637acc_child4ad0c70, child_1637acc_nested,
    child_16e03a4, child_171c8c8, child_181d89c, child_1897120,
    child_6e8330, child_compound6458, child_dd_vectors, child_heap1060,
    child_team_mode3, primitive_children,
)

MAX_BODY_BYTES = 32 * 1024**2
MAX_DIRECT_CHILDREN = 32768


class UnsupportedHumanBudget(ValueError):
    def __init__(self, offset):
        self.offset, self.native = offset, 0x12C2608
        super().__init__('Unsupported HUMAN offline record/child work budget')


@lru_cache(maxsize=1)
def _children():
    context = dict(nation.FIXED_CONTEXT)
    rich = {
        0x17f090c: child_1637acc_nested.parse,
        0x4ad0c70: child_1637acc_child4ad0c70.parse,
        0x184d150: child_1637acc_184d150.parse,
        0x111988c: child_1637acc_111988c.parse,
        0x151a5b4: child_151a5b4.parse_vector,
    }
    children = {
        0x11182bc: nation.read,
        0x43fd1e0: properties.parse,
        0x1553588: partial(child_1553588.parse, reference_profile='local1_streambit1', local_2c98=1, global_3523=1),
        0x1637acc: partial(child_1637acc.parse, child_readers=rich, reference_context=context, variant_switch3522=0),
        0x12ba224: partial(child_12ba224.parse, child_readers={
            0x488b5ac: child_12ba224_488b5ac.parse, 0x4893974: child_12ba224_4893974.parse}),
        0x1459f20: partial(child_1459f20.parse, variant_reader=properties.parse_variant),
        0x145c4e4: child_145c4e4.parse,
        0x138eee4: partial(child_138eee4.parse, reference_context=dict(child_138eee4.RAW32)),
        0x1557180: partial(child_1557180.parse, reference_context=dict(child_1557180.RAW32)),
        0x181d89c: child_181d89c.parse,
        0x1897120: child_1897120.parse,
        0x6e8330: child_6e8330.parse,
        0x16e03a4: child_16e03a4.parse,
        0xdd15ec: partial(child_dd_vectors.parse, team_reader=child_team_mode3.parse),
        0x12b6058: child_12b6058.parse,
        0x12c6458: child_compound6458.parse,
        0x171c8c8: partial(child_171c8c8.parse, reference_context=context),
        0x12c7e88: partial(child_heap1060.parse, variant_reader=properties.parse_variant),
    }
    for native in (0xd895e0, 0xd8984c, 0x1314594, 0x11c3c40):
        children[native] = partial(primitive_children.parse, native=native)
    return children


def parse(data, start, *, ordinal, limit=None, source_major=3754, minor=9):
    if (type(source_major), type(minor)) != (int, int) or (source_major, minor) != (3754, 9):
        raise ValueError('Unsupported explicit HUMAN source version')
    if type(ordinal) is not int or not 0 <= ordinal < 2_000_000:
        raise ValueError('Invalid HUMAN original ordinal')
    bound = len(data) if limit is None else limit
    if type(start) is not int or type(bound) is not int or not 0 <= start < bound <= len(data):
        raise ValueError('Invalid HUMAN record extent')
    # All helpers retain absolute coordinates; this is a zero-copy view even for
    # a 512MiB database. The local bound limits the supported record span.
    bound = min(bound, start + MAX_BODY_BYTES)
    bounded = memoryview(data)[:bound]
    calls = 0

    def guarded(reader):
        def child(data, at, **kwargs):
            nonlocal calls
            calls += 1
            if calls > MAX_DIRECT_CHILDREN:
                raise UnsupportedHumanBudget(at)
            return reader(data, at, **kwargs)
        return child

    children = {native: guarded(reader) for native, reader in _children().items()}
    specific = prefix.parse(bounded, start, children=children, limit=bound)
    if specific.get('complete_human_specific_wire') is not True:
        raise ValueError('Incomplete HUMAN specific wire')
    inherited_start = specific['end']
    at = _bindings.nonplayer_specific(bounded, inherited_start)
    value = _bindings.shared_suffix(bounded, at, ordinal=ordinal, include_actual=True)
    # HUMAN-specific rows are consumed for exact traversal, never projected as
    # football facts or retained in the population prefix cache.
    return {**value, 'human_wire_summary': {
        'specific_start': start, 'specific_end': inherited_start,
        'max_body_bytes': MAX_BODY_BYTES, 'max_direct_children': MAX_DIRECT_CHILDREN,
        'direct_children_checked': calls, 'specific_payload_projected': False,
        'native_reader': '0x12c2608', 'native_writer': '0x12cc17c',
        'profile': 'source3754/minor9; HUMAN localC98=1; compact NATION; switch3522=0; inherited raw64; native globals unobserved',
    }}
