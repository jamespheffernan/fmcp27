"""Typed resident historical/starting table instances, not decoded career histories."""
from collections import Counter
import struct

from . import players, world

# Exact build-pinned globals and RTTI; duplicate native types remain separate instances.
TABLES = (
    (0x56d3280, 0x55a1ee0, b'N2db14DATABASE_TABLEINS_19COMP_HISTORY_RECORDEEE'),
    (0x56d3288, 0x55a1f58, b'N2db14DATABASE_TABLEINS_15PLAYING_HISTORYEEE'),
    (0x56d3290, 0x55a1fd0, b'N2db14DATABASE_TABLEINS_19NON_PLAYING_HISTORYEEE'),
    (0x56d3298, 0x55a2048, b'N2db14DATABASE_TABLEINS_22STARTING_AWARD_HISTORYEEE'),
    (0x56d32a0, 0x55a2660, b'N2db14DATABASE_TABLEINS_13STARTING_LOANEEE'),
    (0x56d32a8, 0x55a2480, b'N2db14DATABASE_TABLEINS_15STARTING_INJURYEEE'),
    (0x56d32b0, 0x55a2318, b'N2db14DATABASE_TABLEINS_19STARTING_CONFIDENCEEEE'),
    (0x56d32b8, 0x55a2408, b'N2db14DATABASE_TABLEINS_24STARTING_FUTURE_TRANSFEREEE'),
    (0x56d32c0, 0x55a21b0, b'N2db14DATABASE_TABLEINS_18STARTING_CLUB_DEBTEEE'),
    (0x56d32c8, 0x55a29a8, b'N2db14DATABASE_TABLEINS_25STARTING_NEWGEN_PARAMETEREEE'),
    (0x56d32d0, 0x55a29a8, b'N2db14DATABASE_TABLEINS_25STARTING_NEWGEN_PARAMETEREEE'),
    (0x56d32d8, 0x55a29a8, b'N2db14DATABASE_TABLEINS_25STARTING_NEWGEN_PARAMETEREEE'),
    (0x56d32e0, 0x55a29a8, b'N2db14DATABASE_TABLEINS_25STARTING_NEWGEN_PARAMETEREEE'),
    (0x56d32e8, 0x55a2228, b'N2db14DATABASE_TABLEINS_30STARTING_CLUB_STAFF_JOB_STATUSEEE'),
    (0x56d32f0, 0x55a22a0, b'N2db14DATABASE_TABLEINS_33STARTING_CLUB_TRANSFER_PREFERENCEEEE'),
    (0x56d32f8, 0x55a26d8, b'N2db14DATABASE_TABLEINS_27STARTING_MANAGER_HOF_RECORDEEE'),
    (0x56d3300, 0x55a2d68, b'N2db14DATABASE_TABLEINS_25STARTING_TEAM_CUP_HISTORYEEE'),
    (0x56d3308, 0x55a2de0, b'N2db14DATABASE_TABLEINS_28STARTING_TEAM_LEAGUE_HISTORYEEE'),
    (0x56d3310, 0x55a2138, b'N2db14DATABASE_TABLEINS_12STARTING_BANEEE'),
    (0x56d3318, 0x55a20c0, b'N2db14DATABASE_TABLEINS_23STARTING_AVERAGE_POINTSEEE'),
    (0x56d3320, 0x55a2cf0, b'N2db14DATABASE_TABLEINS_19STARTING_RETIREMENTEEE'),
    (0x56d3328, 0x55a2930, b'N2db14DATABASE_TABLEINS_28STARTING_MONTHLY_INSTALLMENTEEE'),
    (0x56d3330, 0x55a2ed0, b'N2db14DATABASE_TABLEINS_33STARTING_WEEKLY_WAGE_CONTRIBUTIONEEE'),
    (0x56d3338, 0x55a2c00, b'N2db14DATABASE_TABLEINS_15STARTING_RECORDEEE'),
    (0x56d3340, 0x55a2c00, b'N2db14DATABASE_TABLEINS_15STARTING_RECORDEEE'),
    (0x56d3348, 0x55a2c78, b'N2db14DATABASE_TABLEINS_21STARTING_RESERVE_TEAMEEE'),
    (0x56d3350, 0x55a2a20, b'N2db14DATABASE_TABLEINS_19STARTING_PAST_TRADEEEE'),
    (0x56d3358, 0x55a2a98, b'N2db14DATABASE_TABLEINS_22STARTING_PAST_TRANSFEREEE'),
    (0x56d3360, 0x55a2b10, b'N2db14DATABASE_TABLEINS_23STARTING_PERSON_HISTORYEEE'),
    (0x56d3368, 0x55a2390, b'N2db14DATABASE_TABLEINS_23STARTING_DRAFT_TRANSFEREEE'),
    (0x56d3370, 0x55a28b8, b'N2db14DATABASE_TABLEINS_24STARTING_MLS_TRADED_SLOTEEE'),
    (0x56d3378, 0x55a27c8, b'N2db14DATABASE_TABLEINS_37STARTING_MLS_GENERAL_ALLOCATION_MONEYEEE'),
    (0x56d3380, 0x55a2840, b'N2db14DATABASE_TABLEINS_38STARTING_MLS_TARGETED_ALLOCATION_MONEYEEE'),
    (0x56d3388, 0x55a2b88, b'N2db14DATABASE_TABLEINS_25STARTING_PLAYER_HAPPINESSEEE'),
    (0x56d3390, 0x55a2750, b'N2db14DATABASE_TABLEINS_27STARTING_MEDIA_EXPECTATIONSEEE'),
    (0x56d3398, 0x55a2570, b'N2db14DATABASE_TABLEINS_55STARTING_ITALIAN_SERIE_A_CLUB_THAT_FREED_UP_NON_EU_SLOTEEE'),
    (0x56d33a0, 0x55a24f8, b'N2db14DATABASE_TABLEINS_49STARTING_ITALIAN_SERIE_A_CLUB_NON_EU_SLOTS_NUMBEREEE'),
    (0x56d33a8, 0x55a25e8, b'N2db14DATABASE_TABLEINS_65STARTING_ITALIAN_SERIE_A_NON_EU_PLAYER_SIGNED_FOR_RESTRICTED_SLOTEEE'),
    (0x56d33b0, 0x55a2e58, b'N2db14DATABASE_TABLEINS_25STARTING_VISION_OBJECTIVEEEE'),
)

