"""Render verified terminal observations with explicitly earlier spatial sources."""
import argparse,hashlib,json,sqlite3,math
from pathlib import Path
from render_match_report import load,render
from observed_report import prepare_registered

def prepare(terminal_path,spatial_path,passing_path,database_path=None,locations_path=None,session_evidence_path=None,shot_actors_path=None):
    terminal,t_manifest=load(terminal_path,'Strict current-playthrough terminal observation')
    spatial,s_manifest=load(spatial_path,'Earlier configured position means and sample-density observations')
    passing,p_manifest=load(passing_path,'Terminal native completed-pass pairs by verified period')
    clock=terminal['bound_playback']['current_time_slice']
    if terminal['state']!='verified_terminal_resident_source' or not terminal['verified_readset'] or terminal['displayed_period']!='FullTime' or clock!=terminal['bound_playback']['buffered_max_time_slice']:
        raise ValueError('Terminal observation is not strictly full time')
    raw=terminal['raw_source']['events'];rawsha=hashlib.sha256(bytes.fromhex(raw['hex'])).hexdigest()
    if rawsha!=raw['sha256'] or rawsha!=passing['terminal_native_event_bytes_sha256'] or passing['cutoff']!=clock or not passing['terminal']:
        raise ValueError('Passing and terminal source bytes/cutoff differ')
    fixture=terminal['fixture'];ids=[fixture[k]['native_id'] for k in ['home_team','away_team']]
    if [passing['fixture'][k]['native_id'] for k in ['home_team','away_team']]!=ids or passing['fixture']['date']!=fixture['date'] or passing['official_match_unique_id']!=terminal['bound_playback']['official_match_unique_id'] or passing['score']!=terminal['displayed_score']:
        raise ValueError('Current Forest source identity differs')
    shots=terminal['chance_breakdown']['shots'];periods=terminal['chance_breakdown']['periods']
    if terminal['chance_breakdown']['period_assignment_unknown']:
        raise ValueError('A terminal shot has no proved period')
    if any(not all(isinstance(row[k],(float,int)) and math.isfinite(row[k]) for k in ['expected_goals','native_x','native_y']) or not 0<=row['expected_goals']<=1 for row in shots):
        raise ValueError('Invalid terminal shot values')
    for period in periods:
        for side in period['sides']:
            selected=[s for s in shots if s['side_index']==side['side_index'] and s['period']==period['period']]
            if len(selected)!=side['shots'] or sum(s['outcome'] in ['goal','saved'] for s in selected)!=side['shots_on_target'] or abs(sum(s['expected_goals'] for s in selected)-side['expected_goals_sum_computed'])>1e-9:
                raise ValueError('Terminal half-shot totals disagree')
    for side in passing['sides']:
        for key in ['first','second']:
            if sum(p['count'] for p in side[key]['two_way_pairs'])!=side[key]['events']:
                raise ValueError('A passing-pair denominator does not close')
    if len(spatial['calls'])!=2 or len({c['source_id'] for c in spatial['calls']})!=1:
        raise ValueError('Earlier spatial sides have different sources')
    if session_evidence_path is None:
        raise ValueError('Spatial source withheld: a concrete same-session document-pair receipt is required')
    evidence,e_manifest=load(session_evidence_path,'Pinned same-session independently observed document pair')
    configured,c_manifest=load(Path(evidence['configured_spatial_path']),'Full configured earlier spatial responses and process receipt')
    if evidence['state']!='document_bound_independent_observations_same_running_FM_session' or evidence['terminal_document_sha256']!=t_manifest['sha256'] or evidence['terminal_event_sha256']!=rawsha or evidence['terminal_native_process_load_epoch']!=terminal['process_load_epoch'] or evidence['configured_spatial_document_sha256']!=c_manifest['sha256'] or evidence['configured_process'] not in configured['status']['processes'] or spatial['sha256']!=c_manifest['sha256']:
        raise ValueError('Spatial document pair/session receipt does not bind these exact observations')
    if len(configured['calls'])!=len(spatial['calls']):raise ValueError('Configured call count differs')
    for compact,full in zip(spatial['calls'],configured['calls']):
        r=full['result'];native_side=next(side for side in r['sides'] if side['team']['native_id']==compact['team_native_id'])
        if full['is_error'] or r['source_id']!=compact['source_id'] or r['current_time_slice']!=compact['cursor'] or r['save']!=terminal['save'] or r['heatmaps']['heat_map']!=compact['heat_map']:
            raise ValueError('Compact spatial scope differs from full configured source')
        original={p['canonical_person_id']:p for p in native_side['players']}
        for player in compact['players']:
            if any(original[player['canonical_person_id']][key]!=value for key,value in player.items()):raise ValueError('Compact spatial player values differ')
    for side,call in enumerate(spatial['calls']):
        v=call['prefix_verification'];h=call['heat_map']
        if call['team_native_id']!=ids[side] or call['cursor']>=clock or not v['canonical_actor_ids_rechecked'] or not v['same_match_ownership_rechecked'] or v['state']!='verified_fixed_prefix_under_monotonic_same_match_playback':
            raise ValueError('Earlier spatial source is not guarded')
        if sum(map(sum,h['counts_by_length_then_width']))!=h['coverage']['binned_samples']:
            raise ValueError('Density cells disagree with coverage')
    teams=[{'side_index':i,'native_id':fixture[k]['native_id'],'name':fixture[k]['owner']['name'],'short_name':fixture[k]['owner']['short_name']} for i,k in enumerate(['home_team','away_team'])]
    result = {'report_kind':'source_scoped_observations','match_key':None,'fixture':fixture,'score':terminal['displayed_score'],'teams':teams,'geometry':terminal['raw_source']['pitch_geometry'],'terminal_tick':clock,'shots':shots,'periods':periods,'passing':passing,'spatial':spatial,'players':[p for c in spatial['calls'] for p in c['players']],'average_nodes':[p for c in spatial['calls'] for p in c['players']],'provenance':[t_manifest,s_manifest,p_manifest,e_manifest,c_manifest],'source_identity':{'official_match_unique_id':terminal['bound_playback']['official_match_unique_id'],'terminal_event_sha256':rawsha,'process_load_epoch':terminal['process_load_epoch'],'spatial_source_id':spatial['calls'][0]['source_id']},'scope':'terminal chances/passing; earlier spatial snapshots; saved result/player statistics unavailable'}
    if database_path:
        database_path=database_path.resolve()
        connection=sqlite3.connect(database_path.as_uri()+'?mode=ro',uri=True)
        hashes=dict(connection.execute('SELECT source_id,sha256 FROM source_documents'))
        for role,manifest in [('terminal',t_manifest),('positions',s_manifest),('pass_periods',p_manifest)]:
            if hashes.get(role)!=manifest['sha256']:raise ValueError('Observed database source document differs from report')
        if connection.execute('SELECT COUNT(*) FROM shots').fetchone()[0]!=len(shots) or connection.execute('SELECT COUNT(*) FROM completed_pass_events').fetchone()[0]!=sum(s[k]['events'] for s in passing['sides'] for k in ['first','second']):
            raise ValueError('Observed database row counts differ')
        proof_row=connection.execute("SELECT sha256,original_path,document_json FROM source_documents WHERE source_id='terminal_continuity'").fetchone()
        if proof_row is None:raise ValueError('Observed database lacks terminal continuity proof')
        proof,proof_manifest=load(Path(proof_row[1]),'Same-playthrough terminal shot semantic continuity')
        if proof_manifest['sha256']!=proof_row[0] or proof['terminal_sha256']!=t_manifest['sha256'] or proof['state']!='verified_new_playthrough_terminal_semantic_continuity' or not all(c['all_match'] for c in proof['prior_capture_checks']):
            raise ValueError('Terminal continuity proof does not bind current input')
        result['terminal_continuity']={'full_semantic_fingerprint':proof['full_semantic_fingerprint'],'prior_shot_prefix_checks':len(proof['prior_capture_checks']),'scope':'Shot semantic witnesses, not spatial-byte identity'}
        result['provenance'].append(proof_manifest)
        connection.close()
        result['observed_database']={'path':str(database_path),'file':database_path.name,'sha256':hashlib.sha256(database_path.read_bytes()).hexdigest(),'kind':'observed_run_with_per_source_scopes_not_native_result_record'}
    if locations_path:
        locations,l_manifest=load(locations_path,'Offline projection of terminal completed-pass map event points')
        metadata=locations['metadata']
        if metadata['source_event56_sha256']!=rawsha or metadata['current_time_slice']!=clock or not metadata['same_owner_match_as_actual184'] or not metadata['same184_consumed815_xy_flags_ids_exact'] or not metadata['raw_source_verified_readset']:
            raise ValueError('Completed-pass location projection has different source')
        for side in passing['sides']:
            for phase,key in [('FirstHalf','first'),('SecondHalf','second')]:
                rows=[r for r in locations['events'] if r['team_native_id']==side['team_native_id'] and r['period']==phase]
                if len(rows)!=side[key]['events']:raise ValueError('Pass location period denominator differs')
                pairs={}
                for row in rows:
                    pair=tuple(sorted([row['from_name'],row['to_name']]))
                    pairs[pair]=pairs.get(pair,0)+1
                expected={tuple(sorted(p['pair'])):p['count'] for p in side[key]['two_way_pairs']}
                if pairs!=expected:raise ValueError('Pass location actor pairs differ')
        result['pass_locations']=locations;result['provenance'].append(l_manifest)
    if shot_actors_path:
        actors,a_manifest=load(shot_actors_path,'Additive verified original-roster shot actor projection')
        packet=actors['packet'];projected={(s['side_index'],s['event_id']):s for s in packet['shots']}
        if actors['state']!='passed_actual_frozen_same_match_projection' or actors['input_client_engine']!=terminal['raw_source']['source_identity'][:2] or actors['official_match_unique_id']!=terminal['bound_playback']['official_match_unique_id'] or actors['terminal_cursor']!=clock or not actors['all_cutoffs_preserved'] or len(projected)!=len(shots):
            raise ValueError('Shot actor projection does not bind this terminal source')
        for row in shots:
            projected_row=projected[(row['side_index'],row['event_id'])]
            for key in ['source_record_sha256','native_actor_slot','native_clock_start_raw','native_clock_end_raw','expected_goals','native_x','native_y','period','outcome']:
                if row[key]!=projected_row[key]:raise ValueError('Shot actor projection altered a source field')
            actor=projected_row['actor']
            if actor['side_index']!=row['side_index'] or actor['stored_player_slot']!=row['native_actor_slot'] or not actor.get('canonical_person_id') or not actor.get('person_name'):
                raise ValueError('Shot actor original slot/side is not bound')
            row['actor']=actor;row['actor_identity_state']=projected_row['actor_identity_state']
        result['shot_actor_projection']={'source_sha256':a_manifest['sha256'],'named_shots':len(shots),'immutable_database_actor_names_changed':False,'scope':'Additive same-record native original-roster projection; immutable database legacy actor_name remains null'}
        result['provenance'].append(a_manifest)
    return result

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    for key in ['terminal','spatial','passing','output','receipt']:parser.add_argument('--'+key,type=Path,required=True)
    parser.add_argument('--database',type=Path)
    parser.add_argument('--locations',type=Path)
    parser.add_argument('--session-evidence',type=Path,required=True)
    parser.add_argument('--shot-actors',type=Path)
    a=parser.parse_args();data=prepare(a.terminal,a.spatial,a.passing,a.database,a.locations,a.session_evidence,a.shot_actors);receipt=render(data,a.output);a.receipt.parent.mkdir(parents=True,exist_ok=True);a.receipt.write_text(json.dumps(receipt,indent=2)+'\n');print(json.dumps({k:v for k,v in receipt.items() if k!='sources'}))
