# UI handler sweep, shaped screens and the four holes

Build 27.0.0.2493426, Newcastle United career (manager Cesar Jules), game date 10 Dec 2030,
read on 11 Nov 2026. Everything runs shipped code on copied live memory in `UiHandlerVM`
(see `UI_HANDLERS.md`, `UI_NEWS.md`, `UI_PERSON.md`); nothing is written to the game.

## One reader for every client protocol

`fm_live_mcp/fmdb/ui_recipes_more.py` adds `KeyReader`, which reads one client key with all
four protocols the plugin's clients use:

1. cached inputs: server slot 2 -> client slot 17 for every input the client consumes
   (`transfer_inputs`, done once per handler);
2. declared server keys: client slot 16 groups `{params bag, client params bag, keys}` and
   slot 14 plain keys, each computed by server slot 2 and handed to slot 4 in a property bag;
3. direct keys: client slot 13 names a server key whose value is the property;
4. screen parameters: `params={path RVA: int}` answers `0x77E228` lookups (the hook from
   `ui_recipes_person`); `install_param_trace` records which parameter paths a getter asked for.

State rules. Server keys without parameters are computed once and kept in the committed
baseline. Declarations, keys computed with a params bag, the bag, the request and every store
of slot 4 are discarded. When cached values add 16 MiB to the 64 MiB VM heap the handler is
rebuilt; a read that still runs out of heap is retried on a rebuilt handler, without its
slot-17 inputs when those alone fill most of the heap. A read that fails with "write to
shipped code" or "call into non-plugin code" (pages copied at different moments disagree) is
retried after `refresh_live_memory` (every copied live page dropped; ~15 s to fault them in
again), at most three times per handler; a build that faults is retried once the same way.
Any failed server key makes the property `Unavailable`, never a default value.

## Sweep

`scripts/fmdb_ui_sweep.py` runs every buildable factory type (138) and every class the
DATABASE_RECORD case (type 28) builds by the `dref` table type (12 more: AWARD, PERSON, CLUB,
CONTINENT, LANGUAGE, NATIONAL_TEAM_CONTAINER, NATION, STADIUM, TEAM, COMPETITION, AGREEMENT,
FIXTURE_NAME; table types 2, 7, 19, 28 and 47 build the base DATABASE_RECORD class, the rest
build nothing). Each job gets a fresh VM, 150 s and 15 s per emulated segment.

Bindings come from the career: context record fields on every job (`Hhum`, `huma`, `PbPY`,
`Ttea`, `Team`, `team`, `Teal`, `iyrZ`, `club`, `Club` and today's SI_DATE under `fdte`,
`date`, `fxdt`, `nMzT`, `dcnt`, `CqMA`, `day `), plus one profile chosen by the FourCCs the
server reads: squad player, scouted player, scout, team, club, league, Champions League, next
fixture, last fixture, news item or recruitment focus. With several candidate profiles the
first 14 keys pick the best one. Output: `out/fmdb-ui-sweep/types/<job>.json` and the merged
`out/fmdb-ui-sweep/sweep.json` (untracked); `--markdown FILE` writes the table below.

### Totals

150 jobs (138 factory types and 12 DATABASE_RECORD classes; factory types 1, 2, 28, 101, 102
and 113 build no client and are not jobs), 4,966 client keys, 747 s of handler time.

| Outcome | Jobs |
|---|---|
| at least one key returns a value | 104 |
| builds, every key unset or unavailable | 34 |
| builds, class has no client keys (bare `UI_HANDLER`, FILTER_RULE, FUTURE_FIXTURE, ...) | 12 |
| does not build | 0 |

Keys: 2,500 value, 2,344 unset (195 of them read a screen parameter the sweep did not
supply), 122 unavailable. Blockers of the 46 jobs that read nothing: every key unset under
all bindings (41, including the 12 keyless classes; mostly edit-session sub-rows, DB_SUMMARY
and match-player rows that a parent screen fills), an input that dereferences null (3:
SQUAD_SELECTION_PLAYER 106, MATCH_TACTIC 64, TEAM_TACTIC 126), `CFStringCreateWithCStringNoCopy`
(2: DATABASE_VERSION 29, FANTASY_DRAFT_AI_MANAGER 45). Unavailable keys by reason: unreadable
live memory 39 (GAME_UI_HANDLER, a pointer built from text), `CFStringCreateWithCStringNoCopy`
20, null dereference 14, `SteamInternal_ContextInit` 10, `getpid` 10,
`pthread_mutexattr_init` 9 (COMPETITION stage lists), `asinf` 8, `std::random_device` 4,
`std::__next_prime` 2, timeout 2.

RNG: jobs that drew numbers: CLUB_VISION_MEETING_EDIT_SESSION 14 (1,268 draws),
HIRE_INTERMEDIARY 56 (440), PERSON (256), TEAM (138), COMPETITION (100), MATCH 61 (22),
TEAM_CONFIDENCE 114 (16), CLUB (16), RECRUITMENT_FOCUS 85 (8), season expectations 15 (4).

TEAM_UI_HANDLER needed three passes: with its slot-17 inputs the 64 MiB VM heap ran out after
87 keys (fixed by the heap retry), and one pass hit "write to shipped code" on 160 keys
(fixed by the stale-memory retry). Final pass: 202 / 174 / 6 in 312 s.

### Table, by usefulness to a manager

"Shows" lists the labels of keys that returned values. "Binding" names the profile; `dref`
jobs use the managed object (player, club, team, league) or index 0 of the table.

