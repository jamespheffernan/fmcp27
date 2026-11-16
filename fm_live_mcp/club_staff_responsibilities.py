"""Own stored CLUB responsibility records, separate from effective delegation.

Caller supplies a save-bound read set and verifies all consumed bytes after the
last process/save callback. No source construction or native getter is invoked.
"""
import hashlib
import struct
from . import assessment_people, database, world

SLOT_LIMIT = 4096

LIMITATIONS = ('Own stored responsibility records only. Stored references are distinct from '
    'the effective native delegate: affiliation inheritance, default job selection, eligibility, '
    'native session edits and outer suppression are not evaluated. A missing own vector is '
    'unavailable, not empty. Duplicate and null physical slots remain accounted for. '
    'Descriptions are pinned English resource templates; placeholders are not expanded and '
    'unknown descriptions remain null. No coaching stars, workload, current employment, '
    'fitness, suitability or complete UI responsibility population is inferred.')


def _read(read, address, size):
    if type(address) is not int or address < 4096 or type(size) is not int or not 0 < size <= 16384 or address+size >= 1<<64:
        raise ValueError('Invalid responsibility read geometry')
    raw = read(address,size)
    if len(raw) != size:
        raise ValueError('Incomplete responsibility read')
    return raw


def _pointer(read, address, nullable=False):
    value = struct.unpack('<Q',_read(read,address,8))[0]
    if value == 0 and nullable:
        return 0
    if value < 4096 or value%8:
        raise ValueError('Invalid responsibility pointer')
    return value


def verify_native(read, base):
    if type(base) is not int or base < 4096 or base%4096:
        raise ValueError('Invalid responsibility native image base')
    for rva,size,digest in NATIVE_SPANS:
        if hashlib.sha256(_read(read,base+rva,size)).hexdigest() != digest:
            raise ValueError(f'Responsibility native source changed at {rva:#x}')


def _slots(read, vector):
    start,end,capacity = struct.unpack('<QQQ',_read(read,vector,24))
    if (start,end,capacity) == (0,0,0):
        return []
    if (start < 4096 or any(value%8 for value in (start,end,capacity))
            or not start <= end <= capacity or capacity-start > SLOT_LIMIT*8):
        raise ValueError('Invalid responsibility vector bounds or reader budget')
    return [struct.unpack('<Q',_read(read,at,8))[0] for at in range(start,end,8)]


def _reference(read, base, people, value, mode):
    root = people['root']
    person = 0
    if mode == 1:
        encoding = 'PERSON_table_index'
        if value < 0:
            return dict(state='negative_native_index',encoding=encoding,stored_value=value,person=None)
        flag = _read(read,base+0x56D34E0,1)[0]
        if not flag&1:
            fast,end = struct.unpack('<QQ',_read(read,root+0x68,16))
            if (fast,end) != (0,0) and (fast < 4096 or fast%8 or end%8 or not fast <= end or end-fast > 2_000_000*8):
                raise ValueError('Invalid responsibility fast PERSON table geometry')
            if fast and value < (end-fast)//8:
                person = _pointer(read,fast+value*8,True)
            elif value < people['count']:
                person = _pointer(read,people['start']+value*8,True)
        elif value < people['count']:
            person = _pointer(read,people['start']+value*8,True)
    else:
        encoding = 'PERSON_native_id'
        if value == -1:
            return dict(state='native_unassigned_id',encoding=encoding,stored_value=value,person=None)
        if _read(read,root+0x64,1)[0]&1:
            if _read(read,root+0xA8,1)[0] == 1:
                return dict(state='native_id_lookup_requires_sort',encoding=encoding,stored_value=value,person=None)
            start,end = struct.unpack('<QQ',_read(read,root+0x90,16))
        else:
            start,end = people['start'],people['start']+people['count']*8
        if (start < 4096 or start%8 or end%8 or not start <= end or end-start > 2_000_000*8):
            raise ValueError('Invalid responsibility native-ID vector geometry')
        lo,hi = 0,(end-start)//8-1
        for _ in range(32):
            if lo > hi:
                break
            mid = (lo+hi)//2
            candidate = _pointer(read,start+mid*8)
            found = struct.unpack('<i',_read(read,candidate+12,4))[0]
            if found == value:
                person = candidate
                break
            if found > value:
                hi = mid-1
            else:
                lo = mid+1
        else:
            raise ValueError('Responsibility native-ID search depth exceeded')
    if not person:
        return dict(state='native_reference_not_found',encoding=encoding,stored_value=value,person=None)
    from .knowledge_retained_person import _native_hidden
    if _native_hidden(read,base,person):       # 27.0.1: the resolver drops a PERSON whose virtual +0x510 is true
        return dict(state='native_hidden_person',encoding=encoding,stored_value=value,person=None)
    public = assessment_people.assessor(read,base,people,person)
    return dict(state='resolved_stored_reference',encoding=encoding,stored_value=value,person=public)


