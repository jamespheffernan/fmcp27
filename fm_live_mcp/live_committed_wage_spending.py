"""Current selected-coach binding for host-recomputed native wage commitments."""
from copy import deepcopy
from dataclasses import asdict
from datetime import datetime, timezone
import struct

from . import committed_wage_reduction as scope, committed_wage_total as total
from . import players, prepared_tactics_source, wages, world
from .bridge import BridgeError

SCOPE = (
    'One selected active HUMAN coach\'s canonical club. Payroll is explicitly recomputed '
    'from current retained native inputs in owned memory, then native committed-wage common '
    'arithmetic is evaluated on those same inputs. Amounts use native whole GBP per week; '
    'signed32 arithmetic is preserved. The original game-thread/HUMAN decision to refresh '
    'is not entered or simulated, and no cached payroll is presented as freshly computed. '
    'Unknown monetary branches reject the whole query. The native commitment definition '
    'does not establish a complete future liability schedule, every staff/bonus/tax cost, '
    'cash paid, offer activation, remaining budget or affordability. No native game calls, '
    'game writes, UI activity or disk-save fallback. Reads are non-atomic.'
)


def _selected(read, base, coach):
    team, human = prepared_tactics_source._team_and_human(read, base, coach)
    club = world.pointer(read, coach['team_address']+0x30)
    record, _ = world.club(read, base, club)
    identity = (club, *struct.unpack('<III', read(club+8, 12)))
    if record != coach['club'] or team['owner']['kind'] != 'club':
        raise ValueError('Committed-wage selected coach club changed')
    return team, human, record, identity


def get_club_committed_wage_spending(bridge, session_id, coach_name=None):
    if type(session_id) is not str or not 1 <= len(session_id) <= 128:
        raise BridgeError('session_id must be a current attachment ID of at most 128 characters.')
    if coach_name is not None and (type(coach_name) is not str or not 1 <= len(coach_name) <= 256):
        raise BridgeError('coach_name must be a name returned by fm_get_save.')
    try:
        with bridge.lock, bridge._read_scope(session_id):
            process = bridge._current(session_id)
            tables = bridge._player_layout(process)
            plugin = deepcopy(bridge.plugin_identity)
            base = tables[0]-players.RVA[0]
            read, save, identity = bridge._world_state(process, tables)
            save, identity = deepcopy(save), deepcopy(identity)
            if bridge.world_identity != identity:
                raise ValueError('Committed-wage initial world binding changed')
            coach = deepcopy(bridge._select_coach(save, coach_name))
            team, human, club, club_identity = _selected(read, base, coach)
            currency = wages.base_currency(read, base)
            contexts = [read]

            def lifetime():
                current = bridge._current(session_id)
                if current != process:
                    raise ValueError('Committed-wage process lifetime changed')
                layout = bridge._player_layout(current)
                if layout != tables or bridge.plugin_identity != plugin:
                    raise ValueError('Committed-wage loaded plugin changed')
                current_read, current_save, current_identity = bridge._world_state(current, layout)
                contexts.append(current_read)
                if (current_identity != identity or bridge.world_identity != identity or current_save != save):
                    raise ValueError('Committed-wage loaded career/date changed')
                current_coach = bridge._select_coach(current_save, coach_name)
                if current_coach != coach or _selected(current_read, base, current_coach) != (team, human, club, club_identity):
                    raise ValueError('Committed-wage selected HUMAN/TEAM/CLUB changed')
                if bridge._current(session_id) != process:
                    raise ValueError('Committed-wage final process lifetime changed')
                for context in contexts:
                    context.verify()
                if bridge.plugin_identity != plugin or bridge.world_identity != identity:
                    raise ValueError('Committed-wage outer binding changed')
                values = asdict(current)
                return scope.FinancialLifetime(tuple(values[k] for k in (
                    'pid', 'executable', 'started', 'version', 'bundle_id', 'executable_stamp')),
                    tuple(plugin[0]), plugin[1], base, identity, save['save_count'], save['current_date'], club_identity)

            # Every adapter callback precedes the total's final VM/source byte
            # checks. No later callback can invalidate a previously checked VM.
            result = total.calculate(lambda a,n:bridge._read_memory(process, a,n), base,
                                     plugin[0], club=club_identity[0], lifetime=lifetime)
            for context in contexts:
                context.verify()

            def amount(value):
                return dict(state='recomputed', amount=value, currency=currency, period='week')

            return {
                'session_id': session_id, 'observed_at': datetime.now(timezone.utc).isoformat(),
                'save': bridge._public_save(save), 'coach': coach['name'], 'team': team,
                'club': {**club, 'database_index': club_identity[1], 'native_id': club_identity[2],
                         'random_id': None if club_identity[3] == club_identity[2] else club_identity[3]},
                'current_wage_spending': amount(result.payroll_814),
                'committed_wage_spending': amount(result.committed_signed32),
                'basis': result.basis, 'native_refresh_admission': result.native_refresh_admission,
                'source': 'current_retained_native_wage_inputs_host_recomputed',
                'game_writes': False, 'native_game_functions_executed': False,
                'save_identity': 'native_binding_rechecked', 'atomic': False,
                'saved_file_fallback': False, 'scope': SCOPE,
            }
    except (ValueError, IndexError, KeyError, TypeError, BridgeError) as error:
        raise BridgeError(f'Club committed-wage query rejected; no partial result returned: {error}') from error
