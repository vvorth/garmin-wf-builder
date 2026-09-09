# Build a Garmin watch face

Instructions for an AI assistant with two capabilities: **reading files** and
**running shell commands**. Following them produces a compiled, sideloadable
Garmin Connect IQ watch face (`.prg`) from a picture or a description.

Nothing here is specific to any model or harness. Where a step needs a
capability you may not have — seeing an image, for instance — it says so and
gives you the alternative.

---

## What you are doing

A watch face is declared in a YAML file and compiled by a tool called `wfb`.
You will:

1. find the tool and check the environment;
2. work out what the person wants, and ask about what you cannot infer;
3. write the YAML;
4. loop on `wfb validate` until it passes;
5. loop on `wfb preview` until the render matches the intent;
6. compile with `wfb build`.

**Steps 4 and 5 are the point.** Do not try to be right in one shot. The
compiler's errors name the fix, and the preview shows what you actually built —
between them they will get you there in a handful of rounds. Iterating is the
method, not a sign that something has gone wrong.

---

## 1. Find the tool and check the environment

The tool may be installed in several ways. Try these in order and use whichever
answers:

```sh
wfb doctor                                  # if it is on PATH
python3 /path/to/garmin-wf-builder/wfb.py doctor    # from a checked-out copy
docker run --rm -v "$PWD:/work" \
  -v "$DEVICES_DIR:/devices:ro" garmin-wf-builder doctor   # containerised
```

If you do not know where the project is, look for it — checking the current
directory and its parents as well as the home directory, since a checkout is
often neither:

```sh
find . ~ /opt /srv /workspace -maxdepth 6 -name wfb.py 2>/dev/null | head
```

If that finds nothing, ask the person where the project is rather than guessing.

**Whatever works, use that exact invocation for every command below.** This
document writes `wfb`; substitute yours. The file entry point re-executes itself
under the project's own environment, so any `python3` will do.

`wfb doctor` prints what is present and what is missing, and each missing item
names the command that fixes it. Read its output before doing anything else:

- **`ready`** — everything works.
- **`partial`** — you can design, validate and preview, but not compile. Say so
  now, and continue: everything up to step 6 still works.
- **`not ready`** — stop and report what it says. In particular, **the Garmin
  device definitions cannot be downloaded** (Garmin's endpoint requires an
  interactive login), so if those are missing only the person can supply them.
  Do not attempt to work around this.

Then learn the actual vocabulary rather than trusting your memory of it:

```sh
wfb sources     # every data source you may bind, with its type
wfb devices     # the watches you may target
wfb new --list  # the templates you may start from
```

> **Never bind a data source that is not listed by `wfb sources`.** A plausible
> invented path — `activity.heartrate`, `weather.temp` — is the one class of
> error the tools cannot catch for you, because it will simply fail to exist.

For any command's full flags and behaviour beyond what this document covers,
ask the tool itself rather than guessing: `wfb help <command>` (equivalently
`wfb <command> help` or `wfb <command> --help`) prints it, sourced from that
command's own docstring, so it cannot drift from what the tool actually does.

---

## 2. Work out what to build

### If you were given an image

**If you can see images**, look at it and inventory every visible element. For
each: what it is (text, a ring, a bar, an icon, a plain shape), where it sits as
a *fraction of the way from the centre to the edge*, roughly how big, and what it
appears to show. For arcs, note where the sweep starts, which way it goes, and
whether it closes.

Do not think in pixels. A drawing has no pixels worth having.

**If you cannot see images**, say so plainly and ask the person to describe the
layout instead. Do not guess at a picture you cannot see, and do not pretend to
have looked at it.

### If you were given a description

Work from that directly. The same questions below still apply.

### Then ask — once, and specifically

Show your interpretation and ask the person to correct it. **One message, a
numbered list**, so it is easy to answer. Propose a sensible default for each
point so they can simply agree.

These cannot be inferred from any picture or short description, and each one
changes the design:

| Ask | Why |
|---|---|
| What each data element shows | "72" could be heart rate, a countdown, or a temperature |
| The goal behind every ring or bar | A ring draws a *fraction*, so it needs a maximum |
| What to draw when a value is missing | Every fitness reading can be absent, and the format requires an answer |
| Colours | A sketch is not a colour scheme; watch faces are usually dark |
| Which watches | The design is compiled per device |
| 12- or 24-hour | Or `%h`, which follows the watch's own setting — usually the right answer |

Reasonable defaults to propose: a dark background, `%h` for the hour, `hide` for
a missing value inside a cluster, and `--` where a gap would look broken.

