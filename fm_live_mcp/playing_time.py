"""Stored main-contract agreed playing time; no promise evaluation or game calls."""
from datetime import datetime, timezone
import struct

from . import database, players, world

# Native agreed-playing-time -> PLAYER_TYPE -> compiled English fallback labels.
# Duplicate names remain distinct native codes. Contextual/custom display names
# and promises are separate sources and are deliberately not evaluated here.
LABELS = {
    1: (3200, 482652, 'Star Player'),
    2: (3201, 482653, 'Important Player'),
    3: (3202, 482654, 'Regular Starter'),
    4: (3203, 688150, 'Squad Player'),
    5: (3204, 483636, 'Impact Sub'),
    6: (3205, 688150, 'Squad Player'),
    7: (3206, 688152, 'Fringe Player'),
    8: (3207, 688152, 'Fringe Player'),
    9: (3208, 483637, 'Emergency Backup'),
    10: (3209, 485380, 'Breakthrough Prospect'),
    11: (3210, 485381, 'Future Prospect'),
    12: (3211, 482663, 'Hot Prospect'),
    13: (3212, 482664, 'Youngster'),
    15: (3215, 485382, 'First-Choice Goalkeeper'),
    16: (3216, 485383, 'Cup Goalkeeper'),
    17: (3217, 485384, 'Domestic Cup Goalkeeper'),
    18: (3218, 485385, 'Continental Cup Goalkeeper'),
    19: (3219, 485383, 'Cup Goalkeeper'),
    20: (3220, 485386, 'Backup'),
    21: (3221, 483637, 'Emergency Backup'),
    22: (3214, 482666, 'Surplus to Requirements'),
}
ENGLISH_RESOURCE_SHA256 = '3ce742519bf694636f41a1dae8d45a3dab86fad7d164a58696139e4b4509dd43'
SCOPE = ('Stored current main-contract agreed playing-time code, with compiled English fallback labels. '
         'Not actual minutes, happiness, promise fulfilment, future playing-time pathways, a loan-team '
         'agreement or a selected localized/custom PLAYER_TYPE display name. Active player and club '
         'promises remain unproved. Virtual players are unsupported; no game functions are executed.')


def decode(read, base, person):
    table = world.pointer(read, person)
    if (players.u64(read(table + 121 * 8, 8)) != base + 0xCB3724
            or struct.unpack('<q', read(table - 0x3D8, 8))[0] != -0x110):
        raise ValueError('Playing-time current-contract getter changed')
    contract = players.u64(read(person - 0x98, 8))
    empty = {'native_code': None, 'title': None, 'player_type_native_id': None,
             'translation_id': None, 'label_source': None}
    if not contract:
        return {**empty, 'state': 'no_current_contract'}
    if contract < 4096 or contract % 8:
        raise ValueError('Invalid playing-time contract pointer')
    vtable = world.pointer(read, contract)
    kind = next((kind for kind in ('full_contract', 'basic_contract')
                 if vtable == base + world.TYPES[kind][0]), None)
    if kind is None:
        raise ValueError('Unsupported playing-time contract type')
    world.typed(read, base, contract, kind)
    if world.pointer(read, contract + 8) != person:
        raise ValueError('Playing-time contract owner changed')
    if kind == 'basic_contract':
        return {**empty, 'state': 'basic_contract_playing_time_unavailable'}
    if players.u64(read(vtable + 32 * 8, 8)) != base + 0x1005C78:
        raise ValueError('Agreed playing-time getter changed')
    if read(base + 0x1005C78, 8) != bytes.fromhex('00504139c0035fd6'):
        raise ValueError('Agreed playing-time native accessor changed')
    code = read(contract + 0x54, 1)[0]
    label = LABELS.get(code)
    state = ('decoded_compiled_english' if label is not None else
             'native_empty_display' if code == 0 else
             'contextual_display_unavailable' if code == 14 else
             'native_scouting_required' if code == 23 else 'unmapped_native_code')
    return {**empty, 'native_code': code, 'state': state,
            **({'player_type_native_id': label[0], 'translation_id': label[1],
                'title': label[2], 'label_source': 'compiled_native_english_fallback'} if label else {})}


def get_player_playing_time(bridge, session_id, player_refs):
    from .bridge import BridgeError
    bridge._validate_player_ref_list(player_refs)
    with bridge.lock, bridge._read_scope(session_id):
        process = bridge._current(session_id)
        tables = bridge._player_layout(process)
        base = tables[0] - players.RVA[0]
        read, save, _ = bridge._world_state(process, tables)
        try:
            people = database.table(read, base, 'people')
            subjects = bridge._bound_subjects(session_id, read, base, tables, people, player_refs)
            rows = [{'player_ref': ref, **subjects[ref][1],
                     'agreed_playing_time': decode(read, base, subjects[ref][0])}
                    for ref in player_refs]
            read.verify()
            bridge._current(session_id)
        except (ValueError, IndexError, BridgeError) as error:
            raise BridgeError(f'Agreed playing-time query rejected: {error}') from error
    return {'session_id': session_id, 'observed_at': datetime.now(timezone.utc).isoformat(),
            'save': bridge._public_save(save), 'players': rows,
            'active_player_promises': None, 'active_club_promises': None,
            'promises_state': 'not_decoded', 'scope': SCOPE,
            'evidence': 'canonical_PERSON_to_owned_current_FULL_CONTRACT_native_agreed_playing_time',
            'reads_atomic': False}
