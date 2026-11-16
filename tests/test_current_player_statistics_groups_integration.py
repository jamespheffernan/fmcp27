"""Actual report opt-in hook over one genuine joint statistics packet.

Fixture context and unrelated playback/team projections are isolated doubles;
the real report dispatcher, canonical scalar decoders and bytes are exercised.
"""
from historical_match_identity_fixture import historical_team_identity_contract
from fm_live_mcp import current_match_report as report, world
from test_current_player_match_statistic_groups_joint import Joint,versioned149


def test_report_dispatches_existing_opt_in_to_all_genuine_statistic_groups(monkeypatch):
    f=Joint()
    versioned149(monkeypatch,f)
    context=f.packet['context_before']['fixture']
    binding=f.packet['context_before']['private']
    monkeypatch.setattr(report.active_match_source,'inspect_context',lambda *_args,**_kwargs:(context,binding))
    monkeypatch.setattr(report.live_match_performance,'inspect',lambda *_args:{'isolated_team_source':True})
    monkeypatch.setattr(report,'_statistics',lambda *_args:{'isolated_team_projection':True})
    monkeypatch.setattr(report,'_playback_report',lambda *_args:{})
    read=world.ReadSet(f.read)
    packet=report._inspect(read,f.base,f.packet['context_before']['save']['current_date'],
                           'client_snapshot',False,include_player_statistics=True)
    read.verify()
    assert packet['player_statistics']==f.packet['candidate_projection']
    assert len(packet['player_statistics']['field_qualifiers'])==24
    default=report._inspect(world.ReadSet(f.read),f.base,f.packet['context_before']['save']['current_date'],
                             'client_snapshot',False)
    assert 'player_statistics'not in default and 'player_passing'not in default
