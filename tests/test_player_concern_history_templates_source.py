"""Private combined source on the single genuine 4 December carrier snapshot."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import pytest
from fm_live_mcp import player_concern_history_templates_source as source

H=Path(__file__).resolve().parents[1]/'evidence/concern-history158/inputs'


class Captured:
    def __init__(self,filename='live-concern-template-carriers-context-1.json'):
        path=H/filename
        expected={'live-concern-template-carriers-context-1.json':'e7c9ae3a7b5442faa5009486197da0fa316d7c6ee21193a3a5727c996f730e56',
            'live-current-contract-concerns-pod4-1.json':'5c8f027f32c756df26a29d3ec14b8cc508a3a0f5b2fc43dd44e95b3a589be566'}[filename]
        assert hashlib.sha256(path.read_bytes()).hexdigest()==expected
        self.packet=json.loads(path.read_text());journal=self.packet['journal'];self.cells={}
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
        except KeyError as error:raise ValueError('Missing literal combined concern operand')from error
    def u64(self,address):return int.from_bytes(self.read(address,8),'little')
    def inspect(self,row):
        # The digest was attested before/after this genuine packet. Production
        # callers must establish that binding themselves on each read cycle.
        return source.inspect(self.read,self.base,row['primary_private'],'actual',
            english_resource_sha256=source.ENGLISH_RESOURCE_SHA256,include_stored_name=True)


def test_single_dated_snapshot_raw_records_and_unrendered_templates_match_exactly():
    old=Captured();results=[old.inspect(row)for row in old.packet['players']]
    assert old.packet['context_before']['save']['current_date']=='2030-12-04'
    assert sum(row['native_ring_entry_count']for row in results)==20
    assert sum(row['unrendered_description_count']for row in results)==19
    assert sum(row['unrendered_description_unknown_count']for row in results)==1
    for actual,carrier in zip(results,old.packet['players'],strict=True):
        expected=deepcopy(carrier['concern_history'])
        for entry,template in zip(expected['records'],carrier['unrendered_templates'],strict=True):
            entry['record']['compiled_unrendered_description']=template['compiled_unrendered_template']
        for key,value in expected.items():assert actual[key]==value
        assert actual['UI_or_fulfilment_evaluated']is False
        for entry in actual['records']:
            description=entry['record']['compiled_unrendered_description']
            assert description['complete_formatter_executed']is description['placeholder_people_resolved']is description['localized_UI_rendered']is description['lifecycle_evaluated']is False


def test_miley_context_sensitive_reason_keeps_null_text_and_key():
    old=Captured();result=old.inspect(old.packet['players'][1]);first=result['records'][0]['record']
    assert result['owner']['display_name']=='Lewis Miley'and first['native_reason_code']==648
    description=first['compiled_unrendered_description']
    assert description['state']=='unknown_context_controls_first_key_branch'
    assert description['translation_id']is description['english_template']is None


@pytest.mark.parametrize('digest',[None,False,'0'*64,'3CE742519BF694636F41A1DAE8D45A3DAB86FAD7D164A58696139E4B4509DD43'])
def test_unverified_english_binding_refuses_before_any_game_read(digest):
    with pytest.raises(ValueError,match='Verified static English resource binding'):
        source.inspect(lambda *args:(_ for _ in()).throw(AssertionError('No game read')),0x100000000,0x1000,'actual',english_resource_sha256=digest)


@pytest.mark.parametrize('span',range(7))
def test_each_compiled_template_source_binding_refuses_drift(span):
    old=Captured();old.cells[old.base+source.SOURCE[span][0]]^=1
    with pytest.raises(ValueError,match='Native concern .*source changed'):old.inspect(old.packet['players'][0])


def test_foreign_contexts_remain_null_without_borrowing_later_template_operands():
    old=Captured('live-current-contract-concerns-pod4-1.json')
    rows=[row for row in old.packet['players']if row['concern_history']['native_ring_entry_count']is None]
    assert len(rows)==3
    for row in rows:
        result=old.inspect(row)
        assert result['state']=='main_contract_outside_current_CLUB_context'
        assert result['records']is result['native_ring_entry_count']is result['unrendered_description_count']is result['unrendered_description_unknown_count']is None


def test_controlled_empty_ring_and_null_slot_are_not_unavailable_contexts():
    old=Captured();row=old.packet['players'][0];contract=old.u64(row['primary_private']+0x2f0);ring=old.u64(contract+0x30)
    old.cells[ring]=0
    empty=old.inspect(row)
    assert empty['records']==[]and empty['native_ring_entry_count']==empty['unrendered_description_count']==empty['unrendered_description_unknown_count']==0
    old=Captured();row=old.packet['players'][0];contract=old.u64(row['primary_private']+0x2f0);ring=old.u64(contract+0x30)
    for offset in range(8):old.cells[ring+8+9*8+offset]=0
    null=old.inspect(row)
    assert null['records'][0]['record']is None and null['native_ring_entry_count']==10
    assert null['unrendered_description_count']==9


def test_missing_record_tail_never_becomes_a_guessed_description():
    old=Captured();row=old.packet['players'][0];contract=old.u64(row['primary_private']+0x2f0);ring=old.u64(contract+0x30);record=old.u64(ring+8+9*8)
    old.cells.pop(record+27)
    with pytest.raises(ValueError,match='Missing literal'):old.inspect(row)


def test_source_and_data_have_no_evidence_directory_or_resource_file_dependency():
    from fm_live_mcp import _concern_template_definitions as definitions
    for module in(source,definitions):
        text=Path(module.__file__).read_text()
        assert 'Path('not in text and 'read_text('not in text and 'social-promises-20261109'not in text
