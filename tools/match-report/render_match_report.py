#!/usr/bin/env python3
"""Render one checked retained match as an offline, self-contained report.

No process attachment, network, game code or save reads. Source JSON is supplied
explicitly; identity/reconciliation failures stop rendering.
"""
from __future__ import annotations
import argparse
import base64
import gzip
import hashlib
from html import escape
import json
import math
from pathlib import Path

HERE = Path(__file__).resolve().parent
METRICS = ('minutes', 'match_rating', 'goals', 'assists', 'shots', 'shots_on_target',
           'expected_goals', 'expected_assists', 'passes_attempted', 'passes_completed',
           'key_passes', 'open_play_key_passes', 'chances_created', 'progressive_passes', 'dribbles_made',
           'tackles_attempted', 'tackles_completed', 'interceptions', 'clearances',
           'possession_won', 'possession_lost', 'pressures_attempted', 'pressures_completed',
           'pressure_completion_percentage_computed', 'crosses_attempted',
           'crosses_completed', 'aerial_duels_attempted', 'aerial_duels_completed',
           'saves_held', 'saves_parried', 'saves_tipped', 'total_saves',
           'open_play_crosses_attempted', 'open_play_crosses_completed', 'fouls_committed',
           'yellow_cards_received', 'red_cards_received', 'direct_free_kick_goals')


def load(path: Path, role: str):
    if isinstance(path, tuple):
        value, provenance = path
        return value, {**provenance, 'role': role}
    raw = path.read_bytes()
    value = json.loads(raw)
    return value, {'role': role, 'file': path.name, 'source_path': str(path.resolve()),
                   'sha256': hashlib.sha256(raw).hexdigest(), 'bytes': len(raw)}


