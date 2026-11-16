"""Native-branch semantic and typed-memory controls; synthetic, never live proof."""
from collections import Counter
from dataclasses import replace
from datetime import date, timedelta
import hashlib
from pathlib import Path
import struct

import pytest

from fm_live_mcp import database, international_duty_source as source, players, world

# Installed metadata/name RVAs, including actual byte-aligned (not necessarily
# eight-aligned) native RTTI text. Checked against the binary below.
RTTI_ROUTES = {
    0x5588EE8: (0x558EE60, 0x53889EC),
    0x558A780: (0x558EE60, 0x53889EC),
    0x558EF38: (0x5598AD0, 0x5388F0E),
    0x55908E0: (0x5598AD0, 0x5388F0E),
    0x559CF48: (0x559DA18, 0x5389AF6),
    0x55A1508: (0x55A2F68, 0x538F27B),
    0x55A1940: (0x55A3040, 0x538F3CC),
    0x55A19B8: (0x55A3058, 0x538F401),
    0x55A1C88: (0x55A30E8, 0x538F4E8),
    0x55B2A08: (0x55B2A30, 0x53952CA),
    0x55B5D50: (0x55B5E70, 0x5396EF9),
    0x55B5E98: (0x55B6068, 0x53970F9),
    0x55C2E40: (0x55C3088, 0x53A1B5B),
    0x55E1208: (0x55E12B0, 0x53B1BE4),
    0x559ED88: (0x559EE70, 0x538BB9F),
    0x55A1580: (0x55A2F80, 0x538F29C),
    0x55AB970: (0x55AB948, 0x5392508),
    0x55A16E8: (0x55A2FC8, 0x538F306),
    0x566C2B8: (0x566CAC0, 0x53EA1C9),
    0x569CC88: (0x569CD60, 0x53F8C3C),
    0x569CA88: (0x569CB60, 0x53F8C00),
    0x55DD068: (0x55DD928, 0x53AD568),
    0x55DC600: (0x55DCA30, 0x53AD020),
}


def packed(value, flags=0):
    if isinstance(value, str):
        value = date.fromisoformat(value)
    return struct.pack('<HH', value.timetuple().tm_yday | flags, value.year)