**If the person says to skip the questions and use your judgement, do that** —
but state the assumptions you made, so the preview can be judged against them.

---

## 3. Write the design

Start from a template. It is already correct, so you are editing rather than
inventing:

```sh
wfb new "Their Face Name"             # time, a goal ring, two clusters, a battery bar
wfb new "Their Face Name" -t minimal  # just a background and the time
```

That writes `their-face-name.yaml` with a fresh id. Edit it to match. The
reference at the end of this document has the syntax for every element.

### Reading positions off an image or a description

Treat the dial as a circle of radius **100%** and write every offset in **`%r`**
— percent of the screen's minor radius:

```
halfway out from the centre, below      ->  at: {anchor: center, dy: 50%r}
near the left edge, level with centre   ->  at: {anchor: center, dx: -80%r}
a ring just inside the bezel            ->  radius: 88%r
```

This works because a drawing is *proportional*, and it is the only way the design
stays correct on more than one watch.

> **Never write a bare pixel offset.** `dy: 40` and `dy: 30%r` are identical on
> one watch and different on every other, and nothing will warn you — both are
> legal. Use `%r` for anything you would describe as "this far out from the
> middle".

Angles run **clockwise from 12 o'clock**: `0deg` is the top, `90deg` is 3
o'clock, `180deg` is the bottom. A ring with a gap at the bottom usually starts
near `210deg` and sweeps about `300deg`.

### Eight rules that will otherwise cost you a round

1. **Every fitness reading can be absent**, so any binding to one needs
   `when_absent:` — `hide`, `placeholder` (with `placeholder: "--"`), or
   `fallback`. Sensors are genuinely missing on some watches; the format refuses
   to guess what should appear instead.
2. **Colours must be palette-legal.** Each channel must be `00`, `55`, `AA` or
   `FF`, so `#FF5500` is fine and `#FF6600` is dithered and looks grainy. Declare
   colours in `palette:` and reference them by name.
3. **Time needs a time format**: `format: "{:%h:%M}"`.
4. **`style: arc` and `style: bar` take different keys.** An arc needs `radius`,
   `thickness`, `start_angle` and `sweep`; a bar needs `size`. Mixing them is the
   commonest slip.
5. **An arc is a stroked ring, not a filled wedge.** This platform has no
   filled-arc primitive: `thickness` is a pen width, and there is no inner
   radius, gradient or cap style. `filled:` is an error on `shape: arc` for
   that reason, and `filled: false` is an error on `shape: polygon` because
   `Dc` has `fillPolygon` and no `drawPolygon`.
6. **Stay inside the visible circle.** The frame buffer is square but the panel
   is round, so a corner that fits the buffer can still sit under the bezel.
7. **Never press an icon into service for something it does not mean.** The
   named catalogue (`heart`, `steps`, `flame`, `alarm`, `dnd`, `notification`)
   is six specific shapes, not six interchangeable dots. A heart icon next to a
   do-not-disturb indicator reads as a heart-rate alert, not as "notifications
   are silenced": the viewer trusts the shape, and a mismatched one is actively
   misleading rather than merely generic. **This is rarely forced on you**: an
   icon is a glyph from a large vendored icon font, and `icon:` accepts any
   single character from it directly, not only the six named entries — paste
   the actual character rather than the nearest wrong catalogue name. Look for
   one at https://www.nerdfonts.com/cheat-sheet (search by concept — "alarm",
   "umbrella", "bluetooth" — copy the glyph, paste it as the `icon:` value).
   Only fall back to a plain shape or a labelled number if nothing in that font
   fits at all.
8. **A `size:` that names a font — an `icon`'s, or a `fonts:` entry's — is
   `px` or `%r` only**, never `%` or `pt`. The sheet has to be baked before
   layout runs, so its size cannot depend on a parent box or on a font, neither
   of which is known yet. Prefer `%r`, which follows each device's own screen.
   A `fonts:` entry may also take a bare number (`size: 68`), which means
   pixels on the *smallest* target and is scaled up from there; it still works,
   but `%r` says the same thing per device without an unnamed reference screen,
   and `scale:` may not be combined with a length.

---

## 4. Validate — do not skip this

```sh
wfb validate their-face-name.yaml
```

**Fix only what it reports, then run it again.** The messages name the file, the
line, the column and the fix:

```
did you mean: activity.steps?
choose one of: hide | placeholder (with 'placeholder:') | fallback
nearest legal colour: #FF5500
write it as:
    type: shape
    shape: rectangle
```

Do not go reading documentation while errors remain — the message is almost
always sufficient. **Three or four rounds from a first draft is normal.**

