from contextlib import contextmanager
from hashlib import sha256
import struct
from dataclasses import dataclass

import pytest

from fm_live_mcp import saved_population as population


def retired(i):
    return b'\x10' + struct.pack('<BIIQIII', 0, 0, 0xffffffff, 0, i, i + 5, i + 8)


@pytest.fixture
def checked(monkeypatch):
    data = struct.pack('<IB', 3, 1) + b''.join(retired(i) for i in range(3)) + bytes(9)
    state = {'data': data, 'changed': False}
    @dataclass
    class Layout:
        _data: object
        person_count = 3
        person_offset = 0
        person_records_offset = 5
        name_counts = {'first': 1, 'second': 1, 'common': 0}
        provenance = {'conditional': True}
        def lookup_raw(self, namespace, index):
            return b'First'

    state['layout_calls'] = 0
    def read_layout(source):
        state['layout_calls'] += 1
        return Layout(source)

    monkeypatch.setattr(population.saved_name_vectors, 'locate', read_layout)
    monkeypatch.setattr(population, '_LAST_LAYOUT', None)
    @contextmanager
    def open_name_source(filename, expected_snapshot_id, directory, *, locate):
        assert expected_snapshot_id == 'pin'
        yield state['data'], locate(state['data']), 'pin', {}
        if state['changed']:
            raise ValueError('Snapshot changed during request')
    population._PREFIXES.clear()
    monkeypatch.setattr(population, 'checked_name_source', open_name_source)
    yield state
    population._PREFIXES.clear()


def query(**kw):
    return population.get_person_records('save.fm','pin',**kw)


def test_repeated_pinned_query_advances_and_preserves_order(checked):
    a=query(person_indices=[2,0,2,5],_max_advance=1)
    assert [p['state'] for p in a['people']]==['more_work_required','available','more_work_required','outside_declared_table']
    assert a['retry_same_query_to_advance'] and a['footer']['state']=='not_reached'
    b=query(person_indices=[2,0,2],_max_advance=2)
    assert b['people'][0]==b['people'][2]
    assert b['people'][0]['record_sha256']==sha256(retired(2)).hexdigest()
    assert b['people'][0]['identity']['secondary_word']==10
    assert b['people'][0]['name_fields'][1]['state']=='native_null_reference'
    assert b['new_records_checked']==2 and b['footer']['state']=='source_footer_read'
    assert not b['retry_same_query_to_advance']
    assert query(limit=1)['new_records_checked']==0
    assert checked['layout_calls']==1 and population._LAST_LAYOUT[1]._data is None


def test_unsupported_frontier_preserves_valid_page_prefix(checked):
    checked['data']=checked['data'][:35] + b'\x7f' + checked['data'][36:]
    page=query(limit=3)
    assert [r['state'] for r in page['people']]==['available','unreached_source_frontier','unreached_source_frontier']
    assert page['next_offset'] is None and not page['retry_same_query_to_advance']
    assert page['source_frontier']['ordinal']==1
    assert query(limit=1)['next_offset']==1


def test_changed_source_cannot_publish_checked_offsets(checked):
    checked['changed']=True
    with pytest.raises(ValueError,match='changed'):
        query(limit=2)
    assert not population._PREFIXES
    checked['changed']=False
    assert query(limit=2)['new_records_checked']==2


def test_rehashed_source_and_corrupt_footer(checked):
    query(limit=2)
    checked['data']=checked['data'][:-1]
    with pytest.raises(ValueError,match='footer'):
        query(limit=3)
    assert len(population._PREFIXES)==1


@pytest.mark.parametrize('arguments',[
    {'person_indices':[]},{'person_indices':[True]},{'person_indices':[2],'offset':1},
    {'limit':33},{'offset':-1},{'_max_advance':0},
])
def test_untrusted_request_cannot_supply_or_inflate_checkpoint(arguments):
    with pytest.raises(ValueError):
        query(**arguments)
