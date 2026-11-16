# Live transfer offer records

`fm_query_transfer_offers(session_id, person_native_id=None, team_native_id=None,
club_native_id=None, raw_state_codes=None, limit=50, cursor=None)` reads both
proved offer vectors from the running transfer manager. Native IDs are positive
integers. Filters combine with AND; a club matches the owner of any common TEAM
link. A person filter selects the common primary PERSON, not additional trade
participants. Follow `next_cursor` with the identical selectors and limit.

The result includes source-wide class/state counts, vector slot/null counts,
canonical PERSON/TEAM/club identities, source-local opaque offer identity and
raw current state. Each membership is retained if an object occurs twice.
Names may be unavailable even when canonical identity is known. Source changes
invalidate cursors rather than returning a partially stale population.

This collection contains historical offers. It does **not** establish which
are active, accepted, pending, paid or financially binding. `native_state.code`
is the observed byte; `label` stays null. The separately named UI/inbox status
enum is not proved to represent this byte and is not reused. Other transfer
manager collections are outside this proved two-vector scope.

Loan records expose stored proposed playing/unused weekly wages and monthly
fees in the independently decoded base currency, when available. These are
proposed terms, not current agreements. Only the loan common TEAM+40 link is
proved to mean proposed borrowing team. Other TEAM roles and the common signed
amount in other offer classes remain explicitly unknown.

A verified empty pair of vectors returns `available_empty` and count zero.
A null manager returns unavailable with unknown counts. Unexpected types,
invalid geometry, read-budget exhaustion or changed consumed bytes fail the
query; none of these becomes an empty result. Bounds are 100,000 vector slots,
100 rows per page and a smaller per-query read budget than the helper permits.
The query executes no native functions and uses no UI, saved-game file or game
writes. Every consumed range is rechecked before returning; this is a checked
read sequence, not an atomic game snapshot.

Native proof and actual captures are in the project working evidence batch
`live-transfer-offers-161`. The patch is a source implementation until separately
released and installed.

## Native bindings and practical scope

The typed `TRANSFER_MANAGER` singleton has a public `BASE_TRANSFER_MANAGER`
subobject at +0x18 (RTTI descriptor and native destructor call agree).
The BASE reader's two offer vectors therefore land at live manager +0x20 and
+0x38. Every non-null object must have one of eight exact RTTI/factory kinds;
an unknown kind rejects completeness. Common serializers bind PERSON +0x38
and TEAM +0x40/+0x48; the loan consumer additionally reads TEAM +0x50.
The state classifier reads +0x8D. The factory kind getter and eleven native
instruction spans are checked on every nonempty manager query.

The typed loan constructor/copy chain (native 0x2DF275C, 0x13727C8,
0x2DF28C0) binds offer TEAM +0x40 to proposed borrower. Proposed weekly wage
copies are bound by 0x2DF28A8; monthly copies by 0x2DF2974. Source disassembly
and full plugin fingerprint verification are recorded in project working
batches `live-transfer-offers-161` and `live-transfer-offers-179`.

A practical question is: “Which retained loan proposals mentioning my club
exist, who is the proposed borrower, and what terms were stored?” Use the club
native ID, follow every page and select `offer_type == 'loan'`. Read all four
playing/unused wage/fee fields independently. A question such as “Which active
bids must I respond to today?” remains unsupported: the collection is historical
and raw state codes have no proved English meaning. Do not collapse multiple
proposals for one person, infer recency from slot order, or treat these stored
terms as signed contracts.

The .111 compatibility check used the current open career on 11 November 2030:
23,120 distinct objects, 76 Newcastle-linked memberships and 74 available names
plus two identified retired-name-pointer people with unavailable names. These
are dated evidence, not counts baked into the implementation. The candidate
MCP surface returned the full club result in 7.68 seconds. A source-change
rejection followed by a fresh successful read retained all strict checks.
