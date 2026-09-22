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
snapped to the watch's **64-colour palette** and masked to the round
screen. A position, a size, a font's width or a colour that differs between
the picture and the preview **differs on the watch too**. Do not explain a
mismatch away as "preview inaccuracy": fix the design.

What the preview genuinely cannot show:

- **data:** it uses fixed sample readings (10:09:42, 8432 steps, HR 72,
  battery 68 %, Wednesday 3 Sep). Match the *time* with `--time`; the other
  values will differ from the picture's and that is fine;
- **`complication.*` readings** show as absent, graphs draw a synthetic
  curve, and an `icon_for:` weather icon always draws;
- **fonts the doctor did not find**: those draw in a stand-in face, and
  `wfb preview` prints a warning naming each one. Only then is a glyph-shape
  difference not your design's fault;
- **which side of the radius an outline pen lands on.** The preview draws
  a `filled: false` circle, ellipse or rectangle, and an arc, with the pen
  running *inward* from the declared edge; the linter assumes it straddles
  the edge. What the watch does is unconfirmed. So don't make a design
  depend on a thick outline landing on an exact radius. For a ring that
  must reach the rim, stack two **filled** circles (the ring colour, then
  the dial colour on top, smaller by the ring's width). Filled shapes are
  exact.

---

## 1. Find the tool and check the environment

From the repository root, `./wfb.py <command>` (or `./.venv/bin/python
wfb.py <command>`) always works. This document writes `wfb`; substitute your
invocation. If you do not know where the repository is:

```sh
find . ~ /workspace -maxdepth 6 -name wfb.py 2>/dev/null | head
```

Then run `wfb doctor` and read it:

- **`ready`**: everything works.
- **`partial`**: you can validate and preview but not compile. Say so and
  carry on; only step 6 is affected.
- **`not ready`**: stop and report what it says. **Garmin's device
  definitions cannot be downloaded** (the endpoint needs an interactive
  login), so if they are missing only the person can supply them.

Learn the vocabulary from the tool, not from memory:

```sh
wfb sources            # every data source you may bind, its type, whether it can be absent
wfb devices            # the watches you may target
wfb fonts <device>     # that watch's system fonts (with pixel heights) and vector faces
wfb series             # what a graph may plot
wfb complications      # what on_hold: may open
wfb new --list         # starting templates
wfb help <command>     # any command's full flags
```

> **Never bind a data source that `wfb sources` does not list.** An
> invented path such as `weather.temp` is the one mistake the tools cannot
> repair for you.

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
pixels. If you can run Python, **measure the picture with Pillow** rather
than estimating: sample colours, scan a row or a ray from the centre for
where ink starts and stops, find the extent of a block of text. A minute of
measuring saves three rounds of nudging. For example, scanning outward along
12 o'clock gives the inner and outer radius of the top tick, and the widest
run of dark pixels across it gives its width.

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

### Map what you see onto element types

| You see | Use | Chapter in `docs/guide/` |
|---|---|---|
| any text, digital time, date, a number | `text` (a `face:` font plus `curve:` for rotated or curved text) | `text.md`, `fonts.md`, `data.md` |
| rectangle, card, pill, disc, ring, wedge, divider | `shape` | `shapes.md` |
| a goal ring or bar that fills | `progress` (`style: arc` or `bar`) | `progress-and-graphs.md` |
| a line, area or bar chart | `graph` | `progress-and-graphs.md` |
| a small symbol (heart, steps, battery, weather) | `icon` | `icons.md` |
| analog hands | top-level `hands:` set plus a `type: hands` element | `analog-hands.md` |
| ticks, indices, numerals round a dial, a row of dots | `pattern` (`radial` or `linear`) | `patterns.md` |
| a wearer-selectable data spot | `complication_slot` | `configuration.md` |
| several things that move together | `group` | `elements.md` |

Anything that never changes (background, ticks, printed numerals, fixed
labels) belongs in **`static:`**: it is drawn once and blitted each frame.

**Inventory the small things too**, because they are the ones a first draft
drops: a centre hub or cap over the hands (a `shape: circle` element placed
*after* the `type: hands` element), a hand's tail or counterweight, a
second tick at 12, a date window's frame, a thin separator line. Zoom into
the centre and the rim of the picture before you write YAML.

### Match the typeface

Run `wfb fonts <device>` and compare the picture's lettering with what is
listed:

- a **system font** (`font: FONT_SMALL`) is the cheapest, and its height is
  fixed per device (the table gives it). Pick the one whose line height
  matches the picture's text;
- a **vector face** (`fonts: {x: {face: [RobotoCondensedBold], size: 8%r}}`)
  scales to any size and is the only way to rotate or curve text, but
  exists on only some devices;
- a **baked TTF** (`fonts: {x: {source: assets/Font.ttf, size: 20%r}}`)
  matches a distinctive typeface exactly. A font needs a file the repository
  has or the person supplies; look in `examples/*/assets/` for what is
  already here. Use `monospace: true` for a clock so it does not jitter.

### Ask, once, only what the picture cannot tell you

A picture cannot say what each number measures, what a ring's goal is,
what to show when a reading is missing, or which watches to build for. Put
your interpretation and a proposed default for each open point in **one
numbered message**. Defaults to propose: the design's shown colours
snapped to the palette, `%h` for the hour (follows the watch's 12/24-hour
setting), `when_absent: placeholder` with `"--"` for a lone reading, `hide`
inside a cluster, and targets `fenix8solar47mm, fenix8solar51mm, fr955`.

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
wfb new "Their Face" -t minimal -o their-face/face.yaml   # background and time
wfb new "Their Face" -o their-face/face.yaml              # time, ring, two clusters, battery
```

Then study the example closest to the picture before writing much. They
are known-good and warning-free:

| Picture looks like | Read |
|---|---|
| analog dial with hands, ticks, numerals | `examples/analog-custom/face.yaml`, `examples/features/analog/face.yaml`, `examples/features/patterns/face.yaml` |
| dense digital face with data clusters, arcs | `examples/showcase/face.yaml`, `examples/features/align/face.yaml` |
| rotated or curved text | `examples/features/vector-text/face.yaml` |
| graphs | `examples/features/graph/face.yaml` |
| every shape | `examples/features/shapes/face.yaml` |

### Rules that otherwise cost you a round

1. **Every length that should scale is `%r`.** `px` is the same pixel count
   on every watch; use it only for deliberate hairlines (`thickness: 2px`).
   A bare number is `px`. `%` is of the *parent box* (the screen, or a
   group), per axis.
2. **Every reading can be absent**, so a binding to a nullable source
   (`wfb sources` marks them) needs `when_absent:`: `hide`, `placeholder`
   (with `placeholder: "--"`) or `fallback`.
3. **Colours: each channel is `00`, `55`, `AA` or `FF`**, or the MIP panel
   dithers it. Snap every colour you measured to the nearest legal one,
   declare it in `palette:` and reference `palette.<name>`.
4. **Time needs a time format**: `value: time.clock`, `format: "{:%h:%M}"`.
   Dates: `value: date.today`, `format: "{:%a %e}"`. `text:` is a literal
   string, `value:` is an expression; never put a literal in `value:`.
5. **An arc is a stroke**: `radius`, `thickness` (pen width), `start_angle`,
   `sweep`. There is no filled arc, no round cap, no gradient. A solid wedge
   is a `polygon`; a disc is a `circle`.
6. **`style: arc` and `style: bar` take different keys.** An arc progress
   needs `radius`/`thickness`/`start_angle`/`sweep`, a bar needs `size`.
7. **A font or icon `size:` is `px` or `%r` only.** No bare number, no
   `scale:`.
8. **Icons:** `icon: <name>` for a catalogue name (`wfb sources` lists
   them), or `glyph: "U+XXXX"` for any other Nerd Fonts glyph. Never paste
   a raw character. Never use an icon for something it does not mean.
9. **Hands and pattern parts are drawn at 12 o'clock with the axis at the
   origin**, so a tip is at a *negative* `dy`. Their lengths are `px`/`%r`,
   no `anchor:`. A pattern of 60 ticks with `skip_every: 5` leaves room for
   12 hour ticks drawn by a second pattern.
10. **`align:`/`vertical_align:` say which edge of the element's box sits
    on `at:`**; both default to `center`. `vertical_align` is
    `top`/`center`/`bottom` (no `baseline`). Polygons, lines, patterns and
    hands take neither.
11. **Draw order is document order.** `static:` content is always drawn
    first. A pin that sits over the hands is a `shape: circle` after the
    `type: hands` element.
12. **`antialias: true` on a shape, pattern, hands, progress or graph
    warns `antialias-dither` on a 64-colour MIP panel**: the soft edge is
    dithered. Leave it off unless the picture's smooth edges matter more
    than the grain, and then accept the warning with a `lint:` reason. On a
    `fonts:` entry it is free and usually looks better.
13. **Not available**: `image` and `raw` elements, per-device `overrides`,
    transparency, animation, and taps or swipes (a face gets only touch and
    hold, via `on_hold:`). If the picture needs one, say so and use the
    closest thing that exists.

`wfb schema` prints the normative definition; `docs/guide/` explains every
key with examples. `docs/README.md` is the index.

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

It renders the preview, crops the picture to a square (or to `--crop`, the
dial's pixel box, when the picture has a margin, a bezel or a strap), scales
both to the same size and writes one sheet:
**target | preview | 50/50 overlay | difference heat map**. It prints a
difference score (0 = identical) for the whole dial and for each ninth of it.
`--zoom <region>` adds that region of both images blown up 3x; use
`--zoom centre` at least once (hubs and hand tails live there) and
`--zoom worst` when the grid points somewhere you can't see a problem.

**Get the crop right first.** If the overlay shows two dials of different
sizes or offset centres, every later comparison is noise. Pass `--crop` so
the picture's *screen* circle fills the square exactly.

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
keep it in proportion.

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
format: 1
face:
  id: <uuid>                      # `wfb new` mints one; never copy another face's
  name: My Face
  version: 1.0.0
targets: [fenix8solar47mm, fenix8solar51mm, fr955]

palette:                          # every channel 00 / 55 / AA / FF
  bg: "#000000"
  fg: "#FFFFFF"
  accent: "#FF5500"

fonts:                            # optional
  clock: { source: assets/ChivoMono-Bold.ttf, size: 30%r, monospace: true, antialias: true }
  dial:  { face: [RobotoCondensedBold], size: 8%r }        # device vector face

hands:                            # optional; one named set, drawn at 12 o'clock
  main:
    hour:   { color: palette.fg, parts: [{ shape: rectangle, at: { dy: -20%r }, size: { width: 6%r, height: 55%r } }] }
    minute: { color: palette.fg, parts: [{ shape: polygon, points: [{ dx: -3%r, dy: 15%r }, { dx: -2%r, dy: -88%r }, { dx: 2%r, dy: -88%r }, { dx: 3%r, dy: 15%r }] }] }
    second: { color: palette.accent, parts: [{ shape: line, at: { dy: 20%r }, to: { dy: -85%r }, thickness: 2px },
                                             { shape: circle, radius: 3%r }] }

static:                           # drawn once, blitted each frame
  - id: background
    type: shape
    shape: rectangle
    at: { anchor: center }
    size: { width: 100%, height: 100% }
    color: palette.bg
  - id: minute_ticks
    type: pattern
    pattern: radial
    at: { anchor: center }
    count: 60
    skip_every: 5
    color: palette.fg
    parts: [{ shape: line, at: { dy: -94%r }, to: { dy: -88%r }, thickness: 2px }]
  - id: hour_numerals
    type: pattern
    pattern: radial
    at: { anchor: center }
    count: 12
    color: palette.fg
    parts: [{ shape: text, value: "(copy + 11) % 12 + 1", font: FONT_SMALL, at: { dy: -75%r } }]

elements:
  - id: clock
    type: text
    value: time.clock
    format: "{:%h:%M}"
    font: font.clock
    at: { anchor: center, dy: -10%r }
    color: palette.fg
  - id: date
    type: text
    value: date.today
    format: "{:%a %e}"
    font: FONT_TINY
    at: { anchor: center, dy: 25%r }
    color: palette.fg
  - id: steps_ring
    type: progress
    style: arc
    value: activity.steps
    max: activity.step_goal
    at: { anchor: center }
    radius: 90%r
    thickness: 3%r
    start_angle: 210deg
    sweep: 300deg
    color: palette.accent
    track_color: palette.bg
    when_absent: hide
  - id: hr
    type: group
    at: { anchor: center, dy: 45%r }
    size: { width: 40%r, height: 12%r }
    on_hold: heart_rate
    children:
      - { id: hr_icon, type: icon, icon: heart, size: 9%r, at: { anchor: left }, align: left, color: palette.accent }
      - { id: hr_value, type: text, value: heart_rate.current, format: "{:d}", font: FONT_TINY,
          at: { anchor: right }, align: right, color: palette.fg,
          when_absent: placeholder, placeholder: "--" }
  - id: hands
    type: hands
    hands: main
    at: { anchor: center }
    seconds: awake                # hidden while the watch sleeps
```

Elements may also be written as a mapping keyed by id (`clock: {type:
text, ...}`); it means the same thing. The list form above is what the
schema describes.

## Errors you will meet

| Message | What to do |
|---|---|
| `unknown key ('x', 'y' were unexpected)` | Positions go in `at:`, sizes in `size:`; there are no absolute coordinates |
| `... can be absent, so 'when_absent:' is required` | Add `when_absent: hide`, or a placeholder |
| `unknown data source ...` | Use the suggestion; check `wfb sources`. Never invent one |
| `a time value needs a strftime-style format` | `format: "{:%h:%M}"` |
| `will be dithered` / `palette-dither` | Use the nearest legal colour it names |
| `safe-area` / `off-screen` | Move it inward or shrink it: it is under the bezel |
| `text-overflow` | The widest value does not fit: smaller font, or more room |
| `curve: requires a face: font` | Rotated or curved text needs a `fonts:` entry with `face:` |
| `font-unavailable` | That vector face is missing on a target; add a fallback face to the list, or `if_unavailable: hide` |
| `Invalid device id specified` (build) | Device definitions are missing: run `wfb doctor` |
