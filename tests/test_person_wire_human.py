"""Portable HUMAN controls from four pinned sources plus adversarial boundaries."""
import ast
import builtins
import json
from pathlib import Path
import struct
import tracemalloc
import pytest
from fm_live_mcp.person_wire import human,parse_record

FIXTURES=json.loads(Path(__file__).with_name('person_wire_human_fixtures.json').read_text())


@pytest.mark.parametrize('fixture',FIXTURES,ids=lambda f:f['snapshot_id'][:12])
def test_four_checked_small_humans_keep_identity_and_names(fixture):
    raw=bytes.fromhex(fixture['raw_hex']);prefix=b'prefix'
    row=parse_record(prefix+raw+b'next',len(prefix),fixture['ordinal'],limit=len(prefix)+len(raw))
    assert row['state']=='decoded' and row['source_record_kind']=='HUMAN_NON_PLAYER'
    assert row['end']==len(prefix)+len(raw) and row['identity']['offset']==row['end']-12
    assert {k:row['identity'][k] for k in fixture['identity']}==fixture['identity']
    assert row['names']==fixture['names']
    assert row['human_wire_summary']['specific_payload_projected'] is False
    assert 'parts' not in row and '_scouting' not in row


def test_every_small_human_truncation_rejects_and_ordinal_must_match():
    f=FIXTURES[0];raw=bytes.fromhex(f['raw_hex'])
    for limit in range(len(raw)):
        with pytest.raises(ValueError):parse_record(raw,0,f['ordinal'],limit=limit)
    with pytest.raises(ValueError,match='ordinal|index|original'):
        parse_record(raw,0,f['ordinal']+1,limit=len(raw))


def test_human_unsupported_child_and_versions_stop_without_success():
    f=FIXTURES[0];raw=bytearray.fromhex(f['raw_hex'])
    # 17E7C5C entry is HUMAN body+74; an unsupported version must stop.
    raw[75]=255
    row=parse_record(raw,0,f['ordinal'],limit=len(raw))
    assert row['state']=='unsupported' and 'end' not in row and 'identity' not in row
    assert row['native_reader']=='0x17e7c5c'


def test_human_invalid_writer_presence_is_not_unavailable():
    f=FIXTURES[0];raw=bytearray.fromhex(f['raw_hex']);raw[1702]=2
    with pytest.raises(ValueError,match='presence'):parse_record(raw,0,f['ordinal'],limit=len(raw))


def test_human_does_not_copy_full_database_or_read_files(monkeypatch):
    f=FIXTURES[0];raw=bytes.fromhex(f['raw_hex']);data=bytearray(16*1024**2)+raw+b'tail'
    at=16*1024**2
    def forbidden(*args,**kw):raise AssertionError('Runtime filesystem access')
    monkeypatch.setattr(builtins,'open',forbidden)
    tracemalloc.start()
    row=parse_record(data,at,f['ordinal'],limit=len(data))
    _,peak=tracemalloc.get_traced_memory();tracemalloc.stop()
    assert row['state']=='decoded' and peak<512*1024
    assert data[at:at+len(raw)]==raw


def test_human_has_no_runtime_evidence_imports_or_io():
    root=Path(human.__file__).parent
    for path in root.glob('*.py'):
        text=path.read_text();tree=ast.parse(text)
        assert 'importlib' not in text and 'evidence/' not in text
        for node in ast.walk(tree):
            if isinstance(node,ast.Import):assert all(a.name in ('struct','functools') for a in node.names)
            if isinstance(node,ast.Call):
                name=node.func.id if isinstance(node.func,ast.Name) else getattr(node.func,'attr','')
                assert name not in ('open','read_bytes','read_text','spec_from_file_location','exec_module','eval','exec','__import__')


