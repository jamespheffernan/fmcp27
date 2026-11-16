"""Named bounded fixture checks; no combined clearance or selection decision."""


def other_team_history(history):
    if history is None:
        return {'state': 'unavailable', 'reason': 'cup_history_source_unavailable',
                'applies': None, 'scope': 'native_direct_flag1_history_condition_only'}
    value = history['native_other_team_cup_history_condition']
    return {'state': 'unavailable' if value is None else 'flagged' if value else 'ruled_out',
            'reason': history['native_condition_reason'], 'applies': value,
            'scope': 'native_direct_flag1_history_condition_only',
            'historical_other_team_appearance': None,
            'historical_absence_proved': False}


def signed_after_round(activation):
    value = activation.get('enabled')
    if activation.get('state') == 'decoded_named_round_option' and value is False:
        return {'state': 'ruled_out', 'reason': 'specific_native_check_bypassed_by_clear_round_flag',
                'applies': False, 'activation': activation,
                'scope': 'fixture_selected_signed_after_round_activation_only'}
    return {'state': 'unavailable', 'reason': ('enabled_player_and_date_checks_not_evaluated'
            if value is True else activation.get('reason', 'round_activation_unavailable')),
            'applies': None, 'activation': activation,
            'scope': 'fixture_selected_signed_after_round_activation_only'}


def unavailable(reason):
    return {'state': 'unavailable', 'reason': reason, 'applies': None}
