"""Bind a fresh retained report to preserved same-playthrough observation views."""
import argparse,hashlib,json,math
from pathlib import Path
from render_match_report import prepare_capture,render,load
from pass_location_evidence import add_pass_location_evidence

def prepare(capture_path,heatmaps_path,halves_path,pass_locations_path,observations_path,shot_proof_path,database_receipt_path):
    capture,manifest=load(capture_path,'Retained complete match capture')
    proof,proof_manifest=load(shot_proof_path,'Independent terminal-to-retained shot semantic closure')
    observations,observation_manifest=load(observations_path,'Preserved independently observed final-whistle and earlier-map views')
    db,db_manifest=load(database_receipt_path,'Registered fresh retained database readback')
    if proof['state']!='verified_all_27_terminal_retained_shot_semantics_exact' or proof['capture_sha256']!=manifest['sha256'] or not proof['not_official_UID_only'] or db['capture_artifact_sha256']!=manifest['sha256']:
        raise ValueError('Retained source proof/capture hash does not close')
    if proof['terminal_sha256'] not in [p['sha256']for p in observations['provenance']]:raise ValueError('Preserved views use another terminal observation')
    if hashlib.sha256(Path(db['path']).read_bytes()).hexdigest()!=db['sha256'] or not db['registered'] or not db['captured_query_readback']:raise ValueError('Retained database is not the verified immutable source')
    old_database=observations.get('observed_database')
    if old_database and (hashlib.sha256(Path(old_database['path']).read_bytes()).hexdigest()!=old_database['sha256'] or db['observed_run_untouched_sha256']!=old_database['sha256']):
        raise ValueError('Preserved observed-run database changed')
    record=capture['shot_maps'][0];old={(s['side_index'],s['event_id']):s for s in observations['shots']}
    if len(record['shots'])!=len(old):raise ValueError('Retained and terminal shot counts differ')
    for shot in record['shots']:
        previous=old[(shot['side_index'],shot['event_id'])]
        if any(shot[field]!=previous[field]for field in proof['fields']):raise ValueError('An actual shot tuple differs from terminal evidence')
        if shot['actor']['canonical_person_id']!=previous['actor']['canonical_person_id']:raise ValueError('Retained and original-roster actor projections differ')
    heat,heat_manifest=load(heatmaps_path,'Retained full-time tracking grids and explicitly selected player pools')
    if heat['native_match_key']!=record['native_match_key']:raise ValueError('Retained heat fixture differs')
    # The retained bridge is proved for shots only: never promote clipped tracking halves.
    full_heat={'native_match_key':heat['native_match_key'],'fixture':heat.get('fixture'),'full_match':heat['full_match']}
    data=prepare_capture(capture_path,(full_heat,{**heat_manifest,'source_fragment':'full_match only; tracking half assignment withheld'}),halves_path)
    data=add_pass_location_evidence(data,capture_path,pass_locations_path)
    if [t['native_id']for t in data['teams']]!=[t['native_id']for t in observations['teams']] or data['fixture']['date']!=observations['fixture']['date'] or data['score']!=observations['score']:raise ValueError('Fixture/score differs across source views')
    side_totals=[]
    for side in [0,1]:
        rows=[p for p in data['players']if p['side']==side]
        if any(type(p['pressures_attempted'])is not int or type(p['pressures_completed'])is not int or not 0<=p['pressures_completed']<=p['pressures_attempted'] for p in rows):raise ValueError('Pressure denominator unavailable/inconsistent')
        attempts=sum(p['pressures_attempted']for p in rows);completed=sum(p['pressures_completed']for p in rows)
        for p in rows:
            expected=100*p['pressures_completed']/p['pressures_attempted']if p['pressures_attempted']else None
            if p['pressure_completion_percentage_computed']!=expected:raise ValueError('Captured pressure ratio differs from raw counters')
        side_totals.append({'side_index':side,'stored_player_rows':len(rows),'pressures_attempted':attempts,'pressures_completed':completed,'pressure_completion_percentage_computed':100*completed/attempts if attempts else None,'pressure_completion_state':'available'if attempts else'undefined_zero_pressure_attempts'})
    data['pressure_evidence']={'state':'verified_captured_typed_pressure_counters_complete_roster','sides':side_totals,'raw_frame_sha256':capture['raw_frames'][0]['raw_sha256'],'source_provenance':{k:capture['capture']['action_field_provenance'][k]for k in ['pressures_attempted','pressures_completed','pressure_completion_percentage_computed']}}
    data['observations']=observations
    data['retained_database']={'path':db['path'],'file':Path(db['path']).name,'sha256':db['sha256'],'source_id':db['source_id']}
    data['retained_observation_binding']={'shot_semantic_closure':'all actual shot tuples and canonical actors exact','native_retained_pass_period_assignment':'unavailable; terminal half-by-half passing remains a separate observation source','new_raw_frame_sha256':capture['raw_frames'][0]['raw_sha256'],'new_raw_events_sha256':capture['receipt']['raw_events_sha256']}
    data['provenance'] += [proof_manifest,observation_manifest,db_manifest]
    return data

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for k in ['capture','heatmaps','halves','pass-locations','observations','shot-proof','database-receipt','output','receipt']:p.add_argument('--'+k,type=Path,required=True)
    a=p.parse_args();data=prepare(a.capture,a.heatmaps,a.halves,a.pass_locations,a.observations,a.shot_proof,a.database_receipt);receipt=render(data,a.output);a.receipt.parent.mkdir(parents=True,exist_ok=True);a.receipt.write_text(json.dumps(receipt,indent=2)+'\n');print(json.dumps({k:v for k,v in receipt.items()if k!='sources'}))
