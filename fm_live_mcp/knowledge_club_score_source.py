"""Private passive E076BC/1FA64D8 score for ordinary actual/combined PERSON.

This reproduces the mode0 caller and its age output bytes from checked native
tables. Scores and private operands must never become model-visible facts or
ranking inputs. No player attributes, live calls, cache creation or writes.
"""
from copy import deepcopy
import hashlib
import struct

from . import database,knowledge_inputs,prepared_tactics_source,world
from . import knowledge_transfer_predicate as transfer
from . import knowledge_competition_context_source as context_source
from . import knowledge_search_admission as age
from . import knowledge_context_score as core

NATIVE_GUARDS = (
    (0xe076bc,580,'814a213ea4b5f7a8c59604aa7d3b76e319ea6c19597c3c14b81e318410492358'),
    (0x1fa64d8,1664,'b3e5b811fd6cdb270bee23596efd09c9d565565ff0df49cb52c71b36a1e301b8'),
    (0xd5c344,8,'5103ba3de080c52a046485f800433848701faa49ab8f60241a80987ca249d7ac'),
    (0x53b0998,232,'2b21e60f0d7c171524109ae0f2094fa92270471f2d665b6ed580ab8e8db52f4f'),
    (0xca4640,24,'0a3f211c122334f1ccd799afcee3155b50897632e8b5fa2d6a97f6c15006c8eb'),
    (0x148f4c0,84,'0bbcb291971498f3812946f0484bef7bbd3cc1cef6299c9ddfb13971e8e8326e'),
    (0x3d574b0,412,'78b0d4b5f4560c664509fecaf04e43d17aa48dce579c84d5aa02e1fac5491664'),
)


def signed(value,bits=8):return (value+(1<<(bits-1)))%(1<<bits)-(1<<(bits-1))


def _half(score):return signed(max(int(score/2),3)*5)


def _region_scale(score):
    product=(score*86)&0xffffffff
    rounded=signed((product>>8)+((product>>15)&1))
    return signed(max(rounded,2)*5)


def _quarter(score):return signed(max(int(score/4),1)*5)


def verify_native(read,base):
    # Pinned-code guard: the same answer for the whole of a journalled bulk call.
    memo=knowledge_inputs.call_memo(read)
    if memo is not None:
        return memo(('verify_native','club_score',base),lambda:_verify_native(read,base))
    return _verify_native(read,base)


def _verify_native(read,base):
    context_source.verify_native(read,base)
    for rva,n,digest in NATIVE_GUARDS:
        if hashlib.sha256(read(base+rva,n)).hexdigest()!=digest:
            raise ValueError('Club-score native source changed')


