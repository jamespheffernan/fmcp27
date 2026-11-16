"""Data Hub analytics: the charts the game's analysts draw (docs/fmdb/UI_FRONTEND.md, "Data Hub analytics").

The Data Hub's team and player blocks bind two keys of TEAM_UI_HANDLER: `TeamAnalytics` ('uvRT')
and `PlayerAnalytics` ('fGjn'). Both are lists of `DataHubVisualisationsReference` records, one per
chart: zone maps (Possession Gained, Possession Lost, Passes attempted, Defensive Actions), scatter
graphs against the division, polygons and set-piece first-contact maps.

Why they read empty before: the server getter takes two object arguments from its context bag (the
fourth argument of server slot 2) and returns an empty list when either is missing:

    'Hhum'  the human manager          (view parameter `human`)
    'mCLv'  the team asking for the report  (view parameter `teamrequestingreport`)

The client's parameter slot (slot 2) is where the game turns those view parameters into the two
data-key arguments; each is a RECORD typed value holding the object's UI id under 'dref'. The view
parameter the earlier sweep saw, `boolean`, is read by the client's get slot and only chooses the
voice of the summary sentences: 1 = "We ... / Our ..." (the viewer's own team), 0 = the team by name.
`PlayerAnalytics` also reads `selectedtabindex`: 0 every chart, 1 goalkeepers, 2 defenders,
3 midfielders, 4 attackers (5 and above answer as 0).

The same two arguments open the rest of the Data Hub: `VisualisationDropDownData` ('FyDK', the
"Ask for" catalogue of a team or of one player; flag argument '1H7p' from view parameter
`isteamvisuals` chooses the team's charts or its players'), `OppositionReportVisuals` ('rijN') and,
on a FIXTURE handler built from a row of the Data Hub's last-match list, the match's pass maps, shot
maps and average-position maps.

`ObjectContextKeyReader` puts the object arguments into the context bag of every server computation
and otherwise reads like `ui_recipes_more.KeyReader`; the game's own client code then unpacks each
chart's observation blob into records. Everything runs shipped code on copied live memory; nothing
is written to the game.
"""
from __future__ import annotations

import struct
import time

from . import ui_params
from .ui_recipes_more import (DATABASE_RECORD, KeyReader, Refs, _vm_and_view, open_handler)
from .ui_recipes_news import place_bag
from .ui_recipes_screens import TYPED_OFFSET
from .ui_vm import fourcc
from .vm import Unavailable, _Stop

TEAM_ANALYTICS, PLAYER_ANALYTICS = 'uvRT', 'fGjn'
HUMAN_ARGUMENT, REPORT_TEAM_ARGUMENT = 'Hhum', 'mCLv'
# view parameter -> the data-key argument client slot 2 writes for it (TEAM_UI_HANDLER, both keys)
OBJECT_ARGUMENTS = {'human': HUMAN_ARGUMENT, 'teamrequestingreport': REPORT_TEAM_ARGUMENT}
VOICE_PARAMETER, TAB_PARAMETER = 'boolean', 'selectedtabindex'
PLAYER_TABS = {'all': 0, 'goalkeepers': 1, 'defenders': 2, 'midfielders': 3, 'attackers': 4}
# The catalogue ("Ask for"): VisualisationDropDownData of a team or a person, a list of groups
# {ObservationsListCategory, ObservationsList}. Client slot 2 also turns view parameter
# `isteamvisuals` into flag argument '1H7p': true = the team's charts, false = its players'.
CATALOGUE, GROUP_NAME = 'FyDK', 'V7CW'
TEAM_VISUALS_PARAMETER, TEAM_VISUALS_ARGUMENT = 'isteamvisuals', '1H7p'
REPORT_VISUALS = 'rijN'              # TEAM OppositionReportVisuals
# Match charts: FIXTURE handler (type 50) built from a row of the Data Hub's last-match list.
MATCH_LIST, FIXTURE_RECORD, FIXTURE_HANDLER = 'GfON', 'ftrf', 50
FIXTURE_HOME, FIXTURE_AWAY, FIXTURE_DATE = 'fhmT', 'fawT', 'fdte'
MATCH_CHARTS = {'action_zones': 'TqMq', 'home_shot_map': 'EHW7', 'away_shot_map': 'k3hM', 'home_pass_map': 'LtKt',
                'away_pass_map': 'UIwU', 'home_average_positions': 'MU5d', 'away_average_positions': 'FOjz'}
