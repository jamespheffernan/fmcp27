"""Owner-bound native DebtsAndLoansData/RemainingDebt, without game calls.

RemainingDebt is the game's schedule calculation. It is not a transaction
ledger, evidence of a payment, or a complete account of a club's liabilities.
"""
from datetime import date
import hashlib
import struct

from . import competition_stages, database, players, wages, world
from .saved_starting_finances import DEBT_SOURCES, stored_date


SOURCE = (
    (0x13714F8, 648, '0a216442f2b373452d58d9e31d2af98db44cce32a1c6fbea10fd36916f2bf4b6'),
    (0x5387C10, 16, 'e0e4641f65e18a76108a16dd68edd04088dbf8fc022b8662554490beb2a89257'),
    (0x53876F8, 8, '245bbd9d484dcf27c714e2690cd6544973de5d54aa9cd82eab23d6046a65faa8'),
    (0x53002F0, 16, 'baed642339816affb3fe8719792d0e4ce82f12db72b7373d244eaa65445800fe'),
    (0x1A3B30C, 112, 'bc7075052eaf5d936cbacc275299903b2d2eae0ffe031db5a9105cb80fada7b3'),
    (0x1A3C708, 100, '89e38a6acc1a69071e5ff3159f4bdaa782207345a12c9f8c2216807faef27a60'),
    (0xAAF14, 48, 'aae20bcf2cf29466d707adce304b518cd5525a61f8a123aad8386e5190ba3598'),
    (0xAB570, 124, 'f4bea046126e54e70fda044d2501880a592cd8ca39f900cb983cd8aac33116c6'),
    (0xE4C6E4, 124, '1ec3988ea1f47e1d83e78bf98244077d79a28053c9d1ae0416f23e5bfb57580a'),
)
REPORT_LIMIT = 10
LIMITATIONS = (
    'RemainingDebt reproduces the native calendar-based schedule calculation in whole GBP. '
    'It does not establish actual payments, arrears, a payoff quote, the exact lender, '
    'or the next payment due date. The named native report contains at most the first '
    'ten physical loan slots; other slots and transfer instalments remain outside this '
    'report. Conditional and interest-only source branches can retain the original '
    'amount after the stored end date. Zero is a native result, not proof of settlement. '
    'Reads require request-scoped source and save-context rechecks by the caller.'
)


def _signed32(value):
    return (value + (1 << 31)) % (1 << 32) - (1 << 31)