class Reader(transfer._Reader):
    def bounds2(self,address,width,limit=100000):
        start,end=struct.unpack('<QQ',self.read(address,16))
        if (start,end)==(0,0):return 0,0
        if (start<4096 or start%8 or end%8 or not start<=end<1<<64
                or (end-start)%width or end-start>width*limit):
            raise ValueError('Invalid club-score source bounds or budget')
        return start,(end-start)//width

    def geographic(self,address,kind):
        table,name,source=((0x55ba7b8,b'N2db6REGIONE','regions') if kind=='region'
                           else (0x55a06b0,b'N2db9CONTINENTE','continents'))
        prepared_tactics_source._typed(self.read,self.base,address,table,name)
        identity=struct.unpack('<III',self.read(address+8,12));info=self.table(source)
        if not identity[1] or identity[0]>=info['count'] or self.ptr(info['start']+8*identity[0])!=address:
            raise ValueError('Club-score geographic canonical identity changed')
        return identity

    def key(self,address,kind):
        if not address:return -1
        identity=self.geographic(address,kind) if kind in ('region','continent') else self.entity(address,(kind,))[1]
        return signed(identity[1],32)

    def project(self,nation,alternate):
        self.entity(nation,('nation',))
        result=self.ptr(nation+(0x118 if alternate else 0x110))
        if result:self.entity(result,('national_team_container',))
        return result

    def lower(self,start,count,width,target,key):
        while count:
            half=count//2;middle=start+half*width
            if key(middle)<target:start=middle+width;count-=half+1
            else:count=half
        return start

    def first_team(self,club):
        start,count=self.bounds2(club+0x18,8,4096)
        team=self.ptr(start) if count else 0
        if team:self.team(team)
        return team

    def native_age(self,person):
        _,common,_,_=self.person(person);table=self.ptr(person)
        self.route(table,0x138,0x148f4c0);self.route(table,0x1b8,0xca4640)
        self.adjustment(table,0x1c8,-0x110)
        birth=age.NativeDate.from_bytes(self.read(common+0x58,4))
        core.NativeDate(birth.year,birth.day_word).validate_calendar()
        if birth.default:return 0
        return self.native_age_from_birth(birth)

    def native_age_from_birth(self,birth):
        # The date-dependent tail of native_age, separate so a caller can record it as one fact.
        at=age.NativeDate.from_bytes(self.read(self.base+0x52efdf0,4))
        mode=current=alternate=fallback=None;selected=at
        if at.default:
            mode=self.u8(self.base+0x56d4951);rules=self.ptr(self.base+0x56d57d0)
            if mode in (1,2):
                prepared_tactics_source._typed(self.read,self.base,rules,0x55dd068,b'23GAME_RULE_GROUP_MANAGER')
                alternate=selected=age.NativeDate.from_bytes(self.read(rules+0x184,4))
            else:current=selected=age.NativeDate.from_bytes(self.read(self.base+world.CURRENT_DATE,4))
        core.NativeDate(selected.year,selected.day_word).validate_calendar()
        if selected.year==1900:fallback=int.from_bytes(self.read(self.base+0x56b3390,2),'little')
        return age.person_age(birth,at,mode=mode,current_date=current,alternate_date=alternate,fallback_year=fallback)

    def subject_allowed(self,raw,low,high,home,person):
        if raw==254:
            if not person:return False
            uid=self.person(person)[3][1];home_id=int.from_bytes(self.read(home+0xc,4),'little')
            if (((uid+home_id)*0xcccccccd+0x19999999)&0xffffffff)>0x33333332:return False
        if person:
            table=self.ptr(person);self.route(table,0x4d8,0xd5c344)
            if signed(low)>14 or signed(high)<=44:
                value=self.native_age(person)
                if not signed(low)<=value<=signed(high):return False
        return True

    def table_row(self,header,target,kind):
        start,count=self.bounds2(header,16);end=start+16*count
        key=lambda row:self.key(self.ptr(row+8),kind)
        row=self.lower(start,count,16,self.key(target,kind),key)
        return row if row!=end and self.key(target,kind)>=key(row) else 0

    def shortlist_override(self,club,projection):
        manager=self.ptr(self.base+0x56a4be0)
        prepared_tactics_source._typed(self.read,self.base,manager,0x55f80a0,b'17SHORTLIST_MANAGER')
        start,count=self.bounds2(manager+0x650,32);end=start+32*count
        if not count:return None
        if not projection:raise transfer.SourceUnavailable('Null native club-score target projection')
        nation=self.ptr(projection+0x170);self.entity(nation,('nation',))
        uid=signed(self.club(club)[1],32)
        row=self.lower(start,count,32,uid,lambda at:self.i32(at))
        if row==end or uid<self.i32(row):return None
        begin,n=self.bounds2(row+8,8);nation_uid=self.key(nation,'nation')
        for offset in range(n):
            at=begin+8*offset
            if self.i32(at)==nation_uid:return self.u8(at+4)
        return None

    def game_score(self,club,projection,person,low=14,high=45):
        home=self.ptr(club+0xd8)
        if not home:return 0,low,high
        home_projection=self.project(home,self.u8(club+0xb9)!=0)
        if not home_projection:return 0,low,high
        raw=self.shortlist_override(club,projection)
        if raw not in (None,0,255) and self.subject_allowed(raw,low,high,home_projection,person):
            return _half(signed(raw)),low,high
        if not projection:raise transfer.SourceUnavailable('Null native club-score target projection')
        self.entity(projection,('national_team_container',))
        row=self.table_row(home_projection+0xf0,projection,'national_team_container')
        if row:
            raw=self.u8(row);low=self.u8(row+2);high=self.u8(row+1)
            if raw not in (0,255) and self.subject_allowed(raw,low,high,home_projection,person):
                return _half(signed(raw)),low,high
        if not row:low,high=14,45
        nation=self.ptr(projection+0x170);self.entity(nation,('nation',))
        region=self.ptr(nation+0x100)
        if not region:return 0,low,high
        region_identity=self.geographic(region,'region')
        row=self.table_row(home_projection+0x120,region,'region')
        if row:
            raw=self.u8(row);low=self.u8(row+2);high=self.u8(row+1)
            if raw not in (0,255) and self.subject_allowed(raw,low,high,home_projection,person):
                return _region_scale(signed(raw)),low,high
        low,high=14,45
        if not 1<=region_identity[1]<=29:return 0,low,high
        index=int.from_bytes(self.read(self.base+0x53b0998+(region_identity[1]-1)*8,8),'little')
        continents=self.table('continents')
        if index>=continents['count']:raise ValueError('Native continent mapping index exceeds table')
        continent=self.ptr(continents['start']+8*index)
        if not continent:return 0,low,high
        self.geographic(continent,'continent')
        start,count=self.bounds2(home_projection+0x108,16)
        for offset in range(count):
            row=start+16*offset
            if self.ptr(row+8)!=continent:continue
            raw=self.u8(row);low=self.u8(row+2);high=self.u8(row+1)
            if raw not in (0,255) and self.subject_allowed(raw,low,high,home_projection,person):
                return _quarter(signed(raw)),low,high
            return 0,low,high
        return 0,low,high

    def retained_mode(self,definition):
        projection=self.ptr(definition+0xb0)
        if not projection:return False
        active=int.from_bytes(self.read(self.base+0x56d3518,4),'little')
        group=self.ptr(projection+0x138)
        key=int.from_bytes(self.read(group+0xc,4),'little') if group else 0xffffffff
        if active!=key:
            flags=int.from_bytes(self.read(projection+0x4c,4),'little')
            if flags&64 or self.u8(projection+0x4c0)==3:return False
            if flags&0x20000 or self.ptr(projection+0x510):return False
            settings=self.ptr(projection+0x388);code=self.u8(settings+0x23c) if settings else None
            if code==3 or struct.unpack('<h',self.read(projection+0x3b6,2))[0]==-3:return False
            if code==1 and context_source._classified(self.u8(projection+0x3be)):return False
        return not context_source.predicate(self,definition)

    def score(self,club,nation,person):
        low,high=14,45;self.club(club)
        if person:self.person(person)
        if not nation:return 0,low,high
        self.entity(nation,('nation',));home=self.ptr(club+0xd8)
        if not home:return 0,low,high
        self.entity(home,('nation',));projection=self.project(nation,self.u8(club+0xb9)!=0)
        store=self.ptr(club+0x100)
        if not store:raise transfer.SourceUnavailable('Missing native CLUB score store')
        header=self.ptr(store+0x38);use_rows=False
        if header:
            team=self.first_team(club)
            if team and self.ptr(team+0x30):
                definition=self.ptr(team+0x50)
                if definition:
                    self.entity(definition,('competition',));use_rows=self.retained_mode(definition)
        if use_rows:
            start,count=self.bounds2(header,8)
            for offset in range(count):
                row=self.ptr(start+offset*8)
                if not row:raise transfer.SourceUnavailable('Null visited native club-score retained row')
                if self.ptr(row)==projection:return signed(self.u8(row+0x24)),low,high
        elif home==nation:return 100,low,high
        service=self.ptr(self.base+0x56d2ce8);world.typed(self.read,self.base,service,'game_club')
        self.route(self.ptr(service),0xf0,0x1fa64d8)
        return self.game_score(club,projection,person,low,high)


