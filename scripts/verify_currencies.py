"""Compare every currency/history record and stored-rate conversion through configured MCP."""
import asyncio
from datetime import datetime, timezone
from decimal import Decimal, localcontext
import hashlib
import json
import math
from pathlib import Path
import struct
import subprocess
import sys
import tomllib

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from fm_live_mcp import __version__


def census():
    subprocess.run([sys.executable,str(ROOT/'scripts/survey_currencies.py')],cwd=ROOT,check=True)
    result=json.loads((ROOT/'evidence/currency-survey.json').read_text());assert result['verified']
    return result


def check_rate(actual,raw):
    value=struct.unpack('<f',raw)[0]
    assert actual=={'value':value if math.isfinite(value) else None,'native_float32_hex':raw.hex(),
                    'state':'non_finite' if not math.isfinite(value) else 'negative_native_rate' if value<0 else 'stored',
                    'basis':'currency_units_per_GBP'}


def check(row,source,details=False):
    raw=bytes.fromhex(source['raw']);index,nid,random=struct.unpack_from('<III',raw,8)
    assert row['database_index']==index and row['native_id']==nid and row['random_id']==(None if random==nid else random)
    assert row['name']==source['strings']['0x18'] and row['name_source']=='stored_native_string' and row['currency_ref']
    check_rate(row['exchange_rate'],raw[0x38:0x3c])
    if details:
        assert row['unmapped_text_fields']==[{'native_offset':k,'value':source['strings'][k],'meaning':'unverified'} for k in ('0x20','0x28','0x30')]
        assert row['history_count']==len(source['history']) and row['complete_native_history']
        assert len(row['history'])==len(source['history'])
        for index,(entry,expected) in enumerate(zip(row['history'],source['history'],strict=True)):
            raw_entry=bytes.fromhex(expected['raw']);year=struct.unpack_from('<H',raw_entry)[0]
            assert entry['native_index']==index and entry['native_year']==year
            assert entry['year']==(year if 1<=year<=9999 else None)
            assert entry['year_state']==('stored' if 1<=year<=9999 else 'invalid_native_year')
            check_rate(entry['exchange_rate'],raw_entry[4:8])


