"""Bounded primary-contract source projection from a verified ACTUAL_PERSON seam.

Source3754/9, conditional raw64 direct transport and contract+98 direct64 profile.
CA83B8 stores the first serialized slot to ACTUAL_PERSON+78; CB3724 selects that
same current-contract pointer. FULL_CONTRACT1279724→FE4470→FE4904→D8B50C is
parsed in order. PCsd1005C68 selects+44; Pcex12920F8 selects+48 unless+2Bbit3
requests a computed date; Csts127BE34 selects signed+ C3. Native build SHA256:
774cacde63567fd3901c47719e7a6ed94cc3a0a62e9b94989dcac6b4890ec0e1.
No native loader globals, offer lifecycle, extension activation or whole PERSON
membership are inferred. The caller must supply an independently verified seam.
"""
import struct

from . import contract_status, world

MAX_ROWS = 4096
MAX_EXTRA_BYTES = 4096
WIRE_PROFILE = 'source3754_minor9_direct_raw64_contract98_direct64'


class _Unsupported(ValueError):
    def __init__(self, reason, offset):
        self.reason, self.offset = reason, offset
        super().__init__(reason)


class _Reader:
    def __init__(self, data, start, end):
        self.data, self.offset, self.end = data, start, end
        self.checked = []

    def take(self, size, label=None):
        if size < 0 or size > self.end - self.offset:
            raise _Unsupported('truncated_primary_contract', self.offset)
        start = self.offset
        self.offset += size
        if label:
            self.checked.append({'start': start, 'end': self.offset, 'reader': label})
        return bytes(self.data[start:self.offset])

    def number(self, code):
        return struct.unpack('<' + code, self.take(struct.calcsize('<' + code)))[0]

    def count(self, code):
        value = self.number(code)
        if value > MAX_ROWS:
            raise _Unsupported('primary_contract_count_budget', self.offset)
        return value

    def presence(self):
        value = self.number('B')
        if value not in (0, 1):
            raise _Unsupported('unsupported_current_writer_presence', self.offset - 1)
        return value

    def fixed_rows(self, count, stride, label, version=None):
        if count > (self.end - self.offset) // stride:
            raise _Unsupported('truncated_primary_contract_rows', self.offset)
        start = self.offset
        for _ in range(count):
            raw = self.take(stride)
            if version is not None and raw[0] != version:
                raise _Unsupported('unsupported_current_writer_row_version', self.offset - stride)
        self.checked.append({'start': start, 'end': self.offset, 'reader': label,
                             'count': count, 'stride': stride})


def _basic(reader, person_index, base_currency_code):
    start = reader.offset
    owner = reader.number('I')
    reader.take(8)  # Explicit raw64 reference, not a resolved club/team identity.
    # D8B50C and D8B868 serialize the signed weekly wage before three flags.
    wage_offset = reader.offset
    wage = reader.number('i')
    reader.take(3)
    reader.checked.append({'start': start, 'end': reader.offset, 'reader': 'D8B50C'})
    if owner != person_index:
        raise _Unsupported('primary_contract_owner_ordinal_mismatch', start)
    return {
        'owner_person_index': owner,
        'weekly_wage': {
            'stored_signed_amount': wage,
            'amount': wage if wage >= 0 else None,
            'period': 'week',
            'currency': base_currency_code,
            'state': ('unsupported_negative_amount' if wage < 0 else
                      'base_currency_unverified' if base_currency_code is None else 'decoded'),
            'source_offset': wage_offset,
        },
    }


