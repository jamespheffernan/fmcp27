# Retained shot-origin location

Checked retained shot rows expose `native_location_bin` (0–12),
`official_location`, `location_group`, `location_state`, and
`attacked_goal_positive_native_y`. The original x/y remain intact.

The labels come directly from the native renderer's ordered property keys and
installed official managed bindings. The classifier reproduces the renderer's
float32 predicates and priority. It uses each linked event's direction bit,
not the home/away side or a guessed halftime. Both teams and changes of attacking
direction therefore use the same source rule.

Bins0–5 are officially named six-yard/penalty-box locations. Bins6–11 are named
outside-box locations and return `outside_area`. Bin12 is `LocationOutsideBoxFarFromGoal`, but is also the
native fallback for unmatched exact boundary points. `location_group` preserves
this as `outside_area_or_native_fallback` (only bin12); unavailable location groups
remain null. Do not silently treat the fallback group as a
universal geometric outside-the-penalty-area predicate. The native left/right
labels do not establish a human viewing direction.

Pitch half-width and half-length are captured from CBE+0x100/+0x104 in the same
checked read as the event vectors. The renderer doubles these values to obtain
its pitch dimensions. Missing/invalid geometry leaves location fields unknown
while retaining independently verified attempts. Own-goal markers receive
`not_a_statistical_attempt` and no location class.

Coordinate units, metric distances, and human left/right viewpoint remain
unverified. `coordinate_units`, `coordinate_viewpoint`, and `distance_to_goal`
remain null. No screen calibration or statistical correlation supplies them.

Native proof uses plugin SHA256
`774cacde63567fd3901c47719e7a6ed94cc3a0a62e9b94989dcac6b4890ec0e1`:
renderer0x1A366C, predicates0x4895AC8..0x48963DC, key table0x52E0C5C,
pitch dimensions0x1A47BC. Research receipts are under
`evidence/batches/shot-geography-152/`. Offline instruction emulation is a
research oracle; the installed reader neither executes game functions nor
requires an emulator.
