"""Traverse real Mach memory for all supported staff layouts and name states."""
import json
import subprocess
import sys

import pytest

from test_native import HELPER, native, pytestmark


@pytest.fixture
def staff_target():
    code = r'''
import ctypes,json,os,struct,sys
keep=[]
def buf(data):
 b=ctypes.create_string_buffer(data);keep.append(b);return ctypes.addressof(b)
def name(text):
 s=buf(struct.pack('<I',len(text))+text+b'\0');return buf(struct.pack('<Q',s))
entries=[];addresses=[]
for i,(offset,primary,person) in enumerate([(0x208,0x11100,0x33300),(0x480,0x55500,0x66600),(0x548,0x77700,0x88800),(0x548,0x77700,0x88800),(0,0x99900,0x99900)]):
 d=bytearray(offset+32)
 struct.pack_into('<Q',d,0,primary)
 struct.pack_into('<QIII',d,offset,person,i,100+i,100+i)
 if i<3:
  struct.pack_into('<Q',d,offset-0xf0,name(b'Test'))
  struct.pack_into('<Q',d,offset-0xe8,name([b'Coach',b'Player',b'Manager'][i]))
  struct.pack_into('<Q',d,offset-0xe0,name(b'Common Alias') if i==1 else name(b''))
 elif i==3:struct.pack_into('<Q',d,offset-0xf0,buf(bytes(8)))
 a=buf(bytes(d));addresses.append(a);entries.append(a+offset)
start=buf(struct.pack('<5Q',*entries));header=buf(struct.pack('<3Q',start,start+40,start+40))
print(json.dumps({'pid':os.getpid(),'start':start,'header':header,'addresses':addresses}),flush=True)
for command in sys.stdin:
 if command.strip()=='badname':ctypes.memmove(entries[0]-0xf0,struct.pack('<Q',1),8)
 elif command.strip()=='badtype':ctypes.memmove(addresses[2],struct.pack('<Q',0x11100),8)
 elif command.strip()=='exit':break
 print('changed',flush=True)
'''
    child = subprocess.Popen([sys.executable, '-c', code], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
    target = json.loads(child.stdout.readline())
    target['child'] = child
    try:
        yield target
    finally:
        child.communicate('exit\n', timeout=5)


def args(t, name='Test', start=0, budget=200000, limit=100):
    return ['--list-header', str(t['header']), '--list-start', str(t['start']), '--list-count', '5',
            '--start-index', str(start), '--record-budget', str(budget), '--max-matches', str(limit),
            '--player-primary', str(0x11100), '--player-person', str(0x33300), '--player-playing', str(0x22200),
            '--player-staff-primary', str(0x55500), '--player-staff-person', str(0x66600),
            '--human-primary', str(0x77700), '--human-person', str(0x88800), '--player-query', name]


def test_native_staff_all_types_and_unavailable_name(staff_target):
    t = staff_target
    result = native(t, 'scan-staff-index', *args(t))
    assert result['staff_examined'] == 4 and result['player_staff_examined'] == 1
    assert result['unavailable_name_records'] == 1 and result['other_person_records'] == 1
    assert result['matches'] == [{'address': hex(a)} for a in t['addresses'][:3]]
    common = native(t, 'scan-staff-index', *args(t, name='Alias'))
    assert common['matches'] == [{'address': hex(t['addresses'][1])}]


def test_native_staff_pagination_preserves_records(staff_target):
    t = staff_target
    pages = [native(t, 'scan-staff-index', *args(t, start=i, limit=1)) for i in range(4)]
    assert [p['next_index'] for p in pages] == [1, 2, 3, 5]
    assert sum(p['scanned_records'] for p in pages) == 5
    assert [r for p in pages for r in p['matches']] == [{'address': hex(a)} for a in t['addresses'][:3]]
    assert pages[-1]['unavailable_name_records'] == 1
    budget = native(t, 'scan-staff-index', *args(t, name='Manager', budget=1))
    assert budget['stop_reason'] == 'record_budget' and not budget['matches']


@pytest.mark.parametrize('fault', ['badname', 'badtype'])
def test_native_staff_unreadable_data_fails_entire_scan(staff_target, fault):
    t = staff_target
    t['child'].stdin.write(fault+'\n'); t['child'].stdin.flush()
    assert t['child'].stdout.readline().strip() == 'changed'
    result = subprocess.run([str(HELPER), 'scan-staff-index', '--pid', str(t['pid']), *args(t)], capture_output=True, text=True, timeout=5)
    assert result.returncode != 0 and json.loads(result.stdout)['ok'] is False
