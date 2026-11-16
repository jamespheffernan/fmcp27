"""Official native score selection at a bound playback cursor, passively read.

No final/provisional fixture score, period guess, UI access or game calls. The
caller owns playback identity, optional first-half boundary proof and the final
ReadSet/process/save epoch check. Returned data contains no native pointers.
"""
import struct
from . import players

MAX_INCIDENTS = 2048


def _pointer(value):
    if type(value) is not int or not 4096 <= value < 1 << 48 or value % 8:
        raise ValueError('Invalid playback-score source pointer')
    return value


def _q(read,address):
    raw=read(address,8)
    if not isinstance(raw,bytes)or len(raw)!=8:
        raise ValueError('Incomplete playback-score source read')
    return players.u64(raw)


def _unknown(reason):
    return {'state':'unavailable','reason':reason,'home_goals':None,'away_goals':None}


def project_incidents(records,current_time_slice):
    """Mirror493F8DC's signed-slice physical-prefix path and unsigned counters.

    Equal slices count inclusively. Kind2 reverses the stored side. Kinds1/3
    credit the stored side. Other kinds, including7/8, do not change the score.
    Native counters wrap at256; meaningful public scores remain unknown on wrap.
    """
    if type(current_time_slice)is not int or not 0<=current_time_slice<1<<31:
        return _unknown('unsupported_negative_or_out_of_range_time_slice')
    if not isinstance(records,(list,tuple))or len(records)>MAX_INCIDENTS:
        raise ValueError('Playback-score incident bound exceeded')
    goals=[0,0];seen=0;first_future=None
    for index,raw in enumerate(records):
        if not isinstance(raw,bytes)or len(raw)!=32:
            raise ValueError('Invalid playback-score incident size')
        time_slice=struct.unpack_from('<i',raw,0x18)[0]
        if time_slice>current_time_slice:
            first_future=index
            break
        seen+=1;kind,side=raw[0x1f],raw[0x1d]
        if kind in(1,3):
            if side in(0,1):goals[side]+=1
        elif kind==2:
            if side in(0,1):goals[1-side]+=1
    wrapped=any(value>255 for value in goals)
    return {'state':'unavailable'if wrapped else'available',
            'reason':'native_unsigned_score_counter_wrapped'if wrapped else None,
            'home_goals':None if wrapped else goals[0], 'away_goals':None if wrapped else goals[1],
            'native_u8_score':{'home':goals[0]&255,'away':goals[1]&255},
            'at_time_slice':current_time_slice,
            'prefix_records_considered':seen,
            'stopped_at_first_future_record':first_future is not None,
            'tie_policy':'inclusive_time_slice_all_encountered_records',
            'physical_order_policy':'stop_at_first_future_record_like_native_getter',
            'time_slice_domain':'native_playback_time_slice'}


def _boundary_score(records,bound_playback,boundary,current):
    if boundary is None:
        return _unknown('verified_first_half_boundary_not_supplied')
    if not isinstance(boundary,dict):
        raise ValueError('Invalid trusted first-half boundary')
    if (boundary.get('state')!='verified_first_half_boundary'
            or boundary.get('time_slice_domain')!='native_playback_time_slice'
            or boundary.get('period')!='FirstHalf'):
        return _unknown('first_half_boundary_source_unproved')
    if (type(boundary.get('official_match_unique_id'))is not int
            or boundary['official_match_unique_id']!=bound_playback['official_match_unique_id']):
        raise ValueError('First-half boundary belongs to another playback source')
    cutoff=boundary.get('time_slice')
    start=boundary.get('start_tick')
    end=boundary.get('end_tick')
    second_start=boundary.get('second_half_start_tick')
    if (type(cutoff)is not int or type(start)is not int or type(end)is not int
            or cutoff!=end or not 0<=start<=cutoff<=current
            or (second_start is not None and(type(second_start)is not int or second_start<=end))):
        return _unknown('first_half_boundary_outside_observed_playback')
    result=project_incidents(records,cutoff)
    result['scope']='official_score_at_caller_verified_first_half_boundary'
    result['boundary_proof_owner']='caller_same_readset_native_first_half_boundary'
    return result


