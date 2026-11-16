"""Explicit host-write recorder, separate from game-read-only query tools."""
import os
from pathlib import Path
from typing import Any
from mcp.types import ToolAnnotations
from .observed_run_recorder import capture_prefix, write_prefix
from .observed_run_registry import register_original


def configured_store():
    configured = os.environ.get('FM_LIVE_OBSERVED_STORE')
    if configured:
        path = Path(configured).expanduser()
        if not path.is_absolute():
            raise ValueError('FM_LIVE_OBSERVED_STORE must be absolute')
        return path
    volume = Path('/Volumes/4TB Private')
    if not volume.is_mount():
        raise ValueError('Configure FM_LIVE_OBSERVED_STORE or mount the approved external capture volume')
    return volume/'Offloaded/FM Live Captures/observed-runs'


def record_current_match(bridge,session_id,*,include_tactics=True,include_incomplete_passes=False):
    store = configured_store()
    options = {'include_incomplete_passes': True} if include_incomplete_passes else {}
    if type(include_incomplete_passes) is not bool:
        raise ValueError('include_incomplete_passes must be boolean')
    packet = capture_prefix(bridge,session_id,include_tactics=include_tactics,**options)
    if packet['state']=='unavailable':
        return packet
    receipt = write_prefix(packet,store)
    try:
        from .observed_run_tactical_capture import attestation
        from .observed_pass_attempts import attestation as attempt_attestation
        proof = attempt_attestation(packet,receipt)
        options = {'pass_attempt_attestation': proof} if proof is not None else {}
        register_original(receipt['path'],receipt['source_id'],receipt['sha256'],producer_attestation=attestation(packet,receipt),**options)
    except (OSError, ValueError) as error:
        return {**receipt,'registered':False,'registration_error':str(error),
                'game_writes':False,'background_recording':False}
    return {**receipt,'tactical_collection':packet.get('tactical_observation',{}).get('state','not_collected'),
            'assist_annotation_collection':packet.get('assist_annotation_collection',{'state':'not_collected'}),
            'pass_attempt_collection':'available' if packet.get('pass_attempt_observation') is not None else 'not_requested',
            'registered':True,'product_type':'observed_native_match_run',
            'capture_state':'partial_prefix','game_writes':False,'background_recording':False,
            'replay_exclusion_verified':False,
            'next':'Discover this exact source_id/capture_id with fm_list_observed_match_runs and query its available tables.'}


def register_observed_run_record_tools(mcp,bridge):
    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=False,destructiveHint=False,openWorldHint=False))
    def fm_record_current_match(session_id:str,include_tactics:bool=True,include_incomplete_passes:bool=False)->dict[str,Any]:
        """Explicitly record this observed match prefix to a new immutable HOST SQLite and local observed-run registry. Use when asked to record this match or preserve the current passing/tracking observation for later recap. No background recorder and no game writes/functions/UI. Requires a bound active native fixture and same-career fixed-prefix verification; inactive or drifting sources produce no capture. Preserves completed pass events, observed actor identities, portable raw tracking prefix and observed period markers. Set include_incomplete_passes=true to additionally capture all native pass-family6..11 minus mask8 EVENT map points, with explicit attested pass_attempt_events table: category7 completed, others not_completed with unknown reason; incomplete secondary bytes are not recipients. These are not possession-loss, release/reception/destination points or an independently reconciled attempts denominator. Older recordings without captured XY remain unsupported for this table. By default also attempts one independently rechecked resident manager-settings sample with explicit cursor window and raw instruction flags; include_tactics=false skips it. Missing tactical source stays unavailable and does not discard the event prefix. Sparse settings are not kickoff settings, historical effective roles or an exact tactical-change history. Also attempts optional official score at the fixed cursor and shot/player summaries derived only from completed attempts strictly before it. The inclusive score and exclusive attempt boundaries may differ. These are not engine-frontier PLAYER counters; full-match completion, active XI and replay exclusion remain unavailable. A missing or drifting optional statistics source stays unknown without discarding the base prefix. Native clocks are not displayed minutes and tracking means are not metres or on-pitch time. Unchanged semantic selection reuses its original. Different native incarnations/content produce separate immutable source IDs, never a merged playthrough. Store is configured by FM_LIVE_OBSERVED_STORE or the approved mounted external host store; no caller filesystem path. Afterwards use fm_list_observed_match_runs and fm_query_observed_match_run even after game teardown."""
        return record_current_match(bridge,session_id,include_tactics=include_tactics,include_incomplete_passes=include_incomplete_passes)
