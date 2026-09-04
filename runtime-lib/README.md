# runtime-lib — the support barrel

Hand-written Monkey C that generated faces call.  ADR 0003 permits this and
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
| `WfbIcons.mc` | the icon catalogue, drawn from primitives |

These files are hand-maintained and are *not* regenerated. Edit them here.