async def main():
    started=datetime.now(timezone.utc).isoformat()
    proof=json.loads((ROOT/'evidence/currency-layout-verification.json').read_text());assert proof['verified']
    before=census();rows=before['records']
    config=tomllib.loads((Path.home()/'.codex/config.toml').read_text())['mcp_servers']['fm-live']
    assert config['command']=='/bin/sh' and config['args']==[str(ROOT/'scripts/run_mcp.sh')]
    paths=sorted((ROOT/'fm_live_mcp').glob('*.py'))+[ROOT/'scripts'/p for p in
        ('verify_currency_layout.py','survey_currencies.py','verify_currencies.py')]
    identities={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    conversions=0;filters=[];history_count=0;transient_retries=0
    async with stdio_client(StdioServerParameters(command=config['command'],args=config['args'])) as (read,write):
        async with ClientSession(read,write) as client:
            await client.initialize()
            async def call(tool,**args):
                nonlocal transient_retries
                for attempt in range(5):
                    result=await client.call_tool(tool,args)
                    if not result.isError or 'changed during read' not in str(result.content) or attempt==4:break
                    transient_retries+=1;await asyncio.sleep(.2)
                assert not result.isError and result.structuredContent is not None,(tool,args,result.content)
                return result.structuredContent
            status=await call('fm_status');assert status['server_version']==__version__
            assert status['capabilities']['currency_query'] and status['capabilities']['stored_currency_conversion']
            assert not status['capabilities']['memory_writes']
            tools=(await client.list_tools()).tools;assert len(tools)==52 and all(t.annotations.readOnlyHint for t in tools)
            sid=(await call('fm_attach'))['session_id']
            async def scan(**criteria):
                cursor=None;found=[];next_index=0
                while True:
                    page=await call('fm_find_currencies',session_id=sid,cursor=cursor,max_matches=23,record_budget=37,**criteria)
                    assert page['start_index']==next_index and page['total_records']==len(rows)
                    next_index=page['next_index'];found.extend(page['currencies']);cursor=page['next_cursor']
                    if cursor is None:
                        assert next_index==len(rows);break
                return found
            actual=await scan();assert len(actual)==len(rows)
            for i,(row,source) in enumerate(zip(actual,rows,strict=True)):
                check(row,source)
                fresh=(await call('fm_get_currency',session_id=sid,currency_ref=row['currency_ref']))['currency']
                check(fresh,source,True);history_count+=fresh['history_count']
                if (i+1)%50==0:print('Checked currency histories',i+1,flush=True)
            for criteria in ({'name':'Dollar'},{'name':'POUND'},{'native_id':86},{'name':'Euro','native_id':28},
                             {'name':'no matching currency name'},{'name':'Euro','native_id':86}):
                expected=[r['native_id'] for r in rows
                          if ('native_id' not in criteria or r['native_id']==criteria['native_id'])
                          and ('name' not in criteria or criteria['name'].casefold() in (r['name'] or '').casefold())]
                result=await scan(**criteria);assert [r['native_id'] for r in result]==expected
                filters.append({'criteria':criteria,'matches':len(expected)})
            by_id={r['native_id']:r for r in actual};pound=by_id[86];amount='1000000.25'
            for i,row in enumerate(actual):
                for source,target in ((pound,row),(row,pound)):
                    result=await call('fm_convert_currency',session_id=sid,amount=amount,
                                      from_currency_ref=source['currency_ref'],to_currency_ref=target['currency_ref'])
                    source_rate=source['exchange_rate']['value'];target_rate=target['exchange_rate']['value']
                    assert result['rate_basis']=='GBP' and result['rate_source']=='stored_current_exchange_rates'
                    if source_rate is None or target_rate is None or min(source_rate,target_rate)<=0:
                        assert result['state']=='unavailable_rate' and result['converted_amount'] is None
                    else:
                        # Compute with extra precision, then round once to the API precision.
                        with localcontext() as context:
                            context.prec=150
                            expected=Decimal(amount)*Decimal.from_float(target_rate)/Decimal.from_float(source_rate)
                            context.prec=50;expected=+expected
                        assert result['state']=='calculated' and Decimal(result['converted_amount'])==expected
                    conversions+=1
                if (i+1)%50==0:print('Checked bidirectional currency conversions',i+1,flush=True)
            source,target=by_id[28],by_id[87]
            result=await call('fm_convert_currency',session_id=sid,amount='-250.50',from_currency_ref=source['currency_ref'],to_currency_ref=target['currency_ref'])
            with localcontext() as context:
                context.prec=150;expected=Decimal('-250.50')*Decimal.from_float(target['exchange_rate']['value'])/Decimal.from_float(source['exchange_rate']['value'])
                context.prec=50;expected=+expected
            assert Decimal(result['converted_amount'])==expected;conversions+=1
            save=(await call('fm_get_save',session_id=sid))['save'];await call('fm_detach')
    after=census();assert before['records']==after['records'],'Currency records changed across verification'
    for p,digest in identities.items():assert hashlib.sha256((ROOT/p).read_bytes()).hexdigest()==digest
    receipt={'verified':True,'server_version':__version__,'started_at':started,'completed_at':datetime.now(timezone.utc).isoformat(),
             'save':save,'records_checked':len(rows),'readbacks_checked':len(rows),'history_entries_checked':history_count,
             'complete_scan':True,'filters':filters,'conversions_checked':conversions,'tool_count':len(tools),
             'native_before_after_equal':True,'transient_read_retries':transient_retries,'source_identity':identities,
             'proof_sha256':hashlib.sha256((ROOT/'evidence/currency-layout-verification.json').read_bytes()).hexdigest(),
             'foreground_ui_used':False,'native_execution':False}
    (ROOT/'evidence/live-currencies-mcp.json').write_text(json.dumps(receipt,indent=2)+'\n')
    print(json.dumps({k:v for k,v in receipt.items() if k not in ('source_identity','filters')},indent=2))


if __name__=='__main__':asyncio.run(main())