def observe(read,base,club,club_identity,nation,nation_identity,person,person_identity,*,check_current):
    transfer._identity(club_identity)
    if nation:transfer._identity(nation_identity)
    elif nation_identity is not None:raise ValueError('Null score nation must have null identity')
    if person:transfer._identity(person_identity)
    elif person_identity is not None:raise ValueError('Null score subject must have null identity')
    if not callable(check_current):raise ValueError('A checked score lifetime callback is required')
    before=deepcopy(check_current())
    if type(before) is not tuple or not before:raise ValueError('A checked score lifetime identity is required')
    read=world.ReadSet(read);verify_native(read,base);reader=Reader(read,base)
    if reader.club(club)!=club_identity:raise ValueError('Score CLUB identity changed')
    if nation and reader.entity(nation,('nation',))[1]!=nation_identity:raise ValueError('Score NATION identity changed')
    if person and reader.person(person)[3]!=person_identity:raise ValueError('Score PERSON identity changed')
    value,low,high=reader.score(club,nation,person)
    read.verify()
    if check_current()!=before:raise ValueError('Club-score lifetime changed')
    read.verify()
    return {'scope':'private_native_club_score_mode0_only','native_score':value,
            'lower_age_raw':low,'upper_age_raw':high,'complete_search_population_evaluated':False,
            'field_visibility_evaluated':False,'non_atomic':True}
