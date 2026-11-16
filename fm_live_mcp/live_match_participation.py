"""Conservative native-minute participation projections, based on B89 usage.

Only unused_substitute is an independently proved native appearance label.
Other kinds describe the duration branch, not a decoded lineup designation.
Minute intervals cannot order events within the same labelled minute.
"""


LINEUP_POLICY = {
    'formal_starting_lineup_state': 'not_decoded',
    'formal_started': None,
    'may_report_as_formal_starts': False,
    'match_completion_state': 'not_decoded',
    'claim': ('initial_participant_candidate and native_substitute_duration_flag select native '
              'duration arithmetic, not a verified official starting XI. Exactly eleven candidates, '
              'minute conservation, first-eleven row order, positive minutes or a stored result do '
              'not close the missing starting-lineup/completion source. Do not count or rank these '
              'as actual starts. Report formal starts unavailable; missing rows remain unknown.'),
}


def field_registry():
    return {
        'appearance_kind': {'state': 'native_unused_label_or_duration_branch_only',
                            'formal_started': None, 'may_report_as_formal_starts': False},
        'native_substitute_duration_flag': {'state': 'native_duration_arithmetic_selector',
                                            'formal_started': None, 'may_report_as_formal_starts': False},
    }

def project(row):
    source=row['source'];clock=source['end_clock']
    on,off,injury,sent=(source[k] for k in ('on_minute','off_minute','injury_minute','sent_off_minute'))
    substitute=bool(source['flags5c'] & 32)
    unused=row.get('appearance_state')=='unused_substitute'
    terminal=off or injury or sent or clock
    exit_reason=('off' if off else 'injury' if injury else 'sent_off' if sent else 'end_clock')
    entry=None if unused else on if substitute else 0
    exit_clock=None if unused else terminal
    duration=None if unused else terminal-entry
    state=('unused_substitute' if unused else 'reconciled_native_minute_interval'
           if 0<=entry<=terminal<=clock and duration==row['minutes']
           else 'unresolved_native_clock_or_duration')
    kind='unused_substitute' if unused else 'entered_during_match' if substitute else 'initial_participant_candidate'
    return {
        'appearance_kind':kind,
        'appearance_kind_state':'native_label_proved' if unused else 'derived_from_native_duration_branch',
        'native_substitute_duration_flag':substitute,
        'native_on_minute':on,'native_off_minute':off,
        'native_injury_minute':injury,'native_sent_off_minute':sent,
        'native_end_clock':clock,'sent_off':bool(sent),
        'entry_minute':entry if state!='unresolved_native_clock_or_duration' else None,
        'exit_minute':exit_clock if state!='unresolved_native_clock_or_duration' else None,
        'exit_reason':None if unused else exit_reason,
        'participation_state':state,
        'interval_precision':'stored_minute_labels; event_order_within_minute_unknown',
        'interval_convention':'[entry,exit) for overlap duration only',
        'simultaneous_event_order_known':False,
    }


def enrich(rows):
    return [{**row,**project(row)} for row in rows]


def side_coverage(rows):
    """Summarize duration/manpower without forcing full-team or exact-time claims."""
    active=[r for r in rows if r['appearance_kind']!='unused_substitute']
    clocks={r['native_end_clock'] for r in rows}
    if len(clocks)!=1:raise ValueError('Inconsistent side end clock')
    clock=next(iter(clocks))
    reliable=all(r['participation_state']=='reconciled_native_minute_interval' for r in active)
    boundaries=sorted({0,clock}|{r[k] for r in active for k in ('entry_minute','exit_minute') if r[k] is not None})
    segments=[]
    if reliable:
        for start,end in zip(boundaries,boundaries[1:]):
            count=sum(r['entry_minute']<=start and r['exit_minute']>=end for r in active)
            segments.append({'start_minute':start,'end_minute':end,'projected_player_count':count})
    total=sum(r.get('minutes') or 0 for r in rows)
    expected=11*clock-sum(clock-r['native_sent_off_minute'] for r in active if r['sent_off'])
    return {'initial_participant_candidates':sum(r['appearance_kind']=='initial_participant_candidate' for r in rows),
            'used_participants':len(active),'unused_substitutes':len(rows)-len(active),
            'all_used_intervals_reconcile_native_minutes':reliable,
            'summed_native_minutes':total,'eleven_player_minutes_less_sent_off_loss':expected,
            'minutes_delta_from_eleven_less_sent_off':total-expected,
            'manpower_segments':segments,'event_order_within_minute_known':False}
