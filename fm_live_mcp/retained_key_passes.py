"""Whole-event key-pass annotations with independent per-player counter closure."""
from collections import Counter
import hashlib
import json
import struct
from datetime import datetime,timezone

from .saved_match_player_actions import decode_player_actions
from .live_retained_pass_events import decode_pass_attempts

MAX_EVENTS=30000


def decode_key_pass_annotations(events,players,fixture,*,native_match_key,pitch_geometry=None):
    """Full CBE56 vector, never just the public pass-family projection.

    Counts are annotations, not unique shot/goal-provider links. A mismatching
    side can retain explicitly scoped individually reconciled actor views.
    """
    if not isinstance(events,bytes)or len(events)%56 or len(events)//56>MAX_EVENTS:
        raise ValueError('Unsupported key-pass event extent')
    if type(native_match_key)is not int or native_match_key<=0 or not isinstance(players,list)or len(players)>512:
        raise ValueError('Unsupported key-pass fixture or player budget')
    ids=[struct.unpack_from('<I',events,at+44)[0]for at in range(0,len(events),56)]
    if len(ids)!=len(set(ids)):raise ValueError('Duplicate key-pass source event identity')
    roster={};people=set();checked=[]
    for p in players:
        side,slot=p.get('side_index'),p.get('stored_player_slot')
        if type(side)is not int or side not in(0,1)or type(slot)is not int or not 0<=slot<26 or(side,slot)in roster:
            raise ValueError('Ambiguous original key-pass actor slot')
        team=fixture['home_team'if side==0 else'away_team']
        if(p.get('fixture_key',p.get('native_match_key'))!=native_match_key or p.get('team_index_word')!=team['database_index']
           or p.get('canonical_team_id')!=team['native_id']):
            raise ValueError('Key-pass actor fixture or TEAM differs')
        child=bytes.fromhex(p['raw_child_hex']);delta=4 if child[0]<2 else 0
        if(child[0]!=p['person_reference_tag']or int.from_bytes(child[1:5+delta],'little')!=p['person_index_word']
           or hashlib.sha256(child).hexdigest()!=p['row_sha256']):
            raise ValueError('Independent key-pass player wire identity differs')
        values=decode_player_actions(child)
        if any(p.get(k)!=values[k]for k in('key_passes','passes_attempted','passes_completed')):
            raise ValueError('Projected player counters differ from native wire')
        identity=p.get('canonical_person_id');name=p.get('person_name')
        canonical=type(identity)is int and identity>0 and isinstance(name,str)and bool(name)
        if canonical:
            if identity in people:raise ValueError('Duplicate canonical key-pass PERSON')
            people.add(identity)
        row={**p,'canonical_actor':canonical};roster[side,slot]=row;checked.append(row)
    records=[events[at:at+56]for at in range(0,len(events),56)]
    markers=[(index,e)for index,e in enumerate(records)if struct.unpack_from('<H',e,48)[0]&2]
    if any(e[40]not in(0,1)for _,e in markers):raise ValueError('Unsupported key-pass annotation side')
    counts=Counter((e[40],e[39])for _,e in markers)
    # This independently verifies the complete pass side before a same-ID join.
    passing=(decode_pass_attempts(events,players,pitch_geometry=pitch_geometry)if pitch_geometry is not None else
             {'attempts':[],'side_coverage':[{'side_index':s,'state':'unavailable_native_pitch_geometry_for_pass_locations'}for s in(0,1)]})
    passes={r['event_id']:r for r in passing['attempts']if r['completed']}
    sides=[];annotations=[]
    for side in(0,1):
        own=[r for r in checked if r['side_index']==side];checks=[];eligible=set()
        for p in sorted(own,key=lambda x:x['stored_player_slot']):
            slot=p['stored_player_slot'];n=counts[side,slot];matches=n==p['key_passes']
            state=('available_individual_counter_reconciled'if matches and p['canonical_actor']else
                   'unavailable_actor_identity'if not p['canonical_actor']else'unavailable_key_pass_counter_mismatch')
            cats=Counter(e[42]for _,e in markers if(e[40],e[39])==(side,slot))
            checks.append(dict(stored_player_slot=slot,person_native_id=p.get('canonical_person_id'),person_name=p.get('person_name'),
                               state=state,official_key_passes=p['key_passes'],source_annotation_count=n,
                               difference=n-p['key_passes'],counts_match=matches,
                               annotation_category_counts={str(k):v for k,v in sorted(cats.items())}))
            if state=='available_individual_counter_reconciled':eligible.add(slot)
        missing=sorted({e[39]for _,e in markers if e[40]==side and(side,e[39])not in roster})
        complete=bool(own)and not missing and all(c['state']=='available_individual_counter_reconciled'for c in checks)
        own_rows=[]
        for index,e in markers:
            if e[40]!=side or e[39]not in eligible:continue
            actor=roster[side,e[39]];eid=struct.unpack_from('<I',e,44)[0];linked=passes.get(eid)if e[42]==7 and not e[48]&8 else None
            if linked and(linked['side_index'],linked['stored_player_slot'],linked['person_native_id'])!=(side,e[39],actor['canonical_person_id']):
                raise ValueError('Key-pass/completed-pass same-ID actor differs')
            recipient=roster.get((side,e[41]))if linked else None
            recipient_known=bool(recipient and recipient['canonical_actor'])
            location=linked.get('field_position')if linked else None
            row=dict(record_index=index,event_id=eid,side_index=side,stored_player_slot=e[39],person_native_id=actor['canonical_person_id'],
                     person_name=actor['person_name'],annotation='native_key_pass',native_flag_mask=2,native_category_code=e[42],
                     side_key_pass_denominator_complete=complete,creator_counter_scope='individual native key-pass count reconciled over ALL event categories',
                     completed_pass_event_join_state='same_event_id_counter_qualified_completed_pass'if linked else'unavailable_other_category_or_pass_side_unreconciled',
                     recipient_person_native_id=recipient['canonical_person_id']if recipient_known else None,
                     recipient_name=recipient['person_name']if recipient_known else None,
                     recipient_state='canonical_completed_pass_recipient'if recipient_known else'unmapped_for_this_annotation',
                     field_position=location,field_position_state='official_completed_pass_map_event_location'if location else'unmapped_for_this_annotation',
                     shot_event_id=None,goal_event_id=None,assist=None,
                     provider_link_state='no direct annotation-to-shot-or-goal link proved')
            own_rows.append(row)
        annotations.extend(own_rows);official=sum(p['key_passes']for p in own)if own else None
        known_locations=[r for r in own_rows if r['field_position']is not None]
        suppliers=Counter((r['person_native_id'],r['recipient_person_native_id'])for r in own_rows if r['recipient_person_native_id']is not None)
        names={p['canonical_person_id']:p['person_name']for p in own if p['canonical_actor']}
        categories=Counter(e[42]for _,e in markers if e[40]==side)
        sides.append(dict(side_index=side,team_native_id=fixture['home_team'if side==0 else'away_team']['native_id'],
                          state='available_full_side_denominator'if complete else'partial_individual_actor_views'if eligible else'unavailable_key_pass_reconciliation',
                          full_side_key_pass_counter_closure=complete,captured_player_counter_checks=len(own),
                          matched_player_counter_checks=sum(c['counts_match']for c in checks),
                          zero_counter_players_checked=sum(c['official_key_passes']==0 for c in checks),
                          official_key_pass_total=official,source_annotation_count=sum(v for(s,_),v in counts.items()if s==side),
                          source_annotation_category_counts={str(k):v for k,v in sorted(categories.items())},
                          individually_reconciled_annotation_count=len(own_rows),withheld_unreconciled_actor_annotation_count=sum(v for(s,slot),v in counts.items()if s==side and slot not in eligible),
                          unresolved_annotation_slots=missing,player_checks=checks,
                          completed_pass_side_coverage={k:v for k,v in passing['side_coverage'][side].items()if k!='player_counters'},
                          named_completed_pass_recipient_count=sum(r['recipient_name']is not None for r in own_rows),
                          official_pass_map_location_count=len(known_locations),
                          other_or_unmapped_location_count=len(own_rows)-len(known_locations),
                          location_counts_by_analytical_third=dict(Counter(r['field_position']['analytical_pitch_third']or'outside_pitch_extents'for r in known_locations)),
                          location_scope='only same-ID completed-pass rows among individually reconciled key-pass creators; NOT all key passes when denominator/location coverage is incomplete',
                          supplied_pairs=[dict(from_person_native_id=a,from_name=names[a],to_person_native_id=b,to_name=names[b],key_pass_annotated_completed_pass_events=n)
                                          for(a,b),n in sorted(suppliers.items(),key=lambda x:(-x[1],x[0]))]))
    return dict(state='available'if all(s['full_side_key_pass_counter_closure']for s in sides)else'available_partial',
                native_event_count=len(records),all_event_category_marker_count=len(markers),sides=sides,annotations=annotations,
                annotation_policy='native CBE flags mask2; every native per-player key-pass counter checked over ALL event categories including zero players',
                recipient_location_policy='join by exact event ID to independently whole-side counter-qualified completed passes only; all other categories keep recipient/location unknown',
                limits=['annotated event is not a uniquely linked shot, assist or goal provider','missing side/actor markers are never inferred from proximity',
                        'locations are official pass-map event locations: where the pass was played from; units/human viewpoint remain unknown'])


