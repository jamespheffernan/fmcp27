"""Opaque slicing validates full genuine compressed members, including late failure."""
from hashlib import sha256
from dataclasses import replace
import os
import pytest
from fm_live_mcp import saved_component_slice as slices, snapshot_catalog, saved_player_history
import test_saved_competition_state as archives


def save(tmp_path,monkeypatch,raw=None):
    raw=bytes(range(256))*2000 if raw is None else raw
    monkeypatch.setattr(archives,'world_database',lambda _:b'UNKNOWN_DATABASE_BYTES')
    path=archives.archive(tmp_path/'opaque.fm',[],{'mystery/unknown.bin':raw})
    pin=snapshot_catalog.inspect_snapshot(path.name,directory=tmp_path,limit=1)['snapshot_id']
    return path,pin,raw


def query(source,**kw):
    path,pin,_=source
    return slices.get_component_slice(path.name,'career/mystery/unknown.bin',pin,directory=path.parent,**kw)


def test_full_hash_and_exact_pages_for_unknown_member(tmp_path,monkeypatch):
    src=save(tmp_path,monkeypatch);raw=src[2]
    first=query(src,offset=131071,limit=512)
    assert first['raw_hex']==raw[131071:131583].hex()
    assert first['member_sha256']==sha256(raw).hexdigest()
    assert first['end_offset']==first['next_offset']==131583
    assert first['returned_byte_count']==512 and first['total_size']==len(raw)
    assert first['source_qualification']['semantic_state'].startswith('opaque;')
    assert first['component_validation']['state']=='complete_frame_and_packed_bytes_rechecked'
    final=query(src,offset=len(raw)-3,limit=10)
    assert final['raw_hex']==raw[-3:].hex() and final['next_offset']is None
    empty=query(src,offset=len(raw))
    assert empty['raw_hex']=='' and empty['returned_byte_count']==0 and empty['next_offset']is None
    assert empty['member_sha256']==first['member_sha256']


@pytest.mark.parametrize('member',['../opaque.fm','/career/game_db.dat','career//game_db.dat','career/./game_db.dat','career/../game_db.dat','career\\game_db.dat','career/game_db.dat\x00','',None,1])
def test_bad_paths_before_disk(member):
    with pytest.raises(ValueError):slices.get_component_slice('missing.fm',member,'pin')


@pytest.mark.parametrize('kwargs',[{'offset':True},{'offset':-1},{'offset':2**30},{'limit':True},{'limit':0},{'limit':16385}])
def test_strict_pages_before_disk(kwargs):
    with pytest.raises(ValueError):slices.get_component_slice('missing.fm','career/game_db.dat','pin',**kwargs)


def test_missing_exact_path_stale_pin_and_outside(tmp_path,monkeypatch):
    src=save(tmp_path,monkeypatch);path,pin,raw=src
    for member in ['unknown.bin','mystery/unknown.bin','career/mystery/UNKNOWN.bin']:
        with pytest.raises(ValueError,match='missing or ambiguous'):
            slices.get_component_slice(path.name,member,pin,directory=tmp_path)
    with pytest.raises(ValueError,match='identity changed'):
        slices.get_component_slice(path.name,'career/mystery/unknown.bin','stale',directory=tmp_path)
    with pytest.raises(ValueError,match='outside'):query(src,offset=len(raw)+1)


def test_late_trailing_packed_bytes_fail_even_first_byte(tmp_path,monkeypatch):
    raw=bytes(range(256))*2000
    original=archives.compress
    monkeypatch.setattr(archives,'compress',lambda value:original(value)+(b'bad' if value==raw else b''))
    src=save(tmp_path,monkeypatch,raw)
    with pytest.raises(ValueError):query(src,limit=1)


def test_wrong_declared_extent_fails_even_first_byte(tmp_path,monkeypatch):
    src=save(tmp_path,monkeypatch)
    real=snapshot_catalog.checked_snapshot
    from contextlib import contextmanager
    @contextmanager
    def wrong(*args,**kwargs):
        with real(*args,**kwargs) as(handle,entries,identity):
            yield handle,tuple(replace(e,uncompressed_size=e.uncompressed_size-1) if e.path.endswith('unknown.bin') else e for e in entries),identity
    monkeypatch.setattr(snapshot_catalog,'checked_snapshot',wrong)
    with pytest.raises(ValueError):query(src,limit=1)


def test_snapshot_replacement_before_return_rejected(tmp_path,monkeypatch):
    src=save(tmp_path,monkeypatch)
    original=saved_player_history._component
    from contextlib import contextmanager
    @contextmanager
    def mutate(*args):
        with original(*args) as reader:yield reader
        path=src[0];stamp=path.stat();os.utime(path,ns=(stamp.st_atime_ns,stamp.st_mtime_ns+1))
    monkeypatch.setattr(slices,'_component',mutate)
    with pytest.raises(ValueError,match='changed during'):query(src,limit=1)


@pytest.mark.parametrize('field,value',[('uncompressed_size',512*1024**2+1),('compressed_size',256*1024**2+1),('uncompressed_size',0)])
def test_unsupported_member_budgets_fail_without_partial_return(tmp_path,monkeypatch,field,value):
    src=save(tmp_path,monkeypatch)
    real=snapshot_catalog.checked_snapshot
    from contextlib import contextmanager
    @contextmanager
    def oversized(*args,**kwargs):
        with real(*args,**kwargs) as(handle,entries,identity):
            yield handle,tuple(replace(e,**{field:value}) if e.path.endswith('unknown.bin') else e for e in entries),identity
    monkeypatch.setattr(snapshot_catalog,'checked_snapshot',oversized)
    with pytest.raises(ValueError,match='budget'):query(src,limit=1)


def test_ambiguous_exact_member_never_selected(tmp_path,monkeypatch):
    src=save(tmp_path,monkeypatch);real=snapshot_catalog.checked_snapshot
    from contextlib import contextmanager
    @contextmanager
    def duplicate(*args,**kwargs):
        with real(*args,**kwargs) as(handle,entries,identity):
            entry=next(e for e in entries if e.path.endswith('unknown.bin'))
            yield handle,(*entries,entry),identity
    monkeypatch.setattr(snapshot_catalog,'checked_snapshot',duplicate)
    with pytest.raises(ValueError,match='ambiguous'):query(src)


def test_full_archive_path_budget_does_not_narrow_valid_deep_names():
    # Archive directory permits8 names plus a1024-byte stem and extension.
    member='/'.join(['a'*1024]*8+['b'*2048])
    assert len(member)==slices.MAX_MEMBER_PATH
    assert slices._member_path(member)==member
    with pytest.raises(ValueError):slices._member_path(member+'x')
