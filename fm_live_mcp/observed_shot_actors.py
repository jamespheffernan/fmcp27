"""Recover named attempts from a recorded match with an attested original-slot roster."""
from hashlib import sha256
import json

from .active_match_shot_timeline import project as project_shots
from .active_pass_network import _actor_map, _bound_identity, select_events


TABLE = 'named_shot_chances'
SHOT_FIELDS = ('event_id', 'side_index', 'period', 'expected_goals', 'outcome', 'body_part',
               'is_penalty', 'official_location', 'native_clock_start_raw', 'native_clock_end_raw')
COLUMNS = (*SHOT_FIELDS, 'shooter_person_native_id', 'shooter_name', 'actor_state')
# This immutable recording has independent native CBE actor-namespace and
# original-slot controls. Newly discovered databases need equivalent evidence.
ATTESTED_CAPTURES = {
    '8e8a4d436d01525f20730c53b5abeaf67d75f8a762413e6da9ceb090236de873'
}
SCOPE = ('Terminal recorded shot attempts with native primary actor identities. '
         'Own-goal markers are separate from attempts. An unresolved player remains null. '
         'Native clocks do not establish a displayed minute. A shot does not identify its supplier.')


def _raw(blob):
    data = bytes.fromhex(blob['hex'])
    if sha256(data).hexdigest() != blob['sha256']:
        raise ValueError('Recorded native shot source digest differs')
    return data


def project_named_chances(terminal, packet, stored_shots):
    raw = terminal['raw_source']
    bound = terminal['bound_playback']
    roster_bound = packet['bound']
    binding = packet['binding']
    roster = packet['actors']
    match_id = bound['official_match_unique_id']
    markers = terminal['period_split'].get('period_markers') or []
    if (not markers or markers[-1].get('next_stop_reason') != 'EndOfGame'
            or markers[-1].get('stop_time_slice') != bound['current_time_slice']
            or not all(_bound_identity(bound))
            or terminal['state'] != 'verified_terminal_resident_source' or terminal['verified_readset'] is not True
            or terminal['displayed_period'] != 'FullTime'
            or bound['current_time_slice'] != bound['buffered_max_time_slice']
            or not 0 < roster_bound['current_time_slice'] <= bound['current_time_slice']
            or _bound_identity(bound) != _bound_identity(roster_bound)
            or match_id != packet['source']['match_unique_id']
            or match_id != raw['match_unique_id'] or match_id != roster['official_match_unique_id']
            or raw['source_identity'][:2] != [binding['client'], binding['engine']]
            or raw['fixture_identity'] != packet['source']['fixture_identity']):
        raise ValueError('Shot and original-slot observations belong to different playthroughs')
    events = _raw(raw['events'])
    earlier_events = packet['source']['events']
    if not earlier_events or select_events(events, roster_bound['current_time_slice']) != earlier_events:
        raise ValueError('Terminal event history differs from the original-slot observation')
    people = _actor_map(roster)
    if any(p.get('identity_state') != 'canonical_PERSON_table_same_team_and_typed_stats'
           for p in people.values()):
        raise ValueError('Shot actor does not have a canonical player-stat identity')
    native = dict(raw, events=events, vectors=[_raw(v) for v in raw['vectors']])
    chances = project_shots(native, bound, period_split=terminal['period_split'])
    if chances['state'] != 'available':
        raise ValueError('Terminal shot counters do not reconcile')
    by_id = {s['event_id']:s for s in chances['shots']}
    if len(by_id) != len(chances['shots']) or len(by_id) != len(stored_shots):
        raise ValueError('Recorded and reconstructed shot populations differ')
    result = []
    for stored in stored_shots:
        event = by_id.pop(stored['event_id'], None)
        if event is None or any(event[k] != stored[k] for k in (*SHOT_FIELDS, 'native_actor_slot')):
            raise ValueError('Recorded shot differs from terminal native event')
        person = people.get((event['event_side_index'], event['native_actor_slot']))
        result.append({**{k:event[k] for k in SHOT_FIELDS},
                       'shooter_person_native_id': person['canonical_person_id'] if person else None,
                       'shooter_name': person.get('person_name') if person else None,
                       'actor_state': 'canonical_original_slot' if person else 'unresolved_original_slot'})
    return result


def derive_shot_actors(db, provenance):
    if provenance['capture_id'] not in ATTESTED_CAPTURES:
        return None
    documents = {key:json.loads(value) for key,value in db.execute(
        "SELECT source_id,document_json FROM source_documents WHERE source_id IN ('terminal','pass_actors')")}
    fields = ('event_id','side_index','period','expected_goals','outcome','body_part',
              'native_clock_start_raw','native_clock_end_raw','native_actor_slot')
    records = db.execute('SELECT '+','.join(fields)+
                         ",json_extract(record_json,'$.is_penalty'),json_extract(record_json,'$.official_location') "
                         'FROM shots ORDER BY event_id').fetchall()
    stored = [dict(zip((*fields,'is_penalty','official_location'),record)) for record in records]
    rows = project_named_chances(documents['terminal'], documents['pass_actors'], stored)
    return {'columns':list(COLUMNS), 'rows':rows, 'scope':SCOPE,
            'provenance':{'state':'verified_derived_view','source_kind':'recorded_terminal_and_original_roster',
                          'terminal_event_sha256':documents['terminal']['raw_source']['events']['sha256'],
                          'named_shots':sum(r['shooter_name'] is not None for r in rows),
                          'checked_shots':len(rows),'original_database_unchanged':True}}
