"""Explicit-ref, fixture-bound current UCL registration inputs; no clearance.

The adapter never discovers a population or opens an edit session. It accepts
root-issued refs, including canonical unsupported classes as unknown rows.
"""
from copy import deepcopy
from datetime import date, datetime, timedelta, timezone

from . import assessment_people, database, fixtures, players, prepared_tactics_source
from . import fixture_eligibility_evidence as evidence, player_fixture_suspensions as suspensions
from . import ucl_registration_source as source, ucl_requirement26_projection as requirement26_source
from . import virtual_identity, world
from .bridge import BridgeError

SCOPE = ('Current native registered-to-play(mode1) and the supported UCL requirement14 '
         'age/club-history exemption for explicit canonical player references and a stored '
         'UCL fixture on a later calendar date. No current XI/bench, submitted population, '
         'past-kickoff state or complete fixture eligibility is established. Requirement26 '
         'is a separate conditional native clause over current registration, medical and '
         'current-club rule inputs; a positive first requirement14 skips that clause. '
         'Its shared aggregate counts stored occurrences in native order, including duplicates. '
         'A false clause never establishes exclusion; a true clause is not medical clearance. '
         'With include_fixture_suspension, each row also carries the separate ordinary mode0 '
         'suspension predicate for that fixture and a fixture_eligibility_evidence reading '
         'that keeps registration, suspension and unknown axes apart; neither clears or '
         'excludes a player. '
         'Future application depends on the currently read inputs remaining applicable. '
         'No native game calls, UI, writes, refresh, generation or saved-file fallback.')


def _validate(player_refs, fixture_ref, coach_name, include_suspension=False):
    if type(include_suspension) is not bool:
        raise BridgeError('include_fixture_suspension must be a boolean.')
    if (type(player_refs) is not list or not 1 <= len(player_refs) <= 32
            or any(type(ref) is not str or not 1 <= len(ref) <= 256 for ref in player_refs)
            or len(set(player_refs)) != len(player_refs)):
        raise BridgeError('Supply 1 through 32 distinct existing player references.')
    if type(fixture_ref) is not str or not 1 <= len(fixture_ref) <= 256:
        raise BridgeError('Supply one explicit future fixture reference.')
    if coach_name is not None and (type(coach_name) is not str or not 1 <= len(coach_name) <= 256):
        raise BridgeError('coach_name must be a name returned by fm_get_save.')


def _fixture(read, base, tables, saved):
    if (type(saved) is not dict or type(saved.get('tables')) is not tuple or saved['tables'] != tables
            or any(type(saved.get(key)) is not int for key in ('year', 'day', 'group', 'slot'))
            or not 1850 <= saved['year'] <= 2200 or not 1 <= saved['day'] <= 366
            or saved['group'] < 0 or saved['slot'] < 0 or type(saved.get('address')) is not int
            or saved['address'] < 4096 or saved['address'] % 8 or saved['address'] >= 1 << 64):
        raise ValueError('Unknown, expired or mismatched fixture reference')
    _, years, inventory = fixtures.catalog(read, base)
    if saved['catalog_identity'] != inventory or saved['year'] not in years:
        raise ValueError('Resident fixture inventory changed')
    year = years[saved['year']]
    fixture_date = date(saved['year'], 1, 1)+timedelta(days=saved['day']-1)
    if (fixture_date.year != saved['year'] or saved['group'] >= len(year['groups'])
            or saved['group_address'] != year['groups'][saved['group']]):
        raise ValueError('Fixture canonical calendar/group membership changed')
    entries, route = fixtures.bucket(read, year, saved['day'], saved['group'])
    if (saved['route'] != route or saved['slot'] >= len(entries)
            or entries[saved['slot']] != saved['address']):
        raise ValueError('Fixture canonical bucket membership changed')
    decoded = fixtures.record(read, base, saved['address'], saved['year'], saved['day'], {})
    if decoded['identity'] != saved['identity']:
        raise ValueError('Fixture canonical identity changed')
    return decoded, fixture_date.isoformat()


def _person(read, base, tables, people, binding):
    if (type(binding) is not dict or binding.get('tables') != tables or type(binding.get('tables')) is not tuple
            or ('world_bound' in binding and type(binding['world_bound']) is not bool)):
        raise ValueError('Unknown or expired player reference')
    primary = assessment_people._address(binding.get('address'))
    if world.pointer(read, primary) == base+world.TYPES['virtual_player'][0]:
        compact = virtual_identity.inspect(read, primary, tables)
        if (binding.get('binding_kind') != virtual_identity.BINDING_KIND
                or type(binding.get('identity')) is not tuple or binding['identity'] != compact['identity']
                or any(type(v) is not int for v in binding['identity'][1:])
                or binding.get('record_kind', 'virtual') != 'virtual'
                or ('database_index' in binding and (type(binding['database_index']) is not int
                    or binding['database_index'] != compact['native_identity']['database_index']))):
            raise ValueError('Compact player reference identity changed')
        return primary+0x20, dict(native_identity=compact['native_identity'], record_kind='virtual',
                                 display_name=None)
    return assessment_people.bound_player(read, base, tables, people, binding)


