"""Bounded research inputs for one incoming retained-transfer cash call.

This module collects source context; it does not execute the cash service or
publish a net-cash projection. Unknown native branches remain explicit inputs
for the next offline source proof.
"""
import hashlib
import struct

from . import competition_stages, contingent_transfer_sell_on as clauses, database, finance_person_reference as people
from . import players, retained_transfer_debt as retained, transfer_payment_timing as timing, world


# Additional original callees reached by the controlled complete-service proof.
CASH_SOURCE = ((40560536, 184, '69da1ea8c125e50d4536973311cbe6bcb3893c94410819777258b7a19b4c5169'),
 (13257296, 8, 'd3c844a0173107453aa9896cdb7276470625501e7ff067cd764c7a160ece5ca3'),
 (13317924, 24, 'fe47a1190093b8b56ecf05ed26903bb1621e5bc979ff3fce60ff77b0404010f4'),
 (19506360, 8, '23ba31bca6e99eeaeca35232f284c89f546e52d3ab4cc441902fc17db7fc1dc1'),
 (33208300, 712, '735bb1ec82e6fc9ba862f790f6af41d15db42b1db20206a2065f2c2c75c87465'),
 (14009872, 20, '2d883d700de5b56d2a890e12a2ab812b060f3c7c4a9766e4249a57cc90313472'),
 (21985440, 384, 'bfd6a1aac092e9e33f470e9b3c19313fcbe316e295269f29bef8b2ac0d134623'),
 (15343372, 112, '1e37cc68fd059d15fd3ef72366fe59105d8d39f6de2701b9b2cf619d8531ce45'),
 (15327776, 88, '0c3a880c8d75e9390826549fd207afbfc3309366a3302ffe0fa950130d2a7a49'),
 (17394640, 448, 'ab0463b2159a3c7cb38826193520d947bc27d08997fafc82e775842dc4d89cdb'),
 (13473112, 20, '0b31d8d7ae5de0f1149b6f4aacf257ac81692f75b132727d6b937b4c35d47458'),
 (13351416, 1536, 'd8af35f1b0d5eaccba58e4f498c9fe2bbabbf5dab52e1818a294929f9e2bc803'),
 (25184932, 8, '94152e462f3e98d8d99662739e87c91ff06eb16d5afefc0047346c214bd99ac8'),
 (13642664, 8, '552dde2909931c89f0b0010f88689b68ca46efff233eafb800f88fea882dfa24'),
 (21655056, 856, 'e4de83e51f053f57199dfac39918369e0e7e542df65e7c4d0105ac67757e80dc'))
SOURCE = timing.SOURCE + clauses.SOURCE + people.SOURCE + CASH_SOURCE


def _optional(read, at):
    value = players.u64(read(at, 8))
    if value and (value < 4096 or value % 8):
        raise ValueError('Malformed cash-context pointer')
    return value


def _span(read, at, stride, limit):
    start, end = struct.unpack('<QQ', read(at, 16))
    if start == end == 0:
        return start, 0
    if start < 4096 or start % stride or end % stride or not start <= end <= start + limit * stride:
        raise ValueError('Cash-context vector outside its native bound')
    return start, (end - start) // stride


def schedule_person(read, base, raw, info):
    """Literal2E1B294 lookup: resident vector first, canonical-header fallback."""
    index = struct.unpack_from('<i', raw, 28)[0]
    if not 0 <= index <= info['count']:
        return {'state': 'native_prior_index_removal', 'index': index, 'address': None}
    if not read(base + 0x56D34E0, 1)[0] & 1:
        start, count = _span(read, info['root'] + 0x68, 8, 2000000)
        if index < count:
            return {'state': 'native_resident_index_lookup', 'index': index,
                    'address': _optional(read, start + index * 8)}
    address = _optional(read, info['start'] + index * 8) if index < info['count'] else 0
    return {'state': 'native_header_index_lookup' if address else 'native_null_lookup',
            'index': index, 'address': address}


