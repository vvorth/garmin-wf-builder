---
name: watchface-from-image
description: Turn a picture of a watch face -- a photo, a mockup, or a crude hand drawing -- into a buildable Garmin Connect IQ design. Use when someone shares an image and wants a watch face like it, or says "build me this watch face", "make a face that looks like this", or asks to design a Garmin watch face at all.
user-invocable: true
allowed-tools:
  - Read
  - Write
  - Edit
  - Bash
---

# Build a Garmin watch face from a picture

You are turning an image into a `wfb` YAML design that compiles to a real watch
face. The image tells you the *layout*. The person tells you what the elements
*mean*. The compiler tells you whether you got it right — and it is unusually
good at this, so **use it constantly rather than trying to be correct in one
shot.**

Work in this order. Do not skip steps 4 and 5.

---

## 0. Check the tool works

```sh
wfb devices          # or: ./wfb.py devices   or: ./.venv/bin/python wfb.py devices
```

That prints the installed device definitions. If it fails, stop and say so — a
design cannot be validated or built without them, and they cannot be downloaded.
Use whichever invocation works for every command below; this document writes
`wfb`.

Then, once, so you are working from the real vocabulary rather than memory:

```sh
wfb sources          # every data source you may bind, with its type
wfb new --list       # the templates you can start from
```

**Never bind a data source that is not in `wfb sources`.** If the person wants
something that is not there, say so plainly rather than inventing a plausible
path.

---

## 1. Read the image

Look at it and write down, for yourself, an inventory of everything visible.
For each item note:

- **what it is** — text, a ring or arc, a bar, an icon, a plain shape;
- **where it sits**, as a fraction of the way from the centre to the edge, and in
  which direction. Do not think in pixels. A sketch has no pixels worth having;
- **how big** it is, in the same proportional terms;
- **what it appears to show** — a number, a time, a label, a fill level.

Read arcs carefully: note where the sweep **starts**, which way it **goes**, and
whether it is a full circle or leaves a gap.

## 2. Propose an interpretation, then ask

**Do not ask twenty open questions.** Show the person your inventory with your
best guess at what each element means, and ask them to correct it. One message,
numbered, so it is easy to answer.

Cover these, because they change the design and you cannot get them from a
picture:

| Ask about | Why it cannot be inferred |
|---|---|
| What each data element shows | "72" could be heart rate, a countdown, or a temperature |
| The goal behind any ring or bar | A ring is a *fraction*; it needs a maximum |
| What to draw when a value is missing | Every fitness reading can be absent, and the format requires an answer |
| Colours | A sketch on paper is not a colour scheme; watch faces are usually dark |
| Which watches | The design is built per device |
| 12- or 24-hour | Or use `%h`, which follows the watch's own setting — usually the right answer |

Propose sensible defaults so the person can just say "yes": dark background,
`%h` for the hour, `hide` for a missing value inside a cluster, `--` as a
placeholder where a gap would look broken.

If something in the image is genuinely ambiguous, **ask rather than guess**.

## 3. Write the design

Start from a template rather than an empty file — it is already correct, and you
edit rather than invent:

```sh
wfb new "Their Face Name"        # dashboard: time, ring, two clusters, battery
wfb new "Their Face Name" -t minimal    # just a background and the time
```

Then edit it to match the image. The reference card at the bottom of this
document has the syntax for every element type.

### Reading positions off an image — the one technique that matters

