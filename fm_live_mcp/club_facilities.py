"""Canonical CLUB own stored facility levels; no native effective getter execution."""
from datetime import datetime, timezone
import struct

from . import players

FIELDS = {
    'training_facilities': (0x120, 'Ctlv', 'Training', 0),
    'youth_facilities': (0x12b, 'Cyfb', 'Youth Facilities', -1),
    'youth_coaching': (0x12c, 'Cytv', 'Youth Coaching', -1),
    'youth_recruitment': (0x12d, 'Crcb', 'Youth Recruitment', -1),
}
NATIVE_GUARDS = {
    0xe4b6fc: 'c88e8d52',
    0xe4b700: '886ea872',
    0xe4b704: '3f00086b',
    0xe4b70c: '888240f9',
    0xe4b710: '1381c439',
    0xe4bbc0: 'c88e8e52',
    0xe4bbc4: '286fa872',
    0xe4bbc8: '3f00086b',
    0xe4bbcc: '80c70154',
    0xe4f4bc: '888240f9',
    0xe4f4c0: '13b1c439',
    0xe480d4: '48cc8c52',
    0xe480d8: '286fa872',
    0xe480dc: '3f00086b',
    0xe480e0: '60360454',
    0xe507ac: '888240f9',
    0xe507b0: '13adc439',
    0xe4a91c: '486c8c52',
    0xe4a920: '486ea872',
    0xe4a924: '3f00086b',
    0xe4a928: '80e70254',
    0xe50618: '888240f9',
    0xe5061c: '13b5c439',
}
LIMITATIONS = ('Own stored CLUB levels only. Native effective facility properties can follow affiliations, '
               'shared facilities or inferred defaults; these are not reproduced. No stars, translated '
               'quality bands, grounds, investment costs, development effects or youth-intake forecasts. '
               'Signed -1 is unassigned; zero is retained explicitly. Reads are non-atomic with consumed-byte rechecks.')


def field_registry():
    return {name: dict(native_property=prop, official_editor_label=label,
                       source='canonical CLUB+0x100 stored secondary', native_offset=hex(offset),
                       editor_minimum=minimum, editor_maximum=20, unit='stored native level',
                       effective_value='not_evaluated')
            for name, (offset, prop, label, minimum) in FIELDS.items()}


def decode(read, base, club_address):
    for rva, expected in NATIVE_GUARDS.items():
        if read(base+rva, 4) != bytes.fromhex(expected):
            raise ValueError('Club facility native property code changed')
    pointer = players.u64(read(club_address+0x100, 8))
    if pointer and (pointer < 4096 or pointer % 8):
        raise ValueError('Invalid club facility secondary pointer')
    raw = read(pointer+0x120, 14) if pointer else None
    values = {}
    for name, (offset, prop, label, minimum) in FIELDS.items():
        native = struct.unpack_from('<b', raw, offset-0x120)[0] if raw is not None else None
        state = ('unavailable_secondary' if native is None else
                 'unassigned' if native == -1 and minimum == -1 else
                 'out_of_editor_range' if not minimum <= native <= 20 else 'stored')
        values[name] = dict(native_value=native, value=native if state=='stored' else None,
                            state=state, native_property=prop, unit='stored native level')
    return dict(state='available' if raw is not None else 'unavailable_secondary',
                source='own_stored_club_secondary', values=values,
                field_provenance=field_registry(), effective_values='not_evaluated')


def get_club_facilities(bridge, session_id, club_ref):
    from .bridge import BridgeError
    with bridge.lock, bridge._read_scope(session_id):
        process = bridge._current(session_id)
        tables = bridge._player_layout(process)
        base = tables[0]-players.RVA[0]
        snapshot, save, _ = bridge._world_state(process, tables)
        club, address, index, identity = bridge._referenced_club(snapshot, base, club_ref, tables)
        try:
            facilities = decode(snapshot, base, address)
            snapshot.verify()
        except (ValueError, IndexError) as exc:
            raise BridgeError(f'Club facilities rejected: {exc}') from exc
        bridge._current(session_id)
        return dict(session_id=session_id, observed_at=datetime.now(timezone.utc).isoformat(),
                    save=bridge._public_save(save),
                    club=dict(club, club_ref=club_ref, database_index=index,
                              native_id=identity[0], random_id=identity[1]),
                    facilities=facilities, limitations=LIMITATIONS)
