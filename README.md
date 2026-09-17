# garmin-wf-builder

Describe a Garmin Connect IQ watch face in one YAML file, and `wfb` builds a
signed `.prg` for each target watch, ready to sideload.

**Targets:** fēnix 8 Solar 47 mm / 51 mm, Forerunner 955. **Distribution:**
personal sideload.

![All five styles of the showcase face](docs/screenshots/showcase-styles.png)

*[`examples/showcase`](examples/showcase/face.yaml): one file, five on-device
styles made from two layouts and three colour schemes.*

This page is a tour by example. Sections 1–10 follow the showcase face, and
section 11 covers features from the other examples. Each snippet sits next to
what it draws. [`docs/format.md`](docs/format.md) is the full reference.

All screenshots come from `wfb preview` on a fēnix 8 47 mm, with sample data at
10:09:42. The preview uses the same resolved geometry as the compiled face, so
positions match the watch. Glyph shapes are approximate, and
[a few data values differ](#preview-caveats). To regenerate the screenshots,
run `./.venv/bin/python tools/readme-shots.py`.

---

## 1. Setup and the loop

```sh
./tools/setup-env.sh                # SDK, developer key, device files, .venv
```

Or use the Docker image: see [`docs/container.md`](docs/container.md). Garmin's
device definitions can't be downloaded without a login, so you supply your own
copy. See [`docs/development.md`](docs/development.md).

```sh
wfb new "My Face"                   # a known-good starting file (--list for templates)
wfb preview my-face.yaml --watch    # PNG re-rendered on every save
wfb validate my-face.yaml           # schema, semantic checks and lints; no SDK needed
wfb build my-face.yaml              # generate Monkey C and compile
wfb sources | series | complications  # what you can bind, plot, and open on hold
```

```
built      showcase-fenix8solar47mm.prg  19,412 B / 131,072 B (14.8%)
built      showcase-fenix8solar51mm.prg  19,418 B / 131,072 B (14.8%)
built      showcase-fr955.prg            19,419 B / 131,072 B (14.8%)
```

**What the build produces** (in `build/<name>/`):

| Output | What it is |
|---|---|
| `<name>-<device>.prg` | the signed face, to copy to `GARMIN/APPS/` |
| `source/*View.mc`, `*Delegate.mc`, `Palette.mc`, … | generated Monkey C, shared by all devices |
| `source-<device>/Layout.mc` | every `%` and `%r` resolved to pixels for that screen |
| `resources-<device>/fonts/` | your TTFs baked to bitmap fonts, holding only the glyphs you use |
| `manifest.xml`, `monkey.jungle` | permissions and API floor, derived from what you bind |
| `runtime-lib/` | only the helper modules the face needs |

The memory figure comes from the compiler's own measurement, not an estimate.
Every watch face gets 128 KB.

## 2. File skeleton

```yaml
format: 1
face: { id: <uuid>, name: Showcase, version: 1.1.0 }
targets: [fenix8solar47mm, fenix8solar51mm, fr955]

fonts:    { ... }   # TTF files -> device fonts
palette:  { ... }   # named colours (MIP: each channel 00/55/AA/FF)
color_scheme: { ... }   # named sets of colour roles: bg, fg, dim, ...
config:   { ... }   # what the wearer can change on the watch
hands:    { ... }   # analog hand sets

static:   { ... }   # drawn once, then copied: backgrounds, cards
elements: { ... }   # redrawn every update
layouts:  { ... }   # alternative static/elements sets, picked by a style
```

You can write element lists as a mapping, where the key is the id (as the
showcase does), or as a list of items that each carry an `id:`. Both mean the
same thing.

## 3. Placement: `at:`, anchors and units

```yaml
date_line:
  type: text
  value: date.today
  format: "{:%a, %e %b}"
  font: FONT_XTINY
  at: { anchor: top, dy: 10% }     # 10 % of the screen height below the top edge
  color: config.colors.dim

weather_icon:
  type: icon
  icon_for: weather.condition_today   # the glyph follows the condition
  size: 16%r
  at: { anchor: top, dy: 20% }
```

![date and weather](docs/screenshots/showcase-header.png)

- `anchor:` can be `center`, `top`, `bottom`, `left`, `right`, or a corner
  such as `top_left`. `dx`/`dy` offset from it. Polar placement works too:
  `at: { anchor: center, angle: 45deg, radius: 27%r }` (§11).
- `%` is a fraction of the parent box: its width for `dx`, its height for `dy`.
  `%r` is a fraction of the screen's **radius**, so a round dial stays round on
  every watch. `px` also works.
- `align:` / `vertical_align:` choose which way a box grows from its point
  (§6, §11).
- A value that is absent (no weather yet) shows `placeholder:`. Here that is
  `--°`.

## 4. Custom fonts and a monospaced clock

```yaml
fonts:
  digitalclock:
    source: assets/ChivoMono-Bold.ttf
    size: 60%r            # scales with each watch's screen
    monospace: true       # "11" and "00" take the same width: no jitter
    antialias: true

elements:
  hours:   { type: text, value: time.hour,   format: "{:02d}", font: font.digitalclock,
             at: { anchor: center, dx: -1%, dy: 7% }, align: right, color: config.colors.fg,
             modes: [active, low_power] }        # keeps ticking while the watch sleeps
  minutes: { type: text, value: time.minute, format: "{:02d}", font: font.digitalclock,
             at: { anchor: center, dx: 1%,  dy: 7% }, align: left,  color: config.accent_color,
             modes: [active, low_power] }
```

![two-tone clock](docs/screenshots/showcase-clock.png)

`FONT_XTINY` … `FONT_NUMBER_THAI_HOT` name the watch's built-in fonts. A
`font.<name>` reference uses one of your own from `fonts:`.

## 5. Data slots, cards and a graph

```yaml
static:
  left_card: { type: shape, shape: rounded_rectangle, corner_radius: 3%r,
               at: { anchor: center, dx: -50%r, dy: -23%r },
               size: { width: 42%r, height: 19%r }, color: config.colors.dark }

elements:
  left_register:
    type: complication_slot          # the wearer picks what it shows
    slot: config.data.left_register
    at: { anchor: center, dx: -50%r, dy: -30%r }
    icon_position: top
    icon_color: config.data_color
    when_absent: placeholder
    on_hold: auto                    # touch and hold opens that complication

  hr_graph:
    type: graph
    series: heart_rate               # `wfb series` lists what can be plotted
    range: 4h
    style: area                      # line | area | bars (§11)
    size: { width: 52%r, height: 17%r }
    color: config.data_color
    on_hold: heart_rate
```

![complication slots and heart-rate graph](docs/screenshots/showcase-registers.png)

## 6. Groups, touch-and-hold, progress bar

```yaml
steps_cluster:
  type: group                        # draws nothing itself; positions its children
  size: { width: 38%r, height: 12%r }
  at: { anchor: top, dy: 75% }
  on_hold: steps                     # one hold target for the whole cluster
  children:
    steps_icon:  { type: icon, icon: steps, size: 9%r, at: { anchor: left }, align: left }
    steps_value: { type: text, value: "activity.steps / 1000.0", format: "{:.1f}k",
                   font: FONT_XTINY, at: { anchor: left, dx: 13%r }, align: left }

steps_bar:
  type: progress
  style: bar
  value: activity.steps
  max: activity.step_goal            # max can be data too
  size: { width: 60%, height: 3%r }
  color: config.accent_color
  track_color: config.colors.dark
```

![icon/value clusters and steps bar](docs/screenshots/showcase-clusters.png)

`value:` takes an **expression**. The compiler turns it into Monkey C, and
nothing is interpreted on the watch. A live watch face gets exactly one
gesture, touch and hold, so `on_hold:` is the only way to interact.

## 7. Conditional colour, `visible:`, arc progress

```yaml
notification_badge:
  type: icon
  icon: notification
  color: "device.notification_count > 0 ? config.accent_color : config.colors.dark"

notification_count:
  type: text
  value: device.notification_count
  visible: device.notification_count > 0

battery_arc_l:
  type: progress
  style: arc
  value: system.battery
  max: 100
  radius: 97%r
  thickness: 3%r
  start_angle: 180deg                # 6 o'clock
  sweep: 30deg                       # a negative sweep mirrors it (battery_arc_r)
```

![status row and battery arcs](docs/screenshots/showcase-status.png)

## 8. Analog: hands and patterns

```yaml
hands:
  classic:
    hour:                            # drawn pointing at 12, axis at (0, 0)
      color: config.colors.fg
      parts:
        - shape: polygon
          points: [{dx: -3%r, dy: 8%r}, {dx: -2%r, dy: -38%r}, {dy: -46%r},
                   {dx: 2%r, dy: -38%r}, {dx: 3%r, dy: 8%r}]
    minute: { ... }                  # rectangle + circle
    second: { ... }                  # line + circles, accent-coloured tip

layouts:
  analog:
    static:
      minute_ticks:
        type: pattern
        pattern: radial
        count: 60
        skip_every: 5                # leave room for the hour ticks
        parts: [{ shape: line, at: { dy: -90%r }, to: { dy: -86%r }, thickness: 1px }]
      hour_numerals:
        type: pattern                # 12 numerals, one element
        pattern: radial
        count: 12
        parts:
          - { shape: text, value: "(copy + 11) % 12 + 1", font: font.dialfont, at: { dy: -78%r } }
    elements:
      analog_hands: { type: hands, hands: classic, at: { anchor: center },
                      seconds: awake, antialias: true }
```

| Awake (`--time 03:41:17`, light style) | Asleep (`--asleep`): no second hand |
|---|---|
| ![analog dial](docs/screenshots/showcase-dial.png) | ![analog asleep](docs/screenshots/showcase-asleep.png) |

The numerals stay upright as they go around the dial. Hands take four part
shapes: `polygon`, `rectangle`, `line` and `circle`. The ticks and numerals
are in `static:`, so the watch draws them once and then copies them.

## 9. On-device configuration: styles, colours, data

```yaml
color_scheme:
  dark:  { label: "Dark",  colors: { bg: palette.black, fg: palette.white, ... } }
  light: { label: "Light", colors: { bg: palette.white, fg: palette.black, ... } }

config:
  style:                             # layout × colour scheme, as named entries
    default: digital_dark
    choices:
      analog_dark:  { label: "Analog · Dark",  layout: analog,  colors: dark }
      digital_dark: { label: "Digital · Dark", layout: digital, colors: dark }
  accent_color: { default: palette.red, choices: [palette.red, palette.lime_green, ...] }
  data_color:   { default: palette.red, choices: [palette.red, palette.magenta, ...] }
  data:
    left_register:
      default: complication.steps
      choices: [complication.steps, complication.heart_rate,
                { type: complication.calories, icon: none }]
    right_register: { default: complication.body_battery, choices: any }
```

![three accent / data colour / slot selections](docs/screenshots/showcase-config.png)

*Left: the defaults. Middle: lime accent, magenta data colour, and the left
slot set to heart rate. Right: magenta accent, amber data colour, and the
right slot set to calories.*

The wearer picks these in the fēnix 8's native face editor, which saves up to
four configurations. The fr955 has no on-device editor, so it always shows the
defaults.

## 10. Lints and suppressions

`wfb validate` and `wfb build` check the design against each device for:
- text overflow
- the round screen's safe area
- contrast
- palette and anti-aliasing dither
- the power cost of low-power updates

Each warning states how confident the check is. When a warning is intended,
keep the design and record why:

```yaml
lint:
  allow: [safe-area]
  reason: "hugs the bezel by design"
```

## 11. More features, from the other examples

### Alignment around a point: [`examples/align`](examples/align/face.yaml)

```yaml
steps_slot:
  type: complication_slot
  at: { anchor: center, angle: 45deg, radius: 27%r }   # polar placement
  align: left              # grow rightwards from the point...
  vertical_align: bottom   # ...and upwards
heart_group:
  type: group
  at: { anchor: center, angle: 135deg, radius: 27%r }
  align: left
  vertical_align: top      # the lower-right readout grows downwards
```

<img src="docs/screenshots/align.png" width="260" alt="align example">

Each diagonal readout sits on a point at the same distance from the centre and
grows away from it, so the four corners stay symmetric whatever their content.
`align:` is `left`/`center`/`right` and `vertical_align:` is
`top`/`center`/`bottom`. Both work on:
- groups, text, progress bars and arcs, graphs, icons and complication slots
- shapes other than `polygon` and `line`
- rectangle, circle and text parts of hands and patterns

### Pattern repeats: [`examples/patterns`](examples/patterns/face.yaml)

```yaml
hour_ticks:
  type: pattern
  pattern: radial
  count: 12
  skip: [0]                          # no tick at 12: a doubled marker goes there
twelve:
  type: pattern
  pattern: linear                    # copies step in a straight line
  count: 2
  step: { dx: 6%r }
week_dots:
  type: pattern
  pattern: linear
  count: 7
  step: { dx: 10%r }
  parts:
    - shape: circle
      radius: 2%r
      color: "copy == (date.weekday + 5) % 7 ? palette.cyan : palette.black"  # today lit
test_visibility:                     # a move-bar meter
  type: pattern
  pattern: linear
  count: 5
  when_absent: hide                  # no move-bar reading: hide the whole row
  parts:
    - { shape: rectangle, size: { width: 4%r, height: 4%r },
        visible: "copy <= activity.move_bar_level - 1" }   # per-copy visibility
```

<img src="docs/screenshots/patterns.png" width="260" alt="patterns example">

A pattern draws one template many times: `radial` turns each copy about the
centre, and `linear` steps it by whole pixels. `copy` is the copy's index. You
can use it in a colour, a part's `visible:`, or a text part's `value:`. Parts
may also be an `arc` centred on the pattern (the slate ring segments).
`start:` rotates the first copy (the orange diagonal triangles).

### Graph styles and series: [`examples/graph`](examples/graph/face.yaml)

```yaml
hr_graph:    { type: graph, series: heart_rate, range: 4h, buckets: 32,
               style: line, thickness: 2px }
steps_graph: { type: graph, series: steps, range: 7d,
               style: bars, bar_width: 6px, min: 0 }
temp_graph:  { type: graph, series: forecast_temperature, range: 24h,
               style: area }
```

<img src="docs/screenshots/graph.png" width="260" alt="graph example">

Four families of series can be plotted:
- heart-rate history
- daily activity (steps, calories, distance, floors, active minutes)
- the hourly forecast
- the daily forecast

The platform keeps pressure, stress and Body Battery history away from watch
faces. The preview draws a stand-in curve, not real data.

### Shapes: [`examples/shapes`](examples/shapes/face.yaml)

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

<img src="docs/screenshots/shapes.png" width="260" alt="shapes example">

The shapes are `rectangle`, `rounded_rectangle`, `circle`, `ellipse`, `line`,
`arc` and `polygon`. Closed shapes can be filled or outlined (`filled: false`
plus `thickness:`). An arc is a stroke only. The platform has no filled arc, no
rounded caps and no gradients.

### Several hand sets and a subdial: [`examples/analog`](examples/analog/face.yaml)

```yaml
hands:
  sport:                   # no `second:` at all: this set never shows seconds
    hour:   { parts: [...] }
    minute: { parts: [...] }
  small_seconds:
    second: { parts: [{ shape: line, at: { dy: 3%r }, to: { dy: -20%r } }] }

layouts:
  classic_generated:
    elements:
      main_hands: { type: hands, hands: classic_generated, at: { anchor: center } }
      small_secs: { type: hands, hands: small_seconds,
                    at: { anchor: center, dy: 45%r } }   # an off-centre axis
```

![analog example styles](docs/screenshots/analog-styles.png)

Each style can use its own hand set. A set can omit any hand, and a `type:
hands` element can sit anywhere, such as a small-seconds subdial at 6 o'clock
(fourth panel).

### Features with no example face yet

- **`antialias:` at every level.** Set it on the face, a group, an element, or
  a font. The nearest setting wins, in either direction. The examples only set
  it per element or per font.
- **`min_1px:`.** Stops a thin relative length (`thickness: 0.4%r`) from
  rounding to 0 px on a smaller screen. It's off by default. You can switch it
  on or off per face, group, element or hand/pattern part. Without it, the
  build warns with `sub-pixel-length`.
  ```yaml
  min_1px: true            # face-wide; a group, element or part can override it
  ```
- **`modes: [always_on]`.** A separate element set for AMOLED watches, which
  can't use low-power updates. The targets here are MIP, so nothing uses it.
- **`seconds:` on the analog dial.** `seconds: awake` (the default) hides the
  second hand while the watch sleeps. `seconds: always` isn't built yet.
- **`wfb new -t <template>`.** Starts from a known-good design (`--list` shows
  the templates).

## Preview caveats

`wfb preview` runs on your computer, with no watch data. It uses sample
values, so a few things look different from the watch:

- **`complication.*` read by a `text` or `progress` element has no sample
  value.** It shows as absent. For example, the showcase's Body Battery
  readout shows `--` right next to a slot showing `62`, and
  [`examples/sun`](examples/sun/face.yaml) renders as a blank screen.
- **An `icon_for:` weather icon always draws.** Weather has no sample value,
  so the readout beside it shows `--°`. On the watch, the icon is hidden when
  there is no weather data.
- **Graphs always draw a synthetic curve**, even for a series whose other
  readings are absent (the forecast).

---

## Further reading

| If you want… | Read |
|---|---|
| every key, rule and default | [`docs/format.md`](docs/format.md), and the schema in [`schema/`](schema/) |
| what the platform will not do, and what isn't built yet | [`docs/limitations.md`](docs/limitations.md) |
| setup details, the generated code, repository layout, tests | [`docs/development.md`](docs/development.md) |
| to run it without installing anything | [`docs/container.md`](docs/container.md) |
| the decisions and why | [`docs/adr/README.md`](docs/adr/README.md) |
| to take over the project | **`CLAUDE.md`** |
