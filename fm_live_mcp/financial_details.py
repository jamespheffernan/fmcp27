"""Stored financial properties in the pinned FM27 macOS player and club layouts."""
import math
import struct

from . import competition_stages, competitions, database, players, wages, world
from .saved_starting_finances import DEBT_SOURCES, stored_date


def _optional_pointer(read, address):
    pointer = players.u64(read(address, 8))
    if pointer and (pointer < 4096 or pointer % 8):
        raise ValueError('Invalid financial record pointer')
    return pointer


def price(raw):
    if raw == 0x7fffffff:
        return {'amount': None, 'stored_signed32': raw, 'state': 'unclassified_native_limit'}
    return {'amount': raw if raw >= 0 else None, 'stored_signed32': raw,
            'state': 'stored' if raw >= 0 else 'negative_native_code'}


def player_prices(read, base, player, kind, image_stamp):
    from .ffp_projection import cash_properties
    if kind != 'actual':
        return {'state': 'unsupported_player_layout', 'currency': None}
    table = world.pointer(read, player)
    if table != base + players.RVA[0] or world.pointer(read, table+0x98) != base+0xD24728:
        raise ValueError('Player transfer valuation dispatch changed')
    # PbvE and Papr have contextual branches. Their stored inputs are useful
    # independently of a scout's value range or the selling manager's demand.
    valuation, asking = struct.unpack('<ii', read(player+0x22c, 8))
    last_fee, = struct.unpack('<i', read(player+0x23c, 4))
    return {'state': 'decoded', 'currency': wages.base_currency(read, base),
            'last_transfer_fee': price(last_fee), 'stored_transfer_valuation': price(valuation),
            'stored_asking_price_input': price(asking),
            **cash_properties(read.read, base, image_stamp, player, 0xD3E6F0,
                              {'transfer_value_property': 'PbvE', 'asking_price_property': 'Papr'})}


def _loan(read, address, slot):
    raw = read(address, 27)
    debt, monthly, interest, conditional = struct.unpack_from('<4i', raw)
    source, ffp, interest_only = struct.unpack_from('<bBB', raw, 24)
    if ffp > 1 or interest_only > 1:
        raise ValueError('Invalid club loan boolean')
    return {'slot': slot, 'original_debt': debt, 'monthly_repayment': monthly,
            'monthly_interest_repayment': interest, 'conditional_repayment': conditional,
            'start_date': stored_date(raw[20:24]), 'end_date': stored_date(raw[16:20]),
            'source_code': source, 'source_name': DEBT_SOURCES.get(source),
            'included_in_ffp_calculations': bool(ffp), 'interest_only': bool(interest_only)}


def competition_record(read, base, address):
    if not address:
        return None
    index = int.from_bytes(read(address+8, 4), 'little')
    record = competitions.by_index(read, base, index)
    info = database.table(read, base, 'competitions')
    if world.pointer(read, info['start']+8*index) != address:
        raise ValueError('FFP competition membership changed')
    return record


def _ffp_events(read, base, club):
    # 26aeef0 filters the manager vector by club, type, competition and date.
    manager = _optional_pointer(read, base+0x56b5438)
    result = {'state': 'manager_absent', 'records': None}
    if not manager:
        return result
    competition_stages.typed(read, base, manager, (0x55f5bf0, b'27FINANCIAL_FAIR_PLAY_MANAGER'))
    entries, _ = competition_stages.vector(read, manager+0x18, 4096)
    records = []
    for slot, entry in enumerate(entries):
        if not entry or _optional_pointer(read, entry+0x68) != club:
            continue
        competition = _optional_pointer(read, entry+0x30)
        records.append({'slot': slot, 'native_type_code': read(entry+0x24, 1)[0],
                        'competition': competition_record(read, base, competition),
                        'stored_date': stored_date(read(entry+0x70, 4))})
    result.update(state='decoded', records=records)
    return result


def club_details(read, base, club, image_stamp):
    from .ffp_projection import cash_properties
    # Caller has already checked the club and its finance object's concrete RTTI.
    currency = wages.base_currency(read, base)
    ext = _optional_pointer(read, club+0x100)
    loans = {'state': 'no_club_extension', 'native_slot_count': None, 'records': None}
    if ext:
        entries, _ = competition_stages.vector(read, ext+0x50, 1024, entry_alignment=4)
        loans.update(state='decoded', native_slot_count=len(entries),
                     records=[_loan(read, entry, slot) for slot, entry in enumerate(entries) if entry])
    ticket_prices = None
    finance = _optional_pointer(read, club+0x150)
    if finance:
        match, season = struct.unpack('<ff', read(finance+0x10, 8))
        if not all(math.isfinite(value) for value in (match, season)):
            raise ValueError('Invalid stored ticket price')
        ticket_prices = {'average_match_ticket': match if match >= 0 else None,
                         'average_season_ticket': season if season >= 0 else None}
    holders = struct.unpack('<i', read(ext+0xC0, 4))[0] if ext else None
    return {'currency': currency, 'ticket_prices': ticket_prices, 'debt_and_loans': loans,
            'stored_season_ticket_holders': holders if holders and holders > 0 else None,
            **cash_properties(read.read, base, image_stamp, club, 0xE476C4, {'scouting_budget': 'CSbR'}),
            'financial_fair_play': _ffp_events(read, base, club)}
