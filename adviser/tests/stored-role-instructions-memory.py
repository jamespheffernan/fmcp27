"""Actual payloads and in-memory guards; creates no native archive fixtures."""
import importlib.util
import json
from pathlib import Path
import struct
import sys

spec = importlib.util.spec_from_file_location('writer', sys.argv[1])
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
base, attack = m.TEMPLATES/'3421 FM27 .fmf', m.TEMPLATES/'3421 FM27 Att.fmf'
_, bb, bm = m.read_template(str(base))
_, ab, am = m.read_template(str(attack))
sources = [(base, bb, bm), (attack, ab, am)]
refusals, positives = 0, 0


def request(path, blob):
    return dict(phase='in_possession', position_index=9, donor_position_index=9,
                donor_template_path=str(path), donor_template_sha256=m.sha(blob))


def refuse(call):
    global refusals
    try:
        call()
    except ValueError:
        refusals += 1
    else:
        raise AssertionError('Unproved instruction case accepted')


for source, donor in [(sources[0], sources[1]), (sources[1], sources[0])]:
    raw = source[2]['.tac']
    for variant in [raw, m.replace_tempo(raw, 'Lower Tempo'), m.replace_tac_name(raw, 'Longer Native Instruction Variant Name')]:
        before, at, old_bits = m.stored_role_pi_record(variant)
        changed, receipt, path, blob = m.prepare_stored_role_instructions(variant, request(donor[0], donor[1]))
        target, _, target_bits = m.stored_role_pi_record(donor[2]['.tac'])
        after = m.phase_records(changed)['in_possession'][9]
        assert changed[after['record_offset']:after['record_end_exclusive']] == donor[2]['.tac'][target['record_offset']:target['record_end_exclusive']]
        assert changed[:at] + old_bits.to_bytes(8, 'little') + changed[at+8:] == variant
        assert receipt['before']['native_bits'] == f'{old_bits:016x}'
        assert receipt['after']['native_bits'] == f'{target_bits:016x}'
        assert receipt['native_role_word'] == before['native_role_word'] == after['native_role_word']
        assert path == donor[0].resolve() and blob == donor[1]
        positives += 1
    refuse(lambda: m.prepare_stored_role_instructions(raw, request(source[0], source[1])))
    spec_request = request(donor[0], donor[1])
    for bad in (None, True, False, 1, [], {}, 'Roam From Position'):
        refuse(lambda bad=bad: m.prepare_stored_role_instructions(raw, bad))
    for change in (dict(phase='out_of_possession'), dict(phase=None), dict(position_index=8),
                   dict(position_index=True), dict(donor_position_index=8), dict(donor_position_index=True),
                   dict(option_ids=[24, 27]), dict(role='Other'), dict(native_role_word='0000000000400200'),
                   dict(donor_template_path=True), dict(donor_template_path=''), dict(donor_template_sha256=None),
                   dict(donor_template_sha256='0'*64)):
        refuse(lambda change=change: m.prepare_stored_role_instructions(raw, spec_request | change))
    record, offset, _ = m.stored_role_pi_record(raw)
    for relative in (0, 1, 2, 8):
        bad = bytearray(raw)
        bad[record['record_offset']+relative] ^= 1
        refuse(lambda bad=bad: m.stored_role_pi_record(bytes(bad)))
    for major in (26, 28):
        bad = bytearray(raw)
        bad[11] = major
        refuse(lambda bad=bad: m.stored_role_pi_record(bytes(bad)))
    for word in (0x400200, 0x800080, 0x800200 | 1<<63):
        bad = bytearray(raw)
        struct.pack_into('<Q', bad, record['role_word_offset'], word)
        refuse(lambda bad=bad: m.stored_role_pi_record(bytes(bad)))
    for mask in (8192, 2105344, 1049600):
        bad = bytearray(raw)
        struct.pack_into('<I', bad, record['record_offset']+3, mask)
        refuse(lambda bad=bad: m.stored_role_pi_record(bytes(bad)))
    for bits in (1<<24, 1<<27, 1, 0x9000000 | 1<<57):
        bad = bytearray(raw)
        struct.pack_into('<Q', bad, offset, bits)
        refuse(lambda bad=bad: m.stored_role_pi_record(bytes(bad)))
    vector = record['instruction_vector_offset']
    for at, value, width in [(vector+8, 3, 1), (vector+24, 0x201, 8), (vector, 0x200, 8),
                              (vector+24, 0x800200, 8), (vector+11, 0, 8),
                              (vector+19, 0xfe, 1), (record['record_offset']+7, 1, 1)]:
        bad = bytearray(raw)
        bad[at:at+width] = value.to_bytes(width, 'little')
        refuse(lambda bad=bad: m.stored_role_pi_record(bytes(bad)))

# Independent phase edits compose without changing either target's proof.
role_request = request(attack, ab) | dict(phase='out_of_possession')
role_changed, _, _, _ = m.prepare_base_role(bm['.tac'], role_request)
both, _, _, _ = m.prepare_stored_role_instructions(role_changed, request(attack, ab))
assert m.phase_records(both)['out_of_possession'][9]['native_role_word'] == '0000000040400000'
assert m.stored_role_pi_record(both)[2] == 0x9000000
positives += 1


class MemoryNative:
    def __init__(self, values):
        self.values = values
    def open(self, mode):
        assert mode == 'rb'
        return MemoryNativeFile(self.values)


class MemoryNativeFile:
    def __init__(self, values):
        self.values, self.at = values, 0
    def __enter__(self):
        return self
    def __exit__(self, *args):
        return False
    def seek(self, at):
        self.at = at
    def read(self, size):
        value = self.values[self.at]
        assert len(value) == size
        return value


native = m.ROLE_NATIVE_PLUGIN
values = {}
with native.open('rb') as f:
    for at, size, _ in m.STORED_ROLE_PI_NATIVE_SPANS:
        f.seek(0x5ED4000+at)
        values[0x5ED4000+at] = f.read(size)
for at, _, _ in m.STORED_ROLE_PI_NATIVE_SPANS:
    altered = dict(values)
    key = 0x5ED4000+at
    altered[key] = bytes([altered[key][0]^1])+altered[key][1:]
    m.ROLE_NATIVE_PLUGIN = MemoryNative(altered)
    try:
        refuse(lambda: m.prepare_stored_role_instructions(bm['.tac'], request(attack, ab)))
    finally:
        m.ROLE_NATIVE_PLUGIN = native


class BadResource:
    def read_bytes(self):
        return b'Changed native definitions'


for field in ('LOSS_ENGLISH_RESOURCE', 'STORED_ROLE_PI_METADATA'):
    old = getattr(m, field)
    setattr(m, field, BadResource())
    try:
        refuse(lambda: m.prepare_stored_role_instructions(bm['.tac'], request(attack, ab)))
    finally:
        setattr(m, field, old)
original_decode = m.decode_word
def bad_label(word, phase):
    decoded = original_decode(word, phase)
    if word == 0x800200 and phase == 'in_possession':
        decoded['compiled_english_name'] = 'Changed role'
    return decoded
m.decode_word = bad_label
try:
    refuse(lambda: m.prepare_stored_role_instructions(bm['.tac'], request(attack, ab)))
finally:
    m.decode_word = original_decode
assert base.read_bytes() == bb and attack.read_bytes() == ab
print(json.dumps(dict(actual_payload_positives=positives, refusals=refusals, archive_fixtures_created=0,
                      native_fixture_files_created=0, game_import_verified=False)))
