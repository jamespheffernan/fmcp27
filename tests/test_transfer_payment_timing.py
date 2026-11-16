from datetime import date
import json
from pathlib import Path
import struct

import pytest

from fm_live_mcp import transfer_payment_timing as timing, world
from test_club_debt_obligations import debt_memory
from test_club_finance import finance_memory
from test_database import database_memory
from test_players import memory
from test_retained_transfer_debt import row, transfer_memory
from test_world import world_memory


ADMITTED={'state':'admitted','reason':'native_prior_removal_predicates_passed'}


def current(value=date(2030,11,26),code=57):
    return struct.pack('<HH',value.timetuple().tm_yday|(code<<9),value.year)


def forecast(*,count=8,interval=12,amount=1000,as_of=None,gate=None,flag=1):
    raw=bytearray(row(0x10000,0x20000,amount,count,interval))
    if gate is not None:raw[20:24]=current(gate,25)
    return timing.forecast_row(raw[:34],current() if as_of is None else as_of,
                               admission_flag=flag,prior_admission=ADMITTED)


@pytest.mark.parametrize(('count','interval','expected','events','last','argument_sum'),[
    (8,12,'2031-07-01',1,'2031-07-01',12000),
    (20,12,'2031-07-01',2,'2032-07-01',24000),
    (14,6,'2031-01-01',3,'2032-01-01',18000),
    (3,1,'2030-12-01',3,'2031-02-01',3000),
    (2,2,'2031-01-01',1,'2031-01-01',2000),
])
def test_next_native_cash_branch_uses_monthly_counter_modulo_not_original_transfer_day(count,interval,expected,events,last,argument_sum):
    result=forecast(count=count,interval=interval)
    assert result['state']=='projected_native_cash_branch'
    assert result['next_native_cash_branch']['date']==expected
    assert result['next_native_cash_branch']['time']=='08:30'
    assert result['remaining_native_cash_branch_count']==events
    assert result['last_native_cash_branch_date']==last
    assert result['remaining_native_cash_argument_sum']==argument_sum
    assert result['payment_state']=='not_established' and result['next_payment_due_date'] is None


def test_native_cash_call_argument_is_distinct_from_remaining_schedule_unit_product():
    result=forecast(count=8,interval=12)
    assert result['next_native_cash_branch']['call_argument_amount']==12000
    assert result['remaining_native_cash_argument_sum']==12000
    assert 1000*8==8000  # Native TransferDebt's separate remaining-unit calculation.


@pytest.mark.parametrize(('code','expected'),[(0,'2030-12-01'),(10,'2030-12-01'),(12,'2031-01-01'),(72,'2031-01-01')])
def test_first_day_before_after_native_cash_hour(code,expected):
    result=forecast(count=1,as_of=current(date(2030,12,1),code))
    assert result['next_native_cash_branch']['date']==expected


def test_exact_current_cash_tick_and_unknown_clock_stay_explicitly_unavailable():
    result=forecast(as_of=current(date(2030,12,1),11))
    assert result['reason']=='current_native_cash_tick_before_after_ambiguous'
    assert result['next_native_cash_branch'] is None
    for code in (73,80,127):
        result=forecast(as_of=current(code=code))
        assert result['reason']=='unsupported_native_clock_code'


@pytest.mark.parametrize(('gate','expected'),[(date(2031,2,1),'2031-09-01'),(date(2031,2,2),'2031-10-01')])
def test_date_gate_waits_without_decrementing_the_retained_counter(gate,expected):
    assert forecast(gate=gate)['next_native_cash_branch']['date']==expected


@pytest.mark.parametrize('flag',[0,2,255])
def test_disabled_or_unmapped_native_processing_does_not_become_scheduled_zero(flag):
    result=forecast(flag=flag)
    assert result['next_native_cash_branch'] is result['remaining_native_cash_argument_sum'] is None
    assert result['reason']=='native_cash_processing_not_admitted'


@pytest.mark.parametrize(('amount','state'),[(-1,'unclassified_native_unit_amount'),(2**31-1,'native_cash_argument_signed32_wrap'),(2**30,'native_cash_argument_signed32_wrap')])
def test_unknown_cash_argument_does_not_hide_proved_calendar(amount,state):
    result=forecast(amount=amount)
    assert result['next_native_cash_branch']['date']=='2031-07-01'
    assert result['next_native_cash_branch']['call_argument_amount'] is None
    assert result['next_native_cash_branch']['call_argument_state']==state


