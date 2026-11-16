"""Join official commentary actor UIDs through canonical same-match actors.

The native producer uses original side/roster slots and MATCH_INFO's UID setup.
A joined actor name is not an entry/exit role or evidence of playing membership.
"""
import struct
from . import frame_attack_direction as direction

NATIVE_SPANS = (
    (0x73E388,bytes.fromhex("ff4302d1fa6704a9f85f05a9f65706a9f44f07a9fd7b08a9fd030291f50306aaf80305aaf30304aaf40303aaf60302aaf90301aafa0300aa688c40391f0100718800805217159f1ae8830091e20303aae30317aa0400805293820695e81b40f90003c03d090b40f9e91b00f9e10bc03de00b803d0103803d080b00f9e8030091e0031aaae10319aae20314aa830080520400805284820695e80b40f9a002c03da90a40f9e90b00f9e103c03de003803da102803da80a00f9e00314aae10317aa69d5ff97480080521f00007118119f1ae00314aa01008052e8bf0595151c0013e00315aac59f0595f70300aa8042c079aa760d9508031e32ff0200710811981a09011d321f0000713711881a99064039080080123f07007168020054980240391f67007108020054e00316aaa50d0094b90000340860c039c800f8370801180b04000014095cc039091bf8372801180b081d4093c92e48f90a068052087d2a9b286968b8680200b9990e4039080080123f07007168020054980a40391f67007108020054e00316aa8e0d0094b90000340860c039c800f8370801180b04000014095cc039a918f8372801180b081d4093c92e48f90a068052087d2a9b286968b8680600b999164039080080123f07007168020054981240391f67007108020054e00316aa770d0094b90000340860c039c800f8370801180b04000014095cc0394916f8372801180b081d4093c92e48f90a068052087d2a9b286968b8680a00b9991e4039080080123f07007168020054981a40391f67007108020054e00316aa600d0094b90000340860c039c800f8370801180b04000014095cc039e913f8372801180b081d4093c92e48f90a068052087d2a9b286968b8680e00b999264039080080123f07007168020054982240391f67007108020054e00316aa490d0094b90000340860c039c800f8370801180b04000014095cc0398911f8372801180b081d4093c92e48f90a068052087d2a9b286968b8681200b9982e4039080080121f07007188020054992a40393f67007128020054e00316aa320d0094b80000340860c039c800f8370801190b04000014095cc039290ff8372801190b081d4093c92e48f90a068052087d2a9b286968b8982e4039681600b9880640391f050071e8179f1a890e40394a0080524a158a1a3f0500714801881a891640390a011e323f0500714801881a891e40390a011d323f0500714801881a892640393f050071e9179f1a08751a12296d1c531f070071ea179f1a29150a2a2801082a6862003989428079ca7c02904a611e91283d00124a0140f9490d098bea3f9f9229696af8e90000b42aa540395f010071ea079f1af7020a2a29ad40396996003977920039759a003968360079881640b9681e00b9e00314aa21008052a2c00595602200b9880e40b9682a00b9f40340f9337b02d0f40100b4e00740f9e10314aa1f0014ebc0000054002000d12228f1941f0014eba1ffff54e10340f9f40700f9e80b40f9020101cb604a45f9c15df094f41340f9f40100b4e01740f9e10314aa1f0014ebc0000054002000d11228f1941f0014eba1ffff54e11340f9f41700f9e81b40f9020101cb604a45f9b15df094fd7b48a9f44f47a9f65746a9f85f45a9fa6744a9ff430291c0035fd60860c03988e4ff36e80309aa27ffff170860c039e8e6ff36e80309aa3affff170860c03948e9ff36e80309aa4dffff170860c039a8ebff36e80309aa60ffff170860c03908eeff36e80309aa73ffff170860c03968f0ff36e80309aa86ffff17f599e397f499e39709000014080000140700001406000014f30300aae0830091cd85e497e00313aa92be0e95f30300aae0030091c885e497e0830091c685e497e00313aa8bbe0e95")),
    (0x741B48,bytes.fromhex("00100091c0035fd6")),
    (0x738FC8,bytes.fromhex("a002138ba1a20091e2030091f4120094")),
    (0x73DBC0,bytes.fromhex("f30302aaf50301aaf40300aa")),
    (0x73DD28,bytes.fromhex("954e04f9")),
    (0x73E27C,bytes.fromhex("824e44f98022029181a22191e30313aa3f000094")),
)


