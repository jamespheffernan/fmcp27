"""Stored career morale from the ACTUAL_PLAYER getter with mode bit clear.

The alternate mode can select match/other sources. It is deliberately not
reconstructed here. No native game call, refresh or scouting mask executes.
"""
import hashlib

from . import players, world

SCOPE = ('Stored career PLAYER morale with native getter mode0 only. This is '
         'separate from match morale, overall happiness, concerns, cohesion and '
         'manager support. No native refresh or scouting mask is executed.')
NATIVE_GUARDS = (
    (0xd32ba8, 156, '4377bd874657fc744891029715eece46b28da6bf2b8199db6c1b156b90f8742c'),
    (0x154ab00, 1296, 'a531cbe2eccb715f6cbd4351d3cab10aeaef42fbadaf3619af55f0ea18e9c1e9'),
    (0x539ba7c, 20, '872c3fdac52f27a1cb04df4397c71f10f5f53d8b4b3f1cf95aa34e06eea8edeb'),
    (0x3d5138, 32, '53ee0a35b7a2deb4803e8e1a6f453b154d67f4d5547c5f21fb89ab4af3719477'),
    (0x377b98, 88, 'a4bfcf65e95bd89d9e7e4a74dd2170771118ef7d0f3d42bf4252ce5cacb9981d'),
    (0x20bcf50, 16, '1e388cbc6abfcaea15a594621b12166d31770b9fd5b90e85a125602d0eadce4f'),
    (0x20c414c, 36, '4e787986f0c0ebe8c05825f0a9e3da85852e23b34e0eb4d06a2bd19a579a7e6a'),
)
ENGLISH_SHA256 = '3ce742519bf694636f41a1dae8d45a3dab86fad7d164a58696139e4b4509dd43'
LABELS = {1: (321175, 'Abysmal'), 2: (447767, 'Extremely Poor'), 3: (227503, 'Very Poor'), 4: (227502, 'Poor'), 5: (447766, 'Quite Poor'), 6: (321174, 'Fairly Poor'), 7: (447765, 'Slightly Poor'), 8: (447764, 'Fair'), 9: (447763, 'Fairly Okay'), 10: (227501, 'Okay'), 11: (321173, 'Fairly Good'), 12: (447762, 'Quite Good'), 13: (227500, 'Good'), 14: (447761, 'Really Good'), 15: (227499, 'Very Good'), 16: (447760, 'Extremely Good'), 17: (447759, 'Excellent'), 18: (227498, 'Superb'), 19: (447758, 'Exceptional'), 20: (447757, 'Perfect')}


def verify_native(read, base):
    for rva, size, expected in NATIVE_GUARDS:
        if hashlib.sha256(read(base+rva,size)).hexdigest() != expected:
            raise ValueError(f'Career-morale native source changed at RVA {rva:#x}')
    if players.u64(read(base+players.RVA[0]+142*8,8)) != base+0xd32ba8:
        raise ValueError('Career-morale actual-player getter changed')


def decode(raw):
    if type(raw) is not int or not 0 <= raw <= 255:
        raise ValueError('Expected a stored career-morale byte')
    code = raw if raw < 128 else raw-256
    key, label = LABELS.get(code,(None,None))
    if code < 0:
        state, key, label = 'native_negative_code', 297209, 'Scouting Required'
    else:
        state = 'stored_named_morale' if label else 'outside_named_scale'
    return {'state':state,'raw_code':raw,'native_code':code,
            'english_definition_name':label,'english_resource_key':key,
            'scale':{'minimum':1,'maximum':20,'higher':'better_morale'},
            'source':'stored_career_player_morale','native_getter_mode':0,
            'scouting_mask_applied':False,'refreshed':False}


def inspect(read, base, primary, kind):
    if kind != 'actual':
        return {'state':'unsupported_record_kind','native_code':None,
                'english_definition_name':None,'english_resource_key':None,
                'source':'stored_career_player_morale'}
    if (type(primary) is not int or primary < 4096 or primary%8
            or world.pointer(read,primary) != base+players.RVA[0]):
        raise ValueError('Career-morale primary PLAYER type changed')
    return decode(read(primary+0x264,1)[0])
