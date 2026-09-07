# ADR 0004 — Element model and coordinate system

- **Status:** Accepted
- **Date:** 2026-09-04
- **Decides:** the layer/element vocabulary, and how a single design adapts
  across screen shapes and sizes.

## Context

The design must survive 148 px to 480 px, four screen shapes (round 115,
rectangle 37, semi-octagon 8, semi-round 4), without the author re-laying-out per
device — while still allowing per-device overrides
(`00-summary.md`, `01-platform-capabilities.md` §6).

Even the three chosen targets defeat fixed pixels: `fenix8solar47mm` and `fr955`
are 260×260 but `fenix8solar51mm` is **280×280**.

Prior art is informative in both directions. WFF's element taxonomy is good and
worth borrowing; **its coordinate model is its weakest part** — a fixed
`width`/`height` canvas that the system scales, with no anchoring
(`04-prior-art.md` §1). Wear OS's device spread is narrow enough to absorb that.
Garmin's is not.

## Decision

### 1. Element vocabulary

A tree of typed elements, borrowing WFF's shape but mapped onto Garmin's actual
`Dc` primitives (`01-platform-capabilities.md` §5):

| Element | Renders via |
|---|---|
| `group` | container; applies inherited anchor/visibility/mode, no drawing of its own |
| `text` | `drawText`, or `drawAngledText`/`drawRadialText` where a vector font is available |
| `shape` | `fillRectangle`, `fillRoundedRectangle`, `fillCircle`, `fillEllipse`, `fillPolygon`, `drawLine` |
| `image` | `drawBitmap` / `drawScaledBitmap` |
| `icon` | a single glyph from a vendored icon font, drawn via `drawText` (preferred over `image` — see `02-features-feasibility.md` §1; superseded the drawn-primitives approach this ADR originally described — see CLAUDE.md's icon-catalogue session notes) |
| `progress` | one of four styles, `arc` among them; see below — there is no separate standalone `arc` element, despite an earlier draft of this table listing one |
| `complication_slot` | a bound complication with a hit region |
| `raw` | escape hatch, see ADR 0007 |

**As built, `shape:` exposes only `rectangle`, `rounded_rectangle`, `circle`
and `line`** (the schema's actual enum) — `fillEllipse`/`fillPolygon` were
never implemented; tracked in `docs/limitations.md`.

`progress` is a single element with a `style` discriminator rather than four
element types, because the *binding* and *range* semantics are identical across
them and only the rendering differs:

- `style: arc` — `setPenWidth` + `drawArc`. **Constrained**: no filled sector
  exists, so thickness is a pen width, cap style is not selectable, and true
  annuli/gradients are not offered. The schema deliberately does not expose
  `innerRadius`/`outerRadius`, because promising them would be a lie.
- `style: bar` — `fillRectangle` / `fillRoundedRectangle`.
- `style: segments` — a repeated shape filling one by one.
- `style: scale` — ticks + coloured range band + pointer.

Z-order is document order, with an optional explicit `z` override. Groups nest.

### 2. Coordinate system — anchors plus relative units, with polar as a first-class option

Absolute pixels are rejected as the primary model; they are available only as a
per-device override.

A position is expressed as one of:

```yaml
# cartesian, relative to an anchor on the parent (or screen)
at: { anchor: center, dx: 0, dy: -18% }

# polar -- essential for round faces, which are 115/164 devices
at: { anchor: center, angle: 45deg, radius: 38% }
```

Rules:

- **Percentages resolve against the parent box**: `%` of width for horizontal,
  `%` of height for vertical. `%r` resolves against the screen's *minor radius*,
  which is what keeps a round design circular on a non-square screen.
- **Anchors** are the nine box positions (`center`, `top_left`, `top`, …) on the
  parent group or the screen.
- **Angles** are degrees, 12 o'clock = 0, clockwise positive — chosen to match
  how a watch designer thinks, and normalised to Garmin's `drawArc` convention by
  the generator rather than by the author.
- Lengths accept `px`, `%`, `%r`, and `pt` (font-relative, resolving against the
  *actual* per-device font pixel height — see below).

This mirrors the approach the sibling Dashboard project arrived at empirically:
its `Layout` module holds fractions of screen height/width and forbids bare
fractions in drawing code. That project is direct evidence the model works for a
dense real-world face.

### 3. Safe area and shape adaptation

The device database records `screen_shape`. The compiler derives a **safe
inscribed area** per shape (a circle for `round`, the rectangle for
`rectangle`, shape-specific for `semi-round`/`semi-octagon`) and lints elements
that fall outside it (Phase 1.4). Authors position against anchors; the compiler
knows the shape.

### 3b. `deviceFamily` is the resource-qualifier directory name

`compiler.json` reports `deviceFamily` directly — `round-260x260` for
`fenix8solar47mm` and `fr955`, `round-280x280` for `fenix8solar51mm`
(`05-device-files.md` §5). That string **is** the per-device resource directory
the generator must emit (`resources-round-260x260/`), so the generator reads it
rather than deriving it from width/height. It also confirms that a bitmap font
baked for 260×260 is wrong on the 51 mm — the drift already present in the
sibling Dashboard project.

Also from the device files: **`alphaBlendingSupport` is `false` on all three
targets.** Any element property implying transparency or alpha compositing must
be gated on that flag rather than assumed.

### 4. Per-device overrides

A design is one document; overrides are a scoped patch, never a fork:

```yaml
elements:
  - id: clock
    at: { anchor: center, dy: -12% }
    overrides:
      fenix8solar51mm: { at: { anchor: center, dy: -10% } }
      "shape:rectangle": { at: { anchor: top, dy: 8% } }
```

Override keys may be a device id, or a **capability selector** (`shape:`,
`colors:`, `touch:`, `api:`). Capability selectors are strongly preferred and
device ids are the escape hatch — the same principle as the format overall.
Overrides deep-merge; unknown device ids are a build error, not a silent no-op.

### 5. Text metrics are resolved at build time

The SDK's device reference publishes, per device *and per language*, each
`FONT_*` symbol's face and **pixel size** (`02-features-feasibility.md` §7),
extracted into `docs/research/data/devices/*.json`. So the compiler can compute
real text extents without a device.

This makes `pt` units meaningful, makes "does this label overflow its slot on
this device in this language?" a static check, and is the main reason the preview
renderer can be trusted. It is a capability hand authors do not have.

## Consequences

- The IR carries **resolved absolute pixels per target device**, computed from
  relative units at build time. Nothing relative survives into generated Monkey C
  — the device does no layout arithmetic, which saves both memory and per-frame
  cost.
- The preview renderer consumes the **same resolved IR**, so preview and device
  cannot disagree about position. This is the anti-drift mechanism Phase 3.8 asks
  for, and it works only because layout is resolved before codegen.
- Because the resolver is pure (design + device → geometry), it is directly
  unit-testable with no Garmin toolchain.
- `semi-octagon` and `semi-round` need safe-area definitions we do not have yet;
  until then they are unsupported targets rather than silently wrong ones.

## Open

- Exact safe-area geometry for `semi-round` and `semi-octagon`. Resolvable from
  the device files' screen shape data once available.
- Whether to support a constraint solver (element A right-of element B) rather
  than only parent-relative anchors. Deferred: anchors cover the reference design
  and a solver is a large addition. Revisit if real faces demand it.
