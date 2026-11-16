"""Stored club intensity; native default resolution and applied load stay separate.

The caller owns regular ACTUAL_PLAYER/PERSON identity and current TEAM/lifetime
checks. PLAYER+1EB is a signed stored club setting, independent of the optional
ten-byte additional-focus child and the national setting at+1F5.
"""
import hashlib

OFFSET = 0x1EB
FIELDS = {
    254: (467456, 'No pitch or gym work'),
    0: (466612, 'Half Intensity'),
    1: (467455, 'Normal Intensity'),
    2: (466613, 'Double Intensity'),
}
SCOPE = ('Stored club individual-training selection only. RawFF requests native '
         'default resolution; its applied value is not calculated. No medical '
         'override, workload, attendance, training control or development outcome.')


def decode(raw_code):
    if type(raw_code) is not int or not 0 <= raw_code <= 255:
        raise ValueError('Expected a stored club-intensity byte')
    key, name = FIELDS.get(raw_code, (None, None))
    return dict(raw_code=raw_code, native_code=raw_code if raw_code < 128 else raw_code - 256,
                state='native_default_resolution_requested' if raw_code == 255 else
                      'stored_named_intensity' if name is not None else 'unknown_native_code',
                english_definition_name=name, english_resource_key=key,
                explicit_intensity=False if raw_code == 255 else True if name is not None else None,
                source='stored_regular_player_club_training_intensity', applied_intensity=None,
                workload=None, scope=SCOPE)


def verify_native(read, base):
    for rva, size, digest in NATIVE_GUARDS:
        if hashlib.sha256(read(base + rva, size)).hexdigest() != digest:
            raise ValueError('Stored club-intensity native source changed')


NATIVE_GUARDS = ((47143380, 40, 'fec247ab7acb9a1b7dfc22f14aed54ac189c8b19e849031c2ee8e5b2947e14ee'), (85334193, 24, 'dcdc41aa01d430785fc0e260d9efd151005c6bcb6edb4eb35751ba087af6bd5f'), (26300992, 36, '25ee6d61bb46f47c075e1140b5f58197a8a391d69b668e540490ff8f8f5508d0'), (27302692, 24, '28d20f56bf03a5b9a7909688aaec8def9910292356f4313fed1b52def8fcd8b6'), (27302760, 16, '74b66110412e63a3f07e24656d0778f79b329afd9c0249898b53066a2920ab9d'), (47107204, 956, 'a644b47ebe174dc8e1a151613f0b524e34e80bb3d342f423d7f8317a6ae2b15b'))
