# Stored agreed playing time

`fm_get_player_playing_time(session_id, player_refs)` reads the current
main-contract agreement for 1–100 canonical actual or combined player references.
It returns the native categorical code and the compiled English fallback label.
The query does not calculate actual usage or evaluate promises.

The native source chain is:

- Managed indexed literal2537 `AgreedPlayingTime` registers key`0x32323320`.
- Native181FF8 translates it to`Csqs`; FF5B90 accepts that contract property.
- FF5CA4..FF5CB0 reads the FULL_CONTRACT virtual getter at slot32.
- Getter1005C78 reads the unsigned byte at contract+54. Csqs passes that value
  into15732D0, which stores it under`plti`.
- Formatter172AD44 uses the byte jump table53A1560 to select PLAYER_TYPE IDs.
  Its fallback1559260 uses table539D01C to choose the official English keys.

The older editor`PMsq` source at contract+C4 is separate. Every one of the 28
checked Newcastle managed-roster contracts held signed-1 there while agreed
playing time varied across eight categories. The FM26 squad-role probe explicitly
marked its mappings as guesses, so those mappings were not reused. FM26's staff
promise audit consumes pre-extracted JSON; it does not prove a native promise
collection or enum in FM27.

Codes remain categorical. Codes4 and6 both have the compiled title Squad Player;
codes7 and8 both have Fringe Player. The response preserves the distinct codes.
No numeric ranking, guaranteed minutes or percentage follows. Code0 follows the
native empty frontend display;14 requires contextual rendering;23 is a scouting
placeholder. These and unmapped codes retain a null title and explicit state.
Null and basic contracts have separate unavailable states.

The query verifies canonical PERSON membership and reference identity, native
contract-pointer dispatch, contract RTTI and owner, agreed-time getter and its
instructions, then rechecks consumed bytes. The read remains non-atomic. Virtual
players are unsupported. Custom PLAYER_TYPE strings, selected localized display,
future playing-time pathways, loan-team agreements, promise fulfilment, active
player promises and active club promises remain unproved. Promise fields are
null with`promises_state=not_decoded`.

Read-only candidate validation on the running2030-11-02 career checked28 managed
roster identities. Gordon was Important Player, Woltemade Regular Starter, Miley
Squad Player, Sanusi Breakthrough Prospect, Jay Robinson Star Player and Matthew
Cox Backup. A forged local reference with a wrong canonical index rejected; the
original reference still returned its unchanged agreement. No game function,
input or memory/save write was used.

Reproduce the offline label/accessor verification with the installed binary and
English resource, without attaching to the running process:

```sh
uv run --no-project --with capstone python scripts/verify_playing_time_layout.py
```

The verifier rejects a changed native binary or English-resource fingerprint.
Working proof and read receipts belong in
`evidence/batches/live-playing-time-promises-162/`. This is candidate evidence;
installation and an ordinary installed pi-fm question require separate acceptance.
