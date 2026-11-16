"""Sealed selected-roster adapter for stored current-main-contract history."""
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import os
from pathlib import Path
import stat

from . import database, player_concern_history_source as history
from . import player_concern_history_templates_source as templates
from . import player_promise_inventory_source as promises, promise_kind_definitions as promise_kinds
from . import players, prepared_tactics_source, world
from .bridge import BridgeError
from .reader import ReaderError
from .live_international_duty import _bound_person, _public
from ._os_compat import change_time_ns

ENGLISH_RESOURCE_SHA256 = templates.ENGLISH_RESOURCE_SHA256
ENGLISH_RESOURCE_BYTES = 155367178
ENGLISH_RELATIVE_PATH = 'Resources/data/game_simulation/templates/user_folder/languages/example.ltf'
SCOPE = (
    'Requested fresh references on the selected active HUMAN/TEAM native roster. '
    'This roster can include loaned-out players and is not the whole club. '
    + history.SCOPE
)


def _file_identity(value):
    return (value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns, change_time_ns(value))


def _english_binding(plugin_identity):
    """Read an existing pinned resource; never create or materialize English."""
    # Bridge._player_layout stores (disk stat stamp, verified Mach-O UUID).
    if (type(plugin_identity) is not tuple or len(plugin_identity) != 2
            or type(plugin_identity[0]) is not tuple or len(plugin_identity[0]) != 5
            or type(plugin_identity[0][0]) is not str
            or any(type(value) is not int for value in plugin_identity[0][1:])
            or type(plugin_identity[1]) is not bytes or len(plugin_identity[1]) != 16):
        raise ValueError('Verified game-plugin path required for English templates')
    plugin = Path(plugin_identity[0][0])
    if not plugin.is_absolute():
        raise ValueError('Verified game-plugin path must be absolute')
    path = (plugin.parent.parent / ENGLISH_RELATIVE_PATH).resolve(strict=True)
    with path.open('rb') as stream:
        before = os.fstat(stream.fileno())
        if not stat.S_ISREG(before.st_mode) or before.st_size != ENGLISH_RESOURCE_BYTES:
            raise ValueError('Pinned English resource has an unsupported file type or size')
        digest = hashlib.file_digest(stream, 'sha256').hexdigest()
        after = os.fstat(stream.fileno())
    if (_file_identity(before) != _file_identity(after)
            or _file_identity(path.stat()) != _file_identity(after)):
        raise ValueError('English resource changed while being read')
    if digest != ENGLISH_RESOURCE_SHA256:
        raise ValueError('Pinned English resource digest changed')
    return {'path': str(path), 'identity': _file_identity(after), 'sha256': digest}


def _context_operand(read, base, primary, result):
    if result.get('contract_context') != 'owned_main_FULL_CONTRACT_matches_current_TEAM_CLUB':
        return
    team = players.u64(read(primary + 0x128, 8))
    club = players.u64(read(team + 0x30, 8))
    world.typed(read, base, club, 'club')
    # Original CB86DC consumes this byte. Preserve its literal operand without
    # assigning a role/status; all byte values retain this main-context match.
    if len(read(club + 0xba, 1)) != 1:
        raise ValueError('Incomplete concern current-context operational operand')


def _promise_inventory(read, base, subject, owner_identity, manager_person, english):
    """Decode one player's linked promise vector; templates only when English is bound."""
    _, binding, person, kind, _, _ = subject
    result = promises.inspect(read, base, binding['address'], kind, selected_view_person=manager_person)
    if result['owner'] is not None and result['owner']['native_identity'] != owner_identity:
        raise ValueError('Promise inventory canonical owner differs from the reference')
    for entry in result['promises'] or ():
        if english is None:
            entry['kind_definition'] = None
            entry['kind_name_state'] = 'definition_not_requested'
            continue
        definition = promise_kinds.inspect(read, base, entry['native_kind'])
        if definition['english_resource_sha256'] != english['sha256']:
            raise ValueError('Promise definition resource differs from the bound English resource')
        entry['kind_definition'] = definition
        entry['kind_name_state'] = definition['state']
    return result