MATCH_DEFAULT = ('action_zones', 'home_shot_map', 'away_shot_map', 'xg_story')
# The latest match also has TEAM LastMatchAnalysis ('xlO9', a LastMatchAnalysisVisualsReference; it
# reads screen parameter `id`, and answered the same for every value tried): the analyst's sentence
# on the match, the xG story and the momentum chart.
LAST_MATCH, LAST_MATCH_VALID, LAST_MATCH_SUMMARY, LAST_MATCH_FIXTURE = 'xlO9', '6wOB', 'xMhl', 'zmZa'
LAST_MATCH_CHARTS = {'xg_story': '3yuv', 'momentum': 'XHsY'}
RECORD_TRAITS_OFFSET = 0xB8          # RECORD traits in the typed-value registry (variant.py)
UI_RECORD_TYPE, UI_RECORD_REFERENCE = '110 ', 'dref'

# DataHubVisualisationsReference and the observation records it carries (front-end record schemas
# q7pH, zi2R, IHFl, WpNP, A94L; ui_frontend.json.gz).
OBSERVATION, CATEGORY, SUB_CATEGORY, ANALYST = '0Zoa', 'vj3R', 'L9Nj', 'nLdp'
NAME, SUMMARY, SUMMARY_EXTENDED, SUMMARY_STATE = '7ddJ', 'xMhl', 'OBcC', 'wjEU'
TIME_FRAME, COMPETITION, SUBJECT, PIN_DATA = 'tDch', 'comp', 'BmeB', 'kCGC'
PRISM_ID, PINNED, PREFERRED = 'CpVd', '8wVs', 'FM3F'
ZONES, ZONE_VALUE, ZONE_INTENSITY, BAR_MAX = 'UZlS', '1gpM', 'pyZE', 'tzwN'
POINTS, POINT, POINT_X, POINT_Y, POINT_TEAM, POINT_PLAYER = 'Ywr3', 'YYiF', 'H gt', 'dEkT', 'Team', 'plyr'
X_AXIS, Y_AXIS, QUADRANTS = 'mEuQ', '8DzB', 'bMU2'
AXIS = {'label': '7gZ2', 'short_label': '8pCM', 'min': 'NewX', 'max': 'tYLv', 'mean': 'uQqV'}
QUADRANT = {'zone': 'Ng8F', 'label_first': '0yQ1', 'label_second': 'lhOD', 'performance_type': '9r2h'}
POLYGON_POINTS, POLYGON_REASON = 'VpLh', 'CCgd'
POLYGON_POINT = {'label': '7gZ2', 'short_label': '8pCM', 'value': '1gpM', 'comparison': 'ZtAj',
                 'min': 'NewX', 'max': 'tYLv', 'lower_is_better': 'Obqu'}

FIRST_CONTACT_ZONES = ('near_post', 'centre', 'far_post')
ZONE_MAP_LAYOUT = (
    'Six columns along the length of the pitch. Column 1 is the end the team defends and column 6 the '
    "opposition's end: the view lays the list out left to right in its six-column template, and the game's "
    'own sentences name column 1 "our penalty area" and column 6 "the opposition\'s penalty area". '
    'percent is the share of the team\'s events in that column (the six add up to 100); intensity is the '
    'bar level the game draws (1 to 7). The width of a column is not read: two columns to a third is an '
    'approximation, not a boundary the game states.')
FIRST_CONTACT_LAYOUT = (
    'Three zones across the box in the order near post, centre, far post (both charts\' sentences give '
    'the three percentages in that order). percent is the share of first contacts won.')
LIMITS = (
    'The charts are the ones the game holds for this team now: the time frame and competition each chart '
    'names (this season, the league), not a chosen match.',
    'A team other than the managed one answers with the shorter set its opposition report holds.',
    'summary_state is the game\'s own number for the summary (seen 1 to 4); its wording is not decoded.',
)


