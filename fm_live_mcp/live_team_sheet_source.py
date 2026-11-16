"""Existing HUMAN tactic-edit selection; never creates or applies edit state.

Call within the bridge's save-bound ReadSet, then verify it before publishing.
The source is an owned retained edit session, not proof of foreground visibility,
fixture submission, match eligibility or a completed match lineup.

Where the bench ends (docs/current-formation-boundary.md). The game computes one number for a
TEAM and a fixture, 11 + min(named substitutes of the fixture's rule code for that side, the
fixture's ceiling), in three places: the session constructor (only when its match list holds a
match of this TEAM for the HUMAN), the session's evaluator (for the fixture its caller passes;
the screen property passes the fixture on the current date) and the selection screen's own
model (for the TEAM's next fixture). The first two store it at session+35B0/35B1, so those
bytes stay zero until a fixture is bound; the third numbers slots 11.. as substitutes for the
screen. The reader takes the stored end when the session has one, and otherwise the selection
screen's rule over the TEAM's cached next fixture, and says which.
"""
from datetime import date, timedelta
import struct

from . import (address_book, assessment_people, database, fixture_rules, fixtures, players,
               prepared_tactics_source, world)

EDIT_VTABLE = 0x55E63D8
EDIT_NAME = b'19TACTIC_EDIT_SESSION'
CONTEXT_LIMIT = 64
SLOT_COUNT = 26
STORED_END = 'native_first_11_and_stored_selected_end'
NEXT_FIXTURE_END = 'native_first_11_and_next_fixture_named_substitute_cap'
BENCH_KNOWN = (STORED_END, NEXT_FIXTURE_END)


def bench_known(sheet):
    """True when slots 11.. carry bench categories: from the session's stored end, or from the
    selection screen's rule for the TEAM's next fixture."""
    return sheet.get('source_state') == 'available' and sheet.get('role_boundary_state') in BENCH_KNOWN


def verify_native(read, base):
    for rva, expected in NATIVE_SPANS:
        if read(base + rva, len(expected)) != expected:
            raise ValueError(f'Editable team sheet native source changed at RVA {rva:#x}')


def _calendar(raw):
    low, year = struct.unpack('<HH', raw)
    day = low & 511
    if not 1850 <= year <= 2200 or not 1 <= day <= 366:
        return None
    result = date(year, 1, 1) + timedelta(days=day - 1)
    return result if result.year == year else None


def _no_next_fixture_bench(reason):
    return {'state': 'unavailable', 'reason': reason, 'bench_end': None, 'fixture': None}


@address_book.optional_section(
    'next_fixture_bench', lambda reasons: _no_next_fixture_bench('next_fixture_rule_not_mapped_on_this_build'))
