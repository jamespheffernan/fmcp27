"""Retained passing by host-witnessed periods; no inferred half boundaries."""
from collections import Counter
import hashlib
import struct

from .live_retained_pass_events import decode_pass_attempts
from .match_period_observations import digest


PASS_PERIOD_REPORT_POLICY = 'period_network_fields_and_selection_mask8_v1'


def _fingerprint_rows(event_bytes, cursor):
    if not isinstance(event_bytes,bytes) or len(event_bytes)%56 or len(event_bytes)>30000*56:
        raise ValueError('Unsupported pass fingerprint source')
    if type(cursor)is not int or not 0<cursor<=65536:raise ValueError('Invalid pass fingerprint cutoff')
    rows=[];ids=set()
    for at in range(0,len(event_bytes),56):
        e=event_bytes[at:at+56]
        if e[42] not in range(6,12) or struct.unpack_from('<H',e,50)[0]>=cursor:continue
        eid=struct.unpack_from('<I',e,44)[0]
        if eid in ids:raise ValueError('Duplicate pass fingerprint event ID')
        ids.add(eid)
        rows.append(dict(event_id=eid,side_index=e[40],stored_player_slot=e[39],recipient_slot=e[41],
                         native_category_code=e[42],flags_word=struct.unpack_from('<H',e,48)[0],
                         start_tick=struct.unpack_from('<H',e,34)[0],end_tick=struct.unpack_from('<H',e,50)[0]))
    return sorted(rows,key=lambda r:r['event_id'])


def pass_event_fingerprint(event_bytes, cursor=65536):
    """Original full-flags witness: preserved exactly, including mutable bits."""
    rows=_fingerprint_rows(event_bytes,cursor)
    return dict(schema=1,semantic_sha256=digest(rows),event_count=len(rows),cutoff_exclusive=cursor)


def pass_period_report_fingerprint(event_bytes, cursor=65536):
    """Only this report's IDs/actors/recipients/categories/clocks and mask8.

    The native decoder consumes flag0x8 to exclude unlabelled records. Other
    flags are neither published nor used by this non-spatial period network.
    This does not certify their equality or establish their English meaning.
    A report adding other native fields must introduce a new policy version.
    """
    rows=_fingerprint_rows(event_bytes,cursor)
    for row in rows:
        row['native_selection_mask8']=row.pop('flags_word') & 8
    return dict(schema=1,report_policy=PASS_PERIOD_REPORT_POLICY,native_flags_mask=8,
                semantic_sha256=digest(rows),event_count=len(rows),cutoff_exclusive=cursor)


