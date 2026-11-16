"""Explicit original references for distinct observed-run artifacts; no scanning."""
from ._filelock import lock_exclusive
from ._os_compat import change_time_ns, open_fd, O_NOFOLLOW
import json
import os
from pathlib import Path
import sqlite3
import tempfile

from .captured_match_registry import _identifier, _regular_file, _sha256
from .captured_match_sources import _fingerprint

REGISTRY_PATH = Path.home()/'.local/share/fm-live/observed-match-runs.json'
MAX_BYTES = 1024*1024


def inspect_original(path):
    path = Path(path).expanduser().absolute()
    if any(Path(str(path)+s).exists() for s in ('-wal','-journal')):
        raise ValueError('Observed original has an active journal')
    digest, identity = _fingerprint(path)
    db = sqlite3.connect(path.as_uri()+'?mode=ro', uri=True)
    try:
        db.execute('PRAGMA query_only=ON'); db.execute('PRAGMA trusted_schema=OFF')
        if db.execute('PRAGMA quick_check').fetchone() != ('ok',):
            raise ValueError('Observed original integrity failed')
        metadata = {k:json.loads(v) for k,v in db.execute('SELECT key,value_json FROM metadata')}
        if (metadata.get('product_type') != 'observed_native_match_run' or metadata.get('schema_version') != 1
                or metadata.get('not_retained_match_export') is not True
                or metadata.get('registered_retained_capture') is not False):
            raise ValueError('Not a distinct observed-run product')
        fixtures = db.execute('SELECT date,competition_id,home_team_id,away_team_id FROM fixtures').fetchall()
        if len(fixtures) != 1:
            raise ValueError('Observed original requires exactly one fixture')
        terminal = db.execute("SELECT sha256,document_json FROM source_documents WHERE source_id='terminal'").fetchone()
        if terminal is None:
            raise ValueError('Missing observed provenance')
        raw = terminal[1]
        import hashlib
        if hashlib.sha256(raw.encode()).hexdigest() != terminal[0]:
            raise ValueError('Observed source document hash differs')
        save = json.loads(raw).get('save', {})
        career = {k:save[k] for k in ('name','created_date','created_version')}
        for key in ('current_date','last_saved_date'):
            if key not in save:
                raise ValueError('Incomplete captured career')
        selection = metadata.get('selection_id')
        _sha256(selection)
        count = db.execute('SELECT count(*) FROM completed_pass_events').fetchone()[0]
    finally:
        db.close()
    if _fingerprint(path) != (digest,identity):
        raise ValueError('Observed original changed during validation')
    return {'path':str(path), 'sha256':digest, 'fixture':list(fixtures[0]), 'career':career,
            'selection_id':selection, 'completed_pass_events':count}


def load_registrations():
    try:
        before = _regular_file(REGISTRY_PATH, MAX_BYTES)
    except FileNotFoundError:
        return {}
    raw = REGISTRY_PATH.read_bytes()
    after = REGISTRY_PATH.lstat()
    if (before.st_ino,before.st_size,before.st_mtime_ns,change_time_ns(before)) != (after.st_ino,after.st_size,after.st_mtime_ns,change_time_ns(after)):
        raise ValueError('Observed registry changed during read')
    document = json.loads(raw)
    if document.get('version') != 1 or not isinstance(document.get('sources'),dict) or len(document['sources']) > 256:
        raise ValueError('Unsupported observed registry')
    from .observed_match_runs import SOURCES
    result = {}
    for source_id,row in document['sources'].items():
        _identifier(source_id)
        if source_id in SOURCES or not isinstance(row,dict):
            raise ValueError('Protected or invalid observed registration')
        _sha256(row.get('sha256')); _sha256(row.get('selection_id'))
        if (not isinstance(row.get('path'),str) or not Path(row['path']).is_absolute()
                or not isinstance(row.get('fixture'),list) or len(row['fixture']) != 4
                or not isinstance(row.get('career'),dict)):
            raise ValueError('Incomplete observed registration')
        if row.get('producer_attestation') is not None:
            _validate_producer_attestation(row,row['producer_attestation'],check_original=False)
        if row.get('pass_attempt_attestation') is not None:
            from .observed_pass_attempts import validate_attestation
            validate_attestation(row,row['pass_attempt_attestation'],check_original=False)
        result[source_id] = {**row,'path':Path(row['path'])}
    return result


