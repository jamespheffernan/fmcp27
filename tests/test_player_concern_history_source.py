"""Literal genuine retained history; no installed game or live reader needed."""
import hashlib
import json
from pathlib import Path
import struct
import pytest
from fm_live_mcp import player_concern_history_source as source,players

PATH=Path(__file__).resolve().parents[1]/'evidence/concern-history158/inputs/live-current-contract-concerns-pod4-1.json'


class Original:
    def __init__(self):
        assert hashlib.sha256(PATH.read_bytes()).hexdigest()=='5c8f027f32c756df26a29d3ec14b8cc508a3a0f5b2fc43dd44e95b3a589be566'
        self.packet=json.loads(PATH.read_text());journal=self.packet['journal'];self.cells={}
        assert not journal['truncated']and len(journal['regions'])==journal['region_count']
        assert hashlib.sha256(json.dumps(journal['regions'],separators=(',',':')).encode()).hexdigest()==journal['sha256']
        for row in journal['regions']:
            at=int(row['address'],16);raw=bytes.fromhex(row['raw_hex']);assert len(raw)==row['size']
            for offset,value in enumerate(raw):
                if at+offset in self.cells:assert self.cells[at+offset]==value
                self.cells[at+offset]=value
        self.base=int(self.packet['plugin_base_private'],16)
    def read(self,address,size):
        try:return bytes(self.cells[address+offset]for offset in range(size))
        except KeyError as error:raise ValueError('Missing literal retained concern operand')from error
    def put(self,address,raw):self.cells.update({address+offset:value for offset,value in enumerate(raw)})
    def inspect(self,row):return source.inspect(self.read,self.base,row['primary_private'],'actual',include_stored_name=True)
    def first(self):return self.packet['players'][0]


def test_all_genuine_owners_and_79_records_match_frozen_projection_exactly(monkeypatch):
    old=Original();monkeypatch.setattr(players,'decode',lambda *args,**kwargs:(_ for _ in()).throw(AssertionError('No profile generation')))
    histories=[old.inspect(row)for row in old.packet['players']]
    assert histories==[row['concern_history']for row in old.packet['players']]
    assert len(histories)==29
    assert sum(history['native_ring_entry_count']or 0 for history in histories)==79
    assert sum(history['native_unset_end_filter_count']or 0 for history in histories)==3
    assert sum(history['native_ring_entry_count']is None for history in histories)==3
    assert sum(history['state']=='observed_native_ring'for history in histories)==15
    for history in histories:
        if history['records']is None:continue
        for entry in history['records']:
            assert entry['record']['reason_title']is entry['record']['promise_fulfilled']is entry['record']['satisfaction']is None


@pytest.mark.parametrize('span',range(15))
def test_each_original_native_binding_including_pool_stride_refuses_drift(span):
    old=Original();old.cells[old.base+source.SOURCE[span][0]]^=1
    with pytest.raises(ValueError,match='Native concern source changed'):old.inspect(old.first())


def test_genuine_named_positive_and_unrelated_named_owner_refusal():
    old=Original();first,other=old.packet['players'][:2]
    assert old.inspect(first)['owner']['display_name']=='Anthony Gordon'
    assert old.inspect(other)['owner']['display_name']=='Tino Livramento'
    contract=struct.unpack('<Q',old.read(first['primary_private']+0x2f0,8))[0]
    old.put(contract+8,struct.pack('<Q',other['primary_private']+0x388))
    with pytest.raises(ValueError,match='owner changed'):old.inspect(first)


def test_foreign_club_contexts_are_unavailable_and_never_empty_histories():
    old=Original();rows=[row for row in old.packet['players']if row['concern_history']['native_ring_entry_count']is None]
    assert{row['concern_history']['owner']['display_name']for row in rows}=={'Trevan Sanusi','Leo Shahar','Matthew Cox'}
    for row in rows:
        history=old.inspect(row)
        assert history['state']=='main_contract_outside_current_CLUB_context'
        assert history['records']is history['native_ring_entry_count']is history['native_unset_end_filter_count']is None


def test_missing_4mod8_record_cannot_become_an_empty_or_unavailable_result():
    old=Original();first=old.first();contract=struct.unpack('<Q',old.read(first['primary_private']+0x2f0,8))[0]
    ring=struct.unpack('<Q',old.read(contract+0x30,8))[0];record=struct.unpack('<Q',old.read(ring+8+9*8,8))[0]
    assert record%8==4
    old.cells.pop(record+27)
    with pytest.raises(ValueError,match='Missing literal'):old.inspect(first)


def test_implementation_has_no_private_evidence_directory_or_file_reads():
    text=Path(source.__file__).read_text()
    assert 'Path('not in text and 'read_text('not in text and 'social-promises-20261109'not in text
