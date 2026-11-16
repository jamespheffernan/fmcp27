"""Read-only ordinal observation of native Player Search's base source.

The default observes existing HUMAN/container1/kind1 state and the global
actual-player vector selected by0x208B238. The explicit private admission flag
also evaluates its ordinary native base branch. Neither path refreshes a list,
unions retained entries, applies final filters or verifies Manager knowledge.
Call only with a fingerprinted/runtime-verified plugin and a callback
which checks the current process/save/build lifetime and returns its identity.
All addresses/IDs here are internal source bindings, not public player refs.
"""
from copy import deepcopy
import struct

from . import assessment_people, database, players, prepared_tactics_source, teams, world


BASE_VECTORS = {'all_actual': 0x56D2E18, 'split_0': 0x56D2E30, 'split_1': 0x56D2E48}
LIST_LIMIT = 256
SOURCE_LIMIT = 2_000_000  # Reader budget, not an asserted native population limit.
PAGE_LIMIT = 4096
POINTER_READ_SLOTS = 2048  # Canonical Bridge caps each read at 16384 bytes.
HUMAN_DATA_VTABLE = 0x55ACB30


class SourceUnavailable(ValueError):
    """An existing native source needed by this observer is absent/unsupported."""


def _pointer(value):
    if type(value) is not int or value < 4096 or value % 8 or value >= 1 << 64:
        raise ValueError('Invalid search source pointer')
    return value


def _optional_pointer(read, address):
    value = players.u64(read(address, 8))
    return _pointer(value) if value else 0


def _bounds(read, address, limit):
    start, end, capacity = struct.unpack('<QQQ', read(address, 24))
    if (start, end, capacity) == (0, 0, 0):
        return start, 0
    _pointer(start)
    if (any(value % 8 for value in (end, capacity)) or not start <= end <= capacity
            or capacity - start > limit * 8):
        raise ValueError('Invalid search source vector geometry or reader budget')
    return start, (end - start) // 8


def _values(read, start, count):
    values = []
    for offset in range(0, count, POINTER_READ_SLOTS):
        size = min(POINTER_READ_SLOTS, count - offset)
        values.extend(struct.unpack(f'<{size}Q', read(start + offset * 8, size * 8)))
    return tuple(values)


def verify_native(read, base):
    _pointer(base)
    for rva, expected in NATIVE_SPANS:
        if read(base + rva, len(expected)) != expected:
            raise ValueError(f'Search source native instructions changed at {rva:#x}')


def _human_routes(read, base, human):
    primary, person, data = base + world.TYPES['manager'][0], human + 0x548, human + 0x438
    if struct.unpack('<qq', read(primary - 0x20, 16)) != (0x548, 0x438):
        raise ValueError('Search HUMAN subobject adjustments changed')
    prepared_tactics_source._typed(read, base, data, HUMAN_DATA_VTABLE,
                                  world.TYPES['manager'][1], -0x438)
    for table, slot, target in (
            (base + prepared_tactics_source.PERSON_VTABLE, 0x230, 0xCA4744),
            (base + prepared_tactics_source.PERSON_VTABLE, 0x3C8, 0xCB3724),
            (base + prepared_tactics_source.PERSON_VTABLE, 0x408, 0xC8CF20),
            (base + HUMAN_DATA_VTABLE, 0x438, 0x12FFE58)):
        if players.u64(read(table + slot, 8)) != base + target:
            raise ValueError('Search HUMAN virtual route changed')
    for table, slot, expected in (
            (base + prepared_tactics_source.PERSON_VTABLE, -0x3D8, -0x110),
            (base + prepared_tactics_source.PERSON_VTABLE, -0x418, -0x548),
            (base + HUMAN_DATA_VTABLE, -0x450, -0x438)):
        if struct.unpack('<q', read(table + slot, 8))[0] != expected:
            raise ValueError('Search HUMAN virtual adjustment changed')
    return person, data


def _typed_contract(read, base, contract):
    table = players.u64(read(contract, 8))
    kind = next((kind for kind in ('basic_contract', 'full_contract', 'loan_contract', 'trial_contract')
                 if table == base + world.TYPES[kind][0]), None)
    if kind is None:
        raise SourceUnavailable('Unsupported search-context contract type')
    world.typed(read, base, contract, kind)
    return kind, table


