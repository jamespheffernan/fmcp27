"""Stored weekly wage contributions in the live transfer manager.

The editor's STARTING_WEEKLY_WAGE_CONTRIBUTION table is deliberately unused.
"""
import struct

from . import database, players, staff, transfer_budget, wages, world

ROOT = 0x56A49F8
VECTOR_OFFSET = 0xF0
MAX_RECORDS = 1024
LIMITATIONS = (
    'Stored entries from the live transfer manager weekly wage-contribution list. '
    'Includes both directions and people who now have staff records. This is not a complete '
    'loan-cost, bonus, payroll or future-commitment breakdown. The stored paid-until date does '
    'not establish whether a payment is due today. Amounts use whole GBP per week. '
    'No game function is called, no contribution is recalculated and no payment is made. '
    'All list entries are checked within a 1024-record bound; unsupported person types remain explicit. '
    'Malformed links, exceeded bounds or detected changes reject the query. Reads are non-atomic.'
)


def decode(read, base, selected_club=None):
    manager = world.pointer(read, base + ROOT)
    world.typed(read, base, manager, 'transfer_manager')
    table = world.pointer(read, manager)
    for slot, getter in ((0, 0x2D10D10), (1, 0x2D10D24)):
        if players.u64(read(table + slot*8, 8)) != base + getter:
            raise ValueError('Wage contribution manager changed')
    transfer_budget._service(read, base, transfer_budget.GAME_FINANCE_ROOT,
                             'game_club_finance', {10: 0x1FFE24C})
    if not read(base + 0x56D34E0, 1)[0] & 1:
        raise ValueError('Wage contribution live person-table route is inactive')
    addresses = world.vector(read, manager + VECTOR_OFFSET, MAX_RECORDS)
    wages.base_currency(read, base)
    people = database.table(read, base, 'people')
    clubs = database.table(read, base, 'clubs')
    tables = tuple(base + rva for rva in players.RVA)
    entities = {}

    def club_key(address):
        key = ('club', address)
        if key not in entities:
            record, identity = world.club(read, base, address)
            index = int.from_bytes(read(address + 8, 4), 'little')
            database.club_membership(read, base, clubs, index, address)
            entities[key] = {'record': {**record, 'unique_id': identity[0]},
                             'identity': identity, 'database_index': index}
        return key

    def person_key(index):
        if not 0 <= index < people['count']:
            raise ValueError('Wage contribution person index outside the live table')
        person = world.pointer(read, people['start'] + index*8)
        if int.from_bytes(read(person + 8, 4), 'little') != index:
            raise ValueError('Wage contribution person index changed')
        table = world.pointer(read, person)
        if table in (base + players.RVA[2], base + players.STAFF_RVA[2]):
            address = person - (0x388 if table == base + players.RVA[2] else 0x480)
            key = ('player', address)
            if key not in entities:
                database.player_membership(read, base, people, index, address)
                decoded, identity = players.decode(read, address, tables)
                record = {k: decoded[k] for k in ('name', 'display_name', 'birth_date')}
                record.update(record_kind=decoded.get('record_kind', 'actual_player'), state='decoded')
                entities[key] = {'record': record, 'identity': identity, 'database_index': index}
            return key
        layout = next((fields for fields in staff.LAYOUTS.values() if table == base + fields[1]), None)
        if layout:
            address = person - layout[2]
            key = ('staff', address)
            if key not in entities:
                database.staff_membership(read, base, people, index, address)
                decoded, identity = staff.decode(read, base, address)
                entities[key] = {'record': {**decoded, 'state': 'decoded'},
                                 'identity': identity, 'database_index': index}
            return key
        # Keep the financial record; do not invent a name or silently omit its cost.
        key = ('unsupported_person', person)
        entities[key] = {'record': {'name': None, 'state': 'unsupported_person_type', 'database_index': index}}
        return key

    rows = []
    for address in addresses:
        recipient, payer, index, amount, date = struct.unpack('<QQii4s', read(address, 28))
        if amount < 0:
            raise ValueError('Negative weekly wage contribution')
        recipient_key, payer_key = club_key(recipient), club_key(payer)
        person = person_key(index)
        paid_until = world.packed_date(date)
        if selected_club is not None and selected_club not in (recipient, payer):
            continue
        direction = (None if selected_club is None else 'both' if recipient == payer else
                     'outgoing' if payer == selected_club else 'incoming')
        rows.append({'person_key': person, 'payer_key': payer_key, 'recipient_key': recipient_key,
                     'weekly_amount': amount, 'paid_until': paid_until, 'direction': direction})
    rows.sort(key=lambda row: -row['weekly_amount'])
    return rows, entities, len(addresses)
