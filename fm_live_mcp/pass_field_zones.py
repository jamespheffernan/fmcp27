"""Attempt-denominated summaries of proved pass-map event locations.

Caller provides the complete counter-qualified fixture packet before pagination.
These zones locate native events, not proved ball release or causes of failure.
"""
from collections import Counter

THIRDS=('defensive','middle','attacking')
CHANNELS=('central','outer')


def _counts(attempted, completed):
    return {'attempted':attempted,'completed':completed,
            'not_completed':attempted-completed,
            'completion_rate':completed/attempted if attempted else None,
            'not_completed_rate':(attempted-completed)/attempted if attempted else None}


def aggregate_pass_zones(rows, side_coverage):
    """Summarize all rows; unknown sides/locations remain explicitly distinct."""
    if not isinstance(rows,list) or not isinstance(side_coverage,list):
        raise ValueError('Complete pass rows and side coverage required')
    coverage={}
    for side in side_coverage:
        index=side.get('side_index')
        if type(index) is not int or index not in(0,1) or index in coverage:
            raise ValueError('Invalid or duplicate pass side coverage')
        coverage[index]=side
    if set(coverage)!={0,1}:
        raise ValueError('Both pass side coverage records required')
    groups={0:[],1:[]};seen=set()
    for row in rows:
        side=row.get('side_index');event=row.get('event_id')
        if (type(side) is not int or side not in(0,1) or type(event) is not int or event<0
                or type(row.get('completed')) is not bool or event in seen):
            raise ValueError('Invalid or duplicated pass event row')
        if coverage[side].get('state')!='available':
            raise ValueError('Rows from an unavailable pass side cannot be summarized')
        seen.add(event);groups[side].append(row)
    output=[]
    for side in(0,1):
        source=coverage[side]
        if source.get('state')!='available':
            output.append({'side_index':side,'state':source.get('state','unavailable'),
                           'attempted':None,'completed':None,'not_completed':None,
                           'completion_rate':None,'not_completed_rate':None,
                           'thirds':None,'lateral_channels':None,'zones':None,
                           'unclassified_location':None})
            continue
        own=groups[side]
        expected=source.get('attempt_count')
        if type(expected) is not int or expected!=len(own):
            raise ValueError('Full pass rows do not match counter-qualified side attempt count')
        counts=Counter();done=Counter();unclassified=[];outside=0
        for row in own:
            field=row.get('field_position')
            if field is not None and not isinstance(field,dict):
                raise ValueError('Invalid pass field-position packet')
            third=(field or {}).get('analytical_pitch_third')
            channel=(field or {}).get('analytical_lateral_channel')
            if (field or {}).get('inside_native_pitch_extents') is not True or third not in THIRDS or channel not in CHANNELS:
                unclassified.append(row)
                outside+=int((field or {}).get('inside_native_pitch_extents') is False)
                continue
            counts[third,channel]+=1;done[third,channel]+=int(row['completed'])
        zones=[{'pitch_third':t,'lateral_channel':c,**_counts(counts[t,c],done[t,c])}
               for t in THIRDS for c in CHANNELS]
        thirds=[{'pitch_third':t,**_counts(sum(counts[t,c] for c in CHANNELS),sum(done[t,c] for c in CHANNELS))} for t in THIRDS]
        channels=[{'lateral_channel':c,**_counts(sum(counts[t,c] for t in THIRDS),sum(done[t,c] for t in THIRDS))} for c in CHANNELS]
        output.append({'side_index':side,'state':'available',**_counts(len(own),sum(r['completed'] for r in own)),
            'classified_location_count':len(own)-len(unclassified),
            'outside_pitch_extents_count':outside,
            'unavailable_location_count':len(unclassified)-outside,
            'thirds':thirds,'lateral_channels':channels,'zones':zones,
            'unclassified_location':_counts(len(unclassified),sum(r['completed'] for r in unclassified))})
    return {'source_scope':'complete_fixture_counter_qualified_pass_attempts_before_pagination',
            'location_semantics':'official_pass_map_event_location; pass_origin_proved',
            'binning_policy':'equal_length_thirds_and_central_width_third_versus_outer_width_thirds',
            'rate_denominator':'all attempted passes in the same side and zone; zero-attempt rates are null',
            'sides':output,
            'limits':['Not-completed passes are not a proved total of possession losses.',
                      'Zones do not establish pressure, failure cause, intended destination or tactical effectiveness.',
                      'Human left/right and physical coordinate units remain unproved.']}
