"""Calendar projection of the retained native transfer cash-call branch.

This projects the original branch under unchanged retained inputs. It is not
an invoice due-date or paid-state inference. No game code is invoked.
"""
from datetime import date
import hashlib
import struct

from . import database, players, retained_transfer_debt as retained, world


TIMING_SOURCE = (
    (0x2E143C0, 400, 'c664fd15000ca59dc3318ada40e9d515cdf2844eb305b25e914f6ae47442869b'),
    (0x2536D80, 848, '418650c79b279f1b3160f4284c6cbaef707264f90ecedfd4e8ce55c23958e004'),
    (0x42E98A4, 348, 'b8aa6c353888da56c8b7522fe98538185833ec004b2f1da736c4af1db8c63495'),
    (0x2E1AC08, 20, '86ae95a4077be8d6aa1d440b7e70b71e63fbe4552daf17572ae42d7bf452c49a'),
    (0x2E1B12C, 36, '545d13ff96a9c4ab6ffaee052c6b38f93e5a7e76fda33faeb6c9930ed4e1449d'),
    (0x251FD04, 12, '390ce4e2301aa648885f91d4049eea5b8eecd11df16f91c22a35882a963f70f5'),
    (0x253FADC, 84, '59608e87cb9a18f674bce28b1e46dbd00b037e89c3e5e5bbd957d41fa1372714'),
)
SOURCE = retained.SOURCE + TIMING_SOURCE
LIMITATIONS = (
    'Projects the next native retained-transfer cash-call opportunity under unchanged source '
    'inputs, normal native clock advancement and the processing admission byte remaining1. '
    'The original branch is at08:30 on the first Gregorian day of a month; its date gate, '
    'remaining-counter modulo and prior-removal predicates are applied. The original call '
    'argument is unit amount times interval, distinct from native TransferDebt unit amount '
    'times remaining count. This does not prove an invoice date, actual cash paid, recipient '
    'net after other processing, arrears, affordability, or complete future cash flow. '
    'The08:30 current tick is ambiguous and remains unavailable. Native calendar time has '
    'no established timezone. No native function, refresh or game write is used.'
)


def native_clock(raw):
    world.packed_date(raw)
    code = struct.unpack_from('<H', raw)[0] >> 9
    if code > 72:
        return {'state': 'unsupported_native_clock_code', 'clock_code': code, 'time': None, 'hhmm': None}
    minutes = 0 if code == 0 else 360 + (code - 1) * 15
    hour, minute = divmod(minutes, 60)
    return {'state': 'native_GTIM_clock', 'clock_code': code,
            'time': f'{hour:02}:{minute:02}', 'hhmm': hour * 100 + minute}


def _month(value, offset):
    ordinal = value.year * 12 + value.month - 1 + offset
    year, month = divmod(ordinal, 12)
    if not 1850 <= year <= 2200:
        raise ValueError('Projected native date outside supported calendar')
    return date(year, month + 1, 1)


