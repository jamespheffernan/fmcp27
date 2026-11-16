"""Data Hub analytics: chart shaping and selection on charts read from a live save (offline) and the
object-argument reader's contract. The live read is tests/test_fmdb_ui_analytics_live.py."""
import json
import struct
from pathlib import Path

import pytest

from fm_live_mcp.fmdb import ui_recipes_analytics as A

FIXTURE = Path(__file__).parent / 'fixtures' / 'team_analytics_newcastle_2031_01_05.json'


class Refs:
    def ref(self, value):
        target = value.get('dref') if isinstance(value, dict) else value
        return {'id': target} if target is not None else None


def items():
    return json.loads(FIXTURE.read_text())['items']


def test_zone_maps_keep_the_games_columns_and_sentences():
    charts = [A.shape_chart(item, Refs()) for item in items()]
    gained, lost, first_contact = charts[0], charts[1], charts[2]
    assert (gained['name'], gained['kind'], gained['prism_id']) == (
        'Possession Gained', 'zone_map', 'team-zone_map-possession_gains-seasonal-')
    assert [z['column'] for z in gained['zones']] == [1, 2, 3, 4, 5, 6]
    assert [z['percent'] for z in gained['zones']] == [34.21, 20.89, 23.12, 12.56, 7.81, 1.41]
    assert [z['intensity'] for z in gained['zones']] == [7, 4, 5, 2, 1, 1] and gained['bar_max_percent'] == 34.21
    assert abs(sum(z['percent'] for z in gained['zones']) - 100) < 0.05
    assert abs(sum(z['percent'] for z in lost['zones']) - 100) < 0.05
    # The game's own sentences fix the direction: the fullest column of each chart is the end it names.
    assert max(gained['zones'], key=lambda z: z['percent'])['column'] == 1 and 'around our penalty area' in gained['summary_extended']
    assert max(lost['zones'], key=lambda z: z['percent'])['column'] == 6
    assert "around the opposition's penalty area" in lost['summary_extended']
    assert gained['time_frame'] == 'This Season' and gained['competition'] == {'id': 419430407} and gained['summary_state'] == 2
    # first contacts: near post, centre, far post, as the chart's sentence orders its three percentages
    assert [z['zone'] for z in first_contact['zones']] == ['near_post', 'centre', 'far_post']
    assert [round(z['percent']) for z in first_contact['zones']] == [86, 100, 97]
    assert 'centre of the box is 100%, compared to 86% at the near post, and 97% at the far post' in first_contact['summary_extended']
    assert 'bar_max_percent' not in first_contact


def test_scatter_and_polygon_charts():
    charts = [A.shape_chart(item, Refs()) for item in items()]
    scatter, polygon = charts[3], charts[4]
    assert scatter['kind'] == 'scatter_graph' and scatter['name'] == 'Possession'
    assert scatter['x_axis']['label'] == 'Possession Lost per Game' and scatter['y_axis']['label'] == 'Possession Won per Game'
    assert scatter['x_axis']['min'] < scatter['x_axis']['mean'] < scatter['x_axis']['max']
    assert len(scatter['quadrants']) == 4 and scatter['quadrants'][1]['label_first'] == 'Frequently wins ball'
    assert scatter['points'][0] == {'subject': {'id': 402653644}, 'x': 87.095, 'y': 76.19}
    assert polygon['kind'] == 'polygon' and polygon['name'] == 'General Performance' and polygon['subject'] == {'id': 402653729}
    first = polygon['data_points'][0]
    assert first['label'] == 'Goals per Game' and first['lower_is_better'] is False and first['min'] < first['value'] < first['max']
    assert any(p['lower_is_better'] for p in polygon['data_points'])


def test_chart_selection():
    rows = items()
    assert A.select(rows, None, ('zone_map', 'first_contact_zone_map')) == [0, 1, 2]
    assert A.select(rows, 'all', ()) == [0, 1, 2, 3, 4]
    assert A.select(rows, 'possession gained', ()) == [0] and A.select(rows, 'Possession', ()) == [3]   # exact name first
    assert A.select(rows, 'possession zone', ()) == [0, 1] and A.select(rows, 'zone_map', ()) == [0, 1, 2]
    assert A.select(rows, 'scatter possession', ()) == [3] and A.select(rows, 'polygon', ()) == [4]
    with pytest.raises(ValueError, match='no chart matches .*Possession Gained'):
        A.select(rows, 'expected goals', ())


