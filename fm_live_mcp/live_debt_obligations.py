"""Canonical selected-CLUB adapter for the native remaining-loan report."""
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timezone

from . import club_debt_obligations, players, prepared_tactics_source, world
from .bridge import BridgeError
from .reader import ReadStream


@contextmanager
def _stream(bridge, process):
    if bridge._reader is not None:
        raise ValueError('Nested debt-obligation native reader rejected')
    reader = bridge._reader = ReadStream(bridge.helper, process.pid)
    try:
        yield
    finally:
        bridge._reader = None
        reader.close()


def _selected(bridge, snapshot, base, save, tables, coach_name, club_ref):
    if club_ref is not None:
        club, address, index, identity = bridge._referenced_club(snapshot, base, club_ref, tables)
        return address, {'club': club, 'index': index, 'identity': identity, 'kind': 'club_ref'}
    coach = deepcopy(bridge._select_coach(save, coach_name))
    team, human = prepared_tactics_source._team_and_human(snapshot, base, coach)
    address = world.pointer(snapshot, coach['team_address'] + 0x30)
    club, identity = world.club(snapshot, base, address)
    if club != coach['club'] or team['owner']['kind'] != 'club':
        raise ValueError('Selected debt-obligation HUMAN/TEAM/CLUB association changed')
    return address, {'coach': coach, 'team': team, 'human': human, 'club': club,
                     'identity': identity, 'kind': 'managed_club'}


def get_club_debt_obligations(bridge, session_id, coach_name=None, club_ref=None):
    """Read the report and finish physical checks after all context callbacks."""
    if type(session_id) is not str or not 1 <= len(session_id) <= 128:
        raise BridgeError('session_id must be a current attachment ID of at most 128 characters.')
    if coach_name is not None and (type(coach_name) is not str or not 1 <= len(coach_name) <= 256):
        raise BridgeError('coach_name must be a name returned by fm_get_save.')
    if club_ref is not None and (type(club_ref) is not str or not 1 <= len(club_ref) <= 128):
        raise BridgeError('club_ref must be a canonical reference from fm_find_clubs.')
    if coach_name is not None and club_ref is not None:
        raise BridgeError('Select either club_ref or coach_name, not both.')
    try:
        with bridge.lock:
            process = bridge._current(session_id)
            with _stream(bridge, process):
                tables = bridge._player_layout(process)
                plugin = deepcopy(bridge.plugin_identity)
                base = tables[0] - players.RVA[0]
                snapshot, loaded, identity = bridge._world_state(process, tables)
                save, identity = deepcopy(loaded), deepcopy(identity)
                if bridge.world_identity != identity:
                    raise ValueError('Debt-obligation initial save identity differs')
                club, selection = _selected(bridge, snapshot, base, save, tables, coach_name, club_ref)
                report = club_debt_obligations.decode(snapshot, base, club)
                if bridge._current(session_id) != process:
                    raise ValueError('Debt-obligation process lifetime changed')
                after_tables = bridge._player_layout(process)
                if after_tables != tables or bridge.plugin_identity != plugin:
                    raise ValueError('Debt-obligation loaded plugin/build changed')
                final_context, after_save, after_identity = bridge._world_state(process, after_tables)
                if after_identity != identity or after_save != save or bridge.world_identity != identity:
                    raise ValueError('Debt-obligation save/date context changed')
                after_club, after_selection = _selected(
                    bridge, final_context, base, after_save, after_tables, coach_name, club_ref)
                if after_club != club or after_selection != selection:
                    raise ValueError('Debt-obligation selected club/coach binding changed')
                public_save = bridge._public_save(save)
                if bridge._current(session_id) != process:
                    raise ValueError('Debt-obligation final process lifetime changed')
                snapshot.verify()
                final_context.verify()
                if bridge.plugin_identity != plugin or bridge.world_identity != identity:
                    raise ValueError('Debt-obligation final source binding changed')
                return {'session_id': session_id, 'observed_at': datetime.now(timezone.utc).isoformat(),
                        'save': public_save, 'club': report['selected_club'],
                        'debt_obligations': report, 'save_identity': 'native_binding_rechecked',
                        'atomic': False, 'native_calls': False, 'saved_file_fallback': False,
                        'limitations': club_debt_obligations.LIMITATIONS}
    except (ValueError, IndexError, KeyError, TypeError, BridgeError) as exc:
        raise BridgeError(f'Club debt-obligation query rejected; no partial result returned: {exc}') from exc