Fix the warnings too. `safe-area` and `text-overflow` mean something will be
clipped on a real watch, and `text-overflow` in particular measures the *widest*
value a binding can produce, not the one you happen to be picturing: a clock
showing `7:05` still has to fit `23:59`.

Repeat until it prints `ok`.

---

## 5. Preview and compare — do not skip this either

```sh
wfb preview their-face-name.yaml -d <device> --scale 3
```

That writes a PNG. **If you can see images, open it and compare it with what the
person asked for.** This catches everything the compiler cannot: an element in
the wrong place, text too large, a ring sweeping the wrong way, two things
overlapping.

Check: is each element where it should be? Do the proportions match — is the time
as dominant as intended? Does anything overlap or run off the edge? Does the arc
start and sweep correctly?

Adjust the `%r` values and preview again. **Two or three passes is normal.**

**If you cannot see images**, say so, and instead show the person the preview's
path and ask them to look. Do not claim a design matches a picture you have not
compared.

Positions and sizes in the preview are exactly what the watch will use. Glyph
shapes for built-in fonts are not — the real typefaces are not available
off-device — so judge layout and proportion, not letterforms.

---

## 6. Compile

```sh
wfb build their-face-name.yaml
```

This produces one signed `.prg` per target and reports memory against the 128 KB
watch-face limit. Report the result, including any warnings.

To install: the `.prg` files are copied to the watch's `GARMIN/APPS` directory
over USB.

**You are done when** `wfb build` succeeds, the preview matches what was asked
for, and you have told the person where the files are and what the memory figures
were. If anything was left unresolved — a question they never answered, a
compromise you made — say so rather than letting it pass silently.

---

## Reference

```yaml
format: 1
face:
  id: <uuid>            # `wfb new` generates one; never copy another face's
  name: My Face
targets: [fenix8solar47mm, fenix8solar51mm, fr955]

palette:                # each channel must be 00, 55, AA or FF
  bg: "#000000"
  text: "#FFFFFF"
  accent: "#00AAFF"
  hot: "#FF5500"
  track: "#555555"

fonts:                  # optional -- omit to use built-in fonts only
  clock:
    source: assets/YourFont.ttf
    size: 18%r          # of this device's minor radius -- or 12px, or a bare
                        # number for 'pixels on the smallest target' (rule 8)
    monospace: true     # optional: one cell width for every glyph, so a clock
                        # does not shift as its digits change (align: center)

elements:
  - id: background
    type: shape
    shape: rectangle              # rectangle | rounded_rectangle | circle | ellipse
                                  #  | arc | polygon | line
    at: {anchor: center}
    size: {width: 100%, height: 100%}
    color: palette.bg

  - id: steps_value               # text bound to data
    type: text
    value: activity.steps         # must appear in `wfb sources`
    format: "{:d}"                # {:d} {:02d} {:.1f} {} or a time format
    font: FONT_SMALL              # or font.clock for a declared custom font
    at: {anchor: center, dy: 30%r}
    color: palette.text
    align: center                 # left | center | right    (horizontal part of the box at `at`)
    vertical_align: center        # top | center | baseline  (vertical part of the box at `at`)
    when_absent: placeholder      # hide | placeholder | fallback
    placeholder: "--"

  - id: label                     # fixed text
    type: text
    text: "STEPS"
    font: FONT_XTINY
    at: {anchor: center, dy: 40%r}
    color: palette.text

  - id: step_ring                 # a goal ring
    type: progress
    style: arc                    # arc | bar
    value: activity.steps
    max: activity.step_goal       # a source, or a number such as 10000
    at: {anchor: center}
    radius: 88%r
    thickness: 9px
    start_angle: 210deg           # clockwise from 12 o'clock
    sweep: 300deg
    color: palette.accent
    track_color: palette.track    # optional unfilled remainder
    when_absent: hide

  - id: battery                   # a bar
    type: progress
    style: bar
    value: system.battery
    max: 100
    at: {anchor: center, dy: 62%r}
    size: {width: 40%r, height: 5%r}
    color: palette.text

  - id: hr_icon                   # a glyph from the vendored icon font; small
    type: icon                    # resource cost, takes a colour at runtime
    icon: heart                   # alarm | battery | distance | dnd | flame | floors | heart | notification | phone | steps | weather_cloudy | weather_cloudy_heavy | weather_cloudy_light | weather_dust | weather_fog | weather_hail | weather_haze | weather_hurricane | weather_hurricane_warning | weather_ice | weather_lightning | weather_rain | weather_rain_heavy | weather_rain_light | weather_sandstorm | weather_sleet | weather_smoke | weather_snow | weather_snow_heavy | weather_strong_wind | weather_sunny | weather_sunny_overcast | weather_thunderstorm | weather_thunderstorm_showers | weather_tornado | weather_unknown | weather_volcano | weather_windy | weather_wintry_mix
                                   # -- or any single glyph pasted directly, e.g. icon: ""
    size: 11%r                    # px or %r only -- never % or pt (rule 8)
    at: {anchor: center, dx: -40%r, dy: 30%r}
    color: palette.hot
```

