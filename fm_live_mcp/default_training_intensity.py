"""Read existing managed-team default intensity policy; never materialize it.

Caller binds canonical ordinary PLAYER/PERSON, selected HUMAN/TEAM and career,
then rechecks the consumed source after its final lifetime callback. This is
one resolver's result at current stored condition, not medical clearance,
attendance, actual training control, workload or applied intensity.
"""
import hashlib
import struct
from . import individual_training_intensity as intensity, players, prepared_tactics_source, training_source, world

SCOPE = ('Native default resolver at current stored condition and existing selected '
         'HUMAN/TEAM policy. No native call or policy creation; medical overrides, '
         'actual training control, applied intensity and workload remain unverified.')


def verify_native(read,base):
    training_source.verify_native(read,base)
    for rva,n,digest in NATIVE_GUARDS:
        if hashlib.sha256(read(base+rva,n)).hexdigest()!=digest:
            raise ValueError('Native default-intensity source changed')


def _unavailable(reason):
    return dict(state='unavailable',reason=reason,native_code=None,english_definition_name=None,
                condition_band=None,applied_intensity=None,workload=None,scope=SCOPE)


def condition_band(raw):
    if type(raw)is not int or not -32768<=raw<=32767:
        raise ValueError('Expected signed native stored condition')
    # Exact signed /100 truncation and signed-byte conversion in2cf6060.
    rounded=raw+50
    percent=(abs(rounded)//100)*(1 if rounded>=0 else -1)
    percent=(percent+128)%256-128
    return 4 if percent>85 else 3 if percent>75 else 2 if percent>65 else 1 if percent>50 else 0


def _direct_training_team(read,base,primary,wanted):
    """Admit original2c98dbc's direct stored-TEAM/full-contract route only."""
    table=players.u64(read(primary,8));person=primary+0x388;common=primary+0x278
    if (struct.unpack('<q',read(table-0x20,8))[0]!=0x278
            or struct.unpack('<q',read(table-0x18,8))[0]!=0x388):
        raise ValueError('Training TEAM PLAYER base projections changed')
    event=players.u64(read(common+0x48,8))
    if event and read(event+0x4b,1)!=b'\0':
        return False  # Visited event alternatives require another proof.
    if players.u64(read(primary+0x128,8))!=wanted:return False
    person_table=players.u64(read(person,8))
    if (players.u64(read(person_table+0x3c0,8))!=base+0xcb8c68
            or struct.unpack('<q',read(person_table-0x3d0,8))[0]!=-0x110):
        raise ValueError('Training TEAM PERSON contract dispatch changed')
    main=players.u64(read(common+0x78,8))
    if not main:return False
    contract_table=players.u64(read(main,8))
    kind=next((name for name in ('full_contract','basic_contract','loan_contract','trial_contract')
               if contract_table==base+world.TYPES[name][0]),None)
    if kind is None:raise ValueError('Training TEAM main contract type changed')
    world.typed(read,base,main,kind)
    if players.u64(read(main+8,8))!=person:raise ValueError('Training TEAM main contract PERSON changed')
    if kind!='full_contract':return False
    main_team=players.u64(read(main+0x10,8))
    if not main_team:return False
    world.typed(read,base,main_team,'team')
    club=players.u64(read(wanted+0x30,8))
    if not club or players.u64(read(main_team+0x30,8))!=club:return False
    world.typed(read,base,club,'club')
    if read(club+0xba,1)!=b'\0':return False
    # Native cb85fc can substitute an affiliation parent before equality. Keep
    # its negative parent search; a nonnull matching parent is unsupported.
    if not read(club+0x163,1)[0]&16:
        for row in world.vector(read,club+0x118,1024):
            if players.u64(read(row+8,8))!=club:continue
            kind=read(row+0x30,1)[0]
            if kind<=20 and (1<<kind)&0x1001f0:
                if players.u64(read(row,8)):return False
                break
    contract_table=players.u64(read(main,8))
    if (players.u64(read(contract_table+0x90,8))!=base+0x129fffc
            or players.u64(read(contract_table+0x98,8))!=base+0xd88c8c):
        raise ValueError('Training TEAM full contract type/loan dispatch changed')
    # Ordinary senior TEAM returns directly unless competition UID6 reaches a
    # later youth TEAM selection. Do not assume stored TEAM always wins there.
    if read(wanted+0x28,1)!=b'\0':return False
    competition=players.u64(read(wanted+0x50,8))
    if competition:
        world.typed(read,base,competition,'competition')
        if int.from_bytes(read(competition+0xc,4),'little')==6:return False
    return True


def inspect(read,base,coach,primary):
    read=world.ReadSet(read)
    verify_native(read,base)
    team,human=prepared_tactics_source._team_and_human(read,base,coach)
    wanted=coach['team_address']
    if primary not in world.vector(read,wanted+0x38,256):
        raise ValueError('Default-intensity subject outside selected native roster')
    if (players.u64(read(primary,8))!=base+players.RVA[0]
            or players.u64(read(primary+0x140,8))!=base+players.RVA[1]):
        raise ValueError('Default-intensity subject must be checked ordinary PLAYER')
    if read(primary+0x1eb,1)!=b'\xff':
        read.verify();return dict(state='not_requested',reason='explicit_stored_intensity',native_code=None,
                                 english_definition_name=None,condition_band=None,applied_intensity=None,workload=None,scope=SCOPE)
    if not _direct_training_team(read,base,primary,wanted):
        read.verify();return _unavailable('training_team_source_outside_verified_direct_branch')
    if read(wanted+0x2f,1)!=b'\0':
        read.verify();return _unavailable('unsupported_national_training_context')
    if read(base+training_source.ASSIGNMENT_MODE,1)!=b'\x01':
        read.verify();return _unavailable('unsupported_training_assignment_mode')
    manager=players.u64(read(base+training_source.MANAGER_ROOT,8))
    if not manager:
        read.verify();return _unavailable('training_manager_missing')
    prepared_tactics_source._typed(read,base,manager,training_source.MANAGER_VTABLE,b'16TRAINING_MANAGER')
    # This direct native route requires the TEAM's active HUMAN owner.
    person=human+0x548;table=players.u64(read(person,8))
    if (players.u64(read(wanted+0x80,8))!=human
            or struct.unpack('<q',read(players.u64(read(human,8))-0x20,8))[0]!=0x548
            or players.u64(read(table+0x1b0,8))!=base+0x1300058
            or players.u64(read(table+0x6f0,8))!=base+0x1300074):
        raise ValueError('Default-intensity direct HUMAN dispatch changed')
    owner=None;node=None
    for record in training_source._vector(read,manager+0x38,training_source.OWNER_LIMIT):
        if players.u64(read(record+0x90,8))!=person:continue
        found=training_source._team_node(read,record,wanted)
        if found is None:continue
        if players.u64(read(record+0x98,8))!=players.u64(read(wanted+0x30,8)):
            raise ValueError('Default-intensity policy owner CLUB changed')
        owner,node=record,found
        break
    if owner is None:
        #2cabfb8 can try broader CLUB/association routes. None is fabricated.
        read.verify();return _unavailable('direct_policy_missing_native_fallback_unsupported')
    stored_condition=struct.unpack('<h',read(primary+0x254,2))[0]
    band=condition_band(stored_condition)
    # Existing3a1f1f0 lookup returns node+28; table is returned+60.
    code=read(node+0x88+band,1)[0]
    resolved=code if code<3 else 254
    definition=intensity.decode(resolved)
    read.verify()
    return dict(state='resolved_native_default',reason=None,native_code=definition['native_code'],
                english_definition_name=definition['english_definition_name'],condition_band=band,
                applied_intensity=None,workload=None,scope=SCOPE)


NATIVE_GUARDS = ((47144892, 552, '2b1df5bd94734639637774576cb337d583790e76b821dad29e8a53f34266f2d2'), (46841784, 548, '4b9160f3f830108c85c222f6d393ba3982854b2795b41e601eda420fc8a40216'), (60944880, 324, '294d672e25c5266d05f456f7f28f0bc1599356c02a65b2e188e24422741c1a44'), (19923032, 8, '5103ba3de080c52a046485f800433848701faa49ab8f60241a80987ca249d7ac'), (19923060, 20, '3f6f9d5a8b337d573adebd2a1339b59a12468aba23fb837448a097c1ff86c9fa'), (46763452, 564, 'a46e0ab942fdbeefca263ed71d6885049b730746b6bde10b7ed74940be3d956e'), (13339752, 20, '25c942ded4925619f93fb980c3fde293992b8e61aa50588e1f093c2a01e5cabb'), (13338108, 1644, '671f408e0f459d91457c63d89717b3937b07703b9bdeebfe868c1ad1baa62b62'), (19529724, 8, '2f6110664dbd16b514a0c2c7c8326932a36e85d2f15b91e57ca76efd2c7a625a'), (14191756, 8, '2f6110664dbd16b514a0c2c7c8326932a36e85d2f15b91e57ca76efd2c7a625a'), (46759240, 100, 'a7917604622f70aef06d7f86580fa993b5df085390e6a9c919a81813519e6812'))