def _type_prefix(read, base, address, slot):
    table = world.pointer(read, address)
    if not base + 0x54A0000 <= table < base + 0x56F0000:
        raise ValueError('Cash-context native vtable outside pinned image')
    displacement, info = struct.unpack('<qQ', read(table - 16, 16))
    if not base + 0x54A0000 <= info < base + 0x56F0000:
        raise ValueError('Cash-context typeinfo outside pinned image')
    name = players.u64(read(info + 8, 8))
    if not base + 0x5300000 <= name < base + 0x54E0000:
        raise ValueError('Cash-context RTTI name outside pinned image')
    raw = read(name, 128)
    if b'\0' not in raw:
        raise ValueError('Cash-context RTTI name exceeds bound')
    text = raw.split(b'\0', 1)[0].decode('ascii', errors='strict')
    callee = players.u64(read(table + slot, 8))
    if callee % 4 or not base <= callee < base + 0x4AEF800:
        raise ValueError('Cash-context native callee outside original text')
    code = read(callee, 8)
    return {'table_rva': hex(table - base), 'typeinfo_rva': hex(info - base),
            'displacement': displacement, 'native_rtti': text, 'dispatch_slot': hex(slot),
            'callee_rva': hex(callee - base), 'captured_prefix_hex': code.hex()}


def _contract(read, base, address, person, *, main):
    if not address:
        return {'state': 'native_null_contract', 'address': None}
    table = world.pointer(read, address)
    kind = next((k for k in ('full_contract', 'basic_contract', 'loan_contract')
                 if table == base + world.TYPES[k][0]), None)
    if kind is None:
        return {'state': 'unsupported_native_contract_type', 'address': hex(address),
                'native_type': _type_prefix(read, base, address, 0x70)}
    world.typed(read, base, address, kind)
    if main and world.pointer(read, address + 8) != person:
        raise ValueError('Cash-context main contract PERSON owner changed')
    result = {'state': 'typed_native_contract', 'kind': kind, 'address': hex(address),
              'native_byte_26': read(address + 0x26, 1)[0],
              'native_byte_3a': read(address + 0x3A, 1)[0],
              'native_dispatch_70': _type_prefix(read, base, address, 0x70)}
    if kind == 'full_contract':
        result['native_byte_c2'] = read(address + 0xC2, 1)[0]
    return result


def _offer_references(read, base, header):
    if not header:
        return {'state': 'native_null_offer_reference_container', 'count': None}
    start, count = _span(read, header, 4, 4096)
    indices = [v for (v,) in struct.iter_unpack('<i', read(start, count * 4) if count else b'')]
    result = {'state': 'captured_native_offer_reference_indices', 'count': count,
              'native_signed_indices': indices, 'offer_objects_or_predicate_not_evaluated': True,
              'indexed_entries': []}
    if not count:
        return result
    manager = world.pointer(read, base + 0x56A67F0)
    entries, entry_count = _span(read, manager + 8, 8, 2000000)
    result.update(manager_address=hex(manager), manager_entry_count=entry_count)
    for slot, index in enumerate(indices):
        if not 0 <= index < entry_count:
            result['indexed_entries'].append({'slot': slot, 'native_index': index,
                                              'state': 'native_index_filtered'})
            continue
        entry = _optional(read, entries + index * 8)
        if not entry:
            result['indexed_entries'].append({'slot': slot, 'native_index': index,
                                              'state': 'native_null_entry'})
            continue
        kind = read(entry + 0x8D, 1)[0]
        record = {'slot': slot, 'native_index': index, 'address': hex(entry),
                  'native_reference_count': int.from_bytes(read(entry + 8, 4), 'little'),
                  'native_kind_byte_8d': kind, 'state': 'native_kind_filtered' if kind != 0x13 else 'native_kind_19_candidate'}
        if kind == 0x13:
            record['dispatch_78'] = _type_prefix(read, base, entry, 0x78)
        result['indexed_entries'].append(record)
    return result