class Memory:
    def __init__(self, combined=False):
        self.cells, self.reads, self.tables = {}, [], {}
        self.base, self.next = 0x100000000, 0x400000
        self.primary = 0x100000
        self.person = self.primary + (0x480 if combined else 0x388)
        self.club_team, self.national, self.club, self.container = 0x200000, 0x210000, 0x220000, 0x230000
        self.international, self.provider = 0x240000, 0x250000
        self.combined = combined
        for rva, raw in source.NATIVE_SPANS:
            self.put(self.base + rva, raw)
        for slot, target in ((0x55DF1E8, 0x1F8DB6C), (0x55BA230, 0x153AD48)):
            self.q(self.base + slot, self.base + target)
        primary, offset, name = source.PERSON_TYPES[players.STAFF_RVA[2] if combined else players.RVA[2]]
        person_rva = players.STAFF_RVA[2] if combined else players.RVA[2]
        self.typed(self.primary, (primary, name))
        self.put(self.base + primary - 0x18, struct.pack('<q', offset))
        self.typed(self.person, (person_rva, name), -offset)
        self.put(self.person + 8, struct.pack('<III', 0, 111, 0))
        for slot, adjustment, fn in ((0x668, 0x678, 0xD5C5FC), (0x220, 0x230, 0xD5C560), (0x230, 0x240, 0xD5C578)):
            self.q(self.base + person_rva + slot, self.base + fn)
            self.put(self.base + person_rva - adjustment, struct.pack('<q', -offset))
        for address, kind, index, uid in ((self.club_team, 'team', 0, 222),
                                        (self.national, 'national_team', 1, 333),
                                        (self.club, 'club', 0, 444),
                                        (self.container, 'national_team_container', 0, 555)):
            self.typed(address, world.TYPES[kind])
            self.put(address + 8, struct.pack('<III', index, uid, uid))
        self.put(self.club_team + 0x2F, b'\0')
        self.put(self.national + 0x2F, b'\1')
        self.q(self.club_team + 0x30, self.club)
        self.q(self.national + 0x30, self.container)
        self.q(self.primary + 0x128, self.club_team)
        self.q(self.primary + 0x120, self.national)
        self.q(self.primary + 0x118, self.international)
        self.typed(self.international, source.INTDATA)
        self.typed(self.provider, source.PROVIDER)
        self.q(self.base + 0x56D2B30, self.provider)
        self.q(self.base + source.PROVIDER[0] + 0x38, self.base + 0x204F5C0)
        self.database('people', [self.person])
        self.database('teams', [self.club_team, self.national])
        self.database('clubs', [self.club])
        self.database('national_team_containers', [self.container])
        self.put(self.base + world.CURRENT_DATE, packed('2030-11-13'))
        self.set_fields()
        self.person_ref = source.CanonicalRef(self.person, 0, 111, 0)
        self.team_ref = source.CanonicalRef(self.club_team, 0, 222, 222)
        for slot, fn in ((0x240, 0x1489900), (0x230, 0xD5C578)):
            self.q(self.base + person_rva + slot, self.base + fn)
        self.club_data, self.national_data = 0x260000, 0x270000
        self.fixture_name, self.competition, self.runtime = 0x280000, 0x290000, 0x2A0000
        self.cache = 0x2B0000
        self.rule_manager, self.comp_manager = 0x2C0000, 0x2D0000
        self.typed(self.rule_manager, source.RULE_GROUP_MANAGER)
        self.typed(self.comp_manager, source.COMP_MANAGER)
        self.q(self.base + 0x56D57D0, self.rule_manager)
        self.q(self.rule_manager + 0x158, self.comp_manager)
        self.q(self.comp_manager + 0x60, self.provider)
        self.typed(self.fixture_name, source.FIXTURE_NAME)
        self.typed(self.competition, world.TYPES['competition'])
        self.typed(self.runtime, (0x566C2B8, b'N7sicomps11ACTUAL_COMPE'))
        self.put(self.fixture_name + 8, struct.pack('<III', 0, 777, 777))
        self.put(self.competition + 8, struct.pack('<III', 0, 888, 888))
        self.q(self.fixture_name + 0x18, self.competition)
        self.q(self.competition + 0xB0, self.runtime)
        self.q(self.runtime + 0x138, self.competition)
        self.put(self.runtime + 0x3BE, b'\0')
        self.q(self.runtime + 0x510, self.cache)
        self.put(self.cache + 0x78, packed('2030-11-19'))
        self.put(self.runtime + 0x50, bytes(24))
        for slot, fn in ((0x108, 0x3B4D5B0), (0x100, 0x3B4D4BC), (0xF0, 0x3B4D418)):
            self.q(self.base + 0x566C2B8 + slot, self.base + fn)
        self.database('competitions', [self.competition])
        root, header, vector = self.tables['competitions']
        self.put(root + 0x68, struct.pack('<QQQ', vector, vector + 8, vector + 8))
        self.put(self.base + 0x56D34E0, b'\0')
        self.database('fixture_names', [self.fixture_name])
        v = self.allocate(8)
        self.q(v, self.club_team)
        self.put(self.club + 0x18, struct.pack('<QQQ', v, v + 8, v + 8))
        for team, data in ((self.club_team, self.club_data), (self.national, self.national_data)):
            self.q(team + 0xA0, data)
            self.put(data, bytes(0x120))
            self.put(data + 0x10E, struct.pack('<H', 2030))
            self.q(data + 0x28, self.fixture_name)
            self.q(data + 0x30, team)
            self.q(data + 0x38, self.club_team)
            self.put(data + 0x40, packed('2030-11-23' if team == self.club_team else '2030-11-16'))
        self.q(self.national + 0x50, 0)

    def rows(self, field, rows):
        pointers = []
        for raw in rows:
            row = self.allocate(len(raw))
            self.put(row, raw)
            pointers.append(row)
        vector, header = self.allocate(8 * len(rows)), self.allocate(24)
        self.put(vector, struct.pack('<' + 'Q' * len(rows), *pointers))
        self.put(header, struct.pack('<QQQ', vector, vector + len(rows) * 8, vector + len(rows) * 8))
        self.q(field, header)
        return pointers, header

    def property_values(self, rows):
        payload = bytearray()
        for key, value, null_trait in rows:
            descriptor, handle = self.allocate(16), self.allocate(16)
            trait = source.NULL_TRAIT if null_trait else source.INTEGER_TRAIT
            self.typed(descriptor, trait)
            self.put(descriptor + 8, bytes([0 if null_trait else 1]))
            self.q(self.base + trait[0] + 0x48, self.base + (0x28E64 if null_trait else 0x4406EF8))
            self.q(handle, descriptor)
            self.put(handle + 8, struct.pack('<i', value))
            payload += struct.pack('<IIQ', key, 0, handle)
        start = self.allocate(len(payload))
        self.put(start, bytes(payload))
        self.put(self.runtime + 0x50, struct.pack('<QQQ', start, start + len(payload), start + len(payload)))

    def allocate(self, size):
        value = self.next
        self.next += (size + 7) // 8 * 8
        return value

    def put(self, address, raw):
        self.cells.update((address + i, value) for i, value in enumerate(raw))

    def q(self, address, value):
        self.put(address, struct.pack('<Q', value))

    def read(self, address, size):
        self.reads.append((address, size))
        return bytes(self.cells[address + i] for i in range(size))

    def typed(self, address, layout, displacement=0):
        rva, name = layout
        info, text = (self.base + value for value in RTTI_ROUTES[rva])
        self.q(address, self.base + rva)
        self.put(self.base + rva - 16, struct.pack('<qQ', displacement, info))
        self.q(info + 8, text)
        self.put(text, name + b'\0')

    def database(self, kind, pointers):
        root_rva, table_rva, name = database.TABLES[kind]
        root, header, vector = self.allocate(0x90), self.allocate(24), self.allocate(8 * len(pointers))
        self.typed(root, (table_rva, name))
        self.q(self.base + root_rva, root)
        self.q(root + 0x88, header)
        self.put(header, struct.pack('<QQQ', vector, vector + 8 * len(pointers), vector + 8 * len(pointers)))
        self.put(vector, struct.pack(f'<{len(pointers)}Q', *pointers))
        self.tables[kind] = (root, header, vector)

    def set_fields(self, *, flag=1, end='2030-11-20', start='2030-11-10',
                   travel_start='1900-01-01', travel_end='1900-01-01', phase=0, mode=0):
        self.put(self.national + 0xE2, bytes([flag]))
        self.put(self.national + 0xB8, packed(end))
        self.put(self.national + 0xDC, packed(start))
        self.put(self.international + 0xA4, packed(travel_start))
        self.put(self.international + 0xA8, packed(travel_end))
        self.put(self.international + 0xBB, bytes([phase, mode]))

    def project(self, read=None, **kw):
        return source.read_current(read or self.read, self.base,
            person=kw.get('person', self.person_ref), club_team=kw.get('club_team', self.team_ref))


@pytest.fixture(params=[False, True], ids=['actual', 'combined'])
def memory(request):
    return Memory(request.param)


