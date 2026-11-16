"""Private passive native playback capture. No native calls or UI access.

Caller owns a checked ReadSet/process epoch and must verify it after capture.
This reads the playback cursor; it does not prove rendered pixels, replay exclusion,
or the time domain of any event record.
"""
import struct

NATIVE_SPANS = (
    (0x229dc, bytes.fromhex('f3b702f0685e47f9080100b42000805297a20c95605e47f9c2100e950000805293a20c957f5e07f9e8b702f0005947f9')),  # official primary interface singleton
    (0x733e84, bytes.fromhex('c86d02b008210391080401f8')),  # primary owner vtable
    (0x22554, bytes.fromhex('080040f9096540f9e8030091e10313aa20013fd6')),  # official playback handle lookup virtual C8
    (0x73483c, bytes.fromhex('e10200b4132c40f9930000b4690e40f93f0101ebc0000054133040f9130200b4690e40f93f0101eba1010054f40308aa1f0100f9')),  # lookup local handle vs playback18
    (0x737c24, bytes.fromhex('a86d02b00801129108410091080000f9')),  # playback owner vtable
    (0x73d9a4, bytes.fromhex('686d02f008411291080000f9130800f9')),  # shim same type and backing10
    (0x1f2dc, bytes.fromhex('680240f9082140f9e00313aa00013fd6')),  # official current time getter virtual40
    (0x73d9f0, bytes.fromhex('000840f94aefff17')),  # getter loads backing10
    (0x739714, bytes.fromhex('00c45db9c0035fd600c05db9c0035fd6')),  # max1DC4 current1DC0 getters
    (0x73544c, bytes.fromhex('e00313aaf40308aa9a100094800a00f968ce45b9880200b960be49fd804200fc688253b9880e00b9')),  # official uniqueIDs producer
    (0x7396bc, bytes.fromhex('00044af965200114')),  # matchUniqueId frame provider route
    (0x781854, bytes.fromhex('081440f9001140f9c0035fd6')),  # matchUniqueId source MATCH20
    (0x73adc4, bytes.fromhex('69020039680600b9e832399108fddf086800003688c65db90200001408008052680a00b980de5dbd')),  # official time and catchingup field producer
    (0x7392d4, bytes.fromhex('217ca10a20f8031e00d81dbd00dc1dbd01c01db9')),  # seek raw and float quarter-unit conversion
    (0x73ad8c, bytes.fromhex('88c25db900f9021e81de5dbd0020211e')),  # official TimeSlice to Time comparison
)


def _u64(data):
    return struct.unpack('<Q', data)[0]


def _pointer(value):
    return 4096 <= value < 1 << 48 and value % 4 == 0


def capture(read, base: int, *, client: int | None = None) -> dict:
    """Read official current/max native time slices; optionally bind one client.

    `client` is the exact resident GAME_VIEWABLE_MATCH_CLIENT selected by the
    independently checked manager/fixture lane. Never choose a client by clock.
    Returned private pointers are for owner-lane reconciliation only.
    """
    for at, expected in NATIVE_SPANS:
        if read(base + at, len(expected)) != expected:
            raise ValueError('Native playback source guard mismatch.')
    q = lambda at: _u64(read(at, 8))
    interface = q(base + 0x5721EB0)
    result = {'state': 'absent', 'source': 'official_native_match_playback_interface',
              'interface_address': interface, 'matches': [],
              'event_time_domain_verified': False,
              'replay_exclusion_verified': False,
              'rendered_presentation_verified': False,
              'no_hindsight_event_cutoff': None}
    if not interface:
        return result
    if not _pointer(interface) or q(interface) != base + 0x54EC0C8:
        raise ValueError('Unexpected primary playback owner type.')
    client_handle = engine = None
    if client is not None:
        if not _pointer(client) or q(client) != base + 0x55FAC38:
            raise ValueError('Unexpected viewable client type.')
        owner = q(client + 0xF8)
        if not _pointer(owner):
            raise ValueError('Missing viewable engine owner.')
        engine = q(owner + 0x18)
        if not _pointer(engine) or q(engine) != base + 0x55FA258:
            raise ValueError('Unexpected active engine type.')
        client_handle = q(client + 0x138)
        if not client_handle or q(engine + 0x20) != client_handle:
            raise ValueError('Client and engine match identities disagree.')
    seen = set()
    for field in (0x58, 0x60):
        playback = q(interface + field)
        if not playback:
            continue
        if playback in seen:
            raise ValueError('Duplicate playback owner slots.')
        seen.add(playback)
        if (not _pointer(playback) or q(playback) != base + 0x54EC490
                or q(playback + 0x10) != playback):
            raise ValueError('Unexpected playback owner type or backing self pointer.')
        provider = q(playback + 0x1408)
        if not _pointer(provider):
            raise ValueError('Missing playback frame provider.')
        source_match = q(provider + 0x28)
        if not _pointer(source_match) or q(source_match) != base + 0x55FA258:
            raise ValueError('Unexpected playback source GAME_MATCH type.')
        unique_id = q(source_match + 0x20)
        current, buffered_max = struct.unpack('<II', read(playback + 0x1DC0, 8))
        if current > buffered_max:
            raise ValueError('Playback cursor exceeds buffered maximum.')
        catchup_flag = read(playback + 0x1E4C, 1)[0]
        time = struct.unpack('<f', read(playback + 0x1DDC, 4))[0]
        result['matches'].append({
            'owner_field': field, 'playback_address': playback,
            'frame_provider_address': provider, 'source_match_address': source_match,
            'local_playback_handle': q(playback + 0x18),
            'official_match_unique_id': unique_id,
            'client_identity_matches': client_handle is not None and unique_id == client_handle,
            'current_time_slice': current, 'buffered_max_time_slice': buffered_max,
            'time_slice_domain': 'native_playback_time_slice',
            'official_match_state_time_native_float': time,
            'official_catching_up_to_time_slice': buffered_max if catchup_flag & 1 else 0,
            'native_catching_up_flag': catchup_flag,
            'team_unique_id': struct.unpack('<I', read(playback + 0x5CC, 4))[0],
            'parent_comp_unique_id': struct.unpack('<I', read(playback + 0x1378, 4))[0],
            'sub_comp_unique_id': struct.unpack('<I', read(playback + 0x137C, 4))[0],
            'nation_unique_id': struct.unpack('<I', read(playback + 0x1380, 4))[0],
        })
    if not result['matches']:
        result['state'] = 'no_playback_match'
    elif client is None:
        result['state'] = 'present_client_unbound'
    else:
        matches = [m for m in result['matches'] if m['client_identity_matches']]
        if len(matches) == 1:
            result['state'] = 'bound_playback_cursor'
            result['bound_playback'] = matches[0]
        elif len(matches) > 1:
            raise ValueError('Ambiguous playback owners match one client.')
        else:
            result['state'] = 'client_identity_not_retained'
    return result
