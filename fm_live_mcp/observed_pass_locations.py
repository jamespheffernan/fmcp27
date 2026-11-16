"""Optional, source-pinned virtual pass-map rows; never changes an observed DB.

A policy attests the native decoder source. Raw documents and every base event
must independently agree before the derived view becomes available.
"""
import hashlib
import json
import math
import struct

from .pass_field_position import project_event_location

TABLE = 'completed_pass_event_locations'
COLUMNS = ('event_id','side_index','team_native_id','sender_person_native_id','sender_name',
    'receiver_person_native_id','receiver_name','sender_slot','receiver_slot','start_tick','end_tick',
    'period','native_event_x','native_event_y','attacked_goal_positive_native_y',
    'attack_relative_longitudinal_coordinate','absolute_lateral_centerline_distance',
    'inside_native_pitch_extents','analytical_pitch_third','analytical_lateral_channel',
    'native_flags_word','source_id')
NATIVE_SHA256 = '774cacde63567fd3901c47719e7a6ed94cc3a0a62e9b94989dcac6b4890ec0e1'
POLICY_VERSION = 'native_pass_map_event_point_v1'
# Separate explicit optional attestation; an arbitrary newly captured DB does not
# acquire native field semantics merely by resembling the schema.
APPROVED_POLICIES = {
    '8e8a4d436d01525f20730c53b5abeaf67d75f8a762413e6da9ceb090236de873': {
        'version': POLICY_VERSION, 'native_plugin_sha256': NATIVE_SHA256,
        'raw_event_sha256': 'f6e4bfddc8d6e4ff3cfa2fa5af6642f8f2e6c88f6da6f3ad817983747c505ef8',
        'terminal_payload_sha256': '7447d77137aaf3c2083ea8dc42e1627128612be9207401198ce946e4da87eb22',
        'actor_payload_sha256': '32c0ff45810a8ba157eaa85a02bd53f9c76c213f2203f97f00413a02e66860a3',
        'terminal_sha256': '9ee6e05dd61b20ba3b4d0a1aa71e72825768f0ced6204889c003c5bb7ebc9a9c',
        'actor_document_sha256': '9e0c7e8691a70d75f7a4f639f83c4d03fd23c4d5f8e7d8b4f4b9b40b6705f558',
        'event_count': 1020, 'official_match_unique_id': 2341023333120,
        'proof': 'bfe6b65 / active-pass-locations-185; complete1020 event/actor/clock/point controls',
    },
}
SCOPE = ('Derived official native pass-map EVENT points for completed category7 events only, excluding mask8. '
         'Not proved ball-release, reception, intended destination or trajectory; physical units and human left/right unknown. '
         'Direction flag supplies attack-relative longitudinal coordinate. Thirds/channels are analytical equal bins. '
         'Exact source period containment uses start<=end<period_end; unresolved boundaries remain null. '
         'Not current roster, role, live state, official passing attempts/accuracy, or causal evidence.')