def record_value(vm, fields: dict) -> int:
    """A RECORD typed value on the VM heap: {key: int32} entries, sorted by key."""
    entries = b''
    for key, value in sorted((fourcc(k), v) for k, v in fields.items()):
        typed = vm.heap_bytes(struct.pack('<QQ', vm.registry + TYPED_OFFSET['int'], value & 0xFFFFFFFF))
        entries += struct.pack('<I4xQ', key, typed)
    begin = vm.heap_bytes(entries, 8)
    vector = vm.heap_bytes(struct.pack('<QQQ', begin, begin + len(entries), begin + len(entries)))
    return vm.heap_bytes(struct.pack('<QQ', vm.registry + RECORD_TRAITS_OFFSET, vector))


def object_bag(vm, objects: dict) -> int:
    """A context bag for server slot 2: {data key: UI object id} as references, {data key: bool} as flags."""
    entries = []
    for key, value in sorted(objects.items(), key=lambda item: fourcc(item[0])):
        if isinstance(value, bool):
            entries.append((key, vm.heap_bytes(struct.pack('<QQ', vm.registry + TYPED_OFFSET['bool'], int(value)))))
        else:
            entries.append((key, record_value(vm, {UI_RECORD_TYPE: DATABASE_RECORD, UI_RECORD_REFERENCE: value})))
    return place_bag(vm, entries)


class ObjectContextKeyReader(KeyReader):
    """KeyReader whose server computations receive object arguments in their context bag.

    `objects` = {data key: UI object id, or a bool for a flag argument}. Only computations the client declares without its own
    parameter bag get the bag; one with a declared bag keeps the client's."""

    def __init__(self, vm, handler, registry=None, objects=None):
        super().__init__(vm, handler, registry)
        self.objects = {str(key): value if isinstance(value, bool) else int(value)
                        for key, value in (objects or {}).items()}

    def fetch(self, key, context=0):
        if context or not self.objects:
            return super().fetch(key, context)
        if key in self.data:
            return self.data[key]
        vm = self.vm
        started, rng = time.perf_counter(), vm.rng_uses
        pinned = vm._baseline
        try:
            vm._restore()
            bag = object_bag(vm, self.objects)
            vm.commit()
            _, address, _ = vm.server_value(self.handler, key, context=bag)
            vm.commit()
            result = address
        except _Stop as stop:
            trace = vm.backtrace()
            vm._baseline = pinned
            vm._restore()
            result = Unavailable(f'server key {key}: {stop.reason}',
                                 detail=f'{stop.detail or ""} [{" < ".join(trace)}]')
        self.data[key] = result
        self.data_seconds[key] = time.perf_counter() - started
        self.rng_by_data[key] = vm.rng_uses - rng
        return result


def read_key(vm, view, record: dict, key: str, *, params=None, flags=None, handler_type=DATABASE_RECORD,
             inputs=False):
    """One key as a Data Hub view asks for it: the manager and the managed team in the server
    context, `flags` as further flag arguments, `params` {screen parameter name: int} for the
    client's get slot. Returns the KeyReading."""
    base = open_handler(vm, handler_type, record, inputs=inputs)
    reader = ObjectContextKeyReader(vm, base.handler, base.registry, {
        HUMAN_ARGUMENT: view.person_id, REPORT_TEAM_ARGUMENT: view.team_id, **(flags or {})})
    reader.inputs = inputs
    return reader.get(key, params={ui_params.rva_of(name): int(value) for name, value in (params or {}).items()} or None)


def read_analytics(vm, view, team_id: int, key: str, *, tab: int = 0):
    """One analytics key of a team as the Data Hub asks for it: (KeyReading, voice flag)."""
    own = team_id == view.team_id
    params = {VOICE_PARAMETER: int(own), **({TAB_PARAMETER: int(tab)} if key == PLAYER_ANALYTICS else {})}
    return read_key(vm, view, view.record(dref=team_id), key, params=params), own


# ---------------------------------------------------------------------- shaping
def _number(value, digits=2):
    return round(value, digits) if isinstance(value, float) else value