| # | Type | Class | Binding | Value / unset / unavailable | s | RNG | Shows (or first blocker) |
|---|---|---|---|---|---|---|---|
| | **scouting** | | | | | | |
| 1 | 85 | RECRUITMENT_FOCUS | recruitment_focus | 90 / 10 / 0 | 4.19 | 8 | FocusObjectivesStatsAddItemsList, StatsCategories, NearMissPlayerPool, FocusObjectivesStatsItemsList, AreaCount, SelectedPoolDropdownValue, ConditionCategoryFiltersNumber (+74 more) |
| 2 | 73 | PERSON_SEARCH | squad_player | 44 / 10 / 12 | 8.27 | 0 | AttributesCoaching, SelectedAttributesCompareFlag, QuickFilterButtonList, PlayerInterestLevelSelection, ShortlistScoutingIntervalOptionsList, PlayerInterestLevelString, FilterMatchAttributesList (+31 more). Blocker: external call _getpid |
| 3 | 75 | PLAYER_REPORT | scouted_player | 34 / 21 / 0 | 1.22 | 0 | AnalystReportBasicInfo, UseCoachReportLayout, NoAnalystReportString, ScoutedTransferInfo, ScoutedProConsList, WatchedMatchesInfo, BestOOPRoleForPosition (+17 more) |
| 4 | 95 | SCOUTING_CENTRE_ACTIONS | none | 33 / 2 / 0 | 3.54 | 0 | ScoutingCentreFilterDropdown, FreeAgentOfferMaxAgeList, AgentOfferOptionShowListedPlayers, OfferTrialAction, AgentOfferOptionShowFreeAgents, HighlyRecommendedPlayersMinimumGradeDropdown, RequestedReportsDeliveryOptions (+23 more). Blocker: needs screen parameter 0x56d1388 |
| 5 | 38 | DOF_TARGET | none | 23 / 6 / 0 | 0.37 | 0 | MaxWageListProps, MaxTransferOfferString, DofTargetUrgentPriorityInfoString, DofTargetIsEditing, MaxWage, PriorityValue, MaxWageValue (+16 more) |
| 6 | 97 | SCOUTING_INFO | recruitment_focus | 9 / 12 / 0 | 2.89 | 0 | RecruitmentFocusesListCount, NewRecruitmentFocus, RecruitmentFocusesListType, RecruitmentFocusesListTypes, SelectedRecruitmentFocus, ScoutingRangeEntry, ScoutingBudget (+2 more) |
| 7 | 39 | DOF_TRANSFER_TARGETS | none | 6 / 2 / 0 | 0.25 | 0 | DOfOffersCount, DofTargetSelectedGroup, DofOffersTabString, DofTargetGroupsList, DofTargetSelectedGroupPriorityValue, DofTargetSelectedGroupPriorityList |
| 8 | 91 | SCOUT_PLAYER_PRIORITIES | squad_player | 4 / 6 / 0 | 0.32 | 0 | SpecificallyScoutedPlayers, SpecificallyScoutedPlayersCount |
| 9 | 90 | SCOUT_ASSIGNMENTS | none | 3 / 0 / 0 | 0.12 | 0 | StaffScoutList, SelectedScout |
| 10 | 96 | SCOUTING_CENTRE_DELIVERY_OPTION | none | 3 / 3 / 0 | 0.1 | 0 | DeliveryCategory, DeliveryOptionSubitems, DeliveryTopic |
| 11 | 143 | UPCOMING_COMPETITIONS_TO_SCOUT_NEWS | none | 2 / 2 / 0 | 0.04 | 0 | RecruitmentFocusToCreate, Selected |
| 12 | 92 | SCOUT_TEAM_PRIORITIES | none | 1 / 3 / 0 | 0.05 | 0 | SpecificallyScoutedTeamsCount. Blocker: needs screen parameter 0x56d16e8 |
| | **transfers and contracts** | | | | | | |
| 13 | 19 | CONTRACT | squad_player | 104 / 17 / 0 | 1.62 | 0 | ContractTimeRemainingDecription, TransferOptions, LoanPlayingMonthlyFee, SellingOnFeeProfitPercentageCash, MLSGuranteedContractClause, ContractBonusesCount, WageThreeSeasonsTime (+87 more) |
| 14 | 137 | TRANSFER_OFFER_EDIT_SESSION | squad_player | 80 / 37 / 0 | 1.35 | 0 | ResponseActions, ExchangePlayersCanAddPlayer, ProposalDeadlineDateIsSet, TransferOfferWageClubContribution, ExchangePlayersVisible, TransferOfferAvailableInstallmentFees, TransferBudgetCostValue (+66 more). Blocker: needs screen parameter 0x56d1688 |
| 15 | 20 | CONTRACT_EDIT_SESSION | squad_player | 71 / 9 / 0 | 1.29 | 0 | WageBudgetImpactPieChartData, ContractNegotiationCurrentTransferBudget, AdditionalFunds, OverallOfferLockStatus, FutureTransferWages, SelectedJobIsRecruitment, ContractNegotiationExistingWageContribution (+52 more) |
| 16 | 131 | TRANSFER_ACTIVITY | none | 31 / 11 / 0 | 1.01 | 0 | TransfersAllWagesValueString, TransfersAllBudgetImpactValueString, TransfersAllGuaranteedValue, TransferOffersRequireResponseCountIn, StaffAllCompensationValueString, StaffOutWagesValueString, TransfersOutGuaranteedValue (+24 more) |
| 17 | 141 | TRANSFER_ROOM_ADVERT | none | 31 / 6 / 0 | 0.6 | 0 | PositionString, ResponsesCountString, OOPRoleString, OOPPosition, MaxAgeValue, AgeRange, IpToggleString (+23 more). Blocker: needs screen parameter 0x56d13d8 |
| 18 | 134 | TRANSFER_ACTIVITY_TRANSFER_OFFER | squad_player | 21 / 14 / 0 | 0.53 | 0 | TransferActivityTableOptionsString1, TransferOfferTypeString, OfferRequiresResponse, TransferActivityTableClausesAndOptionsString, Wage, TotalTransferCost, TransferOfferType (+11 more) |
| 19 | 140 | TRANSFER_ROOM | squad_player | 21 / 17 / 0 | 2.91 | 0 | PitchOpportunitiesTopOpportunitiesList, HumanAdvertsResponsesAdvertForFilter, TransfersButtonString, HumanAdvertsFilterIsSet, PitchOpportunitiesFilterIsSet, HumanAdvertsTabString, PitchActivitiesTotalCount (+14 more). Blocker: needs screen parameter 0x56d1648,0x56d1688,0x7d8fe8ca2e00 |
| 20 | 132 | TRANSFER_ACTIVITY_PERSON | squad_player | 20 / 5 / 0 | 0.48 | 0 | MultiResponseShow, TransferActivityWithdrawButtonString, OfferRequiresResponse, TransferActivityRejectButtonString, TransferOffersCount, TransferOfferStatusString, TransferActivityAcceptButtonString (+3 more) |
| 21 | 100 | SET_TRANSFER_STATUS | squad_player | 19 / 4 / 0 | 0.69 | 0 | SetTransferStatusAgentLoanStatusString, SetTransferStatusLoanStatusOptionsList, SetTransferStatusTransferStatusOptionsList, SetTransferStatusAgentLoanStatusCoversationStatus, SetTransferStatusPlayingMonthlyFee, SetTransferStatusLoanStatus, SetTransferStatusUnusedWage (+12 more) |
| 22 | 142 | TRANSFER_WINDOW | league | 17 / 0 / 0 | 1.09 | 0 | TransferWindowDaysSinceStart, TransferWindowOutValue, StartDate, EndDate, TransferWindowTimelineMaxDays, TransferWindowInCount, TransferWindowCompetitions (+10 more) |
| 23 | 130 | TRADE_OFFER_EDIT_SESSION | none | 14 / 3 / 0 | 0.46 | 0 | DoFRecommendedBidCash, MinimumAmountToAcceptForAssetsOfferedCash, NegotiableOptionListEnabled, DoFRecommendedBidCashIntervalsProps, NegotiableOptionListValueString, HumanTeamDoF, ContextHumanTeamAvailableAssetsList (+6 more) |
| 24 | 78 | PRE_CONTRACT_PROMISES_EDIT_SESSION | squad_player | 14 / 4 / 0 | 0.42 | 0 | OverallOfferLockStatus, AgreedPlayingTimeComponentInfo, StartDate, NegotiationReadOnly, StartDateComponentInfo, NegotiationPatience, StartDateLockStatus (+2 more) |
| 25 | 12 | CLUB_TRANSFER_CLAUSES | none | 10 / 0 / 0 | 14.36 | 0 | TransferClausesInternationalSlotsCount, TransferClausesInSellableCount, TransferClausesAll, TransferClausesInSellableTotalValue, TransferClausesAllCount, TransferClausesIn, TransferClausesInCount (+3 more) |
| 26 | 133 | TRANSFER_ACTIVITY_TRADE_OFFER | none | 8 / 3 / 0 | 0.44 | 0 | OfferRequiresResponse, BuyingClub, TransferOfferStatusString, SellingClub, TransferOfferStatus |
| 27 | 68 | NEGOTIATE_ASK_FOR_PAY_OFF | squad_player | 8 / 2 / 0 | 0.16 | 0 | PayOffResetEnabled, PayOffSuggestEnabled, PayOffCompensationCashEnabled, PayOffCompensationCashListProps, PayOffAgentFeedbackString, PayOffCompensationCashValue, PayOffAgentFeedbackColour |
| 28 | 56 | HIRE_INTERMEDIARY | squad_player | 5 / 7 / 0 | 2.92 | 440 | IntermediaryDoFResponseString, IntermediaryAreThereInterestedClubsButNoOffers, IntermediaryAreThereValidIntermediaryOffers, IntermediaryRecruiterPerson, IntermediaryRecruiterPersonJob |
| 29 | 22 | CONTRACT_EXPIRES_SOON | squad_player | 4 / 8 / 0 | 0.27 | 0 | Mode, ExpiringContractsHeading, DofCanOfferContract |
| 30 | 8 | BUY_OR_SELL_PLAYER_IMMEDIATELY | squad_player | 4 / 1 / 0 | 0.24 | 0 | EnableImmediateTransferRequest, BuySellImmediatelyDropdownValueSelectionList, BuySellImmediatelyCashValue |
| 31 | 13 | CLUB_TRANSFER_CLAUSES_PERSON | none | 3 / 2 / 0 | 0.04 | 0 | TransferPersonClausesCount, Person |
| 32 | 135 | TRANSFER_BLOCKED_DUE_TO_STAFF_LIMITS | squad_player | 3 / 4 / 0 | 0.09 | 0 | BlockedJobRoleTakeOverResponsibilities, BlockedJobRoleSelectedPersonToReplace. Blocker: needs screen parameter 0x56d1298 |
| 33 | 139 | TRANSFER_OFFER_POTENTIAL_EXCHANGE_PERSON | squad_player | 3 / 0 / 0 | 0.14 | 0 | PlayerExchangeTransferType, Person |
| 34 | 129 | TRADE_OFFER_ASSET | none | 0 / 13 / 0 | 0.1 | 0 | nothing: every key unset (no binding produced data) |
| 35 | 136 | TRANSFER_OFFER_CLAUSE | none | 0 / 19 / 0 | 0.11 | 0 | nothing: every key unset (no binding produced data) |
| 36 | 138 | TRANSFER_OFFER_EXCHANGED_PERSON | none | 0 / 7 / 0 | 0.1 | 0 | nothing: every key unset (no binding produced data) |
| 37 | 21 | CONTRACT_EDIT_SESSION_ADD_ON_COMPONENT | none | 0 / 11 / 0 | 0.1 | 0 | nothing: every key unset (no binding produced data) |
| 38 | 79 | PRE_CONTRACT_PROMISES_EDIT_SESSION_FUTURE_PLAYNG_TIME | none | 0 / 11 / 0 | 0.09 | 0 | nothing: every key unset (no binding produced data) |
| 39 | 80 | PRE_CONTRACT_PROMISES_EDIT_SESSION_PROMISE | none | 0 / 7 / 0 | 0.08 | 0 | nothing: every key unset (no binding produced data) |
| | **squad and players** | | | | | | |
| 40 | 28:PERSON_UI_HANDLER | PERSON | dref | 319 / 343 / 2 | 78.93 | 256 | ExpectedGoalsPer90, FoulsAgainst, HumanSelectedShortlist, SquadSocialGroupsSpeakTo, ChancesCreated, HeaderCompleted, AnalysisVisualisations (+287 more). Blocker: needs screen parameter 0x56d1248 |
| 41 | 28:TEAM_UI_HANDLER | TEAM | dref | 202 / 174 / 6 | 311.78 | 138 | MentoringGroupsForDropdown, CurrentComp2, SetPieceDataInsights, HierarchyFeedbackStringsPositive, ManagerSupportPlayersNeutralCount, NationalTeamContainer, MatchSquadPickedCountText (+165 more). Blocker: needs screen parameter 0x56d1258 |
| 42 | 105 | SQUAD_REGISTRATION_EDIT_SESSION | squad_player | 28 / 9 / 0 | 17.08 | 0 | DeadlineDate, SquadSelectionName, RuleWarningStrings, PreviousPerson, PlayersToDisplay, ShuffleDraftReturnedPlayersCount, RegisteredPlayersCount (+15 more) |
| 43 | 104 | SQUAD_PLANNER | squad_player | 15 / 19 / 0 | 2.02 | 0 | AddPlayerDropdown, SquadPlanTypeDropdownValue, SquadPlanTypeDropdown, SquadPlanType, SquadPlanInternationalYear, CurrentPlan, CopyPlanDropdownTitle (+7 more). Blocker: needs screen parameter 0x56d12e8 |
| 44 | 74 | PLAYER_FORM | squad_player | 7 / 8 / 0 | 1.28 | 0 | SelectedComp, MatchesData, MatchRatingsStats, PossibleComps, SelectedTeam, PlayerFormFixturesList |
| 45 | 67 | NATIONAL_SQUAD_SELECTION_EDIT_SESSION | squad_player | 5 / 9 / 0 | 37.99 | 0 | RuleWarningStrings, SquadRegistrationQuickActionDropdown, RulesAmountMet, MustRemoveSummary. Blocker: needs screen parameter 0x56d1268 |
| 46 | 103 | SQUAD_NUMBERS_EDIT_SESSION | squad_player | 4 / 3 / 0 | 1.46 | 0 | SquadNumbersDropdown, SquadNumbersList, SquadPlayersAndNumbers, SquadNumbersActionsOptions |
| 47 | 58 | INDUCTION | squad_player | 1 / 0 / 0 | 0.14 | 0 |  |
| 48 | 106 | SQUAD_SELECTION_PLAYER | news | 0 / 0 / 0 | 0.08 | 0 | nothing: input null or low pointer dereference 0x0 |
| 49 | 125 | TEAM_SQUAD_SELECTION | squad_player | 0 / 0 / 0 | 0.08 | 0 | nothing: every key unset (no binding produced data) |
| 50 | 65 | MENTORING_GROUP | none | 0 / 11 / 0 | 0.97 | 0 | nothing: every key unset (no binding produced data) |
| | **training** | | | | | | |
| 51 | 128 | TEAM_TRAINING | news | 34 / 16 / 0 | 2.21 | 0 | TrainingPerformanceMonthlyString, AverageTrainingRating, LastWeekTrainingCategoryName, DefendingTacticalAttributesTooltip, TrainingPerformanceStatus, FMCNextWeekTrainingFocusCache, FMCNextWeekTrainingFocus (+26 more). Blocker: needs screen parameter 0x56d1248 |
| 52 | 77 | PLAYER_TRAINING | squad_player | 26 / 47 / 0 | 2.29 | 0 | ImprovementDefendingTactical, OOPTraining, AvailableRolesDropdown, ImprovementPossessionTechnical, ImprovementFitness, TrainingPosition, TrainingIntensityOrRest (+19 more) |
| 53 | 26 | CUSTOM_TRAINING_SCHEDULE | none | 19 / 10 / 0 | 1.53 | 0 | ExportTrainingScheduleType, TrainingScheduleDropdownName, CalendarWeek, CurrentTrainingSession, TrainingSessionCategoryDropdown, ScheduleImpactList, FileName (+10 more) |
| | **board, club and finances** | | | | | | |
| 54 | 28:CLUB_UI_HANDLER | CLUB | dref | 197 / 168 / 4 | 16.09 | 16 | TransferPolicy, DevelopmentCentreAdviceMeeting, SupporterRecruitmentObjectivesCount, WageBudget, PlayersOutOnLoan, TransferActivity, SupporterBoardInfluence (+157 more). Blocker: external call __ZNSt3__113random_deviceC1ERKNS_12basic_stringIcNS_11char_traitsIcEENS_9allocatorIcEEEE |
| 55 | 114 | TEAM_CONFIDENCE | squad_player | 45 / 26 / 0 | 28.71 | 16 | BoardTacticsGrade, PlayersListWithPlayerConfidence, TransferConfidenceShouldHideLoanTransfers, SupporterFeedbackCriticism, InternationalCompConfidenceStringShort, BoardTacticsFeedback, BoardVisionGrade (+38 more). Blocker: needs screen parameter 0x56d1198 |
| 56 | 10 | CLUB_BUDGET_ADJUSTMENT | none | 11 / 5 / 0 | 0.71 | 0 | BudgetAdjustmentOtherBudgetString, BudgetAdjustmentEditedTransferValue, BudgetAdjustmentCanEditBudgetUp, BudgetAdjustmentEditedOtherValue, BudgetAdjustmentCanEditBudgets, BudgetAdjustmentBoardString, BudgetAdjustmentCurrentSpendString (+4 more) |
| 57 | 14 | CLUB_VISION_MEETING_EDIT_SESSION | none | 8 / 2 / 0 | 7.13 | 1268 | ClubVisionMeetingInformationalObjectives, ClubVisionMeetingActionableObjectives. Blocker: needs screen parameter 0x56d1a28 |
| 58 | 76 | PLAYER_SALARY_CAP_ADJUSTMENT | squad_player | 7 / 3 / 0 | 0.45 | 0 | SalaryCapAdjustmentSliderValue, SalaryCapAdjustmentEditedPlayerSalaryCapValue, MinimumSalaryCapImpactString, SalaryCapAdjustmentEditedGAMValue, SalaryCapAdjustmentSliderProps, SalaryCapAdjustmentCanEditCapImpact, SalaryCapAdjustmentTeamSeasonString |
| 59 | 15 | CLUB_VISION_MEETING_SEASON_EXPECTATIONS | none | 6 / 0 / 0 | 8.95 | 4 | ClubSeasonExpectationsNumberCompetitions, ClubSeasonExpectationsNewTransferBudget, ClubSeasonExpectationsCompetitionList, ClubSeasonExpectationsNewRemainingWageBudgetWithText, ClubSeasonExpectationsNewWageBudget |
| 60 | 11 | CLUB_COLLECTIVE_WIN_BONUS | league | 5 / 3 / 0 | 0.38 | 0 | BonusHasMultiplyDomesticDivision, BonusCupData, BonusContinentalData, Competition, BonusLeagueString |
| 61 | 16 | CODE_OF_CONDUCT | none | 5 / 12 / 0 | 0.65 | 0 | OffencesThisSeasonString, PreviousPlayerOffences, MostRecentOffenceString, Fines |
| 62 | 3 | ADJUST_SEASON_EXPECTATIONS | league | 1 / 3 / 0 | 0.09 | 0 | ClubSeasonExpectationsNewRemainingWageBudgetWithText |
| | **matches and competitions** | | | | | | |
| 63 | 18 | COMPETITION_TACTIC | ucl | 142 / 76 / 3 | 4.93 | 0 | SelectedTeamFitnessLevels, MaxSubsString, TacticalStyleIntensityLevelString, ShotsFromDistance, TacticalStyleIsSuggested, OppositionPlayerShowOnToFootOptions, CurrentTacticSlot (+127 more). Blocker: needs screen parameter 0x56d1928 |
| 64 | 28:COMPETITION_UI_HANDLER | COMPETITION | dref | 121 / 135 / 11 | 38.78 | 100 | TransferInOutListCount, TeamPointsDeduction, TransferInOutValidTypes, TransfersForeignImportInWindowInfo, LatestManagerMovement, TransferWindowClubDataList, PlayerStatsDropdownCategories (+104 more). Blocker: external call _pthread_mutexattr_init |
| 65 | 50 | FIXTURE | squad_player | 53 / 109 / 2 | 2.0 | 0 | HomeShotsOnTarget, HomeFouls, TeamNewsLong, AnalysisData, HomePossession, AwayFouls, AwayCorners (+36 more). Blocker: needs screen parameter 0x56d1278 |
| 66 | 93 | SET_PIECE | team | 32 / 52 / 1 | 7.06 | 0 | PenaltyChangeAlreadyTaken, SetPiecesFreeKickDefensiveRoutinesCreated, SetPiecesTotalRoutinesCreated, SetPiecesFreeKickAttackingRoutinesCreated, CurrentSetPieceRoutineDefendAvailable, PenaltyChangeIfMissed, FilteredPlayers (+19 more). Blocker: needs screen parameter 0x56d1c38,0x56d1c48 |
| 67 | 61 | MATCH | next_fixture | 25 / 55 / 0 | 52.96 | 22 | MatchTeamHasPendingChanges, MatchDugoutTimelineEvent5, MatchDugoutSelectedEvent, MatchHomeTeamName, Tactic, MatchImportance, MatchDugoutIsSelectedEventActionable (+16 more). Blocker: needs screen parameter 0x56d16c8 |
| 68 | 9 | CALENDAR | next_fixture | 21 / 28 / 0 | 7.32 | 0 | SmallDaysOverview, TrainingSchedules, CurrentTrainingSession, TrainingSessionCategoryDropdown, FirstTrainingScheduleCategory, MatchPreparation, MonthsDropdownLastIndex (+10 more). Blocker: needs screen parameter 0x56d1198 |
| 69 | 28:STADIUM_UI_HANDLER | STADIUM | dref | 16 / 0 / 0 | 0.32 | 0 | OwnedByString, PitchLength, Nation, MaxPitchDimensions, YearBuilt, Roof, Capacity (+9 more) |
| 70 | 94 | SET_PIECE_WIZARD | team | 12 / 6 / 0 | 8.48 | 0 | CurrentCreatorSubstep, TotalCreatorSubsteps, AnswerList, SetPieceCreatorState, MaxSubstep, MaxCreatorStep, QuestionID (+1 more) |
| 71 | 17 | COMPETITION_STAGE | none | 8 / 23 / 0 | 0.34 | 0 | NumberOfPots, PotListDropdown, CupTree, StageHasTeamsToDraw, LeagueTableShowsPenaltyWinsAndLosses, LeagueNumberTeams, LeaguePositionRulesHavePrizes (+1 more). Blocker: needs screen parameter 0x56d1858 |
| 72 | 25 | CUP_TIE | staff | 3 / 7 / 0 | 0.16 | 0 | Fixture, AwayTeam, HomeTeam |
| 73 | 51 | FIXTURE_ID | next_fixture | 2 / 0 / 0 | 0.46 | 0 | Fixture |
| 74 | 40 | COMPETITION_DRAFT | squad_player | 1 / 2 / 0 | 0.08 | 0 |  |
| 75 | 6 | ARRANGE_FRIENDLY | none | 1 / 0 / 8 | 0.29 | 0 | MatchRules. Blocker: external call _asinf |
| 76 | 126 | TEAM_TACTIC | none | 0 / 0 / 0 | 0.14 | 0 | nothing: input null or low pointer dereference 0x0 |
| 77 | 28:FIXTURE_NAME_UI_HANDLER | FIXTURE_NAME | dref | 0 / 0 / 0 | 0.06 | 0 | nothing: every key unset (no binding produced data) |
| 78 | 32 | DB_SUMMARY_COMPETITION | none | 0 / 13 / 0 | 0.04 | 0 | nothing: every key unset (no binding produced data) |
| 79 | 37 | DB_SUMMARY_STADIUM | none | 0 / 2 / 0 | 0.02 | 0 | nothing: every key unset (no binding produced data) |
| 80 | 53 | FUTURE_FIXTURE | league | 0 / 0 / 0 | 0.02 | 0 | nothing: every key unset (no binding produced data) |
| 81 | 62 | MATCH_PLAYER | none | 0 / 45 / 0 | 0.05 | 0 | nothing: every key unset (no binding produced data) |
| 82 | 63 | MATCH_PLAYER_STATS | none | 0 / 80 / 0 | 0.15 | 0 | nothing: every key unset (no binding produced data) |
| 83 | 64 | MATCH_TACTIC | none | 0 / 67 / 0 | 0.49 | 0 | nothing: input null or low pointer dereference 0x0 |
| 84 | 84 | PROPOSED_FIXTURE | none | 0 / 0 / 0 | 0.03 | 0 | nothing: every key unset (no binding produced data) |
| | **news and conversations** | | | | | | |
| 85 | 70 | NEWS_ITEM | news | 39 / 8 / 0 | 0.75 | 0 | AttachmentsNewsItem, NewsItemIsPriority, BackgroundImageData, NewsItemTimeSent, NewsActionData, TagsList, ManagerTaskTitle (+25 more). Blocker: needs screen parameter 0x56d1258 |
| 86 | 23 | CONVERSATION_EDIT_SESSION | none | 11 / 12 / 0 | 0.32 | 0 | ConversationSummaryHasPromises, ConversationSummaryHasNotableHighlights, ConversationInteractees, ConversationSummaryHasActions, ConversationSummaryHasPlayerTargets, ConversationSpectatorsDescriptionString, ConversationRoomAtmosphere (+3 more) |
| 87 | 127 | TEAM_TALK | none | 8 / 3 / 0 | 0.1 | 0 | PlayerCount, TeamTalkGroupType, TalkingTo |
| 88 | 81 | PRESS_CONFERENCE_EDIT_SESSION | none | 7 / 4 / 0 | 0.07 | 0 | NumberOfJournalistsAttending, PercentageOfQuestionsAsked, JournalistSpeaking, ConversationRoomAtmosphere |
| 89 | 108 | STAFF_MEETING | none | 6 / 12 / 0 | 0.34 | 0 | StaffMeetingSingleCategoryTopicList, StaffMeetingSplitTopicsList, TacticalMeetingCompetitionString, StaffMeetingType, StaffMeetingAllCategoriesSplitTopicList, TacticalMeetingOppositionString. Blocker: needs screen parameter 0x56d16c8 |
| 90 | 24 | CONVERSATION_EDIT_SESSION_SELECTION_DIALOG | none | 3 / 2 / 0 | 0.1 | 0 | ConversationValueSelectionDataPossibleValues, ConversationValueSelectionDataUsesCashValue, ConversationValueSelectionDataCurrentValue |
| 91 | 59 | INTERACTION_PERSON_AND_BODY_LANGUAGE | none | 2 / 0 / 0 | 0.03 | 0 | InteractionBodyLanguage, Person |
| | **world database** | | | | | | |
| 92 | 28:CONTINENT_UI_HANDLER | CONTINENT | dref | 26 / 15 / 0 | 1.69 | 0 | TransferListSelectedDate, NationCoefficients, TransferListContinentValidTypes, WorldChildren, TransferOverviewContinent, AfricanCaribbeanPacificGroup, TransferListContinent (+18 more). Blocker: needs screen parameter 0x56d1668 |
| 93 | 28:NATION_UI_HANDLER | NATION | dref | 20 / 17 / 0 | 2.24 | 0 | TransferListSelectedDate, Agreements, MainWomanTeamContainer, TitlebarForegroundColour, ClubListNation, TransferOverviewNation, TransferListNationValidTypesDefault (+13 more) |
| 94 | 28:AWARD_UI_HANDLER | AWARD | dref | 10 / 25 / 0 | 2.23 | 0 | TableStatType, PastWinnerDefault, PastWinners, AwardUiType, AwardPeriodString, Nation, ShortName (+3 more) |
| 95 | 28:LANGUAGE_UI_HANDLER | LANGUAGE | dref | 10 / 3 / 0 | 0.1 | 0 | Surname, HighlightFlags, ShirtName, Initials, Editor, InitialSurname, Index (+1 more) |
| 96 | 28:NATIONAL_TEAM_CONTAINER_UI_HANDLER | NATIONAL_TEAM_CONTAINER | dref | 4 / 18 / 0 | 0.77 | 0 | YouthRating, FifaRanking, NationTabIndex, ReputationScope |
| 97 | 28:AGREEMENT_UI_HANDLER | AGREEMENT | dref | 2 / 0 / 0 | 0.68 | 0 | Nations, NationsCount |
| 98 | 30 | DB_SUMMARY_CITY | none | 0 / 2 / 0 | 0.06 | 0 | nothing: every key unset (no binding produced data) |
| 99 | 31 | DB_SUMMARY_CLUB | none | 0 / 15 / 0 | 0.05 | 0 | nothing: every key unset (no binding produced data) |
| 100 | 33 | DB_SUMMARY_CONTINENT | none | 0 / 12 / 0 | 0.03 | 0 | nothing: every key unset (no binding produced data) |
| 101 | 34 | DB_SUMMARY_LANGUAGE | none | 0 / 1 / 0 | 0.02 | 0 | nothing: every key unset (no binding produced data) |
| 102 | 35 | DB_SUMMARY_NATION | none | 0 / 31 / 0 | 0.03 | 0 | nothing: every key unset (no binding produced data) |
| 103 | 36 | DB_SUMMARY_PERSON | none | 0 / 2 / 0 | 0.03 | 0 | nothing: every key unset (no binding produced data) |
| | **game, editor and online** | | | | | | |
| 104 | 57 | IGE_MOVE_PERSON | none | 42 / 2 / 0 | 0.52 | 0 | PurchaseAfterMatchesPlayed, LoanPlayingMonthlyFee, FutureBuyBackPriceListProps, TransferFee, Date, LatestIGETransferDate, PurchaseAfterAchievement (+27 more) |
| 105 | 5 | APPLICATION | none | 39 / 16 / 11 | 0.36 | 0 | DisableStore, EnableTranslationDebug, DisableAchievements, UserIsAdult, AllowFmcStore, ComputerPerformance, DisableWorkshopPublish (+25 more). Blocker: external call _SteamInternal_ContextInit |
| 106 | 89 | SAVE_GAME_SUMMARY | none | 19 / 12 / 0 | 0.32 | 0 | GameSummaryHumanCharacterSettings, TitlebarForegroundColour, Competition, GameSummaryCompetitionSecondaryColour, GameSummaryCompetitionPrimaryColour, GameSummaryTeamPrimaryColour, GameSummaryTeamSecondaryColour (+11 more) |
| 107 | 54 | GAME | squad_player | 18 / 13 / 42 | 19.63 | 0 | ContinentalRuleGroups, DatabaseRecordsCommonType, InternationalRuleGroups, ManageableClubsEditable, NationalRuleGroups, PossibleDivisionLevelsToAdd, FutureTransferMode (+5 more). Blocker: unreadable live memory |
| 108 | 55 | GO_ON_HOLIDAY | squad_player | 16 / 3 / 0 | 0.95 | 0 | LatestReturnDate, AchievementWarningMessage, ReturnDateDropdown, ApplyForJobsDropdownSelectedOption, ApplyForJobs, ApplyForJobsDropdown, ReturnDateType (+7 more) |
| 109 | 86 | RETAIN_PLAYER_FILTER | none | 12 / 6 / 0 | 13.11 | 0 | FantasyDraftSelectedReputationBand, Continents, FantasyDraftFilterPresets, FantasyDraftReputationBands, FantasyDraftSelectedReputationComparator, FantasyDraftReputationComparators, Competitions (+5 more) |
| 110 | 115 | TEAM_SETTINGS_EDIT_SESSION | none | 9 / 4 / 0 | 0.11 | 0 | TrainingResponsibilityGroup, AdviceAndReports, ResponsibilityHumanPreferencesItem, ResponsibilityTabList, SelectedResponsibilityTab, SetPieceTacticResponsibility, ResponsibilitySimpleTabList (+2 more) |
| 111 | 44 | FANTASY_DRAFT | none | 9 / 5 / 0 | 0.31 | 0 | UserCurrentPlayersSetIndexShuffleDraft, ShuffleDraftPickedPlayersInfo, TopDraftPicks, FullSquadsDropdown, PausePerson, ShuffleDraftPlayersNumberInEachSet, ShuffleDraftMaxPicks (+2 more) |
| 112 | 46 | FANTASY_DRAFT_GAME | league | 8 / 9 / 0 | 0.39 | 0 | PlayerPoolName, SelectedVersusCompFormat, TimeString, NextRedraftReturnsAndRemoves, NextRedraftDate, DraftRoundTimeLimit |
| 113 | 111 | STORE | none | 6 / 3 / 7 | 0.29 | 0 | Updated, WalletItemsFilters, TransferBudgetLimitToAccept. Blocker: external call _CFStringCreateWithCStringNoCopy |
| 114 | 71 | ONLINE_LOBBY | none | 6 / 9 / 0 | 0.21 | 0 | LobbyConnectedPlayers, LobbyActiveManagers, SelectedVersusCompFormat, LobbyPassword, DontSeeNewsForOtherHumans, MatchSchedulingOptions |
| 115 | 112 | STORE_ITEM | none | 5 / 4 / 2 | 0.06 | 0 | BoostBankBalanceCashValue, IAPType, CappedAmountApplicable, ApplyRestrictionType, NumberOfEventsToUnlockItem. Blocker: external call _CFStringCreateWithCStringNoCopy |
| 116 | 69 | NETWORK_CONNECTION | none | 5 / 3 / 0 | 0.04 | 0 | ConnectionPlatform, HumanIsOnThisMachine, HumanStatusAction, HumanStatus |
| 117 | 72 | PERSON_FILTER | none | 5 / 16 / 0 | 0.03 | 0 | ScoutedPlayersOnlySelected, FilterAttributesApplyToAll, IncludeOwnStaffSelected |
| 118 | 88 | RULE_GROUP | none | 5 / 19 / 3 | 0.06 | 0 | Nation, MensRuleGroup, WomensRuleGroup. Blocker: needs screen parameter 0x56d11f8 |
| 119 | 110 | STATIC_STRING | none | 3 / 2 / 0 | 0.3 | 0 | NonPlayerAttribute, StadiumSurface, CoachingBadge. Blocker: needs screen parameter 0x56d14a8 |
| 120 | 41 | EDIT_SESSION_UNDO_BUFFER | none | 3 / 0 / 0 | 0.03 | 0 |  |
| 121 | 47 | FILTER | none | 3 / 4 / 0 | 0.23 | 0 | CompareRulesTabString, AttributeRulesTabString |
| 122 | 66 | MULTIPLAYER | news | 3 / 4 / 4 | 0.41 | 0 | ReportReasons, AmountOfBlockedPlayers, AmountOfBannedPlayers. Blocker: external call _SteamInternal_ContextInit |
| 123 | 144 | VERSUS_MODE_FORMAT | none | 2 / 0 / 0 | 0.38 | 0 | VersusGameMinNumberTeams, NumberOfTeams |
| 124 | 4 | AFFILIATE_EDIT_SESSION | none | 2 / 1 / 1 | 0.05 | 0 | Count, SelectedAffiliateClub. Blocker: null or low pointer dereference |
| 125 | 42 | EDITOR | none | 2 / 7 / 0 | 0.04 | 0 | FindField |
| 126 | 83 | PRIORITISE_FUTURE_TRANSFERS | none | 2 / 5 / 0 | 0.04 | 0 | Selected |
| 127 | 98 | SEARCH | none | 2 / 17 / 0 | 0.31 | 0 | DatabaseTableTypeString, SearchIsFinished. Blocker: needs screen parameter 0x56d16c8 |
| 128 | 99 | SEARCH_RESULT | none | 1 / 5 / 0 | 0.02 | 0 | DatabaseRecordType |
| 129 | 107 | UI_HANDLER | none | 0 / 0 / 0 | 0.02 | 0 | nothing: every key unset (no binding produced data) |
| 130 | 109 | START_DATE | none | 0 / 1 / 0 | 0.04 | 0 | nothing: every key unset (no binding produced data) |
| 131 | 116 | TEAM_SETTINGS_EDIT_SESSION_ADVICE_AND_REPORTS | none | 0 / 14 / 0 | 0.11 | 0 | nothing: every key unset (no binding produced data) |
| 132 | 117 | TEAM_SETTINGS_EDIT_SESSION_ADVICE_GIVER_ROW | none | 0 / 2 / 0 | 0.12 | 0 | nothing: every key unset (no binding produced data) |
| 133 | 118 | TEAM_SETTINGS_EDIT_SESSION_ADVICE_TOGGLE_ROW | none | 0 / 2 / 0 | 0.09 | 0 | nothing: every key unset (no binding produced data) |
| 134 | 119 | TEAM_SETTINGS_EDIT_SESSION_CUSTOMISE_ADVICE | none | 0 / 3 / 0 | 0.11 | 0 | nothing: every key unset (no binding produced data) |
| 135 | 120 | TEAM_SETTINGS_EDIT_SESSION_INDIVIDUAL_RESPONSIBILITY | none | 0 / 9 / 0 | 0.09 | 0 | nothing: every key unset (no binding produced data) |
| 136 | 121 | TEAM_SETTINGS_EDIT_SESSION_OFFER_TO_CLUBS | none | 0 / 29 / 0 | 0.14 | 0 | nothing: every key unset (no binding produced data) |
| 137 | 122 | TEAM_SETTINGS_EDIT_SESSION_RESPONSIBILITY_GROUP | none | 0 / 12 / 0 | 0.12 | 0 | nothing: every key unset (no binding produced data) |
| 138 | 123 | TEAM_SETTINGS_EDIT_SESSION_RESPONSIBILITY_HUMAN_PREFERENCES | none | 0 / 14 / 0 | 0.06 | 0 | nothing: every key unset (no binding produced data) |
| 139 | 124 | TEAM_SETTINGS_EDIT_SESSION_RESPONSIBILITY_TAB | none | 0 / 4 / 0 | 0.07 | 0 | nothing: every key unset (no binding produced data) |
| 140 | 27 | UI_HANDLER | none | 0 / 0 / 0 | 0.03 | 0 | nothing: every key unset (no binding produced data) |
| 141 | 29 | DATABASE_VERSION | none | 0 / 0 / 1 | 0.04 | 0 | nothing: server key db  : external call _CFStringCreateWithCStringNoCopy |
| 142 | 43 | EDITOR_FIELD | none | 0 / 28 / 0 | 0.03 | 0 | nothing: every key unset (no binding produced data) |
| 143 | 45 | FANTASY_DRAFT_AI_MANAGER | none | 0 / 0 / 2 | 0.03 | 0 | nothing: external call _CFStringCreateWithCStringNoCopy |
| 144 | 48 | FILTER_RULE | none | 0 / 0 / 0 | 0.02 | 0 | nothing: every key unset (no binding produced data) |
| 145 | 49 | FILTER_RULE_ITEM | none | 0 / 2 / 0 | 0.08 | 0 | nothing: every key unset (no binding produced data) |
| 146 | 52 | UI_HANDLER | none | 0 / 0 / 0 | 0.02 | 0 | nothing: every key unset (no binding produced data) |
| 147 | 60 | UI_HANDLER | none | 0 / 0 / 0 | 0.03 | 0 | nothing: every key unset (no binding produced data) |
| 148 | 7 | UI_HANDLER | none | 0 / 0 / 0 | 0.02 | 0 | nothing: every key unset (no binding produced data) |
| 149 | 82 | PREVIOUS_STAGE_TEAM_LINK | none | 0 / 1 / 0 | 0.02 | 0 | nothing: every key unset (no binding produced data) |
| 150 | 87 | RETAIN_PLAYER_FILTER_RULE_BOX | none | 0 / 2 / 0 | 0.02 | 0 | nothing: every key unset (no binding produced data) |

