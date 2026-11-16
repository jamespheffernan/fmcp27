"""Resident current-player statistics, without native refresh or archive merging."""
import struct

from . import player_statistics, players, teams, world

GAME_PLAYER_ROOT = 0x56D2D08
GAME_PLAYER_TABLE = 0x55DEF88
MAX_ADDITIONAL_TEAMS = 128
CATEGORY_LABELS = ('Non Competitive', 'League', 'Cup', 'Continental', 'International', 'Overall (Club)')
LIMITATIONS = (
    'Resident stored statistics without refresh. Six native categories remain separate; '
    'category totals overlap and must not be summed together. No archive or starting-history merge. '
    'Teams are stored identities with owner names, without display-team normalization. '
    'Club runtime season year is separate from the display season and calendar-year style. '
    'Missing resident objects or categories remain unavailable. Reads are non-atomic.')
NATIVE_SPANS = {
    0x1F89560: '280040f908815ef82800088b090940b93f050031c0020054080d40b91f0500314008407a40020054f44fbea9fd7b01a9fd430091288040f9',
    0x1F895F8: '208040f9',
    0xF78E28: 'd40000b4880240f908815ef88802088b080940b9686200b9',
    0xF21930: 'd70240f9', 0xF21960: 'd70640f9', 0xF21990: 'd70a40f9',
    0xF219C8: 'd70e40f9', 0xF219F8: 'd71240f9', 0xF21A28: 'd61640f9',
    0x17BFB5C: '08e8423968000034000080d2c0035fd6e30301aae10300aaa8f801d000e943f9220080528b4fa914',
    0x42139D4: '336c40f9531400b4289c4b381f01007108228052092380522811889a756a68f8750500b4f40302aaa8ba40f9a9e64239220178b2f60300aae00308aaf70301aa21008052f80303aab8894697e30318aae10317aae80300aae00316aa880300b4a9e642393f010071090780520a0880524911899a086969f8a80200b4b4110034',
    0x13B60FC: 'fd7bbfa9fd030091e81802b0088153391f05007101070054e80300aa009440f9800000b4a2004037fd7bc1a8c0035fd661010035300000145f000072090780520a0880524911899a096869f83f0100f1e003809aa9feffb581fe0736',
    0xF88C88: '3f0900712c040054290800343f050071c00e00543f09007161180054',
    0xF88D10: '3f0d0071800700543f110071200e00543f15007141140054e823009121f98d52a100a072e14ad194',
    0xF88D94: '09e796526900a072e823009121393f11c54ad194',
    0xF88E70: '09e796526900a072e8230091210100328e4ad194',
    0xF88CA4: 'e823009101e796526100a072024bd194',
    0xF88E04: 'e823009141338f526100a072aa4ad194',
    0xF88EE0: '49338f526900a072e823009121490111724ad194',
    0x3DE0F8: 'b5060091f7820091bf1a00f1c0430054e0232391a4470b94a01e0013e1232391d2aa2e94',
    0xF21630: '08684479',
    0x4213A54: '090949393f01007108119f9a2311003409020036',
    0xF20DD8: 'c80e40f9e80900b4',
    0xF20E50: 'e3031aaa628440f8e01b40f9e10315aae40317aa7c010094',
    0xF20D50: '810340f9429740f9c3820091e0031aaa04008012bc010094',
}


def _optional_pointer(read, address):
    value = players.u64(read(address, 8))
    if value and (value < 4096 or value % 8):
        raise ValueError('Invalid current statistics pointer')
    return value


def verify_native(read, base):
    service = world.pointer(read, base + GAME_PLAYER_ROOT)
    if world.pointer(read, service) != base + GAME_PLAYER_TABLE:
        raise ValueError('Current statistics service type changed')
    displacement, info = struct.unpack('<qQ', read(base + GAME_PLAYER_TABLE - 16, 16))
    if displacement != 0:
        raise ValueError('Current statistics service displacement changed')
    name = players.u64(read(info + 8, 8))
    expected_name = b'18GAME_ACTUAL_PLAYER\0'
    if read(name, len(expected_name)) != expected_name:
        raise ValueError('Current statistics service RTTI changed')
    if players.u64(read(base + GAME_PLAYER_TABLE + 0x208, 8)) != base + 0x1F89560:
        raise ValueError('Current statistics getter changed')
    for rva, hex_bytes in NATIVE_SPANS.items():
        expected = bytes.fromhex(hex_bytes)
        if read(base + rva, len(expected)) != expected:
            raise ValueError('Current statistics native layout changed')
    player_statistics.verify_native(read, base)


def _categories(read, address):
    rows = []
    for code in range(6):
        pointer = _optional_pointer(read, address + code*8)
        statistics = None
        if pointer:
            raw = read(pointer, 25)
            indirect_pointer = players.u64(raw)
            if indirect_pointer and (indirect_pointer < 4096 or indirect_pointer % 8):
                raise ValueError('Invalid indirect current statistics pointer')
            indirect = read(indirect_pointer, 136) if indirect_pointer else None
            statistics = player_statistics.decode_compact(raw, indirect)
        rows.append({'native_code': code, 'name': CATEGORY_LABELS[code], 'name_state': 'native_english_label',
                     'availability': 'resident' if pointer else 'unavailable_null_category',
                     'statistics': statistics})
    return rows