def _kind(observation: dict) -> str:
    prism = (observation.get(PIN_DATA) or {}).get(PRISM_ID) or ''
    parts = prism.split('-')
    if len(parts) > 2 and parts[1]:
        return parts[1]
    if ZONES in observation:
        return 'zone_map' if BAR_MAX in observation else 'first_contact_zone_map'
    if POINTS in observation:
        return 'scatter_graph'
    return 'polygon' if POLYGON_POINTS in observation else 'unknown'


def _head(item: dict) -> dict:
    observation = item.get(OBSERVATION) if isinstance(item.get(OBSERVATION), dict) else {}
    pin = observation.get(PIN_DATA) or {}
    return {'name': observation.get(NAME), 'kind': _kind(observation), 'prism_id': pin.get(PRISM_ID),
            'category': item.get(CATEGORY), 'sub_category': item.get(SUB_CATEGORY)}


def _picked(mapping: dict, record: dict) -> dict:
    return {name: _number(record.get(code)) for name, code in mapping.items() if code in record}


def shape_chart(item: dict, refs) -> dict:
    """One DataHubVisualisationsReference record as a named chart."""
    observation = item.get(OBSERVATION) if isinstance(item.get(OBSERVATION), dict) else {}
    pin = observation.get(PIN_DATA) or {}
    out = _head(item)
    out.update({'time_frame': observation.get(TIME_FRAME), 'competition': refs.ref(observation.get(COMPETITION)),
                'summary': observation.get(SUMMARY), 'summary_extended': observation.get(SUMMARY_EXTENDED),
                'summary_state': observation.get(SUMMARY_STATE),
                'pinned': pin.get(PINNED), 'preferred': pin.get(PREFERRED), 'analyst': refs.ref(item.get(ANALYST))})
    zones = observation.get(ZONES)
    if isinstance(zones, list):
        if out['kind'] == 'first_contact_zone_map' and len(zones) == len(FIRST_CONTACT_ZONES):
            out['zones'] = [{'zone': name, 'percent': _number(zone.get(ZONE_VALUE)), 'intensity': zone.get(ZONE_INTENSITY)}
                            for name, zone in zip(FIRST_CONTACT_ZONES, zones)]
        else:
            out['zones'] = [{'column': index, 'percent': _number(zone.get(ZONE_VALUE)), 'intensity': zone.get(ZONE_INTENSITY)}
                            for index, zone in enumerate(zones, 1)]
        if BAR_MAX in observation:
            out['bar_max_percent'] = _number(observation[BAR_MAX])
    points = observation.get(POINTS)
    if isinstance(points, list):
        out['x_axis'], out['y_axis'] = _picked(AXIS, observation.get(X_AXIS) or {}), _picked(AXIS, observation.get(Y_AXIS) or {})
        out['quadrants'] = [_picked(QUADRANT, row) for row in observation.get(QUADRANTS) or [] if isinstance(row, dict)]
        rows = []
        for row in points:
            data = row.get(POINT) or {}
            who = row.get(POINT_PLAYER) or row.get(POINT_TEAM)
            rows.append({'subject': refs.ref(who) if who else None, 'x': _number(data.get(POINT_X), 3),
                         'y': _number(data.get(POINT_Y), 3)})
        out['points'] = rows
    data_points = observation.get(POLYGON_POINTS)
    if isinstance(data_points, list):
        out['subject'] = refs.ref(observation.get(SUBJECT))
        out['performance_reason_value'] = observation.get(POLYGON_REASON)
        out['data_points'] = [_picked(POLYGON_POINT, row) for row in data_points if isinstance(row, dict)]
    return out


def _matches(head: dict, words: list) -> bool:
    text = f"{head.get('name') or ''} {head.get('prism_id') or ''} {head.get('kind') or ''}".lower().replace('_', ' ')
    return all(word in text for word in words)


def select(items: list, chart, default_kinds) -> list:
    """Indexes of the charts to return in full: `chart` None -> those of `default_kinds`; 'all' ->
    every chart; other text -> charts whose name, kind or prism id holds every word."""
    heads = [_head(item) for item in items]
    if chart is None:
        return [i for i, head in enumerate(heads) if head['kind'] in default_kinds]
    words = str(chart).lower().replace('_', ' ').split()
    if words == ['all']:
        return list(range(len(items)))
    exact = [i for i, head in enumerate(heads) if (head.get('name') or '').lower() == ' '.join(words)]
    chosen = exact or [i for i, head in enumerate(heads) if _matches(head, words)]
    if not chosen:
        raise ValueError(f'no chart matches {chart!r}; charts: ' + ', '.join(sorted(
            str(head['name']) for head in heads if head.get('name'))))
    return chosen


