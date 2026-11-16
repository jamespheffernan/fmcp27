"""Export explicitly scoped resident matches from the open game to a new SQLite file."""
import argparse
from datetime import date, timedelta
import json
from pathlib import Path

from .match_dataset import export_dataset


def _stable_career(save):
    """Simulation date and save-file counters advance without changing the career."""
    return {key:value for key,value in save.items()
            if key not in ('current_date','last_saved_date','save_count')}


def _transient_source_change(error):
    message=str(error).lower()
    return any(text in message for text in (
        'game state changed during read; retry','fixture cursor expired',
        'fixture reference identity expired','fixture bucket membership changed',
        'fixture identity changed','resident fixture inventory changed',
        'unknown or expired fixture reference','save changed during selected-frame capture'))


def capture_scope(bridge, session_id, team_id, date_from, date_to, competition_id=None,
                  *, capture=None, max_pages=500, max_matches=500, include_youth_reserves=False,
                  capture_batch_size=16, fixture_query=None, page_retries=2, day_restarts=2, window_days=14,
                  include_shot_map=False, shot_capture=None, include_source_observed_shots=False,
                  include_spatial=False, spatial_capture=None):
    """Capture strict fast windows, splitting only volatile windows into days.

    Completed windows survive later cursor expiry. No failed window is merged.
    Each native source still performs its original byte and identity rechecks.
    """
    if capture is None:
        from .match_data_query import capture_live
        capture=capture_live
    if type(include_spatial) is not bool:
        raise ValueError('include_spatial must be a boolean')
    if include_spatial and spatial_capture is None:
        from .retained_spatial_report import capture_spatial
        spatial_capture=capture_spatial
    if type(include_shot_map) is not bool:
        raise ValueError('include_shot_map must be a boolean')
    if type(include_source_observed_shots) is not bool or (include_source_observed_shots and not include_shot_map):
        raise ValueError('Source-observed shots require explicit shot-map capture')
    if include_shot_map and shot_capture is None:
        from .live_retained_shots import capture_retained_shot_maps
        shot_capture=capture_retained_shot_maps
    fixture_query=fixture_query or bridge.find_fixtures
    start,end=date.fromisoformat(date_from),date.fromisoformat(date_to)
    if start>end or end.year-start.year>5:
        raise ValueError('Select an ordered date interval spanning at most six calendar years')
    if team_id is None and competition_id is None:raise ValueError('Select a native team ID or competition ID')
    if team_id is not None and (type(team_id) is not int or team_id<=0):raise ValueError('team_id must be a positive native team ID')
    if type(capture_batch_size) is not int or not 1<=capture_batch_size<=64:raise ValueError('capture_batch_size must be 1–64')
    if any(type(v) is not int or not 0<=v<=2 for v in (page_retries,day_restarts)):raise ValueError('Recovery budgets must be 0–2')
    if type(window_days) is not int or not 1<=window_days<=31:raise ValueError('window_days must be 1–31')
    baseline=bridge.get_save(session_id)['save'];career=_stable_career(baseline)
    epoch=getattr(bridge,'world_identity',None)
    observed=[baseline];page_count=0;retry_count=0;restart_count=0
    def check_epoch():
        if epoch is not None and getattr(bridge,'world_identity',None)!=epoch:
            raise ValueError('Loaded game identity changed; attach again')
    def observe(save):
        check_epoch()
        if _stable_career(save)!=career:raise ValueError('Loaded career changed during scoped capture')
        if save!=observed[-1]:observed.append(save)
    def checked_call(call, retries=None):
        nonlocal retry_count
        limit=page_retries if retries is None else retries
        for attempt in range(limit+1):
            try:return call()
            except (ValueError,RuntimeError) as error:
                check_epoch()
                if not _transient_source_change(error) or attempt==limit:raise
                retry_count+=1
    coverage=checked_call(lambda:bridge.get_fixture_coverage(session_id))
    if coverage.get('save') is not None:observe(coverage['save'])
    known={row['year'] for row in coverage['years']} if 'years' in coverage else None
    unavailable=sorted({year for year in range(start.year,end.year+1) if known is not None and year not in known})
    combined=dict(save=baseline,fixtures=[],source_kind='running_session_active_fd',
      selectors=dict(team_native_id=team_id,date_from=date_from,date_to=date_to,competition_native_id=competition_id,
                     team_kind='all_selected_club_teams' if include_youth_reserves else 'senior_first_team'),
      fixture_coverage=coverage,unavailable_years=unavailable,game_writes=False,game_inputs=False,
      native_functions_executed=False,scope='Strictly rechecked historical day captures; existing resident results and retained active-bank frames only. Reads across days are not atomic.')
    if include_shot_map:combined['source_observed_shots_requested']=include_source_observed_shots
    players=[];totals=[];frames=[];crossings=[];shot_maps=[];spatial_reports=[];selected_count=0
    windows=[];cursor_day=start
    while cursor_day<=end:
        last=min(end,date(cursor_day.year,12,31),cursor_day+timedelta(days=window_days-1))
        if cursor_day.year not in unavailable:windows.append((cursor_day,last))
        cursor_day=last+timedelta(days=1)
    split_count=0;completed_windows=0
    while windows:
        day,window_end=windows.pop(0);small=day==window_end;fallback=False
        for restart in range(day_restarts+1):
            refs=[];day_batches=[]
            query=dict(year=day.year,team_native_id=team_id,competition_native_id=competition_id,
              date_from=day.isoformat(),date_to=window_end.isoformat(),record_kind='result',max_matches=100,
              record_budget=100 if small else 1000,bucket_budget=256 if small else 4096)
            try:
                while True:
                    def page_call():
                        nonlocal page_count
                        page_count+=1
                        if page_count>max_pages:raise ValueError('Fixture page budget exceeded; narrow selectors')
                        return fixture_query(session_id,**query)
                    page=checked_call(page_call,retries=None if small else 0);observe(page['save'])
                    for row in page['fixtures']:
                        own=[row.get(side) or {} for side in ('home_team','away_team')
                             if team_id is None or (row.get(side) or {}).get('native_id')==team_id]
                        if not own:raise ValueError('Fixture selector returned unrelated native team identity')
                        if include_youth_reserves or any(team.get('native_type_code')==0 for team in own):refs.append(row['fixture_ref'])
                    if selected_count+len(refs)>max_matches:raise ValueError('Fixture match budget exceeded; narrow selectors')
                    if page.get('next_cursor') is None:break
                    query['cursor']=page['next_cursor']
                if len(set(refs))!=len(refs):raise ValueError('Duplicate fixture references in day pages')
                for at in range(0,len(refs),capture_batch_size):
                    batch_refs=refs[at:at+capture_batch_size]
                    def capture_batch():
                        batch=capture(bridge,session_id,batch_refs)
                        if include_shot_map:
                            shot_options={'fixture_captures':batch}
                            if include_source_observed_shots:shot_options['include_source_observed']=True
                            shots=shot_capture(bridge,session_id,batch_refs,**shot_options)
                            returned=[row.get('fixture_ref') or (row.get('fixture') or {}).get('fixture_ref') for row in shots.get('records',())]
                            if len(returned)!=len(batch_refs) or set(returned)!=set(batch_refs):
                                raise ValueError('Shot capture must cover every selected fixture exactly once')
                            batch['shot_maps']=shots['records']
                            batch['capture']['shot_map_coverage']='per_fixture_side_checked_retained_source'
                            batch['capture']['source_observed_shots_requested']=include_source_observed_shots
                            batch['capture']['shot_map_source']={key:value for key,value in shots.items() if key not in ('records','save') and not key.startswith('_')}
                            if shots.get('save') is not None:observe(shots['save'])
                        if include_spatial:
                            reports=[spatial_capture(bridge,session_id,ref,fixture_captures=batch,include_native_heat_map=True) for ref in batch_refs]
                            for ref,report in zip(batch_refs,reports):
                                if (report.get('fixture') or {}).get('fixture_ref') != ref:
                                    raise ValueError('Spatial capture must cover each selected fixture exactly once')
                                if report.get('captured_save') is not None:observe(report['captured_save'])
                            batch['spatial_reports']=reports
                            batch['capture']['spatial_coverage']='per_fixture_guarded_retained_spatial_sources'
                        return batch
                    batch=checked_call(capture_batch,retries=None if small else 0)
                    observe(batch['capture']['save']);day_batches.append(batch)
                break
            except (ValueError,RuntimeError) as error:
                check_epoch()
                if not _transient_source_change(error):raise
                if not small:
                    windows[:0]=[(day+timedelta(days=i),day+timedelta(days=i)) for i in range((window_end-day).days+1)]
                    split_count+=1;fallback=True;break
                if restart==day_restarts:raise
                restart_count+=1
        if fallback:continue
        # Merge only the complete verified window. Earlier windows never restart.
        selected_count+=len(refs)
        for batch in day_batches:
            combined['fixtures'].extend(batch['capture']['fixtures'])
            for key,value in batch['capture'].items():
                if key not in ('save','fixtures'):combined[key]=value
            players.extend(batch.get('retained_players',()))
            totals.extend(batch.get('team_totals',{}).get('records',()))
            frames.extend(batch.get('raw_frames',()))
            crossings.extend(batch.get('goal_crossings',()))
            shot_maps.extend(batch.get('shot_maps',()))
            spatial_reports.extend(batch.get('spatial_reports',()))
        completed_windows+=1
    observe(checked_call(lambda:bridge.get_save(session_id))['save'])
    combined.update(pages=page_count,page_retry_count=retry_count,day_restart_count=restart_count,
       adaptive_window_days=window_days,window_split_count=split_count,completed_windows=completed_windows,
       observed_save_first=observed[0],observed_save_last=observed[-1],observed_save_change_count=len(observed)-1,
       save_identity='same_native_world_load_epoch_and_stable_career',cross_day_atomic=False)
    result=dict(capture=combined,retained_players=players,team_totals={'records':totals},raw_frames=frames,goal_crossings=crossings)
    if include_shot_map:
        combined.setdefault('shot_map_coverage','per_fixture_side_checked_retained_source')
        result['shot_maps']=shot_maps
    if include_spatial:result['spatial_reports']=spatial_reports
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--team-id',type=int,help='Selected club senior-team native ID; discover with fm_find_clubs / fixture identity')
    parser.add_argument('--date-from',required=True);parser.add_argument('--date-to',required=True)
    parser.add_argument('--competition-id',type=int)
    parser.add_argument('--include-youth-reserves',action='store_true',help='Include selected club non-senior teams; default selects its senior team only')
    parser.add_argument('--include-spatial',action='store_true',help='Include checked named pass edges, official tracking average positions and independently labeled heat/density grids when retained')
    parser.add_argument('--include-shot-map',action='store_true',help='Include checked retained shot-cache attempts, separate own-goal markers and explicit per-side source coverage; unavailable is not zero')
    parser.add_argument('--include-source-observed-shots',action='store_true',help='With --include-shot-map, preserve separately count/actor-verified candidates whose xG does not satisfy strict reconciliation; never adds to strict shots')
    parser.add_argument('--output',required=True,type=Path,help='New SQLite output path; existing files are refused')
    parser.add_argument('--register-capture',metavar='SOURCE_ID',help='Explicitly register this new historical export for captured-only MCP queries; never registers other files')
    args=parser.parse_args()
    if args.team_id is None and args.competition_id is None: parser.error('Select --team-id or --competition-id')
    if args.include_source_observed_shots and not args.include_shot_map:parser.error('--include-source-observed-shots requires --include-shot-map')
    if args.register_capture:
        from .captured_match_registry import check_registration_id
        check_registration_id(args.register_capture)
    if args.output.exists(): raise FileExistsError(f'Refusing to replace {args.output}')
    from .bridge import Bridge
    bridge=Bridge();sid=bridge.attach()['session_id']
    try:
        data=capture_scope(bridge,sid,args.team_id,args.date_from,args.date_to,args.competition_id,include_youth_reserves=args.include_youth_reserves,include_shot_map=args.include_shot_map,include_source_observed_shots=args.include_source_observed_shots,include_spatial=args.include_spatial)
        export_dataset(args.output,data['capture'],source='bounded_live_export',
                       retained_players=data['retained_players'],team_totals=data['team_totals'],
                       raw_frames=data['raw_frames'],goal_crossings=data.get('goal_crossings',()),
                       entry_state_policy=data['capture'].get('entry_state_policy'),field_provenance=data['capture'].get('action_field_provenance'),
                       shot_maps=data.get('shot_maps'),spatial_reports=data.get('spatial_reports'))
    finally:
        bridge.detach()
    receipt=dict(path=str(args.output.resolve()),fixtures=len(data['capture']['fixtures']),
                 retained_player_rows=len(data['retained_players']),raw_frames=len(data['raw_frames']))
    if args.include_shot_map:receipt['shot_map_packets']=len(data.get('shot_maps',()))
    if args.include_spatial:receipt['spatial_packets']=len(data.get('spatial_reports',()))
    if args.register_capture:
        from .captured_match_registry import register_capture
        from .captured_match_sources import _fingerprint
        try:
            digest,_=_fingerprint(args.output.resolve())
            receipt['registration']=register_capture(args.output,args.register_capture,digest)
        except (OSError,ValueError) as error:
            raise RuntimeError(f'Export preserved at {args.output.resolve()}, but explicit registration failed: {error}') from error
    print(json.dumps(receipt))


if __name__=='__main__':main()
