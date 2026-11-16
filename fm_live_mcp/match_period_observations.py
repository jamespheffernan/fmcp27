"""Small fixture-bound host observations, not a source of native period guesses."""
from copy import deepcopy
from ._os_compat import O_NOFOLLOW, current_uid, group_or_other_access, open_fd
from datetime import datetime, timezone
from ._filelock import lock_exclusive
import hashlib
import json
import math
import os
from pathlib import Path
import stat
import struct
import tempfile

CAREER_FIELDS = ('name', 'created_date', 'created_version')
MAX_BYTES = 256 * 1024
MAX_FIXTURES_PER_CAREER = 64
MAX_OBSERVATIONS = 8


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def career_identity(save):
    value = {key: save.get(key) for key in CAREER_FIELDS}
    if not all(isinstance(value[k], str) and value[k] for k in CAREER_FIELDS[:2]) or type(value['created_version']) is not int:
        raise ValueError('Incomplete host observation career identity')
    return value


def career_key(save):
    # Match captured_match_sources.career_id, including its JSON convention.
    return hashlib.sha256(json.dumps(career_identity(save),sort_keys=True).encode()).hexdigest()


def fixture_identity(fixture):
    from datetime import date
    date.fromisoformat(fixture['date'])
    def entity(value):
        index, native = value.get('database_index'), value.get('native_id')
        if type(index) is not int or index < 0 or type(native) is not int or native <= 0:
            raise ValueError('Incomplete canonical period fixture identity')
        return dict(database_index=index, native_id=native, random_id=value.get('random_id') or native)
    return dict(date=fixture['date'], competition=entity(fixture['competition']),
                home_team=entity(fixture['home_team']), away_team=entity(fixture['away_team']))


def process_epoch(bridge):
    process = bridge.process
    return digest(dict(pid=process.pid, started=process.started, executable_stamp=process.executable_stamp,
                       version=process.version, loaded_identity=bridge.world_identity))


def attempt_fingerprints(vectors, events, cursor=None):
    """Fields independently stable across active/retained source; omit pointers."""
    if not isinstance(events, bytes) or len(events) % 56 or len(events) > 30000 * 56 or len(vectors) != 2:
        raise ValueError('Invalid period observation source extent')
    event_map = {}
    for at in range(0, len(events), 56):
        row = events[at:at+56]; identity = struct.unpack_from('<I', row, 44)[0]
        if identity in event_map:raise ValueError('Ambiguous period event identity')
        event_map[identity] = row
    result = []
    for side, vector in enumerate(vectors):
        if not isinstance(vector, bytes) or len(vector) % 48 or len(vector) > 1024 * 48:
            raise ValueError('Invalid period attempt vector')
        for at in range(0, len(vector), 48):
            shot = vector[at:at+48]; identity = struct.unpack_from('<I', shot, 36)[0]
            event = event_map.get(identity)
            if event is None:raise ValueError('Missing period attempt event')
            start, end = struct.unpack_from('<H', event, 34)[0], struct.unpack_from('<H', event, 50)[0]
            if start > end:raise ValueError('Wrapped period attempt clocks')
            if cursor is not None and end >= cursor:continue
            payload = shot[:4] + shot[32:48] + b''.join(event[a:z] for a,z in ((24,32),(34,36),(39,43),(44,52)))
            result.append(dict(event_id=identity, side_index=side, start_tick=start, end_tick=end,
                               semantic_sha256=hashlib.sha256(payload).hexdigest()))
    if len({r['event_id'] for r in result}) != len(result):raise ValueError('Duplicate period attempt ID')
    return sorted(result, key=lambda r:r['event_id'])


