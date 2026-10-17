# Build a Garmin watch face from a picture

Instructions for an AI assistant that can **read files**, **run shell
commands** and, ideally, **see images**. Following them turns a picture (a
screenshot, a photo, a mockup, a sketch) or a description into a compiled,
sideloadable Garmin Connect IQ watch face (`.prg`) that looks as close to
the picture as the platform allows.

Nothing here is specific to one model or harness. Where a step needs a
capability you may not have, such as seeing an image, it says so and gives
you the alternative.

---

## What you are doing

A watch face is a YAML file compiled by this repository's tool, `wfb`. You
will:

1. find the tool and check the environment;
2. take the picture apart: every element, its position, size and colour;
3. write the YAML;
4. loop on `wfb validate` until it is clean;
5. **loop on preview-and-compare until the render matches the picture**;
6. compile with `wfb build`, warning-free.

**Step 5 is the job.** A first draft is never right, and it doesn't need to
be. Each round of the loop shows you exactly what you built next to what
you were asked for. Budget **at least four compare rounds**, and keep going
while a round still makes a visible improvement. Iterating is the method,
not a sign that something went wrong.

### The preview is the truth

`wfb preview` draws the face from **the same resolved per-device geometry
the generated Monkey C uses**, in **Garmin's own device fonts** (when
`wfb doctor` reports `Garmin fonts ... previews draw exact glyph shapes`),
snapped to what the panel can show (the **64-colour palette** on a MIP
watch, black and white on an Instinct) and masked to the screen's visible
area: the round dial, or a rectangular or Instinct screen's own outline. A
position, a size, a font's width or a colour that differs between
the picture and the preview **differs on the watch too**. Do not explain a
mismatch away as "preview inaccuracy": fix the design.

What the preview genuinely cannot show:

- **data:** it uses fixed sample readings (10:09:42, 8432 steps, HR 72,
  battery 68 %, Wednesday 3 Sep, metric units; `--units statute` for the
  other). Match the *time* with `--time`; the other
  values will differ from the picture's and that is fine;
- **`complication.*` read by a `text` or `gauge`** shows as absent, graphs
  draw a synthetic curve, and an `icon: {for: weather.condition}` icon
  always draws (rain). A `config: slots:` slot (a `type: data` reading, or
  a gauge or icon with `slot:`) draws its *default* pick with a sample
  reading;
- **fonts the doctor did not find**: those draw in a stand-in face, and
  `wfb preview` prints a warning naming each one. Only then is a glyph-shape
  difference not your design's fault;
- **what a real watch does with a shape.** The preview draws each shape by
  rules measured in Garmin's simulator, not on a watch. They say a
  `filled: false` circle's or an arc's pen **straddles** the radius
  (`radius ± thickness / 2`), so a ring meant to touch the rim needs a
  radius of `100%r` minus half its thickness.

---

## 1. Find the tool and check the environment

From the repository root, `./wfb <command>` always works (it runs the
TypeScript CLI under Node). This document writes `wfb`; substitute your
invocation. If you do not know where the repository is:

```sh
find . ~ /workspace -maxdepth 4 -name wfb -type f -perm -u+x 2>/dev/null | head
```

If `wfb doctor` says something is missing, `./tools/setup-env.sh` in the
repository installs it.

Then run `wfb doctor` and read it:

- **`ready`**: everything works.
- **`partial`**: you can validate and preview but not compile. Say so and
  carry on; only step 6 is affected.
- **`not ready`**: stop and report what it says. **Garmin's device
  definitions cannot be downloaded** (the endpoint needs an interactive
  login), so if they are missing only the person can supply them.

Learn the vocabulary from the tool, not from memory:

```sh
wfb sources            # every data source you may bind (its type, whether it can be absent), and the icon names
wfb devices            # the watches you may target: screen size, shape, display, colours
wfb fonts <device>     # that watch's system fonts (with pixel heights) and vector faces
wfb series             # what a graph may plot
wfb complications      # what on_hold: may open
wfb new --list         # starting templates
wfb help <command>     # any command's full flags
```

> **Never bind a data source that `wfb sources` does not list.** An
> invented path such as `weather.temp` is the one mistake the tools cannot
> repair for you.

**The design format is format 2** (`format: 2` on the first line). It is
the only one the compiler reads. A spelling you remember from elsewhere
(`- id:` element lists, `type: shape`, `type: progress`, `value:` plus
`format:` on text, `palette.x`, `when_absent:`, `vertical_align:`,
`modes:`, `absent: "--"`, `outline: color.x`, `icon: "U+F21E"`) is an
error, and the error names what to write instead. There is no migration
tool: a `format: 1` file is rewritten by hand, by changing the first line
to `format: 2` and fixing what each error names.

---

## 2. Take the picture apart

**If you can see images**, look at the picture and write an inventory
before any YAML. For each visible thing: what kind of element it is, where
its centre is, how big it is, its colour, and what it shows.

**If you cannot see images**, say so plainly and ask for a description. Do
not guess at a picture you cannot see.

### Measure, don't eyeball

