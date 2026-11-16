"""Native credited-assist annotations in attested observed CBE recordings.

Retained HUMAN copies can omit this flag. Never reconstruct missing annotations
from nearby passes or overload result goal-supplier conservation.
"""
from collections import Counter
from hashlib import sha256
import json
import struct

from . import observed_pass_locations
from .observed_assist_proof import COUNTER_PROOF as _COUNTER_PROOF, COUNTER_PROOF_SHA256 as _COUNTER_PROOF_SHA256
from .active_pass_network import _actor_map

TABLE = 'credited_assist_annotations'
COLUMNS = ('event_id','side_index','period','person_native_id','person_name','actor_state',
    'stored_player_slot','native_category_code','native_flags_word','start_tick','end_tick',
    'native_peer_slot','recipient_person_native_id','recipient_name','recipient_state',
    'native_key_pass_annotation','shot_event_id',
    'goal_event_id','provider_link_state')
ATTESTED_CAPTURE = '8e8a4d436d01525f20730c53b5abeaf67d75f8a762413e6da9ceb090236de873'
SCOPE = ('Observed terminal native credited-assist annotations, CBE flags mask4. '
         'Independently reconciled against all stored per-player Assists counters, including zero players. '
         'An annotation names the creator of this annotated event, not a generic event-to-shot/goal foreign key. '
         'shot_event_id and goal_event_id remain null; same-clock/proximity alone never supplies a link. '
         'Non-completed-pass categories retain unknown recipient semantics. '
         'Older retained HUMAN CBE copies can omit mask4; absence there is not zero assists.')


def project_assist_annotations(raw, actor_packet, counters, *, cutoff, intervals, rows_per_side, match_unique_id):
    if not isinstance(raw,bytes) or len(raw)%56 or len(raw)>8192*56 or type(cutoff)is not int or not 0<=cutoff<65536:
        raise ValueError('Unsupported assist annotation source extent or clock')
    if actor_packet.get('official_match_unique_id')!=match_unique_id:
        raise ValueError('Assist annotation actors belong to another match')
    roster=_actor_map(actor_packet)
    by_slot={};identities=set()
    for row in counters:
        side,slot,person,assists=(row.get(k)for k in('side_index','stored_player_slot','canonical_person_id','assists'))
        if (type(side)is not int or side not in(0,1) or type(slot)is not int or not 0<=slot<26
                or type(person)is not int or person<=0 or type(assists)is not int or not 0<=assists<=255
                or(side,slot)in by_slot or person in identities):
            raise ValueError('Invalid independent assist counter actor or value')
        by_slot[side,slot]=row;identities.add(person)
    if (not isinstance(rows_per_side,(list,tuple)) or len(rows_per_side)!=2
            or any(type(n)is not int or not 1<=n<=26 for n in rows_per_side)
            or [sum(side==s for side,_ in by_slot)for s in(0,1)]!=list(rows_per_side)):
        raise ValueError('Incomplete independent assist counter side sections')
    events=[];seen=set()
    for at in range(0,len(raw),56):
        e=raw[at:at+56];identity=int.from_bytes(e[44:48],'little')
        if identity in seen:raise ValueError('Duplicate native assist source event ID')
        seen.add(identity)
        if not e[48]&4:continue
        side,slot=e[40],e[39];start,end=struct.unpack_from('<H',e,34)[0],struct.unpack_from('<H',e,50)[0]
        if side not in(0,1)or(side,slot)not in by_slot or start>end or end>=cutoff:
            raise ValueError('Assist annotation actor, end-exclusive cutoff or clock differs')
        events.append((identity,side,slot,start,end,e))
    counts=Counter((side,slot)for _,side,slot,_,_,_ in events)
    if any(counts[key]!=row['assists']for key,row in by_slot.items()):
        raise ValueError('Native assist annotations do not close every independent player counter; missing is unknown')
    result=[]
    for identity,side,slot,start,end,e in events:
        actor=roster.get((side,slot));counter=by_slot[side,slot]
        if actor and actor['canonical_person_id']!=counter['canonical_person_id']:
            raise ValueError('Assist annotation original-slot and independent counter PERSON differ')
        periods=[name for name,a,b in intervals if a<=start<=end<b]
        if len(periods)>1:raise ValueError('Ambiguous assist annotation source period')
        # Only category7 has the separately proved completed-pass recipient.
        peer=roster.get((side,e[41]))if e[42]==7 and not e[48]&8 else None
        result.append(dict(zip(COLUMNS,(identity,side,periods[0]if periods else None,
            actor['canonical_person_id']if actor else None,actor.get('person_name')if actor else None,
            'canonical_original_slot'if actor and actor.get('person_name')else'canonical_original_slot_name_unknown'if actor else'unresolved_original_slot',
            slot,e[42],int.from_bytes(e[48:50],'little'),start,end,e[41],
            peer['canonical_person_id']if peer else None,peer.get('person_name')if peer else None,
            'canonical_completed_pass_recipient'if peer else'unproved_for_this_annotation',
            int(bool(e[48]&2)),None,None,
            'no_general_shot_or_goal_foreign_key_proved'))))
    return sorted(result,key=lambda r:r['event_id'])