def forecast_row(raw, current_raw, *, admission_flag, prior_admission):
    if len(raw) != 34:
        raise ValueError('Invalid retained transfer timing row width')
    out = {'state': 'unavailable', 'reason': None, 'next_native_cash_branch': None,
           'last_native_cash_branch_date': None, 'remaining_native_cash_branch_count': None,
           'remaining_native_cash_argument_sum': None, 'payment_state': 'not_established',
           'next_payment_due_date': None, 'prior_admission': prior_admission,
           'projection_basis': 'unchanged_retained_counter_and_native_calendar_gates'}
    if prior_admission['state'] != 'admitted':
        out['reason'] = prior_admission['reason']
        return out
    if admission_flag != 1:
        out['reason'] = 'native_cash_processing_not_admitted'
        return out
    clock = native_clock(current_raw)
    if clock['time'] is None:
        out['reason'] = clock['state']
        return out
    current = date.fromisoformat(world.packed_date(current_raw))
    if current.day == 1 and clock['hhmm'] == 830:
        out['reason'] = 'current_native_cash_tick_before_after_ambiguous'
        return out
    amount = struct.unpack_from('<i', raw, 24)[0]
    interval, count = struct.unpack_from('<bb', raw, 32)
    if interval <= 0 or count <= 0:
        out['reason'] = 'unclassified_native_cash_terms'
        return out
    try:
        gate = date.fromisoformat(world.packed_date(raw[20:24]))
        first = _month(current, 0 if current.day == 1 and clock['hhmm'] < 830 else 1)
        if first < gate:
            first = _month(gate, 0 if gate.day == 1 else 1)
        skipped = (count - 1) % interval
        next_date = _month(first, skipped)
        branch_count = (count - 1) // interval + 1
    except ValueError:
        out['reason'] = 'unsupported_native_calendar_gate_or_projection'
        return out
    try:
        last_date, last_state = _month(next_date, (branch_count - 1) * interval).isoformat(), 'native_calendar_projection'
    except ValueError:
        last_date, last_state = None, 'outside_supported_native_calendar'
    argument = amount * interval
    native_argument = retained.loans._signed32(argument)
    argument_state = ('native_cash_argument_signed32_wrap' if native_argument != argument else
                      'unclassified_native_unit_amount' if amount < 0 or amount == 0x7FFFFFFF else
                      'native_cash_call_argument')
    argument_known = argument_state == 'native_cash_call_argument'
    out.update(state='projected_native_cash_branch', reason='original_calendar_date_and_counter_gates',
               next_native_cash_branch={'date': next_date.isoformat(), 'time': '08:30',
                   'call_argument_amount': argument if argument_known else None,
                   'call_argument_native_signed32': native_argument, 'call_argument_state': argument_state,
                   'currency': 'GBP', 'timezone': None,
                   'timezone_state': 'not_established', 'count_before_branch': count - skipped,
                   'counter_opportunities_skipped': skipped},
               last_native_cash_branch_date=last_date, last_native_cash_branch_date_state=last_state,
               remaining_native_cash_branch_count=branch_count,
               remaining_native_cash_argument_sum=argument * branch_count if argument_known else None)
    return out


def _prior_admission(read, raw, people_count):
    index = struct.unpack_from('<i', raw, 28)[0]
    for club in struct.unpack_from('<QQ', raw):
        if not club or int.from_bytes(read(club + 12, 4), 'little') == 0x264B4:
            continue
        nation = players.u64(read(club + 0xD8, 8))
        if not nation:
            return {'state': 'native_prior_removal', 'reason': 'native_club_nation_removal_before_cash',
                    'native_person_index': index, 'native_person_header_count': people_count}
        if nation < 4096 or nation % 8:
            raise ValueError('Malformed transfer cash-admission club nation pointer')
    # Original unsigned count>=sign-extended-index admits equality; its later
    # lookup can be null, but the retained cash-call branch still accepts it.
    admitted = 0 <= index <= people_count
    return {'state': 'admitted' if admitted else 'native_prior_removal',
            'reason': 'native_prior_removal_predicates_passed' if admitted else 'native_person_index_removal_before_cash',
            'native_person_index': index, 'native_person_header_count': people_count,
            'native_null_lookup_boundary': index == people_count}


def decode(read, base, club):
    for rva, size, digest in TIMING_SOURCE:
        if hashlib.sha256(read(base + rva, size)).hexdigest() != digest:
            raise ValueError('Native retained transfer cash-timing source changed')
    report = retained.decode(read, base, club)
    if report['records'] is None:
        report['native_cash_timing'] = {'state': 'unavailable', 'reason': 'retained_source_unavailable'}
        return report
    current_raw = read(base + world.CURRENT_DATE, 4)
    clock = native_clock(current_raw)
    flag = read(base + 0x56D4987, 1)[0]
    people = database.table(read, base, 'people')
    manager = world.pointer(read, base + retained.ROOT)
    entries = retained._entries(read, manager + 0xD8)
    for row in report['records']:
        slot = row['slot']
        if not 0 <= slot < len(entries) or not entries[slot]:
            raise ValueError('Retained transfer timing source slot changed')
        raw = read(entries[slot], 34)
        row['native_cash_timing'] = forecast_row(raw, current_raw, admission_flag=flag,
            prior_admission=_prior_admission(read, raw, people['count']))
    report['native_cash_timing'] = {'state': 'source_profile_applied', 'as_of_native_clock': clock,
        'native_processing_admission_byte': flag, 'timezone': None, 'timezone_state': 'not_established',
        'payment_state': 'not_established', 'next_payment_due_date': None, 'limitations': LIMITATIONS}
    return report
