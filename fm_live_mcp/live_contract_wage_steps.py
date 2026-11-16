"""Canonical current-player adapter for independent stored main-wage scenarios."""
from copy import deepcopy
from datetime import datetime, timezone

from . import contract_wage_steps, database, players
from .bridge import BridgeError


def get_contract_wage_steps(bridge, session_id, player_ref):
    """Bind one regular/combined PLAYER and publish only after outer rechecks."""
    if type(player_ref) is not str or not player_ref:
        raise BridgeError('Select a nonempty player_ref.')
    binding = None
    try:
        with bridge.lock, bridge._read_scope(session_id):
            process = bridge._current(session_id)
            binding = bridge.player_refs.get(player_ref)
            if type(binding) is not dict:
                raise ValueError('Unknown or expired player reference. Find the player again')
            binding = deepcopy(binding)
            if binding.get('binding_kind') is not None or binding.get('record_kind') == 'virtual':
                raise ValueError('Virtual or unsupported player contract binding; no profile is expanded')
            tables = bridge._player_layout(process)
            plugin_identity = deepcopy(bridge.plugin_identity)
            if tables != binding['tables']:
                raise ValueError('Loaded player layout changed')
            read, loaded, world_identity = bridge._world_state(process, tables)
            save, world_identity = deepcopy(loaded), deepcopy(world_identity)
            if bridge.world_identity != world_identity:
                raise ValueError('Contract wage-step world binding differs')
            base, address = tables[0] - players.RVA[0], binding['address']
            # Reject other primary types before the rich reader could use a virtual cache.
            person = address + players.person_offset(read, address, tables)
            index = int.from_bytes(read(person + 8, 4), 'little')
            if 'database_index' in binding and binding['database_index'] != index:
                raise ValueError('Player database index changed')
            people = database.table(read, base, 'people')
            database.player_membership(read, base, people, index, address)
            record, identity = bridge._roster_player(read, address, tables, False, {})
            if identity != binding['identity']:
                raise ValueError('Player identity changed')
            native_identity = bridge._required_roster_identity(read, address, tables, record, identity)
            source = contract_wage_steps.decode(read, base, person)
            read.verify()

            current = bridge._current(session_id)
            if current != process:
                raise ValueError('Contract wage-step process lifetime changed')
            after_tables = bridge._player_layout(current)
            if after_tables != tables or bridge.plugin_identity != plugin_identity:
                raise ValueError('Contract wage-step loaded plugin/build changed')
            after_read, after_save, after_identity = bridge._world_state(current, after_tables)
            if (after_identity != world_identity or bridge.world_identity != world_identity
                    or after_save != save):
                raise ValueError('Contract wage-step loaded save/date context changed')
            # Bind the same PERSON again in the fresh canonical table, not just a cached ref.
            after_people = database.table(after_read, base, 'people')
            database.player_membership(after_read, base, after_people, index, address)
            after_record, after_native = bridge._roster_player(after_read, address, tables, False, {})
            if after_native != identity or after_record != record:
                raise ValueError('Contract wage-step player changed')
            if bridge.player_refs.get(player_ref) != binding:
                raise ValueError('Contract wage-step player reference binding changed')
            read.verify()
            after_read.verify()
            if bridge._current(session_id) != process:
                raise ValueError('Contract wage-step process lifetime changed')
            # Do not let mutation during the final lifetime callback escape consumed reads.
            read.verify()
            after_read.verify()
            if (bridge.player_refs.get(player_ref) != binding
                    or bridge.plugin_identity != plugin_identity
                    or bridge.world_identity != world_identity):
                raise ValueError('Contract wage-step outer binding changed during final check')
            return {
                'session_id': session_id, 'player_ref': player_ref,
                'observed_at': datetime.now(timezone.utc).isoformat(),
                'save': bridge._public_save(save),
                'player': {**{key: record[key] for key in ('name', 'display_name', 'birth_date', 'record_kind')
                            if key in record}, 'native_identity': native_identity},
                'contract_wage_steps': source,
                'save_identity': 'native_binding_rechecked',
                'snapshot': 'best-effort non-atomic read with process/build/save, canonical identity and consumed-byte rechecks',
                'atomic': False, 'saved_file_fallback': False,
            }
    except (ValueError, IndexError, KeyError, TypeError, BridgeError) as exc:
        if binding is not None:
            bridge.player_refs.pop(player_ref, None)
        raise BridgeError(f'Contract wage-step query rejected; no partial result returned: {exc}') from exc