def _person(read, base, lookup):
    person = lookup['address']
    if not person:
        return {'state': 'native_null_person', 'lookup': lookup}
    raw = read(person, 20)
    table, index, native_id, secondary = struct.unpack('<QIII', raw)
    context = people.context(read, base)
    binding = people.playing_identity(read, base, context,
        {'state': 'matched_native_reference', 'person_address': person, 'database_index': index,
         'native_id': native_id, 'secondary_id': secondary, 'binary_search_probes': 0,
         'index_source': lookup['state']})
    result = {'state': 'captured_person_context', 'lookup': lookup, 'identity': binding,
              'address': hex(person), 'native_reference': [native_id, secondary or native_id]}
    if table != base + players.RVA[2]:
        return {**result, 'state': 'regular_person_cash_branch_not_bound'}
    primary = person - 0x388
    for slot, target in ((0x3C8, 0xCB3724), (0x530, 0xCD9558), (0x6D0, 0xCA4A50), (0x6E0, 0xD5C610)):
        if players.u64(read(table + slot, 8)) != base + target:
            raise ValueError('Cash-context regular PERSON dispatch changed')
    main = _optional(read, person - 0x98)
    auxiliary = _optional(read, primary + 0xE0)
    result['main_contract'] = _contract(read, base, main, person, main=True)
    result['primary_auxiliary_contract'] = _contract(read, base, auxiliary, person, main=False)
    result['offer_references'] = _offer_references(read, base, _optional(read, person - 0xA8))
    return result


def _club(read, base, address, clubs):
    identity = retained.loans._club(read, base, clubs, address)
    result = {'club': identity, 'address': hex(address), 'native_byte_163': read(address + 0x163, 1)[0],
              'nation_pointer': hex(_optional(read, address + 0xD8))}
    finance = _optional(read, address + 0x150)
    if finance:
        table = world.pointer(read, finance)
        kind = next((k for k in ('club_finance', 'club_finance_base') if table == base + world.TYPES[k][0]), None)
        if kind:
            world.typed(read, base, finance, kind)
            offsets = ((0xC, 0x278, 0x29C, 0x318, 0x32C, 0x358, 0x4A8, 0x4CC, 0x548, 0x55C, 0x588)
                       if kind == 'club_finance' else (0xC,))
            result['finance'] = {'state': 'typed_full_finance_record' if kind == 'club_finance' else 'typed_base_finance_balance_only',
                'address': hex(finance), 'native_signed32_fields': {
                    hex(o): struct.unpack('<i', read(finance + o, 4))[0] for o in offsets}}
            result['finance']['dispatches'] = {hex(slot): _type_prefix(read, base, finance, slot)
                for slot in (0x1F8, 0x200, 0x288, 0x290, 0x298, 0x2A8)}
        else:
            result['finance'] = {'state': 'unsupported_native_finance_type', 'address': hex(finance),
                                 'native_type': _type_prefix(read, base, finance, 0)}
    else:
        result['finance'] = {'state': 'native_null_finance', 'address': None}
    start, count = _span(read, address + 0x18, 8, 64)
    result['team_count'] = count
    first = _optional(read, start) if count else 0
    if not first:
        return {**result, 'rule_context': {'state': 'native_no_first_team'}}
    world.typed(read, base, first, 'team')
    if world.pointer(read, first + 0x30) != address:
        raise ValueError('Cash-context first TEAM club binding changed')
    competition = _optional(read, first + 0x50)
    result['first_team_address'] = hex(first)
    if not competition:
        return {**result, 'rule_context': {'state': 'native_null_first_team_competition'}}
    world.typed(read, base, competition, 'competition')
    index = int.from_bytes(read(competition + 8, 4), 'little')
    competitions = database.table(read, base, 'competitions')
    if not index < competitions['count'] or world.pointer(read, competitions['start'] + index * 8) != competition:
        raise ValueError('Cash-context competition membership changed')
    extension = _optional(read, competition + 0xB0)
    context = {'competition_address': hex(competition), 'competition_index': index,
               'native_id': int.from_bytes(read(competition + 12, 4), 'little')}
    if not extension:
        return {**result, 'rule_context': {**context, 'state': 'native_null_competition_extension'}}
    start, count = _span(read, extension + 0x370, 8, 128)
    context.update(state='captured_native_ffp_rule_dispatches', extension_address=hex(extension),
                   rule_count=count, rules=[])
    for slot in range(count):
        rule = world.pointer(read, start + slot * 8)
        context['rules'].append({'slot': slot, 'address': hex(rule),
                                 'dispatch': _type_prefix(read, base, rule, 0x18)})
    result['rule_context'] = context
    return result