def test_source_native_gate_positive_actual_and_combined_has_scoped_reason(memory):
    result = memory.project()
    assert result == {'state': 'available', 'reason': 'native_duty_window', 'current_date': '2030-11-13',
        'national_assignment_gate': True,
        'native_gate_reason': {'code': 4, 'key': 242665, 'text': 'On international duty', 'scope': 'input_to_final_availability'},
        'national_team_identity': {'database_index': 1, 'native_id': 333, 'random_id': None},
        'return_date': '2030-11-20', 'return_date_state': 'native_estimated_return', 'eligibility_state': 'not_evaluated'}
    assert not any(key in repr(result) for key in ('address', 'raw_hex', 'due_back', 'a8', 'displayed_status'))
    counts = Counter(memory.reads)
    assert all(value >= 2 for value in counts.values()), 'Every consumed span must be reread'
    assert max(size for _, size in memory.reads) <= 4096


@pytest.mark.parametrize('phase,mode,start,end,gate,reason,code', [
    # Source204f5c0 boundaries, including half-open BB2 and current-day override.
    (0, 0, '2030-11-13', '2030-11-14', True, 'native_travel_window', 16),
    (0, 0, '2030-11-12', '2030-11-13', True, 'native_travel_window', 16),
    (0, 0, '2030-11-13', '2030-11-13', True, 'native_travel_window', 16),
    (2, 0, '2030-11-13', '2030-11-13', True, 'native_travel_window', 16),
    (2, 0, '2030-11-14', '2030-11-12', True, 'native_travel_window', 16),
    (1, 0, '1900-01-01', '1900-01-01', True, 'native_travel_window', 16),
    (1, 1, '1900-01-01', '1900-01-01', True, 'native_travel_window', 15),
    (2, 1, '2030-11-13', '2030-11-14', True, 'native_travel_window', 15),
    # Travel false, assignment remains true; phase3 rejects its duty branch.
    (0, 0, '2030-11-14', '2030-11-15', True, 'native_duty_window', 4),
    (0, 0, '2030-11-01', '2030-11-12', True, 'native_duty_window', 4),
    (3, 0, '2030-11-01', '2030-11-12', False, 'outside_native_assignment_window', None),
    (3, 0, '2030-11-13', '2030-11-13', True, 'native_travel_window', 16),
])
def test_current_date_native_travel_and_duty_branch_table(memory, phase, mode, start, end, gate, reason, code):
    memory.set_fields(phase=phase, mode=mode, travel_start=start, travel_end=end)
    result = memory.project()
    assert (result['state'], result['national_assignment_gate'], result['reason']) == ('available', gate, reason)
    assert result['native_gate_reason'] is None if code is None else result['native_gate_reason']['code'] == code


@pytest.mark.parametrize('flag,end,start,expected,reason', [
    (0, '2030-11-20', '2030-11-10', False, 'native_assignment_flag_inactive'),
    (2, '2030-11-20', '2030-11-10', False, 'native_assignment_flag_inactive'),
    (255, '2030-11-20', '2030-11-10', False, 'native_assignment_flag_inactive'),
    (1, '2030-11-13', '2030-11-10', False, 'native_assignment_expired'),
    (1, '2030-11-12', '2030-11-10', False, 'native_assignment_expired'),
    (1, '1900-01-01', '2030-11-10', False, 'native_assignment_expired'),
    (1, '2030-11-20', '2030-11-14', False, 'outside_native_assignment_window'),
    (1, '2030-11-20', '2030-11-13', True, 'native_duty_window'),
])
def test_native_team_liveness_and_date_guards(memory, flag, end, start, expected, reason):
    memory.set_fields(flag=flag, end=end, start=start)
    before = dict(memory.cells)
    result = memory.project()
    assert result['national_assignment_gate'] is expected and result['reason'] == reason
    assert memory.cells == before, 'Native E2 clear and lifecycle resets must never be executed'


@pytest.mark.parametrize('phase,mode,start,reason', [
    (0, 1, '2030-11-14', 'central_fixture_TLS_selection_unproved'),
    (1, 1, '2030-11-14', 'central_fixture_TLS_selection_unproved'),
    (3, 1, '2030-11-14', 'central_fixture_TLS_selection_unproved'),
    (4, 0, '2030-11-12', 'unsupported_native_phase_or_mode'),
    (255, 0, '2030-11-12', 'unsupported_native_phase_or_mode'),
    (0, 2, '2030-11-12', 'unsupported_native_phase_or_mode'),
])
def test_unclosed_override_or_unknown_phase_never_becomes_false(memory, phase, mode, start, reason):
    memory.set_fields(phase=phase, mode=mode, travel_start=start)
    memory.put(memory.club_data + 0x40, packed('2030-11-13'))
    result = memory.project()
    assert (result['state'], result['reason'], result['national_assignment_gate'], result['native_gate_reason']) == ('unavailable', reason, None, None)


@pytest.mark.parametrize('offset,reason', [(0x118, 'outside_native_retained_fixture_blocks'),
                                         (0x120, 'national_assignment_absent')])
def test_native_null_assignment_and_checked_empty_blocks_are_false_but_not_full_clearance(memory, offset, reason):
    memory.q(memory.primary + offset, 0)
    result = memory.project()
    assert result['state'] == 'available' and result['reason'] == reason
    assert result['national_assignment_gate'] is False and result['native_gate_reason'] is None
    assert result['eligibility_state'] == 'not_evaluated' and result['return_date'] is None


