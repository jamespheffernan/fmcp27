"""Read existing typed per-TEAM match-form rings without materialization."""
import hashlib
import struct
from datetime import datetime, timezone

from . import competitions, database, players, teams, world

SCOPE = ('Existing resident per-TEAM form rings only; retained entries can span seasons and '
         'omit older matches. A form entry, a missing statistics pointer and team-sheet selection '
         'do not prove an appearance or match completion. Confirmed appearances here require '
         'positive stored playing duration or a positive recorded substitution-on minute; '
         'zero-minute records and missing/undated records remain explicit. Opponent is the '
         'native producer-selected opposite fixture TEAM; no fixture reference or unique fixture '
         'identity is retained in these rows. Reads are non-atomic with consumed-byte rechecks.')

NATIVE_GUARDS = (
    (0x153a5d4, 64, 'd956695be4083c6c9d76d8bf06e00fc73061e279a340f8200f06c45175ddebd3'),
    (0x153b390, 64, '094f1cdb80405260dca78480366ee38fcb52e692116dcbd384c2d7630d791484'),
    (0x153a5dc, 64, '419f13e250cf3a3ac78d796ad8abf538e71f0eb9377765a0315bd0ee9a78a693'),
    (0x153b398, 64, '6dd38ea7b5c2881055911807b7b218dfc1e46125fc9626769b5c48f69eef2ba9'),
    (0x32fc080, 1152, 'e7a180d080e652ab1e4c7f6981a71819abce9936a5879f1f2822141c0b4ec7d6'),
    (0x153f518, 2388, '57fb7aaedc8abac6ffa03eb18c8a5116fcf826dc852fed52673451a1b7573a47'),
    (0x153ce10, 260, 'dc3ac5839b9d8016612cbaa76d0d9f24ce00b81dd1290630357ad9b3d0e2d81e'),
    (0x153a504, 208, '1fe5a7dde9eeec9208c3c1c5c03596a94274015c0636fc841866d2e831f2ac5c'),
    (0x153b1d8, 276, 'fec03897e5e727cd812d6bcaae87b4f5b0f3d1c810a6857f20e77ef2f588f1b9'),
    (0x153ef98, 1408, '66773ee82542ce1005f9ef33d23c272f740e5ca11ffc60be6162de5085843e84'),
    (0xd1a1ac, 120, '53ff7e6278179f282ae8f6ea966c830eceb2d1ef1cf622e97bc24bedbc7d42b1'),
    (0x153ad48, 128, 'b776a4cd9656a219b484914c755582e424863a28d3ed44b2d40de0b7b5ad97ca'),
    (0x153b930, 128, '95e91d79204014a6302116a33f710bb9b1b19fb4dcb59a6bbfe654b245b27bf3'),
    (0x153b6c8, 8, '0e6de766d449fe554507239b6a7ad2c85106a33b67dea05075aa7cbb025dafb1'),
    (0x153bf78, 8, '819f7d29f35d1e892da3b49f4fc63044f3ff5fdce304b2eb2a6919d832549125'),
    (0x153b6d0, 32, 'a6d38adef4aefd4bd31f04ac7e3b35b09c0f0b7eb2b53c396c43e253ea1ccc2c'),
    (0x153bf80, 40, 'e5620975e7eeacfa3baa7a87ad0f700bccdf1e78cb64960ea49f752975dc3fc1'),
)
DISPATCH = (0x539ad4d, 65, '9a9c4cf8167f06c7229333216f9e49eeb5970acc9bf0b5ad8b759061bf868efb')

GROUPS = {
    0x55BA1E0: (20, 0xB8, (0x153A5D4, 0x153B390, 0x153A5DC, 0x153B398)),
    0x55BA270: (60, 0x1F8, (0x153B6C8, 0x153BF78, 0x153B6D0, 0x153BF80)),
}


def verify_native(read, base):
    for rva, size, expected in (*NATIVE_GUARDS, DISPATCH):
        if hashlib.sha256(read(base+rva, size)).hexdigest() != expected:
            raise ValueError(f'Match-form native code changed at {rva:#x}')


def _pointer(value):
    if value < 4096 or value % 8:
        raise ValueError('Invalid match-form pointer')
    return value


def _team(read, base, address, info):
    _pointer(address)
    index = struct.unpack('<I', read(address+8, 4))[0]
    row, binding = teams.by_index(read, base, index, info=info)
    if binding['address'] != address:
        raise ValueError('Match-form TEAM canonical membership changed')
    return row, binding