def _contract_accepted(read, base, contract):
    kind, table = _typed_contract(read, base, contract)
    if read(contract + 0x26, 1)[0] > 1:
        return True
    getter = 0x129A4B8 if kind == 'full_contract' else 0xD88C6C
    if players.u64(read(table + 0x70, 8)) != base + getter:
        raise ValueError('Search-context contract getter changed')
    return kind == 'full_contract' and read(contract + 0xC2, 1)[0] >= 2


def _secondary_team(read, base, data):
    # HUMAN's DATA+438 getter, not PERSON+438. Mode993 gates DATA+80 -> +10.
    if read(base + 0x56D4993, 1)[0] != 1:
        return 0, 0
    extra = _optional_pointer(read, data + 0x80)
    contract = _optional_pointer(read, extra + 0x10) if extra else 0
    if not contract:
        return 0, 0
    _typed_contract(read, base, contract)
    team = _optional_pointer(read, contract + 0x10)
    if not team:
        return 0, 0
    index = struct.unpack('<I', read(team + 8, 4))[0]
    _, binding = teams.by_index(read, base, index)
    if binding['address'] != team:
        raise ValueError('Search secondary TEAM canonical identity changed')
    return team, binding['owner_address']


def _vector_choice(read, base, coach, human, data):
    contract = world.pointer(read, human + 0x4B0)
    primary_accepted = _contract_accepted(read, base, contract)
    club = world.pointer(read, coach['team_address'] + 0x30)
    mode = read(base + 0x56D4992, 1)[0]
    secondary_team, secondary_owner = (0, 0)
    if not primary_accepted or mode == 1:
        secondary_team, secondary_owner = _secondary_team(read, base, data)
    if not primary_accepted and not secondary_team:
        return 'all_actual', 'no_native_contract_affiliation', mode
    if mode != 1:
        return 'split_0', 'native_discriminator_mode_not_one', mode

    # CA0540 result1/2 selects split0/1; result3 falls back to the selected
    # TEAM owner's bit0 at 208B50C..208B724. Preserve full-byte mismatch first.
    primary_code = read(club + 0xB9, 1)[0] if primary_accepted else None
    secondary_code = read(secondary_owner + 0xB9, 1)[0] if secondary_owner else None
    if primary_accepted:
        mismatch = secondary_code != primary_code if secondary_code is not None else bool(primary_code & 1)
        if secondary_team and mismatch:
            selected_code = read(club + 0xB9, 1)[0]
            return ('split_1' if selected_code & 1 else 'split_0',
                    'native_discriminator_three_selected_team_fallback', mode)
        return ('split_1' if primary_code & 1 else 'split_0',
                'native_primary_contract_affiliation', mode)
    # Main dispatch calls CA0540 here only because secondary_team is nonnull;
    # its no-primary/no-secondary association-projection fallback is unreachable.
    return ('split_1' if secondary_code is not None and secondary_code & 1 else 'split_0',
            'native_secondary_contract_affiliation', mode)


def _selected_list(read, human):
    start, count = _bounds(read, human + 0x248, LIST_LIMIT)
    pointers = _values(read, start, count)
    kinds = {}
    for index, address in enumerate(pointers):
        if not address:
            continue
        _pointer(address)
        if world.pointer(read, address + 0xD0) != human:
            raise ValueError('Search list selected HUMAN owner backlink differs')
        kinds[index] = read(address + 0x4C, 1)[0]
    stored = struct.unpack('<b', read(human + 0x42B, 1))[0]
    effective = max(stored, 0)
    if effective >= count or not pointers[effective]:
        raise SourceUnavailable('Native selected search list is out of bounds or null')
    selected = effective if kinds[effective] == 1 else None
    if selected is None:
        for index, address in enumerate(pointers):
            if not address:
                raise SourceUnavailable('Null header on native kind1 fallback scan')
            if kinds[index] == 1:
                selected = index
                break
    if selected is None:
        raise SourceUnavailable('No existing native kind1 search list')
    address = pointers[selected]
    _, cached_count = _bounds(read, address + 0x80, SOURCE_LIMIT)
    return address, dict(native_kind=1, native_container=1, list_index=selected,
                         stored_signed_index=stored, effective_clamped_index=effective,
                         current_container_raw=read(human + 0x41F, 1)[0],
                         show_all_raw=read(address + 0x101, 1)[0],
                         refresh_byte_ff=read(address + 0xFF, 1)[0],
                         cached_count=cached_count, cached_freshness='unproved')