def decode(read, base, club_address):
    verify_native(read,base)
    club,_ = world.club(read,base,club_address)
    clubs = database.table(read,base,'clubs')
    index = struct.unpack('<I',_read(read,club_address+8,4))[0]
    database.club_membership(read,base,clubs,index,club_address)
    out = dict(state='unavailable',club={**club,'database_index':index},records=None,
        source_slot_count=None,null_slot_count=None,source='own_stored_CLUB_responsibility_records',
        effective_assignments=None,complete_effective_allocation_verified=False,
        affiliation_fallback_evaluated=False,description_language='pinned_English_resource_templates',
        english_resource_sha256=ENGLISH_RESOURCE_SHA256,limitations=LIMITATIONS)
    secondary = _pointer(read,club_address+0xB0,True)
    if not secondary:
        out['reason'] = 'native_owner_secondary_unavailable'
        return out
    vector = _pointer(read,secondary+0x48,True)
    if not vector:
        out['reason'] = 'own_vector_absent_native_affiliation_fallback_not_evaluated'
        return out
    slots = _slots(read,vector)
    people = database.table(read,base,'people') if any(slots) else None
    rows = []
    for slot,address in enumerate(slots):
        if not address:
            rows.append(dict(slot=slot,state='null_slot',responsibility_code=None,
                description_template=None,description_resource_key=None,team_type_code=None,
                stored_reference=None,reference_mode=None,unmapped_record_bytes_6_8=None))
            continue
        if address < 4096 or address%4:
            raise ValueError('Invalid responsibility row pointer')
        raw = _read(read,address,10)
        code,team_type,mode = raw[4],struct.unpack_from('<b',raw,5)[0],raw[9]
        key,description = DESCRIPTION_TEMPLATES.get(code,(None,None))
        rows.append(dict(slot=slot,state='stored_record',responsibility_code=code,
            description_template=description,description_resource_key=key,
            team_type_code=team_type,reference_mode=mode,unmapped_record_bytes_6_8=raw[6:9].hex(),
            stored_reference=_reference(read,base,people,struct.unpack_from('<i',raw)[0],mode)))
    out.update(state='available_own_stored_records',reason=None,records=rows,
        source_slot_count=len(slots),null_slot_count=slots.count(0))
    return out
NATIVE_SPANS = ((24876376, 312, '5cdd26745bcd5dd4b94a929ce5260436c6a74df245748196ada53f50752ad7c0'),
 (36512744, 296, 'a9c9c11de8097ede31de0cab6b159628f8ff8dfa75df2cbe93bba0f942104424'),
 (22812836, 632, '0a979f02b341e88c5988157dbb5df5d397d4f4557f569b59fd1fe573753de0e6'),
 (22767188, 104, 'e1d4e862c689024285f94f3fc10d78a84beff8cbb1bdbfd4b0e36902460771a3'),
 (22767292, 72, '216aefcd90604544aa5275275b150814eeb4dcfb66b67de8f0a2233a80976da7'),
 (17321124, 300, 'b6823950094e48633de8533ebaf0cdd8d9d10ff0a110f74a98b9cfc41b009eac'),
 (22811220, 256, '84586b709895e10c958a560e2c6524035d8c71f250a53968435daf0f484d03c5'),
 (22805704, 2568, 'd6b930bc26ec77f50e4d578f4e5471d732cb3819d3472e8934783e114d340663'),
 (87682222, 182, '57b55323221935877797075f8f5336c3e13e50892504f67077887a3a932c577d'))