@pytest.mark.parametrize('field', ['person', 'club_team'])
@pytest.mark.parametrize('attribute,value', [('native_id', 901), ('secondary_id', 902), ('database_index', 7)])
def test_stale_expected_person_or_team_reference_rejects(memory, field, attribute, value):
    old = memory.person_ref if field == 'person' else memory.team_ref
    with pytest.raises(ValueError, match='stale'):
        memory.project(**{field: replace(old, **{attribute: value})})


@pytest.mark.parametrize('fault', ['wrong_club_team', 'national_owner', 'club_owner', 'national_type',
    'int_type', 'provider_type', 'person_type', 'primary_type', 'person_displacement',
    'person_cast', 'team_kind', 'national_kind', 'people_slot', 'team_slot', 'container_slot',
    'null_table_root', 'bad_table_bounds', 'cached_person_index', 'provider_dispatch', 'reason_bridge'])
def test_type_owner_canonical_and_dispatch_faults_fail_closed(memory, fault):
    m = memory
    if fault == 'wrong_club_team': m.q(m.primary + 0x128, m.national)
    if fault == 'national_owner': m.q(m.national + 0x30, m.club)
    if fault == 'club_owner': m.q(m.club_team + 0x30, m.container)
    if fault == 'national_type': m.q(m.national, m.base + world.TYPES['team'][0])
    if fault == 'int_type': m.q(m.international, m.base + world.TYPES['team'][0])
    if fault == 'provider_type': m.q(m.provider, m.base + source.INTDATA[0])
    if fault == 'person_type': m.q(m.person, m.base + world.TYPES['virtual_player'][0])
    if fault == 'primary_type': m.q(m.primary, m.base + world.TYPES['virtual_player'][0])
    person_rva = players.STAFF_RVA[2] if m.combined else players.RVA[2]
    if fault == 'person_displacement': m.put(m.base + person_rva - 16, bytes(8))
    if fault == 'person_cast': m.put(m.base + person_rva - 0x678, struct.pack('<q', -0x110))
    if fault == 'team_kind': m.put(m.club_team + 0x2F, b'\1')
    if fault == 'national_kind': m.put(m.national + 0x2F, b'\0')
    if fault == 'people_slot': m.q(m.tables['people'][2], m.person + 8)
    if fault == 'team_slot': m.q(m.tables['teams'][2] + 8, m.club_team)
    if fault == 'container_slot': m.q(m.tables['national_team_containers'][2], m.club)
    if fault == 'null_table_root': m.q(m.base + database.TABLES['teams'][0], 0)
    if fault == 'bad_table_bounds': m.put(m.tables['teams'][1], struct.pack('<QQQ', 0x9000, 0x8FF8, 0x9000))
    if fault == 'cached_person_index': m.put(m.person + 8, struct.pack('<I', 0xFFFFFFFF))
    if fault == 'provider_dispatch': m.q(m.base + source.PROVIDER[0] + 0x38, m.base + 0x204F5C4)
    if fault == 'reason_bridge': m.q(m.base + 0x55DF1E8, m.base + 0x204F5C0)
    with pytest.raises(ValueError): m.project()


@pytest.mark.parametrize('where', ['current', 'assignment_end', 'assignment_start', 'travel_start', 'travel_end'])
@pytest.mark.parametrize('day,year', [(0, 2030), (366, 2030), (511, 2030), (1, 2201), (1, 1849)])
def test_invalid_calendar_inputs_reject_instead_of_normalizing(memory, where, day, year):
    address = {'current': memory.base + world.CURRENT_DATE,
        'assignment_end': memory.national + 0xB8, 'assignment_start': memory.national + 0xDC,
        'travel_start': memory.international + 0xA4, 'travel_end': memory.international + 0xA8}[where]
    memory.put(address, struct.pack('<HH', day, year))
    with pytest.raises(ValueError, match='date|day'): memory.project()


def test_date_flags_are_ignored_by_native_comparison_and_current_default_refuses(memory):
    for address in (memory.base + world.CURRENT_DATE, memory.national + 0xDC):
        memory.put(address, packed('2030-11-13', 0xFE00))
    assert memory.project()['native_gate_reason']['code'] == 4
    memory.put(memory.base + world.CURRENT_DATE, packed('1900-01-01'))
    with pytest.raises(ValueError, match='unset'): memory.project()


@pytest.mark.parametrize('kind', ['primary', 'person', 'intdata', 'provider', 'team',
                                 'national_team', 'club', 'national_team_container'])
def test_native_byte_aligned_rtti_names_are_read_and_wrong_text_refuses(memory, kind):
    layout = players.STAFF_RVA if memory.combined else players.RVA
    rva = {'primary': layout[0], 'person': layout[2], 'intdata': source.INTDATA[0],
           'provider': source.PROVIDER[0]}.get(kind)
    if rva is None:
        rva = world.TYPES[kind][0]
    assert RTTI_ROUTES[rva][1] % 8 != 0
    assert memory.project()['national_assignment_gate'] is True
    memory.put(memory.base + RTTI_ROUTES[rva][1], b'!')
    with pytest.raises(ValueError, match='RTTI'): memory.project()


@pytest.mark.parametrize('field', ['current', 'national_link', 'int_link', 'club_link', 'flag', 'team_end',
    'team_start', 'phase', 'mode', 'travel_start', 'travel_end', 'person_identity', 'canonical_slot', 'native_guard'])
