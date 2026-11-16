"""Fields beyond the editor catalog, for snapshot columns (FM27 27.0.0.2493426).

Two kinds, both read through the PropertyVM (copied live pages, nothing written):

* `EXTRA_FIELDS[record_type][code]` — FourCC keys the record getters claim that are not
  editor catalog fields. Found by `scripts/fmdb_extras.py`: a static scan of every record
  class getter (and game-layer interceptor handler) for `movz/movk wN; cmp wK, wN` FourCC
  constants, minus every catalog code, then each key asked of sampled records. Each entry:
  `{'name', 'name_inferred', 'kind', 'sample', 'records_with_value', 'records_sampled',
  'view'}`. `name` is a best-effort label: `name_inferred` is True unless the meaning was
  established from the getter code (see PROVEN). `view == 'game'` means only the game layer
  answered (the record's own getter did not claim the key). Read like an editor field:
  `vm.get_property(record, code)`.
* `DERIVED[record_type][name]` — values no property key serves, read by calling the native
  getter slot the property code itself uses, or a hand-proven layout. Read with
  `read_derived(vm, record, name)`; returns a `PropertyResult` whose key is `x:<name>`.

Record types are `tables.RECORD_TYPES` keys ('play', 'nnpl', 'club', ...).
"""
from __future__ import annotations

from dataclasses import dataclass
import gzip
import json
from pathlib import Path
import struct
from typing import Callable

from . import tables
from .vm import CallStats, PropertyResult, Unavailable, _Stop

DATA = Path(__file__).with_name('data') / 'extras.json.gz'


# ---------------------------------------------------------------------------------------
# Derived fields: native getter slots and hand-proven layouts
# ---------------------------------------------------------------------------------------

# ACTUAL_PLAYER-family primary vtable slots (docs/research.md 0.16.0; checked per call).
PLAYER_SLOTS = {
    21: (0xD09BB0, 0xD5BEA8),     # has injuries: player +0xF0 vector non-empty (virtual: 0)
    23: (0xD2CA74, None),         # max over the injury vector of 0x154D334 = days still out
    138: (0xD3012C, None),        # condition; w1 = 0 skips the refresh, reads int16 +0x254
                                  # (virtual players compute condition per team: refused)
}
PRIMARY = {name: offset for _, (name, _, offset) in tables.CLASSES.items() if offset is not None}


@dataclass(frozen=True)
class Derived:
    kind: str
    label: str
    source: str
    read: Callable


def _primary(vm, record):
    name = tables.class_of(vm.read, vm.base, record)[0]
    if name not in PRIMARY:
        raise _Stop('record class has no proven primary offset', name)
    return name, record - PRIMARY[name]


def _slot_call(vm, record, slot, args=()):
    name, primary = _primary(vm, record)
    if name not in tables.PLAYERS:
        raise _Stop('not a player record', name)
    target = vm.read_u64(vm.read_u64(primary) + slot * 8) - vm.base
    regular, virtual = PLAYER_SLOTS[slot]
    if name == 'VIRTUAL_PLAYER' and virtual is None:
        raise _Stop('virtual players have no stored value for this slot', str(slot))
    if target not in (regular, virtual):
        raise _Stop('player getter slot changed', f'{slot}: {target:#x}')
    value, _ = vm.call(vm.base + target, (primary, *args))
    return value


def _condition_stored(vm, record):
    return 'int', struct.unpack('<h', struct.pack('<H', _slot_call(vm, record, 138, (0,)) & 0xFFFF))[0]


def _injury_days(vm, record):
    name, _ = _primary(vm, record)
    if name == 'VIRTUAL_PLAYER':
        return 'int', 0
    return 'int', struct.unpack('<h', struct.pack('<H', _slot_call(vm, record, 23) & 0xFFFF))[0]


def _has_injury(vm, record):
    return 'bool', bool(_slot_call(vm, record, 21) & 1)


def _injuries(vm, record):
    """Every entry of the native injury vector (player +0xF0), decoded as player_health does."""
    from .. import database, player_health, world
    name, primary = _primary(vm, record)
    if name == 'VIRTUAL_PLAYER':
        return 'list', []
    _slot_call(vm, record, 21)                    # checks the slot still points at 0xD09BB0
    read = vm.read
    header = struct.unpack('<Q', read(primary + 0xF0, 8))[0]
    addresses = world.vector(read, header, 128) if header else ()
    info = database.table(read, vm.base, 'injuries') if addresses else None
    return 'list', [player_health.injury(read, vm.base, a, info) for a in addresses]


def _pitch_type_stored(vm, record):
    # STADIUM getter 0x16C8BC8, case 'Spty' (0x16C97B8 -> 0x16C9EF4): ldrb +0xAD, then
    # `csinc w20, w8, wzr, hi` returns 1 (Grass) for a stored 0 (not specified) or 1.
    if tables.class_of(vm.read, vm.base, record)[0] != 'STADIUM':
        raise _Stop('not a stadium record')
    return 'int', vm.read(record + 0xAD, 1)[0]


