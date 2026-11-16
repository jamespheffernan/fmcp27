"""Passive official playback event storage, before participation interpretation.

Named MATCH_EVENT fields preserve raw IDs and simulation slices. Neither their
six actor-role meanings nor complete playing intervals are inferred here.
"""
import struct
from . import frame_attack_direction as direction

MAX_EVENTS = 8192
STRIDE = 44
NATIVE_SPANS = (
    (0x2059C, bytes.fromhex("680240f9087140f9e1230091e00313aa00013fd6")),
    (0x73DA90, bytes.fromhex("000840f9a5f8ff17")),
    (0x73BD28, bytes.fromhex("088382520000088bc30d0014")),
    (0x73F1D8, bytes.fromhex("092041a9080109cb08fd4293697491d2c945b7f2095dd4f269d1e5f2007d099bc0035fd6")),
    (0x73F43C, bytes.fromhex("092041a9080109cb09fd4293687491d2c845b7f2085dd4f268d1e5f22b7d089b090040f9ea030baa690109eba00200540a0080d28b0580520c0040f90d0840f98c350b9b8c010a8b2d0040f9ad010a8b800540ad82c1c13ca2c1813ca00500ad4ab10091290500f181feff540a0040b90b2441a929010bcb29fd42932b7d089b084063390b0000f91f402339e9030a2a208108aac0035fd6")),
    (0xE204, bytes.fromhex("c18102d021a4329160420091a20180521d5d0094010080d28a802b95c18102b021600e9122008052175d00948100805284802b95c18102b021400e9122008052115d0094c18102d021dc329160420091a20180520c5d00948100805279802b95c18102b021600e9122008052065d00948100805273802b95c18102b021400e9122008052005d0094c18102d02114339160420091a2018052fb5c00940101805268802b95c18102b021600e9122008052f55c00948100805262802b95c18102b021400e9122008052ef5c0094c18102d0214c339160420091a2018052ea5c00948101805257802b95c18102b021600e9122008052e45c00948100805251802b95c18102b021400e9122008052de5c0094c18102d02184339160420091a2018052d95c00940102805246802b95c18102b021600e9122008052d35c00948100805240802b95c18102b021400e9122008052cd5c0094c18102d021bc339160420091a2018052c85c00948102805235802b95c18102b021600e9122008052c25c0094810080522f802b95c18102b021400e9122008052bc5c0094c18102d021f4339160420091e2018052b75c00940103805224802b95c18102b021600e9122008052b15c0094210080521e802b95c18102b021400e9122008052ab5c0094c18102d0213434916042009162028052a65c00944103805213802b95c18102b021600e9122008052a05c0094410080520d802b95c18102b021400e91220080529a5c0094c18102b0211c199160420091a2018052955c00948103805202802b95c18102b021600e91220080528f5c009481008052fc7f2b95c18102b021400e9122008052895c0094c18102d02184349160420091c2028052845c009401048052f17f2b95c18102b021600e91220080527e5c009481008052eb7f2b95c18102b021400e9122008052785c0094c18102b021f418916042009122018052735c009481048052e07f2b95c18102b021600e91220080526d5c009421008052da7f2b95c18102b021400e9122008052675c0094c18102d021e034916042009102038052625c0094a1048052cf7f2b95c18102b021600e91220080525c5c009421008052c97f2b95c18102b021400e9122008052565c0094c18102d02144359160420091c2028052515c0094c1048052be7f2b95c18102b021600e91220080524b5c009421008052b87f2b95c18102b021400e9122008052455c0094c18102d021a035916042009122018052405c009401058052ad7f2b95c18102b021600e91220080523a5c009481008052")),
    (0x5048CA9, b'o(PlayerID1)=\x00'),
    (0x5048CB7, b'o(PlayerID2)=\x00'),
    (0x5048CC5, b'o(PlayerID3)=\x00'),
    (0x5048CD3, b'o(PlayerID4)=\x00'),
    (0x5048CE1, b'o(PlayerID5)=\x00'),
    (0x5048CEF, b'o(PlayerID6)=\x00'),
    (0x5048CFD, b'o(PlayerTeams)=\x00'),
    (0x5048D0D, b'o(CommentaryEvent)=\x00'),
    (0x5047647, b'o(TimeSlice)=\x00'),
    (0x5048D21, b'o(DurationTimeSlices)=\x00'),
    (0x504763D, b'o(Flags)=\x00'),
    (0x5048D38, b'o(CommentaryImportance)=\x00'),
    (0x5048D51, b'o(IncidentImportance)=\x00'),
    (0x5048D68, b'o(Data1)=\x00'),
)


