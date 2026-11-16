"""Read only the proved fixed ACTUAL_COMP prefix from the selected archive.

The stored season code is a discriminator, not a decoded date range. Unconsumed
component suffixes are not validated or interpreted by this reader.
"""
from .saved_component_stream import open_component

HEADER = bytes.fromhex('03017461642e0902')
FIXED_PREFIX_SIZE = 49
MAX_PAGE_MEMBERS = 500


class _PrefixHandle:
    """Permit at most one decoder input block, even for hostile empty blocks."""
    def __init__(self, handle):
        self.handle, self.remaining = handle, 128 * 1024

    def seek(self, offset):
        return self.handle.seek(offset)

    def read(self, size):
        if size > self.remaining:
            raise ValueError('Saved competition prefix input budget exceeded')
        data = self.handle.read(size)
        self.remaining -= len(data)
        return data


class StateReader:
    """Bound work to 500 selected prefixes; never decompress an entire member.

    Each decoder pulls at most one 128KiB packed block for the 49-byte prefix
    (64MiB per maximum page). Decoder-owned window memory is bounded to64MiB
    and released between members. No cache of decompressed member bodies exists.
    """
    def __init__(self, handle, entries, root):
        self.handle, self.entries, self.root = handle, entries, root
        self.reads = 0

    def read(self, native_id):
        if type(native_id) is not int or not 0 <= native_id < 1 << 32:
            raise ValueError('Invalid unsigned competition native ID')
        self.reads += 1
        if self.reads > MAX_PAGE_MEMBERS:
            raise ValueError('Saved competition state page budget exceeded')
        # Native43880A0 formats COMP+C with %d, although the public ID is u32.
        signed_id = native_id if native_id < 1 << 31 else native_id - (1 << 32)
        path = f'{self.root}/rgman/comp_{signed_id}.dat'
        result = dict(status='absent', component_path=path, stream_version=None,
                      native_season_code=None, scope='fixed prefix only')
        entry = self.entries.get(path)
        if entry is None:
            return result
        if entry.uncompressed_size == 0:
            result['status'] = 'unsupported_layout'
            return result
        with open_component(_PrefixHandle(self.handle), entry) as reader:
            header = reader.take(min(8, reader.size))
            result['status'] = 'unsupported_layout'
            if len(header) == len(HEADER) and header[:6] == HEADER[:6]:
                result['stream_version'] = int.from_bytes(header[6:8], 'little')
            if header != HEADER:
                return result
            prefix = header + reader.take(FIXED_PREFIX_SIZE - 8)
            code = int.from_bytes(prefix[20:22], 'little')
            result.update(status='decoded' if code else 'no_season_code',
                          stream_version=521, native_season_code=code)
            return result