ENGLISH_RESOURCE_SHA256 = '3ce742519bf694636f41a1dae8d45a3dab86fad7d164a58696139e4b4509dd43'
DESCRIPTION_TEMPLATES = {100: (492371, 'Provides financial support to the club as and when needed.'),
 101: (492372, 'The face of the club in the media regarding club-related issues.'),
 102: (492373, "Sets out and develops the club's long-term vision."),
 110: (492374, 'Takes charge of all meetings about scouting.'),
 111: (492375, 'Collates and provides feedback on scouting assignments.'),
 112: (492376, 'Manages the general assignments of the scouting team.'),
 113: (513356, 'Collates and provides scouting reports on the next opponent.'),
 114: (513358, 'Collates and provides analysis reports on the opposition.'),
 115: (513357, 'Collates and provides analysis reports on our own team.'),
 122: (492380,
       'Finds suitable [%job#2] candidates, brings them to the club and evaluates their performance.'),
 123: (492381, 'Negotiates new contracts with the [%job#2].'),
 124: (492380,
       'Finds suitable [%job#2] candidates, brings them to the club and evaluates their performance.'),
 125: (492381, 'Negotiates new contracts with the [%job#2].'),
 128: (492380,
       'Finds suitable [%job#2] candidates, brings them to the club and evaluates their performance.'),
 129: (492381, 'Negotiates new contracts with the [%job#2].'),
 130: (492380,
       'Finds suitable [%job#2] candidates, brings them to the club and evaluates their performance.'),
 131: (492381, 'Negotiates new contracts with the [%job#2].'),
 134: (492380,
       'Finds suitable [%job#2] candidates, brings them to the club and evaluates their performance.'),
 135: (492381, 'Negotiates new contracts with the [%job#2].'),
 138: (492382, 'Responsible for hiring and firing the [%job#2].'),
 139: (492381, 'Negotiates new contracts with the [%job#2].'),
 140: (492383, 'Decides who to keep on the coaching staff, who to bring in, and who to let go.'),
 141: (492384, 'Negotiates new contracts with the coaching staff.'),
 142: (492385, 'Maintains the medical department, bringing in new staff, and deciding who to let go.'),
 143: (492386, 'Negotiates new contracts with the medical staff.'),
 144: (492387, 'Oversees the scouting department, bringing in new faces and allowing others to leave.'),
 145: (492388, 'Negotiates new contracts with the scouting staff.'),
 150: (492389, 'Tasked with making initial transfer offers for potential new signings.'),
 151: (492390, 'Negotiates transfer deals when the initial offer is not immediately accepted.'),
 152: (492391, 'Finalises transfer deals when an agreement has been found.'),
 153: (492392,
       'Tasked with offloading players through offering them to other clubs, on loan or permanently, or '
       'through a mutual termination of their contract.'),
 154: (492393, 'Negotiates player sales when an interested party submits an unsatisfactory offer.'),
 155: (492394, 'Finalises player sales when a deal has been agreed.'),
 156: (492395, 'Deals with contract discussions for players.'),
 157: (492396, 'Collates and provides feedback on players who are out on loan.'),
 158: (705518, 'Makes decisions on loan offers for young players not in the First Team squad.'),
 160: (494128,
       'Handles team training in general, creating schedules for the squad and identifying areas to focus '
       'on.'),
 161: (492399, 'Handles individual training where players need to improve a specific area of their game.'),
 162: (492400, 'Collates and provides player reports.'),
 163: (496404, 'Brings through the next generation of young players coming through the ranks at the club.'),
 164: (492402, 'Collates and provides reports on staff development.'),
 165: (492403, 'Decides which coaches should undertake further education on courses.'),
 170: (492404, 'Responsible for selecting and managing the team.'),
 171: (492405, 'Takes charge of friendly matches.'),
 172: (492406, 'Provides team line-up suggestions with reasons for potential selections.'),
 175: (492409, 'Prepares and implements specific instructions to handle opposition players.'),
 176: (492410, 'Leads team talks.'),
 180: (504223, 'Attends league pre and post-match press conferences.'),
 181: (492412, 'Attends press conferences to unveil new signings.'),
 182: (515196, 'Attends pre and post-match broadcast interviews.'),
 183: (504224, 'Attends domestic cup pre and post-match press conferences.'),
 184: (504225, 'Attends continental cup pre and post-match press conferences.'),
 185: (509739, 'Provides updates on commercial operations'),
 186: (509740, 'Provides updates on facilities'),
 187: (509741, 'Provides updates on financial operations'),
 188: (585473, 'Manages the tactical instructions the team should execute during set piece routines'),
 189: (585471, 'Maintains the priority lists of set piece takers'),
 190: (585475, 'Maintains the priority lists of set piece personnel')}
