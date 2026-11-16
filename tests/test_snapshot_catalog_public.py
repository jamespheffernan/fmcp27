"""Independent fixtures for the bounded disk-reader public contract."""
import ctypes
import ctypes.util
import os
from pathlib import Path
import struct

import pytest

from fm_live_mcp import snapshot_catalog as catalog


def compress(data):
    z = ctypes.CDLL(ctypes.util.find_library('zstd'))
    z.ZSTD_compress.argtypes = [ctypes.c_void_p,ctypes.c_size_t,ctypes.c_void_p,ctypes.c_size_t,ctypes.c_int]
    z.ZSTD_compress.restype = ctypes.c_size_t
    output = ctypes.create_string_buffer(len(data)+1024)
    n = z.ZSTD_compress(output,len(output),data,len(data),1)
    return output.raw[:n]


def archive(path):
    string = lambda b:struct.pack('<I',len(b))+b
    payload = compress(b'first')+compress(b'second')
    a = len(compress(b'first')); b = len(payload)-a
    table = string(b'career')+struct.pack('<I',2)
    for name,start,packed,raw in [(b'z',0,a,5),(b'a',a,b,6)]:
        table += string(name)+string(b'.dat')+struct.pack('<5Q',start,packed,raw,0,0)
    table += struct.pack('<I',0)
    offset = 26+len(payload)+9
    path.write_bytes(catalog.MAGIC+struct.pack('<Q',offset-18)+b'\0'*9+payload+catalog.MAGIC+compress(table))
    return path


def test_ordered_pagination_without_game_process(tmp_path):
    path = archive(tmp_path/'a.fm')
    first = catalog.inspect_snapshot(path.name,directory=tmp_path,limit=1)
    second = catalog.inspect_snapshot(path.name,directory=tmp_path,offset=1,limit=1)
    assert [first['components'][0]['path'],second['components'][0]['path']] == ['career/a.dat','career/z.dat']
    assert first['total'] == 2
    assert catalog.inspect_snapshot(path.name,directory=tmp_path,offset=2)['components'] == []


@pytest.mark.parametrize('offset,limit',[(True,1),(-1,1),(0,0),(0,501),(0,False)])
def test_pagination_bounds(tmp_path,offset,limit):
    with pytest.raises(ValueError):catalog.inspect_snapshot('a.fm',directory=tmp_path,offset=offset,limit=limit)


@pytest.mark.parametrize('mutation',['version','offset','compressed','footer'])
def test_malformed_archive(tmp_path,mutation):
    path=archive(tmp_path/'a.fm'); data=bytearray(path.read_bytes())
    offset=int.from_bytes(data[9:17],'little')+18
    if mutation=='version':data[6]=9
    if mutation=='offset':data[9:17]=(2**63).to_bytes(8,'little')
    if mutation=='compressed':data[offset:]=b'bad'
    if mutation=='footer':data[offset-9]=99
    path.write_bytes(data)
    with pytest.raises(ValueError):catalog.inspect_snapshot(path.name,directory=tmp_path)


@pytest.mark.parametrize('change',['in_place','replace'])
def test_change_during_read_rejected(tmp_path,change):
    path=archive(tmp_path/'a.fm')
    with pytest.raises(ValueError):
        with catalog.checked_snapshot(path.name,directory=tmp_path):
            if change=='in_place':
                with path.open('r+b') as f:f.seek(26);f.write(b'xxxx')
            else:
                other=archive(tmp_path/'replacement.fm');os.replace(other,path)


def test_path_scope_and_symlink(tmp_path):
    path=archive(tmp_path/'a.fm'); (tmp_path/'linked.fm').symlink_to(path)
    for name in ['../outside.fm','/tmp/outside.fm','linked.fm']:
        with pytest.raises((ValueError,OSError)):catalog.inspect_snapshot(name,directory=tmp_path)


def test_table_truncation_overlap_and_trailing(tmp_path):
    string=lambda b:struct.pack('<I',len(b))+b
    table=string(b'career')+struct.pack('<I',1)+string(b'a')+string(b'.dat')+struct.pack('<5Q',0,4,8,0,0)+struct.pack('<I',0)
    assert len(catalog._parse_table(table,4))==1
    for data,size in [(table[:-1],4),(table+b'!',4),(table,3),(table,5)]:
        with pytest.raises(ValueError):catalog._parse_table(data,size)