def derive_pass_locations(db, provenance, *, policy=None):
    policy = policy if policy is not None else APPROVED_POLICIES.get(provenance['capture_id'])
    if policy is None:
        return None
    if (not isinstance(policy,dict) or policy.get('version') != POLICY_VERSION
            or policy.get('native_plugin_sha256') != NATIVE_SHA256):
        raise ValueError('Unsupported observed pass-map native-source attestation')
    document = db.execute("SELECT sha256,document_json FROM source_documents WHERE source_id='terminal'").fetchone()
    if document is None or document[0] != provenance['source_document_hashes'].get('terminal') or document[0] != policy.get('terminal_sha256'):
        raise ValueError('Derived pass-map terminal provenance differs')
    terminal = json.loads(document[1])
    payload_hash=lambda value:hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()).hexdigest()
    if payload_hash(terminal)!=policy.get('terminal_payload_sha256'):
        raise ValueError('Derived pass-map terminal payload differs from attestation')
    source = terminal.get('raw_source',{})
    encoded = source.get('events',{})
    if not isinstance(encoded,dict) or not isinstance(encoded.get('hex'),str) or len(encoded['hex']) > 8192*56*2:
        raise ValueError('Derived pass-map raw event extent unsupported')
    try:raw = bytes.fromhex(encoded['hex'])
    except ValueError as error:raise ValueError('Derived pass-map event hex malformed') from error
    digest = hashlib.sha256(raw).hexdigest()
    if not raw or len(raw)%56 or digest != encoded.get('sha256') or digest != policy.get('raw_event_sha256'):
        raise ValueError('Derived pass-map raw event hash differs')
    fixture = db.execute('SELECT date,competition_id,home_team_id,away_team_id,official_match_unique_id FROM fixtures').fetchall()
    if len(fixture)!=1 or fixture[0][4] != policy.get('official_match_unique_id') or source.get('match_unique_id') != fixture[0][4]:
        raise ValueError('Derived pass-map fixture/match identity differs')
    if provenance['fixture_scope'] != dict(zip(('date','competition_native_id','home_team_native_id','away_team_native_id'),fixture[0][:4])):
        raise ValueError('Derived pass-map fixture scope differs')
    native_fixture=source.get('fixture_identity')
    expected_native=(fixture[0][0],fixture[0][1],fixture[0][2],fixture[0][3])
    if (not isinstance(native_fixture,list) or len(native_fixture)!=4
            or (native_fixture[0],native_fixture[1],native_fixture[2][1],native_fixture[3][1]) != expected_native):
        raise ValueError('Derived pass-map raw fixture identity differs')
    bound=terminal.get('bound_playback') or terminal.get('playback') or {}
    cutoff=bound.get('current_time_slice')
    if type(cutoff)is not int or not 0<=cutoff<65536 or bound.get('official_match_unique_id')!=fixture[0][4]:
        raise ValueError('Derived pass-map cutoff ownership unsupported')
    geometry=source.get('pitch_geometry');width,length=(geometry.get(k)for k in('half_width_native','half_length_native'))if isinstance(geometry,dict)else(None,None)
    if any(type(v)not in(int,float)or not math.isfinite(v)or not 0<v<=1000 for v in(width,length)):
        raise ValueError('Derived pass-map pitch geometry unsupported')
    actor_document=db.execute("SELECT sha256,document_json FROM source_documents WHERE source_id='pass_actors'").fetchone()
    if actor_document is None or actor_document[0] != policy.get('actor_document_sha256') or actor_document[0] != provenance['source_document_hashes'].get('pass_actors'):
        raise ValueError('Derived pass-map actor source provenance differs')
    actor_packet=json.loads(actor_document[1])
    if payload_hash(actor_packet)!=policy.get('actor_payload_sha256'):
        raise ValueError('Derived pass-map actor payload differs from attestation')
    actor_source=actor_packet.get('actors',{})
    if actor_source.get('state')!='validated_native_stored_slots' or actor_source.get('official_match_unique_id')!=fixture[0][4]:
        raise ValueError('Derived pass-map actor source match identity differs')
    actor_rows=db.execute('SELECT side_index,stored_player_slot,canonical_person_id,person_name,source_id FROM pass_actors').fetchall()
    actors={};people=set()
    for side,slot,person,name,source_id in actor_rows:
        if (type(side)is not int or side not in(0,1)or type(slot)is not int or not 0<=slot<26
                or type(person)is not int or person<=0 or not isinstance(name,str)or not name
                or(side,slot)in actors or person in people or source_id!='pass_actors'):
            raise ValueError('Derived pass-map canonical actor coverage invalid')
        actors[side,slot]=(person,name);people.add(person)
    source_actors={(p['side_index'],p['stored_player_slot']):(p['canonical_person_id'],p['person_name']) for p in actor_source['players']}
    if len(source_actors)!=len(actor_source['players']) or actors!=source_actors:
        raise ValueError('Derived pass-map actor table differs from canonical source')
    base=db.execute('SELECT event_id,side_index,sender_slot,receiver_slot,sender_name,receiver_name,start_tick,end_tick,period,source_id FROM completed_pass_events').fetchall()
    if len(base)!=policy.get('event_count') or len({r[0]for r in base})!=len(base):
        raise ValueError('Derived pass-map base event count or identities differ')
    base_by_id={row[0]:row for row in base};intervals=db.execute('SELECT period,start_tick,end_tick FROM match_periods').fetchall()
    source_intervals=[(p['period'],p['start_tick'],p['end_tick'] if p['end_tick'] is not None else cutoff) for p in terminal.get('period_split',{}).get('period_intervals',[])]
    if (not intervals or sorted(intervals)!=sorted(source_intervals)
            or len({p for p,_,_ in intervals})!=len(intervals)
            or any(type(a)is not int or type(b)is not int or not 0<=a<b<=cutoff for _,a,b in intervals)):
        raise ValueError('Derived pass-map period intervals invalid')
    rows=[];seen=set()
    for at in range(0,len(raw),56):
        event=raw[at:at+56];flags=int.from_bytes(event[48:50],'little');end=int.from_bytes(event[50:52],'little')
        if event[42]!=7 or flags&8 or end>=cutoff:continue
        start=int.from_bytes(event[34:36],'little');identity=int.from_bytes(event[44:48],'little');side=event[40];sender,receiver=event[39],event[41]
        if start>end or identity in seen or side not in(0,1)or(side,sender)not in actors or(side,receiver)not in actors:
            raise ValueError('Derived pass-map native event identity/actor/clock invalid')
        seen.add(identity);person,name=actors[side,sender];recipient,recipient_name=actors[side,receiver]
        periods=[period for period,a,b in intervals if a<=start<=end<b]
        if len(periods)>1:raise ValueError('Derived pass-map ambiguous period intervals')
        period=periods[0]if periods else None
        expected=(identity,side,sender,receiver,name,recipient_name,start,end,period,'terminal')
        if base_by_id.get(identity)!=expected:
            raise ValueError('Derived pass-map base event/actor/clock/period differs')
        location=project_event_location(event,geometry,expected_event_id=identity,expected_side_index=side,expected_player_slot=sender)
        x,y=struct.unpack_from('<ff',event,24)
        values=(identity,side,fixture[0][2+side],person,name,recipient,recipient_name,sender,receiver,start,end,period,x,y,
            int(location['attacked_goal_positive_native_y']),location['attack_relative_longitudinal_coordinate'],
            location['absolute_lateral_centerline_distance'],int(location['inside_native_pitch_extents']),
            location['analytical_pitch_third'],location['analytical_lateral_channel'],flags,'terminal')
        rows.append(dict(zip(COLUMNS,values)))
    if seen!=set(base_by_id):
        raise ValueError('Derived pass-map native/base event sets differ')
    rows.sort(key=lambda r:r['event_id'])
    return {'rows':rows,'columns':list(COLUMNS),'scope':SCOPE,'provenance':{
        'state':'verified_derived_view','policy_version':POLICY_VERSION,'native_plugin_sha256':NATIVE_SHA256,
        'source_terminal_sha256':document[0],'source_event56_sha256':digest,
        'same_capture_base_event_actor_clock_period_checks':len(rows),'original_database_unchanged':True,
        'pitch_geometry':geometry,'cutoff':cutoff,'proof':policy.get('proof')}}
