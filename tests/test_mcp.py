import asyncio
from pathlib import Path
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


def test_stdio_contract_and_error_propagation():
    async def check():
        root = Path(__file__).resolve().parents[1]
        params = StdioServerParameters(command=sys.executable, args=["-m", "fm_live_mcp.server"], cwd=str(root))
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as client:
                await client.initialize()
                tools = (await client.list_tools()).tools
                assert {t.name for t in tools} == {"fm_enhance_goal", "fm_enhance_status", "fm_native_read", "fm_native_schema", "fm_get_match", "fm_coverage", "fm_db_query", "fm_db_read", "fm_db_refresh", "fm_db_schema", "fm_get_calendar", "fm_get_club_vision", "fm_get_inbox", "fm_get_player_status", "fm_get_manager_visible_attributes", "fm_get_saved_player_health", "fm_get_fixture_player_checks", "fm_query_saved_people_by_name", "fm_get_retained_cross_events", "fm_get_club_committed_wage_spending", "fm_report_retained_lateral_width_by_period", "fm_get_club_stadium_rent", "fm_get_player_international_duty", "fm_report_retained_possession_by_period", "fm_get_league_player_statistics", "fm_rank_league_players", "fm_get_saved_club_starting_finances", "fm_get_managed_player_instructions", "fm_get_retained_possession_events", "fm_record_current_match", "fm_compare_retained_player_width", "fm_get_current_match_pass_events", "fm_report_retained_pass_network_by_period", "fm_list_observed_match_runs", "fm_query_observed_match_run", "fm_report_retained_match_periods", "fm_get_current_match_frame", "fm_report_retained_goal_suppliers", "fm_get_current_match_player_physical", "fm_get_retained_key_pass_annotations", "fm_query_transfer_offers", "fm_get_current_match_shot_origins", "fm_get_current_match_pass_network", "fm_get_retained_pass_events", "fm_get_current_match_spatial", "fm_get_retained_match_spatial", "fm_get_current_match", "fm_get_player_playing_time", "fm_find_awards", "fm_get_award", "fm_find_national_teams", "fm_get_club_facilities", "fm_report_simultaneous_bench_cover", "fm_get_current_player_cup_history", "fm_list_retained_match_data", "fm_report_live_pass_network", "fm_report_retained_shot_quality", "fm_get_retained_shot_map", "fm_compare_live_match_windows", "fm_get_managed_penalty_takers", "fm_get_live_match_rank_metrics", "fm_rank_live_match_players", "fm_report_live_player_pair_overlap", "fm_report_live_match_crossing", "fm_list_captured_match_sources", "fm_query_captured_match_data", "fm_report_captured_match_crossing", "fm_get_match_data_columns", "fm_query_match_scope", "fm_query_match_data", "fm_get_player_injury_status", "fm_get_managed_league_age_exemptions", "fm_get_player_match_form", "fm_get_league_scorers", "fm_get_fixture_rules", "fm_get_player_injury_return_estimates", "fm_get_managed_tactical_assignments", "fm_get_managed_in_possession_positions", "fm_get_next_match_squad", "fm_get_managed_team_sheet", "fm_get_saved_staff_history", "fm_find_saved_transfer_offers", "fm_get_saved_match_player_statistics", "fm_list_saved_match_event_streams", "fm_get_saved_match_passes", "fm_get_saved_match_crosses", "fm_get_saved_match_shots", "fm_status", "fm_get_saved_competition_history", "fm_get_saved_component_slice", "fm_get_saved_history_inventory", "fm_compare_saved_current_player_statistics", "fm_get_saved_player_starting_history", "fm_get_saved_player_injury_history", "fm_get_saved_player_statistics_history", "fm_find_saved_fixture_results", "fm_get_saved_league_table", "fm_compare_saved_player_form", "fm_list_saved_careers", "fm_find_saved_clubs", "fm_get_saved_club_squads", "fm_get_saved_person_name_candidates", "fm_get_saved_person_records", "fm_find_saved_players", "fm_find_saved_people", "fm_get_saved_player_form", "fm_get_saved_player_profiles", "fm_find_saved_teams", "fm_find_saved_competitions", "fm_find_saved_currencies", "fm_get_saved_career", "fm_attach", "fm_search_text", "fm_read_anchor", "fm_detach", "fm_find_players", "fm_get_player", "fm_get_current_player_statistics", "fm_get_player_statistics_history", "fm_compare_team_league_performance", "fm_get_save", "fm_get_managed_tactics", "fm_get_managed_training", "fm_get_player_morale", "fm_get_player_concern_history", "fm_get_managed_player_contract_expiry", "fm_get_player_individual_training", "fm_get_managed_shortlists", "fm_get_player_assessments", "fm_get_player_bans", "fm_get_managed_squad", "fm_get_club_squads", "fm_get_club_finances", "fm_check_transfer_budget", "fm_check_wage_budget", "fm_get_wage_contributions", "fm_get_contract_terms", "fm_get_contract_wage_steps", "fm_get_loan_contract", "fm_get_team_squad", "fm_query_team_players", "fm_get_database_catalog", "fm_find_save_players", "fm_query_save_players", "fm_find_clubs", "fm_find_staff", "fm_get_staff", "fm_get_club_staff", "fm_query_club_staff", "fm_query_club_staff_contracts", "fm_query_club_staff_wages", "fm_find_competitions", "fm_get_competition", "fm_get_competition_teams", "fm_get_competition_registrations", "fm_get_competition_stages", "fm_get_standings", "fm_get_fixture_coverage", "fm_find_fixtures", "fm_get_fixture", "fm_find_stadiums", "fm_get_stadium", "fm_find_cities", "fm_get_city", "fm_find_media_sources", "fm_get_media_source", "fm_find_languages", "fm_get_language", "fm_find_local_regions", "fm_get_local_region", "fm_find_weather_profiles", "fm_get_weather_profile", "fm_find_stadium_changes", "fm_get_stadium_change", "fm_find_currencies", "fm_get_currency", "fm_convert_currency", "fm_get_club_debt_obligations", "fm_get_club_transfer_debt_obligations", "fm_get_club_staff_responsibilities", "fm_get_club_transfer_payment_schedule", "fm_get_club_contingent_transfer_clauses", "fm_get_club_sell_on_transfer_clauses", "fm_get_club_current_staff_responsibilities", "fm_get_player_ucl_registration", "fm_ui_schema", "fm_ui_read", "fm_get_board_confidence", "fm_get_scouting", "fm_get_transfer_activity", "fm_get_squad_dynamics", "fm_get_training_schedule", "fm_get_medical_centre", "fm_get_finance_projections", "fm_get_youth_intake", "fm_get_manager_profile", "fm_get_league_table", "fm_get_season_expectations", "fm_get_club_vision_progress", "fm_ui_frontend", "fm_get_squad_happiness", "fm_get_ui_screen"}
                assert len(tools) == 202
                ban_tool = next(t for t in tools if t.name == 'fm_get_player_bans')
                assert ban_tool.annotations.readOnlyHint is True
                assert ban_tool.annotations.destructiveHint is False
                assert set(ban_tool.inputSchema['required']) == {'session_id', 'player_refs'}
                assert set(ban_tool.inputSchema['properties']) == {'session_id', 'player_refs', 'fixture_ref'}
                assert ban_tool.inputSchema['properties']['fixture_ref']['default'] is None
                for invalid in (True, 1, [], {}):
                    error = await client.call_tool(ban_tool.name,
                        {'session_id': 'invalid', 'player_refs': ['invalid'], 'fixture_ref': invalid})
                    assert error.isError
                    assert 'validation error' in ' '.join(getattr(item, 'text', '') for item in error.content).lower()
                form_tool = next(t for t in tools if t.name == 'fm_get_player_match_form')
                assert form_tool.annotations.readOnlyHint is True
                assert form_tool.annotations.destructiveHint is False
                assert set(form_tool.inputSchema['required']) == {'session_id', 'player_ref'}
                assert set(form_tool.inputSchema['properties']) == {'session_id', 'player_ref', 'team_ref', 'mode', 'limit'}
                for options in ({'limit':True},{'limit':0},{'limit':61},{'mode':'all'}):
                    assert (await client.call_tool(form_tool.name, {'session_id':'invalid', 'player_ref':'invalid', **options})).isError
                rules_tool = next(t for t in tools if t.name == 'fm_get_fixture_rules')
                assert rules_tool.annotations.readOnlyHint is True
                assert rules_tool.annotations.destructiveHint is False
                assert set(rules_tool.inputSchema['required']) == {'session_id', 'fixture_ref'}
                assert set(rules_tool.inputSchema['properties']) == {'session_id', 'fixture_ref'}
                assert (await client.call_tool('fm_get_fixture_rules', {'session_id': 'invalid', 'fixture_ref': 'invalid'})).isError
                starting_tool = next(t for t in tools if t.name == 'fm_get_saved_player_starting_history')
                assert starting_tool.annotations.readOnlyHint is True
                assert starting_tool.annotations.destructiveHint is False
                starting_schema = starting_tool.inputSchema
                assert set(starting_schema['required']) == {'filename', 'person_index', 'expected_snapshot_id'}
                assert set(starting_schema['properties']) == {'filename', 'person_index', 'expected_snapshot_id', 'years', 'offset', 'limit', 'include_names'}
                assert starting_schema['properties']['include_names']['default'] is False
                assert starting_schema['properties']['include_names']['type'] == 'boolean'
                assert starting_schema['properties']['limit']['maximum'] == 200
                assert starting_schema['properties']['person_index']['exclusiveMaximum'] == 2**31
                for invalid in ({'person_index': True}, {'person_index': -1}, {'years': []},
                                {'years': [True]}, {'years': [32768]}, {'offset': True}, {'limit': 201},
                                {'include_names': 1}, {'include_names': 'true'}, {'include_names': None}):
                    rejected = await client.call_tool('fm_get_saved_player_starting_history',
                        {'filename': 'missing.fm', 'person_index': 0, 'expected_snapshot_id': 'a'*64, **invalid})
                    assert rejected.isError
                    assert 'validation error' in ' '.join(getattr(item, 'text', '') for item in rejected.content).lower()
                injury_tool = next(t for t in tools if t.name == 'fm_get_saved_player_injury_history')
                injury_schema = injury_tool.inputSchema
                assert injury_tool.annotations.readOnlyHint is True
                assert injury_tool.annotations.destructiveHint is False
                assert set(injury_schema['required']) == {'filename', 'person_index', 'expected_snapshot_id'}
                assert set(injury_schema['properties']) == {'filename', 'person_index', 'expected_snapshot_id', 'date_from', 'date_to', 'injury_native_ids', 'offset', 'limit', 'include_installed_names'}
                assert injury_schema['properties']['include_installed_names']['default'] is False
                assert injury_schema['properties']['include_installed_names']['type'] == 'boolean'
                for extra in ({'include_installed_names': 1}, {'include_installed_names': 'true'},
                              {'include_installed_names': None}):
                    rejected = await client.call_tool('fm_get_saved_player_injury_history',
                        {'filename': 'missing.fm', 'person_index': 0, 'expected_snapshot_id': 'a'*64, **extra})
                    assert rejected.isError
                    assert 'validation error' in ' '.join(getattr(item, 'text', '') for item in rejected.content).lower()
                league_tool = next(t for t in tools if t.name == 'fm_get_saved_league_table')
                assert league_tool.annotations.readOnlyHint is True
                assert league_tool.annotations.destructiveHint is False
                league_schema = league_tool.inputSchema
                assert set(league_schema['required']) == {'filename', 'competition_index', 'expected_snapshot_id'}
                assert set(league_schema['properties']) == {'filename', 'competition_index', 'expected_snapshot_id', 'stage_ordinal'}
                assert league_schema['properties']['competition_index']['minimum'] == 0
                assert league_schema['properties']['competition_index']['exclusiveMaximum'] == 2**31
                assert league_schema['properties']['stage_ordinal']['default'] == 0
                assert league_schema['properties']['stage_ordinal']['minimum'] == 0
                assert league_schema['properties']['stage_ordinal']['exclusiveMaximum'] == 1024
                for invalid in ({'competition_index': True}, {'competition_index': -1},
                                {'competition_index': 2**31}, {'stage_ordinal': True},
                                {'stage_ordinal': -1}, {'stage_ordinal': 1024}):
                    rejected = await client.call_tool('fm_get_saved_league_table',
                        {'filename': 'missing.fm', 'expected_snapshot_id': 'invalid',
                         'competition_index': 0, **invalid})
                    assert rejected.isError
                    assert 'validation error' in ' '.join(getattr(item, 'text', '') for item in rejected.content).lower()
                history_tool = next(t for t in tools if t.name == 'fm_get_saved_player_statistics_history')
                history_schema = history_tool.inputSchema
                assert set(history_schema['required']) == {'filename', 'person_index', 'expected_snapshot_id'}
                assert history_schema['properties']['person_index']['minimum'] == 0
                assert history_schema['properties']['limit']['maximum'] == 200
                assert history_tool.annotations.readOnlyHint and history_tool.annotations.destructiveHint is False
                for extra in ({'years': []}, {'category_codes': []}, {'years': [True]}, {'person_index': True}):
                    args = {'filename': 'missing.fm', 'person_index': 0, 'expected_snapshot_id': 'pin', **extra}
                    assert (await client.call_tool(history_tool.name, args)).isError
                scouting_tool = next(t for t in tools if t.name == 'fm_find_saved_players')
                assert scouting_tool.annotations.readOnlyHint is True
                assert scouting_tool.annotations.destructiveHint is False
                scouting = scouting_tool.inputSchema
                assert set(scouting['required']) == {'filename', 'expected_snapshot_id'}
                assert set(scouting['properties']) == {'filename', 'expected_snapshot_id', 'criteria', 'min_age', 'max_age', 'cursor', 'limit', 'scan_limit'}
                assert scouting['properties']['limit']['default'] == 20
                assert scouting['properties']['limit']['minimum'] == 1
                assert scouting['properties']['limit']['maximum'] == 50
                assert scouting['properties']['scan_limit']['default'] == 10000
                assert scouting['properties']['scan_limit']['minimum'] == 1
                assert scouting['properties']['scan_limit']['maximum'] == 10000
                for key in ('min_age', 'max_age'):
                    assert scouting['properties'][key]['default'] is None
                    age_schema = next(v for v in scouting['properties'][key]['anyOf'] if v.get('type') == 'integer')
                    assert age_schema['minimum'] == 0 and age_schema['maximum'] == 150
                for invalid in ({'min_age': True}, {'max_age': '23'}, {'limit': True},
                                {'scan_limit': True}, {'scan_limit': 10001}, {'limit': 51},
                                {'criteria': {'attributes.finishing': {'min': True}}}):
                    error = await client.call_tool('fm_find_saved_players',
                        {'filename': 'missing.fm', 'expected_snapshot_id': 'invalid', **invalid})
                    assert error.isError
                    assert 'validation error' in ' '.join(getattr(item, 'text', '') for item in error.content).lower()
                fixture_tool = next(t for t in tools if t.name == 'fm_find_saved_fixture_results')
                assert fixture_tool.annotations.readOnlyHint is True
                assert fixture_tool.annotations.destructiveHint is False
                fs = fixture_tool.inputSchema
                assert set(fs['required']) == {'filename', 'team_index', 'date_from', 'date_to', 'expected_snapshot_id'}
                assert fs['properties']['limit']['maximum'] == 500
                assert fs['properties']['include_competition']['default'] is False
                assert fs['properties']['include_historical']['default'] is False
                for invalid in ({'team_index': True}, {'team_index': -1}, {'limit': 501}, {'offset': True},
                                {'include_historical': 1}, {'include_competition': 'true'}):
                    rejected = await client.call_tool('fm_find_saved_fixture_results',
                        {'filename': 'missing.fm', 'team_index': 7, 'date_from': '2030-01-01',
                         'date_to': '2030-01-01', 'expected_snapshot_id': 'a'*64, **invalid})
                    assert rejected.isError
                    assert 'validation error' in ' '.join(getattr(item, 'text', '') for item in rejected.content).lower()
                population_tool = next(t for t in tools if t.name == 'fm_get_saved_person_records')
                assert population_tool.annotations.readOnlyHint is True
                assert population_tool.annotations.destructiveHint is False
                population_schema = population_tool.inputSchema
                assert set(population_schema['required']) == {'filename', 'expected_snapshot_id'}
                assert set(population_schema['properties']) == {'filename', 'expected_snapshot_id', 'person_indices', 'offset', 'limit'}
                indices = population_schema['properties']['person_indices']
                assert indices['default'] is None
                array_schema = next(value for value in indices['anyOf'] if value.get('type') == 'array')
                assert array_schema['minItems'] == 1 and array_schema['maxItems'] == 32
                assert array_schema['items']['type'] == 'integer'
                assert array_schema['items']['minimum'] == 0
                assert array_schema['items']['exclusiveMaximum'] == 2**31
                assert population_schema['properties']['offset']['default'] == 0
                assert population_schema['properties']['offset']['minimum'] == 0
                assert population_schema['properties']['offset']['exclusiveMaximum'] == 2**31
                assert population_schema['properties']['limit']['default'] == 20
                assert population_schema['properties']['limit']['minimum'] == 1
                assert population_schema['properties']['limit']['maximum'] == 32
                for invalid in ({'person_indices': [True]}, {'person_indices': ['1']},
                                {'person_indices': []}, {'person_indices': [0] * 33},
                                {'person_indices': [-1]}, {'person_indices': [2**31]},
                                {'offset': True}, {'offset': -1}, {'offset': 2**31},
                                {'limit': True}, {'limit': 0}, {'limit': 33}):
                    rejected = await client.call_tool('fm_get_saved_person_records',
                        {'filename': 'missing.fm', 'expected_snapshot_id': 'invalid', **invalid})
                    assert rejected.isError
                    errors = ' '.join(getattr(item, 'text', '') for item in rejected.content)
                    assert 'validation error' in errors.lower()
                comparison_schema = next(t.inputSchema for t in tools if t.name == 'fm_compare_saved_player_form')
                assert set(comparison_schema['required']) == {'filename', 'person_indices', 'expected_snapshot_id', 'team_index', 'date_from', 'date_to', 'minimum_observed_minutes'}
                assert 'session_id' not in comparison_schema['properties']
                assert comparison_schema['properties']['person_indices']['minItems'] == 1
                assert comparison_schema['properties']['person_indices']['maxItems'] == 32
                assert comparison_schema['properties']['team_index']['minimum'] == 0
                assert comparison_schema['properties']['team_index']['maximum'] == 2**32 - 2
                assert comparison_schema['properties']['person_indices']['items']['minimum'] == 0
                assert comparison_schema['properties']['person_indices']['items']['exclusiveMaximum'] == 2**31
                assert comparison_schema['properties']['minimum_observed_minutes']['exclusiveMinimum'] == 0
                assert comparison_schema['properties']['competition_index']['default'] is None
                name_schema = next(t.inputSchema for t in tools if t.name == 'fm_find_saved_people')
                assert set(name_schema['required']) == {'filename', 'expected_snapshot_id'}
                assert 'session_id' not in name_schema['properties']
                for part in ('first_name', 'surname', 'common_name'):
                    field = name_schema['properties'][part]
                    assert field['default'] is None
                    string = next(v for v in field['anyOf'] if v.get('type') == 'string')
                    assert string['minLength'] == 1 and string['maxLength'] == 256
                assert name_schema['properties']['match_mode']['default'] == 'exact'
                assert set(name_schema['properties']['match_mode']['enum']) == {'exact', 'prefix', 'substring'}
                assert name_schema['properties']['offset']['default'] == 0
                assert name_schema['properties']['offset']['minimum'] == 0
                assert name_schema['properties']['limit']['default'] == 20
                assert name_schema['properties']['limit']['minimum'] == 1
                assert name_schema['properties']['limit']['maximum'] == 50
                form_schema = next(t.inputSchema for t in tools if t.name == 'fm_get_saved_player_form')
                assert set(form_schema['required']) == {'filename', 'person_index', 'expected_snapshot_id'}
                assert form_schema['properties']['person_index']['minimum'] == 0
                assert form_schema['properties']['person_index']['exclusiveMaximum'] == 2**31
                assert form_schema['properties']['offset']['default'] == 0
                assert form_schema['properties']['offset']['minimum'] == 0
                assert form_schema['properties']['limit']['default'] == 50
                assert form_schema['properties']['limit']['minimum'] == 1
                assert form_schema['properties']['limit']['maximum'] == 500
                profile_schema = next(t.inputSchema for t in tools if t.name == 'fm_get_saved_player_profiles')
                assert set(profile_schema['required']) == {'filename', 'person_indices', 'expected_snapshot_id'}
                assert profile_schema['properties']['person_indices']['minItems'] == 1
                assert profile_schema['properties']['person_indices']['maxItems'] == 32
                assert profile_schema['properties']['person_indices']['items']['minimum'] == 0
                assert profile_schema['properties']['person_indices']['items']['exclusiveMaximum'] == 2**31
                assert profile_schema['properties']['include_current_contract']['default'] is False
                assert profile_schema['properties']['include_current_contract']['type'] == 'boolean'
                assert profile_schema['properties']['fields']['default'] is None
                competition_schema = next(t.inputSchema for t in tools if t.name == 'fm_find_saved_competitions')
                assert competition_schema['properties']['include_saved_state']['default'] is False
                assert competition_schema['properties']['include_saved_state']['type'] == 'boolean'
                period_width = next(t for t in tools if t.name == 'fm_report_retained_lateral_width_by_period')
                assert period_width.outputSchema and period_width.annotations.readOnlyHint is True
                assert period_width.annotations.destructiveHint is period_width.annotations.openWorldHint is False
                assert set(period_width.inputSchema['properties']) == set(period_width.inputSchema['required']) == {'session_id', 'fixture_ref', 'team_native_id'}
                assert period_width.inputSchema['properties']['fixture_ref']['minLength'] == 1
                assert period_width.inputSchema['properties']['fixture_ref']['maxLength'] == 128
                assert period_width.inputSchema['properties']['team_native_id']['exclusiveMinimum'] == 0
                assert 'Reads existing host observations only' in period_width.description
                host_writers = {
                    'fm_record_current_match', 'fm_get_current_match',
                    'fm_get_current_match_shot_origins', 'fm_report_retained_match_periods',
                    'fm_report_retained_pass_network_by_period',
                    'fm_report_retained_possession_by_period',
                    'fm_enhance_goal',          # writes image files on the host; reads the game only
                }
                game_writers = set()            # the reader registers no edit tool (fm_live_write does, when loaded)
                writers = host_writers | game_writers
                assert {t.name for t in tools if t.annotations.readOnlyHint is False} == writers
                assert all(t.annotations.readOnlyHint is (t.name not in writers) for t in tools)
                assert all(t.annotations.destructiveHint is (t.name in game_writers) for t in tools)
                for name, reference in (('fm_get_current_player_statistics', 'player_ref'), ('fm_get_player_statistics_history', 'player_ref'), ('fm_get_competition_stages', 'competition_ref'),
                                        ('fm_get_standings', 'stage_ref'), ('fm_get_fixture', 'fixture_ref'), ('fm_get_stadium', 'stadium_ref'), ('fm_get_city', 'city_ref'), ('fm_get_language', 'language_ref'), ('fm_get_local_region', 'local_region_ref'), ('fm_get_weather_profile', 'weather_ref'), ('fm_get_stadium_change', 'stadium_change_ref'), ('fm_get_currency', 'currency_ref')):
                    schema = next(t.inputSchema for t in tools if t.name == name)
                    assert set(schema['required']) == {'session_id', reference}
                    assert schema['properties'][reference]['type'] == 'string'
                for tool in tools:
                    if tool.name in {'fm_find_fixtures', 'fm_get_fixture'}:
                        assert tool.inputSchema['properties']['include_stage']['default'] is False
                        assert tool.inputSchema['properties']['include_stage']['type'] == 'boolean'
                    if tool.name in {'fm_get_player', 'fm_get_managed_squad', 'fm_get_team_squad'}:
                        assert tool.inputSchema['properties']['include_clubs']['default'] is False
                        assert tool.inputSchema['properties']['include_profile']['default'] is False
                for tool in tools:
                    if tool.name in {'fm_get_staff', 'fm_get_club_staff'}:
                        assert tool.inputSchema['properties']['include_attributes']['default'] is False
                        assert tool.inputSchema['properties']['include_job']['default'] is False
                for tool in tools:
                    if tool.name in {'fm_get_player', 'fm_get_staff', 'fm_get_club_staff'}:
                        assert tool.inputSchema['properties']['include_wage']['default'] is False
                        assert tool.inputSchema['properties']['include_contract_status']['default'] is False
                status = await client.call_tool("fm_status", {})
                assert not status.isError
                from fm_live_mcp import __version__
                assert status.structuredContent['server_version'] == __version__
                assert status.structuredContent["capabilities"]["memory_writes"] is False    # no write module loaded
                invalid = await client.call_tool("fm_search_text", {"session_id": "invalid", "texts": ["Wirtz"]})
                assert invalid.isError
                rejected = await client.call_tool("fm_search_text", {"session_id": "invalid", "texts": ["Wirtz"], "max_mib": 2000})
                assert rejected.isError
                for name, arguments in (("fm_get_managed_tactics", {"session_id": "invalid"}),
                                        ("fm_get_fixture", {"session_id": "invalid", "fixture_ref": "invalid"}),
                                        ("fm_get_fixture_coverage", {"session_id": "invalid"}),
                                        ("fm_find_fixtures", {"session_id": "invalid"}),
                                        ("fm_get_standings", {"session_id": "invalid", "stage_ref": "invalid"}),
                                        ("fm_get_competition_stages", {"session_id": "invalid", "competition_ref": "invalid"}),
                                        ("fm_get_competition_registrations", {"session_id": "invalid", "competition_ref": "invalid"}),
                                        ("fm_get_competition_teams", {"session_id": "invalid", "competition_ref": "invalid"}),
                                        ("fm_find_competitions", {"session_id": "invalid"}),
                                        ("fm_find_stadiums", {"session_id": "invalid"}),
                                        ("fm_find_currencies", {"session_id": "invalid"}),
                                        ("fm_get_currency", {"session_id": "invalid", "currency_ref": "invalid"}),
                                        ("fm_convert_currency", {"session_id": "invalid", "amount": "1", "from_currency_ref": "invalid", "to_currency_ref": "invalid"}),
                                        ("fm_find_stadium_changes", {"session_id": "invalid"}),
                                        ("fm_get_stadium_change", {"session_id": "invalid", "stadium_change_ref": "invalid"}),
                                        ("fm_find_cities", {"session_id": "invalid"}),
                                        ("fm_get_city", {"session_id": "invalid", "city_ref": "invalid"}),
                                        ("fm_find_weather_profiles", {"session_id": "invalid"}),
                                        ("fm_get_weather_profile", {"session_id": "invalid", "weather_ref": "invalid"}),
                                        ("fm_find_media_sources", {"session_id": "invalid"}),
                                        ("fm_get_media_source", {"session_id": "invalid", "media_source_ref": "x"}),
                                        ("fm_find_languages", {"session_id": "invalid"}),
                                        ("fm_get_language", {"session_id": "invalid", "language_ref": "invalid"}),
                                        ("fm_find_local_regions", {"session_id": "invalid"}),
                                        ("fm_get_local_region", {"session_id": "invalid", "local_region_ref": "invalid"}),
                                        ("fm_get_stadium", {"session_id": "invalid", "stadium_ref": "invalid"}),
                                        ("fm_get_competition", {"session_id": "invalid", "competition_ref": "invalid"}),
                                        ("fm_find_players", {"session_id": "invalid", "name": "Wirtz"}),
                                        ("fm_find_save_players", {"session_id": "invalid", "name": "Wirtz"}),
                                        ("fm_query_save_players", {"session_id": "invalid", "name_contains": "Wirtz"}),
                                        ("fm_check_wage_budget", {"session_id": "invalid", "additional_weekly_wage_gbp": 100}),
                                        ("fm_get_database_catalog", {"session_id": "invalid"}),
                                        ("fm_get_wage_contributions", {"session_id": "invalid"}),
                                        ("fm_get_contract_terms", {"session_id": "invalid", "player_ref": "invalid"}),
                                        ("fm_get_contract_wage_steps", {"session_id": "invalid", "player_ref": "invalid"}),
                                        ("fm_get_loan_contract", {"session_id": "invalid", "player_ref": "invalid"}),
                                        ("fm_get_managed_training", {"session_id": "invalid"}),
                                        ("fm_get_player_individual_training", {"session_id": "invalid", "player_refs": ["invalid"]}),
                                        ("fm_get_managed_shortlists", {"session_id": "invalid"}),
                                        ("fm_get_player_assessments", {"session_id": "invalid", "player_refs": ["invalid"]}),
                                        ("fm_get_player_bans", {"session_id": "invalid", "player_refs": ["invalid"]}),
                                        ("fm_get_current_player_statistics", {"session_id": "invalid", "player_ref": "invalid"}),
                                        ("fm_get_player_statistics_history", {"session_id": "invalid", "player_ref": "invalid"}),
                                        ("fm_compare_team_league_performance", {"session_id": "invalid", "team_ref": "invalid"}),
                                        ("fm_get_player", {"session_id": "invalid", "player_ref": "invalid"})):
                    assert (await client.call_tool(name, arguments)).isError
    asyncio.run(check())


def test_write_module_is_loaded_only_when_named():
    """The reader registers no edit tool; FMCP_EXTENSIONS=fm_live_write adds the one that exists."""
    import os

    async def names(extensions):
        root = Path(__file__).resolve().parents[1]
        env = {**os.environ, 'FMCP_EXTENSIONS': extensions}
        params = StdioServerParameters(command=sys.executable, args=["-m", "fm_live_mcp.server"], cwd=str(root), env=env)
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as client:
                await client.initialize()
                tools = (await client.list_tools()).tools
                return {t.name: t.annotations for t in tools}

    plain = asyncio.run(names(''))
    assert 'fm_set_player_training_intensity' not in plain and len(plain) == 202
    assert not any(a.destructiveHint for a in plain.values())
    loaded = asyncio.run(names('fm_live_write'))
    assert set(loaded) - set(plain) == {'fm_set_player_training_intensity'}
    assert loaded['fm_set_player_training_intensity'].readOnlyHint is False
