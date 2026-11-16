"""Goals-only ranking of a fully supplied, source-qualified candidate census."""

MAX_CANDIDATES = 20_000
MAX_OUTPUT_ROWS = 1000


def rank_candidates(candidates, limit=10):
    """Never prefilter by minutes/assists or silently cut a cutoff tie.

    The collector owns competition/season and duplicate-membership semantics.
    This function does not certify that its candidate census is authoritative.
    """
    if type(limit) is not int or not 1 <= limit <= 50:
        raise ValueError('Scorer limit must be an integer in 1..50')
    if not isinstance(candidates, list) or len(candidates) > MAX_CANDIDATES:
        raise ValueError('Scorer candidate reader budget exceeded')
    indices = set()
    ordinals = set()
    known = []
    unknown = []
    for candidate in candidates:
        if not isinstance(candidate, dict):
            raise ValueError('Invalid scorer candidate')
        index = candidate.get('person_index')
        ordinal = candidate.get('source_ordinal')
        if type(ordinal) is not int or ordinal < 0 or ordinal in ordinals:
            raise ValueError('Scorer source ordinals must be unique nonnegative integers')
        ordinals.add(ordinal)
        if index is not None:
            if type(index) is not int or not 0 <= index < 2**31 or index in indices:
                raise ValueError('Scorer PERSON duplicates must be resolved by the source collector')
            indices.add(index)
        goals = candidate.get('goals')
        if goals is None:
            unknown.append(candidate)
        else:
            if index is None or type(goals) is not int or not 0 <= goals < 2**31:
                raise ValueError('Invalid normalized scorer goal value or identity')
            known.append(candidate)
    positive = [row for row in known if row['goals'] > 0]
    positive.sort(key=lambda row: (-row['goals'], row['person_index']))
    cutoff = positive[min(limit, len(positive)) - 1]['goals'] if positive else None
    winners = [row for row in positive if row['goals'] >= cutoff] if cutoff is not None else []
    if len(winners) > MAX_OUTPUT_ROWS:
        raise ValueError('Complete cutoff tie exceeds scorer output budget; no partial tie returned')
    ranked = []
    previous = None
    place = 0
    for ordinal, row in enumerate(winners, 1):
        if row['goals'] != previous:
            place = ordinal
        ranked.append({**row, 'rank': place})
        previous = row['goals']
    return {
        'rows': ranked,
        'candidate_count': len(candidates),
        'known_goals_count': len(known),
        'unknown_goals_count': len(unknown),
        'zero_goals_count': len(known) - len(positive),
        'positive_goals_count': len(positive),
        'returned_count': len(ranked),
        'limit': limit,
        'cutoff_goals': cutoff,
        'cutoff_ties_added': max(0, len(ranked) - limit),
        'cutoff_ties_complete': True,
        'unknown_candidates_present': bool(unknown),
        'ranking_scope': 'known normalized goal values from the supplied candidate census',
        'metric': 'goals',
        'minutes_filter_applied': False,
        'assists_filter_applied': False,
    }
