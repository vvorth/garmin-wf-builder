# Cookbook

Recipes for things the format can do that no single chapter makes
obvious: compositions of two or three features, expressions worth
remembering, and corners of the vocabulary that are easy to forget. Each
recipe is a snippet and the reason it works, with the chapter that holds
the rules. Nothing here is a new feature; everything is buildable today.
The plain cases live in [`examples/`](../../examples/README.md).

## Pointers over any value

**A 24-hour hand, which `hand_sets:` do not offer.** A needle gauge takes
any expression as its value, so the clock itself can drive one. A second
one with `time.utc_offset` folded in is a GMT hand.

```yaml
hand_24h:
  type: gauge
  style: needle
  value: time.hour * 60 + time.minute
  max: 1440
  at: { anchor: center }
  start_angle: 180deg          # midnight at the bottom, as on a 24-hour dial
  sweep: 360deg
  color: color.accent
  needle:
    blade: { type: line, at: { dy: 4%r }, to: { dy: -70%r }, thickness: 2px }
    tip: { type: polygon, mirror: x, points: [{ dx: -3%r, dy: -70%r }, { dy: -78%r }] }
gmt_hand:
  type: gauge
  style: needle
  value: "((time.hour * 3600 + time.minute * 60 - time.utc_offset) % 86400 + 86400) % 86400"
  max: 86400
  at: { anchor: center }
  start_angle: 180deg
  sweep: 360deg
  color: color.dim
  needle: { blade: { type: line, at: { dy: 4%r }, to: { dy: -60%r }, thickness: 1px } }
```