def statistics(raw):
    if raw is None:
        return {'state':'unavailable_missing_statistics', 'goals':None, 'minutes':None,
                'minutes_raw':None, 'substitution_on_minute':None,
                'substitution_on_minute_raw':None,
                'appearance_state':'unknown_missing_statistics'}
    if len(raw) != 37:
        raise ValueError('Invalid match-form statistics width')
    minute, on = raw[0x15], raw[0x11]
    known = minute <= 127
    state = ('confirmed_positive_stored_duration' if known and minute > 0 else
             'confirmed_recorded_substitution_on' if 0 < on <= 127 else
             'unknown_unmapped_duration' if not known else 'unknown_zero_minutes')
    return {'state':'stored_statistics', 'goals':raw[7],
            'minutes':minute if known else None, 'minutes_raw':minute,
            'substitution_on_minute':on if 0 < on <= 127 else None,
            'substitution_on_minute_raw':on, 'appearance_state':state}


def select(rows, mode, limit):
    if mode not in ('confirmed_appearances', 'team_entries'):
        raise ValueError('mode must be confirmed_appearances or team_entries')
    if type(limit) is not int or not 1 <= limit <= 60:
        raise ValueError('limit must be an integer from 1 to 60')
    ordered = sorted(rows, key=lambda r:(r['date'] or '', r['native_row_index']), reverse=True)
    dated = [r for r in ordered if r['date'] is not None]
    confirmed = [r for r in dated if r['appearance_state'].startswith('confirmed_')]
    chosen = (confirmed if mode == 'confirmed_appearances' else dated)[:limit]
    cutoff = chosen[-1]['date'] if len(chosen) == limit else None
    ambiguous = [r for r in ordered if r['date'] is None or
                 ((cutoff is None or r['date'] >= cutoff) and not r['appearance_state'].startswith('confirmed_'))]
    ties = sorted({r['date'] for r in dated if sum(x['date']==r['date'] for x in dated)>1})
    return {'mode':mode, 'rows':chosen, 'count':len(chosen),
            'retained_entry_count':len(rows), 'confirmed_appearance_count':len(confirmed),
            'ambiguous_entries_at_or_after_cutoff':ambiguous,
            'undated_entries':[r for r in ordered if r['date'] is None],
            'same_day_ties':ties, 'same_day_order':'reverse_native_ring_order_not_kickoff_order',
            'last_confirmed_rows_unambiguous_within_resident_ring':bool(len(chosen)==limit and not ambiguous and not ties)}


def decode(read, base, address, tables, team_address, mode, limit):
    verify_native(read, base)
    if players.u64(read(address,8)) != tables[0]:
        raise ValueError('Match form supports canonical regular ACTUAL_PLAYER only')
    if tuple(players.u64(read(address+off,8)) for off in (0,0x140,0x388)) != tables:
        raise ValueError('Match-form player runtime type changed')
    person = address+0x388
    identity = struct.unpack('<III', read(person+8,12))
    info = database.table(read,base,'people')
    database.player_membership(read,base,info,identity[0],address)
    ti=teams.lookup(read,base)
    selected_team,_ = _team(read,base,team_address,ti)
    def unavailable(reason, group_count=None):
        return {'source_state':'unavailable', 'unavailable_reason':reason,
                'team':selected_team, 'native_identity':dict(database_index=identity[0],
                    native_id=identity[1],secondary_id=identity[2]),
                'group_count':group_count, 'capacity':None,
                'selection':None, 'limitations':SCOPE}
    f0=players.u64(read(address+0xF0,8))
    if not f0:return unavailable('player_secondary_not_resident')
    _pointer(f0)
    form=players.u64(read(f0+0x58,8))
    if not form:return unavailable('match_form_not_resident')
    groups=world.vector(read,_pointer(form),128)
    seen_teams=set();selected=None
    for group_index,g in enumerate(groups):
        vt=world.pointer(read,g);rva=vt-base
        if rva not in GROUPS:raise ValueError('Unsupported match-form group type')
        cap,head_offset,getters=GROUPS[rva]
        displacement,typ=struct.unpack('<qQ',read(vt-16,16))
        name=players.u64(read(typ+8,8));expected=f'N2db25PLAYER_TEAM_FORM_CONCRETEILm{cap}EEE'.encode()+b'\0'
        if displacement or read(name,len(expected))!=expected:
            raise ValueError('Match-form group RTTI changed')
        if tuple(players.u64(read(vt+slot,8))-base for slot in (0x30,0x38,0x40,0x48))!=getters:
            raise ValueError('Match-form group getter changed')
        raw=read(g,head_offset+1);count,head=raw[0x10],raw[head_offset]
        if count>cap or head>=cap:raise ValueError('Invalid match-form ring geometry')
        owner=players.u64(raw,8);_team(read,base,owner,ti)
        if owner in seen_teams:raise ValueError('Ambiguous duplicate match-form TEAM groups')
        seen_teams.add(owner)
        if owner==team_address:selected=(group_index,cap,count,head,raw)
    if selected is None:return unavailable('no_retained_group_for_selected_team',len(groups))
    group_index,cap,count,head,raw=selected
    ptrs=struct.unpack_from('<'+'Q'*cap,raw,0x18)
    result=[];seen=set();cache={};comps={}
    for i in range(count):
        physical=(head+i)%cap;row_pointer=_pointer(ptrs[physical])
        if row_pointer in seen:raise ValueError('Duplicate match-form row pointer')
        seen.add(row_pointer);row=read(row_pointer,0x20)
        opponent,stats_pointer=struct.unpack_from('<QQ',row)
        if opponent and opponent not in cache:cache[opponent]=_team(read,base,opponent,ti)[0]
        raw_date=row[0x10:0x14]
        try:day=world.packed_date(raw_date)
        except ValueError:day=None
        # The native default DATE is not a dated match.
        if struct.unpack('<I',raw_date)[0]>>16==1900 and struct.unpack('<H',raw_date[:2])[0]&511==1:day=None
        competition=struct.unpack_from('<i',row,0x14)[0]
        if competition < -1:raise ValueError('Invalid match-form competition index')
        if competition>=0 and competition not in comps:comps[competition]=competitions.by_index(read,base,competition)
        stats=statistics(read(_pointer(stats_pointer),37) if stats_pointer else None)
        result.append({'native_row_index':i,'physical_ring_slot':physical,
                       'date':day,'date_state':'stored_date' if day else 'unavailable_packed_date',
                       'raw_date_hex':raw_date.hex(),'opponent':cache.get(opponent),
                       'opponent_state':'canonical_team' if opponent else 'unavailable_null_team',
                       'competition':comps.get(competition), 'competition_index':competition,
                       'competition_state':'canonical_competition' if competition>=0 else 'unavailable_native_sentinel',
                       'raw_status_code':row[0x18], **stats})
    return {'source_state':'available', 'unavailable_reason':None,'team':selected_team,
            'native_identity':dict(database_index=identity[0],native_id=identity[1],secondary_id=identity[2]),
            'group_count':len(groups),'selected_group_index':group_index,'capacity':cap,
            'retention_state':'at_capacity_older_entries_may_be_overwritten' if count==cap else 'bounded_resident_ring',
            'selection':select(result,mode,limit),'whole_career_complete':False,'limitations':SCOPE}