def verify_native(read,base):
    from .live_retained_passes import PASS_NATIVE_SPANS
    from .pass_field_position import NATIVE_SPANS as POSITION_SPANS
    for at,expected in KEYPASS_NATIVE_SPANS+PASS_NATIVE_SPANS+POSITION_SPANS:
        if read(base+at,len(expected))!=expected:raise ValueError('Native retained key-pass binding changed')


def get_retained_key_pass_annotations(bridge,session_id,fixture_ref,*,team_native_id=None,person_native_id=None,
                                      offset=0,limit=100,expected_source_id=None,coach_index=None):
    """One current-session retained fixture; full counter coverage before paging."""
    from . import players as layout
    from .match_data_query import capture_epoch
    from .live_match_backing import read_selected_matches
    from .live_match_team_totals import decode_team_totals
    from .live_match_players import project_frame
    from .live_retained_shots import capture_source,_validate_team_oracle,_actor_rows
    if not isinstance(fixture_ref,str)or not fixture_ref:raise ValueError('Select one retained RESULT fixture reference')
    for value in(team_native_id,person_native_id):
        if value is not None and(type(value)is not int or value<=0):raise ValueError('Invalid canonical key-pass selector')
    if person_native_id is not None and team_native_id is None:raise ValueError('A selected key-pass player requires its team')
    if type(offset)is not int or offset<0 or type(limit)is not int or not 1<=limit<=500:raise ValueError('Invalid key-pass page')
    if expected_source_id is not None and(not isinstance(expected_source_id,str)or len(expected_source_id)!=64 or any(c not in'0123456789abcdef'for c in expected_source_id)):
        raise ValueError('Invalid key-pass source pin')
    if offset and expected_source_id is None:raise ValueError('Key-pass continuation requires the first source_id')
    epoch=capture_epoch(bridge,session_id)
    observed_first=bridge.get_save(session_id)['save']
    with bridge.lock,bridge._read_scope(session_id):
        process=bridge._current(session_id);tables=bridge._player_layout(process);read,_,_=bridge._world_state(process,tables)
        verify_native(read,tables[0]-layout.RVA[0]);read.verify();bridge._current(session_id)
    backing=read_selected_matches(bridge,session_id,[fixture_ref],include_players=True)
    records=backing['records']
    if len(records)!=1 or records[0]['fixture_ref']!=fixture_ref:raise ValueError('Key-pass backing fixture scope differs')
    record=records[0];fixture=record['fixture_native'];key=record['key']
    selected_sides=[side for side,k in enumerate(('home_team','away_team'))if team_native_id is None or fixture[k]['native_id']==team_native_id]
    if not selected_sides:raise ValueError('Selected team is not in the retained fixture')
    base=dict(fixture=fixture,native_match_key=key,source_kind='active_human_retained_cbe_key_pass_annotations',
              saved_file_fallback=False,atomic=False,observed_save_first=observed_first,source_id=None,annotations=[],sides=[],offset=offset,limit=limit,
              total_count=None,available_row_count=None,next_offset=None,team_native_id=team_native_id,person_native_id=person_native_id)
    if record['state']!='available':return {**base,'state':record['state']}
    raw=record['raw'];totals=decode_team_totals(raw)
    if totals['result_key']!=key:raise ValueError('Key-pass raw frame result key differs')
    _validate_team_oracle(fixture,totals['teams'])
    complete=project_frame(raw,key)
    if not complete['coverage']['complete_side_sections']:raise ValueError('Incomplete native key-pass player side sections')
    roster=[{**p,**decode_player_actions(bytes.fromhex(p['raw_child_hex']))}for p in _actor_rows(record,None)]
    if len(roster)!=sum(complete['coverage']['stored_rows_per_side']):raise ValueError('Key-pass full roster count differs')
    source=capture_source(bridge,session_id,fixture_ref,key,fixture,coach_index)
    if source['state']!='available':return {**base,'state':source['state']}
    decoded=decode_key_pass_annotations(source['events'],roster,fixture,native_match_key=key,pitch_geometry=source.get('pitch_geometry'))
    if capture_epoch(bridge,session_id)!=epoch:raise ValueError('Key-pass career epoch changed during capture')
    observed_last=bridge.get_save(session_id)['save']
    if capture_epoch(bridge,session_id)!=epoch:raise ValueError('Key-pass career epoch changed before publication')
    digest=hashlib.sha256(repr(epoch).encode()+raw+source['events']+json.dumps({'fixture':fixture,'players':roster,'pitch_geometry':source.get('pitch_geometry'),'team':team_native_id,'person':person_native_id},sort_keys=True).encode()).hexdigest()
    if expected_source_id is not None and expected_source_id!=digest:raise ValueError('Key-pass source or selectors changed; restart paging')
    sides=[r for r in decoded['sides']if r['side_index']in selected_sides]
    annotations=[r for r in decoded['annotations']if r['side_index']in selected_sides and(person_native_id is None or r['person_native_id']==person_native_id)]
    checks=[r for side in sides for r in side['player_checks']if person_native_id is None or r['person_native_id']==person_native_id]
    available=(bool(checks)and all(c['state']=='available_individual_counter_reconciled'for c in checks)
               and(person_native_id is not None or all(s['full_side_key_pass_counter_closure']for s in sides)))
    if person_native_id is not None and not checks:
        return {**base,'state':'unavailable_selected_key_pass_actor','source_id':digest,'sides':sides}
    end=min(offset+limit,len(annotations))
    return {**base,**{k:v for k,v in decoded.items()if k not in('sides','annotations','state')},
            'state':'available'if available else'available_partial','sides':sides,'annotations':annotations[offset:end],
            'available_row_count':len(annotations),'total_count':len(annotations)if available else None,
            'source_id':digest,'observed_save_last':observed_last,'observed_at':datetime.now(timezone.utc).isoformat(),'next_offset':end if end<len(annotations)else None,
            'complete_native_roster_rows_per_side':complete['coverage']['stored_rows_per_side'],
            'raw_frame_sha256':hashlib.sha256(raw).hexdigest(),
            'selected_counter_checks':checks if person_native_id is not None else None}