def register_original(path, source_id, sha256, *, producer_attestation=None, pass_attempt_attestation=None):
    _identifier(source_id); _sha256(sha256)
    from .observed_match_runs import SOURCES
    if source_id in SOURCES:
        raise ValueError('Cannot replace a protected observed source')
    entry = inspect_original(path)
    if producer_attestation is not None:
        _validate_producer_attestation(entry,producer_attestation)
        entry['producer_attestation']=producer_attestation
    if pass_attempt_attestation is not None:
        from .observed_pass_attempts import validate_attestation
        validate_attestation(entry,pass_attempt_attestation)
        entry['pass_attempt_attestation']=pass_attempt_attestation
    if entry['sha256'] != sha256:
        raise ValueError('Explicit observed hash does not match original')
    REGISTRY_PATH.parent.mkdir(parents=True,exist_ok=True)
    lock = open_fd(str(REGISTRY_PATH)+'.lock', os.O_CREAT|os.O_RDWR|O_NOFOLLOW,0o600)
    try:
        lock_exclusive(lock)
        entries = load_registrations()
        entries = {key:{**row,'path':str(row['path'])} for key,row in entries.items()}
        if source_id in entries:
            if entries[source_id] != entry:
                raise ValueError('Observed source ID already refers to another original')
            return entry
        if len(entries) >= 256:
            raise ValueError('Observed registration budget exceeded')
        entries[source_id] = entry
        raw = json.dumps({'version':1,'sources':entries},sort_keys=True).encode()
        if len(raw) > MAX_BYTES:
            raise ValueError('Observed registry byte budget exceeded')
        fd,name = tempfile.mkstemp(prefix='.observed-registry-',dir=REGISTRY_PATH.parent)
        try:
            with os.fdopen(fd,'wb') as stream:
                stream.write(raw);stream.flush();os.fsync(stream.fileno())
            os.replace(name,REGISTRY_PATH)
        finally:
            Path(name).unlink(missing_ok=True)
    finally:
        os.close(lock)
    return entry


def _validate_producer_attestation(entry,proof,*,check_original=True):
    if (not isinstance(proof,dict) or proof.get('producer')!='verified_observed_recorder'
            or proof.get('schema_version')!=1 or proof.get('source_document_id')!='tactical_samples'
            or proof.get('selection_id')!=entry['selection_id']):
        raise ValueError('Invalid observed producer attestation')
    _sha256(proof.get('source_document_sha256'));_sha256(proof.get('source_incarnation_id'))
    policy=proof.get('policy',{})
    if policy.get('policy_id')!='same_source_resident_manager_settings_v1':
        raise ValueError('Unsupported observed tactical collection policy')
    _sha256(policy.get('native_guard_digest'));_sha256(policy.get('source_policy_digest'))
    if check_original:
        db=sqlite3.connect(Path(entry['path']).as_uri()+'?mode=ro',uri=True)
        try:
            db.execute('PRAGMA query_only=ON');db.execute('PRAGMA trusted_schema=OFF')
            row=db.execute('SELECT sha256,document_json FROM source_documents WHERE source_id=?',(proof['source_document_id'],)).fetchone()
            import hashlib
            if row is None or row[0]!=proof['source_document_sha256'] or hashlib.sha256(row[1].encode()).hexdigest()!=row[0]:
                raise ValueError('Observed tactical source document differs')
            document=json.loads(row[1])
            if (document.get('state')!='available' or document.get('source_incarnation_id')!=proof['source_incarnation_id']
                    or document.get('policy')!=policy or document.get('career')!=entry['career']):
                raise ValueError('Observed tactical source identity differs')
        finally:
            db.close()
