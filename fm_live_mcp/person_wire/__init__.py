"""Portable, bounded stored-PERSON record decoding for source3754/minor9.

The caller owns snapshot/format validation. All source offsets stay absolute;
no filesystem, native game, ambient globals or name lookup is accessed here.
"""
import struct
from . import _bindings, _official4, _person_tag5, _person_tag6, _person_tag7, _person_tag8, _person_tag18, human

KINDS = {1: 'ACTUAL_NON_PLAYER', 2: 'ACTUAL_PLAYER', 3: 'ACTUAL_PLAYER_AND_NON_PLAYER',
         4: 'OFFICIAL', 5: 'RETIRED_PERSON_NAME_STRINGS', 6: 'JOURNALIST', 7: 'VIRTUAL_PLAYER',
         8: 'SUPPORT_STAFF', 9: 'HUMAN_NON_PLAYER', 16: 'RETIRED_PERSON_NAME_POINTERS', 18: 'AGENT'}


def _retired(data, start, ordinal):
    if len(data) - start < 1:
        raise ValueError('Truncated retired pointer selector')
    selector = data[start]
    if selector not in (0, 1, 2, 3):
        raise ValueError('Unsupported retired pointer selector')
    size = 29 if selector == 0 else 25
    if len(data) - start < size:
        raise ValueError('Truncated retired pointer record')
    at = start + 1
    raw20 = struct.unpack_from('<I', data, at)[0] if selector == 0 else None
    at += 4 if selector == 0 else 0
    raw28, flags = struct.unpack_from('<IQ', data, at)
    identity_at = at + 12
    stored, native, secondary = struct.unpack_from('<III', data, identity_at)
    if stored != ordinal:
        raise ValueError('Retired pointer original ordinal mismatch')
    expected = 1 if flags & (1 << 29) else 2 if flags & (1 << 30) else 3 if flags & (1 << 31) else 0
    if selector != expected:
        raise ValueError('Retired pointer selector and final flags mismatch')
    if flags & 0x60000000:
        routes = (('0x28', 'common', raw28),)
    elif flags & (1 << 31):
        routes = (('0x28', 'second', raw28),)
    elif flags & (1 << 16):
        routes = (('0x20', 'second', raw20), ('0x28', 'first', raw28))
    else:
        routes = (('0x20', 'first', raw20), ('0x28', 'second', raw28))
    refs = [{'native_offset': offset, 'namespace': namespace, 'raw_index': index,
             'state': 'native_null_reference' if index & (1 << 31) else 'unresolved_name_reference'}
            for offset, namespace, index in routes]
    return {'end': start + size, 'identity': {'offset': identity_at, 'stored_index': stored,
            'native_id_word': native, 'secondary_word': secondary}, 'names': None,
            'retired_name_references': refs, 'retired_pointer_raw': {
                'selector': selector, 'raw_field20_u32': raw20, 'raw_field28_u32': raw28,
                'final_flags_u64': flags}}


def _names(value):
    if 'names' in value:
        return value['names']
    rows = value.get('parts', {}).get('common', {}).get('prefix', {}).get('names')
    return None if rows is None else [{k: row[k] for k in (
        'root_offset', 'original_reference_index', 'inline_marker', 'inline_record')} for row in rows]


def _unsupported(error):
    # A malformed extent or identity must not become an unavailable row.
    text = str(error).lower()
    if 'truncat' in text or isinstance(error.__cause__, (IndexError, struct.error)):
        return False
    if type(error).__name__.startswith('Unsupported'):
        return True
    if text.startswith(('unproved', 'unimplemented')):
        return True
    return text.startswith('unsupported') and any(term in text for term in (
        'version', 'subtype', 'kind', 'child', 'branch', 'wire mode',
        'reference', 'legacy', 'variant', 'selector',
    ))


