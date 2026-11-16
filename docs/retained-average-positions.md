# Official retained tracking average positions

`decode_tracking_average_positions` reconstructs the all-sample native `AveragePositionMap` product. `capture_source(..., include_tracking=True)` adds bounded tracking reads to the existing canonical retained-result owner checks. The default capture payload stays unchanged.

## Source binding

The managed keys `HomeAveragePositionMap` (`4d553564`) and `AwayAveragePositionMap` (`464f6a7a`) select native `29f6ec`, which calls `1a65e8`. That renderer calls `4896890` with player slot and ordered side. It searches the CBE `+d0` vector of 40-byte records using signed key `slot*2+side`. Each record holds a uint32 start tick at `+8` and a vector of signed int16 coordinate pairs at `+10`. Every pair occupies four bytes. The iterator advances 24 native ticks per pair.

Native `1a67ec..1a6884` multiplies each coordinate by float32 `0.01` or `-0.01`, accumulates with float32 FMADD, then divides by the sample count converted to float32. Stationary samples count. The denominator is the number of position samples, independent of touches, passes, event counts and minutes. The Python decoder uses host `fmaf` to preserve that rounding path.

Native `4895a60` selects the sign using CBE `+108/+10c/+110` int32 boundaries and side flags `+115/+116`. The decoder follows each strict comparison and applies the result separately at each sample tick. It preserves both axes as `native_axis_0` and `native_axis_1`. Half-extents at CBE `+100/+104` support pitch plotting, but physical unit names and human left/right labels remain unproved here.

The runtime capture checks exact native instruction spans for the getter, sign selector, iteration, accumulation, divisor and official route. Stream bounds, duplicate player keys, canonical slot identities, sample width, count budgets and tick overflow fail closed.

## Independent pass-map product

The pass-map renderer `1a5368` calls `4893cec` and `4893f70`. Those functions average accepted category7 event origin float32 pairs at `+18`, grouped by source player slot. Their denominator counts accepted completed-pass-map events, including the unlabelled mask8 subset. This pass-origin mean differs from the official tracking mean above. A visualization can place passing edges at the tracking positions when it labels that combination explicitly.

## Frozen Newcastle control

The retained result `136523` on 2 November 2030 is Newcastle United 3–1 Southampton. The capture owner is team688. The frozen source contains 32 tracking streams and 23,953 coordinate samples. The canonical retained match frame resolves every stream to a named player; eight further match-frame player rows have no tracking stream.

Aaron Ramsdale has 1,002 samples and means `(-0.24314433336257935, -39.131019592285156)`. Christian Kofane has 1,002 samples and means `(-0.5774760246276855, 11.110604286193848)`. Gift Orban has 75 samples and means `(-6.198801040649414, 7.819601058959961)`.

`tests/fixtures/retained_tracking_average_positions.json.gz` preserves the raw coordinate pairs, orientation profile, canonical player rows and expected reconstruction. The regression verifies this reconstruction; it does not claim an independent screenshot or rendered-property readback. The game was read only. No game function, input or memory write supplied the result.

## Possession subsets

Each player also has `possession_means.in_possession` and `possession_means.out_of_possession`, with separate sample counts and float32 coordinate means. Native `48928b4` clamps `tick//24` into the CBE `+e8` byte stream. Byte `-1` contributes to neither subset; byte0 selects the home side and byte1 the away side. Other values follow the native out-of-possession branch and produce an explicit unmapped-phase caveat. Missing streams retain unknown subset means.

The Newcastle control contains only bytes0,1 and-1. Kofane has523 in-possession samples at `(-0.29950469732284546,20.14513397216797)`,432 out-of-possession samples at `(-0.9886336922645569,0.6653483510017395)` and47 unclassified samples. These sum to his1,002 all-position samples.

## Coverage caveat

The Newcastle source preserves zero tails after players leave. Alberto Costa and Lewis Hall each have888 stored samples, including407 trailing `(0,0)` pairs; their last nonzero sample is native tick11544. Tino Livramento and El Hadji Malick Diouf begin at11664. Assignon has888 samples including336 trailing zeros. The official renderer counts those zeros in its denominator and its phase subsets. The decoder preserves that behavior and reports zero counts, first/last nonzero ticks and `on_pitch_time_coverage_verified:false`. A count of stored samples cannot establish minutes played or active movement. Removing zeros would create a different statistic.

A fresh typed capture after the game advanced to3November reproduced all32 frozen rows exactly. It verified the native source spans, result fixture136523 and each canonical retained player identity. Half-extents were34 and52.5 native units.