def find_charts(value, group=None) -> list:
    """[(group name or None, chart record)] for every DataHubVisualisationsReference nested in a value
    (the catalogue groups its charts under `ObservationsListCategory`)."""
    out = []
    if isinstance(value, dict):
        if isinstance(value.get(OBSERVATION), dict):
            return [(group, value)]
        group = value.get(GROUP_NAME, group)
        for item in value.values():
            out += find_charts(item, group)
    elif isinstance(value, list):
        for item in value:
            out += find_charts(item, group)
    return out


def labelled(value, refs, labels, depth=0):
    """Any record keyed by the game's property labels: references named, numbers rounded, colours
    dropped, values the reader cannot decode left out."""
    if isinstance(value, dict):
        if UI_RECORD_REFERENCE in value and set(value) <= {UI_RECORD_TYPE, UI_RECORD_REFERENCE}:
            return refs.ref(value)
        if 'unavailable' in value or set(value) == {'a', 'r', 'g', 'b'}:
            return None
        out = {}
        for key, item in value.items():
            shown = labelled(item, refs, labels, depth + 1) if depth < 8 else None
            if shown is not None and shown != [] and shown != {}:
                out[labels.get(key, key)] = shown
        return out
    if isinstance(value, list):
        return [labelled(item, refs, labels, depth + 1) for item in value]
    return _number(value, 3)


def _answer(vm, started, rng0, **fields) -> dict:
    return {**fields, 'limits': list(LIMITS), 'seconds': round(time.perf_counter() - started, 3),
            'rng_uses': vm.rng_uses - rng0}


def _chart_screen(vm_or_session, name, key, *, subject, record_of, chart, default_kinds=(), params=None, flags=None,
                  coach=0) -> dict:
    """Read one chart-list key and shape it. `subject`: UI id or None; `record_of(view, subject)` gives
    (handler record, subject id, voice flag)."""
    vm, view = _vm_and_view(vm_or_session, coach)
    started, rng0 = time.perf_counter(), vm.rng_uses
    record, subject_id, own = record_of(vm, view, subject)
    params = {VOICE_PARAMETER: int(own), **(params or {})}
    reading = read_key(vm, view, record, key, params=params, flags=flags)
    recipe = {'record': {UI_RECORD_REFERENCE: subject_id}, 'key': key, 'params': params,
              'context_objects': {HUMAN_ARGUMENT: view.person_id, REPORT_TEAM_ARGUMENT: view.team_id, **(flags or {})}}
    out = {'screen': name, 'recipe': recipe, 'voice': 'first person (the managed team)' if own else 'team by name'}
    if isinstance(reading.value, Unavailable):
        return _answer(vm, started, rng0, **out, state='unavailable', unavailable=reading.value.reason,
                       detail=str(reading.value.detail or '')[:400])
    found = find_charts(reading.json_value() or [])
    items = [item for _group, item in found]
    chosen = set(select(items, chart, default_kinds)) if items else set()
    refs = Refs(vm)
    charts = [{**({'group': group} if group else {}), **shape_chart(item, refs)}
              for index, (group, item) in enumerate(found) if index in chosen]
    others = [{**({'group': group} if group else {}), **{k: v for k, v in _head(item).items() if k in ('name', 'kind', 'prism_id')}}
              for index, (group, item) in enumerate(found) if index not in chosen]
    kinds = {row['kind'] for row in charts}
    return _answer(vm, started, rng0, **out, subject=refs.ref(subject_id), state='available' if items else 'no_charts',
                   chart_count=len(items), charts=charts, other_charts=others,
                   layout={kind: text for kind, text in (('zone_map', ZONE_MAP_LAYOUT),
                                                         ('first_contact_zone_map', FIRST_CONTACT_LAYOUT)) if kind in kinds})