def test_record_value_and_object_bag_layout():
    """RECORD typed value: {registry + 0xB8, vector of {key, int32 typed*}}; bag entries sorted by key."""
    class VM:
        registry = 0x7000_0000_0000

        def __init__(self):
            self.heap, self.top = {}, 0x1000

        def heap_bytes(self, data, align=16):
            at = self.top
            self.heap[at] = bytes(data)
            self.top += (len(data) + 15) // 16 * 16
            return at

    vm = VM()
    typed = A.record_value(vm, {'dref': 0x18000221, '110 ': 28})
    traits, vector = struct.unpack('<QQ', vm.heap[typed])
    assert traits == vm.registry + 0xB8
    begin, end, cap = struct.unpack('<QQQ', vm.heap[vector])
    assert end - begin == 32 and cap == end
    entries = [struct.unpack_from('<I4xQ', vm.heap[begin], at) for at in (0, 16)]
    keys = [key for key, _ in entries]
    assert keys == sorted(keys) and set(keys) == {struct.unpack('>I', b'dref')[0], struct.unpack('>I', b'110 ')[0]}
    values = {key: struct.unpack('<QQ', vm.heap[pointer]) for key, pointer in entries}
    assert values[struct.unpack('>I', b'dref')[0]] == (vm.registry + 0x28, 0x18000221)
    assert A.OBJECT_ARGUMENTS == {'human': 'Hhum', 'teamrequestingreport': 'mCLv'}


def test_fm_ui_read_names_a_record_handler_by_class_and_takes_context():
    from fm_live_mcp.fmdb import ui_tools

    class Reg:
        types = {114: {'client': 'TEAM_CONFIDENCE_UI_HANDLER'}}
        classes = {'TEAM_UI_HANDLER': object(), 'TEAM_CONFIDENCE_UI_HANDLER': object()}

        def type_of(self, name):
            return {'TEAM_CONFIDENCE_UI_HANDLER': 114}.get(name)

    number, row = ui_tools.resolve_handler(Reg(), 'TEAM_UI_HANDLER')
    assert number == 28 and row == {'client': 'TEAM_UI_HANDLER', 'server': None, 'record_class': True}
    assert ui_tools.resolve_handler(Reg(), 'team')[0] == 28 and ui_tools.resolve_handler(Reg(), 'TEAM_CONFIDENCE')[0] == 114
    with pytest.raises(ui_tools.UiToolError, match='no buildable handler type'):
        ui_tools.resolve_handler(Reg(), 'NO_SUCH')
    assert ui_tools.normalize_record({'Hhum': 'managed_manager', 'mCLv': 'managed_team'}) == {
        'Hhum': 'managed_manager', 'mCLv': 'managed_team'}


def test_catalogue_groups_and_labelled_records():
    rows = items()
    catalogue = [{'V7CW': 'Possession', '0Hsw': rows[:2]}, {'V7CW': 'General', '0Hsw': [rows[4]]}]
    found = A.find_charts(catalogue)
    assert [(group, item['0Zoa']['7ddJ']) for group, item in found] == [
        ('Possession', 'Possession Gained'), ('Possession', 'Possession Lost'), ('General', 'General Performance')]
    assert [group for group, _item in A.find_charts(rows)] == [None] * 5
    # a match chart keeps the game's labels: references named, colours and undecoded values dropped
    labels = {'plyr': 'Player', 'p2AO': 'AveragePosition', 'mEuQ': 'XaxisData', '8DzB': 'YaxisData', 'rTx6': 'IconBackgroundColour',
              'fdte': 'FixtureDate', 'Psnu': 'SquadNumber', 'dNtn': 'CombinedPlayerData'}
    raw = {'dNtn': [{'plyr': {'110 ': 28, 'dref': 7}, 'Psnu': 13, 'rTx6': {'a': 255, 'r': 1, 'g': 2, 'b': 3},
                     'p2AO': {'mEuQ': 0.34972247, '8DzB': -39.668503}, 'fdte': {'unavailable': 'variant kind 27', 'raw': '00'}}],
           'ZZZZ': 4}
    assert A.labelled(raw, Refs(), labels) == {'CombinedPlayerData': [{'Player': {'id': 7}, 'SquadNumber': 13,
                                               'AveragePosition': {'XaxisData': 0.35, 'YaxisData': -39.669}}], 'ZZZZ': 4}
    assert set(A.SCREENS) == {'team_analytics', 'player_analytics', 'person_analytics', 'opposition_analytics', 'match_analytics'}
    assert set(A.MATCH_DEFAULT) < set(A.MATCH_CHARTS) | set(A.LAST_MATCH_CHARTS)


def test_context_bag_carries_flags_beside_objects(monkeypatch):
    placed = {}
    monkeypatch.setattr(A, 'place_bag', lambda vm, entries: placed.setdefault('entries', entries) and 1)

    class VM:
        registry = 0x7000_0000_0000

        def __init__(self):
            self.heap, self.top = {}, 0x1000

        def heap_bytes(self, data, align=16):
            at = self.top
            self.heap[at] = bytes(data)
            self.top += (len(data) + 15) // 16 * 16
            return at

    vm = VM()
    A.object_bag(vm, {'mCLv': 0x18000221, 'Hhum': 0x0101AC65, '1H7p': True})
    keys = [key for key, _typed in placed['entries']]
    assert sorted(keys, key=lambda k: struct.unpack('>I', k.encode())[0]) == keys and set(keys) == {'1H7p', 'Hhum', 'mCLv'}
    typed = dict(placed['entries'])
    assert struct.unpack('<QQ', vm.heap[typed['1H7p']]) == (vm.registry + 0x18, 1)          # bool traits
    assert struct.unpack('<QQ', vm.heap[typed['Hhum']])[0] == vm.registry + 0xB8            # RECORD traits
