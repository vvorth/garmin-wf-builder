# Probe: the text the watch shows for a Boolean, and `Math.round` of a negative half

**Why.** The host prints values in two places the watch also prints them: the
preview draws a `text:` template's readings, and expressions it can fold are
baked in as text. Two of those answers are not in the SDK documentation:

1. What `Boolean.toString()` returns. `Toybox.Lang.Boolean` documents only
   `compareTo` (`$CIQ_SDK/doc/Toybox/Lang/Boolean.html`); `toString` is
   inherited from `Object` and its text is not stated. The preview prints
   Python's `True`/`False`.
2. What `Math.round` returns for a negative exact half. The SDK says
   "Decimal values >= .5 will be rounded up" (`$CIQ_SDK/doc/Toybox/Math.html`),
   which leaves `-2.5` open: rounded up it is `-2`, rounded away from zero
   `-3`. `../math-parity/` left this UNVERIFIED; the compiler declines to fold
   such a `round()` (`ts/src/expr.ts`, `roundFoldable`), but the preview still
   has to draw something.

## Method

`face.yaml` is an ordinary face built by `wfb build` (SDK 9.2.0, 2026-10-07),
so the code under test is exactly what generated faces run:

| Line | Generated Monkey C | Preview draws today |
|---|---|---|
| A | `"A " + deviceIs24Hour.toString()` | `A True` (with 24-hour on) |
| B | `"B " + (!deviceIs24Hour).toString()` | `B False` |
| C | `"C " + Math.round(-2.5f).toNumber().toString()` | `C -2` |
| D | `"D " + Math.round(-1.5f).toNumber().toString()` | `D -1` |
| E | `"E " + Math.round(-0.5f).toNumber().toString()` | `E 0` |
| F | `"F " + 3.toString()` (folded: a control) | `F 3` |

Run it in the simulator on `fenix8solar47mm` or `fr955` and read the six
lines. Whether line A shows `true` or `false` depends on the simulator's
24-hour setting; A and B always show the two Boolean spellings between them.

## Findings

Screenshots: `text-of-values-fr955.png`, `-f8s47mm.png` and `-f8s51mm.png`
(the user's macOS simulator, 2026-10-07; fr955 at API level 5.2.0, fēnix 8
Solar 47 mm at 6.0.2). All three watches show the same six lines:
`A true`, `B false`, `C -2`, `D -1`, `E 0`, `F 3`.

1. **A Boolean prints as `true` and `false`, lower case.** VERIFIED. The
   preview printed Python's `True`/`False`; it now prints the watch's
   spelling (`ts/src/formatting.ts`, `ts/src/complications.ts`).
2. **`Math.round` rounds a negative exact half up, toward +infinity**:
   `-2.5` is `-2`, `-1.5` is `-1`, `-0.5` is `0`. VERIFIED. The host's
   `round()` already computed exactly this, so the compiler now also folds
   a negative half instead of leaving the call for the watch.
