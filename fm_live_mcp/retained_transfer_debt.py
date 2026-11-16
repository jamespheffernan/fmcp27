"""Native TransferDebt over retained TRANSFER_MANAGER schedule records.

This source is independent of proposed offers. The native net value preserves
source order, duplicates and its first-null early return. No game calls.
"""
import hashlib
import struct

from . import club_debt_obligations as loans
from . import database, players, wages, world
from .saved_starting_finances import stored_date


ROOT, FULL_ROOT, FULL_TABLE = 0x56A49F8, 0x56D2C68, 0x55DFCF8
MAX_SLOTS = 16384
SOURCE = (
    (0x1FD5728, 112, '7858353f9c55afa6bf9ff6378bf425f57e8f79f17c8630772bec1d1947a3d608'),
    (0x1A3B30C, 112, 'bc7075052eaf5d936cbacc275299903b2d2eae0ffe031db5a9105cb80fada7b3'),
    (0x1A3B7C0, 32, 'c2f27e8e9fb68aead3b6d61e5f02387ad41cf490556f909c8ae70cab9830a696'),
    (0x2E48D70, 568, 'd61462e429223cd5405575acc35782388ca2cbd5855452156c2d28b2e40ea87b'),
    (0x2E1B174, 932, '7c06ce5db3a72a2d2ba98c55646a263c613305719e580ea6f8696bab1497ba0b'),
    (0x2D11FA8, 428, 'ea9eb188a9859daddb444f7f8ead99dbc668b3bb4fc17b0d70872b2a7cedc007'),
    (0x2DB9288, 4800, '014efdc18d4736166ecaf7a822fbb44628900db4ec28b9d184481fec85568aa9'),
    (0xEA8CFC, 180, '2dc9a6b45f407ae09789ad24a6868b0479382b8d96cda541d212aa281de5e9ed'),
    (0xEA82CC, 44, '0fc743e6a283c23a87c47e714c6405ee09cd4d8200515f5a61e8505c5431b6e9'),
    (0x1FFCFF0, 116, '2e7c283c243afb798ee91cf2538d240750a7d25c2037d42491c6b45ab8e0b665'),
)
LIMITATIONS = (
    'Native TransferDebt is a signed net of the retained transfer-manager schedule source: '
    'recorded payer adds and recorded recipient subtracts. It is separate from proposed offers '
    'and club bank loans. Stored unit amount times the signed remaining schedule count is '
    'native arithmetic, not a complete payment transaction ledger. Stored dates and interval '
    'codes are preserved without inventing a next due date. Null slots terminate the native '
    'sum; later slots are outside that native prefix. Repeated entries remain repeated. '
    'A native zero does not establish no gross payables or settlement. Complete club liabilities, '
    'contingent triggers, all instalments and actual cash paid are not established.'
)


def native_sum(rows, club):
    """Exact signed32 1FD5728; None represents a native null source slot."""
    total, wrapped = 0, False
    for raw in rows:
        if raw is None:
            break
        if len(raw) < 34:
            raise ValueError('Native transfer-debt row is truncated')
        first, second = struct.unpack_from('<QQ', raw)
        if first != club and second != club:
            continue
        amount = struct.unpack_from('<i', raw, 24)[0]
        count = struct.unpack_from('<b', raw, 33)[0]
        full = total + amount * count if first == club else total - amount * count
        value = loans._signed32(full)
        wrapped |= full != value
        total = value
    return {'native_signed32': total, 'signed32_wrap': wrapped}


def _verify(read, base):
    for rva, size, digest in SOURCE:
        if hashlib.sha256(read(base + rva, size)).hexdigest() != digest:
            raise ValueError('Native retained transfer-debt source changed')
    service = world.pointer(read, base + FULL_ROOT)
    if world.pointer(read, service) != base + FULL_TABLE:
        raise ValueError('Native full transfer-debt service type changed')
    displacement, info = struct.unpack('<qQ', read(base + FULL_TABLE - 16, 16))
    if displacement != 0 or info != base + 0x55DFF18:
        raise ValueError('Native full transfer-debt service metadata changed')
    name = players.u64(read(info + 8, 8))
    if name < 4096 or read(name, 20) != b'17GAME_CLUB_FINANCE\0':
        raise ValueError('Native full transfer-debt service RTTI changed')
    slots = ((FULL_TABLE, 0x50, 0x1FD5728), (FULL_TABLE, 0x168, 0x1FFCFF0),
             (world.TYPES['club_finance'][0], 0x1F8, 0xEA8CFC),
             (world.TYPES['club_finance'][0], 0x290, 0xEA82CC))
    for table, slot, expected in slots:
        if players.u64(read(base + table + slot, 8)) != base + expected:
            raise ValueError('Native transfer-debt monetary dispatch changed')