def _team(read, base, address, cache):
    if not address:
        return None, None
    if address not in cache:
        index = int.from_bytes(read(address + 8, 4), 'little')
        row, binding = teams.by_index(read, base, index)
        if binding['address'] != address:
            raise ValueError('Current statistics team membership changed')
        cache[address] = (row, binding)
    return cache[address]


def _season(read, base, binding):
    def unavailable(reason):
        return {'value': None, 'state': 'unavailable', 'reason': reason}
    if binding is None:
        return unavailable('no_current_team')
    if binding['owner_kind'] != 'club':
        return unavailable('unsupported_team_owner')
    club = binding['owner_address']
    if players.u64(read(base + world.TYPES['club'][0] + 0x168, 8)) != base + 0x17BFB5C:
        raise ValueError('Club runtime season getter changed')
    if read(club + 0xBA, 1)[0] != 0:
        return unavailable('unsupported_club_runtime_branch')
    if read(base + 0x56D34E0, 1)[0] != 1:
        return unavailable('inactive_runtime_lookup')
    gender = read(club + 0xB9, 1)[0]
    if gender not in (0, 1):
        return unavailable('unsupported_club_gender_branch')
    nation = _optional_pointer(read, club + 0xD8)
    if not nation:
        return unavailable('missing_nation_requires_runtime_fallback')
    world.typed(read, base, nation, 'nation')
    context = _optional_pointer(read, nation + (0x118 if gender else 0x110))
    if not context:
        return unavailable('missing_context_requires_runtime_fallback')
    context_gender = read(context + 0xB9, 1)[0]
    if context_gender not in (0, 1):
        return unavailable('unsupported_context_gender_branch')
    owner = _optional_pointer(read, context + 0x170)
    if not owner:
        return unavailable('missing_runtime_owner')
    world.typed(read, base, owner, 'nation')
    runtime = _optional_pointer(read, owner + 0x128)
    if not runtime:
        return unavailable('missing_runtime_requires_fallback')
    season = _optional_pointer(read, runtime + (0x40 if context_gender else 0x38))
    if not season:
        return unavailable('missing_season_requires_runtime_fallback')
    if not read(season + 0x242, 1)[0] & 1:
        return unavailable('native_season_unavailable')
    year = int.from_bytes(read(season + 0x234, 2), 'little')
    if not 1850 <= year <= 2200:
        raise ValueError('Invalid club runtime season year')
    return {'value': year, 'state': 'decoded', 'reason': 'stored_normal_club_runtime'}


def decode(read, base: int, address: int, tables: tuple) -> dict:
    if address < 4096 or address % 8:
        raise ValueError('Invalid actual player address')
    expected = tuple(base + rva for rva in players.RVA)
    if tuple(tables) != expected or players.u64(read(address, 8)) != expected[0]:
        raise ValueError('Current statistics support actual players only')
    if (players.u64(read(address + 0x140, 8)) != expected[1]
            or players.u64(read(address + 0x388, 8)) != expected[2]
            or struct.unpack('<q', read(expected[0] - 0x18, 8))[0] != 0x388):
        raise ValueError('Actual player statistics layout changed')
    identity = struct.unpack('<i', read(address + 0x390, 4))[0]
    if identity < 0:
        raise ValueError('Invalid actual player identity')
    verify_native(read, base)
    cache = {}
    current_address = _optional_pointer(read, address + 0x128)
    current, binding = _team(read, base, current_address, cache)
    resident = _optional_pointer(read, address + 0x100)
    result = {'state': 'unavailable_not_resident' if not resident else 'stored_without_refresh',
              'current_team': current, 'current_team_state': 'decoded' if current else 'unassigned',
              'club_runtime_season_year': _season(read, base, binding),
              'categories': [], 'additional_team_rows': [],
              'additional_team_rows_state': 'unavailable_not_resident',
              'source_coverage': 'resident_current_stats_only_no_archives_or_starting_history',
              'limitations': LIMITATIONS}
    if not resident:
        result['categories'] = [{'native_code': i, 'name': CATEGORY_LABELS[i], 'name_state': 'native_english_label',
                                 'availability': 'unavailable_not_resident',
                                 'statistics': None} for i in range(6)]
        return result
    if struct.unpack('<i', read(resident + 0x60, 4))[0] != identity:
        raise ValueError('Current statistics owner identity disagrees')
    result['categories'] = _categories(read, resident + 0x20)
    header = _optional_pointer(read, resident + 0x18)
    entries = world.vector(read, header, MAX_ADDITIONAL_TEAMS) if header else ()
    result['additional_team_rows_state'] = 'resident_vector' if header else 'null_vector'
    for index, entry in enumerate(entries):
        team_address = _optional_pointer(read, entry)
        team, _ = _team(read, base, team_address, cache)
        result['additional_team_rows'].append({
            'row_index': index, 'team': team,
            'team_state': 'decoded' if team else 'unassigned',
            'categories': _categories(read, entry + 8)})
    return result
