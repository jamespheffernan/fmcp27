"""Private thresholds for all47 ordinary native fields, not field permission.

Every pair comes from the complete original14E98E4 dispatcher and seven exact
field tables. H/K/UI source, getter binding and lifetime checks are separate.
"""
import hashlib

NATIVE_GUARDS=(
    (0x14e98e4,3940,'d8ba68fb2e502cc925bf25786a7eb19bc9f84c1f7d43d0467beeb53bb6c032eb'),
    (0xd5c4bc,8,'87c95004f83bcde8ac89e5691e743bac0d3e0aa4923aa7f39425750b11cd24b8'),
    (0x5399406,343,'391c74f48699e6e862a576345b677910c61d8cdd525dfba56e190e190c983694'),
)
# Columns: category0,3,2/4/13/14,5/7,6/8/9/11,10,12; each(low,exact).
THRESHOLDS=(
    ((8, 46), (39, 77), (39, 77), (39, 77), (39, 77), (39, 77), (39, 77)),  # native field0
    ((4, 42), (39, 77), (39, 77), (39, 77), (39, 77), (39, 77), (39, 77)),  # native field1
    ((17, 55), (39, 77), (39, 77), (39, 77), (39, 77), (39, 77), (39, 77)),  # native field2
    ((12, 50), (39, 77), (39, 77), (39, 77), (39, 77), (39, 77), (39, 77)),  # native field3
    ((3, 41), (39, 77), (39, 77), (39, 77), (39, 77), (39, 77), (39, 77)),  # native field4
    ((5, 43), (39, 77), (39, 77), (39, 77), (39, 77), (39, 77), (39, 77)),  # native field5
    ((9, 47), (39, 77), (39, 77), (39, 77), (39, 77), (39, 77), (39, 77)),  # native field6
    ((10, 48), (39, 77), (39, 77), (39, 77), (39, 77), (39, 77), (39, 77)),  # native field7
    ((7, 45), (39, 77), (39, 77), (39, 77), (39, 77), (39, 77), (39, 77)),  # native field8
    ((6, 44), (39, 77), (39, 77), (39, 77), (39, 77), (39, 77), (39, 77)),  # native field9
    ((11, 49), (39, 77), (39, 77), (39, 77), (39, 77), (39, 77), (39, 77)),  # native field10
    ((39, 77), (36, 74), (4, 42), (23, 61), (4, 42), (20, 58), (21, 59)),  # native field11
    ((39, 77), (26, 64), (13, 51), (25, 63), (3, 41), (13, 51), (24, 62)),  # native field12
    ((39, 77), (38, 76), (32, 70), (20, 58), (10, 48), (7, 45), (3, 41)),  # native field13
    ((39, 77), (4, 42), (15, 53), (13, 51), (35, 73), (17, 55), (10, 48)),  # native field14
    ((39, 77), (29, 67), (38, 76), (9, 47), (12, 50), (9, 47), (12, 50)),  # native field15
    ((39, 77), (35, 73), (29, 67), (37, 75), (36, 74), (37, 75), (36, 74)),  # native field16
    ((39, 77), (6, 44), (6, 44), (32, 70), (38, 76), (32, 70), (38, 76)),  # native field17
    ((39, 77), (11, 49), (11, 49), (6, 44), (9, 47), (4, 42), (9, 47)),  # native field18
    ((39, 77), (37, 75), (37, 75), (38, 76), (22, 60), (30, 68), (22, 60)),  # native field19
    ((38, 76), (33, 71), (33, 71), (35, 73), (20, 58), (23, 61), (34, 72)),  # native field20
    ((39, 77), (3, 41), (3, 41), (4, 42), (33, 71), (38, 76), (33, 71)),  # native field21
    ((30, 68), (18, 56), (18, 56), (16, 54), (11, 49), (10, 48), (11, 49)),  # native field22
    ((23, 61), (9, 47), (9, 47), (3, 41), (7, 45), (3, 41), (7, 45)),  # native field23
    ((39, 77), (34, 72), (34, 72), (36, 74), (15, 53), (27, 65), (35, 73)),  # native field24
    ((29, 67), (17, 55), (17, 55), (15, 53), (34, 72), (34, 72), (20, 58)),  # native field25
    ((18, 56), (14, 52), (14, 52), (33, 71), (32, 70), (33, 71), (32, 70)),  # native field26
    ((16, 54), (25, 63), (25, 63), (27, 65), (28, 66), (36, 74), (28, 66)),  # native field27
    ((36, 74), (31, 69), (31, 69), (7, 45), (16, 54), (5, 43), (16, 54)),  # native field28
    ((19, 57), (15, 53), (26, 64), (34, 72), (23, 61), (12, 50), (23, 61)),  # native field29
    ((33, 71), (8, 46), (12, 50), (21, 59), (19, 57), (21, 59), (19, 57)),  # native field30
    ((37, 75), (32, 70), (35, 73), (8, 46), (17, 55), (8, 46), (17, 55)),  # native field31
    ((21, 59), (21, 59), (36, 74), (17, 55), (30, 68), (25, 63), (30, 68)),  # native field32
    ((35, 73), (30, 68), (30, 68), (29, 67), (13, 51), (29, 67), (13, 51)),  # native field33
    ((14, 52), (7, 45), (7, 45), (24, 62), (37, 75), (24, 62), (37, 75)),  # native field34
    ((31, 69), (19, 57), (19, 57), (11, 49), (25, 63), (11, 49), (25, 63)),  # native field35
    ((28, 66), (16, 54), (16, 54), (10, 48), (14, 52), (28, 66), (14, 52)),  # native field36
    ((22, 60), (22, 60), (22, 60), (30, 68), (24, 62), (6, 44), (15, 53)),  # native field37
    ((15, 53), (23, 61), (23, 61), (31, 69), (31, 69), (31, 69), (31, 69)),  # native field38
    ((25, 63), (12, 50), (8, 46), (18, 56), (5, 43), (14, 52), (5, 43)),  # native field39
    ((13, 51), (28, 66), (28, 66), (28, 66), (8, 46), (16, 54), (29, 67)),  # native field40
    ((20, 58), (27, 65), (27, 65), (26, 64), (21, 59), (26, 64), (27, 65)),  # native field41
    ((26, 64), (13, 51), (5, 43), (19, 57), (6, 44), (15, 53), (6, 44)),  # native field42
    ((32, 70), (20, 58), (20, 58), (12, 50), (18, 56), (19, 57), (18, 56)),  # native field43
    ((24, 62), (10, 48), (10, 48), (5, 43), (29, 67), (35, 73), (8, 46)),  # native field44
    ((27, 65), (5, 43), (21, 59), (14, 52), (27, 65), (18, 56), (4, 42)),  # native field45
    ((34, 72), (24, 62), (24, 62), (22, 60), (26, 64), (22, 60), (26, 64)),  # native field46
 )


def verify_native(read,base):
    for rva,n,digest in NATIVE_GUARDS:
        if hashlib.sha256(read(base+rva,n)).hexdigest()!=digest:
            raise ValueError('Native attribute thresholds changed')


def thresholds(field,category_byte):
    if type(field)is not int or not 0<=field<47:
        raise ValueError('Expected native attribute field0..46')
    if type(category_byte)is not int or not 0<=category_byte<=255:
        raise ValueError('Expected native category byte0..255')
    category=category_byte if category_byte<128 else category_byte-256
    if category==0:group=0
    elif category==3:group=1
    elif category in(2,4,13,14):group=2
    elif category in(5,7):group=3
    elif category in(6,8,9,11):group=4
    elif category==10:group=5
    elif category==12:group=6
    else:return 0,0
    return THRESHOLDS[field][group]
