"""Official retained pass-map links, with a separately reconciled completion subset."""
from collections import Counter
import hashlib
import json
import struct

MAX_EVENTS=30000


def decode_pass_network(event_bytes, players):
    """Pure projection of complete CBE56 records and same-fixture canonical rows.

    Category7 is CBE_END_PASS_COMPLETED. The official map includes mask8 rows;
    their action meaning is unknown. Only publish the mask8-excluded completion
    subset when every captured individual counter independently agrees.
    """
    if not isinstance(event_bytes,bytes) or len(event_bytes)%56 or len(event_bytes)//56>MAX_EVENTS:
        raise ValueError('Unsupported retained pass event width or budget')
    events=[event_bytes[at:at+56] for at in range(0,len(event_bytes),56)]
    if any(e[42]==7 and e[40] not in (0,1) for e in events):raise ValueError('Unsupported pass event side')
    event_ids=[struct.unpack_from('<I',e,44)[0] for e in events]
    if len(set(event_ids))!=len(event_ids):raise ValueError('Duplicate retained event identities')
    sides=[]
    for side in (0,1):
        own=[p for p in players if p.get('side_index')==side]
        slots=[p.get('stored_player_slot') for p in own]
        if any(type(slot) is not int or not 0<=slot<26 for slot in slots) or len(set(slots))!=len(slots):
            raise ValueError('Ambiguous native player slot')
        roster=dict(zip(slots,own))
        mapped=[e for e in events if e[42]==7 and e[40]==side and e[39]<128 and e[41]<128]
        subset=[e for e in mapped if not e[48]&8]
        raw_pairs=Counter((e[39],e[41]) for e in mapped)
        subset_pairs=Counter((e[39],e[41]) for e in subset)
        counts=Counter(e[39] for e in subset)
        missing_slots=sorted({slot for pair in raw_pairs for slot in pair if slot not in roster})
        canonical=all(type(p.get('canonical_person_id')) is int and p['canonical_person_id']>0
                      and isinstance(p.get('person_name'),str) and p['person_name'] for p in own)
        canonical=canonical and len({p.get('canonical_person_id') for p in own})==len(own)
        valid_counters=bool(own) and all(type(p.get('passes_completed')) is int and p['passes_completed']>=0 for p in own)
        matches=valid_counters and not missing_slots and all(counts[slot]==p['passes_completed'] for slot,p in roster.items())
        state=('unavailable_player_rows' if not own else 'unavailable_actor_identity' if missing_slots or not canonical
               else 'available' if matches else 'unavailable_completed_counter_reconciliation')
        edges=[]
        if not missing_slots and canonical:
            for (sender,receiver),n in sorted(raw_pairs.items(),key=lambda item:(-item[1],item[0])):
                if sender==receiver:continue
                a,b=roster[sender],roster[receiver]
                edges.append({'from_person_native_id':a['canonical_person_id'],'from_name':a['person_name'],
                              'to_person_native_id':b['canonical_person_id'],'to_name':b['person_name'],
                              'official_map_count':n,
                              'counter_reconciled_completed_passes':subset_pairs[sender,receiver] if matches else None,
                              'excluded_unlabelled_mask8_count':n-subset_pairs[sender,receiver]})
        attempts=[p.get('passes_attempted') for p in own]
        attempts_valid=bool(own) and all(type(v) is int and v>=0 for v in attempts)
        coherent=valid_counters and attempts_valid and all(p['passes_attempted']>=p['passes_completed'] for p in own)
        player_counters=[]
        if not missing_slots and canonical:
            for slot,p in sorted(roster.items()):
                attempted,completed=p.get('passes_attempted'),p.get('passes_completed')
                valid=(type(attempted) is int and type(completed) is int and 0<=completed<=attempted)
                player_counters.append({'person_native_id':p['canonical_person_id'],'person_name':p['person_name'],
                                        'stored_player_slot':slot,
                                        'state':'available_official_player_counters' if valid else 'unavailable_player_counters',
                                        'passes_attempted':attempted if valid else None,
                                        'passes_completed':completed if valid else None,
                                        'passes_not_completed':attempted-completed if valid else None,
                                        'completion_events_reconciled':bool(matches)})
        sides.append({'side_index':side,'state':state,'official_map_record_count':len(mapped),
                      'excluded_unlabelled_mask8_count':len(mapped)-len(subset),
                      'counter_reconciled_completed_passes':len(subset) if matches else None,
                      'official_player_completed_sum':sum(p['passes_completed'] for p in own) if valid_counters else None,
                      'official_player_attempted_sum':sum(attempts) if attempts_valid else None,
                      'official_player_not_completed_sum':sum(attempts)-sum(p['passes_completed'] for p in own) if coherent else None,
                      'player_counters':player_counters,
                      'captured_player_counter_checks':len(own),'all_captured_player_counters_match':bool(matches),
                      'missing_actor_slots':missing_slots,'edges':edges})
    return {'sides':sides,'native_event_count':len(events),
            'policy':'official category7 map; mask8-excluded subset requires every captured player completion counter to reconcile',
            'unknown_fields':['mask8_action_meaning','attempted_pass_events','pair_completion_rate',
                              'origin_destination_route','coordinates','defensive_third','pressure','phase']}