def collect(bridge, session_id, player_ref, team_ref, mode, limit):
    # Validate options even when the native source is unavailable.
    select([],mode,limit)
    process=bridge._current(session_id)
    saved=bridge.player_refs.get(player_ref)
    if not saved:raise ValueError('Unknown or expired player reference; find the player again')
    tables=bridge._player_layout(process)
    if tables!=saved['tables']:raise ValueError('Player layout changed')
    snapshot,save,_=bridge._world_state(process,tables);base=tables[0]-players.RVA[0]
    if players.u64(snapshot(saved['address'],8))!=tables[0]:
        raise ValueError('Match form for virtual or combined player/staff is unsupported')
    record,identity=bridge._roster_player(snapshot,saved['address'],tables,False,{})
    if identity!=saved['identity']:raise ValueError('Player identity changed')
    if record.get('record_kind','actual')!='actual':
        raise ValueError('Match form for virtual or combined player/staff is unsupported')
    if team_ref is None:
        team_address=bridge._select_coach(save,None)['team_address']
    else:
        binding=bridge.team_refs.get(team_ref)
        if not binding or binding['tables']!=tables:raise ValueError('Unknown or expired team reference')
        team_address=binding['address']
        if snapshot(team_address+8,12)!=binding['identity']:raise ValueError('Team identity changed')
        _,canonical=_team(snapshot,base,team_address,teams.lookup(snapshot,base))
        if binding.get('source')=='competition':
            if any(canonical[key]!=binding[key] for key in canonical):raise ValueError('Team binding changed')
        elif canonical['owner_address']!=binding.get('club_address'):
            raise ValueError('Team club association changed')
        if binding.get('club_identity') is not None:
            _,club_identity=world.club(snapshot,base,canonical['owner_address'])
            if club_identity!=binding['club_identity']:
                raise ValueError('Team owner identity changed')
    value=decode(snapshot,base,saved['address'],tables,team_address,mode,limit)
    if saved.get('database_index',value['native_identity']['database_index'])!=value['native_identity']['database_index']:
        raise ValueError('Player database index changed')
    snapshot.verify();bridge._current(session_id)
    return {'session_id':session_id,'player_ref':player_ref,'team_ref':team_ref,
            'observed_at':datetime.now(timezone.utc).isoformat(),'save':bridge._public_save(save),
            'player':{'name':record['name'],'record_kind':'actual'},**value,
            'snapshot':'best-effort non-atomic; identity and consumed bytes rechecked'}
