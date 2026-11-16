"""Save-bound adapter for supported current native responsibility queries."""
from copy import deepcopy
from datetime import datetime,timezone
from . import current_staff_responsibilities,players
from .bridge import BridgeError
from .reader import ReaderError
from .live_staff_responsibilities import _selected


def get_club_current_staff_responsibilities(bridge,session_id,coach_name=None,club_ref=None):
    if type(session_id) is not str or not 1 <= len(session_id) <= 128:
        raise BridgeError('session_id must be a current attachment ID of at most 128 characters.')
    if coach_name is not None and (type(coach_name) is not str or not 1 <= len(coach_name) <= 256):
        raise BridgeError('coach_name must be a name returned by fm_get_save.')
    if club_ref is not None and (type(club_ref) is not str or not 1 <= len(club_ref) <= 128):
        raise BridgeError('club_ref must be a canonical reference from fm_find_clubs.')
    if coach_name is not None and club_ref is not None:
        raise BridgeError('Select either club_ref or coach_name, not both.')
    state = {}

    def seal():
        # Bridge performs its post-yield process callback before this hook.
        # Every remaining context/public callback precedes both physical fences.
        if bridge._current(session_id) != process:raise ValueError('Responsibility process lifetime changed')
        after_tables = bridge._player_layout(process)
        if after_tables != tables or bridge.plugin_identity != plugin:
            raise ValueError('Responsibility loaded plugin/build changed')
        final_context,after_save,after_identity = bridge._world_state(process,after_tables)
        if after_identity != identity or after_save != save or bridge.world_identity != identity:
            raise ValueError('Responsibility save/date context changed')
        after_club,after_selection = _selected(
            bridge,final_context,base,after_save,after_tables,coach_name,club_ref)
        if after_club != club or after_selection != selection:
            raise ValueError('Responsibility selected club/coach binding changed')
        public_save = bridge._public_save(save)
        public_club = {**report['club'],'native_id':selection['identity'][0],
            'secondary_id':selection['identity'][1]}
        managed_context = None if club_ref is not None else {
            'coach_name':selection['coach']['name'],'team':selection['team']}
        if bridge._current(session_id) != process:raise ValueError('Final responsibility process lifetime changed')
        if (bridge.session != session_id or bridge.process != process
                or bridge.plugin_identity != plugin or bridge.world_identity != identity
                or (club_ref is not None and bridge.club_refs.get(club_ref) != club_binding)):
            raise ValueError('Final responsibility source binding changed')
        snapshot.verify()
        final_context.verify()
        state['result'] = {'session_id':session_id,'observed_at':datetime.now(timezone.utc).isoformat(),
            'save':public_save,'club':public_club,'current_staff_responsibilities':report,
            'managed_context':managed_context,'save_identity':'native_binding_rechecked','atomic':False,
            'native_calls':False,'original_native_code_emulated':report['original_native_code_emulated'],'saved_file_fallback':False,
            'limitations':current_staff_responsibilities.LIMITATIONS}

    try:
        with bridge.lock:
            with bridge._read_scope(session_id,final_verify=seal):
                process = bridge._current(session_id)
                tables = bridge._player_layout(process)
                plugin = deepcopy(bridge.plugin_identity)
                base = tables[0]-players.RVA[0]
                snapshot,loaded,identity = bridge._world_state(process,tables)
                save,identity = deepcopy(loaded),deepcopy(identity)
                if bridge.world_identity != identity:raise ValueError('Initial responsibility save identity differs')
                club_binding = deepcopy(bridge.club_refs.get(club_ref)) if club_ref is not None else None
                club,selection = _selected(bridge,snapshot,base,save,tables,coach_name,club_ref)
                report = current_staff_responsibilities.decode(snapshot,base,club)
            return state['result']
    except (ValueError,IndexError,KeyError,TypeError,BridgeError,ReaderError) as error:
        raise BridgeError(f'Current staff-responsibility query rejected; no partial result returned: {error}') from error
