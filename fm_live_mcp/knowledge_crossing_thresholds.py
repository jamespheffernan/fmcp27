"""Private native Crossing11 threshold component; grants no field visibility.

Full14E98E4 dispatch + ordinary primary518 getter select seven category tables.
Crossing's branch bytes differ from Passing: e.g. category3 is36/74, not11/49.
This does not implement Crossing H/K/UI caller, an attribute read or a mode.
"""
import hashlib

FIELD=11
NATIVE_GUARDS=(
    (0x14e98e4,3940,'d8ba68fb2e502cc925bf25786a7eb19bc9f84c1f7d43d0467beeb53bb6c032eb'),
    (0xd5c4bc,8,'87c95004f83bcde8ac89e5691e743bac0d3e0aa4923aa7f39425750b11cd24b8'),
)
TABLE_BRANCHES=((0x5399412,0),(0x5399443,77),(0x5399474,77),(0x53994a5,77),
    (0x53994d6,77),(0x5399507,77),(0x5399538,77))


def verify_native(read,base):
    for rva,size,digest in NATIVE_GUARDS:
        if hashlib.sha256(read(base+rva,size)).hexdigest()!=digest:
            raise ValueError('Native Crossing threshold source changed')
    for rva,value in TABLE_BRANCHES:
        if read(base+rva,1)!=bytes([value]):
            raise ValueError('Native Crossing threshold branch changed')


def crossing_thresholds(category_byte):
    """Return original lower/exact thresholds, given an established category."""
    if type(category_byte)is not int or not 0<=category_byte<=255:
        raise ValueError('Expected native category byte0..255')
    category=category_byte if category_byte<128 else category_byte-256
    if category==0:return 39,77
    if category==3:return 36,74
    if category in(2,4,6,8,9,11,13,14):return 4,42
    if category in(5,7):return 23,61
    if category==10:return 20,58
    if category==12:return 21,59
    return 0,0
