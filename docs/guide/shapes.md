# Shapes

`type: shape` draws one primitive from the `Dc` drawing API — a rectangle,
circle, ellipse, arc, polygon or line — filled or outlined. Each shape reads
only the keys its own geometry needs, so a card, a pill, a chevron and a
divider rule are each a few keys, not a general-purpose shape object.

![shapes example](../screenshots/shapes.png)
*All seven shapes, from `examples/features/shapes/face.yaml`.*

## At a glance

| `shape:` | Keys read | Draws |
|---|---|---|
| `rectangle` | `size`, `color`, `filled`, `thickness` | [`fillRectangle` / `drawRectangle`](#shape) |
| `rounded_rectangle` | `size`, `corner_radius`, `color`, `filled`, `thickness` | [`fillRoundedRectangle` / `drawRoundedRectangle`](#shape) |
| `circle` | `radius`, `color`, `filled`, `thickness` | [`fillCircle` / `drawCircle`](#shape) |
| `ellipse` | `size`, `color`, `filled`, `thickness` | [`fillEllipse` / `drawEllipse`](#shape) |
| `arc` | `radius`, `start_angle`, `sweep`, `thickness`, `color` | [`setPenWidth` + `drawArc`](#arc) |
| `polygon` | `points`, `color` | [`fillPolygon`](#polygon) |
| `line` | `to`, `thickness`, `color` | [`drawLine`](#shape) |

`filled:` defaults to `true` on the four rows that accept it; `thickness:`
defaults to 1 px. See [Shapes](#shape) below for which shapes reject `filled:`
and why.

## Example

```yaml
card:    { type: shape, shape: rounded_rectangle, corner_radius: 6px,
           filled: false, thickness: 2px }
pill:    { type: shape, shape: ellipse, size: { width: 22%, height: 11% } }
chevron: { type: shape, shape: polygon,
           points: [{ anchor: center, dy: 26% },
                    { anchor: center, dx: -9%, dy: 34% },
                    { anchor: center, dx: 9%, dy: 34% }] }
rule:    { type: shape, shape: line, at: { ... }, to: { ... } }
```

The shapes are `rectangle`, `rounded_rectangle`, `circle`, `ellipse`, `line`,
`arc` and `polygon`. Closed shapes can be filled or outlined (`filled: false`
plus `thickness:`). An arc is a stroke only. The platform has no filled arc, no
rounded caps and no gradients.

### `shape`

```yaml
- id: background
  type: shape
  shape: rectangle    # rectangle | rounded_rectangle | circle | ellipse
  at: { anchor: center }    #  | arc | polygon | line
  size: { width: 100%, height: 100% }
  color: palette.bg
```

Seven shapes, one per native `Dc` drawing call. Each takes `color:`, and each
takes **only** the keys its own geometry needs -- a key from another row is an
error, not a no-op, so `radius:` typed where `corner_radius:` was meant is
reported rather than drawing square corners in silence:

| `shape:` | keys | draws |
|---|---|---|
| `rectangle` | `size` | `fillRectangle` / `drawRectangle` |
| `rounded_rectangle` | `size`, `corner_radius` | `fillRoundedRectangle` / `drawRoundedRectangle` |
| `circle` | `radius` | `fillCircle` / `drawCircle` |
| `ellipse` | `size` | `fillEllipse` / `drawEllipse` |
| `arc` | `radius`, `start_angle`, `sweep` | `setPenWidth` + `drawArc` |
| `polygon` | `points` | `fillPolygon` |
| `line` | `to` | `drawLine` |

`align:`/`vertical_align:` follow the one placement rule every accepting kind
shares: [Placement: `at:` and `align:`](placement.md#placement-at-and-align). Accepted on
every row above except `polygon` and `line`, which reject them with the
reason (no single `at:` to align on; `at:`/`to:` are already the two ends).

**`filled:` (default `true`) is a real switch, not decoration.** `filled: false`
draws the outline at `thickness:` (default 1 px) instead of filling, on
`rectangle`, `rounded_rectangle`, `circle` and `ellipse`. The outlined shape's
ink straddles the declared box, so the compiler grows the element's extent by
half a pen width for the safe-area and overlap checks -- what you declare is
still the geometry, not the ink.

`thickness:` is checked against `filled:` rather than against the shape: a
`line` and an `arc` always draw with it, and any other shape uses it only when
outlined, so `thickness:` on a shape left filled is an error too.

Two shapes reject `filled:`, and both refusals are the platform's, not this
project's:

* **`arc` rejects `filled:` outright.** There is no `fillArc`, `fillSector` or
  `drawSector` anywhere in Connect IQ. An arc is a pen width and nothing else,
  so there is no inner/outer radius, no cap control, and no gradient sweep. For
  a solid disc use `circle`; for a solid wedge, approximate it with `polygon`.
* **`polygon` rejects `filled: false`.** `Dc` has `fillPolygon` and no
  `drawPolygon`. Draw the edges as `line` elements if you want an outline.

`points:`, `start_angle:` and `sweep:` are likewise errors on a shape that
cannot use them, rather than being read and quietly dropped.

#### `arc`

```yaml
- id: outer_arc
  type: shape
  shape: arc
  at: { anchor: center }
  radius: 92%r
  thickness: 5px
  start_angle: 210deg     # 12 o'clock is 0, clockwise positive
  sweep: 300deg           # negative sweeps counter-clockwise
  color: palette.dim
```

Angles are the format's own convention -- 12 o'clock is 0 and clockwise is
positive -- converted to Garmin's (3 o'clock is 0, counter-clockwise) at build
time. It is **exactly** the conversion `progress` with `style: arc` uses; both
call `wfb.layout.garmin_arc` and both draw through the same
`WfbArc.drawSpan`, so the two arcs cannot drift apart.

Use `shape: arc` for a fixed decorative span and `type: progress` /
`style: arc` for one whose length is bound to a reading.

#### `polygon`

```yaml
- id: chevron
  type: shape
  shape: polygon
  points:                             # 3 to 64 of them
    - { anchor: center, dy: 26% }
    - { anchor: center, dx: -9%, dy: 34% }
    - { anchor: center, dx: 9%, dy: 34% }
  color: palette.accent
```

Each entry in `points:` is a full `at:`-style position -- anchor, `dx`/`dy`, or
polar `angle`/`radius` -- resolved against the parent box exactly the way a
`line`'s `to:` is. The resolved vertices land in the per-device `Layout` module
as one `Array<Graphics.Point2D>` constant, so the device does no arithmetic
(ADR 0004). `fillPolygon` documents a **64-point limit**, which the schema
enforces.

See `examples/features/shapes/face.yaml` for all seven on one face.

## See also

- [`examples/features/shapes/face.yaml`](../../examples/features/shapes/face.yaml) — all seven shapes on one face.
- [Progress bars, arcs and graphs](progress-and-graphs.md) — `type: progress` / `style: arc`, for a span bound to a reading instead of a fixed decoration.
- [Placement](placement.md#placement-at-and-align) — `at:`, `align:` and `vertical_align:`.