def test_consumed_bytes_are_rechecked_and_drift_cannot_publish(memory, field):
    addresses = {'current': (memory.base + world.CURRENT_DATE, 4),
        'national_link': (memory.primary + 0x120, 8), 'int_link': (memory.primary + 0x118, 8),
        'club_link': (memory.primary + 0x128, 8), 'flag': (memory.national + 0xE2, 1),
        'team_end': (memory.national + 0xB8, 4), 'team_start': (memory.national + 0xDC, 4),
        'phase': (memory.international + 0xBB, 2), 'mode': (memory.international + 0xBB, 2),
        'travel_start': (memory.international + 0xA4, 4), 'travel_end': (memory.international + 0xA8, 4),
        'person_identity': (memory.person, 20), 'canonical_slot': (memory.tables['people'][2], 8),
        'native_guard': (memory.base + source.NATIVE_SPANS[0][0], len(source.NATIVE_SPANS[0][1]))}
    target, size = addresses[field]
    count = 0
    def changed(address, length):
        nonlocal count
        raw = memory.read(address, length)
        if (address, length) == (target, size):
            count += 1
            if count == 2:
                index = 1 if field == 'mode' else 0
                return raw[:index] + bytes([raw[index] ^ 1]) + raw[index + 1:]
        return raw
    with pytest.raises(ValueError, match='changed during read'): memory.project(changed)


def test_unused_duty_start_is_not_required_when_native_travel_branch_wins(memory):
    memory.set_fields(phase=2)
    for i in range(4): del memory.cells[memory.national + 0xDC + i]
    assert memory.project()['native_gate_reason']['code'] == 16
    assert (memory.national + 0xDC, 4) not in memory.reads


@pytest.mark.parametrize('index', range(len(source.NATIVE_SPANS)))
def test_each_source_guard_rejects_changed_native_bytes(memory, index):
    rva, raw = source.NATIVE_SPANS[index]
    memory.put(memory.base + rva, bytes([raw[0] ^ 1]) + raw[1:])
    with pytest.raises(ValueError, match='native source changed'): memory.project()


@pytest.mark.parametrize('bad', [True, None, {}, (1, 2), 0x1000])
def test_no_boolean_permission_or_untyped_identity_can_supply_gate(memory, bad):
    with pytest.raises(ValueError, match='canonical references'):
        memory.project(person=bad)


def test_no_requested_future_date_or_lifetime_claim_is_supported(memory):
    with pytest.raises(TypeError):
        source.read_current(memory.read, memory.base, person=memory.person_ref,
                            club_team=memory.team_ref, requested_date='2030-11-14')
    assert 'before and after' in source.__doc__ and 'cannot establish process/save lifetime' in source.__doc__


def test_incomplete_or_nonbytes_native_reads_fail_closed(memory):
    for broken in (lambda a, n: b'\0' * (n - 1), lambda a, n: bytearray(n)):
        with pytest.raises(ValueError, match='Incomplete'): memory.project(broken)


def test_guard_bytes_and_enum_bridge_match_actual_installed_binary():
    import _pinned_build
    binary = _pinned_build.PLUGIN
    if not binary.exists(): pytest.skip(_pinned_build.MISSING)
    with binary.open('rb') as stream:
        assert hashlib.file_digest(stream, 'sha256').hexdigest() == source.PLUGIN_SHA256
        for rva, expected in source.NATIVE_SPANS:
            stream.seek(0x5ED4000 + rva)
            assert stream.read(len(expected)) == expected
        for slot, target in ((0x55DF1E8, 0x1F8DB6C), (0x55BA230, 0x153AD48)):
            stream.seek(0x5ED4000 + slot)
            assert int.from_bytes(stream.read(8), 'little') & 0xFFFFFFFF == target
        for table, (info, text) in RTTI_ROUTES.items():
            stream.seek(0x5ED4000 + table - 8)
            assert int.from_bytes(stream.read(8), 'little') & 0xFFFFFFFF == info
            stream.seek(0x5ED4000 + info + 8)
            assert int.from_bytes(stream.read(8), 'little') & 0xFFFFFFFF == text
    language = _pinned_build.language_template()
    raw = language.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == source.ENGLISH_RESOURCE_SHA256
    text = raw.decode('utf-8-sig')
    assert 'KEY-242665: On international duty[COMMENT' in text
    assert 'KEY-260981: Travelling[COMMENT' in text


@pytest.mark.parametrize('phase,start,end,expected,code', [
    (3, '2030-11-14', '2030-11-14', False, None),
    (1, '2030-11-12', '2030-11-14', True, 15),
    (0, '2030-11-12', '2030-11-14', True, 15),
])
def test_direct_inline_override_baseline_after_assignment_end_preserves_dates(memory, phase, start, end, expected, code):
    memory.set_fields(phase=phase, mode=1, travel_start=start, travel_end=end)
    before = dict(memory.cells)
    result = memory.project()
    assert result['national_assignment_gate'] is expected
    assert result['native_gate_reason'] is None if code is None else result['native_gate_reason']['code'] == code
    assert result['return_date'] == ('2030-11-20' if expected else None)
    assert memory.cells == before
    assert not any(a == memory.national + 0x50 or a == memory.club_data + 0x98 for a, n in memory.reads)


@pytest.mark.parametrize('runtime_kind', [9, 13, 24, 104])
def test_inline_excluded_runtime_kind_leaves_dates_unchanged(memory, runtime_kind):
    memory.set_fields(phase=3, mode=1, travel_start='2030-11-13', travel_end='2030-11-13')
    memory.put(memory.runtime + 0x3BE, bytes([runtime_kind]))
    assert memory.project()['native_gate_reason']['code'] == 15
    assert not any(a == memory.national + 0x50 for a, n in memory.reads)


