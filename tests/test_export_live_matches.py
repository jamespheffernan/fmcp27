import pytest
from fm_live_mcp.export_live_matches import capture_scope

class Source:
    def __init__(self):self.calls=[]
    def get_save(self,sid):return {'save':{'current_date':'2030-10-28'}}
    def get_fixture_coverage(self,sid):return {'years':[{'year':2030,'all_groups_materialized':False}]}
    def find_fixtures(self,sid,**kw):
        self.calls.append(kw)
        if not kw['date_from']<='2030-10-26'<=kw['date_to']:
            return dict(save=self.get_save(sid)['save'],fixtures=[],next_cursor=None)
        def row(ref,kind=0):return {'fixture_ref':ref,'home_team':{'native_type_code':kind,'native_id':688},'away_team':{'native_type_code':0}}
        return dict(save=self.get_save(sid)['save'],fixtures=[] if 'cursor' not in kw else [row('senior'),row('youth',1)],next_cursor='next' if 'cursor' not in kw else None)

def test_empty_pages_continue_and_senior_scope():
    source=Source();captured=[]
    def capture(b,s,refs):
        captured.extend(refs)
        return dict(capture={'save':b.get_save(s)['save'],'fixtures':[]},retained_players=[],raw_frames=[])
    result=capture_scope(source,'session',688,'2029-10-01','2030-10-28',capture=capture)
    assert captured==['senior']
    assert result['capture']['unavailable_years']==[2029]
    assert any(call.get('cursor')=='next' for call in source.calls)
    assert source.calls[0]['team_native_id']==688

def test_budget_and_save_change_fail_closed():
    with pytest.raises(ValueError,match='page budget'):
        capture_scope(Source(),'s',688,'2030-01-01','2030-10-28',capture=lambda *a:None,max_pages=1)
    with pytest.raises(ValueError,match='ordered'):
        capture_scope(Source(),'s',688,'2031-01-01','2030-01-01',capture=lambda *a:None)


def test_include_club_other_teams_and_keep_unknown_opponent():
    class Mixed(Source):
        def find_fixtures(self,sid,**kw):
            return dict(save=self.get_save(sid)['save'],next_cursor=None,fixtures=[
                {'fixture_ref':'senior','home_team':{'native_id':688,'native_type_code':0},'away_team':None},
                {'fixture_ref':'youth','home_team':{'native_id':688,'native_type_code':1},'away_team':None}])
    seen=[]
    def capture(b,s,refs):
        seen.extend(refs);return {'capture':{'save':b.get_save(s)['save'],'fixtures':[]}}
    capture_scope(Mixed(),'s',688,'2030-10-26','2030-10-26',capture=capture)
    assert seen==['senior']
    seen.clear()
    capture_scope(Mixed(),'s',688,'2030-10-26','2030-10-26',capture=capture,include_youth_reserves=True)
    assert seen==['senior','youth']


def test_competition_only_selectors_and_required_scope():
    source=Source()
    def capture(b,s,refs):return {'capture':{'save':b.get_save(s)['save'],'fixtures':[]}}
    result=capture_scope(source,'s',None,'2030-10-25','2030-10-27',11,capture=capture)
    assert source.calls[0]['team_native_id'] is None
    assert source.calls[0]['competition_native_id']==11
    assert result['capture']['selectors']['competition_native_id']==11
    with pytest.raises(ValueError,match='team ID or competition'):
        capture_scope(Source(),'s',None,'2030-10-25','2030-10-27',capture=capture)


def test_clock_progress_is_recorded_with_same_load_epoch():
    class Moving(Source):
        world_identity=('same-load',)
        def __init__(self):super().__init__();self.day='2030-10-28'
        def get_save(self,sid):return {'save':{'name':'Career','created_date':'2025-10-23','current_date':self.day,'save_count':1 if self.day.endswith('28') else 2}}
        def find_fixtures(self,sid,**kw):
            self.day='2030-10-29'
            return {'save':self.get_save(sid)['save'],'fixtures':[],'next_cursor':None}
    result=capture_scope(Moving(),'s',688,'2030-10-26','2030-10-26',capture=lambda *args:None)
    assert result['capture']['observed_save_first']['current_date']=='2030-10-28'
    assert result['capture']['observed_save_last']['current_date']=='2030-10-29'
    assert result['capture']['cross_day_atomic'] is False


