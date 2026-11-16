from decimal import Decimal, localcontext
import struct

import pytest

from fm_live_mcp import currencies, world
from fm_live_mcp.bridge import BridgeError
from test_bridge import bridge
from test_database import bind, database_memory
from test_players import memory
from test_world import world_memory


@pytest.fixture
def currency_memory(database_memory):
    m = database_memory; addresses = []
    for i, (nid, name, rate) in enumerate(((86, 'United Kingdom Pound', 1), (28, 'European Euro', 1.25), (500, 'Fußland Coin', 2))):
        a = m['typed']('currency', 0x58)
        m['put'](a+8, struct.pack('<III', i, nid, nid if i < 2 else 501))
        for offset, value in ((0x18, name), (0x20, 'unit'), (0x28, None), (0x30, '')):
            m['q'](a+offset, m['text'](value) if value is not None else 0)
        m['put'](a+0x38, struct.pack('<f', rate))
        raw = b''.join(struct.pack('<H2xf', year, value) for year, value in ((2020, 0), (2020, 1.5), (0, 2.25), (65535, -1)))
        start = m['allocate'](len(raw)); m['put'](start, raw)
        m['put'](a+0x40, struct.pack('<QQQ', start, start+len(raw), start+len(raw)))
        addresses.append(a)
    m['vec'](m['headers']['currencies'], addresses)
    m['q'](m['base']+world.TYPES['currency'][0]+24, m['base']+currencies.PROPERTY_GETTER)
    m['put'](m['base']+0x538EF50, struct.pack('<I', 86))
    m['currency_addresses'] = addresses
    return m


def test_full_record_history_unknown_strings_and_random_id(bridge, monkeypatch, currency_memory):
    m = currency_memory; bind(bridge, monkeypatch, m)
    page = bridge.find_currencies(bridge.session)
    assert page['count'] == page['total_records'] == 3 and page['complete_table_scan']
    assert [r['random_id'] for r in page['currencies']] == [None, None, 501]
    assert all('history' not in r for r in page['currencies'])
    row = bridge.get_currency(bridge.session, page['currencies'][1]['currency_ref'])['currency']
    assert row['exchange_rate']['value'] == 1.25 and row['exchange_rate']['basis'] == 'currency_units_per_GBP'
    assert row['unmapped_text_fields'] == [
        {'native_offset': '0x20', 'value': 'unit', 'meaning': 'unverified'},
        {'native_offset': '0x28', 'value': None, 'meaning': 'unverified'},
        {'native_offset': '0x30', 'value': '', 'meaning': 'unverified'}]
    assert row['complete_native_history'] and row['history_count'] == 4
    assert [x['native_year'] for x in row['history']] == [2020, 2020, 0, 65535]
    assert [x['year'] for x in row['history']] == [2020, 2020, None, None]
    assert [x['exchange_rate']['value'] for x in row['history']] == [0, 1.5, 2.25, -1]


@pytest.mark.parametrize('criteria,ids', [({}, [86,28,500]), ({'name':'FUSS'}, [500]), ({'native_id':28}, [28]),
    ({'name':'Euro','native_id':86}, []), ({'name':'missing'}, [])])
def test_filters(bridge, monkeypatch, currency_memory, criteria, ids):
    bind(bridge, monkeypatch, currency_memory)
    assert [r['native_id'] for r in bridge.find_currencies(bridge.session, **criteria)['currencies']] == ids


def test_empty_pages_query_bound_cursor_and_table_replacement(bridge, monkeypatch, currency_memory):
    m=currency_memory; bind(bridge, monkeypatch, m)
    page=bridge.find_currencies(bridge.session, name='FUSS', record_budget=1)
    assert page['count']==0 and page['next_cursor']
    with pytest.raises(BridgeError, match='different query'):
        bridge.find_currencies(bridge.session, name='Euro', cursor=page['next_cursor'])
    fresh=bridge.find_currencies(bridge.session, name='FUSS', cursor=page['next_cursor'], max_matches=1, record_budget=2)
    assert fresh['count']==1 and fresh['next_cursor'] is None and not fresh['complete_table_scan']
    m['vec'](m['headers']['currencies'], m['currency_addresses'])
    with pytest.raises(BridgeError, match='expired'):
        bridge.find_currencies(bridge.session, name='FUSS', cursor=page['next_cursor'])


@pytest.mark.parametrize('args', [{'name':''},{'name':'\ud800'},{'name':'é'*100},{'name':'x\n'},
    {'native_id':True},{'native_id':0},{'native_id':2**32},{'max_matches':101},{'record_budget':1001},{'cursor':False}])
def test_invalid_filters(bridge,args):
    with pytest.raises(BridgeError):bridge.find_currencies(bridge.session,**args)


@pytest.mark.parametrize('bits,value,state', [('00000000',0,'stored'),('00000080',-0.0,'stored'),
    ('000080bf',-1,'negative_native_rate'),('0000807f',None,'non_finite'),('000080ff',None,'non_finite'),
    ('0100c07f',None,'non_finite'),('01000000',2**-149,'stored')])
