"""Mapping between the knowledge engine's 47 attribute fields and editor FourCC codes.

The bulk knowledge engine (`knowledge_bulk`) names its fields by the native compiled names in
`knowledge_field_catalog.FIELDS` (stored byte at primary+0x148+offset). The editor catalog
(`editor.fmf`, record type `play`) exposes the same attributes twice:

* a 1..20 family (`Paab`, `Ppas`, ...), the value the game shows; and
* a 1..100 family in the "Player Attributes" category (`PDae`, `PDps`, ...), which the UI never
  shows as a number.

`FIELDS` below was established on the live save (Newcastle United, 10 December 2030) by
`verify_field_codes`: for every own-club player (where every cell is exact), the PropertyVM
getter value of each of the 106 `attribute`-typed `play` codes was compared with the bulk
engine's exact value. Each field matched exactly one 1..20 code on all 29 players, and exactly
one 1..100 code under round(x / 5). Five 1..20 codes have no knowledge field (hidden
attributes): `PCON` Consistency, `Pdir` Dirtiness, `Pimp` Important Matches, `Pipr` Injury
Proneness, `Pver` Versatility; their 1..100 twins and the foot ratings `PDlf`/`PDri` likewise.

Reading attribute values through the VM is done here only for own-club players, whose
attributes the manager sees exactly; nothing else in this module reads game memory.
"""
from __future__ import annotations

import re
import struct
from pathlib import Path

from .. import knowledge_field_catalog as kfc


def column_name(field_name: str) -> str:
    """snake_case column for a knowledge field name ("Rushing Out (Tendency)" -> rushing_out_tendency)."""
    return re.sub(r'[^a-z0-9]+', '_', field_name.lower()).strip('_')


# (knowledge field name, 1..20 editor code, 1..100 editor code), in native field-id order.
_PAIRS = (
    ('Aerial Reach', 'Paab', 'PDae'), ('Command Of Area', 'Pcoa', 'PDca'),
    ('Communication', 'Pcom', 'PDcm'), ('Eccentricity', 'Pecc', 'PDec'),
    ('Handling', 'Phan', 'PDhn'), ('Kicking', 'Pkic', 'PDkc'), ('Reflexes', 'Pref', 'PDrf'),
    ('Rushing Out (Tendency)', 'Prou', 'PDro'), ('Punching (Tendency)', 'Pttp', 'PDtp'),
    ('Throwing', 'Pthr', 'PDth'), ('One On Ones', 'Pooo', 'PDoo'), ('Crossing', 'Pcro', 'PDcr'),
    ('Dribbling', 'Pdri', 'PDdr'), ('Finishing', 'Pfin', 'PDfn'), ('Heading', 'Phea', 'PDhd'),
    ('Long Shots', 'Plsh', 'PDls'), ('Long Throws', 'Plth', 'PDlt'), ('Marking', 'Pmar', 'PDmr'),
    ('Passing', 'Ppas', 'PDps'), ('Penalty Taking', 'Ppen', 'PDpn'),
    ('Free Kick Taking', 'Pfrk', 'PDfk'), ('Tackling', 'Ptac', 'PDtk'),
    ('Technique', 'Ptec', 'PDtc'), ('First Touch', 'Pfrs', 'PDft'), ('Corners', 'Pcor', 'PDcs'),
    ('Aggression', 'Pagg', 'PDag'), ('Anticipation', 'Pant', 'PDan'), ('Bravery', 'Pbra', 'PDbr'),
    ('Vision', 'Pcre', 'PDvs'), ('Decisions', 'Pdec', 'PDdc'), ('Determination', 'Pdet', 'PDde'),
    ('Flair', 'Pfla', 'PDfl'), ('Leadership', 'Pinf', 'PDld'), ('Off The Ball', 'Potb', 'PDmv'),
    ('Positioning', 'Ppsn', 'PDpt'), ('Teamwork', 'Ptwr', 'PDtm'), ('Work Rate', 'Pwkr', 'PDwr'),
    ('Composure', 'Pcmp', 'PDcp'), ('Concentration', 'Pcnt', 'PDcc'),
    ('Acceleration', 'Pacc', 'PDac'), ('Agility', 'Pagi', 'PDal'), ('Balance', 'Pbal', 'PDbl'),
    ('Pace', 'Ppac', 'PDpc'), ('Stamina', 'Psta', 'PDsm'), ('Strength', 'Pstr', 'PDst'),
    ('Jumping Reach', 'Pjum', 'PDjm'), ('Natural Fitness', 'Pnft', 'PDnf'),
)
assert tuple(p[0] for p in _PAIRS) == tuple(f[0] for f in kfc.FIELDS), 'field order differs from the engine'

