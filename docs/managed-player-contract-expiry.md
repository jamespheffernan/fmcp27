# Managed player main-contract expiry query

`fm_get_managed_player_contract_expiry` classifies every membership slot on one
selected manager's native `TEAM+0x38` roster against a required civil-date cutoff.
It matches only verified fixed main-contract expiries on or before that date,
including already expired dates. It retains duplicate memberships and nulls.
The roster can contain loaned-out players and does not establish whole-club
coverage.

This private candidate uses reader157's `Bridge._read_scope(final_verify=seal)`.
It introduces no native function calls, profile expansion, attribute reads,
installation, version change or disk-save fallback.

## Request

| Parameter | Contract |
| --- | --- |
| `session_id` | Current attachment. |
| `expires_on_or_before` | Required canonical `YYYY-MM-DD`, year 1850–2200. |
| `coach_name` | Optional active coach name from `fm_get_save`; omission requires exactly one active coach. |
| `limit` | Strict integer 1–100; default 100. |
| `offset` | Strict integer 0–256; default 0. Applies to sorted fixed matches. |
| `expected_source_id` | Lowercase SHA256 from the first page; required when offset exceeds zero. |
| `unclassified_limit` | Strict integer 0–256; default 100. Set 256 to retrieve every unclassified detail row. |

Continue each `next_offset` with the first page's `source_id`, the same cutoff
and the same selected coach. Each call rereads the source; a changed source
rejects continuation. Reads remain non-atomic within and across calls.

## Coverage and accounting

`slot_manifest` always contains one compact row per native membership slot,
bounded at 256. Each entry gives its `roster_index`, canonical identity when
available, record kind, classification and `matches_cutoff`. That last field is
true or false only for a verified fixed expiry; unclassified slots use null.

`native_slot_count` and `scanned_count` count memberships, including null and
duplicate slots. `duplicate_slot_count` counts repeated nonnull memberships
after their first occurrence. Every slot contributes to exactly one
`state_counts` entry:

| Classification | Cutoff treatment |
| --- | --- |
| `fixed_expiry` | Inclusive comparison with the verified main-contract expiry. |
| `dynamic_expiry` | Unclassified; retains the existing decoder's computed date and anchor. |
| `no_contract` | Unclassified; no fixed expiry is inferred. |
| `basic_contract_fields_unavailable` | Unclassified; retains the existing joined-date result. |
| `virtual_unsupported` | Unclassified; preserves canonical identity without expanding a profile. |
| `unsupported_person_kind` | Unclassified; preserves a known canonical non-player identity. |
| `null_slot` | Unclassified; preserves the membership position. |

`classified_count` equals `fixed_expiry_count`. `fixed_nonmatch_count` counts
fixed dates after the cutoff. `matched_count` counts all matching memberships;
`returned_count` counts this page, and `truncated_count` counts matching rows
omitted from this response, including earlier pages. `truncated` reports any
such omission. `has_more` and `next_offset` describe only later matching rows.

`unclassified_count`, `unclassified_returned_count` and
`unclassified_truncated_count` account for the separately bounded
`unclassified_players` list. Unclassified detail rows retain native roster
order. They are never counted as confirmed nonmatches.

Fixed matches sort by expiry, case-folded display name, birth date, canonical
database index, native ID and native roster index. Duplicate matching
memberships remain distinct rows; duplicate returned slots share one new
opaque player reference within that response.

## Sources and rejection

The adapter selects and rechecks the existing canonical HUMAN/TEAM ownership
route. The roster vector reuses the existing bounded null/duplicate-preserving
reader. Each nonnull slot must have a known primary type, matching PERSON
subobject/RTTI and canonical PERSON membership. Actual and combined players
also require the existing PERSON player cast and canonical player membership.
Names, birthday and stock reference identities use the existing narrow
international-duty identity routine. No rich player decoder runs.

`contract_dates.decode` supplies joined, last-signed, expiry and fixed/dynamic/
basic/no-contract classification through its existing checked dispatch, RTTI
and owner route. Main-contract `+0x10/+0x18` TEAM links and PLAYER `+0x128`
current-club TEAM links follow the existing club-link layout. Each linked TEAM
and owner uses `teams.by_index` to check canonical identity, lookup membership,
owner membership and backlink. The two main-contract links must resolve to
the same club. Public rows keep main-contract teams/club and current team/club
separate. A different current club does not itself establish loan status.

The source ID binds process/plugin/career identity, selected coach, cutoff and
all consumed initial-source bytes. That includes every scanned slot's
classification, contract fields and ownership links, even for omitted rows.
Fresh observation timestamps and opaque references do not affect the ID.

The real read scope performs its post-yield process check before `seal`.
`seal` rechecks process, plugin, loaded career/date, coach/TEAM ownership,
complete roster and newly published reference bindings. Every callback runs
before the final complete initial and final-context consumed-byte fences.
Detected drift, short reads, invalid dates, broken canonical ownership,
unrecognised primary/contract types or vector bounds reject the entire result.
Newly created references are removed on rejection.

Loan expiry, future agreements, status10 labels, extension/clause activation,
renewals and departure are outside this query. Dynamic-positive population
coverage remains an independent acceptance gap.

## Private verification and remaining acceptance

Synthetic typed-memory tests exercise the actual Bridge read scope and existing
date decoder. They cover inclusive cutoff, ordering, ties, duplicates, nulls,
all seven classifications, combined players, distinct main/current clubs,
empty and 256-slot populations, complete pinned page union, stale continuation,
malformed/short sources and mutations at post-yield/final callbacks.

Root owns the independent configured live roster and individual-date comparison,
ordinary Pi acceptance, integration review and any release. This candidate has
performed no live reads and establishes no UI or installed-app behavior.