def _project(bridge, read, base, tables, save, coach_name, saved_fixture, bindings, fixture_ref,
             include_suspension=False):
    coach = deepcopy(bridge._select_coach(save, coach_name))
    team, human = prepared_tactics_source._team_and_human(read, base, coach)
    decoded, fixture_date = _fixture(read, base, tables, saved_fixture)
    if fixture_date <= save['current_date']:
        context = dict(state='unavailable', reason='fixture_not_on_later_calendar_date',
                       fixture_phase_evaluated=False, full_eligibility_evaluated=False)
        native_binding = None
    else:
        context, native_binding = source.fixture_context(
            read, base, coach, saved_fixture['address'], decoded, save['current_date'])
    context.update(fixture_ref=fixture_ref, fixture_date=fixture_date, current_read_date=save['current_date'])
    people = database.table(read, base, 'people')
    rows, identities, projected, subjects, bans = [], {}, {}, [], {}
    ban_context = ban_binding = None
    if include_suspension:
        ban_context, ban_binding = suspensions.context(read, base, saved_fixture['address'], decoded,
                                                       save['current_date'])
        ban_context.update(fixture_ref=fixture_ref, as_of_date=save['current_date'])
    for ref, binding in bindings.items():
        person, identity = _person(read, base, tables, people, binding)
        identities[ref] = (person, deepcopy(identity))
        kind, primary = identity['record_kind'], binding['address']
        key = (person, kind)
        if key not in projected:
            registered = source.registered(read, primary, kind, native_binding)
            exemption = source.requirement14(read, primary, kind, native_binding)
            first = exemption['native_requirement14'] is True
            requirement26 = dict(state='not_evaluated_first_requirement14_sufficient' if first else 'unavailable',
                                 native_result=None, reason='first_native_requirement14_sufficient' if first
                                 else 'native_requirement26_not_supported')
            covered = registered['native_predicate_result'] is True or first
            projected[key] = dict(registration=registered, requirement14=exemption, requirement26=requirement26,
                registration_covered_by_current_sources=True if covered else None,
                full_eligibility_evaluated=False)
            if include_suspension:
                bans[key] = suspensions.project(read, base, primary, kind, ban_binding)
            if not first:
                subjects.append((ref, primary, kind))
        rows.append((ref, identity, key))
    clause = dict(fixture_context=dict(state='not_evaluated',
                  reason='first_native_requirement14_sufficient_for_all_requested_people'),
                  aggregate=None, players=[], current_club_rule_sources=[], full_eligibility_evaluated=False)
    if subjects:
        if native_binding is None:
            clause['fixture_context'] = dict(context)
            clause['players'] = [dict(player_ref=ref, state='unavailable', native_requirement26=None,
                reason='ucl_fixture_registration_context_unavailable')for ref, _, _ in subjects]
        else:
            clause = requirement26_source.project(read, base, coach, saved_fixture['address'], decoded,
                                           save['current_date'], subjects)
        if [row['player_ref']for row in clause['players']] != [ref for ref, _, _ in subjects]:
            raise ValueError('UCL requirement26 explicit population coverage changed')
        for row in clause['players']:
            person, identity = identities[row['player_ref']]
            value = row['native_requirement26']
            if value is not None and type(value) is not bool:
                raise ValueError('UCL requirement26 native predicate type changed')
            target = projected[(person, identity['record_kind'])]
            target['requirement26'] = dict(
                **{name: deepcopy(value)for name, value in row.items()
                   if name not in ('player_ref', 'native_requirement26')}, native_result=value)
            if value is True:
                target['registration_covered_by_current_sources'] = True
    for key, target in projected.items() if include_suspension else ():
        target['fixture_suspension'] = deepcopy(bans[key])
        target['fixture_eligibility_evidence'] = evidence.combine(
            target['registration'], target['requirement14'], target['requirement26'],
            target['registration_covered_by_current_sources'], bans[key])
    rows = [dict(player_ref=ref, **identity, loan_state='not_evaluated', **deepcopy(projected[key]))
            for ref, identity, key in rows]
    public_fixture = dict(fixture_ref=fixture_ref, date=fixture_date, record_kind=decoded['kind']+'_record',
                          competition=decoded['competition'],
                          home_team=None if decoded['team_ids'][0] is None else
                              dict(database_index=decoded['team_ids'][0][0], native_id=decoded['team_ids'][0][1]),
                          away_team=None if decoded['team_ids'][1] is None else
                              dict(database_index=decoded['team_ids'][1][0], native_id=decoded['team_ids'][1][1]))
    return dict(coach=coach, team=team, human=human, fixture=public_fixture,
                context=context, native_binding=native_binding, rows=rows, identities=identities,
                requirement26_context=clause['fixture_context'], requirement26_aggregate=clause['aggregate'],
                requirement26_current_club_rule_sources=clause['current_club_rule_sources'],
                suspension_context=ban_context, suspension_binding=ban_binding)


