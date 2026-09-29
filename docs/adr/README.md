# Architecture decision records

Each ADR states the context, the decision, the rationale, the consequences, and
the alternatives rejected. Where a decision rests on a Phase 0 finding, it cites
the research file so the evidence is traceable.

| # | Decision | Status |
|---|---|---|
| [0001](0001-host-language-python.md) | Host language: **Python** | Accepted |
| [0002](0002-authoring-interface.md) | Authoring: **YAML canonical, GUI as lossless editor** | Accepted |
| [0003](0003-compilation-strategy.md) | Compilation: **code generation**, with a small support barrel | Accepted |
| [0004](0004-element-model-and-coordinates.md) | Element model; **anchors + relative/polar units**, per-device overrides | Accepted |
| [0005](0005-data-binding-and-expressions.md) | Typed data catalogue; **expressions compile to Monkey C**, no runtime evaluator | Accepted |
| [0006](0006-configuration-theming-and-modes.md) | Config surfaces, palettes, power modes, tap/hold interactivity | Accepted |
| [0007](0007-escape-hatch.md) | A **narrow, bounded escape hatch** to hand-written Monkey C | Accepted |
| [0008](0008-validation-and-linting.md) | Build-time checks, with **explicit confidence levels** | Accepted |
| [0009](0009-schema-versioning.md) | Format versioning and forward compatibility | Accepted |

## The through-line

Three Phase 0 findings drive most of what follows:

1. **There is no device-side renderer**, so the format must compile ahead of time
   (0003) — which in turn is why expressions need no runtime evaluator (0005) and
   why layout is fully resolved at build time (0004).
2. **The platform is smaller than the ambition** — 128 KB, no filled arc, a
   four-axis on-device editor, `onTap` on a minority of devices. So the format's
   job is partly to *refuse* to promise things (0006, 0008), and to leave a
   dignified exit when it must (0007).
3. **The compiler knows the whole design**, which is where the value is:
   permissions derived from bindings, clip rectangles computed from geometry,
   glyph sets from strings, and lints that a hand author cannot run (0005, 0008).

## Decisions taken by the user

- **fr955 interaction:** tap where available, hold on fr955; both generated from
  one declaration (0006).
- **On-device configuration:** the native editor for the four `config:`
  axes, and, on a watch without it (fr955), the same axes in a generated
  settings menu (`getSettingsView`); no separate wearer-settings language,
  no phone settings, no `.SET` writer (0006 tenth and eleventh amendments,
  2026-09-27). This reverses the 2026-09-04 "no generated menu" decision,
  whose premise (phone settings reach a sideload) was false.
- **Host language:** Python (0001).
- **Format 2 (2026-09-28, plan 22):** one designed revision of the YAML
  format -- one `color.` namespace, author-shaped names, one spelling per
  idea, a grouped top level -- migrated once by `wfb migrate` rather than
  deprecated over a major (0009, and the 2026-09-29 amendments to 0004,
  0005 and 0006).
- **Per-device API gating (2026-09-15):** a feature needing a higher API level
  (complications) is guarded at runtime per device (`Toybox has :Complications`),
  never by raising the shared `minApiLevel` -- a target device lacking a
  binding reads it as absent, the same contract every nullable source already
  has (0005, 0006 sixth amendment).