def _base_identity(read, base, people, primary):
    _pointer(primary)
    table = players.u64(read(primary, 8))
    if table == base + world.TYPES['virtual_player'][0]:
        raise SourceUnavailable('Compact virtual object unexpectedly occurs in base vector')
    tables = tuple(base + rva for rva in players.RVA)
    offset = players.person_offset(read, primary, tables)
    person = primary + offset
    found, found_offset, identity, _, _ = assessment_people._person(read, base, people, person)
    if found != primary or found_offset != offset or identity['record_kind'] not in ('actual', 'player_staff'):
        raise ValueError('Search base actual/combined canonical binding differs')
    person_table = base + (players.RVA[2] if offset == 0x388 else players.STAFF_RVA[2])
    if (players.u64(read(person_table + 0x6E0, 8)) != base + 0xD5C610
            or struct.unpack('<q', read(person_table - 0x6F0, 8))[0] != -offset):
        raise ValueError('Search base PERSON producer cast changed')
    database.player_membership(read, base, people, identity['native_identity']['database_index'], primary)
    return dict(primary=primary, person=person, record_kind=identity['record_kind'],
                native_identity=identity['native_identity'])


def observe(read, base, coach, *, check_current, source_offset=0, source_limit=128,
            apply_native_admission=False):
    """Return one checked ordinal base-source page, never a known-player result.

    check_current must validate the process/save/build lifetime and return its
    nonempty identity tuple before/after observation. The caller retains its
    outer read scope. Consumed-byte verification is non-atomic and also covers
    freshly loaded save/date/coach identities. Source pages preserve duplicates
    and null slots; retained-union discard/dedup logic is not applied to base.
    """
    if (type(source_offset) is not int or source_offset < 0
            or type(source_limit) is not int or not 1 <= source_limit <= PAGE_LIMIT):
        raise ValueError('Invalid search source ordinal page')
    if type(apply_native_admission) is not bool:
        raise ValueError('Expected explicit private native-admission flag')
    if not callable(check_current):
        raise ValueError('Search source requires a process/save/build identity check')
    before = deepcopy(check_current())
    if type(before) is not tuple or not before:
        raise ValueError('Search source requires a checked lifetime identity tuple')
    read = world.ReadSet(read)
    verify_native(read, base)
    save, _ = world.loaded(read, base)
    if coach not in save['coaches']:
        raise ValueError('Selected search coach differs from the loaded save')
    team, human = prepared_tactics_source._team_and_human(read, base, coach)
    if read(coach['team_address'] + 0x2F, 1)[0] != 0:
        raise SourceUnavailable('Selected club container1 requires native TEAM marker zero')
    _, data = _human_routes(read, base, human)
    _, listing = _selected_list(read, human)
    vector, choice, mode = _vector_choice(read, base, coach, human, data)
    _, global_count = _bounds(read, base + BASE_VECTORS['all_actual'], SOURCE_LIMIT)
    start, total = _bounds(read, base + BASE_VECTORS[vector], SOURCE_LIMIT)
    if source_offset > total:
        raise IndexError('Search source offset is outside the native vector')
    scanned = min(source_limit, total - source_offset)
    pointers = _values(read, start + source_offset * 8, scanned)
    people = database.table(read, base, 'people')
    show_all = bool(listing['show_all_raw'] & 1)
    admission = None
    if apply_native_admission:
        if not global_count:
            raise SourceUnavailable('Native empty-global-source diagnostic is not replayed')
        from .knowledge_search_base_admission import Frame
        admission = Frame(read, base, human, show_all=show_all)
    identities, rows = {}, []
    for ordinal, primary in enumerate(pointers, source_offset):
        if not primary:
            rows.append(dict(native_ordinal=ordinal, state='null_base_slot'))
            continue
        if primary not in identities:
            identities[primary] = _base_identity(read, base, people, primary)
        rows.append(dict(native_ordinal=ordinal, state='canonical_actual_subject',
                         **deepcopy(identities[primary])))
        if admission is not None:
            rows[-1]['native_admitted'] = admission.admitted(identities[primary]['person'])
    result = dict(source_state='available', source_scope='stored_native_base_vector_before_retained_union_and_filters',
                  save=save, selected_team=team, list_context=listing, vector=vector,
                  vector_choice=choice, vector_mode_992=mode,
                  fow_enabled_raw=read(base + 0x56D4980, 1)[0],
                  all_actual_source_empty=global_count == 0,
                  native_empty_diagnostic_not_replayed=global_count == 0,
                  source_total=total, source_offset=source_offset, scanned_count=scanned,
                  next_source_offset=source_offset + scanned if source_offset + scanned < total else None,
                  complete_base_source=source_offset == 0 and scanned == total,
                  admission_state=('unrestricted_show_all_bypass' if show_all
                                   else 'restricted_admission_unimplemented'),
                  retained_union_state='unimplemented', complete_search_population=False,
                  manager_knowledge_verified=False, subjects=rows, non_atomic_read=True)
    if apply_native_admission:
        result['native_base_admission_evaluated'] = True
        if not show_all:
            result['admission_state'] = 'native_restricted_base_admission_evaluated'
    read.verify()
    if check_current() != before:
        raise ValueError('Search source process/save/build lifetime changed')
    read.verify()
    return result