def test_human_explicit_profile_types_and_direct_child_work_guard(monkeypatch):
    f=FIXTURES[0];raw=bytes.fromhex(f['raw_hex'])
    for kw in ({'source_major':True},{'ordinal':True},{'minor':8}):
        args={'ordinal':f['ordinal'],**kw}
        with pytest.raises(ValueError):human.parse(raw,1,**args)
    monkeypatch.setattr(human,'MAX_DIRECT_CHILDREN',0)
    row=parse_record(raw,0,f['ordinal'],limit=len(raw))
    assert row['state']=='unsupported' and row['native_reader']=='0x12c2608'


def test_nonmaterializing_fixed_children_keep_constraints_and_boundaries():
    from fm_live_mcp.person_wire.human import child_138eee4 as marked,child_6e8330 as values
    from fm_live_mcp.person_wire.human import child_12ba224_4893974 as settings
    count=100000
    raw=struct.pack('<I',count)+bytes(4*count)+struct.pack('<I',count)+bytes(11*count)+struct.pack('<I',3)+bytes(12)
    tracemalloc.start();result=settings.parse(raw,0);_,peak=tracemalloc.get_traced_memory();tracemalloc.stop()
    assert result['end']==len(raw) and result['first_entries']is None and peak<64*1024
    with pytest.raises(ValueError):settings.parse(raw,0,limit=len(raw)-1)
    wrong=bytearray(raw);struct.pack_into('<I',wrong,len(raw)-16,4)
    with pytest.raises(ValueError,match='fixed count'):settings.parse(wrong,0)
    for fmt,stride in [(0,12),(1,9),(65535,9)]:
        data=struct.pack('<HH',65535,fmt)+bytes(65535*stride)
        assert values.parse(data,0)['end']==len(data)
        with pytest.raises(ValueError):values.parse(data,0,limit=len(data)-1)
    raw=struct.pack('<h',2)+b'\x01'+bytes(6)+b'\x01'+bytes(6)
    assert marked.parse(raw,0,reference_context=marked.RAW32)['end']==len(raw)
    altered=bytearray(raw);altered[9]=0
    with pytest.raises(ValueError,match='marker'):marked.parse(altered,0,reference_context=marked.RAW32)


def test_newly_reachable_selected_regular_player_has_fixed_scouting_values():
    from fm_live_mcp import saved_scouting_query as scouting
    f=json.loads(Path(__file__).with_name('person_wire_new_player_fixture.json').read_text())
    raw=bytes.fromhex(f['raw_hex']);row=parse_record(raw,0,f['person_index'],limit=len(raw),_include_scouting=True)
    assert row['state']=='decoded' and row['signed_tag']==2 and row['end']==len(raw)
    assert row['identity']['native_id_word']==row['identity']['secondary_word']==f['identity']['native_id']
    state,values,_=scouting._evaluate(row,f['criteria'],None,None,None)
    assert state=='matched' and values=={'ability.current':82,'ability.potential':111}
    assert [n['original_reference_index'] for n in row['names']]==[200420,406240,-1]


def test_cached_ui_marker_is_not_mistaken_for_a_boolean_wire_guard():
    f=FIXTURES[0];raw=bytearray.fromhex(f['raw_hex']);raw[1]=255
    #12C2704 compares exactly1; other values use a cached-object branch with no
    #stream child.12CC270 writes a virtual-method byte, not a proved Boolean.
    assert parse_record(raw,0,f['ordinal'],limit=len(raw))['state']=='decoded'


def test_canonical_projection_keeps_human_profile_limits_without_payload():
    from fm_live_mcp import saved_population as population
    f=FIXTURES[0];raw=bytes.fromhex(f['raw_hex']);row=parse_record(raw,0,f['ordinal'],limit=len(raw))
    class Layout:
        name_counts={'first':0,'second':0,'common':0}
    projected=population._project(raw,Layout(),row)
    assert projected['source_record_kind']=='HUMAN_NON_PLAYER'
    assert projected['human_wire_summary']['max_body_bytes']==32*1024**2
    assert projected['human_wire_summary']['specific_payload_projected']is False
    assert 'parts' not in projected and 'raw_hex' not in projected