## Shaped screens

Each function takes a `UiHandlerVM` or a live session and returns named fields, the recipe of
every handler it used, coverage, unavailable reasons, `fields_using_random_draws`, seconds and
RNG draws. Times are warm-VM times on the reference save; the first call on a new VM adds
5-15 s of page faults. Every screen except `medical`, `manager_profile` and
`season_expectations` drew no random numbers.

| Function (tool) | Recipe | Value / unset / unavailable | Time | Facts to check on screen |
|---|---|---|---|---|
| `scouting` (`fm_get_scouting`) | type 90 (scouts), 91 (players scouted specifically), 92 (teams), 97 SCOUTING_INFO with `iyrZ` = team (recruitment focuses, budget, range), each focus through type 85 `{PbPY, iyrZ, rfid}`, CLUB `4Ynn`/`wZfj` (knowledge by nation and region) | 219 / 5 / 0 | 9.4 s | 13 scouts; 7 players scouted specifically, among them Moisés Caicedo and Lennart Karl; 10 recruitment focuses, focus 18 "In Progress" with Moritz Steidten and Ged Murphy, 20 recommended and 27 near misses; Portugal knowledge Exceptional (Bruno Reis); 39 nations, 15 regions |
| `transfers` (`fm_get_transfer_activity`) | type 131 TRANSFER_ACTIVITY, CLUB budget keys, type 142 TRANSFER_WINDOW with `comp` = managed league | 29 / 6 / 0 | 1.4-2.2 s | no active player, staff or trade offers; window 1 Jan - 3 Feb 2031, 22 days until it opens (`days_remaining` counts to the opening while closed); remaining wage budget £25.5M p/a |
| `squad_dynamics` (`fm_get_squad_dynamics`) | TEAM (type 28, team dref), no slot-17 inputs | 13 / 0 / 0 | 0.7 s (30 s with the TEAM inputs; identical values) | team leaders Livramento, Kobel, Gordon; 11 highly influential, 7 influential, 5 other; dressing-room atmosphere level 6 |
| `training` (`fm_get_training_schedule`) | type 128 with `Ttea` and `PbPY` (hole 3) | 16 / 2 / 0 | 1.3 s | Tuesday: Travel, Match, Travel; Monday: Chance Creation, In Possession Shape, Final Third; last week "Tactical Focus - Out Of Possession"; performance "Very Good", average 7.77 |
| `medical` (`fm_get_medical_centre`) | TEAM, no inputs | 8 / 0 / 0 | 3.1 s, 136 draws (risk assessment and recurring injuries) | "14 at risk"; "None exhausted and 3 recurring injuries"; "No players expected to return vs Villarreal C.F."; 14 medical staff |
| `finances` (`fm_get_finance_projections`) | CLUB | 29 / 0 / 0 | 0.8 s | balance £26,390,569; income this season £631,353,163; projected profit end of 2030/31 £59,241,351; projected transfer budget £92,979,220 |
| `youth_intake` (`fm_get_youth_intake`) | CLUB | 3 / 4 / 2 | 0.3 s | 96 days to the intake; youth facilities "Great". Level and feedback: `std::random_device` (server key `CNGr`) |
| `league_table` (`fm_get_league_table`) | COMPETITION `stgr` gives the stage record `{dref, year, mnst, sbst, ssst}`; type 17 `lgtb`, `lxgt` | 9 / 0 / 0 | 2.0 s | Arsenal 1st, 16 played, 38 points; Newcastle 4th, 15 played, 31 points; top scorer Thierno Barry 12 |
| `manager_profile` (`fm_get_manager_profile`) | PERSON on the manager; TEAM_CONFIDENCE for job security | 17 / 0 / 0 | 19 s, 16 draws | preferred mentality Adventurous, pressing Balanced; wage £3.85M p/a; renewal advice "Delay Decision"; job security from contract 45 |
| `season_expectations` (`fm_get_season_expectations`) | type 15 CLUB_VISION_MEETING_SEASON_EXPECTATIONS | 5 / 0 / 0 | 6.8 s, 4 draws | UCL Semi Final / Required; Premier League 4th / Required; Emirates FA Cup Final / Preferred; Carabao Cup Quarter Final / Favoured |
| `fixture_result` (no tool) | type 50 with the game's own record (below) | 19 / 4 / 0 (23 keys) | 0.9-2.5 s | Newcastle 0-0 Sheffield United, 15:00, possession 44 / 56, 57°F calm |