def _next_fixture_bench(read, base, team_address):
    """The selection screen's substitute count for this TEAM, from the game's own inputs.

    The screen's model (2E4D258) takes the TEAM's next fixture from 17743B8(team, 365), which
    returns the pointer cached at [[team+A0]+B8] whenever one is cached, and stores
    min(48F9CFC(fixture+3E, team is not the home side), fixture vtable+B0()) as its substitute
    count; its slot labels (535DB8) name slot i a substitute while 11 <= i < 11 + count. Only
    the cached pointer is read: when the game has none it would search for one, and the
    reader does not."""
    for rva, expected in NEXT_FIXTURE_SPANS:
        if read(base + rva, len(expected)) != expected:
            return _no_next_fixture_bench('next_fixture_rule_native_source_changed')
    holder = _u64(read, team_address + 0xA0)
    if not holder:
        return _no_next_fixture_bench('team_fixture_cache_absent')
    if holder < 4096 or holder % 8:
        return _no_next_fixture_bench('team_fixture_cache_pointer_invalid')
    fixture = _u64(read, holder + 0xB8)
    if not fixture:
        return _no_next_fixture_bench('next_fixture_not_cached')
    if fixture < 4096 or fixture % 8:
        return _no_next_fixture_bench('cached_next_fixture_pointer_invalid')
    raw = read(fixture, 0x58)
    if players.u64(raw) != base + fixtures.TYPES['fixture'][0]:
        return _no_next_fixture_bench('cached_next_fixture_unsupported_type')
    try:
        fixtures.typed(read, base, fixture, 'fixture')
    except ValueError:
        return _no_next_fixture_bench('cached_next_fixture_unsupported_type')
    home, away = players.u64(raw, 8), players.u64(raw, 16)
    if (home == team_address) == (away == team_address):
        return _no_next_fixture_bench('team_not_exactly_one_side_of_cached_next_fixture')
    today, when = _calendar(read(base + world.CURRENT_DATE, 4)), _calendar(raw[0x4C:0x50])
    if today is None or when is None:
        return _no_next_fixture_bench('cached_next_fixture_date_unsupported')
    if when < today:
        return _no_next_fixture_bench('cached_next_fixture_before_current_date')
    side = 'home' if home == team_address else 'away'
    try:
        # Guards 48F9CFC, its byte table and the FIXTURE ceiling getter; a moved byte is caught
        # again by the caller's ReadSet verification.
        rules = fixture_rules.read_rules(read, base, fixture)
    except ValueError:
        return _no_next_fixture_bench('fixture_substitution_rule_unavailable')
    limits = next(row for row in rules['substitutions'] if row['side'] == side)
    cap = limits['named_substitute_cap']
    if limits['state'] != 'native_declared_fixture_limits' or type(cap) is not int or not 0 <= cap <= 15:
        return _no_next_fixture_bench('next_fixture_substitution_rule_unsupported')
    return {'state': 'available', 'reason': None, 'bench_end': 11 + cap,
            'fixture': {'date': when.isoformat(), 'days_from_current_date': (when - today).days,
                        'managed_side': side, 'native_rule_code': limits['native_rule_code'],
                        'named_substitute_cap': cap,
                        'used_substitute_cap': limits['used_substitute_cap'],
                        'fixture_ceiling': limits['fixture_ceiling'],
                        'source': 'team_cached_next_fixture_pointer'}}


def _u64(read, address):
    return struct.unpack('<Q', read(address, 8))[0]


def _kind(read, base, address):
    table = _u64(read, address)
    prepared_tactics_source._pointer(table, 'edit session vtable')
    method = _u64(read, table + 0x10)
    if not base <= method < base + 0x4F00000:
        raise ValueError('Edit context kind method is outside the pinned image')
    first, second = struct.unpack('<II', read(method, 8))
    # Interpret only the constant-return getter used by the pinned session kinds.
    # No native function is executed, and an unknown getter is not skipped.
    if first & 0xFFE0001F != 0x52800000 or second != 0xD65F03C0:
        return None
    return (first >> 5) & 0xFFFF


def _unavailable(team, reason):
    return {
        'team': team, 'source_state': 'unavailable', 'unavailable_reason': reason,
        'source': 'existing_human_tactic_edit_session',
        'slots': None, 'slot_count': None, 'selected_count': None,
        'starting_count': None, 'bench_count': None, 'empty_slot_count': None,
        'stored_nonnull_count': None,
        'stored_selected_end': None, 'role_boundary_state': 'source_unavailable',
        'bench_end': None, 'bench_boundary_source': None,
        'bench_boundary_unavailable_reason': 'source_unavailable',
        'session_fixture_extent_state': None, 'bench_fixture': None,
        'formation_boundary_state': 'source_unavailable',
        'duplicate_person_indices': None,
        'match_submission_state': 'not_established',
        'foreground_screen_state': 'not_observed',
    }


