"""Bounded HUMAN DD15EC x4 / DD2054 collection wire; no field semantics."""

class UnsupportedChild(ValueError):

    def __init__(self, partial):
        self.partial = partial
        self.offset = partial['end']
        self.native = partial['next_native_reader']
        super().__init__(f"{self.native} at {self.offset}: {partial['reason']}")

class BudgetExceeded(ValueError):
    pass

def parse(data, start, *, source_major=3754, minor=9, limit=None, reference_profile='local1_streambit1', max_rows=4096, max_words=65536, team_reader=None):
    """Consume four DD15EC collections and one DD2054, or exact first edge.

 local1_streambit1 explicitly selects four opaque PERSON bytes under native
 HUMAN C98=1. TEAM mode3 positive rows require a real supplied callback.
 Resource stops are research budget failures, never native-invalid claims.
 """
    if type(source_major) is not int or type(minor) is not int or (source_major, minor) != (3754, 9):
        raise ValueError('Unsupported source version')
    if reference_profile != 'local1_streambit1':
        raise ValueError('Unproved PERSON reference profile')
    bound = len(data) if limit is None else limit
    if type(start) is not int or type(bound) is not int or (not 0 <= start <= bound <= len(data)):
        raise ValueError('Invalid bounds')
    if type(max_rows) is not int or type(max_words) is not int or min(max_rows, max_words) < 0:
        raise ValueError('Invalid budget')
    at = start
    collections = []
    remaining = max_rows
    remaining_words = max_words

    def take(n):
        nonlocal at
        if n < 0 or n > bound - at:
            raise ValueError('Truncated DD collection')
        a = at
        at += n
        return bytes(data[a:at])

    def u(n):
        return int.from_bytes(take(n), 'little')

    def signed8(v):
        return v if v < 128 else v - 256

    def stop(native, reason):
        raise UnsupportedChild(dict(start=start, end=at, complete_child_wire=False, collections=collections, next_native_reader=native, reason=reason))
    for ci in range(5):
        begin = at
        version = u(1)
        count = int.from_bytes(take(4), 'little', signed=True)
        if count < 0:
            raise ValueError('Negative native collection allocation count')
        if count > remaining:
            raise BudgetExceeded('DD row work budget; not native rejection')
        remaining -= count
        rows = []
        coll = dict(start=begin, container_version=version, count=count, rows=rows)
        collections.append(coll)
        for ri in range(count):
            rowstart = at
            rv = u(1)
            sv = signed8(rv)
            if ci < 4:
                ref = take(4).hex()
                fields = {'0x28': u(1), '0x29': u(1)}
                if sv >= 5:
                    fields['0x2a'] = u(1)
                fields['0x2b'] = u(1)
                if sv > 2:
                    fields['0x2c'] = u(1)
                words = []
                tail = []
                if sv >= 2:
                    n = u(4)
                    if n > remaining_words:
                        raise BudgetExceeded('DD u32 vector work budget; not native rejection')
                    remaining_words -= n
                    words = [u(4) for _ in range(n)]
                    if sv >= 4:
                        tail.append(take(4).hex())
                    if sv >= 5:
                        tail.append(take(4).hex())
                rows.append(dict(start=rowstart, end=at, version=rv, person_reference_raw_hex=ref, fields=fields, raw_u32_words=words, tail_words_hex=tail))
            else:
                if team_reader is None:
                    stop('0x11019A0 mode3', 'TEAM profile not implied by PERSON profile; exact positive child callback required')
                result = team_reader(data, at, limit=bound, mode=3)
                end = result.get('end')
                if result.get('complete_child_wire') is not True or type(end) is not int or (not at < end <= bound):
                    raise ValueError('Invalid bounded TEAM callback')
                at = end
                fields = take(3).hex()
                blocks = [take(13).hex() for _ in range(4)] if sv >= 2 else [take(2).hex()]
                rows.append(dict(start=rowstart, end=at, version=rv, team=result, fields_hex=fields, blocks_hex=blocks))
        coll['end'] = at
    return dict(start=start, end=at, collections=collections, complete_child_wire=True, pending_bytes=0, reference_profile=reference_profile, local_2c98=1, runtime_stream_and_switches_proved=False, semantic_fields_resolved=False)
