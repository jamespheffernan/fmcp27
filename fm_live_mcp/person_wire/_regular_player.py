"""Bounded regular ACTUAL_PLAYER composition; explicit native stops, no guesses."""
from . import _identity, _actual64_contracts, _actual64_parse, _contract_extra, _contract_full, _national_children_family_f218, _person_player, _player_after_ring, _player_continue, _player_f0, _player_individual_training, _player_tail, _ring_limit
_base = _identity
_initial = _person_player
_ring = _player_continue
_after = _player_after_ring
_tail = _player_tail
_wire_ring = _ring_limit
_f0 = _player_f0
_actual = _actual64_parse
_contract = _contract_full
_contract_extra = _contract_extra
_contract_base = _actual64_contracts
_variant = _national_children_family_f218
_training = _player_individual_training

def _variant_value(data, start):
    return _variant._Reader(data, start, 10000, 32, 1048576).variant(0)

def _full_contract(data, start, *, kind, reference_mode):
    if kind != 0 or reference_mode != 'raw64':
        raise ValueError('Unsupported regular-player full-contract context')
    return _contract.parse(data, start, reference_mode=reference_mode, extra_reader=_contract_extra.parse, base_reader=_contract_base.parse_fe4904)

class UnsupportedPlayer(ValueError):

    def __init__(self, native, offset, parts, reason):
        self.native, self.offset, self.parts = (native, offset, parts)
        super().__init__(f'Unsupported regular ACTUAL_PLAYER reader {native} at {offset}: {reason}')

def parse(data, start, *, ordinal, reference_mode='raw64', source_major=3754, minor=9, initial_ring_count=0, collection_limit=None, variant_reader=None, individual_training_reader=None, f0_reader=None, ring_policy='source_wire', full_contract_reader=None, language_mode=1, f0_child_readers=None, tail_child_readers=None, body_only=False, actual_reader=None):
    if type(ordinal) is not int or not 0 <= ordinal < 2000000:
        raise ValueError('Invalid player ordinal')
    if reference_mode not in ('raw32', 'raw64'):
        raise ValueError('Explicit raw32/raw64 player transport required')
    if ring_policy not in ('native_checked', 'source_wire'):
        raise ValueError('Unsupported ring policy')
    parts = {}
    width = 8 if reference_mode == 'raw64' else 4
    parts['initial'] = _initial.parse_initial(data, start, reference_word_bytes=width, source_major=source_major, minor=minor, body_mode=1)
    at = parts['initial']['end']
    try:
        if ring_policy == 'source_wire':
            measured = _ring.parse_measurement(data, at)
            c = measured['end']
            if c + 5 > len(data):
                raise ValueError('Truncated player ring scalar prefix')
            wire = _wire_ring.parse_ring_wire(data, c + 5, end=len(data))
            parts['measurement_and_ring'] = {'start': at, 'end': wire['end'], 'measurement': measured, 'ring': wire, 'native_fields': {'0x244': int.from_bytes(data[c:c + 4], 'little'), '0x265': data[c + 4]}}
        else:
            parts['measurement_and_ring'] = _ring.parse(data, at, initial_ring_count=initial_ring_count, collection_limit=collection_limit, source_major=source_major, minor=minor, body_mode=1)
    except ValueError as exc:
        if 'Positive ring requires' in str(exc):
            measurement = _ring.parse_measurement(data, at)
            parts['measurement'] = measurement
            raise UnsupportedPlayer('0xcfd864 positive ring collection-limit guard', measurement['end'] + 9, parts, str(exc)) from exc
        raise
    parts['measurement_and_ring']['native_acceptance_state'] = 'unproved_collection_limit' if ring_policy == 'source_wire' else 'caller_checked_limit'
    if ring_policy == 'source_wire':
        parts['measurement_and_ring']['ring']['checked_native_collection_limit'] = None
    at = parts['measurement_and_ring']['end']
    try:
        parts['embedded190_and_tail'] = _after.parse(data, at, source_major=source_major, minor=minor, body_mode=1, variant_reader=variant_reader or _variant_value, individual_training_reader=individual_training_reader or _training.parse)
    except _after.UnsupportedChild as exc:
        raise UnsupportedPlayer(hex(exc.reader), exc.offset, parts, str(exc)) from exc
    at = parts['embedded190_and_tail']['end']
    if at >= len(data):
        raise ValueError(f'Truncated PLAYER+108 marker at {at}')
    marker = data[at]
    at += 1
    child_start = at
    if marker == 1:
        if at + 30 > len(data):
            raise ValueError(f'Truncated PLAYER+108 raw30 child at {at}')
        at += 30
    parts['optional108'] = {'presence': marker, 'start': child_start, 'end': at, 'raw': data[child_start:at].hex()}
    if at >= len(data):
        raise ValueError(f'Truncated PLAYER+F0 marker at {at}')
    marker = data[at]
    at += 1
    parts['optional_f0_presence'] = marker
    if marker == 1:
        if f0_reader is None:
            f0_reader = lambda d, c: _f0.parse(d, c, reference_mode=reference_mode, source_major=source_major, minor=minor, child_readers=f0_child_readers)
        try:
            child = f0_reader(data, at)
        except _f0.UnsupportedChild as exc:
            raise UnsupportedPlayer(exc.native if hasattr(exc, 'native') else exc.reader, exc.offset, parts, str(exc)) from exc
        if not isinstance(child, dict) or type(child.get('end')) is not int or (not at < child['end'] <= len(data)):
            raise ValueError('Invalid PLAYER+F0 callback cursor')
        at = child['end']
        parts['f0'] = child
    try:
        parts['remaining_tail'] = _tail.parse(data, at, optional118_reader=(tail_child_readers or {}).get(20214628), polymorphic_reader=(tail_child_readers or {}).get(67504356), optional_f8_reader=(tail_child_readers or {}).get(20507620))
    except _tail.UnsupportedTail as exc:
        parts['remaining_tail'] = exc.parts
        raise UnsupportedPlayer(exc.native, exc.offset, parts, str(exc)) from exc
    at = parts['remaining_tail']['end']
    if body_only:
        return {'start': start, 'end': at, 'parts': parts, 'source_record_kind': 'PLAYER_specific_read_base0', 'identity': None, 'ring_policy': ring_policy, 'native_loader_acceptance_proved': False, 'reference_mode': reference_mode}
    actual_mode = 'raw64' if reference_mode == 'raw64' else 'index32'
    parts['actual_person'] = (actual_reader or _actual.parse_actual)(data, at, reference_mode=actual_mode, full_contract_reader=full_contract_reader or _full_contract)
    at = parts['actual_person']['end']
    parts['common'] = _actual.parse_common(data, at, reference_mode=actual_mode, language_mode=language_mode)
    at = parts['common']['end']
    parts['canonical_base'] = _base.parse_identity_base(data, at, ordinal=ordinal)
    ident = parts['canonical_base']['identity']
    at = parts['canonical_base']['end']
    return {'start': start, 'end': at, 'source_record_kind': 'ACTUAL_PLAYER', 'identity': ident, 'parts': parts, 'ring_policy': ring_policy, 'native_loader_acceptance_proved': False, 'reference_mode': reference_mode}

def parse_player_specific(data, start, **context):
    context['body_only'] = True
    return parse(data, start, **context)