`wfb.icons.METRIC_ICON` also lists the conventional icon for many catalogue data
sources (`activity.steps` → `steps`, `heart_rate.current` → `heart`, and so on) --
useful as a default when a design binds a source and needs an icon to go with
it, not a constraint the compiler enforces.

Most of the day-condition weather names above also have a `_night` variant
(`weather_sunny_night`, `weather_rain_night`, ...) for a font glyph specifically
drawn for after dark -- not every condition has one, so check `wfb sources` or
`wfb.icons.names()` rather than assuming. `icon_for:` (below) only resolves the
day glyph today (there is no sunrise/sunset source yet to know which half
applies on-device); a static `icon: weather_rain_night` is how a design reaches
a night glyph directly today.

**A dynamic icon** chooses its glyph on-device at runtime instead of at build
time -- `icon_for:` instead of `icon:`, mutually exclusive with it, and
currently only accepting a bare `weather.condition` / `weather.condition_today`
/ `weather.condition_tomorrow` source (never an expression over one -- the
on-device lookup needs the raw `Weather.CONDITION_*` value):

```yaml
  - id: weather_icon
    type: icon
    icon_for: weather.condition
    size: 18%r
    color: palette.text
```

No `when_absent:` for this -- it just does not draw while the value is
absent, same as any other binding defaulting to `hide`.

**`on_hold:`** makes any single element open a glance. A live watch face
receives exactly one gesture -- touch and hold -- and `Complications.exitTo` is
the only exit the platform offers, so the value names a *complication type*
(run `wfb complications` for the ~42 names) and the watch opens whatever owns
it:

```yaml
  - id: hr_icon
    type: icon
    icon: heart
    size: 11%r
    at: {anchor: center, dy: -20%}
    color: palette.hot
    on_hold: heart_rate           # touch and hold -> the heart-rate glance
```

The hit region is the element's own drawn box, so put several elements in a
`group` and hold that when you want a bigger target. There is no `on_tap:` --
it was renamed, because no device delivers a tap to a live watch face.

`on_hold: auto` resolves the target for you, from the element's own value
binding, instead of naming one by hand:

```yaml
  - id: hr_value
    type: text
    value: heart_rate.current
    format: "{:d}"
    font: FONT_SMALL
    on_hold: auto                 # resolves to 'heart_rate'
```

It errors (`hold-auto-unresolved` / `hold-auto-ambiguous`) rather than guess
if the element's bound source has no conventional glance, or more than one
candidate -- name a target explicitly in that case. A carousel element itself
may not take `on_hold:` at all (`carousel-on-hold`); use each item's own
`launch:` instead, which also accepts `auto`.

**`complication.*` is a separate, wider namespace of its own** -- not just an
`on_hold:` target. `wfb sources` lists all 42 alongside every other source,
each prefixed `complication.` (e.g. `complication.body_battery`,
`complication.sleep_score`). Reach for one only when there is no cheaper
direct path -- most sources you would want are already bound directly
(`activity.steps`, `heart_rate.current`, and so on), and those cost no extra
permission or `minApiLevel` floor. `complication.body_battery` is the one
genuinely common case with no direct alternative at all (Body Battery has no
non-Complications, non-SensorHistory route, and a watch face may not declare
`SensorHistory`).

**A carousel** is a row of readings the *wearer* picks between -- the stock
Forerunner face's data row. Use it when a design wants several readings in one
place and there is no room for all of them, or when the wearer should choose:

```yaml
  - id: data
    type: carousel
    at: {anchor: center, dy: 20%}
    size: {width: 62%, height: 22%}   # the TOUCH target: split into thirds
    pitch: 22%r                       # centre-to-centre slot spacing
    icon_size: 9%r
    color: palette.accent             # the selected item
    inactive_color: palette.track     # its neighbours
    value_font: FONT_SMALL
    value_color: palette.text
    value_offset: {anchor: center, dy: 34%}
    items:
      - value: heart_rate.current     # icon inferred from the source
        format: "{:d}"
        when_absent: placeholder
        placeholder: "--"
        launch: heart_rate            # centre-hold opens this glance
      - value: activity.steps
        format: "{:d}"
        when_absent: hide
      - icon: battery                 # or name one
        value: system.battery
        format: "{:.0f}%"
```

