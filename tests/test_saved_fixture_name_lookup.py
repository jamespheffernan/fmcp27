import struct
from io import BytesIO
import pytest
from fm_live_mcp import saved_fixture_name_lookup as lookup
from fm_live_mcp.saved_component_stream import Reader

ROW = struct.Struct('<b5i3I')

def table(count=7, *, refs=(0, 0, -1, 1, -1), bad=None, auxiliary=0):
    rows=[]
    for index in range(count):
        values=[0,*refs,index,900+index,100+index]
        if bad is not None and index==bad[0]:values[bad[1]]=bad[2]
        rows.append(ROW.pack(*values))
    return struct.pack('<IB',count,0)+b''.join(rows)+struct.pack('<I',auxiliary)+bytes(auxiliary*12)+struct.pack('<BI',1,17)

def context(count):
    return [dict(database_index=i,native_id=10+i,secondary_id=20+i,name=f'name{i}') for i in range(count)]

def test_unique_complete_source_and_batch_original_ids():
    data=b'x'*13+table()+b'z'*30
    out=lookup.lookup_from_buffer(data,[3,0,3,99],competitions=context(2),stage_names=context(2))
    assert out['table']['start']==13 and out['table']['search_complete']
    assert out['rows'][0]['native_id']==903 and out['rows'][0]['secondary_id']==103
    assert out['rows'][0]['primary_competition']['database_index']==0
    assert [x and x['database_index'] for x in out['rows'][0]['stage_names']]==[0,None,1]
    assert out['rows'][0]==out['rows'][2]
    assert out['rows'][3]==dict(database_index=99,state='out_of_range')

def test_ambiguous_even_when_second_table_cannot_hold_requested_row():
    with pytest.raises(ValueError,match='Ambiguous'):
        lookup.lookup_from_buffer(table(7)+b'padding'+table(4),[6],competitions=context(2),stage_names=context(2))

def test_false_geometry_never_promotes_and_repairs_fail_closed():
    bad=table(bad=(5,6,9))
    with pytest.raises(ValueError,match='No complete'):
        lookup.locate_fixture_name_table(bad,competition_count=2,stage_name_count=2)
    with pytest.raises(ValueError,match='repair'):
        lookup.locate_fixture_name_table(table(refs=(3,0,-1,1,-1)),competition_count=2,stage_name_count=2)
    # An unsupported-reference candidate must not be silently discarded in favour of another table.
    with pytest.raises(ValueError,match='Ambiguous'):
        lookup.locate_fixture_name_table(table()+table(refs=(3,0,-1,1,-1)),competition_count=2,stage_name_count=2)

def test_all_truncated_bounds_and_footer_auxiliary():
    data=table(4,auxiliary=2)
    for end in range(len(data)):
        with pytest.raises(ValueError):lookup.locate_fixture_name_table(data[:end],competition_count=2,stage_name_count=2)
    assert lookup.locate_fixture_name_table(data,competition_count=2,stage_name_count=2)['footer']['count']==2

def test_incomplete_budgets_do_not_choose_first_match(monkeypatch):
    monkeypatch.setattr(lookup,'MAX_ANCHOR_HITS',1)
    with pytest.raises(ValueError,match='incomplete'):
        lookup.locate_fixture_name_table(table()+b'\3\0\0\0',competition_count=2,stage_name_count=2)

def test_small_table_unavailable_not_empty():
    with pytest.raises(ValueError,match='unavailable or unsupported'):
        lookup.locate_fixture_name_table(table(3),competition_count=2,stage_name_count=2)

@pytest.mark.parametrize('indices',[[],[True],[-1],[2**31],list(range(501))])
def test_strict_indices(indices):
    with pytest.raises(ValueError):lookup.lookup_from_buffer(table(),indices,competitions=context(2),stage_names=context(2))

def test_stage_only_stored_name_and_ordinal():
    raw=b'\1'+struct.pack('<I',4)+b'name'+struct.pack('<III',0,7,8)
    row=lookup._stage_name(Reader(BytesIO(raw),len(raw)),0,-128)
    assert row['name']=='name' and 'short_name' not in row and row['secondary_id']==8
    with pytest.raises(ValueError,match='ordinal'):
        lookup._stage_name(Reader(BytesIO(raw),len(raw)),1,0)

def test_pin_is_mandatory_and_filename_checked():
    with pytest.raises(ValueError,match='exact snapshot'):
        lookup.load_fixture_name_lookup('example.fm',[1],expected_snapshot_id='')

def test_changed_pin_rejected_before_decoder(monkeypatch):
    from contextlib import contextmanager
    @contextmanager
    def checked(*args,**kwargs):yield object(),[],{}
    monkeypatch.setattr(lookup.snapshot_catalog,'checked_snapshot',checked)
    monkeypatch.setattr(lookup.snapshot_catalog,'snapshot_id',lambda value:'new')
    with pytest.raises(ValueError,match='Snapshot identity changed'):
        lookup.load_fixture_name_lookup('example.fm',[1],expected_snapshot_id='old')

@pytest.mark.parametrize('rows', [[None], [dict(database_index=True)], [dict(database_index=1)]])
def test_invalid_canonical_context_is_explicit(rows):
    with pytest.raises(ValueError, match='original ordinal'):
        lookup.lookup_from_buffer(table(), [0], competitions=rows, stage_names=context(2))


def test_text_budget_checked_while_collecting(monkeypatch):
    monkeypatch.setattr(lookup.saved_database_header, 'read_header', lambda reader: {})
    monkeypatch.setattr(lookup.saved_database_tables, 'reach_clubs', lambda reader: None)
    monkeypatch.setattr(lookup.saved_database, 'skip_table', lambda *args: None)
    visited = []
    def rows(*args):
        visited.append(0)
        yield dict(name='too long', short_name=None)
        visited.append(1)
        raise AssertionError('Should stop before retaining further rows')
    monkeypatch.setattr(lookup.saved_database, 'table', rows)
    monkeypatch.setattr(lookup, 'MAX_CONTEXT_TEXT_BYTES', 1)
    with pytest.raises(ValueError, match='text budget'):
        lookup._canonical_context(b'')
    assert visited == [0]


def test_replacement_on_checked_context_exit_discards_result_and_releases_slot(monkeypatch):
    from contextlib import contextmanager
    from types import SimpleNamespace
    @contextmanager
    def checked(*args, **kwargs):
        yield object(), [SimpleNamespace(path='root/game_db.dat')], {}
        raise ValueError('Snapshot changed during read')
    @contextmanager
    def component(*args):
        yield SimpleNamespace(offset=0, size=0,
                              source=SimpleNamespace(read=lambda n: b'', finished=True))
    monkeypatch.setattr(lookup.snapshot_catalog, 'checked_snapshot', checked)
    monkeypatch.setattr(lookup.snapshot_catalog, 'snapshot_id', lambda value: 'pin')
    monkeypatch.setattr(lookup.snapshot_catalog, '_metadata', lambda *args: {})
    monkeypatch.setattr(lookup.saved_component_stream, 'open_component', component)
    for _ in range(2):
        with pytest.raises(ValueError, match='Snapshot changed during read'):
            with lookup._checked_buffer('example.fm', 'pin', None):
                pass
