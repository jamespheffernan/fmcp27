"""Guarded live read of the selected payer retained appearance-clause family."""
from copy import deepcopy
from datetime import datetime, timezone

from . import players, contingent_transfer_appearance, contingent_transfer_people
from .bridge import BridgeError
from .live_debt_obligations import _selected, _stream


def get_club_contingent_transfer_clauses(bridge, session_id, coach_name=None, club_ref=None):
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
                    raise ValueError('Contingent-clause initial save identity differs')
                club, selection = _selected(bridge, snapshot, base, save, tables, coach_name, club_ref)
                report = contingent_transfer_people.decode(snapshot, base, club)
                if bridge._current(session_id) != process:
                    raise ValueError('Contingent-clause process lifetime changed')
                after_tables = bridge._player_layout(process)
                if after_tables != tables or bridge.plugin_identity != plugin:
                    raise ValueError('Contingent-clause loaded plugin/build changed')
                final_context, after_save, after_identity = bridge._world_state(process, after_tables)
                if after_identity != identity or after_save != save or bridge.world_identity != identity:
                    raise ValueError('Contingent-clause save/date context changed')
                after_club, after_selection = _selected(
                    bridge, final_context, base, after_save, after_tables, coach_name, club_ref)
                if after_club != club or after_selection != selection:
                    raise ValueError('Contingent-clause selected club/coach binding changed')
                public_save = bridge._public_save(save)
                if bridge._current(session_id) != process:
                    raise ValueError('Contingent-clause final process lifetime changed')
                snapshot.verify()
                final_context.verify()
                if bridge.plugin_identity != plugin or bridge.world_identity != identity:
                    raise ValueError('Contingent-clause final source binding changed')
                return {'session_id': session_id, 'observed_at': datetime.now(timezone.utc).isoformat(),
                        'save': public_save, 'club': report['selected_club'],
                        'contingent_transfer_clauses': report, 'save_identity': 'native_binding_rechecked',
                        'atomic': False, 'native_calls': False, 'saved_file_fallback': False,
                        'limitations': contingent_transfer_people.LIMITATIONS}
    except (ValueError, IndexError, KeyError, TypeError, BridgeError) as exc:
        raise BridgeError(f'Club contingent transfer-clause query rejected; no partial result returned: {exc}') from exc
