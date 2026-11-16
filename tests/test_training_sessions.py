"""Training labels retain signed codes and depend on verified bundle resources."""
import hashlib
from pathlib import Path
import plistlib

import pytest

from fm_live_mcp import players, training_sessions as sessions, world


@pytest.fixture
def native_memory():
    base = 0x100000000
    cells = {}
    def put(address, data):
        cells.update({address + i: byte for i, byte in enumerate(data)})
    def read(address, size):
        return bytes(cells[address+i] for i in range(size))
    for rva, raw in sessions.NATIVE_SPANS:
        put(base+rva, raw)
    return {'base': base, 'read': read, 'put': put, 'cells': cells}


def test_native_guards_verify_and_readset_detects_later_mutation(native_memory):
    m = native_memory
    seen = world.ReadSet(m['read'])
    sessions.verify_native(seen, m['base'])
    rva, raw = sessions.NATIVE_SPANS[-1]
    m['put'](m['base']+rva, bytes([raw[0] ^ 1]))
    with pytest.raises(ValueError):
        seen.verify()


@pytest.mark.parametrize('span', range(16))
def test_every_native_span_rejects_changed_bytes(native_memory, span):
    m = native_memory
    rva, raw = sessions.NATIVE_SPANS[span]
    m['put'](m['base']+rva+len(raw)-1, bytes([raw[-1] ^ 1]))
    with pytest.raises(ValueError, match='native route changed'):
        sessions.verify_native(m['read'], m['base'])


@pytest.mark.parametrize('base', [True, None, 0, 4095, 4097, -4096, 1 << 64, (1 << 64)-4096])
def test_native_base_rejected_before_reads(base):
    def forbidden(*args):
        raise AssertionError('Invalid base read native memory')
    with pytest.raises(ValueError, match='native base'):
        sessions.verify_native(forbidden, base)


def test_short_native_read_rejected(native_memory):
    with pytest.raises(ValueError, match='native route changed'):
        sessions.verify_native(lambda address, size: native_memory['read'](address, size)[:-1], native_memory['base'])


def test_reader_errors_propagate(native_memory):
    def failed(*args):
        raise OSError('memory source unavailable')
    with pytest.raises(OSError, match='memory source unavailable'):
        sessions.verify_native(failed, native_memory['base'])


# Frozen native branch/resource proof; independent of production's dictionary.
EXPECTED_NAMES = [
    (0, 'Passing Style'),
    (1, 'Build Up'),
    (2, 'Chance Creation'),
    (3, 'In Possession Shape'),
    (4, 'Line of Engagement'),
    (5, 'Pressing Intensity'),
    (6, 'Pressing Trap'),
    (7, 'Out Of Possession Shape'),
    (100, 'Press Avoidance'),
    (101, 'Ball Progression'),
    (102, 'Final Third'),
    (103, 'Defensive Block'),
    (104, 'Defensive Positioning'),
    (105, 'Defensive Engagement'),
    (106, 'Corners'),
    (107, 'Free Kicks'),
    (108, 'Penalties'),
    (200, 'Individual Development'),
    (201, 'Attacking Ball Work'),
    (202, 'Defensive Ball Work'),
    (203, 'Possession Ball Work'),
    (220, 'Attacking - Balanced'),
    (221, 'Attacking - Patient'),
    (222, 'Attacking - Direct'),
    (223, 'Attacking - Wings'),
    (224, 'Defending - Balanced'),
    (225, 'Defending - Engaged'),
    (226, 'Defending - Disengaged'),
    (227, 'Defending - Wide'),
    (228, 'Theory - Attacking Shadow Play'),
    (229, 'Theory - Defensive Shadow Play'),
    (230, 'Technical - Chance Creation'),
    (231, 'Technical - Chance Conversion'),
    (232, 'Technical - Ball Retention'),
    (233, 'Technical - Ground Defence'),
    (234, 'Technical - Aerial Defence'),
    (235, 'Transition - Restrict'),
    (236, 'Transition - Press'),
    (237, 'Transition - Progress'),
    (238, 'GK - Balanced'),
    (239, 'GK - Shot Stopping'),
    (240, 'GK - Handling'),
    (241, 'GK - One On Ones'),
    (242, 'GK - Distribution'),
    (243, 'Set Pieces - Delivery'),
    (244, 'Set Pieces - Penalties'),
    (300, 'Rest'),
    (301, 'Recovery'),
    (302, 'Light Conditioning'),
    (303, 'Conditioning'),
    (304, 'Heavy Conditioning'),
    (320, 'Rest (IM)'),
    (321, 'Recovery (IM)'),
    (322, 'Light Conditioning (IM)'),
    (400, 'Team Bonding'),
    (401, 'Community Outreach'),
    (402, 'Travel'),
    (500, 'Match'),
    (600, 'Not Available'),
]