def test_expired_cursor_restarts_only_current_day():
    class Expiring(Source):
        def __init__(self):super().__init__();self.second_day_starts=0
        def find_fixtures(self,sid,**kw):
            self.calls.append(kw)
            def row(ref):return {'fixture_ref':ref,'home_team':{'native_id':688,'native_type_code':0}}
            if kw['date_from']=='2030-10-25':return {'save':self.get_save(sid)['save'],'fixtures':[row('first')],'next_cursor':None}
            if 'cursor' not in kw:
                self.second_day_starts+=1
                return {'save':self.get_save(sid)['save'],'fixtures':[row('stale' if self.second_day_starts==1 else 'fresh')],'next_cursor':'expired' if self.second_day_starts==1 else None}
            raise RuntimeError('Fixture cursor expired or belongs to a different query')
    source=Expiring();captured=[]
    def capture(b,s,refs):captured.extend(refs);return {'capture':{'save':b.get_save(s)['save'],'fixtures':[]}}
    result=capture_scope(source,'s',688,'2030-10-25','2030-10-26',capture=capture,window_days=1)
    assert captured==['first','fresh']
    assert len([c for c in source.calls if c['date_from']=='2030-10-25'])==1
    assert result['capture']['day_restart_count']==1


def test_native_reload_is_rejected_even_same_public_career():
    class Reloading(Source):
        world_identity=('old',)
        def find_fixtures(self,sid,**kw):
            self.world_identity=('new',)
            return {'save':self.get_save(sid)['save'],'fixtures':[],'next_cursor':None}
    with pytest.raises(ValueError,match='Loaded game identity changed'):
        capture_scope(Reloading(),'s',688,'2030-10-26','2030-10-26',capture=lambda *args:None)


def test_same_page_byte_change_retries_without_weakening_source():
    class Changing(Source):
        def __init__(self):super().__init__();self.attempts=0
        def find_fixtures(self,sid,**kw):
            self.attempts+=1
            if self.attempts==1:raise RuntimeError('Fixture query rejected: Game state changed during read; retry')
            return {'save':self.get_save(sid)['save'],'fixtures':[],'next_cursor':None}
    source=Changing();result=capture_scope(source,'s',688,'2030-10-26','2030-10-26',capture=lambda *args:None)
    assert source.attempts==2
    assert result['capture']['page_retry_count']==1


def test_persistent_expiry_stops_at_bounded_current_day_budget():
    class AlwaysExpired(Source):
        def __init__(self):super().__init__();self.attempts=0
        def find_fixtures(self,sid,**kw):
            self.attempts+=1
            raise RuntimeError('Fixture cursor expired or belongs to a different query')
    source=AlwaysExpired()
    with pytest.raises(RuntimeError,match='Fixture cursor expired'):
        capture_scope(source,'s',688,'2030-10-26','2030-10-26',capture=lambda *args:None)
    assert source.attempts==9


def test_clean_scope_uses_fast_windows_and_only_failed_window_splits():
    class Windows(Source):
        def __init__(self):super().__init__();self.failed=False
        def find_fixtures(self,sid,**kw):
            self.calls.append(kw)
            if kw['date_from']=='2030-07-15' and kw['date_to']!='2030-07-15' and not self.failed:
                self.failed=True
                raise RuntimeError('Game state changed during read; retry')
            return {'save':self.get_save(sid)['save'],'fixtures':[],'next_cursor':None}
    source=Windows();result=capture_scope(source,'s',688,'2030-07-01','2030-07-28',capture=lambda *args:None)
    assert len([c for c in source.calls if c['date_from']=='2030-07-01'])==1
    assert result['capture']['window_split_count']==1
    assert len(source.calls)==16
    assert source.calls[0]['record_budget']==1000
    assert source.calls[2]['record_budget']==100
    clean=Windows();clean.failed=True
    result=capture_scope(clean,'s',688,'2030-07-01','2030-10-28',capture=lambda *args:None)
    assert len(clean.calls)==9
    assert result['capture']['window_split_count']==0


