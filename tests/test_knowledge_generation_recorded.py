"""Offline generation receipt tamper controls, using only this test process."""
from copy import deepcopy
import importlib.util
import os
from pathlib import Path

import pytest

from test_knowledge_generation_transport import g

PATH=Path(__file__).resolve().parents[1]/'evidence/knowledge-complete-identity-v2-20261109/check_recorded_v2.py'
spec=importlib.util.spec_from_file_location('generation_recorded',PATH)
v=importlib.util.module_from_spec(spec);spec.loader.exec_module(v)


def packet():
    baseline=g.KernelIdentity()(os.getpid())
    return dict(kernel_generation_baseline=deepcopy(baseline),kernel_generation_after_attach=deepcopy(baseline),
        kernel_generation_per_port_verified=True,process={'pid':os.getpid()},transport_segments=[dict(
            closed=True,kernel_generation_baseline=deepcopy(baseline),kernel_generation_checks={
                phase:deepcopy(baseline)for phase in('before_lazy_port_open','after_first_physical_read','before_port_close')})])


def test_matching_raw_kernel_generation_receipts_are_accepted():
    result=v.kernel_receipts(packet(),g)
    assert result['before_attach_after_attach_and_every_lazy_open_first_read_close_match']


@pytest.mark.parametrize('change',['uniqueid','idversion','uuid','rawhex','missing_phase','open_port','metadata_error','claim_false','wrong_pid'])
def test_generation_receipt_tamper_or_missing_proof_refuses(change):
    p=packet();segment=p['transport_segments'][0];receipt=segment['kernel_generation_checks']['after_first_physical_read']
    if change=='uniqueid':receipt['process_unique_id']+=1
    elif change=='idversion':receipt['idversion_bits']^=1
    elif change=='uuid':receipt['executable_uuid_hex']='00'*16
    elif change=='rawhex':receipt['kernel_token_rawhex']='00'*56
    elif change=='missing_phase':segment['kernel_generation_checks'].pop('before_port_close')
    elif change=='open_port':segment['closed']=False
    elif change=='metadata_error':segment['kernel_generation_errors']={'before_port_close':{'error':'denied'}}
    elif change=='claim_false':p['kernel_generation_per_port_verified']=False
    else:p['process']['pid']+=1
    with pytest.raises((AssertionError,ValueError)):v.kernel_receipts(p,g)
