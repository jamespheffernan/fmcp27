"""Offline verifier rejects tampered physical/byte records; never opens a reader."""
import hashlib
import importlib.util
import json
from pathlib import Path
import struct

import pytest

HERE=Path(__file__).resolve().parents[1]/'evidence/knowledge-complete-identity-20261109'
spec=importlib.util.spec_from_file_location('complete_recorded',HERE/'check_recorded150.py')
v=importlib.util.module_from_spec(spec);spec.loader.exec_module(v)


def record(rows):
    return dict(regions=rows,sha256=hashlib.sha256(json.dumps(rows,separators=(',',':'),ensure_ascii=True).encode()).hexdigest(),
        truncated=False,region_count=len(rows),consumed_bytes=sum(r['size']for r in rows),
        bounds=dict(bytes=128*1024*1024,regions=4_000_000,per_read=16384))


def row(a,raw):return dict(address=hex(a),size=len(raw),rawhex=raw.hex())


def fixture(tmp_path):
    r=record([row(4096,b'AB'),row(5000,b'C')])
    headers=[];segments=[]
    physical=[(4096,b'AB',0),(5000,b'C',0),(4096,b'AB',1),(5000,b'C',1),(4096,b'AB',2),(5000,b'C',2)]
    digest=hashlib.sha256()
    for i,(a,raw,p)in enumerate(physical,1):
        headers.append(v.HEADER.pack(a,len(raw),p,i)+raw)
        digest.update(struct.pack('<QI',a,len(raw)));digest.update(raw)
    segments=[dict(ordinal=1,pid=42,process_started='offline',session_identity_sha256='session',helper='/offline/helper',requests=6,bytes=9,closed=True,requests_and_raw_sha256=digest.hexdigest())]
    r.update(physical_bounds=dict(bytes=8*1024*1024*1024,reads=64_000_000),physical_reads=6,physical_bytes=9,physical_phase_counts={'0':2,'1':2,'2':2},final_fence_passes=2)
    path=tmp_path/'audit.bin';path.write_bytes(b''.join(headers))
    return path,r,segments


def verify(path,r,s):return v.audit_verify(path,r,v.Journal(r),s,{'pid':42,'started':'offline'},'session','/offline/helper')


def test_complete_two_fence_physical_audit(tmp_path):
    p,r,s=fixture(tmp_path)
    result=verify(p,r,s)
    assert result['both_fences_cover_every_consumed_region']and result['every_segment_closed']


@pytest.mark.parametrize('change',['payload','sequence','phase','truncated','unconsumed','extra'])
def test_corrupted_audit_rejected(tmp_path,change):
    p,r,s=fixture(tmp_path);raw=bytearray(p.read_bytes())
    if change=='payload':raw[v.HEADER.size]^=1
    elif change=='sequence':raw[16]=2
    elif change=='phase':raw[12]=2
    elif change=='truncated':raw=raw[:-1]
    elif change=='unconsumed':raw[:8]=struct.pack('<Q',6000)
    else:raw.extend(b'X')
    p.write_bytes(raw)
    with pytest.raises(AssertionError):verify(p,r,s)


@pytest.mark.parametrize('field,value',[('pid',43),('process_started','other'),('session_identity_sha256','other'),('helper','other'),('closed',False),('requests',5),('bytes',8),('requests_and_raw_sha256','bad')])
def test_transport_binding_closure_count_or_digest_rejected(tmp_path,field,value):
    p,r,s=fixture(tmp_path);s[0][field]=value
    with pytest.raises(AssertionError):verify(p,r,s)


def test_merged_byte_reader_permits_only_recorded_consistent_overlap():
    j=v.Journal(record([row(4096,b'ABC'),row(4097,b'BCDE'),row(5000,b'Z')]))
    assert j.read(4096,5)==b'ABCDE'
    assert j.read(4098,2)==b'CD'
    for a,n in[(4095,1),(4100,2),(5001,1)]:
        with pytest.raises(ValueError,match='Missing recorded'):j.read(a,n)
    j.excluded.add(4097)
    with pytest.raises(ValueError,match='Missing recorded'):j.read(4096,2)


def test_conflicting_recorded_overlap_rejected():
    with pytest.raises(AssertionError,match='Conflicting journal overlap'):
        v.Journal(record([row(4096,b'ABC'),row(4097,b'Z')]))
