"""One label for every (record type, FourCC) the readers return, with the source it came from.

`label_for(record_type, code) -> (label, source)` looks in game sources first:

* ``editor``           the shipped editor schema (`editor.fmf`) defines the code on this record type;
* ``editor_language``  the editor field's ``translation_id`` resolved in the shipped language table
                       (only when the editor gives no name of its own);
* ``getter_code``      a meaning established from the getter's code (`extras.PROVEN`);
* ``filters``          the shipped person search-filter metadata (`filters.fmf`,
                       ``filters/person_filter_metadata.xml``) names the property: each item pairs a
                       person property FourCC with its English name, translation id, category and the
                       person types it is valid for (``play``, ``nnpl`` or ``any``); person types only;
* ``editor_other``     the editor defines the same FourCC on another record type (FourCCs are shared
                       between record types, e.g. person keys on players and staff);
* ``ui_registry``      the front end's own property registry pairs the FourCC with a property name
                       (GameAssembly 0xA296BC, `ui_registry`), shown as words (``WageAfterTax`` ->
                       "Wage after tax");
* ``inferred``         the census label of `extras.py`, inferred from spelling and sampled values.

``None`` when nothing names the code. Nothing here reads the game.

The language table is the shipped `templates/user_folder/languages/example.ltf` (the English
template of `languages.fmf`: ``KEY-<translation id>: text[COMMENT ...]``). Editor fields carry
the translation id of their name, enum values the translation id of each label; 2,959 of the
2,960 editor translation ids give exactly the editor's own name. The 136 enum fields whose label
set is not in `editor.fmf` reference 19 named enums (formations, positions, roles, jobs, height,
reputation ranges, stadium rules, substitution rules); the language table holds the words (for
example the 59 formation names at ids 636403-636461), but the value -> translation id mapping is
built in native code (ids are `movz/movk` immediates, no data table), so those sets stay
unresolved here: see `ENUM_SETS_UNRESOLVED`.
"""
from __future__ import annotations

from functools import lru_cache
import re
from pathlib import Path

LTF_RELATIVE = Path('Contents/PlugIns/game_plugin.bundle/Contents/Resources/data/game_simulation/'
                    'templates/user_folder/languages/example.ltf')
from .. import build_paths  # noqa: E402

DEFAULT_APP = build_paths.installed_app()   # run time: the installed build (FMCP_PLUGIN_PATH)

FILTERS_RELATIVE = Path('Contents/PlugIns/game_plugin.bundle/Contents/Resources/data/game_simulation/filters.fmf')
PERSON_TYPES = frozenset({'pers', 'play', 'nnpl', 'offc', 'jour', 'agen'})

SOURCES = ('editor', 'editor_language', 'getter_code', 'filters', 'editor_other', 'ui_registry', 'inferred')
GAME_SOURCES = frozenset(SOURCES[:-1])

# Named enums referenced by editor fields whose label sets are not in editor.fmf, with the game
# source that holds the words and what is missing to pair values with them.
ENUM_SETS_UNRESOLVED = {
    'pfms': 'formation names: language ids 636403-636461 (59) and 688193-688204, 720516; '
            'index -> id mapping is in native code',
    'sfms': 'formation names (as pfms)', 'dfms': 'formation names (as pfms)',
    'afms': 'formation names (as pfms)', 'foms': 'formation names (award team formation)',
    'Posi': 'tactical positions: position names are translation immediates in native code',
    'nprl': 'in-possession roles: role names are translation immediates in native code',
    'Oprl': 'out-of-possession roles (as nprl)', 'ovrl': 'roles (as nprl)',
    'mdbj': 'staff jobs: `staff_jobs.py` holds 196 native job-title labels from 0x1358AC8, but '
            'equality of the editor enum numbering with the native job byte is unproven',
    'mdjz': 'staff jobs (as mdbj)', 'mdnj': 'staff jobs (as mdbj)', 'mdjc': 'staff jobs (as mdbj)',
    'mj+c': 'staff jobs (as mdbj)',
    'Phei': 'height: an integer in cm rendered by native code, not a label set',
    'crrp': 'reputation ranges: declared without labels',
    'nstr': 'stadium rules: not in the archive', 'subs': 'substitution rules: not in the archive',
    'LxEd': 'licence expiry dates: not in the archive',
}


def words(name: str) -> str:
    """'WageAfterTax' -> 'Wage after tax'; keeps acronyms ('xGOT' stays)."""
    if not name or ' ' in name:
        return name
    parts = re.findall(r'[A-Z]{2,}(?=[A-Z][a-z]|\d|$)|[A-Z]?[a-z]+|[A-Z]+|\d+', name)
    if not parts:
        return name
    out = [parts[0]] + [p if p.isupper() and len(p) > 1 else p.lower() for p in parts[1:]]
    return ' '.join(out)


def ltf_path(app: Path | None = None) -> Path:
    return (app or DEFAULT_APP) / LTF_RELATIVE


