import contextlib
import io
import json
from pathlib import Path
import struct
from types import SimpleNamespace

import pytest

from fm_live_mcp import saved_starting_finances as q
from fm_live_mcp.saved_component_stream import Reader

FIXTURE=json.loads((Path(__file__).parent/'fixtures/saved_starting_finances.json').read_text())

class Source(io.BytesIO):
    @property
    def finished(self):
        return self.tell()==len(self.getvalue())

def reader(raw):
    return Reader(Source(raw),len(raw))

def table(rows):
    data=[]
    for ordinal,raw in enumerate(rows):
        row=bytearray(raw);struct.pack_into('<I',row,67,ordinal);data.append(row)
    return bytes.fromhex('0301746d632e')+struct.pack('<HIB',3754,len(data),0)+b''.join(data)+struct.pack('<IBI',0,1,len(data))

def raw_row(ordinal):
    return bytes.fromhex(next(r['raw_hex']for r in FIXTURE['rows']if r['original_ordinal']==ordinal))

def context(native=688):
    ids=[0]*546;ids[545]=native
    comps=[{'database_index':i,'native_id':i+1,'secondary_id':i+1,'name':None,'short_name':None}for i in range(638)]
    return ids,comps

def decode(rows,**kwargs):
    ids,comps=context()
    return q.read_starting_finances(reader(table(rows)),club_native_id=688,team_native_ids=ids,competitions=comps,**kwargs)

def test_positive_original_bank_and_dates_unproved_currency_and_term():
    r=decode([raw_row(32947)])
    row,=r['rows']
    assert row['source_name']=='Bank'
    assert row['cash']['value']==50_000_000 and row['cash']['currency_code']is None
    assert row['cash']['meaning']=='Original Debt'
    assert row['start_date']['value']=='2024-07-01' and row['end_date']['value']=='2029-06-30'
    assert row['unmapped_stored_fields']['0x5c']=='3000'
    assert row['interest_rate']['stored_value']==-99.0 and row['interest_rate']['value']==0.0
    assert row['current_obligation_state']=='not_established'
    assert r['complete_component']and r['native_debt_count']==r['matched_count']==1
    assert r['native_ffp_count']is None


def test_original_rows_read_without_rewriting_own_IDs():
    for f in FIXTURE['rows']:
        row=q._read_row(reader(bytes.fromhex(f['raw_hex'])),f['original_ordinal'])
        assert row['ordinal']==f['original_ordinal']and row['end']==79
        assert row['native_id']==f['original_ordinal']+1


def test_native_categories_and_original_pagination_never_double_count():
    rows=[raw_row(i)for i in(422,32947,33490,33491,33916,33917)]
    r=decode(rows)
    assert r['native_debt_count']==r['matched_count']==1 and r['matching_starting_record_count']==6
    assert r['excluded_native_category_count']==1
    r=decode(rows,include_ffp=True,offset=1,limit=2)
    assert r['matched_count']==5 and r['native_debt_count']==1 and r['native_ffp_count']==4
    assert [x['original_record_index']for x in r['rows']]==[2,3]
    assert [x['cash']['value']for x in r['rows']]==[-71800000,-54000000]
    assert all(x['section']=='financial_fair_play'and x['interest_rate']is None for x in r['rows'])
    assert r['next_offset']==3
    assert [x['year']for x in r['rows']]==[2022,2022]
    assert decode(rows,include_ffp=True,offset=5)['rows']==[]


@pytest.mark.parametrize('code',range(-128,128))
def test_all_source_codes_follow_native_filter(code):
    row=bytearray(raw_row(32947));row[15]=code&255
    r=decode([row],include_ffp=True)
    assert r['matched_count']==int(code not in(0,-5))
    assert r['native_debt_count']==int(code not in(0,-3,-5))
    assert r['native_ffp_count']==int(code==-3)
    if r['rows']and code not in q.DEBT_SOURCES and code!=-3:
        assert r['rows'][0]['source_name']is None


def test_shared_TEAM_native_ids_follow_predicate_without_owner_filter():
    ids,comps=context();ids[544]=688
    row=bytearray(raw_row(32947));struct.pack_into('<i',row,1,544)
    r=q.read_starting_finances(reader(table([row])),club_native_id=688,team_native_ids=ids,competitions=comps)
    assert r['matched_count']==1 and r['rows'][0]['team']['database_index']==544
    r=q.read_starting_finances(reader(table([row])),club_native_id=99,team_native_ids=ids,competitions=comps)
    assert r['state']=='available'and r['complete_component']and r['matched_count']==0


def test_null_reference_empty_table_and_native_default_dates():
    r=decode([raw_row(0)])
    assert r['rows']==[] and r['matched_count']==0 and r['complete_component']
    assert decode([])['table_count']==0
    assert q.stored_date(bytes.fromhex('01006c07'))['state']=='native_default_sentinel'