def _existing_session(read, base, human, team_pointer, team_index):
    matches = []
    for offset in (0x218, 0x200):
        contexts = prepared_tactics_source._vector(read, human + offset, CONTEXT_LIMIT)
        for address in contexts:
            if not address:
                continue
            kind = _kind(read, base, address)
            if kind is None:
                return None, 'unsupported_edit_context_kind_getter'
            if kind != 3:
                continue
            table = _u64(read, address)
            if table != base + EDIT_VTABLE:
                return None, 'unsupported_tactic_edit_session_type'
            prepared_tactics_source._typed(read, base, address, EDIT_VTABLE, EDIT_NAME)
            if (_u64(read, table + 0x10) != base + 0x22CED60
                    or _u64(read, table + 0x28) != base + 0x22CE460):
                raise ValueError('Tactic edit session kind or team matcher changed')
            owner = _u64(read, address + 8)
            if owner != human:
                raise ValueError('Tactic edit session HUMAN ownership disagrees')
            selected_team = _u64(read, address + 0x3590)
            if not selected_team:
                continue
            prepared_tactics_source._pointer(selected_team, 'edit session team')
            selected_index = struct.unpack('<I', read(selected_team + 8, 4))[0]
            if selected_index == team_index:
                if selected_team != team_pointer:
                    raise ValueError('Tactic edit session canonical team identity disagrees')
                matches.append(address)
    if not matches:
        return None, 'existing_tactic_edit_session_missing'
    if len(matches) != 1:
        return None, 'multiple_matching_tactic_edit_sessions'
    return matches[0], None


def _person(read, base, people, index):
    if not 0 <= index < people['count']:
        raise ValueError('Selected PERSON index is outside the canonical table')
    person = _u64(read, people['start'] + index * 8)
    primary, displacement, public, native, secondary = assessment_people._person(
        read, base, people, person)
    if public['native_identity']['database_index'] != index:
        raise ValueError('Selected PERSON index disagrees with its canonical identity')
    kind = public['record_kind']
    result = {
        'database_index': index, 'native_id': native, 'secondary_id': secondary,
        'record_kind': kind, 'name': None, 'display_name': None,
        'identity_state': 'same_snapshot_canonical_PERSON',
        'name_state': 'unavailable_without_generated_profile',
    }
    if kind in ('actual', 'player_staff'):
        tables = tuple(base + rva for rva in players.RVA)
        database.player_membership(read, base, people, index, primary)
        decoded, identity = players.decode(read, primary, tables)
        decoded_native = identity[1] if kind == 'player_staff' else identity[0]
        if decoded_native != native or identity[-1] != secondary:
            raise ValueError('Selected player identity changed during name decode')
        result.update(name=decoded['name'], display_name=decoded['display_name'],
                      name_state='stored_native_strings')
    elif kind != 'virtual':
        raise ValueError('Selected PERSON is not a supported player class')
    return result


