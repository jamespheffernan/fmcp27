"""Passive E1E354 range admission for caller-bound CLUB/context/COMP/NATION.

Native range codes remain internal. A Boolean is one admission dependency,
never permission to expose player attributes or a complete search result.
The GAME_CLUB override is specialized to this caller's same mode/flag gate.
"""
import hashlib
import struct

from . import knowledge_transfer_predicate as transfer
from . import world

NATIVE_GUARDS = (
    (0xe1e354,472,'1277c441fd97593e88a1c04286306bd7cf8fa5fe796941b1a8fd4f51ab546629'),
)
OVERRIDE_GUARDS = (
    (0x1fa72c4,744,'9daa40a22b8a99833db2242ca38f9dce844474e6c82a6eab883c67f9ed66dd6a'),
    (0x169552c,644,'114c335d315c5479e32146ec583b3abcd1fba7625e02dd4b4f7df32db795b370'),
)


def _first_team(reader,club):
    start,count=reader.bounds(club+0x18,8,4096)
    if not count:return 0
    team=reader.ptr(start)
    if team:reader.team(team)
    return team


def _competition(reader,team):
    if not reader.ptr(team+0x30):return 0
    competition=reader.ptr(team+0x50)
    if competition:reader.entity(competition,('competition',))
    return competition


def _shared_region(reader,definition,other):
    # Both objects are canonical COMPETITIONs. These are native opaque
    # projections/keys, compared only; their English meaning is not inferred.
    left=reader.ptr(definition+0xb0)
    if not left:return False
    left=reader.ptr(left+0x7c8)
    if not left:return False
    right=reader.ptr(other+0xb0)
    return bool(right and reader.ptr(right+0x7c8)==left)


def _override(reader,club):
    for rva,n,digest in OVERRIDE_GUARDS:
        if hashlib.sha256(reader.read(reader.base+rva,n)).hexdigest()!=digest:
            raise ValueError('Scouting range override native source changed')
    service=reader.ptr(reader.base+0x56d2ce8)
    world.typed(reader.read,reader.base,service,'game_club')
    reader.route(reader.ptr(service),0x168,0x1fa72c4)
    if reader.u8(club+0x161)&64 or reader.i32(club+0xc)==0xd70dd0:return 1
    team=_first_team(reader,club)
    if not team:return 1
    has_next=reader.ptr(team+0x58)!=0
    home=reader.ptr(club+0xd8)
    if not home:return 4
    reader.entity(home,('nation',))
    definition=reader.ptr(team+(0x58 if has_next else 0x50))
    if definition:reader.entity(definition,('competition',))
    projection=reader.ptr(home+(0x118 if reader.u8(club+0xb9)!=0 else 0x110))
    if projection:reader.entity(projection,('national_team_container',))
    if not definition or not projection:return 4
    # This E1E354 caller reaches1FA72C4 only when mode951 is not1/2 and
    # flag96E bit0 is set. Under the same checked ReadSet,169552C therefore
    # takes552C..5564 ->56FC..5714, stores7 and returns true. All later
    # reputation/finance arithmetic in1FA72C4 is unreachable for this caller.
    if reader.u8(reader.base+0x56d4951) in (1,2) or not reader.u8(reader.base+0x56d496e)&1:
        raise ValueError('Scouting range override caller gate changed')
    return 7


def admitted(reader,club,context,definition,nation):
    """Caller binds context to the selected HUMAN's owned personal data."""
    transfer._pointer(context)
    reader.entity(club,('club',))
    if definition:reader.entity(definition,('competition',))
    if nation:reader.entity(nation,('nation',))
    for rva,n,digest in NATIVE_GUARDS:
        if hashlib.sha256(reader.read(reader.base+rva,n)).hexdigest()!=digest:
            raise ValueError('Scouting range native source changed')
    code=reader.u8(context+0x1cc)
    mode=reader.u8(reader.base+0x56d4951)
    if mode not in (1,2) and reader.u8(reader.base+0x56d496e)&1:
        code=_override(reader,club)
    if code==7:return True
    if code not in (2,3,4,5,6):return False
    home=0
    if code!=2:
        home=reader.ptr(club+0xd8)
        if home:reader.entity(home,('nation',))
    if code==4:return home==nation
    if code in (5,6):
        if not home or not nation:return False
        offset=0x100 if code==5 else 0xf8
        return reader.ptr(nation+offset)==reader.ptr(home+offset)
    if code==3 and home!=nation:return False
    team=_first_team(reader,club)
    if not team:return code==2 and not definition
    other=_competition(reader,team)
    if code==2:
        if other==definition:return True
        return bool(definition and other and _shared_region(reader,definition,other))
    if not definition or not other:return False
    if definition==other or _shared_region(reader,definition,other):return True
    left=struct.unpack('<b',reader.read(definition+0x1aa,1))[0]
    right=struct.unpack('<b',reader.read(other+0x1aa,1))[0]
    return left in (right-1,right+1)
