from contextlib import contextmanager
import struct
import asyncio

import pytest

from fm_live_mcp import saved_person_name_search as search


class Layout:
    person_count = 100
    person_offset = 0
    person_records_offset = 5
    provenance = {'scope': 'synthetic checked name vectors'}
    names = {'first': [b'Other', 'Kylian'.encode(), b'Virgil'],
             'second': [b'Other', 'Mbappé'.encode(), b'van Dijk'],
             'common': [b'Other', b'Rodri']}
    @property
    def name_counts(self):return {k:len(v) for k,v in self.names.items()}
    def lookup_raw(self, ns, i):return self.names[ns][i]


def record(index, names=(1,1,-1), primary=42, secondary=43):
    common = b''.join(struct.pack('<iB', n, 0) for n in names) + bytes(4+38+2)
    return common + bytes(8) + struct.pack('<IIIb', index, primary, secondary, 2)


def source(*records):return struct.pack('<IBB',100,1,1)+b''.join(records)


def discover(data, **kw):
    mode = kw.pop('match_mode', 'exact')
    budget = kw.pop('budget', None)
    query = search._queries(kw.get('first_name'),kw.get('surname'),kw.get('common_name'),mode)
    return search.search_buffer(data, Layout(), query, mode, budget=budget)


def test_conjunction_unicode_and_modes():
    data = source(record(7),record(8,(2,2,1)))
    for surname in ('Mbappé','MBAPPE',' Mbappe '):
        result=discover(data,first_name='kylian',surname=surname)
        assert result['search_complete']
        assert [r['identity']['stored_index'] for r in result['candidates']]==[7]
        assert result['candidates'][0]['names'][1]['text']=='Mbappé'
    assert not discover(data,first_name='Virgil',surname='Mbappe')['candidates']
    assert discover(data,surname='van Dijk')['candidates'][0]['identity']['stored_index']==8
    assert discover(data,surname='van',match_mode='prefix')['candidates']
    assert not discover(data,surname='Dijk',match_mode='prefix')['candidates']
    assert discover(data,surname='Dijk',match_mode='substring')['candidates']
    assert not discover(data,surname='van  Dijk')['candidates']


def test_ambiguity_zero_unequal_words_and_outside_header_retained():
    data=source(record(7,(2,2,1),0,999),record(8,(1,1,1)),record(1000,(1,1,1)))
    result=discover(data,common_name='Rodri')
    assert result['search_complete']
    assert {r['identity']['stored_index'] for r in result['candidates']}=={7,8,1000}
    assert result['candidates'][0]['identity']['native_id_word']==0
    assert result['candidates'][0]['identity']['secondary_word']==999
    assert result['candidates'][-1]['stored_index_inside_declared_population']is False
    assert all(r['certified_person_record']is False for r in result['candidates'])


@pytest.mark.parametrize('budget,reason',[
    (search.Budget(max_name_rows=0),'name_rows'),
    (search.Budget(max_name_bytes=0),'name_bytes'),
    (search.Budget(max_scan_bytes=0),'scan_bytes'),
    (search.Budget(max_byte_work=0),'byte_work'),
    (search.Budget(max_reference_hits=0),'reference_hits'),
    (search.Budget(max_candidates=0),'candidates'),
    (search.Budget(max_candidate_name_bytes=0),'candidate_name_bytes'),
    (search.Budget(max_text_bytes=1),'name_text_bytes'),
    (search.Budget(max_name_ids=0),'name_reference_set_budget'),
])
def test_limits_never_become_absence(budget,reason):
    result=discover(source(record(7)),surname='Mbappe',budget=budget)
    assert not result['search_complete']
    assert reason in result['budget_reasons']


def test_scoped_no_dictionary_match_and_invalid_queries():
    result=discover(source(record(7)),surname='not stored')
    assert result['search_complete']and not result['candidates']
    for args in [(None,None,None,'exact'),('',None,None,'exact'),('x',None,None,'bad'),(' '*2,None,None,'exact')]:
        with pytest.raises(ValueError):search._queries(*args)
    assert search.normalize('van Dijk') != search.normalize('van  Dijk')


def test_broad_prefix_cap_is_explicit():
    layout=Layout();layout.names={**layout.names,'second':[b'Smith'+str(i).encode()for i in range(20)]}
    data=source(record(7))
    result=search.search_buffer(data,layout,{'second':'smith'},'prefix',budget=search.Budget(max_prefix_hits=0))
    assert result['strategy']=='bounded_common_prefix_pass'
    assert not result['search_complete']and 'prefix_hits'in result['budget_reasons']