def inspect(read, base, coach):
    """Return address-free source metadata and all ordered slots, preserving nulls."""
    verify_native(read, base)
    prepared_tactics_source.verify_native(read, base)
    team, human = prepared_tactics_source._team_and_human(read, base, coach)
    address, reason = _existing_session(
        read, base, human, coach['team_address'], team['database_index'])
    if reason:
        return _unavailable(team, reason)
    raw = read(address + 0x2200, SLOT_COUNT * 4)
    indices = struct.unpack('<26i', raw)
    if any(index < -1 for index in indices):
        raise ValueError('Unsupported negative selected PERSON index')
    # The native consumer separates slots0..10 from slots11..<35B1. Later
    # reserved slots are retained, never presented as selected substitutes.
    permitted_end, selected_end = struct.unpack('<bb', read(address + 0x35B0, 2))
    stored_known = 11 <= selected_end <= SLOT_COUNT
    next_fixture = None
    if stored_known:
        bench_end, extent_state = selected_end, 'stored_for_a_bound_fixture'
    elif permitted_end == 0 and selected_end == 0:
        # Constructor value: no fixture has been bound to this session (22BFB2C zeroes both
        # bytes; 22BFD40, 22C3ABC, 22C40A4 and 22C08E4 write them only with a fixture).
        extent_state = 'unset_no_fixture_bound'
        next_fixture = _next_fixture_bench(read, base, coach['team_address'])
        bench_end = next_fixture['bench_end']
    else:
        bench_end, extent_state = None, 'unsupported_stored_value'
    boundary_known = bench_end is not None
    assessment_people.verify_native(read, base)
    people = database.table(read, base, 'people')
    identities = {index: _person(read, base, people, index)
                  for index in dict.fromkeys(indices) if index >= 0}
    slots = []
    for index, person_index in enumerate(indices):
        # Native role lookup23928F4..2940 bounds formation slots0..10
        # independently of the fixture-specific selected-bench end at35B1.
        category = ('starting_position' if index < 11 else None
                    if not boundary_known else 'bench' if index < bench_end
                    else 'outside_selected_bench_boundary')
        slots.append({
            'slot_index': index, 'category': category,
            'bench_ordinal': index - 10 if category == 'bench' else None,
            'state': ('empty_slot' if person_index == -1 else 'selected_person'
                      if index < 11 or (boundary_known and index < bench_end) else 'stored_person_boundary_unresolved'
                      if not boundary_known else 'stored_outside_selected_extent'),
            'person': None if person_index == -1 else identities[person_index],
        })
    selected_indices = indices[:bench_end] if boundary_known else indices
    duplicates = sorted(index for index in set(selected_indices) if index >= 0
                        and selected_indices.count(index) > 1)
    return {
        'team': team, 'source_state': 'available', 'unavailable_reason': None,
        'source': 'existing_human_tactic_edit_session',
        'slots': slots, 'slot_count': SLOT_COUNT,
        'selected_count': sum(index >= 0 for index in selected_indices) if boundary_known else None,
        'stored_nonnull_count': sum(index >= 0 for index in indices),
        'starting_count': sum(index >= 0 for index in indices[:11]),
        'bench_count': sum(index >= 0 for index in indices[11:bench_end]) if boundary_known else None,
        'empty_slot_count': indices.count(-1), 'stored_selected_end': selected_end,
        'role_boundary_state': (STORED_END if stored_known else NEXT_FIXTURE_END if boundary_known
                                else 'stored_boundary_unmapped'),
        'bench_end': bench_end,
        'bench_boundary_source': ('session_stored_fixture_extent' if stored_known else
                                  'selection_screen_rule_for_cached_next_fixture' if boundary_known
                                  else None),
        'bench_boundary_unavailable_reason': (None if boundary_known else
                                              next_fixture['reason'] if next_fixture is not None
                                              else 'unsupported_stored_selected_end'),
        'session_fixture_extent_state': extent_state,
        'bench_fixture': None if next_fixture is None else next_fixture['fixture'],
        'formation_boundary_state': 'native_first_11',
        'duplicate_person_indices': duplicates,
        'match_submission_state': 'not_established',
        'foreground_screen_state': 'not_observed',
        'selection_is_roster_or_eligibility_list': False,
    }