def finite(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def prepare(postgame: Path, passes: Path, averages: Path, heatmaps: Path, halves: Path | None, pass_attempts: Path | None = None, orientation_proof: Path | None = None):
    inputs = [load(p, role) for p, role in ((postgame, 'Retained fixture, team and player totals'),
              (passes, 'Named directed pass edges'), (averages, 'Named official stored average positions'),
              (heatmaps, 'Retained positional grid'))]
    (post, edges, avg, heat) = [x[0] for x in inputs]
    half = None
    if halves is not None:
        half, half_manifest = load(halves, "Retrospective native-period shot split")
        inputs.append((half, half_manifest))
    manifest = [x[1] for x in inputs]
    if post.get('errors'):
        raise ValueError('Retained capture contains errors')
    record = post['shots']['records'][0]
    fixture = record['fixture']
    key = record['native_match_key']
    if not all(x == key for x in (edges['native_match_key'], avg['fixture_key'], heat['native_match_key'], half['native_match_key'] if half else key)):
        raise ValueError('Report sources refer to different match keys')
    if half is not None and half['state'] != 'verified_retrospective_cross_observation':
        raise ValueError('A checked retrospective half split is required')
    if fixture['scores']['final_score'] != edges['fixture']['scores']['final_score']:
        raise ValueError('Fixture score disagrees between sources')
    teams = [{'side_index': i, 'native_id': fixture[k]['native_id'],
              'name': fixture[k]['owner']['name'], 'short_name': fixture[k]['owner']['short_name']}
             for i, k in enumerate(('home_team', 'away_team'))]
    geometry = record['pitch_geometry']
    if not all(finite(geometry[k]) and geometry[k] > 0 for k in ('half_width_native', 'half_length_native')):
        raise ValueError('Checked pitch bounds are unavailable')
    players = []
    identities = {}
    for p in post['capture']['retained_players']:
        if p['fixture_key'] != key or p['side_index'] not in (0, 1):
            raise ValueError('Unexpected retained player fixture or side')
        if not p.get('person_name') or not p.get('canonical_person_id'):
            raise ValueError('Unresolved player identity')
        identity = (p['side_index'], p['canonical_person_id'])
        if identity in identities:
            raise ValueError('Duplicated player identity on a retained side')
        row = {k: p.get(k) for k in METRICS}
        row['source_form_rating'] = p.get('match_rating')
        row['rating_state'] = p.get('rating_gate')
        if p.get('rating_gate') != 'qualified':
            row['match_rating'] = None
        row.update(side=p['side_index'], id=p['canonical_person_id'], name=p['person_name'],
                   slot=p['stored_player_slot'], position=p.get('stored_match_position'),
                   appearance=p.get('appearance_kind'), participation=p.get('participation_state'),
                   source_row_sha256=p['row_sha256'])
        players.append(row)
        identities[identity] = row
    team_totals = post['capture']['team_totals']['records'][0]
    if team_totals['result_key'] != key:
        raise ValueError('Team total key mismatch')
    totals = sorted(team_totals['teams'], key=lambda r: r['side_index'])
    shot_coverage = record.get('side_coverage') or []
    strict_sides = {r['side_index'] for r in shot_coverage if r['state'] == 'available'} if shot_coverage else {0, 1}
    shot_map = {(s['side_index'], s['event_id']): s for s in record['shots']}
    shots = []
    for s in half['shots'] if half else record['shots']:
        original = shot_map.pop((s['side_index'], s['event_id']))
        for field in ('expected_goals', 'native_x', 'native_y', 'outcome'):
            if original[field] != s[field]:
                raise ValueError(f'Retained shot disagrees with period source: {field}')
        if not finite(s['expected_goals']) or not 0 <= s['expected_goals'] <= 1:
            raise ValueError('Invalid per-shot expected goals')
        if half is not None and s.get('period') not in ('FirstHalf', 'SecondHalf'):
            raise ValueError('A shot has no verified normal-half classification')
        actor = s.get('actor') or {}
        if (s['side_index'], actor.get('canonical_person_id')) not in identities:
            raise ValueError('Shot actor is not a checked retained participant')
        direction = s.get('attacked_goal_positive_native_y')
        if type(direction) is not bool:
            raise ValueError('Shot orientation is not established')
        sign = 1 if direction else -1
        shots.append({'side': s['side_index'], 'event_id': s['event_id'],
                      'player_id': actor['canonical_person_id'], 'name': actor['person_name'],
                      'axis0': sign * s['native_x'], 'axis1': sign * s['native_y'],
                      'xg': s['expected_goals'], 'outcome': s['outcome'], 'period': s.get('period'),
                      'location': s.get('official_location'), 'penalty': s.get('is_penalty'),
                      'source_sha256': s['source_record_sha256']})
    if shot_map or (half is not None and half['unknown_boundary_rows']):
        raise ValueError('Incomplete shot-period coverage')
    tracking_forward_proved = False
    if orientation_proof is not None:
        orientation, orientation_source = load(orientation_proof, 'Match-specific tracking and shot orientation controls')
        original_shots = {(x['side_index'], x['event_id']): x for x in record['shots']}
        if not orientation.get('all25_goal_direction_bits_equal_tracking_orientation') or len(orientation['rows']) != len(original_shots):
            raise ValueError('Tracking orientation controls are incomplete')
        seen = set()
        for control in orientation['rows']:
            identity = (control['side'], control['event_id'])
            source_shot = original_shots[identity]
            if (identity in seen or not control['same'] or control['tick'] != source_shot['native_clock_start_raw']
                    or control['raw_y'] != source_shot['native_y']
                    or control['attacked_goal_positive_native_y'] != source_shot['attacked_goal_positive_native_y']
                    or control['tracking_positive_orientation'] != control['attacked_goal_positive_native_y']):
                raise ValueError('A tracking/shot orientation control disagrees with the retained match')
            seen.add(identity)
        tracking_forward_proved = True
        manifest.append(orientation_source)
    nodes = []
    for p in avg['players']:
        owner = identities.get((p['side_index'], p['canonical_person_id']))
        if owner is None or owner['slot'] != p['stored_player_slot']:
            raise ValueError('Average-position player join failed')
        coverage = p.get('coverage') or {}
        tail = coverage.get('trailing_zero_pair_sample_count')
        nodes.append({'side': p['side_index'], 'id': p['canonical_person_id'], 'name': p['person_name'],
                      'axis0': p['native_axis_0'], 'axis1': p['native_axis_1'],
                      'samples': p['sample_count'], 'coverage': coverage,
                      'trailing_zero_tail': tail,
                      'clean_full_duration': owner['minutes'] == 90 and tail == 0,
                      'unpadded': tail == 0,
                      'possession_means': p.get('possession_means')})
    side_edges = []
    for side in edges['sides']:
        if side['state'] != 'available' or not side['all_captured_player_counters_match']:
            raise ValueError('Pass-edge checks failed')
        i = side['side_index']
        for edge in side['edges']:
            for field in ('from_person_native_id', 'to_person_native_id'):
                if (i, edge[field]) not in identities:
                    raise ValueError('Pass-edge participant join failed')
        side_edges.append({'side': i, 'official_map_records': side['official_map_record_count'],
                           'completed': side['counter_reconciled_completed_passes'],
                           'excluded_mask8': side['excluded_unlabelled_mask8_count'],
                           'edges': [{'from': e['from_person_native_id'], 'to': e['to_person_native_id'],
                                      'count': e['counter_reconciled_completed_passes'],
                                      'official_map_count': e['official_map_count'],
                                      'excluded_mask8': e['excluded_unlabelled_mask8_count']} for e in side['edges']]})
    # Reconcile independently captured team totals before showing a result.
    for total in totals:
        side = total['side_index']
        selected = [s for s in shots if s['side'] == side]
        if side not in strict_sides:
            if selected:
                raise ValueError('Unreconciled side unexpectedly exposes strict shot rows')
        elif len(selected) != total['shots']:
            raise ValueError('Retained shots disagree with checked team total')
        if side in strict_sides and sum(s['outcome'] in ('goal', 'saved') for s in selected) != total['shots_on_target']:
            raise ValueError('Retained on-target attempts disagree with team total')
        if side in strict_sides and abs(sum(s['xg'] for s in selected) - total['expected_goals']) >= 1e-6:
            raise ValueError('Retained xG sum disagrees with checked team total')
        if sum(p['passes_completed'] or 0 for p in players if p['side'] == side) != total['passes_completed']:
            raise ValueError('Player pass completions disagree with checked team total')
        if next(x['completed'] for x in side_edges if x['side'] == side) != total['passes_completed']:
            raise ValueError('Directed pass completion total disagrees with team total')
    observed_shots = []
    observed_coverage = record.get('source_observed_coverage') or []
    for coverage in observed_coverage:
        if coverage['state'] != 'available_source_observed_counts_verified_xg_unreconciled' or coverage['verified_shots_promoted'] or coverage['xg_tolerance_widened']:
            raise ValueError('Unsupported observed-shot guard state')
        side = coverage['side_index']
        rows = [s for s in record.get('source_observed_shots', []) if s['side_index'] == side]
        total = next(t for t in totals if t['side_index'] == side)
        if len(rows) != total['shots'] or len(rows) != coverage['observed_shot_count'] or sum(s['outcome'] in ('goal','saved') for s in rows) != total['shots_on_target']:
            raise ValueError('Observed shot counts disagree with official totals')
        for evidence in coverage['individual_player_evidence']:
            if not evidence['counts_exact']:
                raise ValueError('Observed player counters did not reconcile')
        for row in rows:
            actor = row['actor'];identity=(side,actor['canonical_person_id'])
            if identity not in identities or identities[identity]['slot'] != row['stored_player_slot']:
                raise ValueError('Observed shot actor join failed')
            value=row['native_expected_goals'];direction=row['attacked_goal_positive_native_y']
            if not finite(value) or not 0 <= value <= 1 or type(direction) is not bool:
                raise ValueError('Invalid observed shot xG or direction')
            sign=1 if direction else -1
            observed_shots.append({'side':side,'event_id':row['event_id'],'player_id':actor['canonical_person_id'],'name':actor['person_name'],
                'axis0':sign*row['native_x'],'axis1':sign*row['native_y'],'xg':value,'outcome':row['outcome'],'period':None,
                'location':row.get('official_location'),'penalty':row.get('is_penalty'),'source_sha256':row['source_record_sha256'],
                'verification_scope':row['verification_scope'],'xg_reconciliation':row['xg_reconciliation']})
    attempt_coverage = None
    if pass_attempts is not None:
        attempts, attempt_source = load(pass_attempts, 'Reconciled pass-attempt availability')
        if attempts['state'] != 'available' or attempts['native_match_key'] != key:
            raise ValueError('Pass-attempt source is unavailable or belongs to another match')
        for side in attempts['side_coverage']:
            total = next(t for t in totals if t['side_index'] == side['side_index'])
            if side['attempt_count'] != total['passes_attempted'] or side['completed_count'] != total['passes_completed']:
                raise ValueError('Pass-attempt coverage disagrees with checked team totals')
        attempt_coverage = {'attempt_count': len(attempts['attempts']),
                            'side_coverage': [{k: row[k] for k in ('side_index', 'attempt_count', 'completed_count', 'not_completed_count')}
                                              for row in attempts['side_coverage']],
                            'limits': attempts.get('limits'), 'raw_paths_plotted': False}
        manifest.append(attempt_source)
    half_summary = [{k: r[k] for k in ('side_index', 'period', 'shots', 'shots_on_target', 'shot_goals', 'xg_sum_computed')}
                    for r in half['summary']] if half else []
    markers = half['native_period_markers'] if half else []
    boundaries = {'first_half_end_tick': next(x['stop_time_slice'] for x in markers if x['next_stop_reason'] == 'EndOfPeriod'),
                  'second_half_start_tick': next(x['stop_time_slice'] for x in markers if x['next_stop_reason'] == 'StartOfPeriod' and x['source_index'] > 0)} if half else {}
    heat_windows = {}
    for label, window in heat.items():
        if not isinstance(window, dict) or 'players' not in window:
            continue
        start, end = window.get('requested_start_tick'), window.get('requested_end_tick')
        name = ('Full' if start is None and end is None else 'FirstHalf' if start is None
                and half and end == boundaries['first_half_end_tick'] else 'SecondHalf' if end is None
                and half and start == boundaries['second_half_start_tick'] else None)
        if name is not None:
            def compact_map(row):
                clean = {k: v for k, v in row.items() if k not in ('raw_cells', 'cells')}
                clean['cells'] = [[c['axis_0_index'], c['axis_1_index'], c['normalized_intensity']] for c in row['cells']]
                return clean
            heat_windows[name] = {
                k: v for k, v in window.items() if k not in ('players', 'teams', 'clean_90min_teams', 'unpadded_teams')}
            for group in ('players', 'teams', 'clean_90min_teams', 'unpadded_teams'):
                heat_windows[name][group] = [compact_map(row) for row in window.get(group, [])]
    if 'Full' not in heat_windows:
        raise ValueError('Expected complete native-period heat-map windows')
    # Keep source datasets whole; the UI marks the selected stream subset and coverage.
    return {'schema_version': 1, 'match_key': key, 'fixture': fixture, 'teams': teams,
            'score': fixture['scores']['final_score'], 'geometry': geometry, 'team_totals': totals,
            'half_split_available': half is not None, 'half_summary': half_summary, 'pass_attempt_coverage': attempt_coverage, 'period_boundaries': boundaries, 'players': players,
            'source_observed_shots': observed_shots, 'source_observed_coverage': observed_coverage, 'shot_coverage': shot_coverage, 'shots': shots, 'average_nodes': nodes, 'pass_sides': side_edges, 'heat_windows': heat_windows,
            'provenance': manifest, 'retrospective': True, 'tracking_forward_proved_for_this_match': False, 'tracking_orientation_controls_match_all_shots': tracking_forward_proved, 'heat_cell_schema': ['axis_0_index', 'axis_1_index', 'normalized_intensity'],
            'limits': ['Reconstructed from checked retained match captures; not a live halftime recommendation.',
                       'Shots are oriented towards the attacked goal at right; tracking attacking direction is unverified.' + ' Physical units and human left/right viewpoint remain unknown; pitch markings are schematic.',
                       'Stored tracking samples and their means are not playing minutes. Zero tails after exit can distort official retained means; the default spatial subset excludes these streams.',
                       'Directed pass counts are full-match completed-pass counts between players. Lines connect average coordinates, not observed pass routes.',
                       'The half split uses native period boundaries including stoppage time; exact displayed shot minutes are not supplied.' if half else 'No authoritative retained half boundary is available for this fixture. Only full-match statistics are shown; timing gaps and orientation changes are not used to invent halves.']}


def prepare_capture(capture_path: Path, heatmaps_path: Path, halves_path: Path | None = None):
    capture, provenance = load(capture_path, 'Fresh retained match capture')
    if not capture['receipt']['same_native_epoch_verified']:
        raise ValueError('Capture native epoch was not verified')
    spatial = capture['spatial_reports'][0]
    record = capture['shot_maps'][0]
    post = {'errors': [], 'shots': {'records': [record]},
            'capture': {'retained_players': capture['retained_players'], 'team_totals': capture['team_totals']}}
    edges = {**spatial['pass_network'], 'native_match_key': record['native_match_key'], 'fixture': record['fixture']}
    averages = {**spatial['average_positions'], 'fixture_key': record['native_match_key']}
    def supplied(value, fragment):
        return value, {**provenance, 'source_fragment': fragment}
    result = prepare(supplied(post, 'shot_maps[0],retained_players,team_totals'),
                   supplied(edges, 'spatial_reports[0].pass_network'),
                   supplied(averages, 'spatial_reports[0].average_positions'), heatmaps_path, halves_path,
                   supplied(capture['pass_attempts'][0], 'pass_attempts[0]') if capture.get('pass_attempts') else None)
    raw=next((row for row in capture.get('raw_frames',[]) if row['key']==record['native_match_key']),None)
    result['capture_identity']={'observed_at':capture['receipt'].get('observed_at'),'raw_frame_sha256':raw.get('raw_sha256') if raw else None,'source_capture_sha256':provenance['sha256']}
    return result


def add_key_pass_evidence(data, capture_path: Path, key_passes_path: Path):
    capture, _ = load(capture_path, 'Fresh retained match capture')
    receipt, provenance = load(key_passes_path, 'Retained key-pass actor and supplier checks')
    result = receipt.get('result', receipt)
    raw = next(r for r in capture['raw_frames'] if r['key'] == data['match_key'])
    if result['native_match_key'] != data['match_key'] or result['raw_frame_sha256'] != raw['raw_sha256']:
        raise ValueError('Key-pass fixture/frame evidence differs from report source')
    players = {(p['side'],p['id']):p for p in data['players']}
    checked=set()
    for side in result['sides']:
        index=side['side_index']
        if side['team_native_id'] != data['teams'][index]['native_id']:
            raise ValueError('Key-pass team identity mismatch')
        roster=[p for p in data['players'] if p['side']==index]
        if len(side['player_checks']) != len(roster):
            raise ValueError('Key-pass roster is incomplete')
        for check in side['player_checks']:
            identity=(index,check['person_native_id']);player=players[identity]
            if identity in checked or check['stored_player_slot'] != player['slot'] or check['official_key_passes'] != player['key_passes']:
                raise ValueError('Key-pass actor slot/counter mismatch')
            if check['counts_match'] != (check['source_annotation_count'] == check['official_key_passes']):
                raise ValueError('Key-pass closure flag contradicts actor counters')
            checked.add(identity)
            player['retained_key_pass_annotations'] = check['source_annotation_count'] if check['counts_match'] else None
            player['retained_key_pass_state']=check['state']
        if sum(p['key_passes'] for p in roster) != side['official_key_pass_total']:
            raise ValueError('Official key-pass side sum mismatch')
        for pair in side.get('supplied_pairs',[]):
            if any((index,pair[field]) not in players for field in ['from_person_native_id','to_person_native_id']):
                raise ValueError('Key-pass supplier/recipient outside roster')
    if len(checked) != len(players):
        raise ValueError('Not every retained key-pass actor was checked')
    for row in result['annotations']:
        identity=(row['side_index'],row['person_native_id'])
        if identity not in players or players[identity]['retained_key_pass_annotations'] is None:
            raise ValueError('Unsupported actor annotation exposed')
    for identity,player in players.items():
        count=player['retained_key_pass_annotations']
        if count is not None and sum((a['side_index'],a['person_native_id'])==identity for a in result['annotations'])!=count:
            raise ValueError('Supported key-pass actor annotations are incomplete')
    data['key_pass_evidence']=result
    data['provenance'].append(provenance)
    return data


def add_pressure_evidence(data, capture_path: Path, pressures_path: Path):
    capture,_=load(capture_path,'Fresh retained match capture')
    result,provenance=load(pressures_path,'Named native pressure attempts and completion counters')
    raw=next(r for r in capture['raw_frames'] if r['key']==data['match_key'])
    if result['native_match_key']!=data['match_key'] or result['raw_frame_sha256']!=raw['raw_sha256'] or result['state']!='verified_raw_frame_boundary_and_canonical_player_pressure_fields':
        raise ValueError('Pressure source does not match fixture/raw frame')
    players={(p['side'],p['id']):p for p in data['players']};seen=set()
    for row in result['rows']:
        identity=(row['side_index'],row['canonical_person_id']);p=players[identity]
        if identity in seen or row['fixture_key']!=data['match_key'] or row['stored_player_slot']!=p['slot'] or row['minutes']!=p['minutes'] or row['row_sha256']!=p['source_row_sha256'] or hashlib.sha256(bytes.fromhex(row['raw_child_hex'])).hexdigest()!=row['row_sha256']:
            raise ValueError('Pressure canonical player/raw child mismatch')
        seen.add(identity);attempts=row['pressures_attempted'];completed=row['pressures_completed']
        if any(type(v)is not int or v<0 for v in [attempts,completed]) or completed>attempts or completed!=p['pressures_completed']:
            raise ValueError('Invalid pressure counters')
        expected=100*completed/attempts if attempts else None
        if row['pressure_completion_percentage_computed']!=expected:
            raise ValueError('Pressure ratio disagrees with counters')
        for k in ['pressures_attempted','pressure_completion_percentage_computed','pressure_completion_state']:p[k]=row[k]
    if seen!=set(players):raise ValueError('Pressure source does not cover full roster')
    for side in result['sides']:
        rows=[p for p in data['players'] if p['side']==side['side_index']]
        for field in ['pressures_attempted','pressures_completed']:
            if sum(p[field] for p in rows)!=side[field]:raise ValueError('Pressure side totals mismatch')
        expected=100*side['pressures_completed']/side['pressures_attempted'] if side['pressures_attempted'] else None
        if expected!=side['pressure_completion_percentage_computed']:raise ValueError('Pressure team ratio mismatch')
    data['pressure_evidence']={k:v for k,v in result.items() if k!='rows'}
    data['provenance'].append(provenance)
    return data


def render(data: dict, output: Path):
    script = (HERE / 'dist/report.js').read_text()
    css = (HERE / 'src/report.css').read_text()
    payload_json = json.dumps(data, ensure_ascii=False, separators=(',', ':'))
    payload = base64.b64encode(gzip.compress(payload_json.encode('utf-8'), compresslevel=9, mtime=0)).decode('ascii')
    title = f"{data['teams'][0]['short_name']} v {data['teams'][1]['short_name']} — match analysis"
    html = f'''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta http-equiv="Content-Security-Policy" content="connect-src 'none'; object-src 'none'; base-uri 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; img-src data:"><title>{escape(title)}</title><style>{css}</style></head><body><div id="root"></div><noscript>This interactive report needs JavaScript. All data is embedded in this file; no internet connection is needed.</noscript><script type="application/octet-stream" data-encoding="gzip-base64" id="match-data">{payload}</script><script>{script}</script></body></html>'''
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(html)
    return {'output': str(output.resolve()), 'bytes': output.stat().st_size,
            'sha256': hashlib.sha256(output.read_bytes()).hexdigest(),
            'match_key': data['match_key'], 'players': len(data['players']), 'shots': len(data['shots']),
            'average_nodes': len(data['average_nodes']), 'sources': data['provenance']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('heatmaps', 'output'):
        parser.add_argument('--' + name, required=True, type=Path)
    for name in ('postgame', 'passes', 'averages', 'capture'):
        parser.add_argument('--' + name, type=Path)
    parser.add_argument('--pressures', type=Path)
    parser.add_argument('--key-passes', type=Path)
    parser.add_argument('--pass-locations', type=Path)
    parser.add_argument('--halves', type=Path)
    parser.add_argument('--receipt', type=Path)
    parser.add_argument('--pass-attempts', type=Path)
    parser.add_argument('--orientation-proof', type=Path)
    a = parser.parse_args()
    if a.capture:
        if any((a.postgame, a.passes, a.averages, a.pass_attempts, a.orientation_proof)):
            parser.error('--capture cannot be combined with separate source adapters')
        data = prepare_capture(a.capture, a.heatmaps, a.halves)
    else:
        if not all((a.postgame, a.passes, a.averages)):
            parser.error('Provide --capture or all of --postgame, --passes and --averages')
        data = prepare(a.postgame, a.passes, a.averages, a.heatmaps, a.halves, a.pass_attempts, a.orientation_proof)
    if a.key_passes:
        if not a.capture:
            parser.error('--key-passes requires --capture for raw-frame/roster validation')
        data = add_key_pass_evidence(data, a.capture, a.key_passes)
    if a.pressures:
        if not a.capture:parser.error('--pressures requires --capture for raw-child/roster validation')
        data = add_pressure_evidence(data, a.capture, a.pressures)
    if a.pass_locations:
        if not a.capture:parser.error('--pass-locations requires --capture for frame/roster/counter checks')
        from pass_location_evidence import add_pass_location_evidence
        data = add_pass_location_evidence(data, a.capture, a.pass_locations)
    receipt = render(data, a.output)
    if a.receipt:
        a.receipt.parent.mkdir(parents=True, exist_ok=True)
        a.receipt.write_text(json.dumps(receipt, indent=2) + '\n')
    print(json.dumps({k: v for k, v in receipt.items() if k != 'sources'}, indent=2))


if __name__ == '__main__':
    main()