def derive_assist_annotations(db,provenance):
    if provenance['capture_id']!=ATTESTED_CAPTURE:return None
    # Reuse the independently attested terminal/actor payload, fixture, period,
    # native-source and all1020 completed-event checks without any new read path.
    passing=observed_pass_locations.derive_pass_locations(db,provenance)
    if passing is None:raise ValueError('Observed assist source lacks the attested terminal/actor gate')
    docs={k:json.loads(v)for k,v in db.execute("SELECT source_id,document_json FROM source_documents WHERE source_id IN('terminal','pass_actors')")}
    terminal=docs['terminal'];packet=docs['pass_actors'];raw=bytes.fromhex(terminal['raw_source']['events']['hex'])
    intervals=db.execute('SELECT period,start_tick,end_tick FROM match_periods').fetchall()
    proof=_COUNTER_PROOF
    if sha256(json.dumps(proof,sort_keys=True,separators=(',',':')).encode()).hexdigest()!=_COUNTER_PROOF_SHA256:
        raise ValueError('Independent assist counter proof changed')
    rows=project_assist_annotations(raw,packet['actors'],proof['rows'],cutoff=terminal['bound_playback']['current_time_slice'],
        intervals=intervals,rows_per_side=proof['rows_per_side'],match_unique_id=terminal['bound_playback']['official_match_unique_id'])
    return {'columns':list(COLUMNS),'rows':rows,'scope':SCOPE,'provenance':{
        'state':'verified_derived_view','native_flag_mask':4,'native_plugin_sha256':observed_pass_locations.NATIVE_SHA256,
        'source_terminal_sha256':passing['provenance']['source_terminal_sha256'],
        'source_event56_sha256':passing['provenance']['source_event56_sha256'],
        'independent_retained_database_sha256':proof['retained_database_sha256'],
        'independent_retained_frame_sha256':proof['retained_frame_sha256'],
        'independent_native_match_key':proof['native_match_key'],
        'independent_counter_proof_sha256':_COUNTER_PROOF_SHA256,
        'checked_player_counters':len(proof['rows']),'all_independent_counter_checks_match':True,
        'annotation_presence_scope':'observed_terminal_only','positive_counter_players':sum(r['assists']>0 for r in proof['rows']),
        'checked_zero_counter_players':sum(r['assists']==0 for r in proof['rows']),
        'annotation_count':len(rows),'unresolved_actors':sum(r['actor_state']!='canonical_original_slot'for r in rows),
        'general_shot_or_goal_link_proved':False,'retained_annotation_absence_is_not_zero':True,'original_database_unchanged':True}}
