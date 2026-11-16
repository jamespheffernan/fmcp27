"""Screen parameters: what each parameter global is and which values to pass for it.

Getters read screen parameters through 0x77E228(request, path global, out typed*, inherit)
(`ui_recipes_person` answers the lookup with int32 typed values; `ui_recipes_screens.PARAMS`
names the Club Vision ones). The plugin defines 231 such globals, each a {hash, const char
*name} pair set by a static initialiser; `ui_frontend.json.gz` (`plugin_params`) maps the
name to the global's RVA. The front end sets them from the view (literal `{name}{Int|N|}`
parameters in the UXML: `views[*].params`) or from the object the view shows (person,
team, club, competition, date ...).

This module gives each parameter a kind and the values worth trying for it on a career:
object parameters take the UI id of a bound object (`1 << 24 | person index`, team, club,
competition ids as in UI_RECORD fields), dates take an SI_DATE, flags 1 then 0, counts and
indexes the values the views use plus small integers. `candidates(name, bindings)` returns
them in the order to try. Which of them a getter accepts is established by running it
(`scripts/fmdb_ui_sweep.py --round2`), never assumed: a value counts only when the getter
returns data with it.
"""
from __future__ import annotations

from collections import Counter
from functools import lru_cache

# Object-valued parameters -> the binding (scripts/fmdb_ui_sweep.collect_bindings) to pass.
OBJECT_PARAMS = {
    'person': ('player', 'human', 'scouted_player', 'scout'),
    'comparisonperson': ('scouted_player', 'player'),
    'human': ('human', 'human_person_index'),
    'scout': ('scout',),
    'team': ('team', 'opponent_team'),
    'humanteam': ('team',), 'localteam': ('team',), 'newscontextteam': ('team',),
    'teamrequestingreport': ('team',), 'buyingteam': ('team',), 'sellingteam': ('opponent_team',),
    'oppoteam': ('opponent_team',),
    'club': ('club', 'opponent_club'), 'comparisonclub': ('opponent_club',), 'otherclub': ('opponent_club',),
    'buyingclub': ('club',), 'sellingclub': ('opponent_club',), 'targetclub': ('opponent_club',),
    'competition': ('league', 'ucl'), 'dbsummarycompetition': ('league',),
    'nation': ('nation',), 'dbsummarynation': ('nation',), 'continent': ('continent',),
    'record': ('player', 'team', 'club'), 'selectedobject': ('player', 'team'),
    'context': ('team', 'player'), 'specificdatabaseobjectuid': ('player',),
    'newsitem': ('news_unid',), 'newsitemuniqueid': ('news_unid',),
    'recruitmentfocusid': ('recruitment_focus',),
    'id': ('player', 'team', 'human', 'news_unid', 'scout'),
}
DATE_PARAMS = ('date', 'selecteddate', 'dateofbirth')
YEAR_PARAMS = ('year', 'selectedyear', 'nextseason')
FLAG_HINTS = ('is', 'has', 'show', 'highlight', 'hide', 'allow', 'only', 'boolean', 'inpossession',
              'unpicked', 'onepergender', 'fixturehasresult', 'addany', 'adjust', 'withselector')
# Integer parameters with no literal in the views: values that are valid on every screen.
SMALL_INTS = (0, 1, 2, 3, 5)
COUNT_PARAMS = {'number': (10, 5, 20, 1), 'numbertoreturn': (10, 5), 'resultstoshow': (10,),
                'numsimilartosuggestions': (5, 10), 'numpositionrolesuggestions': (5,),
                'numberofrecruitmentfocusbasicsuggestions': (5,), 'squaddepthmaximumplayercount': (3,)}


