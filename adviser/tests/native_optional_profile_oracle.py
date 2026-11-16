"""Read-only current-role optional PI oracle for the separately owned loader VM.

Original4976140(record) is a pure normalized-key getter.
Original4976030(record,0) returns the current PI value pointer but INSERTS an
empty value if absent. Original4ADEC28(record,option,0) calls it and selects one
raw optional bit, without availability gating. Use this independent walker to
avoid allocation while preserving exactly that present/absent semantics.
"""
import struct
KEY_MASK=0xFFFBFFFFF91FFFFF
OPTION_MASK=(1<<43)-1
KEY_GETTER_ENTRY=0x4976140
CREATOR=0x100400000
PHASE_OFFSETS={'in_possession':0x120,'out_of_possession':0x440}

def current_optional_profile(read,phase,slot,*,native_key_getter=None):
    """read(at,n)->bytes; optional native_key_getter(entry,args)->X0."""
    if type(phase)is not str or phase not in PHASE_OFFSETS:raise ValueError('Unknown phase')
    if type(slot)is not int or not 0<=slot<11:raise ValueError('Unknown slot')
    record=CREATOR+PHASE_OFFSETS[phase]+72*slot
    def exact(at,n):
        raw=read(at,n)
        if type(raw)is not bytes or len(raw)!=n:raise ValueError('Incomplete owned VM operand')
        return raw
    role=struct.unpack('<Q',exact(record+64,8))[0];key=role&KEY_MASK
    if native_key_getter is not None:
        if native_key_getter(KEY_GETTER_ENTRY,[record])!=key:raise ValueError('Original normalized-key getter mismatch')
    first,last,capacity=struct.unpack('<3Q',exact(record+8,24))
    if (first,last,capacity)!=(0,0,0):
        if not 4096<=first<=last<=capacity<1<<64 or(first|last|capacity)&7 or(last-first)%24 or(capacity-first)%24 or capacity-first>512*24:raise ValueError('Unsupported primary PI vector')
    rows=exact(first,last-first)if last>first else b''
    keys=[struct.unpack_from('<Q',rows,i)[0]for i in range(0,len(rows),24)]
    if any(a>=b for a,b in zip(keys,keys[1:])):raise ValueError('PI keys must be sorted and unique')
    matches=[i for i,k in enumerate(keys)if k==key]
    if not matches:return dict(phase=phase,slot=slot,role_word=role,normalized_role_key=key,stored_profile_present=False,stored_low43=0,selected_optional_ids=[],inactive_profile_count=len(keys),raw_value_hex=None)
    i=matches[0];value=rows[24*i+8:24*i+24];bits=struct.unpack_from('<Q',value)[0];low=bits&OPTION_MASK
    return dict(phase=phase,slot=slot,role_word=role,normalized_role_key=key,stored_profile_present=True,stored_low43=low,selected_optional_ids=[i for i in range(43)if low&(1<<i)],inactive_profile_count=len(keys)-1,raw_value_hex=value.hex())
