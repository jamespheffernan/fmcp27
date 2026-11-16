"""Private canonical CLUB -> native selector inputs -> copied wage reducer.

The caller owns process/session discovery and supplies the full lifetime reader,
not selected offers or amounts. This component checks that callback against the
mapped plugin, loaded career/date/count and canonical selected CLUB. Every game
read is passive; copied instructions and stores remain inside the reducer VM.
Payroll refresh, v138 and EAEB's final total are outside this component.
"""
from dataclasses import dataclass
import struct
import time

from . import committed_wage_offer_selection as selector
from . import committed_wage_spending_core as reducer
from . import database, players, world


@dataclass(frozen=True)
class FinancialLifetime:
    """Caller-read identity, not a credential or an assertion of authority.

    process_identity is Bridge.Process's six fields in declaration order.
    plugin_stamp and plugin_uuid are its checked image stamp and mapped UUID.
    world_identity is world.loaded's identity, with its current save_count/date
    supplied separately. club_identity is (address, ordinal, UID, secondaryUID).
    The callback must freshly recheck the process/session on every invocation.
    """
    process_identity: tuple
    plugin_stamp: tuple
    plugin_uuid: bytes
    plugin_base: int
    world_identity: tuple
    save_count: int
    current_date: str
    club_identity: tuple


@dataclass(frozen=True)
class SelectedWageReduction:
    club_identity: tuple
    first_team: int
    selection: selector.OfferSelection
    reduction: reducer.WageReduction


def _lifetime(value, base, image_stamp, club):
    if type(value) is not FinancialLifetime:
        raise reducer.SourceUnavailable('full caller-owned financial lifetime is required')
    process = value.process_identity
    if (type(process) is not tuple or len(process) != 6 or type(process[0]) is not int
            or process[0] <= 0 or any(type(x) is not str or not x for x in process[1:])
            or process[3] != players.VERSION or process[4] != 'com.SportsInteractive.FootballManager27'
            or type(value.plugin_stamp) is not tuple or value.plugin_stamp != tuple(image_stamp)
            or type(value.plugin_uuid) is not bytes or len(value.plugin_uuid) != 16
            or type(value.plugin_base) is not int or value.plugin_base != base
            or type(value.world_identity) is not tuple or not value.world_identity
            or type(value.save_count) is not int or not 0 <= value.save_count <= 10000000
            or type(value.current_date) is not str or type(value.club_identity) is not tuple
            or len(value.club_identity) != 4 or value.club_identity[0] != club
            or any(type(x) is not int for x in value.club_identity)):
        raise reducer.SourceUnavailable('incomplete or mismatched financial lifetime identity')
    return value


def calculate(read, base, image_stamp, *, club, lifetime):
    """Select native (1,0,2) inputs and reduce them in one checked read scope.

    Success is conditional copied-native arithmetic over checked retained
    sources, not a current payroll/commitment total. Unknown selection or a
    cold reducer branch raises; no partial financial result is returned.
    """
    reducer._address(base)
    reducer._address(club)
    if not callable(lifetime):
        raise reducer.SourceUnavailable('financial lifetime reader required')
    initial = _lifetime(lifetime(), base, image_stamp, club)
    deadline = time.monotonic()+30
    remaining = [256*1024*1024, 400000]

    def bounded_read(address, count):
        if (type(address) is not int or type(count) is not int or address < 4096
                or not 0 <= count <= 2*1024*1024):
            raise reducer.SourceUnavailable('invalid composition source read')
        remaining[0] -= count
        remaining[1] -= 1
        if min(remaining) < 0 or time.monotonic() >= deadline:
            raise reducer.SourceUnavailable('composition source read bound')
        return read(address, count)

    selected_inputs = world.ReadSet(bounded_read)
    if players.macho_uuid(selected_inputs(base, 16384)) != initial.plugin_uuid:
        raise reducer.SourceUnavailable('composition mapped plugin UUID changed')
    career, identity = world.loaded(selected_inputs, base)
    if (identity != initial.world_identity or career['save_count'] != initial.save_count
            or career['current_date'] != initial.current_date):
        raise reducer.SourceUnavailable('composition loaded career context changed')
    world.typed(selected_inputs, base, club, 'club')
    actual_club = (club, *struct.unpack('<III', selected_inputs(club+8, 12)))
    if actual_club != initial.club_identity or not actual_club[2]:
        raise reducer.SourceUnavailable('composition selected CLUB identity changed')
    clubs = database.table(selected_inputs, base, 'clubs')
    database.club_membership(selected_inputs, base, clubs, actual_club[1], club)
    begin, end = reducer._vector(selected_inputs, club+0x18, limit=256)
    first_team = players.u64(selected_inputs(begin, 8)) if begin != end else 0
    if first_team:
        selector._Source(selected_inputs, base).team(first_team)
        if (players.u64(selected_inputs(first_team+0x30, 8)) != club
                or selected_inputs(first_team+0x2f, 1) != b'\0'):
            raise reducer.SourceUnavailable('composition first TEAM owner or compact type changed')

    def check_lifetime():
        current = _lifetime(lifetime(), base, image_stamp, club)
        if current != initial:
            raise reducer.SourceUnavailable('financial composition lifetime changed')
        return current

    try:
        selection = selector.select_offers(selected_inputs, base, first_team,
            exclude_native_states=True, skip_state19=False, mode=2)
        if selection.state != 'selected' or selection.selected is None:
            raise reducer.SourceUnavailable(f'financial selection unavailable: {selection.reason}')
        addresses = tuple(row.address for row in selection.selected)
        persons = tuple(row.person_address for row in selection.selected)
        # Native1826988 materializes source40 in a null alternate48 after
        # source!=original. Preserve that selected-row local cache effect;
        # retain original source bytes in selected_inputs for final rechecks.
        cached_alternates = {}
        for address in set(addresses):
            source = players.u64(selected_inputs(address+0x40, 8))
            if source != first_team and not players.u64(selected_inputs(address+0x48, 8)):
                field = address+0x48
                cached_alternates.setdefault(field & -4096, {})[field] = struct.pack('<Q', source)

        def reducer_read(address, count):
            raw = bytearray(bounded_read(address, count))
            for page in range(address & -4096, address+count, 4096):
                for field, value in cached_alternates.get(page, {}).items():
                    lo, hi = max(address, field), min(address+count, field+8)
                    if lo < hi:
                        raw[lo-address:hi-address] = value[lo-field:hi-field]
            return bytes(raw)
        # Raw page transport must bypass selected_inputs: reducer verifies its
        # exact consumed spans, not unrelated padding in fetched 4KiB pages.
        result = reducer.calculate(reducer_read, base, image_stamp, club=club,
            selected_offers=addresses, selected_persons=persons, lifetime=check_lifetime)
    except (selector.UnsupportedSelection, reducer.SourceUnavailable):
        check_lifetime()
        selected_inputs.verify()
        raise
    # The reducer's final callback checked the shared lifetime before its own
    # final byte rechecks. Recheck selector inputs after that same callback;
    # no later callback can invalidate an already-verified financial value.
    selected_inputs.verify()
    return SelectedWageReduction(actual_club, first_team, selection, result)