@lru_cache(maxsize=1)
def language_table(path: str | None = None) -> dict:
    """{translation id: (text, comment)} from the shipped English template (about 0.6 s)."""
    p = Path(path) if path else ltf_path()
    out = {}
    if not p.exists():
        return out
    rx = re.compile(r'^KEY-(\d+): (.*)$')
    with open(p, encoding='utf-8', errors='replace') as handle:
        for line in handle:
            m = rx.match(line)
            if not m:
                continue
            text, comment = m.group(2).rstrip('\n'), None
            i = text.find('[COMMENT')
            if i >= 0:
                comment, text = text[i + 8:].strip().rstrip(']').strip(' -:'), text[:i]
            out[int(m.group(1))] = (text.strip(), comment)
    return out


_MARKUP = re.compile(r'\[(?:%[^\]]*|COMMENT[^\]]*)\]')


def clean_text(text: str | None) -> str | None:
    """Drop the language markers ('[%person#1-hidden]') and translator comments from a game string."""
    if text is None:
        return None
    return ' '.join(_MARKUP.sub('', text).split()) or None


@lru_cache(maxsize=1)
def person_filters(path: str | None = None) -> dict:
    """{FourCC: {name, translation_id, category, valid_type}} from the shipped `filters.fmf`."""
    import xml.etree.ElementTree as ET
    from . import catalog
    p = Path(path) if path else DEFAULT_APP / FILTERS_RELATIVE
    if not p.exists():
        return {}
    frames, _ = catalog.parse_container(p.read_bytes())
    out = {}
    for info, raw in frames:
        if not info.name.endswith('person_filter_metadata.xml'):
            continue
        root = ET.fromstring(raw.decode('utf-8-sig', errors='replace'))
        for item in root.iter('record'):
            code = name = tid = category = valid = None
            for child in item:
                cid = child.get('id')
                if child.tag == 'integer' and cid == 'id':
                    code = child.get('value')
                elif child.tag == 'translation' and cid == 'name':
                    name, tid = clean_text(child.get('value')), child.get('translation_id')
                elif child.tag == 'translation' and cid == 'category':
                    category = clean_text(child.get('value'))
                elif child.tag == 'flags' and cid == 'valid_type':
                    valid = child.get('value')
            if code and name and len(code) == 4:
                out.setdefault(code, {'name': name, 'translation_id': int(tid) if tid else None,
                                      'category': category, 'valid_type': valid})
    return out


def _filter_label(record_type, code):
    if record_type not in PERSON_TYPES:
        return None
    item = person_filters().get(code)
    if not item:
        return None
    valid = item.get('valid_type') or 'any'
    allowed = {'any': PERSON_TYPES, 'play': {'pers', 'play'}, 'staf': {'pers', 'nnpl'}}.get(valid, {valid})
    if record_type not in allowed:
        return None
    return item['name']


@lru_cache(maxsize=1)
def _sources():
    from . import catalog, extras, ui_registry
    try:
        cat = catalog.load_catalog()
    except Exception:  # noqa: BLE001 - offline machines without the game
        cat = None
    try:
        reg = ui_registry.default()
    except Exception:  # noqa: BLE001
        reg = None
    return cat, extras, reg


def label_for(record_type: str | None, code: str) -> tuple[str | None, str | None]:
    cat, extras, reg = _sources()
    if cat is not None and record_type in cat.record_types:
        f = cat.field(record_type, code)
        if f is not None:
            if f.name:
                return f.name, 'editor'
            if f.translation_id:
                text = language_table().get(f.translation_id)
                if text and text[0]:
                    return text[0], 'editor_language'
    proven = extras.PROVEN.get((record_type, code)) or extras.PROVEN.get(('*', code))
    if proven:
        return proven, 'getter_code'
    filtered = _filter_label(record_type, code)
    if filtered:
        return filtered, 'filters'
    if cat is not None:
        for scope in cat.find(code):
            if scope.field.name:
                return scope.field.name, 'editor_other'
    if reg is not None and reg.label(code):
        return words(reg.label(code)), 'ui_registry'
    info = extras.EXTRA_FIELDS.get(record_type, {}).get(code)
    if info:
        return info['name'], 'inferred'
    return None, None


def census() -> dict:
    """How the getter keys outside the editor schema (`extras.EXTRA_FIELDS`) are labelled."""
    from collections import Counter
    _, extras, _ = _sources()
    counts, total = Counter(), 0
    for rtype, fields in extras.EXTRA_FIELDS.items():
        for code in fields:
            total += 1
            counts[label_for(rtype, code)[1]] += 1
    game = sum(n for s, n in counts.items() if s in GAME_SOURCES)
    return {'extra_keys': total, 'by_source': dict(counts), 'from_game_source': game,
            'inferred': counts.get('inferred', 0)}


def editor_language_check() -> dict:
    """Editor names against the language table by translation id (same text / different / absent)."""
    cat, _, _ = _sources()
    table = language_table()
    same = diff = absent = 0
    for scope in (cat.iter_fields() if cat else ()):
        t = scope.field.translation_id
        if not t:
            continue
        if t not in table:
            absent += 1
        elif table[t][0] == (scope.field.name or '').strip():
            same += 1
        else:
            diff += 1
    return {'same': same, 'different': diff, 'absent': absent}
