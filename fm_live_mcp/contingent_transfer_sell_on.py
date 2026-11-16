"""Retained NEXT_SALE_PERCENTAGE_INFO and its conditional cash allocation.

The calculation starts after native clause selection. It does not establish
that a transfer will occur, select every recipient, or calculate final net cash.
"""
import hashlib
import math
import struct

from . import club_debt_obligations as loans, database, players, retained_transfer_debt, wages, world


TABLE = 0x55C3A90
TYPE_INFO = 0x55C4E40
TYPE_NAME = b'N2db25NEXT_SALE_PERCENTAGE_INFOE'
SOURCE = (
    (0x1804AA4, 8, '94152e462f3e98d8d99662739e87c91ff06eb16d5afefc0047346c214bd99ac8'),
    (0x18043D4, 264, 'c0d5e7bd219879cff2f4093819413d71acd7285e5929c92d9a10aa97f4c865ff'),
    (0x180459C, 600, 'f361cda2fd94133a0d8c40c8e4bae8ab9980ddac18e1acd863bf28bf1b3b4ada'),
    (0x180481C, 408, 'dac004e32d8159a093207f8fb2015673811dc98eb8503ab35f1b4fd771e3ced8'),
    (0x2DBE500, 352, '51cd34b63c2ee4844a8a9f2397e6ac9a02aef9fde47ad175c377c1163b01b1fa'),
    (0x1FAB7EC, 712, '735bb1ec82e6fc9ba862f790f6af41d15db42b1db20206a2065f2c2c75c87465'),
    (0x2DB9CC4, 272, '0cdaba90c5f1b350fb4d689baa5374ee6132e78071f30aabbb2e19713b2fbaff'),
) + retained_transfer_debt.SOURCE
LIMITATIONS = (
    'Selected club owned retained NEXT_SALE_PERCENTAGE_INFO only; incoming records in other '
    'clubs and synthetic country fallback clauses are not scanned. Recorded recipient and '
    'storage fields are decoded, but complete person/contract/transfer admission, native '
    'selection order, recursive cash redistribution and final recipient net cash are not '
    'evaluated. Basis-used is native mutable calculation state, not a paid journal. No due '
    'payment, settlement or future transfer is established. No native calls or game writes.'
)


def _i32(value):
    return (value + 0x80000000) % 0x100000000 - 0x80000000


def _f32(value):
    return struct.unpack('<f', struct.pack('<f', value))[0]


def describe(raw):
    if len(raw) != 37:
        raise ValueError('Invalid next-sale percentage clause width')
    person_id, secondary = struct.unpack_from('<II', raw, 8)
    basis, used, flags, percentage, override, flag = struct.unpack_from('<iiHbbB', raw, 24)
    return {
        'native_person_reference': {'native_id': person_id, 'secondary_id_or_native_id': secondary,
                                    'name': None, 'resolution_state': 'literal_native_reference_only'},
        'native_percentage': percentage, 'native_override_percentage': override,
        'native_basis_amount': {'native_signed32': basis, 'currency': 'GBP'},
        'native_basis_used': {'native_signed32': used, 'currency': 'GBP', 'state': 'mutable_native_allocation_state'},
        'native_flags': flags, 'native_flag_24': flag,
        'amount_due_now': None, 'next_payment_due_date': None, 'payment_state': 'not_established',
    }