@pytest.mark.parametrize('fallback_kind,expected', [(9, True), (24, True), (0, False), (13, False)])
def test_inline_null_runtime_uses_db_comp_f8_not_runtime_kind_set(memory, fallback_kind, expected):
    memory.set_fields(phase=3, mode=1, travel_start='2030-11-13', travel_end='2030-11-13')
    memory.put(memory.club_data + 0x40, packed('2030-11-14'))
    memory.q(memory.competition + 0xB0, 0)
    memory.put(memory.competition + 0xF8, bytes([fallback_kind]))
    result = memory.project()
    assert result['national_assignment_gate'] is expected


@pytest.mark.parametrize('end', ['2030-11-14', '2030-11-15'])
def test_direct_inline_warm_national_bound_produces_real_local_date_mutation(memory, end):
    memory.set_fields(phase=3, mode=1, travel_start='2030-11-12', travel_end=end)
    memory.put(memory.club_data + 0x40, packed('2030-11-13'))
    # baseline==today, warm national descriptor16Nov -> bound15Nov.
    result = memory.project()
    assert result['national_assignment_gate'] is False
    assert result['reason'] == 'outside_native_assignment_window'
    assert (memory.national_data + 0x40, 4) in memory.reads
    # Native mutation is local: the stored A4/A8 still contain the original dates.
    assert memory.read(memory.international + 0xA4, 8) == packed('2030-11-12') + packed(end)


@pytest.mark.parametrize('start,end,third,expected', [
    ('2030-11-12', '2030-11-14', '2030-11-13', True),
    ('2030-11-13', '2030-11-13', '2030-11-14', True),
    ('2030-11-14', '2030-11-20', '2030-11-15', False),
    ('2030-11-01', '2030-11-12', '2030-11-13', False),
])
def test_null118_block_window_boundaries_are_inclusive_and_estimate_is_national_b8(memory, start, end, third, expected):
    memory.q(memory.primary + 0x118, 0)
    memory.rows(memory.national_data + 0xA0, [packed(start) + packed(end) + packed(third) + bytes(20)])
    result = memory.project()
    assert result['national_assignment_gate'] is expected
    assert result['return_date'] == ('2030-11-20' if expected else None)
    assert result['eligibility_state'] == 'not_evaluated'


def test_null118_reverse_first_qualified_row_stops_before_unrelated_earlier_payload(memory):
    memory.q(memory.primary + 0x118, 0)
    rows, _ = memory.rows(memory.national_data + 0xA0, [bytes(32),
        packed('2030-11-12') + packed('2030-11-14') + packed('2030-11-13') + bytes(20)])
    assert memory.project()['national_assignment_gate'] is True
    assert not any(rows[0] <= a < rows[0] + 32 for a, n in memory.reads)


def test_null118_matching_row_remains_candidate_when_query_precedes_third_date(memory):
    memory.q(memory.primary + 0x118, 0)
    memory.rows(memory.national_data + 0xA0, [
        packed('2030-11-12') + packed('2030-11-14') + packed('2030-11-20') + bytes(20)])
    assert memory.project()['national_assignment_gate'] is True


@pytest.mark.parametrize('case', ['null_data', 'bad_header', 'null_row'])
def test_null118_unreadable_or_malformed_source_is_not_checked_absence(memory, case):
    memory.q(memory.primary + 0x118, 0)
    if case == 'null_data':
        memory.q(memory.national + 0xA0, 0)
        result = memory.project()
        assert result['state'] == 'unavailable' and result['national_assignment_gate'] is None
    else:
        rows, header = memory.rows(memory.national_data + 0xA0, [bytes(32)])
        if case == 'bad_header': memory.q(header + 8, 0x100)
        else: memory.q(int.from_bytes(memory.read(header, 8), 'little'), 0)
        with pytest.raises(ValueError): memory.project()


@pytest.mark.parametrize('field', ['descriptor_owner', 'name_type', 'name_slot', 'competition_slot', 'runtime_owner', 'runtime_type', 'current_club_dispatch'])
def test_override_typed_owner_identity_and_dispatch_controls(memory, field):
    memory.set_fields(phase=3, mode=1, travel_start='2030-11-14')
    if field == 'descriptor_owner': memory.q(memory.club_data + 0x30, memory.national)
    if field == 'name_type': memory.q(memory.fixture_name, memory.base + source.INTDATA[0])
    if field == 'name_slot': memory.q(memory.tables['fixture_names'][2], memory.competition)
    if field == 'competition_slot': memory.q(memory.tables['competitions'][2], memory.fixture_name)
    if field == 'runtime_owner': memory.q(memory.runtime + 0x138, memory.club_team)
    if field == 'runtime_type': memory.q(memory.runtime, memory.base + source.INTDATA[0])
    if field == 'current_club_dispatch':
        layout = players.STAFF_RVA if memory.combined else players.RVA
        memory.q(memory.base + layout[2] + 0x240, memory.base + 0x1489904)
    if field == 'runtime_type':
        result = memory.project()
        assert result['state'] == 'unavailable' and result['reason'] == 'unsupported_fixture_runtime_type'
    else:
        with pytest.raises(ValueError): memory.project()


@pytest.mark.parametrize('field', ['team_data', 'descriptor_date', 'descriptor_owner', 'opponent', 'name', 'competition', 'runtime', 'runtime_kind', 'runtime_owner'])
def test_override_consumed_link_and_scalar_drift_never_publishes(memory, field):
    memory.set_fields(phase=3, mode=1, travel_start='2030-11-14')
    target, length = {
        'team_data': (memory.club_team + 0xA0, 8), 'descriptor_date': (memory.club_data + 0x40, 4),
        'descriptor_owner': (memory.club_data + 0x30, 8), 'opponent': (memory.club_data + 0x38, 8),
        'name': (memory.club_data + 0x28, 8), 'competition': (memory.fixture_name + 0x18, 8),
        'runtime': (memory.competition + 0xB0, 8), 'runtime_kind': (memory.runtime + 0x3BE, 1),
        'runtime_owner': (memory.runtime + 0x138, 8)}[field]
    count = 0
    def changed(address, size):
        nonlocal count
        raw = memory.read(address, size)
        if (address, size) == (target, length):
            count += 1
            if count == 2: return bytes([raw[0] ^ 1]) + raw[1:]
        return raw
    with pytest.raises(ValueError, match='changed during read'): memory.project(changed)


