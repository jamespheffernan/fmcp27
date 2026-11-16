"""Local stdio MCP with read queries and one explicit training selection edit."""

from typing import Annotated, Any, Literal

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations
from pydantic import Field

from .bridge import Bridge
from . import address_book as _address_book
from . import saved_transfer_offers
from . import saved_player_history, saved_player_injury_history, saved_starting_career, saved_player_health, saved_staff_history
from . import saved_population, saved_scouting_query, saved_fixture_query, saved_current_statistics
from . import saved_starting_finances, saved_history_inventory, saved_component_slice, saved_competition_history, saved_match_statistics, saved_match_events, saved_canonical_person_names
from . import saved_club_search, saved_person_search, saved_person_name_search, saved_player_form_query, saved_form_comparison, saved_league_tables, saved_player_profile_query, saved_squad_search, saved_team_search, saved_world_search, snapshot_catalog


from .match_data_query import MatchDataQueries

bridge = Bridge()
_address_book.apply_withheld(bridge)
match_data_queries = MatchDataQueries()
from .match_scope_query import ScopedMatchQueries, column_catalog
from .captured_match_tools import register_captured_match_tools
from .captured_crossing_tools import register_captured_crossing_tools
match_scope_queries = ScopedMatchQueries()
mcp = FastMCP(
    "Football Manager Live", log_level="WARNING",
    instructions=("macOS live-memory bridge for FM26/FM27. Every tool of the reader is read-only against the game; edits exist only in a separate write module that is not loaded unless FMCP_EXTENSIONS names it. "
                  "Use fm_get_player_injury_status without player_refs to check the current picked XI and bench in one pass; null means unsupported, not uninjured. "
                  "Use fm_get_league_scorers with an exact competition_ref for live domestic league goals leaders and complete cutoff ties. "
                  "For a requested historical observed native run, including a just-finished match before a retained RESULT or disk save exists, use fm_list_observed_match_runs then fm_query_observed_match_run with its exact source/capture pins; require the requested fixture and keep terminal shots, completed passing and earlier spatial-prefix scopes separate. This product is neither the current runtime nor a retained/disk save, and must not substitute for a current-state question. When FM is unavailable or at its menu, use fm_list_captured_match_sources then fm_query_captured_match_data for explicitly named historical live-capture exports independent of attachment; distinguish captured save date from fixture coverage and the last disk save. For historical captured crossing reports, discover a source with fm_list_captured_match_sources then call fm_report_captured_match_crossing with its exact hash pin; current career and current squad questions still require live sources. For fresh active-career crossing scouting use fm_report_live_match_crossing with explicit dates and a live fixture_ref anchor; it never falls back to exported files. For a team chance-creation comparison across two explicit periods use fm_compare_live_match_windows; it returns compact team rates and returning-player rate changes from a shared live capture. For league/team player action leaderboards use fm_rank_live_match_players with explicit dates and minimum minutes; fm_get_live_match_rank_metrics discovers the bounded metric catalog without a capture. For assigned penalty order use fm_get_managed_penalty_takers, and compare with the independently read editable team sheet; pending taker edits and final match takers remain unestablished. Use fm_list_retained_match_data to discover currently retained managed and next-opponent shot and pass fixtures. For chance quality across several retained games use fm_report_retained_shot_quality with for/against to compare penalties and non-penalty shots. For per-attempt shot origins and xG, try fm_get_retained_shot_map with exact live result fixture_refs; retained source availability is conditional and own-goal markers are separate. For scoped match analytics prefer fm_query_match_scope to enumerate and capture several projections once. Use fm_get_match_data_columns for field discovery without any live capture. Request retained_players in that same scoped call when player contributions are needed. "
                  "For every pass of a stored match with the game closed (passer, receiver, outcome, location, restart), use fm_list_saved_match_event_streams then fm_get_saved_match_passes; fm_get_saved_match_crosses and fm_get_saved_match_shots give every cross and every shot of the same stored matches. "
                  "Use fm_get_saved_match_player_statistics with a pinned fixture archive_key and original PERSON index for stored match goals/assists; preserve unavailable and zero values, and do not infer appearances from row presence. Use fm_find_saved_fixture_results for pinned saved TEAM fixture/result rows with stored Kick Off dates, separate score channels and explicit retained versus historical coverage; do not infer completion. For saved files on disk, use fm_list_saved_careers, fm_get_saved_career, fm_find_saved_clubs, fm_get_saved_club_squads, fm_find_saved_teams, fm_find_saved_competitions and fm_find_saved_currencies directly without attaching. Use fm_find_saved_people with supplied first/surname/common-name parts to discover matching source candidates in a pinned save without a club; preserve ambiguity and bounded coverage. Use fm_get_saved_person_name_candidates to follow file-local roster references and report candidate names with their evidence status. Use fm_get_saved_player_form for a pinned PERSON index to page stored form rows, preserving candidate states and nullable statistics. Use fm_get_saved_player_injury_history for a pinned regular PERSON's retained injury rows, stored-date and canonical injury-ID filters; preserve unavailable states and do not infer current availability. Use fm_get_saved_player_profiles for compact ratings for up to32 pinned PERSON indices, retaining partial states and stored scale context. For the loaded game, call fm_status and fm_attach. Use fm_find_players and fm_get_player for build-verified player fields. Use fm_get_saved_competition_history for pinned retained First/Second/Third Placed results, Year/Start Year/End Year and Date Decided; preserve historical and unavailable scope. "
                  "Use fm_query_saved_people_by_name for cursor-paged canonical typed names, retained literals and explicit unresolved-name coverage; fm_find_saved_people remains the faster candidate search. "
                  "Use fm_compare_saved_current_player_statistics with pinned saved-roster PERSON indices for primary-category starts, substitute appearances and exact goals-plus-assists per90 ranks; preserve null/absent states and ambiguous names. These primary buckets are not proven team-specific or a calendar season. "
                  "Prefer fm_find_save_players for regular players in the current save; it searches the native person table, supports common names and paginates every limit. "
                  "Use fm_query_save_players for save-wide attribute/profile and birth-date filtering; continue every cursor, and do not treat database order as a ranking. Use fm_find_staff and fm_get_staff for staff identity, optional contract club and stored ratings; fm_get_club_staff lists checked staff and fm_query_club_staff filters their ratings. "
                  "Use fm_get_database_catalog for native table counts and explicit coverage limits. "
                  "Use fm_find_competitions and fm_get_competition for stored competition identities, names and geographic/type context; omit search criteria to enumerate every record, including unnamed competitions. "
                  "Use fm_get_competition_stages then fm_get_standings for native stored league tables, including group tables, overall/home/away results and team roster references. Check shared runtime ownership and result-category meanings. "
                  "Use fm_find_currencies/fm_get_currency for stored names, rates and historical entries; fm_convert_currency calculates current stored-rate amounts. Existing budget tools accept GBP. Use fm_get_current_match for fixture-bound current match client performance and both sides’ resident tactical plans. Use fm_get_save for current_date. Use fm_get_fixture_coverage then fm_find_fixtures for resident calendar-year fixtures, date/team/competition filters, stored kickoff clocks and scores; follow every cursor and preserve unavailable archived groups. fm_get_fixture rechecks an individual result. Use fm_find_stadiums to search stored names, IDs, capacity and flags; fm_get_stadium opens a search or fixture venue reference for stored stadium details and city/owner/nearby-stadium links. Use fm_find_cities and fm_get_city for stored city fields and geographic identities. Use fm_find_languages/fm_get_language and fm_find_local_regions/fm_get_local_region for stored language fields, region populations and complete region-language entries. Use fm_find_weather_profiles/fm_get_weather_profile for stored weather periods; city and region weather links open profile details. Use fm_find_stadium_changes/fm_get_stadium_change for stored move records with team/stadium links and explicit unknown units/status. City links open both language/region detail tools; fm_find_cities(local_region_native_id=...) enumerates a region’s cities. "
                  "Use fm_get_current_player_cup_history for current retained cup PERSON counters/last-associated side and optional narrowly scoped fixture-rule comparisons; this is not a full cup-tied verdict. Use fm_query_transfer_offers for current stored live offer objects across both proved manager vectors; raw native state bytes are not labelled acceptance/active status, and proposed terms are not obligations. Use native identity selectors and continue unchanged cursors. Use fm_get_loan_contract for stored loan dates, wages, fees, purchase conditions and recall/playing clause flags; current club can differ and activation is not evaluated. Use fm_get_wage_contributions for live payer/recipient commitments. Use fm_get_club_stadium_rent for the selected coach club's recorded annual rent in GBP; keep missing finance and native base zero separate from concrete amounts, without inferring payment or future liability. Use fm_get_club_committed_wage_spending for explicitly host-recomputed current and committed weekly wages of the selected active coach club; unsupported monetary branches reject, and original game-thread refresh admission is not simulated. Use fm_get_club_finances for balance and budgets, fm_check_transfer_budget for upfront fees and fm_check_wage_budget for additional weekly wages, with explicit coverage limits. Use fm_find_clubs then fm_get_club_squads(club_ref=...) to inspect other clubs' teams and rosters. "
                  "Use fm_get_player_international_duty for current native national-duty/travel gates and official native estimated returns on selected native-roster refs; preserve false, unavailable and outside-scope states. This is not full availability or a guaranteed return. Use fm_report_retained_possession_by_period for player possession won/lost within independently witnessed native half intervals of an exact retained result; missing witnesses remain unavailable. These period reports may persist local host linkage; game access stays read-only. Use fm_get_player_bans for stored personal bans and supported international ban wording. Use fm_get_contract_wage_steps for separate stored appearance-linked wage targets and target-minus-current GBP/week scenarios; activation, progress and budget effects are not established. Use fm_get_save for loaded-career identity and fm_get_managed_squad for the active coach's native roster. Use fm_get_player_assessments with player refs for stored assessment dates and assessors. Use include_joining_interest=true for the recorded English joining-interest labels. Use fm_get_managed_shortlists for your personal recruitment lists, retained entries and player references. Use fm_get_managed_training for the stored team training calendar, session names and rest days. Use fm_get_player_morale for stored career morale on selected native-roster refs; keep overall happiness, concerns, cohesion, manager support and match morale separate. Use fm_get_player_concern_history for bounded stored current-main-contract history on fresh selected native-roster refs; include_templates=true adds unrendered English templates with literal placeholders and explicit unknowns. include_promises=true adds each player's stored native promise vector with raw codes and dates and neutral person links; with templates it adds compiled English kind templates for kinds 1, 16, 25, 69 and 120 only. Preserve empty versus unavailable and raw dates; current unhappiness, promise activity and promise fulfilment are not evaluated. Use fm_get_player_individual_training for stored additional-focus codes and supported English names on selected native-roster player refs; role, intensity, workload and effective training remain separate unknowns. Use fm_get_managed_tactical_assignments for picked XI positions and stored base roles in both phases. Use fm_get_managed_in_possession_positions for where each picked starter is assigned in possession. Use fm_get_managed_team_sheet for who you have picked right now and the current bench. Use fm_get_managed_tactics for stored tactics and primary trained selection. When comparing setups use include_roles=true for phase-specific stored roles (each phase has its own role; the role is the whole selection), include_formation=true for formation IDs and supported English names, and include_instructions=true for mentality and selected options. "
                  "Set include_clubs=true on player or managed-squad reads for current/contract clubs and verified loan status. "
                  "Use fm_get_competition_registrations for stored registration records with years and registration identifiers. Use fm_get_competition_teams for direct stored division assignments and team references; these are not complete cup/stage participant lists. Use fm_get_club_squads then fm_get_team_squad for reserve, youth and other native club rosters, including virtual players. Set profile_policy=available on roster/player reads to preserve checked identities with null unavailable profile fields; required is the strict default. "
                  "Use fm_query_team_players to filter attributes, sort players and inspect loans within a selected team. "
                  "For all-category key-pass event creators, recipients and locations use fm_get_retained_key_pass_annotations with an exact retained fixture; preserve full-side and individual counter coverage and unknown links. Use fm_search_text and fm_read_anchor for raw research. "
                  "Use fm_get_manager_visible_attributes for what the selected manager sees of players' attributes: per field exact, range, unknown or unavailable with a reason. Other tools return stored full information, which the manager does not have. "
                  "Text hits do not prove loaded-save identity, player records, or field semantics. "
                  "Never present raw bytes as verified player attributes. Reattach after save changes."),
)
from .playing_time_tools import register_playing_time_tools
register_playing_time_tools(mcp, bridge)
from .current_match_tools import register_current_match_tools
from .match_period_tools import register_match_period_tools
register_current_match_tools(mcp, bridge)
from .player_physical_tools import register_player_physical_tools
register_player_physical_tools(mcp, bridge)
register_match_period_tools(mcp, bridge)
from .observed_match_tools import register_observed_match_tools
register_observed_match_tools(mcp)
from .current_shot_origin_tools import register_current_shot_origin_tools
register_current_shot_origin_tools(mcp, bridge)
from .current_spatial_tools import register_current_spatial_tools
register_current_spatial_tools(mcp, bridge)
from .current_frame_tools import register_current_frame_tools
register_current_frame_tools(mcp, bridge)

from .simultaneous_bench_tools import register_simultaneous_bench_tools
register_simultaneous_bench_tools(mcp, bridge)

from .live_crossing_tools import register_live_crossing_tools
register_live_crossing_tools(mcp, bridge)
from .live_pair_overlap_tools import register_live_pair_overlap_tools
register_live_pair_overlap_tools(mcp, bridge)
from .live_match_rank_tools import register_live_match_rank_tools
register_live_match_rank_tools(mcp, bridge)
from .live_match_window_tools import register_live_match_window_tools
register_live_match_window_tools(mcp, bridge)

from .retained_match_discovery_tools import register_retained_match_discovery_tools
register_retained_match_discovery_tools(mcp, bridge)

from .retained_shot_tools import register_retained_shot_tools
register_retained_shot_tools(mcp, bridge)
from .retained_pass_tools import register_retained_pass_tools
register_retained_pass_tools(mcp, bridge)
from .active_pass_tools import register_active_pass_tools
register_active_pass_tools(mcp, bridge)
from .retained_spatial_tools import register_retained_spatial_tools
register_retained_spatial_tools(mcp, bridge)
from .retained_pass_event_tools import register_retained_pass_event_tools
register_retained_pass_event_tools(mcp, bridge)
from .player_instruction_tools import register_player_instruction_tools
register_player_instruction_tools(mcp, bridge)
from .retained_key_pass_tools import register_retained_key_pass_tools
register_retained_key_pass_tools(mcp, bridge)
from .retained_cross_event_tools import register_retained_cross_event_tools
register_retained_cross_event_tools(mcp, bridge)
from .retained_goal_tools import register_retained_goal_tools
register_retained_goal_tools(mcp, bridge)
from .club_facility_tools import register_club_facility_tools
register_club_facility_tools(mcp, bridge)
from .live_national_squad_tools import register_live_national_squad_tools
register_live_national_squad_tools(mcp, bridge)
from .individual_training_tools import register_individual_training_tools
register_individual_training_tools(mcp, bridge)
from .player_morale_tools import register_player_morale_tools
register_player_morale_tools(mcp, bridge)
from .player_concern_history_tools import register_player_concern_history_tools
register_player_concern_history_tools(mcp, bridge)
from .international_duty_tools import register_international_duty_tools
register_international_duty_tools(mcp, bridge)
from .retained_possession_period_tools import register_retained_possession_period_tools
register_retained_possession_period_tools(mcp, bridge)
from .club_stadium_rent_tools import register_club_stadium_rent_tools
register_club_stadium_rent_tools(mcp, bridge)
from .committed_wage_tools import register_committed_wage_tools
register_committed_wage_tools(mcp, bridge)
from .contract_wage_step_tools import register_contract_wage_step_tools
register_contract_wage_step_tools(mcp, bridge)
from .player_contract_expiry_tools import register_player_contract_expiry_tools
register_player_contract_expiry_tools(mcp, bridge)
from .award_tools import register_award_tools
register_award_tools(mcp, bridge)
from .debt_obligation_tools import register_debt_obligation_tools
register_debt_obligation_tools(mcp, bridge)
from .transfer_debt_obligation_tools import register_transfer_debt_obligation_tools
register_transfer_debt_obligation_tools(mcp, bridge)
from .staff_responsibility_tools import register_staff_responsibility_tools
register_staff_responsibility_tools(mcp, bridge)
from .transfer_payment_schedule_tools import register_transfer_payment_schedule_tools
register_transfer_payment_schedule_tools(mcp, bridge)
from .contingent_transfer_clause_tools import register_contingent_transfer_clause_tools
register_contingent_transfer_clause_tools(mcp, bridge)
from .sell_on_transfer_clause_tools import register_sell_on_transfer_clause_tools
register_sell_on_transfer_clause_tools(mcp, bridge)
from .current_staff_responsibility_tools import register_current_staff_responsibility_tools
register_current_staff_responsibility_tools(mcp, bridge)
from .ucl_registration_tools import register_ucl_registration_tools
register_ucl_registration_tools(mcp, bridge)
from .manager_visible_attribute_tools import register_manager_visible_attribute_tools
register_manager_visible_attribute_tools(mcp, bridge)
from .fmdb.ui_tools import register_fmdb_ui_tools; register_fmdb_ui_tools(mcp, bridge)  # noqa: E702

READ = ToolAnnotations(readOnlyHint=True, destructiveHint=False, openWorldHint=False)


register_captured_match_tools(mcp)
register_captured_crossing_tools(mcp)


@mcp.tool(annotations=READ)
def fm_list_saved_careers(
    offset: Annotated[int, Field(strict=True, ge=0)] = 0,
    limit: Annotated[int, Field(strict=True, ge=1, le=500)] = 50,
) -> dict[str, Any]:
    """List the saved career files in the local FM27 games directory. No game session is required. Each readable file has a snapshot identity, component count and any verified saved summary. Use its filename to inspect the archive with fm_get_saved_career."""
    return snapshot_catalog.discover_snapshots(offset=offset, limit=limit)


@mcp.tool(annotations=READ)
def fm_get_saved_career(
    filename: str, offset: Annotated[int, Field(strict=True, ge=0)] = 0,
    limit: Annotated[int, Field(strict=True, ge=1, le=500)] = 100,
    prefix: str | None = None, expected_snapshot_id: str | None = None,
) -> dict[str, Any]:
    """Read one named on-disk FM27 career without attaching to the game. Returns saved manager/date metadata when supported and an ordered page of component paths and sizes. Use a filename from fm_list_saved_careers. Prefix is a literal prefix of the stored path including the archive root. On later pages pass next_offset, the same prefix and the returned snapshot_id as expected_snapshot_id. Saved dates refer to this file."""
    return snapshot_catalog.inspect_snapshot(filename, offset=offset, limit=limit, prefix=prefix,
                                             expected_snapshot_id=expected_snapshot_id)


