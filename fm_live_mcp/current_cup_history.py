"""Current resident cup PERSON aggregates and optional narrow fixture-rule context.

Reuses independently verified B121/B133 sources. TEAM can be overwritten while
the unsigned cumulative counter continues; no count-by-club or eligibility claim.
"""
import hashlib
import struct

from . import competition_stages, competition_scorers, players, teams, world


class UnsupportedHistory(ValueError):
    """A resident source branch outside the ratified cup-history subset."""


NATIVE_GUARDS = (
    (0x3ab4274, 896, '4926b5ae4bf5e2f2a8fc965a5b9ff13c1fcadf5a61cab8d89c5439ca69b5ea5a'),
    (0x3aa6014, 256, 'eadf4433564b050d94dc15cca710a11b761ed6c090686093e65cd5f8e3ba9d4f'),
    (0x3c6c550, 32, '1118c30d6646815d162f804db0dc176130e7478f0732dc45a90d6a721231616a'),
    (0x1b14708, 816, 'fe4c783e46bcd559ac22a65ce3d2f12ad0e2daa0387c0c553d114ffbb1124855'),
    (0x3aa4128, 1148, '27ba44e52328b0c718db06a3f0f67a03690ffbe06046c193a73feeceaf345891'),
    (0xf38f70, 1172, 'cf2c27f7ccbdc90c6a1740ea0dccbd939933ad810af535b9233115649c858234'),
    (0x3c9c284, 128, '5eb5c6b51b58627448a36533c26ad3eff902f46b3426aedead7678c027ab55ba'),
    (0x3b8c0a0, 128, '53033ee617748f2f3746ea7c0c027879e9db206ec3f1ffb6bcc4613a3a08406e'),
    (0x3b8c090, 128, '8d37ed359f8afc182f3313d1a43c6eef6a2d6c55146bc3a95c7a07a0c0b861da'),
    (0x3c9c27c, 128, 'e9a9ab8bcc6bacb3ff98020546910e2c83721f20584abc3249c4334c4ebb8f01'),
    (0x3c6c498, 128, 'df6d2793634aa4872cc78bfc80ef0fd9d99780396cbcc2d7390ea3b853d16b22'),
    (0x3c9c290, 128, 'efb3a239d2fe504820ea328388d28dac79f69cfbade2ec909df7379a4b4cba10'),
    (0x3c6dbf4, 128, 'b73a5549bfe49b301e3400fe80b87dca11367278b85da7aa535c4acbc5e73e0e'),
    (0x3c855e8, 128, '8b90f4f86684828a0242f148a3a3cd1e307b3e4bd2aeca9eda15464c4396c8a1'),
)


def verify_native(read, base):
    competition_scorers.verify_native(read, base)
    for rva, size, expected in (*NATIVE_GUARDS, *PRODUCER_GUARDS):
        digest = hashlib.sha256()
        for at in range(0, size, 4096):
            digest.update(read(base + rva + at, min(4096, size - at)))
        if digest.hexdigest() != expected:
            raise ValueError('Cup history native context changed')


def _method(read, base, vtable, slot, expected):
    if players.u64(read(vtable + slot, 8)) != base + expected:
        raise ValueError('Cup history stage dispatch changed')


