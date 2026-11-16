"""Persistent registration markers for caller-validated ordinary PLAYER bindings.

The caller owns canonical PLAYER/TEAM identity, selected native rule/selector,
current competition/season context and final consumed-byte verification. This
reads a persistent TEAM/selector fact. The optional current_predicate projector
closes D32054's supported earlier gates for the current Premier League rule.
The official submitted population and fixture eligibility remain separate. A
marker has no decoded COMP, season or submission timestamp; current context
supplies the rule scope without inventing a historical submission date.
"""
import hashlib
import struct

MAX_RECORDS = 125
NATIVE_GUARDS = (
    (0xD32054, 0x290, 'c8e5a0ed8f94d32ad40c215396d1f6417f48c95906b6ce0ca5b3b71ae0b0b55b'),
    (0xD325DC, 0x274, '3e22e4a95f35ac82a2229bfe1bca3cfee404ec09ea23cab63079c5627a2bfa3e'),
    (0x14D1880, 0x124, 'd284b35320714f337884e96e7b83822ae0251daa77840d5a5b2263a59e7dfeb4'),
    (0xD2DCB8, 0x3A8, 'efdebfe23f59ddeb11e677743246d04d3f57342580d9ddfbf13266b4f935f4de'),
    (0x14A6478, 0x1AC, '9df7a86301b56c53e1798e7171e61252a3c950358feee7068cd4d7ad1c2a8002'),
    (0x3D46BF0, 0x1D0, '52bf8f78528afb1b26f67a7da4dbbcd5ba778eb02884624f12dce767a40bbddc'),
)
STATES = {25: 'native_committed_marker', 26: 'native_temporary_addition',
          27: 'native_temporary_removal'}


def _address(value):
    if type(value) is not int or value < 4096 or value % 8 or value >= 1 << 64:
        raise ValueError('Invalid persistent player registration source address')


def _read(read, address, size):
    raw = read(address, size)
    if type(raw) is not bytes or len(raw) != size:
        raise ValueError('Incomplete persistent player registration source read')
    return raw


def _code_pointer(read, address, base):
    value = struct.unpack('<Q', _read(read, address, 8))[0]
    # The pinned ARM64 __text section is [55F0,4AED934). Instructions are
    # four-byte aligned; ordinary object pointers still use _address's eight.
    if value % 4 or not base+0x55F0 <= value <= base+0x4AED934-8:
        raise ValueError('Invalid persistent registration code pointer')
    return value


def verify_native(read, base):
    _address(base)
    for rva, size, expected in NATIVE_GUARDS:
        if hashlib.sha256(_read(read, base+rva, size)).hexdigest() != expected:
            raise ValueError(f'Persistent registration source changed at RVA {rva:#x}')