def _entries(read, address):
    start, end, capacity = struct.unpack('<QQQ', read(address, 24))
    if (start, end, capacity) == (0, 0, 0):
        return ()
    if (start < 4096 or any(p % 8 for p in (start, end, capacity))
            or not start <= end <= capacity or capacity - start > MAX_SLOTS * 8):
        raise ValueError('Invalid retained transfer schedule vector bound')
    raw = b''.join(read(at, min(8192, end-at)) for at in range(start, end, 8192))
    entries = tuple(value for (value,) in struct.iter_unpack('<Q', raw))
    if any(value and (value < 4096 or value % 4) for value in entries):
        raise ValueError('Invalid retained transfer schedule row pointer')
    return entries


def decode(read, base, club):
    """Return one effective owner's native prefix and checked counterparties.

    Call only inside a save-bound ReadSet and physically recheck all consumed
    bytes after final process, build, context and presentation callbacks.
    """
    _verify(read, base)
    clubs = database.table(read, base, 'clubs')
    selected = loans._club(read, base, clubs, club)
    owner, relation = loans._owner(read, club)
    owner_info = selected if owner == club else loans._club(read, base, clubs, owner)
    out = {'state': 'unavailable', 'selected_club': selected, 'financial_owner': owner_info,
           'owner_relationship': relation, 'as_of_date': world.packed_date(read(base + world.CURRENT_DATE, 4)),
           'currency': None, 'source_slot_count': None, 'native_prefix_slot_count': None,
           'first_null_slot': None, 'outside_native_prefix_slot_count': None,
           'native_transfer_debt': None, 'records': None, 'complete_liability_ledger': False,
           'evidence': 'native_TransferDebt_retained_transfer_manager_schedule', 'limitations': LIMITATIONS}
    if not loans._full_finance(read, base, club) or not loans._full_finance(read, base, owner):
        out['reason'] = 'native_report_requires_full_selected_and_owner_finance'
        return out
    manager = players.u64(read(base + ROOT, 8))
    if not manager:
        out['reason'] = 'missing_retained_transfer_manager'
        return out
    world.typed(read, base, manager, 'transfer_manager')
    table = world.pointer(read, manager)
    for slot, expected in ((0, 0x2D10D10), (8, 0x2D10D24)):
        if players.u64(read(table + slot, 8)) != base + expected:
            raise ValueError('Retained transfer-manager dispatch changed')
    entries = _entries(read, manager + 0xD8)
    first_null = next((i for i, value in enumerate(entries) if not value), None)
    prefix = entries if first_null is None else entries[:first_null]
    source_rows, records, valid = [], [], True
    for slot, address in enumerate(prefix):
        # Native comparisons consume the two CLUB links before monetary fields.
        first, second = struct.unpack('<QQ', read(address, 16))
        if owner not in (first, second):
            continue
        raw = read(address, 34)
        source_rows.append(raw)
        amount = struct.unpack_from('<i', raw, 24)[0]
        count = struct.unpack_from('<b', raw, 33)[0]
        product = amount * count
        amount_valid = amount >= 0 and amount != 0x7FFFFFFF and count > 0 and loans._signed32(product) == product
        valid &= amount_valid
        payer = loans._club(read, base, clubs, first) if first else None
        recipient = loans._club(read, base, clubs, second) if second else None
        records.append({'slot': slot, 'recorded_payer': payer, 'recorded_recipient': recipient,
                        'direction': 'self' if first == second else 'outgoing' if first == owner else 'incoming',
                        'stored_unit_amount': amount, 'remaining_native_count': count,
                        'native_remaining_amount': {'amount': product if amount_valid else None,
                                                    'native_signed32': loans._signed32(product),
                                                    'state': 'native_schedule_product' if amount_valid else 'unclassified_native_terms'},
                        'native_date_10': stored_date(raw[16:20]),
                        'native_date_gate_14': stored_date(raw[20:24]), 'payment_interval_code': raw[32],
                        'date_field_names_state': 'native_storage_roles_only',
                        'next_payment_due_date': None, 'payment_state': 'not_established'})
    total = native_sum(source_rows, owner)
    out.update(state='decoded', reason='native_retained_transfer_schedule_prefix', currency=wages.base_currency(read, base),
               source_slot_count=len(entries), native_prefix_slot_count=len(prefix), first_null_slot=first_null,
               outside_native_prefix_slot_count=0 if first_null is None else len(entries) - first_null - 1,
               records=records, native_transfer_debt={**total,
                   'amount': total['native_signed32'] if valid and not total['signed32_wrap'] else None,
                   'state': 'native_schedule_net' if valid and not total['signed32_wrap'] else 'unclassified_native_terms'})
    return out
