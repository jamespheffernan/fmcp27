"""Attested optional native pass-attempt points in schema1 observed originals.

Old recordings without this source document stay unsupported, never checked-empty.
No subtraction, independently reconciled denominator, possession-loss cause or
release/reception/destination is inferred from the native event-map point.
"""
import hashlib
import json
import sqlite3
from pathlib import Path

from . import active_pass_attempts

TABLE = 'pass_attempt_events'
DOCUMENT = 'pass_attempt_samples'
COLUMNS = ('event_id','side_index','team_native_id','outcome','completed',
    'sender_person_native_id','sender_name','sender_state','sender_slot',
    'receiver_person_native_id','receiver_name','recipient_state','receiver_slot',
    'native_secondary_byte','native_category_code','native_flags_word',
    'start_tick','end_tick','period','native_event_x','native_event_y',
    'attacked_goal_positive_native_y','attack_relative_longitudinal_coordinate',
    'absolute_lateral_centerline_distance','inside_native_pitch_extents',
    'analytical_pitch_third','analytical_lateral_channel','source_id')
SCOPE = ('Native categories6..11 excluding mask8, start<=end<fixed cursor. Category7 completed; '
    'others not_completed with unknown failure reason. Canonical sender where resolved; recipient only7. '
    'Official native EVENT map points, not proved release/reception/intended destination/trajectory. '
    'Thirds/channels are analytical equal bins; physical units/human left-right unknown. '
    'Not possession-loss events, an independently reconciled attempts denominator, tactical cause or full-match coverage. '
    'Period remains unknown in this schema1 recorder increment.')


def _json(value):
    return json.dumps(value,sort_keys=True,separators=(',', ':'),allow_nan=False)


def _sha(value):
    return hashlib.sha256(_json(value).encode()).hexdigest()


def capture_document(packet, source):
    document = {'state':'available','schema_version':1,'policy':source['pass_attempt_policy'],
        'source_incarnation_id':packet['incarnation_id'],'fixed_time_slice':packet['cursor'],
        'fixture':packet['fixture'],
        'career':{k:packet['save'][k] for k in ('name','created_date','created_version')},
        'actors':packet['actors'],'events':packet['events'],'pitch_geometry':source['pitch_geometry']}
    validate(document,packet)
    return document


def _rows(document):
    fixture = document['fixture']
    return active_pass_attempts.project(document['events'],{
        'state':'validated_native_stored_slots','official_match_unique_id':fixture['official_match_unique_id'],
        'players':document['actors']},
        {'home_team':{'native_id':fixture['home_team_id']},'away_team':{'native_id':fixture['away_team_id']}},
        document['pitch_geometry'],cursor=document['fixed_time_slice'],official_match_unique_id=fixture['official_match_unique_id'])


def validate(document, packet):
    if document is None:
        return
    if (not isinstance(document,dict) or document.get('state')!='available' or document.get('schema_version')!=1
            or document.get('policy')!=active_pass_attempts.source_policy()
            or document.get('source_incarnation_id')!=packet['incarnation_id']
            or document.get('fixed_time_slice')!=packet['cursor']
            or document.get('fixture')!=packet['fixture']
            or document.get('career')!={k:packet['save'][k] for k in ('name','created_date','created_version')}
            or document.get('actors')!=packet['actors'] or document.get('events')!=packet['events']):
        raise ValueError('Observed pass-attempt policy/source binding differs')
    if (type(document['fixed_time_slice']) is not int or not 0<=document['fixed_time_slice']<65536
            or not isinstance(document['events'],list) or len(document['events'])>8192):
        raise ValueError('Observed pass-attempt fixed selection unsupported')
    # Even a checked-empty view must prove its pitch geometry, not skip validation.
    from .pass_field_position import project_event_location
    import struct
    probe=bytearray(56);probe[42]=7;struct.pack_into('<I',probe,44,0)
    project_event_location(bytes(probe),document['pitch_geometry'],expected_event_id=0,expected_side_index=0,expected_player_slot=0)
    _rows(document)


def verify_stored(db, document):
    if document is None:
        return
    row=db.execute('SELECT sha256,document_json FROM source_documents WHERE source_id=?',(DOCUMENT,)).fetchone()
    if row is None or row[0]!=_sha(document) or _sha(json.loads(row[1]))!=row[0] or json.loads(row[1])!=document:
        raise ValueError('Existing observed pass-attempt source changed')


def attestation(packet, receipt):
    document=packet.get('pass_attempt_observation')
    if document is None:
        return None
    validate(document,packet)
    proof={'producer':'verified_observed_recorder','schema_version':1,'source_document_id':DOCUMENT,
           'source_document_sha256':_sha(document),'selection_id':receipt['selection_id'],
           'source_incarnation_id':packet['incarnation_id'],'policy':document['policy']}
    validate_attestation(receipt,proof)
    return proof


def validate_attestation(entry, proof, *, check_original=True):
    from .captured_match_registry import _sha256
    if (not isinstance(proof,dict) or proof.get('producer')!='verified_observed_recorder'
            or proof.get('schema_version')!=1 or proof.get('source_document_id')!=DOCUMENT
            or proof.get('selection_id')!=entry['selection_id']
            or proof.get('policy') not in active_pass_attempts.recorded_policies()):
        raise ValueError('Unsupported observed pass-attempt attestation')
    _sha256(proof.get('source_document_sha256'));_sha256(proof.get('source_incarnation_id'))
    if check_original:
        db=sqlite3.connect(Path(entry['path']).as_uri()+'?mode=ro',uri=True)
        try:
            db.execute('PRAGMA query_only=ON');db.execute('PRAGMA trusted_schema=OFF')
            derive_pass_attempts(db,{'source_document_hashes':dict(db.execute('SELECT source_id,sha256 FROM source_documents'))},attestation=proof)
        finally:
            db.close()