def project(read, primary_address, record_kind, team_address, selector):
    """Read the newest exact TEAM/selector marker without executing its getter.

    Call verify_native once per request. An ordinary actual PLAYER's common
    subobject is primary+278 in the pinned build; the caller checks canonical
    type/identity before calling. No pointer or raw record is returned.
    """
    if record_kind not in ('actual', 'player_staff', 'virtual'):
        raise ValueError('Unknown player registration binding kind')
    _address(team_address)
    if type(selector) is not int or not 0 <= selector <= 255:
        raise ValueError('Invalid native registration selector')
    result = dict(source_state='unsupported_record_kind', physical_record_count=None,
                  selected_marker=None, submission_date=None, marker_season=None,
                  marker_competition=None, registration_verdict=None,
                  eligibility_state='not_evaluated')
    if record_kind != 'actual':
        return result
    _address(primary_address)
    holder = struct.unpack('<Q', _read(read, primary_address+0x278+0x48, 8))[0]
    if not holder:
        result['source_state'] = 'holder_absent'
        return result
    _address(holder)
    start, end, capacity = struct.unpack('<QQQ', _read(read, holder, 24))
    if start == end == capacity == 0:
        count = 0
    else:
        if (start < 4096 or not start <= end <= capacity
                or any(value % 8 for value in (start, end, capacity))
                or (end-start) % 16 or (capacity-start) % 16
                or capacity-start > MAX_RECORDS*16):
            raise ValueError('Invalid persistent player registration vector')
        count = (end-start)//16
    raw = _read(read, start, count*16) if count else b''
    selected = None
    for slot in reversed(range(count)):
        pointer, _, transport, kind, stored_selector, metadata, _ = struct.unpack_from(
            '<QHBBBBH', raw, slot*16)
        if not (25 <= kind <= 29 or kind == 56):
            continue
        if kind != 56 and stored_selector != selector:
            continue
        if transport != 4 or pointer != team_address:
            continue
        selected = dict(native_slot_index=slot, native_kind=kind,
                        state=STATES.get(kind, 'unmapped_native_marker_kind'),
                        native_selector=stored_selector,
                        selector_match='native_kind56_bypass' if kind == 56 else 'exact',
                        unmapped_metadata_byte=metadata)
        break
    result.update(source_state='present_marker' if selected else
                  'present_no_matching_marker' if count else 'present_empty',
                  physical_record_count=count, selected_marker=selected)
    return result


def current_league_context(read, base, coach, current_date):
    """Bind the supported current PL selector and all shared pending-state gates.

    No marker timestamp is required: D32054 never reads one. Competition and
    season qualify this selected current rule; they do not date a stored marker.
    """
    from . import league_age_exemptions, players, prepared_tactics_source
    league_age_exemptions.verify_native(read, base)
    verify_native(read, base)
    _, human = prepared_tactics_source._team_and_human(read, base, coach)
    team = coach['team_address']
    public, club = league_age_exemptions.context(read, base, team, current_date)
    result = dict(source_state='unavailable', reason=public['reason'],
                  team=public['team'], competition=public['competition'],
                  native_season_code=public['native_season_code'], native_selector=None)
    if public['source_state'] != 'available':
        return result, None
    def pointer(at):
        value = struct.unpack('<Q', _read(read, at, 8))[0]
        if value:
            _address(value)
        return value
    comp = pointer(team+0x50)
    runtime = pointer(comp+0xB0)
    owner = pointer(runtime+0x388)
    flags = struct.unpack('<I', _read(read, runtime+0x4C, 4))[0]
    parent = pointer(runtime+0x138)
    parent_id = struct.unpack('<i', _read(read, parent+12, 4))[0] if parent else -1
    global_id = struct.unpack('<i', _read(read, base+0x56D3518, 4))[0]
    # 3D46BF0 admits this direct own-runtime branch. Other branches remain
    # unavailable instead of selecting an inferred current rule.
    if (global_id != parent_id and (flags & ((1 << 6) | (1 << 17))
            or _read(read, runtime+0x4C0, 1)[0] == 3
            or pointer(runtime+0x510)
            or _read(read, owner+0x23C, 1)[0] in (1, 3)
            or struct.unpack('<h', _read(read, runtime+0x3B6, 2))[0] == -3)):
        result['reason'] = 'unsupported_player_rule_selection_branch'
        return result, None
    bank = pointer(owner+0x1F0)
    rules = prepared_tactics_source._vector(read, bank+0x60, 256)
    index = _read(read, runtime+0x49, 1)[0]
    rule = rules[index]
    mask = struct.unpack('<Q', _read(read, rule+0xE8, 8))[0]
    # Every true-return path in D2DCB8 is controlled by one of these bits.
    if mask & sum(1 << bit for bit in (14, 37, 3, 31)):
        result['reason'] = 'unsupported_player_registration_restriction_mask'
        return result, None
    kinds = []
    # 14A652C/14A65B4 test kind19 in both vectors; each other pinned
    # literal leaf skips its PLAYER/TEAM matching call.
    leaves = {0x22A8DB8: 37, 0x22DC800: 17, 0x22CED60: 3, 0x22BEF64: 11,
              0x22D3820: 23, 0x22A11B4: 12}
    for offset in (0x200, 0x218):
        for session in prepared_tactics_source._vector(read, human+offset, 128):
            if not session:
                continue
            vt = pointer(session)
            fn = _code_pointer(read, vt+0x10, base)
            kind = leaves.get(fn-base)
            if kind is None:
                result['reason'] = 'unsupported_pending_player_context_kind'
                return result, None
            expected = struct.pack('<II', 0x52800000 | (kind << 5), 0xD65F03C0)
            if _read(read, fn, 8) != expected:
                raise ValueError('Pending registration context kind leaf changed')
            kinds.append(kind)
    # Kind19 would need its PLAYER/TEAM matching method. It is not among the
    # admitted literal leaves, so an existing kind19 takes unavailable above.
    result.update(source_state='available', reason='native_current_pl_registration_context',
                  native_selector=8, native_rule_index=index,
                  pending_context_kinds=kinds)
    return result, dict(team_address=team, club_address=club, selector=8,
                        rule_address=rule, base=base)