def phase(read, base, runtime, fixture_address, fixture_stage):
    """Only the ordinary CUP_STAGE selector route; unknown routes stay explicit."""
    state = read(runtime + 0x49, 4)
    if state[3] & 8 or read(runtime + 0x3BE, 1) != b'\x03':
        raise UnsupportedHistory('unsupported_runtime_rule_override')
    stage_index, round_index = struct.unpack('<bb', read(fixture_address + 0x38, 2))
    direct = struct.unpack('<b', read(fixture_address + 0x54, 1))[0]
    origin = 'fixture_direct_phase'
    if direct == -1:
        stages, _ = competition_stages.vector(read, runtime + 0x1D8, 256)
        if not 0 <= stage_index < len(stages) or stages[stage_index] != fixture_stage:
            raise UnsupportedHistory('fixture_stage_membership_unavailable')
        competition_stages.typed(read, base, fixture_stage, competition_stages.STAGE_TYPES['cup'])
        vtable = world.pointer(read, fixture_stage)
        for slot, expected in ((0x2F8, 0x3C9C284), (0x2D8, 0x3B8C0A0),
                               (0x2C8, 0x3B8C090), (0x2C0, 0x3C9C27C),
                               (0x360, 0x3C6C498), (0x368, 0x3C9C290)):
            _method(read, base, vtable, slot, expected)
        details = world.pointer(read, fixture_stage + 0x90)
        rounds, _ = competition_stages.vector(read, details + 0x58, 128)
        if not 0 <= round_index < len(rounds) or not rounds[round_index]:
            raise UnsupportedHistory('fixture_round_unavailable')
        direct = struct.unpack('<b', read(rounds[round_index] + 0x137, 1))[0]
        origin = 'fixture_stage_round_phase'
    index = state[0] if direct == -1 else direct
    owner = world.pointer(read, runtime + 0x388)
    bank = world.pointer(read, owner + 0x1F0)
    rules, _ = competition_stages.vector(read, bank + 0x60, 128)
    if not 0 <= index < len(rules) or not rules[index]:
        raise UnsupportedHistory('selected_phase_rule_absent')
    rule = rules[index]
    if read(rule + 0x125, 1) == b'\x08':
        raise UnsupportedHistory('unsupported_rule_selector8_filter')
    requirements = players.u64(read(rule + 0x70, 8))
    flags = []
    if requirements:
        competition_scorers._pointer(requirements)
        count = read(requirements + 0x18, 1)[0]
        flags = list(read(requirements + 0x19, count)) if count else []
    return {'state': 'matched', 'source': origin, 'stage_index': stage_index,
            'round_index': round_index, 'phase_index': index, 'rule_flags': flags}


def collect(read, base, saved, fixture_address, decoded, stage_binding, selected):
    """Return exact resident lookup facts, never an all-history appearance verdict."""
    verify_native(read, base)
    context, runtime, binding = competition_stages.runtime_context(read, base, saved)
    coverage = {**context, 'source_state': 'unavailable', 'unavailable_reason': None,
                'physical_row_count': None, 'complete_resident_lookup': False,
                'phase': None}
    if runtime is None:
        return {**coverage, 'unavailable_reason': 'runtime_competition_absent'}, None
    if (binding[1] != competition_scorers.ACTUAL_COMP or context['shared_runtime']
            or not context['native_season_code']):
        return {**coverage, 'unavailable_reason': 'unsupported_or_shared_runtime'}, None
    if decoded['season_code'] != context['native_season_code']:
        return {**coverage, 'unavailable_reason': 'fixture_runtime_season_mismatch'}, None
    if stage_binding is None or stage_binding['kind'] != 'cup':
        return {**coverage, 'unavailable_reason': 'ordinary_cup_stage_not_bound'}, None
    try:
        selected_phase = phase(read, base, runtime, fixture_address, stage_binding['address'])
    except UnsupportedHistory as error:
        return {**coverage, 'unavailable_reason': str(error)}, None
    coverage['phase'] = selected_phase
    return _history(read, base, runtime, binding, coverage, selected)


def collect_current(read, base, saved, selected):
    """Current resident cup aggregate only; no fixture or age of last update."""
    verify_native(read, base)
    context, runtime, binding = competition_stages.runtime_context(read, base, saved)
    coverage = {**context, "source_state": "unavailable", "unavailable_reason": None,
                "physical_row_count": None, "complete_resident_lookup": False, "phase": None}
    if runtime is None:
        return {**coverage, "unavailable_reason": "runtime_competition_absent"}, None
    if (binding[1] != competition_scorers.ACTUAL_COMP or context["shared_runtime"]
            or not context["native_season_code"] or read(runtime + 0x3BE, 1) != b"\x03"):
        return {**coverage, "unavailable_reason": "unsupported_or_shared_cup_runtime"}, None
    return _history(read, base, runtime, binding, coverage, selected)


