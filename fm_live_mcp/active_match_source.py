"""Passive typed viewable-client inventory; no active gameplay/halftime verdict.

Caller owns the current process/save ReadSet and final epoch check. A checked
empty current manager inventory is a supported negative; absent/other manager
or nonempty clients without an independently bound fixture stay unknown.
"""
import struct
from . import players

ROOT = 0x56A6AD8
MANAGER_VTABLE = 0x55FADD8
MANAGER_PRIMARY_VTABLE = 0x55FAD88
MANAGER_NAME = b'34GAME_VIEWABLE_MATCH_CLIENT_MANAGER'
MAX_CLIENTS = 16


def _read(read, address, size):
    raw = read(address, size)
    if not isinstance(raw, bytes) or len(raw) != size:
        raise ValueError('Incomplete viewable-match source read')
    return raw


def _pointer(value, *, nullable=False):
    if nullable and value == 0:
        return value
    if type(value) is not int or value < 4096 or value % 8 or value >= 1 << 48:
        raise ValueError('Invalid viewable-match source pointer')
    return value


def _u64(read, address):
    return players.u64(_read(read, address, 8))


def verify_native(read, base):
    for rva, expected in (*NATIVE_SPANS, *FIXTURE_OWNER_SPANS):
        if _read(read, base+rva, len(expected)) != expected:
            raise ValueError('Viewable-match native source changed')


def _type(read, base, address, table, displacement, name):
    if _u64(read, address) != base+table:
        raise ValueError('Viewable-match source type changed')
    offset, info = struct.unpack('<qQ', _read(read, base+table-16, 16))
    if offset != displacement:
        raise ValueError('Viewable-match source displacement changed')
    _pointer(info)
    text = _u64(read, info+8)
    if text < 4096 or _read(read, text, len(name)+1) != name+b'\0':
        raise ValueError('Viewable-match source RTTI changed')


def native_client_predicate(*, engine_present, flags):
    """Mirror48EB4DC's numeric client test, not a named match period/state."""
    if type(engine_present) is not bool or type(flags) is not int or not 0<=flags<=65535:
        raise ValueError('Invalid native viewable-client predicate inputs')
    return engine_present and not(flags & 0x1080) and (flags & 0x1800) != 0x800


def inspect(read, base):
    verify_native(read, base)
    root = _pointer(_u64(read, base+ROOT), nullable=True)
    result = {'source':'native_viewable_match_client_manager', 'source_state':'unknown',
        'reason':'manager_absent', 'physical_client_count':None,
        'native_viewable_client_predicate':None, 'clients':None,
        'bound_active_fixture':None, 'gameplay_active':None, 'halftime_state':None,
        'scope':'Current typed manager resident clients only. Not a historical export, '
                'GUI observation, replay/live distinction or fixture-bound halftime report.'}
    if not root:
        return result
    _type(read,base,root,MANAGER_VTABLE,-8,MANAGER_NAME)
    _type(read,base,root-8,MANAGER_PRIMARY_VTABLE,0,MANAGER_NAME)
    start,end,capacity = struct.unpack('<QQQ', _read(read,root+8,24))
    if (start,end,capacity) == (0,0,0):
        count=0
    else:
        for value in (start,end,capacity):_pointer(value)
        if not start<=end<=capacity or (end-start)%16 or (capacity-start)%16 or capacity-start>MAX_CLIENTS*16:
            raise ValueError('Invalid or excessive viewable-client vector')
        count=(end-start)//16
    clients=[]
    raw=_read(read,start,count*16)if count else b''
    for index in range(count):
        client,control=struct.unpack_from('<QQ',raw,index*16)
        _pointer(client);_pointer(control,nullable=True)
        table=_u64(read,client)-base
        if table==0x55FAC38:
            _type(read,base,client,table,0,b'26GAME_VIEWABLE_MATCH_CLIENT')
        elif table==0x56A1468:
            _type(read,base,client,table,0,b'N7simatch21VIEWABLE_MATCH_CLIENTE')
        else:
            raise ValueError('Unsupported viewable client type')
        owner=_pointer(_u64(read,client+0xF8),nullable=True)
        engine=_pointer(_u64(read,owner+0x18),nullable=True)if owner else 0
        flags=struct.unpack('<H',_read(read,client+0x17C,2))[0]
        clients.append({'source_index':index,'native_flags_u16':flags,
            'engine_pointer_present':bool(engine),
            'fixture_handle_present':bool(_u64(read,client+0x138)),
            'native_predicate':native_client_predicate(engine_present=bool(engine),flags=flags),
            'fixture_binding_state':'not_established', 'period_binding_state':'not_established'})
    result.update(source_state='inactive'if count==0 else'present_unbound',
        reason='checked_empty_viewable_client_inventory'if count==0 else'fixture_and_live_replay_context_unbound',
        physical_client_count=count, native_viewable_client_predicate=any(row['native_predicate']for row in clients),
        clients=clients)
    return result


