"""Save/coach-bound fixed main-contract expiry query, with sealed byte fences."""
from copy import deepcopy
from datetime import date, datetime, timezone
import hashlib
import secrets
from struct import error as StructError

from . import assessment_people, database, player_contract_expiry_source as source
from . import players, prepared_tactics_source
from .bridge import BridgeError
from .reader import ReaderError


def get_managed_player_contract_expiry(bridge, session_id, expires_on_or_before,
                                     coach_name=None, limit=100, unclassified_limit=100, offset=0,
                                     expected_source_id=None):
    try:
        cutoff = date.fromisoformat(expires_on_or_before)
        if cutoff.isoformat() != expires_on_or_before or not 1850 <= cutoff.year <= 2200:
            raise ValueError('Noncanonical date')
    except (TypeError, ValueError) as exc:
        raise BridgeError('expires_on_or_before must be YYYY-MM-DD, with year 1850–2200.') from exc
    for value, low, high, name in ((offset, 0, 256, 'offset'), (limit, 1, 100, 'limit'),
                                  (unclassified_limit, 0, 256, 'unclassified_limit')):
        if type(value) is not int or not low <= value <= high:
            raise BridgeError(f'{name} must be an integer from {low} through {high}.')
    if coach_name is not None and (type(coach_name) is not str or not 1 <= len(coach_name) <= 256):
        raise BridgeError('coach_name must be a name returned by fm_get_save.')
    if expected_source_id is not None and (type(expected_source_id) is not str
            or len(expected_source_id) != 64
            or any(c not in '0123456789abcdef' for c in expected_source_id)):
        raise BridgeError('expected_source_id must be a lowercase SHA256 source ID.')
    if offset and expected_source_id is None:
        raise BridgeError('Continuation requires expected_source_id from the first page.')
    published = {}

    def seal():
        # Real Bridge._read_scope's post-yield process callback runs first.
        # No bridge/public/cache callbacks may follow the final byte fences.
        if bridge._current(session_id) != process:
            raise ValueError('Player expiry process lifetime changed')
        after_tables = bridge._player_layout(process)
        if after_tables != tables or bridge.plugin_identity != plugin:
            raise ValueError('Player expiry loaded plugin/build changed')
        after_read, after_save, after_identity = bridge._world_state(process, after_tables)
        if after_save != save or after_identity != identity or bridge.world_identity != identity:
            raise ValueError('Player expiry loaded save/date context changed')
        after_coach = bridge._select_coach(after_save, coach_name)
        after_team, after_human = prepared_tactics_source._team_and_human(after_read, base, after_coach)
        after_roster = source.roster(after_read, after_coach['team_address'])
        if (after_coach != coach or after_team != team or after_human != human
                or after_roster != roster):
            raise ValueError('Player expiry selected coach/TEAM/roster changed')
        if bridge._current(session_id) != process:
            raise ValueError('Player expiry process lifetime changed')
        if (bridge.session != session_id or bridge.process != process
                or bridge.plugin_identity != plugin or bridge.world_identity != identity
                or any(bridge.player_refs.get(ref) != binding for ref, binding in published.items())):
            raise ValueError('Player expiry final context/reference binding changed')
        read.verify()
        after_read.verify()

    try:
        with bridge.lock:
            with bridge._read_scope(session_id, final_verify=seal):
                process = bridge._current(session_id)
                tables = bridge._player_layout(process)
                plugin = deepcopy(bridge.plugin_identity)
                read, loaded, identity = bridge._world_state(process, tables)
                save, identity = deepcopy(loaded), deepcopy(identity)
                if bridge.world_identity != identity:
                    raise ValueError('Player expiry initial world binding differs')
                base = tables[0] - players.RVA[0]
                coach = deepcopy(bridge._select_coach(save, coach_name))
                team, human = prepared_tactics_source._team_and_human(read, base, coach)
                roster = source.roster(read, coach['team_address'])
                people = database.table(read, base, 'people')
                assessment_people.verify_native(read, base)
                rows, bindings = [], {}
                for slot, address in enumerate(roster):
                    row, binding = source.inspect_slot(read, base, tables, people, address, slot)
                    rows.append(row)
                    if binding is not None:
                        bindings[slot] = binding
                # Physical consumed-source bytes also bind raw flags and ownership,
                # including unreturned rows. Timestamps and fresh opaque refs do not.
                source_id = hashlib.sha256(repr((process, plugin, identity, coach,
                    expires_on_or_before, sorted(read.observed.items()))).encode('utf-8')).hexdigest()
                if expected_source_id is not None and source_id != expected_source_id:
                    raise ValueError('Player expiry source or selectors changed; restart paging')
                report = source.summarize(rows, expires_on_or_before, offset, limit, unclassified_limit)
                report['duplicate_slot_count'] = len([a for a in roster if a]) - len({a for a in roster if a})
                # Bind only returned supported rows; repeated slots share one ref.
                references = {}
                for row in report['players'] + report['unclassified_players']:
                    binding = bindings.get(row['roster_index'])
                    if binding is None:
                        continue
                    key = binding['address']
                    if key not in references:
                        if len(bridge.player_refs) >= 10000:
                            raise ValueError('Player reference cache capacity reached; attach again')
                        reference = secrets.token_urlsafe(12)
                        if reference in bridge.player_refs:
                            raise ValueError('Player expiry reference collision')
                        references[key] = reference
                        published[reference] = deepcopy(binding)
                        bridge.player_refs[reference] = deepcopy(binding)
                    row['player_ref'] = references[key]
                public_save = bridge._public_save(save)
                result = {'session_id': session_id, 'observed_at': datetime.now(timezone.utc).isoformat(),
                          'save': public_save, 'coach': coach['name'], 'club': coach['club'], 'team': team,
                          **report, 'query': {'expires_on_or_before': expires_on_or_before,
                              'offset': offset, 'limit': limit, 'unclassified_limit': unclassified_limit,
                              'sort_direction': 'expiry_ascending', 'cutoff_inclusive': True},
                          'complete_native_roster_scan': True,
                          'source_id': source_id,
                          'source': 'selected_team_stored_main_contract_dates',
                          'save_identity': 'native_binding_rechecked', 'scope': source.SCOPE,
                          'atomic': False, 'native_calls': False, 'saved_file_fallback': False}
            return result
    except (ValueError, IndexError, KeyError, TypeError, BridgeError, ReaderError, StructError) as exc:
        for reference in published:
            bridge.player_refs.pop(reference, None)
        raise BridgeError(f'Player expiry query rejected; no partial result returned: {exc}') from exc