@pytest.mark.parametrize('phase', [0, 1, 2, 3])
def test_estimated_return_never_uses_intdata_a8_or_local_fixture_date(memory, phase):
    memory.set_fields(phase=phase, mode=0, travel_start='2030-11-13', travel_end='2030-11-14', end='2030-11-20')
    result = memory.project()
    assert result['national_assignment_gate'] is True
    assert result['return_date'] == '2030-11-20' and result['return_date_state'] == 'native_estimated_return'
    memory.set_fields(flag=0)
    assert memory.project()['return_date'] is None


def native_raw(year, day, flags=0):
    return year << 16 | flags | day


@pytest.mark.parametrize('year', [1899, 1900, 1999, 2000, 2030, 2099, 2100, 2399, 2400])
@pytest.mark.parametrize('day', [1, 2, 59, 60, 365])
@pytest.mark.parametrize('delta', [-32767, -511, -366, -1, 0, 1, 366, 511])
def test_native_date_arithmetic_matches_independent_calendar_in_nonoverflow_domain(year, day, delta):
    actual = source._native_add(native_raw(year, day, 0x9A00), delta)
    expected = date(year, 1, 1) + timedelta(days=day - 1 + delta)
    assert actual == native_raw(expected.year, expected.timetuple().tm_yday, 0x9A00)


@pytest.mark.parametrize('year,day,delta,want_year,want_day', [
    (1899, 2, 32767, 1899, 1), (2030, 318, 32767, 2030, 317),
    (2030, 365, 32767, 2030, 364), (2030, 1, 32767, 2119, 262),
])
def test_literal_native_signed16_date_overflow_edges(year, day, delta, want_year, want_day):
    assert source._native_add(native_raw(year, day, 0x7600), delta) == native_raw(want_year, want_day, 0x7600)


@pytest.mark.parametrize('delta', [-32768, -32767, -366, -1, 0, 1, 366, 32767])
def test_native_subtract_uses_its_signed16_special_case(delta):
    raw = native_raw(2030, 318, 0x7600)
    expected_delta = -32767 if delta == -32768 else -delta
    expected = date(2030, 1, 1) + timedelta(days=317 + expected_delta)
    # +32767 overflows the native intermediate when day>1.
    want = native_raw(2030, 317, 0x7600) if expected_delta == 32767 else native_raw(expected.year, expected.timetuple().tm_yday, 0x7600)
    assert source._native_sub(raw, delta) == want


@pytest.mark.parametrize('baseline,start,end,bound,expected_start,expected_end', [
    ('2030-11-13','2030-11-12','2030-11-14','2030-11-20','2030-11-14','2030-11-16'),
    ('2030-11-13','2030-11-12','2030-11-19','2030-11-17','2030-11-15','2030-11-16'),
    ('2030-11-15','2030-11-12','2030-11-19','2030-11-17','2030-11-16','2030-11-17'),
    ('2030-11-17','2030-11-12','2030-11-19','2030-11-17','2030-11-16','2030-11-17'),
    ('2030-11-18','2030-11-12','2030-11-19','2030-11-17','2030-11-12','2030-11-19'),
    ('2030-11-13','2030-11-14','2030-11-19','2030-11-17','2030-11-14','2030-11-19'),
    ('2030-12-31','2030-12-30','2031-01-02','2031-01-20','2031-01-01','2030-01-04'),
])
def test_scalar_local_adjustment_bounds_and_cross_year_raw_duration(baseline,start,end,bound,expected_start,expected_end):
    args = [int.from_bytes(packed(d), 'little') for d in (baseline,start,end,bound)]
    assert source._adjust_dates(*args) == tuple(int.from_bytes(packed(d), 'little') for d in (expected_start,expected_end))


@pytest.mark.parametrize('rule,want', [(0, '2030-11-19'), (1, '2030-11-18'), (14, '2030-11-05'), (-1, '2030-11-20')])
def test_warm_runtime_date_rule_r0_r1_and_negative_are_source_produced(memory, rule, want):
    memory.q(memory.national + 0x50, memory.competition)
    memory.put(memory.runtime + 0x3BE, bytes([6]))
    memory.property_values([(0x44624C6D, rule, False)])
    assert source._bound(memory.read, memory.base, memory.national, (2030, 317)) == int.from_bytes(packed(want), 'little')


@pytest.mark.parametrize('rows,kind,want', [
    ([], 0, 14), ([], 9, 1), ([(0x64627373, 2, False)],0,1),
    ([(0x64626D75, -2, False)],0,-2), ([(0x44624C6D, 0,True),(0x64626D75,8,False)],0,0),
    ([(0x44624C6D, 3,False),(0x44624C6D,9,False)],0,3),
    ([(0x64626D75,32768,False)],0,-32768),
])
def test_ordered_runtime_rule_priority_null_trait_and_signed16(memory, rows, kind, want):
    memory.property_values(rows)
    memory.put(memory.runtime + 0x3BE, bytes([kind]))
    assert source._runtime_rule(memory.read,memory.base,memory.runtime) == want


