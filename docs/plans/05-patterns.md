# Plan 05: Patterns — one template, repeated radially or in a line

- **Date:** 2026-09-14
- **Status:** approved for building, 2026-09-14. The user asked for the
  research, a plan and straightforward requirements, and for the build to
  go to subagents and be integrated and committed. §9 lists the choices
  made without a round-trip, for the user to review afterwards.
- **Ask (the user's words, condensed):** draw patterns from primitives.
  Hour notches described as objects to draw, `type: radial`, a centre,
  30 degrees between objects and how many times to repeat; minute objects
  with 6 degrees between them. Maybe `type: linear` too, so the same group
  of objects (lines, etc.) can be repeated into a pattern. All of it
  anti-aliasable.
- **Builds on:** ADR 0004 (build-time resolution, and its 2026-09-14
  amendment for hands), plan 04 (analog hands: the part vocabulary and
  the rotate-and-draw barrel, `git show 93ef6d7:docs/plans/04-analog-hands.md`),
  `docs/format.md` "`antialias:`" and "`static:`", and the probe
  `docs/research/probes/pattern-cost/`, written for this plan.

---

## 1. What the platform gives (research)

| Question | Answer | Evidence |
|---|---|---|
| Is there a "repeat"/instancing draw call? | **No.** `Dc` draws one primitive per call. | `$CIQ_SDK/doc/Toybox/Graphics/Dc.html`; `bin/api.debug.xml` |
| Is there a rotated draw call? | **No** (plan 04 §1). Rotation is vertex arithmetic, then `fillPolygon`/`drawLine`/`fillCircle`. | same; `runtime-lib/WfbHands.mc` |
| Can the watch do the trigonometry? | Yes: `Math.sin`/`Math.cos`, typed `Float or Double` (pass as `Decimal`). | `docs/lore/monkeyc.md`; `docs/research/probes/analog-hands/` |
| Does `drawArc` rotate? | Its start angle is a plain parameter, so an arc centred on the pattern's centre "rotates" by shifting its start angle. `WfbArc.drawSpan` already takes a Float start. | `runtime-lib/WfbArc.mc` |
| Anti-aliasing | `Dc.setAntiAlias`, per element, already bracketing every primitive-drawing element's draw method (`ANTIALIASED_PRIMITIVES`). | `docs/format.md` "`antialias:`" |
| Draw once? | `static:` paints into a `BufferedBitmap` once; any element without a data binding may go there. | `docs/format.md` "`static:`" |

**Prior art.** Watch Face Format has no repeat element; WFF designs draw
indices as a pre-rendered image. Connect IQ's own samples draw hour ticks
in a hand-written `for` loop with `Math.sin`/`Math.cos`
(`$CIQ_SDK/samples/Analog/source/AnalogView.mc`, `drawHashMarks`).

## 2. The probe: bake or loop?

`docs/research/probes/pattern-cost/` measured three strategies on
`--build-stats`:

| strategy | 60 line ticks | grows with count? |
|---|---|---|
| expand into 60 `shape` elements (desugar) | **+4,960 B** | ~83 B a copy |
| one baked flat array + loop | +1,369 B | ~5 B a coordinate |
| baked `Point2D` arrays (12 rectangles) | +1,974 B | badly |
| **template + runtime rotation loop** | **+170 B** (+~20 B for a skip test) | **no** |

A 60-tick ring baked as elements is 3.8% of the whole 128 KB budget. The
loop is flat. **Decision: the watch loops over the copies and rotates or
translates the build-time-resolved template** — the same bargain ADR 0004
already struck for hands (§9, D2). Its cost is time, one `sin`/`cos` pair
and one draw call per copy per frame, and zero for content in `static:`,
which is where a tick ring belongs.

## 3. Requirements

| # | Requirement |
|---|---|
| R1 | A pattern is **one element**: a template of 1–16 primitives plus a repeat rule. |
| R2 | **Radial** repeat: a centre, a copy count, an angle between copies (default `360deg / count`), and the angle of the first copy. |
| R3 | **Linear** repeat: an origin, a copy count, and an `{dx, dy}` offset between copies. |
| R4 | The template is authored exactly like a hand part: **at 12 o'clock, origin = the pattern's `at:`**, `px`/`%r` only, no `anchor:`. |
| R5 | Parts: `polygon`, `rectangle`, `line`, `circle` (the hand vocabulary) **plus `arc`**, centred on the origin, whose start angle turns with the copy. |
| R6 | **Anti-aliasing** works exactly as on a `shape`: the element's `antialias:` (inherited from group / face default) brackets the whole pattern. |
| R7 | Copies can be **skipped**, by index list and by "every Nth", so a minute ring can leave room for hour ticks. |
| R8 | A pattern can live in `static:`, in a group, in a `layouts:` entry, and under `visible:`, like a `shape`. |
| R9 | Everything the format already guarantees holds: warning-free builds on all three targets, a preview drawn from the same resolved geometry, lints that know the real extent, one error (not N) per mistake, no silent no-ops. |

## 4. The YAML

```yaml
static:
  minute_ticks:
    type: pattern
    pattern: radial            # radial | linear
    at: {anchor: center}       # the centre every copy turns about
    count: 60                  # 1..360 copies
    # step: 6deg               # radial default: 360deg / count
    # start: 0deg              # radial only: where copy 0 points (default 12 o'clock)
    skip_every: 5              # leave every 5th copy (0, 5, 10, ...) to the hour ticks
    color: palette.gray        # default for every part without its own
    antialias: true
    parts:                     # copy 0, drawn at 12 o'clock, origin = at:
      - {shape: line, at: {dy: -94%r}, to: {dy: -88%r}, thickness: 1px}

  hour_ticks:
    type: pattern
    pattern: radial
    at: {anchor: center}
    count: 12
    step: 30deg
    skip: [0]                  # 12 o'clock has its own marker
    color: palette.white
    parts:
      - {shape: rectangle, at: {dy: -87%r}, size: {width: 3%r, height: 12%r}}

  segments:
    type: pattern
    pattern: radial
    at: {anchor: center}
    count: 12
    color: palette.dark_gray
    parts:
      - {shape: arc, radius: 70%r, thickness: 4px, start_angle: 3deg, sweep: 24deg}

elements:
  week_dots:
    type: pattern
    pattern: linear
    at: {anchor: center, dx: -30%r, dy: 45%r}   # copy 0's origin
    count: 7
    step: {dx: 10%r}                             # copy i's origin is at + i * step
    color: palette.cyan
    parts:
      - {shape: circle, radius: 2%r}
```

`type: pattern` + `pattern: <kind>` follows `type: shape` + `shape:
<kind>` and `type: hands` + `hands: <set>`.

## 5. Semantics

### 5.1 Keys

A `type: pattern` element takes `id`, `type`, `pattern`, `at`, `count`,
`step`, `start`, `skip`, `skip_every`, `color`, `parts`, `modes`, `z`,
`visible`, `static`, `antialias`, `lint`, `overrides`. Not `size:` (the
extent is computed from the ink), not `on_hold:` (hold a `group` around
it).

| key | radial | linear |
|---|---|---|
| `at:` | the centre of rotation; any ordinary position (anchor, dx/dy, polar), parent-box relative | copy 0's origin; same |
| `count:` | required, integer 1–360 | same |
| `step:` | an angle; default `360deg / count`; negative turns counter-clockwise; `0deg` is an error | **required** `{dx, dy}` (either may be omitted = 0); lengths as in `at:` (`px`, `%`, `%r`; not `pt`) |
| `start:` | angle of copy 0, default `0deg` | **error** |
| `skip:` | list of copy indices (0-based, each `< count`, no duplicates) not drawn | same |
| `skip_every:` | integer `2..count`: copies whose index is a multiple of it are not drawn | same |
| `color:` | default colour for parts without their own | same |
| `parts:` | 1–16 parts (§5.2) | same |

### 5.2 Parts

A part is a hand part (`docs/format.md` "Analog hands") with one addition:

| `shape:` | keys | per copy, on the watch |
|---|---|---|
| `polygon` | `points` (3–64) | transform every vertex, `fillPolygon` |
| `rectangle` | `at` (its centre, default the origin), `size` | folded into a 4-point polygon at build time, then as above |
| `line` | `at` (start, default the origin), `to`, `thickness` (default 1px) | transform both ends, `drawLine` |
| `circle` | `at` (default the origin), `radius`, `filled` (default true), `thickness` (only when `filled: false`) | transform the centre, `fillCircle`/`drawCircle` |
| `arc` (**new**) | `radius`, `thickness` (default 1px), `start_angle`, `sweep`; **no `at:`** — always centred on the copy's origin | radial: start angle + the copy's rotation; linear: centre moves. `WfbArc.drawSpan` |

- Part positions use the hand frame: origin = the pattern's `at:`, `dx`
  right, `dy` down, `px`/`%r` only, `anchor:` rejected, polar `{angle,
  radius}` allowed. Resolved to whole pixels, rounded half away from zero
  (`wfb.layout._round_away`), exactly as a hand part.
- `rounded_rectangle`, `ellipse`, `text`, `icon` are rejected with a reason
  each (no `Dc` call draws the first two rotated; a bitmap font cannot
  rotate). `at:` on an `arc` part is rejected (§9 D3). `filled: false` on
  `polygon`/`rectangle` is rejected (no `drawPolygon`). A key a part's
  shape does not read is an error — the `_check_hand_part_keys` precedent.
- A part with no colour of its own and no element `color:` is an error. A
  colour that reads data is an error (the hand rule; a pattern has no
  `when_absent:`). Palette, literal, `config.*` and conditionals over those
  are fine.

### 5.3 The transform

- **Radial:** copy `i` is the template rotated **clockwise** by
  `start + i × step` degrees about `at:` (screen convention, y down):
  `x' = cx + x cos θ − y sin θ`, `y' = cy + x sin θ + y cos θ` — the
  `WfbHands` formula. An arc part's author start angle becomes
  `start_angle + start + i × step`.
- **Linear:** copy `i`'s origin is `at + i × step`. `step` is resolved to
  **whole pixels once** (`_round_away`), so every gap is identical; the
  total span may drift from `count × step` by under half a pixel per copy.
- **Draw order:** copy by copy in ascending index; within a copy, parts in
  list order.

### 5.4 Build-time checks (all errors, each driven red by a test)

1. `pattern: radial` with a mapping `step:`; `pattern: linear` with an
   angle `step:`, or with no `step:`.
2. `start:` on a linear pattern.
3. Radial `step: 0deg`; radial copies that land on each other:
   `|step| × (count − 1) ≥ 360°` (error names the two copy indices).
4. A `skip:` index `≥ count` or repeated; `skip_every` `> count`; every
   copy skipped.
5. The part rules of §5.2.
6. `modes:` containing `low_power` (as on `hands`: a fixed pattern gains
   nothing from `onPartialUpdate`, and its clip would be its whole extent).
7. Lint (per device, error, code `pattern-step`): a linear `step:` that
   rounds to `{0, 0}` on that device.

A rejected pattern element is one error, not N (`docs/lore/codegen.md`).

### 5.5 Extent and lints

- `box` is the bounding box of the ink of every **drawn** copy (lines
  padded by half the pen width, circles by the radius, outlined circles
  by half the pen as well, arcs conservatively by their full circle).
- A radial pattern also reports `reach` (the farthest ink from the
  centre); `circular_extent()` returns `(cx, cy, reach)` for it, so a
  full-dial tick ring is checked as the disc it is, like `hands`.
- `PlacedPattern` joins `ANTIALIASED_PRIMITIVES` (emit gate, per-element
  toggle, `antialias-dither`).

## 6. Interfaces (the contract between the build phases)

### 6.1 IR (`wfb/ir.py`)

```python
@dataclass
class HandPart:            # existing; gains two fields for `arc` parts
    ...
    start_angle: Angle | None = None   # arc only, author degrees
    sweep: Angle | None = None         # arc only

@dataclass
class PatternElement(Element):          # kind == "pattern"
    pattern: str = "radial"             # "radial" | "linear"
    count: int = 1
    step_angle: float = 0.0             # radial: degrees, default already applied
    start_angle: float = 0.0            # radial
    step: Position | None = None        # linear: dx/dy only
    skip: tuple[int, ...] = ()
    skip_every: int | None = None
    parts: list[HandPart] = field(default_factory=list)
    color: Expression | None = None     # element default, before part overrides
    colors: tuple[Expression, ...] = () # every effective part colour, deduplicated

    def drawn_indices(self) -> tuple[int, ...]: ...   # ascending, skips applied
    def _own_expressions(self) -> list[Expression]: return list(self.colors)
```

Part building reuses `_build_hand_part`/`_check_hand_part_keys`,
parameterised by context (hand vs pattern) for the allowed shapes, the
`arc` keys and the wording of messages (`hands.<set>.<hand>.parts[i]` vs
`<element id>.parts[i]`). Hand behaviour must not change.

### 6.2 Layout (`wfb/layout.py`)

```python
@dataclass(frozen=True)
class ResolvedHandPart:    # existing; gains arc fields
    ...
    start_angle: float = 0.0   # "arc": author degrees (12 o'clock = 0, clockwise)
    sweep: float = 0.0

@dataclass
class PlacedPattern(Placed):
    parts: tuple[ResolvedHandPart, ...] = ()   # rectangle folded into polygon
    copies: tuple[int, ...] = ()               # drawn indices, ascending
    start: float = 0.0                         # radial: degrees
    step: float = 0.0                          # radial: degrees
    dx: int = 0                                # linear: whole pixels
    dy: int = 0
    reach: float = 0.0                         # radial: farthest ink from centre

    def transform(self, index: int) -> tuple[float, float, float, float]:
        """(ox, oy, sin, cos) for copy `index`: radial = (cx, cy, sinθ, cosθ);
        linear = (cx + i*dx, cy + i*dy, 0.0, 1.0).  The one formula the
        preview and the extent computation share."""
```

`center` is the origin `(round(cx), round(cy))`. `ANTIALIASED_PRIMITIVES`
gains `PlacedPattern`.

### 6.3 Barrel (`runtime-lib/`)

The four rotate-and-draw helpers move out of `WfbHands.mc` into a new
shared **`WfbGeom.mc`** (module `WfbGeom`), used by both hands and
patterns — the "one convention, one helper" precedent `WfbArc.mc` set for
arcs. `WfbHands.mc` keeps only the three angle functions. `WfbGeom` also
gains `fillTranslated(dc, points, ox as Number, oy as Number)` for linear
polygon parts. `wfb/emit/project.py` `BARREL_FILES`/`_barrel_for` pull
`WfbGeom.mc` for hands and patterns, `WfbArc.mc` for a pattern with an arc
part.

### 6.4 Generated code

`Layout` constants, per device, prefix `P = _const_prefix(id)`: `P_X`,
`P_Y` (origin); linear `P_DX`, `P_DY`; per part `j` the same constants a
hand part gets (`P_<j>_POINTS`, `_X1.._Y2`, `_THICKNESS`, `_X/_Y/_RADIUS`)
and, for an arc, `P_<j>_RADIUS`, `P_<j>_THICKNESS`. Angles, `count` and
skips are device-independent: literals in the view.

Radial draw method, shape of the output:

```monkeyc
//! `minute_ticks` -- a radial pattern: 60 copies, 6 degrees apart (48 drawn).
//! Drawn in: active.
private function drawMinuteTicks(dc as Dc) as Void {
    var cx = Layout.MINUTE_TICKS_X;
    var cy = Layout.MINUTE_TICKS_Y;
    dc.setColor(Palette.GRAY, Graphics.COLOR_TRANSPARENT);   // hoisted: one colour
    dc.setPenWidth(Layout.MINUTE_TICKS_0_THICKNESS);           // hoisted: one pen, no arc
    for (var i = 0; i < 60; i++) {
        if (i % 5 == 0) {
            continue;
        }
        var angle = i * 0.10471975511965977;                   // (0 + 6 i) degrees
        var sin = Math.sin(angle);
        var cos = Math.cos(angle);
        WfbGeom.drawLineRotated(dc, Layout.MINUTE_TICKS_0_X1, Layout.MINUTE_TICKS_0_Y1,
                                Layout.MINUTE_TICKS_0_X2, Layout.MINUTE_TICKS_0_Y2,
                                cx, cy, sin, cos);
    }
    dc.setPenWidth(1);
}
```

- Colour: one distinct part colour → `setColor` once before the loop;
  several → inside the loop body, before part 0 and at each change.
- Pen width: hoisted when every line/outlined-circle part shares one width
  and there is no arc part (`drawSpan` resets the pen); otherwise set per
  part inside the loop. Restored to 1 after the loop when set.
- Skip: `if (<i % N == 0> || <i == a> || ...) { continue; }`, omitting
  explicit indices already covered by `skip_every`; no `if` when nothing
  is skipped.
- Arc, radial: `WfbArc.drawSpan(dc, cx, cy, Layout.P_j_RADIUS,
  Layout.P_j_THICKNESS, <g0> - i * <step>, <sweep>)` with `g0 = 90 −
  (start_angle + start)` and `step` in degrees, Float literals.
- Linear: `var ox = Layout.P_X + i * Layout.P_DX; var oy = …`; lines,
  circles and arcs draw directly at `ox + X` etc.; polygons via
  `WfbGeom.fillTranslated`.
- `visible:`, the anti-alias toggle, `static:` and layouts need nothing
  new: the ordinary per-element draw-method machinery wraps this body.

### 6.5 Sites that switch on element kinds (check every one)

`grep -n "HandsElement\|PlacedHands\|\"hands\"" wfb/` lists them. Known:
`wfb/ir.py` element dispatch; `wfb/layout.py` `_resolve_list`,
`circular_extent`, `ANTIALIASED_PRIMITIVES`; `wfb/emit/monkeyc.py`
`_layout_constants`, draw dispatch, `_describe`, the Layout module's
`Toybox.Graphics` import gate (`_hands_needs_graphics`, `Point2D`), the
view's `Toybox.Math` import gate (`hands_modules`); `wfb/emit/project.py`
`_barrel_for`; `wfb/preview.py` dispatch; `wfb/lint.py` wherever a kind
is enumerated.

## 7. Build phases

| phase | who | scope |
|---|---|---|
| 1 | subagent A | schema (`patternElement`, `patternPart`, `patternStep`, `element` oneOf, `antialias` description), `wfb/validate.py` if it enumerates types, IR (§6.1, §5.4 1–6), layout (§6.2, §5.5), lint (`pattern-step`, `circular_extent`, dither), tests |
| 2a | subagent B | barrel split (§6.3), codegen (§6.4, §6.5), project barrel, codegen tests, warning-free `monkeyc` builds of `examples/patterns/` and `examples/analog/` on all three targets, `--build-stats` figures |
| 2b | subagent C | preview (`PlacedPattern` via `transform()`, reusing `_hand_part` plus an arc branch through `arc_span`), preview tests |
| 3 | orchestrator | review, docs (§8), history, commit; this plan deleted once built |

**Acceptance:** `examples/patterns/face.yaml` builds warning-free on all
three targets and is clean under `test_example_is_clean_on_every_target`;
`pytest -m "not slow"` shows only the three known failures; every §5.4
error has a test that drives it red; `examples/analog/` output is
unchanged apart from `WfbHands.` → `WfbGeom.` for the moved helpers.

## 8. Documentation touched when built

`docs/format.md` (a `### pattern` section; `antialias:` and element-list
mentions), the schema, `docs/limitations.md` §2, `docs/adr/0004` (a second
amendment: the repeat transform runs on the watch), `docs/lore/roadmap.md`,
root `CLAUDE.md` §1/§6, `examples/CLAUDE.md`, `runtime-lib/README.md`,
`docs/history.md`.

## 9. Decisions made without a round-trip (for the user to review)

- **D1 — `type: pattern` + `pattern: radial | linear`**, not `type:
  radial` / `type: linear`. Element types are nouns (`shape`, `hands`,
  `graph`); the two kinds share every key but `start`/`step`'s shape; one
  type leaves room for `pattern: grid` later.
- **D2 — the watch performs the repeat transform** (ADR 0004 amended a
  second time). Measured in §2: 170 B instead of ~5 KB for a minute ring.
  The template itself is still resolved to whole pixels at build time.
- **D3 — arc parts are centred on the origin** (no `at:`). That covers
  segmented rings, the use case; an off-centre rotating arc would need a
  rounded rotated centre, and nothing asked for it.
- **D4 — linear steps are whole pixels**: equal gaps matter more to the
  eye than an exact total span.
- **D5 — not in this plan:** text/numeral parts (index-dependent text),
  `pattern: grid`, data-bound colours, `on_hold:`, `low_power`, per-copy
  variation beyond skipping, `rounded_rectangle`/`ellipse` parts in a
  linear pattern. Each is listed in `docs/limitations.md` §2.
- **D6 — the template is inline** on the element, not a named top-level
  block like `hands:`: a pattern is placed once, and `layouts:` can hold a
  different pattern element per style if one is needed.
- **D7 — `WfbHands`' rotate-and-draw helpers move to a shared `WfbGeom`**
  rather than being duplicated or pulled in by patterns under a hands name.
