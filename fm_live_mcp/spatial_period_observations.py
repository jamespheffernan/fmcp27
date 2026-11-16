"""Bounded spatial-only host records; legacy shot/pass validators stay intact."""
import json
from ._os_compat import O_NOFOLLOW, current_uid, group_or_other_access, open_fd
import os
from pathlib import Path
import stat

from .match_period_observations import ObservationStore, MAX_BYTES, MAX_OBSERVATIONS, digest
from .spatial_period_witness import WITNESS_KEY, validate_witness


class SpatialPeriodStore(ObservationStore):
    """Own namespace/validation; reuse existing locked bounded publication.

    report() only reads this store. A reviewed root capture hook may publish a
    new prospective record after all source/read-set/process checks succeed.
    """
    def __init__(self, root=None):
        if root is None:
            root = (Path(os.environ['FMCP_CACHE_DIR']) / 'spatial-period-observations-v1'
                    if os.environ.get('FMCP_CACHE_DIR') else
                    Path.home() / '.local/share/fm-live/spatial-period-observations-v1')
        super().__init__(root=root)

    def _load(self, path):
        try: descriptor = open_fd(path, os.O_RDONLY | O_NOFOLLOW)
        except FileNotFoundError: return dict(version=1, observations={}, links={})
        except OSError as error: raise ValueError('Invalid spatial period file') from error
        try:
            before = os.fstat(descriptor)
            if (not stat.S_ISREG(before.st_mode) or before.st_size > MAX_BYTES
                    or before.st_uid != current_uid() or group_or_other_access(before)):
                raise ValueError('Unsafe spatial period file')
            with os.fdopen(descriptor, 'rb', closefd=False) as stream: raw = stream.read(MAX_BYTES + 1)
            after, current = os.fstat(descriptor), path.lstat()
            identity = lambda value: (value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns)
            if (len(raw) > MAX_BYTES or identity(before) != identity(after)
                    or not stat.S_ISREG(current.st_mode) or identity(current) != identity(before)):
                raise ValueError('Spatial period file changed while reading')
        finally: os.close(descriptor)
        value = json.loads(raw)
        if (type(value) is not dict or set(value) != {'version', 'observations', 'links'}
                or type(value['version']) is not int or value['version'] != 1
                or type(value['observations']) is not dict or len(value['observations']) > MAX_OBSERVATIONS
                or value['links'] != {}):
            raise ValueError('Invalid spatial period document')
        for key, observation in value['observations'].items():
            self._validate_record(observation)
            if digest(observation) != key: raise ValueError('Spatial period record digest mismatch')
        return value

    @staticmethod
    def _validate_record(observation):
        if (type(observation) is not dict
                or observation.get('source_kind') != 'host_captured_native_spatial_period_observation'
                or validate_witness(observation) is None):
            raise ValueError('A prospective spatial-only observation is required')

    def save(self, observation):
        self._validate_record(observation)
        def change(value):
            for key, old in value['observations'].items():
                if (old['process_load_epoch'] == observation['process_load_epoch']
                        and old['official_match_unique_id'] == observation['official_match_unique_id']
                        and old['intervals'] == observation['intervals']
                        and old[WITNESS_KEY]['tracking_fingerprint'] == observation[WITNESS_KEY]['tracking_fingerprint']):
                    return dict(state='already_captured', capture_id=key)
            if len(value['observations']) >= MAX_OBSERVATIONS:
                raise ValueError('Spatial period observation budget exceeded')
            key = digest(observation)
            value['observations'][key] = observation
            return dict(state='captured', capture_id=key)
        return self._mutate(observation['career'], observation['fixture'], change)
