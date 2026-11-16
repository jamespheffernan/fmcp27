from fm_live_mcp.live_match_participation import project, enrich, side_coverage

def row(on=0,off=0,injury=0,sent=0,sub=False,minutes=90,unused=False):
    return {'minutes':minutes,'appearance_state':'unused_substitute' if unused else None,'source':{'on_minute':on,'off_minute':off,'injury_minute':injury,'sent_off_minute':sent,'flags5c':32 if sub else 0,'end_clock':90}}

def test_native_priority_preserves_late_injury_gap():
    p=project(row(on=63,off=89,injury=90,sub=True,minutes=26))
    assert (p['entry_minute'],p['exit_minute'],p['exit_reason'])==(63,89,'off')
    assert not p['simultaneous_event_order_known']

def test_same_minute_substitution_has_no_overlap_duration():
    rows=enrich([row(off=63,minutes=63),row(on=63,sub=True,minutes=27)])
    assert rows[0]['exit_minute']==rows[1]['entry_minute']==63
    assert all(r['participation_state']=='reconciled_native_minute_interval' for r in rows)

def test_unused_is_absent_not_zero_length_appearance():
    p=project(row(sub=True,minutes=None,unused=True))
    assert p['entry_minute'] is None and p['exit_minute'] is None
    assert p['appearance_kind_state']=='native_label_proved'

def test_wrapped_native_duration_is_not_presented_as_interval():
    p=project(row(on=91,sub=True,minutes=0))
    assert p['entry_minute'] is None and p['participation_state']=='unresolved_native_clock_or_duration'

def test_sent_off_loss_reconciles_side_and_manpower():
    rows=enrich([row() for _ in range(10)]+[row(sent=70,minutes=70)])
    c=side_coverage(rows)
    assert c['minutes_delta_from_eleven_less_sent_off']==0
    assert c['manpower_segments']==[{'start_minute':0,'end_minute':70,'projected_player_count':11},{'start_minute':70,'end_minute':90,'projected_player_count':10}]


def test_reconciled_eleven_candidates_do_not_promote_formal_starts():
    from fm_live_mcp.live_match_participation import LINEUP_POLICY, field_registry
    candidates=enrich([row() for _ in range(11)])
    coverage=side_coverage(candidates)
    assert coverage['initial_participant_candidates']==11
    assert coverage['minutes_delta_from_eleven_less_sent_off']==0
    assert LINEUP_POLICY['formal_started'] is None
    assert LINEUP_POLICY['may_report_as_formal_starts'] is False
    assert LINEUP_POLICY['formal_starting_lineup_state']=='not_decoded'
    assert LINEUP_POLICY['match_completion_state']=='not_decoded'
    for field in ('appearance_kind','native_substitute_duration_flag'):
        assert field_registry()[field]['formal_started'] is None
        assert field_registry()[field]['may_report_as_formal_starts'] is False
