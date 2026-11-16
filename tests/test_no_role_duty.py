"""No result, description or recorded-data view of the reader names a role duty.

A role in Football Manager 27 has no duty: each phase has its own role and that is all the game
shows. The stored role word also holds internal flag bits, one fixed value per role. Until
15 November 2026 the reader published the game's text for that flag as a `duty`. These tests
hold the public results of the tactics tools, the tool descriptions and the recorded-match
views to carrying neither the key, the word nor the flag's names as values.
"""
import asyncio
import json
import re

import pytest

from fm_live_mcp import current_match_report, prepared_tactic_roles as roles, world
from fm_live_mcp import observed_run_tactical_capture as tactical
from prepared_tactic_formation_fixture import add_formation_context
from prepared_tactic_instruction_fixture import add_instruction_context
from prepared_tactics_fixture import prepared_tactics_memory
from test_bridge import bridge
from test_database import bind, database_memory
from test_live_in_possession_source import context
from test_live_tactical_assignments_source import two_phase
from test_players import memory
from test_teams import team_memory
from test_world import world_memory

FLAG_NAMES = frozenset(text for _bit, _key, text in roles.DUTY_BRANCHES)
ROLE_KEYS = {'raw_encoding', 'compiled_english_name', 'native_resource_key', 'name_state'}
_WORD = re.compile(r'dut(y|ies)', re.IGNORECASE)
_SUFFIX = re.compile(r'\((%s)\)' % '|'.join(sorted(FLAG_NAMES)))
# Wing-Back and Full-Back in possession, as stored: the role bit and flag bit 22.
WING_BACK, FULL_BACK = 0x400008, 0x400004


def duty_mentions(value, path='result'):
    """Every place a result names a duty: a key or a text with the word, a value that is one of
    the internal flag's names, or a role line ending in one. JSON text columns are opened."""
    found = []
    if isinstance(value, dict):
        for key, item in value.items():
            if _WORD.search(str(key)):
                found.append(f'{path}: key {key!r}')
            found += duty_mentions(item, f'{path}.{key}')
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            found += duty_mentions(item, f'{path}[{index}]')
    elif isinstance(value, str):
        if _WORD.search(value) or value in FLAG_NAMES or _SUFFIX.search(value):
            found.append(f'{path}: {value[:80]!r}')
        elif value[:1] in ('[', '{'):
            try:
                found += duty_mentions(json.loads(value), path + '<json>')
            except ValueError:
                pass
    return found


def test_the_check_itself_finds_each_old_form():
    old_role = {'compiled_english_name': 'Full-Back', 'duty': {'name': 'Defend', 'state': 'named'}}
    assert len(duty_mentions(old_role)) == 2
    assert duty_mentions({'unavailable_fields': ['roles', 'duties']})
    assert duty_mentions({'in_possession': ['D(R) Full-Back (Defend)']})
    assert duty_mentions({'phases_json': '{"in_possession":[{"base_role":"Full-Back","duty":"Support"}]}'})
    assert duty_mentions({'limitations': 'Base role names and duties describe the stored position.'})
    # A role whose own name holds such a word is a role name, not a duty.
    assert duty_mentions({'base_role': 'Attacking Midfielder', 'other': 'Covering Centre-Back'}) == []


def test_the_flag_table_keeps_the_name_and_shape_the_tactic_writer_reads():
    assert roles.DUTY_BRANCHES == ((21, 297461, 'Defend'), (25, 297462, 'Stopper'), (26, 297463, 'Cover'),
                                   (22, 297464, 'Support'), (23, 297465, 'Attack'), (34, 300963, 'Automatic'))


@pytest.mark.parametrize('phase', ['in_possession', 'out_of_possession'])
@pytest.mark.parametrize('bit', [bit for bit, _key, _text in roles.DUTY_BRANCHES])
def test_a_decoded_role_word_names_the_role_and_nothing_else(phase, bit):
    word = 1 | (1 << bit)
    result = roles.decode_word(word, phase)
    assert set(result) == ROLE_KEYS and duty_mentions(result) == []
    assert result['compiled_english_name'] == 'Goalkeeper' and result['raw_encoding'] == f'0x{word:016x}'


@pytest.fixture
def composed(bridge, monkeypatch, prepared_tactics_memory):
    m = prepared_tactics_memory
    add_formation_context(m)
    add_instruction_context(m)
    for rva, raw in roles.NATIVE_SPANS:
        m['put'](m['base'] + rva, raw)
    for creator in m['creator_addresses']:
        for offset in (0x120, 0x440):
            for index in range(11):
                m['q'](creator + offset + 0x48 * index + 0x40, WING_BACK if index % 2 else FULL_BACK)
    bind(bridge, monkeypatch, m)
    return m


@pytest.mark.parametrize('include_roles', [False, True])
def test_managed_tactics_result_has_no_duty(bridge, composed, include_roles):
    result = bridge.get_managed_tactics(bridge.session, include_formation=True, include_instructions=True,
                                        include_roles=include_roles)
    assert duty_mentions(result) == []
    assert result['unavailable_fields'][2:4] == (['localized_role_name', 'effective_player_role'] if include_roles
                                                 else ['roles', 'instruction_phase_applicability'])
    if include_roles:
        position = result['slots'][0]['phases']['in_possession']['positions'][1]
        assert position['base_role'] == {'raw_encoding': '0x0000000000400008', 'compiled_english_name': 'Wing-Back',
                                         'native_resource_key': 688080, 'name_state': 'named'}


