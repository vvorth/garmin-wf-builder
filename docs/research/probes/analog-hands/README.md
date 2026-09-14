# Probe: can a generated view rotate a hand made of primitives at runtime?

**Answer: yes.** `BUILD SUCCESSFUL`, warning-free, under `-w -l 3`
(`project.typecheck = strict`, `-O 3z`) on `fenix8solar47mm`,
`fenix8solar51mm` and `fr955`, SDK 9.2.0, 2026-09-14. Backs
[plan 04](../../../plans/04-analog-hands.md) §2.

## Why this was asked

ADR 0004 §2 says nothing relative reaches the device, and the watch does no
layout arithmetic. An analog hand cannot follow that rule completely,
because its angle *is* the time. Plan 04 keeps it for everything except
the rotation: a hand's shape and its axis resolve to per-device `Layout`
constants, and the watch only rotates them. This probe checks that the
generated Monkey C for that design type-checks, and how much it costs.

## What was built

The three files here are dropped into a project generated from
`tests/fixtures/slice/face.yaml` with `wfb build --no-compile`. The
generated view, `Palette.mc`, fonts and barrel files are replaced by
these files, with `ProbeLayout.mc` as each device's `Layout.mc`:

| file | stands in for |
|---|---|
| `WfbHands.mc` | a new `runtime-lib/` barrel: three angle functions and three rotate-and-draw helpers |
| `ProbeLayout.mc` | a per-device `Layout` module: one axis per `type: hands` element, and each part in the hand's own frame (origin = axis, pointing at 12 o'clock) |
| `ProbeView.mc` | the generated view: one draw method per hands element, one `sin`/`cos` pair per hand, and the second hand gated on `_sleeping` |

It covers a polygon part (with a tail behind the axis), a line part with a
pen width, a circle at the axis, a circle *off* the axis whose centre
moves, and a second hands element with an **off-centre axis** (a
small-seconds subdial at 6 o'clock).

## Findings

1. **Float vertices satisfy `fillPolygon` under strict typing.** A vertex
   built as `[cx + x * cos - y * sin, cy + x * sin + y * cos]` into
   `new Array<Graphics.Point2D>[n]` is accepted. `Point2D` is
   `[Numeric, Numeric]` (see `../polygon-const/`), and a `Float` is a
   `Numeric`. The SDK's own Analog sample passes floats the same way
   (`$CIQ_SDK/samples/Analog/source/AnalogView.mc`,
   `generateHandCoordinates`, which adds `+ 0.5`). So the watch does
   not round rotated coordinates; the firmware rasterises them.
2. **`Math.sin`/`Math.cos` results must be passed as `Decimal`, not
   `Float`.** Their declared return type is `Float or Double`
   (`bin/api.debug.xml`, `Math.sin`, `Math.cos`). With the helper's
   parameters typed `Float`, the build fails:

   ```
   ERROR: fr955: .../SliceView.mc:60,8: Passing 'PolyType<$.Toybox.Lang.Double or
   $.Toybox.Lang.Float>' as parameter 6 of non-poly type '$.Toybox.Lang.Float'.
   ```

   `Lang.Decimal` (`Float or Double`) is accepted without a cast.
3. **`drawLine` and `fillCircle` accept Float coordinates** under strict
   typing too, so a rotated line and a moving circle need no rounding
   either.
4. **A `_sleeping` flag works with no `always_on` mode.** It is set by
   `onEnterSleep`/`onExitSleep` and gates only the second hand's parts. It
   builds warning-free. The generated view today declares the flag only
   when `always_on` is in use (`wfb/emit/monkeyc.py`, `emit_view`).
5. **All the symbols used are on all three targets:** `Math.sin`,
   `Math.cos`, `Dc.fillPolygon`, `Dc.drawLine`, `Dc.fillCircle`,
   `WatchFace.onEnterSleep`/`onExitSleep`. Each was checked in
   `~/.Garmin/ConnectIQ/Devices/<id>/<id>.api.debug.xml` and by this
   build. `Math.sin`/`cos` are API 1.0.0.

The typecheck was driven red to prove it was really running, not skipped.
Finding 2's error is one such run. A `String` in the rotated vertex is the
other, and it fails as it should:
`Cannot assign type '…Array[…String, …Double or …Float]' to
'…Array<…Array[…Numeric, …Numeric]>'`.

## Cost

`--build-stats 0`, `fenix8solar47mm`, measured on the whole probe app: the
app class, this view, the barrel, and a `Layout` with two hands elements
(four hands, six parts):

| Data | Code | Total |
|---|---|---|
| 927 B | 1,198 B | 2,125 B (1.6% of 131,072 B) |

This is not a clean "cost of hands" figure. It includes the app skeleton
that every face has. What it does show is that the order of magnitude is
around a kilobyte, not tens.

## Alternatives checked and not used

- **`Graphics.AffineTransform`** has `rotate`, `translate` and
  `transformPoints`. It is present on all three targets (18 members each)
  and is `@since 4.2.0`. It could replace the Monkey C loop with one
  native call. It is not used for two reasons. First, its behaviour in a
  y-down frame (the sign of `rotate`) cannot be observed without a
  simulator. Second, the loop is what the SDK's own sample does and runs
  from API 1.0.0. It is a candidate optimisation to measure once someone
  can run a simulator.
- **Precomputed per-position tables** (60 rotated copies of each hand, with
  no trigonometry at runtime) move the cost from CPU to memory. The hour
  hand needs 720 positions for minute resolution. The watch-face budget is
  128 KB (constraint 2), so this is rejected.
- **Rotated bitmaps** (`drawBitmap2` with a `:transform`) are on all three
  targets. They would need the `image` element, which is not implemented,
  and a hand bitmap with transparency, which constraint 10 and
  `../static-buffer/` leave unresolved. This is out of scope.

## What this probe does NOT settle

- **What any of it looks like.** There is no simulator in this container
  (`docs/lore/codegen.md` finding 11). Edge quality of a rotated
  `fillPolygon` with or without `setAntiAlias`, and the look of a rotated
  thick `drawLine`'s ends, are unobserved.
- **Whether a face starts awake.** The flag starts as `false` (awake). The
  SDK sample starts its equivalent `_isAwake` as `null` (asleep). Which
  one matches the first frame after the face loads is behaviour. It is
  left for the user's host simulator, which has a low-power toggle (plan
  04 §9).
- **CPU and battery cost per frame** of about six `sin`/`cos` calls and
  a few dozen multiplies.

## Rebuilding it

```sh
wfb build tests/fixtures/slice/face.yaml --no-compile -o /tmp/probe
cd /tmp/probe/slice
rm source/SliceView.mc source/Palette.mc runtime-lib/*.mc
rm -rf resources-*/fonts
cp <this dir>/ProbeView.mc source/SliceView.mc
cp <this dir>/WfbHands.mc runtime-lib/
for d in fenix8solar47mm fenix8solar51mm fr955; do
    cp <this dir>/ProbeLayout.mc source-$d/Layout.mc
    $CIQ_SDK/bin/monkeyc -f monkey.jungle -d $d -o $d.prg \
        -y ~/ciq/developer_key.der -w -l 3
done
```