def _team_record(vm, view, team):
    team_id = view.team_id if team is None else int(team)
    return view.record(dref=team_id), team_id, team_id == view.team_id


def _person_record(vm, view, person):
    if person is None:
        from .ui_recipes_round2 import squad_people
        person = squad_people(vm, view, 1)[0]
    return view.record(dref=int(person)), int(person), True


def team_analytics(vm_or_session, *, team=None, chart=None, coach=0) -> dict:
    """The Data Hub's team charts. `chart`: None = the zone maps in full and the names of the rest;
    'all' = every chart in full; other text = the charts whose name, kind or prism id holds every
    word ('possession gained', 'zone map', 'scatter passing'). `team`: TEAM UI id (default: the
    managed team)."""
    out = _chart_screen(vm_or_session, 'team_analytics', TEAM_ANALYTICS, subject=team, record_of=_team_record,
                        chart=chart, default_kinds=('zone_map', 'first_contact_zone_map'), coach=coach)
    out['team'] = out.pop('subject', None)
    return out


def player_analytics(vm_or_session, *, team=None, chart=None, coach=0) -> dict:
    """Every player chart the Data Hub offers for the squad ("Ask for"): scatter graphs of the
    players against their position in the division, in the game's groups (General, Defensive,
    Creating, Scoring, Possession, Goal Keeping). `on_data_hub` marks the ones the analyst has put
    on the Data Hub's player block. `chart` as in team_analytics (None = names only)."""
    out = _chart_screen(vm_or_session, 'player_analytics', CATALOGUE, subject=team, record_of=_team_record, chart=chart,
                        params={TEAM_VISUALS_PARAMETER: 0}, flags={TEAM_VISUALS_ARGUMENT: False}, coach=coach)
    out['team'] = out.pop('subject', None)
    if out.get('state') == 'available':
        vm, view = _vm_and_view(vm_or_session, coach)
        shown, _own = read_analytics(vm, view, out['team']['id'] if out['team'] else view.team_id, PLAYER_ANALYTICS)
        names = {_head(item)['name'] for _g, item in find_charts(shown.json_value() or [])} \
            if not isinstance(shown.value, Unavailable) else set()
        for row in out['charts'] + out['other_charts']:
            row['on_data_hub'] = row['name'] in names
    return out


def person_analytics(vm_or_session, *, person=None, chart=None, coach=0) -> dict:
    """One player's own charts (the Analytics the player's profile offers): polygons against his
    position and scatter graphs placing him among the division's players. `person`: PERSON UI id
    (default: the first player of the managed squad). `chart` None = the polygons in full."""
    out = _chart_screen(vm_or_session, 'person_analytics', CATALOGUE, subject=person, record_of=_person_record,
                        chart=chart, default_kinds=('polygon',), coach=coach)
    out['person'] = out.pop('subject', None)
    return out


def opposition_analytics(vm_or_session, *, team=None, chart=None, coach=0) -> dict:
    """The charts of a team's report (the opposition report's key findings: the team's general
    polygon and its standout players). `team`: TEAM UI id (default: the managed team's own)."""
    out = _chart_screen(vm_or_session, 'opposition_analytics', REPORT_VISUALS, subject=team, record_of=_team_record,
                        chart=chart if chart is not None else 'all', coach=coach)
    out['team'] = out.pop('subject', None)
    return out


