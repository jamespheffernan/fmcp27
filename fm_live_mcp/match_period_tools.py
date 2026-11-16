"""Retrospective periods require host-captured native stops and retained continuity."""
from typing import Annotated, Any
from mcp.types import ToolAnnotations
from pydantic import Field

from . import live_retained_shots as retained
from .match_data_query import capture_live, capture_epoch
from .match_period_observations import ObservationStore, link_retained, process_epoch


def report_retained_periods(bridge, session_id, fixture_ref, *, store=None):
    epoch = capture_epoch(bridge,session_id)
    capture = capture_live(bridge,session_id,[fixture_ref],include_players=True)
    items=capture['capture']['fixtures']
    if len(items)!=1:raise ValueError('Select one canonical retained result')
    fixture=items[0]['fixture'];key=items[0]['native_match_key']
    records=capture['team_totals']['records']
    if len(records)!=1 or records[0]['result_key']!=key:raise ValueError('Missing exact period team oracle')
    teams=records[0]['teams'];retained._validate_team_oracle(fixture,teams)
    actors=retained._validated_actors(capture['retained_players'],teams)
    source=retained.capture_source(bridge,session_id,fixture_ref,key,fixture)
    if source['state']!='available':
        return dict(state=source['state'],fixture=fixture,native_match_key=key,periods=None,shot_periods=None)
    packet=retained.decode_attempts(source['vectors'],source['events'],teams,pitch_geometry=source.get('pitch_geometry'))
    if any(side['state']!='available'for side in packet['side_coverage']):
        return dict(state='unavailable_unreconciled_retained_attempts',fixture=fixture,native_match_key=key,periods=None,shot_periods=None)
    for shot in packet['shots']:
        actor=actors.get((shot['side_index'],shot['stored_player_slot']))
        shot['actor']=actor
    if capture_epoch(bridge,session_id)!=epoch:raise ValueError('Native load changed during period linkage')
    save=bridge.get_save(session_id)['save']
    result=link_retained(store or ObservationStore(),save,fixture,key,source,packet['shots'],process_epoch(bridge))
    result.update(fixture=fixture,native_match_key=key,observed_save=save,retained_side_coverage=packet['side_coverage'])
    return result


def register_match_period_tools(mcp,bridge):
    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=False,destructiveHint=False,openWorldHint=False))
    def fm_report_retained_match_periods(
        session_id:str,
        fixture_ref:Annotated[str,Field(min_length=1,max_length=128,description='Exact historical result fixture_ref from fm_find_fixtures; match date/ordered teams/competition are checked.')],
    )->dict[str,Any]:
        """Answer which half created chances using host-captured verified native period stops linked to this exact retained result. Normal fm_get_current_match reads can preserve these observations locally while the source is resident; no unattended capture runs. Reports historical capture provenance and verified retrospective continuity, not a new live halftime reading. Requires exact career/fixture identity and complete attempt/event semantic prefix agreement; a new process/load may reuse only a previously finalized exact retained fingerprint. Uncaptured, conflicting, partial or unreconciled evidence stays unavailable. Only closed source-proved period intervals receive shots/xG; boundary ties and unobserved intervals remain unknown. No halves inferred from event order, raw-time gaps, coordinates or changing ends. No tactical-edit history or causal effect. Read-only game access; local observation linkage may be finalized in the host cache; no caller paths, disk-save decoding or game writes."""
        return report_retained_periods(bridge,session_id,fixture_ref)
