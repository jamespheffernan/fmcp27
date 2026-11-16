"""Retained contingent source with bounded checked playing-person names."""
from copy import deepcopy

from . import contingent_transfer_appearance as clauses, finance_person_reference as people

SOURCE = clauses.SOURCE + people.SOURCE
LIMITATIONS = clauses.LIMITATIONS + (
    ' Person names use the original bounded native ID-pair search and canonical playing-person '
    'membership. Native sorting/remapping and nonplaying person types remain unresolved. '
    'No whole-person scan, sorting, remapping, profile generation or native call is performed.'
)


def decode(read, base, club):
    report = clauses.decode(read, base, club)
    if report['records'] is None:
        return report
    if not report['records']:
        report['person_binding'] = {'state': 'empty_reference_set', 'unique_reference_count': 0,
            'resolved_unique_reference_count': 0, 'whole_person_scan': False, 'native_sort_or_remap': False}
        return report
    context = people.context(read, base)
    cache = {}
    for row in report['records']:
        reference = row['native_person_reference']
        pair = reference['native_id'], reference['secondary_id_or_native_id']
        if pair not in cache:
            match = people.lookup(read, context, *pair)
            cache[pair] = people.playing_identity(read, base, context, match)
        binding = deepcopy(cache[pair])
        reference.update(name=binding.get('name'), resolution_state=binding['state'], playing_person=binding)
    report['person_binding'] = {'state': 'bounded_native_reference_search', 'index_source': context['state'],
        'unique_reference_count': len(cache), 'resolved_unique_reference_count': sum(v['state']=='canonical_playing_person' for v in cache.values()),
        'whole_person_scan': False, 'native_sort_or_remap': False}
    report['limitations'] = LIMITATIONS
    return report