def current_predicate(read, primary_address, record_kind, binding):
    """Project exact D32054(mode1) under the proved current PL branch.

    A true committed25 is a current native registered-predicate fact. Pending26
    can also return true; that state is kept explicit. The official submitted
    population and fixture eligibility are separate contracts.
    """
    from . import players, teams
    result = dict(source_state='unavailable', reason='current_context_unavailable',
                  native_predicate_result=None, marker=None,
                  complete_submitted_population_evaluated=False,
                  fixture_eligibility_evaluated=False)
    if binding is None:
        return result
    base, team, club, selector = (binding[key] for key in (
        'base', 'team_address', 'club_address', 'selector'))
    if record_kind != 'actual':
        result['reason'] = 'unsupported_record_kind'
        return result
    if struct.unpack('<Q', _read(read, primary_address, 8))[0] != base+players.RVA[0]:
        raise ValueError('Current registration ordinary PLAYER type changed')
    if struct.unpack('<q', _read(read, base+players.RVA[0]-0x20, 8))[0] != 0x278:
        raise ValueError('Current registration common PLAYER displacement changed')
    person = primary_address+0x388
    person_vt = struct.unpack('<Q', _read(read, person, 8))[0]
    if (person_vt != base+players.RVA[2]
            or struct.unpack('<Q', _read(read, person_vt+0x230, 8))[0] != base+0xD5C578
            or struct.unpack('<q', _read(read, person_vt-0x240, 8))[0] != -0x388):
        raise ValueError('Current registration PERSON current-team getter changed')
    marker = project(read, primary_address, record_kind, team, selector)
    result['marker'] = marker
    current = struct.unpack('<Q', _read(read, primary_address+0x128, 8))[0]
    if not current:
        result['reason'] = 'player_current_team_absent'
        return result
    _address(current)
    index = struct.unpack('<I', _read(read, current+8, 4))[0]
    _, current_binding = teams.by_index(read, base, index)
    if current_binding['address'] != current:
        raise ValueError('Current registration PLAYER team membership changed')
    if current_binding['owner_address'] != club or _read(read, current+0x2F, 1) != b'\0':
        result['reason'] = 'player_current_team_outside_managed_club'
        return result
    if marker['source_state'] == 'holder_absent':
        result.update(source_state='available', reason='native_holder_absent',
                      native_predicate_result=False)
        return result
    contract = struct.unpack('<Q', _read(read, primary_address+0x278+0x78, 8))[0]
    if contract:
        _address(contract)
        if _read(read, contract+0x28, 1)[0] & 8:
            result['reason'] = 'unsupported_contract_registration_override'
            return result
    selected = marker['selected_marker']
    value = bool(selected and selected['native_kind'] in (25, 26))
    result.update(source_state='available', reason='native_player_registration_predicate_mode1',
                  native_predicate_result=value)
    return result
