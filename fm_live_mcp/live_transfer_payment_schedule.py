"""Guarded live projection of the native retained transfer payment calendar."""
from copy import deepcopy
from datetime import datetime, timezone

from . import players, transfer_payment_timing
from .bridge import BridgeError
from .live_debt_obligations import _selected, _stream
from .live_transfer_debt_obligations import schedule_totals


def payment_schedule_summary(report):
    """Summarize native call arguments without relabeling native debt totals."""
    records = report['records']
    summary = {'state': 'source_unavailable' if records is None else 'projected_native_cash_schedule',
               'as_of_native_clock': report['native_cash_timing'].get('as_of_native_clock'),
               'currency': report['currency'], 'timezone': None, 'timezone_state': 'not_established',
               'actual_payment_state': 'not_established', 'arrears_state': 'not_established',
               'complete_cash_flow': False, 'directions': {}}
    for direction in ('outgoing', 'incoming', 'self'):
        rows = [] if records is None else [r for r in records if r['direction'] == direction]
        available = [r for r in rows if r['native_cash_timing']['next_native_cash_branch'] is not None]
        complete = records is not None and len(available) == len(rows)
        first_date = min((r['native_cash_timing']['next_native_cash_branch']['date'] for r in available), default=None)
        first_rows = [r for r in available if r['native_cash_timing']['next_native_cash_branch']['date'] == first_date]
        first_values = [r['native_cash_timing']['next_native_cash_branch']['call_argument_amount'] for r in first_rows]
        remaining_values = [r['native_cash_timing']['remaining_native_cash_argument_sum'] for r in rows]
        summary['directions'][direction] = {
            'record_count': len(rows) if records is not None else None,
            'projected_record_count': len(available) if records is not None else None,
            'state': 'source_unavailable' if records is None else 'complete_projection' if complete else 'partial_projection',
            'next_projected_native_payment_date': first_date if complete else None,
            'next_projected_native_payment_time': '08:30' if complete and first_date else None,
            'next_native_call_argument_sum': sum(first_values) if complete and first_rows and all(v is not None for v in first_values) else None,
            'next_native_call_record_count': len(first_rows) if complete else None,
            'remaining_native_call_argument_sum': sum(remaining_values) if complete and all(v is not None for v in remaining_values) else None,
        }
    if records is not None and any(side['state'] == 'partial_projection' for side in summary['directions'].values()):
        summary['state'] = 'partial_native_cash_projection'
    return summary


def get_club_transfer_payment_schedule(bridge, session_id, coach_name=None, club_ref=None):
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
                    raise ValueError('Transfer-payment initial save identity differs')
                club, selection = _selected(bridge, snapshot, base, save, tables, coach_name, club_ref)
                report = transfer_payment_timing.decode(snapshot, base, club)
                if bridge._current(session_id) != process:
                    raise ValueError('Transfer-payment process lifetime changed')
                after_tables = bridge._player_layout(process)
                if after_tables != tables or bridge.plugin_identity != plugin:
                    raise ValueError('Transfer-payment loaded plugin/build changed')
                final_context, after_save, after_identity = bridge._world_state(process, after_tables)
                if after_identity != identity or after_save != save or bridge.world_identity != identity:
                    raise ValueError('Transfer-payment save/date context changed')
                after_club, after_selection = _selected(
                    bridge, final_context, base, after_save, after_tables, coach_name, club_ref)
                if after_club != club or after_selection != selection:
                    raise ValueError('Transfer-payment selected club/coach binding changed')
                totals = schedule_totals(report)
                payment_schedule = payment_schedule_summary(report)
                public_save = bridge._public_save(save)
                if bridge._current(session_id) != process:
                    raise ValueError('Transfer-payment final process lifetime changed')
                snapshot.verify()
                final_context.verify()
                if bridge.plugin_identity != plugin or bridge.world_identity != identity:
                    raise ValueError('Transfer-payment final source binding changed')
                return {'session_id': session_id, 'observed_at': datetime.now(timezone.utc).isoformat(),
                        'save': public_save, 'club': report['selected_club'],
                        'transfer_payment_schedule': report, 'native_debt_totals': totals,
                        'projected_native_payment_schedule': payment_schedule, 'save_identity': 'native_binding_rechecked',
                        'atomic': False, 'native_calls': False, 'saved_file_fallback': False,
                        'limitations': transfer_payment_timing.LIMITATIONS}
    except (ValueError, IndexError, KeyError, TypeError, BridgeError) as exc:
        raise BridgeError(f'Club transfer payment-schedule query rejected; no partial result returned: {exc}') from exc
