"""Private explicit-reference transport qualification for requirement26.

Production composes source.project into the existing UCL registration tool.
This standalone transport remains unregistered.
"""
from copy import deepcopy
from datetime import datetime, timezone

from . import database, players, prepared_tactics_source
from . import ucl_registration as references, ucl_requirement26_projection as source
from .bridge import BridgeError

SCOPE = ('Current native UCL requirement26 only for explicit existing player references and a stored '
         'UCL fixture on a later calendar date. Each goalkeeper registration prerequisite binds its '
         'own current CLUB/TEAM/competition/runtime/rule separately from the target fixture UCL rule. '
         'The aggregate counts qualifying stored occurrences in native order, including duplicates. '
         'Medical records, no record, checked empty and unavailable remain distinct. Current-source '
         'false is not fixture exclusion; true is not medical clearance, registration submission or '
         'complete fixture eligibility. No current XI/bench is established. Future application '
         'depends on unchanged applicable registration, medical and rule inputs. No native game '
         'calls, writes, generated profiles, UI, refresh or saved-file fallback.')


def _project(bridge, read, base, tables, save, coach_name, fixture_binding, player_bindings, fixture_ref):
    coach = deepcopy(bridge._select_coach(save, coach_name))
    team, human = prepared_tactics_source._team_and_human(read, base, coach)
    decoded, fixture_date = references._fixture(read, base, tables, fixture_binding)
    people = database.table(read, base, 'people')
    identities, subjects = {}, []
    for ref, binding in player_bindings.items():
        person, identity = references._person(read, base, tables, people, binding)
        identities[ref] = (person, deepcopy(identity))
        subjects.append((ref, binding['address'], identity['record_kind']))
    result = source.project(read, base, coach, fixture_binding['address'], decoded, save['current_date'], subjects)
    if [row['player_ref'] for row in result['players']] != list(player_bindings):
        raise ValueError('Requirement26 explicit population coverage changed')
    rows = [dict(**row, **identities[row['player_ref']][1], loan_state='not_evaluated')
            for row in result['players']]
    fixture = dict(fixture_ref=fixture_ref, date=fixture_date, record_kind=decoded['kind'] + '_record',
                   competition=decoded['competition'],
                   home_team=None if decoded['team_ids'][0] is None else dict(
                       database_index=decoded['team_ids'][0][0], native_id=decoded['team_ids'][0][1]),
                   away_team=None if decoded['team_ids'][1] is None else dict(
                       database_index=decoded['team_ids'][1][0], native_id=decoded['team_ids'][1][1]))
    return dict(coach=coach, team=team, human=human, fixture=fixture, identities=identities,
                rows=rows, fixture_context=result['fixture_context'], aggregate=result['aggregate'],
                current_club_rule_sources=result['current_club_rule_sources'])


def get_player_ucl_requirement26(bridge, session_id, fixture_ref, player_refs, coach_name=None):
    """Rebind all physical sources, including the full native aggregate, before publication."""
    references._validate(player_refs, fixture_ref, coach_name)
    state = {}

    def seal():
        process, tables = state['process'], state['tables']
        if bridge._current(session_id) != process:
            raise ValueError('Requirement26 process lifetime changed')
        current_tables = bridge._player_layout(process)
        if current_tables != tables or bridge.plugin_identity != state['plugin']:
            raise ValueError('Requirement26 loaded build changed')
        fresh_read, fresh_save, fresh_world = bridge._world_state(process, tables)
        if (fresh_save != state['save'] or fresh_world != state['world']
                or bridge.world_identity != state['world']):
            raise ValueError('Requirement26 save/date/world changed')
        if (bridge.fixture_refs.get(fixture_ref) != state['fixture_binding']
                or any(bridge.player_refs.get(ref) != binding for ref, binding in state['bindings'].items())):
            raise ValueError('Requirement26 root reference binding changed')
        fresh = _project(bridge, fresh_read, state['base'], tables, fresh_save, coach_name,
                         state['fixture_binding'], state['bindings'], fixture_ref)
        if fresh != state['projected']:
            raise ValueError('Requirement26 owner/person/fixture/current-club-rule/medical aggregate changed')
        # No callback follows this one. Both complete journals are physically
        # verified after process/session/cache checks, including every GK club.
        if bridge._current(session_id) != process:
            raise ValueError('Requirement26 final process lifetime changed')
        if (bridge.session != session_id or bridge.process != process
                or bridge.plugin_identity != state['plugin'] or bridge.world_identity != state['world']
                or bridge.fixture_refs.get(fixture_ref) != state['fixture_binding']
                or any(bridge.player_refs.get(ref) != binding for ref, binding in state['bindings'].items())):
            raise ValueError('Requirement26 final context/reference binding changed')
        state['read'].verify()
        fresh_read.verify()

    try:
        with bridge.lock, bridge._read_scope(session_id, final_verify=seal):
            process = bridge._current(session_id)
            tables = bridge._player_layout(process)
            plugin = deepcopy(bridge.plugin_identity)
            read, loaded, world_identity = bridge._world_state(process, tables)
            save, world_identity = deepcopy(loaded), deepcopy(world_identity)
            if bridge.world_identity != world_identity:
                raise ValueError('Requirement26 initial world differs')
            fixture_binding = deepcopy(bridge.fixture_refs.get(fixture_ref))
            bindings = {ref: deepcopy(bridge.player_refs.get(ref)) for ref in player_refs}
            base = tables[0] - players.RVA[0]
            projected = _project(bridge, read, base, tables, save, coach_name,
                                 fixture_binding, bindings, fixture_ref)
            public_save = deepcopy(bridge._public_save(save))
            state.update(process=process, tables=tables, plugin=plugin, read=read, save=save,
                         world=world_identity, fixture_binding=fixture_binding, bindings=bindings,
                         base=base, projected=projected)
        return dict(session_id=session_id, observed_at=datetime.now(timezone.utc).isoformat(),
                    save=public_save, coach=projected['coach']['name'], club=projected['coach']['club'],
                    team=projected['team'], fixture=projected['fixture'],
                    fixture_context=projected['fixture_context'], aggregate=projected['aggregate'],
                    current_club_rule_sources=projected['current_club_rule_sources'],
                    players=projected['rows'], count=len(projected['rows']),
                    unique_person_count=len({v[0] for v in projected['identities'].values()}),
                    population_scope='explicit_existing_player_refs', current_selection_verified=False,
                    medical_clearance_evaluated=False, full_eligibility_evaluated=False,
                    atomic=False, saved_file_fallback=False, scope=SCOPE)
    except (ValueError, IndexError, KeyError, TypeError, BridgeError) as exc:
        raise BridgeError(f'UCL requirement26 query rejected; no partial result returned: {exc}') from exc