Work in **`%r`, percent of the dial's radius**, with the dial centre at
(0, 0), `dx` positive right and `dy` positive **down**. For a picture of a
round face, find the dial circle (the visible screen, not the bezel or the
background around it) and convert any pixel `(x, y)` to

```
dx = (x - cx) / R * 100 %r        dy = (y - cy) / R * 100 %r
```

where `(cx, cy)` is the dial centre and `R` its radius in the picture's
pixels. On a **rectangular or Instinct screen**, `%r` is half the *shorter*
side, the origin is still the screen's centre, and `%` is a fraction of the
screen per axis (width across, height down); `wfb devices` gives each
screen's size in pixels. If you can run Python, **measure the picture with Pillow** rather
than estimating: sample colours, scan a row or a ray from the centre for
where ink starts and stops, find the extent of a block of text. A minute of
measuring saves three rounds of nudging. For example, scanning outward along
12 o'clock gives the inner and outer radius of the top tick, and the widest
run of dark pixels across it gives its width.

**Which watch is it?** A round dial fits the default targets. A square or
rectangular screen is a Venu Sq/X1 class watch, and a squarish screen with
cut corners and a small round window top right is an **Instinct**
(semi-octagon, black and white only). Target a watch of the picture's own
shape (`wfb devices` lists each one's `shape`), and say which you chose.

**What is the screen?** Decide before measuring. A screenshot's whole
round area is the screen. A photo or render of a watch also shows a case,
bezel or strap that is *not* on the display: measure `R` from the display
circle alone, pass the same circle to `face-compare.py --crop`, and do not
draw the bezel. If you cannot tell, treat what is inside the outermost ring
as the screen and say so.

**Read the time off the picture** whenever it shows hands or digits, and
render at that time (`--time`), or every hand comparison is noise. On the
watch the **minute hand jumps once a minute** (it points at `minute × 6°`,
ignoring seconds), the hour hand moves each minute, and the second hand
jumps each second. So measure each hand's angle clockwise from 12 and take
`minute = floor(angle / 6)`, `second = round(angle / 6)`, then check the
hour hand agrees (`(hour % 12) × 30° + minute × 0.5°`). A picture whose
minute hand sits between two marks was drawn with a sweeping hand; the
nearest whole minute *below* is as close as the watch can get.

**Every hand has a pointing end, and a hand read from the wrong end is 180°
out.** The pointing end is the long arm; a tail, counterweight or short
stub sits behind the axis. A disc or lollipop on a second hand (a railway
clock's) is on the *pointing* end, not the counterweight. Decide which end
points before you read the angle, and author that end at negative `dy`. A
hand drawn backwards at a time read backwards matches the picture exactly
in that one frame and is wrong in every other, so no comparison against the
picture can catch it. The direction check in step 5 does.

Angles run **clockwise from 12 o'clock**: `0deg` top, `90deg` 3 o'clock,
`180deg` bottom. A ring with a gap at the bottom typically starts near
`210deg` and sweeps about `300deg`.

Something placed round the dial (an icon at 2 o'clock, a reading along the
rim) is easiest measured **polar**: its angle from 12 and its distance from
the centre, written straight into `at: { anchor: center, angle: 60deg,
radius: 80%r }`, rather than converted to `dx`/`dy`.

### Map what you see onto element types

| You see | Use | Chapter in `docs/guide/` |
|---|---|---|
| any text, digital time, date, a number | `text` with a `text:` template, `"{time.clock:%h:%M}"`, several readings allowed (`"{heart_rate.current:d} / {activity.steps:d}"`); a `face:` font plus `curve:` for rotated or curved text | `text.md`, `fonts.md`, `data.md` |
| a sunrise time, recovery hours, a race time, a pace | `text` with a duration spec on a number of seconds (`"{complication.sunrise:%h:%M}"`, `%-H:%M:%S`, `"{…:%-M:%S}{unit}"`) | `data.md` |
| a distance, temperature, elevation or speed with its unit | `text` with `units: auto` and `{unit}` in the `text:` template | `data.md` |
| outlined or hollow digits, a halo round text or a shape, hands parted by a thin gap | `outline: {color:, width:}` on the element (text, icon, shape, hands, pattern, `arc`/`bar`/`needle` gauge, or a whole group) | `outlines.md`, `text.md` |
| rectangle, card, pill, disc, ring, wedge, divider | `type: rectangle`, `circle`, `ellipse`, `polygon`, `line` or `arc` (a pill is a `rectangle` with `corner_radius:`) | `shapes.md` |
| a goal ring or bar that fills | `gauge` (`style: arc` or `bar`) | `progress-and-graphs.md` |
| a ring or bar of separate cells, some lit | `gauge` with `style: segments` | `progress-and-graphs.md` |
| coloured zones with a dot at the value | `gauge` with `style: scale` | `progress-and-graphs.md` |
| a gauge needle driven by a reading (battery, HR) | `gauge` with `style: needle` | `progress-and-graphs.md` |
| a line, area or bar chart | `graph` | `progress-and-graphs.md` |
| a small symbol (heart, steps, battery, weather) | `icon` | `icons.md` |
| a symbol turned to stand along the bezel | `icon` with `rotate:` (any angle, clockwise; baked already turned, so it draws on every watch) | `icons.md` |
| a reading set round the rim, its icon turned beside it | a `text` (fixed reading) or `type: data` (a wearer's slot) with `curve: {style: radial, angle:, radius:}` in a `face:` font; on `data`, `icon: {position: left\|right}` turns the icon with the run | `text.md`, `configuration.md` ("A curved reading") |
| analog hands | a `resources: {hand_sets:}` entry plus a `type: hands` element with `set:` | `analog-hands.md` |
| ticks, indices, numerals round a dial, a row or grid of dots | `pattern` (`radial`, `linear` or `grid`) | `patterns.md` |
| a wearer-selectable data spot | a `config: {slots:}` entry, drawn by `type: data` (the reading), a `gauge` with `slot:` (filled against the pick's own scale) and an `icon` with `slot:` (the pick's glyph), grouped with `on_hold: auto` | `configuration.md`, `icons.md` |
| a whole different layout per variant (analog vs digital) | `layouts:` picked by `config: {style:}` entries | `styles-and-layouts.md` |
| a gauge or number in an Instinct's small round window | any element at `at: { anchor: subscreen }` | `placement.md` |
| several things that move together | `group` | `elements.md` |
| a colour or visibility that follows a reading (red HR above 150) | a `?:` expression, or a rule list `[{when:, value:}, …, {else:}]` | `data.md` ("Rules") |
| one element that must sit differently, take another colour or hide on one watch or screen shape | `overrides:` on the element, keyed by device id, `shape:…` or `display:…` | `placement.md` |

Anything that never changes (background, ticks, printed numerals, fixed
labels) belongs in **`static:`**: it is drawn once and blitted each frame.

**Inventory the small things too**, because they are the ones a first draft
drops: a centre hub or cap over the hands (a `type: circle` element placed
*after* the `type: hands` element), a hand's tail or counterweight, a
second tick at 12, a date window's frame, a thin separator line. Zoom into
the centre and the rim of the picture before you write YAML.

### Match the typeface

Run `wfb fonts <device>` and compare the picture's lettering with what is
listed:

- a **system font** (`font: FONT_SMALL`) is the cheapest, and its height is
  fixed per device (the table gives it). Pick the one whose line height
  matches the picture's text;
- a **vector face** (`resources: {fonts: {x: {face: [RobotoCondensedBold],
  size: 8%r}}}`, used as `font: font.x`) scales to any size and is the only
  way to rotate or curve text (a `text`, or a slot's `type: data` reading).
  The three default targets all have vector faces, but only about a third
  of all watches do: list a fallback face (`face: [BionicSemiBold,
  RobotoCondensedBold]`), and on a target with none the build fails unless
  the element or font sets `unsupported: hide`. An *icon* needs none of
  this: `rotate:` turns it on every watch;
- a **baked TTF** (`resources: {fonts: {x: {source: assets/Font.ttf, size: 20%r}}}`)
  matches a distinctive typeface exactly. A font needs a file the repository
  has or the person supplies; copy one into the face's own `assets/`
  (`examples/dashboard/assets/` has ChivoMono, `examples/analog-custom/assets/`
  Dynalight, `ts/templates/assets/` the templates' fonts). Use
  `monospace: true` for a clock so it does not jitter.

A font only one text uses can be written on that text instead of under
`resources:`: `font: {source: assets/Font.ttf, size: 20%r}`, the same keys.

Lettering with a contrasting edge, or hollow digits, is any of the three
fonts plus **`outline:`**, a ring round the glyphs (see rule 14).

### Ask, once, only what the picture cannot tell you

A picture cannot say what each number measures, what a ring's goal is,
what to show when a reading is missing, or which watches to build for. Put
your interpretation and a proposed default for each open point in **one
numbered message**. Defaults to propose: the design's shown colours
snapped to the palette, `%h` for the hour (follows the watch's 12/24-hour
setting), `absent: {text: "--"}` for a lone reading, `absent: hide` inside a
cluster, and targets `fenix8solar47mm, fenix8solar51mm, fr955`
for a round picture (a watch of the picture's own shape otherwise).

**If the person says to use your judgement, or gave no room for questions,
do that** and list the assumptions you made in your final report.

Reproduce the *style and layout*. Leave out other companies' logos and
wordmarks unless the person says they own them; a plain dial, or the face's
own name, goes in their place.

---

## 3. Write the design

Start from a template, which is already correct, so you edit rather than
invent:

```sh
wfb new "Their Face" -t analog -o their-face/face.yaml    # pick the closest template
wfb new --list                                            # all of them
```

| Template | Starts you with |
|---|---|
| `dashboard` (the default) | the time, a goal ring, two data clusters, a battery bar |
| `minimal` | a background and the time |
| `analog` | a three-hand dial: ticks, twelve numerals, a date window |
| `navy_classic` | a dress dial: polygon hands, batons, a day/date window at 3 |
| `sport` | the time, a heart-rate graph, four readouts, distance in the wearer's units |
| `gauge` | a battery needle gauge across the top half, the time below it |
| `calendar` | the time over a month of dots, today lit |
| `themed` | light/dark schemes, accent and data colours, two complication slots |
| `showcase` | three layouts switched by Styles: analog, digital dashboard, roman dial |
| `amoled` | an AMOLED target with a sparse always-on frame |
| `palette` | all 64 MIP colours as named swatches |

`wfb new --list` is the current list; trust it over this table.

Then study the example closest to the picture before writing much. They
are known-good and warning-free:

| Picture looks like | Read |
|---|---|
| analog dial with hands, ticks, numerals | `examples/analog-custom/face.yaml`, `examples/features/analog/face.yaml`, `examples/features/patterns/face.yaml` |
| dense digital face with data clusters, arcs | `examples/showcase/face.yaml`, `examples/features/align/face.yaml` |
| gauges, segmented rings, zone scales | `examples/features/gauge/face.yaml`, `examples/features/progress/face.yaml` |
| rotated or curved text | `examples/features/vector-text/face.yaml` |
| graphs | `examples/features/graph/face.yaml` |
| an Instinct: black and white, the subscreen window | `examples/features/instinct/face.yaml` |
| every shape | `examples/features/shapes/face.yaml` |
| outlines, rings round hands and ticks | `examples/features/outline/face.yaml`, `examples/features/rings/face.yaml` |
| a grid of dots or cells | `examples/features/grid/face.yaml` |
| readings, rings and icons round the bezel, a turned icon | `examples/features/curved-slot/face.yaml` |
| wearer-picked data spots, gauges on them | `examples/features/slots/face.yaml`, `examples/features/slot-gauge/face.yaml` |
| colour or layout variants | `examples/features/styles/face.yaml`, `examples/features/config/face.yaml` |
| distances and temperatures in the wearer's units | `examples/features/units/face.yaml` |
| an AMOLED watch's always-on frame | `examples/features/aod/face.yaml` |
| earlier output of this skill, from a photo | `examples/generated_by_skill/` (`navy-classic`, a dress dial; `trail-utility`, a digital sports face; `red-tactical`, a red tactical face from a render of a fēnix 8), with the prompts in `prompts.md` |

### Rules that otherwise cost you a round

1. **Elements are a mapping keyed by id**, under `static:`, `elements:` and
   a group's `children:`: `clock: {type: text, ...}`, never a `- id:` list.
   The key *is* the id; YAML order is draw order.
2. **Every length that should scale is `%r`.** `px` is the same pixel count
   on every watch; use it only for deliberate hairlines (`thickness: 2px`).
   A bare number is `px`. `%` is of the *parent box* (the screen, or a
   group), per axis.
3. **Every reading can be absent**, so a binding to a nullable source
   (`wfb sources` marks them) needs `absent:`, one of three shapes:
   `hide`, `{text: "--"}` (drawn in its place), or `{value: <expression>}`
   (substituted into the placeholder). A bare string (`absent: "--"`) is
   an error. A nullable `color:` or `max:` needs `absent:` too. On a
   `gauge`, `absent: hide` still draws the track and leaves out only the
   fill, and `{value:}` is the fill fraction (0.0-1.0); use `visible:` to
   hide it whole.
4. **Colours: each channel is `00`, `55`, `AA` or `FF`**, or the MIP panel
   dithers it. Snap every colour you measured to the nearest legal one,
   declare it in `resources: {palette:}` and reference it as
   `color.<name>` (the one colour namespace: palette entries and theme
   roles alike). On an **Instinct** (2 colours) only `#000000` and
   `#FFFFFF` are safe (`palette-mono` warns on anything else): turn the
   picture's shades into black-or-white shapes, not greys.
5. **Text is one `text:` template**: literal text around
   `{expression:spec}` placeholders. The time is `text: "{time.clock:%h:%M}"`,
   a date `"{date.today:%a %e}"`, a number `"{activity.steps:d}"`, a label
   `"STEPS"`. A time value needs a spec in its placeholder. Text outside the
   braces is drawn as written, so `"%H:%M"` without braces draws those five
   characters. Several placeholders in one text are fine
   (`"{heart_rate.current:d} bpm / {activity.steps:d}"`); the text is then
   absent when any reading is, and `absent: {value:}` and `units:` are
   errors beside them (each speaks of one reading). A literal brace is
   written twice (`"{{"`). A ternary in a placeholder goes in parentheses.
   A text is one line: draw each line as its own element.
6. **An arc is a stroke**: `radius`, `thickness` (pen width), `start_angle`,
   `sweep`. There is no filled arc, no round cap, no gradient. A solid wedge
   is a `polygon`; a disc is a `circle`.
7. **A gauge's `style: arc` and `style: bar` take different keys.** An arc
   needs `radius`/`thickness`/`start_angle`/`sweep`, a bar needs `size`.
   `segments` (`count:`, `gap:`) and `scale` (`bands:`) take either track.
   A `needle` takes neither: its `needle:` is parts keyed by id, authored
   like a hand's (rule 10), about `at:`, turned to
   `start_angle + fraction × sweep`. A graph's span is an object:
   `range: {duration: 4h}` or `range: {samples: 24}`.
8. **A font or icon `size:` is `px` or `%r` only.** No bare number, no
   `scale:`.
9. **Icons:** `icon: <name>` for a catalogue name (`wfb sources` lists
   them), `icon: {codepoint: "U+XXXX"}` for any other Nerd Fonts glyph,
   `icon: {for: weather.condition}` for a glyph chosen by the weather, or,
   instead of `icon:`, `slot: <name>` for the glyph of whatever the wearer
   picked in that `config: slots:` slot (its `on_hold:` is then `auto`
   only). `rotate: -46deg` turns any of them clockwise from upright.
   Never paste a raw character. Never use an icon for something it does not
   mean.
10. **Hand, needle and pattern parts are drawn at 12 o'clock with the axis
    at the origin**, so a tip is at a *negative* `dy`. `parts:` is a mapping
    keyed by id, like elements (`parts: {blade: {type: polygon, ...}, hub:
    {type: circle, ...}}`), drawn in order. Each part names its own `type:`
    (`polygon`, `rectangle`, `line`, `circle`; a pattern also takes `arc` and
    `text`). Their lengths are `px`/`%r`, no `anchor:`. A symmetric polygon
    lists one half with `mirror: x`. A radial pattern's spacing is
    `step_angle:` (default `360deg / count`); a linear or grid one's is
    `step: {dx, dy}`. A pattern of 60 ticks with `skip_every: 5` leaves room
    for 12 hour ticks drawn by a second pattern.
11. **`align:` says which point of the element's box sits on `at:`**: one
    of the nine anchor names, `top_left`, `top`, `top_right`, `left`,
    `center` (the default), `right`, `bottom_left`, `bottom`,
    `bottom_right`. There is no separate vertical key. Polygons, lines,
    patterns and hands take no `align:`.
12. **Draw order is document order.** `static:` content is always drawn
    first. A pin that sits over the hands is a `type: circle` after the
    `type: hands` element.
13. **`antialias: true` on a shape, pattern, hands, gauge or graph warns
    `antialias-dither` on a 64-colour MIP panel**: the soft edge is
    dithered. Leave it off unless the picture's smooth edges matter more
    than the grain, and then accept the warning with a `lint:` reason. On a
    `resources: {fonts:}` entry it is free and usually looks better. A
    face-wide default goes in `defaults: {antialias:}`.
14. **`outline:` draws a ring round an element**: one object,
    `outline: {color: color.x}` (1 px) or `{color: color.x, width: 2}`
    (1-3 px). A bare colour and `outline: none` are errors; no key means no
    ring. It goes on text, icons, shapes, `hands` (each hand ringed whole),
    a `pattern` (each copy), an `arc`, `bar` or `needle` gauge, a pattern's
    `type: text` part, or a whole `group` (round its members together); not
    on a single hand or needle part, a `data`, a `graph` or a
    `segments`/`scale` gauge. A ring in the background colour parts
    overlapping hands. On text the interior is then painted in the
    element's own `color:`, **over** whatever is underneath: there is no
    transparency. For hollow digits, make `color:` the exact palette entry
    of the background beneath them, or `text-outline-interior` warns.
15. **Not available**: `image` and `raw` elements, transparency,
    animation, text on several lines, and taps or swipes (a face gets only
    touch and hold, via `on_hold:`). There are no wearer settings beyond
    `config:` (no on/off switches, no choice lists of your own). Format 2
    reserves some vocabulary that is not built yet (`components:` with
    `use:`/`with:`, `effects:` such as a drop shadow, a `data` element's
    `parts:`); writing it is a friendly "not implemented" error.
    `docs/limitations.md` §2 is the full list. If the picture needs
    something missing, say so and use the closest thing that exists (a drop
    shadow is a second, offset copy drawn first).
16. **`anchor: subscreen`** (Instinct 2/2X/3 Solar 45mm/E 45mm) goes on a
    top-level element's own `at:`, and inside it `%` is of the 62 px window;
    `%r` is still the whole screen's. A target without the window is a build
    error unless that element sets `unsupported: hide`.
17. **`sleep_update: true`** also redraws an element every second while a
    MIP watch sleeps (a seconds readout). Everything else redraws once a
    minute asleep. Leave it off unless the picture needs it: it costs
    power budget, and it is a build error on an AMOLED target.

`wfb schema` prints the normative definition; `docs/guide/` explains every
key with examples. `docs/README.md` is the index.

### Wearer choices: `config:`

If the picture comes with colour variants, or a data spot the wearer should
pick, that is `config:` (`docs/guide/configuration.md`,
`styles-and-layouts.md`; `wfb new -t themed` starts one). Colour variants
are `theme: {schemes:}` whose roles are read as `color.<role>` (a variant
scheme can write `base: <scheme>` and list only the roles it changes),
picked through `config: {style:}` entries (a style can also pick a whole
`layouts:` entry, for variants that differ in more than colour); the accent
and data colours are `config: {accent_color:, data_color:}` (read as
`color.accent` and `color.data`); a data spot is a `config: {slots:}` entry
drawn by a `type: data` element with `slot: <name>`. A fēnix 8 edits it in
Garmin's own face editor; an fr955 gets the same choices in a generated
settings menu, where a slot's optional `label:` is its title. You design it
once for both.

A slot can be drawn in up to three pieces that all follow the wearer's
pick: the reading (`type: data`, optionally with `curve:` round the rim),
a ring or bar (`type: gauge` with `slot:`, filled against the pick's own
scale and hidden for a pick with none) and the glyph (`type: icon` with
`slot:`, placed and turned on its own). Put the pieces in a `group` with
`on_hold: auto`, and holding anywhere in the group opens the pick's glance:

```yaml
config:
  slots:
    left: { default: steps, choices: [steps, floors_climbed, body_battery, stress] }
elements:
  left_slot:
    type: group
    size: { width: 50%, height: 100% }
    at: { anchor: left }
    align: left
    on_hold: auto                    # follows the one slot inside the group
    children:
      left_ring:  { type: gauge, slot: left, style: arc, at: { anchor: right }, radius: 93%r, thickness: 4%r,
                    start_angle: 360deg, sweep: -180deg, color: color.accent, track_color: color.dim, absent: hide }
      left_glyph: { type: icon, slot: left, size: 12%r, rotate: -58deg,
                    at: { anchor: right, angle: -58deg, radius: 80%r }, color: color.accent }
      left_value:
        type: data
        slot: left
        font: font.reading           # a face: font, as curve: requires
        at: { anchor: right }        # the group's right edge is the dial's centre
        curve: { style: radial, angle: -50deg, radius: 80%r }
        align: left                  # the run starts at -50deg and runs clockwise
        color: color.fg
        absent: { text: "--" }
```

On a radial reading the icon can also be the reading's own: `icon: {size:
12%r, position: left}` (or `right`; `top`/`bottom` are errors) stands it
just before (after) the run, turned to the circle there.
`examples/features/curved-slot/face.yaml` is the full example.

### AMOLED targets: the always-on frame

`wfb devices` lists each watch's `display`. The default targets are MIP.
If the person names an **AMOLED** watch (`fenix847mm`, `epix2`, `venu`, …),
two things change:

- `sleep_update: true` is a **build error** there: AMOLED has no partial
  updates.
- While asleep the watch draws an **always-on (AOD) frame**, and a design
  with nothing in it warns `aod-empty`. Nothing is drawn there unless it
  says so: an element's `aod:` block puts it in the frame, restyled with
  its own keys (overrides on the same design, not a second layout).
  `aod:` is one block everywhere: on an element, on a group, and in
  `defaults:` for the face-wide `visible`, `dim`, `mask` and `lint`.

```yaml
defaults:
  aod:
    dim: 0.6                         # scale every colour the AOD frame draws
elements:
  clock:
    type: text
    text: "{time.clock:%h:%M}"
    font: font.clock
    color: color.fg
    aod:                             # this element shows in AOD, restyled
      color: color.bg                # hollow digits: the ring is the only ink
      outline: { color: color.dim, width: 2 }
  date:
    type: text
    text: "{date.today:%a %e}"
    font: FONT_TINY
    color: color.fg
    aod: {}                          # shown in AOD as it is (`aod: {visible: false}` hides it)
```

Garmin's rule is under 10 % of pixels and luminance lit, and
`aod-burn-in` checks it against the rendered frame. Show the time and
little else: hollow or thin digits, no filled areas. Check the frame with
`wfb preview --aod` (it applies the moving 2×2 pixel mask the watch uses,
so only one pixel in each 2×2 tile lights: dotted, on purpose). If the picture itself *is* an always-on
screenshot, compare against it with `face-compare.py --aod`. The full
reference is `docs/guide/always-on-display.md`.

---

## 4. Validate

```sh
wfb validate their-face/face.yaml
```

Fix what it reports and run it again. The messages name the line, the
column and usually the exact fix (`did you mean`, `nearest legal colour`,
`choose one of`). Three or four rounds from a first draft is normal. Fix
the warnings too: `safe-area` and `off-screen` mean something is under the
bezel, and `text-overflow` checks the *widest* value a binding can
produce, not today's. A warning you keep on purpose gets
`lint: {allow: [<code>], reason: "..."}` on that element.

---

## 5. The feedback loop: compare, fix, repeat

Each round:

```sh
python3 skills/face-compare.py <picture> their-face/face.yaml \
    -d fenix8solar47mm --time <HH:MM:SS shown in the picture> \
    [--crop L,T,R,B] [--zoom centre|worst|<region>] -o build/compare/round-<n>.png
```

It renders the preview, crops the picture to the screen's shape (a square
for a round dial; or to `--crop`, the screen's pixel box, when the picture
has a margin, a bezel or a strap), scales both to the same size, masks both
to the visible area and writes one sheet:
**target | preview | 50/50 overlay | difference heat map**. It prints a
difference score (0 = identical) for the whole dial and for each ninth of it.
`--zoom <region>` adds that region of both images blown up 3x; use
`--zoom centre` at least once (hubs and hand tails live there) and
`--zoom worst` when the grid points somewhere you can't see a problem.

**Get the crop right first.** If the overlay shows two dials of different
sizes or offset centres, every later comparison is noise. Pass `--crop` so
the picture's *screen* fills the box exactly: the dial circle on a round
face, the display's rectangle otherwise.

Then **look at the sheet** (open the PNG) and work through this list in
order, biggest error first:

1. **Missing or extra elements.** Anything in the picture not in the
   preview, or the reverse.
2. **Position.** In the overlay, a misplaced element shows twice. Measure
   the offset and correct the `%r` value; do not nudge by feel.
3. **Size and proportion.** Tick lengths and widths, hand lengths, ring
   radius and thickness, text height. Is the time as dominant as intended?
4. **Colour.** Compare against the palette-snapped colour, not the
   picture's exact shade.
5. **Typeface and weight.** Choose a closer font or size.
6. **Small detail.** Tails, counterweights, hubs, gaps, alignment of
   labels. Go back to your inventory and tick off each item against the
   zoomed panels; an element missing from both the inventory and the
   preview is invisible to every other check.

Change a few things per round, then compare again. **Keep a short log** of
each round: the score, what you changed, and what still differs. The score
should fall; if a change raised it, look at why before keeping it. The
heat map shows remaining differences as bright shapes; a bright *outline*
round an element means it is slightly off in place or size, a bright
*solid* shape means it is missing or the wrong colour.

**Check hand direction at a second time** once the hands match, because a
match at one time proves nothing about the others:

```sh
wfb preview their-face/face.yaml -d fenix8solar47mm --time 03:00:15 -o build/compare/direction
```

The hour hand must point at 3, the minute hand at 12 and the second hand at
3, each by its pointing end (disc, arrow, long arm). If a hand points the
other way, it was authored backwards: flip the signs of its parts' `dy`
and re-read the picture's time from the correct end.

**Build a throwaway calibration face** when you are unsure how a key
renders (how thick a `2px` line looks, where an outline lands, how wide a
font's digits are): a few elements in a scratch file, previewed and
measured, costs less than a round of guessing on the real design.

**Stop** when no remaining difference is fixable within the format: what is
left is sample data, a typeface you cannot get, or a platform limit (no
alpha, 64 colours, no round caps). A score of zero is not the target; a
picture that a person would call the same face is.

**If you cannot see images**, you can still use the scores and the grid,
but tell the person where the sheets are and ask them to look before you
claim the design matches.

Also preview every target once at the end (`wfb preview face.yaml`, output
in `build/preview/`): the 51 mm fēnix has a bigger screen, and `%r` should
keep it in proportion. A system font does *not* scale with `%r`, so on a
target of another size or shape check that text still fits its space.
Where one watch or screen shape still needs an element moved, recoloured or
hidden, give that element `overrides:` for it rather than moving it for
every watch.
`wfb preview face.yaml --skin` sets each render inside the watch's own
simulator image, the best picture to show the person at the end.

---

## 6. Compile

```sh
wfb build their-face/face.yaml
```

This writes one signed `.prg` per target to `build/<name>/` and reports the
measured memory against **each device's own limit** (it varies by device;
do not quote 128 KB for everything). **The bar is warning-free**, not
merely a successful build. To install, copy the `.prg` to the watch's
`GARMIN/APPS/` folder over USB.

**You are done when** the build is warning-free, the hands pass the
direction check, the last compare sheet
matches the picture as closely as the platform allows, and you have told
the person: where the design and the `.prg` files are, the memory figures,
the compare log (first and last score), the assumptions you made, and every
difference you could not remove and why.

---

## Quick reference

```yaml
format: 2
face:
  id: <uuid>                      # `wfb new` mints one; never copy another face's
  name: My Face
  version: 1.0.0

build:
  targets: [fenix8solar47mm, fenix8solar51mm, fr955]

resources:
  palette:                        # every channel 00 / 55 / AA / FF
    bg: "#000000"
    fg: "#FFFFFF"
    accent: "#FF5500"
  fonts:                          # optional
    clock: { source: assets/ChivoMono-Bold.ttf, size: 30%r, monospace: true, antialias: true }
    dial:  { face: [RobotoCondensedBold], size: 8%r }        # device vector face
  hand_sets:                      # optional; each drawn at 12 o'clock
    main:
      hour:
        color: color.fg
        parts:
          blade: { type: rectangle, at: { dy: -20%r }, size: { width: 6%r, height: 55%r } }
      minute:
        color: color.fg
        parts:
          blade: { type: polygon, mirror: x, points: [{ dx: -3%r, dy: 15%r }, { dx: -2%r, dy: -88%r }] }
      second:
        color: color.accent
        parts:
          needle: { type: line, at: { dy: 20%r }, to: { dy: -85%r }, thickness: 2px }
          hub:    { type: circle, radius: 3%r }

static:                           # drawn once, blitted each frame
  background:
    type: rectangle
    at: { anchor: center }
    size: { width: 100%, height: 100% }
    color: color.bg
  minute_ticks:
    type: pattern
    pattern: radial
    at: { anchor: center }
    count: 60
    skip_every: 5
    color: color.fg
    parts:
      tick: { type: line, at: { dy: -94%r }, to: { dy: -88%r }, thickness: 2px }
  hour_numerals:
    type: pattern
    pattern: radial
    at: { anchor: center }
    count: 12
    color: color.fg
    parts:
      numeral: { type: text, text: "{(copy + 11) % 12 + 1}", font: FONT_SMALL, at: { dy: -75%r } }

elements:
  clock:
    type: text
    text: "{time.clock:%h:%M}"
    font: font.clock
    at: { anchor: center, dy: -10%r }
    color: color.fg
  date:
    type: text
    text: "{date.today:%a %e}"
    font: FONT_TINY
    at: { anchor: center, dy: 25%r }
    color: color.fg
  steps_ring:
    type: gauge
    style: arc
    value: activity.steps
    max: activity.step_goal
    at: { anchor: center }
    radius: 90%r
    thickness: 3%r
    start_angle: 210deg
    sweep: 300deg
    color: color.accent
    track_color: color.bg
    absent: hide
  hr:
    type: group
    at: { anchor: center, dy: 45%r }
    size: { width: 40%r, height: 12%r }
    on_hold: heart_rate
    children:
      hr_icon:  { type: icon, icon: heart, size: 9%r, at: { anchor: left }, align: left, color: color.accent }
      hr_value:
        type: text
        text: "{heart_rate.current:d}"
        font: FONT_TINY
        at: { anchor: right }
        align: right
        color: color.fg
        absent: { text: "--" }
  battery:
    type: text
    text: "{system.battery:d}%"
    font: FONT_TINY
    at: { anchor: center, dy: -45%r }
    color:                        # a rule list: the same as "system.battery < 20 ? color.accent : color.fg"
      - { when: system.battery < 20, value: color.accent }
      - { else: color.fg }
  hands:
    type: hands
    set: main
    at: { anchor: center }
    seconds: awake                # hidden while the watch sleeps
```

`static:`, `elements:`, a group's `children:` and every `parts:` are
mappings keyed by id, as above. `wfb schema` prints the normative definition.

## Errors you will meet

| Message | What to do |
|---|---|
| `'<key>:' is format 1; format 2 writes ...`, `unknown element type 'shape'` | A format 1 habit: write what the note says |
| `this file is format 1, which this compiler no longer reads` | Change it to `format: 2`; each old key is then reported with its replacement, to rewrite by hand |
| `a placeholder is written 'absent: {text: "--"}', not a bare string` | `absent: {text: "--"}` |
| `write 'outline: {color: ...}'`, `'outline: none' is not accepted here` | `outline: {color: color.x}` (add `width:`), or omit the key for no ring |
| `write 'icon: {codepoint: "U+XXXX"}'` | A glyph by code is an object; a bare string is a catalogue name |
| `an angle between copies is written 'step_angle: ...'` | A radial pattern's spacing is `step_angle:`; `step:` is a linear or grid one's `{dx, dy}` |
| `a span of time is written 'range: {duration: ...}'` | `range: {duration: 4h}` or `range: {samples: 24}` |
| `unknown key ('x', 'y' were unexpected)` | Positions go in `at:`, sizes in `size:`; there are no absolute coordinates |
| `... can be absent, so 'absent:' is required` | Add `absent: hide`, or `absent: {text: "--"}` |
| `unknown data source ...` | Use the suggestion; check `wfb sources`. Never invent one |
| `a time value needs a format spec in its placeholder` | `text: "{time.clock:%h:%M}"` |
| `will be dithered` / `palette-dither` | Use the nearest legal colour it names |
| `palette-mono` | An Instinct shows black and white only: use the one it names |
| `... have no subscreen window` | Target only Instincts, or give the element `unsupported: hide` |
| `safe-area` / `off-screen` | Move it inward or shrink it: it is under the bezel (or outside a rectangle's rounded corners, or the Instinct's window) |
| `text-overflow` | The widest value does not fit: smaller font, or more room |
| `'curve:' needs a 'face:' (vector) font` | Rotated or curved text needs a `resources: {fonts:}` entry with `face:` |
| `font-unavailable` | That vector face is missing on a target; add a fallback face to the list, or `unsupported: hide` |
| `'icon:' and 'slot:' both choose the glyph` | An icon takes one: a fixed glyph (`icon:`) or the slot's pick (`slot:`) |
| `'on_hold:' on an icon with 'slot:' only accepts 'auto'` | `on_hold: auto`, or none; a fixed target would disagree with the wearer's pick |
| `a radial reading takes its icon before or after the run` | `icon: {position: left}` or `right` on a radial `data` reading; or a separate `type: icon` with `slot:` and `rotate:` |
| `beside an icon, 'curve: {radius:}' must be px or %r` | Give the curved reading's `radius:` in `%r` |
| `'on_hold: auto' is ambiguous between slots` | A group with `on_hold: auto` holds one slot only: split it into one group per slot |
| `text-outline-interior` | An outlined text's interior paints over something drawn earlier: make its `color:` the palette entry underneath, or move it |
| `... is an AMOLED device and does not support onPartialUpdate` | Drop `sleep_update: true`; the AMOLED sleep frame is `aod:` |
| `aod-empty` | Nothing draws in always-on display on an AMOLED target: give the time an `aod:` block (`aod: {}` shows it as it is) |
| `aod-burn-in` | The AOD frame lights too much: show less, dim it (`defaults: {aod: {dim: ...}}`), use hollow or thinner digits |
| `Invalid device id specified` (build) | Device definitions are missing: run `wfb doctor` |
