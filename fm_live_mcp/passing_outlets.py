"""Summarize recipients and their suppliers from the full reconciled pass map."""
from collections import defaultdict


def passing_outlets(side, person_native_id=None):
    total = side['counter_reconciled_completed_passes']
    accounted = sum(edge['counter_reconciled_completed_passes'] for edge in side['edges'])
    result = {
        'state': 'available', 'team_completed_passes': total,
        'named_teammate_completions': accounted, 'receivers': [],
    }
    # Native map construction omits self-links. Only rank whole-team outlets
    # when all player-completed counters also reconcile with directed edges.
    if accounted != total:
        return dict(result, state='unavailable_incomplete_named_network')
    players = {row['person_native_id']: row for row in side['player_counters']}
    if person_native_id is not None and person_native_id not in players:
        return dict(result, state='player_outside_selected_roster')
    suppliers = defaultdict(list)
    for edge in side['edges']:
        count = edge['counter_reconciled_completed_passes']
        if count:
            suppliers[edge['to_person_native_id']].append({
                'person_native_id': edge['from_person_native_id'],
                'name': edge['from_name'], 'completions': count,
            })
    for person_id, player in players.items():
        if person_native_id is not None and person_id != person_native_id:
            continue
        feeds = sorted(suppliers[person_id], key=lambda row: (-row['completions'], row['person_native_id']))
        received = sum(feed['completions'] for feed in feeds)
        result['receivers'].append({
            'person_native_id': person_id, 'name': player['person_name'],
            'completed_passes_received': received,
            'share_of_team_completions': received / total if total else None,
            'distinct_suppliers': len(feeds),
            'suppliers': feeds,
            'leading_suppliers': [feed for feed in feeds if feed['completions'] == feeds[0]['completions']],
        })
    result['receivers'].sort(key=lambda row: (-row['completed_passes_received'], row['person_native_id']))
    return result