def _services(read, base):
    club_service = world.pointer(read, base + 0x56D2CE8)
    world.typed(read, base, club_service, 'game_club')
    if players.u64(read(base + world.TYPES['game_club'][0] + 0x120, 8)) != base + 0x1FAB7EC:
        raise ValueError('Cash-context native clause-selector dispatch changed')
    ffp = _optional(read, base + 0x56B5438)
    if ffp:
        competition_stages.typed(read, base, ffp, (0x55F5BF0, b'27FINANCIAL_FAIR_PLAY_MANAGER'))
    return {'game_club_address': hex(club_service), 'ffp_manager_address': hex(ffp),
            'ffp_manager_state': 'typed_manager_inputs_not_fully_bound' if ffp else 'native_null_manager'}


def decode(read, base, club):
    for at, n, digest in CASH_SOURCE:
        if hashlib.sha256(read(base + at, n)).hexdigest() != digest:
            raise ValueError('Cash-context original callee source changed')
    schedule = timing.decode(read, base, club)
    result = {'state': 'unavailable', 'scope': 'one_incoming_retained_transfer_cash_context_research',
              'selected_club': schedule['selected_club'], 'schedule': schedule,
              'actual_payment_or_final_net_established': False, 'full_cash_replay_performed': False}
    candidates = [row for row in schedule['records'] or [] if row['direction'] == 'incoming'
                  and row['native_cash_timing']['state'] == 'projected_native_cash_branch'
                  and row['native_cash_timing']['next_native_cash_branch']['call_argument_amount'] is not None]
    if not candidates:
        return {**result, 'reason': 'no_supported_incoming_native_cash_branch_in_observed_prefix'}
    row = min(candidates, key=lambda r: (r['native_cash_timing']['next_native_cash_branch']['date'], r['slot']))
    manager = world.pointer(read, base + retained.ROOT)
    address = retained._entries(read, manager + 0xD8)[row['slot']]
    raw = read(address, 34)
    payer, recipient = struct.unpack_from('<QQ', raw)
    info = database.table(read, base, 'people')
    person = _person(read, base, schedule_person(read, base, raw, info))
    clubs = database.table(read, base, 'clubs')
    owned = clauses.decode(read, base, recipient)
    holder = _optional(read, recipient + 0xB0)
    types = []
    if holder:
        cache = {}
        for slot, value in enumerate(retained._entries(read, holder)):
            if not value:
                types.append({'slot': slot, 'state': 'native_null_clause'})
                continue
            table = world.pointer(read, value)
            if table not in cache:
                cache[table] = _type_prefix(read, base, value, 0x28)
            types.append({'slot': slot, 'address': hex(value), 'native_type': cache[table]})
    return {**result, 'state': 'captured_bounded_research_context', 'reason': 'one_fresh_incoming_native_schedule',
            'selected_schedule_slot': row['slot'], 'selected_schedule_raw_hex': raw.hex(),
            'entry_context': {'category': 2, 'offer': None, 'forecast': row['native_cash_timing']},
            'person': person, 'payer': _club(read, base, payer, clubs),
            'recipient': _club(read, base, recipient, clubs),
            'recipient_retained_sell_on_clauses': owned, 'recipient_clause_types': types,
            'services': _services(read, base),
            'native_mode_bytes': {'951': read(base + 0x56D4951, 1)[0], '953': read(base + 0x56D4953, 1)[0]},
            'remaining_work': 'Original full cash replay requires all reached rule/offer/recipient branches; no paid-state inference.'}