def project_native_allocation(raw, cash_argument, category=2):
    """Original scalar branch for an already selected, existing owned record.

    No synthetic country adjustment or optional percentage accumulator. Native
    signed32 wrap and float32 conversion are preserved, including unusual data.
    The returned state is hypothetical; this function never mutates the record.
    """
    fields = describe(raw)
    if type(cash_argument) is not int or not -0x80000000 <= cash_argument <= 0x7FFFFFFF:
        raise ValueError('Cash argument must be native signed32')
    if type(category) is not int or not -0x80000000 <= category <= 0x7FFFFFFF:
        raise ValueError('Category must be native signed32')
    basis = fields['native_basis_amount']['native_signed32']
    used = fields['native_basis_used']['native_signed32']
    result = {'state': 'conditional_existing_record_native_branch', 'cash_argument': cash_argument,
              'native_category': category, 'currency': 'GBP',
              'native_float_context': 'round_to_nearest_ties_to_even', 'native_basis_used_after': used,
              'native_recursive_call_amount': None, 'actual_cash_payment': None,
              'final_recipient_net_cash': None, 'full_native_selection_evaluated': False}
    if cash_argument < 501:
        return {**result, 'branch': 'cash_argument_below_501_skips_allocation'}
    deducted = min(_i32(basis - used), cash_argument)
    taxable = _i32(cash_argument - deducted)
    override = fields['native_override_percentage']
    percentage = override if override > 0 and category == 2 else fields['native_percentage']
    floating = _f32(_f32(percentage / _f32(100.0)) * _f32(taxable))
    converted = min(0x7FFFFFFF, max(-0x80000000, math.trunc(floating)))
    return {**result, 'branch': 'before_recursive_cash_callee', 'native_deducted_basis': deducted,
            'native_taxable_base': taxable, 'native_effective_percentage': percentage,
            'native_basis_used_after': _i32(used + deducted),
            'native_recursive_call_amount': max(0, converted)}


def _verify(read, base):
    for rva, size, digest in SOURCE:
        if hashlib.sha256(read(base + rva, size)).hexdigest() != digest:
            raise ValueError('Native next-sale clause source changed')
    table = base + TABLE
    displacement, info = struct.unpack('<qQ', read(table - 16, 16))
    if displacement or info != base + TYPE_INFO:
        raise ValueError('Native next-sale clause metadata changed')
    name = players.u64(read(info + 8, 8))
    if name < 4096 or read(name, len(TYPE_NAME) + 1) != TYPE_NAME + b'\0':
        raise ValueError('Native next-sale clause RTTI changed')
    for offset, target in ((0x18, 0x18043D4), (0x28, 0x1804AA4), (0x98, 0x180459C), (0xA8, 0x180481C)):
        if players.u64(read(table + offset, 8)) != base + target:
            raise ValueError('Native next-sale clause dispatch changed')


def decode(read, base, club):
    _verify(read, base)
    clubs = database.table(read, base, 'clubs')
    owner = loans._club(read, base, clubs, club)
    result = {'state': 'unavailable', 'selected_club': owner, 'recorded_container_owner': owner,
              'scope': 'selected_club_owned_retained_next_sale_percentage_clauses',
              'as_of_date': world.packed_date(read(base + world.CURRENT_DATE, 4)),
              'currency': None, 'source_slot_count': None, 'null_source_slot_count': None,
              'other_clause_slot_count': None, 'records': None, 'incoming_scanned': False,
              'complete_liability_ledger': False, 'limitations': LIMITATIONS}
    holder = players.u64(read(club + 0xB0, 8))
    if not holder:
        return {**result, 'reason': 'missing_native_club_clause_container'}
    if holder < 4096 or holder % 8:
        raise ValueError('Malformed native club clause container')
    entries = retained_transfer_debt._entries(read, holder)
    records, nulls, other = [], 0, 0
    for slot, address in enumerate(entries):
        if not address:
            nulls += 1
            continue
        if world.pointer(read, address) != base + TABLE:
            other += 1
            continue
        raw = read(address, 37)
        recipient_address = players.u64(raw, 16)
        recipient = loans._club(read, base, clubs, recipient_address) if recipient_address else None
        records.append({'slot': slot, 'native_family': 'db::NEXT_SALE_PERCENTAGE_INFO',
                        'recorded_container_owner': owner, 'recorded_recipient': recipient,
                        'recipient_state': 'canonical_native_club' if recipient else 'native_null_recipient',
                        **describe(raw)})
    return {**result, 'state': 'decoded', 'reason': 'typed_club_owned_retained_clause_container',
            'currency': wages.base_currency(read, base), 'source_slot_count': len(entries),
            'null_source_slot_count': nulls, 'other_clause_slot_count': other, 'records': records}