Three things to get right, all of which the linter will otherwise tell you:

* **`size:` is the touch target, not the drawn extent.** It is cut into equal
  thirds -- previous, open the glance, next -- because a live watch face gets
  exactly one gesture (touch and hold) and coordinates are the only way to give
  it three meanings. Be generous; a third under 40px warns, and so does a third
  that lands under a round screen's bezel.
* **`when_absent:` goes on the item, not the element**, and `hide` blanks that
  item's reading while leaving its icon drawn -- the row does not collapse.
* **The carousel's own colours may not be nullable.** There is no
  `when_absent:` for the row's appearance; guard a conditional colour inside
  the expression instead.

`animate:` (seconds, default 0.3) and `persist:` (default true) are usually
right as they stand. The slide only runs while the watch is awake -- generated
code guards it, because `WatchUi.animate` crashes the app in low power mode.

**Anchors** — `center`, `top`, `bottom`, `left`, `right`, `top_left`,
`top_right`, `bottom_left`, `bottom_right`. Offsets are measured from the anchor.

**Lengths** — `%r` (of the screen's minor radius; prefer this), `%` (of the
parent box), `px` (avoid), `pt` (multiples of the element's font height).

**Time formats** — `%h` hour following the watch's setting · `%H` 24-hour ·
`%I` 12-hour · `%M` minute · `%S` second · `%p` AM/PM.

**Built-in fonts**, with pixel heights on a 260 px watch. They differ per device,
which is why you never hard-code a size:

| Font | px | Good for |
|---|---|---|
| `FONT_XTINY` | 28 | labels beside a value |
| `FONT_TINY` | 38 | secondary text |
| `FONT_SMALL` | 42 | data values, the date |
| `FONT_MEDIUM` / `FONT_LARGE` | 51 / 53 | a prominent value |
| `FONT_NUMBER_MILD` / `FONT_NUMBER_MEDIUM` | 58 / 65 | a centred clock |
| `FONT_NUMBER_HOT` | 99 | a clock that fills the dial |

`FONT_NUMBER_HOT` renders `23:59` about 210 px wide, nearly the full screen. If
the clock is not centred, drop to `FONT_NUMBER_MEDIUM`.

For anything not covered here, `wfb schema` prints the normative definition, and
the project's `docs/format.md` explains the reasoning.

---

## Errors you will meet, and what they mean

| Message | What to do |
|---|---|
| `unknown element type 'rectangle'` | The note gives the exact spelling — use it |
| `unknown key ('x', 'y' were unexpected)` | Positions go in `at:`, sizes in `size:`. There are no absolute coordinates |
| `'style: bar' but carries arc-only keys` | Choose one: `arc` takes radius/thickness/start_angle/sweep, `bar` takes size |
| `'activity.steps' can be absent, so 'when_absent:' is required` | Add `when_absent: hide`, or a placeholder |
| `unknown data source 'steps'` | The note suggests the real path. Never invent one — check `wfb sources` |
| `a time value needs a strftime-style format` | `format: "{:%h:%M}"` |
| `will be dithered` | Use the nearest legal colour the warning names |
| `reaches outside the visible area` | Reduce the `%r` offset; it is under the bezel |
| `the widest rendering … does not fit` | The value gets wider than today's. Smaller font, or move it inward |
| `Invalid device id specified` | The device definitions are missing — run `wfb doctor` |
| Preview looks nothing like the request | Re-check the proportions. Are the offsets in `%r`? Is the arc sweeping the right way? |

## What this format cannot do

Say so plainly if the design needs one of these, rather than approximating in
silence:

- **filled wedges or gradient arcs** — rings are strokes only;
- **transparency or blending** — these panels have no alpha channel;
- **animation, except a `carousel`'s slide** — a watch face has timers and
  animations only during the ~10s of high power mode after a gesture, and
  `WatchUi.animate` crashes the app if called outside it;
- **tap, swipe or button input** — a live watch face receives *only* touch and
  hold (`onPress`). `WatchFaceDelegate.onTap` exists on some watches and fires
  solely inside the on-device config editor, never on a face being looked at.
  Anything modelled on a stock face's tap behaviour is modelled on native
  firmware this API does not expose;
- **images and complication slots** — not implemented yet;
- **multi-coloured text** — a bitmap font carries a single colour.