def verify_native(read, base):
    for at, expected in NATIVE_SPANS:
        if direction._read(read,base+at,len(expected)) != expected:
            raise ValueError('Native official playback event source changed')
    if direction._q(read,base+0x54EC490+0xE0) != base+0x73DA90:
        raise ValueError('Official playback event virtual route changed')


def capture(read, base, bound):
    verify_native(read,base)
    playback=bound['playback_address']
    for address, expected in ((playback,base+0x54EC490),(playback+0x10,playback),
        (playback+0x18,bound['local_playback_handle']),
        (playback+0x1408,bound['frame_provider_address']),
        (bound['frame_provider_address']+0x28,bound['source_match_address']),
        (bound['source_match_address']+0x20,bound['official_match_unique_id'])):
        if direction._q(read,address) != expected:
            raise ValueError('Official playback event owner changed')
    state=direction._read(read,playback+0x1418,40)
    consumed,released,start,end,capacity=struct.unpack('<5Q',state)
    common={'source':'official_native_playback_match_event_storage',
        'official_match_unique_id':bound['official_match_unique_id'],
        'native_update_consumed_index':consumed,'native_auxiliary_release_index':released,
        'rows':None,'history_complete':None,'on_pitch_population_verified':False,
        '_source':(state,)}
    if (start,end,capacity)==(0,0,0):
        if consumed or released:raise ValueError('Inconsistent absent native event list')
        return common | {'state':'available_empty_native_storage','rows':[]}
    direction._pointer(start)
    if not start<=end<=capacity or (end-start)%STRIDE or (capacity-start)%STRIDE:
        raise ValueError('Unsupported native event vector bounds')
    count=(end-start)//STRIDE
    if count>MAX_EVENTS or (capacity-start)//STRIDE>MAX_EVENTS:
        return common | {'state':'unavailable_native_event_budget'}
    if not 0<=consumed<=count or not 0<=released<=count:
        raise ValueError('Native event processing index is outside captured list')
    raw=b''.join(direction._read(read,start+offset,min(8192,count*STRIDE-offset))
        for offset in range(0,count*STRIDE,8192))
    rows=[]
    for index in range(count):
        row=raw[index*STRIDE:(index+1)*STRIDE]
        rows.append({'native_event_index':index,'player_ids_raw':list(struct.unpack_from('<6I',row)),
            'player_teams_bits_raw':row[24],'commentary_event_raw':struct.unpack_from('<H',row,26)[0],
            'time_slice_raw':struct.unpack_from('<I',row,28)[0],
            'duration_time_slices_raw':struct.unpack_from('<I',row,32)[0],
            'flags_raw':row[36],'commentary_importance_raw':row[37],
            'incident_importance_raw':row[38],'data1_raw':struct.unpack_from('<I',row,40)[0]})
    return common | {'state':'available_native_event_rows','rows':rows,'_source':(state,raw)}


def verify_capture(read,base,captured,bound):
    current=capture(read,base,bound)
    if current != captured:
        raise ValueError('Consumed official playback event bytes changed')
    return captured | {'native_event_bytes_physically_reselected':True}


def project(verified):
    if verified.get('native_event_bytes_physically_reselected') is not True:
        raise ValueError('Final official event source verification required')
    return {k:v for k,v in verified.items() if not k.startswith('_')} | {
        'interpretation':'Native commentary facts only. Actor IDs are not assumed to be PERSON IDs. '
        'Substitution actor roles, initial participation, removal and re-entry coverage, '
        'history completeness and relation to an exact frame require separate proof.'}
