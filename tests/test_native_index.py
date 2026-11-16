"""Exercise actual Mach person-table traversal, limits and malformed objects."""
import json
import subprocess
import sys

import pytest

from test_native import HELPER, native, pytestmark


@pytest.fixture
def index_target(request):
    code = r'''
import ctypes,json,os,struct,sys
keep=[]
def buf(data):
 b=ctypes.create_string_buffer(data);keep.append(b);return ctypes.addressof(b)
def name(text):
 s=buf(struct.pack('<I',len(text))+text+b'\0');return buf(struct.pack('<Q',s))
entries=[];primary=[]
staff_mode = sys.argv[1] == 'staff'
for i in range(4):
 staff = staff_mode and i == 3
 delta = 0xf8 if staff else 0
 d=bytearray(0x4a0 if staff else 0x3a8)
 if i==1:
  struct.pack_into('<QI',d,0,0x44400,i)
  entries.append(buf(bytes(d)));continue
 for o,v in [(0,0x55500 if staff else 0x11100),(0x140,0x22200),(0x388+delta,0x66600 if staff else 0x33300)]:struct.pack_into('<Q',d,o,v)
 first={0:b'Scott',2:b'Adam',3:b'Sheku'}[i]
 struct.pack_into('<Q',d,0x298+delta,name(first))
 if i!=3:struct.pack_into('<Q',d,0x2a0+delta,name(b'Wharton'))
 else:struct.pack_into('<Q',d,0x2a8+delta,name(b'Sheku Fassine Fofana'))
 struct.pack_into('<III',d,0x390+delta,i,100+i,100+i)
 struct.pack_into('<hh',d,0x25c,{0:110,2:160,3:180}[i],{0:150,2:-95,3:190}[i])
 d[0x270]=0x80 if i!=3 else 0
 d[0x15e]={0:77,2:88,3:20}[i]
 d[0x154]={0:18,2:19,3:20}[i]
 d[0x2bc+delta]={0:12,2:16,3:20}[i]
 struct.pack_into('<HH',d,0x2d0+delta,60,{0:2000,2:2010,3:2012}[i])
 a=buf(bytes(d));primary.append(a);entries.append(a+0x388+delta)
start=buf(struct.pack('<4Q',*entries));header=buf(struct.pack('<3Q',start,start+32,start+32))
print(json.dumps({'pid':os.getpid(),'start':start,'header':header,'addresses':primary}),flush=True)
for command in sys.stdin:
 if command.strip()=='badindex':ctypes.memmove(entries[0]+8,struct.pack('<I',99),4)
 elif command.strip()=='badtype':ctypes.memmove(primary[0],struct.pack('<Q',0x55500),8)
 elif command.strip()=='badbounds':ctypes.memmove(header+8,struct.pack('<Q',start-8),8)
 elif command.strip()=='badfilter':ctypes.memmove(primary[0]+0x15e,b'\xff',1)
 elif command.strip()=='baddate':ctypes.memmove(primary[0]+0x2d0,struct.pack('<HH',366,2001),4)
 elif command.strip()=='generated':
  for p in primary:ctypes.memmove(p+(0x490 if staff_mode and p==primary[-1] else 0x398),struct.pack('<I',0),4)
 elif command.strip()=='alternate_id':ctypes.memmove(primary[0]+0x398,struct.pack('<I',999),4)
 elif command.strip()=='zero_id':ctypes.memmove(primary[0]+0x394,bytes(4),4)
 elif command.strip()=='null_first':
  handle=struct.unpack('<Q',ctypes.string_at(primary[0]+0x298,8))[0];ctypes.memmove(handle,bytes(8),8)
 elif command.strip() in ('empty_first','malformed_empty'):
  handle=struct.unpack('<Q',ctypes.string_at(primary[0]+0x298,8))[0]
  pointer=struct.unpack('<Q',ctypes.string_at(handle,8))[0]
  ctypes.memmove(pointer,bytes(4)+(b'x' if command.strip()=='malformed_empty' else b'\0'),5)
 elif command.strip()=='nameless':ctypes.memmove(primary[0]+0x298,bytes(24),24)
 elif command.strip()=='exit':break
 print('changed',flush=True)
'''
    child = subprocess.Popen([sys.executable, '-c', code, 'staff' if getattr(request, 'param', False) else 'regular'], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
    target = json.loads(child.stdout.readline())
    target['child'] = child
    try:
        yield target
    finally:
        child.communicate('exit\n', timeout=5)


def args(target, name='Wharton', start=0, budget=200000, limit=100):
    return ['--list-header',str(target['header']),'--list-start',str(target['start']),
            '--list-count','4','--start-index',str(start),'--record-budget',str(budget),
            '--max-matches',str(limit),'--player-primary',str(0x11100),
            '--player-playing',str(0x22200),'--player-person',str(0x33300),'--player-query',name]


def test_native_index_match_limit_has_lossless_continuation(index_target):
    t = index_target
    first = native(t, 'scan-player-index', *args(t, limit=1))
    assert first['next_index'] == 1 and first['stop_reason'] == 'match_limit'
    second = native(t, 'scan-player-index', *args(t, start=1, limit=1))
    assert second['next_index'] == 3 and second['other_person_records'] == 1
    final = native(t, 'scan-player-index', *args(t, start=3, limit=1))
    assert final['stop_reason'] == 'table_end' and not final['matches']
    assert [p['first_name'] for p in first['matches']+second['matches']] == ['Scott','Adam']


def test_native_index_budget_and_common_name(index_target):
    t = index_target
    first = native(t, 'scan-player-index', *args(t, name='Fassine', budget=2))
    assert first['matches'] == [] and first['next_index'] == 2 and first['stop_reason'] == 'record_budget'
    second = native(t, 'scan-player-index', *args(t, name='Fassine', start=2))
    assert second['matches'] == [{'address':hex(t['addresses'][-1]),'first_name':'Sheku','last_name':''}]
    assert second['stop_reason'] == 'table_end'


@pytest.mark.parametrize('mutation',['badindex','badtype','badbounds'])
def test_native_index_rejects_broken_links(index_target, mutation):
    t = index_target
    t['child'].stdin.write(mutation+'\n');t['child'].stdin.flush()
    assert t['child'].stdout.readline().strip()=='changed'
    result = subprocess.run([str(HELPER),'scan-player-index','--pid',str(t['pid']),*args(t)],capture_output=True,text=True,timeout=5)
    assert result.returncode != 0 and json.loads(result.stdout)['ok'] is False


@pytest.mark.parametrize('index_target', [True], indirect=True)
def test_native_index_searches_player_staff_layout(index_target):
    t = index_target
    result = native(t, 'scan-player-index', *args(t, name='Fassine'),
                    '--player-staff-primary', str(0x55500), '--player-staff-person', str(0x66600))
    assert result['player_staff_examined'] == 1
    assert result['actual_players_examined'] == 3
    assert result['matches'] == [{'address': hex(t['addresses'][-1]), 'first_name': 'Sheku', 'last_name': ''}]


@pytest.mark.parametrize('mutation',['null_first','empty_first','nameless'])
def test_native_valid_missing_names_preserve_search_continuation(index_target,mutation):
    t=index_target
    t['child'].stdin.write(mutation+'\n');t['child'].stdin.flush()
    assert t['child'].stdout.readline().strip()=='changed'
    first=native(t,'scan-player-index',*args(t,budget=1))
    second=native(t,'scan-player-index',*args(t,start=first['next_index']))
    assert first['next_index']==1 and second['stop_reason']=='table_end'
    assert first['unavailable_name_records']==(1 if mutation=='nameless' else 0)
    assert [p['first_name'] for p in first['matches']+second['matches']]==(['Adam'] if mutation=='nameless' else ['', 'Adam'])


def test_native_malformed_empty_name_still_fails(index_target):
    t=index_target
    t['child'].stdin.write('malformed_empty\n');t['child'].stdin.flush()
    assert t['child'].stdout.readline().strip()=='changed'
    result=subprocess.run([str(HELPER),'scan-player-index','--pid',str(t['pid']),*args(t)],capture_output=True,text=True,timeout=5)
    assert result.returncode!=0 and json.loads(result.stdout)['ok'] is False
