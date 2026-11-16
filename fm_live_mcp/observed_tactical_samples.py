"""Query verified recorder snapshots without inventing prior tactical history."""
from datetime import datetime, timezone
import hashlib
import json
import math

from . import observed_run_tactical_capture as producer
from .observed_tactical_settings import LEGACY_POSITION_KEYS, public_phases

EXTRA_COLUMNS=('native_cursor_window_start','native_cursor_window_end','fixed_event_cursor',
    'raw_selection_flags_hex','unclassified_selected_bits_json','unmapped_serialized_bits_json',
    'source_incarnation_id','sample_summary_sha256','resident_settings_sha256')
SCOPE=('One verified resident manager-settings observation per capture, sampled within the reported cursor window. '
       'The fixed event cursor is separate; same-tick settings, period, score, kickoff plan, effective individual '
       'overrides, change history and causal effects are unknown. Raw instruction flags and unknown bits are preserved. '
       'No prior state or cross-capture change is synthesized.')


def _pin(value):
    return isinstance(value,str) and len(value)==64 and all(c in '0123456789abcdef' for c in value)


def derive(db,provenance,proof,*,table,snapshot_table,columns):
    if proof is None:return None
    if not isinstance(proof,dict):raise ValueError('Recorded tactical producer proof malformed')
    metadata=provenance['limitations']
    if (proof.get('producer')!='verified_observed_recorder' or proof.get('schema_version')!=1
            or proof.get('source_document_id')!='tactical_samples'
            or proof.get('selection_id')!=metadata.get('selection_id')
            or proof.get('source_incarnation_id')!=metadata.get('source_incarnation_id')
            or not all(_pin(proof.get(k)) for k in ('selection_id','source_document_sha256','source_incarnation_id'))):
        raise ValueError('Recorded tactical producer identity differs')
    row=db.execute("SELECT sha256,document_json FROM source_documents WHERE source_id='tactical_samples'").fetchone()
    if (row is None or row[0]!=proof['source_document_sha256']
            or hashlib.sha256(row[1].encode()).hexdigest()!=row[0]):
        raise ValueError('Recorded tactical producer document hash differs')
    document=json.loads(row[1])
    if document.get('policy')!=proof.get('policy'):
        raise ValueError('Recorded tactical native field policy differs')
    terminal=db.execute("SELECT sha256,document_json FROM source_documents WHERE source_id='terminal'").fetchone()
    if terminal is None or hashlib.sha256(terminal[1].encode()).hexdigest()!=terminal[0]:
        raise ValueError('Recorded tactical terminal provenance differs')
    terminal=json.loads(terminal[1]);fixture=terminal['fixture']
    scope=provenance['fixture_scope']
    if (tuple(fixture.get(k) for k in ('date','competition_id','home_team_id','away_team_id'))
            !=tuple(scope[k] for k in ('date','competition_native_id','home_team_native_id','away_team_native_id'))
            or db.execute('SELECT official_match_unique_id FROM fixtures').fetchall()!=[(fixture.get('official_match_unique_id'),)]
            or terminal['fixed_time_slice']!=metadata.get('fixed_time_slice')):
        raise ValueError('Recorded tactical fixture or fixed cursor differs')
    packet={'fixture':fixture,'save':terminal['save'],'incarnation_id':metadata['source_incarnation_id'],
            'cursor':metadata['fixed_time_slice']}
    # Reuse the producer's native field-label/flag and ordered-side validation;
    # stale or unknown producer policy fails closed instead of silently relabeling.
    producer.validate(document,packet)
    if document.get('state')!='available':
        raise ValueError('Recorded tactical sample unavailable')
    if table!=snapshot_table:
        raise ValueError('Tactical change history unavailable: one verified observation; no before-state recorded')
    sample=document['samples'][0];stamp=sample['observed_at_unix']
    if (type(stamp) not in (int,float) or not math.isfinite(stamp) or not 0<stamp<253402300799
            or not _pin(sample.get('resident_settings_sha256'))
            or sample.get('change_history')!='unknown_single_observation'
            or sample.get('verification')!='typed_ordered_team_managers_and_native_guards_and_consumed_byte_recheck'):
        raise ValueError('Recorded tactical timestamp or verification differs')
    rows=[];window=sample['native_cursor_window']
    for side in sample['sides']:
        mentality=side['mentality'];phases=side['phases']
        if not isinstance(mentality,dict) or not isinstance(phases,dict):
            raise ValueError('Recorded tactical field shape differs')
        if set(phases)-{'in_possession','out_of_possession'}:
            raise ValueError('Recorded tactical phase semantics differ')
        for positions in phases.values():
            if not isinstance(positions,list) or len(positions)>11:
                raise ValueError('Recorded tactical phase coverage differs')
            # Both recorded shapes: with and without the legacy key (observed_tactical_settings).
            if any(not isinstance(position,dict)
                   or set(position)-LEGACY_POSITION_KEYS!={'slot','position','position_mask','base_role'}
                   for position in positions):
                raise ValueError('Recorded tactical phase fields differ')
        rows.append({'snapshot_label':'observation_0','side_index':side['side_index'],'team_native_id':side['team_id'],
            'official_match_unique_id':fixture['official_match_unique_id'],'native_cursor':None,'period':None,
            'observed_at_utc':datetime.fromtimestamp(stamp,timezone.utc).isoformat(),'score_home':None,'score_away':None,
            'mentality_name':mentality.get('name'),'mentality_native_code':mentality.get('native_code'),
            'selected_instructions_json':producer._json(side['options']),'phases_json':producer._json(public_phases(phases)),
            'source_snapshot_sha256':row[0],'native_cursor_window_start':window['start'],
            'native_cursor_window_end':window['end'],'fixed_event_cursor':sample['fixed_event_cursor'],
            'raw_selection_flags_hex':side['raw_selection_flags_hex'],
            'unclassified_selected_bits_json':producer._json(side['unclassified_selected_bits']),
            'unmapped_serialized_bits_json':producer._json(side['unmapped_serialized_bits']),
            'source_incarnation_id':document['source_incarnation_id'],'sample_summary_sha256':sample['summary_sha256'],
            'resident_settings_sha256':sample['resident_settings_sha256']})
    return {'columns':[*columns,*EXTRA_COLUMNS],'rows':rows,'scope':SCOPE,
        'provenance':{'state':'verified_derived_view','source_kind':'verified_recorder_resident_manager_settings',
            'source_document_sha256':row[0],'official_match_unique_id':fixture['official_match_unique_id'],
            'source_incarnation_id':document['source_incarnation_id'],'producer_policy':document['policy'],
            'sample_count':1,'change_history':'unknown_single_observation','exact_change_time_known':False,
            'same_tick_as_events_verified':False,'causal_effect_verified':False,'original_database_unchanged':True}}