Not verified: incoming and outgoing offers are empty lists because the club has none on this
date, so their row shape is unknown; all ten recruitment focuses read "Any" for positions
(not checked against the screen); unit membership in training (below).

## The four holes

### 1. Club vision judgements: not available (0 of 21 read)

The vision list getter `ViOl` reads only server keys `COlY` (true), `Ccse` (2030), `CvBo` /
`Cvso` (the serialised objectives) and `cmtm` (the team), with parameters owner, filter and
flag. Per objective it returns `cvon cvoi coip cvoc hint Viys VOse VOdt cvos cvop aZDo comp`.
`cvop` is 6 on all 26 board and supporter rows, in the serialised `CvBo` bytes as well;
`aZDo` (VisionObjectivePerformance, 0x1A26C88) formats a linked object for link types 1-3 and
is empty here; the flag parameter (0, 1, 2) changes nothing. Across the 150 sweep jobs the
words "On Course", "Reserving Judgement" and "Not Judging" occur once, in a TEAM_CONFIDENCE
board highlight ("The board are pleased that the team is currently on course to reach the
Quarter Final of the UEFA Champions League."). The same highlight list says the board is
pleased the team won the Community Shield and reached the EFL Cup quarter final. Those are
sentences about three competition objectives, not per-objective judgements, and
TEAM_CONFIDENCE has no per-objective list. The judgement column is most likely computed in
the front end (GameAssembly), which this emulator does not run.

Two raw fields line up with the screen without being judgements: `cvos` = 1 only on "Be
competitive in the Community Shield" (screen: Passed, 1 of 1) and `VOdt` = 1 exactly on the
four contract-length rules (screen: Not Judging, 4 of 4). They are recorded here, not
returned as judgements.

### 2. "Challenge for the FA Cup": found as a season expectation

The FA Cup is absent from `CvBo` under every filter, owner and flag, and from the vision
meeting's objectives for each year (type 14 `K4uX`, year parameter 0x56D1A28 = 0..5). It is
present in the board's season expectations (type 15 `Rp8X`): Emirates FA Cup, importance 4,
expected stage "Final", minimum option "Reach Quarter Final", can be set to not judged. The
importance band gives Preferred, as on the screen. The row text "Challenge for the FA Cup" is
not produced by any handler; the screen builds it. `fm_get_season_expectations` returns the
row. The other three expectations agree with the vision importances (UCL 10 Required, EFL Cup
1 Favoured).

### 3. TEAM_TRAINING: fixed

The input `TiSc` needs `PbPY` (the manager's person id) in the record; without it the server
dereferences null at 0x43FEB48 and all four units read "Goalkeeping Unit". Leave-one-out over
the full context record shows only `Ttea` and `PbPY` matter. With them `TiSc` transfers, the
units read Goalkeeping, Defensive, Midfield and Attacking, and the current and next week's
schedules, last week's template and category, focus, rating and the training squad return
values. Unit membership is not exposed: the unit records carry name, index and involvement
level, and `kpQq` (Units) stays unset.

### 4. Fixture result: score and result fixed, venue not

Two changes. The client inputs (`isVM lasc slLL tims`) must be transferred first: `slLL`
carries the score. And the record must be the one the game builds (TEAM_CONFIDENCE
`MatchConfidenceFixtureList` entries): `{fhmT, fawT, fdte, ctxt: viewing team, VMty: -1,
frhi: -1, frht: -1}`. `ctxt` is the viewing team's id; server key `FxRl` reads it from the
record through 0x207304 before falling back to HUMAN+0x438 (the null at 0xCB51D8). Result for
Newcastle v Sheffield United (7 Dec): home 0, away 0, "0 - 0", result type 9, has result and
final result true, home xG 1.93. For the unplayed Villarreal match the handler reads -1;
`fixture_result` returns null scores when `has_result` is false. `MatchVenue` (`KmOX`) and
`MatchVenueShort` stay empty strings: the server key computes without error and returns "".

## Stability (read order)

`tests/test_fmdb_ui_stability_live.py` reads board confidence, 20 player statuses, the
60-day calendar and the club vision in one VM, then in a second VM in the reverse order
(players reversed too), and compares everything except timings: identical, 80 s for both
orders. The order dependence seen earlier (bag inserts touching the variant pool) stays fixed
by the pinned baseline in `DataReader` and `KeyReader`.

The stale-page failure recurred twice in this lane: a RECRUITMENT_FOCUS build faulted (null
dereference in the factory) on a VM that had read many handlers and built on a fresh one, and
one TEAM sweep pass returned "write to shipped code" for 160 keys. Both now trigger
`refresh_live_memory` and a retry (cost ~15 s when it happens). A fresh VM per handler family
would cost 5-15 s of page faults per family on every call, so the retry is cheaper.

## Shared-file edits

`ui_tools.py`: additive registration (`register_more_ui_tools`, `MORE_SCREENS`,
`COMPETITION_TABLE_TYPE`) and three `RECORD_DOCS` entries (types 128, 50, 97). No change to
`ui_vm.py`, `ui_handlers.py`, `ui_recipes_news.py` or `ui_recipes_person.py`.
