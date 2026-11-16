"""Owner-bound retained APPEARANCE_MONEY_INFO transfer clauses.

This is the selected club's own retained clause container. It does not scan
other clubs for incoming clauses or evaluate the full match admission path.
"""
import hashlib
import struct

from . import club_debt_obligations as loans, database, players, retained_transfer_debt, wages, world


TABLE = 0x55C3B50
TYPE_INFO = 0x55C4E58
TYPE_NAME = b'N2db21APPEARANCE_MONEY_INFOE'
SOURCE = (
    (0x1FB3544, 172, '2101f1238ec8035ae8cf812dbb9894fd47c770da6a68b84fb7b4a7fd89a27acc'),
    (0x2E265E8, 404, 'bdd68152ad37f9a59165eac24f8ccf3dc38332703063e86fe0caa16ed4ec9b17'),
    (0x1A836F0, 1256, '40fe0895110dee5a3f241fc39e652b098153e212ad2a1c5e0a1d96f9e3a0c732'),
    (0x1A83F74, 280, '83d5a7c3e50af640d3e316fe31133549ff655fba1870b897b02885c866392ce4'),
    (0x1A84338, 364, '69624033092a150c44520c80912dd09db5f12cb10270b1957828a63051446b4a'),
    (0x2DBE6FC, 360, '589b789ae3812c1585f7d3020d0fb7fd0aee78c26bc3e8a2a7ca691facf276a5'),
    (0x2DF41EC, 128, 'bb61bbdba3102450021802284d003e4904fc190daacf85d6e4deeb3687e9223e'),
    (0x2DF499C, 784, 'c228e5792605b72ca18b5de25d14421b64837470ec605832a35e8ac447572b41'),
    (0x2DF6C84, 200, '737d56a528721934e86f0a33d1880b0a2719617e64543986c83418b3d248d023'),
    (0x2DF6DC4, 152, '5fbabb1ca608cb52d4b43edb2442d3a09103ed655630c90c4315038691a7e9e1'),
    (0x2DF7160, 112, 'e29820852f7067411487125450796ac7e85f6f06212f3a4b090f450ec20ad2c0'),
    (0x2DF7748, 44, '1c3ce30d4ac9bef4e21d543631c6c3d290a70d72094693dce100af73b8ddeb9c'),
    (0x1812D44, 16, 'ab646d55fd5d8262b673de52189f18a5c9194b9a0a44dd2492b7350da93b3bef'),
    (0x1804D50, 596, '432cf1bb6765d6785e686588f0ef123d7230b3f8abb67b3e2fe1cc9952145623'),
    (0x1805118, 556, '04cc1f417476f2793713385616c531156541770e13413222a83cf0f8c058c960'),
    (0x18053A8, 352, 'b184fae9c9fe16cb384acbe4a75e53e74555e8ff61307c248084c088366bd2d9'),
) + retained_transfer_debt.SOURCE
LIMITATIONS = (
    'Selected payer club retained APPEARANCE_MONEY_INFO records only. Other clause families, '
    'other clubs and incoming clauses are not scanned. The source proves recorded payer, '
    'recipient, native call amount, event-kind code and current/target counters. Event-kind '
    'English labels and complete person/contract/match admission are not established. '
    'A counter comparison is distinct from complete trigger eligibility, a due payment or '
    'settlement. Kind2 pays each qualified event; kinds0/1/4 use a threshold; kind3 uses an '
    'event-supplied increment. Actual payments, arrears and a next calendar date remain unknown. '
    'No native function, refresh, UI, game write or saved-file fallback.'
)