def parse_record(data, tag_offset, ordinal, *, limit, _include_scouting=False, _include_history=False):
    """Return a compact decoded record or an explicit unsupported frontier.

    Malformed/truncated input raises ValueError. `limit` is an exclusive absolute
    member offset; no successful result can consume any byte at or beyond it.
    """
    try:
        view = memoryview(data)
    except TypeError as error:
        raise ValueError('PERSON source must be a checked byte buffer') from error
    if type(tag_offset) is not int or type(limit) is not int or not 0 <= tag_offset < limit <= len(view):
        raise ValueError('Invalid PERSON tag offset or exclusive limit')
    if type(ordinal) is not int or not 0 <= ordinal < 2_000_000:
        raise ValueError('Invalid original PERSON ordinal')
    if view.ndim != 1 or view.itemsize != 1 or not view.c_contiguous:
        raise ValueError('PERSON source must be a contiguous byte buffer')
    bounded = view.cast('B')[:limit]
    tag = struct.unpack_from('<b', bounded, tag_offset)[0]
    body = tag_offset + 1
    base = {'ordinal': ordinal, 'signed_tag': tag, 'tag_offset': tag_offset, 'body_offset': body}
    if tag not in KINDS:
        return {**base, 'state': 'unsupported', 'reason': 'unsupported_source_tag'}
    player_value = None
    try:
        if tag == 1:
            at = _bindings.nonplayer_specific(bounded, body)
            value = _bindings.shared_suffix(bounded, at, ordinal=ordinal, include_actual=True)
        elif tag == 2:
            value = _bindings.player(bounded, body, ordinal=ordinal)
            player_value = value
        elif tag == 3:
            player_value = _bindings.player(bounded, body, ordinal=ordinal, body_only=True)
            at = player_value['end']
            at = _bindings.nonplayer_specific(bounded, at)
            value = _bindings.shared_suffix(bounded, at, ordinal=ordinal, include_actual=True)
        elif tag == 4:
            value = _official4.parse(bounded, body, ordinal=ordinal)
        elif tag == 9:
            value = human.parse(bounded, body, ordinal=ordinal)
        elif tag == 16:
            value = _retired(bounded, body, ordinal)
        else:
            reader = {5: _person_tag5.parse, 6: _person_tag6.parse, 7: _person_tag7.parse,
                      8: _person_tag8.parse, 18: _person_tag18.parse}[tag]
            value = reader(bounded, body, ordinal=ordinal)
    except ValueError as error:
        if not _unsupported(error):
            raise
        native = getattr(error, 'native', getattr(error, 'reader', None))
        return {**base, 'state': 'unsupported', 'source_record_kind': KINDS[tag],
                'reason': str(error), 'native_reader': hex(native) if type(native) is int else native,
                'stopped_at': getattr(error, 'offset', None)}
    except (IndexError, struct.error) as error:
        raise ValueError('Truncated or invalid PERSON source record') from error
    end = value['end']
    identity = value['identity']
    if (type(end) is not int or not body < end <= limit or identity['stored_index'] != ordinal
            or identity['offset'] != end - 12):
        raise ValueError('Invalid PERSON record or canonical identity extent')
    names = _names(value)
    if names is not None and any(row['inline_marker'] not in (0, 1) for row in names):
        raise ValueError('PERSON inline name marker differs from current writer')
    result = {**base, 'state': 'decoded', 'source_record_kind': KINDS[tag], 'end': end,
              'identity': identity, 'names': names,
              'source_profile': 'source3754/minor9 conditional pinned writer profile; ambient native globals unobserved'}
    if _include_history and tag == 2:
        actual = player_value['parts']['actual_person']
        tail = next(part['parsed'] for part in actual['parts'] if part['phase'] == 'tail')
        owner_offset = tail['end'] - 21
        owner_raw = bytes.fromhex(tail['fixed_fields_raw']['object_bc'])
        if bytes(bounded[owner_offset:owner_offset + 4]) != owner_raw:
            raise ValueError('Archived statistics owner word differs from source')
        result['_history'] = {'owner_index': struct.unpack('<i', owner_raw)[0],
                              'source_offset': owner_offset,
                              'source_field': 'ACTUAL_PERSON+0xBC'}
    if _include_scouting and player_value is not None:
        parts = player_value['parts']
        scale_at = parts['remaining_tail']['end'] - 8
        common_raw = (value['parts']['common']['prefix']['object_58_65_raw']
                      if tag == 2 else value['_common_scalar_raw'])
        result['_scouting'] = {'raw69': bytes(bounded[body + 30:body + 99]),
            'scale_byte': bounded[scale_at], 'scale_offset': scale_at,
            'current': struct.unpack_from('<h', bounded, body + 6)[0],
            'potential': struct.unpack_from('<h', bounded, body + 8)[0],
            'birth_raw': bytes.fromhex(common_raw)[:4]}
    for key in ('stored_name_strings', 'retired_name_references', 'retired_pointer_raw',
                'native_fields', 'optional_0c', 'nation_reference', 'reference_conditions', 'human_wire_summary'):
        if key in value:
            result[key] = value[key]
    if tag == 18:
        people = value['person_vector']
        dates = value['date_word_vector']
        result['person_vector_summary'] = {
            'count': people['count'], 'count_offset': people['count_offset'],
            'rows_start': people['count_offset'] + 4, 'rows_end': dates['count_offset'],
            'entry_bytes': 4, 'payload_state': 'not_projected',
        }
        result['date_word_vector_summary'] = {
            'count': dates['count'], 'count_offset': dates['count_offset'],
            'rows_start': dates['count_offset'] + 4,
            'rows_end': value['parts']['specific_prefix']['end'] - 1,
            'entry_bytes': 8, 'payload_state': 'not_projected',
        }
    return result