@pytest.mark.parametrize('code,name', EXPECTED_NAMES)
def test_all_59_exact_native_and_resource_names(code, name):
    assert sessions.label(2, code, True) == {
        'slot_index': 2, 'native_code': code, 'english_definition_name': name,
        'name_state': 'named_installed_definition'}


@pytest.mark.parametrize('code,name', [
    (0, 'Passing Style'), (300, 'Rest'), (301, 'Recovery'), (402, 'Travel'),
    (500, 'Match'), (600, 'Not Available'),
])
def test_special_codes_are_explicit_labels(code, name):
    assert sessions.label(0, code, True)['english_definition_name'] == name


@pytest.mark.parametrize('code', [-32768, -1, 8, 9, 10, 58, 59, 109, 299, 305, 601, 32767])
def test_unknown_and_compiled_only_codes_preserve_signed_value(code):
    assert sessions.label(1, code, True) == {
        'slot_index': 1, 'native_code': code, 'english_definition_name': None,
        'name_state': 'unmapped_native_code'}


@pytest.mark.parametrize('code', [-32768, -1, 0, 300, 402, 500, 600, 32767])
def test_resource_unavailable_never_invents_a_name(code):
    assert sessions.label(0, code, False) == {
        'slot_index': 0, 'native_code': code, 'english_definition_name': None,
        'name_state': 'unavailable_definition_resource'}


@pytest.mark.parametrize('slot', [-1, 3, True, False, None, '0', 0.0])
def test_invalid_slot_rejected(slot):
    with pytest.raises(ValueError, match='slot index'):
        sessions.label(slot, 300, True)


@pytest.mark.parametrize('code', [-32769, 32768, True, False, None, '300', 300.0])
def test_invalid_signed_code_rejected(code):
    with pytest.raises(ValueError, match='signed 16-bit'):
        sessions.label(0, code, True)


@pytest.mark.parametrize('value', [0, 1, None, 'true', [], {}])
def test_resource_verification_requires_actual_boolean(value):
    with pytest.raises(ValueError, match='boolean'):
        sessions.label(0, 300, value)


@pytest.fixture
def bundle(tmp_path, monkeypatch):
    contents = tmp_path / 'Football Manager 27.app/Contents'
    executable = contents / 'MacOS/Football Manager 27'
    executable.parent.mkdir(parents=True)
    executable.write_bytes(b'fixture executable')
    metadata = {'CFBundleIdentifier': 'com.SportsInteractive.FootballManager27',
                'CFBundleExecutable': executable.name,
                'CFBundleShortVersionString': players.VERSION}
    plist = contents / 'Info.plist'
    plist.write_bytes(plistlib.dumps(metadata))
    resource = contents / sessions.RESOURCE_RELATIVE_PATH
    resource.parent.mkdir(parents=True)
    raw = b'verified compact training archive'
    resource.write_bytes(raw)
    monkeypatch.setattr(sessions, 'RESOURCE_SIZE', len(raw))
    monkeypatch.setattr(sessions, 'RESOURCE_SHA256', hashlib.sha256(raw).hexdigest())
    return dict(contents=contents, executable=executable, metadata=metadata,
                plist=plist, resource=resource, raw=raw)


def test_standard_bundle_resource_matches(bundle):
    assert sessions.resource_matches(str(bundle['executable'])) is True


def test_process_fm_executable_name_is_supported(bundle):
    alias = bundle['executable'].with_name('fm')
    bundle['executable'].rename(alias)
    bundle['metadata']['CFBundleExecutable'] = 'fm'
    bundle['plist'].write_bytes(plistlib.dumps(bundle['metadata']))
    assert sessions.resource_matches(alias) is True


def test_frozen_resource_digest_and_length_are_the_verified_archive():
    assert sessions.RESOURCE_SIZE == 6499
    assert sessions.RESOURCE_SHA256 == '63b209ef8660bf5ce39c36b1348c79dcdec6eb2b3f7c6479e9fb30d23c26f69d'
    assert sessions.SESSION_MEMBER_SHA256 == '9f99d3db032fb12b0dfc6f50cbb389e3ce6e449f4344e317a576c611ac3f7c6c'


