# ADR 0008 — Validation and linting

- **Status:** Accepted
- **Date:** 2026-09-04
- **Decides:** what the compiler catches at build time, and how confident each
  check is allowed to sound.

## Context

The brief lists nine checks the compiler should perform. Phase 0 showed that
some are genuinely computable from the SDK on disk, some need the device files,
and at least one cannot be done honestly at all without measurement. Presenting
a guess with the same authority as a fact would be worse than not checking, so
each check declares its confidence.

## Decision

### Severity and confidence

Three severities — `error` (build fails), `warning` (build proceeds), `note` —
and every diagnostic carries **file, line and column** from the YAML source
(ADR 0002). Checks that rest on estimation say so in their message.

### The checks

| # | Check | Severity | Basis | Confidence |
|---|---|---|---|---|
| 1 | **Unbound / misspelled data source** | error | generated catalogue from SDK | exact |
| 2 | **Unsupported API for a targeted device** | error | **the device's own `<id>.api.debug.xml`** (`05-device-files.md` §2) | exact |
| 3 | **Palette-illegal colour** | warning | device `display_colors` (64 → `0x00/55/AA/FF`) | exact |
| 4 | **Element outside safe/visible area** | error (outside screen) / warning (outside safe area) | resolved geometry + `screen_shape` | exact for round/rectangle; **unavailable** for semi-round/semi-octagon (ADR 0004) |
| 5 | **Text overflows its slot** | warning | resolved geometry + per-device, per-language font pixel metrics | exact for fixed system fonts; approximate for vector fonts |
| 6 | **Missing glyph in a subsetted font** | error | used-glyph set vs. font `cmap` | exact |
| 7 | **Estimated memory overrun** | warning | `monkeyc --build-stats` against the device limit from the device DB | **measured, not estimated** — see below |
| 8 | **AMOLED always-on pixel/luminance violation** | warning | rasterise `always_on` layout, integrate | estimate; simulator heat map is authoritative |
| 9 | **Partial-update power-budget risk** | warning | clip area + operation count heuristic | **heuristic only** — see below |
| 10 | **Insufficient contrast** | warning | WCAG-style ratio between element and its backdrop | exact arithmetic, subjective threshold |
| 11 | **Config surface unavailable on target** | error | API 5.1.0 + four-axis limits (ADR 0006) | exact |
| 12 | **Low-power element reads a slow-tier source** | error | refresh tiers (ADR 0005) | exact |

### Check 2 must use per-device symbol tables, not API level

`05-device-files.md` §2 establishes this the hard way: **`fr955` runs API level
5.2.0 — above `onTap`'s documented "since" of 5.1.0 — and still does not have
`WatchFaceDelegate.onTap`.** Gating on `minApiVersion` would emit a face that
compiles cleanly and silently never responds to taps, which is exactly the
silent-failure class this framework exists to eliminate.

Availability is therefore resolved against each device's own
`<id>.api.debug.xml`, keyed by fully-qualified parent (note that `fr955` *does*
have `InputDelegate.onTap`, which is a different symbol). Neither API level nor
the documentation's product-name lists are authoritative.

### Two checks that must not overclaim

**#7 memory.** The honest approach is *measurement*, not estimation: run
`monkeyc --build-stats` and compare against the per-device Watch Face limit
already in the device database (128 KB on all three targets). Static estimation
of Monkey C bytecode size from an IR would be guesswork, and a wrong "fits"
is worse than no answer. This makes the check depend on the device files, which
is acceptable because a real build needs them anyway. Where `raw` elements are
present, their contribution is real (they are compiled) but their *runtime*
allocation is not modelled — flagged per ADR 0007.

**#9 power budget.** The numeric budget is not published; the docs say only
"strict limits" (`01-platform-capabilities.md` §2, open question 1). We can
compute the two things that provably drive cost — the **clip rectangle area**
(all pixels in the clip count as modified whenever any do) and the **number of
drawing operations** in `onPartialUpdate` — and warn on relative grounds
("this face clips 38% of the screen each second"). It must be labelled a
heuristic until measured empirically against `onPowerBudgetExceeded`. Given that
overrunning permanently disables partial updates, a conservative warning is
worth having even without an exact threshold.

### Ordering

Validation runs in stages, each gating the next, so errors are reported against
the earliest meaningful representation:

1. **Schema** — JSON Schema over the parsed YAML. Structural errors only.
2. **Semantic** — data sources, expression types, config surfaces, modes/tiers
   (checks 1, 2, 11, 12). Device-independent.
3. **Per-device resolve** — geometry, fonts, palette, safe area
   (checks 3, 4, 5, 6, 10). Runs once per target device.
4. **Post-build** — memory (7), and AMOLED/power estimates (8, 9).

Stages 1–3 need **no Garmin toolchain**, which matters: they run in CI where
device files are unavailable (`03-toolchain.md` §6). Only stage 4 needs a real
build.

### Suppression

Any check is suppressible per element with a reason, because a linter that
cannot be overridden gets disabled wholesale:

```yaml
lint:
  allow: [palette_dither]
  reason: "deliberate orange accent, matches the brand"
```

`error`-severity checks that reflect hard platform limits (2, 11, 12) are **not**
suppressible — suppressing them produces a face that does not work.

## Consequences

- The linter is the framework's main claim to being better than hand-writing, so
  its credibility matters more than its coverage. Hence the explicit confidence
  labelling.
- Checks 4 (semi-shapes), 2 (name join) and 9 (budget) have known gaps tracked
  in `00-summary.md`; each must degrade to "not checked" rather than to a
  confident wrong answer.
- `docs/limitations.md` should list what is *not* checked, alongside what the
  platform disallows.
