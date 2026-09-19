# Probe: system-font-metrics

A minimal, hand-written Monkey C watch face that reads back the SDK's own
system-font measurements at runtime, for plan 09
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

Build for a device and push it to a running simulator on the host (the
simulator does not survive `monkeydo` in the sandbox, `docs/lore/toolchain.md`):

```sh
export CIQ_SDK=~/ciq/sdks/9.2.0
cd docs/research/probes/system-font-metrics
$CIQ_SDK/bin/monkeyc -f monkey.jungle -d fenix8solar47mm \
    -o /tmp/probe.prg -y ~/ciq/developer_key.der -w -l 3
$CIQ_SDK/bin/connectiq                      # launch the simulator (GUI)
$CIQ_SDK/bin/monkeydo /tmp/probe.prg fenix8solar47mm
```

The manifest lists `fenix8solar47mm`, `fenix8solar51mm`, `fr955` (TTF
fonts) and `fenix6`, `fr245` (`.cft` bitmap fonts); all build warning-free.
The console lines appear in the simulator's log pane; the on-screen table
is what a screenshot shows.

## What the numbers are used for

They are the ground truth that `wfb/fonts/fallback.py` is calibrated
against (`docs/research/10-system-fonts.md` §9; §10.9 for the bitmap-font
devices, still open). The `w1`/`w2` sample strings are the same ones
`examples/system-fonts*/` draw, so the widths compare directly.

## Results (2026-09-18)

The user ran the probe in the macOS simulator for all three targets. The
console output is transcribed in `results-2026-09-18.txt` and checked by
`tests/test_system_font_metrics.py::test_metrics_match_what_the_simulator_reported`.
The findings are in `docs/research/10-system-fonts.md` §9:

- Height, ascent and descent are exact everywhere.
- The device lays text out per glyph, at the whole-pixel em.
- Bionic is within 4 px over ten digits.

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
