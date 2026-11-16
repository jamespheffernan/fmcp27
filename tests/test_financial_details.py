import struct

import pytest
import unicorn as uc

from fm_live_mcp import ffp_projection as ffp, financial_details as details


def test_live_loan_decodes_packed_flags_unknown_source_and_zero():
    raw = bytes.fromhex('baa26e0282f20800f4880100000000004e33f0074f33e907100100')
    row = details._loan(lambda address, size: raw[:size], 0x8000, 2)
    assert (row['slot'], row['original_debt'], row['monthly_repayment'],
            row['monthly_interest_repayment']) == (2, 40_805_050, 586_370, 100_596)
    assert row['start_date']['value'] == '2025-12-01'
    assert row['end_date']['value'] == '2032-11-29'
    assert row['included_in_ffp_calculations'] and not row['interest_only']
    assert row['source_code'] == 16 and row['source_name'] is None
    assert row['conditional_repayment'] == 0
    with pytest.raises(ValueError, match='loan boolean'):
        details._loan(lambda *_: raw[:-1]+b'\x02', 0x8000, 2)


def test_stored_negative_and_zero_prices_are_distinct():
    assert details.price(0) == {'amount': 0, 'state': 'stored', 'stored_signed32': 0}
    assert details.price(-2) == {'amount': None, 'state': 'negative_native_code', 'stored_signed32': -2}
    assert details.price(0x7fffffff)['amount'] is None
    assert details.player_prices(None, None, None, 'virtual', None)['state'] == 'unsupported_player_layout'


def test_private_projection_stores_and_consumed_byte_rechecks(tmp_path, monkeypatch):
    # ARM64 ldr w2,[x0]; str w1,[x0]; mov w0,w2; ret
    program = bytes.fromhex('020040b9010000b9e003022ac0035fd6')
    binary = tmp_path/'test-image'
    binary.write_bytes(program + bytes(ffp.PAGE-len(program)))
    monkeypatch.setattr(ffp, 'ARM_SLICE', 0)
    monkeypatch.setattr(ffp, 'TEXT_END', ffp.PAGE)
    base, source = 0x180000000, 0x1000000
    live = bytearray(ffp.PAGE)
    struct.pack_into('<I', live, 0, 13)
    def read(address, n):
        assert address == source
        return bytes(live[:n])
    with binary.open('rb') as image:
        cpu = ffp.FinanceCPU(read, base, image)
        try:
            assert cpu.run(0, source, 99) == 13
            assert struct.unpack('<I', cpu.local_read(source, 4))[0] == 99
            assert live[:4] == struct.pack('<I', 13)
            live[7] = 0xff
            cpu.verify()
            live[2] = 0xff
            with pytest.raises(ffp.UnsupportedProjection, match='inputs changed'):
                cpu.verify()
            with pytest.raises((ffp.UnsupportedProjection, uc.UcError)):
                cpu.run(source-base)
        finally:
            cpu.close()


def test_club_finance_schema_preserves_cheap_default_and_validates_opt_ins():
    from fm_live_mcp.bridge import Bridge, BridgeError
    b = Bridge()
    for name in ('include_details', 'include_ffp_projection'):
        with pytest.raises(BridgeError, match='boolean'):
            b.get_club_finances('invalid', **{name: 1})
    with pytest.raises(BridgeError, match='boolean'):
        b.get_player('invalid', 'invalid', include_transfer_prices=1)


# Pinned IsPassingFfp machine code. Two different native failed checks have
# different meanings even when both projections return false.
@pytest.mark.parametrize('amount,minimum,disable_zero_check,expected', [
    (350363904, -15000000, False, (True, None)),
    (-92252960, 0x7fffffff, False, (False, 'assessment_below_zero')),
    (-20, -15, True, (False, 'assessment_below_minimum')),
    (-15, -15, True, (True, None)),
])
def test_native_ffp_verdict_and_exit(amount, minimum, disable_zero_check, expected, tmp_path, monkeypatch):
    method = bytes.fromhex(
        '080441b90900b0121f01096b80000054090041b93f01086b8d000054086c40f9'
        '6800f8b61a000014086c40f90900b0121f0109ebc00000540a0c81b95f01096b'
        '600000541f010aeb24020054091041b9890000340a1c41b93f010a6b8b010054'
        '091881b9890000340a6840f95f0109ebea0000540900b0521f0109ebcb000054'
        '08ec4439200080524800003600008052c0035fd620008052c0035fd6'
    )
    binary = tmp_path/'native-verdict'
    binary.write_bytes(bytes(0x660)+method+bytes(ffp.PAGE-0x660-len(method)))
    monkeypatch.setattr(ffp, 'ARM_SLICE', -0x1A45000)
    with binary.open('rb') as stream:
        cpu = ffp.FinanceCPU(lambda *_: pytest.fail('unexpected game read'), 0x180000000, stream)
        try:
            row = bytearray(0x140)
            struct.pack_into('<q', row, 0xd8, amount)
            struct.pack_into('<i', row, 0x104, 0 if disable_zero_check else 0x7fffffff)
            struct.pack_into('<i', row, 0x10c, minimum)
            cpu.vm.mem_write(ffp.SCRATCH, bytes(row))
            assert cpu.ffp_verdict(ffp.SCRATCH) == expected
        finally:
            cpu.close()