def inspect(read, base):
    """Read all bounded table headers; null vectors mean resident empty instances."""
    rows = []
    type_counts = Counter(name for _, _, name in TABLES)
    seen_types = Counter()
    objects = {}
    for root_rva, table_rva, name in TABLES:
        root = world.pointer(read, base + root_rva)
        vtable = base + table_rva
        if world.pointer(read, root) != vtable:
            raise ValueError('Unexpected auxiliary database table type')
        displacement, info = struct.unpack('<qQ', read(vtable - 16, 16))
        if displacement != 0:
            raise ValueError('Unexpected auxiliary database table displacement')
        text = players.u64(read(info + 8, 8))
        if text < 4096 or read(text, len(name) + 1) != name + b'\0':
            raise ValueError('Unexpected auxiliary database table RTTI')
        header = world.pointer(read, root + 0x88)
        start, end, capacity = struct.unpack('<QQQ', read(header, 24))
        if (start, end, capacity) != (0, 0, 0):
            if (start < 4096 or any(p % 8 for p in (start, end, capacity))
                    or not start <= end <= capacity or capacity - start > 2000000 * 8):
                raise ValueError('Invalid auxiliary database table bounds')
        count = (end - start) // 8
        seen_types[name] += 1
        identifier = name.decode().split('INS_', 1)[1]
        identifier = identifier.lstrip('0123456789')[:-3]
        row = {'source_index': len(rows), 'native_table_type': name.decode(), 'record_type': identifier,
               'source_classification': 'starting_record_table' if identifier.startswith('STARTING_')
                                        else 'history_record_table',
               'instance_ordinal': seen_types[name], 'same_type_instance_count': type_counts[name],
               'record_slot_count': count, 'state': 'resident_empty' if count == 0 else 'resident_with_slots',
               'same_object_alias_of': objects.get(root), 'record_fields_decoded': False}
        rows.append(row)
        objects.setdefault(root, len(rows) - 1)
    return {'tables': rows, 'resident_global_instance_count': len(rows),
            'distinct_resident_object_count': len(objects), 'distinct_native_table_type_count': len(type_counts),
            'empty_instance_count': sum(row['record_slot_count'] == 0 for row in rows),
            'scope': 'Exact typed resident history/starting table headers. Empty does not mean no career history; other current managers, nested vectors and archives are separate. Duplicate native types remain distinct global instances; same-object aliases are explicit. Static-only types are excluded.'}
