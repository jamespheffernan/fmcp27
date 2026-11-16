"""Bounded exercised PLAYER+F0 reader11E7C4C / pairedwriter11E9F30.

Supports zero-count native+0/+18 vectors, absent optional+30, raw optional+38,
and absent remaining optional+40/+48/+50/+58. Other populated branches stop at
an exact native edge. No reference width or semantic field units are inferred.
"""
CHUNKS_38 = ((12, 4), (16, 4), (20, 4), (24, 4), (28, 4), (44, 4), (54, 1), (55, 1), (32, 4), (48, 2), (50, 2), (52, 1), (53, 1), (8, 4), (57, 1), (56, 1), (0, 8), (36, 4), (40, 4))
assert sum((n for _, n in CHUNKS_38)) == 58

class UnsupportedChild(ValueError):

    def __init__(self, native, offset, parts, reason):
        self.reader = native
        self.native = hex(native)
        self.offset = offset
        self.parts = parts
        self.partial = parts
        super().__init__(f'Unsupported PLAYER+F0 edge {native:#x} at {offset}: {reason}')
