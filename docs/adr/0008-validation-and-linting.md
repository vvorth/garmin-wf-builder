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
| 4 | **Element outside safe/visible area** | warning, suppressible (`off-screen` outside the framebuffer / `safe-area` outside the safe area — see amendment below) | resolved geometry + `screen_shape` | exact for round/rectangle; **unavailable** for semi-round/semi-octagon (ADR 0004) |
| 5 | **Text overflows its slot** | warning | resolved geometry + per-device, per-language font pixel metrics | exact for fixed system fonts; approximate for vector fonts |
| 6 | **Missing glyph in a subsetted font** | error | used-glyph set vs. font `cmap` | exact |
| 7 | **Estimated memory overrun** | warning | `monkeyc --build-stats` against the device limit from the device DB | **measured, not estimated** — see below |
| 8 | **AMOLED always-on pixel/luminance violation** | **error** (uniquely suppressible, see amendment below) | rasterise the resolved `aod:` set with `wfb.preview.render` (the same function `wfb preview --aod` uses), score lit-pixel and luminance fractions over the round-masked display at a sampled worst-case frame | estimate; simulator heat map is authoritative — built 2026-09-23 (plan 14 slice 4, code `aod-burn-in`); a weaker precursor, `aod-empty` (does *anything* draw in AOD at all), shipped in slice 1 |
| 9 | **Partial-update power-budget risk** | warning | clip area + operation count heuristic | **heuristic only** — see below |
| 10 | **Insufficient contrast** | warning | WCAG-style ratio between element and its backdrop | exact arithmetic, subjective threshold |
| 11 | **Config surface unavailable on target** | error | API 5.1.0 + four-axis limits (ADR 0006) | exact |
| 12 | ~~**Low-power element reads a slow-tier source**~~ **Deleted** | ~~error~~ n/a | ~~refresh tiers (ADR 0005)~~ | n/a — ADR 0005's refresh-tier concept this check depended on no longer exists (see that ADR's amendment); any source may now be bound from a `low_power` element, guarded only by check 9's suppressible heuristic instead |

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
2. **Semantic** — data sources, expression types, config surfaces, modes
   (checks 1, 2, 11; check 12 no longer exists, see its table row above).
   Device-independent.
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
  allow: [palette-dither]
  reason: "deliberate orange accent, matches the brand"
