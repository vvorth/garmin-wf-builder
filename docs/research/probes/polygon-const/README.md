# Probe: how does a resolved polygon's point array reach `fillPolygon`?

**Answer: as a module-level `const … as Array<Graphics.Point2D>` in the
generated per-device `Layout` module.** `BUILD SUCCESSFUL` under `-l 3` on
`fenix8solar47mm`, `fenix8solar51mm` and `fr955`, SDK 9.2.0, warning-free.

## Why this was asked

ADR 0004 is categorical: nothing relative survives into generated Monkey C and
the device does no layout arithmetic. Every other coordinate in the project is
therefore a `Number`/`Float` constant in `Layout`. A polygon's vertices are the
first coordinates that are not a scalar, and `const` in Monkey C is not `const`
in C -- whether the compiler folds an array literal into a module constant, and
whether the result satisfies `fillPolygon`'s parameter type under strict
typechecking, is not something the doc pages answer. So it was built.

Three candidate shapes were compiled side by side (`ProbeLayout.mc`,
`ProbeView.mc`):

| | shape | result |
|---|---|---|
| **A** | `const P as Array<Graphics.Point2D> = [[10, 20], …];` | **accepted -- this is what shipped** |
| B | `const P = [[10, 20], …];` (no declared type) | accepted, but declares nothing and checks nothing |
| C | per-coordinate `const`s, literal assembled at the call site | accepted, and unnecessary |

## The one thing that is genuinely easy to get wrong

`Dc.fillPolygon(pts as Lang.Array<Graphics.Point2D>)`
(`$CIQ_SDK/doc/Toybox/Graphics/Dc.html`), and `Point2D` is the **fixed-size
tuple** type `[Lang.Numeric, Lang.Numeric]`
(`$CIQ_SDK/doc/Toybox/Graphics.html`), not `Array<Number>`. Declaring the
constant as `Array<Array<Number> >` compiles the *constant* fine and then fails
at the call site:

```
Invalid '$.Toybox.Lang.Array<$.Toybox.Lang.Array<$.Toybox.Lang.Number>>'
passed as parameter 1 of type
'$.Toybox.Lang.Array<$.Toybox.Lang.Array[$.Toybox.Lang.Numeric, $.Toybox.Lang.Numeric]>'.
```

That is why `wfb/emit/monkeyc.py`'s `McLiteral` carries a declared type at all,
and why `emit_layout` adds `import Toybox.Graphics;` to a `Layout` module that
contains a polygon -- the only reason that module ever imports anything beyond
`Toybox.Lang`.

The typecheck was confirmed to be genuinely running rather than silently
skipped, by putting a `String` in the array and watching it fail:
`Cannot assign value '…Array[…String, …Number], …' to member ':PROBE_POINTS'.`

## Also settled here

`drawArc`, `drawEllipse`, `fillEllipse`, `drawRectangle` and
`drawRoundedRectangle` are all present on all three targets -- confirmed both in
each device's own `~/.Garmin/ConnectIQ/Devices/<id>/<id>.api.debug.xml`
`<functionEntry>` table and by this build. **`drawPolygon` does not exist**, on
any target or in the SDK docs, which is why `filled: false` on a
`shape: polygon` is a compile error naming that rather than a silent fill.

`fillPolygon`'s own doc page documents a **64-point limit**; the schema enforces
it as `maxItems`.

## What this probe does NOT settle

What any of it *looks like*. The simulator does not run in this container
(`docs/limitations.md` §2), so every result here is compile-time. `wfb preview`
renders all of these shapes, but its arc caps, ellipse rasterisation and
polygon edge antialiasing are Pillow's, not the firmware's.

## Rebuilding it

Source-only, like the sibling probes. Drop both files into a minimal watch-face
project with an `AppBase` returning `new ProbeView()`, then:

```sh
$CIQ_SDK/bin/monkeyc -f monkey.jungle -d fenix8solar47mm \
    -o probe.prg -y ~/ciq/developer_key.der -w -l 3
```
