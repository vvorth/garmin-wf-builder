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
| `WfbArc.mc` | progress-arc geometry over `setPenWidth` + `drawArc` |
| `WfbWeather.mc` | `chooseIcon(condition)` — maps a `Weather.Condition` to a catalogue icon *name* (never a glyph; see `source/IconGlyphs.mc`, generated per project) |
| `WfbComplications.mc` | safe complication subscribe (`subscribe`) and pull (`valueOf`) — every `complication.*` read goes through `valueOf`, called fresh each frame like any other reader; `subscribe` is not a cache, see the file's own header |
| `WfbSeries.mc` | heart-rate acquisition and time-binning, drawing (line/area/bars) and generic array min/max for a `graph` element — the per-series array loop (`day.steps` vs. `day.calories`) is generated, because Monkey C offers no way to pass a field name |

These files are hand-maintained and are *not* regenerated. Edit them here.

**Icons are not here.** An icon element draws a glyph from a baked font
(`wfb/icons.py`, sourced from `wfb/assets/icons/`) via `drawText` -- the same
mechanism any other bound text uses -- rather than a hand-drawn shape, so
there is no per-icon barrel function to keep in sync with the catalogue.
