# Progress bars, arcs and graphs

`progress` draws a fill as a bar or an arc — a step ring, a battery level,
anything bound to a value and a max. `graph` plots a time series as a line, a
filled area or bars. Both take an expression for their data, and both follow
the same placement rule as every other element with a box.

![battery arc progress](../screenshots/showcase-status.png)
*Two `style: arc` progress elements drawing `system.battery`, from `examples/showcase`.*

## At a glance

### `progress`

| Key | Values | Default | Meaning |
|---|---|---|---|
| `style` | `arc`\|`bar`\|`needle` | required | ring, bar, or [gauge needle](#gauge-needles) |
| `value` | expression | required | the fill amount |
| `max` | expression | required | the full-scale amount |
| `radius` | length | required (`arc`) | ring radius |
| `thickness` | length | required (`arc`) | pen width |
| `start_angle` | angle | required (`arc`, `needle`) | where the ring starts, or where the needle points at 0 |
| `sweep` | angle | required (`arc`, `needle`) | how far the ring sweeps, or the needle turns at full scale |
| `needle` | 1–16 [hand parts](analog-hands.md#analog-hands) | required (`needle`) | the needle, pointing at 12, axis at `at:` |
| `size` | size | required (`bar`) | the bar's box |
| `color` | color expression | — | fill colour |
| `track_color` | color expression | — | the unfilled track |
| `align` / `vertical_align` | `left`\|`center`\|`right` / `top`\|`center`\|`bottom` | `center` | box edge at `at:`, both styles ([details](placement.md#placement-at-and-align)) |
| `when_absent` | `hide`\|`fallback` | — | required once `value`/`max` can be absent |
| `fallback` | expression | — | substitute with `when_absent: fallback` |

### `graph`

| Key | Values | Default | Meaning |
|---|---|---|---|
| `series` | a name from `wfb series` | required | which time series to plot |
| `range` | duration (`30m`/`4h`/`7d`) or a sample count | required | how much history |
| `buckets` | integer | `40` | time bins; `heart_rate` over a duration only |
| `style` | `line`\|`area`\|`bars` | `line` | rendering |
| `thickness` | length | — | pen width, `style: line` only |
| `bar_width` | length | — | `style: bars` only |
| `min` / `max` | `auto`\|number\|expression | `auto` | plotted bounds |
| `size` | size | required | the graph's own box |
| `color` | color expression | — | line/area/bar colour |
| `align` / `vertical_align` | `left`\|`center`\|`right` / `top`\|`center`\|`bottom` | `center` | box edge at `at:` ([details](placement.md#placement-at-and-align)) |

Run `wfb series` for the current catalogue of plottable series names.

## Example

```yaml
hr_graph:    { type: graph, series: heart_rate, range: 4h, buckets: 32,
               style: line, thickness: 2px }
steps_graph: { type: graph, series: steps, range: 7d,
               style: bars, bar_width: 6px, min: 0 }
temp_graph:  { type: graph, series: forecast_temperature, range: 24h,
               style: area }
```

![graph example](../screenshots/graph.png)

Four families of series can be plotted:
- heart-rate history
- daily activity (steps, calories, distance, floors, active minutes)
- the hourly forecast
- the daily forecast

The platform keeps pressure, stress and Body Battery history away from watch
faces. The preview draws a stand-in curve, not real data.

### `progress`

One element with a `style` discriminator, because the *binding* and *range*
semantics are identical across styles and only the rendering differs.

```yaml
- id: step_ring
  type: progress
  style: arc                # arc | bar
  value: activity.steps
  max: activity.step_goal
  at: { anchor: center }
  radius: 90%r
  thickness: 10px
  start_angle: 180deg
  sweep: 340deg
  color: palette.accent
  track_color: palette.track
  when_absent: hide
```

> **`style: arc` is a stroked ring, not a filled sector.** There is no `fillArc`,
> `fillSector` or `drawSector` anywhere in the Connect IQ API. `thickness` is a
> pen width; cap style is not selectable; true annuli and gradient sweeps do not
> exist. The schema deliberately does not offer `inner_radius`/`outer_radius`,
> because promising them would be a lie.

`align:`/`vertical_align:` follow the one placement rule every accepting kind
shares: [Placement: `at:` and `align:`](placement.md#placement-at-and-align) — accepted on
`bar` and `arc`: `bar`'s box is `size:` and `arc`'s is the full `2·radius`
circle, same as `shape: arc`. A needle refuses both (below).

#### Gauge needles

`style: needle` turns a needle about `at:` to show the fraction — the
analog hands' rotation machinery, driven by a reading instead of the
clock:

```yaml
- id: battery_needle
  type: progress
  style: needle
  value: system.battery
  max: 100
  at: { anchor: center }               # the axis
  start_angle: 240deg                  # where the needle points at 0%
  sweep: 240deg                        # how far it turns at 100%, clockwise
  color: "system.battery < 20 ? palette.low : palette.accent"
  needle:                              # authored like an analog hand's parts
    - shape: polygon
      points: [{ dx: -3%r, dy: 12%r }, { dy: -74%r }, { dx: 3%r, dy: 12%r }]
    - { shape: circle, radius: 5%r, color: palette.fg }   # a hub that turns with it
```

The needle points at `start_angle + fraction × sweep`, clockwise from 12,
where the fraction is `value / max` clamped to 0–1 — the same mapping an
`arc` fills with, so a needle and an arc with the same `start_angle` and
`sweep` agree. `needle:` takes exactly what a [hand's
`parts:`](analog-hands.md#analog-hands) takes: `polygon`, `rectangle`, `line`
and `circle`, authored **as they look at 12 o'clock** with the axis at the
origin, so the tip sits at a negative `dy`. A part with no `color:` takes
the element's own, which may read data like any progress colour; a part's
own colour may not, as on a hand.

The needle's extent is the disc it sweeps (the axis plus its farthest
part), which the visible-area checks read like a hand's. `when_absent:`
works as on the other styles: `hide` draws nothing, `fallback:` supplies
the fraction to park at. `aod: {color, thickness}` restyles every part.
`radius`, `thickness`, `size`, `track_color` and `align`/`vertical_align`
are not read by a needle, and each is an error saying so: its length is
its parts, and `at:` is the axis, not a box. Draw the dial itself with a
separate `style: arc` progress or a radial `pattern` of ticks, sharing the
needle's `start_angle` and `sweep` (`examples/features/gauge/face.yaml`).

### `graph`

A time series, drawn as a line, a filled area or bars:

```yaml
- id: hr_graph
  type: graph
  at: { x: 50%, y: 72% }
  size: { width: 60%, height: 18% }

  series: heart_rate          # run `wfb series` for the full catalogue
  range: 4h                   # a duration (30m/4h/7d) or a bare sample count
  buckets: 40                 # time-binned series only; default 40

  style: line                 # line | area | bars ; default line
  thickness: 2px               # style: line only
  bar_width: 3px               # style: bars only

  min: auto                   # auto (default) | a number | an expression
  max: auto

  color: palette.accent
```

`align:`/`vertical_align:` follow the one placement rule every accepting kind
shares: [Placement: `at:` and `align:`](placement.md#placement-at-and-align) — a graph's
placement box is its own `size:`.

**`series:`** names an entry in a second, smaller catalogue than `wfb
sources`' — run `wfb series` for the current list. Four families, all
needing **no permission**: `heart_rate` (`ActivityMonitor.
getHeartRateHistory`); the daily activity family `steps`, `calories`,
`distance`, `floors_climbed`, `active_minutes` (`ActivityMonitor.
getHistory()`, at most 7 days); the hourly forecast family
`forecast_temperature`, `forecast_precipitation_chance`,
`forecast_cloud_cover`, `forecast_uv_index`, `forecast_wind_speed`,
`forecast_humidity`; and the daily forecast family
`daily_high_temperature`, `daily_low_temperature`,
`daily_precipitation_chance` (both `Weather` calls). **Nothing backed by
`Toybox.SensorHistory` — pressure, stress, elevation, Body Battery as a
history — and no solar series exist at all**: see
[`docs/limitations.md`](../limitations.md) and
`docs/research/08-graphs-and-configuration.md` §1.

Naming one of those anyway is an error that **says why**, rather than
reporting an unknown name:

```
error[graph]: 'pressure' cannot be plotted on a watch face
  note: Toybox.SensorHistory is the only API that serves it as a history, and a
        watch face may not declare that permission -- Core_Topics/
        Manifest_and_Permissions.html gives SensorHistory an empty
        'Watch Face' column
```

Each of these is a real quantity the watch measures and shows in its own
native widgets, which is exactly why the name gets typed; "unknown series"
would send you hunting for a spelling mistake that does not exist. A genuine
typo still gets the suggestion (`series: step` → *did you mean: steps?*).

**`range:`** is a duration (`30m`, `4h`, `7d`) or a bare integer sample
count. `heart_rate` passes a duration straight through to
`getHeartRateHistory`, which bins it by real time on-device — its own
sample interval is device-dependent, so a build-time sample count cannot be
derived from it. Every other series converts a duration to a count at build
time using its own natural interval (one day for the activity and
daily-forecast families, one hour for the hourly-forecast one); asking for
more than a series' own documented maximum (`steps`, `calories`,
`distance`, `floors_climbed` and `active_minutes` all read the same
`getHistory()`, whose own limit is 7 days) is a **build error**, not a
silent clamp to 7 — silently drawing fewer than asked for is exactly the
class of quiet wrongness this compiler exists to remove. The forecast
families document no such maximum, so a design asking for more than the
provider actually has simply gets fewer, checked at runtime the same
bounds-checked way `weather.condition_today`/`_tomorrow` already are.

**`buckets:`** only means something for `heart_rate` read over a
*duration* — a time-binned series, where a bucket can genuinely have no
sample in it. Naming it on anything else is a build error pointing at the
series that would silently have ignored it. Default 40. It cannot be
derived from the element's resolved width: `wfb/emit/project.py` generates
one view shared across every target device, so a per-device pixel width can
never become a build-time constant in it — the same constraint
`wfb.icons.font_key`'s docstring records for a font's declared, rather than
resolved, size.

**A bucket, or a day/hour with no reading, does not draw** rather than
plotting a zero or a guessed value — a line breaks there instead of joining
straight across, and a bar simply is not drawn. A filled area cannot lift
the pen partway through one `fillPolygon`'s own outline, so `style: area`
draws one filled run per contiguous stretch of present samples instead,
each closed with its own two bottom corners — a gap ends one run and starts
the next, rather than joining straight across it, guessing, or blanking the
whole graph for the sake of one missing sample.

**`style: area` is capped at 62 samples.** `Dc.fillPolygon` is the only fill
`Dc` offers that follows a curve, so a filled graph inherits its 64-point
limit; closing the outline costs two corners, leaving 62 for the series
itself. Exceeding it is a build error naming the cap and `style: line` as
the alternative.

**`min:`/`max:`** are `auto` (the default), a number, or an expression —
the last two compile exactly like any other bound value. `auto` on
`heart_rate` reads the iterator's own `getMin()`/`getMax()`, which is free
and already scoped to the samples in this graph's own range; `auto` on
every other series computes the extent of whatever was actually collected,
skipping gaps. Two fixed bounds with `min >= max` is a build error.

**The series is cached in a private view field and rebuilt only when the
clock minute changes** — one `Number` comparison a frame, not the TTL cache
this project deleted (`wfb/catalog.py`'s module docstring): that deletion
was about re-caching a value Garmin already caches on its own side, and a
graph's own computation over a source whose sample interval is minutes
cannot produce new information by recomputing it every second. **CPU cost
is unmeasured** — see `docs/limitations.md`.

## See also

- [`examples/features/graph/face.yaml`](../../examples/features/graph/face.yaml) — every series family and all three graph styles.
- [`examples/showcase/face.yaml`](../../examples/showcase/face.yaml) — two `style: arc` battery progress rings.
- [Placement: `at:` and `align:`](placement.md#placement-at-and-align) — the shared alignment rule.
- [Elements](elements.md) — the common keys every element shares (`modes`, `visible`, `static`, `antialias`, `min_1px`, `lint`, `on_hold`).
- [`docs/limitations.md`](../limitations.md) — `SensorHistory`/solar series and `segments`/`scale` progress styles are not implemented.