# Pinned native ownership, mutable working payload, consumer bounds and apply
# direction. Bytes are embedded in the package; no research files are imported.
NATIVE_SPANS = (
    (0x2ECD278, bytes.fromhex(
        '360840b9091041f9080c41f93f0108eb20030054170080d2147977f8f40100b4880240f9080940f9e00314aa00013fd6'
        '1f0c007121010054880240f9081540f9e00314aae10316aa020080120300801200013fd6a00d0037f7060091691241f9'
        '680e41f9290108cbff0e89eb63fdff54b60a40b9690641f9680241f93f0108eb00030054170080d2147977f8f40100b4'
        '880240f9080940f9e00314aa00013fd61f0c007121010054880240f9081540f9e00314aae10316aa0200801203008012'
        '00013fd6200a0037f7060091690641f9680241f9290108cbff0e89eb63fdff54'
    )),
    (0x22BFA70, bytes.fromhex(
        '289901f008610f91080481a821008052ab769694e0e7076f60e608fd083a82526802088b7fea08f91f210039083c8252'
        '6002088b21008052'
    )),
    (0x22BFB04, bytes.fromhex(
        '7b0e4091130000f960c61af974ca1af900e4006f08b38652606aa83c'
    )),
    (0x22CED60, bytes.fromhex(
        '60008052c0035fd6'
    )),
    (0x22CE460, bytes.fromhex(
        '08c85af9080100b44900010a3f050031e0000054080940b91f01016be0179f1ac0035fd600008052c0035fd620008052'
        'c0035fd6'
    )),
    (0x22C0104, bytes.fromhex(
        '163c82526002168b21a300910a237f97084084527502088b61ca5af9e00315aa50592294'
    )),
    (0x22CE2AC, bytes.fromhex(
        '173c8252084084527802088b39a001903aa001b0086b76b80804f83729c346f9c90300b44a835339ea0000372aad46a9'
        '6b010acb1f0d8beb62000054480d088b08000014294540f9292940a94a0109eb400200541f0d8aeb02020054280d088b'
        '000140f9a00100b4080040f9087143f900013fd6200100b4089040f969ca5af91f0109eba0000054016b76b86002178b'
        '22008052013f9694d6120091dfa201f1a1fbff54'
    )),
    (0x22CE364, bytes.fromhex(
        '153c82521f0500714101005408aa865209ae865265ae75b96202158b6302088b6402098be00314aa1d3122942d000014'
        '210400b428a0019008bd46f9c80300b4084540f9092140a93f0108eb40030054e00301aaf40301aa38232294c00200b4'
        '098c40f8890200b4880a40b9f60300aa2a2140b95f01086beaa79f1ad6b2899a29596af869ffffb5df0200eb40010054'
        'c92240b91f01096beb000054c0a200916102158b4cea7e97c1a20091e00314aa6521229460ca5af9'
    )),
    (0x22C4300, bytes.fromhex(
        '1a0080d218008052084084527602088bf70316aa61ca5af9e00317aad2482294e00000b45f2b00f16801005488da4b39'
        '0805001188da0b39180000145f2f00f10304005488c796395f0308eb18a7981a1c00001488c796395f0308ebaa000054'
        '88de4b390805001188de0b390b00001488c396395f0308ebaa00005488e24b390805001188e20b390400001488e64b39'
        '0805001188e60b3988c396395f0308eb0a01005461ca5af9461f0013e20315aae30314aa04008052050080d2c6060094'
        '5a070091f71200915f6b00f141faff54'
    )),
    (0x22C85F0, bytes.fromhex(
        'a81e0013e8bb00b91f2d0071e8630a91f8b3889a'
    )),
    (0x446F240, bytes.fromhex(
        '3f640071681100542211f837'
    )),
    (0x446F450, bytes.fromhex(
        '69f841b93f01026b610000540900801269f801b909008012097828b802d821b83f680071e0279f1ac0035fd6'
    )),
    (0x22CA758, bytes.fromhex(
        '140080d2a8434039e86700b9084084520803088be84300f913108152f5bb03911b3c8252680222d1096975383f050071'
        'e1020054e9ab48a94a0109cb9f0e8aeb02010054297974f8690100b42a0140f94a815ef829010a8b220940b907000014'
        '017b73b802031b8be04340f9159286940700001402008012011d001303031b8be04340f9999286949406009173060091'
        '7f6a22f181fcff54'
    )),
    (0x22CA6BC, bytes.fromhex(
        'bf03163800cb5af90b3c8252020740f9fb0240f9fb8700f99b0000b46843009129008052080129b8f75705a9ffab0039'
        'faa70039ffa30039a88302d1e9bb0391ea23029101030b8be5230491e8db01a9e9f300a9ea0300f9e33b40f9e40315aa'
        'e60314aae70319aa88f4ff97'
    )),
    (0x2ECE2CC, bytes.fromhex(
        'e00317aae10318aae1fbff97f40300aa'
    )),
    (0x2ECE3EC, bytes.fromhex(
        'e00314aae10316aae30317aa04008052e50315aa070080527ff0cf97'
    )),
)