def project(event_bytes, players, period_link, observation):
    """Require a prior witness for report fields; preserve stricter mismatch separately."""
    unavailable = dict(state='unavailable_no_exact_pass_period_source', periods=None, sides=None)
    if period_link.get('state') != 'verified_retrospective_continuity':
        return dict(unavailable, reason='verified_host_period_link_required')
    if digest(observation) != period_link.get('capture_id'):
        raise ValueError('Period capture identity differs')
    strict=observation.get('pass_event_fingerprint')
    report_witness=observation.get('pass_period_report_fingerprint')
    strict_state='not_captured'
    if strict is not None:
        strict_state=('matched' if isinstance(strict,dict) and strict == pass_event_fingerprint(event_bytes,strict.get('cutoff_exclusive')) else 'mismatch')
    report_state='not_captured'
    if report_witness is not None:
        report_state=('matched' if isinstance(report_witness,dict) and report_witness == pass_period_report_fingerprint(event_bytes,report_witness.get('cutoff_exclusive')) else 'mismatch')
        if report_state!='matched':
            return dict(unavailable,reason='published_pass_period_fields_or_selection_mask_differ',
                        strict_pass_event_continuity=strict_state,pass_period_report_continuity=report_state)
        binding='published_period_network_fields_and_native_selection_mask8_match_host_observation'
        witness=report_witness
    elif strict is not None:
        if strict_state!='matched':
            return dict(unavailable,reason='complete_observed_pass_semantics_differ',
                        strict_pass_event_continuity=strict_state,pass_period_report_continuity=report_state)
        binding='all_pass_event_semantics_match_host_observation'
        witness=strict
    elif hashlib.sha256(event_bytes).hexdigest() == observation.get('source_hashes', {}).get('events'):
        binding='exact_complete_observed_event_vector'
        witness=None
    else:
        return dict(unavailable, reason='complete_observed_event_vector_fingerprint_differs')
    intervals = period_link.get('intervals', [])
    if witness is not None and any(i['end_tick']>witness['cutoff_exclusive']for i in intervals):
        return dict(unavailable,reason='period_exceeds_observed_pass_prefix')
    if not intervals:
        return dict(unavailable, reason='no_closed_observed_periods')
    decoded = decode_pass_attempts(event_bytes, players)
    raw = [event_bytes[i:i+56] for i in range(0,len(event_bytes),56)]
    clocks = {}
    for row in decoded['attempts']:
        event = raw[row['record_index']]
        start,end=struct.unpack_from('<H',event,34)[0],struct.unpack_from('<H',event,50)[0]
        if start>end:raise ValueError('Wrapped or reversed retained pass clocks')
        clocks[row['event_id']] = start,end
    sides=[]
    for coverage in decoded['side_coverage']:
        side=coverage['side_index']
        if coverage['state']!='available':
            sides.append(dict(side_index=side,state=coverage['state'],periods=None,unknown_interval_attempts=None));continue
        selected=[r for r in decoded['attempts']if r['side_index']==side]
        groups={i['period']:[]for i in intervals};unknown=0
        for row in selected:
            start,end=clocks[row['event_id']]
            matches=[i['period']for i in intervals if i['start_tick']<=start<=end<i['end_tick']]
            if len(matches)!=1:unknown+=1;continue
            groups[matches[0]].append(row)
        periods=[]
        for interval in intervals:
            rows=groups[interval['period']];completed=[r for r in rows if r['completed']]
            pairs=Counter();names={};actors=Counter();received=Counter()
            for row in completed:
                a,b=row['person_native_id'],row['recipient_person_native_id']
                if b is None:raise ValueError('Completed recipient missing')
                pairs[a,b]+=1;names[a]=row['person_name'];names[b]=row['recipient_name'];actors[a]+=1;received[b]+=1
            denominator=len(completed)
            directed=[dict(from_person_native_id=a,from_name=names[a],to_person_native_id=b,to_name=names[b],completed_passes=n)
                      for (a,b),n in sorted(pairs.items(),key=lambda x:(-x[1],x[0]))]
            combined=Counter()
            for (a,b),n in pairs.items():combined[tuple(sorted((a,b)))]+=n
            two_way=[dict(person_native_ids=list(pair),names=[names[x]for x in pair],completed_passes=n,
                          share_of_period_completed_passes_computed=100*n/denominator if denominator else None)
                     for pair,n in sorted(combined.items(),key=lambda x:(-x[1],x[0]))]
            periods.append(dict(**interval,attempts=len(rows),completed_passes=denominator,
                not_completed_passes=len(rows)-denominator,directed_pairs=directed,two_way_pairs=two_way,
                players=[dict(person_native_id=p,person_name=names[p],completed_passes_sent=actors[p],completed_passes_received=received[p])for p in sorted(names)]))
        sides.append(dict(side_index=side,state='available',periods=periods,unknown_interval_attempts=unknown,
                          full_fixture_attempts=coverage['attempt_count'],full_fixture_completed_passes=coverage['completed_count']))
    return dict(state='available'if all(s['state']=='available'for s in sides)else'partial',sides=sides,
        periods=intervals,period_provenance=period_link['provenance'],
        event_vector_sha256=hashlib.sha256(event_bytes).hexdigest(),pass_period_binding=binding,pass_semantic_fingerprint=digest(pass_event_fingerprint(event_bytes)),
        pass_period_report_semantic_fingerprint=digest(pass_period_report_fingerprint(event_bytes)),
        strict_pass_event_continuity=strict_state,pass_period_report_continuity=report_state,
        boundary_policy='period_start<=event_start<=event_end<period_end; ties/crossings/unobserved intervals unknown',
        denominator_policy='Pair share divides by all counter-qualified completed pass events in that side and period; not attempted pair completion rate.',
        limits='Whole-fixture individual attempt/completion counters reconcile; no independent period aggregate oracle. Original stored roster actors, not current on-pitch membership. No minute guesses, pass routes, pressure or tactical causation. Report-specific continuity does not certify other native flags, raw byte equality or unconsumed event annotations.')


