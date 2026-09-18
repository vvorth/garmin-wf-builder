# Probe: system-font-metrics

A minimal, hand-written Monkey C watch face that reads back the SDK's own
system-font measurements at runtime, for `docs/plans/09-system-font-metrics.md`
S4 R3 (step C). Unlike most probes in this directory, this one's
`manifest.xml` and `monkey.jungle` are committed alongside the source,
because the task that built it asked for a self-contained project rather
than "drop these files into a scratch build" (the shape most other probes
here use -- see e.g. `../config-axes/README.md`'s "Rebuilding it").

## What it prints

On the first `onUpdate`, for every `Graphics.FONT_*` constant the SDK
defines (`$CIQ_SDK/bin/api.debug.xml`, `symbol="FONT_*"` -- 29 of them:
the five text sizes, the four number sizes, five `FONT_SYSTEM_*`, four
`FONT_SYSTEM_NUMBER_*`, `FONT_GLANCE`/`FONT_GLANCE_NUMBER`, and
`FONT_AUX1`..`FONT_AUX9`), `System.println`s one line:

```
FONT_X h=<Graphics.getFontHeight> a=<Graphics.getFontAscent> d=<Graphics.getFontDescent> w1=<dc.getTextWidthInPixels("Hxg0123", f)> w2=<dc.getTextWidthInPixels("0123456789", f)>
```

Every call is `has`-guarded (`if (Graphics has :FONT_XTINY) { ... }`, one
guard per constant, `ProbeView.mc`'s `collect`) because per-device
availability, not SDK-wide presence, is what decides whether a symbol is
real on a given watch (`CLAUDE.md` constraint 6;
`../device-symbol-gate/README.md` shows the compiler will not catch this
for you). All 29 constants are present in all three probe targets' own
`<id>.api.debug.xml` (`~/.Garmin/ConnectIQ/Devices/<id>/<id>.api.debug.xml`,
checked with `grep -oE 'symbol="FONT_[A-Z0-9_]+"'` before writing this file),
so every guard is true here -- but it is what keeps the same source correct
on a fourth target that lacks one, with no per-device source split.

It also draws the same data as a compact table on screen, in `FONT_XTINY`,
three columns (`ProbeView.mc`'s `drawTable`, sized from the live
`dc.getWidth()`/`dc.getHeight()` rather than a hardcoded screen size), as
`"<abbreviation>:<height>"` pairs -- e.g. `XT:21`, `NTH:121`. The console
line carries the full data (height, ascent, descent, two sample widths);
the on-screen table is a coarse visual cross-check, height only, because a
260px round screen has no room for five numbers per row across 29 rows.

## How to run it

Build for a target and push it to a *running* simulator instance
(`docs/lore/toolchain.md` S3 -- the simulator does not survive
`monkeydo` pushing an app inside this sandbox, so this step is for the
user's host, not this container):

```sh
export CIQ_SDK=~/ciq/sdks/9.2.0
cd docs/research/probes/system-font-metrics
$CIQ_SDK/bin/monkeyc -f monkey.jungle -d fenix8solar47mm \
    -o /tmp/probe.prg -y ~/ciq/developer_key.der -w -l 3
$CIQ_SDK/bin/connectiq                      # launch the simulator (GUI)
$CIQ_SDK/bin/monkeydo /tmp/probe.prg fenix8solar47mm
```

Swap `fenix8solar47mm` for `fenix8solar51mm` or `fr955` for the other two
targets. `BUILD SUCCESSFUL`, warning-free, under `-l 3`, confirmed for all
three from inside this sandbox (build only -- there is no simulator here to
push to, `docs/lore/toolchain.md` S3).

The console lines appear in the simulator's own log/console pane. The
on-screen table needs no console at all -- it is what a screenshot of the
running probe shows directly.

## What the numbers are used for

`docs/plans/09-system-font-metrics.md` S4 R2 built `wfb.devices.
Device.system_fonts` and `wfb/fonts/fallback.py` from the *published*
device-file/scraped-table metrics, not from a live device reading -- there
is no simulator or watch inside this project's sandbox to read one from
(`CLAUDE.md` S3). This probe is how the user closes that gap: run it on
their host simulator (or a real watch), and the `h=`/`a=`/`d=`/`w1=`/`w2=`
figures it prints are the ground truth `docs/research/10-system-fonts.md`
S3 and `wfb/fonts/fallback.py` get calibrated against (plan 09 S7, open
until those numbers come back). The `w1`/`w2` sample strings
(`"Hxg0123"`, `"0123456789"`) are deliberately the same two samples
`examples/system-fonts/` and the `examples/system-fonts-numbers*/` faces
draw, so a width printed here can be checked directly against those faces'
own measured widths.

## SDK doc paths for the APIs used

- `Graphics.getFontHeight`, `Graphics.getFontAscent`, `Graphics.getFontDescent`
  -- `$CIQ_SDK/doc/Toybox/Graphics.html` (static module functions, `@since 1.2.0`).
- `Dc.getTextWidthInPixels` -- `$CIQ_SDK/doc/Toybox/Graphics/Dc.html`.
- `Graphics has :FONT_*` -- the per-device `has` idiom,
  `$CIQ_SDK/doc/docs/Core_Topics/Graphics.html` and
  `../antialias/README.md` S1 (same idiom, different symbol).
- `System.println` -- `$CIQ_SDK/doc/Toybox/System.html`.
- `Lang.format` -- `$CIQ_SDK/doc/Toybox/Lang.html`.

All four font-metric symbols were confirmed present in
`$CIQ_SDK/bin/api.debug.xml` (SDK-wide) and in each of
`fenix8solar47mm`/`fenix8solar51mm`/`fr955`'s own `<id>.api.debug.xml`
before this probe was written.
