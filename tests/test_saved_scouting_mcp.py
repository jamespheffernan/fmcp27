import asyncio
from pathlib import Path
import sys
from mcp import ClientSession,StdioServerParameters
from mcp.client.stdio import stdio_client

def test_scouting_registration_and_strict_arguments():
 async def check():
  params=StdioServerParameters(command=sys.executable,args=['-m','fm_live_mcp.server'],cwd=str(Path(__file__).resolve().parents[1]))
  async with stdio_client(params)as(read,write):
   async with ClientSession(read,write)as client:
    await client.initialize();tools=(await client.list_tools()).tools;t=next(t for t in tools if t.name=='fm_find_saved_players')
    assert t.annotations.readOnlyHint is True and t.annotations.destructiveHint is False
    assert set(t.inputSchema['required'])=={'filename','expected_snapshot_id'}
    for extra in ({'criteria':{'ability.current':{'min':True}}},{'min_age':True},{'scan_limit':10001},{'limit':0},{'cursor':'stale'},{'criteria':{}}):
     assert(await client.call_tool(t.name,{'filename':'x.fm','expected_snapshot_id':'pin',**extra})).isError
 asyncio.run(check())
