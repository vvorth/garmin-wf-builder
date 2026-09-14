# runtime-lib — the support barrel

Hand-written Monkey C that generated faces call. ADR 0003 permits this and
draws the line precisely:

> **Generated code decides *what* is drawn; the barrel only helps with *how*.**
> If a barrel function ever needs to branch on the design, that branch belongs
> in the generator.

Nothing here dispatches on serialised layout data, so none of it is an
interpreter.  The build copies in only the files a face actually needs, so an
unused helper costs nothing.

| File | Contents |
|---|---|
| `WfbMath.mc` | `min`, `max`, `clamp`, `abs`, `percent` — the expression language's function set |
| `WfbTime.mc` | 12/24-hour conversion following `DeviceSettings.is24Hour`, and AM/PM |
| `WfbArc.mc` | arc geometry over `setPenWidth` + `drawArc` — a `progress` ring's track, a plain `shape: arc`, and a pattern's `arc` part (plan 05) all draw through the one `drawSpan` |
| `WfbWeather.mc` | `chooseIcon(condition)` — maps a `Weather.Condition` to a catalogue icon *name* (never a glyph; see `source/IconGlyphs.mc`, generated per project) |
| `WfbComplications.mc` | safe complication subscribe (`subscribe`) and pull (`valueOf`) — every `complication.*` read goes through `valueOf`, called fresh each frame like any other reader; `subscribe` is not a cache, see the file's own header |
| `WfbSeries.mc` | heart-rate acquisition and time-binning, drawing (line/area/bars) and generic array min/max for a `graph` element — the per-series array loop (`day.steps` vs. `day.calories`) is generated, because Monkey C offers no way to pass a field name |
| `WfbHands.mc` | analog hands (plan 04): `hourAngle`/`minuteAngle`/`secondAngle` — a `System.ClockTime` in, that hand's rotation angle out. Drawing itself is `WfbGeom.mc`, below |
| `WfbGeom.mc` | rotate/translate-and-draw helpers shared by analog hands (plan 04) and patterns (plan 05): `fillRotated`/`drawLineRotated`/`fillCircleRotated`/`drawCircleRotated` each turn a build-time-resolved shape by one `sin`/`cos` pair and draw it (a hand's own angle, or a radial pattern's copy angle); `fillTranslated` shifts a polygon part by a linear pattern's copy origin instead, no rotation at all. `sin`/`cos` are typed `Decimal`, not `Float` — `Math.sin`/`Math.cos` are declared to return `Float or Double`, and strict typing fails a narrower parameter. Moved out of `WfbHands.mc` when patterns needed the same four calls — "one convention, one helper", the precedent `WfbArc.mc` already set for arcs |

These files are hand-maintained and are *not* regenerated. Edit them here.

**Icons are not here.** An icon element draws a glyph from a baked font
(`wfb/icons.py`, sourced from `wfb/assets/icons/`) via `drawText` -- the same
mechanism any other bound text uses -- rather than a hand-drawn shape, so
there is no per-icon barrel function to keep in sync with the catalogue.
