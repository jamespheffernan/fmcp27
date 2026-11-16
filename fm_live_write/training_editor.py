"""The first game edit: one guarded stored club training-intensity byte.

No arbitrary address, data payload, native call, allocation or automatic retry.
The native helper checks the complete selection readset before and after writing.
Execution is non-atomic; a post-write failure must report that a change may exist.
"""
from datetime import datetime, timezone
import json
import os
import struct
import subprocess
import uuid

from fm_live_mcp.bridge import BridgeError, ROOT
from fm_live_mcp.individual_training_intensity import decode
from fm_live_mcp.live_individual_training import get_player_individual_training

CHOICES = {'half': 0, 'normal': 1, 'double': 2, 'rest': 254, 'default': 255}


def encode_request(pid, player, table, before, after, guards):
    if (type(pid) is not int or not 0 < pid <= 2**31 - 1
            or type(player) is not int or not 4096 <= player < 2**64 - 0x400 or player % 8
            or type(table) is not int or not 4096 <= table < 2**64 or table % 8
            or type(before) is not int or before not in CHOICES.values()
            or type(after) is not int or after not in CHOICES.values()
            or not 1 <= len(guards) <= 8192):
        raise BridgeError('Invalid bounded training edit request.')
    parts = [struct.pack('<8sIQQBBI', b'FMTEDIT1', pid, player, table, before, after, len(guards))]
    total = 0
    for (address, length), data in sorted(guards.items()):
        if (type(address) is not int or type(length) is not int
                or not 4096 <= address < 2**64 - length or not 1 <= length <= 16384
                or type(data) is not bytes or len(data) != length):
            raise BridgeError('Invalid training edit source guard.')
        total += length
        parts.extend((struct.pack('<QI', address, length), data))
    if total > 4 * 1024 * 1024:
        raise BridgeError('Training edit source guard budget exceeded.')
    return b''.join(parts)


def _audit(path, record):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('a', encoding='utf-8') as stream:
        stream.write(json.dumps(record, sort_keys=True) + '\n')
        stream.flush()
        os.fsync(stream.fileno())


def _audit_outcome(path, record):
    try:
        _audit(path, record)
    except OSError as exc:
        raise BridgeError(f'Write was attempted but its outcome receipt failed; inspect the selection and do not retry automatically. Receipt: {path}: {exc}') from exc


def set_player_training_intensity(bridge, session_id, player_ref, intensity,
                                  expected_raw_code, coach_name=None, *, dry_run=False):
    """Set a known stored selection on one direct managed ordinary player.

    expected_raw_code is mandatory and comes from a fresh training query.
    A successful write is followed by a separate source query. Stored selection
    is not applied workload or evidence that the game has saved it to disk.
    """
    if type(intensity) is not str or intensity not in CHOICES:
        raise BridgeError('Choose half, normal, double, rest or default.')
    if type(expected_raw_code) is not int or expected_raw_code not in CHOICES.values():
        raise BridgeError('expected_raw_code must be a known raw selection: 0, 1, 2, 254 or 255.')
    if type(dry_run) is not bool:
        raise BridgeError('dry_run must be Boolean.')
    if type(player_ref) is not str or not player_ref:
        raise BridgeError('Supply one player_ref from the managed squad.')
    with bridge.lock:
        guards = {}
        before = get_player_individual_training(bridge, session_id, [player_ref], coach_name,
                                                _capture=guards, _for_edit=True)
        row, = before['players']
        old = row['club_training_intensity']['raw_code']
        if old != expected_raw_code:
            raise BridgeError(f'Training selection changed: expected {expected_raw_code}, found {old}; no write attempted.')
        process = bridge._current(session_id)
        binding = bridge.player_refs[player_ref]
        player = binding['address']
        payload = encode_request(process.pid, player, binding['tables'][0], old, CHOICES[intensity], guards)
        result = dict(player_ref=player_ref, name=row['display_name'], coach=before['coach'],
                      save=before['save'], before=decode(old), requested=decode(CHOICES[intensity]),
                      dry_run=dry_run, atomic=False, save_requested=False,
                      saved_file_persistence_verified=False,
                      scope='Stored club training selection only; applied workload and development are unverified.')
        if dry_run:
            return dict(result, state='validated_without_write', write_performed=False)
        helper = bridge.helper.parent / 'fm_training_editor'
        if not helper.is_file():
            raise BridgeError('Training editor missing; run sh scripts/build_training_editor.sh. No write attempted.')
        edit_id = uuid.uuid4().hex
        audit = ROOT / 'evidence' / 'training-edits' / f'{edit_id}.jsonl'
        _audit(audit, dict(event='intent', edit_id=edit_id, observed_at=datetime.now(timezone.utc).isoformat(), **result))
        try:
            bridge._current(session_id)
            completed = subprocess.run([str(helper)], input=payload, capture_output=True, timeout=30)
            native = json.loads(completed.stdout)
            _audit(audit, dict(event='native_result', returncode=completed.returncode, result=native))
        except (OSError, subprocess.SubprocessError, ValueError) as exc:
            raise BridgeError(f'Edit outcome unknown; do not retry automatically. Inspect the selection. Receipt: {audit}: {exc}') from exc
        if completed.returncode or native.get('ok') is not True:
            raise BridgeError(f'Edit did not verify: {native}. Do not retry automatically. Receipt: {audit}')
        try:
            after = get_player_individual_training(bridge, session_id, [player_ref], coach_name)
            actual, = after['players']
            if (after['save'] != before['save'] or actual['native_identity'] != row['native_identity']
                    or actual['club_training_intensity']['raw_code'] != CHOICES[intensity]):
                raise ValueError('Fresh training readback differs')
        except (BridgeError, ValueError) as exc:
            _audit_outcome(audit, dict(event='readback_unverified', reason=str(exc)))
            raise BridgeError(f'Write occurred but fresh readback failed; inspect before any further edit. Receipt: {audit}') from exc
        _audit_outcome(audit, dict(event='verified', after=actual['club_training_intensity']))
        return dict(result, state=native['state'], write_performed=native['write_performed'],
                    after=actual['club_training_intensity'], fresh_readback_verified=True,
                    receipt_path=str(audit))