def _full(reader, person_index, base_currency_code):
    start = reader.offset
    status_at = start
    status = reader.number('b')
    reader.take(16 + 8 + 1 + 2)
    clause_count = reader.number('B')
    options = []
    clause_start = reader.offset
    for native_slot in range(clause_count):
        at = reader.offset
        _, parameter, kind, flags = struct.unpack('<ihBB', reader.take(8))
        if kind == 22:
            options.append({'native_slot': native_slot, 'years_raw_signed16': parameter,
                            'flags_raw_u8': flags, 'source_offset': at})
    reader.checked.append({'start': clause_start, 'end': reader.offset,
                           'reader': '1279724_clause_vector', 'count': clause_count, 'stride': 8})
    count80 = reader.number('B')
    #132418C consumes exactly31 current-source bytes, with no variable subtree.
    reader.fixed_rows(count80, 31, '132418C')
    presence98 = reader.presence()
    count98 = 0
    if presence98:
        count98 = reader.count('I')
        if count98 > (reader.end - reader.offset) // 15:
            raise _Unsupported('truncated_contract98_direct64_rows', reader.offset)
        at = reader.offset
        for _ in range(count98):
            row_at = reader.offset
            if reader.number('H') != 1:
                raise _Unsupported('unsupported_contract98_row_version', row_at)
            reader.take(8 + 4 + 1)
        reader.checked.append({'start': at, 'end': reader.offset, 'reader': '1279E3C',
                               'count': count98, 'stride': 15, 'reference_profile': 'direct64'})
    discarded = reader.count('I')
    if discarded:
        raise _Unsupported('positive_discarded_contract_rows_unported', reader.offset)
    reader.take(1)  # Stored native+C4 byte; not a boolean or lifecycle status.
    # FE4470's final4 bytes remain pending natively; caller flushes them before
    # FE4904. Consume that physical tail exactly once in the source reader.
    extra_start = reader.offset
    if reader.number('B') != 3:
        raise _Unsupported('unsupported_FE4470_current_writer_version', extra_start)
    extra_count = reader.number('I')
    if extra_count > MAX_EXTRA_BYTES:
        raise _Unsupported('FE4470_byte_budget', reader.offset)
    reader.take(extra_count + 4)
    reader.checked.append({'start': extra_start, 'end': reader.offset, 'reader': 'FE4470'})
    shared_start = reader.offset
    reader.take(12)
    expiry_at = reader.offset
    expiry_raw = reader.take(8)[:4]
    reader.take(6)
    numeric_count = reader.count('I')
    reader.fixed_rows(numeric_count, 29, '1543D60', version=7)
    reader.take(1)
    signed_at = reader.offset
    signed_raw = reader.take(4)
    reader.take(7)
    flags_at = reader.offset
    flags = reader.take(8)
    reader.take(4 + 1)
    reader.checked.append({'start': shared_start, 'end': reader.offset, 'reader': 'FE4904'})
    basic = _basic(reader, person_index, base_currency_code)
    return {**basic, 'status_code': status, 'status_offset': status_at,
            'expiry_raw': expiry_raw, 'expiry_offset': expiry_at,
            'signed_raw': signed_raw, 'signed_offset': signed_at,
            'dynamic': bool(flags[3] & 8), 'dynamic_flag_offset': flags_at + 3,
            'stored_club_extension_options': options,
            'counts': {'clauses': clause_count, 'rows80': count80, 'rows98': count98,
                       'numeric_rows': numeric_count, 'FE4470_bytes': extra_count}}


