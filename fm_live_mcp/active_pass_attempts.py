"""Cursor-bound native pass-attempt EVENT points; possession loss is separate.

The retained converter establishes categories6..11 minus mask8 as attempts.
Current prefixes have no matching aggregate-counter oracle; no denominator,
specific failure reason, release/reception/destination or turnover is inferred.
"""
from collections import Counter,OrderedDict
from copy import deepcopy
import hashlib,json,secrets,struct,time
from . import active_pass_network,pass_field_position,live_retained_pass_events

POLICY_ID='current_pass_attempt_event_points_v1'
NATIVE_SHA256='774cacde63567fd3901c47719e7a6ed94cc3a0a62e9b94989dcac6b4890ec0e1'
_CACHE=OrderedDict()


def source_policy():
    spans=live_retained_pass_events.ATTEMPT_NATIVE_SPANS+pass_field_position.NATIVE_SPANS
    return {'policy_id':POLICY_ID,'native_plugin_sha256':NATIVE_SHA256,
            'native_guard_digest':hashlib.sha256(json.dumps([(rva,raw.hex()) for rva,raw in spans],separators=(',',':')).encode()).hexdigest(),
            'categories':[6,7,8,9,10,11],'excluded_mask':8,'completed_category':7,
            'location':'official_native_pass_map_event_point','counter_reconciliation':'unavailable_at_fixed_current_prefix',
            'possession_loss_event_binding_verified':False,'release_reception_destination_verified':False}


# The guard digest of the pinned build's spans (their pinned bytes). A run recorded on the pinned
# build carries that policy; on a mapped build the spans are rewritten, so the stored run is checked
# against the policy of the build that recorded it. New recordings must carry the current policy.
PINNED_GUARD_DIGEST='c3a344caedbfdfb027a7c81b458e2c23caef0f4fd7909e912b027a154d107593'


def recorded_policies():
    """The policies a stored run may carry: the current build's and the pinned build's."""
    from . import address_book
    current=source_policy()
    pinned=dict(current,native_plugin_sha256=address_book.PINNED_SHA256,native_guard_digest=PINNED_GUARD_DIGEST)
    return [current] if pinned==current else [current,pinned]


def verify_native(read,base):
    for at,expected in live_retained_pass_events.ATTEMPT_NATIVE_SPANS+pass_field_position.NATIVE_SPANS:
        if read(base+at,len(expected))!=expected:raise ValueError('Current pass-attempt native source changed')


def actor_manifest(events,actors):
    """Exactly the consumed sender/known completed-recipient identity fields."""
    roster=active_pass_network._actor_map(actors)
    used=set()
    for event in events:
        if event['flags_word']&8:continue
        used.add((event['side_index'],event['stored_player_slot']))
        if event['category']==7:used.add((event['side_index'],event['recipient_slot']))
    return [{'side_index':side,'stored_player_slot':slot,
             **{key:roster.get((side,slot),{}).get(key) for key in
                ('canonical_person_id','person_index_word','person_name')}} for side,slot in sorted(used)]