NATIVE_SPANS = (
    (0x48eaaa0,bytes.fromhex('f30300aaa86d00f008411791080000f9f50300aabf8e00f81f7c01a9d66d00d0c84a45f9080100b5a86e00f008a1199108c1bf3828080036a86e00f008c11891c84a05f9e86d0090136d05f9c86d00d0')),
    (0x48eb14c,bytes.fromhex('220100542a0440f9282900a98a0000b4482100912a00805208012af836410091300000146b0640f929010bcb34fd4493890600912cfd7cd30c0600b5eceb7cb24a010bcb4bfd43937f0109eb6981899a5f010ceb0a00fe9236318a9ad56d00b0360100b4a04a45f9c8ee7cd3f70301aae10308aa11aae997e10317aae80240f902000014000080d20910148b2a0440f91710168b282900a98a0000b4482100912a00805208012af83641009161a240a9020101cb340102cbe00314aaea0e0894610640f974da00a9680e40f9770e00f9810000b4020101cba04a45f92babe997760a00f9fd7b43a9')),
    (0x48eb4dc,bytes.fromhex('08a440a91f0109eb000200540a1082520b0140f96c7d40f92c0100b48c0d40f9ec0000b46bf942797f010a6a810000546b0515127f012071c1000054084100911f0109eb61feff5400008052c0035fd620008052c0035fd6')),
    (0x48eb24c,bytes.fromhex('08a440a91f0109eb200100540a0140f94a9d40f95f0101eba0000054084100911f0109eb41ffff54e80309aa1f0109ebe0079f1a')),
    (0x48e6a1c,bytes.fromhex('087c40f9680000b4000d40f9c0035fd6000080d2c0035fd6')),
)


def _fixture(read, base, address):
    from datetime import date, timedelta
    from . import fixtures, teams
    _pointer(address)
    packed = struct.unpack('<I', _read(read, address+0x4C, 4))[0]
    year, day = packed >> 16, packed & 511
    if not 1850 <= year <= 2200 or not 1 <= day <= 366:
        raise ValueError('Invalid active input fixture date')
    value = date(year,1,1)+timedelta(days=day-1)
    if value.year != year:
        raise ValueError('Invalid active input fixture calendar day')
    decoded = fixtures.record(read,base,address,year,day,{})
    if decoded['competition'] is None or any(row is None for row in decoded['team_ids']):
        raise ValueError('Incomplete active input competition or sides')
    sides=[]
    for pointer, identity in zip(decoded['teams'], decoded['team_ids'], strict=True):
        public,binding=teams.by_index(read,base,identity[0])
        if binding['address'] != pointer or public['native_id'] != identity[1]:
            raise ValueError('Active input canonical TEAM disagrees')
        sides.append(public)
    # No score or record-kind comparison: resident and input records are separate
    # native copies; a RESULT class does not establish match completion.
    name=decoded['name_identity']
    signature=(year,day,tuple(decoded['team_ids']),decoded['competition']['database_index'],
               decoded['competition']['native_id'],decoded['season_code'],
               decoded['stage_index'],None if name is None else name[:4])
    public={'date':value.isoformat(),'record_kind':decoded['kind']+'_record',
            'competition':decoded['competition'],'home_team':sides[0],'away_team':sides[1],
            'native_season_code':decoded['season_code'],
            'match_completion_state':'not_established'}
    return signature,public,decoded,year,day


def _resident_day(read,base,signature,year,day,team_addresses):
    from . import fixtures
    _,years,_=fixtures.catalog(read,base)
    binding=years.get(year)
    if binding is None:
        return {'state':'unavailable_year'},None
    if len(binding['groups'])>128 or any(not flag&1 for flag in binding['flags']):
        return {'state':'incomplete_or_excessive_resident_groups'},None
    count=0;matches=[];seen=set()
    cache = {}
    for group in range(len(binding['groups'])):
        entries,_=fixtures.bucket(read,binding,day,group)
        count+=len(entries)
        if count>2000:
            return {'state':'resident_day_budget_exceeded'},None
        for address in entries:
            if address in seen:
                continue
            seen.add(address)
            # Read the cheap source team/date/competition keys before expanding
            # names and sides of unrelated same-day fixtures.
            decoded=fixtures.record(read,base,address,year,day,cache,ordered_team_addresses=team_addresses)
            if decoded.get('filter_match') is False:
                continue
            name=decoded['name_identity'];comp=decoded['competition']
            key=(year,day,tuple(decoded['team_ids']),None if comp is None else comp['database_index'],
                 None if comp is None else comp['native_id'],decoded['season_code'],
                 decoded['stage_index'],None if name is None else name[:4])
            if key==signature:
                matches.append(address)
    return {'state':'unique_semantic_match'if len(matches)==1 else'absent_or_ambiguous',
            'matching_records':len(matches),'checked_physical_records':count,
            'all_current_day_groups_materialized':True},matches[0]if len(matches)==1 else None


