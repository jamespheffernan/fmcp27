"""Independent bounded native census for stage/table public-query comparisons."""
import collections, json, struct, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from fm_live_mcp.bridge import Bridge
from fm_live_mcp import database, players, world

b = Bridge(); sid = b.attach()['session_id']
rows = []; types = {}; identity = None
def native_vector(read, address, limit):
    start, end, capacity = struct.unpack('<QQQ',read(address,24))
    if (start,end,capacity)==(0,0,0):return []
    assert start>=4096 and start<=end<=capacity
    assert not any(x%8 for x in (start,end,capacity)) and capacity-start<=limit*8
    data=read(start,end-start) if end>start else b''
    entries=[v for (v,) in struct.iter_unpack('<Q',data)]
    assert all(v==0 or v>=4096 and v%8==0 for v in entries)
    return entries
try:
    start = 0
    while True:
        with b.lock, b._read_scope(sid):
            p = b._current(sid); layout = b._player_layout(p)
            base = layout[0]-players.RVA[0]
            read, _, _ = b._world_state(p, layout)
            info = database.table(read, base, 'competitions')
            assert info['count'] <= 200000, 'competition census exceeds bounded limit'
            team_table = database.table(read, base, 'teams')
            if identity is not None: assert identity == info['identity']
            identity = info['identity']
            end = min(start+250, info['count'])
            for index in range(start, end):
                comp = world.pointer(read, info['start']+8*index)
                runtime = players.u64(read(comp+0xb0, 8))
                if not runtime: continue
                runtime_comp = world.pointer(read, runtime+0x138)
                runtime_comp_index = int.from_bytes(read(runtime_comp+8,4),'little')
                assert runtime_comp_index < info['count']
                assert world.pointer(read,info['start']+runtime_comp_index*8)==runtime_comp
                comp_row = {'competition_index': index, 'runtime_competition_index':runtime_comp_index, 'runtime_address':hex(runtime), 'native_id': int.from_bytes(read(comp+12,4),'little'), 'runtime_vtable':hex(world.pointer(read,runtime)-base), 'native_season_code':int.from_bytes(read(runtime+0x3b0,2),'little'), 'stages':[]}
                stage_entries = [(str(i),s) for i,s in enumerate(native_vector(read,runtime+0x1d8,256))]
                for stage_index, stage in stage_entries:
                    if not stage:
                        comp_row['stages'].append({'stage_index':stage_index,'null':True});continue
                    vtable = world.pointer(read,stage); kind = hex(vtable-base)
                    if kind not in types:
                        assert base+0x5400000 <= vtable < base+0x56a4000
                        metadata = read(vtable-16,16)
                        typeinfo = players.u64(metadata,8)
                        name = players.u64(read(typeinfo+8,8))
                        assert base <= name < base+0x5884e40
                        types[kind] = {'rtti':read(name,140).split(b'\0')[0].decode(),'displacement':struct.unpack_from('<q',metadata)[0]}
                    stage_comp = players.u64(read(stage+0x70,8))
                    row = {'stage_index':stage_index,'address':hex(stage),'vtable':kind,'comp_backlink':stage_comp==comp,'runtime_comp_backlink':stage_comp==runtime_comp,'raw_header':read(stage+0x48,16).hex()}
                    if kind == '0x5673fe0':
                        assert '/' not in stage_index, 'unexpected nested GROUP_STAGE'
                        children=native_vector(read,stage+0xd0,256)
                        assert len(stage_entries)+len(children) <= 1024, 'stage census exceeds bounded limit'
                        row['group_count']=len(children)
                        stage_entries.extend((f'{stage_index}/{i}',s) for i,s in enumerate(children))
                    if kind == '0x56759f8':
                        settings = world.pointer(read,stage+0xf0)
                        assert world.pointer(read,settings) == base+0x5675f28
                        row['point_rules'] = list(struct.unpack('<6b',read(settings+0x98,6)))
                        row['native_view_code'] = struct.unpack('<b',read(stage+0x101,1))[0]
                        row['native_count'] = struct.unpack('<b',read(stage+0x100,1))[0]
                        row['rows'] = []
                        for order,child in enumerate(world.vector(read,stage+0xc0,1024)):
                            raw = read(child,0xf8)
                            team = players.u64(raw,0x88)
                            team_index = int.from_bytes(read(team+8,4),'little') if team else None
                            if team:
                                assert team_index < team_table['count']
                                assert world.pointer(read,team_table['start']+team_index*8)==team
                            row['rows'].append({'index':order,'team_index':team_index,'native_id':int.from_bytes(read(team+12,4),'little') if team else None,
                                'stats':raw[:0x80].hex(),'tail':raw[0xd0:0xf8].hex()})
                    comp_row['stages'].append(row)
                rows.append(comp_row)
            read.verify()
        print(f'{end}/{info["count"]}: {len(rows)} runtime competitions',flush=True)
        if end == info['count']:break
        start = end
finally:
    b.detach()
receipt={'verified':True,'competition_count':info['count'],'types':types,'competitions':rows,'scope':'Non-atomic batched census with per-batch consumed-byte rechecks; raw counters and native order retained for independent comparison'}
(ROOT/'evidence/runtime-stage-survey.json').write_text(json.dumps(receipt,indent=2)+'\n')
print(json.dumps({'types':types,'stage_counts':dict(collections.Counter(s.get('vtable','null') for c in rows for s in c['stages']))},indent=2))
