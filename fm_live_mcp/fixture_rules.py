"""Checked declared substitution limits and effective stored fixture draw rules."""
import hashlib
import struct
from datetime import datetime, timezone

from . import fixtures, players

NATIVE_GUARDS = (
    (0x22c0820, 200, 'c7b002da63c4f59a32e453becfb43aa0acac4ed099ce9aeab2c6efb0aba8fc64'),
    (0x22c1e90, 240, '8d790f109aa23fa397b7fc2c9481053477836f46ae44876dc9241c27a7f919b4'),
    (0x22ced98, 60, '9c2f54768d0785327336b4628f575454c23e86a0be877cff4f0d030e3f7c25f1'),
    (0x3cfab7c, 8, 'fe47d7a16181f369cbe73d0e546796e691abdb56b6757a3ab277e21315425461'),
    (0x48f9cfc, 168, '7c88dbfee56401e704c6cd0d2462a4f49d381052d53294b22f59ce123b1dfea6'),
    (0x48f9da4, 152, '0d7441db5ca4f13eaa0b21b8c9fa9e5cfcdd24dad7e44825e9c12ad379902821'),
    (0x48f9e84, 88, 'c1e07d41484ce3e127f154b3efb94e3daf2ed3b64069ff65397b9fbf6c9db2a2'),
    (0x540377e, 91, '53e908eaac5ea58ccc662d5c546f4e64eabb09e5518a95fca5496e4ccc52a0ad'),
    (0x54037d9, 91, 'c1addff088512f74dc48c38f0c778e928005902c0408dd8425e531bd093fa4cf'),
    (0x540390b, 93, '6eb122ddaac5b2f3c4bb1ec58615ca6bb334e954169dff9e659bf8dd3ca5b3a4'),
    (0x208438, 32, '44ca8f29aa5f28e97e907ec184514a0c45c4f398e4d3df13ebe0c140443ec62f'),
    (0x20a1d8, 16, '366d5e7efd2c2183179bd5daad006093639890a988cf4e5d9b39bd033bc6acdf'),
    (0x208704, 32, 'b74ac58838cf26030522420a1ed93df7a55d4f9707df4450647244f6a8ece341'),
    (0x202268, 48, '61f96aedb2c69f74fe89081174d02ede3ff8ce191cc45a180a2860af3f3d86ee'),
    (0x202b44, 128, 'dbda04ba9bfcd166c28b85d2ba7acc11f2ddecf6947114211d2b64d29cc8e126'),
    (0x202d18, 672, '5cc3970c63aec600526d6cfd69611fb19e50202cea0370c25a0ae891065e807b'),
    (0x202fcc, 164, 'b5536955676a42037b1d8f727feb40b5785eed14b6d15eadca49846e30f1124c'),
)

NAMED = bytes.fromhex('020607060210100e000204060606060e1d040c12020218060408040e141002060200040000000000000a06040200080400040002020600040200040a0a00020408080a000a08080e0e0c0c0c0202060802000c000c040a04020404')
USED = bytes.fromhex('0101010101010101010201010101010100000406000801000a0108010c080a00000a0102111315171901000101010a02000008000100080a00000000000000000015000000000000000000000101000008020a0a0a021502021313')
STOPPAGES = bytes.fromhex('ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff03ff03ff030303030303ffffff03ff03ff03ff03ff0303030303ff030303ff03ff0303ff03ff')
NAMED_RESULTS = {0:12,2:7,4:9,6:5,7:3,8:11,10:10,12:15,14:6,16:4,18:0,29:8}
USED_RESULTS = {0:5,1:3,2:7,4:15,6:0,8:4,10:6,17:8,19:9,21:10,23:11,25:12}

SCOPE = ('Declared limits from this resident fixture, not a player eligibility or team-sheet '
         'confirmation check. Extra-time substitute additions and additional stage restrictions '
         'remain unknown. Draw rules describe the effective stored fixture fields and audited '
         'native rule-text branches. Unmapped combinations remain explicit. No game functions, '
         'refreshes, archive loads or match simulation are executed. Consumed bytes are rechecked; '
         'these observations are non-atomic and may change before kickoff.')


def verify_native(read, base):
    for rva, length, expected in NATIVE_GUARDS:
        if hashlib.sha256(read(base + rva, length)).hexdigest() != expected:
            raise ValueError(f'Fixture-rule native code changed at RVA {rva:#x}')


def substitutions(code, away, ceiling):
    """Mirror the native signed-byte helpers and fixture ceiling, without calling them."""
    if type(code) is not int or not -128 <= code <= 127:
        raise ValueError('Invalid native substitution code')
    if type(away) is not bool or type(ceiling) is not int or not 0 <= ceiling <= 255:
        raise ValueError('Invalid substitution context')
    if 0 <= code <= 90:
        branch = NAMED[code]
        named = ((10 if not away else 12) if branch == 20 else
                 (7 if not away else 5) if branch == 24 else NAMED_RESULTS[branch])
        branch = USED[code]
        used = (10 if not away else 12) if branch == 12 else USED_RESULTS[branch]
        state = 'native_declared_fixture_limits'
    else:
        named = used = 5
        state = 'native_fallback_for_out_of_range_code'
    raw = STOPPAGES[code + 1] if -1 <= code <= 91 else 255
    stoppages = raw if raw < 128 else raw - 256
    return {'state': state, 'native_rule_code': code,
            'named_substitute_cap': min(named, ceiling),
            'used_substitute_cap': min(used, ceiling),
            'substitution_stoppages': None if stoppages < 0 else stoppages,
            'stoppages_state': 'unavailable_native_sentinel' if stoppages < 0 else 'stored_native_limit',
            'fixture_ceiling': ceiling, 'away_context': away,
            'stage_adjusted_confirmation_cap': None,
            'extra_time_substitute_addition': None,
            'extra_time_substitute_addition_state': 'not_established',
            'player_eligibility_evaluated': False}