def match_analytics(vm_or_session, *, match=1, chart=None, coach=0) -> dict:
    """The match charts of one of the Data Hub's recent matches (`match` 1 = the latest of its
    last-match list): action zones, each side's shot map by location with expected goals, pass map
    and average positions (all, in possession, out of possession); for the latest match also the
    analyst's sentence, the xG story (each shot's time, expected goals and the score) and the
    momentum chart. `chart`: None = action zones, shot maps and the xG story in full; 'all'; or
    words of a chart's name ('pass map', 'away average', 'momentum')."""
    from . import ui_frontend, variant
    vm, view = _vm_and_view(vm_or_session, coach)
    started, rng0 = time.perf_counter(), vm.rng_uses
    listing = read_key(vm, view, view.record(dref=view.team_id), MATCH_LIST)
    rows = [row[FIXTURE_RECORD] for row in (listing.json_value() or []) if isinstance(row, dict)
            and isinstance(row.get(FIXTURE_RECORD), dict)] if not isinstance(listing.value, Unavailable) else []
    out = {'screen': 'match_analytics'}
    if not rows:
        return _answer(vm, started, rng0, **out, state='no_matches', matches=[])
    if not 1 <= int(match) <= len(rows):
        raise ValueError(f'match {match} is not one of the {len(rows)} recent matches (1 = the latest)')
    fixture = rows[int(match) - 1]
    last = {}
    if int(match) == 1:
        analysis = read_key(vm, view, view.record(dref=view.team_id), LAST_MATCH, params={'id': 0})
        value = analysis.json_value() if not isinstance(analysis.value, Unavailable) else None
        about = ((value or {}).get(LAST_MATCH_CHARTS['xg_story']) or {}).get(LAST_MATCH_FIXTURE) or {}
        # published only when the analysis names the same two teams and date as the list's first row
        if isinstance(value, dict) and value.get(LAST_MATCH_VALID) and all(
                about.get(key) == fixture.get(key) for key in (FIXTURE_HOME, FIXTURE_AWAY, FIXTURE_DATE)):
            last = value
    available = list(MATCH_CHARTS) + [name for name, code in LAST_MATCH_CHARTS.items() if last.get(code)]
    wanted = list(available) if chart is None or str(chart).lower().strip() == 'all' else [
        name for name in available if all(word in name.replace('_', ' ') for word in str(chart).lower().replace('_', ' ').split())]
    if chart is None:
        wanted = [name for name in wanted if name in MATCH_DEFAULT]
    if not wanted:
        raise ValueError(f'no match chart matches {chart!r}; charts: ' + ', '.join(available))
    record = view.record(**{key: value for key, value in fixture.items() if key != UI_RECORD_TYPE and isinstance(value, int)})
    base = open_handler(vm, FIXTURE_HANDLER, record, inputs=True)
    reader = ObjectContextKeyReader(vm, base.handler, base.registry,
                                    {HUMAN_ARGUMENT: view.person_id, REPORT_TEAM_ARGUMENT: view.team_id})
    readings = {name: reader.get(MATCH_CHARTS[name]) for name in wanted if name in MATCH_CHARTS}
    refs = Refs(vm)
    labels = ui_frontend.table().get('registry') or {}

    def described(row):
        date = variant.si_date(row.get(FIXTURE_DATE, 0))
        return {'home': refs.ref(row.get(FIXTURE_HOME)), 'away': refs.ref(row.get(FIXTURE_AWAY)),
                'date': getattr(date, 'iso', None)}
    charts, failed = {}, {}
    for name, reading in readings.items():
        if isinstance(reading.value, Unavailable):
            failed[name] = reading.value.reason
        elif reading.status == 'value':
            charts[name] = labelled(reading.json_value(), refs, labels)
    for name, code in LAST_MATCH_CHARTS.items():
        if name in wanted:
            charts[name] = labelled(last[code], refs, labels)
    return _answer(vm, started, rng0, **out, state='available' if charts else 'no_charts', match=described(fixture),
                   matches=[{'match': index, **described(row)} for index, row in enumerate(rows, 1)],
                   summary=last.get(LAST_MATCH_SUMMARY), charts=charts, unavailable=failed,
                   other_charts=[name for name in available if name not in wanted],
                   coordinates='AveragePosition XaxisData runs across the pitch and YaxisData along it, in the match '
                               'record\'s native units centred on 0. The game turns both sides the same way for this '
                               'map: each defends the negative YaxisData end in both halves (on the match read on '
                               '13 November 2026 both goalkeepers averaged -40 to -45).')


SCREENS = {'team_analytics': team_analytics, 'player_analytics': player_analytics, 'person_analytics': person_analytics,
           'opposition_analytics': opposition_analytics, 'match_analytics': match_analytics}

__all__ = ['SCREENS', 'team_analytics', 'player_analytics', 'person_analytics', 'opposition_analytics', 'match_analytics',
           'ObjectContextKeyReader', 'object_bag', 'record_value', 'read_key', 'read_analytics', 'shape_chart', 'select',
           'find_charts', 'labelled', 'OBJECT_ARGUMENTS']
