import json
import subprocess
import sys
import pytest

from test_native import HELPER, native, pytestmark


@pytest.mark.parametrize('secondary', ['equal', '0', '999'])
def test_club_table_names_pagination_and_explicit_other_types(secondary):
    code = r'''
import ctypes,json,os,struct,sys
keep=[]
def buf(data):
 b=ctypes.create_string_buffer(data);keep.append(b);return ctypes.addressof(b)
def text(s):return buf(struct.pack('<I',len(s))+s+b'\0')
entries=[]
for i,short in enumerate([b'United',b'Other',b'UTD']):
 d=bytearray(0xD0);struct.pack_into('<QIII',d,0,0x11100 if i!=1 else 0x22200,i,i+100,i+100 if sys.argv[1]=='equal' else int(sys.argv[1]))
 struct.pack_into('<QQ',d,0xC0,text(b'Test United'),text(short));entries.append(buf(bytes(d)))
start=buf(struct.pack('<3Q',*entries));header=buf(struct.pack('<3Q',start,start+24,start+24))
print(json.dumps({'pid':os.getpid(),'start':start,'header':header}),flush=True)
sys.stdin.readline()
'''
    child = subprocess.Popen([sys.executable,'-c',code,secondary],stdin=subprocess.PIPE,stdout=subprocess.PIPE,text=True)
    try:
        target=json.loads(child.stdout.readline())
        args=['--list-header',str(target['header']),'--list-start',str(target['start']),
              '--list-count','3','--record-budget','200000','--max-matches','1','--player-primary',str(0x11100)]
        first=native(target,'scan-club-index',*args,'--player-query','United')
        assert first['next_index']==1 and first['stop_reason']=='match_limit'
        second=native(target,'scan-club-index',*args,'--start-index','1','--player-query','United')
        assert second['next_index']==3 and second['stop_reason']=='table_end'
        assert second['other_club_records']==1 and second['clubs_examined']==1
        assert second['matches'][0]['short_name']=='UTD'
        by_short=native(target,'scan-club-index',*args,'--player-query','UTD')
        assert by_short['matches']==second['matches']
    finally:
        child.communicate('\n',timeout=5)