@mcp.tool(annotations=READ)
def fm_get_saved_club_starting_finances(
    filename: str,
    club_index: Annotated[int, Field(strict=True, ge=0, lt=2**31)],
    expected_snapshot_id: str,
    include_ffp: Annotated[bool, Field(strict=True)] = False,
    offset: Annotated[int, Field(strict=True, ge=0)] = 0,
    limit: Annotated[int, Field(strict=True, ge=1, le=100)] = 50,
) -> dict[str, Any]:
    """Read stored starting debt inputs for one original CLUB index in an exact pinned saved file. No game session is required. Returns the native pre-game Debts list, with original debt cash, labelled source such as Bank, stored dates and qualified interest fields. These are starting inputs, not today's outstanding loan balance, repayments or discharge status. Currency is explicitly unproved; do not add a currency symbol. The raw unknown 0x5c field has no proved term unit. Match all original TEAM native IDs to the selected CLUB native ID exactly as the native getter does; duplicate/shared IDs are disclosed rather than silently choosing one TEAM. Set include_ffp=true to additionally include the distinct stored Financial Fair Play Records branch. Page qualified records in original component order with next_offset and the same pin/options. Missing components are unavailable, while a completely checked empty native debt list has matched_count0. Preserve negative FFP amounts, unknown source codes and raw fields without treating them as loans."""
    return saved_starting_finances.get_starting_finances(
        filename, club_index, expected_snapshot_id, include_ffp=include_ffp,
        offset=offset, limit=limit,
    )


@mcp.tool(annotations=READ)
def fm_find_saved_clubs(
    filename: str, name: Annotated[str | None, Field(min_length=1, max_length=256)] = None,
    native_id: Annotated[int | None, Field(strict=True, ge=0, le=4294967295)] = None,
    offset: Annotated[int, Field(strict=True, ge=0)] = 0,
    limit: Annotated[int, Field(strict=True, ge=1, le=500)] = 50,
    expected_snapshot_id: str | None = None,
) -> dict[str, Any]:
    """Search every CLUB slot in one named on-disk save without a game session. Name matches case-insensitive substrings in full or short names. Native ID matches exactly. Both filters can be combined or omitted. Duplicate names retain separate identities. Continue with the returned next_offset, identical filters and snapshot_id as expected_snapshot_id. Unsupported database layouts raise an error."""
    return saved_club_search.find_clubs(filename, name=name, native_id=native_id, offset=offset,
                                        limit=limit, expected_snapshot_id=expected_snapshot_id)


@mcp.tool(annotations=READ)
def fm_get_saved_club_squads(
    filename: str, club_native_id: Annotated[int, Field(strict=True, ge=0, le=4294967295)],
    expected_snapshot_id: str | None = None,
) -> dict[str, Any]:
    """Read a saved club's teams, roster sizes and ordered member slots directly from disk. Select an exact native ID from fm_find_saved_clubs and pass the saved snapshot_id to pin the file. Each roster entry references the PERSON table of that file only. Null slots remain null. Roster size counts stored slots, including nulls. Compare team native IDs between dated saves. Membership alone does not establish player identity, eligibility or ownership."""
    return saved_squad_search.get_saved_club_squads(filename, club_native_id, expected_snapshot_id)


@mcp.tool(annotations=READ)
def fm_get_saved_person_name_candidates(
    filename: str,
    person_indices: Annotated[list[Annotated[int, Field(strict=True, ge=0, lt=2**31)]], Field(min_length=1, max_length=32)],
    expected_snapshot_id: str, include_alternatives: Annotated[bool, Field(strict=True)] = False,
    include_ability: Annotated[bool, Field(strict=True)] = False,
    candidate_offset: Annotated[int, Field(strict=True, ge=0)] = 0,
    candidate_limit: Annotated[int, Field(strict=True, ge=1, le=100)] = 100,
) -> dict[str, Any]:
    """Look up candidate names for 1–32 PERSON indices returned by a roster in this exact saved file. Pass the same snapshot ID. Uses archived name tables without a game session. The default returns the strongest locally corroborated candidates when available. Set include_alternatives=true to page through all supported suffix witnesses. Each row has its own next_candidate_offset. Report alternatives and incomplete searches. An unresolved index may still represent a person. Set include_ability=true for native signed PCAB/PPAB values only at checked target starts anchored by a preceding ordinal packet. Competing start geometries remain separate. Values are qualified source fields, without scouting masks or star ratings; they do not certify the complete PERSON record."""
    return saved_person_search.get_name_candidates(
        filename, person_indices, expected_snapshot_id, include_alternatives=include_alternatives,
        candidate_offset=candidate_offset, candidate_limit=candidate_limit, include_ability=include_ability,
    )


@mcp.tool(annotations=READ)
def fm_get_saved_person_records(
    filename: str,
    expected_snapshot_id: str,
    person_indices: Annotated[list[Annotated[int, Field(strict=True, ge=0, lt=2**31)]] | None,
                              Field(min_length=1, max_length=32)] = None,
    offset: Annotated[int, Field(strict=True, ge=0, lt=2**31)] = 0,
    limit: Annotated[int, Field(strict=True, ge=1, le=32)] = 20,
) -> dict[str, Any]:
    """Read consecutive, typed records from the selected save’s structurally located PERSON table.
    Supply 1–32 file-local indices (duplicates and order preserved), or use offset/limit for a page.
    A single call advances at most 10,000 new source records. Repeat the same query on this server
    when retry_same_query_to_advance is true. An unsupported source type stops the prefix.
    Returned IDs, byte ranges and names belong to the selected archive. Native loader settings
    and the source tables preceding the PERSON header have separate evidence limits.
    """
    return saved_population.get_person_records(filename, expected_snapshot_id,
                                               person_indices=person_indices, offset=offset, limit=limit)


@mcp.tool(annotations=READ)
def fm_find_saved_players(
    filename: str,
    expected_snapshot_id: str,
    criteria: dict[str, dict[str, Annotated[int, Field(strict=True)]]] | None = None,
    min_age: Annotated[int | None, Field(strict=True, ge=0, le=150)] = None,
    max_age: Annotated[int | None, Field(strict=True, ge=0, le=150)] = None,
    cursor: str | None = None,
    limit: Annotated[int, Field(strict=True, ge=1, le=50)] = 20,
    scan_limit: Annotated[int, Field(strict=True, ge=1, le=10000)] = 10000,
) -> dict[str, Any]:
    """Find conditional stored player ratings in a pinned saved archive, without a live session.
    Supply AND criteria such as {"attributes.finishing":{"min":15},"positions.striker":{"min":20}}.
    Ability criteria require fixed CA/PA0..200; negative PA ranges remain unavailable.
    Optional age bounds use only the same-file verified save date and stored birth date.
    Scans bounded consecutive original PERSON slots, including regular and combined PLAYER classes.
    Follow next_cursor even after an empty partial page; keep identical filename, pin and criteria.
    Cursors expire when this server restarts. Counts distinguish known rejection, unavailable fields,
    excluded classes and unsupported frontiers. Names may be unavailable even when ratings match.
    Complete-table claims require the source footer; decoded slots alone do not prove native loading.
    Report original-slot coverage and conditional source profile; partial nil is not whole-save absence.
    This is distinct from the loaded-game fm_query_save_players tool.
    """
    return saved_scouting_query.find_players(filename, expected_snapshot_id, criteria=criteria,
        min_age=min_age,max_age=max_age,cursor=cursor,limit=limit,scan_limit=scan_limit)