def _currency_name_stored(vm, record):
    # currencies.py: stored native string at +0x18; the Cnam getter returns the translated name.
    from .. import world
    if tables.class_of(vm.read, vm.base, record)[0] != 'CURRENCY_RECORD':
        raise _Stop('not a currency record')
    pointer = vm.read_u64(record + 0x18)
    return 'string', world.string(vm.read, pointer) if pointer else None


def _transfer_window(key):
    # editor2 lane: the EDITOR getter 0x6710F0 on the nation's men's national team container (editor_live.py)
    def read(vm, record):
        from .editor_live import nation_transfer_window
        return nation_transfer_window(vm, record, key)
    return read


_WINDOW_LABELS = {'cwsd': 'Current transfer window start date', 'cwed': 'Current transfer window end date',
                  'nwsd': 'Next transfer window start date', 'nwed': 'Next transfer window end date'}


DERIVED = {
    'nati': {f'transfer_window_{k}': Derived('date', label, f'EDITOR getter 0x6710F0 key {k} on the nation\'s '
                                                            f'men\'s national team container (editor_live.py)',
                                             _transfer_window(k))
             for k, label in _WINDOW_LABELS.items()},
    'play': {
        'condition_stored': Derived('int', 'Condition (stored, 0-10000)',
                                    'primary slot 138 (0xD3012C) with refresh flag 0: int16 +0x254. Pcon returns -1 '
                                    'instead while slots 21/23 report an injury with days still out.',
                                    _condition_stored),
        'injury_days_remaining': Derived('int', 'Days out with current injuries (max over injuries)',
                                         'primary slot 23 (0xD2CA74): max of 0x154D334 over the injury vector; '
                                         'the Pcon getter returns -1 when this is > 0', _injury_days),
        'has_injury_record': Derived('bool', 'Has at least one current injury record',
                                     'primary slot 21 (0xD09BB0): player +0xF0 vector non-empty', _has_injury),
        'injuries': Derived('list', 'Current injuries (name, sentence name, start date)',
                            'player +0xF0 injury vector and typed INJURY definitions (player_health.injury); '
                            'Pijl/Phij are the editor starting-injury list instead', _injuries),
    },
    'stad': {
        'pitch_type_stored': Derived('int', 'Pitch type as stored (0 = not specified)',
                                     'STADIUM byte +0xAD; Spty returns 1 (Grass) for a stored 0', _pitch_type_stored),
    },
    'curr': {
        'name_stored': Derived('string', 'Currency name as stored (untranslated)',
                               'native string at +0x18 (currencies.py); Cnam/dbnm return the translated name',
                               _currency_name_stored),
    },
}


def read_derived(vm, record: int, name: str, rtype: str | None = None) -> PropertyResult:
    """Read one DERIVED field; failures come back as Unavailable, as from get_property."""
    found = [fields[name] for t, fields in DERIVED.items() if name in fields and rtype in (None, t)]
    key = f'x:{name}'
    if not found:
        return PropertyResult(key, Unavailable('unknown derived field', detail=name), None, None, CallStats())
    try:
        vm._restore()
        vm.last_stats = None
        kind, value = found[0].read(vm, record)
    except _Stop as stop:
        return PropertyResult(key, Unavailable(stop.reason, detail=stop.detail), None, None,
                              getattr(vm, 'last_stats', None) or CallStats())
    except (ValueError, struct.error, UnicodeError) as exc:
        return PropertyResult(key, Unavailable('derived field decode error', detail=str(exc)), None, None,
                              CallStats())
    return PropertyResult(key, value, kind, True, getattr(vm, 'last_stats', None) or CallStats(), view='derived')


# ---------------------------------------------------------------------------------------
# Getter-claimed extra keys (census)
# ---------------------------------------------------------------------------------------

# Meanings established from the getter code (not inferred).
# Pcjo: PERSON tree case -> PERSON slot 130 -> main contract (+0x78) slot 11 -> 0xD8C3C8
# `ldrb w0, [x0, #0x26]` (0x1494B3C); the editor PCJO is a different field (+0x24, 0 in play).
PROVEN = {
    ('*', 'Pcjo'): 'Contract job (native job code, main contract +0x26)',
    ('*', 'injr'): 'Current injury info record (injury index, start date iida, ...)',
}

