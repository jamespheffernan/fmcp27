"""One scoped live capture, compact projections, and capture-free column discovery."""
from collections import OrderedDict
from datetime import datetime, timezone
import json
import secrets
import threading
import time

from .match_data_query import TABLES, capture_epoch, capture_live
from .live_match_participation import LINEUP_POLICY, field_registry as participation_registry

DEFAULT_FIELDS = {
    'fixtures': ['fixture_id','native_match_key','date','competition_id','competition','home_team_id','home_team','away_team_id','away_team','home_score','away_score','event_state'],
    'team_totals': ['fixture_id','native_match_key','side_index','team_index','shots','shots_on_target','expected_goals'],
    'retained_players': ['fixture_id','native_match_key','side_index','canonical_person_id','person_name','minutes','goals','assists','match_rating','expected_goals','shots','shots_on_target','passes_attempted','passes_completed','identity_state'],
    'events': ['fixture_id','source_index','person_index','side_code','kind_code','clock_word'],
    'goal_crossings': ['fixture_id','native_match_key','record_index','side_index','canonical_scorer_id','scorer_name','native_horizontal','native_height','height_band','coordinate_units','horizontal_viewpoint','identity_state'],
    'sub_entry_context': ['fixture_id','native_match_key','team_id','person_id','player','entry_minute','native_minutes','entry_state','evidence_state','score_for_before_entry','score_against_before_entry','personal_goals_after_entry'],
    'player_matches': ['row_id','person_index','player','date','minutes','goals','appearance_state','join_state'],
}


def column_catalog():
    """Inspect the shared empty projection schema; never attach or read the game."""
    from .match_dataset import build_connection
    from .saved_match_player_defensive import field_registry as defensive_registry
    from .saved_match_player_crosses import cross_field_registry
    from .saved_match_player_keeper import field_registry as keeper_registry
    from .match_player_position import field_registry as position_registry
    from .saved_match_player_recoveries import recovery_field_registry
    from .saved_match_player_progression import progression_field_registry
    from .saved_match_player_running import running_field_registry
    from .saved_match_player_sprinting import sprinting_field_registry
    from .saved_match_player_final_third import final_third_field_registry
    from .saved_match_player_free_kicks import free_kick_field_registry
    from .live_match_team_totals import crossing_field_registry as team_crossing_registry
    db = build_connection({'fixtures': []})
    try:
        catalog = {table: dict(columns=[row[1] for row in db.execute(f'PRAGMA table_info({table})')],
                            default_fields=DEFAULT_FIELDS[table],
                            requires_player_identities=table in ('retained_players','goal_crossings','sub_entry_context'),
                            source_policy='b129_scoring_credit_and_display_clock' if table=='sub_entry_context' else None,
                            field_provenance={**participation_registry(), **defensive_registry(), **cross_field_registry(), **keeper_registry(), **recovery_field_registry(), **progression_field_registry(), **running_field_registry(), **sprinting_field_registry(), **final_third_field_registry(), **free_kick_field_registry(), **position_registry()} if table=='retained_players' else team_crossing_registry() if table=='team_totals' else {}) for table in TABLES}
        guidance = 'For per-attempt origins/native xG, find an exact live result fixture_ref with fm_find_fixtures, then try fm_get_retained_shot_map. It can expose source-proved body parts, terminal outcomes and official native location bins; metric distances and human pitch viewpoint remain unproved. It returns conditional retained-source coverage, reconciled sides, and separate own-goal markers; unavailable is not zero and no full-season retention is promised.'
        for table in ('fixtures', 'team_totals', 'goal_crossings'):
            catalog[table]['how_to_query'] = guidance
        catalog['retained_players']['historical_lineup_policy']=dict(LINEUP_POLICY)
        catalog['retained_players']['possession_event_query'] = 'Use fm_get_retained_possession_events for exact retained fixture possession won/lost actors and counters. Raw native ancestry anchors are not proved transition points; no pressure-regain or beaten-press attribution.'
        catalog['retained_players']['key_pass_annotation_query'] = 'Use fm_get_retained_key_pass_annotations with an exact retained fixture for all-category native annotations, creators and same-event counter-qualified recipients/locations. Preserve full-side versus individual closure; no direct shot, goal or assist link is proved.'
        catalog['retained_players']['pressure_analysis_policy'] = 'Pressures_attempted and pressures_completed are distinct native counts. Use100*sum(completed)/sum(attempted) after checking all selected rows have counters and completed<=attempted; do not average row percentages or drop unknown rows. Zero attempts gives null rate. Statistical completions are not possession regains, beaten presses, locations or tactical causality.'
        catalog['goal_crossings']['limitations'] = 'Goal-line endpoints for credited goals, not all attempts or shot origins. The separate retained-shot tool may supply reconciled attempt origins for a sourced fixture.'
        return catalog
    finally:
        db.close()


def scoped_capture(bridge, session_id, team_id, date_from, date_to, competition_id, include_youth_reserves, include_players, include_goal_crossings=False):
    from .export_live_matches import capture_scope
    return capture_scope(bridge,session_id,team_id,date_from,date_to,competition_id,
                         capture=lambda b,s,refs:capture_live(b,s,refs,include_players=include_players,include_goal_crossings=include_goal_crossings),
                         max_matches=128, include_youth_reserves=include_youth_reserves,
                         capture_batch_size=16 if include_players else 64,
                         fixture_query=lambda sid,**query:bridge.find_fixtures(sid,selector_prefilter=True,**query))


