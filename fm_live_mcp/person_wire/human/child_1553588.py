"""Full1553588 child wire subset, paired1553414; numeric fields stay raw.
The enclosing HUMAN_NON_PLAYER forces localC98=1. No common raw64 inheritance.
"""
import struct
LOCAL_PROFILE = 'local1_streambit1'

class UnsupportedChild(ValueError):

    def __init__(self, partial):
        self.partial = partial
        self.offset = partial['end']
        self.native = partial['next_native_reader']
        super().__init__(f'Unparsed HUMAN+308 child edge {self.native} at {self.offset}')

def _packed(format_byte, raw):
    value = raw
    bits = raw & 8128
    if format_byte <= 2 and bits in (896, 960) or (format_byte == 3 and bits == 960):
        value = raw & ~8128 | 3200
    return value & 8191

def parse(data, start, *, source_major=3754, minor=9, limit=None, reference_profile=LOCAL_PROFILE, local_2c98=1, global_3523=None):
    """Return complete_child_wire/end, or raise with the exact first unknown edge.

 Supported refs: local1_streambit1 (4B opaque words); noncompact_index32
 (null or marker0 lookup only). Runtime stream/switch state stays conditional.
 """
    if (type(source_major), type(minor), source_major, minor) != (int, int, 3754, 9):
        raise ValueError('Unsupported HUMAN child source context')
    if type(local_2c98) is not int or local_2c98 != 1:
        raise ValueError('This parent proves only localC98=1')
    if reference_profile not in (LOCAL_PROFILE, 'noncompact_index32'):
        raise ValueError('Unsupported child PERSON reference profile; raw64 is not implied by its parent')
    if global_3523 is not None and (type(global_3523) is not int or not 0 <= global_3523 <= 255):
        raise ValueError('Invalid explicit3523 state')
    bound = len(data) if limit is None else limit
    if type(start) is not int or type(bound) is not int or (not 0 <= start <= bound <= len(data)):
        raise ValueError('Invalid HUMAN child bounds')
    at = start
    parts = []

    def take(n):
        nonlocal at
        if n < 0 or n > bound - at:
            raise ValueError('Truncated HUMAN+308 child')
        old = at
        at += n
        return bytes(data[old:at])

    def unsigned(n):
        return int.from_bytes(take(n), 'little')

    def stop(reader, reason):
        raise UnsupportedChild(dict(start=start, end=at, complete_child_wire=False, next_native_reader=reader, reason=reason, parts=parts, consumed_wire_hex=bytes(data[start:at]).hex(), reference_profile=reference_profile, local_2c98=1))
    version = unsigned(1)
    parts.append(dict(native_field='child_version', start=start, end=at, value=version))
    refs = []
    for destination in (0, 8):
        begin = at
        raw = take(4)
        word = int.from_bytes(raw, 'little')
        marker = None
        if reference_profile == 'noncompact_index32' and word != 4294967295:
            marker = unsigned(1)
            if marker:
                parts.append(dict(native_field=hex(destination), start=begin, end=at, raw_hex=raw.hex(), inline_marker=marker))
                stop('0x1104FB0 continuation0x11050A4', 'Positive inline PERSON payload not decoded; no guessed skip')
        ref = dict(native_field=hex(destination), start=begin, end=at, raw_hex=raw.hex(), raw_u32=word, raw_signed32=int.from_bytes(raw, 'little', signed=True), inline_marker=marker, native_reader='0x1104FB0', namespace='PERSON reference transport; identity unresolved')
        refs.append(ref)
        parts.append(ref)
    fields = {}
    for destination in (20, 24, 26, 22):
        begin = at
        raw = take(2)
        fields[hex(destination)] = dict(start=begin, end=at, raw_hex=raw.hex(), raw_u16=int.from_bytes(raw, 'little'))
    fields['0x1c'] = dict(offset=at, raw_u8=unsigned(1))
    if version == 2 and global_3523 is None:
        stop('0x15536A4', 'Version2 +1D presence depends on unobserved global3523; provide explicit context')
    has_1d = version >= (2 if global_3523 in (None, 0) else 3)
    fields['0x1d'] = dict(serialized=has_1d, offset=at if has_1d else None, raw_u8=unsigned(1) if has_1d else None, native_absent_default=0 if not has_1d else None)
    packed = []
    for destination in (16, 18):
        begin = at
        fmt = unsigned(1)
        word = unsigned(2)
        packed.append(dict(native_field=hex(destination), start=begin, end=at, format_byte=fmt, raw_u16=word, native_before_legacy_fixup_u16=_packed(fmt, word), semantic_label=None))
    return dict(start=start, end=at, complete_child_wire=True, pending_bytes=0, native_reader='0x1553588', native_writer='0x1553414', child_version=version, source_major=source_major, minor=minor, reference_profile=reference_profile, local_2c98=1, global_3523=global_3523, global_3523_required_for_wire=version == 2, references=refs, fields=fields, packed_words=packed, legacy_postread_4acf738_not_executed=version <= 3, legacy_postread_is_nonwire=True, runtime_stream_and_switches_proved=False, semantic_fields_resolved=False)