def make_observation(save, fixture, bound, split, source, epoch, observed_at):
    from .active_match_shot_timeline import project
    if split.get('state') != 'available':raise ValueError('Verified native period stops required')
    packet = project(source, bound, period_split=split)
    if (packet['state'] != 'available' or not packet.get('native_event_clock_domain_verified')
            or not packet.get('native_ended_exclusive_cutoff_verified')
            or len(packet['source_validation']) != 2
            or any(r['state'] != 'available' for r in packet['source_validation'])):
        raise ValueError('Reconciled bound attempt source required')
    identity = fixture_identity(fixture)
    expected = (identity['date'], identity['competition']['native_id'],
                *((identity[k]['database_index'],identity[k]['native_id']) for k in ('home_team','away_team')))
    actual=source['fixture_identity']
    actual=(actual[0],actual[1],*(tuple(v) for v in actual[2:]))
    if actual != expected:
        raise ValueError('Period capture fixture differs from native CBE fixture')
    prefix = attempt_fingerprints(source['vectors'], source['events'], bound['current_time_slice'])
    if len(prefix) < 3:raise ValueError('Insufficient attempt continuity witnesses')
    intervals=deepcopy(split['period_intervals'])
    markers=split['period_markers']
    if (split.get('period_source',{}).get('simulation_period')=='FullTime' and markers
            and markers[-1].get('next_stop_reason')=='EndOfGame'
            and markers[-1]['stop_time_slice']==bound['current_time_slice']==bound['buffered_max_time_slice']):
        for interval in intervals:
            if interval['period']=='SecondHalf':interval['end_tick']=markers[-1]['stop_time_slice']
    value = dict(schema_version=1, source_kind='host_captured_native_period_observation',
                 capture_method='normal_current_match_query_single_verified_readset',
                 career=career_identity(save), fixture=identity, official_match_unique_id=bound['official_match_unique_id'],
                 process_load_epoch=epoch, observed_at=observed_at,
                 fingerprint_cursor=bound['current_time_slice'], attempt_prefix=prefix,
                 period_markers=markers, intervals=intervals,
                 confidence='native_period_evidence_pending_retained_continuity',
                 clock_domain='native_playback_time_slice', boundary_policy='start<=event_start<=event_end<period_end',
                 source_hashes=dict(events=hashlib.sha256(source['events']).hexdigest(),
                                    vectors=[hashlib.sha256(v).hexdigest() for v in source['vectors']]))
    try:
        from .retained_pass_periods import pass_event_fingerprint
        value['pass_event_fingerprint'] = pass_event_fingerprint(source['events'], bound['current_time_slice'])
    except (ImportError, ValueError, TypeError, KeyError):
        # Optional pass continuity never authorizes or blocks the shot witness.
        pass
    try:
        from .retained_pass_periods import pass_period_report_fingerprint
        value['pass_period_report_fingerprint'] = pass_period_report_fingerprint(source['events'], bound['current_time_slice'])
    except (ImportError, ValueError, TypeError, KeyError):
        pass
    validate_observation(value)
    return value


