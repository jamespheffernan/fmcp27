"""Selected active HUMAN/TEAM/CLUB adapter for recorded annual stadium rent."""
from copy import deepcopy
from datetime import datetime, timezone
import struct

from . import club_stadium_rent, players, prepared_tactics_source, world
from .bridge import BridgeError

SCOPE = (
    'One selected active HUMAN coach\'s canonical CLUB and its recorded annual stadium rent '
    '(native Csry), in whole GBP per year when decoded. Missing finance is unavailable; '
    'typed base finance returns a distinct native literal zero. Concrete finance preserves '
    'signed cash; a negative amount is not interpreted as a refund or credit. '
    'Stored data is not refreshed. This is separate from weekly wages and transfer budgets; '
    'no payment timing, legal lease, future liability, outstanding debt, payroll or offer '
    'affordability is established. No native game calls, game writes or disk-save fallback.'
)


def _club_binding(read, base, coach):
    team, human = prepared_tactics_source._team_and_human(read, base, coach)
    address = world.pointer(read, coach['team_address'] + 0x30)
    club, identity = world.club(read, base, address)
    index = struct.unpack('<I', read(address + 8, 4))[0]
    binding = club_stadium_rent.ClubBinding(address, index, *identity)
    if club != coach['club'] or team['owner']['kind'] != 'club':
        raise ValueError('Annual-rent selected coach CLUB association changed')
    return team, human, club, binding


def get_club_stadium_rent(bridge, session_id, coach_name=None):
    """Read one current managed CLUB, with source and outer lifetime rechecks."""
    if type(session_id) is not str or not 1 <= len(session_id) <= 128:
        raise BridgeError('session_id must be a nonempty current attachment ID of at most 128 characters.')
    if coach_name is not None and (type(coach_name) is not str or not 1 <= len(coach_name) <= 256):
        raise BridgeError('coach_name must be a name returned by fm_get_save.')
    try:
        with bridge.lock, bridge._read_scope(session_id):
            process = bridge._current(session_id)
            tables = bridge._player_layout(process)
            plugin_identity = deepcopy(bridge.plugin_identity)
            read, loaded, world_identity = bridge._world_state(process, tables)
            save, world_identity = deepcopy(loaded), deepcopy(world_identity)
            if bridge.world_identity != world_identity:
                raise ValueError('Annual-rent world binding differs')
            base = tables[0] - players.RVA[0]
            coach = deepcopy(bridge._select_coach(save, coach_name))
            team, human, club, binding = _club_binding(read, base, coach)
            rent = club_stadium_rent.read_annual_rent(read, base, binding)
            read.verify()

            current = bridge._current(session_id)
            if current != process:
                raise ValueError('Annual-rent process lifetime changed')
            after_tables = bridge._player_layout(current)
            if after_tables != tables or bridge.plugin_identity != plugin_identity:
                raise ValueError('Annual-rent loaded plugin/build changed')
            after_read, after_save, after_identity = bridge._world_state(current, after_tables)
            if (after_identity != world_identity or bridge.world_identity != world_identity
                    or after_save != save):
                raise ValueError('Annual-rent loaded save/date context changed')
            after_coach = bridge._select_coach(after_save, coach_name)
            after_team, after_human, after_club, after_binding = _club_binding(after_read, base, after_coach)
            if (after_coach != coach or after_team != team or after_human != human
                    or after_club != club or after_binding != binding):
                raise ValueError('Annual-rent selected HUMAN/TEAM/CLUB owner changed')
            read.verify()
            after_read.verify()
            if bridge._current(session_id) != process:
                raise ValueError('Annual-rent process lifetime changed')
            # Recheck consumed source after the final process callback as well.
            read.verify()
            after_read.verify()
            if bridge.plugin_identity != plugin_identity or bridge.world_identity != world_identity:
                raise ValueError('Annual-rent outer binding changed during final check')
            return {
                'session_id': session_id, 'observed_at': datetime.now(timezone.utc).isoformat(),
                'save': bridge._public_save(save), 'coach': coach['name'], 'team': team,
                'club': {**club, 'database_index': binding.database_index, 'native_id': binding.native_id,
                         'random_id': None if binding.secondary_id == binding.native_id else binding.secondary_id},
                'annual_stadium_rent': rent, 'scope': SCOPE,
                'source': 'selected_managed_club_native_Csry_annual_rent',
                'save_identity': 'native_binding_rechecked', 'atomic': False,
                'snapshot': 'best-effort non-atomic read with process/build/save, selected HUMAN/TEAM/CLUB and consumed-byte rechecks',
                'saved_file_fallback': False,
            }
    except (ValueError, IndexError, KeyError, TypeError, BridgeError) as exc:
        raise BridgeError(f'Club stadium-rent query rejected; no partial result returned: {exc}') from exc