def derive_pass_attempts(db, provenance, *, attestation=None):
    if attestation is None:
        return None
    metadata={k:json.loads(v) for k,v in db.execute('SELECT key,value_json FROM metadata')}
    validate_attestation({'selection_id':metadata.get('selection_id')},attestation,check_original=False)
    row=db.execute('SELECT sha256,document_json FROM source_documents WHERE source_id=?',(DOCUMENT,)).fetchone()
    if (row is None or row[0]!=attestation['source_document_sha256']
            or hashlib.sha256(row[1].encode()).hexdigest()!=row[0]
            or row[0]!=provenance['source_document_hashes'].get(DOCUMENT)):
        raise ValueError('Observed pass-attempt source document differs')
    document=json.loads(row[1])
    fixture=db.execute('SELECT date,competition_id,home_team_id,away_team_id,official_match_unique_id FROM fixtures').fetchall()
    if len(fixture)!=1:
        raise ValueError('Observed pass-attempt fixture extent differs')
    fixture=dict(zip(('date','competition_id','home_team_id','away_team_id','official_match_unique_id'),fixture[0]))
    terminal_row=db.execute("SELECT sha256,document_json FROM source_documents WHERE source_id='terminal'").fetchone()
    if terminal_row is None or hashlib.sha256(terminal_row[1].encode()).hexdigest()!=terminal_row[0]:
        raise ValueError('Observed pass-attempt terminal provenance differs')
    terminal=json.loads(terminal_row[1])
    if (terminal.get('fixture')!=fixture or terminal.get('fixed_time_slice')!=metadata.get('fixed_time_slice')
            or document.get('source_incarnation_id')!=metadata.get('source_incarnation_id')
            or document.get('source_incarnation_id')!=attestation['source_incarnation_id']):
        raise ValueError('Observed pass-attempt original identity differs')
    events=[json.loads(raw) for _,raw in db.execute('SELECT event_id,record_json FROM native_pass_events ORDER BY event_id')]
    if any(e['event_id']!=key for key,raw in db.execute('SELECT event_id,record_json FROM native_pass_events') for e in [json.loads(raw)]):
        raise ValueError('Observed pass-attempt native event key differs')
    actors=[dict(zip(('side_index','stored_player_slot','canonical_person_id','person_name','identity_state'),r))
            for r in db.execute('SELECT side_index,stored_player_slot,canonical_person_id,person_name,identity_state FROM pass_actors ORDER BY side_index,stored_player_slot')]
    # PERSON index is capture provenance, not a physical schema1 column.
    stored_actors=[{k:v for k,v in a.items() if k!='person_index_word'} for a in document.get('actors',[])]
    if sorted(stored_actors,key=lambda a:(a['side_index'],a['stored_player_slot']))!=actors:
        raise ValueError('Observed pass-attempt actor table differs')
    packet={'incarnation_id':metadata.get('source_incarnation_id'),'cursor':metadata.get('fixed_time_slice'),
        'fixture':fixture,'save':terminal['save'],'actors':document.get('actors'), 'events':events}
    validate(document,packet)
    # Cross-check the legacy completed relation too; the new view never rewrites it.
    by_actor={(a['side_index'],a['stored_player_slot']):a for a in actors}
    expected=[]
    for e in events:
        if e['category']==7 and not e['flags_word']&8:
            sender=by_actor.get((e['side_index'],e['stored_player_slot']),{})
            receiver=by_actor.get((e['side_index'],e['recipient_slot']),{})
            expected.append((e['event_id'],e['side_index'],e['stored_player_slot'],e['recipient_slot'],sender.get('person_name'),receiver.get('person_name'),e['start'],e['end'],None,'terminal'))
    if db.execute('SELECT * FROM completed_pass_events ORDER BY event_id').fetchall()!=expected:
        raise ValueError('Observed pass-attempt legacy completed relation differs')
    rows=[]
    for r in _rows(document):
        point=r['native_pass_map_location']
        values=(r['event_id'],r['side_index'],r['team_native_id'],r['outcome'],int(r['completed']),
            r['from_person_native_id'],r['from_name'],r['sender_state'],r['stored_player_slot'],
            r['to_person_native_id'],r['to_name'],r['recipient_state'],r['recipient_slot'],
            r['native_secondary_byte'],r['native_category_code'],r['native_flags_word'],
            r['native_start_time_slice'],r['native_end_time_slice'],None,point['native_x'],point['native_y'],
            int(r['attacked_goal_positive_native_y']),r['attack_relative_longitudinal_coordinate'],
            r['absolute_lateral_centerline_distance'],int(r['inside_native_pitch_extents']),
            r['analytical_pitch_third'],r['analytical_lateral_channel'],DOCUMENT)
        rows.append(dict(zip(COLUMNS,values)))
    return {'rows':rows,'columns':list(COLUMNS),'scope':SCOPE,'provenance':{
        'state':'verified_derived_view','policy':document['policy'],'source_document_sha256':row[0],
        'same_capture_native_events_actor_fixture_checks':len(rows),'fixed_time_slice':document['fixed_time_slice'],
        'original_database_unchanged':True,'counter_reconciliation':'unavailable_at_fixed_current_prefix',
        'possession_loss_events_included':False,'summary':active_pass_attempts.summarize(_rows(document))}}