@pytest.mark.parametrize('value', [None, 12, True, '', 'relative.app/Contents/MacOS/fm'])
def test_invalid_executable_path_returns_false(value):
    assert sessions.resource_matches(value) is False


@pytest.mark.parametrize('key,value', [
    ('CFBundleIdentifier', 'com.SportsInteractive.FootballManager26'),
    ('CFBundleIdentifier', 'com.example.fake'),
    ('CFBundleExecutable', 'other'), ('CFBundleShortVersionString', 'changed'),
])
def test_changed_bundle_metadata_rejected(bundle, key, value):
    bundle['metadata'][key] = value
    bundle['plist'].write_bytes(plistlib.dumps(bundle['metadata']))
    assert sessions.resource_matches(bundle['executable']) is False


@pytest.mark.parametrize('target', ['resource', 'plist', 'executable'])
def test_missing_bundle_input_returns_false(bundle, target):
    bundle[target].unlink()
    assert sessions.resource_matches(bundle['executable']) is False


@pytest.mark.parametrize('raw', [b'', b'changed compact training archive', b'x' * 100000])
def test_missing_changed_and_oversize_resource_never_verifies(bundle, raw):
    bundle['resource'].write_bytes(raw)
    assert sessions.resource_matches(bundle['executable']) is False


def test_same_size_resource_change_is_rejected(bundle):
    bundle['resource'].write_bytes(bytes([bundle['raw'][0] ^ 1]) + bundle['raw'][1:])
    assert sessions.resource_matches(bundle['executable']) is False


@pytest.mark.parametrize('raw', [b'not a plist', b'<?xml version="1.0"?><plist><dict>', b'x' * 65537])
def test_malformed_or_oversize_plist_returns_false(bundle, raw):
    bundle['plist'].write_bytes(raw)
    assert sessions.resource_matches(bundle['executable']) is False


def test_non_dictionary_plist_returns_false(bundle):
    bundle['plist'].write_bytes(plistlib.dumps(['not metadata']))
    assert sessions.resource_matches(bundle['executable']) is False


@pytest.mark.parametrize('target', ['resource', 'plist'])
def test_bundle_symlink_escape_rejected(bundle, tmp_path, target):
    original = bundle[target]
    outside = tmp_path / f'outside-{target}'
    outside.write_bytes(original.read_bytes())
    original.unlink()
    original.symlink_to(outside)
    assert sessions.resource_matches(bundle['executable']) is False


def test_directory_instead_of_resource_rejected(bundle):
    bundle['resource'].unlink()
    bundle['resource'].mkdir()
    assert sessions.resource_matches(bundle['executable']) is False


def test_nonregular_resource_rejected_before_open(bundle, monkeypatch):
    import os
    resource = bundle['resource']
    resource.unlink()
    os.mkfifo(resource)
    assert sessions.resource_matches(bundle['executable']) is False


def test_resource_path_replaced_after_read_is_rejected(bundle, monkeypatch):
    original_open = Path.open
    resource = bundle['resource']
    replacement = resource.with_name('replacement.fmf')
    replacement.write_bytes(bundle['raw'])
    class SwappingRead:
        def __init__(self, stream): self.stream = stream
        def __enter__(self): return self
        def __exit__(self, *args): self.stream.close()
        def fileno(self): return self.stream.fileno()
        def read(self, size):
            raw = self.stream.read(size)
            replacement.replace(resource)
            return raw
    def open_file(path, *args, **kwargs):
        stream = original_open(path, *args, **kwargs)
        return SwappingRead(stream) if path == resource and args == ('rb',) else stream
    monkeypatch.setattr(Path, 'open', open_file)
    assert sessions.resource_matches(bundle['executable']) is False


def test_portable_real_resource_fixture_runs_actual_digest(tmp_path):
    from training_session_fixture import RESOURCE_BYTES, training_resource_bundle
    m = training_resource_bundle(tmp_path)
    assert len(RESOURCE_BYTES) == 6499
    assert hashlib.sha256(RESOURCE_BYTES).hexdigest() == sessions.RESOURCE_SHA256
    assert sessions.resource_matches(m['executable']) is True
