"""Declarative map from the existing hand-proven tools' output fields to generic-reader properties.

The differential suite (`scripts/fmdb_oracle.py`) reads a record through an existing tool
(`Bridge` method, arguments, JSON path) and through the generic reader
(`PropertyVM.get_property(record, FourCC)`), then compares the two with a named rule.

Vocabulary
----------
* `Call`    one existing-tool invocation: the Bridge method (or `module:function` taking
            `(bridge, session_id, **kwargs)`), fixed keyword arguments, the keyword that
            receives the record handle, and which Bridge reference table the handle lives in.
* `Entry`   one compared field: family, field name, call, JSON path inside the call's result,
            the sample record family it is read from, an optional `via` reference code to hop
            to the referenced record first, the editor FourCC(s) read there, and the rule.
* `Rule`    how the two values are compared (see `RULES`). A rule receives the tool value, a
            `{code: decoded generic value}` dict, the entry parameters and a context object
            (`resolve_name`, `resolve_uid`, `enum_label`) and returns `(ok, detail)`.
* `UNMAPPED` hand-built tool fields for which no editor code could be established.
* `TOOL_GAPS` generic-reader fields that the existing tools do not expose at all.
* `FINDINGS` the written classification of every disagreement the live run showed.

Statuses recorded per (record, entry): `match`, `mismatch`, `generic_unavailable` (the VM
could not produce the value, or the getter did not claim the key), `tool_unavailable` (the
tool omitted the field or returned null while the generic reader has a value). A tool null
against a generic null counts as a match: both readers agree the value is absent.
"""
from __future__ import annotations

from dataclasses import dataclass
import struct

MISSING = object()


STATUSES = ('match', 'mismatch', 'generic_unavailable', 'tool_unavailable')
CLASSES = ('generic reader wrong', 'existing tool wrong', 'different semantics (both defensible)',
           'undetermined')


# ---------------------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------------------

@dataclass(frozen=True)
class Call:
    key: str
    method: str                 # Bridge attribute, or 'package.module:function' (bridge, session, **kw)
    kwargs: tuple = ()          # fixed keyword arguments as ((name, value), ...)
    ref_kwarg: str = ''         # keyword that receives the record handle
    ref_table: str = ''         # Bridge attribute holding that handle table
    root: str = ''              # JSON path of the record object inside the result ('' = whole result)

    def arguments(self) -> dict:
        return dict(self.kwargs)


@dataclass(frozen=True)
class Entry:
    family: str
    field: str
    call: str
    path: str                   # dotted path under the call result; `[n]` indexes lists
    rtype: str                  # editor record type the code belongs to ('play', 'club', ...)
    codes: tuple
    rule: str
    params: tuple = ()          # ((name, value), ...) rule parameters
    sample: str = ''            # sample family supplying records (default: the entry family)
    via: str = ''               # reference code on the sampled record leading to the compared record
    note: str = ''

    @property
    def sample_family(self) -> str:
        return self.sample or self.family.split('.')[0]

    @property
    def key(self) -> str:
        return f'{self.family}.{self.field}'

    def param(self, name, default=None):
        for k, v in self.params:
            if k == name:
                return v
        return default


@dataclass(frozen=True)
class Unmapped:
    family: str
    field: str
    tool: str                   # where the existing tool exposes it
    tried: str
    reason: str


@dataclass(frozen=True)
class Gap:
    family: str
    code: str
    name: str
    reason: str


def P(**kwargs) -> tuple:
    return tuple(kwargs.items())


# ---------------------------------------------------------------------------------------
# Comparison rules
# ---------------------------------------------------------------------------------------

class Context:
    """Services a rule may need; the live driver implements them against the VM."""

    def resolve_name(self, ref, kind):                    # -> str | raises LookupError
        raise LookupError('no resolver')

    def resolve_uid(self, ref):                           # -> int | raises LookupError
        raise LookupError('no resolver')

    def resolve_index_name(self, kind, index):            # -> str | raises LookupError
        raise LookupError('no resolver')

    def enum_label(self, rtype, code, value):             # -> str | None
        raise LookupError('no catalog')


def _one(gen, entry_codes=None):
    if len(gen) == 1:
        return next(iter(gen.values()))
    raise ValueError('rule needs a single code')


def _f32(x):
    return struct.pack('<f', x)


def rule_exact(tool, gen, params, ctx):
    v = _one(gen)
    if isinstance(tool, bool) or isinstance(v, bool):
        return isinstance(tool, bool) and isinstance(v, bool) and tool == v, None
    return tool == v, None


def rule_string(tool, gen, params, ctx):
    v = _one(gen)
    if v is None:
        v = ''
    return tool == v, None if tool == v else f'{tool!r} != {v!r}'


def rule_empty_as_null(tool, gen, params, ctx):
    """Tool uses null for an empty stored string; generic returns ''. Equal when both are empty."""
    v = _one(gen)
    return (tool or '') == (v or ''), None


def rule_int_tol(tool, gen, params, ctx):
    v = _one(gen)
    tol = params.get('tol', 0)
    return isinstance(v, (int, float)) and abs(tool - v) <= tol, None


def rule_float32(tool, gen, params, ctx):
    """Tool float (widened float32) against a generic float32: bit-exact or within `rel`."""
    v = _one(gen)
    if not isinstance(v, (int, float)):
        return False, None
    if _f32(float(tool)) == _f32(float(v)):
        return True, None
    rel = params.get('rel', 0.0)
    return (abs(tool - v) <= rel * max(abs(tool), abs(v), 1e-30)), None


def rule_date_iso(tool, gen, params, ctx):
    v = _one(gen)
    iso = getattr(v, 'iso', v)
    return tool == iso, None