KEYPASS_NATIVE_SPANS = ((76386728, b'\xe1\x03\x15\xaaX\xef\xfe\x97\xa8\xa2A9\x80\xf3\xff\xb4\x1fa\x00q\xa1\n\x00TI\x00\x80R\n`@yI\x01\t*\t`\x00y'), (76107532, b'\x08\xa4@\xa9)\x01\x08\xcb)\xfdC\x93\xea\xb6\x8d\xd2j\xdb\xb6\xf2\xaam\xdb\xf2\xca\xb6\xed\xf2)}\n\x9b?\x05\x00q\xab\x0c\x00T\xfco\xba\xa9\xfag\x01\xa9\xf8_\x02\xa9\xf6W\x03\xa9\xf4O\x04\xa9\xfd{\x05\xa9\xfdC\x01\x91)y@\x92*D@\xb9T\xe1\x01Q5\xa8A96\x05\x00\x91\n\x07\x80R(!\xaa\x9b\x17\xe1\x00\xd18\xacA9\xfa\x1f\x80Ryi\x8cR9\x8c\xaer{\xee\x8dR[n\xacr\x9c\xee\x8dR\x1cm\xaer\xe8F@y\x9f\x02\x08k\xec\x08\x00T\xf3\xaa\xc09\xe0\x03\x13\xaa#\xda\xff\x97\xe8\xa2@9\x1f\x01\x15ka\x01\x00T\xe9\x9e@9?\x01\x18k\xe1\x01\x00T\x7f\xda\x00q\x80\x03\x00T\xeab@yJ\x03\x007\x1f\x00\x19k\x01\x02\x00T\x17\x00\x00\x14_\xff\x03q\xa1\x03\x00T\xd6\x06\x00\xd1\xf7\xe2\x00\xd1\xdf\x06\x00\xf1\x08\xfd\xffT0\x00\x00\x14\xea\xa6@9_\x01\x18k\x00\xfe\xffT\x7f\x06\x00q\xa1\xfe\xffT\xfa\x03\t\xaa\xf5\xff\xff\x17\x1f\x00\x1bk\xe0\x00\x00T\x1f\x00\x1ck\xa0\x00\x00Tjj\x8eR*\x0c\xaer\x1f\x00\nk\xa1\xfe\xffT\xe0\x03\x17\xaa\xfd{E\xa9\xf4OD\xa9\xf6WC\xa9\xf8_B\xa9\xfagA\xa9\xfco\xc6\xa8\xc0\x03_\xd6\x1f\x01\x15ka\xfc\xffT\xe8\x9e@9\x1f\x01\x1ak\x00\xfc\xffT\x1f\x01\x18k\xc0\xfb\xffT\xe8b@y\x08\x02\x007\x01\x00\x80\xd2h\xee\x8dRHn\xacr\x1f\x00\x08k\xa0\x01\x00Thj\x8eR(\x0c\xaer\x1f\x00\x08k \x01\x00T\x88\xee\x8dR\x08m\xaer\x1f\x00\x08k\xe0\x03\x01\xaa\xc1\xf9\xffT\xe2\xff\xff\x17\x00\x00\x80\xd2\xe0\xff\xff\x17\xe0\x03\x01\xaa\xde\xff\xff\x17\x00\x00\x80\xd2'), (76792876, b'\xe9\x1b@\xf9(e@\xb9)\xa1A9H\x01\x186'), (76793048, b'?u\x00qH\x1e\x01TKV\x00\xb0k\xb1\x0b\x91\x8c\x00\x00\x10myix\x8c\t\r\x8b\x80\x01\x1f\xd6'), (88101660, b'\x99\x00'), (76793692, b'W\n\x01\xb4\xe9\xf2B9)\x05\x00\x11\xe9\xf2\x029\tC\x80R\x1f\x01\tj\x81\t\x01T\xe8\xf6B9\x08\x05\x00\x11\xe8\xf6\x029H\x08\x00\x14'), (2118056, b'\xe1\xf2B9\xe0#\x00\x91Q\xfb\x07\x95\xe0c\x00\x91\xe2#\x00\x91\xe1\r\x8dR!)\xadrH\xc8\x07\x95'))