```

`error`-severity checks that reflect hard platform limits (2, 11; 12 no longer
exists) are **not** suppressible — suppressing them produces a face that does
not work. Check 8 (`aod-burn-in`, added 2026-09-23, see its own amendment
below) is the one deliberate exception: it is `error`-severity but *is*
suppressible, because exceeding it does not describe generated code that
fails to work — see that amendment for why.

The code named in `allow:` is checked against the set the compiler actually
emits (`lint.ALL_CODES`, kept honest by a test that re-derives it from the
source), so a misspelling and a deliberately-unsuppressible code are reported
differently instead of both being ignored in silence — `lint.check_lint_allow`,
which runs once per build rather than once per target because an element's
`allow:` list is fixed before any device is resolved. This decision cost a real
bug: the code above was written `palette_dither` in this ADR for a long time,
which the compiler would have accepted and silently ignored.

## Consequences

- The linter is the framework's main claim to being better than hand-writing, so
  its credibility matters more than its coverage. Hence the explicit confidence
  labelling.
- Checks 4 (semi-shapes), 2 (name join) and 9 (budget) have known gaps tracked
  in `00-summary.md`; each must degrade to "not checked" rather than to a
  confident wrong answer.
- `docs/limitations.md` should list what is *not* checked, alongside what the
  platform disallows.

## Amendment (2026-09-21): check 4's off-screen half is a suppressible warning

**What changed.** `off-screen` (drawing partly or fully off the framebuffer)
is no longer the `error`-severity, unsuppressible half of check 4. It is now
`Severity.WARNING` and in `lint.SUPPRESSIBLE`, the same as `safe-area`
(outside the visible disc but still on the framebuffer). An element that
suppresses `off-screen` is not also checked for `safe-area`: a box outside
the rectangular framebuffer is necessarily outside the visible disc it
contains, so the second check would only repeat the first finding under a
different name (`wfb.lint.check_geometry`).

**Why.** SDK 9.2.0's `Toybox.Graphics.Dc` documents no exception for
out-of-range draw coordinates on any draw call — only `drawBitmap2` throws,
and that is for a *source* rect inside the bitmap, not a destination point.
`Dc` clips silently, the same way `setClip` does ("Pixels outside of the
region will not be affected by any operations"). Check 2 and check 11 remain
`error` and unsuppressible because they describe an API the generated code
would call and get a crash or an invalid manifest back; check 4's off-screen
half describes no such failure — a cropped element is exactly as legal as
one that runs off under the bezel, which check 4's other half already
treated as a warning. Treating the two halves differently was never
supported by anything platform-specific, only by an earlier, mistaken
assumption that an out-of-range `Dc` call throws.

**Consequence for `ResolvedFace.clip_for`.** An off-screen `low_power`
element can now reach codegen instead of being rejected at the lint stage,
so the `low_power` clip rectangle it feeds (`wfb.layout.ResolvedFace.
clip_for`, emitted into `dc.setClip(...)` by `wfb.emit.monkeyc.view.
_emit_on_partial_update`) must itself be clamped to the framebuffer, never
left negative. `wfb.units.IntBox.clamp_to` was intersecting each edge
independently, which — for a box with **no** overlap with the frame at all —
could clamp one edge up to `0` while the opposite edge clamped down to a
value still on the wrong side of it, producing a negative width or height.
Fixed to compute the intersection properly, floored at zero per axis, so a
fully off-screen `low_power` element now clamps to a genuinely empty
(zero-area) clip rather than a nonsense one.

## Amendment (2026-09-21): check 4's `safe-area` half is shape-aware, not box-corner-aware

**What changed.** On a round screen, `safe-area` (outside the visible disc,
row 4's second half) no longer tests every element's four AABB corners
against the disc. `wfb.layout.circular_extent`/`visible_reach` compute the
element's own *real* farthest reach from the screen centre instead, for
every kind that genuinely is not its own bounding box: `shape: arc`/
`circle`, a `progress` arc, `hands`, a radial `pattern` (already true before
this amendment for a `line`/`circle`/`arc`/`polygon` template part, whose
own reach `Resolver._resolve_hand_part` already derived from real
geometry, rotation-invariant), a standalone `curve: {style: radial}` or
`{style: angled}` `text` element, and — the fix this amendment records — a
radial pattern's own `shape: text` part under either `curve:` style, whose
reach used to come from that part's per-copy AABB corners instead.
`off-screen` (row 4's first half, the rectangular framebuffer test) is
unchanged: the framebuffer really is rectangular, so its own AABB corners
are the right test there, and remain so.

**Why.** An axis-aligned bounding box drawn *around* a rotated rectangle or
an annulus sector has corners that are not points on the shape at all —
the same "union of extremes is not a point on the shape" trap
`wfb.layout.arc_bbox`'s own docstring already named for the framebuffer-
relative case. Measured from an *arbitrary* external point (the screen
centre, not necessarily the shape's own centre), that AABB's corners can
sit substantially farther out than the shape's real farthest point ever
does. Concretely: a full 12-copy radial ring of `shape: text` numerals
(`examples/showcase`'s own `numerals` element, `curve: {style: radial}`)
tripped `safe-area` at a radius comfortably inside the visible disc, purely
because each copy's own annulus-sector AABB has corners well outside
`radius:`'s own outer edge — acknowledged with `lint: {allow: [safe-area],
reason: ...}` until this fix, now unnecessary and removed.

**How.** `wfb.layout.annulus_sector_reach(cx, cy, r_inner, r_outer,
theta_a, theta_b, px, py)` is the farthest distance from an arbitrary point
to an annulus sector — exact when the direction from the sector's own
centre straight away from that point falls inside the sector's sweep (the
common case, and the only case for a ring whose curve centre coincides
with the pattern's own rotation axis, `radius: 75%r` and no `at:` override
being the exact shape `examples/showcase`'s own numerals use), and a tight
comparison of both radii at both sweep endpoints otherwise.
`wfb.layout.rotated_rect_corners` is the analogous fix for `curve:
{style: angled}`: the four *real* corners of the rotated text box, not
its AABB's. Both a standalone element (`wfb.layout.visible_reach`, read by
`wfb.layout.inside_visible_area_for`) and a pattern's own `shape: text`
part (`Resolver._resolve_pattern`'s per-copy `text_reach`, sharing
`wfb.layout._pattern_text_ink_geometry` with `_pattern_part_ink`'s own
AABB so the two questions are always asked of the same shape) go through
this geometry. `check_geometry`'s `safe-area` message now also names the
reach and the limit it compared against, not just "outside the visible
area", so the finding can be checked, not just trusted (`ADR 0008`'s own
confidence discipline). Full design: `wfb/layout.py`'s own docstrings
(`annulus_sector_reach`, `rotated_rect_corners`, `visible_reach`,
`circular_extent`), and `docs/guide/text.md`'s "`curve:` — rotated and radial
text" section. Tests: `tests/test_pattern_text_curve.py`,
`tests/test_vector_text_layout.py`, `tests/test_patterns.py`.

## Amendment (2026-09-23): check 8 built, `aod-burn-in` -- and the first
## deliberately suppressible `error`

**What changed.** Check 8 (the table above) is built: `wfb.lint.
check_aod_burn_in`, code `aod-burn-in` (plan 14 slice 4, research 11 §6 D).
It renders the resolved `aod:` set through `wfb.preview.render` -- the same
function `wfb preview --aod` uses, no second renderer -- at device
resolution, at a sampled worst-case frame (two clock times, `10:08` and
`20:08`, full battery, `wfb.preview.SAMPLE`'s other defaults unchanged),
and scores two fractions over the round-masked display area: the share of
non-black pixels (Garmin's own FAQ, research 11 §1.1: "a pixel is
considered on when rendering any color other than black") and the mean
relative luminance (`wfb.palette.Color.relative_luminance`, the same
Rec. 709/WCAG formula check 10 already uses, as a fraction of full white).
Both of Garmin's two generation-specific 10% rules (research 11 §1.2 --
original Venu on lit pixels, Venu 2+ on luminance) are checked at once,
since the device files carry no field saying which generation a target is;
exceeding either is the finding. It is reported **per element**: every
AOD-shown element is re-rendered alone (`dataclasses.replace(resolved,
items=[placed])`, cheap because geometry is already absolute at this
stage) and ranked by its own lit-pixel count, and the diagnostic is
anchored at the biggest contributor's own source line.

**Severity, and the one deliberate exception to this ADR's own "error +
hard platform limit -> unsuppressible" rule.** Over 10% (either fraction)
is `Severity.ERROR` -- consistent with this project's other AMOLED hard
error, `partial-update` (check 9's own device-support branch). But unlike
that error, which describes generated code that would not run on the
device at all, exceeding the 10% rule breaks nothing the compiler emits:
at worst, the watch's own OS disables always-on for the app, a
product-quality guideline the *device* enforces, not a structural limit
this framework's output violates. So `aod-burn-in` is, on purpose, in
`wfb.lint.SUPPRESSIBLE` -- the first `error`-severity code in this
project that is. This ADR's own "checks 2 and 11 are the unsuppressible
hard-limit errors" language (Decision, "Suppression") still holds for
those two; `aod-burn-in` is a third, narrower case this ADR did not
originally anticipate needing, because its harm is enforced by the watch's
policy engine, not by anything that fails to run. Under 10% is
`Severity.NOTE`, stating both figures -- the same "the author sees the
number on every build" shape check 7's row above (`graphics-pool`) already
established.

**What is still an estimate, not a measurement, and says so.** The
lit-pixel fraction is exact *for the rendered sample frame*, but that
frame is one of two sampled clock times with a fixed data snapshot, not
every time/data combination a real face can show, and the AOD frame's
own 3-minute static-pixel rule (research 11 §1.2/§5) is a property of a
*sequence* of frames this single-frame check cannot see at all. The
luminance fraction additionally depends on this compiler's own choice of
formula, since Garmin's is unpublished. `confidence=` on the diagnostic
says all of this, and `docs/limitations.md` §3 has the full account.