@lru_cache(maxsize=1)
def table() -> dict:
    """{name (lower case): {'rva': int, 'view_values': [int, ...]}} for the 231 globals."""
    from . import ui_frontend
    data = ui_frontend.load_table()
    values = {}
    for view in (data.get('views') or {}).values():
        for name, literals in (view.get('params') or {}).items():
            c = values.setdefault(name.lower(), Counter())
            for lit in literals:
                kind, _, text = str(lit).partition(':')
                if kind in ('Int', 'Bool'):
                    try:
                        c[int(text)] += 1
                    except ValueError:
                        continue
    out = {}
    for name, rva in (data.get('plugin_params') or {}).items():
        rva = int(rva, 16) if isinstance(rva, str) else int(rva)
        out[name.lower()] = {'name': name, 'rva': rva,
                             'view_values': [v for v, _ in values.get(name.lower(), Counter()).most_common()]}
    return out


@lru_cache(maxsize=1)
def by_rva() -> dict:
    return {row['rva']: name for name, row in table().items()}


def name_of(rva: int) -> str | None:
    return by_rva().get(rva)


def rva_of(name: str) -> int:
    row = table().get(name.lower())
    if row is None:
        from . import ui_frontend
        data = ui_frontend.table()
        if name.lower() in (data.get('_plugin_params_dropped') or ()):
            raise KeyError(f'screen parameter {name!r} has no known global on the running build. {ui_frontend.note()}')
        raise KeyError(f'unknown screen parameter {name!r}')
    return row['rva']


def kind_of(name: str) -> str:
    name = name.lower()
    if name in OBJECT_PARAMS:
        return 'object'
    if name in DATE_PARAMS:
        return 'date'
    if name in YEAR_PARAMS:
        return 'year'
    if name in COUNT_PARAMS:
        return 'count'
    if name.startswith(FLAG_HINTS) or name in ('gender', 'boolean'):
        return 'flag' if name != 'gender' else 'int'
    return 'int'


def candidates(name: str, bindings: dict, limit: int = 6) -> list:
    """Values to try for one parameter on this career, best first (ints, deduplicated)."""
    name = name.lower()
    kind = kind_of(name)
    out = []
    if kind == 'object':
        for b in OBJECT_PARAMS[name]:
            v = bindings.get(b)
            if isinstance(v, int) and not isinstance(v, bool):
                out.append(v)
    elif kind == 'date':
        out.append(bindings.get('today_si'))
    elif kind == 'year':
        year = int(str(bindings.get('game_date', '2030'))[:4])
        out += [year, year - 1, 0]
    elif kind == 'count':
        out += list(COUNT_PARAMS[name])
    elif kind == 'flag':
        out += [1, 0]
    row = table().get(name) or {}
    out += row.get('view_values', [])
    if kind in ('int', 'count'):
        out += list(SMALL_INTS)
        if name.endswith('month') or name == 'monthindex':
            month = int(str(bindings.get('game_date', '2030-12'))[5:7])
            out = [month - 1, month] + out
    seen, clean = set(), []
    for v in out:
        if isinstance(v, bool):
            v = int(v)
        if isinstance(v, int) and v not in seen:
            seen.add(v)
            clean.append(v)
    return clean[:limit]


def assignments(rvas, bindings: dict, limit: int = 8) -> list:
    """Parameter sets ({rva: int}) to try for a getter that read `rvas`: every parameter at
    its first candidate, then one parameter at a time through its other candidates."""
    names = [(rva, name_of(rva)) for rva in rvas]
    names = [(rva, n) for rva, n in names if n]
    if not names:
        return []
    cands = {rva: candidates(n, bindings) or [0] for rva, n in names}
    first = {rva: c[0] for rva, c in cands.items()}
    out = [first]
    for rva, c in cands.items():
        for v in c[1:]:
            out.append({**first, rva: v})
            if len(out) >= limit:
                return out
    return out


def describe(rvas) -> list:
    """[{'rva', 'name', 'kind'}] for parameter RVAs a getter read (unknown ones too)."""
    out = []
    for rva in rvas:
        rva = int(rva, 16) if isinstance(rva, str) else int(rva)
        n = name_of(rva)
        out.append({'rva': hex(rva), 'name': n, 'kind': kind_of(n) if n else None})
    return out


__all__ = ['table', 'name_of', 'rva_of', 'kind_of', 'candidates', 'assignments', 'describe', 'OBJECT_PARAMS']
