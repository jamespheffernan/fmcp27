"""Scoped raw64 for direct10FF49C only; index32 delegates unchanged B34."""
from . import _actual64_common, _actual64_contracts, _actual64_middle, _actual64_offers, _actual_tail
import struct

def parse_prefix(data, start, *, reference_mode):
    if reference_mode != 'raw64':
        raise ValueError('explicit reference mode required')
    if type(start) is not int or not 0 <= start <= len(data):
        raise ValueError('invalid start')
    at = start

    def take(n):
        nonlocal at
        if n > len(data) - at:
            raise ValueError('truncated raw64 actualprefix')
        b = data[at:at + n]
        at += n
        return b
    first = take(2)
    ref = take(8)
    scalar = take(6)
    opaque = take(8)
    byte = take(1)[0]
    count = take(1)[0]
    values = list(struct.unpack('<' + 'I' * count, take(4 * count)))
    return {'start': start, 'end': at, 'object_102_103_raw': first.hex(), 'object_d8_reference_raw64_hex': ref.hex(), 'object_104_109_raw': scalar.hex(), 'object_e8_ef_raw': opaque.hex(), 'object_10b_u8': byte, 'object_68_count': count, 'object_68_source_values': values, 'next_native': 'CA8220', 'reference_mode': 'raw64'}

def parse_actual(data, start, *, reference_mode, full_contract_reader=None, option_reader=None):
    prefix = parse_prefix(data, start, reference_mode=reference_mode)
    at = prefix['end']
    parts = [{'phase': 'prefix', 'parsed': prefix}]
    contracts = _actual64_contracts
    if at + 5 > len(data):
        raise ValueError('truncated A framing')
    astart = at
    b0 = struct.unpack_from('<I', data, at)[0]
    count = data[at + 4]
    at += 5
    if count > 5:
        raise ValueError('unsupported A native slot capacity')
    slots = []
    for _ in range(count):
        if at >= len(data):
            raise ValueError('truncated A subtype')
        kind = struct.unpack_from('<b', data, at)[0]
        at += 1
        if kind in (0, 1):
            if full_contract_reader is None:
                raise ValueError(f'Unproved raw64 full contract kind{kind} at{at}')
            value = full_contract_reader(data, at, kind=kind, reference_mode='raw64')
        elif kind in (2, 3, 4, 5):
            value = contracts.parse_contract(data, at, kind)
        else:
            value = None
        if value is not None:
            if type(value.get('end')) is not int or not at <= value['end'] <= len(data):
                raise ValueError('bad A child handoff')
            at = value['end']
        slots.append({'kind': kind, 'child': value})
    parts.append({'phase': 'optional', 'parsed': {'start': astart, 'end': at, 'word': b0, 'count': count, 'slots': slots}})

    def offer_contract(data, start, *, kind, **context):
        expected = dict(source_version=3754, global_source_version=3754, minor=9, body_mode=1, read_base=0, reference_mode='raw64')
        if context != expected:
            raise ValueError('Unsupported explicit offer contract context')
        if kind in (0, 1):
            if full_contract_reader is None:
                raise ValueError(f'Unproved raw64 offer contract kind{kind} at{start}')
            return full_contract_reader(data, start, kind=kind, reference_mode='raw64')
        return contracts.parse_contract(data, start, kind, **context)
    for name, fn, kw in [('collection', _actual64_offers.parse, {'contract_reader': offer_contract, 'option_reader': option_reader}), ('middle', _actual64_middle.decode, {'reference_mode': 'raw64'}), ('tail', _actual_tail.parse, {})]:
        value = fn(data, at, **kw)
        if value['start'] != at:
            raise ValueError('bad segment start')
        at = value['end']
        parts.append({'phase': name, 'parsed': value})
    return {'start': start, 'end': at, 'parts': parts, 'complete_actual_body': True, 'reference_mode': 'raw64', 'references_resolved': False}

def parse_common(data, start, *, reference_mode, language_mode):
    return _actual64_common.parse_common_body(data, start, source_version=3754, global_source_version=3754, global_minor=9, body_mode=1, read_base=0, reference_mode=reference_mode, language_mode=language_mode)