def capture(read,base,*,bound_playback,current_time_slice=None,trusted_first_half_boundary=None):
    """Select current and optional first-half scores from one official ledger.

    bound_playback is spatial's already source-bound private playback dictionary.
    Optional first-half boundary must be source-proved by the caller in this same
    ReadSet, not a rounded minute, supplied goal time or arbitrary user cutoff.
    """
    if not isinstance(bound_playback,dict):
        raise ValueError('A bound playback source is required')
    for rva,expected in NATIVE_SPANS:
        if read(base+rva,len(expected))!=expected:
            raise ValueError('Official playback-score native algorithm changed')
    required=('playback_address','frame_provider_address','source_match_address',
              'official_match_unique_id','current_time_slice')
    if any(type(bound_playback.get(key))is not int for key in required):
        raise ValueError('Incomplete typed bound playback source')
    if bound_playback['official_match_unique_id'] <= 0:
        raise ValueError('Missing bound official match identity')
    backing,provider,match=(_pointer(bound_playback[key])for key in required[:3])
    cursor=bound_playback['current_time_slice']if current_time_slice is None else current_time_slice
    if type(cursor)is not int or cursor!=bound_playback['current_time_slice']:
        raise ValueError('Score cursor differs from bound playback cursor')
    if not 0<=cursor<1<<31:
        return {'state':'unavailable','reason':'unsupported_playback_cursor',
                'current_score':None,'first_half_score':None}
    interface=_pointer(_q(read,base+0x5721EB0))
    if _q(read,interface)!=base+0x54EC0C8:
        raise ValueError('Playback-score primary owner type changed')
    owners=[_q(read,interface+field)for field in(0x58,0x60)]
    if owners.count(backing)!=1:
        raise ValueError('Playback-score backing is no longer a unique current owner')
    if _q(read,backing)!=base+0x54EC490 or _q(read,backing+0x10)!=backing:
        raise ValueError('Playback-score backing type or self binding changed')
    if _q(read,backing+0x1408)!=provider or _q(read,provider+0x28)!=match:
        raise ValueError('Playback-score frame provider binding changed')
    if _q(read,match)!=base+0x55FA258 or _q(read,match+0x20)!=bound_playback['official_match_unique_id']:
        raise ValueError('Playback-score match identity changed')
    if struct.unpack('<i',read(backing+0x1DC0,4))[0]!=cursor:
        raise ValueError('Playback-score current slice changed')
    owner=_pointer(_q(read,provider))
    stats=_pointer(_q(read,owner+0x58))
    if _q(read,stats)not in(base+0x55FA850,base+0x56A2380):
        raise ValueError('Unsupported provider-selected score statistics type')
    start,end,capacity=struct.unpack('<QQQ',read(stats+0x38,24))
    if (start,end,capacity)==(0,0,0):
        count=0
    else:
        for value in(start,end,capacity):_pointer(value)
        if not start<=end<=capacity or (end-start)%8 or(capacity-start)%8 or capacity-start>MAX_INCIDENTS*8:
            raise ValueError('Invalid or excessive playback-score incident vector')
        count=(end-start)//8
    pointers=read(start,count*8)if count else b''
    records=[]
    for index in range(count):
        address=_pointer(struct.unpack_from('<Q',pointers,index*8)[0])
        records.append(read(address,32))
    current=project_incidents(records,cursor)
    first_half=_boundary_score(records,bound_playback,trusted_first_half_boundary,cursor)
    return {'state':'available_at_bound_playback_cursor'if current['state']=='available'else'unavailable',
            'source':'official_MatchState_781BE0_to_493F8DC_score_selection',
            'official_match_unique_id':bound_playback['official_match_unique_id'],
            'current_time_slice':cursor,'current_score':current,'first_half_score':first_half,
            'score_source_time_domain_verified':True,
            'rendered_pixels_verified':False,'replay_exclusion_verified':False,
            'engine_result_score_used':False,
            'limitations':'Native MatchState score at the bound cursor, including equal-time incidents and side reversal. '
                'No final/provisional fixture score, scorer attribution or rounded-minute half inference. '
                'First-half score requires a caller-verified same-source boundary. '
                'Caller must recheck consumed bytes and process/save epoch before publishing.'}


NATIVE_SPANS = (
    (0x73adf0,bytes.fromhex('80064af981c25db97a1b0194602a0079')),
    (0x781be0,bytes.fromhex('ff4301d1f65702a9f44f03a9fd7b04a9fd030191f40301aae8ff9f52e83f0079150040f9b3420291f30300f928008052e8230039e00313aad794f094a02e40f9e00b00f9e87b0091e17b0091020140b2e30314aa0400801229f70695e00313aace94f094e03f4079fd7b44a9f44f43a9f65742a9ff430191c0035fd6')),
    (0x493f8dc,bytes.fromhex('5f0000393f00003909a043a91f0109eb40090054a304f8370a0080d22b796af86c1940b99f01036b8c0800546c7d40398d1d0051bf090071e30200548d791e12bf050071010100546c754039eb0302aa9f05007180010054ec010035eb0301aa090000149f090071610100546c754039eb0302aa8c000034eb0301aa9f050071a100005468014039080500116801003909a043a94a0500910b0109cb5f0d8bebe3fbff54250000148404f8370a0080d22b796af86c71c0399f01046bec0300546c7d40398d1d0051bf090071e30200548d791e12bf050071010100546c754039eb0301aaac010034eb0302aa9f050071400100540d0000149f090071610100546c754039eb0301aa9f05007160000054cc000035eb0302aa68014039080500116801003909a043a94a0500910b0109cb5f0d8bebe3fbff54c0035fd6')),
)