def describe(raw):
    """Exact typed fields; unknown English labels never suppress proved numbers."""
    if len(raw) != 33:
        raise ValueError('Invalid appearance-money clause width')
    person_id, person_secondary = struct.unpack_from('<II', raw, 8)
    amount, target, count, kind = struct.unpack_from('<iHHb', raw, 24)
    comparison = 'below' if count < target else 'equal' if count == target else 'above'
    rule = ('native_counter_threshold' if kind in (0, 1, 4) else
            'each_qualified_native_event_until_counter_limit' if kind == 2 else
            'native_event_increment_threshold' if kind == 3 else 'unmapped_native_event_kind')
    return {'native_person_reference': {'native_id': person_id, 'secondary_id_or_native_id': person_secondary,
                                       'name': None, 'resolution_state': 'literal_native_reference_only'},
            'native_call_amount': {'amount': amount if 0 <= amount < 0x7FFFFFFF else None,
                                   'native_signed32': amount, 'currency': 'GBP',
                                   'state': 'native_call_argument' if 0 <= amount < 0x7FFFFFFF else 'unclassified_native_amount'},
            'native_event_kind': {'code': kind, 'name': None, 'name_state': 'unmapped'},
            'native_trigger_progress': {'count': count, 'target': target,
                'remaining_to_target': target - count if count <= target else None,
                'comparison': comparison, 'cash_rule': rule,
                'native_report_count_amount_predicate': count < target and amount > 0,
                'full_trigger_eligibility': 'not_evaluated'},
            'amount_due_now': None, 'next_payment_due_date': None, 'payment_state': 'not_established'}


def _verify(read, base):
    for rva, size, digest in SOURCE:
        if hashlib.sha256(read(base + rva, size)).hexdigest() != digest:
            raise ValueError('Native retained appearance-clause source changed')
    table = base + TABLE
    displacement, info = struct.unpack('<qQ', read(table - 16, 16))
    if displacement != 0 or info != base + TYPE_INFO:
        raise ValueError('Native appearance-clause type metadata changed')
    name = players.u64(read(info + 8, 8))
    if name < 4096 or read(name, len(TYPE_NAME) + 1) != TYPE_NAME + b'\0':
        raise ValueError('Native appearance-clause RTTI changed')
    for offset, expected in ((0x28, 0x1812D44), (0xB0, 0x1812D4C), (0x98, 0x1805118), (0xA8, 0x18053A8)):
        if players.u64(read(table + offset, 8)) != base + expected:
            raise ValueError('Native appearance-clause dispatch changed')


def decode(read, base, club):
    """Decode one canonical payer's source without claiming complete liabilities."""
    _verify(read, base)
    clubs = database.table(read, base, 'clubs')
    owner = loans._club(read, base, clubs, club)
    report = {'state': 'unavailable', 'selected_club': owner, 'recorded_payer': owner,
              'scope': 'selected_payer_owned_retained_appearance_money_clauses',
              'as_of_date': world.packed_date(read(base + world.CURRENT_DATE, 4)),
              'currency': None, 'source_slot_count': None, 'null_source_slot_count': None,
              'other_clause_slot_count': None, 'records': None, 'incoming_scanned': False,
              'complete_liability_ledger': False, 'limitations': LIMITATIONS}
    holder = players.u64(read(club + 0xB0, 8))
    if not holder:
        report['reason'] = 'missing_native_club_clause_container'
        return report
    if holder < 4096 or holder % 8:
        raise ValueError('Malformed native club clause container')
    entries = retained_transfer_debt._entries(read, holder)
    records, nulls, other = [], 0, 0
    for slot, address in enumerate(entries):
        if not address:
            nulls += 1
            continue
        table = world.pointer(read, address)
        if table != base + TABLE:
            other += 1
            continue
        raw = read(address, 33)
        recipient_address = players.u64(raw, 16)
        recipient = loans._club(read, base, clubs, recipient_address) if recipient_address else None
        records.append({'slot': slot, 'native_family': 'db::APPEARANCE_MONEY_INFO',
                        'recorded_payer': owner, 'recorded_recipient': recipient,
                        'recipient_state': 'canonical_native_club' if recipient else 'native_null_recipient',
                        'direction': 'self' if recipient_address == club else 'outgoing', **describe(raw)})
    report.update(state='decoded', reason='typed_payer_owned_retained_clause_container',
                  currency=wages.base_currency(read, base), source_slot_count=len(entries),
                  null_source_slot_count=nulls, other_clause_slot_count=other, records=records)
    return report