def validate_observation(value):
    if value.get('capture_method') not in ('normal_current_match_query_single_verified_readset','verified_retrospective_authentic_bundle'):
        raise ValueError('Unrecognised host period observation provenance')
    if value.get('schema_version') != 1 or value.get('clock_domain') != 'native_playback_time_slice':
        raise ValueError('Unsupported host period observation')
    career_identity(value['career']); fixture_identity(value['fixture'])
    uid = value['official_match_unique_id']
    if type(uid) is not int or not 0 < uid < 2**64:raise ValueError('Invalid observed match UID')
    cursor = value['fingerprint_cursor']
    if type(cursor) is not int or not 0 < cursor < 65536:raise ValueError('Unsupported period clock extent')
    prefix = value['attempt_prefix']
    if not isinstance(prefix,list) or not 3 <= len(prefix) <= 2048 or len({r['event_id'] for r in prefix}) != len(prefix):
        raise ValueError('Invalid attempt continuity witnesses')
    for row in prefix:
        if row['side_index'] not in (0,1) or not 0 <= row['start_tick'] <= row['end_tick'] < cursor:
            raise ValueError('Attempt witness outside observation cutoff')
        if len(row['semantic_sha256']) != 64:raise ValueError('Invalid continuity fingerprint')
    pass_fingerprint = value.get('pass_event_fingerprint')
    if pass_fingerprint is not None:
        if (not isinstance(pass_fingerprint, dict)
                or set(pass_fingerprint) != {'schema', 'semantic_sha256', 'event_count', 'cutoff_exclusive'}
                or type(pass_fingerprint['schema']) is not int or pass_fingerprint['schema'] != 1
                or type(pass_fingerprint['event_count']) is not int or not 0 <= pass_fingerprint['event_count'] <= 30000
                or type(pass_fingerprint['cutoff_exclusive']) is not int or pass_fingerprint['cutoff_exclusive'] != cursor
                or not isinstance(pass_fingerprint['semantic_sha256'], str)
                or len(pass_fingerprint['semantic_sha256']) != 64
                or any(c not in '0123456789abcdef' for c in pass_fingerprint['semantic_sha256'])):
            raise ValueError('Invalid optional pass continuity fingerprint')
    report_fingerprint = value.get('pass_period_report_fingerprint')
    if report_fingerprint is not None:
        if (not isinstance(report_fingerprint, dict)
                or set(report_fingerprint) != {'schema', 'report_policy', 'native_flags_mask', 'semantic_sha256', 'event_count', 'cutoff_exclusive'}
                or type(report_fingerprint['schema']) is not int or report_fingerprint['schema'] != 1
                or report_fingerprint['report_policy'] != 'period_network_fields_and_selection_mask8_v1'
                or type(report_fingerprint['native_flags_mask']) is not int or report_fingerprint['native_flags_mask'] != 8
                or type(report_fingerprint['event_count']) is not int or not 0 <= report_fingerprint['event_count'] <= 30000
                or type(report_fingerprint['cutoff_exclusive']) is not int or report_fingerprint['cutoff_exclusive'] != cursor
                or not isinstance(report_fingerprint['semantic_sha256'], str)
                or len(report_fingerprint['semantic_sha256']) != 64
                or any(c not in '0123456789abcdef' for c in report_fingerprint['semantic_sha256'])):
            raise ValueError('Invalid optional report-specific pass continuity fingerprint')
    intervals = value['intervals']
    if not 1 <= len(intervals) <= 2:raise ValueError('No verified normal period intervals')
    known = set()
    for interval in intervals:
        name = interval['period'];start=interval['start_tick'];end=interval['end_tick']
        expected={'FirstHalf':'verified_first_half_boundary','SecondHalf':'verified_second_half_start'}
        if name not in expected or name in known or interval['state'] != expected[name]:raise ValueError('Unverified period interval')
        known.add(name)
        if interval['official_match_unique_id'] != uid or interval['time_slice_domain'] != value['clock_domain']:
            raise ValueError('Period interval has a different native match/domain')
        if type(start) is not int or start < 0 or (end is not None and (type(end) is not int or end <= start)):
            raise ValueError('Invalid period interval extent')
    markers=value['period_markers']
    if not isinstance(markers,list) or not 2<=len(markers)<=4:
        raise ValueError('Unverified native period marker sequence')
    reasons=[r['next_stop_reason']for r in markers]
    if reasons[0]not in('StartOfPeriod','StartOfGame') or reasons[1:]not in (['EndOfPeriod'],['EndOfPeriod','StartOfPeriod'],['EndOfPeriod','StartOfPeriod','EndOfGame']):
        raise ValueError('Ambiguous native period marker sequence')
    ticks=[r['stop_time_slice']for r in markers]
    if any(type(t)is not int or not 0<=t<65536 for t in ticks)or any(a>=b for a,b in zip(ticks,ticks[1:])):
        raise ValueError('Invalid native stop marker clocks')
    for interval in intervals:
        expected_start=ticks[0]if interval['period']=='FirstHalf'else ticks[2]if len(ticks)>=3 else None
        expected_end=ticks[1]if interval['period']=='FirstHalf'else ticks[3]if len(ticks)==4 else None
        if (interval['start_tick'],interval['end_tick'])!=(expected_start,expected_end):
            raise ValueError('Interval does not match recorded native stops')
    # Preserve only closed intervals for retrospective assignments. A later
    # terminal native stop can close the second half; no final-score inference.
    return value


