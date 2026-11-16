"""Read-only canonical CLUB adapter for retained transfer schedule obligations."""
from copy import deepcopy
from datetime import datetime, timezone

from . import players, retained_transfer_debt
from .bridge import BridgeError
from .live_debt_obligations import _selected, _stream


def schedule_totals(report):
    """Derived gross sides, distinct from the original native signed net."""
    groups = {name: [] for name in ('outgoing', 'incoming', 'self')}
    records = report['records']
    if records is not None:
        for row in records:
            groups[row['direction']].append(row)
    totals = {}
    for name, rows in groups.items():
        values = [row['native_remaining_amount']['amount'] for row in rows]
        known = records is not None and all(value is not None for value in values)
        totals[name] = {'amount': sum(values) if known else None, 'currency': report['currency'],
                        'record_count': len(rows) if records is not None else None,
                        'state': 'derived_retained_schedule_sum' if known else
                                 'source_unavailable' if records is None else 'unclassified_native_terms'}
    net = report['native_transfer_debt']
    reconciled = None
    if net is not None and net['amount'] is not None and all(t['amount'] is not None for t in totals.values()):
        reconciled = totals['outgoing']['amount'] - totals['incoming']['amount'] + totals['self']['amount'] == net['amount']
        if not reconciled:
            raise ValueError('Derived retained transfer gross sides do not reconcile with native net')
    return {'gross_outgoing': totals['outgoing'], 'gross_incoming': totals['incoming'],
            'self_club_native_positive_contribution': totals['self'], 'native_net_transfer_debt': net,
            'gross_sides_reconcile_native_net': reconciled, 'scope': 'native_retained_prefix_only',
            'payment_state': 'not_established', 'next_payment_due_date': None,
            'complete_liability_ledger': False}


def get_club_transfer_debt_obligations(bridge, session_id, coach_name=None, club_ref=None):
    """Read the report and finish physical checks after all context callbacks."""
    if type(session_id) is not str or not 1 <= len(session_id) <= 128:
        raise BridgeError('session_id must be a current attachment ID of at most 128 characters.')
    if coach_name is not None and (type(coach_name) is not str or not 1 <= len(coach_name) <= 256):
        raise BridgeError('coach_name must be a name returned by fm_get_save.')
    if club_ref is not None and (type(club_ref) is not str or not 1 <= len(club_ref) <= 128):
        raise BridgeError('club_ref must be a canonical reference from fm_find_clubs.')
    if coach_name is not None and club_ref is not None:
        raise BridgeError('Select either club_ref or coach_name, not both.')
    try:
        with bridge.lock:
            process = bridge._current(session_id)
            with _stream(bridge, process):
                tables = bridge._player_layout(process)
                plugin = deepcopy(bridge.plugin_identity)
                base = tables[0] - players.RVA[0]
                snapshot, loaded, identity = bridge._world_state(process, tables)
                save, identity = deepcopy(loaded), deepcopy(identity)
                if bridge.world_identity != identity:
                    raise ValueError('Debt-obligation initial save identity differs')
                club, selection = _selected(bridge, snapshot, base, save, tables, coach_name, club_ref)
                report = retained_transfer_debt.decode(snapshot, base, club)
                if bridge._current(session_id) != process:
                    raise ValueError('Debt-obligation process lifetime changed')
                after_tables = bridge._player_layout(process)
                if after_tables != tables or bridge.plugin_identity != plugin:
                    raise ValueError('Debt-obligation loaded plugin/build changed')
                final_context, after_save, after_identity = bridge._world_state(process, after_tables)
                if after_identity != identity or after_save != save or bridge.world_identity != identity:
                    raise ValueError('Debt-obligation save/date context changed')
                after_club, after_selection = _selected(
                    bridge, final_context, base, after_save, after_tables, coach_name, club_ref)
                if after_club != club or after_selection != selection:
                    raise ValueError('Debt-obligation selected club/coach binding changed')
                totals = schedule_totals(report)
                public_save = bridge._public_save(save)
                if bridge._current(session_id) != process:
                    raise ValueError('Debt-obligation final process lifetime changed')
                snapshot.verify()
                final_context.verify()
                if bridge.plugin_identity != plugin or bridge.world_identity != identity:
                    raise ValueError('Debt-obligation final source binding changed')
                return {'session_id': session_id, 'observed_at': datetime.now(timezone.utc).isoformat(),
                        'save': public_save, 'club': report['selected_club'],
                        'transfer_debt_obligations': report, 'schedule_totals': totals, 'save_identity': 'native_binding_rechecked',
                        'atomic': False, 'native_calls': False, 'saved_file_fallback': False,
                        'limitations': retained_transfer_debt.LIMITATIONS}
    except (ValueError, IndexError, KeyError, TypeError, BridgeError) as exc:
        raise BridgeError(f'Club transfer debt-obligation query rejected; no partial result returned: {exc}') from exc