Treat the dial as a circle whose radius is **100%**, and write every offset in
**`%r`** (percent of the screen's minor radius):

```
something halfway out from the centre, below     ->  at: {anchor: center, dy: 50%r}
something near the left edge, level with centre  ->  at: {anchor: center, dx: -80%r}
a ring just inside the bezel                     ->  radius: 88%r
```

This works because a sketch is *proportional* and `%r` is the proportional unit.
It is also the only way the design stays right on more than one watch.

> **Never write a bare pixel offset.** `dy: 40` and `dy: 30%r` look identical on
> one watch and differ on every other one — and nothing will warn you, because
> both are legal. Use `%r` for anything you think of as "this far out from the
> middle".

Angles are measured **clockwise from 12 o'clock**: `0deg` is the top, `90deg` is
3 o'clock, `180deg` is the bottom. A ring with a gap at the bottom typically
starts around `210deg` and sweeps about `300deg`.

### Rules that will otherwise bite you

1. **Every fitness reading can be absent**, so every binding to one needs
   `when_absent:` — `hide`, `placeholder` (with `placeholder: "--"`), or
   `fallback`. This is not bureaucracy: sensors are simply missing on some
   watches, and the format refuses to guess what should be drawn instead.
2. **Colours must be palette-legal.** Each channel must be `00`, `55`, `AA` or
   `FF` — so `#FF5500` is fine and `#FF6600` is dithered and looks grainy. Name
   every colour in `palette:` and reference it; the linter will tell you the
   nearest legal colour if you get one wrong.
3. **Time needs a time format.** `format: "{:%h:%M}"`. `%h` follows the watch's
   12/24-hour setting; `%H` forces 24-hour.
4. **A progress arc is a stroked ring, not a filled wedge.** There is no
   filled-arc primitive on this platform. `thickness` is a pen width; there is no
   inner radius, no gradient, and no cap style. `style: arc` and `style: bar`
   take *different* keys — an arc needs `radius`, `thickness`, `start_angle` and
   `sweep`; a bar needs `size`. Mixing them is the commonest slip here.
5. **A bar or ring needs a maximum.** It draws a fraction, so `max:` must be a
   goal — a source like `activity.step_goal`, or a number. Some values have no
   natural goal (heart rate); ask what the person wants the full bar to mean.
5. **Keep it inside the visible circle.** The screen buffer is square but the
   panel is round, so a corner that fits the buffer can still be under the bezel.
   The linter checks this.

## 4. Validate — not optional

```sh
wfb validate my-face.yaml
```

**Fix only what it reports, then run it again.** The errors are written to be
acted on: they name the file, the line, the column, and the fix. Expect three or
four rounds from a first draft — that is normal and fast, not a sign you are
doing badly.

```
did you mean: activity.steps?
choose one of: hide | placeholder (with 'placeholder:') | fallback
nearest legal colour: #FF5500
write it as:
    type: shape
    shape: rectangle
```

Do not go looking through documentation while errors remain. The message is
almost always sufficient. Repeat until it says `ok`.

Warnings are worth fixing too — especially `safe-area` and `text-overflow`, which
mean something will be clipped on a real watch.

## 5. Preview and compare — not optional

```sh
wfb preview my-face.yaml -d <device> --scale 3
```

**Then open the PNG and compare it to the original image.** This is the step that
catches everything the compiler cannot: an element in the wrong place, text too
large, a ring sweeping the wrong way, two things overlapping.

Look for:

- Is each element roughly where the image put it?
- Do the proportions match — is the time as dominant as it is in the picture?
- Does anything overlap or run off the edge?
- Does the arc start and sweep the way the image shows?

Adjust the `%r` numbers and preview again. Two or three passes is normal.

While iterating, `wfb preview my-face.yaml --watch` re-renders on every save.

**A note on fidelity.** Positions and sizes in the preview are exactly what the
watch will use. Glyph shapes for built-in fonts are *not* — the real typefaces
are not available off-device — so judge layout and proportion, not letterforms.

## 6. Build

```sh
wfb build my-face.yaml
```

That compiles a signed `.prg` per target and reports memory against the 128 KB
watch-face limit. Report the result, including any warnings.

Then hand over: the `.prg` files can be copied to the watch's `GARMIN/APPS`
directory over USB.

---

## Reference card

```yaml
format: 1
face:
  id: <uuid>            # `wfb new` generates one; never reuse another face's
  name: My Face
targets: [fenix8solar47mm, fenix8solar51mm, fr955]

palette:                # channels must be 00/55/AA/FF
  bg: "#000000"
  text: "#FFFFFF"
  accent: "#00AAFF"
  hot: "#FF5500"
  track: "#555555"

fonts:                  # optional; omit to use built-in fonts only
  clock:
    source: assets/YourFont.ttf
    size: 68            # em pixels on the smallest target, scaled per device

elements:
  # a full-screen background
  - id: background
    type: shape
    shape: rectangle              # rectangle | rounded_rectangle | circle | line
    at: {anchor: center}
    size: {width: 100%, height: 100%}
    color: palette.bg

  # text bound to data
  - id: steps_value
    type: text
    value: activity.steps         # must exist in `wfb sources`
    format: "{:d}"                # {:d} {:02d} {:.1f} {} or a time format
    font: FONT_SMALL              # or font.clock for a declared custom font
    at: {anchor: center, dy: 30%r}
    color: palette.text
    align: center                 # left | center | right
    when_absent: placeholder      # hide | placeholder | fallback
    placeholder: "--"

  # fixed text
  - id: label
    type: text
    text: "STEPS"
    font: FONT_XTINY
    at: {anchor: center, dy: 40%r}
    color: palette.text

  # a goal ring
  - id: step_ring
    type: progress
    style: arc                    # arc | bar
    value: activity.steps
    max: activity.step_goal       # a source, or a number like 10000
    at: {anchor: center}
    radius: 88%r
    thickness: 9px
    start_angle: 210deg           # clockwise from 12 o'clock
    sweep: 300deg
    color: palette.accent
    track_color: palette.track    # optional unfilled remainder
    when_absent: hide

  # a bar
  - id: battery
    type: progress
    style: bar
    value: system.battery
    max: 100
    at: {anchor: center, dy: 62%r}
    size: {width: 40%r, height: 5%r}
    color: palette.text

  # a drawn icon -- costs no memory and takes a colour
  - id: hr_icon
    type: icon
    icon: heart                   # heart | steps | flame
    size: 11%r
    at: {anchor: center, dx: -40%r, dy: 30%r}
    color: palette.hot
```

**Built-in fonts**, smallest to largest, with their pixel height on a 260 px
watch. They differ per device, which is why sizes are never hard-coded:

| Font | px | Good for |
|---|---|---|
| `FONT_XTINY` | 28 | labels next to a value |
| `FONT_TINY` | 38 | secondary text |
| `FONT_SMALL` | 42 | data values, the date |
| `FONT_MEDIUM` / `FONT_LARGE` | 51 / 53 | a prominent value |
| `FONT_NUMBER_MILD` / `FONT_NUMBER_MEDIUM` | 58 / 65 | a centred clock |
| `FONT_NUMBER_HOT` | 99 | a clock that fills the dial |

`FONT_NUMBER_HOT` renders `23:59` about 210 px wide — nearly the whole screen. If
the clock is not centred, drop to `FONT_NUMBER_MEDIUM`. The overflow lint will
tell you, because it measures the *widest* value the binding can produce rather
than the one in the picture: a sketch showing `7:05` still has to fit `23:59`.

**Anchors:** `center`, `top`, `bottom`, `left`, `right`, `top_left`, `top_right`,
`bottom_left`, `bottom_right`. Offsets are measured from the anchor.

**Lengths:** `%r` (of the screen's minor radius — prefer this), `%` (of the
parent box), `px` (avoid), `pt` (multiples of the element's font height).

**Time formats:** `%h` hour following the watch's setting · `%H` 24-hour ·
`%I` 12-hour · `%M` minute · `%S` second · `%p` AM/PM.

Anything not covered here is in `docs/format.md`, and the schema
(`wfb schema`) is the normative definition.

---

## Common failures, and what they mean

| What you see | What to do |
|---|---|
| `unknown element type 'rectangle'` | The note tells you the exact spelling — use it |
| `'style: bar' but carries arc-only keys` | Pick one: `arc` takes `radius`/`thickness`/`start_angle`/`sweep`, `bar` takes `size` |
| `unknown key ('x', 'y' were unexpected)` | Positions go in `at:`, sizes in `size:`. There are no absolute coordinates |
| `'activity.steps' can be absent, so 'when_absent:' is required` | Add `when_absent: hide` or a placeholder |
| `unknown data source 'steps'` | The note suggests the real path. Never invent one — check `wfb sources` |
| `a time value needs a strftime-style format` | `format: "{:%h:%M}"` |
| `will be dithered` | Use the nearest legal colour the warning names |
| `reaches outside the visible area` | Reduce the `%r` offset — it is under the bezel |
| `the widest rendering '88888' … does not fit` | The value can get wider than it looks today. Use a smaller font or move it inward |
| Preview looks nothing like the image | Re-read the proportions. Are your offsets in `%r`? Is the arc sweeping the right way? |

## Things this format cannot do

Say so plainly if the image needs one of these, rather than approximating in
silence:

- **filled wedges or gradient arcs** — rings are strokes only;
- **transparency or blending** — the panels have no alpha;
- **animation**;
- **images and complication slots** — not implemented yet;
- **multi-coloured text** — a bitmap font is a single colour.