def read_primary_contract(data, actual_start, common_start, *, person_index,
                          source_major=3754, minor=9, reference_mode='raw64', base_currency_code=None):
    """Read the first current slot; never search for a contract signature.

    actual_start must be the verified end of a player-specific traversal and
    common_start its independently witnessed exclusive common-body boundary.
    Later auxiliary contracts and CONTRACT_OFFER records are not consumed.
    All actual corpus controls are kind0; null/basic/other-kind tests synthetic.
    """
    try:
        view = memoryview(data)
    except TypeError as error:
        raise ValueError('Primary-contract source must be a byte buffer') from error
    if view.ndim != 1 or view.itemsize != 1:
        view.release()
        raise ValueError('Primary-contract source must be a byte buffer')
    view.release()
    if (type(actual_start) is not int or type(common_start) is not int or
            not 0 <= actual_start < common_start <= len(data) or
            type(person_index) is not int or not 0 <= person_index < 2_000_000):
        raise ValueError('Invalid primary-contract boundary or PERSON index')
    if base_currency_code not in (None, 'GBP'):
        raise ValueError('Unsupported verified base currency code')
    result = {'state': 'unsupported', 'reason': None, 'source_kind': None, 'weekly_wage': None,
              'actual_person_start': actual_start, 'exclusive_common_start': common_start,
              'source_start': None, 'source_end': None, 'contract_dates': None,
              'contract_status': None, 'owner_person_index': None,
              'stored_club_extension_options': [], 'extension_activation_evaluated': False,
              'primary_contract_wire_complete': False, 'complete_actual_person': False,
              'wire_profile': WIRE_PROFILE, 'wire_profile_is_conditional': True,
              'native_loader_acceptance_proved': False, 'checked_ranges': []}
    if (type(source_major) is not int or type(minor) is not int or
            (source_major, minor, reference_mode) != (3754, 9, 'raw64')):
        return {**result, 'reason': 'unsupported_primary_contract_source_profile'}
    reader = _Reader(data, actual_start, common_start)
    try:
        reader.take(25, 'CA7D88_fixed_raw64_prefix')
        names_count = reader.number('B')
        reader.take(names_count * 4, 'ACTUAL_PERSON_native68_u32_vector')
        reader.take(4)  # Stored ACTUAL_PERSON+B0, not a contract or date selector.
        slot_count = reader.number('B')
        if not 1 <= slot_count <= 5:
            raise _Unsupported('primary_slot_not_serialized_or_unsupported_count', reader.offset - 1)
        kind = reader.number('b')
        result.update(source_kind=kind, source_start=reader.offset)
        if kind == -1:
            if slot_count - 1 > common_start - reader.offset:
                raise _Unsupported('truncated_remaining_contract_slot_markers', reader.offset)
            return {**result, 'state': 'no_current_contract',
                    'reason': 'serialized_primary_kind_minus1', 'source_end': reader.offset,
                    'checked_ranges': reader.checked}
        if kind not in (0, 5):
            raise _Unsupported('unsupported_primary_contract_kind', reader.offset)
        fields = (_basic(reader, person_index, base_currency_code) if kind == 5 else
                  _full(reader, person_index, base_currency_code))
        if slot_count - 1 > common_start - reader.offset:
            raise _Unsupported('truncated_remaining_contract_slot_markers', reader.offset)
        result.update(owner_person_index=fields['owner_person_index'], weekly_wage=fields['weekly_wage'],
                      source_end=reader.offset, primary_contract_wire_complete=True)
        if kind == 5:
            return {**result, 'reason': 'basic_contract_date_fields_unavailable',
                    'checked_ranges': reader.checked}
        signed = world.packed_date(fields['signed_raw'])
        expiry = None if fields['dynamic'] else world.packed_date(fields['expiry_raw'])
        code = fields['status_code']
        result.update(state='dynamic_expiry' if fields['dynamic'] else 'available',
                      reason='dynamic_expiry_requires_independent_date_anchor' if fields['dynamic'] else None,
                      source_end=reader.offset, owner_person_index=fields['owner_person_index'],
                      contract_dates={'last_signed': signed, 'expires': expiry,
                                      'state': 'dynamic_unavailable' if fields['dynamic'] else 'fixed_expiry'},
                      contract_status={'native_code': code, 'title': contract_status.LABELS.get(code),
                                       'state': 'decoded' if code in contract_status.LABELS else 'unmapped_native_status'},
                      source_offsets={'last_signed': fields['signed_offset'], 'expires': fields['expiry_offset'],
                                      'dynamic_flag': fields['dynamic_flag_offset'], 'status': fields['status_offset']},
                      stored_expiry_packed_hex=fields['expiry_raw'].hex(),
                      stored_club_extension_options=fields['stored_club_extension_options'],
                      counts=fields['counts'], serialized_slot_count=slot_count,
                      primary_contract_wire_complete=True, checked_ranges=reader.checked)
        return result
    except (_Unsupported, ValueError, struct.error) as error:
        return {**result, 'state': 'unsupported',
                'reason': getattr(error, 'reason', str(error)),
                'stop_offset': getattr(error, 'offset', reader.offset),
                'checked_ranges': reader.checked}