def test_unknown_last_date_does_not_hide_supported_next_date():
    result=forecast(count=127,interval=1,as_of=current(date(2200,1,2),57))
    assert result['next_native_cash_branch']['date']=='2200-02-01'
    assert result['last_native_cash_branch_date'] is None
    assert result['last_native_cash_branch_date_state']=='outside_supported_native_calendar'


def test_all_positive_signed_count_interval_pairs_match_independent_decrement_loop():
    for count in range(1,128):
        for interval in range(1,128):
            skipped=0
            remaining=count
            while interval!=1 and remaining%interval!=1:
                remaining-=1;skipped+=1
            expected=[]
            counter=count
            tick=0
            while counter>0:
                if interval==1 or counter%interval==1:expected.append(tick)
                counter-=1;tick+=1
            result=forecast(count=count,interval=interval)
            assert result['next_native_cash_branch']['counter_opportunities_skipped']==skipped==expected[0]
            assert result['remaining_native_cash_branch_count']==len(expected)


@pytest.fixture
def timing_memory(transfer_memory):
    m=transfer_memory
    spans=json.loads((Path(__file__).parents[1]/'evidence/transfer-payment-timing-20261109/source-bytes.json').read_text())['spans']
    for span in spans:m['put'](m['base']+span['rva'],bytes.fromhex(span['hex']))
    m['put'](m['base']+world.CURRENT_DATE,current())
    m['put'](m['base']+0x56D4987,b'\x01')
    nation=m['allocate'](8)
    m['q'](m['club']+0xD8,nation);m['q'](m['other_club']+0xD8,nation)
    for address in (m['outgoing'],m['incoming']):m['put'](address+28,struct.pack('<i',0))
    m['put'](m['outgoing'],row(m['club'],m['other_club'],1000,8,12))
    m['put'](m['outgoing']+28,struct.pack('<i',0))
    return m


def test_decoder_binds_clock_person_header_nations_and_exact_retained_source(timing_memory):
    m=timing_memory
    result=timing.decode(m['read'],m['base'],m['club'])
    assert result['native_cash_timing']['as_of_native_clock']['time']=='20:00'
    payment=result['records'][0]['native_cash_timing']
    assert payment['next_native_cash_branch']['date']=='2031-07-01'
    assert payment['next_native_cash_branch']['call_argument_amount']==12000
    assert result['native_transfer_debt']['amount']==7000
    assert result['records'][0]['native_remaining_amount']['amount']==8000


@pytest.mark.parametrize('fault',['nation','person_index','source','processing_byte','clock'])
def test_prior_removal_and_unavailability_do_not_mean_paid(timing_memory,fault):
    m=timing_memory
    if fault=='nation':m['q'](m['club']+0xD8,0)
    elif fault=='person_index':m['put'](m['outgoing']+28,struct.pack('<i',2))
    elif fault=='source':m['put'](m['base']+timing.TIMING_SOURCE[0][0],b'\0')
    elif fault=='processing_byte':m['put'](m['base']+0x56D4987,b'\0')
    else:m['put'](m['base']+world.CURRENT_DATE,current(code=127))
    if fault=='source':
        with pytest.raises(ValueError,match='source changed'):timing.decode(m['read'],m['base'],m['club'])
        return
    payment=timing.decode(m['read'],m['base'],m['club'])['records'][0]['native_cash_timing']
    assert payment['next_native_cash_branch'] is None and payment['payment_state']=='not_established'


@pytest.mark.parametrize('field',['nation','processing_byte','person_header','clock','row'])
def test_new_timing_inputs_require_final_physical_rechecks(timing_memory,field):
    m=timing_memory
    read=world.ReadSet(m['read'])
    timing.decode(read,m['base'],m['club'])
    address={'nation':m['club']+0xD8,'processing_byte':m['base']+0x56D4987,
             'person_header':m['headers']['people'],'clock':m['base']+world.CURRENT_DATE,'row':m['outgoing']+33}[field]
    byte=m['read'](address,1)[0]
    m['put'](address,bytes([byte^1]))
    with pytest.raises(ValueError,match='changed during read'):read.verify()