def draw_resolution(word, special):
    if type(word) is not int or not 0 <= word <= 65535:
        raise ValueError('Invalid native match-rule word')
    if type(special) is not int or not 0 <= special <= 255:
        raise ValueError('Invalid native special-rule byte')
    extra, penalties, replay = bool(word & 1), bool(word & 2), bool(special & 4)
    # The audited simple patterns preserve bit9 without assigning it a meaning.
    # Other native decisions (seeding, US shootouts, away-goal variants, etc.)
    # must not be silently reduced to the ordinary penalty/replay pattern.
    unmapped_word, unmapped_special = word & ~0x203, special & ~4
    supported = not (unmapped_word or unmapped_special or penalties and replay)
    after90 = after_extra = key = text = None
    if supported:
        if extra:
            after90 = 'extra_time'
            after_extra = 'penalty_shootout' if penalties else 'replay' if replay else 'not_established'
            if penalties:
                key, text = 230308, 'Penalty shootout if scores are still level'
        elif penalties:
            after90 = 'penalty_shootout'
            key, text = 230309, 'Penalty shootout if scores are level after ninety minutes'
        elif replay:
            after90 = 'replay'
            key, text = 230313, 'Match replayed if scores are level after ninety minutes'
        else:
            after90 = 'no_deciding_flag'
    return {'state': 'decoded_supported_stored_pattern' if supported else 'unavailable_unmapped_rule_pattern',
            'raw_FxMR_u16': word, 'raw_FxSR_u8': special,
            'extra_time_flag': extra, 'penalty_shootout_flag': penalties, 'replay_flag': replay,
            'after_90_if_level': after90, 'after_extra_time_if_still_level': after_extra,
            'native_English_resource_key': key, 'native_English_rule': text,
            'unmapped_match_rule_bits': unmapped_word, 'unmapped_special_rule_bits': unmapped_special,
            'bit9_semantics': 'not_decoded'}


def read_rules(read, base, address):
    verify_native(read, base)
    raw = read(address, 0x58)
    table = players.u64(raw)
    if table not in (base + fixtures.TYPES['fixture'][0], base + fixtures.TYPES['result'][0]):
        raise ValueError('Fixture rules require a checked fixture or result type')
    if players.u64(read(table + 0xB0, 8)) != base + 0x3CFAB7C:
        raise ValueError('Fixture substitution ceiling getter changed')
    code = struct.unpack_from('<b', raw, 0x3E)[0]
    home, away = players.u64(raw, 8), players.u64(raw, 16)
    limits = []
    for side, team in (('home', home), ('away', away)):
        item = dict(side=side, **substitutions(code, home != team, 15))
        item['team_context_state'] = ('missing_team' if not team else
                                      'same_team_on_both_sides' if home == away else 'stored_side_team')
        if not team:
            item.update(state='unavailable_team_context', away_context=None,
                        named_substitute_cap=None, used_substitute_cap=None)
        limits.append(item)
    return {'substitutions': limits,
            'draw_resolution': draw_resolution(int.from_bytes(raw[0x32:0x34], 'little'), raw[0x3C]),
            'source': 'resident_effective_FIXTURE_32_3C_3E_with_native_helpers',
            'stage_confirmation': 'not_evaluated', 'player_eligibility': 'not_evaluated',
            'match_simulation_executed': False}


def collect(bridge, session_id, fixture_ref):
    """Validate one existing reference and publish only after the complete read succeeds."""
    process = bridge._current(session_id)
    saved = bridge.fixture_refs.get(fixture_ref) if isinstance(fixture_ref, str) else None
    if saved is None:
        raise ValueError('Unknown or expired fixture reference. Call fm_find_fixtures again.')
    tables = bridge._player_layout(process)
    snapshot, save, _ = bridge._world_state(process, tables)
    base = tables[0] - players.RVA[0]
    if saved['tables'] != tables:
        raise ValueError('Fixture runtime layout changed')
    _, years, identity = fixtures.catalog(snapshot, base)
    if saved['catalog_identity'] != identity:
        raise ValueError('Resident fixture inventory changed')
    binding = years[saved['year']]
    entries, route = fixtures.bucket(snapshot, binding, saved['day'], saved['group'])
    if (route != saved['route'] or saved['slot'] >= len(entries)
            or entries[saved['slot']] != saved['address']):
        raise ValueError('Fixture bucket membership changed')
    cache = {}
    decoded = fixtures.record(snapshot, base, saved['address'], saved['year'], saved['day'], cache)
    if decoded['identity'] != saved['identity']:
        raise ValueError('Fixture identity changed')
    row, _, _ = fixtures.detail(snapshot, base, saved['address'],
        saved['year'], saved['day'], decoded, cache, False)
    rules = read_rules(snapshot, base, saved['address'])
    snapshot.verify()
    bridge._current(session_id)
    # Return checked fixture values without minting additional references.
    row['fixture_ref'] = fixture_ref
    for item, team in zip(rules['substitutions'], (row['home_team'], row['away_team'])):
        item['team'] = team
    return {'session_id': session_id, 'observed_at': datetime.now(timezone.utc).isoformat(),
            'save': bridge._public_save(save), 'fixture': row, 'rules': rules,
            'evidence': 'rechecked_fixture_membership_effective_rules_and_native_count_helpers',
            'limitations': SCOPE}

