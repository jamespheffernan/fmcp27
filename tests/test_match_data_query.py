import pytest
from fm_live_mcp.match_data_query import MatchDataQueries


class Bridge:
    def __init__(self):
        self.checked = []
    def get_fixture(self, session_id, ref):
        self.checked.append((session_id, ref))
        return {'fixture': {'fixture_ref': ref}}


def source(bridge, session_id, refs):
    return {'capture': {'fixtures': [{'fixture': {'fixture_ref': ref, 'date': f'2026-01-0{i+1}'}} for i, ref in enumerate(refs)]}}


def test_projection_and_bound_cursor():
    query = MatchDataQueries(source, epoch=lambda b, s: getattr(b, 'epoch', 1))
    bridge = Bridge()
    first = query.query(bridge, 'session', ['f1', 'f2'], 'fixtures', ['fixture_ref'], 1)
    assert first['rows'] == [{'fixture_ref': 'f1'}]
    assert first['row_count'] == 2
    assert first['historical_lineup_policy']['formal_started'] is None
    assert first['historical_lineup_policy']['may_report_as_formal_starts'] is False
    second = query.query(bridge, 'session', ['f1', 'f2'], 'fixtures', ['fixture_ref'], 1, first['next_cursor'])
    assert second['rows'] == [{'fixture_ref': 'f2'}]
    assert second['next_cursor'] is None
    assert second['historical_lineup_policy']==first['historical_lineup_policy']
    assert bridge.checked == []  # fixture calendar changes cannot invalidate stored pages
    with pytest.raises(ValueError, match='changed selectors'):
        query.query(bridge, 'session', ['f2'], 'fixtures', ['fixture_ref'], 1, first['next_cursor'])


def test_rejects_identifiers_and_duplicate_refs():
    query = MatchDataQueries(source, epoch=lambda b, s: getattr(b, 'epoch', 1))
    with pytest.raises(ValueError, match='Supported fields'):
        query.query(Bridge(), 's', ['f1'], 'fixtures', ['raw_json;DROP TABLE fixtures'])
    with pytest.raises(ValueError, match='distinct'):
        query.query(Bridge(), 's', ['f1', 'f1'], 'fixtures')
    with pytest.raises(ValueError, match='table must'):
        query.query(Bridge(), 's', ['f1'], 'sqlite_master')


def test_reload_expires_cursor_but_clock_progression_preserves_capture():
    query = MatchDataQueries(source, epoch=lambda b, s: b.epoch)
    bridge = Bridge()
    bridge.epoch = ('pid', 'loaded-career-1')
    first = query.query(bridge, 's', ['f1', 'f2'], 'fixtures', ['date'], 1)
    # Changed fixture inventory/date does not change the already checked capture.
    bridge.clock = 'next day'
    second = query.query(bridge, 's', ['f1', 'f2'], 'fixtures', ['date'], 1, first['next_cursor'])
    assert second['observed_at'] == first['observed_at']
    assert second['rows'] == [{'date': '2026-01-02'}]
    bridge.epoch = ('pid', 'loaded-career-2')
    with pytest.raises(ValueError, match='epoch changed'):
        query.query(bridge, 's', ['f1', 'f2'], 'fixtures', ['date'], 1, first['next_cursor'])


def test_public_64_ref_capture_chunks_without_dropping_rows(monkeypatch):
    import fm_live_mcp.match_data_query as module
    calls=[]
    def batch(b,s,refs,*,include_players,include_goal_crossings=False):
        calls.append(list(refs))
        return dict(capture={'save':{'current_date':'2030-10-29'},'fixtures':[{'fixture_ref':r} for r in refs]},retained_players=[{'ref':r} for r in refs],team_totals={'records':[{'ref':r} for r in refs]},raw_frames=[{'ref':r} for r in refs])
    monkeypatch.setattr(module,'_capture_live_batch',batch)
    monkeypatch.setattr(module,'capture_epoch',lambda *_:('native-epoch',))
    refs=[f'f{i}' for i in range(64)]
    out=module.capture_live(None,'s',refs)
    assert list(map(len,calls))==[16,16,16,16]
    assert [r['ref'] for r in out['retained_players']]==refs
    assert len(out['capture']['fixtures'])==64
    assert len(out['raw_frames'])==64
    assert out['_live_capture_epoch']==('native-epoch',)
    assert '_live_capture_epoch' not in out['capture']
    calls.clear()
    module.capture_live(None,'s',refs,include_players=False)
    assert list(map(len,calls))==[64]


def test_chunk_capture_rejects_changed_save(monkeypatch):
    import fm_live_mcp.match_data_query as module
    dates=iter(['2030-10-29','2030-10-30'])
    def batch(*args,**kwargs):
        return dict(capture={'save':{'current_date':next(dates)},'fixtures':[]},retained_players=[],team_totals={'records':[]},raw_frames=[])
    monkeypatch.setattr(module,'_capture_live_batch',batch)
    monkeypatch.setattr(module,'capture_epoch',lambda *_:('native-epoch',))
    with pytest.raises(ValueError,match='no partial capture'):
        module.capture_live(None,'s',[f'f{i}' for i in range(32)])


def test_private_capture_stamp_rejects_a_real_epoch_change(monkeypatch):
    import fm_live_mcp.match_data_query as module
    epochs=iter([('load-a',),('load-b',)])
    monkeypatch.setattr(module,'capture_epoch',lambda *_:next(epochs))
    monkeypatch.setattr(module,'_capture_live_batch',lambda *a,**k:dict(capture={'save':{},'fixtures':[]},retained_players=[],team_totals={'records':[]},raw_frames=[]))
    with pytest.raises(ValueError,match='epoch changed'):
        module.capture_live(None,'s',['f'])