def test_every_small_table_truncation_and_trailing_bytes_fail():
    raw=table([raw_row(32947)])
    ids,comps=context()
    for end in range(len(raw)):
        with pytest.raises(ValueError):
            q.read_starting_finances(reader(raw[:end]),club_native_id=688,team_native_ids=ids,competitions=comps)
    with pytest.raises(ValueError):
        q.read_starting_finances(reader(raw+b'\0'),club_native_id=688,team_native_ids=ids,competitions=comps)


def test_corrupt_ordinal_kind_reference_and_count_fail_closed():
    raw=bytearray(table([raw_row(32947)]));ids,comps=context()
    for offset,fmt,value in((13,'B',1),(80,'I',9),(14,'i',546),(76,'i',638),(8,'I',0xffffffff),(12,'B',1),(6,'H',3753)):
        bad=bytearray(raw);struct.pack_into('<'+fmt,bad,offset,value)
        with pytest.raises(ValueError):
            q.read_starting_finances(reader(bad),club_native_id=688,team_native_ids=ids,competitions=comps)


def test_native_interest_null_and_unmapped_float_preserved():
    for value,state in((-1.,'native_unset'),(4.5,'stored_native_real'),(51.0,'outside_supported_editor_domain'),(float('nan'),'unmapped_float_encoding')):
        row=bytearray(raw_row(32947));struct.pack_into('<f',row,28,value)
        out=decode([row])['rows'][0]['interest_rate'];assert out['state']==state


@pytest.mark.parametrize('kwargs',[{'club_index':True},{'club_index':-1},{'club_index':2**31},{'expected_snapshot_id':''},{'include_ffp':1},{'offset':True},{'limit':101}])
def test_backend_strict_validation_before_open(kwargs):
    args=dict(club_index=414,expected_snapshot_id='pin');args.update(kwargs)
    with pytest.raises(ValueError):q.get_starting_finances('save.fm',**args)


def install_query_context(monkeypatch, *, component=True, debt_rows=None, shared=False):
    clubs=[{'database_index':i,'native_id':688 if i in((0,1)if shared else(0,))else 99,
            'secondary_id':688,'name':'Club '+str(i),'short_name':None,'record_kind':'club'}for i in range(2)]
    teams=[{'database_index':i,'native_id':688,'secondary_id':688,'owner_kind':'club',
            'owner_index':i,'name':'Team '+str(i),'short_name':None}for i in range(2)]
    comps=[{'database_index':i,'native_id':i,'secondary_id':i,'name':None,'short_name':None}for i in range(638)]
    entries=[SimpleNamespace(path='root/game_db.dat')]
    if component:entries.append(SimpleNamespace(path='root/starting_club_debt_db.cmt',uncompressed_size=101))
    @contextlib.contextmanager
    def opened(*args):
        assert args[1]=='pin'
        yield object(),{'filename':'x.fm','snapshot_id':'pin','source':'on-disk save snapshot'},object(),entries
    exhausted=[]
    def tables(_r,label,_decode):
        for r in clubs if label=='CLUB'else teams:yield r
        exhausted.append(label)
    monkeypatch.setattr(q.saved_database,'open_archive_at_clubs',opened)
    monkeypatch.setattr(q.saved_database,'table',tables)
    monkeypatch.setattr(q,'_reach_teams',lambda _:comps)
    rows=[]
    for raw in debt_rows or []:
        row=bytearray(raw);struct.pack_into('<i',row,1,1);rows.append(row)
    raw=table(rows)
    @contextlib.contextmanager
    def body(*args):yield reader(raw)
    monkeypatch.setattr(q.saved_component_stream,'open_component',body)
    return exhausted


def test_public_query_shared_native_ids_does_not_pick_reciprocal_team(monkeypatch):
    exhausted=install_query_context(monkeypatch,shared=True,debt_rows=[raw_row(32947)])
    out=q.get_starting_finances('x.fm',0,'pin')
    assert exhausted==['CLUB','TEAM_BASE']
    assert out['identity_context']['same_native_id_club_count']==2
    assert out['identity_context']['matching_team_count']==2
    assert out['identity_context']['club_identity_state']=='shared_native_id_native_predicate_only'
    assert out['rows'][0]['team']['database_index']==1 #Owner1 differs from requestedCLUB0.
    assert out['matched_count']==1


def test_public_missing_component_not_reported_as_empty_and_lock_released(monkeypatch):
    install_query_context(monkeypatch,component=False)
    out=q.get_starting_finances('x.fm',0,'pin')
    assert out['state']=='unavailable'and out['matched_count']is None and not out['complete_component']
    assert q._SLOT.acquire(blocking=False);q._SLOT.release()
    install_query_context(monkeypatch,component=True)
    out=q.get_starting_finances('x.fm',0,'pin')
    assert out['state']=='available'and out['matched_count']==0 and out['complete_component']


def test_bad_club_index_does_not_fall_back_to_native_id(monkeypatch):
    install_query_context(monkeypatch)
    with pytest.raises(ValueError,match='CLUB index outside'):
        q.get_starting_finances('x.fm',2,'pin')
    assert q._SLOT.acquire(blocking=False);q._SLOT.release()
