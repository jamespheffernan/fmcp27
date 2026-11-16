"""Hash-attested sparse native manager settings in an approved observed run.

No current tactic lookup, source path access, game attachment or DB writes.
Observation differences bound an interval; they do not date a change precisely.
"""
from datetime import datetime, timezone
from hashlib import sha256
import json

SNAPSHOTS_TABLE='recorded_tactical_snapshots'
CHANGES_TABLE='recorded_tactical_changes'
SNAPSHOT_COLUMNS=('snapshot_label','side_index','team_native_id','official_match_unique_id',
    'native_cursor','period','observed_at_utc','score_home','score_away','mentality_name',
    'mentality_native_code','selected_instructions_json','phases_json','source_snapshot_sha256')
CHANGE_COLUMNS=('side_index','team_native_id','official_match_unique_id','before_cursor','after_cursor',
    'before_period','after_period','before_observed_at_utc','after_observed_at_utc',
    'removed_instructions_json','added_instructions_json','mentality_changed','before_mentality',
    'after_mentality','phase_positions_or_roles_changed','before_snapshot_sha256','after_snapshot_sha256')
SCOPE=('Sparse observed resident engine manager settings. Differences occurred between the two checked observations; '
       'the later sample can be deep into the second half. Exact change time, user intent, kickoff settings, '
       'effective individual overrides and causal effects on chances are not established.')


# Recordings written before 15 November 2026 carry one more key in each phase position: the
# name of an internal flag of the stored role word. The flag is fixed by the role, so the key
# says nothing the role does not. It is accepted on read (the stored document and its hashes
# stay as written), never returned and never written.
LEGACY_POSITION_KEYS=frozenset({'duty'})


def public_phases(phases):
    """Recorded phases as returned: every position without the legacy key."""
    if not isinstance(phases,dict):return phases
    return {name:[{k:v for k,v in position.items() if k not in LEGACY_POSITION_KEYS}
                  if isinstance(position,dict) else position for position in positions]
            if isinstance(positions,list) else positions for name,positions in phases.items()}


def _json(value):
    return json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False)


def _digest(value):
    return sha256(_json(value).encode()).hexdigest()


def project_settings(document,fixture,attestation):
    """Generic projection; an independent native-capture attestation is required."""
    if document.get('state')!='observed_settings_difference_between_two_samples':
        raise ValueError('Unsupported recorded tactical observation source')
    before,after=document['before'],document['after']
    if (type(before.get('cursor'))is not int or type(after.get('cursor'))is not int
            or not 0<=before['cursor']<after['cursor']<1<<32):
        raise ValueError('Recorded tactical observation interval is not ordered')
    wanted=[fixture['home_team_native_id'],fixture['away_team_native_id']]
    match_id=attestation['official_match_unique_id']
    if type(match_id)is not int or not 0<match_id<1<<64:
        raise ValueError('Invalid attested tactical match identity')
    snapshots=[];verified={}
    for label,sample in (('before',before),('after',after)):
        proof=attestation[label]
        public={k:sample[k]for k in ('sha256','cursor','period','score','sides')}
        if _digest(public)!=proof['summary_sha256']:
            raise ValueError('Recorded tactical snapshot differs from attested native sample')
        if [s['team_id']for s in sample['sides']]!=wanted:
            raise ValueError('Recorded tactical team ordering differs from fixture')
        observed=datetime.fromtimestamp(proof['observed_at_unix'],timezone.utc).isoformat()
        verified[label]=[]
        for side,settings in enumerate(sample['sides']):
            options=settings['options'];ids=[v['native_option_id']for v in options]
            if (len(options)>256 or len(ids)!=len(set(ids))
                    or any(type(v)is not int or v<0 for v in ids)):
                raise ValueError('Invalid recorded tactical option identities')
            mentality=settings['mentality']
            row={'snapshot_label':label,'side_index':side,'team_native_id':settings['team_id'],
                 'official_match_unique_id':match_id,'native_cursor':sample['cursor'],'period':sample['period'],
                 'observed_at_utc':observed,'score_home':sample['score']['home'],'score_away':sample['score']['away'],
                 'mentality_name':mentality.get('name'),'mentality_native_code':mentality.get('native_code'),
                 'selected_instructions_json':_json(options),'phases_json':_json(public_phases(settings['phases'])),
                 'source_snapshot_sha256':sample['sha256']}
            snapshots.append(row);verified[label].append((settings,row))
    changes=[]
    for side in(0,1):
        a,ar=verified['before'][side];b,br=verified['after'][side]
        old={o['native_option_id']:o for o in a['options']};new={o['native_option_id']:o for o in b['options']}
        if any(old[k]!=new[k]for k in old.keys()&new.keys()):
            raise ValueError('Same tactical option identity has conflicting captured semantics')
        changes.append({'side_index':side,'team_native_id':wanted[side],'official_match_unique_id':match_id,
            'before_cursor':before['cursor'],'after_cursor':after['cursor'],
            'before_period':before['period'],'after_period':after['period'],
            'before_observed_at_utc':ar['observed_at_utc'],'after_observed_at_utc':br['observed_at_utc'],
            'removed_instructions_json':_json([old[k]for k in sorted(old.keys()-new.keys())]),
            'added_instructions_json':_json([new[k]for k in sorted(new.keys()-old.keys())]),
            'mentality_changed':a['mentality']!=b['mentality'],
            'before_mentality':a['mentality'].get('name'),'after_mentality':b['mentality'].get('name'),
            'phase_positions_or_roles_changed':public_phases(a['phases'])!=public_phases(b['phases']),
            'before_snapshot_sha256':before['sha256'],'after_snapshot_sha256':after['sha256']})
    return snapshots,changes