@mcp.tool(annotations=READ)
def fm_get_saved_player_injury_history(
    filename: str,
    person_index: Annotated[int, Field(strict=True, ge=0, lt=2**31)],
    expected_snapshot_id: str,
    date_from: Annotated[str | None, Field(strict=True, min_length=10, max_length=10,
                                          pattern=r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$")] = None,
    date_to: Annotated[str | None, Field(strict=True, min_length=10, max_length=10,
                                        pattern=r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$")] = None,
    injury_native_ids: Annotated[list[Annotated[int, Field(strict=True, ge=0, lt=2**32)]] | None,
                                 Field(min_length=1, max_length=100)] = None,
    offset: Annotated[int, Field(strict=True, ge=0, lt=2**31)] = 0,
    limit: Annotated[int, Field(strict=True, ge=1, le=200)] = 50,
    include_installed_names: Annotated[bool, Field(strict=True)] = False,
) -> dict[str, Any]:
    """Read a regular PLAYER's retained injury history from one pinned saved archive.
    person_index is the original saved PERSON ordinal, not a native ID or owner key.
    Optional inclusive date bounds select the stored DATE; onset, recovery and end-date
    meaning remain unproved. injury_native_ids selects canonical same-save INJURY IDs.
    Names, raw value units and flags remain explicit. This does not assess current injury,
    availability, medical clearance or complete lifetime injury history. Filters precede
    paging; original entry order, duplicates and unknown filter states remain visible.
    A bounded PERSON walk may stop; retry only when PERSON_coverage says more work remains.
    Missing components, unsupported owners and unreached records are not empty histories.
    Complete used frames and snapshot identity are verified without a game session.
    include_installed_names adds separately attributed, verified English database 2600
    baseline labels when that installed resource is available. Saved names remain null;
    career language and override equivalence are unverified. Core access needs no game.
    """
    return saved_player_injury_history.get_injury_history(
        filename, person_index, expected_snapshot_id, date_from=date_from, date_to=date_to,
        injury_native_ids=injury_native_ids, offset=offset, limit=limit,
        include_installed_names=include_installed_names)


@mcp.tool(annotations=READ)
def fm_get_saved_staff_history(
    filename: str,
    person_index: Annotated[int, Field(strict=True, ge=0, lt=2**31)],
    expected_snapshot_id: str,
    offset: Annotated[int, Field(strict=True, ge=0, lt=2**31)] = 0,
    limit: Annotated[int, Field(strict=True, ge=1, le=200)] = 50,
) -> dict[str, Any]:
    """Read pinned saved non-playing histories for one typed ACTUAL_PERSON.
    person_index is an original same-save PERSON ordinal, never a native ID or owner key.
    The complete typed PERSON, unique structural table conjunction and two native-ID maps
    must be checked. A bounded PERSON walk can stop; repeat only if coverage permits.
    Missing map, stored negative owner, selected empty vector and unavailable PERSON differ.
    Ordered rows preserve duplicates, raw dates and unlabelled fields. TEAM native IDs resolve
    against the same-file table; multiple matches remain explicit. Date precision can be year-only;
    native default dates and history rows do not establish current employment or full career.
    Job English is a separately verified build-specific baseline, never a saved role label.
    """
    return saved_staff_history.get_staff_history(filename, person_index, expected_snapshot_id,
                                                 offset=offset, limit=limit)


@mcp.tool(annotations=READ)
def fm_get_saved_player_starting_history(
    filename: str,
    person_index: Annotated[int, Field(strict=True, ge=0, lt=2**31)],
    expected_snapshot_id: str,
    years: Annotated[list[Annotated[int, Field(strict=True, ge=0, le=32767)]] | None,
                     Field(min_length=1, max_length=100)] = None,
    offset: Annotated[int, Field(strict=True, ge=0, lt=2**31)] = 0,
    limit: Annotated[int, Field(strict=True, ge=1, le=200)] = 50,
    include_names: Annotated[bool, Field(strict=True)] = False,
) -> dict[str, Any]:
    """Read one regular PLAYER's retained starting playing history from a pinned save.
    person_index is the original same-save PERSON ordinal, never a native ID or history key.
    A bounded consecutive typed PERSON walk may require repeating the identical request.
    The authoritative saved native-ID map is anchored by a unique complete FIXTURE_NAME
    conjunction plus three checked adjoining empty tables; unsupported positives fail closed.
    Stored year, appearances, goals and loan flag are verified;255 counts become null,0 stays0.
    Raw TEAM/COMP native identity words are not table indices. Optional include_names joins
    exact pairs in this same pinned source; TEAM names require reciprocal owning CLUB membership.
    Missing, ambiguous, sentinel and conflicting owners remain explicit; no primary-ID fallback.
    Year filtering precedes paging; original order and duplicates remain. Career completeness,
    season convention, fee currency and date sentinel meanings are not proved. Unreached,
    unsupported, missing-map and outside-owner states are distinct from a selected empty vector.
    """
    return saved_starting_career.get_starting_history(filename,person_index,expected_snapshot_id,
        years=years,offset=offset,limit=limit,include_names=include_names)



@mcp.tool(annotations=READ)
def fm_get_saved_player_statistics_history(
    filename: str,
    person_index: Annotated[int, Field(strict=True, ge=0, lt=2**31)],
    expected_snapshot_id: str,
    years: Annotated[list[Annotated[int, Field(strict=True, ge=0, le=65535)]] | None,
                     Field(min_length=1, max_length=100)] = None,
    category_codes: Annotated[list[Annotated[int, Field(strict=True, ge=0, le=5)]] | None,
                              Field(min_length=1, max_length=100)] = None,
    offset: Annotated[int, Field(strict=True, ge=0, lt=2**31)] = 0,
    limit: Annotated[int, Field(strict=True, ge=1, le=200)] = 50,
) -> dict[str, Any]:
    """Read one regular PLAYER's indexed statistics history from a pinned saved archive.
    person_index is the original saved PERSON ordinal, not a native ID or history owner key.
    years selects exact stored native years; season-start/end convention remains unproved.
    Category codes preserve separate native categories and overlapping totals must not be summed.
    Filters precede paging; native entry order and duplicate rows are preserved. Zero remains0;
    unknown byte255 becomes null. TEAM/COMP references remain unresolved same-snapshot indices.
    A bounded PERSON advance may require repeating the identical query on this server; inspect
    PERSON_coverage and state. Unsupported or unreached owners are not empty history.
    Complete used frames and snapshot identity are checked; no live session or current-form merge.
    """
    return saved_player_history.get_history(filename, person_index, expected_snapshot_id,
        years=years,category_codes=category_codes,offset=offset,limit=limit)


@mcp.tool(annotations=READ)
def fm_get_saved_competition_history(
    filename: str,
    competition_index: Annotated[int, Field(strict=True, ge=0, lt=2**31)],
    expected_snapshot_id: str,
    years: Annotated[list[Annotated[int, Field(strict=True, ge=-32768, le=32767)]] | None,
                     Field(min_length=1, max_length=100)] = None,
    offset: Annotated[int, Field(strict=True, ge=0, lt=2**31)] = 0,
    limit: Annotated[int, Field(strict=True, ge=1, le=200)] = 50,
) -> dict[str, Any]:
    """Read retained competition-history rows from one pinned saved archive.
    competition_index is the original COMP ordinal from fm_find_saved_competitions,
    not its native ID or history owner key. years filters exact signed native Year
    fields before original-order paging; Start Year/End Year add no season convention.
    First/Second/Third Placed TEAMs and their CLUB owners are joined canonically in
    the same file. Stored empty TEAM names remain empty; owner CLUB names are separate.
    Date Decided preserves native unset/unknown values and raw bits. Retained history
    does not establish a current table, latest completed season, individual match
    completion or complete lifetime results. Missing/outside/negative-key states are
    distinct from a checked empty vector. No game session or installed labels needed.
    """
    return saved_competition_history.get_history(filename, competition_index, expected_snapshot_id,
        years=years, offset=offset, limit=limit)


@mcp.tool(annotations=READ)
def fm_get_saved_component_slice(
    filename: str,
    member_path: Annotated[str, Field(strict=True, min_length=1, max_length=10248)],
    expected_snapshot_id: str,
    offset: Annotated[int, Field(strict=True, ge=0, le=512*1024**2)] = 0,
    limit: Annotated[int, Field(strict=True, ge=1, le=16384)] = 1024,
) -> dict[str, Any]:
    """Read opaque bytes from any exact full member path listed by fm_get_saved_career.
    Use the same filename and required snapshot ID; paths are archive members, not disk paths.
    offset is zero-based in the uncompressed member, limit is bytes (maximum16384).
    Every page streams the entire bounded member, validates its complete frame and packed
    bytes, and rechecks snapshot identity before returning its full SHA256 and raw hex page.
    Missing, ambiguous, changed, corrupt or unsupported members fail explicitly. There is
    no source cache. Opaque byte validation does not decode fields, identify owners or
    establish football facts, native-loader acceptance or completeness of any domain.
    """
    return saved_component_slice.get_component_slice(
        filename, member_path, expected_snapshot_id, offset=offset, limit=limit)


@mcp.tool(annotations=READ)
def fm_get_saved_history_inventory(
    filename: str,
    expected_snapshot_id: str,
    family: str | None = None,
    owner_index: Annotated[int | None, Field(strict=True, ge=0, lt=2**31)] = None,
    offset: Annotated[int, Field(strict=True, ge=0, lt=2**31)] = 0,
    limit: Annotated[int, Field(strict=True, ge=1, le=200)] = 20,
) -> dict[str, Any]:
    """Inventory16 allowlisted saved fixed-history families without loading game_db or attaching.
    Omit family for all structural indexed/free/physical counts. Supply an exact returned family
    and its source-local owner_index to page opaque bytes/extents in original entry order.
    Owner ordinals are not PERSON indices or native IDs. Raw bytes have no inferred football meaning;
    domain-specific saved-player queries remain primary. Missing pairs, unsupported profiles,
    empty data, empty owners and free slots remain distinct. Other components are not surveyed.
    Complete used frames, packed bytes and the same snapshot pin are rechecked. No arbitrary paths.
    """
    return saved_history_inventory.get_inventory(filename, expected_snapshot_id,
        family=family,owner_index=owner_index,offset=offset,limit=limit)


@mcp.tool(annotations=READ)
def fm_find_saved_people(
    filename: str,
    expected_snapshot_id: str,
    first_name: Annotated[str | None, Field(strict=True, min_length=1, max_length=256)] = None,
    surname: Annotated[str | None, Field(strict=True, min_length=1, max_length=256)] = None,
    common_name: Annotated[str | None, Field(strict=True, min_length=1, max_length=256)] = None,
    match_mode: Literal['exact', 'prefix', 'substring'] = 'exact',
    offset: Annotated[int, Field(strict=True, ge=0)] = 0,
    limit: Annotated[int, Field(strict=True, ge=1, le=50)] = 20,
) -> dict[str, Any]:
    """Find name-reference candidates in one exact dated save without a game session or known club/PERSON index. Supply at least one name part; supplied first_name, surname and common_name combine with AND under the same exact/prefix/substring mode. Comparison folds case and combining accents (NFKD), strips outer whitespace and preserves internal spaces/punctuation; stored names remain unchanged. Results retain stored index and both identity words, local candidate evidence, ambiguity and work limits. A scoped no-match is not a whole-population absence: inline-name transports, unparsed record types and continuous membership remain unproved. Narrow broad queries when state is stopped. Continue next_offset with the same name parts, mode and snapshot pin. A returned person_index is a file-local candidate: fm_get_saved_player_profiles independently revalidates it. No result certifies a complete PERSON record or native loader acceptance."""
    return saved_person_name_search.find_people(
        filename, expected_snapshot_id, first_name=first_name, surname=surname,
        common_name=common_name, match_mode=match_mode, offset=offset, limit=limit,
    )


@mcp.tool(annotations=READ)
def fm_query_saved_people_by_name(
    filename: str,
    expected_snapshot_id: str,
    first_name: Annotated[str | None, Field(strict=True, min_length=1, max_length=256)] = None,
    surname: Annotated[str | None, Field(strict=True, min_length=1, max_length=256)] = None,
    common_name: Annotated[str | None, Field(strict=True, min_length=1, max_length=256)] = None,
    any_name: Annotated[str | None, Field(strict=True, min_length=1, max_length=256)] = None,
    match_mode: Literal['exact', 'prefix', 'substring'] = 'exact',
    cursor: str | None = None,
    limit: Annotated[int, Field(strict=True, ge=1, le=50)] = 20,
    scan_limit: Annotated[int, Field(strict=True, ge=1, le=10000)] = 10000,
) -> dict[str, Any]:
    """Page a typed canonical PERSON name search in one pinned saved archive.
    Supply at least one first_name, surname, common_name or any_name. Selectors
    combine with AND; any_name matches any decoded stored part or retired literal,
    without concatenating parts or guessing a literal's First/Surname meaning.
    Case/combining accents fold with the same NFKD policy as fm_find_saved_people.
    This query reads complete typed records and canonical independent identity
    words; the existing fm_find_saved_people remains the faster suffix-candidate
    path. Follow next_cursor with identical selectors, even after an empty partial
    page. A process-private source-hash-bound index avoids repeated body parsing;
    returned cached matches are freshly decoded. Unresolved encoding, out-of-range
    fields, unprojected virtual names and inline effective-name deduplication stay
    explicit. Full record traversal is separate from absence across all names.
    Wire placement/native-global conditions remain qualified; no game session is
    needed. Cursors expire when their source/index is evicted or the server restarts.
    """
    return saved_canonical_person_names.find_people(
        filename, expected_snapshot_id, first_name=first_name, surname=surname,
        common_name=common_name, any_name=any_name, match_mode=match_mode,
        cursor=cursor, limit=limit, scan_limit=scan_limit,
    )


@mcp.tool(annotations=READ)
def fm_get_saved_player_form(
    filename: str,
    person_index: Annotated[int, Field(strict=True, ge=0, lt=2**31)],
    expected_snapshot_id: str,
    offset: Annotated[int, Field(strict=True, ge=0)] = 0,
    limit: Annotated[int, Field(strict=True, ge=1, le=500)] = 50,
) -> dict[str, Any]:
    """Read stored form rows for one file-local PERSON index in the exact pinned save. No game session is required. Uses a locally corroborated regular-player start; unavailable, competing or incomplete candidates return explicit states without choosing a form list. Continue next_offset with the same filename, person_index, snapshot ID and limit. Offset/limit page original rows across groups, preserving group ordinals, order, duplicate dates and nullable absent statistics. Stored stats.played_minutes reports native playing duration in the event-minute clock: absent statistics remain null and present zero remains zero. Duration does not identify starters or unused substitutes, or prove match completion or stoppage-time precision. Current producer values are 0–127; outside-profile bytes remain raw with null played minutes. Empty fully read groups differ from unavailable or absent sections. Each group retains owner_reference_word and a nullable stored_group_team_index in TEAM_BASE, an original same-snapshot index with unresolved team identity. Match it only to database_index on a team row already returned by fm_get_saved_club_squads on this pin. Row team words have separate unresolved meanings. Dates and competition words remain qualified stored fields; no fixture or score is inferred, and the complete player record is not certified."""
    return saved_player_form_query.get_player_form(
        filename, person_index, expected_snapshot_id, offset=offset, limit=limit,
    )


@mcp.tool(annotations=READ)
def fm_compare_saved_current_player_statistics(
    filename: Annotated[str, Field(strict=True, min_length=1)],
    person_indices: Annotated[list[Annotated[int, Field(strict=True, ge=0, lt=2**31)]],
                              Field(strict=True, min_length=1, max_length=32)],
    expected_snapshot_id: Annotated[str, Field(strict=True, pattern='^[0-9a-f]{64}$')],
    category_code: Annotated[int, Field(strict=True, ge=0, le=5)] = 1,
    minimum_minutes: Annotated[int, Field(strict=True, ge=1, le=32767)] = 270,
) -> dict[str, Any]:
    """Compare stored current primary categories for 1..32 exact same-snapshot PERSON indices.
    Use original PERSON indices from fm_get_saved_club_squads and that filename's snapshot ID;
    no game session is required. Native categories 0..5 are Non Competitive, League, Cup,
    Continental, International and Overall (Club); default League 1. Primary categories are
    per PERSON, not proven statistics for the selected roster's team. Numeric season year
    remains unresolved. Do not add overlapping categories, archived history or starting history.
    One complete source scan checks every owner and rejects duplicate owners before returning
    any absence. Preserve available, serialized_null_category and no_serialized_current_entry;
    missing entries/counters are not zero appearances. Starts, substitutes, goals, assists and
    signed minutes retain raw counters; 255 is an unavailable byte value. Positive supported
    minutes and known goals/assists determine G+A/90 with exact rational ranks and ties.
    eligible means meeting ranking criteria, not match or registration eligibility. Duplicate
    requests are evaluated once in input order. Names carry separate unique, ambiguous,
    incomplete or unavailable candidate evidence; never select an ambiguous display name.
    Resolve it independently with a checked same-pin PERSON/profile identity or retain the
    numeric index. Unsupported writer variants fail explicitly; no native code is invoked.
    """
    return saved_current_statistics.compare_current_statistics(
        filename, person_indices, expected_snapshot_id,
        category_code=category_code, minimum_minutes=minimum_minutes,
    )


@mcp.tool(annotations=READ)
def fm_compare_saved_player_form(
    filename: str,
    person_indices: Annotated[list[Annotated[int, Field(strict=True, ge=0, lt=2**31)]], Field(min_length=1, max_length=32)],
    expected_snapshot_id: str,
    team_index: Annotated[int, Field(strict=True, ge=0, le=2**32 - 2)],
    date_from: str,
    date_to: str,
    minimum_observed_minutes: Annotated[int, Field(strict=True, gt=0)],
    competition_index: Annotated[int | None, Field(strict=True, ge=0, lt=2**31)] = None,
) -> dict[str, Any]:
    """Rank goals plus assists per 90 observed minutes for up to 32 supplied PERSON indices in one pinned on-disk save. Supply the exact stored TEAM_BASE group owner index from a same-pin club-squad team, inclusive YYYY-MM-DD date bounds and a positive minimum observed minute threshold. Optionally filter the exact stored COMP index. One checked source pass evaluates duplicate PERSON requests once. Return every selected person's eligible, below-minimum, absent, stopped or candidate-search state, observed goals/assists/minutes, missing-stat and retained-date coverage, plus exact-ratio ranks preserving all ties. Missing statistics contribute neither numerator nor denominator; zero duration stays present. Retain distinct serialized rows including duplicate dates. Scope is retained form rows, not complete season, senior squad, match completion or certified PERSON coverage. Row team words have separate unresolved meanings and are not the owner filter."""
    return saved_form_comparison.compare_player_form(
        filename, person_indices, expected_snapshot_id, team_index=team_index,
        date_from=date_from, date_to=date_to,
        minimum_observed_minutes=minimum_observed_minutes,
        competition_index=competition_index,
    )


@mcp.tool(annotations=READ)
def fm_get_saved_player_health(
    filename: Annotated[str, Field(strict=True, min_length=1)],
    person_indices: Annotated[list[Annotated[int, Field(strict=True, ge=0, lt=2**31)]],
                              Field(strict=True, min_length=1, max_length=32)],
    expected_snapshot_id: Annotated[str, Field(strict=True, pattern='^[0-9a-f]{64}$')],
    include_installed_names: Annotated[bool, Field(strict=True)] = False,
) -> dict[str, Any]:
    """Read stored fitness and injury-vector records for up to32 original PERSON indices in one pinned save, without a game session. Use indices from the same snapshot's roster. Condition and sharpness use native0..10000 units; fatigue is signed, higher meaning more fatigued. Fitness and injuries have independent states, so a stopped injury traversal can retain decoded fitness. Original injury-vector records resolve same-save INJURY indices; empty decoded vectors differ from unknown sections. Stored injury dates retain their raw bits without an onset/recovery interpretation. Optional installed English injury labels are separately attributed baseline text, not saved names or the career's language. Preserve ambiguous/incomplete PERSON placement and unknown references. These stored readings execute no refresh and establish neither medical clearance, recovery forecasts nor match/registration eligibility. Duplicate input indices retain input order; bounded output may require a smaller batch."""
    return saved_player_health.get_player_health(
        filename, person_indices, expected_snapshot_id,
        include_installed_names=include_installed_names)


@mcp.tool(annotations=READ)
def fm_get_saved_player_profiles(
    filename: str,
    person_indices: Annotated[list[Annotated[int, Field(strict=True, ge=0, lt=2**31)]], Field(min_length=1, max_length=32)],
    expected_snapshot_id: str,
    include_current_contract: Annotated[bool, Field(strict=True)] = False,
    fields: Annotated[list[Annotated[str, Field(strict=True, min_length=1, max_length=80)]] | None,
                      Field(min_length=1, max_length=128)] = None,
) -> dict[str, Any]:
    """Read compact stored player profiles for 1–32 PERSON indices in one exact pinned save, without a game session. Results preserve requested order and separate available, partial, unavailable, competing and incomplete candidates. Omit fields for all groups, or select group/field names such as attributes, positions, goalkeeping, hidden_attributes, feet, ability.current or attributes.passing. Attribute-like values use the separately stored scale; positions remain native0–20, and signed CA/PA codes are preserved without guessing ranges. Missing scale leaves attributes null while usable positions and ability remain explicit. Set include_current_contract=true to add owner-checked primary contract dates/status and weekly_wage when its ACTUAL_PERSON boundary is reached. Weekly wages retain the signed raw amount and source offset; nonnegative whole base-currency amounts report GBP only when the same snapshot verifies the supported GBP base-currency context, while negative codes and unverified currency remain explicit. Primary wages do not include auxiliary loan contributions, bonuses or offers. Unavailable contracts never erase ratings, and dynamic expiry or extension activation is not guessed. Report per-person evidence and unavailable fields; these locally corroborated starts do not certify complete PERSON records or native loader acceptance."""
    return saved_player_profile_query.get_player_profiles(
        filename, person_indices, expected_snapshot_id, fields=fields,
        include_current_contract=include_current_contract,
    )


@mcp.tool(annotations=READ)
def fm_find_saved_teams(
    filename: str, native_id: Annotated[int | None, Field(strict=True, ge=0, le=4294967295)] = None,
    owner_kind: Literal['club', 'national'] | None = None,
    team_type_code: Annotated[int | None, Field(strict=True, ge=-128, le=127)] = None,
    person_indices: Annotated[list[Annotated[int, Field(strict=True, ge=0, le=2147483647)]] | None,
                              Field(min_length=1, max_length=500)] = None,
    offset: Annotated[int, Field(strict=True, ge=0)] = 0,
    limit: Annotated[int, Field(strict=True, ge=1, le=500)] = 50,
    expected_snapshot_id: str | None = None,
    include_nation_context: Annotated[bool, Field(strict=True)] = False,
    nation_native_id: Annotated[int | None, Field(strict=True, ge=0, le=4294967295)] = None,
) -> dict[str, Any]:
    """Search all teams in a saved file. Filter by exact native ID, owner kind, signed team type or any of up to 500 distinct PERSON indices from the same snapshot. With person_indices, pass its snapshot_id as expected_snapshot_id and obtain the zero-based matching roster slots. Combine owner_kind='national' with a saved club roster's PERSON indices to find overlapping national rosters. Set include_nation_context=true for the saved country identity and an English name from the installed database when available. An exact nation_native_id filter implies that context. Membership alone does not establish an active international call-up. Paginate with next_offset and the same pin and filters."""
    return saved_team_search.find_teams(filename, native_id=native_id, owner_kind=owner_kind,
                                        team_type_code=team_type_code, person_indices=person_indices,
                                        offset=offset, limit=limit, expected_snapshot_id=expected_snapshot_id,
                                        include_nation_context=include_nation_context, nation_native_id=nation_native_id)


@mcp.tool(annotations=READ)
def fm_find_saved_competitions(
    filename: str, native_id: Annotated[int | None, Field(strict=True, ge=0, le=4294967295)] = None,
    type_code: Annotated[int | None, Field(strict=True, ge=-128, le=127)] = None,
    gender: Literal["male", "female"] | None = None,
    is_extinct: Annotated[bool | None, Field(strict=True)] = None,
    offset: Annotated[int, Field(strict=True, ge=0)] = 0,
    limit: Annotated[int, Field(strict=True, ge=1, le=500)] = 50,
    expected_snapshot_id: str | None = None,
    include_saved_state: Annotated[bool, Field(strict=True)] = False,
) -> dict[str, Any]:
    """Search every competition slot in a named saved file without attaching. Combine exact native ID, signed type code, gender and stored extinct flag, or omit filters to enumerate in saved order. Returns stored context and any names serialized within each record. Omitted names remain null. Opt into include_saved_state for the same archive's rgman component availability and stored native season discriminator; this does not decode a season date range, stages, schedules or champions. Use next_offset with the same filters and snapshot_id as expected_snapshot_id for later pages."""
    return saved_world_search.find_competitions(filename, native_id=native_id, type_code=type_code,
                                                gender=gender, is_extinct=is_extinct, offset=offset,
                                                limit=limit, expected_snapshot_id=expected_snapshot_id,
                                                include_saved_state=include_saved_state)


@mcp.tool(annotations=READ)
def fm_get_saved_league_table(
    filename: str,
    competition_index: Annotated[int, Field(strict=True, ge=0, lt=2**31)],
    expected_snapshot_id: str,
    stage_ordinal: Annotated[int, Field(strict=True, ge=0, lt=1024)] = 0,
) -> dict[str, Any]:
    """Read a retained ordinary league table from one pinned saved competition, without a game session. Supply the original COMP database_index from fm_find_saved_competitions and the same snapshot ID. stage_ordinal selects an original stage slot, default0; it is not a season or round name. Resolve canonical TEAM and owner CLUB rows from the same pin, preserving empty TEAM names. Return stored overall/home/away statistics and a guarded stored overall position, not current league standings. Preserve absent, unsupported, stopped and budget states. The stored stage calendar is rule-processing context, not an as-of date; real season interval, table effective date and currentness remain unknown. Source reference/factory profiles are conditional and only the first C0 table is complete; preceding unparsed nonnull stages cannot be skipped."""
    return saved_league_tables.get_league_table(
        filename, competition_index, expected_snapshot_id, stage_ordinal=stage_ordinal)


@mcp.tool(annotations=READ)
def fm_find_saved_transfer_offers(
    filename: str,
    expected_snapshot_id: str,
    person_index: Annotated[int | None, Field(strict=True, ge=0, lt=2**31)] = None,
    team_index: Annotated[int | None, Field(strict=True, ge=0, lt=2**31)] = None,
    offset: Annotated[int, Field(strict=True, ge=0)] = 0,
    limit: Annotated[int, Field(strict=True, ge=1, le=500)] = 50,
) -> dict[str, Any]:
    """Find stored transfer offers in one pinned save without attaching. Supply a PERSON or TEAM index previously issued for this snapshot. PERSON matches the common offer PERSON+38 field; TEAM matches common TEAM+40/+48/+50 fields, with business direction unresolved. Both selectors combine with AND. Search covers two complete named BASE_TRANSFER_MANAGER offer vectors, preserves source order, separate objects and null-slot counts, and pages with the same selectors and snapshot pin. Offer class, raw state code, source extent/digest and proved loan terms remain explicit. Loan wage terms use whole base-currency units per week; monthly fees stay separate and currency remains null. Acceptance, scheduled payment and an amount due are unresolved. Third and later manager sections are excluded, and no full-save absence is established."""
    return saved_transfer_offers.find_offers(
        filename, expected_snapshot_id=expected_snapshot_id,
        person_index=person_index, team_index=team_index, offset=offset, limit=limit,
    )


@mcp.tool(annotations=READ)
def fm_get_saved_match_player_statistics(
    filename: str,
    fixture_key: Annotated[int, Field(strict=True, ge=0, lt=2**31)],
    person_index: Annotated[int, Field(strict=True, ge=0, lt=2**31)],
    expected_snapshot_id: str,
) -> dict[str, Any]:
    """Read stored goals and assists for one PERSON in a pinned retained match. First use fm_find_saved_fixture_results for the desired TEAM/date and its archive_key, then pass that exact key and the original same-snapshot PERSON index. Missing retained keys or player rows are explicit unavailable states; stored zero is preserved. Duplicate keys/subjects and unsupported encodings fail. Both team-stat side sections are checked before returning; later event collections remain unparsed. Stored row presence does not establish an appearance or match completion. No attachment, game calls or live IDs are used."""
    return saved_match_statistics.get_player_statistics(
        filename, fixture_key, person_index, expected_snapshot_id=expected_snapshot_id)


@mcp.tool(annotations=READ)
def fm_list_saved_match_event_streams(filename: str, expected_snapshot_id: str) -> dict[str, Any]:
    """List the matches whose full event record a saved career holds, without the game running. The game saves its retained full-detail matches (your team's recent matches and the matches it kept for opponent analysis, some of them years old) with every pass, shot and duel event. Each stream gives its date, the native id of the team it is filed under, its event count, counted pass attempts and throw-ins. Use a filename from fm_list_saved_careers and its snapshot_id. Then find the fixture with fm_find_saved_fixture_results for that team and date and call fm_get_saved_match_passes with its archive_key; for a stream whose match has no stored statistics frame, pass the stream's date and owner_team_native_id instead. The same match can be listed twice when two lists keep it. Absence of a match here means the save holds no event record for it, not that no passes were played."""
    return saved_match_events.list_saved_match_event_streams(filename, expected_snapshot_id=expected_snapshot_id)


@mcp.tool(annotations=READ)
def fm_get_saved_match_passes(
    filename: str,
    expected_snapshot_id: str,
    fixture_key: Annotated[int | None, Field(strict=True, ge=0, lt=2**31)] = None,
    match_date: str | None = None,
    owner_team_native_id: Annotated[int | None, Field(strict=True, ge=-2**31, lt=2**31)] = None,
    offset: Annotated[int, Field(strict=True, ge=0)] = 0,
    limit: Annotated[int, Field(strict=True, ge=1, le=500)] = 100,
    include_throw_ins: Annotated[bool, Field(strict=True)] = True,
) -> dict[str, Any]:
    """Read every pass of one stored match from a saved career, without the game running: passer, receiver of a completed pass, outcome (completed, intercepted, blocked, out_of_play, not_completed_other), who won the ball, displayed minute and second, where the pass started and ended, restart (throw_in, corner, free_kick) and the game's key-pass, chance-created and assist markers. Select by fixture_key (the archive_key from fm_find_saved_fixture_results): rows are then bound to PERSON indices of this save and published only when every stored player's passes attempted and completed equal the event record; side_coverage shows both totals. For a stream from fm_list_saved_match_event_streams with no stored statistics frame, pass match_date and owner_team_native_id instead: rows then carry a side and a player slot, no PERSON, and are not checked against counters. Throw-ins are returned with counted=false because the game leaves them out of pass counts. A failed pass has no stored intended recipient. Markers can be missing: false does not show a pass was not a key pass. Page with next_offset and the same selectors. Name PERSON indices with fm_get_saved_person_name_candidates. Values describe the match as stored in this file."""
    return saved_match_events.get_saved_match_passes(
        filename, fixture_key, expected_snapshot_id=expected_snapshot_id, match_date=match_date,
        owner_team_native_id=owner_team_native_id, offset=offset, limit=limit, include_throw_ins=include_throw_ins)


@mcp.tool(annotations=READ)
def fm_get_saved_match_crosses(
    filename: str,
    expected_snapshot_id: str,
    fixture_key: Annotated[int | None, Field(strict=True, ge=0, lt=2**31)] = None,
    match_date: str | None = None,
    owner_team_native_id: Annotated[int | None, Field(strict=True, ge=-2**31, lt=2**31)] = None,
    offset: Annotated[int, Field(strict=True, ge=0)] = 0,
    limit: Annotated[int, Field(strict=True, ge=1, le=500)] = 100,
) -> dict[str, Any]:
    """Read every cross of one stored match from a saved career, without the game running: crosser, whether it was completed, receiver of a completed cross, outcome (completed, intercepted, blocked, out_of_play, not_completed_other), the opposing player the cross ended at, displayed minute and second, where it was played from and where the ball path ended, restart (corner, free_kick) and the game's key-pass, chance-created and assist markers. Select by fixture_key (the archive_key from fm_find_saved_fixture_results): rows are then bound to PERSON indices of this save and published only when every stored player's crosses attempted and completed equal the event record; side_coverage shows both totals, outcome counts and crosses from corners and free kicks. For a stream from fm_list_saved_match_event_streams with no stored statistics frame, pass match_date and owner_team_native_id instead: rows then carry a side and a player slot, no PERSON, and are not checked against counters. Only completed is the game's own category; the failure types are named from where the stored ball path ends. Markers can be missing: false does not show a cross created no chance. Page with next_offset and the same selectors. Name PERSON indices with fm_get_saved_person_name_candidates. Values describe the match as stored in this file."""
    return saved_match_events.get_saved_match_crosses(
        filename, fixture_key, expected_snapshot_id=expected_snapshot_id, match_date=match_date,
        owner_team_native_id=owner_team_native_id, offset=offset, limit=limit)


@mcp.tool(annotations=READ)
def fm_get_saved_match_shots(
    filename: str,
    expected_snapshot_id: str,
    fixture_key: Annotated[int | None, Field(strict=True, ge=0, lt=2**31)] = None,
    match_date: str | None = None,
    owner_team_native_id: Annotated[int | None, Field(strict=True, ge=-2**31, lt=2**31)] = None,
    offset: Annotated[int, Field(strict=True, ge=0)] = 0,
    limit: Annotated[int, Field(strict=True, ge=1, le=500)] = 100,
) -> dict[str, Any]:
    """Read every shot of one stored match from a saved career, without the game running: shooter, outcome (goal, missed_target, hit_woodwork, saved, blocked), on_target, expected goals, head or feet, penalty, direct free kick, displayed minute and second, where the shot was taken, the game's shot-map zone and where the ball path ended. own_goals lists own goals apart; they are not shots. Select by fixture_key (the archive_key from fm_find_saved_fixture_results): rows are then bound to PERSON indices of this save and published only when every stored player's shots and shots on target, and both stored team totals, equal the event record; side_coverage shows the totals, outcome counts and whether the summed expected goals equal the stored team value. For a stream from fm_list_saved_match_event_streams with no stored statistics frame, pass match_date and owner_team_native_id instead: rows then carry a side and a player slot, no PERSON, and are not checked against counters. A shot can have no stored shot record; its expected_goals is then null and side_coverage counts it. Page with next_offset and the same selectors. Name PERSON indices with fm_get_saved_person_name_candidates. Values describe the match as stored in this file."""
    return saved_match_events.get_saved_match_shots(
        filename, fixture_key, expected_snapshot_id=expected_snapshot_id, match_date=match_date,
        owner_team_native_id=owner_team_native_id, offset=offset, limit=limit)


@mcp.tool(annotations=READ)
def fm_find_saved_fixture_results(
    filename: str,
    team_index: Annotated[int, Field(strict=True, ge=0, lt=2**31)],
    date_from: str,
    date_to: str,
    expected_snapshot_id: str,
    offset: Annotated[int, Field(strict=True, ge=0)] = 0,
    limit: Annotated[int, Field(strict=True, ge=1, le=500)] = 50,
    include_competition: Annotated[bool, Field(strict=True)] = False,
    include_historical: Annotated[bool, Field(strict=True)] = False,
) -> dict[str, Any]:
    """Search one exact pinned save for stored fixture/result rows containing a same-file TEAM_BASE index in either ordered side, with inclusive YYYY-MM-DD native stored Kick Off dates. No game session is required. Keep side order without assuming home/away roles, preserve duplicate serialized rows and page with identical selectors and pin. Normal-time, extra-time, penalties and aggregate score bytes remain separate; FF is unset and a bare FIXTURE has no RESULT score block. This does not establish completion, winner, actual played date or actual venue. Default coverage is retained base, initial and declared outer FIX_MAN groups; separate indexed historical storage is searched only with include_historical=true. Set include_competition=true for qualified same-file FIXTURE_NAME to COMP/STAGE_NAME joins; omitted names remain null and structural placement remains explicit. Empty retained results do not establish full-save absence."""
    return saved_fixture_query.find_fixture_results(
        filename, team_index, date_from, date_to, expected_snapshot_id=expected_snapshot_id,
        offset=offset, limit=limit, include_competition=include_competition,
        include_historical=include_historical,
    )



@mcp.tool(annotations=READ)
def fm_find_saved_currencies(
    filename: str, name: Annotated[str | None, Field(min_length=1, max_length=256)] = None,
    native_id: Annotated[int | None, Field(strict=True, ge=0, le=4294967295)] = None,
    include_history: Annotated[bool, Field(strict=True)] = False,
    offset: Annotated[int, Field(strict=True, ge=0)] = 0,
    limit: Annotated[int, Field(strict=True, ge=1, le=500)] = 50,
    expected_snapshot_id: str | None = None,
) -> dict[str, Any]:
    """Find currencies in a named saved file without attaching. Combine an exact native ID and a case-insensitive substring of the primary stored name. Current and optional historical rates are stored currency units per GBP. History retains every stored entry in native order, including duplicate years. Pass next_offset and expected_snapshot_id for later pages. Reduce the page size if the selected histories exceed the response budget."""
    return saved_world_search.find_currencies(filename, name=name, native_id=native_id,
                                              include_history=include_history, offset=offset, limit=limit,
                                              expected_snapshot_id=expected_snapshot_id)


@mcp.tool(annotations=READ)
def fm_status() -> dict[str, Any]:
    """Discover running FM26/FM27 games and supported capabilities without requesting memory access. game_build says which game build the reader addresses and, on a build other than the verified one, which tools are unavailable there and why."""
    out = bridge.status()
    out["game_build"] = _address_book.report(_address_book.tool_functions(mcp))
    return out


@mcp.tool(annotations=READ)
def fm_attach(pid: Annotated[int | None, Field(ge=1, le=2147483647)] = None) -> dict[str, Any]:
    """Verify read access and create a fresh session. macOS may request Developer Tools Access authentication."""
    return bridge.attach(pid)


@mcp.tool(annotations=READ)
def fm_search_text(
    session_id: str,
    texts: Annotated[list[str], Field(min_length=1, max_length=8)],
    max_mib: Annotated[int, Field(ge=1, le=1024)] = 256,
    max_matches: Annotated[int, Field(ge=1, le=100)] = 20,
    cursor: str | None = None,
) -> dict[str, Any]:
    """Find exact UTF-8/UTF-16LE text in private writable game memory. Use next_cursor with identical texts to continue a byte-limited search. Missing matches never prove absence."""
    return bridge.search(session_id, texts, max_mib, max_matches, cursor)


@mcp.tool(annotations=READ)
def fm_read_anchor(
    session_id: str, anchor_id: str,
    before: Annotated[int, Field(ge=0, le=256)] = 32,
    after: Annotated[int, Field(ge=0, le=512)] = 96,
) -> dict[str, Any]:
    """Read a bounded byte window around a discovered anchor and reject it if the original text changed. Research bytes have no verified field layout."""
    return bridge.read_anchor(session_id, anchor_id, before, after)


@mcp.tool(annotations=READ)
def fm_find_players(
    session_id: str, name: Annotated[str, Field(min_length=3, max_length=128)],
    max_mib: Annotated[int, Field(ge=1, le=1024)] = 256,
    max_matches: Annotated[int, Field(ge=1, le=100)] = 20,
    cursor: str | None = None,
) -> dict[str, Any]:
    """Research fallback: scan writable memory for regular players by full/common name. Prefer fm_find_save_players for current-save membership. Virtual players are available through squad tools. Returns name, birth date and 36 outfield attributes. Continue byte-limited scans with next_cursor and identical name. Empty results do not prove absence; matches may be retained objects. Non-ASCII spelling is exact; ASCII is case-insensitive."""
    return bridge.find_players(session_id, name, max_mib, max_matches, cursor)


@mcp.tool(annotations=READ)
def fm_get_database_catalog(session_id: str, include_auxiliary: bool = False) -> dict[str, Any]:
    """Count records in typed live database tables, including people, clubs, national-team containers, teams, competitions, nations, continents, cities, languages, local regions, weather records, stadiums, player types, currencies, injuries, fixture names and stage names. Counts include multiple subtypes and retired records; they do not mean all records or fields are decoded. Fixture-name records are not individual fixtures. include_auxiliary adds independently typed resident history/starting table instances, preserving duplicate types and empty vectors; empty does not mean no career history elsewhere, and no record fields are decoded. Static-only types are excluded. Binds to the loaded career and rechecks table headers."""
    return bridge.get_database_catalog(session_id, include_auxiliary=include_auxiliary)


@mcp.tool(annotations=READ)
def fm_find_save_players(
    session_id: str, name: Annotated[str, Field(min_length=3, max_length=128)],
    max_matches: Annotated[int, Field(ge=1, le=100, strict=True)] = 20,
    record_budget: Annotated[int, Field(ge=1, le=200000, strict=True)] = 200000,
    cursor: str | None = None,
) -> dict[str, Any]:
    """Find regular players and players with staff roles in the loaded save by full or common name. Returns names, DOB, 36 outfield attributes and references that recheck table membership. Searches at most record_budget people and returns max_matches; continue every next_cursor with identical name. Counts skipped staff-only/retired/virtual types explicitly. Missing name components are allowed; records with no name appear in unavailable_name_records. ASCII case-insensitive substring; non-ASCII spelling is exact. An empty page is not proof of absence. Use squad tools for materialized virtual players."""
    return bridge.find_save_players(session_id, name, max_matches, record_budget, cursor)


@mcp.tool(annotations=READ)
def fm_query_save_players(
    session_id: str,
    minimum_attributes: dict[str, Annotated[int, Field(ge=0, le=20, strict=True)]] | None = None,
    maximum_attributes: dict[str, Annotated[int, Field(ge=0, le=20, strict=True)]] | None = None,
    minimum_profile: dict[str, Annotated[int, Field(ge=0, le=200, strict=True)]] | None = None,
    maximum_profile: dict[str, Annotated[int, Field(ge=0, le=200, strict=True)]] | None = None,
    born_on_or_after: str | None = None, born_on_or_before: str | None = None,
    name_contains: str | None = None,
    max_matches: Annotated[int, Field(ge=1, le=100, strict=True)] = 20,
    record_budget: Annotated[int, Field(ge=1, le=200000, strict=True)] = 200000,
    cursor: str | None = None,
) -> dict[str, Any]:
    """Search all regular and combined player/staff records by inclusive attribute/profile bounds and optional YYYY-MM-DD birth-date bounds. Profile keys: ability.current/potential (0–200), positions.*, goalkeeping.*, hidden_attributes.*, feet.left/right and personality.* (0–20). Example: born_on_or_after='2010-01-01', minimum_profile={'ability.potential':170,'positions.striker':15}, minimum_attributes={'pace':15}. Returns full profiles and checked player_refs in database order, not a global ranking. Unknown required fixed potential appears under unclassified_players and counts toward max_matches. Continue every next_cursor with identical criteria/name, even after empty pages, to cover the table. Virtual/retired/staff-only types are counted but excluded. Matching records with no name appear in unavailable_name_records. Stored unmasked ratings do not establish scouting visibility, current age, transfer availability, price or interest. No game actions occur."""
    return bridge.query_save_players(session_id, minimum_attributes, maximum_attributes, minimum_profile,
        maximum_profile, born_on_or_after, born_on_or_before, name_contains, max_matches, record_budget, cursor)


@mcp.tool(annotations=READ)
def fm_find_clubs(
    session_id: str, name: Annotated[str, Field(min_length=3, max_length=128)],
    max_matches: Annotated[int, Field(ge=1, le=100, strict=True)] = 20,
    record_budget: Annotated[int, Field(ge=1, le=200000, strict=True)] = 200000,
    cursor: str | None = None,
) -> dict[str, Any]:
    """Find ordinary clubs in the live club table by full or short name, with club_ref for fm_get_club_squads. Names may be shared by different clubs; inspect returned squads to select the intended one. League-body club records are counted but not decoded. Continue every next_cursor with identical name after either limit. ASCII case-insensitive substring; non-ASCII spelling is exact."""
    return bridge.find_clubs(session_id, name, max_matches, record_budget, cursor)


@mcp.tool(annotations=READ)
def fm_find_weather_profiles(session_id: str, name: str | None = None,
                             native_id: Annotated[int, Field(strict=True, ge=1, le=4294967295)] | None = None,
                             max_matches: Annotated[int, Field(strict=True, ge=1, le=100)] = 20,
                             record_budget: Annotated[int, Field(strict=True, ge=1, le=1000)] = 1000,
                             cursor: str | None = None) -> dict[str, Any]:
    """Search stored weather profiles by Unicode case-insensitive name substring and/or native ID, or enumerate all records. Returns weather_ref and four periods in native order, stored start days and wind/precipitation/temperature weights. Editor temperature labels are not verified runtime generation intervals. Preserve raw weights and totals without normalization. Day/night variance 100 is unspecified; other values retain an unverified unit. No forecast, current conditions, season names or calendar conversion. Follow every next_cursor with identical selectors, including empty pages. Max 100 matches/1000 examined records; read-only with consumed-byte rechecks."""
    return bridge.find_weather_profiles(session_id,name,native_id,max_matches,record_budget,cursor)


@mcp.tool(annotations=READ)
def fm_get_weather_profile(session_id: str, weather_ref: str) -> dict[str, Any]:
    """Refresh a stored weather profile from weather search or a city/region weather_ref. Rechecks native identity and canonical membership; ordinary names and four period values refresh. Save/build changes, identity replacement, detach and cache eviction expire references. Preserves unknown units, native start days and unspecified variance; no forecast or current conditions. To find direct stored relationships, use fm_find_cities or fm_find_local_regions with weather_native_id and follow all cursors. No city/region fallback is inferred."""
    return bridge.get_weather_profile(session_id,weather_ref)


@mcp.tool(annotations=READ)
def fm_find_media_sources(session_id: str, name: str | None = None,
                          native_id: Annotated[int, Field(strict=True, ge=1, le=4294967295)] | None = None,
                          max_matches: Annotated[int, Field(strict=True, ge=1, le=100)] = 20,
                          record_budget: Annotated[int, Field(strict=True, ge=1, le=1000)] = 1000,
                          cursor: str | None = None) -> dict[str, Any]:
    """Find press outlets by stored name substring or native ID, or enumerate the active career's media sources. Returns stored publication period, geographic scope and links, style and press conference flag. Read all cursors with the same filters for complete coverage. Actual conference attendance and published stories are separate."""
    return bridge.find_media_sources(session_id, name, native_id, max_matches, record_budget, cursor)


@mcp.tool(annotations=READ)
def fm_get_media_source(session_id: str, media_source_ref: str) -> dict[str, Any]:
    """Refresh one named press outlet and its stored fields using the reference returned by fm_find_media_sources."""
    return bridge.get_media_source(session_id, media_source_ref)


@mcp.tool(annotations=READ)
def fm_find_languages(session_id: str, name: str | None = None,
                       native_id: Annotated[int, Field(strict=True, ge=1, le=4294967295)] | None = None,
                       nation: str | None = None,
                       nation_native_id: Annotated[int, Field(strict=True, ge=1, le=4294967295)] | None = None,
                       maximum_difficulty: Annotated[int, Field(strict=True, ge=0, le=20)] | None = None,
                       minimum_influence: Annotated[int, Field(strict=True, ge=0, le=20)] | None = None,
                       is_deleted: Annotated[bool, Field(strict=True)] | None = None,
                       max_matches: Annotated[int, Field(strict=True, ge=1, le=100)] = 20,
                       record_budget: Annotated[int, Field(strict=True, ge=1, le=1000)] = 1000,
                       cursor: str | None = None) -> dict[str, Any]:
    """Search stored languages or enumerate all records. Name and nation use Unicode case-insensitive substrings; nation matches its stored short name/abbreviation. All selectors combine. Returns language_ref, stored nation, family/group/subgroup codes and editor labels, influence and difficulty. Preserve unknown classification codes; DELE means native family == -1. Ratings do not predict learning time or player fluency. Follow every next_cursor with identical selectors, including empty pages. Native database order; up to 100 matches and 1000 examined records. Non-atomic, read-only with consumed-byte rechecks."""
    return bridge.find_languages(session_id,name,native_id,nation,nation_native_id,maximum_difficulty,
                                 minimum_influence,is_deleted,max_matches,record_budget,cursor)


@mcp.tool(annotations=READ)
def fm_get_language(session_id: str, language_ref: str) -> dict[str, Any]:
    """Refresh a language from language search, a city's direct language link or a region language entry. Rechecks native identity and canonical table membership; ordinary names, ratings and nation links refresh. Save/build changes, identity replacement, detach and cache eviction expire references. Returns stored classifications and ratings, not fluency or learning outcomes. Preserve unmapped codes."""
    return bridge.get_language(session_id,language_ref)


@mcp.tool(annotations=READ)
def fm_find_local_regions(session_id: str, name: str | None = None,
                           native_id: Annotated[int, Field(strict=True, ge=1, le=4294967295)] | None = None,
                           nation: str | None = None,
                           nation_native_id: Annotated[int, Field(strict=True, ge=1, le=4294967295)] | None = None,
                           minimum_population: Annotated[int, Field(strict=True, ge=0, le=2147483647)] | None = None,
                           max_matches: Annotated[int, Field(strict=True, ge=1, le=100)] = 20,
                           record_budget: Annotated[int, Field(strict=True, ge=1, le=1000)] = 1000,
                           cursor: str | None = None,
                           weather_native_id: Annotated[int, Field(strict=True, ge=1, le=4294967295)] | None = None) -> dict[str, Any]:
    """Search stored local regions or enumerate all records. Unicode case-insensitive name/nation substrings; nation matches stored short name/abbreviation. All selectors combine, including the direct stored weather_native_id. Returns local_region_ref, nation/weather summaries with usable weather_ref values, stored population and complete language entries with usable language_ref values. Population freshness is unverified; zero remains stored. Percentages may sum above 100: preserve entries and never normalize. Null/duplicate languages and out-of-range percentages remain explicit. Weather identifies a record, not current conditions. Use fm_find_cities(local_region_native_id=...) for the reverse city relationship. Follow all cursors with identical selectors, including empty pages; max 100 matches/1000 examined records. Read-only, non-atomic."""
    return bridge.find_local_regions(session_id,name,native_id,nation,nation_native_id,minimum_population,
                                     max_matches,record_budget,cursor,weather_native_id)


@mcp.tool(annotations=READ)
def fm_get_local_region(session_id: str, local_region_ref: str) -> dict[str, Any]:
    """Refresh a local region from search or a city's local_region_ref. Identity and canonical membership are rechecked; population, nation/weather links and language entries refresh. Child language references bind independently to their target records. Language vectors are complete or rejected, with at most 1000 allocated entries. Percentages retain their stored values even above/below 0–100; do not normalize totals. For member cities, call fm_find_cities(local_region_native_id=region.native_id) and follow every cursor. Local-region deletion and current population/weather are not established."""
    return bridge.get_local_region(session_id,local_region_ref)


@mcp.tool(annotations=READ)
def fm_find_cities(session_id: str, name: str | None = None,
                   native_id: Annotated[int, Field(strict=True, ge=1, le=4294967295)] | None = None,
                   nation: str | None = None,
                   nation_native_id: Annotated[int, Field(strict=True, ge=1, le=4294967295)] | None = None,
                   minimum_attraction: Annotated[int, Field(strict=True, ge=0, le=20)] | None = None,
                   is_deleted: Annotated[bool, Field(strict=True)] | None = None,
                   max_matches: Annotated[int, Field(strict=True, ge=1, le=100)] = 20,
                   record_budget: Annotated[int, Field(strict=True, ge=1, le=1000)] = 1000,
                   cursor: str | None = None,
                   local_region_native_id: Annotated[int, Field(strict=True, ge=1, le=4294967295)] | None = None,
                   language_native_id: Annotated[int, Field(strict=True, ge=1, le=4294967295)] | None = None,
                   weather_native_id: Annotated[int, Field(strict=True, ge=1, le=4294967295)] | None = None) -> dict[str, Any]:
    """Search stored city records or enumerate the table. Name and nation use Unicode case-insensitive substrings; nation matches stored short name or abbreviation. All selectors combine, including native IDs, minimum stored attraction and the DELE flag. local_region_native_id selects the native reverse region/city relationship; language_native_id filters only the direct stored language link, with no regional fallback. Returns city_ref, stored name, coordinates, population category, attraction and checked nation/language/local-region/weather summaries. Language, local-region and weather summaries carry references for their detail tools. weather_native_id selects only the direct stored weather link. Altitude keeps its native integer with unit null and state unit_unverified. Population is a stored range category, not current population; weather is a database-record link, not current conditions. Continue every next_cursor with identical selectors, including empty pages. Max 100 matches and 1000 examined records per call, in native database order. Reads are non-atomic; no native getters execute."""
    return bridge.find_cities(session_id,name,native_id,nation,nation_native_id,minimum_attraction,
                              is_deleted,max_matches,record_budget,cursor,local_region_native_id,language_native_id,weather_native_id)


@mcp.tool(annotations=READ)
def fm_get_city(session_id: str, city_ref: str) -> dict[str, Any]:
    """Refresh a city from fm_find_cities or a stadium's city_ref. Rechecks type, canonical membership and native identity. Ordinary fields and geographic links refresh; replaced identities, changed saves/builds, detach and cache eviction expire references. Returns stored fields and linked geographic identities/names, with language_ref and local_region_ref for detailed queries. Use weather_ref with fm_get_weather_profile for stored profile periods. Preserve null, unknown enum and invalid-coordinate states; altitude's physical unit remains unverified. Read-only with consumed-byte rechecks."""
    return bridge.get_city(session_id,city_ref)


@mcp.tool(annotations=READ)
def fm_find_stadiums(session_id: str, name: str | None = None,
                     native_id: Annotated[int, Field(strict=True, ge=1, le=4294967295)] | None = None,
                     minimum_capacity: Annotated[int, Field(strict=True, ge=0, le=2147483647)] | None = None,
                     is_extinct: Annotated[bool, Field(strict=True)] | None = None,
                     is_training_ground: Annotated[bool, Field(strict=True)] | None = None,
                     max_matches: Annotated[int, Field(strict=True, ge=1, le=100)] = 20,
                     record_budget: Annotated[int, Field(strict=True, ge=1, le=1000)] = 1000,
                     cursor: str | None = None) -> dict[str, Any]:
    """Search stored stadium names and continental names, or enumerate all records. Unicode case-insensitive substrings; all filters combine. minimum_capacity applies to stored total capacity. Extinct/training-ground filters use native flags, not match suitability. Return stadium_ref plus stored capacities, coordinates, pitch fields, facility flags and dates. Used/all-seater capacities <=0 are unspecified; zero seating remains stored. Dates preserve native years, including future/outliers. Pitch dimensions keep separate default/international/minimum/maximum values with native_tenths; values are metres decoded from native tenths. Covered is a stored flag, not current roof state. Names omit contextual/generated formatting. Continue every next_cursor with identical filters, including empty pages; limits may change. Native database order, max 100 matches and 1000 scanned records per call. City, owner_club and nearby_stadium are nullable stored links with references for fm_get_city, club tools and fm_get_stadium. Nearby stadiums are summaries; cycles do not expand recursively. These links do not establish legal ownership, groundsharing or match allocation. Stadium substructures remain unfinished."""
    return bridge.find_stadiums(session_id,name,native_id,minimum_capacity,is_extinct,is_training_ground,
                               max_matches,record_budget,cursor)


@mcp.tool(annotations=READ)
def fm_get_stadium(session_id: str, stadium_ref: str) -> dict[str, Any]:
    """Refresh a stadium selected by fm_find_stadiums or a fixture's stadium reference. Rechecks typed canonical membership and native identity before returning stored names, capacities, coordinates, pitch fields, flags and dates. City, owner_club and nearby_stadium links carry usable references and refresh independently of the parent identity. Nearby links remain summaries, including cycles. Stored owner-club links do not establish legal ownership. Values can refresh between calls; replaced records, changed saves/builds and detach expire the reference. Preserve null and unknown states. No attendance, availability, match suitability, contextual pitch selection or roof-state calculation is established. Read-only with consumed-byte rechecks; no native function execution."""
    return bridge.get_stadium(session_id,stadium_ref)


@mcp.tool(annotations=READ)
def fm_find_currencies(session_id: str, name: str | None = None,
                       native_id: Annotated[int, Field(strict=True, ge=1, le=4294967295)] | None = None,
                       max_matches: Annotated[int, Field(strict=True, ge=1, le=100)] = 20,
                       record_budget: Annotated[int, Field(strict=True, ge=1, le=1000)] = 1000,
                       cursor: str | None = None) -> dict[str, Any]:
    """Enumerate stored currency records or combine a Unicode case-insensitive name substring and exact native ID. Returns currency_ref, stored name and current stored exchange rate in currency units per GBP. These are game rates, not real-world quotes. A record does not establish UI selectability or an ISO code. Names omit contextual localization. Continue every next_cursor with identical selectors, including empty pages; limits may change. Native database order, at most 100 matches and 1000 examined records per call. Use fm_get_currency for the complete stored historical year/rate vector and additional text fields; use fm_convert_currency for arithmetic on current stored rates. Non-atomic read-only query with consumed-byte rechecks."""
    return bridge.find_currencies(session_id, name, native_id, max_matches, record_budget, cursor)


@mcp.tool(annotations=READ)
def fm_get_currency(session_id: str, currency_ref: str) -> dict[str, Any]:
    """Refresh a currency reference from fm_find_currencies. Returns stored name, rate, identity, complete historical year/rate entries and three additional serialized text fields whose meanings remain unverified. History retains native order, duplicate years, zero rates and invalid years; no interpolation is applied. Rates are game currency units per GBP. Non-finite floats return null values and their original bits. Unmapped strings are research data; do not label them ISO codes or formatter prefixes/suffixes. Native names can differ from localized UI names. Rechecks typed canonical membership and identity; ordinary fields refresh. Changed saves/builds, replaced records, detach and cache eviction expire references. Read-only with consumed-byte rechecks."""
    return bridge.get_currency(session_id, currency_ref)


@mcp.tool(annotations=READ)
def fm_convert_currency(session_id: str,
                         amount: Annotated[str, Field(pattern=r'^-?(?:0|[1-9][0-9]{0,17})(?:\.[0-9]{1,18})?$')],
                         from_currency_ref: str, to_currency_ref: str) -> dict[str, Any]:
    """Convert an amount between two checked currency records using current stored game rates relative to GBP. Discover references with fm_find_currencies. amount is a plain decimal string, such as '1000000' or '-250.50', with at most 18 whole and 18 fractional digits. Returns a decimal string calculated as amount * to_rate / from_rate with 50 significant decimal digits. Reads and rechecks both current rates and the GBP basis together; stale parent identities fail. Zero, negative or non-finite rates return unavailable_rate and a null converted amount. This is stored-rate arithmetic, not real-world FX, historical conversion, native display rounding or proof that an offer fits a budget. Keep the result's currency explicit; existing budget tools accept GBP."""
    return bridge.convert_currency(session_id, amount, from_currency_ref, to_currency_ref)


@mcp.tool(annotations=READ)
def fm_find_stadium_changes(session_id: str,
                            native_id: Annotated[int, Field(strict=True, ge=1, le=4294967295)] | None = None,
                            team_native_id: Annotated[int, Field(strict=True, ge=1, le=4294967295)] | None = None,
                            stadium_native_id: Annotated[int, Field(strict=True, ge=1, le=4294967295)] | None = None,
                            type_code: Annotated[int, Field(strict=True, ge=-128, le=127)] | None = None,
                            max_matches: Annotated[int, Field(strict=True, ge=1, le=100)] = 20,
                            record_budget: Annotated[int, Field(strict=True, ge=1, le=1000)] = 1000,
                            cursor: str | None = None) -> dict[str, Any]:
    """Enumerate stored stadium-change records or combine native ID, direct team ID, stadium ID and type-code filters. stadium_native_id matches current, new or alternative stadium; discover IDs with fm_find_stadiums. Null team/current stadium does not hide a record. Returns stadium_change_ref, checked team_ref for fm_get_team_squad and stadium_ref links for fm_get_stadium. Includes separate start/leave/latest-move dates, capacities, attendance estimates, facility levels, condition and potential-move flag. Type 2 remains unmapped. Signed -1 is unspecified; zero remains stored. Rental cash, future development fund and expected season tickets retain raw values with unknown units/scales. Do not convert them to currency or ticket counts. Move likelihood is not a verified probability. These records do not establish project activity, completion, an effective ground or a construction schedule. Native table order; follow every next_cursor with identical selectors, including empty pages. Page limits may change. Read-only, non-atomic, consumed-byte rechecked."""
    return bridge.find_stadium_changes(session_id, native_id, team_native_id, stadium_native_id,
                                       type_code, max_matches, record_budget, cursor)


@mcp.tool(annotations=READ)
def fm_get_stadium_change(session_id: str, stadium_change_ref: str) -> dict[str, Any]:
    """Refresh a stadium-change reference from fm_find_stadium_changes. Recheck native type, getter, canonical membership and identity before returning current stored fields and nullable team/stadium references. Fields and links refresh independently of parent identity; each child reference remains bound to its own record. Preserve unknown types, raw monetary/season-ticket units and separate date meanings. No active/completed status or effective allocation is inferred. Save/build changes, replaced identity, detach and cache eviction expire references. Read-only with consumed-byte rechecks."""
    return bridge.get_stadium_change(session_id, stadium_change_ref)


@mcp.tool(annotations=READ)
def fm_find_competitions(
    session_id: str, name: Annotated[str | None, Field(min_length=1, max_length=128)] = None,
    native_id: Annotated[int | None, Field(ge=1, le=4294967295, strict=True)] = None,
    max_matches: Annotated[int, Field(ge=1, le=100, strict=True)] = 20,
    record_budget: Annotated[int, Field(ge=1, le=1000, strict=True)] = 1000,
    cursor: str | None = None,
    nation: Annotated[str | None, Field(min_length=1, max_length=128)] = None,
    continent: Annotated[str | None, Field(min_length=1, max_length=128)] = None,
    type_code: Annotated[int | None, Field(ge=-128, le=127, strict=True)] = None,
    gender: Literal['male', 'female'] | None = None,
    is_extinct: Annotated[bool | None, Field(strict=True)] = None,
) -> dict[str, Any]:
    """Search stored competition names/short names/abbreviations, or match a native_id from a loan condition. All selectors combine; omit them to enumerate every record, including unnamed ones. nation matches the stored nation short name or abbreviation, continent matches its name or abbreviation; string filters use Unicode case-insensitive substrings. type_code matches the native enum (0 top division, 1 division, 2 main cup, 3 league cup, 21 club champions cup; -1 unspecified). gender selects male/female; is_extinct matches the stored flag, not current-season activity. Returns checked competition_ref, native_id, random_id (null when equal to native_id, otherwise the stored value) and context: nation, continent, parent competition, reputation, native level, type and gender with explicit unmapped states. Continue every next_cursor with identical selectors, including after empty pages; limits may change. Records follow native database order. Stored names omit localization/generated formatting. Use fm_get_competition_teams for direct stored division assignments. Use fm_get_competition_stages and fm_get_standings for stored league tables. Use fm_find_fixtures for resident fixtures. Broader competition rules remain undecoded."""
    return bridge.find_competitions(session_id, name, native_id, max_matches, record_budget, cursor,
                                   nation, continent, type_code, gender, is_extinct)


@mcp.tool(annotations=READ)
def fm_get_fixture_coverage(session_id: str) -> dict[str, Any]:
    """List resident fixture calendar years and loaded/unavailable group counts. main_year is the fixture manager's stored year; use save.current_date for the current simulation calendar date. Missing years and unloaded archived groups are unavailable, not empty. Never forces data to load. Use fm_find_fixtures for each listed year; complete-save history and future schedule coverage remain unproven."""
    return bridge.get_fixture_coverage(session_id)


@mcp.tool(annotations=READ)
def fm_find_fixtures(
    session_id: str,
    year: Annotated[int | None, Field(ge=1, le=9999, strict=True)] = None,
    team_native_id: Annotated[int | None, Field(ge=1, le=4294967295, strict=True)] = None,
    competition_native_id: Annotated[int | None, Field(ge=1, le=4294967295, strict=True)] = None,
    date_from: str | None = None, date_to: str | None = None,
    record_kind: Literal['fixture', 'result'] | None = None,
    max_matches: Annotated[int, Field(ge=1, le=100, strict=True)] = 20,
    record_budget: Annotated[int, Field(ge=1, le=1000, strict=True)] = 1000,
    bucket_budget: Annotated[int, Field(ge=1, le=4096, strict=True)] = 4096,
    cursor: str | None = None,
    include_stage: Annotated[bool, Field(strict=True)] = False,
) -> dict[str, Any]:
    """Query materialized fixture groups by calendar year (default main_year from fm_get_fixture_coverage). Inclusive YYYY-MM-DD bounds must be within that year. All filters combine. team_native_id matches home or away; competition_native_id matches the stored fixture-name competition. IDs come from existing team/competition tools. record_kind selects native fixture/result objects, not verified upcoming/completed status. Returns date, days_from_current_date (calendar days relative to the response save.current_date), kickoff_time (time/state/native_code/timezone), teams with roster references, competition reference and stored normal-time/extra-time/penalty/aggregate score pairs; missing bytes are null. final_score uses extra time when stored, else normal time, excluding penalties. Continue every next_cursor with identical selectors, including empty pages; limits may change. Order is day then native group/slot, not kickoff time. Unloaded groups remain unavailable; end of scan does not establish whole-save coverage. Kickoff time is the native stored clock with timezone null (unknown); zero, unset-date and unmapped codes have null time and explicit states. include_stage adds stage_link with native season codes and an optional top-level stage. Different seasons, absent runtimes, invalid/missing slots and empty stages remain explicit. Use its stage_ref with fm_get_standings when standings_available is true. Keep include_stage identical across cursor pages. fixture_name is null when absent; otherwise it contains three stage_names slots (null or stored Name/Short Name/Plural Name with IDs) and an optional secondary_competition. These are stored naming components, not a generated display string or fixed stage/round/leg labels. Use the secondary competition native_id with fm_find_competitions. stadium is null for an absent stored venue, otherwise a checked identity/name with stadium_ref for fm_get_stadium. No group-child resolution, half-time scores or match events yet. Never executes game functions or loads archives."""
    return bridge.find_fixtures(session_id, year, team_native_id, competition_native_id, date_from, date_to,
                                record_kind, max_matches, record_budget, bucket_budget, cursor, include_stage)


@mcp.tool(annotations=READ)
def fm_get_match_data_columns() -> dict[str, Any]:
    """Historical formal starts and match completion remain not_decoded. Initial-participant candidates and duration flags must not be counted/ranked as actual starts, even with eleven candidates or reconciled minutes. List supported match-data columns, compact defaults and the conditional retained-shot lookup route without attaching, capturing, or reading the game. Use this for field discovery before fm_query_match_scope or fm_query_match_data."""
    return column_catalog()


@mcp.tool(annotations=READ)
def fm_query_match_scope(
    session_id: str,
    date_from: str,
    date_to: str,
    team_native_id: int | None = None,
    competition_native_id: int | None = None,
    tables: list[str] | None = None,
    fields: dict[str, list[str]] | None = None,
    limit: Annotated[int, Field(strict=True, ge=1, le=500)] = 500,
    cursor: str | None = None,
    include_youth_reserves: bool = False,
) -> dict[str, Any]:
    """Collect one explicit date/team/competition scope and project several tables from the same bounded historical capture. The same career may advance during collection; metadata records first/last observed save states and non-atomic windows. Select a native team ID or competition ID. Default tables fixtures+team_totals return compact identity/scores and shots/shots_on_target/expected_goals, avoiding player identity lookups. Request retained_players for names, minutes/goals/assists/rating, aggregate expected_goals and action counters; events preserve raw event codes. Request goal_crossings for credited-player goal-line endpoints with unresolved units/viewpoint (not all attempts); it requires player identity reads. Request sub_entry_context for source-policy-verified entry states, retaining unknown and same-minute ambiguous states. Player expected_assists is an aggregate; open-play xA is unavailable. Call fm_get_match_data_columns for free column discovery, then supply fields by table. Every row has {table,row}; counts account for all tables. Continue every next_cursor with identical selectors; pages share capture_id/collection metadata/observed_at, preserve the first captured_save, survive clock progression and expire after reload or five minutes. At most128 selected resident results; narrow selectors for larger scopes. Unknown coverage, result completion and unsupported spatial semantics stay explicit. No saved-file aliases, game writes or native execution."""
    return match_scope_queries.query(bridge, session_id, team_native_id, date_from, date_to,
                                    competition_native_id, tables, fields, limit, cursor, include_youth_reserves)


@mcp.tool(annotations=READ)
def fm_query_match_data(
    session_id: str,
    fixture_refs: list[str],
    table: Literal['fixtures', 'team_totals', 'events', 'player_matches', 'retained_players'],
    fields: list[str] | None = None,
    limit: Annotated[int, Field(strict=True, ge=1, le=500)] = 100,
    cursor: str | None = None,
) -> dict[str, Any]:
    """Historical formal starts and match completion remain not_decoded. Do not count initial-participant candidates/duration flags as actual starts or provide a fewest-starts ranking from them. Project a bounded selection of 1–64 live fixture_refs into structured rows for agent calculations. Obtain refs from fm_find_fixtures. Tables expose source-backed fields with coverage and raw source data; use fm_get_match_data_columns for capture-free column discovery and request explicit fields. Missing player/event captures remain explicitly unavailable. Compute arbitrary filters, comparisons and aggregations in codemode from returned rows. Follow next_cursor with identical fixture_refs, table and fields; pagination preserves the initial capture for five minutes and expires after a career reload. No game writes, native execution or caller-selected filesystem paths. Team side_index is native ordered side, not an inferred home/away label. Stored result data does not establish match completion."""
    return match_data_queries.query(bridge, session_id, fixture_refs, table, fields, limit, cursor)


@mcp.tool(annotations=READ)
def fm_get_fixture_rules(session_id: str, fixture_ref: str) -> dict[str, Any]:
    """Read one existing resident fixture's declared substitution caps and effective stored draw rules. Obtain fixture_ref from fm_find_fixtures or fm_get_next_match_squad. Returns separate home/away named and used substitute caps, native stoppage limit or explicit unavailable sentinel, and raw FxMR/FxSR rule fields. Supported simple draw patterns distinguish extra time, a penalty shootout after ninety minutes, a replay and no deciding flag; unfamiliar combinations keep raw flags and an unavailable combined decision. These are fixture-specific stored limits, not an individual eligibility or team-sheet confirmation check. Extra-time substitute additions and additional stage restrictions remain unknown. Rechecks canonical fixture bucket membership, identity, native helper code and all consumed bytes. No game functions, refreshes, UI or archive loads."""
    return bridge.get_fixture_rules(session_id, fixture_ref)


@mcp.tool(annotations=READ)
def fm_get_fixture(session_id: str, fixture_ref: str,
                   include_stage: Annotated[bool, Field(strict=True)] = False) -> dict[str, Any]:
    """Recheck a fixture returned by fm_find_fixtures, including year/group/day membership, record identity, teams and stored competition. Returns fresh scores, stored kickoff_time and days_from_current_date relative to the response save.current_date, plus team/competition references and an optional stadium reference for fm_get_stadium. Date progression refreshes the day difference without expiring an otherwise unchanged fixture reference. A changed route or identity expires the reference; repeat the search. Result-record presence does not establish completion. Kickoff clocks have no verified timezone; unknown time codes remain explicit. include_stage adds the same guarded top-level stage_link as fm_find_fixtures; use its stage_ref with fm_get_standings only when standings_available is true. fixture_name preserves stored naming components, including three stage_names slots and an optional secondary_competition; it does not reproduce localized display composition. Archived coverage remains partial."""
    return bridge.get_fixture(session_id, fixture_ref, include_stage)


@mcp.tool(annotations=READ)
def fm_get_competition_stages(session_id: str, competition_ref: str) -> dict[str, Any]:
    """List a competition's stored runtime stages and league children of group stages. Select a stage with standings_available=true and pass its stage_ref to fm_get_standings. Paths are zero-based slots, not named rounds. native_season_code is a stored discriminator, not a season date range. runtime_competition identifies the actual owner when competition records share runtime state. Absent runtime, null slots and empty vectors remain distinct; none prove no participants. Cup/cup-group contents, localized stage names, seasons, active/completed status remain undecoded. Use fm_find_fixtures for resident fixtures. Reads recheck types, owner membership and consumed bytes; references are session-bound. Enumerates at most 1,024 slots and rejects larger structures explicitly."""
    return bridge.get_competition_stages(session_id, competition_ref)


@mcp.tool(annotations=READ)
def fm_get_standings(session_id: str, stage_ref: str) -> dict[str, Any]:
    """Read a league stage selected by fm_get_competition_stages or a fixture stage_link with standings_available=true. Returns every native row with team/roster reference, stored position, overall/home/away played, wins, draws_or_penalty_wins, losses, penalty_losses, goals for/against/difference and points, plus point rules. Played can include games carried from earlier stages. Wins/losses exclude penalty decisions; draws_or_penalty_wins combines ordinary draws and penalty wins. Do not recalculate points or ranks from generic rules. Null team slots remain unassigned rows. Home/away figures retain overall row order. For an unmapped native sorting view, position is null and native_order_view_code remains explicit. Rechecks stage membership, teams and consumed bytes; fails without partial rows or new references on mutation. Stored order does not establish freshness, active season, finality or eligibility. Never executes game functions."""
    return bridge.get_standings(session_id, stage_ref)


@mcp.tool(annotations=READ)
def fm_get_competition_registrations(
    session_id: str, competition_ref: str,
    year: Annotated[int | None, Field(ge=1, le=65534, strict=True)] = None,
    max_matches: Annotated[int, Field(ge=1, le=100, strict=True)] = 100,
    record_budget: Annotated[int, Field(ge=1, le=1000, strict=True)] = 1000,
    cursor: str | None = None,
) -> dict[str, Any]:
    """Read the native Registered Teams list for a competition. Returns team identities and roster references, nation, stored year and registration_identifier (the editor’s Info field). Year 0/65535 and negative registration identifiers are unspecified; raw codes remain available. Optional year filters exact stored values, with no current-season inference. This list does not prove current cup/stage participation, player registration or eligibility. Null record slots are counted and skipped; duplicate teams remain separate records. Continue every next_cursor with the same competition_ref and year filter, including empty pages. Read-only, bounded, non-atomic."""
    return bridge.get_competition_registrations(session_id, competition_ref, year, max_matches, record_budget, cursor)


@mcp.tool(annotations=READ)
def fm_get_competition_teams(
    session_id: str, competition_ref: str,
    assignment: Literal['current', 'next', 'secondary', 'next_secondary'] = 'current',
    max_matches: Annotated[int, Field(ge=1, le=100, strict=True)] = 100,
    record_budget: Annotated[int, Field(ge=1, le=200000, strict=True)] = 200000,
    cursor: str | None = None,
) -> dict[str, Any]:
    """List direct stored competition assignments. Select current, next, secondary or next_secondary; next lists fall back to the corresponding current division when unset. Includes club and national teams, owner identities, optional random IDs and team_ref handles usable with fm_get_team_squad/fm_query_team_players. This is not cup/stage participation, registration or parent-competition aggregation. An empty list does not establish no participants. Continue every next_cursor with the same competition_ref and assignment, including empty pages. Native order, bounded non-atomic reads, no game function execution."""
    return bridge.get_competition_teams(session_id, competition_ref, assignment, max_matches, record_budget, cursor)


@mcp.tool(annotations=READ)
def fm_get_managed_league_age_exemptions(
    session_id: str, coach_name: str | None = None,
    include_registration: Annotated[bool, Field(strict=True)] = False,
) -> dict[str, Any]:
    """Check the native current Premier League age-exemption requirement for the managed club's Senior/U21/U18 rosters. Reports the bound competition, observation date and native cutoff. Includes every selected roster slot, preserving overlap; current PERSON team/club context is checked independently. Players currently at another club, unknown/unsupported age sources and unproved birthday branches remain explicit, not false. Other squad types are excluded and reported. Supports the pinned Premier League default rule3/empty-cutoff-override branch only; unsupported contexts are unavailable. Opt in include_registration for the exact current native PLAYER registration predicate D32054(mode1), bound to the current Premier League TEAM/season/rule/selector. Each row preserves committed25 versus temporary26/27 and unknown outside-club/virtual contexts. A native-false youth player can still be age-exempt; false is not an exclusion verdict. Marker historical season/submission date, complete official submitted population and full fixture clearance remain unknown. No game functions, refresh, generation, context creation or writes."""
    if include_registration:
        return bridge.get_managed_league_age_exemptions(
            session_id, coach_name, include_registration=True)
    return bridge.get_managed_league_age_exemptions(session_id, coach_name)


@mcp.tool(annotations=READ)
def fm_get_league_player_statistics(
    session_id: str, competition_ref: str,
    player_refs: Annotated[list[str], Field(min_length=1, max_length=100)],
) -> dict[str, Any]:
    """Compare exact current competition starting appearances, minutes and goals for 1–100 checked player_refs, such as an entire managed squad. Obtain competition_ref from fm_find_competitions and player_refs from live player or roster tools. Reads the complete COMP-owned resident PERSON counter pool once, then returns only requested players in input order, preserving duplicates. This does not substitute a primary player League category or infer that counters belong to the player's current club after transfers. A player absent from the resident pool has null counters and not_observed_in_resident_pool, never assumed zero. Unsupported/unavailable sources, raw signed anomalies and native season discriminator remain explicit. Starting appearances use the official competition enum45; no reconstructed fixture XI, completed-season or award/playing-eligibility claim. Stored compact virtual refs from available-policy rosters can be identity-checked without generating a profile. No UI, game calls, native refresh, sorting, creation or writes."""
    return bridge.get_league_player_statistics(session_id, competition_ref, player_refs)


@mcp.tool(annotations=READ)
def fm_rank_league_players(session_id: str, competition_ref: str,
                           sort_by: Literal['starting_appearances','minutes','goals'] = 'starting_appearances',
                           order: Literal['ascending','descending'] = 'ascending',
                           minutes_over: Annotated[int | None, Field(strict=True, ge=0, le=2147483647)] = None,
                           limit: Annotated[int, Field(strict=True, ge=1, le=100)] = 10,
                           page_size: Annotated[int, Field(strict=True, ge=1, le=100)] = 100,
                           cursor: str | None = None, source_pin: str | None = None) -> dict[str, Any]:
    """Rank starting_appearances, minutes or goals across every row of one exact current COMP-owned resident PERSON pool, including combined player/staff. Obtain competition_ref from fm_find_competitions. order is ascending or descending. minutes_over is optional and strictly greater than (1000 excludes exactly1000); no default minutes filter. limit1..100 selects the cutoff and every equal-value tie is retained. page_size1..100 bounds each response; follow next_cursor with the same selectors and returned source_pin. Each continuation rereads the full native source; changed source/save/identities invalidate the cursor. returned_complete becomes true only on the final page, including unknown/anomalous ledger rows. Starting appearances follow official competition enum45, not initial-participant/duration flags or a formal per-fixture XI. Raw signed starts/minutes and unsigned goals remain visible; anomalies are explicitly excluded when relevant to filtering/ordering. Unknown identities and valid0 stay distinct. Returns native season discriminator without calendar-season inference. No primary League category or current-club roster substitution; last TEAM is not attribution of all counts after transfers. This is complete resident-counter ranking, not a completed-season/completion/award-eligibility claim. No UI, game calls, native sort, refresh, creation or writes."""
    return bridge.rank_league_players(session_id,competition_ref,sort_by,order,minutes_over,limit,page_size,cursor,source_pin)


@mcp.tool(annotations=READ)
def fm_get_league_scorers(
    session_id: str, competition_ref: str,
    limit: Annotated[int, Field(strict=True, ge=1, le=50)] = 10,
) -> dict[str, Any]:
    """Rank the complete observed resident individual goal rows for a domestic league competition. Use an exact competition_ref from fm_find_competitions. Supports Domestic Top Division, Domestic Division and Domestic Other Division with their own current ACTUAL_COMP runtime; cups, shared and unsupported contexts remain unavailable. Reads the COMP-owned participant pool including contributors outside current rosters; no assists, per90 or minutes filter. Limit chooses at least that many positive scorers when present, including every cutoff tie. Returns compact goals, source/coverage counts and player_refs for supported identity drilldowns. Last associated TEAM is not each goal's club attribution. Native runtime season discriminator and observation date are explicit; generic rollover/reset and award eligibility/tiebreaks are not established. Missing resident tables are unavailable; valid empty tables are distinct. No native refresh, sort, creation or game writes."""
    return bridge.get_league_scorers(session_id, competition_ref, limit)


@mcp.tool(annotations=READ)
def fm_get_competition(session_id: str, competition_ref: str) -> dict[str, Any]:
    """Read a competition selected by fm_find_competitions, rechecking identity and table membership for it and linked geography/parent records. Returns stored names and context: nation, continent, parent competition, reputation, level, type, gender and extinct flag. Type/gender preserve unknown native codes; level is the native property value, including zero, and stored code 100 means unspecified. Parent context is not recursively expanded. Names omit localization; null and empty remain distinct. References are session-bound and may expire. Use fm_get_competition_teams for direct stored division assignments. Use fm_get_competition_stages and fm_get_standings for stored league tables. Use fm_find_fixtures for resident fixtures; broader rules and current activity remain undecoded. Never executes game functions."""
    return bridge.get_competition(session_id, competition_ref)


@mcp.tool(annotations=READ)
def fm_find_staff(
    session_id: str, name: Annotated[str, Field(min_length=3, max_length=128)],
    max_matches: Annotated[int, Field(ge=1, le=100, strict=True)] = 20,
    record_budget: Annotated[int, Field(ge=1, le=200000, strict=True)] = 200000,
    cursor: str | None = None,
) -> dict[str, Any]:
    """Search staff-only, human-manager and player/staff records by full or common name. Returns names, DOB and staff_ref. Search results omit ratings; request include_attributes on fm_get_staff. Counts other types and nameless records explicitly; they are not searched. Continue every next_cursor with identical name. ASCII case-insensitive; non-ASCII spelling is exact. Empty pages do not prove absence."""
    return bridge.find_staff(session_id, name, max_matches, record_budget, cursor)


@mcp.tool(annotations=READ)
def fm_query_club_staff(
    session_id: str,
    minimum_attributes: dict[str, Annotated[int, Field(ge=1, le=20, strict=True)]] | None = None,
    sort_by: str | None = None,
    limit: Annotated[int, Field(ge=1, le=100, strict=True)] = 20,
    coach_name: str | None = None, club_ref: str | None = None,
    job_contains: Annotated[str, Field(min_length=1, max_length=128)] | None = None,
    minimum_personality: dict[str, Annotated[int, Field(ge=0, le=20, strict=True)]] | None = None,
) -> dict[str, Any]:
    """Filter the selected club's native staff list by stored attribute minima and sort descending by one attribute. minimum_personality accepts adaptability, ambition, controversy, loyalty, pressure, professionalism, sportsmanship and temperament (0–20); sort_by also accepts personality.<name>. Use job_contains for a case-insensitive title substring, such as Physio or GK Coach. For example, attacking:15 and motivating:15 sorted by determination. Job filtering rejects unmapped titles. Returns checked staff refs, full match counts and truncation. Defaults to your club; club_ref and coach_name are mutually exclusive. Underlying ratings do not establish job suitability, availability, workload or coaching stars. Role/UI visibility suppression is not applied."""
    return bridge.query_club_staff(session_id, minimum_attributes, sort_by, limit, coach_name, club_ref, job_contains, minimum_personality)


@mcp.tool(annotations=READ)
def fm_query_club_staff_wages(
    session_id: str,
    minimum: Annotated[int, Field(ge=0, le=2147483647, strict=True)] = 0,
    maximum: Annotated[int, Field(ge=0, le=2147483647, strict=True)] | None = None,
    limit: Annotated[int, Field(ge=1, le=100, strict=True)] = 20,
    coach_name: str | None = None, club_ref: str | None = None,
) -> dict[str, Any]:
    """Rank checked club staff by stored weekly main-contract wage in GBP, highest first. Inclusive minimum/maximum bounds use GBP per week. Returns full counts, truncation, and sums before limiting. Defaults to your club. This is not a complete payroll or wage-budget query: bonuses, contributions and staff outside the checked native lists are excluded. UI currency and wage-period preferences are not applied."""
    return bridge.query_club_staff_wages(session_id, minimum, maximum, limit, coach_name, club_ref)


@mcp.tool(annotations=READ)
def fm_query_club_staff_contracts(
    session_id: str, expires_on_or_before: str,
    limit: Annotated[int, Field(ge=1, le=100, strict=True)] = 100,
    coach_name: str | None = None, club_ref: str | None = None,
) -> dict[str, Any]:
    """Find staff with verified fixed contract expiries on or before YYYY-MM-DD, earliest first. Defaults to your club. Basic contracts and computed dynamic expiry appear separately as unclassified_staff, never as confirmed nonmatches. Includes already expired dates; does not predict renewals or departures. Returns full match counts and truncation. Club staff coverage remains limited to the checked native vectors and team managers."""
    return bridge.query_club_staff_contracts(session_id, expires_on_or_before, limit, coach_name, club_ref)


@mcp.tool(annotations=READ)
def fm_get_club_staff(session_id: str, coach_name: str | None = None,
                      club_ref: str | None = None,
                      include_attributes: Annotated[bool, Field(strict=True)] = False,
                      include_job: Annotated[bool, Field(strict=True)] = False,
                      include_contract_dates: Annotated[bool, Field(strict=True)] = False,
                      include_wage: Annotated[bool, Field(strict=True)] = False,
                      include_contract_status: Annotated[bool, Field(strict=True)] = False,
                      include_contract_bonuses: Annotated[bool, Field(strict=True)] = False,
                      include_contract_terms: Annotated[bool, Field(strict=True)] = False) -> dict[str, Any]:
    """include_contract_terms adds the complete stored main-contract entry vector using fm_get_contract_terms semantics. include_contract_bonuses adds six stored main-contract cash bonuses in GBP: appearance, goals, assists, clean sheets, unused substitute and international caps. Absent entries differ from zero; basic contracts return unavailable and virtual players are unsupported. The bonus option alone excludes other clauses. Payment eligibility is not evaluated. Read and deduplicate three native club staff vectors plus team managers. Defaults to the active coach's club, or accepts club_ref from fm_find_clubs. coach_name and club_ref are mutually exclusive. Checks each person's live table membership and full/basic-contract club. Returns staff refs, names, DOB and contract club. include_attributes adds 23 stored staff ratings, 12 tendencies, four board ratings and eight personality ratings; role/UI visibility suppression is not applied. include_job adds the native role title with team scope. include_contract_dates adds joined, last_signed and expires dates with explicit fixed, computed and unavailable states. include_contract_status adds the current contract status label and native code, with explicit basic/unmapped states. Specialized league types and virtual-player status remain unsupported. include_wage adds the stored weekly main-contract amount in GBP; bonuses, contributions and UI formatting are excluded. Complete board/support coverage remains unverified. Unsupported records fail the whole query."""
    return bridge.get_club_staff(session_id, coach_name, club_ref, include_attributes, include_job, include_contract_dates, include_wage, include_contract_status, include_contract_bonuses, include_contract_terms)


@mcp.tool(annotations=READ)
def fm_get_staff(session_id: str, staff_ref: str,
                 include_club: Annotated[bool, Field(strict=True)] = False,
                 include_attributes: Annotated[bool, Field(strict=True)] = False,
                 include_job: Annotated[bool, Field(strict=True)] = False,
                 include_contract_dates: Annotated[bool, Field(strict=True)] = False,
                 include_wage: Annotated[bool, Field(strict=True)] = False,
                 include_contract_status: Annotated[bool, Field(strict=True)] = False,
                 include_contract_bonuses: Annotated[bool, Field(strict=True)] = False) -> dict[str, Any]:
    """include_contract_bonuses adds six stored main-contract cash bonuses in GBP: appearance, goals, assists, clean sheets, unused substitute and international caps. Absent entries differ from zero; basic contracts return unavailable and virtual players are unsupported. Use fm_get_contract_terms for further stored main-contract clauses; payment eligibility is not evaluated. Reread staff identity and optional full/basic-contract club, checking native table membership and ownership. Null contract pointers are explicit; unsupported contract types fail. include_attributes adds 23 stored staff ratings, 12 tendencies, four board ratings and eight personality ratings with native scaling. These may differ from role-filtered UI values. include_job adds the native role title and implies include_club. include_contract_dates adds joined, last_signed and expires dates with fixed/computed states and implies include_club; basic and dynamic expiry states are explicit. include_contract_status adds the current contract status label and native code, with explicit basic/unmapped states. Specialized league types and virtual-player status remain unsupported. include_wage adds the stored weekly main-contract amount in GBP and implies include_club. The wage field excludes bonuses; UI currency/period rounding is not applied. Rejects changed references; reattach after loading a save."""
    return bridge.get_staff(session_id, staff_ref, include_club, include_attributes, include_job, include_contract_dates, include_wage, include_contract_status, include_contract_bonuses)


@mcp.tool(annotations=READ)
def fm_get_player(session_id: str, player_ref: str,
                  include_clubs: Annotated[bool, Field(strict=True)] = False,
                  include_contract_dates: Annotated[bool, Field(strict=True)] = False,
                  include_wage: Annotated[bool, Field(strict=True)] = False,
                  include_contract_status: Annotated[bool, Field(strict=True)] = False,
                  include_profile: Annotated[bool, Field(strict=True)] = False,
                  include_health: Annotated[bool, Field(strict=True)] = False,
                  include_contract_bonuses: Annotated[bool, Field(strict=True)] = False,
                  profile_policy: Literal["required", "available"] = "required",
                  include_transfer_prices: Annotated[bool, Field(strict=True)] = False) -> dict[str, Any]:
    """include_transfer_prices adds the last transfer fee, stored valuation and asking-price input, plus the contextual transfer value and asking-price properties for regular players in GBP. Negative native codes have null amounts. Contextual market ranges and negotiated fees are unavailable. profile_policy="available" preserves checked roster identities when a virtual profile is absent or its otherwise typed generated cache belongs to another PERSON: name, display_name, birth_date, attributes and requested clubs/profile/health are null, with explicit availability metadata. The default "required" retains strict rich-profile reads. Available-policy results label rejected caches cache_identity_mismatch and never borrow cached fields; negative_cache_index distinguishes genuinely cold profiles. Canonical identity, type, bounds, marker or read-drift faults still fail closed. include_contract_bonuses adds six stored main-contract cash bonuses in GBP: appearance, goals, assists, clean sheets, unused substitute and international caps. Absent entries differ from zero; basic contracts return unavailable and virtual players are unsupported. Use fm_get_contract_terms for further stored main-contract clauses and fm_get_loan_contract for loan terms; payment eligibility is not evaluated. Reread a player, verifying build, types and identity. Set include_clubs for independent main-contract/current/loan clubs and the native On Loan flag. Missing parent/current teams remain null; empty auxiliary slots, trials and the native affiliation exception produce false with a reason. Unsupported contract states fail explicitly. include_contract_dates adds joined, last_signed and expires dates with fixed/computed states; unavailable/dynamic states are explicit and virtual records are unsupported. include_contract_status adds the current contract status label and native code, with explicit basic/unmapped states. Specialized league types and virtual-player status remain unsupported. include_wage adds the stored weekly main-contract amount in GBP, excluding bonuses and loan contributions. include_health adds stored condition, match_sharpness and fatigue plus named injury records. It does not refresh fitness or establish match eligibility. Virtual condition/sharpness are explicitly unavailable. include_profile adds stored current/potential ability, 14 position ratings, 11 goalkeeper ratings, five hidden ratings, foot strength and eight personality ratings; uses existing virtual caches without creating profiles. These are native values without scouting masks, not star ratings or role recommendations. Rejects changed/expired references. Reattach after loading a save."""
    return bridge.get_player(session_id, player_ref, include_clubs, include_contract_dates, include_wage, include_contract_status, include_profile, include_health, include_contract_bonuses, profile_policy=profile_policy, include_transfer_prices=include_transfer_prices)


@mcp.tool(annotations=READ)
def fm_get_player_match_form(session_id: str, player_ref: str,
                             team_ref: str | None = None,
                             mode: str = 'confirmed_appearances',
                             limit: Annotated[int, Field(strict=True)] = 5) -> dict[str, Any]:
    """Read last retained match-form entries for a checked regular player and one exact TEAM. Obtain player_ref from the live squad/player tools; team_ref is optional and defaults to the managed TEAM, not every team in the club. mode confirmed_appearances selects dated rows with positive stored minute duration or a positive substitution-on event, preserving zero-minute subs. mode team_entries includes dated entries with missing statistics. Returns dates, canonical opponent TEAM/competition, goals and minute duration, with explicit missing/zero states, retained counts, same-day ties, undated entries and ambiguous entries at/after the cutoff that could change an ordinary last-five answer. It does not label missing statistics as unused, prove completion, identify a unique fixture, or establish a complete season/career. Ring capacity20/60 can overwrite older entries; national/youth teams are separate. Virtual/combined player/staff owners remain unsupported. limit1..60. No archive loads, UI, game calls or refreshes; native identity and consumed bytes are rechecked."""
    return bridge.get_player_match_form(session_id, player_ref, team_ref, mode, limit)


@mcp.tool(annotations=READ)
def fm_get_current_player_statistics(session_id: str, player_ref: str) -> dict[str, Any]:
    """Read resident current-player statistics for a checked regular actual-player reference. Returns six native category slots, proven appearances/goals/assists/minutes/rating fields and explicitly raw advanced statistics. Keeps main and additional team sources separate; never adds totals to component categories or merges archived history. Missing resident objects or categories remain unavailable because obtaining them through native getters could allocate game state. Team links describe stored associations, and any club runtime season year is distinct from FM's normalized history display year. Does not claim complete career history, match eligibility, freshness after recalculation or UI aggregate equivalence. Virtual and combined player/staff records are unsupported. Rechecks save binding, identity and consumed bytes; reads are non-atomic."""
    return bridge.get_current_player_statistics(session_id, player_ref)


@mcp.tool(annotations=READ)
def fm_compare_team_league_performance(
    session_id: str,
    team_ref: str,
    minimum_minutes: Annotated[int, Field(ge=0, le=32767, strict=True)] = 450,
    limit: Annotated[int, Field(ge=1, le=25, strict=True)] = 5,
    include_history: Annotated[bool, Field(strict=True)] = True,
) -> dict[str, Any]:
    """Compare the selected native team roster by stored current League goals plus assists per90. Collects and classifies the complete bounded roster before ranking known regular actual-player values with exact arithmetic, an inclusive minimum-minutes threshold, then minutes and native roster order as tie-breaks. Missing and unsupported values remain explicit and can prevent a complete-roster ranking claim. Roster membership is distinct from current team, club ownership and match eligibility. Optional archived League context retains separate native year/team rows and never contributes to the current ranking. Repeated save, roster, current-statistics and archive reads reject observed drift; this is a non-atomic observation interval, not a refreshed game evaluation. Reattach/reselect expired references. No native functions, profile materialization or game writes."""
    return bridge.compare_team_league_performance(session_id, team_ref, minimum_minutes, limit, include_history)


@mcp.tool(annotations=READ)
def fm_get_player_statistics_history(session_id: str, player_ref: str) -> dict[str, Any]:
    """Read indexed archived statistics for a checked regular actual-player reference. Preserves native record order, year, six category meanings, signed statistics and unmapped metadata; accounts for skipped negative offsets. Named team and competition references describe stored context, not proof that each category was played in that competition. Distinguishes decoded empty, no history index and unavailable sources. Does not merge resident current statistics, starting playing history or resident archive caches, normalize season years or claim UI career-history equivalence. Rechecks person membership, source file binding and every consumed byte before publishing links. Reads are non-atomic; virtual and combined player/staff records are unsupported."""
    return bridge.get_player_statistics_history(session_id, player_ref)


@mcp.tool(annotations=READ)
def fm_get_loan_contract(session_id: str, player_ref: str) -> dict[str, Any]:
    """Read the current stored loan agreement for a checked player_ref. Returns parent/borrowing clubs, signed/end dates, playing/unused weekly wages and monthly fees in GBP, buy-back fee and future purchase fee with native match counters and stored competition achievement conditions. Distinguishes no current loan, unspecified amounts and zero. Purchase triggers are described but never evaluated; competition conditions include named source/qualification competitions and supported achievement codes. Stage-name composition and other achievement codes remain explicit as undecoded. Thirteen stored clause flags cover recall, termination, cup/parent-club permissions and continental restrictions; nonzero native overrides replace the base flags. Unmapped bits stay explicit. Does not calculate payment schedules, actual costs, current validity or recall/match eligibility. Parent-club absence and differences between the borrowing and current clubs stay explicit; the agreement is not assumed active today. Virtual players are unsupported. Reads are non-atomic with identity and consumed-byte rechecks."""
    return bridge.get_loan_contract(session_id, player_ref)


@mcp.tool(annotations=READ)
def fm_get_contract_terms(session_id: str, player_ref: str | None = None,
                          staff_ref: str | None = None) -> dict[str, Any]:
    """Read every stored entry in one player's or staff member's main-contract vector. Select exactly one checked player_ref or staff_ref. Decodes cash bonuses, wage-change percentages, release fees and expiry dates, sell-on terms, extension conditions, landmark bonuses, wages after appearance thresholds and presence clauses. Preserves repeated entries, native order and the native property's selected entry. Unmapped kinds retain raw values explicitly; basic contracts return unavailable and virtual players are unsupported. These are stored terms, not proof of activation, payment due, transfer eligibility, UI visibility or all future/loan contracts. Negative parameters remain unavailable; expiry dates follow the native signed-date offset and mode branches without executing game code. Rechecks ownership, types, references and consumed bytes; reads are non-atomic."""
    return bridge.get_contract_terms(session_id, player_ref, staff_ref)


@mcp.tool(annotations=READ)
def fm_get_save(session_id: str) -> dict[str, Any]:
    """Read loaded career name, creation date, save count, current_date, last_saved_date and active employed human managers with clubs from verified native roots. current_date is the native simulation calendar date used by fixture-relative labels; last_saved_date is separate. Neither supplies a verified current clock time or timezone. Rejects detected save changes; reattach after loading a save."""
    return bridge.get_save(session_id)


@mcp.tool(annotations=READ)
def fm_get_player_injury_status(
    session_id: str,
    player_refs: Annotated[list[str] | None, Field(min_length=1, max_length=100)] = None,
    coach_name: str | None = None,
) -> dict[str, Any]:
    """Read FM's current-date injury-status branch for your picked XI and bench in one pass when player_refs are omitted. Uses the existing manager edit session; preserves duplicate picks and reports all26 stored slot positions including empties. Choose coach_name when multiple managers are active. For another player or a reusable batch, provide1..100 current player_refs instead; coach_name then does not apply. Returns flagged true/false for audited native branches, null with an explicit unsupported reason otherwise. Named stored injuries are separate from the computed Inj/Injured status; record presence alone is not the flag. This reconstructs a pinned native branch without executing it or reading a resident UI status-flags object. It does not assess medical clearance, a future fixture, eligibility or recovery dates. Use fm_get_player_injury_return_estimates for the separately qualified estimate workflow. No game writes, refresh or UI."""
    return bridge.get_player_injury_status(session_id, player_refs, coach_name)


@mcp.tool(annotations=READ)
def fm_get_player_injury_return_estimates(
    session_id: str,
    player_refs: Annotated[list[str], Field(min_length=1, max_length=32)],
) -> dict[str, Any]:
    """Reconstruct the current club medical estimate for 1–32 fresh player references. Resolve names/ambiguity with existing live player tools first; no archive is used. Supported injury records expose signed native PPMi/PPMa remaining calendar days as of the current simulation date and a separately labelled arithmetic date conversion. Each injury keeps its own result; unsupported treatment/date/mode or staff-selection branches retain explicit reasons, and empty checked vectors are not zero-day forecasts. Current club, first matching native Head Physio and raw inputs are rebound and byte-rechecked on every request; no refresh, report creation or game function runs. Say reconstructed club medical estimate, not a recently displayed physio report. Neither these estimates nor empty injury vectors establish medical clearance, training permission, match eligibility or guaranteed recovery."""
    return bridge.get_player_injury_return_estimates(session_id, player_refs)


@mcp.tool(annotations=READ)
def fm_get_current_player_cup_history(
    session_id: str, competition_ref: str,
    player_refs: Annotated[list[str], Field(min_length=1, max_length=32)],
    fixture_ref: str | None = None,
) -> dict[str, Any]:
    """Read named players' CURRENT resident cup PERSON aggregates for a checked competition_ref. Find competition and players with fm_find_competitions/fm_find_save_players. Returns native season, last-associated TEAM and cumulative unsigned-byte appearance counter; counter is NOT appearances for that TEAM and may wrap. Missing row is not historical absence. Optional fixture_ref from fm_find_fixtures must match competition; returns only the CURRENT-source flag1 different-TEAM inner condition for a current fixture participant and its explicit rule/date context. Past fixture context never reconstructs kickoff status. Unsupported rule/runtime/type/duplicate sources stay unknown; no overall cup-tied, registration or fixture eligibility verdict. No disk or UI fallback."""
    return bridge.get_current_player_cup_history(session_id, competition_ref, player_refs, fixture_ref)


@mcp.tool(annotations=READ)
def fm_get_player_bans(
    session_id: str, player_refs: Annotated[list[str], Field(min_length=1, max_length=100)],
    fixture_ref: str | None = None,
) -> dict[str, Any]:
    """Read stored personal ban records for up to 100 regular or combined player references. Find players with fm_find_save_players or a squad query. Each row distinguishes a checked empty source from missing secondary data or an unsupported combined player/staff source. For supported international records, read the English main text and stored start date. Native kind1 records include a canonical typed scope competition and stored total-minus-served match balance when supported; this is not an active-ban filter. Optionally supply an exact fixture_ref from fm_find_fixtures or fm_get_next_match_squad to project the official ordinary mode0 suspension predicate on its canonical stored COMP/date. Supports unplayed FIXTURE records, checked empty lists and a single supported kind1 record; unsupported gates/kinds remain unknown. Future results assume the currently recorded bans remain unchanged. The native supported path does not gate on stored match balance. This is the suspension predicate only; overall fixture eligibility, medical clearance and the outer availability decision remain not evaluated. Omitting fixture_ref preserves the stored-record response. No game functions, UI lookup, simulation, cleanup or writes."""
    if fixture_ref is not None:
        return bridge.get_player_bans(session_id, player_refs, fixture_ref)
    return bridge.get_player_bans(session_id, player_refs)


@mcp.tool(annotations=READ)
def fm_get_player_assessments(
    session_id: str, player_refs: Annotated[list[str], Field(min_length=1, max_length=100)],
    coach_name: str | None = None, source_offset: Annotated[int, Field(strict=True, ge=0)] = 0,
    source_limit: Annotated[int, Field(strict=True, ge=1, le=4096)] = 4096,
    include_joining_interest: Annotated[bool, Field(strict=True)] = False,
) -> dict[str, Any]:
    """Read stored assessments for up to 100 regular or combined player references in one pass. Use player_refs from your personal shortlist or other player reads. Each match includes its assessor, when the game populated the record, and whether extra assessment data is stored. Set include_joining_interest for stored English joining-interest labels. These describe the assessment at the time it was recorded. The source includes coaching assessments. Follow source.next_source_offset to search more physical slots. An empty match list covers only the examined source range. Completed scout reports and grades remain unknown."""
    return bridge.get_player_assessments(session_id, player_refs, coach_name, source_offset, source_limit, include_joining_interest)


@mcp.tool(annotations=READ)
def fm_get_managed_shortlists(
    session_id: str, coach_name: str | None = None,
    list_index: Annotated[int, Field(strict=True, ge=0)] | None = None,
    offset: Annotated[int, Field(strict=True, ge=0)] = 0,
    limit: Annotated[int, Field(strict=True, ge=1, le=100)] = 50,
) -> dict[str, Any]:
    """List your ordinary personal recruitment shortlists and read one page of retained entries. With no list_index, read the current personal selection when available. Use a native list_index from lists to select another. Each entry keeps its native position, including unresolved slots. Open a returned player_ref with fm_get_player. A null stored name means the display title is unknown. Scouting reports, active monitoring and expiry remain unknown."""
    return bridge.get_managed_shortlists(session_id, coach_name, list_index, offset, limit)


@mcp.tool(annotations=READ)
def fm_get_managed_training(
    session_id: str, coach_name: str | None = None, start_date: str | None = None,
    day_count: Annotated[int, Field(strict=True, ge=1, le=366)] = 7,
) -> dict[str, Any]:
    """Read the managed team's stored training schedule for a civil date window. Defaults to seven days starting on the loaded simulation date. Supply YYYY-MM-DD and 1 to 366 days to inspect another window. Dates and slots retain their order, with exact signed session codes and verified English names where available. A missing stored week has null slots. Rest and Match are named training entries. The schedule does not establish attendance, completion or kickoff times. Choose coach_name from fm_get_save when needed."""
    return bridge.get_managed_training(session_id, coach_name, start_date, day_count)


@mcp.tool(annotations=READ)
def fm_get_managed_tactical_assignments(
    session_id: str, coach_name: str | None = None,
    phase: Literal['both', 'in_possession', 'out_of_possession'] = 'both',
    include_personal_overrides: Annotated[bool, Field(strict=True)] = False,
) -> dict[str, Any]:
    """Read where your picked XI is assigned in both tactical phases in the active manager's existing working edit session. Defaults to both; select a phase to narrow the response. Player identities retain selection-slot order. Out-of-possession uses the selected creator's stored phase map, including native FF same-slot fallback; it is not inferred from in-possession positions. Returns raw mappings, phase slot indices, position masks and verified English position/base-role names. Empty or duplicate people, repeated target slots, unknown labels and unsupported map indices remain explicit; no permutation is assumed. Missing edit sessions are unavailable, not empty. Set include_personal_overrides=true to inspect bounded stored personal position records, with separate exact-mask/nonzero and strict IP role lookup policies. Absence, inactive first matches, stored positive records and policy differences are explicit. This opt-in does not replace base roles, decode all instructions or establish effective overrides. Does not establish foreground screen, submission, eligibility or effective individual role overrides. Read-only: never creates or applies an edit session."""
    return bridge.get_managed_tactical_assignments(session_id, coach_name, phase, include_personal_overrides)


@mcp.tool(annotations=READ)
def fm_get_managed_in_possession_positions(session_id: str, coach_name: str | None = None) -> dict[str, Any]:
    """Read where each picked starter is assigned in possession in the active manager's existing working edit session. Returns eleven original slots with canonical PERSON identities, stored position masks and verified English names, and source-qualified stored base roles. This tool covers in-possession pairing only; never infer out-of-possession player positions from it. Empty slots, duplicate people, unmapped masks/roles and unavailable creator selections remain explicit. Repeated role names are retained per slot. This does not establish foreground screen, match submission, eligibility or effective individual overrides. Use coach_name from fm_get_save when needed. Read-only; never creates or applies an edit session."""
    return bridge.get_managed_in_possession_positions(session_id, coach_name)


@mcp.tool(annotations=READ)
def fm_get_fixture_player_checks(session_id: str, fixture_ref: str,
                                  coach_name: str | None = None,
                                  player_refs: list[str] | None = None) -> dict[str, Any]:
    """Check named fixture reasons for current editable picks or proposed players.

    Requires a fresh fm_find_fixtures reference. Returns separate direct other-team
    cup-history, ordinary suspension and signed-after-round activation checks.
    Unknown branches remain unavailable; overall clearance always remains unknown.
    Optional player_refs checks 1..32 actual managed-club non-loan proposals without
    changing selection. This does not establish historical other-club appearances,
    submitted registration, medical clearance or full eligibility. Absent history
    is not zero appearances. Choose coach_name for multiple active managers.
    """
    return bridge.get_fixture_player_checks(session_id, fixture_ref, coach_name, player_refs)


@mcp.tool(annotations=READ)
def fm_get_managed_team_sheet(session_id: str, coach_name: str | None = None) -> dict[str, Any]:
    """Read who you have currently picked in the active manager's existing editable team selection. Returns original ordered slots and checked player identities, preserving empty slots and duplicates. Slots 0-10 are the XI. The bench ends where the game puts it: at the end stored in the session for a fixture bound to it, otherwise at the selection screen's substitute count for the team's cached next fixture; bench_boundary_source and bench_fixture say which, and later slots stay unresolved when neither is established. A missing edit session is unavailable, not an empty team. This does not establish submission, eligibility or a played-match lineup. Choose coach_name from fm_get_save when multiple managers are active. Reads only: never creates an edit session or applies changes."""
    return bridge.get_managed_team_sheet(session_id, coach_name)


@mcp.tool(annotations=READ)
def fm_get_managed_penalty_takers(session_id: str,coach_name: str | None=None) -> dict[str,Any]:
    """Read the current managed team's stored penalty taker priority order, bound to the selected active HUMAN manager and canonical TEAM. Preserve order, empty lists, null sentinels, duplicate references, unresolved PERSON entries and separate current-club/loan links. This is assigned stored order, not best attributes or last scorer. Pending working-edit overrides are explicitly unknown; never call the first entry the final match taker or predict shootout outcomes. Compare to fm_get_managed_team_sheet independently using each PERSON's database_index/native_id/secondary_id; selection membership does not change this stored list. Corners/free-kick taker orders are not yet decoded. No UI, edit-session creation, native execution, saved-file decode or game writes."""
    return bridge.get_managed_penalty_takers(session_id,coach_name)


@mcp.tool(annotations=READ)
def fm_get_managed_tactics(
    session_id: str, coach_name: str | None = None,
    include_formation: Annotated[bool, Field(strict=True)] = False,
    include_instructions: Annotated[bool, Field(strict=True)] = False,
    include_roles: Annotated[bool, Field(strict=True)] = False,
) -> dict[str, Any]:
    """Read your managed team's prepared tactics, primary trained selection, exact names and both sets of 11 positions. Set include_instructions=true to compare each tactic's stored mentality and selected team instructions. Set include_formation=true for each phase's numeric formation ID and ordinary English name where verified. Set include_roles=true for each position's stored base role and its compiled English label; each phase has its own role and the role is the whole selection, with no further level beneath it. Names can be null. Per-player choices and localized display names require separate evidence. Unmapped positions and instruction options retain their native values. Choose coach_name from fm_get_save when needed. Null slots retain their place. Match assignment, per-player overrides and the effective instructions applied during play require separate evidence. Rechecks consumed bytes and ownership."""
    return bridge.get_managed_tactics(session_id, coach_name, include_formation, include_instructions, include_roles)


@mcp.tool(annotations=READ)
def fm_get_next_match_squad(
    session_id: str, coach_name: str | None = None,
    window_days: Annotated[int, Field(strict=True, ge=1, le=366)] = 35,
    position_minimum: Annotated[int, Field(strict=True, ge=1, le=20)] = 15,
    max_fixture_pages: Annotated[int, Field(strict=True, ge=1, le=50)] = 20,
) -> dict[str, Any]:
    """Read your managed team's next known dated fixture candidate and compact native roster in one live observation. Search complete calendar days from current_date, stopping after every group/slot of the earliest candidate day, or at current_date+window_days inclusively. Distinguish selection-prefix completeness from a fully scanned window; retain resident-year/group coverage, remaining-window cursors and missing years. Same-day rows remain candidates because live time-of-day and completion are unknown; scores or result-record presence never prove completion. The roster separates verified current managed-club identities from away players, including loans, and preserves unknown club links. Position cover uses stored0–20 ratings at or above position_minimum; this threshold is not a can-play verdict. Stored condition/sharpness percentages, signed fatigue, recorded injuries and personal bans are shown without refresh. Active ban applicability, registration, medical clearance and fixture eligibility remain unknown. No starting XI is selected. All consumed bytes, root identity, fixture routes and roster links are rechecked before session-bound references are published; a changed observation fails. No disk save or cached source is used."""
    return bridge.get_next_match_squad(session_id, coach_name, window_days,
                                       position_minimum, max_fixture_pages)


@mcp.tool(annotations=READ)
def fm_get_managed_squad(session_id: str, coach_name: str | None = None,
                         include_clubs: Annotated[bool, Field(strict=True)] = False,
                         include_profile: Annotated[bool, Field(strict=True)] = False,
                         include_health: Annotated[bool, Field(strict=True)] = False,
                  profile_policy: Literal["required", "available"] = "required") -> dict[str, Any]:
    """profile_policy="available" preserves checked roster identities when a virtual profile is absent or its otherwise typed generated cache belongs to another PERSON: name, display_name, birth_date, attributes and requested clubs/profile/health are null, with explicit availability metadata. The default "required" retains strict rich-profile reads. Available-policy results label rejected caches cache_identity_mismatch and never borrow cached fields; negative_cache_index distinguishes genuinely cold profiles. Canonical identity, type, bounds, marker or read-drift faults still fail closed. include_health adds stored condition, match_sharpness and fatigue plus named injury records. It does not refresh fitness or establish match eligibility. Virtual condition/sharpness are explicitly unavailable. include_profile adds stored ability, 14 positions, 11 goalkeeper ratings, five hidden ratings, foot strength and eight personality ratings, without scouting masks. Query the active coach's native team roster with attributes and reusable references. Set include_clubs for each player's main-contract/current club and loan status. Select coach_name from fm_get_save for multiple coaches. Includes native roster members, possibly loaned out; differs from UI filters, youth call-ups and eligibility. Unsupported records fail the entire query."""
    return bridge.get_managed_squad(session_id, coach_name, include_clubs, include_profile, include_health, profile_policy=profile_policy)


@mcp.tool(annotations=READ)
def fm_get_club_finances(session_id: str, coach_name: str | None = None,
                         club_ref: str | None = None,
                         include_details: Annotated[bool, Field(strict=True)] = False,
                         include_ffp_projection: Annotated[bool, Field(strict=True)] = False) -> dict[str, Any]:
    """Read club balance, total weekly wage budget, remaining_weekly_wage_budget, stored transfer budget and current_transfer_budget in whole GBP. Defaults to your club; accepts club_ref from fm_find_clubs or coach_name, mutually exclusive. Remaining wage budget uses the native property and stored spending without triggering recalculation; refresh markers stay null. Current transfer budget follows verified native availability rules; unsupported mode/date/manager adjustments stay null with reasons. These figures do not establish complete offer affordability or board approval. Base finance records expose balance only. include_details adds the scouting budget, stored season ticket holders, ticket prices, original debt, repayment schedules, loan FFP inclusion and club-linked FFP manager records. Use include_ffp_projection for the per-competition IsPassingFfp verdict. It privately replays the pinned game calculation using stored spending, rechecks inputs and returns unavailable for unsupported branches. Rechecks consumed bytes and club references; reads are non-atomic."""
    return bridge.get_club_finances(session_id, coach_name, club_ref, include_details=include_details, include_ffp_projection=include_ffp_projection)


@mcp.tool(annotations=READ)
def fm_check_transfer_budget(
    session_id: str, upfront_fee_gbp: Annotated[int, Field(ge=0, le=2147483647, strict=True)],
    coach_name: str | None = None, club_ref: str | None = None,
) -> dict[str, Any]:
    """Compare one upfront transfer fee in whole GBP with the decoded current transfer budget. Returns fits_current_transfer_budget and budget_after_upfront_fee; both stay null when the native budget is unavailable. Defaults to your club or accepts club_ref from fm_find_clubs. This is arithmetic only: wages, signing/agent fees, instalments, conditional payments, pending offers, seller demands, registration and board approval are excluded. Never submits an offer or changes the budget."""
    return bridge.check_transfer_budget(session_id, upfront_fee_gbp, coach_name, club_ref)


@mcp.tool(annotations=READ)
def fm_check_wage_budget(
    session_id: str, additional_weekly_wage_gbp: Annotated[int, Field(ge=0, le=2147483647, strict=True)],
    coach_name: str | None = None, club_ref: str | None = None,
) -> dict[str, Any]:
    """Compare a supplied additional weekly wage in whole GBP with remaining wage budget from native stored totals. Returns fits_remaining_wage_budget and budget_after_additional_wage, null when unavailable. Defaults to your club or accepts club_ref from fm_find_clubs. Does not refresh spending or calculate additional bonuses, loan contributions, future commitments, fees or board approval. Never submits an offer or changes the budget."""
    return bridge.check_wage_budget(session_id, additional_weekly_wage_gbp, coach_name, club_ref)


@mcp.tool(annotations=READ)
def fm_query_transfer_offers(
    session_id: str,
    person_native_id: Annotated[int, Field(strict=True, ge=1, le=4294967295)] | None = None,
    team_native_id: Annotated[int, Field(strict=True, ge=1, le=4294967295)] | None = None,
    club_native_id: Annotated[int, Field(strict=True, ge=1, le=4294967295)] | None = None,
    raw_state_codes: list[Annotated[int, Field(strict=True, ge=0, le=255)]] | None = None,
    limit: Annotated[int, Field(strict=True, ge=1, le=100)] = 50,
    cursor: str | None = None,
) -> dict[str, Any]:
    """Enumerate stored live transfer offers, including historical objects, from two complete typed manager vectors. Optional positive native PERSON/TEAM/CLUB IDs combine with AND; TEAM/CLUB match any of three common TEAM links whose business direction remains unresolved except the loan's common_team_40 proposed borrowing-team link. Omit selectors for the full population. PERSON covers the common primary person only; additional trade participants are not decoded. Complete slot/null/class/state counts precede pagination; continue each opaque cursor with unchanged selectors. Changed populations, current states or predicate identities reject continuation. Native offer-state bytes have no verified English mapping: do not reuse the UI display-status enum or assume pending/accepted/active status. Known loan fields are proposed weekly wages/monthly fees in verified base GBP, not obligations; other raw amount semantics remain unknown. Missing names, null references and unavailable currency are explicit. No saved archive, game function, recalculation, UI or game write is used."""
    return bridge.query_transfer_offers(session_id, person_native_id=person_native_id,
        team_native_id=team_native_id, club_native_id=club_native_id,
        raw_state_codes=raw_state_codes, limit=limit, cursor=cursor)


@mcp.tool(annotations=READ)
def fm_get_wage_contributions(
    session_id: str, coach_name: str | None = None, club_ref: str | None = None,
    all_clubs: Annotated[bool, Field(strict=True)] = False,
) -> dict[str, Any]:
    """List live transfer-manager weekly wage contributions, with payer/recipient clubs, person references, whole-GBP weekly amounts and stored paid-until dates. Defaults to your club, accepts club_ref or coach_name, or all_clubs=true alone. Returns incoming/outgoing/net totals for a selected club and sorts records by weekly amount descending. Staff identities are supported when a former player now has a staff record. Unsupported person types remain explicit. This is the native contribution list, not all loan costs, bonuses, payroll or future commitments. Checks the complete list within a 1024-record bound; never silently truncates. Does not refresh or pay anything."""
    return bridge.get_wage_contributions(session_id, coach_name, club_ref, all_clubs)


@mcp.tool(annotations=READ)
def fm_get_club_squads(session_id: str, coach_name: str | None = None,
                       club_ref: str | None = None) -> dict[str, Any]:
    """List every native team belonging to a club, with counts and opaque team references. Defaults to the active coach's club; pass club_ref from fm_find_clubs for any supported club, or coach_name for a different active coach. club_ref and coach_name are mutually exclusive. Includes youth and other squads. Counts describe native roster membership, not ownership or eligibility."""
    return bridge.get_club_squads(session_id, coach_name, club_ref)


@mcp.tool(annotations=READ)
def fm_get_team_squad(session_id: str, team_ref: str,
                      include_clubs: Annotated[bool, Field(strict=True)] = False,
                      include_profile: Annotated[bool, Field(strict=True)] = False,
                      include_health: Annotated[bool, Field(strict=True)] = False,
                  profile_policy: Literal["required", "available"] = "required") -> dict[str, Any]:
    """Every player row includes native_identity (PERSON database_index, native_id and independent random_id) from the checked typed record, including required-profile reads. Join retained canonical_person_id to native_identity.native_id rather than names or roster slots. profile_policy="available" preserves checked roster identities when a virtual profile is absent or its otherwise typed generated cache belongs to another PERSON: name, display_name, birth_date, attributes and requested clubs/profile/health are null, with explicit availability metadata. The default "required" retains strict rich-profile reads. Available-policy results label rejected caches cache_identity_mismatch and never borrow cached fields; negative_cache_index distinguishes genuinely cold profiles. Canonical identity, type, bounds, marker or read-drift faults still fail closed. include_health adds stored condition, match_sharpness and fatigue plus named injury records. It does not refresh fitness or establish match eligibility. Virtual condition/sharpness are explicitly unavailable. include_profile adds stored ability, 14 positions, 11 goalkeeper ratings, five hidden ratings, foot strength and eight personality ratings, without scouting masks. Read an entire team roster selected from fm_get_club_squads, fm_get_competition_teams, fm_get_competition_registrations or fm_get_standings, including fixture-derived team references. Competition-derived references add team identity/owner details; club is null for national and ownerless teams. Returns actual and virtual players with attributes and fresh references. Rich virtual fields require an existing identity-matched profile cache; available policy permits checked identity-only entries for negative cache indexes or an independently validated compact PERSON whose typed cache has a conflicting primary identity. unavailable_profiles identifies every unresolved roster entry. include_clubs distinguishes contracted players from uncontracted virtual roster members."""
    return bridge.get_team_squad(session_id, team_ref, include_clubs, include_profile, include_health, profile_policy=profile_policy)


@mcp.tool(annotations=READ)
def fm_query_team_players(
    session_id: str, team_ref: str,
    minimum_attributes: dict[str, Annotated[int, Field(ge=1, le=20, strict=True)]] | None = None,
    sort_by: str | None = None,
    limit: Annotated[int, Field(ge=1, le=100)] = 20,
    include_virtual: Annotated[bool, Field(strict=True)] = False,
    loan_status: Literal['any', 'on_loan', 'not_on_loan'] = 'any',
    minimum_profile: dict[str, Annotated[int, Field(ge=0, le=200, strict=True)]] | None = None,
    minimum_health: dict[str, Annotated[int, Field(ge=-32768, le=32767, strict=True)]] | None = None,
    maximum_health: dict[str, Annotated[int, Field(ge=-32768, le=32767, strict=True)]] | None = None,
    injury_records: Literal["any", "with_records", "without_records"] = "any",
) -> dict[str, Any]:
    """Find players in a team from fm_get_club_squads, fm_get_competition_teams, fm_get_competition_registrations or fm_get_standings, including fixture-derived team references, including national teams. Filter with minimum_attributes (e.g. passing:15, vision:15), sort descending by one supported outfield attribute or profile path, and optionally filter loan status. minimum_profile accepts ability.current/potential (0–200), positions.<name>, goalkeeping.<name>, hidden_attributes.<name>, personality.<name> and feet.left/right (0–20). minimum_health/maximum_health use condition and match_sharpness (0–10000) and fatigue (signed native integer, higher means more fatigued). sort_by also accepts health.<field>. injury_records filters native record presence, not medical clearance. Uses available-profile roster reads: virtual records excluded by default do not block known-player queries. Included records with valid unavailable predicate or sort fields are explicitly unclassified; any known failed predicate excludes the record first. Malformed sources still fail. Classifications and counts account for the complete roster before limiting matches; complete_for_included_population means no included record remains unclassified. Example: positions.goalkeeper:15, goalkeeping.reflexes:14, sorted by ability.current. Virtual personality controversy follows a native constant zero, identified by personality_native_defaults. Unknown fixed potential from range codes is listed under unclassified_players, not treated as a nonmatch. Profile values are native values without scouting masks. Returns fresh player refs, counts and truncation. Rich ordering is descending by the requested field, then display name and birth date, retaining native order for exact ties; default ordering is display name. Missing name/date sort keys remain unclassified without invented labels. Virtual players are excluded by default. Loan filtering follows the native On Loan flag, including affiliation suppression, empty slots and trial contracts; a stored loan agreement alone does not establish that flag. Attribute/loan filtering does not establish match eligibility or role suitability."""
    return bridge.query_team_players(session_id, team_ref, minimum_attributes, sort_by,
                                     limit, include_virtual, loan_status, minimum_profile, minimum_health, maximum_health, injury_records)


@mcp.tool(annotations=READ)
def fm_detach() -> dict[str, Any]:
    """Discard the MCP session, player/team references, anchors and cursors. Does not stop or suspend the game."""
    return bridge.detach()


from .retained_pass_period_tools import register_retained_pass_period_tools
register_retained_pass_period_tools(mcp, bridge)

from .retained_paired_width_tools import register_retained_paired_width_tools
register_retained_paired_width_tools(mcp, bridge)

from .observed_run_record_tools import register_observed_run_record_tools
register_observed_run_record_tools(mcp, bridge)

from .retained_possession_tools import register_retained_possession_tools
register_retained_possession_tools(mcp, bridge)

from .retained_period_width_tools import register_retained_period_width_tools
register_retained_period_width_tools(mcp, bridge)

from .fmdb.tools import register_fmdb_tools
register_fmdb_tools(mcp, bridge)
from .fmdb.ledger_tools import register_ledger_tools; register_ledger_tools(mcp, bridge)  # noqa: E702
from .fmdb.persist_tools import register_persist_tools; register_persist_tools(mcp, bridge)  # noqa: E702

# Enhance Mode reads the game like every other tool here. Its job writes image files on the
# host and spends the user's own ChatGPT plan through their Codex CLI, so it is not marked read-only.
from .enhance_tools import register_enhance_tools
register_enhance_tools(mcp, bridge)

def _load_extensions() -> list[str]:
    """Modules named in FMCP_EXTENSIONS (comma separated) add their tools through register(mcp, bridge).

    The reader is read-only against the game and registers no edit tool itself. The write module
    (`fm_live_write`) is loaded only this way, so a default server cannot change the game. A module
    that is named and cannot be loaded stops the server: a missing edit tool must not look like a
    reader that silently lost it."""
    import importlib
    import os
    added = []
    for name in filter(None, (n.strip() for n in os.environ.get('FMCP_EXTENSIONS', '').split(','))):
        added += importlib.import_module(name).register(mcp, bridge) or []
    return added


EXTENSION_TOOLS = _load_extensions()


def main() -> None:
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
