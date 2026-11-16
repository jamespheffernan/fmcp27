"""`fm_coverage`: what the reader can read, measured against the game's own inventories (`ledger.py`)."""
from __future__ import annotations

from functools import lru_cache
from typing import Annotated, Any, Literal

from mcp.types import ToolAnnotations
from pydantic import Field

from . import ledger

NOTE = ('Denominators come from the game itself: the editor schema, the record getters, the front-end property '
        'registry, the plugin RTTI with live roots, the persistence layer, and the hand-built tools. "reads" means a '
        'route returned values on this career; unset_on_samples means the route runs but every sampled record or '
        'binding was empty; empty_in_save means a full scan asked every record and none holds a value (reachable, no data in this save); needs_parameter means a screen parameter was not supplied; unavailable carries the '
        'reason; unreached means no reader reaches it. availability says where a readable value lives: '
        'snapshot_direct and snapshot_emulated are columns of fm_db_query; on_demand is computed per call '
        '(fm_db_read, fm_ui_read, a screen tool or a hand-built tool); cost_class and cost give the measured price '
        '(microseconds per cell, ms per row or key, seconds per handler). Use "surfaces" to find the tool or column.')


@lru_cache(maxsize=1)
def _ledger():
    data = ledger.load(ledger.CURRENT) or ledger.load(ledger.BEFORE)
    if data is None:
        raise ValueError('No ledger is packaged; run scripts/fmdb_ledger.py')
    return data


def coverage(domain=None, search=None, denominator=None, status=None, limit=40) -> dict[str, Any]:
    data = _ledger()
    out = {'built_at': data['meta'].get('built_at'), 'game_date': data['meta'].get('game_date'), 'note': NOTE}
    if not (domain or search or denominator or status):
        out['headline'] = {k: {'reads': v['reads'], 'total': v['total'], 'percent': v['percent'],
                               'by_status': v['by_status'], 'by_availability': v.get('by_availability')}
                           for k, v in data['headline'].items()}
        out['costs'] = data['meta'].get('costs')
        out['domains'] = list(ledger.DOMAIN_NAMES)
        out['denominators'] = ledger.DENOMINATORS
        out['top_gaps'] = [{k: g[k] for k in ('title', 'domain', 'denominator', 'status', 'size', 'reason', 'route')
                            if g.get(k) is not None} for g in data.get('gaps', [])[:20]]
        return out
    out.update(ledger.query(data, domain=domain, search=search, denominator=denominator, status=status,
                            limit=limit))
    if domain:
        out['gaps'] = [g for g in data.get('gaps', []) if domain.lower() in g['domain']][:15]
    return out


def register_ledger_tools(mcp, bridge):
    read_only = ToolAnnotations(readOnlyHint=True, destructiveHint=False, openWorldHint=False)

    @mcp.tool(annotations=read_only)
    def fm_coverage(
        session_id: str,
        domain: Annotated[str | None, Field(min_length=2, max_length=64)] = None,
        search: Annotated[str | None, Field(min_length=2, max_length=120)] = None,
        denominator: Literal['editor', 'getter_extra', 'ui', 'native', 'persisted', 'tools'] | None = None,
        status: Literal['reads', 'unset_on_samples', 'empty_in_save', 'needs_parameter', 'unavailable', 'unreached'] | None = None,
        limit: Annotated[int, Field(ge=1, le=200)] = 40,
    ) -> dict[str, Any]:
        """Say truthfully whether a piece of game data is readable and through which tool. No filters: headline coverage per inventory (editor schema fields, getter keys, UI property keys, native classes, persisted classes, hand-built tools), the domain list and the top gaps ranked by value to a manager. domain (e.g. "transfers", "scouting", "training"), search (words matched against keys, names and labels, e.g. "wage budget", "PCAB", "SCOUT_MANAGER"), denominator and status filter the ledger rows; each row gives status, route, reason and "surfaces" (the snapshot column or tool that returns it). Reads a packaged ledger; never touches the game."""
        out = coverage(domain=domain, search=search, denominator=denominator, status=status, limit=limit)
        from .. import address_book
        build = address_book.report(address_book.tool_functions(mcp) if address_book.MAP is not None else None)
        if address_book.MAP is not None:
            build['unavailable_tables'] = address_book.unavailable_tables()
        out['game_build'] = build
        return out

    return ['fm_coverage']