def test_status_limitations_have_no_duty(bridge):
    assert duty_mentions({'limitations': [line for line in bridge.status()['limitations'] if 'tactic' in line.lower()]}) == []


def _set_roles(c, offset):
    for index in range(11):
        c['memory'].pack(c['creator'] + offset + 0x40 + index * 0x48, '<Q', WING_BACK if index % 2 else FULL_BACK)


def test_in_possession_positions_result_has_no_duty(context):
    from fm_live_mcp import live_in_possession_source as source
    _set_roles(context, 0x120)
    read = world.ReadSet(context['memory'].read)
    result = source.inspect(read, context['base'], context['coach'])
    read.verify()
    assert result['source_state'] == 'available' and duty_mentions(result) == []
    role = result['assignments'][1]['stored_base_role']
    assert set(role) == ROLE_KEYS and role['compiled_english_name'] == 'Wing-Back'


def test_tactical_assignments_result_has_no_duty(two_phase):
    from fm_live_mcp import live_tactical_assignments_source as source
    _set_roles(two_phase, 0x120)
    _set_roles(two_phase, 0x440)
    read = world.ReadSet(two_phase['memory'].read)
    result = source.inspect(read, two_phase['base'], two_phase['coach'], 'both')
    read.verify()
    assert duty_mentions(result) == []
    for phase in result['phases'].values():
        assert all(set(row['stored_base_role']) == ROLE_KEYS for row in phase['assignments'])
    assert result['phases']['in_possession']['assignments'][2]['stored_base_role']['compiled_english_name'] == 'Full-Back'


def _plans():
    """Resident match plans as resident_match_plans.inspect returns them, with decoded role words."""
    sides = []
    for side, team in enumerate((10, 20)):
        flags = (1 << 64) | (1 << 84)
        phases = {name: {'positions': [
            {'position_index': index, 'name': 'D(R)', 'native_mask': 4,
             'stored_base_role': roles.decode_word(WING_BACK if index else FULL_BACK, name)} for index in range(2)]}
            for name in ('in_possession', 'out_of_possession')}
        sides.append({'side_index': side, 'team': {'native_id': team}, 'plan': {
            'name': 'Stored plan', 'mentality': {'native_code': 9, 'name': None, 'state': 'unmapped_native_code'},
            'team_instructions': {'selected_options': [{'native_option_id': 64, 'name': None, 'state': 'no_native_label'}],
                                  'raw_selection_flags_hex': flags.to_bytes(11, 'little').hex(),
                                  'unclassified_selected_bits': [84], 'unmapped_serialized_bits': []},
            'phases': phases}})
    return {'content_sha256': 'a' * 64, 'sides': sides}


def test_current_match_tactics_positions_have_no_duty():
    result = current_match_report._tactics(_plans())
    assert duty_mentions(result) == []
    position = result['sides'][0]['phases']['in_possession'][1]
    assert position == {'slot': 1, 'position': 'D(R)', 'position_mask': 4, 'base_role': 'Wing-Back'}


def test_a_new_recording_does_not_write_the_key(monkeypatch):
    bound = {'current_time_slice': 100, 'official_match_unique_id': 123, 'playback_address': 4000,
             'frame_provider_address': 5000}
    calls = []

    def playback(*args, **kwargs):
        calls.append(1)
        return {'state': 'bound_playback_cursor',
                'bound_playback': {**bound, 'current_time_slice': 100 if len(calls) % 2 else 102}}
    monkeypatch.setattr(tactical.active_match_playback, 'capture', playback)
    monkeypatch.setattr(tactical.resident_match_plans, 'inspect', lambda *args, **kwargs: _plans())
    document = tactical.capture(lambda address, length: bytes(length), 0,
                                {'client': 6000, 'engine': 7000, 'team_indices': [1, 2]}, bound)
    assert document['state'] == 'available' and duty_mentions(document) == []
    for side in document['samples'][0]['sides']:
        for positions in side['phases'].values():
            assert all(set(position) == {'slot', 'position', 'position_mask', 'base_role'} for position in positions)


def _text_without_international_duty(text):
    """International duty (a player away with his national team) is another matter and stays."""
    return re.sub(r'(inter)?national[-_ ]dut(y|ies)|fm_get_player_international_duty', '', text, flags=re.IGNORECASE)


def test_no_tool_description_argument_text_or_server_instruction_names_a_role_duty():
    from fm_live_mcp import server
    tools = asyncio.run(server.mcp.list_tools())
    assert len(tools) > 50 and 'include_roles=true' in server.mcp.instructions
    texts = [('server instructions', server.mcp.instructions)]
    texts += [(tool.name, json.dumps([tool.description, tool.inputSchema])) for tool in tools]
    for name, text in texts:
        text = _text_without_international_duty(text)
        assert not _WORD.search(text), name
        assert not re.search(r'(Wing-Back|Full-Back|Centre Forward|Midfielder) (Defend|Support|Attack)\b', text), name
