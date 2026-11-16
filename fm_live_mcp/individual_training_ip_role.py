"""Pure original1579B00 IP-role selector over already bound stored occurrences.

The caller owns ordinary PLAYER/PERSON identity, selected HUMAN/TEAM roster,
the PLAYER+1A0 child and its bounded24-byte vector, source/build checks and all
final physical fences. This module neither discovers people nor reads a game.
Native zero does not establish that planned/applied/effective training is absent.
"""
import hashlib
import struct

OCCURRENCE_BYTES = 24
OCCURRENCE_LIMIT = 256
NATIVE_GUARDS = (
    (0x1579B00, 544, '6b7b41f947b6abd0c2e74ad2c60afef3b2d41c01fd1d3ae51ca8b32547cf5094'),
    (0x539DA5C, 20, '2d13f8f0e89e6e3e9928bca51ca38fe9f130302cbe2d3093ae444adfc311fb79'),
    (0x539DA70, 31, '07331749fdbc3d771fd5c14a087918582fe689455b9363e46c044ef4df5e38b1'),
)
# Exact original data-table destinations. Legacy family-19 loops to the next
# stored occurrence. Family-31 shares RET after the original's initial W0=1.
FAMILY_BITS = {
    -31: 0, -30: 1, -29: 2, -28: 3, -27: 4, -26: 5, -25: 6, -24: 7,
    -23: 9, -22: 10, -21: 11, -20: 12, -18: 14, -17: 15, -16: 16,
    -15: 17, -14: 18, -13: 19, -12: 20, -11: 24, -10: 27, -9: 28,
    -8: 29, -7: 30, -6: 31, -5: 32, -4: 33, -3: 35, -2: 36, -1: 37,
    0: 38, 1: 39, 2: 40, 3: 41, 4: 42, 5: 43, 6: 44, 7: 45,
    8: 46, 9: 47, 10: 49, 11: 48, 12: 50, 13: 51, 14: 52, 15: 53,
    16: 54, 17: 55, 18: 56, 19: 57,
}
SCOPE = ('Native first eligible stored IP-role occurrence only. No current UI '
         'population, planned/applied/effective training, medical clearance, '
         'attendance, workload, recommendation or development outcome.')


def verify_native(read, base):
    if type(base) is not int or base < 4096 or base % 4096:
        raise ValueError('Invalid individual-training native image base')
    for rva,size,digest in NATIVE_GUARDS:
        value = read(base+rva,size)
        if type(value) is not bytes or len(value) != size or hashlib.sha256(value).hexdigest() != digest:
            raise ValueError('Individual-training IP-role native source changed or incomplete')


def decode(entries):
    """Preserve native occurrence order, early return, zero and unknown inputs.

    An empty tuple is an explicitly captured empty vector. A missing child or
    failed read must be represented by the caller before this function is used.
    """
    if type(entries) is not tuple or len(entries) > OCCURRENCE_LIMIT:
        raise ValueError('Invalid individual-training stored occurrence population')
    if any(type(entry) is not bytes or len(entry) != OCCURRENCE_BYTES for entry in entries):
        raise ValueError('Incomplete individual-training stored occurrence')
    rows,selected,mask = [],None,0
    for index,entry in enumerate(entries):
        row = dict(stored_slot=index, raw_hex=entry.hex(), state='not_reached_after_native_return')
        rows.append(row)
        if selected is not None:
            continue
        packed,level = struct.unpack_from('<Hh',entry,8)
        position,family = packed & 63,(packed >> 6) & 127
        position = position-64 if position >= 32 else position
        family = family-128 if family >= 64 else family
        row.update(native_packed_word=packed, native_signed_position_code=position,
                   native_signed_role_family=family, native_signed_level_operand=level,
                   native_flag_byte=entry[23])
        if entry[23]:
            row['state'] = 'native_flag_skipped'
        elif level < 1:
            row['state'] = 'native_nonpositive_level_skipped'
        elif family not in FAMILY_BITS:
            row['state'] = 'native_unsupported_role_family_skipped'
        else:
            mask,selected = 1 << FAMILY_BITS[family],index
            row['state'] = 'native_first_match'
    return dict(state='checked_native_nonzero' if mask else 'checked_native_zero',
                source_state='stored_occurrences' if entries else 'checked_empty_vector',
                native_ip_role_mask=f'0x{mask:016x}', selected_stored_slot=selected,
                stored_occurrence_count=len(entries), occurrences=rows,
                native_operator='0x1579B00', native_ip_position_mask=None,
                planned_training_evaluated=False, applied_training_evaluated=False,
                effective_training_evaluated=False, scope=SCOPE)
