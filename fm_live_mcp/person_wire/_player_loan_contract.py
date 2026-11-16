"""Kind1 LOAN_CONTRACT1373090 current3754/9 derived prefix + shared FE4904.

The derived shape is not FULL_CONTRACT1279724. Optional positive children need
explicit callbacks. Current compact blocks support writer version2/encoding5;
legacy conversions and runtime reference/filter effects are not reproduced.
"""
from . import _actual64_contracts
import struct

class UnsupportedLoanContract(ValueError):

    def __init__(self, message, *, native, offset, parts):
        self.native, self.offset, self.parts = (native, offset, parts)
        super().__init__(message)

def parse_prefix(data, start, *, reference_mode, source_major=3754, minor=9, limit=None, structure68_reader=None, row70_reader=None, vector88_reader=None):
    if type(source_major) is not int or type(minor) is not int or (source_major, minor) != (3754, 9):
        raise ValueError('Unsupported LOAN_CONTRACT source context')
    if reference_mode != 'raw64':
        raise ValueError('LOAN_CONTRACT requires explicit raw64 shared-base context')
    limit = len(data) if limit is None else limit
    if type(start) is not int or type(limit) is not int or (not 0 <= start <= limit <= len(data)):
        raise ValueError('Invalid LOAN_CONTRACT checked span')
    bounded = memoryview(data)[:limit]
    at = start
    parts = {}

    def take(n):
        nonlocal at
        if n < 0 or n > limit - at:
            raise ValueError(f'Truncated LOAN_CONTRACT at {at}: need {n}')
        value = bytes(bounded[at:at + n])
        at += n
        return value

    def uint(n):
        return int.from_bytes(take(n), 'little')

    def presence(label):
        value = uint(1)
        if value not in (0, 1):
            raise ValueError(f'Unsupported current-writer LOAN_CONTRACT {label} presence')
        return value

    def child(native, callback):
        nonlocal at
        if callback is None:
            raise UnsupportedLoanContract('Positive LOAN_CONTRACT child requires explicit codec', native=native, offset=at, parts=parts)
        result = callback(bounded, at)
        if not isinstance(result, dict) or type(result.get('end')) is not int or (not at < result['end'] <= limit):
            raise ValueError('Invalid LOAN_CONTRACT child boundary')
        at = result['end']
        return result
    parts['presence_68'] = presence('+68')
    if parts['presence_68']:
        parts['structure68'] = child(25570304, structure68_reader)
    raw_count = int.from_bytes(take(1), 'little', signed=True)
    parts['count_70_raw_i8'] = raw_count
    parts['rows70'] = []
    for _ in range(max(0, raw_count)):
        parts['rows70'].append(child(20070796, row70_reader))
    parts['presence_88'] = presence('+88')
    if parts['presence_88']:
        parts['vector88'] = child(20394860, vector88_reader)
    blocks = []
    for native_offset in (160, 168):
        block_start = at
        version, encoding = (uint(1), uint(1))
        if (version, encoding) != (2, 5):
            raise UnsupportedLoanContract('Unsupported compact block outside current-writer2/5 profile', native=20391260, offset=block_start, parts=parts)
        raw = take(8)
        blocks.append({'native_offset': hex(native_offset), 'start': block_start, 'end': at, 'version': version, 'encoding': encoding, 'raw_payload_hex': raw.hex()})
    parts['compact_blocks'] = blocks
    fields = {}
    fields['native_ec_f3_raw8_hex'] = take(8).hex()
    marker = uint(1)
    if marker != 1:
        raise ValueError('Unsupported current-writer LOAN_CONTRACT fixed marker; expected1')
    fields['ignored_writer_marker'] = marker
    fields['native_94_9c_raw9_hex'] = take(9).hex()
    fields['native_90_raw_u32'] = uint(4)
    fields['native_b0_eb_raw60_hex'] = take(60).hex()
    fields['native_f4_fd_raw10_hex'] = take(10).hex()
    parts['fields'] = fields
    return {'start': start, 'end': at, 'kind': 1, 'native_reader': '0x1373090', 'native_writer': '0x1373C24', 'reference_mode': reference_mode, 'parts': parts, 'derived_prefix_complete': True, 'complete_loan_contract': False, 'next_native': '0xFE4904', 'pending_bytes': 0, 'references_resolved': False}

def _shared_base(data, start):
    return _actual64_contracts.parse_fe4904(data, start)

def parse(data, start, *, kind=1, reference_mode, base_reader=None, **kwargs):
    if type(kind) is not int or kind != 1:
        raise ValueError('LOAN_CONTRACT decoder accepts kind1 only; preserve other subtype dispatch')
    prefix = parse_prefix(data, start, reference_mode=reference_mode, **kwargs)
    limit = len(data) if kwargs.get('limit') is None else kwargs['limit']
    base = (base_reader or _shared_base)(memoryview(data)[:limit], prefix['end'])
    if not isinstance(base, dict) or type(base.get('end')) is not int or (not prefix['end'] < base['end'] <= limit):
        raise ValueError('Invalid shared FE4904 loan-contract boundary')
    return {'start': start, 'end': base['end'], 'kind': 1, 'native_reader': '0x1373090', 'prefix': prefix, 'base': base, 'complete_loan_contract': True, 'pending_bytes': 0, 'references_resolved': False, 'native_loader_acceptance_proved': False}
