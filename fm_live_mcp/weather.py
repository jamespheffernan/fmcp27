"""Stored WEATHER profiles; no forecast, date selection or weather simulation."""
import struct

from . import geography

SCOPE = ('Stored weather profiles with four periods in native order. Start-day integers retain their native '
         'calendar encoding; season names and date conversion remain unverified. Category labels come from '
         'the installed editor. Temperature labels are editor categories, not verified runtime generation '
         'intervals. Weights retain signed stored values and totals without normalization. Day/night variance '
         '100 means unspecified; other values retain an unverified physical unit. No current weather, '
         'forecast, effective city/region fallback or match conditions are inferred. References bind identity '
         'and canonical membership; ordinary fields refresh. Reads are non-atomic with consumed-byte rechecks.')

CATEGORIES = {
    'wind': ('Calm', 'Breezy', 'Gusty', 'Strong', 'Gale'),
    'precipitation': ('Dry', 'Wet', 'Drizzle', 'Shower', 'Down Pour'),
    'temperature': ('Extremely Freezing (-16 Celsius and below)',
                    'Very Freezing (-15 to -8 Celsius)', 'Freezing (-7 to 0 Celsius)',
                    'Cold (1 to 6 Celsius)', 'Mild (7 to 13 Celsius)',
                    'Fine (14 to 21 Celsius)', 'Warm (22 to 28 Celsius)',
                    'Hot (29 to 34 Celsius)', 'Very Hot (35 to 42 Celsius)',
                    'Extremely Hot (43 Celsius and above)'),
}


def record(read, base, address, *, include_details=False):
    binding = geography.identity(read, base, address, 'weather')
    row = {**geography.record(read, base, address, 'weather'), 'kind': 'weather'}
    if include_details:
        periods = []
        for index in range(4):
            raw = read(address + 0x20 + index * 0x18, 0x17)
            start_day, *values = struct.unpack('<h21b', raw)
            variance = values[20]
            period = {'native_index': index,
                      'start_day': {'native_value': start_day,
                                    'state': 'calendar_encoding_unverified' if 0 <= start_day <= 365 else 'out_of_range'},
                      'day_night_variance': {'native_value': variance, 'value': None if variance == 100 else variance,
                                             'unit': None,
                                             'state': 'not_specified' if variance == 100 else 'unit_unverified'}}
            for kind, offset in (('wind', 0), ('precipitation', 5), ('temperature', 10)):
                weights = values[offset:offset + len(CATEGORIES[kind])]
                period[kind] = {'label_source': 'installed_editor', 'native_weight_total': sum(weights),
                                'categories': [{'native_index': i, 'label': label, 'native_weight': weight,
                                                'state': 'stored' if 0 <= weight <= 100 else 'out_of_range'}
                                               for i, (label, weight) in enumerate(zip(CATEGORIES[kind], weights, strict=True))]}
            periods.append(period)
        row.update(periods=periods, period_count=4, complete_native_periods=True)
    return row, binding