def _verify_pass_native(bridge,session_id):
    from . import players
    with bridge.lock,bridge._read_scope(session_id):
        process=bridge._current(session_id);tables=bridge._player_layout(process)
        read,_,_=bridge._world_state(process,tables);base=tables[0]-players.RVA[0]
        for rva,expected in PASS_NATIVE_SPANS:
            if read(base+rva,len(expected))!=expected:raise ValueError('Official pass-map source binding changed')
        read.verify();bridge._current(session_id)


def capture_retained_pass_networks(bridge,session_id,fixture_refs,*,fixture_captures=None,coach_index=None):
    """Read selected retained owners once; reuse one epoch-stamped frame packet."""
    from .match_data_query import capture_epoch,capture_live
    from .live_retained_shots import capture_source,decode_attempts,_validate_team_oracle,_validated_actors
    if (not isinstance(fixture_refs,list) or not 1<=len(fixture_refs)<=16
            or any(not isinstance(r,str) or not r for r in fixture_refs) or len(set(fixture_refs))!=len(fixture_refs)):
        raise ValueError('Select1–16 distinct live fixture references')
    epoch=capture_epoch(bridge,session_id)
    packet=fixture_captures if fixture_captures is not None else capture_live(bridge,session_id,fixture_refs,include_players=True)
    if packet.get('_live_capture_epoch')!=epoch:raise ValueError('Frame packet belongs to another native capture epoch')
    items=packet['capture']['fixtures']
    if len(items)!=len(fixture_refs) or {i['fixture']['fixture_ref'] for i in items}!=set(fixture_refs):
        raise ValueError('Frame packet selection differs')
    keys=[i['native_match_key'] for i in items if type(i.get('native_match_key')) is int]
    if len(set(keys))!=len(keys):raise ValueError('Duplicate selected native fixture identity')
    _verify_pass_native(bridge,session_id)
    totals={r['result_key']:r for r in packet['team_totals']['records']}
    output=[]
    for item in items:
        fixture=item['fixture'];key=item['native_match_key'];ref=fixture['fixture_ref']
        base={'fixture':fixture,'fixture_ref':ref,'native_match_key':key,'source_kind':'active_human_retained_cbe',
              'saved_file_fallback':False,'atomic':False}
        if key not in totals:
            output.append({**base,'state':'unavailable_team_oracle','sides':[]});continue
        _validate_team_oracle(fixture,totals[key]['teams'])
        source=capture_source(bridge,session_id,ref,key,fixture,coach_index)
        if source['state']!='available':
            output.append({**base,'state':source['state'],'sides':[]});continue
        oracle=decode_attempts(source['vectors'],source['events'],totals[key]['teams'])
        players=[p for p in packet['retained_players'] if p.get('fixture_key',p.get('native_match_key'))==key]
        actors=_validated_actors(players,totals[key]['teams'])
        if len(actors)!=len(players):
            output.append({**base,'state':'unavailable_actor_team_identity','sides':[],
                           'fixture_shot_oracle':oracle['side_coverage']});continue
        result=decode_pass_network(source['events'],players)
        for side in result['sides']:
            team=fixture['home_team' if side['side_index']==0 else 'away_team']
            side.update(team_native_id=team['native_id'],team_name=(team.get('owner') or {}).get('name'))
        digest=hashlib.sha256(struct.pack('<i',key)+source['events']+json.dumps(players,sort_keys=True).encode()).hexdigest()
        output.append({**base,**result,'state':'available' if all(s['state']=='available' for s in result['sides']) else 'partial',
                       'source_id':digest,'owner_team_native_id':source['owner_team_native_id'],
                       'fixture_shot_oracle':oracle['side_coverage']})
    if capture_epoch(bridge,session_id)!=epoch:raise ValueError('Native load epoch changed during pass capture')
    return {'records':output,'captured_save':packet['capture']['save'],
            'source_kind':'active_human_retained_cbe','saved_file_fallback':False}


