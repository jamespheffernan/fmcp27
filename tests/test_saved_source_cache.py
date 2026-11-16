from contextlib import contextmanager
from io import BytesIO
from types import SimpleNamespace
import ctypes
import os
import threading

import pytest

from fm_live_mcp import saved_source_cache as cache
from fm_live_mcp.saved_component_stream import _library


def packed(raw):
    lib = _library()
    lib.ZSTD_compress.argtypes = [ctypes.c_void_p, ctypes.c_size_t, ctypes.c_void_p, ctypes.c_size_t, ctypes.c_int]
    lib.ZSTD_compress.restype = ctypes.c_size_t
    out = ctypes.create_string_buffer(len(raw)+1024)
    size = lib.ZSTD_compress(out, len(out), raw, len(raw), 1)
    assert not lib.ZSTD_isError(size)
    return out.raw[:size]


def archive(raw, *, compression=None):
    value = packed(raw) if compression is None else compression
    return BytesIO(bytes(26)+value), SimpleNamespace(path='root/game_db.dat', start=0,
               compressed_size=len(value), uncompressed_size=len(raw))


@pytest.fixture(autouse=True)
def isolated(monkeypatch, tmp_path):
    cache.clear()
    root = tmp_path/'private'
    monkeypatch.setenv('FMCP_CACHE_DIR', str(root))
    yield root
    cache.clear()
    assert list(root.iterdir()) == [] if root.exists() else True


def test_immutable_hit_fresh_hash_no_redecode(monkeypatch):
    handle, entry = archive(b'abcdef'*100)
    calls = []
    original = cache.stream.open_component
    @contextmanager
    def counted(*args):
        calls.append(1)
        with original(*args) as reader:
            yield reader
    monkeypatch.setattr(cache.stream, 'open_component', counted)
    with cache.source(handle, entry, 'pin') as data:
        assert bytes(data) == b'abcdef'*100 and memoryview(data).readonly
        with pytest.raises(TypeError):data[0] = 0
    with cache.source(handle, entry, 'pin') as second:
        assert bytes(second) == b'abcdef'*100
    assert calls == [1] and cache.status()['state'] == 'hit'
    # Same identity and extent, changed original bytes cannot authorize a hit.
    handle.seek(26);handle.write(b'BAD!')
    with pytest.raises(ValueError):
        with cache.source(handle, entry, 'pin'):
            pass
    assert calls == [1,1]


def test_pin_component_and_packed_digest_all_key_the_cache():
    a, entry = archive(b'AAAA')
    with cache.source(a, entry, 'one') as first:assert bytes(first)==b'AAAA'
    with cache.source(a, entry, 'two') as second:assert bytes(second)==b'AAAA'
    b, changed = archive(b'BBBB')
    with cache.source(b, changed, 'two') as third:assert bytes(third)==b'BBBB'
    assert cache.status()['entries']==2


def test_disabled_unavailable_and_permissions_keep_memory_path(monkeypatch, tmp_path):
    h, e = archive(b'test')
    monkeypatch.delenv('FMCP_CACHE_DIR')
    with cache.source(h,e,'pin') as data:assert data is None
    for path in ('relative', str(tmp_path/'missing'/'child')):
        monkeypatch.setenv('FMCP_CACHE_DIR',path)
        with cache.source(h,e,'pin') as data:assert data is None
    if os.name == 'nt':
        return  # no permission bits on Windows: a folder's access is set by its access-control list
    public = tmp_path / 'public'
    public.mkdir()
    public.chmod(0o755)
    monkeypatch.setenv('FMCP_CACHE_DIR', str(public))
    with cache.source(h,e,'pin') as data:assert data is None


def test_truncation_trailing_frame_and_raw_extent_fail_closed(isolated):
    h,e=archive(b'data');h.truncate(len(h.getvalue())-1)
    with pytest.raises(ValueError):
        with cache.source(h,e,'pin'):pass
    for raw, compression in [(b'data',packed(b'data')+b'junk'),(b'wrong size',packed(b'data'))]:
        h,e=archive(raw,compression=compression)
        with pytest.raises(ValueError):
            with cache.source(h,e,'pin'):pass
    assert cache.status()['entries']==0


def test_lru_budget_and_active_lease_protect_mapping(monkeypatch):
    monkeypatch.setattr(cache,'MAX_BYTES',8)
    monkeypatch.setattr(cache,'MAX_ENTRIES',1)
    a,e=archive(b'aaaa');b,f=archive(b'bbbb')
    with cache.source(a,e,'a') as first:
        cache.clear()
        with pytest.raises(ValueError,match='leased'):
            with cache.source(b,f,'b'):pass
        assert bytes(first)==b'aaaa'
    with cache.source(b,f,'b') as second:assert bytes(second)==b'bbbb'
    assert cache.status()['cached_bytes']==4 and cache.status()['entries']==1
    with pytest.raises(ValueError):
        with cache.source(*archive(b'x'*9),'large'):pass


def test_concurrent_leases_and_exception_cleanup():
    a,e=archive(b'data');barrier=threading.Barrier(2);errors=[]
    def other():
        try:
            b,f=archive(b'data')
            with cache.source(b,f,'same') as data:
                barrier.wait(timeout=5);assert bytes(data)==b'data'
        except BaseException as error:errors.append(error)
    with cache.source(a,e,'same') as data:
        t=threading.Thread(target=other);t.start();barrier.wait(timeout=5)
        cache.clear();assert bytes(data)==b'data'
    t.join(timeout=5);assert not t.is_alive() and errors==[]
    with pytest.raises(RuntimeError):
        with cache.source(a,e,'same'):raise RuntimeError('caller failed')
    cache.clear();assert cache.status()['entries']==0