def native_remaining_debt(raw, current_raw):
    """Port original 13714F8(mode=1), on supported Gregorian packed dates.

    Keep every signed32 operation, including wrap, rather than silently turning
    a negative or overflowed native result into a plausible monetary amount.
    """
    if len(raw) != 27 or len(current_raw) != 4:
        raise ValueError('Invalid native loan/date width')
    end = date.fromisoformat(world.packed_date(raw[16:20]))
    current = date.fromisoformat(world.packed_date(current_raw))
    days = (end - current).days
    months = max(1, days // 30) if days > 0 else 0
    debt, monthly, interest, _ = struct.unpack_from('<4i', raw)
    source, _, interest_only = raw[24:27]
    if source <= 14 and (1 << source) & 0x6D00:
        value, branch, wrapped = debt, 'native_source_retains_original', False
    elif interest_only == 1:
        value, branch, wrapped = debt, 'native_interest_only_retains_original', False
    else:
        principal = _signed32(monthly - interest)
        accrued = _signed32(principal * months)
        wrapped = principal != monthly - interest or accrued != principal * months
        value, branch = min(accrued, debt), 'native_monthly_principal_capped_at_original'
    return {'native_signed32': value, 'branch': branch,
            'days_to_stored_end': days, 'native_thirty_day_periods': months,
            'signed32_wrap': wrapped}


def loan_projection(raw, current_raw, slot):
    if len(raw) != 27:
        raise ValueError('Invalid native loan row width')
    debt, monthly, interest, conditional = struct.unpack_from('<4i', raw)
    source, ffp, interest_only = raw[24:27]
    if ffp > 1 or interest_only > 1:
        raise ValueError('Invalid native loan boolean')
    end, start = stored_date(raw[16:20]), stored_date(raw[20:24])
    remaining = {'amount': None, 'native_signed32': None, 'state': 'unsupported_date',
                 'payment_state': 'not_established'}
    try:
        native = native_remaining_debt(raw, current_raw)
    except ValueError:
        pass
    else:
        remaining.update(native)
        value = native['native_signed32']
        independent_date = native['branch'] != 'native_monthly_principal_capped_at_original'
        if debt == 0x7FFFFFFF or value == 0x7FFFFFFF:
            state = 'unclassified_native_limit'
        elif native['signed32_wrap']:
            state = 'native_signed32_wrap'
        elif debt < 0 or value < 0 or monthly < 0 or interest < 0:
            state = 'negative_native_value'
        elif end['state'] != 'stored_date' and not independent_date:
            state = 'unknown_end_date'
        else:
            state = 'native_schedule_calculation'
            remaining['amount'] = value
        remaining['state'] = state
    return {'slot': slot, 'original_debt': debt, 'monthly_repayment': monthly,
            'monthly_interest_repayment': interest, 'conditional_repayment': conditional,
            'start_date': start, 'end_date': end, 'source_code': source,
            'source_name': DEBT_SOURCES.get(source),
            'source_name_state': 'installed_editor_enum' if source in DEBT_SOURCES else 'unmapped_enum',
            'included_in_ffp_calculations': bool(ffp), 'interest_only': bool(interest_only),
            'remaining_debt': remaining, 'counterparty': None,
            'counterparty_state': 'exact_lender_not_in_source',
            'next_payment_due_date': None, 'next_payment_due_date_state': 'not_established'}


def verify_source(read, base):
    for rva, size, digest in SOURCE:
        if hashlib.sha256(read(base + rva, size)).hexdigest() != digest:
            raise ValueError('Native club debt source changed')
    if players.u64(read(base + world.TYPES['club'][0] + 24, 8)) != base + 0xE476C4:
        raise ValueError('Native CLUB property dispatch changed')


def _club(read, base, info, address):
    club, identity = world.club(read, base, address)
    index = int.from_bytes(read(address + 8, 4), 'little')
    database.club_membership(read, base, info, index, address)
    return {**club, 'database_index': index, 'native_id': identity[0], 'secondary_id': identity[1]}


def _owner(read, club):
    if read(club + 0x163, 1)[0] & 16:
        return club, None
    entries, _ = competition_stages.vector(read, club + 0x118, 256)
    for slot, relation in enumerate(entries):
        if not relation:
            raise ValueError('Null native financial-owner relationship')
        if players.u64(read(relation + 8, 8)) != club:
            continue
        code = read(relation + 0x30, 1)[0]
        if code <= 20 and (1 << code) & 0x1001F0:
            parent = players.u64(read(relation, 8))
            if parent and (parent < 4096 or parent % 8):
                raise ValueError('Invalid native financial owner')
            # The first qualifying relation stops the native search even if
            # its parent is null; the original club is the native fallback.
            return parent or club, {'slot': slot, 'source_code': code, 'null_parent_fallback': not bool(parent)}
    return club, None


def _full_finance(read, base, club):
    finance = players.u64(read(club + 0x150, 8))
    if not finance:
        return False
    if finance < 4096 or finance % 8:
        raise ValueError('Invalid native club finance pointer')
    table = world.pointer(read, finance)
    if table == base + world.TYPES['club_finance_base'][0]:
        world.typed(read, base, finance, 'club_finance_base')
        return False
    world.typed(read, base, finance, 'club_finance')
    if players.u64(read(table + 0x40, 8)) != base + 0xEB8174:
        raise ValueError('Native full-finance discriminator changed')
    return True


def decode(read, base, club):
    """Read a bounded report; caller must journal and recheck all reads.

    Source-order nulls and repeated objects are retained. Do not infer an empty
    source from a missing extension or an unsupported finance type.
    """
    verify_source(read, base)
    info = database.table(read, base, 'clubs')
    selected = _club(read, base, info, club)
    owner, relation = _owner(read, club)
    owner_info = selected if owner == club else _club(read, base, info, owner)
    current_raw = read(base + world.CURRENT_DATE, 4)
    current_date = world.packed_date(current_raw)
    result = {'state': 'unavailable', 'selected_club': selected, 'financial_owner': owner_info,
              'owner_relationship': relation, 'as_of_date': current_date, 'currency': None,
              'source_slot_count': None, 'native_report_limit': REPORT_LIMIT,
              'outside_report_slot_count': None, 'records': None,
              'complete_liability_ledger': False, 'evidence': 'native_DebtsAndLoansData_RemainingDebt',
              'limitations': LIMITATIONS}
    if not _full_finance(read, base, club) or not _full_finance(read, base, owner):
        result['reason'] = 'native_report_requires_full_selected_and_owner_finance'
        return result
    extension = players.u64(read(owner + 0x100, 8))
    if not extension:
        result['reason'] = 'missing_native_club_extension'
        return result
    if extension < 4096 or extension % 8:
        raise ValueError('Invalid native club extension')
    entries, _ = competition_stages.vector(read, extension + 0x50, 1024, entry_alignment=4)
    records = []
    for slot, entry in enumerate(entries[:REPORT_LIMIT]):
        records.append(loan_projection(read(entry, 27), current_raw, slot) if entry else
                       {'slot': slot, 'state': 'null_native_report_source_slot', 'remaining_debt': None})
    result.update(state='decoded' if all(entries[:REPORT_LIMIT]) else 'partial_null_source_slot',
                  reason='native_report_source_order', currency=wages.base_currency(read, base),
                  source_slot_count=len(entries), outside_report_slot_count=max(0, len(entries) - REPORT_LIMIT),
                  records=records)
    return result
