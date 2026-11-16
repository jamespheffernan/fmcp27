"""Static child composition for the pinned conditional source-writer profile."""
from functools import lru_cache, partial
from . import (
    _actual64_parse as actual, _actual64_contracts as contracts,
    _actual64_common as common, _identity, _contract_full, _contract_extra,
    _full_contract80, _full_contract98, _loan_1862c00, _player_loan_contract,
    _regular_player, _nonplayer_framing, _optional_nonplayer_b0, _optional90,
    _nonplayer58, _nonplayer70, _nonplayer70_reference, _nonplayer78,
    _nonplayer98, _nonplayerA8, _player_f0, _player_11e8640, _player_11e9524,
    _player_154e184, _player_153e56c, _player_151f710, _player_155007c,
    _f0_vector18, _combined_11e9354, _player_1347364_binding,
    _player_138ebe4, _player_40608e4, _player_157c308,
)

NESTED_REFERENCE_CONTEXT = {
    'stream_flags': 2, 'root_80a': 0, 'global_3522': 0,
    'global_3523': 1, 'global_2c98': 1,
}


def full_contract(data, start, *, kind, reference_mode):
    if reference_mode != 'raw64':
        raise ValueError('Unsupported contract reference profile')
    if kind == 1:
        return _player_loan_contract.parse(
            data, start, kind=kind, reference_mode=reference_mode,
            structure68_reader=_loan_1862c00.parse,
            base_reader=contracts.parse_fe4904,
            row70_reader=_full_contract80.parse,
        )
    if kind != 0:
        raise ValueError(f'Unsupported full-contract kind {kind} at {start}')
    return _contract_full.parse(
        data, start, reference_mode=reference_mode,
        extra_reader=_contract_extra.parse, base_reader=contracts.parse_fe4904,
        row80_reader=_full_contract80.parse,
        vector98_reader=partial(_full_contract98.parse, reference_mode='direct64'),
    )


def actual_person(data, start, *, reference_mode='raw64', full_contract_reader=None):
    return actual.parse_actual(
        data, start, reference_mode=reference_mode,
        full_contract_reader=full_contract_reader or full_contract,
        option_reader=partial(_player_157c308.parse,
                              person_reference_profile='direct32_local1', stream_bit1=True),
    )


def raw64(data, start, namespace, field):
    if len(data) - start < 8:
        raise ValueError('Truncated raw64 reference')
    return {'start': start, 'end': start + 8, 'raw_hex': data[start:start + 8].hex(),
            'namespace': namespace, 'field': field, 'references_resolved': False}


def current70(data, start):
    value = _nonplayer70.parse(
        data, start,
        reference_reader=_nonplayer70_reference.make_current_writer_reader('raw64'),
    )
    _nonplayer70.validate_current_writer(value)
    return value


def current58(data, start):
    value = _nonplayer58.parse(data, start)
    _nonplayer58.validate_current_writer(value)
    return value


def nonplayer_specific(data, start):
    prefix = _nonplayer_framing.prefix(data, start, reference_word_bytes=8)
    if prefix['b0_marker'] not in (0, 1):
        raise ValueError('NON_PLAYER+B0 presence differs from current writer')
    at = prefix['end']
    if prefix['b0_marker'] == 1:
        value = _optional_nonplayer_b0.parse(data, at, reference_reader=raw64)
        _optional_nonplayer_b0.validate_current_writer(value)
        at = value['end']
    def current90(d, p):
        value = _optional90.parse(d, p)
        if value['version'] != 1 or any(row['marker'] != 1 for row in value['rows']):
            raise ValueError('NON_PLAYER+90 differs from current writer')
        return value
    rest = _nonplayer_framing.remainder(data, at, children={
        0xd7d794: current90, 0xd8a570: current70, 0x1462b9c: _nonplayerA8.parse,
        0xeed850: _nonplayer78.parse, 0x145d2c8: _nonplayer98.parse, 0x14618a8: current58,
    })
    if any(row['marker'] not in (0, 1) for row in rest['optionals']):
        raise ValueError('NON_PLAYER optional presence differs from current writer')
    return rest['end']


@lru_cache(maxsize=1)
def player_bindings():
    readers = {
        0x11e8640: _player_11e8640.parse,
        0x11e9524: _player_11e9524.parse,
        0x154e184: partial(_player_154e184.parse,
                          native_reference_context=NESTED_REFERENCE_CONTEXT),
        0x151f710: _player_151f710.parse,
        0x155007c: _player_155007c.parse,
        0x405d598: _f0_vector18.parse,
        0x11e9354: _combined_11e9354.parse,
    }
    readers[0x153e56c] = partial(_player_153e56c.parse, child_readers=readers)
    def f0(data, start):
        return _player_f0.parse(data, start, reference_mode='raw64', stream_bit1=True,
                                child_readers=readers)
    return {'f0_reader': f0, 'tail_child_readers': {
        0x1347364: _player_1347364_binding.parse,
        0x138ebe4: _player_138ebe4.parse, 0x40608e4: _player_40608e4.parse,
    }}


def player(data, start, *, ordinal, body_only=False):
    return _regular_player.parse(
        data, start, ordinal=ordinal, reference_mode='raw64', ring_policy='source_wire',
        full_contract_reader=full_contract, actual_reader=actual_person,
        body_only=body_only, **player_bindings(),
    )


def shared_suffix(data, start, *, ordinal, include_actual):
    at = start
    if include_actual:
        at = actual_person(data, at)['end']
    value = actual.parse_common(data, at, reference_mode='raw64', language_mode=0)
    identity = _identity.parse_identity_base(data, value['end'], ordinal=ordinal)
    return {'end': identity['end'], 'identity': identity['identity'],
            '_common_scalar_raw': value['prefix']['object_58_65_raw'],
            'names': [{k: row[k] for k in ('root_offset', 'original_reference_index',
                                         'inline_marker', 'inline_record')}
                      for row in value['prefix']['names']]}