def test_source_changes_during_creation_are_not_published(monkeypatch):
    h,e=archive(b'AAAA');changed,_=archive(b'BBBB');original=cache._create
    def create(*args):
        value=original(*args)
        h.seek(0);h.write(changed.getvalue())
        return value
    monkeypatch.setattr(cache,'_create',create)
    with pytest.raises(ValueError,match='changed during creation'):
        with cache.source(h,e,'same'):pass
    assert cache.status()['entries']==0


def test_shared_adapter_fresh_context_exit_and_fallback(monkeypatch):
    from fm_live_mcp import saved_person_name_search as search
    h,e=archive(b'raw source');closed=[]
    @contextmanager
    def checked(*args,**kwargs):
        try:
            yield h,[e],{}
        finally:
            closed.append(True)
    monkeypatch.setattr(search.snapshot_catalog,'checked_snapshot',checked)
    monkeypatch.setattr(search.snapshot_catalog,'snapshot_id',lambda identity:'pin')
    monkeypatch.setattr(search.snapshot_catalog,'_metadata',lambda *args:{'status':'synthetic'})
    for enabled in (True,False):
        if not enabled:monkeypatch.delenv('FMCP_CACHE_DIR')
        with search._source('sample.fm','pin',None,locate=lambda data:'layout') as result:
            data,layout,pin,metadata=result
            assert bytes(data)==b'raw source' and layout=='layout' and pin=='pin'
            assert metadata=={'status':'synthetic'}
    assert closed==[True,True]
    @contextmanager
    def replaced(*args,**kwargs):
        yield h,[e],{}
        raise ValueError('Snapshot changed during request')
    monkeypatch.setattr(search.snapshot_catalog,'checked_snapshot',replaced)
    with pytest.raises(ValueError,match='changed during request'):
        with search._source('sample.fm','pin',None,locate=lambda data:'layout'):pass


def test_name_search_bytes_and_mapping_have_identical_witnesses():
    from fm_live_mcp import saved_person_name_search as search
    import struct
    class Layout:
        person_records_offset = 5
        person_count = 100
        name_counts = {'first': 2, 'second': 2, 'common': 0}
        def lookup_raw(self, namespace, index):
            return {'first': [b'Other', b'First'], 'second': [b'Other', b'Last']}[namespace][index]
    raw = (struct.pack('<IBB',100,1,1)+struct.pack('<iBiBiB',1,0,1,0,-1,0)
           +bytes(4+38+2+8)+struct.pack('<IIIb',7,0,999,2))
    expected=search.search_buffer(raw,Layout(),{'second':'last'},'exact')
    assert expected['candidates'][0]['identity']['stored_index']==7
    h,e=archive(raw)
    with cache.source(h,e,'pin') as data:
        assert search.search_buffer(data,Layout(),{'second':'last'},'exact')==expected


def test_spool_is_unlinked_even_while_being_filled(monkeypatch, isolated):
    h,e=archive(b'raw source');original=cache.stream.open_component
    @contextmanager
    def inspect(*args):
        assert list(isolated.iterdir())==[]
        with original(*args) as reader:yield reader
    monkeypatch.setattr(cache.stream,'open_component',inspect)
    with cache.source(h,e,'pin') as data:assert bytes(data)==b'raw source'


def test_scouting_cursor_survives_memory_to_mapping_transition(monkeypatch, isolated):
    from dataclasses import dataclass
    from fm_live_mcp import saved_population as population, saved_scouting_query as scout
    from fm_live_mcp import saved_person_name_search as search
    @dataclass
    class Layout:
        _data: object = None
        person_count: int = 3
        person_offset: int = 0
        person_records_offset: int = 0
        provenance: str = 'synthetic context transition only'
    h,e=archive(b'abc');layout=Layout()
    @contextmanager
    def checked(*args, **kwargs):yield h,[e],{}
    monkeypatch.setattr(search.snapshot_catalog,'checked_snapshot',checked)
    monkeypatch.setattr(search.snapshot_catalog,'snapshot_id',lambda identity:'pin')
    monkeypatch.setattr(search.snapshot_catalog,'_metadata',lambda *args:{'status':'verified','saved_simulation_date':'2030-10-23'})
    monkeypatch.setattr(population.saved_name_vectors,'locate',lambda data:layout)
    monkeypatch.setattr(population,'_LAST_LAYOUT',None)
    monkeypatch.setattr(population,'_PREFIXES',type(population._PREFIXES)())
    def read(data, at, ordinal, **kwargs):
        return {'state':'unsupported','signed_tag':6,'reason':'test frontier'} if ordinal==2 else {'state':'decoded','end':ordinal+1,'signed_tag':2,'ordinal':ordinal}
    monkeypatch.setattr(population,'_read_record',read)
    monkeypatch.setattr(scout,'_evaluate',lambda *args:('matched',{'ability.current':100},{'age':20}))
    monkeypatch.setattr(population,'_project',lambda data, layout, record:{'ordinal':record['ordinal']})
    monkeypatch.delenv('FMCP_CACHE_DIR')
    first=scout.find_players('sample.fm','pin',criteria={'ability.current':{'min':10}},limit=1)
    monkeypatch.setenv('FMCP_CACHE_DIR',str(isolated))
    second=scout.find_players('sample.fm','pin',criteria={'ability.current':{'min':10}},cursor=first['next_cursor'])
    assert first['matches'][0]['database_index']==0 and second['matches'][0]['database_index']==1
    assert second['component_sha256']==first['component_sha256']
    assert second['next_cursor'] is None and second['cumulative_counts']['matched']==2
    assert second['source_frontier']['ordinal']==2