class ObservationStore:
    """Exact-key reads only. At most8 observations/1MiB per career+fixture."""
    def __init__(self, root=None):
        self.root = Path(root) if root is not None else (
            Path(os.environ['FMCP_CACHE_DIR']) / 'period-observations-v1' if os.environ.get('FMCP_CACHE_DIR')
            else Path.home()/'.local/share/fm-live/period-observations-v1')

        if not self.root.is_absolute():raise ValueError('Host period cache root must be absolute')

    def path(self, career, fixture):
        return self.root / career_key(career) / (digest(fixture_identity(fixture))+'.json')

    def _load(self,path):
        try:descriptor=open_fd(path,os.O_RDONLY|O_NOFOLLOW)
        except FileNotFoundError:return dict(version=1,observations={},links={})
        except OSError as error:raise ValueError('Invalid host period file')from error
        try:
            info=os.fstat(descriptor)
            if not stat.S_ISREG(info.st_mode)or info.st_size>MAX_BYTES or info.st_uid!=current_uid()or group_or_other_access(info):raise ValueError('Invalid host period file')
            with os.fdopen(descriptor,'rb',closefd=False)as stream:raw=stream.read(MAX_BYTES+1)
            after=os.fstat(descriptor);current=path.lstat()
            if len(raw)>MAX_BYTES or (info.st_ino,info.st_size,info.st_mtime_ns)!=(after.st_ino,after.st_size,after.st_mtime_ns)or current.st_ino!=info.st_ino:
                raise ValueError('Host period file changed while reading')
        finally:os.close(descriptor)
        value=json.loads(raw)
        if (value.get('version')!=1 or not isinstance(value.get('observations'),dict)
                or not isinstance(value.get('links'),dict)or len(value['links'])>MAX_OBSERVATIONS
                or len(value['observations'])>MAX_OBSERVATIONS):raise ValueError('Invalid host period index')
        for key,observation in value['observations'].items():
            validate_observation(observation)
            if digest(observation)!=key:raise ValueError('Host period observation digest mismatch')
        return value

    def _mutate(self,career,fixture,change):
        path=self.path(career,fixture)
        self.root.mkdir(parents=True,exist_ok=True,mode=0o700)
        path.parent.mkdir(exist_ok=True,mode=0o700)
        for directory in (self.root,path.parent):
            info=directory.lstat()
            if (not stat.S_ISDIR(info.st_mode)or directory.is_symlink()
                    or info.st_uid!=current_uid()or group_or_other_access(info)):raise ValueError('Unsafe host period directory')
        lock=open_fd(path.parent/'.period.lock',os.O_CREAT|os.O_RDWR|O_NOFOLLOW,0o600)
        try:
            if not stat.S_ISREG(os.fstat(lock).st_mode):raise ValueError('Invalid host period lock')
            lock_exclusive(lock)
            index_path=path.parent/'.index.json'
            try:
                index_info=index_path.lstat()
                if not stat.S_ISREG(index_info.st_mode)or index_info.st_size>16384:raise ValueError('Invalid host period career index')
                index=json.loads(index_path.read_bytes())
            except FileNotFoundError:index=[]
            if not isinstance(index,list)or len(index)>MAX_FIXTURES_PER_CAREER or any(not isinstance(v,str)or len(v)!=64 for v in index):raise ValueError('Invalid host period career index')
            key=path.stem
            if key not in index:
                if len(index)>=MAX_FIXTURES_PER_CAREER:raise ValueError('Host period career fixture budget exceeded')
                index.append(key)
                descriptor,index_temp=tempfile.mkstemp(dir=path.parent,prefix='.index-')
                try:
                    with os.fdopen(descriptor,'wb')as out:out.write(canonical(sorted(index)));out.flush();os.fsync(out.fileno())
                    os.replace(index_temp,index_path)
                finally:
                    if os.path.exists(index_temp):os.unlink(index_temp)
            value=self._load(path);result=change(value)
            raw=canonical(value)
            if len(raw)>MAX_BYTES:raise ValueError('Host period observation budget exceeded')
            fd,name=tempfile.mkstemp(dir=path.parent,prefix='.period-')
            try:
                with os.fdopen(fd,'wb')as out:out.write(raw);out.flush();os.fsync(out.fileno())
                os.replace(name,path)
            finally:
                if os.path.exists(name):os.unlink(name)
            return result
        finally:os.close(lock)

    def save(self,observation):
        validate_observation(observation)
        def change(value):
            # One immutable witness per native interval state: normal repeated
            # reads do not fill the store with an advancing second-half prefix.
            state_key=digest([observation['official_match_unique_id'],observation['process_load_epoch'],observation['intervals'],observation['period_markers']])
            for key,old in value['observations'].items():
                if digest([old['official_match_unique_id'],old['process_load_epoch'],old['intervals'],old['period_markers']])==state_key:
                    shared_cursor=min(old['fingerprint_cursor'],observation['fingerprint_cursor'])
                    old_prefix=[r for r in old['attempt_prefix']if r['end_tick']<shared_cursor]
                    new_prefix=[r for r in observation['attempt_prefix']if r['end_tick']<shared_cursor]
                    # A report-specific witness is independent of the preserved
                    # strict full-flags witness. Never overwrite either record.
                    witness_name=('pass_period_report_fingerprint' if observation.get('pass_period_report_fingerprint') else 'pass_event_fingerprint')
                    old_pass=old.get(witness_name);new_pass=observation.get(witness_name)
                    pass_compatible=not new_pass or (old_pass is not None and (old_pass['cutoff_exclusive']!=new_pass['cutoff_exclusive'] or old_pass==new_pass))
                    if old_prefix==new_prefix and pass_compatible:
                        return dict(state='already_captured',capture_id=key)
            if len(value['observations'])>=MAX_OBSERVATIONS:raise ValueError('Host period observation budget exceeded')
            key=digest(observation);value['observations'][key]=observation
            return dict(state='captured',capture_id=key)
        return self._mutate(observation['career'],observation['fixture'],change)

    def observations(self,career,fixture):
        return self._load(self.path(career,fixture))

    def finalize(self,career,fixture,native_key,capture_id,retained_fingerprint):
        def change(value):
            if capture_id not in value['observations']:raise ValueError('Observation disappeared during finalization')
            key=f'{native_key}:{retained_fingerprint}';old=value['links'].get(key)
            if old is not None and old['retained_fingerprint']!=retained_fingerprint:raise ValueError('Conflicting retained period linkage')
            ids=set(old['capture_ids']if old else[])
            ids.add(capture_id)
            value['links'][key]=dict(capture_ids=sorted(ids),retained_fingerprint=retained_fingerprint)
        self._mutate(career,fixture,change)