def get_player_concern_history(bridge, session_id, player_refs, coach_name=None, *,
                               include_templates=False, include_promises=False):
    if type(session_id) is not str or not 1 <= len(session_id) <= 128:
        raise BridgeError('session_id must be a current attachment ID of at most 128 characters.')
    if (type(player_refs) is not list or not 1 <= len(player_refs) <= 100
            or any(type(ref) is not str or not ref for ref in player_refs)
            or len(set(player_refs)) != len(player_refs)):
        raise BridgeError('Supply 1 through 100 distinct nonempty player references.')
    if coach_name is not None and (type(coach_name) is not str or not 1 <= len(coach_name) <= 256):
        raise BridgeError('coach_name must be a name returned by fm_get_save.')
    if type(include_templates) is not bool:
        raise BridgeError('include_templates must be a Boolean.')
    if type(include_promises) is not bool:
        raise BridgeError('include_promises must be a Boolean.')

    def seal():
        # The real156 scope performs its hidden post-yield lifetime callback
        # before this hook. All remaining callbacks precede both byte journals.
        current = bridge._current(session_id)
        if current != process:
            raise ValueError('Concern-history process lifetime changed')
        after_tables = bridge._player_layout(current)
        if after_tables != tables or bridge.plugin_identity != plugin_identity:
            raise ValueError('Concern-history loaded plugin/build changed')
        after_read, after_save, after_identity = bridge._world_state(current, after_tables)
        if (after_identity != world_identity or bridge.world_identity != world_identity
                or after_save != save):
            raise ValueError('Concern-history loaded save/date context changed')
        after_coach = bridge._select_coach(after_save, coach_name)
        after_team, after_human = prepared_tactics_source._team_and_human(after_read, base, after_coach)
        after_roster = world.vector(after_read, after_coach['team_address'] + 0x38, 256)
        if (after_coach != coach or after_team != team or after_human != human
                or after_roster != roster):
            raise ValueError('Concern-history selected coach/TEAM/roster changed')
        if bridge._current(session_id) != process:
            raise ValueError('Concern-history final process lifetime changed')
        if include_templates and _english_binding(plugin_identity) != english:
            raise ValueError('Concern-history English resource binding changed')
        if (bridge.session != session_id or bridge.process != process
                or bridge.plugin_identity != plugin_identity or bridge.world_identity != world_identity
                or any(bridge.player_refs.get(ref) != binding for ref, binding in bindings.items())):
            raise ValueError('Concern-history final context/reference binding changed')
        read.verify()
        after_read.verify()

    try:
        with bridge.lock, bridge._read_scope(session_id, final_verify=seal):
            process = bridge._current(session_id)
            tables = bridge._player_layout(process)
            plugin_identity = deepcopy(bridge.plugin_identity)
            read, loaded, identity = bridge._world_state(process, tables)
            save, world_identity = deepcopy(loaded), deepcopy(identity)
            if bridge.world_identity != world_identity:
                raise ValueError('Concern-history initial world binding differs')
            base = tables[0] - players.RVA[0]
            # Journal the runtime header/RTTI too: _player_layout's direct
            # transport reads alone would escape a later callback mutation.
            if players.verify_runtime(read, base, plugin_identity[1]) != tables:
                raise ValueError('Concern-history journaled runtime layout changed')
            coach = deepcopy(bridge._select_coach(save, coach_name))
            team, human = prepared_tactics_source._team_and_human(read, base, coach)
            roster = world.vector(read, coach['team_address'] + 0x38, 256)
            people = database.table(read, base, 'people')
            bindings, subjects = {}, []
            for reference in player_refs:
                binding = bridge.player_refs.get(reference)
                if type(binding) is not dict:
                    raise ValueError('Unknown or expired player reference')
                binding = deepcopy(binding)
                if binding.get('world_bound') is not True:
                    raise ValueError('Player reference needs a fresh loaded-career roster binding')
                if binding.get('address') not in roster:
                    raise ValueError('Player reference is outside the selected native TEAM roster')
                person, kind, name, display = _bound_person(read, base, tables, people, binding)
                bindings[reference] = binding
                subjects.append((reference, binding, person, kind, name, display))
            english = _english_binding(plugin_identity) if include_templates else None
            rows = []
            for reference, binding, person, kind, name, display in subjects:
                if include_templates:
                    result = templates.inspect(read, base, binding['address'], kind,
                        english_resource_sha256=english['sha256'], include_stored_name=kind == 'actual')
                else:
                    result = history.inspect(read, base, binding['address'], kind, include_stored_name=kind == 'actual')
                if result['owner'] is not None and result['owner']['native_identity'] != _public(person):
                    raise ValueError('Concern-history canonical owner differs from the reference')
                _context_operand(read, base, binding['address'], result)
                promise_inventory = (_promise_inventory(read, base, (reference, binding, person, kind, name, display),
                    _public(person), coach['manager_address']+0x548, english) if include_promises else None)
                rows.append({'player_ref': reference, 'native_identity': _public(person),
                    'record_kind': kind, 'name': name, 'display_name': display,
                    'name_state': 'unavailable_without_generated_profile' if kind == 'virtual' else 'stored_native_name_fields',
                    'concern_history': result, **({'promise_inventory': promise_inventory} if include_promises else {})})
            result = {'session_id': session_id, 'observed_at': datetime.now(timezone.utc).isoformat(),
                'save': bridge._public_save(save), 'coach': coach['name'], 'club': coach['club'], 'team': team,
                'players': rows, 'count': len(rows), 'source': ('stored_current_main_contract_concern_history_and_player_promise_inventory'
                    if include_promises else 'stored_current_main_contract_concern_history'),
                'templates_requested': include_templates, 'promises_requested': include_promises,
                'english_resource_sha256': english['sha256'] if english else None,
                'scope': SCOPE + (' ' + templates.DESCRIPTION_SCOPE if include_templates else '')
                    + (' ' + promises.SCOPE if include_promises else ''),
                'atomic': False, 'saved_file_fallback': False, 'native_calls': False,
                'profile_expansion': False, 'current_unhappiness_evaluated': False, 'promise_fulfilment_evaluated': False,
                'promise_lifecycle_evaluated': False}
        return result
    except (ValueError, IndexError, KeyError, TypeError, OSError, ReaderError, BridgeError) as exc:
        raise BridgeError(f'Concern-history query rejected; no partial result returned: {exc}') from exc
