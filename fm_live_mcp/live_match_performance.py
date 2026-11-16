"""Current engine/client cumulative statistics; displayed-time scope unproved."""
import math
import struct
from . import fixtures, players


def decode_side(raw, expected_team_index):
    if len(raw)!=0x1a0:
        raise ValueError('Truncated live SIDE_STATS')
    team=struct.unpack_from('<I',raw,0x5c)[0]
    if team!=expected_team_index:
        raise ValueError('Live statistics TEAM differs from canonical fixture side')
    shots,target=raw[0x16f],raw[0x170]
    xg=struct.unpack_from('<f',raw,0x60)[0]
    attempts,completed=struct.unpack_from('<hh',raw,0xd8)
    possession=struct.unpack_from('<i',raw,0x7c)[0]
    if target>shots or not math.isfinite(xg)or xg<0 or not 0<=completed<=attempts:
        raise ValueError('Invalid live cumulative statistics')
    return dict(team_index=team,shots=shots,shots_on_target=target,expected_goals=xg,
                passes_attempted=attempts,passes_completed=completed,
                pass_completion_percentage_computed=100*completed/attempts if attempts else None,
                corners=raw[0x19d],possession_time_raw=possession,
                possession_time_units=None,chances=None)


def _fixture(read,base,address):
    vt=players.u64(read(address,8))
    kind=next((k for k in('fixture','result')if vt==base+fixtures.TYPES[k][0]),None)
    if kind is None:
        raise ValueError('Unsupported live input fixture type')
    fixtures.typed(read,base,address,kind)
    packed=struct.unpack('<I',read(address+0x4c,4))[0]
    year,day=packed>>16,packed&511
    record=fixtures.record(read,base,address,year,day,{})
    return fixtures.detail(read,base,address,year,day,record,{},False)[0]


def _identity(fixture):
    return (fixture['date'],fixture['competition']['native_id'],
            *((fixture[s]['database_index'],fixture[s]['native_id'],fixture[s].get('native_type_code'))
              for s in('home_team','away_team')))


def _input(read,base,address,expected_vtable):
    raw=read(address,0x78)
    if players.u64(raw)!=base+expected_vtable:
        raise ValueError('Unsupported live statistics input type')
    fixture=_fixture(read,base,players.u64(raw,0x18))
    sides=[]
    for index,field in enumerate(('home_team','away_team')):
        ptr=players.u64(raw,0x68+8*index)
        if not ptr or ptr%8:
            raise ValueError('Absent or unaligned live statistics side')
        row=decode_side(read(ptr,0x1a0),fixture[field]['database_index'])
        row.update(side_index=index,team_native_id=fixture[field]['native_id'])
        sides.append(row)
    return dict(fixture=fixture,sides=sides,
                source_clock_words_unmapped=list(struct.unpack_from('<II',raw,0x24)))


def inspect(read,base,client,engine):
    """Use inside caller's checked active-client readset and epoch guard."""
    for rva, expected in NATIVE_SPANS:
        value=bytes.fromhex(expected)
        if read(base+rva,len(value))!=value:
            raise ValueError('Live statistics source native binding changed')
    if players.u64(read(client,8))!=base+0x55fac38 or players.u64(read(engine,8))!=base+0x55fa258:
        raise ValueError('Unsupported resident client or GAME_MATCH type')
    owner=players.u64(read(client+0xf8,8))
    if not owner or players.u64(read(owner+0x18,8))!=engine:
        raise ValueError('Live client does not own this GAME_MATCH')
    source=players.u64(read(engine+0x14e90,8))
    if not source:
        return dict(state='unavailable_engine_statistics_absent',sides=None)
    engine_input=_input(read,base,source,0x55fa850)
    client_input=_input(read,base,client+8,0x56a2380)
    if _identity(engine_input['fixture'])!=_identity(client_input['fixture']):
        raise ValueError('Engine/client cumulative statistics fixture identities differ')
    return dict(state='available_engine_cumulative_display_time_unverified',
                source_kind='resident_GAME_MATCH_owned_GAME_MATCH_STATS',
                fixture=engine_input['fixture'],
                fixture_score_semantics='provisional resident live result; not a full-time score',sides=engine_input['sides'],
                client_statistics_snapshot=client_input,
                engine_source_clock_words_unmapped=engine_input['source_clock_words_unmapped'],
                engine_client_statistics_equal=engine_input['sides']==client_input['sides'],
                temporal_scope='engine cumulative; may include events ahead of manager display',
                displayed_clock_bound=False,displayed_time_statistics_verified=False,
                possession_policy='raw native time counter; units and official displayed percentage unproved here',
                chances_state='unmapped',archive_or_saved_fixture_fallback=False)


NATIVE_SPANS = ((76440584, '688600f8e00313aa06540194'), (76788820, '286b00f008010e91087c00a9'), (41853452, 'cba20191a90240f9f62f00f9890000b4290940b9297d60d302000014e97f60b2ec4b40f97b796cf86b7974f8eb5300f9'), (41866080, '686340bd'), (41868708, '73bf4539'), (41868820, '73c34539'), (71855804, '084b89522800a0727f1b0cb96002088b87341194'), (76366712, 'c29b0194f60300aa601e02f9'))
