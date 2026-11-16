"""Current selected-roster career morale; no profile generation or game calls."""
from copy import deepcopy
from datetime import datetime, timezone

from . import assessment_people, database, player_career_morale as morale
from . import players, prepared_tactics_source, world
from .bridge import BridgeError
# Reuse only the existing narrow canonical reference/name checks. These do not
# inspect national-duty sources or decode attributes/generated player profiles.
from .live_international_duty import _bound_person, _public

SCOPE = ('Requested distinct player references on the selected HUMAN/TEAM native roster; '
         'this can include loaned-out players and is not whole-club coverage. '+morale.SCOPE)


def get_player_morale(bridge, session_id, player_refs, coach_name=None):
    """Read 1–100 distinct existing refs, rejecting a drifting batch as a whole."""
    if (type(player_refs) is not list or not 1 <= len(player_refs) <= 100
            or any(type(ref) is not str or not ref for ref in player_refs)
            or len(set(player_refs)) != len(player_refs)):
        raise BridgeError('Supply 1 through 100 distinct nonempty player references.')
    if coach_name is not None and (type(coach_name) is not str or not 1 <= len(coach_name) <= 256):
        raise BridgeError('coach_name must be a name returned by fm_get_save.')
    try:
        with bridge.lock, bridge._read_scope(session_id):
            process = bridge._current(session_id)
            tables = bridge._player_layout(process)
            plugin = deepcopy(bridge.plugin_identity)
            read, loaded, identity = bridge._world_state(process, tables)
            save, identity = deepcopy(loaded), deepcopy(identity)
            if bridge.world_identity != identity:
                raise ValueError('Career-morale world binding differs')
            base = tables[0] - players.RVA[0]
            coach = deepcopy(bridge._select_coach(save, coach_name))
            team, human = prepared_tactics_source._team_and_human(read, base, coach)
            roster = world.vector(read, coach['team_address'] + 0x38, 256)
            people = database.table(read, base, 'people')
            assessment_people.verify_native(read, base)
            morale.verify_native(read, base)
            bindings, rows = {}, []
            for reference in player_refs:
                binding = bridge.player_refs.get(reference)
                if type(binding) is not dict:
                    raise ValueError('Unknown or expired player reference')
                binding = deepcopy(binding)
                if binding.get('address') not in roster:
                    raise ValueError('Player reference is outside the selected native TEAM roster')
                bindings[reference] = binding
                person, kind, name, display = _bound_person(read, base, tables, people, binding)
                row = {'player_ref': reference, 'native_identity': _public(person),
                       'record_kind': kind, 'name': name, 'display_name': display,
                       'name_state': 'unavailable_without_generated_profile' if kind == 'virtual'
                                     else 'stored_native_name_fields',
                       'morale': morale.inspect(read, base, binding['address'], kind)}
                rows.append(row)
            read.verify()
            current = bridge._current(session_id)
            if current != process:
                raise ValueError('Career-morale process lifetime changed')
            after_tables = bridge._player_layout(current)
            if after_tables != tables or bridge.plugin_identity != plugin:
                raise ValueError('Career-morale loaded plugin/build changed')
            after_read, after_save, after_identity = bridge._world_state(current, after_tables)
            if (after_identity != identity or bridge.world_identity != identity or after_save != save):
                raise ValueError('Career-morale loaded save/date context changed')
            after_coach = bridge._select_coach(after_save, coach_name)
            after_team, after_human = prepared_tactics_source._team_and_human(after_read, base, after_coach)
            after_roster = world.vector(after_read, after_coach['team_address'] + 0x38, 256)
            if (after_coach != coach or after_team != team or after_human != human or after_roster != roster):
                raise ValueError('Career-morale selected coach/TEAM/roster changed')
            if any(bridge.player_refs.get(ref) != value for ref, value in bindings.items()):
                raise ValueError('Career-morale player reference binding changed')
            read.verify()
            after_read.verify()
            if bridge._current(session_id) != process:
                raise ValueError('Career-morale process lifetime changed')
            # Recheck both source journals after the final lifetime callback.
            read.verify()
            after_read.verify()
            if (bridge.plugin_identity != plugin or bridge.world_identity != identity
                    or any(bridge.player_refs.get(ref) != value for ref, value in bindings.items())):
                raise ValueError('Career-morale final context/reference binding changed')
            return {'session_id': session_id, 'observed_at': datetime.now(timezone.utc).isoformat(),
                    'save': bridge._public_save(save), 'coach': coach['name'], 'club': coach['club'],
                    'team': team, 'players': rows, 'count': len(rows),
                    'source': 'stored_career_player_morale',
                    'scope': SCOPE, 'atomic': False, 'saved_file_fallback': False}
    except (ValueError, IndexError, KeyError, TypeError, BridgeError) as exc:
        raise BridgeError(f'Career-morale query rejected; no partial result returned: {exc}') from exc