# Independently verified formation-position and substitute-number consumers.
NATIVE_SPANS += (
    (0x23928F4, bytes.fromhex('08048252a002088bc37083941f04003100184a7acc020054')),
    (0x2392938, bytes.fromhex('090980520820299b012141b902b140f9')),
    (0x535DB8, bytes.fromhex('082d00111f01156bad010054a92a0051c15802b021281791e8a30091201d0012f1cd0c95')),
    (0x4869600, bytes.fromhex('617899526100a072acc8ed97')),
    (0x486962C, bytes.fromhex('817899526100a072a1c8ed97')),
    (0x48696E0, bytes.fromhex('a17899526100a07274c8ed97')),
    (0x26818C, bytes.fromhex('0869e9381f2d0071ab710054')),
    (0x2681A4, bytes.fromhex('817899526100a072c3cd0595')),
    (0x2681B4, bytes.fromhex('e9c483520869e93808290051')),
)

# The bench end the game computes for a TEAM and a fixture, and where it keeps it.
# Selection screen model: its fixture is 17743B8(team, 365) (2E4D29C, kept at [sp+8], reloaded
# into x28 at 2E4D930); its substitute count at model+5194 is 15 from the constructor (2E4CFE8)
# and min(48F9CFC(fixture+3E, team != fixture+8), fixture vtable+B0()) once a fixture exists
# (2E4DBE4); the slot label reads that count (535DB0, compared at 535DB8 above).
# 17743B8: the pointer cached at [[team+A0]+B8] is returned as it is when days > 364 (1774410,
# return at 177471C); without one the game searches, which the reader does not repeat.
# Session: the constructor zeroes 35B0..35B6 (22BFB28) and stores 11 + the same minimum in
# 35B0 and 35B1 only when its match list holds a match of this TEAM (skip at 22BFCB8, stores
# at 22BFD0C); the evaluator stores it for the fixture its caller passes before it classifies
# any slot (22C3A8C) and may rewrite 35B1 (22C409C). So a session holding zero in both bytes
# has never been given a fixture.
NEXT_FIXTURE_SPANS = (
    (0x2E4D29C, bytes.fromhex('e00301aaa12d8052459ca497e00700f9')),
    (0x2E4D930, bytes.fromhex('fc0740f9')),
    (0x2E4DBE4, bytes.fromhex(
        'fc0100b497fbc039884f40a9085940f9e0031caa00013fd6f60300aa7f0214ebe1079f1ae00317aa3cb06a94'
        '1f00166b08b0961ae90340f928510639'
    )),
    (0x2E4CFE8, bytes.fromhex('e801805288530639')),
    (0x535DB0, bytes.fromhex('88328a52886ae838')),
    (0x1774410, bytes.fromhex('895240f92a5d40f96a0700b4205d40f9e01700b47fb20571ac170054')),
    (0x177471C, bytes.fromhex('fd7b42a9f44f41a9f657c3a8c0035fd6')),
    (0x22BFB28, bytes.fromhex('68c316917fb305b91f3100b8')),
    (0x22BFCB8, bytes.fromhex('960400b4')),
    (0x22BFD0C, bytes.fromhex(
        'd4fac039c80240f9085940f9e00316aa00013fd6f50300aaff0218ebe1079f1ae00314aaf3e798941f00156b'
        '08b0951a082d001168c3163968c71639'
    )),
    (0x22C3A8C, bytes.fromhex(
        '1f0109ebe1079f1aa0fac03999d89894f60300aaa80240f9085940f9e00315aa00013fd6df02006bc8b2801a'
        '082d001188c3163988c71639'
    )),
    (0x22C409C, bytes.fromhex('08b0981a082d001188c71639')),
)