def verify_native(read,base):
    for at,expected in NATIVE_SPANS:
        if direction._read(read,base+at,len(expected)) != expected:
            raise ValueError('Native official commentary actor constructor changed')


def project(rows,actors):
    # actors must come from the same fixture's canonical typed original-slot
    # capture, with its native MATCH_PLAYER UID. No current tactics slots.
    if not isinstance(rows,list) or len(rows)>8192 or not isinstance(actors,list) or len(actors)>52:
        raise ValueError('Unsupported commentary actor budget')
    mapping={}
    canonical=set()
    for actor in actors:
        side,uid,person=(actor.get(k) for k in ('side_index','engine_playback_uid','canonical_person_id'))
        if type(side) is not int or side not in (0,1) or type(uid) is not int or not 0<=uid<0xFFFFFFFF:
            raise ValueError('Invalid native commentary actor identity')
        if type(person) is not int or person<=0 or person in canonical or (side,uid) in mapping:
            raise ValueError('Ambiguous canonical commentary actor identity')
        canonical.add(person);mapping[side,uid]=actor
    output=[]
    for row in rows:
        ids,bits=row.get('player_ids_raw'),row.get('player_teams_bits_raw')
        if not isinstance(ids,list) or len(ids)!=6 or any(type(uid) is not int or not 0<=uid<=0xFFFFFFFF for uid in ids):
            raise ValueError('Unsupported official event PlayerID fields')
        if type(bits) is not int or not 0<=bits<=255:
            raise ValueError('Unsupported official event PlayerTeams field')
        players=[]
        for slot,uid in enumerate(ids):
            side=(bits>>slot)&1
            actor=mapping.get((side,uid))
            players.append({'event_player_field':slot+1,'playback_uid':uid,'side_index':side,
                'canonical_person_id':actor['canonical_person_id'] if actor else None,
                'person_name':actor.get('person_name') if actor else None,
                'identity_state':'same_match_canonical_original_slot_native_uid' if actor else 'unavailable_canonical_actor_for_event_uid',
                'participation_role':None,'on_pitch':None})
        output.append({**row,'event_players':players})
    return {'state':'commentary_actor_identities_only','rows':output,
        'source_namespace':'official_MATCH_INFO_original_slot_player_UID',
        'substitution_actor_roles_verified':False,'historical_on_pitch_verified':False}


def capture(read,base,bound,rows,actors):
    """Reconcile constructor UID setup before canonical commentary labels."""
    if not isinstance(actors,list) or len(actors)>52:
        raise ValueError('Unsupported canonical commentary actor budget')
    verify_native(read,base)
    info=bound['playback_address']+0x28
    if direction._q(read,bound['playback_address']+0x1418+0x898) != info:
        raise ValueError('Official commentary MATCH_INFO owner changed')
    bases=direction._read(read,info+0x1B,2)
    table_raw=direction._read(read,info+0x1058,8)
    table=struct.unpack('<Q',table_raw)[0]
    direction._pointer(table)
    matched=[];unresolved=[];operands=[]
    for actor in actors:
        side,slot=actor.get('side_index'),actor.get('stored_player_slot')
        if type(side) is not int or side not in (0,1) or type(slot) is not int or not 0<=slot<26:
            raise ValueError('Invalid canonical original actor slot')
        native_base=struct.unpack_from('<b',bases,side)[0]
        if native_base<0 or native_base+slot>=128:
            unresolved.append({'side_index':side,'stored_player_slot':slot,'reason':'unavailable_native_original_side_base'})
            continue
        raw=direction._read(read,table+48*(native_base+slot),4)
        operands.append((side,slot,raw))
        if struct.unpack('<I',raw)[0]!=actor.get('engine_playback_uid'):
            unresolved.append({'side_index':side,'stored_player_slot':slot,'reason':'native_MATCH_INFO_and_MATCH_PLAYER_uid_disagree'})
            continue
        matched.append(actor)
    return project(rows,matched) | {'unresolved_canonical_actor_setup':unresolved,
        '_source':(bases,table_raw,operands),'_rows':rows,'_actors':actors,
        'official_match_unique_id':bound['official_match_unique_id']}


def verify_capture(read,base,bound,captured):
    again=capture(read,base,bound,captured['_rows'],captured['_actors'])
    if again!=captured:
        raise ValueError('Official commentary actor UID setup changed')
    return captured | {'native_actor_uid_setup_physically_reselected':True}