def derive_tactical_settings(db,provenance,*,table,producer_attestation=None):
    if producer_attestation is not None:
        from .observed_tactical_samples import derive
        return derive(db,provenance,producer_attestation,table=table,
                      snapshot_table=SNAPSHOTS_TABLE,columns=SNAPSHOT_COLUMNS)
    proof=ATTESTED_CAPTURES.get(provenance['capture_id'])
    if proof is None:return None
    row=db.execute("SELECT sha256,document_json FROM source_documents WHERE source_id='tactical_observations'").fetchone()
    if row is None:return None
    digest,raw=row
    if (sha256(raw.encode()).hexdigest()!=proof['stored_document_sha256']
            or digest!=proof['document_sha256']):
        raise ValueError('Recorded tactical source document hash differs')
    terminal_row=db.execute("SELECT document_json FROM source_documents WHERE source_id='terminal'").fetchone()
    if terminal_row is None:raise ValueError('Recorded tactical run terminal identity is absent')
    terminal=json.loads(terminal_row[0])
    if (terminal['raw_source']['match_unique_id']!=proof['official_match_unique_id']
            or {k:terminal['save'][k]for k in proof['career']}!=proof['career']):
        raise ValueError('Recorded tactical career or playthrough identity differs')
    snapshots,changes=project_settings(json.loads(raw),provenance['fixture_scope'],proof)
    columns,rows=(SNAPSHOT_COLUMNS,snapshots)if table==SNAPSHOTS_TABLE else(CHANGE_COLUMNS,changes)
    return {'columns':list(columns),'rows':rows,'scope':SCOPE,
        'provenance':{'state':'verified_derived_view','source_kind':'hash_attested_recorded_native_manager_settings',
            'official_match_unique_id':proof['official_match_unique_id'],'source_document_sha256':digest,
            'observation_cursors':[snapshots[0]['native_cursor'],snapshots[2]['native_cursor']],
            'observation_periods':[snapshots[0]['period'],snapshots[2]['period']],
            'exact_change_time_known':False,'causal_effect_verified':False,'original_database_unchanged':True}}


# Approved immutable original; summaries were independently checked against the
# two complete native-capture bundles with the same career/client/engine/run.
ATTESTED_CAPTURES = {'8e8a4d436d01525f20730c53b5abeaf67d75f8a762413e6da9ceb090236de873': {'document_sha256': 'dd6c05488143669371cbd0e1eaf33ca2778b4965e1ef3f92dbd28d1bbe1a1918',
                                                                      'official_match_unique_id': 2341023333120,
                                                                      'career': {'name': 'Cesar '
                                                                                         'Jules - '
                                                                                         'Newcastle',
                                                                                 'created_date': '2025-10-23',
                                                                                 'created_version': 2223821},
                                                                      'before': {'summary_sha256': 'b65a019ca2d176673287f59ffd5b4229434b6fd68606eceafbd5fab4373b7b29',
                                                                                 'observed_at_unix': 1794089830.556833},
                                                                      'after': {'summary_sha256': '84de5b0968e0852564995973c43ba0b8c27107d64c2ebff20edd63711e220f48',
                                                                                'observed_at_unix': 1794090021.2367911},
                                                                      'stored_document_sha256': 'aa26bcf096bb388f5ff15e6e5840469468bcea9dc6a9e940f038c63a99eda42e'}}