def test_rates_preserve_float_bits_and_special_values(bits,value,state):
    row=currencies.rate(bytes.fromhex(bits))
    assert row['value']==value and row['state']==state and row['native_float32_hex']==bits


@pytest.mark.parametrize('fault', ['type','getter','id','index','membership','rtti','name','table'])
def test_bad_records_never_publish_partial_refs(bridge,monkeypatch,currency_memory,fault):
    m=currency_memory;bind(bridge,monkeypatch,m);a=m['currency_addresses'][1];vt=m['base']+world.TYPES['currency'][0]
    if fault=='type':m['q'](a,m['base']+world.TYPES['club'][0])
    elif fault=='getter':m['q'](vt+24,0)
    elif fault=='id':m['put'](a+12,bytes(4))
    elif fault=='index':m['put'](a+8,struct.pack('<I',0))
    elif fault=='membership':m['vec'](m['headers']['currencies'],[m['currency_addresses'][1],m['currency_addresses'][0],m['currency_addresses'][2]])
    elif fault=='rtti':m['q'](vt-16,8)
    elif fault=='name':m['q'](a+0x18,m['text']('bad\nname'))
    else:m['q'](m['roots']['currencies'],0)
    with pytest.raises(BridgeError):bridge.find_currencies(bridge.session)
    assert not bridge.currency_refs


@pytest.mark.parametrize('fault', ['reverse','unaligned','oversized','bad_start'])
def test_bad_history_headers_reject(bridge,monkeypatch,currency_memory,fault):
    m=currency_memory;bind(bridge,monkeypatch,m)
    ref=bridge.find_currencies(bridge.session)['currencies'][0]['currency_ref'];a=m['currency_addresses'][0]
    start,end,capacity=struct.unpack('<QQQ',m['read'](a+0x40,24))
    if fault=='reverse':end=start-8
    elif fault=='unaligned':end-=1
    elif fault=='oversized':capacity=start+(currencies.MAX_HISTORY+1)*8
    else:start=0
    m['put'](a+0x40,struct.pack('<QQQ',start,end,capacity))
    with pytest.raises(BridgeError,match='history vector'):bridge.get_currency(bridge.session,ref)


def test_refresh_empty_history_and_null_name(bridge,monkeypatch,currency_memory):
    m=currency_memory;bind(bridge,monkeypatch,m)
    ref=bridge.find_currencies(bridge.session)['currencies'][1]['currency_ref'];a=m['currency_addresses'][1]
    m['q'](a+0x18,0);m['put'](a+0x40,bytes(24));m['put'](a+0x38,struct.pack('<f',3.5))
    row=bridge.get_currency(bridge.session,ref)['currency']
    assert row['name'] is None and row['exchange_rate']['value']==3.5
    assert row['history']==[] and row['history_count']==0 and row['complete_native_history']
    page=bridge.find_currencies(bridge.session)
    assert page['count']==3 and page['unnamed_records_examined']==1


@pytest.mark.parametrize('fault',['identity','random_id','membership','save','detach','cache'])
def test_reference_expiry(bridge,monkeypatch,currency_memory,fault):
    m=currency_memory;bind(bridge,monkeypatch,m);a=m['currency_addresses'][1]
    ref=bridge.find_currencies(bridge.session)['currencies'][1]['currency_ref']
    if fault=='identity':m['put'](a+12,struct.pack('<I',123))
    elif fault=='random_id':m['put'](a+16,struct.pack('<I',123))
    elif fault=='membership':m['vec'](m['headers']['currencies'],[m['currency_addresses'][1],m['currency_addresses'][0],m['currency_addresses'][2]])
    elif fault=='save':m['q'](m['save']+0x28,m['text']('Other career'))
    elif fault=='detach':bridge.detach()
    else:bridge.currency_refs.clear()
    with pytest.raises(BridgeError):bridge.get_currency(bridge.session,ref)
    assert ref not in bridge.currency_refs


def test_cache_reservation(bridge,monkeypatch,currency_memory):
    bind(bridge,monkeypatch,currency_memory)
    bridge.currency_refs.update({str(i):{} for i in range(10000)})
    rows=bridge.find_currencies(bridge.session)['currencies']
    assert len(bridge.currency_refs)==3
    assert all(bridge.get_currency(bridge.session,r['currency_ref'])['currency']['native_id']==r['native_id'] for r in rows)


@pytest.mark.parametrize('amount,source,target,expected', [('100',0,1,'125'),('100',1,0,'80'),
    ('-250.50',1,2,'-400.80'),('0',1,2,'0'),('0.000000000000000001',0,1,'0.00000000000000000125'),
    ('999999999999999999.999999999999999999',1,1,'999999999999999999.999999999999999999')])
def test_conversion_direction_precision_and_negative_balances(bridge,monkeypatch,currency_memory,amount,source,target,expected):
    bind(bridge,monkeypatch,currency_memory)
    rows=bridge.find_currencies(bridge.session)['currencies']
    result=bridge.convert_currency(bridge.session,amount,rows[source]['currency_ref'],rows[target]['currency_ref'])
    assert result['state']=='calculated' and Decimal(result['converted_amount'])==Decimal(expected)
    assert result['rate_basis']=='GBP' and result['decimal_precision']==50


