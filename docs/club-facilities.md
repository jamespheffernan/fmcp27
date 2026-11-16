# Own stored club facilities

Call `fm_find_clubs` and select the correct canonical club, then call `fm_get_club_facilities(session_id, club_ref)`. Names can be duplicated. The response binds the club's table index, native ID and secondary identity, save metadata and fresh read time.

The four fields are signed native levels: training facilities (`Ctlv`, editor0..20), youth facilities (`Cyfb`), youth coaching (`Cytv`, also called junior coaching in the editor layout), and youth recruitment (`Crcb`). The youth editor ranges are-1..20. Each exposes `native_value`, nullable `value` and `state`; -1 is unassigned, zero remains stored. Missing secondary data returns `unavailable_secondary` with null values. Out-of-editor-range values preserve raw signed bytes but return null interpreted values.

These are the club's **own stored** levels. They are not stars or translated quality descriptions. Native effective properties separately evaluate affiliated/shared facilities, inferred defaults and runtime overrides; this tool deliberately reports that effective values were not evaluated. It does not predict player development or intake quality, identify a training ground, expose corporate facilities or estimate investment costs.

Source closure: official editor field labels and bounds in `evidence/editor-contract-frame-50.xml`; native CLUB property getter follows CLUB+100 to secondary signed-byte fields120/12B/12C/12D. Twenty-three exact guards bind keys and loads. See `docs/source-proofs/club-facilities-b161.json` for installed-binary hash, editor hash, instructions, scope and independent control coverage.

Fresh read-only control: 35 clubs in the loaded1November2030save; independently captured canonical IDs and raw bytes match the candidate output35/35. Examples: Newcastle688 (15/14/17/20), Southampton713 (18/17/17/19), Barcelona1708 (20/20/20/20), Crewe641 (15/13/10/8), Gateshead655 (9/8/7/8), NewcastleNIR1900828 (1/1/-1/-1). Order is training/youth facilities/youth coaching/recruitment. Identically named Newcastle United2000290848 has different stored values14/14/9/9, proving why name-only selection is insufficient.

Runtime checks reject changed native property bytes, invalid secondary pointers, stale/foreign club references, changed canonical table membership and consumed-byte drift. Reads are bounded and non-atomic. No UI, native function execution, save-file decode or game writes.