def test_public_pagination_and_scope(monkeypatch):
    data=source(record(7,(2,2,1)),record(8,(1,1,1)))
    @contextmanager
    def checked(*args):yield data,Layout(),'pin',{'date':'stored only'}
    monkeypatch.setattr(search,'_source',checked)
    first=search.find_people('save.fm','pin',common_name='Rodri',limit=1)
    second=search.find_people('save.fm','pin',common_name='Rodri',offset=first['next_offset'],limit=1)
    assert [p['person_index'] for p in first['people']+second['people']]==[7,8]
    assert first['state']=='ambiguous_candidates'and second['next_offset']is None
    assert first['whole_population_complete']is False
    assert first['coverage']['certified_person_record']is False
    assert first['people'][0]['matching_name_witnesses_only']is True
    stopped=search.find_people('save.fm','pin',surname='Mbappe',_budget=search.Budget(max_reference_hits=0))
    assert stopped['state']=='stopped'and not stopped['search_complete_in_supported_scope']
    missing=search.find_people('save.fm','pin',surname='unavailable')
    assert missing['state']=='no_matches_in_supported_scope'and not missing['whole_population_complete']


def test_stale_snapshot_rejected_before_body_read(monkeypatch):
    @contextmanager
    def checked(*args,**kw):yield object(),[],object()
    monkeypatch.setattr(search.snapshot_catalog,'checked_snapshot',checked)
    monkeypatch.setattr(search.snapshot_catalog,'snapshot_id',lambda _: 'fresh')
    with pytest.raises(ValueError,match='Snapshot identity changed'):
        search.find_people('save.fm','stale',surname='Mbappe')


def test_mcp_schema_and_forwarding(monkeypatch):
    from fm_live_mcp import server
    def query(*args,**kw):return {'args':list(args),'options':kw}
    monkeypatch.setattr(search,'find_people',query)
    result=server.fm_find_saved_people('save.fm','pin',first_name='Kylian',surname='Mbappe')
    assert result['options']['surname']=='Mbappe'
    tools={t.name:t for t in asyncio.run(server.mcp.list_tools())}
    schema=tools['fm_find_saved_people'].inputSchema
    assert set(schema['required'])=={'filename','expected_snapshot_id'}
    assert schema['properties']['match_mode']['enum']==['exact','prefix','substring']
    assert tools['fm_find_saved_people'].annotations.readOnlyHint


def test_duplicate_suffixes_same_index_do_not_become_one_identity(monkeypatch):
    data=source(record(7,(1,1,1),10,20),record(7,(2,2,1),30,40))
    @contextmanager
    def checked(*args):yield data,Layout(),'pin',{}
    monkeypatch.setattr(search,'_source',checked)
    out=search.find_people('save.fm','pin',common_name='Rodri')
    assert out['matching_stored_index_groups']==1
    assert out['matching_suffix_witnesses']==2
    assert out['state']=='ambiguous_candidates'
    assert out['people'][0]['state']=='ambiguous_name_witnesses'
    assert [c['identity']['native_id_word']for c in out['people'][0]['candidates']]==[10,30]
    assert out['people'][0]['candidate_projection_complete']is True


def test_projection_cap_is_explicit_and_longer_wire_is_excluded(monkeypatch):
    data=source(*(record(7,(1,1,1),i,i+1)for i in range(101)))
    @contextmanager
    def checked(*args):yield data,Layout(),'pin',{}
    monkeypatch.setattr(search,'_source',checked)
    out=search.find_people('save.fm','pin',common_name='Rodri')
    row=out['people'][0]
    assert out['state']=='ambiguous_candidates'
    assert row['candidate_count']==101 and len(row['candidates'])==100
    assert row['alternatives_omitted']==1 and not row['candidate_projection_complete']
    assert not out['candidate_projections_complete_for_page']
    assert row['alternative_lookup']['tool']=='fm_get_saved_person_name_candidates'
    narrow=search.find_people('save.fm','pin',common_name='Rodri',_budget=search.Budget(common_span=20))
    assert narrow['coverage']['common_body_span_limit_bytes']==20
    assert 'valid longer body'in narrow['coverage']['larger_common_bodies']
    assert narrow['state']=='no_matches_in_supported_scope'
    assert narrow['whole_population_complete']is False
