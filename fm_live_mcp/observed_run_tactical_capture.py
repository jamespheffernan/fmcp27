"""Optional source collection; no historical tactical-change projection.

The caller binds fixture/career/incarnation and rechecks the overall native epoch.
Only resident manager settings are sampled, with an explicit cursor window.
"""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

from . import (active_match_playback, active_pass_network, resident_match_plans,
               prepared_tactics_fields, prepared_tactic_instructions, prepared_tactic_roles)
from .current_match_report import ReportReadSet, _tactics

POLICY_ID = 'same_source_resident_manager_settings_v1'
# This policy's portable field layout and native decoder contract. Change the
# policy ID and add an explicit reader when either semantic contract changes.
# One change was made under the same ID on 15 November 2026: a phase position no
# longer carries the name of the role word's internal flag. The flag is fixed by
# the role, so no meaning was lost, and the query reader takes both shapes
# (observed_tactical_settings.LEGACY_POSITION_KEYS).
NATIVE_GUARD_DIGEST_V1 = 'be34bb45014e7ce1b7859c25da323057e2e2ead7bae4dc357c405921b2cb35fa'


def _json(value):
    return json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False)


def _native_guard_digest():
    """The decoder contract: the guard spans as the source writes them (the pinned build's).

    On a mapped build the address map has re-derived each span for the running game and the
    decoders check those; hashing the rewritten spans made every recording on 27.0.1 lose its
    tactics (found on a live match, 12 November 2026)."""
    from . import address_book
    modules = (resident_match_plans,prepared_tactics_fields,prepared_tactic_instructions,prepared_tactic_roles)
    spans = [(module.__name__,[(rva,raw.hex()) for rva,raw in address_book.pinned_constant(module,'NATIVE_SPANS')])
             for module in modules]
    return hashlib.sha256(_json(spans).encode()).hexdigest()


def _validate_policy(value):
    """Read the known semantic version; producer source bytes are provenance."""
    if (not isinstance(value,dict)
            or set(value)!={'policy_id','native_guard_digest','source_policy_digest'}
            or value['policy_id']!='same_source_resident_manager_settings_v1'
            or value['native_guard_digest']!=NATIVE_GUARD_DIGEST_V1
            or _native_guard_digest()!=NATIVE_GUARD_DIGEST_V1
            or not isinstance(value['source_policy_digest'],str)
            or len(value['source_policy_digest'])!=64
            or any(c not in '0123456789abcdef' for c in value['source_policy_digest'])):
        raise ValueError('Unsupported tactical observation semantic policy')


def policy():
    """Persist native semantics and historical producer provenance separately."""
    modules = (resident_match_plans,prepared_tactics_fields,prepared_tactic_instructions,prepared_tactic_roles)
    source = [(module.__name__,hashlib.sha256(Path(module.__file__).read_bytes()).hexdigest()) for module in modules]
    value = {'policy_id':POLICY_ID,'native_guard_digest':_native_guard_digest(),
            'source_policy_digest':hashlib.sha256(_json(source).encode()).hexdigest()}
    _validate_policy(value)
    return value


def capture(read,base,binding,bound):
    """Return optional checked observation; drift withholds only this scope."""
    try:
        start = active_match_playback.capture(read,base,client=binding['client'])
        if start['state']!='bound_playback_cursor':
            return {'state':'unavailable','reason':'tactical_playback_unavailable'}
        before = start['bound_playback']
        if (active_pass_network._bound_identity(before)!=active_pass_network._bound_identity(bound)
                or before['current_time_slice']<bound['current_time_slice']):
            return {'state':'unavailable','reason':'tactical_owner_or_cursor_changed'}
        checked = ReportReadSet(read)
        plans = resident_match_plans.inspect(checked,base,binding['engine'],binding['team_indices'],
                                             include_raw_instructions=True)
        checked.verify()
        finish = active_match_playback.capture(read,base,client=binding['client'])
        if finish['state']!='bound_playback_cursor':
            return {'state':'unavailable','reason':'tactical_playback_unavailable'}
        after = finish['bound_playback']
        if (active_pass_network._bound_identity(after)!=active_pass_network._bound_identity(bound)
                or after['current_time_slice']<before['current_time_slice']):
            return {'state':'unavailable','reason':'tactical_owner_or_cursor_changed'}
        projected = _tactics(plans)
        sides = []
        for raw,side in zip(plans['sides'],projected['sides'],strict=True):
            instructions = raw['plan']['team_instructions']
            sides.append({'side_index':raw['side_index'],'team_id':side['team']['native_id'],
                'mentality':side['mentality'],'options':instructions['selected_options'],
                'raw_selection_flags_hex':instructions['raw_selection_flags_hex'],
                'unclassified_selected_bits':instructions['unclassified_selected_bits'],
                'unmapped_serialized_bits':instructions['unmapped_serialized_bits'],
                'phases':side['phases']})
        sample = {'native_cursor_window':{'start':before['current_time_slice'],'end':after['current_time_slice']},
                  'fixed_event_cursor':bound['current_time_slice'],
                  'official_match_unique_id':bound['official_match_unique_id'],
                  'observed_at_unix':datetime.now(timezone.utc).timestamp(),
                  'sides':sides,'period':None,'score':None,
                  'resident_settings_sha256':plans['content_sha256'],
                  'verification':'typed_ordered_team_managers_and_native_guards_and_consumed_byte_recheck',
                  'same_tick_as_events_verified':False,'kickoff_plan_verified':False,
                  'effective_individual_overrides_verified':False,'change_history':'unknown_single_observation'}
        stable = {k:v for k,v in sample.items() if k!='observed_at_unix'}
        sample['summary_sha256']=hashlib.sha256(_json(stable).encode()).hexdigest()
        return {'state':'available','product_type':'observed_tactical_samples','schema_version':1,
                'policy':policy(),'samples':[sample]}
    except ValueError:
        return {'state':'unavailable','reason':'tactical_source_validation_failed'}