def inspect_context(read,base,*,expected_current_date=None):
    """Return(public,private) with exact current fixture binding when proved.

    Private contains client/engine pointers for other bounded native adapters.
    Never merge private into an MCP response. Caller still verifies ReadSet+epoch.
    A bound match is not proof of live-vs-replay or displayed-time synchronization.
    """
    from . import world,player_injury_status
    public=inspect(read,base)
    if public['source_state'] in('unknown','inactive'):
        return public,None
    eligible=[row for row in public['clients']if row['native_predicate']]
    if len(eligible)!=1:
        public['reason']='no_unique_native_viewable_client'
        return public,None
    root=_u64(read,base+ROOT);start=_u64(read,root+8)
    client=_u64(read,start+eligible[0]['source_index']*16)
    _type(read,base,client,0x55FAC38,0,b'26GAME_VIEWABLE_MATCH_CLIENT')
    owner=_pointer(_u64(read,client+0xF8));engine=_pointer(_u64(read,owner+0x18))
    _type(read,base,engine,0x55FA258,0,b'10GAME_MATCH')
    if _u64(read,client+0x138)!=_u64(read,engine+0x20):
        raise ValueError('Viewable client and owned engine handle disagree')
    stats=_pointer(_u64(read,engine+0x14E90),nullable=True)
    if not stats:
        public['reason']='owned_engine_statistics_absent'
        return public,None
    _type(read,base,stats,0x55FA850,0,b'16GAME_MATCH_STATS')
    _type(read,base,client+8,0x56A2380,0,b'N13simatchshared11MATCH_STATSE')
    engine_fixture=_pointer(_u64(read,stats+0x18))
    client_fixture=_pointer(_u64(read,client+8+0x18))
    signature,fixture,decoded,year,day=_fixture(read,base,engine_fixture)
    other,_,_,_,_=_fixture(read,base,client_fixture)
    if signature!=other:
        raise ValueError('Engine and viewable-client fixture identities disagree')
    source_date=player_injury_status.calendar(_read(read,base+world.CURRENT_DATE,4))[0].isoformat()
    if expected_current_date is not None and expected_current_date!=source_date:
        raise ValueError('Active-match date differs from checked save')
    if fixture['date']!=source_date:
        public.update(reason='viewable_fixture_not_current_career_date',source_date=source_date)
        return public,None
    team_indices=[row[0]for row in decoded['team_ids']]
    for side,index in enumerate(team_indices):
        side_object=_pointer(_u64(read,engine+0x15370+side*8))
        if _u64(read,side_object+0xB8)!=decoded['teams'][side]:
            raise ValueError('Owned MATCH side canonical TEAM disagrees with fixture')
    resident,address= _resident_day(read,base,signature,year,day,tuple(decoded['teams']))
    if address is None:
        public.update(reason='resident_fixture_identity_not_uniquely_bound',
                      fixture_binding_state=resident,source_date=source_date)
        return public,None
    public.update(source_state='available_fixture_bound',reason=None,source_date=source_date,
        bound_active_fixture=fixture,fixture_binding_state=resident,
        binding_scope='owned_client_engine_and_statistics_copies_plus_unique_resident_current_day_fixture',
        replay_live_state='not_established',display_synchronization='not_established')
    public['clients'][eligible[0]['source_index']]['fixture_binding_state']='canonical_current_day_fixture_bound'
    private={'engine':engine,'client':client,'team_indices':team_indices,
        'engine_stats':stats,'engine_fixture':engine_fixture,'client_fixture':client_fixture,
        'resident_fixture_address':address}
    return public,private


# Native MATCH-owned stats construction and shared MATCH_STATS input base.
FIXTURE_OWNER_SPANS = (
    (0x4486ebc,bytes.fromhex('084b89522800a0727f1b0cb96002088b87341194')),
    (0x48d4378,bytes.fromhex('c29b0194f60300aa601e02f900238052e9680894f50300aa360080522100805295fffe97752202f9a80236b8')),
    (0x493b454,bytes.fromhex('286b00f008010e91087c00a9')),
)