def project(events,actors,fixture,geometry,*,cursor,official_match_unique_id):
    if actors.get('official_match_unique_id')!=official_match_unique_id:
        raise ValueError('Current pass-attempt actors belong to another match')
    roster=active_pass_network._actor_map(actors);rows=[];seen=set()
    for event in events:
        for name, maximum in (('category',255),('flags_word',65535),('event_id',(1<<32)-1),
                              ('side_index',1),('stored_player_slot',255),('recipient_slot',255),
                              ('start',65535),('end',65535)):
            if type(event.get(name)) is not int or not 0<=event[name]<=maximum:
                raise ValueError('Invalid consumed current pass-attempt field '+name)
        if event['category'] not in active_pass_network.PASS_CATEGORIES:
            raise ValueError('Unsupported current pass-attempt category')
        if event['category'] not in active_pass_network.PASS_CATEGORIES or event['flags_word']&8:continue
        side,slot,identity=event['side_index'],event['stored_player_slot'],event['event_id']
        if (side not in (0,1) or type(slot) is not int or not 0<=slot<26 or identity in seen
                or not 0<=event['start']<=event['end']<cursor):
            raise ValueError('Invalid consumed current pass-attempt identity/actor/clock')
        seen.add(identity);completed=event['category']==7
        if completed and not 0<=event['recipient_slot']<26:
            raise ValueError('Invalid completed pass recipient slot')
        sender=roster.get((side,slot));recipient=roster.get((side,event['recipient_slot'])) if completed else None
        raw=bytearray(56)
        try:xy=bytes.fromhex(event['location_xy_hex'])
        except (KeyError,TypeError,ValueError) as error:raise ValueError('Current pass-attempt EVENT point unavailable') from error
        if len(xy)!=8:raise ValueError('Current pass-attempt EVENT point width differs')
        raw[24:32]=xy;raw[39:43]=bytes((slot,side,event['recipient_slot'],event['category']))
        struct.pack_into('<I',raw,44,identity);struct.pack_into('<H',raw,48,event['flags_word'])
        location=pass_field_position.project_event_location(bytes(raw),geometry,expected_event_id=identity,
                         expected_side_index=side,expected_player_slot=slot)
        team=fixture['home_team' if side==0 else 'away_team']
        rows.append({'event_id':identity,'side_index':side,'team_native_id':team['native_id'],
            'from_person_native_id':sender['canonical_person_id'] if sender else None,
            'from_name':sender.get('person_name') if sender else None,
            'sender_state':'canonical_original_slot' if sender else 'unresolved_original_slot',
            'stored_player_slot':slot,'recipient_slot':event['recipient_slot'] if completed else None,
            'to_person_native_id':recipient['canonical_person_id'] if recipient else None,
            'to_name':recipient.get('person_name') if recipient else None,
            'recipient_state':'canonical_completed_pass_recipient' if recipient else 'unresolved_completed_recipient' if completed else 'not_decoded_for_not_completed_attempt',
            'native_secondary_byte':event['recipient_slot'],
            'native_start_time_slice':event['start'],'native_end_time_slice':event['end'],
            'native_category_code':event['category'],'native_flags_word':event['flags_word'],
            'completed':completed,'outcome':'completed' if completed else 'not_completed',
            'specific_failure_reason':None,'possession_loss_event_link':None,'tactical_cause':None,
            **{key:location[key] for key in ('native_pass_map_location','attacked_goal_positive_native_y',
                'attack_relative_longitudinal_coordinate','absolute_lateral_centerline_distance',
                'inside_native_pitch_extents','analytical_pitch_third','analytical_lateral_channel')}})
    return sorted(rows,key=lambda row:row['event_id'])


def summarize(rows):
    bins=Counter((r['outcome'],r['analytical_pitch_third'],r['analytical_lateral_channel']) for r in rows)
    return {'event_count':len(rows),'completed_event_count':sum(r['completed'] for r in rows),
            'not_completed_event_count':sum(not r['completed'] for r in rows),
            'unresolved_sender_count':sum(r['sender_state']!='canonical_original_slot' for r in rows),
            'by_analytical_field_bin':[{'outcome':a,'analytical_pitch_third':b,'analytical_lateral_channel':c,'event_count':n}
                                      for (a,b,c),n in sorted(bins.items(),key=lambda item:repr(item[0]))],
            'scope':'Selected native event points; neither count subtraction nor possession-loss locations.'}


