"""Actual Mach-read coverage for competition assignment selection."""
import json
import subprocess
import sys

import pytest

from test_native import HELPER, native, pytestmark


@pytest.fixture
def team_target():
    code = r'''
import ctypes,json,os,struct,sys
keep=[]
def buf(data):
 b=ctypes.create_string_buffer(data);keep.append(b);return ctypes.addressof(b)
def vector(entries):
 start=buf(struct.pack('<'+str(len(entries))+'Q',*entries))
 return start,buf(struct.pack('<3Q',start,start+len(entries)*8,start+len(entries)*8))
entries=[]
# Current, next, secondary, next secondary, owner, national, unequal IDs.
for i,values in enumerate([(0x3000,0,0,0,0x4000,0,0),(0x3000,0x5000,0x3000,0,0x4000,1,1),
                           (0x5000,0x3000,0x5000,0x3000,0x4000,0,1),(0x3000,0,0x3000,0,0,1,0)]):
 current,next_,secondary,next_secondary,owner,national,random=values
 d=bytearray(0x78);struct.pack_into('<QIII',d,0,0x22200 if national else 0x11100,i,i+100,i+900 if random else i+100)
 struct.pack_into('<Q',d,0x30,owner)
 for offset,value in zip((0x50,0x58,0x68,0x70),(current,next_,secondary,next_secondary)):struct.pack_into('<Q',d,offset,value)
 entries.append(buf(bytes(d)))
start,header=vector(entries)
short_start,short=vector(entries[:2]);_,wrong=vector(list(reversed(entries)))
empty=buf(bytes(24))
print(json.dumps({'pid':os.getpid(),'start':start,'header':header,'short':short,'wrong':wrong,'empty':empty,'entries':entries}),flush=True)
for line in sys.stdin:
 if line.strip()=='exit':break
 address,fmt,value=json.loads(line);data=struct.pack(fmt,value);ctypes.memmove(address,data,len(data));print('changed',flush=True)
'''
    child = subprocess.Popen([sys.executable, '-c', code], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
    target = json.loads(child.stdout.readline())
    target['child'] = child
    try:
        yield target
    finally:
        child.communicate('exit\n', timeout=5)


def arguments(target, assignment='current', lookup='header', start=0, budget=200000, maximum=100):
    return ['--list-header', str(target['header']), '--list-start', str(target['start']),
            '--lookup-header', str(target[lookup]), '--list-count', '4', '--start-index', str(start),
            '--record-budget', str(budget), '--max-matches', str(maximum),
            '--team-primary', str(0x11100), '--national-team-primary', str(0x22200),
            '--competition', str(0x3000), '--team-assignment', assignment]


@pytest.mark.parametrize('assignment,indices', [('current', [0,1]), ('next', [0,2,3]),
                                                ('secondary', [1,3]), ('next_secondary', [1,2,3])])
def test_assignment_branches_include_national_random_ids_and_native_fallback(team_target, assignment, indices):
    result = native(team_target, 'scan-team-index', *arguments(team_target, assignment))
    assert [row['database_index'] for row in result['matches']] == indices
    assert result['teams_examined'] == result['scanned_records'] == result['next_index'] == 4
    assert result['national_teams_examined'] == 2
    assert result['lookup_unavailable_records'] == 0 and result['stop_reason'] == 'table_end'


def test_pagination_counts_match_limits_and_empty_pages(team_target):
    first = native(team_target, 'scan-team-index', *arguments(team_target, maximum=1))
    assert first['next_index'] == first['scanned_records'] == 1 and first['stop_reason'] == 'match_limit'
    second = native(team_target, 'scan-team-index', *arguments(team_target, start=1, budget=1))
    assert second['next_index'] == 2 and second['scanned_records'] == 1 and second['stop_reason'] == 'record_budget'
    last = native(team_target, 'scan-team-index', *arguments(team_target, start=2))
    assert last['matches'] == [] and last['next_index'] == 4 and last['scanned_records'] == 2
    assert last['stop_reason'] == 'table_end'


@pytest.mark.parametrize('lookup,count,unavailable', [('short',2,2),('empty',0,4)])
def test_selected_lookup_has_no_canonical_fallback(team_target, lookup, count, unavailable):
    result = native(team_target, 'scan-team-index', *arguments(team_target, lookup=lookup))
    assert len(result['matches']) == count
    assert result['teams_examined'] == count and result['lookup_unavailable_records'] == unavailable
    assert result['scanned_records'] == 4


@pytest.mark.parametrize('fault', ['lookup','index','type','zero_id','pointer','bounds','unreadable'])
def test_invalid_identity_or_table_fails_entire_scan(team_target, fault):
    target = team_target
    changes = {'index':(target['entries'][1]+8,'<I',9),'type':(target['entries'][1],'<Q',0x99900),
               'zero_id':(target['entries'][1]+12,'<I',0),'pointer':(target['start']+8,'<Q',1),
               'bounds':(target['header']+8,'<Q',target['start']-8),
               'unreadable':(target['entries'][1]+0,'<Q',0x99900)}
    if fault != 'lookup':
        change = changes[fault]
        if fault == 'unreadable': change = (target['start']+8,'<Q',0x1000)
        child = target['child']; child.stdin.write(json.dumps(change)+'\n');child.stdin.flush()
        assert child.stdout.readline().strip() == 'changed'
    result = subprocess.run([str(HELPER),'scan-team-index','--pid',str(target['pid']),
                             *arguments(target, lookup='wrong' if fault=='lookup' else 'header')],
                            capture_output=True,text=True,timeout=10)
    assert result.returncode != 0 and json.loads(result.stdout)['ok'] is False


@pytest.mark.parametrize('assignment', ['unknown','CURRENT',''])
def test_invalid_assignment_rejected(team_target, assignment):
    result = subprocess.run([str(HELPER),'scan-team-index','--pid',str(team_target['pid']),
                             *arguments(team_target, assignment)],capture_output=True,text=True,timeout=10)
    assert result.returncode != 0