FIELDS = tuple(dict(field_id=i, name=name, column=column_name(name), code=code, code_100=code_100)
               for i, (name, code, code_100) in enumerate(_PAIRS))
BY_NAME = {f['name']: f for f in FIELDS}
BY_CODE = {f['code']: f for f in FIELDS}
COLUMNS = tuple(f['column'] for f in FIELDS)
VISIBLE_CODES = frozenset(f['code'] for f in FIELDS)
SCALED_CODES = frozenset(f['code_100'] for f in FIELDS)
# Attribute-typed `play` codes with no knowledge field: hidden attributes and their 1..100 twins,
# plus the 1..100 foot ratings.
HIDDEN_ATTRIBUTE_CODES = frozenset({'PCON', 'Pdir', 'Pimp', 'Pipr', 'Pver',
                                    'PDcy', 'PDdt', 'PDim', 'PDij', 'PDvt', 'PDlf', 'PDri'})


def _blob_value(value):
    """VM value of a 1..20 attribute: a 4-byte DATA blob whose byte 1 is the stored value."""
    if isinstance(value, (bytes, bytearray)) and len(value) == 4:
        return value[1]
    if type(value) is int:
        return value
    return None


def verify_field_codes(bridge_or_session, *, catalog=None) -> dict:
    """Live check of `FIELDS` on the managed club's players (every cell exact there).

    For each of the 47 knowledge fields, compares the bulk engine's exact values with the
    PropertyVM getter value of every `attribute`-typed `play` code, on all own-club players.
    Returns per field the matching 1..20 codes, the 1..100 codes matching under round(x/5) and
    whether the result equals `FIELDS`. Reads attribute values only of own-club players.
    """
    from .. import bridge as bridge_module, knowledge_bulk as kb, players
    from . import tables
    from .catalog import load_catalog_for_plugin
    from .image import PluginImage
    from .live import StreamReader
    from .vm import PropertyVM, Unavailable

    bridge, sid = kb._bridge_and_session(bridge_or_session)
    with bridge.lock, bridge._read_scope(sid):
        layout = bridge._player_layout(bridge._current(sid))
    base = layout[0] - players.RVA[0]
    plugin = Path(bridge.plugin_identity[0][0])
    reader = StreamReader(bridge.helper, bridge.process.pid)
    try:
        _, persons = tables.managed(reader.read, base)
        indices = [struct.unpack('<I', reader.read(p + 8, 4))[0] for p in persons]
        cells = kb.visible_attributes_bulk((bridge, sid), indices)
        exact = {}
        for row in cells['players']:
            if any(c['state'] != 'exact' for c in row['fields']):
                raise ValueError(f'Own-club player {row["key"]} has a non-exact cell; cannot verify codes')
            exact[row['key']] = [c['value'] for c in row['fields']]
        cat = catalog or load_catalog_for_plugin(plugin)
        codes = [f.code for f in cat.record_types['play'].field_list if f.type == 'attribute']
        vm = PropertyVM(reader, base, PluginImage.load(plugin))
        vm_values = {}
        for person, index in zip(persons, indices):
            row = {}
            for code in codes:
                value = vm.get_property(person, code).value
                row[code] = None if isinstance(value, Unavailable) else value
            vm_values[index] = row
    finally:
        reader.close()
    result = []
    for f in FIELDS:
        want = [exact[i][f['field_id']] for i in indices]
        direct = [c for c in codes if [_blob_value(vm_values[i][c]) for i in indices] == want]
        scaled = [c for c in codes
                  if all(type(vm_values[i][c]) is int and int(vm_values[i][c] / 5 + 0.5) == w
                         for i, w in zip(indices, want))]
        result.append(dict(field=f['name'], code_matches=direct, code_100_matches=scaled,
                           paired=direct == [f['code']] and scaled == [f['code_100']]))
    unmatched = sorted(set(c for c in codes if not c.startswith('PD')) - VISIBLE_CODES)
    return dict(game_date=cells['save']['current_date'], players=len(indices), codes_tested=len(codes),
                fields=result, paired=sum(r['paired'] for r in result), unpaired=[r['field'] for r in result
                                                                                   if not r['paired']],
                codes_without_field=unmatched)
