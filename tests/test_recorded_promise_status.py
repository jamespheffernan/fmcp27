"""Original predicate on a real literal journal, not a lifecycle/UI assertion."""
import gzip
import hashlib
import importlib.util
import json
from pathlib import Path
import pytest

ROOT=Path(__file__).resolve().parents[1]
P=ROOT/'evidence/social-promises-20261109/native_status_vm.py'
spec=importlib.util.spec_from_file_location('recorded_status_vm',P)
vm=importlib.util.module_from_spec(spec);spec.loader.exec_module(vm)


@pytest.fixture(scope='module')
def recorded():
    raw=gzip.decompress((ROOT/'tests/fixtures/promise_status_original_7e85cb7.json.gz').read_bytes())
    assert hashlib.sha256(raw).hexdigest()=='89536d1526faec6856fbd211f903a9b6f91d39c37fb885056c979f25edf5a2d7'
    packet=json.loads(raw);journal=packet['journal'];rows=journal['regions'];cells={}
    assert hashlib.sha256(json.dumps(rows,separators=(',',':')).encode()).hexdigest()==journal['sha256']
    assert len(rows)==journal['region_count']and journal['truncated']is False
    for row in rows:
        at=int(row['address'],16);value=bytes.fromhex(row['raw_hex']);assert len(value)==row['size']
        for offset,byte in enumerate(value):
            if at+offset in cells:assert cells[at+offset]==byte
            cells[at+offset]=byte
    assert packet['detach']=={'detached':True}and packet['source_before']==packet['source_after']
    return packet,cells


def literal(cells):
    def read(address,size):
        try:return bytes(cells[address+i]for i in range(size))
        except KeyError as error:raise ValueError('Missing genuine recorded operand')from error
    return read


def test_actual_original_full_predicate_returns_raw_six_and_flag_zero(recorded):
    packet,cells=recorded;attempt=packet['native_status_attempt']
    result=vm.execute(literal(cells),int(packet['plugin_base_private'],16),attempt['promise_private'],instruction_limit=10000)
    assert json.loads(json.dumps(result))==attempt['result']
    assert result['state']=='complete_original_status_predicate_return'
    assert result['native_return']==6 and result['native_output_flag']==0
    assert result['instruction_count']==254 and len(result['unique_code_pages'])==8
    assert result['trace'][0]==0x246a250 and result['trace'][-1]==0x246dea8
    assert result['label_interpretation']is None and result['UI_ongoing_evaluated']is False
    assert attempt['active']is attempt['fulfilled']is attempt['ongoing']is None


@pytest.mark.parametrize('operand',['original-entry','guard-pointer','party-B'])
def test_omitted_genuine_operands_do_not_become_zero_or_disk_values(recorded,operand):
    packet,original=recorded;cells=original.copy();base=int(packet['plugin_base_private'],16)
    promise=packet['native_status_attempt']['promise_private']
    address={'original-entry':base+0x246a250,'guard-pointer':base+0x54b05b0,'party-B':promise+0x20}[operand]
    cells.pop(address)
    with pytest.raises(ValueError,match='Missing genuine recorded operand'):
        vm.execute(literal(cells),base,promise,instruction_limit=10000)
