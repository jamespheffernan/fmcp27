"""Bounded v6 retained match storage, preserving physical ranges."""
import hashlib
import struct

MAX_CONTAINERS = 2048
MAX_INDICES = 65536
MAX_NAME = 8192


class GeometryError(ValueError):
    pass


class BudgetError(ValueError):
    pass


def parse(reader, *, manager28_present):
    if type(manager28_present) is not bool:
        raise ValueError('Profile must explicitly identify manager28 presence')
    raw_size = reader.size
    def left(): return raw_size-reader.offset
    def require(n):
        if n < 0 or n > left():
            raise GeometryError(f'Extent {n} exceeds remaining {left()} at {reader.offset}')
    def take(n):
        require(n);return reader.take(n)
    def number(code):return struct.unpack('<'+code,take(struct.calcsize('<'+code)))[0]
    header=take(8)
    if header!=bytes.fromhex('03017461642e0600'):
        raise ValueError('Unsupported component header/endianness/version')
    manager_word=number('I');containers=[];vectors=[]
    def vector(field):
        start=reader.offset;version=number('B');count=number('I')
        if len(containers) + count > MAX_CONTAINERS:raise BudgetError('Total container budget exceeded')
        require(count*23) # Every entry has >=23B metadata even with empty text/index/payload.
        if count>MAX_CONTAINERS:raise BudgetError('Container budget exceeded')
        vectors.append({'manager_field':field,'start':start,'wire_version':version,'count':count})
        for ordinal in range(count):
            first=reader.offset;storage_index=number('I');name_size=number('I');require(name_size)
            if name_size>MAX_NAME:raise BudgetError(f'Name budget exceeded at {reader.offset}: {name_size}')
            name_raw=take(name_size)
            try:name=name_raw.decode('utf-8')
            except UnicodeError:name=None
            requested_capacity=number('I');compressed_flag=number('B');index_version=number('B');n=number('I')
            require(n*12+14)
            if n + sum(c['index_count'] for c in containers)>MAX_INDICES:raise BudgetError('Total index count budget exceeded')
            indices=[]
            for slot in range(n):
                key,offset,length=number('I'),number('I'),number('I')
                indices.append({'ordinal':slot,'key_u32':key,'key_i32':key-(1<<32) if key>=1<<31 else key,
                                'offset':offset,'length':length})
            meta=reader.offset;capacity=number('I');used=number('I');storage_mode=number('B');size=number('i')
            require(size+1)
            for row in indices:
                if row['offset']>size or row['length']>size-row['offset']:
                    raise GeometryError(f'Indexed extent exceeds payload at {first}, index {row["ordinal"]}')
            payload_start=reader.offset;sha=hashlib.sha256();remaining=size
            while remaining:
                chunk=take(min(131072,remaining));sha.update(chunk);remaining-=len(chunk)
            trailer=number('B')
            keys=[row['key_u32'] for row in indices];ranges=[(row['offset'],row['length'])for row in indices]
            containers.append({'manager_field':field,'vector_ordinal':ordinal,'container_ordinal':len(containers),
                'start':first,'end':reader.offset,'storage_index':storage_index,'name':name,'name_hex':name_raw.hex(),
                'requested_capacity_word':requested_capacity,'compressed_flag':compressed_flag,'index_version':index_version,
                'index_count':n,'indices':indices,'duplicate_key_count':len(keys)-len(set(keys)),
                'duplicate_range_count':len(ranges)-len(set(ranges)),'metadata_start':meta,
                'capacity_word':capacity,'field_c_word':used,'storage_mode':storage_mode,'payload_start':payload_start,
                'payload_size':size,'payload_sha256':sha.hexdigest(),'trailer':trailer})
    if manager28_present:vector('0x28')
    presence_at=reader.offset;presence=number('B')
    if presence==1:vector('0x20')
    if reader.offset!=raw_size:
        raise GeometryError(f'Unconsumed trailing bytes: {raw_size-reader.offset}')
    return {'state':'complete_outer_v6_profile','manager28_present':manager28_present,
            'header_hex':header.hex(),'manager_word':manager_word,'manager20_presence_offset':presence_at,
            'manager20_presence_byte':presence,'vectors':vectors,'containers':containers,'end':reader.offset,
            'complete_raw_extent_accounted':True,'native_key_meanings_resolved':False}