# Best-effort labels, inferred from FourCC spelling, value shape and sampled values (not from
# the getter code). ('*', code) applies to every record type.
LABELS = {
    ('*', 'Pmor'): 'Morale', ('*', 'Pfrm'): 'Form (recent average rating)',
    ('*', 'Prat'): 'Season average rating (value, matches)', ('*', 'Ptrt'): 'Training rating',
    ('*', 'Poap'): 'Appearances (starts Posa, as substitute Posu)', ('*', 'Posa'): 'Starts',
    ('*', 'Posu'): 'Substitute appearances', ('*', 'Pgls'): 'Goals (value, matches)',
    ('*', 'POgl'): 'Goals (value, matches)', ('*', 'Poas'): 'Assists (value, matches)',
    ('*', 'POmi'): 'Minutes played (value, matches)', ('*', 'PoxG'): 'Expected goals (value, matches)',
    ('*', 'PxGO'): 'Expected goals (value, matches)', ('*', 'PoxA'): 'Expected assists (value, matches)',
    ('*', 'POpa'): 'Passes attempted (value, matches)', ('*', 'POpC'): 'Passes completed (value, matches)',
    ('*', 'POpc'): 'Pass completion percent (value, matches)', ('*', 'POkp'): 'Key passes (value, matches)',
    ('*', 'POcc'): 'Chances created (value, matches)', ('*', 'POsa'): 'Shots (value, matches)',
    ('*', 'POst'): 'Shots on target (value, matches)', ('*', 'POtc'): 'Tackles won (value, matches)',
    ('*', 'POta'): 'Tackles attempted (value, matches)', ('*', 'POhr'): 'Header win percent (value, matches)',
    ('*', 'POdr'): 'Distance covered (value, matches)', ('*', 'Poyc'): 'Yellow cards (value, matches)',
    ('*', 'Porc'): 'Red cards (value, matches)', ('*', 'Pofm'): 'Fouls committed (value, matches)',
    ('*', 'Pofa'): 'Fouls against (value, matches)', ('*', 'Pcww'): 'Contract weekly wage',
    ('*', 'PcwR'): 'Contract wage range (min, max)', ('*', 'PcSd'): 'Contract start date',
    ('*', 'Pced'): 'Contract end date', ('*', 'Pagn'): 'Agent', ('*', 'PNat'): 'Nationality',
    ('*', 'PNal'): 'Nationalities', ('*', 'Plcl'): 'Loan club', ('*', 'Pclb'): 'Club',
    ('*', 'Pctt'): 'Current team', ('*', 'InRs'): 'Injury risk', ('*', 'PPra'): 'Position ratings',
    ('*', 'Ppsa'): 'Position familiarity', ('*', 'Lang'): 'Languages spoken', ('*', 'Pnam'): 'Name parts',
    ('*', 'dbnD'): 'Database display name', ('*', 'sibs'): 'Related people', ('*', 'iida'): 'Injury start date',
    ('*', 'Cnkn'): 'Nickname', ('*', 'CSnm'): 'Stadium name', ('*', 'TCsn'): 'Short name',
    ('*', 'TCln'): 'Long name', ('*', 'Cprp'): 'Reputation', ('*', 'TCrp'): 'Reputation',
    ('*', 'DELE'): 'Deleted flag', ('*', 'dref'): 'Own database reference',
    ('*', 'hier'): 'Record hierarchy (parents)', ('*', 'Accl'): 'Colours',
    ('*', 'PRCF'): 'Condition and match sharpness (Pcon, Pfit)', ('*', 'Pfot'): 'Feet (left, right)',
    ('*', 'Ppss'): 'Positions (short text)', ('*', 'Poav'): 'Season average rating (value, matches)',
    ('*', 'Pogl'): 'Goals (value, matches)', ('*', 'Popk'): 'Key passes (value, matches)',
    ('*', 'naml'): 'Human manager account name', ('*', 'Pjls'): 'Job preferences (job, value)',
}


def _shape_label(info):
    sample = info['sample']
    if "'valu'" in sample and "'numb'" in sample:
        return 'Statistic (value, matches)'
    if "'minv'" in sample and "'maxv'" in sample:
        return 'Range (min, max)'
    if sample.startswith(("{'dref'", 'RecordRef(')):
        return 'Record reference'
    if "'a': 255" in sample or info['kind'] in ('colour', 'color'):
        return 'Colour'
    return f"Unlabelled {info['kind']}"


def _load():
    if not DATA.exists():
        return {}, {}
    with gzip.open(DATA, 'rt') as handle:
        data = json.load(handle)
    out = {}
    for rtype, row in data['types'].items():
        fields = {}
        for code, info in sorted(row['fields'].items()):
            proven = PROVEN.get((rtype, code)) or PROVEN.get(('*', code))
            label = proven or LABELS.get((rtype, code)) or LABELS.get(('*', code)) or _shape_label(info)
            fields[code] = {'name': label, 'name_inferred': proven is None,
                            'kind': info['kind'], 'sample': info['sample'], 'view': info['view'],
                            'records_with_value': info['records_with_value'],
                            'records_sampled': info['records_sampled']}
        out[rtype] = fields
    counts = {rtype: {'candidates': row['candidates'], 'claimed': row['claimed'], 'with_value': row['with_value'],
                      'classes': row['classes'], 'records': row['records']}
              for rtype, row in data['types'].items()}
    return out, {'meta': data['meta'], 'types': counts}


EXTRA_FIELDS, CENSUS = _load()
