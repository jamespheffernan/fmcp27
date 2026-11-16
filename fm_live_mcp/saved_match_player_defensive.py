"""Native named defensive counts on complete MATCH_STATS60 player children."""
from . import saved_match_statistics_wire as wire

_FIELDS={
 'aerial_duels_attempted':(0xca,95,'AerialDuelsAttempted',0x4a44386c,0x205818),
 'aerial_duels_completed':(0xcb,96,'AerialDuelsCompleted',0x7a303345,0x205840),
 'interceptions':(0xcf,100,'Interceptions',0x65627130,0x205180),
 'clearances':(0xd9,153,'Clearances',0x7a434632,0x204ec8),
}

def decode_player_defensive(child):
    parsed=wire.player(child,0,version=60,stream_bit1=True)
    if parsed['end']!=len(child):raise ValueError('Player child extent mismatch')
    delta=4 if parsed['reference']['tag']<2 else 0
    return {name:child[off+delta] for name,(_,off,_,_,_) in _FIELDS.items()}


def field_registry():
    return {name:{'native_offset':hex(native),'wire_offset_u32_person':off,
                  'wire_offset_u64_person':off+4,'width':1,'encoding':'unsigned byte',
                  'frontend_literal':label,'property_key':hex(key),'native_load_rva':hex(rva),
                  'semantic_state':'official_frontend_property_to_native_player_exporter_and_wire',
                  'limits':'Stored count; aerial totals do not establish a defending-cross subset or opponent delivery difficulty; no action location or quality implied.'}
            for name,(native,off,label,key,rva) in _FIELDS.items()}