@pytest.mark.parametrize('amount',[1,True,None,'',' 1','1 ','+1','01','1e3','NaN','Infinity','1.','1,000',
    '1000000000000000000','0.1234567890123456789'])
def test_conversion_input_validation(bridge,amount):
    with pytest.raises(BridgeError,match='decimal string'):bridge.convert_currency(bridge.session,amount,'a','b')


@pytest.mark.parametrize('bits',['00000000','000080bf','0000807f','0100c07f'])
def test_invalid_rates_return_explicit_unavailable(bridge,monkeypatch,currency_memory,bits):
    m=currency_memory;bind(bridge,monkeypatch,m)
    rows=bridge.find_currencies(bridge.session)['currencies'];m['put'](m['currency_addresses'][1]+0x38,bytes.fromhex(bits))
    for source,target,invalid in ((0,1,'to_currency'),(1,0,'from_currency')):
        result=bridge.convert_currency(bridge.session,'100',rows[source]['currency_ref'],rows[target]['currency_ref'])
        assert result['state']=='unavailable_rate' and result['converted_amount'] is None and result['unavailable_rates']==[invalid]


def test_conversion_rechecks_rates_and_base(bridge,monkeypatch,currency_memory):
    m=currency_memory;bind(bridge,monkeypatch,m)
    rows=bridge.find_currencies(bridge.session)['currencies'];refs=[r['currency_ref'] for r in rows]
    m['put'](m['currency_addresses'][1]+0x38,struct.pack('<f',2.5))
    assert Decimal(bridge.convert_currency(bridge.session,'100',refs[0],refs[1])['converted_amount'])==250
    m['put'](m['base']+0x538EF50,struct.pack('<I',28))
    with pytest.raises(BridgeError,match='base currency mapping'):bridge.convert_currency(bridge.session,'100',refs[0],refs[1])


@pytest.mark.parametrize('operation',['search','readback','convert'])
def test_mutation_during_read_rejects(bridge,monkeypatch,currency_memory,operation):
    m=currency_memory;bind(bridge,monkeypatch,m);refs=[r['currency_ref'] for r in bridge.find_currencies(bridge.session)['currencies']]
    target=m['currency_addresses'][1]+0x38;hits=0
    def read(address,size):
        nonlocal hits
        if (address,size)==(target,4):
            hits+=1
            if hits==2:m['put'](target,struct.pack('<f',7))
        return m['read'](address,size)
    monkeypatch.setattr(bridge,'_read_memory',lambda p,a,n:read(a,n))
    before=set(bridge.currency_refs)
    with pytest.raises(BridgeError,match='changed during read'):
        if operation=='search':bridge.find_currencies(bridge.session)
        elif operation=='readback':bridge.get_currency(bridge.session,refs[1])
        else:bridge.convert_currency(bridge.session,'100',refs[0],refs[1])
    assert set(bridge.currency_refs)<=before


def test_conversion_rounds_only_final_result(bridge,monkeypatch,currency_memory):
    m=currency_memory;bind(bridge,monkeypatch,m)
    for i,value in ((1,1.157130479812622),(2,1.3508245944976807)):
        m['put'](m['currency_addresses'][i]+0x38,struct.pack('<f',value))
    rows=bridge.find_currencies(bridge.session)['currencies'];amount='987654321012345678.123456789012345678'
    with localcontext() as context:
        context.prec=100
        expected=(Decimal(amount)*Decimal.from_float(rows[2]['exchange_rate']['value'])
                  /Decimal.from_float(rows[1]['exchange_rate']['value']))
        context.prec=50;expected=+expected
    actual=bridge.convert_currency(bridge.session,amount,rows[1]['currency_ref'],rows[2]['currency_ref'])
    assert Decimal(actual['converted_amount'])==expected
    same=bridge.convert_currency(bridge.session,amount,rows[1]['currency_ref'],rows[1]['currency_ref'])
    assert Decimal(same['converted_amount'])==Decimal(amount)


def test_exact_history_bound_and_mutation_recheck(bridge,monkeypatch,currency_memory):
    m=currency_memory;bind(bridge,monkeypatch,m);a=m['currency_addresses'][1]
    raw=struct.pack('<H2xf',2020,1.25)*currencies.MAX_HISTORY
    start=m['allocate'](len(raw));m['put'](start,raw)
    m['put'](a+0x40,struct.pack('<QQQ',start,start+len(raw),start+len(raw)))
    ref=bridge.find_currencies(bridge.session)['currencies'][1]['currency_ref']
    assert bridge.get_currency(bridge.session,ref)['currency']['history_count']==currencies.MAX_HISTORY
    hits=0
    def read(address,size):
        nonlocal hits
        if (address,size)==(start,len(raw)):
            hits+=1
            if hits==2:m['put'](start+4,struct.pack('<f',7))
        return m['read'](address,size)
    monkeypatch.setattr(bridge,'_read_memory',lambda p,a,n:read(a,n))
    with pytest.raises(BridgeError,match='changed during read'):bridge.get_currency(bridge.session,ref)