def summarize_pass_network(captured,team_native_id,*,minimum_matches=2,leaders=10,
                           ranking_basis='counter_reconciled_completed_passes'):
    """Compact repeated-pair report; never treat an unavailable fixture as zero."""
    if type(team_native_id) is not int or not 1<=team_native_id<=4294967295:raise ValueError('Invalid canonical team ID')
    if type(minimum_matches) is not int or not 1<=minimum_matches<=16:raise ValueError('minimum_matches must be1–16')
    if type(leaders) is not int or not 1<=leaders<=50:raise ValueError('leaders must be1–50')
    if ranking_basis not in ('counter_reconciled_completed_passes','official_map_count'):raise ValueError('Unsupported ranking basis')
    grouped={};fixtures=[]
    keys=[r['native_match_key'] for r in captured['records'] if type(r.get('native_match_key')) is int]
    if len(set(keys))!=len(keys):raise ValueError('Duplicate selected native fixture identity')
    for record in captured['records']:
        f=record['fixture'];own=[s for s in record['sides'] if s.get('team_native_id')==team_native_id]
        base={'native_match_key':record['native_match_key'],'fixture_ref':record['fixture_ref'],
              'date':f.get('date'),'home_team':(f.get('home_team',{}).get('owner') or {}).get('name'),
              'away_team':(f.get('away_team',{}).get('owner') or {}).get('name'),
              'home_team_native_id':(f.get('home_team') or {}).get('native_id'),
              'away_team_native_id':(f.get('away_team') or {}).get('native_id'),
              'competition':(f.get('competition') or {}).get('name'),
              'competition_native_id':(f.get('competition') or {}).get('native_id'),
              'final_score':(f.get('scores') or {}).get('final_score'),
              'source_state':record['state'],'source_id':record.get('source_id'),
              'source_coverage':[{k:v for k,v in s.items() if k!='edges'} for s in record['sides']]}
        if len(own)!=1:
            fixtures.append({**base,'state':'unavailable_selected_team_or_source'});continue
        side=own[0];base.update(state=side['state'],side_index=side['side_index'])
        available=side['state']=='available' if ranking_basis=='counter_reconciled_completed_passes' else bool(side['edges']) or side['state']=='available'
        if not available:
            fixtures.append(base);continue
        for edge in side['edges']:
            value=edge[ranking_basis]
            if value is None or value<=0:continue
            key=(edge['from_person_native_id'],edge['to_person_native_id'])
            if key not in grouped:
                grouped[key]={k:edge[k] for k in ('from_person_native_id','from_name','to_person_native_id','to_name')}
                grouped[key].update(matches_observed=0,official_map_count=0,
                                    counter_reconciled_completed_passes=0,fixture_contributions=[])
            group=grouped[key];group['matches_observed']+=1;group['official_map_count']+=edge['official_map_count']
            if edge['counter_reconciled_completed_passes'] is None:group['counter_reconciled_completed_passes']=None
            elif group['counter_reconciled_completed_passes'] is not None:group['counter_reconciled_completed_passes']+=edge['counter_reconciled_completed_passes']
            group['fixture_contributions'].append({'native_match_key':record['native_match_key'],'date':f.get('date'),
                                                    'official_map_count':edge['official_map_count'],
                                                    'counter_reconciled_completed_passes':edge['counter_reconciled_completed_passes']})
        fixtures.append(base)
    eligible=[g for g in grouped.values() if g['matches_observed']>=minimum_matches]
    eligible.sort(key=lambda g:(-g[ranking_basis],g['from_person_native_id'],g['to_person_native_id']))
    selected=eligible[:leaders];cutoff=selected[-1][ranking_basis] if selected else None
    omitted_ties=sum(g[ranking_basis]==cutoff for g in eligible[leaders:]) if cutoff is not None else 0
    return {'team_native_id':team_native_id,'captured_save':captured['captured_save'],
            'ranking_basis':ranking_basis,'minimum_matches':minimum_matches,'selected_fixture_count':len(fixtures),
            'counter_reconciled_fixture_count':sum(f['state']=='available' for f in fixtures),
            'eligible_pair_count':len(eligible),'returned_pair_count':len(selected),'omitted_cutoff_ties':omitted_ties,
            'pairs':selected,'fixtures':fixtures,'source_kind':'active_human_retained_cbe','saved_file_fallback':False,
            'limits':['Completed passes means only the all-captured-player-counter-reconciled subset; official map counts are separate.',
                      'Player attempted/completed counters come from the selected historical player rows. Not-completed is their arithmetic difference, not a decoded failed-pass event or named recipient.',
                      'Mask8 action meaning is unknown; it is not labelled open play, throw-in or pressure.',
                      'No per-pair attempts, completion rate, route coordinates, pitch-third, phase or pressure inference.',
                      'Coverage is only selected retained sources; unavailable fixtures are unknown, not zero.',
                      'Repeated full-match combinations do not establish how a team played out or a pressing vulnerability.']}


PASS_NATIVE_SPANS = (
    (0x52da373, b'CBE_END_PASS_COMPLETED\0'),
    (0x489b188, bytes.fromhex('e8008052e8630039ff1300f9e15100f021cc0d91606200910200801255b7eb97')),
    (0x29b290, bytes.fromhex('886e8952888ea9723f03086b21940054e00314aae10313aa0200805270100094')),
    (0x29bbb8, bytes.fromhex('36008052e00314aae10313aa22008052290e009404060014bf7f31a9806a40f9')),
    (0x29f52c, bytes.fromhex('e8430091e2e30091e10315aae30314aa240080520500805206008052070080525f16fc97')),
    (0x1a54a4, bytes.fromhex('08ab40391f1d0071c1feff5408000014e89b41b9e99f41b90aab40391f00086b00a0497a40d9477ac1fdff5408a34039e94340f91f01296b41fdff5408a7c03908fdff37e00318aa5ac11b95e80300aa')),
    (0x4893d10, bytes.fromhex('289cc03929a4c0394a03805217250a1b')),
    (0x1a55ac, bytes.fromhex('a92e41f9a82a41f9290108cb5f0f89ebe2fdff5408797af8a8fdffb4')),
)