def link_retained(store, save, fixture, native_key, source, shots, epoch):
    career=career_identity(save);identity=fixture_identity(fixture)
    document=store.observations(career,identity);all_attempts=attempt_fingerprints(source['vectors'],source['events'])
    fingerprint=digest(all_attempts);linked=[];reasons=[];pass_states={}
    for capture_id,value in document['observations'].items():
        if value['career']!=career or value['fixture']!=identity:raise ValueError('Host index identity mismatch')
        prefix=[r for r in all_attempts if r['end_tick']<value['fingerprint_cursor']]
        if prefix!=value['attempt_prefix']:
            reasons.append('attempt_event_semantic_prefix_mismatch');continue
        # Metric families stay separate. A mutable, non-consumed pass flag
        # cannot erase an independently matching shot/period observation.
        family=dict(strict_full_flags='not_captured',period_network_fields='not_captured')
        try:
            from .retained_pass_periods import pass_event_fingerprint, pass_period_report_fingerprint
        except ImportError:
            family=dict(strict_full_flags='validator_unavailable',period_network_fields='validator_unavailable')
        else:
            for name,field,projector in [('strict_full_flags','pass_event_fingerprint',pass_event_fingerprint),
                                        ('period_network_fields','pass_period_report_fingerprint',pass_period_report_fingerprint)]:
                witness=value.get(field)
                if witness is not None:
                    family[name]='matched' if witness==projector(source['events'],witness['cutoff_exclusive']) else 'mismatch'
        pass_states[capture_id]=family
        pin=document['links'].get(f'{native_key}:{fingerprint}')
        if value['process_load_epoch']!=epoch and not (pin and capture_id in pin['capture_ids']and pin['retained_fingerprint']==fingerprint):
            reasons.append('unfinalized_observation_process_or_load_changed');continue
        linked.append((capture_id,value))
    if not linked:return dict(state='unavailable_no_verified_host_period_link',reasons=sorted(set(reasons)) or ['no_captured_period_observation'],periods=None,shot_periods=None)
    # Multiple observations may corroborate the same intervals. Conflicting
    # captured boundaries never become a guessed best match.
    if len({v['official_match_unique_id']for _,v in linked})!=1:
        return dict(state='unavailable_ambiguous_native_match_observations',periods=None,shot_periods=None)
    closed={}
    for _,value in linked:
        for interval in value['intervals']:
            if interval['end_tick']is None:continue
            key=interval['period'];extent=(interval['start_tick'],interval['end_tick'])
            if key in closed and closed[key]!=extent:return dict(state='unavailable_conflicting_period_observations',periods=None,shot_periods=None)
            closed[key]=extent
    selected=max(linked,key=lambda pair:(len([i for i in pair[1]['intervals']if i['end_tick']is not None]),pair[1]['fingerprint_cursor'],pass_states[pair[0]]['period_network_fields']=='matched',pass_states[pair[0]]['strict_full_flags']=='matched'))
    capture_id,observation=selected
    pin=document['links'].get(f'{native_key}:{fingerprint}')
    if pin is not None and pin['retained_fingerprint']!=fingerprint:
        return dict(state='unavailable_conflicting_retained_pin',periods=None,shot_periods=None)
    store.finalize(career,identity,native_key,capture_id,fingerprint)
    rows=[]
    for shot in shots:
        start,end=shot['native_clock_start_raw'],shot['native_clock_end_raw']
        assigned=[period for period,(a,b)in closed.items()if a<=start<=end<b]
        rows.append(dict(shot,period=assigned[0]if len(assigned)==1 else None,
                         period_state='verified_retrospective_continuity'if len(assigned)==1 else 'unknown_boundary_or_unobserved_interval'))
    periods=[]
    for period,(start,end)in sorted(closed.items()):
        sides=[]
        for side in(0,1):
            ss=[r for r in rows if r['period']==period and r['side_index']==side]
            sides.append(dict(side_index=side,shots=len(ss),shots_on_target=sum(r['native_category_code']in(1,4)for r in ss),
                              shot_goals=sum(r['native_category_code']==1 for r in ss),expected_goals_sum_computed=math.fsum(r['expected_goals']for r in ss)))
        periods.append(dict(period=period,start_tick=start,end_tick=end,sides=sides))
    return dict(state='verified_retrospective_continuity',capture_id=capture_id,native_match_key=native_key,
                source_kind='host_captured_period_observation',confidence='verified_retrospective_continuity',
                metric_family_continuity=dict(shots='matched',passes=pass_states[capture_id]),
                clock_domain='native_playback_time_slice',official_match_unique_id=observation['official_match_unique_id'],link_state='verified_retrospective_continuity',
                fixture=identity,periods=periods,intervals=[dict(period=p,start_tick=a,end_tick=b)for p,(a,b)in closed.items()],
                shot_periods=rows,unknown_boundary_attempts=sum(r['period']is None for r in rows),
                provenance=dict(career_id=career_key(career),observation_time=observation['observed_at'],capture_method=observation['capture_method'],
                                official_match_unique_id=observation['official_match_unique_id'],retained_semantic_fingerprint=fingerprint,
                                cross_observation=observation.get('cross_observation',False),pass_continuity=pass_states[capture_id],
                                native_period_markers=observation['period_markers'],source_hashes=observation['source_hashes'],
                                binding='same_process_load_prefix_match_or_previously_finalized_retained_fingerprint',
                                period_aggregate_oracle=False,atomic=False),
                limits='Host-captured native stops joined retrospectively to the exact retained source; no inferred periods, minute conversion or tactical causation. Unobserved intervals stay unknown.')