def _history(read, base, runtime, binding, coverage, selected):
    stats = players.u64(read(runtime + 0x390, 8))
    if not stats:
        return {**coverage, 'unavailable_reason': 'competition_history_not_resident'}, None
    competition_scorers._pointer(stats)
    competition_stages.typed(read, base, stats, competition_scorers.STATS_TYPE)
    if (world.pointer(read, stats + 0x7B8) != binding[2]
            or players.u64(read(base + competition_scorers.STATS_TYPE[0] + 0x40, 8))
            != base + 0xF3CA9C):
        raise ValueError('Cup history COMP ownership or lookup dispatch changed')
    header = struct.unpack('<QQQ', read(stats + 0x1278, 24))
    start, end, capacity = header
    if header == (0, 0, 0):
        pointers = ()
    else:
        competition_scorers._pointer(start)
        if (not start <= end <= capacity or end % 8 or capacity % 8
                or capacity - start > 20_000 * 8):
            return {**coverage, 'unavailable_reason': 'resident_history_bounds_or_budget'}, None
        pointers = struct.unpack(f'<{(end-start)//8}Q', read(start, end-start)) if end > start else ()
    matches = {index: [] for index in selected}
    for pointer in pointers:
        competition_scorers._pointer(pointer, alignment=4)
        raw = read(pointer, 16)
        index = int.from_bytes(raw[:4], 'little')
        if index in matches:
            matches[index].append(raw)
    rows = {}
    lookup = teams.lookup(read, base)
    for index, raw_rows in matches.items():
        row = {'state': 'absent', 'reason': None,
               'stored_appearance_counter_raw_u8': None,
               'last_associated_team': None, 'last_associated_team_state': 'no_row',
               'native_other_team_cup_history_condition': None,
               'historical_other_team_appearance': None,
               'historical_other_team_appearance_state': 'not_established_by_aggregate_person_row'}
        if len(raw_rows) > 1:
            row.update(state='unavailable', reason='ambiguous_duplicate_person_history_rows')
        elif raw_rows:
            raw = raw_rows[0]
            team_index = int.from_bytes(raw[4:8], 'little')
            row.update(state='present', stored_appearance_counter_raw_u8=raw[10],
                       _team_index=team_index,
                       last_associated_team_state='unassigned' if team_index == 0xFFFFFFFF else 'decoded')
            if team_index != 0xFFFFFFFF:
                if team_index >= lookup['count']:
                    row.update(state='unavailable', reason='history_team_index_out_of_range',
                               last_associated_team_state='unavailable')
                else:
                    team, _ = teams.by_index(read, base, team_index, info=lookup)
                    row['last_associated_team'] = team
        rows[index] = row
    coverage.update(source_state='available', physical_row_count=len(pointers),
                    complete_resident_lookup=True)
    return coverage, rows


def condition(row, fixture_team_index, flags):
    """Exact flag1 branch. Its absent lookup is false, never zero appearances."""
    row = dict(row)
    team_index = row.pop('_team_index', None)
    if row['state'] == 'unavailable':
        reason = row['reason']
        value = None
    elif 1 not in flags:
        reason, value = 'whole_competition_flag1_not_selected', None
    else:
        reason, value = 'native_flag1_person_row_team_comparison', bool(
            row['state'] == 'present' and team_index != fixture_team_index)
    row.update(native_other_team_cup_history_condition=value,
               native_condition_reason=reason)
    return row


# B133 producer guards pin admitted updates, TEAM overwrite and byte counter.
PRODUCER_GUARDS = (
    (0xf52878, 492, '150daa6f6c3dd54e591a170e15b3097710b784469af065f323f666b8cf1052d2'),
    (0xf52b48, 116, 'a5a8594d3b4dc21349940b024b9331d27bf8019c9dc48df091e48fc0bdd691d5'),
    (0xf52d04, 120, '29ab162280ef2fcf162eb0858dd3e84147c33fd4c28c08e610f6af3b73ec6ad2'),
    (0xf53050, 24, 'bfee29370b02605670b287b5c03b2950de04839747f1d2f3dcdb3ea47c08d654'),
    (0xf53274, 12, 'c4dd834f92b315160ca5b559cc5311273560d607aba3832ba2ada02351835c40'),
    (0xf3cb34, 76, 'df0ee2a4690950db65d1a9d6848f7046421917612f4e39ae5ec0f8ecc854855c'),
    (0x1b147c4, 68, '049cdfb7ad0dbb8b5033f78095348af80a9030ffc0b239ab09276755260e0df5'),
    (0x1b14864, 76, '6adec3cbf7ff36265265c0c7aaa76932381b8e28a0fc7047a5081b4b225e8c41'),
)