def _verify_clocks(bridge,session_id):
    from .active_pass_network import PASS_CLOCK_SPANS
    from . import players
    with bridge.lock,bridge._read_scope(session_id):
        process=bridge._current(session_id);tables=bridge._player_layout(process)
        read,_,_=bridge._world_state(process,tables);base=tables[0]-players.RVA[0]
        for at,expected in PASS_CLOCK_SPANS:
            if read(base+at,len(expected))!=expected:raise ValueError('Retained pass clock native source changed')
        read.verify();bridge._current(session_id)


def report(bridge, session_id, fixture_ref, *, store=None):
    from . import live_retained_shots as retained
    from .match_data_query import capture_epoch, capture_live
    from .match_period_observations import ObservationStore, link_retained, process_epoch
    from .live_retained_passes import _verify_pass_native
    from .live_retained_pass_events import _verify_attempt_native
    epoch=capture_epoch(bridge,session_id)
    capture=capture_live(bridge,session_id,[fixture_ref],include_players=True)
    if capture.get('_live_capture_epoch')!=epoch:raise ValueError('Retained frame epoch differs')
    items=capture['capture']['fixtures']
    if len(items)!=1 or items[0]['fixture']['fixture_ref']!=fixture_ref:raise ValueError('Exact retained fixture required')
    fixture,key=items[0]['fixture'],items[0]['native_match_key']
    records=[r for r in capture['team_totals']['records']if r['result_key']==key]
    if len(records)!=1:raise ValueError('Exact retained team oracle required')
    teams=records[0]['teams'];retained._validate_team_oracle(fixture,teams)
    players=[p for p in capture['retained_players']if p.get('fixture_key',p.get('native_match_key'))==key]
    if len(retained._validated_actors(players,teams))!=len(players):raise ValueError('Canonical retained actors differ')
    _verify_pass_native(bridge,session_id);_verify_attempt_native(bridge,session_id);_verify_clocks(bridge,session_id)
    source=retained.capture_source(bridge,session_id,fixture_ref,key,fixture)
    if source['state']!='available':return dict(state=source['state'],fixture=fixture,sides=None,periods=None)
    shots=retained.decode_attempts(source['vectors'],source['events'],teams)
    if any(s['state']!='available'for s in shots['side_coverage']):
        return dict(state='unavailable_retained_shot_continuity',fixture=fixture,sides=None,periods=None)
    save=bridge.get_save(session_id)['save'];store=store or ObservationStore()
    link=link_retained(store,save,fixture,key,source,shots['shots'],process_epoch(bridge))
    document=store.observations(save,fixture)
    observation=document['observations'].get(link.get('capture_id'),{})
    result=project(source['events'],players,link,observation)
    fresh=retained.capture_source(bridge,session_id,fixture_ref,key,fixture)
    if (fresh.get('state')!='available' or fresh['events']!=source['events'] or fresh['vectors']!=source['vectors']
            or capture_epoch(bridge,session_id)!=epoch):raise ValueError('Retained period pass source changed')
    return dict(result,fixture=fixture,native_match_key=key,saved_file_fallback=False,atomic=False)