def test_selected_frame_clock_mismatch_retries_same_verified_day():
    source=Source();attempts=[]
    def capture(b,s,refs):
        attempts.append(refs)
        if len(attempts)==1:raise ValueError('Save changed during selected-frame capture; no partial capture returned.')
        return {'capture':{'save':b.get_save(s)['save'],'fixtures':[]}}
    result=capture_scope(source,'s',688,'2030-10-26','2030-10-26',capture=capture)
    assert attempts==[['senior'],['senior']]
    assert result['capture']['page_retry_count']==1


def test_optional_shots_reuses_each_existing_batch_and_default_never_reads_shot_cache():
    source=Source(); packets=[]; reads=[]
    def capture(b,s,refs):
        packet={'capture':{'save':b.get_save(s)['save'],'fixtures':[]},'checked_epoch':'private-token'}
        packets.append(packet)
        return packet
    def shot_capture(b,s,refs,*,fixture_captures):
        assert fixture_captures is packets[-1]
        reads.append(list(refs))
        return {'records':[{'fixture_ref':ref} for ref in refs],'source_kind':'checked_retained_cache'}
    ordinary=capture_scope(source,'s',688,'2030-10-26','2030-10-26',capture=capture,shot_capture=shot_capture)
    assert reads==[] and 'shot_maps' not in ordinary
    result=capture_scope(source,'s',688,'2030-10-26','2030-10-26',capture=capture,
                         include_shot_map=True,shot_capture=shot_capture)
    assert reads==[['senior']]
    assert result['shot_maps']==[{'fixture_ref':'senior'}]


def test_optional_shot_capture_retry_recaptures_only_its_checked_batch():
    source=Source(); captured=[]; shots=[]
    def capture(b,s,refs):
        captured.append(list(refs))
        return {'capture':{'save':b.get_save(s)['save'],'fixtures':[]}}
    def shot_capture(b,s,refs,*,fixture_captures):
        shots.append(list(refs))
        if len(shots)==1:raise RuntimeError('Game state changed during read; retry')
        return {'records':[{'fixture_ref':ref} for ref in refs]}
    result=capture_scope(source,'s',688,'2030-10-26','2030-10-26',capture=capture,
                         include_shot_map=True,shot_capture=shot_capture)
    assert captured==[['senior'],['senior']]
    assert shots==captured
    assert result['capture']['page_retry_count']==1
    assert len(result['shot_maps'])==1


def test_optional_shots_require_each_ref_and_refuse_partial_packet_lists():
    with pytest.raises(ValueError,match='every selected fixture exactly once'):
        capture_scope(Source(),'s',688,'2030-10-26','2030-10-26',
                      capture=lambda b,s,refs:{'capture':{'save':b.get_save(s)['save'],'fixtures':[]}},
                      include_shot_map=True,shot_capture=lambda *args,**kwargs:{'records':[]})


def test_source_observed_export_requires_explicit_map_optin_and_forwards_it_once():
    with pytest.raises(ValueError,match='explicit shot-map'):
        capture_scope(Source(),'s',688,'2030-10-26','2030-10-26',include_source_observed_shots=True)
    calls=[]
    def capture(b,s,refs):return {'capture':{'save':b.get_save(s)['save'],'fixtures':[]}}
    def shots(b,s,refs,*,fixture_captures,include_source_observed):
        calls.append(include_source_observed)
        return {'records':[{'fixture_ref':r,'source_observed_policy':'checked'}for r in refs]}
    r=capture_scope(Source(),'s',688,'2030-10-26','2030-10-26',capture=capture,shot_capture=shots,
                    include_shot_map=True,include_source_observed_shots=True)
    assert calls==[True]
    assert r['capture']['source_observed_shots_requested'] is True
    assert r['shot_maps'][0]['source_observed_policy']=='checked'


def test_empty_scope_keeps_explicit_observed_capture_mode_without_inventing_rows():
    r=capture_scope(Source(),'s',688,'2030-11-01','2030-11-02',capture=lambda *a:pytest.fail('empty scope'),
                    include_shot_map=True,include_source_observed_shots=True,
                    shot_capture=lambda *a:pytest.fail('empty scope'))
    assert r['capture']['source_observed_shots_requested'] is True
    assert r['shot_maps']==[]