def get_player_ucl_registration(bridge, session_id, fixture_ref, player_refs, coach_name=None,
                                include_fixture_suspension=False):
    """Read and rebind the entire explicit batch before the final physical fence."""
    _validate(player_refs, fixture_ref, coach_name, include_fixture_suspension)
    state = {}

    def seal():
        # Canonical Bridge._read_scope invokes its own final process callback
        # before this hook. All callbacks/rebindings below precede both fences.
        process, tables = state['process'], state['tables']
        current = bridge._current(session_id)
        if current != process:
            raise ValueError('UCL registration process lifetime changed')
        after_tables = bridge._player_layout(current)
        if after_tables != tables or bridge.plugin_identity != state['plugin']:
            raise ValueError('UCL registration loaded plugin/build changed')
        after_read, after_save, after_world = bridge._world_state(current, after_tables)
        if (after_save != state['save'] or after_world != state['world']
                or bridge.world_identity != state['world']):
            raise ValueError('UCL registration loaded save/date/world changed')
        if (bridge.fixture_refs.get(fixture_ref) != state['fixture_binding']
                or any(bridge.player_refs.get(ref) != binding for ref, binding in state['bindings'].items())):
            raise ValueError('UCL registration root reference binding changed')
        fresh = _project(bridge, after_read, state['base'], tables, after_save, coach_name,
                         state['fixture_binding'], state['bindings'], fixture_ref, include_fixture_suspension)
        if fresh != state['projected']:
            raise ValueError('UCL registration fixture/owner/person/phase result changed')
        if bridge._current(session_id) != process:
            raise ValueError('UCL registration final process lifetime changed')
        if (bridge.session != session_id or bridge.process != process
                or bridge.plugin_identity != state['plugin'] or bridge.world_identity != state['world']
                or bridge.fixture_refs.get(fixture_ref) != state['fixture_binding']
                or any(bridge.player_refs.get(ref) != binding for ref, binding in state['bindings'].items())):
            raise ValueError('UCL registration final context/reference binding changed')
        state['read'].verify()
        after_read.verify()

    try:
        with bridge.lock, bridge._read_scope(session_id, final_verify=seal):
            process = bridge._current(session_id)
            tables = bridge._player_layout(process)
            plugin = deepcopy(bridge.plugin_identity)
            read, loaded, identity = bridge._world_state(process, tables)
            save, identity = deepcopy(loaded), deepcopy(identity)
            if bridge.world_identity != identity:
                raise ValueError('UCL registration world binding differs')
            saved_fixture = deepcopy(bridge.fixture_refs.get(fixture_ref))
            bindings = {ref: deepcopy(bridge.player_refs.get(ref)) for ref in player_refs}
            base = tables[0]-players.RVA[0]
            projected = _project(bridge, read, base, tables, save, coach_name, saved_fixture, bindings, fixture_ref,
                                 include_fixture_suspension)
            public_save = deepcopy(bridge._public_save(save))
            state.update(process=process, tables=tables, plugin=plugin, read=read, save=save, world=identity,
                         fixture_binding=saved_fixture, bindings=bindings, base=base, projected=projected)
        rows = projected['rows']
        optional = dict(fixture_suspension_context=projected['suspension_context'],
                        fixture_suspension_scope=suspensions.SCOPE,
                        fixture_eligibility_scope=evidence.SCOPE) if include_fixture_suspension else {}
        return dict(session_id=session_id, observed_at=datetime.now(timezone.utc).isoformat(),
                    save=public_save, coach=projected['coach']['name'], club=projected['coach']['club'],
                    team=projected['team'], fixture=projected['fixture'], fixture_context=projected['context'],
                    requirement26_context=projected['requirement26_context'],
                    requirement26_aggregate=projected['requirement26_aggregate'],
                    requirement26_current_club_rule_sources=projected['requirement26_current_club_rule_sources'],
                    **optional,
                    players=rows, count=len(rows), unique_person_count=len(set(v[0] for v in projected['identities'].values())),
                    population_scope='explicit_existing_player_refs', current_selection_verified=False,
                    full_eligibility_evaluated=False, scope=SCOPE, atomic=False, saved_file_fallback=False)
    except (ValueError, IndexError, KeyError, TypeError, BridgeError) as exc:
        raise BridgeError(f'UCL registration query rejected; no partial result returned: {exc}') from exc
