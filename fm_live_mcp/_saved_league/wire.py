"""Portable COMP-to-C0 traversal; a C0 prefix never impersonates a full stage."""
from functools import partial
from .errors import UnsupportedLayout
from . import adapter, comp5b0, league, row, settings, stages

REFERENCE_PROFILE = dict(stream_bit1=True, global_3522=0, global_3523=1, global_2c98=1)
PROFILE_SCOPE = {
    'reference_context': REFERENCE_PROFILE,
    'extended_stats_factory_56D497A': 'conditional_equals1',
    'native_runtime_selectors_observed': False,
    'wire_profile_is_conditional': True,
    'native_loader_acceptance': False,
}


def decode(data, stage_ordinal):
    """Locate the requested stage by forward framing and consume its first C0 table."""
    try:
        before = stages.parse(data, reference_context=REFERENCE_PROFILE,
                              child_readers={0x3be2048: adapter.make_reader(),
                                             0x3bdf670: comp5b0.parse})
        entries = before.get('stage_entries', [])
        selected = next((e for e in entries if e['native_slot_index'] == stage_ordinal), None)
        base = dict(state='stopped', stage_count=before.get('stage_count'),
                    stage_ordinal=stage_ordinal, stage_kind=None,
                    consumed_end=before['end'], next_native_reader=before.get('next_native_reader'),
                    reason=before.get('stop_reason'), native_season_code=before['prefix']['native_season_code'])
        if before.get('stage_count') is not None and stage_ordinal >= before['stage_count']:
            return {**base, 'state': 'stage_absent', 'reason': 'Requested original stage ordinal is outside the stored vector'}
        if selected is None:
            return {**base, 'reason': 'Traversal stopped before the requested stage; preceding bodies cannot be skipped'}
        base['stage_kind'] = selected['kind_code']
        if selected['kind_code'] == 7:
            return {**base, 'state': 'stage_absent', 'reason': 'Stored null stage slot'}
        if selected['kind_code'] != 1:
            return {**base, 'state': 'unsupported_stage', 'reason': 'Requested stage is outside the ordinary league-stage reader'}
        table = league.parse_prefix(data, selected['body_start'], child_readers={
            0x3ef0568: settings.parse,
            0x3f4ebec: partial(row.parse, reference_context=REFERENCE_PROFILE),
        })
        base.update(consumed_end=table['end'], next_native_reader=table.get('next_native_reader'),
                    reason=table.get('stop_reason'), stage_body_start=selected['body_start'])
        if table.get('next_native_reader') != '0x3eefa74' or len(table.get('rows', [])) != table.get('row_count'):
            return base
        return {**base, 'state': 'decoded', 'table': table,
                'reason': 'Complete stored C0 table; remaining stage and competition suffixes unparsed'}
    except UnsupportedLayout as error:
        return dict(state='unsupported_layout', stage_ordinal=stage_ordinal,
                    stage_count=None, stage_kind=None, consumed_end=None,
                    next_native_reader=None, reason=str(error),
                    native_season_code=int.from_bytes(data[20:22], 'little'))
    except ValueError as error:
        # Only explicit native-child frontiers become stopped results. Malformed
        # framing, bounds, count budgets and unknown generic failures propagate.
        native = getattr(error, 'native', None)
        offset = getattr(error, 'offset', None)
        if native is None or type(offset) is not int:
            raise
        return dict(state='stopped', stage_ordinal=stage_ordinal, stage_count=None,
                    stage_kind=None, consumed_end=offset,
                    next_native_reader=hex(native) if type(native) is int else native,
                    reason=str(error), native_season_code=int.from_bytes(data[20:22], 'little'))