def semantic(document):
    """Deduplicate equal source selections without treating observation time as data."""
    if document is None:return None
    return {**document,'samples':[{k:v for k,v in sample.items() if k not in ('observed_at_unix',)}
                                  for sample in document.get('samples',[])]}


def validate(document,packet):
    """Reject inconsistent portable proof before host publication."""
    if document.get('state')!='available':return
    _validate_policy(document.get('policy'))
    fixture=packet['fixture'];samples=document.get('samples')
    if (document.get('product_type')!='observed_tactical_samples' or document.get('schema_version')!=1
            or not isinstance(samples,list) or len(samples)!=1
            or document.get('fixture')!=fixture
            or document.get('source_incarnation_id')!=packet['incarnation_id']
            or document.get('career')!={k:packet['save'][k] for k in ('name','created_date','created_version')}):
        raise ValueError('Tactical observation source attestation differs')
    sample=samples[0];window=sample['native_cursor_window']
    if (sample.get('official_match_unique_id')!=fixture['official_match_unique_id']
            or sample.get('fixed_event_cursor')!=packet['cursor']
            or any(type(window.get(k)) is not int for k in ('start','end'))
            or not packet['cursor']<=window['start']<=window['end']<65536
            or sample.get('same_tick_as_events_verified') is not False
            or sample.get('kickoff_plan_verified') is not False
            or sample.get('effective_individual_overrides_verified') is not False
            or sample.get('period') is not None or sample.get('score') is not None):
        raise ValueError('Tactical observation cursor or scope differs')
    stable={k:v for k,v in sample.items() if k not in ('observed_at_unix','summary_sha256')}
    if hashlib.sha256(_json(stable).encode()).hexdigest()!=sample.get('summary_sha256'):
        raise ValueError('Tactical observation summary differs')
    wanted=[fixture['home_team_id'],fixture['away_team_id']]
    if len(sample['sides'])!=2:
        raise ValueError('Tactical observation side coverage differs')
    for side,team in zip(sample['sides'],wanted,strict=True):
        if side['side_index']!=wanted.index(team) or side['team_id']!=team:
            raise ValueError('Tactical observation ordered team differs')
        raw=side['raw_selection_flags_hex']
        if not isinstance(raw,str) or len(raw)!=22 or raw.lower()!=raw:
            raise ValueError('Tactical raw flags unavailable')
        flags=int.from_bytes(bytes.fromhex(raw),'little')
        selected=[i for i in range(1,84) if flags&(1<<i)]
        if ([o['native_option_id'] for o in side['options']]!=selected
                or side['unclassified_selected_bits']!=[i for i in (0,84,85,86,87) if flags&(1<<i)]
                or side['unmapped_serialized_bits']!=([0] if flags&1 else [])):
            raise ValueError('Tactical selected flags were omitted or changed')
        for option in side['options']:
            name=prepared_tactic_instructions.OPTION_NAMES.get(option['native_option_id'])
            if option!={'native_option_id':option['native_option_id'],'name':name,'state':'named' if name else 'no_native_label'}:
                raise ValueError('Tactical instruction label policy differs')


def attestation(packet,receipt):
    document=packet.get('tactical_observation',{})
    if document.get('state')!='available':return None
    validate(document,packet)
    import sqlite3
    db=sqlite3.connect(Path(receipt['path']).as_uri()+'?mode=ro',uri=True)
    try:
        row=db.execute("SELECT sha256,document_json FROM source_documents WHERE source_id='tactical_samples'").fetchone()
        if row is None or hashlib.sha256(row[1].encode()).hexdigest()!=row[0]:
            raise ValueError('Recorded tactical document differs')
        stored=json.loads(row[1])
        if semantic(stored)!=semantic(document):
            raise ValueError('Recorded tactical observation semantics differ')
        document=stored
    finally:
        db.close()
    return {'producer':'verified_observed_recorder','schema_version':1,
            'policy':document['policy'],'source_document_id':'tactical_samples',
            'source_document_sha256':hashlib.sha256(_json(document).encode()).hexdigest(),
            'selection_id':receipt['selection_id'],'source_incarnation_id':packet['incarnation_id']}