def current_pass_attempt_events(bridge,session_id,*,pass_outcome,team_native_id=None,from_person_native_id=None,
                                to_person_native_id=None,limit=50,cursor=None):
    if pass_outcome not in ('all','not_completed'):raise ValueError('Select all or not_completed pass outcomes')
    if to_person_native_id is not None:raise ValueError('Recipient filters require completed pass_outcome; incomplete secondary bytes are not recipient identities')
    for value in (team_native_id,from_person_native_id):
        if value is not None and (type(value) is not int or value<=0):raise ValueError('Positive canonical TEAM/PERSON IDs required')
    if type(limit) is not int or not 1<=limit<=100:raise ValueError('Active pass event limit must be 1..100')
    selectors=(pass_outcome,team_native_id,from_person_native_id,limit);now=time.monotonic()
    with bridge.lock:
        for key in list(_CACHE):
            if _CACHE[key]['expires']<now:del _CACHE[key]
        if cursor is not None:
            if type(cursor) is not str or cursor not in _CACHE:raise ValueError('Active pass attempt cursor expired or invalid')
            snapshot=_CACHE[cursor]
            if snapshot['session_id']!=session_id or snapshot['selectors']!=selectors:
                raise ValueError('Active pass attempt cursor belongs to another session or selectors')
            from .active_pass_locations import _verify_page
            _verify_page(bridge,session_id,snapshot);offset=snapshot['next_offset']
        else:
            network,packet,epoch=active_pass_network.current_pass_network(bridge,session_id,
                _include_locations=True,_include_pass_attempts=True,_return_private=True)
            if packet is None:return {**network,'events':None,'next_cursor':None,'total_selected_events':None}
            if team_native_id is not None and team_native_id not in {packet['fixture'][k]['native_id'] for k in ('home_team','away_team')}:
                raise ValueError('Selected team does not participate in this checked match')
            rows=project(packet['source']['events'],packet['actors'],packet['fixture'],packet['source']['pitch_geometry'],
                         cursor=packet['bound']['current_time_slice'],official_match_unique_id=packet['bound']['official_match_unique_id'])
            source_rows=[row for row in rows if (pass_outcome=='all' or not row['completed'])
                         and (team_native_id is None or row['team_native_id']==team_native_id)]
            unresolved=sum(row['sender_state']!='canonical_original_slot' for row in source_rows)
            rows=[row for row in source_rows if from_person_native_id is None or row['from_person_native_id']==from_person_native_id]
            metadata={key:value for key,value in network.items() if key not in ('sides','temporal_scope','actor_policy','coordinates','limits','state')}
            metadata.update(state='available_partial' if unresolved else 'available',
                temporal_scope='native_pass_attempts_start<=end<fixed_cursor; equality withheld',
                actor_policy='Canonical sender where original-slot identity resolves; recipient only native completed7; unresolved actors remain explicit',
                pass_outcome=pass_outcome,pass_attempt_policy=source_policy(),pass_field_summary=summarize(rows),
                unresolved_source_sender_count=unresolved,
                person_filter_coverage='partial_unknown_senders_cannot_be_attributed' if unresolved and from_person_native_id is not None else 'selected_native_actor_coverage',
                coordinates='official native pass-map EVENT point only',coordinate_units=None,human_left_right=None,
                release_location=None,reception_location=None,intended_destination=None,trajectory=None,
                possession_loss_events_included=False,counter_reconciliation='unavailable_at_fixed_current_prefix',
                limits=['Not-completed categories are not decoded interception/out-of-play causes or possession-loss events.',
                        'Native point is where the pass was played from, not its reception or intended destination; analytical bins are equal thirds.',
                        'Complete bounded event-vector coverage at a fixed cursor is not an independently reconciled attempted-pass denominator.'])
            snapshot={'rows':rows,'metadata':metadata,'packet':packet,'epoch':epoch,'session_id':session_id,'selectors':selectors,
                      'expires':now+120,'last_cursor':network['prefix_verification']['verified_at_time_slice']};offset=0
        end=min(offset+limit,len(snapshot['rows']));token=None
        if end<len(snapshot['rows']):
            token=secrets.token_urlsafe(24);_CACHE[token]={**snapshot,'next_offset':end}
            while len(_CACHE)>4:_CACHE.popitem(last=False)
        return deepcopy({**snapshot['metadata'],'events':snapshot['rows'][offset:end],'offset':offset,
            'total_selected_events':len(snapshot['rows']),'next_cursor':token,'capture_id':snapshot['metadata']['source_id'],
            'captured_observed_at':snapshot['metadata']['observed_at'],
            'pagination_policy':'Immutable fixed-prefix rows; identical selectors/limit, current original session/epoch/match and monotonic playback;120s expiry.'})
