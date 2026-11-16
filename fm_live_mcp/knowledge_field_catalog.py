"""Private native attribute metadata, separate from field visibility.

The compiled-name mode2 dispatch defines47 fields; ordinary getter D19EB0
uses the associated offset table. This catalog reads no player values and
grants no permission to read them. CA/PA and perceived stars are separate.
"""
import hashlib

PLUGIN_SHA256 = '774cacde63567fd3901c47719e7a6ed94cc3a0a62e9b94989dcac6b4890ec0e1'
FIELDS = (
    ('Aerial Reach', 0x1b, 0x50bd9a9),
    ('Command Of Area', 0x1c, 0x50bd9ba),
    ('Communication', 0x1d, 0x50bd9ce),
    ('Eccentricity', 0x2e, 0x50b0c86),
    ('Handling', 0x1a, 0x50bd9e4),
    ('Kicking', 0x1e, 0x50bd9f1),
    ('Reflexes', 0x24, 0x50bd9fd),
    ('Rushing Out (Tendency)', 0x2f, 0x50bda0a),
    ('Punching (Tendency)', 0x30, 0x50bda25),
    ('Throwing', 0x1f, 0x50bda3d),
    ('One On Ones', 0x22, 0x50bdaa6),
    ('Crossing', 0xf, 0x50bda4a),
    ('Dribbling', 0x10, 0x50bda57),
    ('Finishing', 0x11, 0x50bda65),
    ('Heading', 0x12, 0x50bda73),
    ('Long Shots', 0x13, 0x50bda7f),
    ('Long Throws', 0x2d, 0x50bda8a),
    ('Marking', 0x14, 0x50b0c27),
    ('Passing', 0x16, 0x50bda9a),
    ('Penalty Taking', 0x17, 0x50bdab6),
    ('Free Kick Taking', 0x32, 0x50bdac9),
    ('Tackling', 0x18, 0x50bdade),
    ('Technique', 0x26, 0x50bdaeb),
    ('First Touch', 0x25, 0x50bdaf9),
    ('Corners', 0x2a, 0x50bdb09),
    ('Aggression', 0x3c, 0x50bdb15),
    ('Anticipation', 0x20, 0x50bdb24),
    ('Bravery', 0x3a, 0x50bdb35),
    ('Vision', 0x19, 0x50bdb41),
    ('Decisions', 0x21, 0x50bdb48),
    ('Determination', 0x42, 0x50b0c5e),
    ('Flair', 0x29, 0x50bdb5a),
    ('Leadership', 0x37, 0x50bdb64),
    ('Off The Ball', 0x15, 0x50bdb6f),
    ('Positioning', 0x23, 0x50bdb80),
    ('Teamwork', 0x2b, 0x50bdb90),
    ('Work Rate', 0x2c, 0x50bdb9d),
    ('Composure', 0x43, 0x50bdbab),
    ('Concentration', 0x44, 0x50bdbb9),
    ('Acceleration', 0x31, 0x50bdbcb),
    ('Agility', 0x3d, 0x50bdbdc),
    ('Balance', 0x39, 0x50bdbe8),
    ('Pace', 0x35, 0x50bdbf4),
    ('Stamina', 0x34, 0x50bdbfd),
    ('Strength', 0x33, 0x50bdc09),
    ('Jumping Reach', 0x36, 0x50bdc16),
    ('Natural Fitness', 0x41, 0x50bdc28),
)
NATIVE_GUARDS = (
    (0x1567ee0, 2412, '8be2318fa0f006966a72c2e1db67bc3c12e55b8b7710ce683e9f97ee171aa09c'),
    (0x539d234, 94, '3055a77f3de535597dd4968c829d9d204e5fefd2a3becd017f859e73d6cc304e'),
    (0x540420e, 47, 'a30e65b8de1b29df45f6c7a909ae78e9fdcba84196964038cd998d1ac74e855d'),
    (0x4acf834, 36, 'f0b21cec26691de907c307936e46a342cdd2ca1a812ad2995a8b6c9de0f37325'),
)


def field(native_id):
    if type(native_id) is not int or not 0 <= native_id < len(FIELDS):
        raise ValueError('Expected a native attribute field ID0 through46')
    name,offset,_ = FIELDS[native_id]
    return {'native_field_id':native_id,'compiled_name':name,
            'stored_offset':offset,'primary_offset':0x148+offset,
            'field_visibility_evaluated':False}


def verify_native(read, base):
    for rva,n,digest in NATIVE_GUARDS:
        if hashlib.sha256(read(base+rva,n)).hexdigest()!=digest:
            raise ValueError('Native attribute metadata changed')
    for name,_,rva in FIELDS:
        raw=name.encode('ascii')+b'\0'
        if read(base+rva,len(raw))!=raw:
            raise ValueError('Native attribute compiled name changed')
