"""11019A0 mode3 wire under an explicit HUMAN-local conditional context."""

def parse(data, start, *, limit=None, mode=3, stream_flags=2, switch3522=0, switch3523=1, local_c98=1):
    bound = len(data) if limit is None else limit
    if type(start) is not int or type(bound) is not int or (not 0 <= start <= bound <= len(data)):
        raise ValueError('Invalid bounds')
    if type(mode) is not int or mode != 3:
        raise ValueError('Unsupported TEAM mode')
    if (stream_flags, switch3522, switch3523, local_c98) != (2, 0, 1, 1):
        raise ValueError('Unsupported explicit conditional reference context')
    if bound - start < 4:
        raise ValueError('Truncated TEAM reference')
    return dict(start=start, end=start + 4, complete_child_wire=True, raw_reference_word=int.from_bytes(data[start:start + 4], 'little'), namespace='TEAM_BASE', canonical_membership_resolved=False, context_provenance='conditional coherent HUMAN witness; runtime globals unobserved', mode=3)