def rule_fifths_raw(tool, gen, params, ctx):
    """Stored raw 0-100 byte shown as 1-20 in fifths: max(1, (raw + 2) // 5)."""
    v = _one(gen)
    if not isinstance(v, int) or isinstance(v, bool) or not 0 <= v <= 100:
        return False, f'raw {v!r} outside 0-100'
    return tool == max(1, (v + 2) // 5), f'raw {v}'


def rule_direct_raw(tool, gen, params, ctx):
    v = _one(gen)
    return tool == v, None


def rule_blob_byte(tool, gen, params, ctx):
    """Display attribute: 4-byte DATA blob whose byte `index` (default 1) is the displayed rating."""
    v = _one(gen)
    index = params.get('index', 1)
    if not isinstance(v, (bytes, bytearray)) or len(v) <= index:
        return False, f'blob {v!r}'
    return tool == v[index], f'blob {bytes(v).hex()}'


def rule_enum_code(tool, gen, params, ctx):
    v = _one(gen)
    return tool == v, None


def rule_enum_label(tool, gen, params, ctx):
    v = _one(gen)
    label = ctx.enum_label(params['rtype'], params['code'], v)
    if label is None:
        return False, f'no editor label for {v!r}'
    same = _norm(label) == _norm(tool)
    return same, None if same else f'editor label {label!r}'


def _norm(text):
    return ''.join(ch for ch in str(text).casefold() if ch.isalnum())


def rule_ref_name(tool, gen, params, ctx):
    v = _one(gen)
    if v is None:
        return False, 'generic reference null'
    name = ctx.resolve_name(v, params['kind'])
    same = (_norm(name) == _norm(tool)) if params.get('fold') else name == tool
    return same, None if same else f'resolved {name!r}'


def rule_index_name(tool, gen, params, ctx):
    """Generic integer that is a database index into another table; resolve it and compare names (folded)."""
    v = _one(gen)
    if not isinstance(v, int) or isinstance(v, bool):
        return False, f'not an index: {v!r}'
    name = ctx.resolve_index_name(params['kind'], v)
    same = _norm(name) == _norm(tool)
    return same, None if same else f'resolved {name!r}'


def rule_ref_uid(tool, gen, params, ctx):
    v = _one(gen)
    uid = ctx.resolve_uid(v)
    return uid == tool, None if uid == tool else f'unique id {uid!r}'


def rule_presence(tool, gen, params, ctx):
    """Tool count against presence of a generic record/list: (count > 0) == (value present)."""
    v = _one(gen)
    present = v not in (None, [], {}, b'')
    return (tool > 0) == present, f'tool count {tool}, generic {"present" if present else "absent"}'


def rule_unset(tool, gen, params, ctx):
    """Tool native code/integer where one of `unset` (default 0, -1) means 'not specified', against
    a generic integer or null: equal, or both unset."""
    v = _one(gen)
    unset = tuple(params.get('unset', (0, -1)))
    if tool == v and type(tool) is type(v):
        return True, None
    if (tool is None or tool in unset) and (v is None or v in unset):
        return True, 'both unset'
    return False, None


def rule_date_unset(tool, gen, params, ctx):
    """Tool date string (null when not specified) against a generic date; 1900-01-01 means not specified."""
    v = _one(gen)
    iso = getattr(v, 'iso', v)
    if tool is None:
        return iso in (None, '1900-01-01'), 'both unset' if iso in (None, '1900-01-01') else f'generic {iso}'
    return tool == iso, None


def _full(gen, first, second, common):
    parts = [p for p in (gen.get(first), gen.get(second)) if p]
    return ' '.join(parts) or (gen.get(common) or None)


def rule_full_name(tool, gen, params, ctx):
    full = _full(gen, 'Pfna', 'Psna', 'Pcna')
    return tool == full, None if tool == full else f'first+second {full!r}'


def rule_display_name(tool, gen, params, ctx):
    shown = gen.get('Pcna') or _full(gen, 'Pfna', 'Psna', 'Pcna')
    return tool == shown, None if tool == shown else f'common-or-full {shown!r}'


def rule_list_len(tool, gen, params, ctx):
    v = _one(gen)
    return isinstance(v, (list, tuple)) and len(v) == tool, f'len {len(v) if hasattr(v, "__len__") else v!r}'


def rule_bool(tool, gen, params, ctx):
    v = _one(gen)
    return isinstance(v, bool) and v == bool(tool), None


RULES = {
    'exact': rule_exact, 'string': rule_string, 'empty_as_null': rule_empty_as_null,
    'int_tol': rule_int_tol, 'float32': rule_float32, 'date_iso': rule_date_iso,
    'fifths_raw': rule_fifths_raw, 'direct_raw': rule_direct_raw, 'blob_byte': rule_blob_byte,
    'enum_code': rule_enum_code, 'enum_label': rule_enum_label, 'ref_name': rule_ref_name,
    'ref_uid': rule_ref_uid, 'index_name': rule_index_name, 'presence': rule_presence,
    'unset': rule_unset, 'date_unset': rule_date_unset, 'full_name': rule_full_name, 'display_name': rule_display_name,
    'list_len': rule_list_len, 'bool': rule_bool,
}

RULE_DOC = {
    'exact': 'integers/bools equal',
    'string': 'strings equal (generic null = empty)',
    'empty_as_null': 'tool null or empty equals generic empty',
    'int_tol': 'integers within `tol`',
    'float32': 'float32 bit-exact, else within `rel`',
    'date_iso': 'generic SI date ISO string equals the tool date string',
    'fifths_raw': 'stored byte 0-100 shown as max(1, (raw+2)//5)',
    'direct_raw': 'stored byte equals displayed value (direct mode)',
    'blob_byte': 'displayed attribute equals byte 1 of the 4-byte DATA blob',
    'enum_code': 'native enum integer equals the tool native_code',
    'enum_label': 'tool label equals the editor enum label for the generic integer (case/punctuation folded)',
    'ref_name': 'generic record reference resolved to the target record and its name compared',
    'ref_uid': 'generic record reference unique id equals the tool native_id',
    'full_name': 'first + second name (or common name) equals the tool full name',
    'display_name': 'common name, else full name, equals the tool display name',
    'list_len': 'generic list length equals the tool count',
    'bool': 'booleans equal',
    'index_name': 'generic integer database index resolved in another table and its name compared (folded)',
    'presence': 'tool count > 0 equals presence of the generic record/list',
    'unset': 'equal, or tool and generic both unset (tool 0/-1, generic null)',
    'date_unset': 'dates equal; tool null equals generic null or 1900-01-01 (not specified)',
}


def compare(entry: Entry, tool_value, gen: dict, ctx: Context):
    """Apply an entry's rule; returns (ok, detail)."""
    fn = RULES[entry.rule]
    params = dict(entry.params)
    key = params.get('key')
    if key:      # the code returns a record (dict); compare one of its members
        gen = {c: (v.get(key) if isinstance(v, dict) else v) for c, v in gen.items()}
    return fn(tool_value, gen, params, ctx)


def get_path(doc, path):
    """Value at a dotted path with `[n]` list indexes; MISSING when any step is absent."""
    cur = doc
    if not path:
        return cur
    for part in path.split('.'):
        name, _, rest = part.partition('[')
        if name:
            if not isinstance(cur, dict) or name not in cur:
                return MISSING
            cur = cur[name]
        while rest:
            idx, _, rest = rest.partition(']')
            rest = rest.lstrip('[')
            if not isinstance(cur, (list, tuple)):
                return MISSING
            if '=' in idx:       # [key=value]: first element whose `key` member equals `value`
                key, _, value = idx.partition('=')
                cur = next((x for x in cur if isinstance(x, dict) and str(x.get(key)) == value), MISSING)
                if cur is MISSING:
                    return MISSING
            elif idx.lstrip('-').isdigit() and -len(cur) <= int(idx) < len(cur):
                cur = cur[int(idx)]
            else:
                return MISSING
    return cur


# ---------------------------------------------------------------------------------------
# Reference targets (record reference FourCC -> table and name code)
# ---------------------------------------------------------------------------------------

# kind -> (live table, name code). The `Ttea` reference of a contract club shares its unique
# id with the CLUB record; it is resolved against the clubs table (checked by the live run).
REF_KINDS = {
    'nation': ('nations', 'Nsnm'), 'nation_abbr': ('nations', 'N3ln'),
    'city': ('cities', 'Cnam'), 'stadium': ('stadiums', 'Snam'), 'currency': ('currencies', 'Cnam'),
    'competition': ('competitions', 'cnam'), 'club': ('clubs', 'dbnm'), 'club_short': ('clubs', 'Csnm'),
    'continent': ('continents', 'Cnam'), 'language': ('languages', 'Lnam'),
    'local_region': ('local_regions', 'Lnam'), 'weather': ('weather', 'wnam'), 'injury': ('injuries', 'Inam'),
    'injury_sentence': ('injuries', 'Isnm'),
}
# Record-reference table FourCC -> kind used when a rule does not say otherwise.
REF_FOURCC_KIND = {
    'Nnat': 'nation', 'city': 'city', 'stad': 'stadium', 'curr': 'currency', 'comp': 'competition',
    'Ttea': 'club', 'cont': 'continent', 'lang': 'language', 'lcrg': 'local_region', 'wthr': 'weather',
}


# ---------------------------------------------------------------------------------------
# Calls
# ---------------------------------------------------------------------------------------

PLAYER_FLAGS = P(include_clubs=True, include_profile=True, include_health=True, include_wage=True,
                 include_contract_dates=True, include_contract_status=True, include_transfer_prices=True,
                 include_contract_terms=True)
STAFF_FLAGS = P(include_club=True, include_attributes=True, include_job=True, include_contract_dates=True,
                include_wage=True, include_contract_status=True)

CALLS = {c.key: c for c in (
    Call('player', 'get_player', PLAYER_FLAGS, 'player_ref', 'player_refs', 'player'),
    Call('staff', 'get_staff', STAFF_FLAGS, 'staff_ref', 'staff_refs', 'staff'),
    Call('club_finances', 'get_club_finances', P(include_details=True), 'club_ref', 'club_refs', ''),
    Call('club_facilities', 'fm_live_mcp.club_facilities:get_club_facilities', (), 'club_ref', 'club_refs', ''),
    Call('competition', 'get_competition', (), 'competition_ref', 'competition_refs', 'competition'),
    Call('stadium', 'get_stadium', (), 'stadium_ref', 'stadium_refs', 'stadium'),
    Call('city', 'get_city', (), 'city_ref', 'city_refs', 'city'),
    Call('currency', 'get_currency', (), 'currency_ref', 'currency_refs', 'currency'),
)}

# Sample family -> editor record type of the sampled record.
SAMPLE_RTYPE = {'player': 'play', 'staff': 'nnpl', 'club': 'club', 'competition': 'comp',
                'stadium': 'stad', 'city': 'city', 'currency': 'curr'}

FAMILY_TITLES = {
    'player.identity': 'Player identity', 'player.attributes': 'Player outfield attributes (displayed)',
    'player.attributes_raw': 'Player outfield attributes (stored byte, fifths)',
    'player.goalkeeping': 'Player goalkeeper attributes (displayed)',
    'player.goalkeeping_raw': 'Player goalkeeper attributes (stored byte, fifths)',
    'player.hidden': 'Player hidden attributes (displayed)', 'player.hidden_raw': 'Player hidden attributes (stored byte)',
    'player.feet': 'Player feet (displayed)', 'player.feet_raw': 'Player feet (stored byte)',
    'player.ability': 'Player ability', 'player.positions': 'Player position ratings',
    'player.personality': 'Player personality', 'player.health': 'Player condition and injuries',
    'player.contract': 'Player contract and wage', 'player.value': 'Player transfer value', 'player.terms': 'Player contract terms',
    'player.club': 'Player club links',
    'staff.identity': 'Staff identity', 'staff.attributes': 'Staff attributes (displayed)',
    'staff.attributes_raw': 'Staff attributes (stored byte)', 'staff.tendencies': 'Staff tendencies (displayed)',
    'staff.tendencies_raw': 'Staff tendencies (stored byte)', 'staff.board': 'Staff board attributes (displayed)',
    'staff.board_raw': 'Staff board attributes (stored byte)',
    'staff.personality': 'Staff personality', 'staff.job': 'Staff job', 'staff.contract': 'Staff contract and wage',
    'club.identity': 'Club identity', 'club.finance': 'Club finance', 'club.facilities': 'Club facilities',
    'competition.identity': 'Competition identity', 'competition.context': 'Competition context',
    'stadium.identity': 'Stadium identity', 'stadium.capacity': 'Stadium capacity', 'stadium.pitch': 'Stadium pitch',
    'stadium.links': 'Stadium links and flags',
    'city.identity': 'City identity and geography', 'city.links': 'City links',
    'currency.identity': 'Currency',
    'nation.identity': 'Nation (reached from competition)', 'continent.identity': 'Continent (reached from competition)',
}


# ---------------------------------------------------------------------------------------
# Entries
# ---------------------------------------------------------------------------------------

def _build():
    out = []

    def add(fam, fld, call, path, rtype, codes, rule, params=(), sample='', via='', note=''):
        out.append(Entry(fam, fld, call, path, rtype, tuple(codes), rule, tuple(params), sample, via, note))

    # ----- player ---------------------------------------------------------------
    add('player.identity', 'name', 'player', 'name', 'pers', ('Pfna', 'Psna', 'Pcna'), 'full_name')
    add('player.identity', 'display_name', 'player', 'display_name', 'pers', ('Pfna', 'Psna', 'Pcna'), 'display_name')
    add('player.identity', 'name_dbnm', 'player', 'display_name', 'pers', ('dbnm',), 'string',
        note='dbnm is the stored database name; the tool display_name is the common name else the full name')
    add('player.identity', 'birth_date', 'player', 'birth_date', 'pers', ('Pdob',), 'date_iso')

    outfield = [  # tool name, displayed code, raw code
        ('crossing', 'Pcro', 'PDcr'), ('dribbling', 'Pdri', 'PDdr'), ('finishing', 'Pfin', 'PDfn'),
        ('heading', 'Phea', 'PDhd'), ('long_shots', 'Plsh', 'PDls'), ('marking', 'Pmar', 'PDmr'),
        ('off_the_ball', 'Potb', 'PDmv'), ('passing', 'Ppas', 'PDps'), ('penalty_taking', 'Ppen', 'PDpn'),
        ('tackling', 'Ptac', 'PDtk'), ('vision', 'Pcre', 'PDvs'), ('anticipation', 'Pant', 'PDan'),
        ('decisions', 'Pdec', 'PDdc'), ('positioning', 'Ppsn', 'PDpt'), ('first_touch', 'Pfrs', 'PDft'),
        ('technique', 'Ptec', 'PDtc'), ('flair', 'Pfla', 'PDfl'), ('corners', 'Pcor', 'PDcs'),
        ('teamwork', 'Ptwr', 'PDtm'), ('work_rate', 'Pwkr', 'PDwr'), ('long_throws', 'Plth', 'PDlt'),
        ('acceleration', 'Pacc', 'PDac'), ('free_kick_taking', 'Pfrk', 'PDfk'), ('strength', 'Pstr', 'PDst'),
        ('stamina', 'Psta', 'PDsm'), ('pace', 'Ppac', 'PDpc'), ('jumping_reach', 'Pjum', 'PDjm'),
        ('leadership', 'Pinf', 'PDld'), ('balance', 'Pbal', 'PDbl'), ('bravery', 'Pbra', 'PDbr'),
        ('aggression', 'Pagg', 'PDag'), ('agility', 'Pagi', 'PDal'), ('natural_fitness', 'Pnft', 'PDnf'),
        ('determination', 'Pdet', 'PDde'), ('composure', 'Pcmp', 'PDcp'), ('concentration', 'Pcnt', 'PDcc'),
    ]
    for name, shown, raw in outfield:
        add('player.attributes', name, 'player', f'attributes.{name}', 'play', (shown,), 'blob_byte', P(index=1))
        add('player.attributes_raw', name, 'player', f'attributes.{name}', 'play', (raw,), 'fifths_raw')

    goalkeeping = [
        ('aerial_reach', 'Paab', 'PDae'), ('command_of_area', 'Pcoa', 'PDca'), ('communication', 'Pcom', 'PDcm'),
        ('eccentricity', 'Pecc', 'PDec'), ('handling', 'Phan', 'PDhn'), ('kicking', 'Pkic', 'PDkc'),
        ('one_on_ones', 'Pooo', 'PDoo'), ('reflexes', 'Pref', 'PDrf'), ('rushing_out', 'Prou', 'PDro'),
        ('tendency_to_punch', 'Pttp', 'PDtp'), ('throwing', 'Pthr', 'PDth'),
    ]
    for name, shown, raw in goalkeeping:
        add('player.goalkeeping', name, 'player', f'profile.goalkeeping.{name}', 'play', (shown,), 'blob_byte', P(index=1))
        add('player.goalkeeping_raw', name, 'player', f'profile.goalkeeping.{name}', 'play', (raw,), 'fifths_raw')

    hidden = [('consistency', 'PCON', 'PDcy'), ('dirtiness', 'Pdir', 'PDdt'), ('important_matches', 'Pimp', 'PDim'),
              ('injury_proneness', 'Pipr', 'PDij'), ('versatility', 'Pver', 'PDvt')]
    for name, shown, raw in hidden:
        add('player.hidden', name, 'player', f'profile.hidden_attributes.{name}', 'play', (shown,), 'exact')
        add('player.hidden_raw', name, 'player', f'profile.hidden_attributes.{name}', 'play', (raw,), 'fifths_raw')

    for name, shown, raw in (('left', 'Plft', 'PDlf'), ('right', 'Prft', 'PDri')):
        add('player.feet', name, 'player', f'profile.feet.{name}', 'play', (shown,), 'exact')
        add('player.feet_raw', name, 'player', f'profile.feet.{name}', 'play', (raw,), 'fifths_raw')

    add('player.ability', 'current', 'player', 'profile.ability.current', 'play', ('PCAB',), 'exact')
    add('player.ability', 'potential_native_code', 'player', 'profile.ability.potential_native_code', 'play',
        ('PPAB',), 'exact')
    add('player.ability', 'potential', 'player', 'profile.ability.potential', 'play', ('PPAB',), 'exact',
        P(none_if_negative=True), note='tool null when the stored potential is a negative range code')

    positions = [('goalkeeper', 'Pgoa'), ('defender_left', 'Pdls'), ('defender_central', 'Pdce'),
                 ('defender_right', 'Pdrs'), ('defensive_midfielder', 'Pdmc'), ('midfielder_left', 'Pmls'),
                 ('midfielder_central', 'Pmce'), ('midfielder_right', 'Pmrs'),
                 ('attacking_midfielder_left', 'Paml'), ('attacking_midfielder_central', 'Pamc'),
                 ('attacking_midfielder_right', 'Pamr'), ('striker', 'Pace'), ('wing_back_left', 'Pwbl'),
                 ('wing_back_right', 'Pwbr')]
    for name, code in positions:
        add('player.positions', name, 'player', f'profile.positions.{name}', 'play', (code,), 'exact')

    personality = [('adaptability', 'Pada'), ('ambition', 'Pamb'), ('controversy', 'Pcvy'), ('loyalty', 'Ploy'),
                   ('pressure', 'Ppre'), ('professionalism', 'Ppro'), ('sportsmanship', 'Pspo'),
                   ('temperament', 'Ptem')]
    for name, code in personality:
        add('player.personality', name, 'player', f'profile.personality.{name}', 'pers', (code,), 'exact')

    add('player.health', 'condition', 'player', 'health.condition', 'play', ('Pcon',), 'exact')
    add('player.health', 'condition_stored', 'player', 'health.condition', 'play', ('x:condition_stored',), 'exact',
        note='extras.DERIVED: primary slot 138 with refresh flag 0 (the getter Pcon uses), int16 +0x254')
    add('player.health', 'match_sharpness', 'player', 'health.match_sharpness', 'play', ('Pfit',), 'exact')
    add('player.health', 'fatigue', 'player', 'health.fatigue', 'play', ('Pjad',), 'exact')
    add('player.health', 'injury_list_len', 'player', 'health.injury_record_count', 'play', ('x:injuries',), 'list_len',
        note='extras.DERIVED: the native injury vector (player +0xF0). The editor list Pijl (and Phij) read the '
             'STARTING_INJURY table, which is empty in a running career')
    add('player.health', 'injury_present', 'player', 'health.injury_record_count', 'play', ('injr',), 'presence',
        note='injr is the injury-info record the native injury builder publishes (research.md, 0.16.0)')
    add('player.health', 'injury_started', 'player', 'health.injuries[0].started', 'play', ('injr',), 'date_iso',
        P(key='iida'))
    add('player.health', 'injury_sentence_name', 'player', 'health.injuries[0].sentence_name', 'play', ('injr',),
        'index_name', P(key='injr', kind='injury_sentence'))
    add('player.health', 'injury_name', 'player', 'health.injuries[0].name', 'play', ('injr',), 'index_name',
        P(key='injr', kind='injury'))

    add('player.contract', 'wage_weekly_gbp', 'player', 'wage.amount', 'pers', ('Pcwg',), 'exact')
    add('player.contract', 'joined', 'player', 'contract_dates.joined', 'pers', ('Pcjd',), 'date_iso')
    add('player.contract', 'last_signed', 'player', 'contract_dates.last_signed', 'pers', ('Pcsd',), 'date_iso')
    add('player.contract', 'expires', 'player', 'contract_dates.expires', 'pers', ('Pcex',), 'date_iso')
    add('player.contract', 'status_code', 'player', 'contract_status.native_code', 'pers', ('Pcst',), 'enum_code')
    add('player.contract', 'status_label', 'player', 'contract_status.title', 'pers', ('Pcst',), 'enum_label',
        P(rtype='pers', code='Pcst'))

    add('player.value', 'transfer_value', 'player', 'transfer_prices.transfer_value_property.amount', 'play',
        ('PbvE',), 'exact')
    add('player.value', 'asking_price', 'player', 'transfer_prices.asking_price_property.amount', 'play',
        ('Papr',), 'exact', P(none_if_negative=True))

    for name, kind, code, member in (
            ('appearance_fee', 'appearance_fee', 'Pcap', 'amount_gbp'),
            ('unused_substitute_fee', 'unused_substitute_fee', 'Pusb', 'amount_gbp'),
            ('top_division_relegation_wage_drop', 'top_division_relegation_wage_drop', 'Ptrd', 'percentage'),
            ('relegation_wage_drop', 'relegation_wage_drop', 'Pcrd', 'percentage'),
            ('promotion_wage_rise', 'promotion_wage_rise', 'Pcpi', 'percentage'),
            ('top_division_promotion_wage_rise', 'top_division_promotion_wage_rise', 'Ptpi', 'percentage'),
            ('yearly_wage_rise', 'yearly_wage_rise', 'Pywi', 'percentage'),
            ('sell_on_fee', 'sell_on_fee', 'Psof', 'percentage')):
        add('player.terms', name, 'player', f'contract_terms.terms[kind={kind}].values.{member}', 'pers',
            (code,), 'exact')
    add('player.club', 'contract_club_name', 'player', 'clubs.contract_club.name', 'pers', ('Pcti',), 'ref_name',
        P(kind='club'))
    add('player.club', 'contract_club_short_name', 'player', 'clubs.contract_club.short_name', 'pers', ('Pcti',),
        'ref_name', P(kind='club_short'))
    add('player.club', 'current_club_name', 'player', 'clubs.current_club.name', 'pers', ('Ptaj',), 'ref_name',
        P(kind='club', key='Ttea'))
    add('player.club', 'current_club_name_Pcti', 'player', 'clubs.current_club.name', 'pers', ('Pcti',), 'ref_name',
        P(kind='club'))
    add('player.club', 'on_loan', 'player', 'clubs.on_loan', 'pers', ('Pion',), 'bool')

    # ----- staff ----------------------------------------------------------------
    add('staff.identity', 'name', 'staff', 'name', 'pers', ('Pfna', 'Psna', 'Pcna'), 'full_name')
    add('staff.identity', 'display_name', 'staff', 'display_name', 'pers', ('Pfna', 'Psna', 'Pcna'), 'display_name')
    add('staff.identity', 'birth_date', 'staff', 'birth_date', 'pers', ('Pdob',), 'date_iso')

    staff_attr = [  # tool name, displayed code, raw code, fifths
        ('goalkeeping', 'Npgs', 'NDgs', True), ('working_with_youngsters', 'Npwy', 'NDwy', False),
        ('people_management', 'Npmm', 'NDmm', True), ('attacking', 'Ncha', 'NDca', True),
        ('defending', 'Nchd', 'NDdf', True), ('fitness', 'Nchf', 'NDfi', True), ('possession', 'Nchm', 'NDmn', True),
        ('technical', 'Ncte', 'NDth', True), ('tactical', 'Ncta', 'NDtc', True), ('set_pieces', 'Ncsp', 'NDsp', True),
        ('tactical_knowledge', 'Nptk', 'NDtk', True), ('determination', 'Npde', 'NDde', True),
        ('judging_player_ability', 'Npja', 'NDja', True), ('judging_player_potential', 'Npjp', 'NDjp', True),
        ('authority', 'Npld', 'NDld', False), ('motivating', 'Npmo', 'NDmo', True),
        ('physiotherapy', 'Npph', 'NDph', True), ('analysing_data', 'Npjd', 'NDjd', True),
        ('judging_staff_ability', 'Npjs', 'NDjs', True), ('sports_science', 'NpIM', 'NDim', True),
        ('negotiating', 'Nneg', 'NNeg', True), ('versatility', 'Npvr', 'NDvr', True),
    ]
    for name, shown, raw, fifths in staff_attr:
        add('staff.attributes', name, 'staff', f'attributes.{name}', 'nnpl', (shown,), 'exact')
        add('staff.attributes_raw', name, 'staff', f'attributes.{name}', 'nnpl', (raw,),
            'fifths_raw' if fifths else 'direct_raw')
    add('staff.attributes', 'adaptability', 'staff', 'attributes.adaptability', 'nnpl', ('Npad',), 'exact')

    tendencies = [
        ('attacking', 'Natt', 'NDat', False), ('defensive_line', 'Ndep', 'NDdp', False),
        ('directness', 'Ndir', 'NDdi', False), ('dirtiness_allowance', 'Ndal', 'NDda', True),
        ('flexibility', 'Nflx', 'NDfx', False), ('trigger_press', 'Npre', 'NDpr', False),
        ('tempo', 'Ntem', 'NDto', False), ('width', 'Nwid', 'NDwd', False),
        ('buying_players', 'Nbpl', 'NDbp', False), ('hardness_of_training', 'Nhat', 'NDht', False),
        ('mind_games', 'Nmig', 'NDmg', False), ('squad_rotation', 'Nrot', 'NDsr', False),
    ]
    for name, shown, raw, fifths in tendencies:
        add('staff.tendencies', name, 'staff', f'tendencies.{name}', 'nnpl', (shown,), 'exact')
        add('staff.tendencies_raw', name, 'staff', f'tendencies.{name}', 'nnpl', (raw,),
            'fifths_raw' if fifths else 'direct_raw')
    board = [('business', 'Nbus', 'NDbs'), ('interference', 'Nint', 'NDin'), ('resources', 'Nres', 'NDrs'),
             ('patience', 'Npat', 'NDpt')]
    for name, shown, raw in board:
        add('staff.board', name, 'staff', f'board_attributes.{name}', 'nnpl', (shown,), 'exact')
        add('staff.board_raw', name, 'staff', f'board_attributes.{name}', 'nnpl', (raw,), 'direct_raw')

    for name, code in personality:
        add('staff.personality', name, 'staff', f'personality.{name}', 'pers', (code,), 'exact')

    add('staff.job', 'native_code', 'staff', 'contract.job.native_code', 'pers', ('Pcjo',), 'enum_code',
        note='Pcjo found by case variation of the editor PCJO and validated across the sample; not an editor field')
    add('staff.job', 'native_code_PCJO', 'staff', 'contract.job.native_code', 'pers', ('PCJO',), 'enum_code',
        note='the editor Job field (contract +0x24 per research.md)')
    add('staff.contract', 'club_name', 'staff', 'contract.club.name', 'pers', ('Pcti',), 'ref_name', P(kind='club'))
    add('staff.contract', 'joined', 'staff', 'contract.dates.joined', 'pers', ('Pcjd',), 'date_iso')
    add('staff.contract', 'last_signed', 'staff', 'contract.dates.last_signed', 'pers', ('Pcsd',), 'date_iso')
    add('staff.contract', 'expires', 'staff', 'contract.dates.expires', 'pers', ('Pcex',), 'date_iso')
    add('staff.contract', 'wage_weekly_gbp', 'staff', 'contract.wage.amount', 'pers', ('Pcwg',), 'exact')
    add('staff.contract', 'status_code', 'staff', 'contract.status.native_code', 'pers', ('Pcst',), 'enum_code')

    # ----- club -----------------------------------------------------------------
    add('club.identity', 'name', 'club_finances', 'club.name', 'club', ('Cnam',), 'string')
    add('club.identity', 'name_dbnm', 'club_finances', 'club.name', 'club', ('dbnm',), 'string')
    add('club.identity', 'short_name', 'club_finances', 'club.short_name', 'club', ('Csnm',), 'string')
    add('club.finance', 'balance', 'club_finances', 'finances.balance', 'club', ('Ccba',), 'exact')
    add('club.finance', 'weekly_wage_budget', 'club_finances', 'finances.weekly_wage_budget', 'club', ('Cwwb',), 'exact')
    add('club.finance', 'stored_transfer_budget', 'club_finances', 'finances.stored_transfer_budget', 'club',
        ('Ctfc',), 'exact')
    add('club.finance', 'current_transfer_budget', 'club_finances', 'finances.current_transfer_budget.amount',
        'club', ('Ctfc',), 'exact', note='tool applies native availability rules to the stored budget')
    add('club.finance', 'scouting_budget', 'club_finances', 'finances.details.scouting_budget.amount', 'club',
        ('CSbR',), 'exact')
    # fields lane: the live remaining wage budget is the game-layer key Cwrb (fieldroutes.ROUTES club.Crmb)
    add('club.finance', 'remaining_weekly_wage_budget', 'club_finances', 'finances.remaining_weekly_wage_budget.amount',
        'club', ('Cwrb',), 'exact', note='Crmb is answered only by the empty STARTING_CLUB_DEBT table')
    add('club.finance', 'average_match_ticket', 'club_finances', 'finances.details.ticket_prices.average_match_ticket',
        'club', ('Cmtp',), 'exact', P(none_if_negative=True), note='tool null where the stored price is the -1 sentinel')
    add('club.finance', 'average_season_ticket', 'club_finances', 'finances.details.ticket_prices.average_season_ticket',
        'club', ('Casp',), 'exact', P(none_if_negative=True))
    add('club.finance', 'season_ticket_holders', 'club_finances', 'finances.details.stored_season_ticket_holders',
        'club', ('Csth',), 'exact')
    add('club.finance', 'debt_and_loan_records', 'club_finances', 'finances.details.debt_and_loans.native_slot_count',
        'club', ('Cfln',), 'list_len')
    for name, code in (('training_facilities', 'Ctlv'), ('youth_facilities', 'Cyfb'), ('youth_coaching', 'Cytv'),
                       ('youth_recruitment', 'Crcb')):
        add('club.facilities', name, 'club_facilities', f'facilities.values.{name}.native_value', 'club', (code,), 'exact')

    # ----- competition ------------------------------------------------------------
    add('competition.identity', 'name', 'competition', 'name', 'comp', ('cnam',), 'string')
    add('competition.identity', 'name_dbnm', 'competition', 'name', 'comp', ('dbnm',), 'string')
    add('competition.identity', 'short_name', 'competition', 'short_name', 'comp', ('csnm',), 'string')
    add('competition.identity', 'abbreviation', 'competition', 'abbreviation', 'comp', ('c3ln',), 'string')
    add('competition.context', 'reputation', 'competition', 'context.reputation', 'comp', ('crep',), 'exact')
    add('competition.context', 'level', 'competition', 'context.level', 'comp', ('levl',), 'exact')
    add('competition.context', 'is_extinct', 'competition', 'context.is_extinct', 'comp', ('cext',), 'bool')
    add('competition.context', 'type_code', 'competition', 'context.competition_type.native_code', 'comp', ('dbty',),
        'unset', P(unset=(-1,)))
    add('competition.context', 'parent_name', 'competition', 'context.parent_competition.name', 'comp', ('cpcm',),
        'ref_name', P(kind='competition'))
    add('competition.context', 'type_label', 'competition', 'context.competition_type.name', 'comp', ('dbty',),
        'enum_label', P(rtype='comp', code='dbty'))
    add('competition.context', 'gender_code', 'competition', 'context.gender.native_code', 'comp', ('PLgn',), 'enum_code')
    add('competition.context', 'gender_label', 'competition', 'context.gender.name', 'comp', ('PLgn',), 'enum_label',
        P(rtype='comp', code='PLgn'))
    add('competition.context', 'nation_native_id', 'competition', 'context.nation.native_id', 'comp', ('cnti',),
        'ref_uid')
    add('competition.context', 'nation_name', 'competition', 'context.nation.short_name', 'comp', ('cnti',),
        'ref_name', P(kind='nation'))
    add('competition.context', 'nation_abbreviation', 'competition', 'context.nation.abbreviation', 'comp', ('cnti',),
        'ref_name', P(kind='nation_abbr'))
    add('competition.context', 'continent_native_id', 'competition', 'context.continent.native_id', 'comp',
        ('ccti',), 'ref_uid')
    add('competition.context', 'continent_name', 'competition', 'context.continent.name', 'comp', ('ccti',),
        'ref_name', P(kind='continent'))

    # nations and continents reached from the competition sample
    add('nation.identity', 'short_name', 'competition', 'context.nation.short_name', 'nati', ('Nsnm',), 'string',
        sample='competition', via='cnti')
    add('nation.identity', 'name_dbnm', 'competition', 'context.nation.short_name', 'nati', ('dbnm',), 'string',
        sample='competition', via='cnti')
    add('nation.identity', 'abbreviation', 'competition', 'context.nation.abbreviation', 'nati', ('N3ln',), 'string',
        sample='competition', via='cnti')
    add('continent.identity', 'name', 'competition', 'context.continent.name', 'cont', ('Cnam',), 'string',
        sample='competition', via='ccti')
    add('continent.identity', 'abbreviation', 'competition', 'context.continent.abbreviation', 'cont', ('C3ln',),
        'string', sample='competition', via='ccti')

    # ----- stadium ----------------------------------------------------------------
    add('stadium.identity', 'name', 'stadium', 'name', 'stad', ('Snam',), 'string')
    add('stadium.identity', 'name_dbnm', 'stadium', 'name', 'stad', ('dbnm',), 'string')
    add('stadium.identity', 'continental_name', 'stadium', 'continental_name', 'stad', ('Scnm',), 'empty_as_null')
    add('stadium.identity', 'is_extinct', 'stadium', 'is_extinct', 'stad', ('Sext',), 'bool')
    add('stadium.identity', 'is_training_ground', 'stadium', 'is_training_ground', 'stad', ('Sitg',), 'bool')
    add('stadium.capacity', 'total', 'stadium', 'capacities.total.native_value', 'stad', ('Scpy',), 'exact')
    add('stadium.capacity', 'seated', 'stadium', 'capacities.seated.native_value', 'stad', ('Sscy',), 'exact')
    add('stadium.capacity', 'used', 'stadium', 'capacities.used.native_value', 'stad', ('Sucy',), 'unset',
        P(unset=(0, -1)))
    add('stadium.capacity', 'expansion', 'stadium', 'capacities.expansion.native_value', 'stad', ('Secy',), 'exact')
    add('stadium.capacity', 'all_seater_competitions', 'stadium', 'capacities.all_seater_competitions.native_value',
        'stad', ('Scas',), 'unset', P(unset=(0, -1)))
    add('stadium.pitch', 'latitude', 'stadium', 'coordinates.latitude', 'stad', ('Slat',), 'float32')
    add('stadium.pitch', 'longitude', 'stadium', 'coordinates.longitude', 'stad', ('Slon',), 'float32')
    add('stadium.pitch', 'type_code', 'stadium', 'pitch.type.native_code', 'stad', ('Spty',), 'enum_code')
    add('stadium.pitch', 'type_label', 'stadium', 'pitch.type.name', 'stad', ('Spty',), 'enum_label',
        P(rtype='stad', code='Spty'))
    add('stadium.pitch', 'type_code_stored', 'stadium', 'pitch.type.native_code', 'stad', ('x:pitch_type_stored',),
        'enum_code', note='extras.DERIVED: stored byte +0xAD the Spty getter maps 0 -> 1 (Grass)')
    add('stadium.pitch', 'condition', 'stadium', 'pitch.condition', 'stad', ('Sptc',), 'exact')
    add('stadium.pitch', 'deterioration_code', 'stadium', 'pitch.deterioration_rate.native_code', 'stad', ('Sdtr',),
        'enum_code')
    add('stadium.pitch', 'recovery_rate', 'stadium', 'pitch.recovery_rate', 'stad', ('Sprr',), 'exact')
    add('stadium.pitch', 'length_default', 'stadium', 'pitch.dimensions.default.length.value', 'stad', ('Spln',),
        'float32')
    add('stadium.pitch', 'width_default', 'stadium', 'pitch.dimensions.default.width.value', 'stad', ('Spwd',),
        'float32')
    add('stadium.pitch', 'length_minimum', 'stadium', 'pitch.dimensions.minimum.length.value', 'stad', ('Smnl',),
        'float32')
    add('stadium.pitch', 'width_maximum', 'stadium', 'pitch.dimensions.maximum.width.value', 'stad', ('Smxw',),
        'float32')
    add('stadium.pitch', 'width_minimum', 'stadium', 'pitch.dimensions.minimum.width.value', 'stad', ('Smnw',),
        'float32')
    add('stadium.pitch', 'length_maximum', 'stadium', 'pitch.dimensions.maximum.length.value', 'stad', ('Smxl',),
        'float32')
    add('stadium.pitch', 'length_international', 'stadium', 'pitch.dimensions.international.length.value', 'stad',
        ('SlIM',), 'float32')
    add('stadium.pitch', 'width_international', 'stadium', 'pitch.dimensions.international.width.value', 'stad',
        ('SwIM',), 'float32')
    add('stadium.links', 'owner_type_code', 'stadium', 'owner_type.native_code', 'stad', ('Soty',), 'unset',
        P(unset=(0, -1)))
    add('stadium.links', 'environment_code', 'stadium', 'environment.native_code', 'stad', ('Senv',), 'unset',
        P(unset=(0, -1)))
    add('stadium.links', 'condition_code', 'stadium', 'stadium_condition.native_code', 'stad', ('Sste',), 'unset',
        P(unset=(0, -1)))
    add('stadium.links', 'has_digital_advertising', 'stadium', 'facilities.has_digital_advertising', 'stad', ('Sdah',), 'bool')
    add('stadium.links', 'has_undersoil_heating', 'stadium', 'facilities.has_undersoil_heating', 'stad', ('Sush',), 'bool')
    add('stadium.links', 'has_retractable_roof', 'stadium', 'facilities.has_retractable_roof', 'stad', ('Srrf',), 'bool')
    add('stadium.links', 'covered', 'stadium', 'facilities.stored_covered', 'stad', ('Scov',), 'bool')
    add('stadium.links', 'built', 'stadium', 'dates.built.date', 'stad', ('Sbld',), 'date_unset')
    add('stadium.links', 'rebuilt', 'stadium', 'dates.rebuilt.date', 'stad', ('Srbd',), 'date_unset')
    add('stadium.links', 'pitch_relay_required', 'stadium', 'dates.pitch_relay_required.date', 'stad', ('Sprl',),
        'date_unset')
    add('stadium.links', 'owner_club_name', 'stadium', 'owner_club.name', 'stad', ('Sowi',), 'ref_name', P(kind='club'))
    add('stadium.links', 'nearby_stadium_name', 'stadium', 'nearby_stadium.name', 'stad', ('Snbs',), 'ref_name',
        P(kind='stadium'))
    add('stadium.links', 'decay', 'stadium', 'decay', 'stad', ('Sdcy',), 'exact')
    add('stadium.links', 'senior_national_usage', 'stadium', 'national_team_usage.senior.native_code', 'stad',
        ('Sunt',), 'enum_code')
    add('stadium.links', 'city_name', 'stadium', 'city.name', 'stad', ('Scti',), 'ref_name', P(kind='city'))
    add('stadium.links', 'city_native_id', 'stadium', 'city.native_id', 'stad', ('Scti',), 'ref_uid')

    # ----- city -------------------------------------------------------------------
    add('city.identity', 'name', 'city', 'name', 'city', ('Cnam',), 'string')
    add('city.identity', 'name_dbnm', 'city', 'name', 'city', ('dbnm',), 'string')
    add('city.identity', 'latitude', 'city', 'coordinates.latitude', 'city', ('Clat',), 'float32')
    add('city.identity', 'longitude', 'city', 'coordinates.longitude', 'city', ('Clon',), 'float32')
    add('city.identity', 'altitude', 'city', 'altitude.native_value', 'city', ('Calt',), 'exact')
    add('city.identity', 'attraction', 'city', 'attraction', 'city', ('Catt',), 'exact')
    add('city.identity', 'population_code', 'city', 'population.native_code', 'city', ('Cinh',), 'enum_code')
    add('city.identity', 'is_deleted', 'city', 'is_deleted', 'city', ('DELE',), 'bool')
    add('city.links', 'nation_name', 'city', 'nation.short_name', 'city', ('Cnti',), 'ref_name', P(kind='nation'))
    add('city.links', 'nation_native_id', 'city', 'nation.native_id', 'city', ('Cnti',), 'ref_uid')
    add('city.links', 'local_region_name', 'city', 'local_region.name', 'city', ('Clri',), 'ref_name',
        P(kind='local_region'))
    add('city.links', 'weather_name', 'city', 'weather.name', 'city', ('Cwea',), 'ref_name', P(kind='weather'))
    add('city.links', 'language_name', 'city', 'language.name', 'city', ('Clgi',), 'ref_name', P(kind='language'))

    # ----- currency ---------------------------------------------------------------
    add('currency.identity', 'name', 'currency', 'name', 'curr', ('Cnam',), 'string')
    add('currency.identity', 'name_dbnm', 'currency', 'name', 'curr', ('dbnm',), 'string')
    add('currency.identity', 'name_stored', 'currency', 'name', 'curr', ('x:name_stored',), 'string',
        note='extras.DERIVED: stored native string +0x18; Cnam/dbnm return the translated name')
    add('currency.identity', 'exchange_rate', 'currency', 'exchange_rate.value', 'curr', ('Cexr',), 'float32')
    return out


ENTRIES = _build()

FAMILIES = tuple(dict.fromkeys(e.family for e in ENTRIES))          # per-field-group families
SAMPLES = ('player', 'staff', 'club', 'competition', 'stadium', 'city', 'currency')


def entries_for(sample: str):
    return [e for e in ENTRIES if e.sample_family == sample]


# ---------------------------------------------------------------------------------------
# Unmapped hand-built fields and generic-only fields
# ---------------------------------------------------------------------------------------

UNMAPPED = [
    Unmapped('staff', 'contract.job.title', 'get_staff(include_job)',
             'PCJO (editor Job, enum mdbj), PSJO, PNJO, CntF PFjo; the editor.fmf catalog',
             'The tool title is the native contract-job byte plus a team-type conversion (196 hand-extracted labels). '
             'The editor enum `mdbj` is a stub with no labels in editor.fmf, so only the native code is compared '
             '(via `Pcjo`, plus the editor `PCJO` for contrast).'),
    Unmapped('player', 'transfer_prices.last_transfer_fee / stored_transfer_valuation / stored_asking_price_input',
             'get_player(include_transfer_prices)',
             'catalog search for Transfer, Fee, Value, Asking; PbvE and Papr',
             'The tool reads three stored inputs (player +0x22C, +0x230, +0x23C). The only editor codes, PbvE and Papr, '
             'are the computed properties built on them (mapped as transfer_value and asking_price); no code returns the '
             'stored inputs. PFtf (Transfer Fee) belongs to a past-transfers list element.'),
    Unmapped('player', 'profile.ability.potential_range / potential_state', 'get_player(include_profile)',
             'PPMX (min_and_max), PPAR (enum), PPPA',
             'Derived from the 19-entry PPAR table for negative stored potential. The 300 random players probed all had '
             'a fixed positive PPAB, so no negative-potential example could be compared.'),
    Unmapped('player', 'clubs.loan_club (and the parent contract club of a loaned player)', 'get_player(include_clubs)',
             'PLcl, PFcl, Pcti, Ptaj, Pion',
             'PLcl and PFcl are not claimed by the PERSON getter. Pcti and Ptaj return the club the player currently plays '
             'for, so a loaned-out player resolves to the loan club (compared as contract_club_name, a known mismatch).'),
    Unmapped('player', 'contract_terms.terms of the other 36 kinds, contract_bonuses, loan_contract',
             'get_player(include_contract_terms / include_contract_bonuses / include_loan_contract)',
             'CntF codes PFap, PFgb, PFab, PFcb, PFfr, PFsq, PFms, PFwi, PFjo; guessed PERSON spellings Pgbo, Pabo, Pcsb',
             'The CntF contract-record codes are not claimed by the PERSON getter (all nine probed return not handled). '
             'Only eight kinds have a PERSON-level editor code (Pcap, Pusb, Ptrd, Pcrd, Pcpi, Ptpi, Pywi, Psof) and are mapped.'),
    Unmapped('club', 'finances.details.financial_fair_play, debt_and_loans.records[*] (amounts and dates)',
             'get_club_finances(include_details)',
             'Cffp, Cfln, Cdbt list codes',
             'Only the debt/loan record count is compared (list length of Cfln). Element fields were not decoded.'),
    Unmapped('currency', 'unmapped_text_fields (0x20, 0x28, 0x30) and history[] (65 yearly rates)', 'get_currency',
             'editor.fmf currency fields: only Cnam and Cexr exist',
             'The tool exposes three serialised text fields and the yearly rate history that have no editor field.'),
    Unmapped('stadium', 'dimensions.*.native_tenths, capacities.*.state, pitch state labels', 'get_stadium',
             'Spln, Spwd, Smnl, Smnw, Smxl, Smxw, SlIM, SwIM',
             'Compared as metre values (float32). The tool-only native tenths and state strings are derived and not compared.'),
]

TOOL_GAPS = [
    Gap('player', 'Pnat', 'Nationality (also Pnti, Pnbi, Pcbi, P2ni)',
        'get_player, get_staff and the player/staff finders return no nationality, birth nation or city, or second nations (the other ~160 tools were not searched).'),
    Gap('player', 'PCRP', 'Current / home / world reputation (PHRP, PWRP)', 'Not returned by get_player or the finders.'),
    Gap('player', 'Phei', 'Height (also Pife gender, Page age, Psnu squad number, Piap/Pigl international caps)',
        'Returned by the VM for the probed player; no tool field.'),
    Gap('player', 'Pagt', 'Agent reference', 'Not returned by get_player.'),
    Gap('club', 'Crep', 'Club reputation', 'get_club_finances and find_clubs return only names and finances.'),
    Gap('club', 'Cnti', 'Club nation (also Cbni based nation, Csti stadium, Ctsi training ground)',
        'No club tool returns nation or stadium links.'),
    Gap('club', 'Cl3n', 'Three-letter name and nickname (TCnn)', 'Not exposed.'),
    Gap('stadium', 'Snti', 'Stadium nation', 'get_stadium returns city and owner club only.'),
]

# Codes the generic reader answers that are not field definitions of the stated record type in
# editor.fmf (checked by an offline test so that they stay explicit).
OUTSIDE_CATALOG = {
    ('play', 'injr'): 'injury-info record published by the native injury builder (docs/research.md 0.16.0); not an editor field',
    ('pers', 'Pcjo'): 'live contract job byte (+0x26); found by case variation of PCJO, validated against the tool',
    ('play', 'Papr'): 'asking price property used by the tool (financial_details.player_prices); not an editor field',
    ('city', 'DELE'): 'stored deleted flag the tool reads (cities.py); the getter claims it, the editor does not list it',
    ('club', 'Cwrb'): 'game-layer remaining weekly wage budget (wage_budget.py); the editor Crmb is answered only by '
                      'the empty STARTING_CLUB_DEBT table (fieldroutes.ROUTES)',
}


DIFFERENT = 'different semantics (both defensible)'
GENERIC_WRONG = 'generic reader wrong'
TOOL_WRONG = 'existing tool wrong'
UNDETERMINED = 'undetermined'

_STAFF_BASIC = (
    'Staff on a basic contract (job 46, contract status -1) get 0 from every display attribute key while the tool reports '
    'the stored rating and the raw NDxx key agrees with the tool. The NON_PLAYER getter suppresses ratings for that '
    'role/contract; the tool says it does not apply role or UI visibility suppression.')

TOOL_UNAVAILABLE = {
    'player.contract.*': 'Free agent: the tool reports state no_contract and omits every contract date, while the person-level '
                         'Date Joined (Pcjd) keeps the date of the last club.',
    'staff.contract.joined': 'Same: staff without a contract get no dates from the tool; Pcjd keeps the person-level date.',
    'staff.contract.*': 'Staff without a contract (state no_contract): the tool returns no club, dates, status or wage.',
    'staff.job.*': 'Staff without a contract: the tool returns no job.',
    'player.value.transfer_value': 'Combined player/staff records: the tool reports unsupported_player_layout for prices.',
    'club.finance.*': 'Tool null while the generic reader returns a stored value.',
    'competition.identity.*': 'Competition with no stored name or abbreviation: the tool returns null, the generic getter '
                              'returns an empty string (cnam/csnm/c3ln) or a generated name (dbnm).',
    'stadium.pitch.type_label': 'Stored pitch type 0 (not specified): the tool has no label; the generic getter returns Grass.',
    'stadium.pitch.*': 'Tool null (value not specified) while the generic reader returns a value.',
}

FINDINGS = {
    'staff.attributes.*': (DIFFERENT, _STAFF_BASIC),
    'stadium.pitch.type_code': (
        DIFFERENT,
        'Stored pitch type 0 (not specified; the tool returns code 0 and no label) comes back from the generic getter as 1 '
        '(Grass): the STADIUM getter reads byte +0xAD and returns max(1, value) (0x16C9EF4, `csinc w20, w8, wzr, hi`), '
        'so the game treats an unspecified pitch as grass. The stored byte is compared as type_code_stored.'),
    'staff.job.native_code_PCJO': (
        DIFFERENT,
        'PCJO is the editor Job field at contract +0x24 and is 0 for every sampled contract; the tool decodes the live job '
        'byte at +0x26 (docs/research.md 0.10.0 already warns against substituting PCJO). The key `Pcjo` returns that live '
        'byte and agrees with the tool on every record that has a job. Comparing the tool to PCJO is expected to fail.'),
    'player.health.condition': (
        DIFFERENT,
        'The Pcon property (0x1509140) returns -1 when primary slot 21 reports an injury record and slot 23 (the most days '
        'still out over the injury vector) is above 0; otherwise it returns slot 138 (stored int16 +0x254). So -1 is the '
        "game's own answer for a player who is out injured. The tool returns the stored value without that rule; the "
        'stored value is compared as condition_stored (extras.DERIVED) and agrees.'),
    'player.club.contract_club_name': (
        DIFFERENT,
        'The tool reports the club of the full contract (the parent club of a loaned-out player, and the owning club of a '
        'B/reserve team); `Pcti` is the team the player currently plays for (a loan club, or a B team that has its own club '
        'record). Players on loan have Pion true. The editor schema has no team-to-club link, and PFcl/PLcl are not claimed, '
        'so the generic reader cannot answer the parent-club question.'),
    'player.club.contract_club_short_name': (
        DIFFERENT, 'Same cause as contract_club_name.'),
    'player.club.current_club_name': (
        DIFFERENT,
        'The tool current club is the CLUB behind the current TEAM; `Ptaj`/`Pcti` return the team. For B and reserve teams the '
        'clubs table has a separate record with the same id and the B-team name (`Stade Lavallois Mayenne FC 2`, `Havre AC 2`), '
        'so resolution by id lands on that record rather than the parent club. Most youth-team references (ids above '
        '2,000,000,000, e.g. `AJ Auxerre Under 19s`) have no club record at all and are reported as generic-unavailable.'),
    'player.club.current_club_name_Pcti': (
        DIFFERENT, 'Same cause as current_club_name.'),
    'currency.identity.name': (
        DIFFERENT,
        'The generic name getter returns the translated display name when the game has one (`United Kingdom Pound` stored, '
        '`UK Pound Sterling` shown); `dbnm` shows the same translated name. The tool deliberately reads the stored string '
        '("names omit native localization overrides"). Translations not cached in memory are read from the plugin\'s '
        'languages.fmf (PropertyVM file_resolver). The stored string is compared as name_stored.'),
    'currency.identity.name_dbnm': (DIFFERENT, 'Same cause as currency.identity.name.'),
}