class ScopedMatchQueries:
    def __init__(self, capture=None, epoch=None):
        self.capture = capture or scoped_capture
        self.epoch = epoch or capture_epoch
        self.pages = OrderedDict()
        self.lock = threading.RLock()

    def query(self, bridge, session_id, team_native_id, date_from, date_to, competition_native_id=None,
              tables=None, fields=None, limit=500, cursor=None, include_youth_reserves=False):
        tables = ['fixtures','team_totals'] if tables is None else tables
        if not isinstance(tables,list) or not tables or any(type(t) is not str or t not in TABLES for t in tables) or len(set(tables))!=len(tables):
            raise ValueError(f'tables must select distinct names from {TABLES}')
        if type(limit) is not int or not 1 <= limit <= 500:
            raise ValueError('limit must be 1–500.')
        catalog = column_catalog()
        if fields is not None and (not isinstance(fields,dict) or any(table not in tables for table in fields)):
            raise ValueError('fields must map requested tables to supported column lists.')
        projection = {}
        for table in tables:
            selected = (fields or {}).get(table,DEFAULT_FIELDS[table])
            if not isinstance(selected,list) or not selected or any(type(c) is not str or c not in catalog[table]['columns'] for c in selected) or len(set(selected))!=len(selected):
                raise ValueError(f'Unsupported fields for {table}; use fm_get_match_data_columns.')
            projection[table] = selected
        selectors = json.dumps([session_id,team_native_id,date_from,date_to,competition_native_id,tables,projection,include_youth_reserves],sort_keys=True)
        with self.lock:
            now = time.monotonic()
            for token in list(self.pages):
                if now-self.pages[token]['created']>300:
                    del self.pages[token]
            if cursor is not None:
                page = self.pages.get(cursor)
                if page is None or page['selectors']!=selectors:
                    raise ValueError('Expired cursor or changed selectors.')
                if self.epoch(bridge,session_id)!=page['epoch']:
                    del self.pages[cursor]
                    raise ValueError('Career/load epoch changed; start a fresh scoped capture.')
                offset = page['offset']
            else:
                from .match_dataset import build_connection
                epoch = self.epoch(bridge,session_id)
                include_players = any(table in tables for table in ('retained_players','goal_crossings','sub_entry_context'))
                captured = self.capture(bridge,session_id,team_native_id,date_from,date_to,competition_native_id,include_youth_reserves,include_players,include_goal_crossings='goal_crossings' in tables)
                if self.epoch(bridge,session_id)!=epoch:
                    raise ValueError('Career/load epoch changed during capture.')
                db=build_connection(captured['capture'],captured.get('player_rows',()),source='live_scoped_match_query',team_totals=captured.get('team_totals'),retained_players=captured.get('retained_players',()),goal_crossings=captured.get('goal_crossings',()),entry_state_policy=captured['capture'].get('entry_state_policy'))
                try:
                    rows=[];counts={}
                    for table,columns in projection.items():
                        result=db.execute('SELECT '+','.join('"'+c+'"' for c in columns)+' FROM '+table)
                        table_rows=[]
                        for values in result:
                            row=dict(zip(columns,values))
                            if 'raw_json' in row: row['raw_json']=json.loads(row['raw_json'])
                            table_rows.append(dict(table=table,row=row))
                        counts[table]=len(table_rows);rows.extend(table_rows)
                    metadata={key:json.loads(value) for key,value in db.execute('SELECT key,value_json FROM metadata')}
                    metadata['completion_policy']='Select stored result records inside explicit date bounds; actual completion remains unknown.'
                    metadata['coverage']=[dict(source=s,state=state,raw=json.loads(raw)) for s,state,raw in db.execute('SELECT * FROM coverage')]
                finally:
                    db.close()
                page=dict(selectors=selectors,epoch=epoch,created=time.monotonic(),rows=rows,counts=counts,metadata=metadata,projection=projection,
                          capture_id=secrets.token_urlsafe(16),observed_at=datetime.now(timezone.utc).isoformat())
                offset=0
            end=offset;size=0
            for row in page['rows'][offset:offset+limit]:
                row_size=len(json.dumps(row,ensure_ascii=False).encode())
                if row_size>262144: raise ValueError('One row exceeds response budget; select fewer fields.')
                if size+row_size>262144: break
                size+=row_size;end+=1
            next_cursor=None
            if end<len(page['rows']):
                next_cursor=secrets.token_urlsafe(24)
                self.pages[next_cursor]={**page,'offset':end}
                while len(self.pages)>32: self.pages.popitem(last=False)
            return dict(session_id=session_id,capture_id=page['capture_id'],observed_at=page['observed_at'],captured_save=page['metadata'].get('save'),fields=projection,
                        counts=page['counts'],rows=page['rows'][offset:end],next_cursor=next_cursor,metadata=page['metadata'],
                        historical_lineup_policy=dict(LINEUP_POLICY),
                        claim='One selected live capture shared by every requested projection; missing values remain unknown.')