# Exact static source guards are appended below. No native targets are invoked.
NATIVE_SPANS = (
    (0x194a5fc, bytes.fromhex(
        'e00314aa2100805222008052030080d2040080d2050080d2aedce597c00200b416044439'
    )),
    (0x12c1578, bytes.fromhex(
        '8102f837291c0012280589131f0900718d0300540a0d00515f090071630800541f190071c105005408b05039081d0013'
        '087da80a0b3441f90a3041f96b010acb1f0d8beb820c00544b00805240000014097c5039280500511f090071c8020054'
        '081d40928a0602d04a212191487968f808686838081d0013087da80a0f000014480500341f090071a102005408ac5039'
        '081d0013087da80a0b2841f90a2441f96b010acb1f0d8beb620900542b00805227000014080080d23f05007120020054'
        '3f090071800100543f0d0071410800540a1c41f9091841f90c000014020200b448bc403948fdff341f050071e0f9ff54'
        '390000140a3441f9093041f9030000140a2841f9092441f94a0109cb1f0d8aeb22060054287968f83000001428050051'
        '1f0500718805005408a85039081d0013087da80a0b1c41f90a1841f96b010acb1f0d8beb820400546b008052487968f8'
        '480400b40a3141395f01096be0030054687d7dd3082100d18a0602d04ae121914a6968f88c0602d08c412291886968f8'
        '086868f80a686af808010aeb600200540afd4393690200347f050071e00500547f090071010700540b0080d20c3041f9'
        '88796bf80d314139bf01096be0000054080080d26b0500915f010beb21ffff5402000014080080d2e00308aac0035fd6'
        '090080d27f050071c00000547f0d0071e10000540c1c41f9081841f9060000140c2841f9082441f9030000140c3441f9'
        '083041f98c0108cb3f0d8ceb62000054087969f802000014080080d20c314139ac0000350c7540f90cfdffb48c0140b9'
        'ccfcff34080080d2290500915f0109eba1fcff54e1ffff170b0080d20c2441f988796bf80d314139bf01096b60fbff54'
        '080080d26b0500915f010beb21ffff54d6ffff170b0080d20c1841f988796bf80d314139bf01096b00faff54080080d2'
        '6b0500915f010beb21ffff54cbffff17'
    )),
    (0x14d9bbc, bytes.fromhex(
        '686a40f9a80200b409a542f929e541f90021159120013fd6'
    )),
    (0x208b314, bytes.fromhex(
        'f6221591e8a642f908e541f9e00316aa00013fd6000200b4089840391f05007128010054080040f9083940f9f50300aa'
        '00013fd6e80300aae00315aa1f090071a3000054080840f9680000b409bd403909120034ff0f00f9e80240f908815ef8'
        'e802088b153d40f9550100b4a80240f9082d40f9e00315aa00013fd61f08007183000054a80a40f9e81700f902000014'
        'ff1700f9c80240f9080542f9e00316aa00013fd6200200b4081840f9e80100b409bc40393f010071092e80520a1b8052'
        '4901899a096969f8090100b408e542391f010071082280520a2380524811889a346968f802000014140080d2e00318aa'
        '010080d202008052bd3ad197ff7f04a9ff2b00f9c8b001b0084945f9280100b5a8b101d008a1199108c1bf38889e0036'
        'a8b101d008c11891c9b001b0284905f9c80240f9081941f9e00316aa00013fd6400300b5c80240f908e541f9e00316aa'
        '00013fd6000200b4089840391f05007128010054080040f9083940f9fa0300aa00013fd6e80300aae0031aaa1f090071'
        'a3000054080840f9680000b409bd403929960034c80240f9080542f9e00316aa00013fd6400300b4e00317aa2054b097'
        '1f040071400100541f080071e101005428b201f008613891092940a93f010aeb6006005408c100918e00001428b201f0'
        '08613891092940a93f010aeba00800540861009187000014790b00b4281b40f9e80e00b413e5423976000014'
    )),
    (0x208b6f0, bytes.fromhex(
        '1300805228b201f008613891092140a93f0108eb408000547f02007208238052092680522811889a29b201f029613491'
        '2801088b010940a9480001cb03fd4393e0030191a1230094'
    )),
    (0x208bb88, bytes.fromhex(
        '28054439c8000036190900b4280340f908815ef83503088b45000014'
    )),
    (0xca0540, bytes.fromhex(
        'a8510290084966391f050071a1050054f44fbea9fd7b01a9fd430091f30300aa080040f908015ef8096868f829e541f9'
        '0000088b20013fd6000200b4089840391f05007128010054080040f9083940f9f40300aa00013fd6e80300aae00314aa'
        '1f090071a3000054080840f9680000b409bd403929060034140080d2680240f908815ef8696a68f8291d42f96002088b'
        '20013fd6a00100b4080840f9b40100b4880100b489e64239081940f9480300b408e542391f01096b0103005419000014'
        '20008052c0035fd6d40200b508000014940200b5c80000b4081940f9880100b408e542394801003610000014680240f9'
        '08015ef86002088b210080528ba61f94600000b408e44239080100372000805207000014690000366000805204000014'
        '88e6423948ff073640008052fd7b41a9f44fc2a8c0035fd6141940f9d0ffff17'
    )),
    (0x12ffe58, bytes.fromhex(
        'a81e02b0084d66391f05007181010054080040f9084111d1080140f90800088b090140f929815ef80801098b084140f9'
        '680000b4000940f9c0035fd6000080d2c0035fd6'
    )),
    (0xc8cf20, bytes.fromhex(
        'fd7bbfa9fd030091080040f9086110d1080140f90800088b090140f929815ef80a6969f84a1d42f90001098b40013fd6'
        '400000b4000840f9fd7bc1a8c0035fd6'
    )),
    (0xca4744, bytes.fromhex(
        '000080d2c0035fd6'
    )),
    (0xcb3724, bytes.fromhex(
        '080040f908610fd1080140f90800088b003d40f9c0035fd6'
    )),
    (0x129a4b8, bytes.fromhex(
        '00084339c0035fd6'
    )),
    (0xd88c6c, bytes.fromhex(
        '00008052c0035fd6'
    )),
    (0x103d5fc, bytes.fromhex(
        '880240f9087143f9e00314aa00013fd6e00700f9800100b460020491e1230091f2d80494880e40f91f0174f208268052'
        '092380522801889a6002088be1230091ead80494'
    )),
    (0xd5c610, bytes.fromhex(
        '080040f908c11bd1080140f90000088bc0035fd6'
    )),
)