Add `3600 * N` inside the parentheses for a fixed zone N hours east of
UTC. The modulo dance keeps the value in `0..86399` whatever the sign of
the offset ([Expressions](data.md#expressions): `%` follows the sign of
its left side).

**A date pointer with a step short of a full turn.** Thirty-one days on a
dial whose 31 sits one step before its 1: `max: 30` over `date.day - 1`,
and a sweep of 30 steps, not 31.

```yaml
date_hand:
  type: gauge
  style: needle
  value: date.day - 1
  max: 30
  at: { anchor: center, dy: 45%r }
  start_angle: 0deg
  sweep: 348.387deg            # 30 of 31 steps of 11.6129deg
  color: color.accent
  needle:
    blade: { type: line, at: { dy: 3%r }, to: { dy: -13%r }, thickness: 2px }
    moon: { type: arc, at: { dy: -17%r }, radius: 4%r, thickness: 2px, start_angle: 200deg, sweep: 320deg }
```

The ticks behind it are a radial pattern with the same `step_angle:
11.6129deg` and `count: 31`; neither lands on whole degrees, so the
pattern's lines are exact and the needle's position is, while an arc on
either would warn `whole-degree`
([Gauge needles](progress-and-graphs.md#gauge-needles),
[Patterns](patterns.md#pattern)).

**Astronomy on a needle.** Every `astro.*` source is a number, so each is
a dial: `astro.moon_age` over `max: 29.53` is a moon-age pointer,
`astro.sun_altitude` (degrees, negative below the horizon) a sun-height
pointer, `astro.equation_of_time` a slow-swinging equation-of-time hand,
`astro.sun_declination` a season hand. A value below 0 needs offsetting
first, since a gauge's fraction clamps at 0:

```yaml
eot_hand:
  type: gauge
  style: needle
  value: astro.equation_of_time + 16   # -16..+14 minutes becomes 0..30
  max: 30
  start_angle: -60deg
  sweep: 120deg
  at: { anchor: center, dx: 50%r }
  color: color.fg
  needle: { blade: { type: line, to: { dy: -20%r }, thickness: 1px } }
```

The `date.*`, `time.*` and `astro.*` sources need no permission;
`astro.sun_*` need the position, which adds one ([Astronomy](data.md#astronomy)).

**A complication on a scale you do not know.** `max: auto` reads the
wearer's own range, and `slot:` makes the gauge follow whatever the wearer
picks for that slot, each pick on its own scale:

```yaml
hr_zone_ring: { type: gauge, style: arc, value: complication.heart_rate, max: auto, radius: 46%r, thickness: 5px, start_angle: 150deg, sweep: 240deg, at: { anchor: center }, color: color.accent, track_color: color.track, absent: hide }
pick_ring:    { type: gauge, style: segments, slot: top, count: 10, gap: 4deg, radius: 40%r, thickness: 4px, start_angle: 152deg, sweep: 236deg, at: { anchor: center }, color: color.accent, track_color: color.track, absent: hide }
```

([Gauges on a slot](progress-and-graphs.md#gauges-on-a-slot).)

## Expressions to keep

**The ISO week number**, from the day of the year and the weekday:

```yaml
week: { type: text, text: "W{floor((astro.day_of_year - ((date.weekday + 5) % 7 + 1) + 10) / 7)}", font: FONT_XTINY, at: { anchor: center, dy: 30%r }, color: color.fg }
```

`(date.weekday + 5) % 7 + 1` turns Garmin's Sunday-first weekday into
ISO's Monday-first one. The result is 0 in the first days of a January
that belongs to the previous year's last week, and 53 in a late December
that belongs to the next year's first; a face that cares spells both out
with a rule list over `date.year % 4`.

**Lighting today in a ring of seven.** `copy` is the copy's index in a
pattern's colours, its parts' `visible:` and its text parts:

```yaml
weekdays:
  type: pattern
  pattern: radial
  at: { anchor: center }
  count: 7
  step_angle: 20deg
  start: -60deg
  color: "copy == (date.weekday + 5) % 7 ? color.accent : color.dim"
  parts:
    letter:
      type: text
      font: FONT_XTINY
      at: { dy: -80%r }
      text: "{(copy == 0 ? 'M' : copy == 1 ? 'T' : copy == 2 ? 'W' : copy == 3 ? 'T' : copy == 4 ? 'F' : copy == 5 ? 'S' : 'S')}"
```

**A meter out of a pattern.** A part's `visible:` is evaluated per copy,
so ten dots become a ten-step gauge of anything; `absent: hide` is
required once a part reads data:

```yaml
battery_dots:
  type: pattern
  pattern: linear
  at: { anchor: center, dy: 40%r }
  count: 10
  step: { dx: 6%r }
  absent: hide
  parts:
    dot: { type: circle, at: { dx: -27%r }, radius: 2%r, color: color.accent, visible: "copy < round(system.battery / 10)" }
```

**Day or night without a weather reading.** `astro.sun_altitude` is
computed on the watch from the time and the position, so it never waits
for a forecast:

```yaml
color: "astro.sun_altitude > 0 ? color.day : astro.sun_altitude > -6 ? color.dusk : color.night"
```

**Things the language will refuse, and the spelling it wants.**
`%` wants whole numbers: wrap a Float in `floor()` or `round()`. A ternary
inside a placeholder is parenthesised: `"{(steps > 0 ? steps : 0):d}"`.
A literal brace is doubled: `"{{"`. A colour in an expression is a
`color.<name>`, never a hex. Division by a reading of 0 is 0, not a crash.
There are seven functions: `min`, `max`, `clamp`, `round`, `floor`, `abs`,
`percent` ([Expressions](data.md#expressions)).

## Readings that are times

**A duration or a time of day from a plain number.** A duration spec on a
number reads it as seconds; sources stated in minutes, hours or days are
converted first:

```yaml
sunrise:  { type: text, text: "{complication.sunrise:%h:%M}", absent: hide, font: FONT_XTINY, at: { anchor: center, dy: -30%r }, color: color.fg }
recovery: { type: text, text: "{complication.recovery_time:%-H:%M}", absent: { text: "--" }, font: FONT_XTINY, at: { anchor: center, dy: -20%r }, color: color.fg }
pace_5k:  { type: text, text: "{complication.race_pace_predictor_5k:%-M:%S}{unit}", units: auto, absent: hide, font: FONT_XTINY, at: { anchor: center, dy: -10%r }, color: color.fg }
```

`%h` follows the watch's 12/24-hour setting; `%-H` lets a 37-hour recovery
read `37:15` ([Durations and times of day](data.md#durations-and-times-of-day),
[Units](data.md#units)).

**A clock that does not jitter.** Proportional digits move the colon as
the minutes change; `monospace: true` on the font with `align: center`
pins it ([Fonts](fonts.md#monospace-stops-a-clock-from-jittering)).

## Sleep and the always-on frame

**Everything off but the time, and hollow digits there.** Face defaults
hide every element in the AMOLED frame; one element turns itself back on,
restyled, and draws its ring only, so almost no pixel stays lit:

```yaml
defaults:
  aod: { visible: false }
elements:
  clock:
    type: text
    text: "{time.clock:%h:%M}"
    font: FONT_NUMBER_HOT
    at: { anchor: center }
    color: color.fg
    aod:
      visible: true
      color: color.black                       # the interior vanishes on the black frame
      outline: { color: color.dim, width: 2 }
      text: "{:%H}"                            # hours only; the empty placeholder keeps the element's own reading
```

`dim:` scales every AOD colour, `mask:` is on unless `defaults: {aod:
{mask: false}}` ([Always-on display](always-on-display.md#per-element-or-group)).

**Seconds that vanish asleep, digital and analog.** A second hand hides
itself (`seconds: awake` is the default); a digital seconds readout reads
the same flag:

```yaml
seconds: { type: text, text: "{time.second:%S}", visible: system.awake, font: FONT_XTINY, at: { anchor: center, dy: 20%r }, color: color.dim }
```

([Hide it while asleep](modes-and-interaction.md#hide-it-while-asleep-systemawake).)

## Shapes the primitives do not have

**A crescent, a collar, a serpentine.** An `arc` part of a hand turns with
it, on or off the axis. Chained arcs must overlap by about `60 / radius`
degrees with a pen of 2 px or more, the radius taken in pixels on the
smallest target ([Analog hands](analog-hands.md#analog-hands),
[`examples/features/arc-hands`](../../examples/features/arc-hands/face.yaml)).

**Hands that stay apart where they cross.** A background-coloured ring on
the hands element draws each hand whole over the one beneath it:

```yaml
hands: { type: hands, set: main, at: { anchor: center }, outline: { color: color.bg, width: 2 } }
```

([Outlines](outlines.md#hands-and-patterns).)

**A reading bent round the dial, icon first.** `curve:` on a `data`
element lays the reading along a circle and the icon sits at either end:

```yaml
steps_curved:
  type: data
  slot: top
  font: font.bezel                 # a face: font; a baked font cannot bend
  at: { anchor: center }
  color: color.fg
  curve: { style: radial, angle: -46deg, radius: 80%r }
  align: left
  icon: { size: 10%r, position: left, gap: 2px }
```

([A curved reading](configuration.md#a-curved-reading-curve).)

**A filled sector.** There is none: approximate the wedge with a
`polygon`, or draw a `circle` and cover what is not wanted with
background-coloured shapes drawn after it ([Shapes](shapes.md#arc)).

## One design, several watches

**The same face on round, rectangular and AMOLED watches.** `overrides:`
patches geometry, colour and visibility per device id, screen shape or
display type, each override replacing the key whole:

```yaml
date:
  type: text
  text: "{date.today:%a %e}"
  at: { anchor: center, dy: 30%r }
  color: color.fg
  overrides:
    "shape:rectangle": { at: { anchor: center, dy: 22% } }
    "display:amoled": { color: color.accent }
    fenix5: { visible: false }
```

([Per-device overrides](placement.md#per-device-and-per-shape-overrides).)

**Styles that switch the whole character.** One `config: style:` entry
names a layout and a scheme, and each layout may place a different hand
set, so one entry changes dial, hands and colours together
([Styles and layouts](styles-and-layouts.md#styles-and-layouts),
[Analog hands](analog-hands.md#analog-hands)).

## Seeing it before the watch does

```sh
./wfb preview face.yaml --time 10:08:42 --date 2026-12-31     # a given moment
./wfb preview face.yaml --sample heart_rate.current=null       # a reading absent
./wfb preview face.yaml --sample astro.moon_age=14.8 --units statute
./wfb preview face.yaml --all-styles                           # every style, one PNG per device
./wfb preview face.yaml --aod --heatmap                        # the burn-in picture the lint judges
```

A bare `--sample steps` sets every source a complication type feeds.
`--asleep` renders the sleeping glance on any watch
([Preview and CLI](preview-and-cli.md#commands)).

## See also

- [`examples/README.md`](../../examples/README.md) — one face per feature, where the plain cases live.
- [Data](data.md) — the catalogue of sources, the expression language and the format specs these recipes lean on.