@pytest.mark.parametrize('which', ['cold_descriptor','cold_runtime'])
def test_reached_cold_bound_source_remains_unavailable(memory, which):
    memory.set_fields(phase=3,mode=1,travel_start='2030-11-12',travel_end='2030-11-14')
    memory.put(memory.club_data+0x40,packed('2030-11-13'))
    if which=='cold_descriptor':memory.q(memory.national_data+0x38,0)
    else:
        memory.q(memory.national+0x50,memory.competition)
        memory.put(memory.runtime+0x3BE,b'\6')
        memory.q(memory.runtime+0x510,0)
    result=memory.project()
    assert result['state']=='unavailable' and result['national_assignment_gate'] is None and result['return_date'] is None


def test_retained_future_row_baseline_changes_the_gate_without_inline_or_central_query(memory):
    memory.set_fields(phase=3,mode=1,travel_start='2030-11-12',travel_end='2030-11-14')
    memory.q(memory.club_data+0x38,0)
    rows,_=memory.rows(memory.club_data+0x98,[bytes(8)+packed('2030-11-13')+struct.pack('<i',0)+bytes(8)])
    result=memory.project()
    assert result['national_assignment_gate'] is False and result['reason']=='outside_native_assignment_window'
    assert (rows[0]+8,4) in memory.reads


def test_retained_future_earliest_date_first_tie_and_typed_exclusion(memory):
    memory.q(memory.club_data+0x38,0)
    _,_=memory.rows(memory.club_data+0x98,[
        bytes(8)+packed('2030-11-19',0x0200)+struct.pack('<i',0)+bytes(8),
        bytes(8)+packed('2030-11-15',0x0400)+struct.pack('<i',0)+bytes(8),
        bytes(8)+packed('2030-11-15',0x0600)+struct.pack('<i',0)+bytes(8)])
    start=int.from_bytes(packed('2030-11-13'),'little')
    assert source._future_baseline(memory.read,memory.base,memory.club_team,memory.club_data,start)==int.from_bytes(packed('2030-11-15',0x0400),'little')
    memory.put(memory.runtime+0x3BE,b'\x68')
    assert source._future_baseline(memory.read,memory.base,memory.club_team,memory.club_data,start)==source.DEFAULT_DATE


@pytest.mark.parametrize('kind', range(256))
def test_all_runtime_kinds_select_native_bound_source_with_real_typed_inputs(memory, kind):
    memory.q(memory.national+0x50,memory.competition)
    memory.put(memory.runtime+0x3BE,bytes([kind]))
    memory.property_values([(0x44624C6D,1,False)])
    got=source._bound(memory.read,memory.base,memory.national,(2030,317))
    expected='2030-11-18' if kind in (6,10,15,17,19,25,101,102,104) else '2030-11-15'
    assert got==int.from_bytes(packed(expected),'little')


@pytest.mark.parametrize('field', ['root_link','manager_link','context_operand','primary_PERSON_base','PERSON230_cast'])
def test_literal_override_context_and_cast_inputs_are_reread(memory, field):
    memory.set_fields(phase=3,mode=1,travel_start='2030-11-14')
    layout=players.STAFF_RVA if memory.combined else players.RVA
    target={
        'root_link':memory.base+0x56D57D0,
        'manager_link':memory.rule_manager+0x158,
        'context_operand':memory.comp_manager+0x60,
        'primary_PERSON_base':memory.base+layout[0]-0x18,
        'PERSON230_cast':memory.base+layout[2]-0x240}[field]
    count=0
    def changed(address,size):
        nonlocal count
        raw=memory.read(address,size)
        if (address,size)==(target,8):
            count+=1
            if count==2:return bytes([raw[0]^1])+raw[1:]
        return raw
    with pytest.raises(ValueError,match='changed during read'):memory.project(changed)


@pytest.mark.parametrize('field', ['root_type','manager_type','primary_PERSON_base','PERSON230_cast'])
def test_literal_context_and_cast_corruption_refuses_before_result(memory,field):
    memory.set_fields(phase=3,mode=1,travel_start='2030-11-14')
    layout=players.STAFF_RVA if memory.combined else players.RVA
    if field=='root_type':memory.q(memory.rule_manager,memory.base+source.PROVIDER[0])
    if field=='manager_type':memory.q(memory.comp_manager,memory.base+source.PROVIDER[0])
    if field=='primary_PERSON_base':memory.put(memory.base+layout[0]-0x18,struct.pack('<q',0x110))
    if field=='PERSON230_cast':memory.put(memory.base+layout[2]-0x240,struct.pack('<q',-0x110))
    with pytest.raises(ValueError):memory.project()


@pytest.mark.parametrize('which', ['root68','root88','negative','missing'])
def test_retained_future_native_ordinal_table_routes_and_absence(memory,which):
    root,header,vector=memory.tables['competitions']
    if which=='root88':memory.put(memory.base+0x56D34E0,b'\1')
    if which=='missing':memory.q(vector,0)
    value=source._future_competition(memory.read,memory.base,-1 if which=='negative' else 0)
    assert value==(0 if which in ('negative','missing') else memory.competition)


def test_future_wrong_ordinal_is_not_an_unrelated_competition_fallback(memory):
    memory.put(memory.competition+8,struct.pack('<I',1))
    with pytest.raises(ValueError,match='ordinal'):source._future_competition(memory.read,memory.base,0)


def test_native_default_bound_and_baseline_leave_local_dates_unchanged():
    start,end=[int.from_bytes(packed(d),'little') for d in ('2030-11-12','2030-11-14')]
    b=int.from_bytes(packed('2030-11-13'),'little')
    assert source._adjust_dates(source.DEFAULT_DATE,start,end,b)==(start,end)
    assert source._adjust_dates(b,start,end,source.DEFAULT_DATE)==(start,end)
