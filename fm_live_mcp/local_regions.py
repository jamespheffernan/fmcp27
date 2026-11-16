"""Stored LOCAL_REGION fields and complete bounded language vectors."""
import struct

from . import geography,players

SCOPE = ('Stored local-region name, nation, weather link, population integer and language entries. '
         'Population freshness is unverified; zero remains a stored value. Weather is a database link, not current conditions. '
         'Language percentages remain separate stored values and may total above 100; they are not normalized. '
         'Null languages, duplicate entries and out-of-range percentages are retained. '
         'Language vectors are complete or the read rejects; at most 1000 allocated entries are accepted. '
         'Use fm_find_cities(local_region_native_id=...) and follow every cursor for the native reverse city relationship. '
         'Local-region deletion and further fields remain unverified. References bind identity and membership; '
         'ordinary links and fields refresh. Reads are non-atomic with consumed-byte rechecks.')


def record(read, base, address, *, include_details=False):
    binding = geography.identity(read,base,address,'local_region')
    row = {**geography.record(read,base,address,'local_region'),'kind':'local_region'}
    bindings = []
    if include_details:
        for kind,offset in (('nation',0x48),('weather',0x50)):
            pointer = players.u64(read(address+offset,8))
            row[kind] = geography.record(read,base,pointer,kind) if pointer else None
        row['population'] = int.from_bytes(read(address+0x58,4),'little',signed=True)
        start,end,capacity = struct.unpack('<QQQ',read(address+0x30,24))
        if start or end or capacity:
            if (start<4096 or not start<=end<=capacity or any(p%8 for p in (start,end,capacity))
                    or (end-start)%16 or (capacity-start)%16 or capacity-start>16000):
                raise ValueError('Invalid or oversized local-region language vector')
        entries = []
        for index,offset in enumerate(range(start,end,16)):
            raw = read(offset,16)
            pointer = players.u64(raw)
            language = geography.record(read,base,pointer,'language') if pointer else None
            bindings.append(geography.identity(read,base,pointer,'language') if pointer else None)
            percentage = int.from_bytes(raw[8:9],'little',signed=True)
            entries.append({'native_index':index,'language':{**language,'kind':'language'} if language else None,
                            'percentage_native':percentage,'percentage_state':'stored' if 0<=percentage<=100 else 'out_of_range'})
        row.update(languages=entries,language_count=len(entries),complete_native_language_vector=True)
    return row,binding,bindings
