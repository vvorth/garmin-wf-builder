#!/usr/bin/env python3
"""Generate face.yaml beside this script.

The YAML format has no variables, so every expression the face shares is
spelled out in full wherever it is used.  This script keeps each fragment
in one place and substitutes it, so the moon age read by the shadow discs,
the age needle, the tide and the spring/neap marker is one expression, and
the twenty second-time-zone layouts come out of one loop.

The astronomy itself is the watch's: `astro.day_of_year`, `astro.moon_age`,
`astro.equation_of_time`, `astro.sun_declination`, `astro.sidereal_time`
and `astro.sun_noon_altitude` (docs/guide/data.md, "Astronomy"), the UTC
offset is `time.utc_offset`, and only the calendar's ISO-week year-edge
arithmetic and the tide's lunitidal cycle are computed here.

Preview a particular sky with `wfb preview`'s own switches, for example
`--sample astro.moon_age=5`, `--date 2026-12-21 --time 12:00:00 --sample
time.utc_offset=0`, or `--style tz_tokyo`.
"""
import math
import sys

OUT = sys.argv[1] if len(sys.argv) > 1 else "examples/generated_by_skill/solaria/face.yaml"

# -- calendar ----------------------------------------------------------------
LEAP = "((date.year % 4 == 0 and date.year % 100 != 0) or date.year % 400 == 0)"
# day of the year, 1..366
N = "astro.day_of_year"
# ISO weekday, Monday = 1 .. Sunday = 7 (date.weekday is 1 = Sunday)
ISODOW = "((date.weekday + 5) % 7 + 1)"
# ISO week number: floor((N - isodow + 10) / 7), with the year-edge cases.
W0 = f"floor(({N} - {ISODOW} + 10) / 7)"


def jan1_dow(y):
    # Gauss: day of the week of 1 January, 0 = Sunday .. 6 = Saturday
    return f"((1 + 5 * (({y} - 1) % 4) + 4 * (({y} - 1) % 100) + 6 * (({y} - 1) % 400)) % 7)"


def leap_of(y):
    return f"((({y}) % 4 == 0 and ({y}) % 100 != 0) or ({y}) % 400 == 0)"


def has53(y):
    j = jan1_dow(y)
    return f"({j} == 4 or ({leap_of(y)} and {j} == 3))"


WEEK = (f"({W0} < 1 ? ({has53('date.year - 1')} ? 53 : 52) : "
        f"({W0} == 53 and not {has53('date.year')}) ? 1 : {W0})")

# -- moon ----------------------------------------------------------------------
LUN = "29.530588"
AGE = "astro.moon_age"                 # days, 0 at new .. 14.77 full .. 29.53
HALF = "14.765294"
# days into the current half-lunation: 0 at a syzygy, 7.38 at a quadrature
DSYZ = f"({AGE} - {HALF} * floor({AGE} / {HALF}))"
# spring tides within ~3 days of new/full moon
SPRING = f"(abs({DSYZ} - 7.382647) > 4.4)"
# minutes since the moon's last transit, over a 745-minute (12h25m) tidal cycle:
# the moon transits about 12:00 at new moon and 48.8 min later each day
TIDE = f"((floor(time.hour * 60 + time.minute - 720 - {AGE} * 48.8) % 745 + 745) % 745)"

# -- sun -----------------------------------------------------------------------
EOT = "astro.equation_of_time"         # minutes, apparent minus mean
DEC = "astro.sun_declination"          # degrees, + north
CULM = "((complication.sunrise + complication.sunset) / 2)"   # seconds, local clock
LST_SEC = "(astro.sidereal_time * 3600)"                      # seconds of sidereal day

SEASON = (f'({N} < 79 ? "WINTER" : {N} < 172 ? "SPRING" : {N} < 266 ? "SUMMER" : '
          f'{N} < 355 ? "AUTUMN" : "WINTER")')
# IAU constellation boundaries along the ecliptic, by day of the year
ZOD = (f'({N} < 20 ? "SGR" : {N} < 47 ? "CAP" : {N} < 70 ? "AQR" : {N} < 108 ? "PSC" : '
       f'{N} < 133 ? "ARI" : {N} < 172 ? "TAU" : {N} < 201 ? "GEM" : {N} < 222 ? "CNC" : '
       f'{N} < 259 ? "LEO" : {N} < 303 ? "VIR" : {N} < 327 ? "LIB" : {N} < 333 ? "SCO" : '
       f'{N} < 351 ? "OPH" : "SGR")')

DAY_NOW = ("(time.hour * 3600 + time.minute * 60 + time.second >= complication.sunrise and "
           "time.hour * 3600 + time.minute * 60 + time.second < complication.sunset)")


def pol(cx, cy, ang, r):
    """`at:` for a point at polar (ang, r) around (cx, cy), all in %r."""
    t = math.radians(ang)
    return f"{{ anchor: center, dx: {cx + r * math.sin(t):.1f}%r, dy: {cy - r * math.cos(t):.1f}%r }}"


def q(s):
    """A YAML single-quoted scalar."""
    return "'" + s.replace("'", "''") + "'"


# -- second time zone layouts -------------------------------------------------
# (entry, dial label of at most five letters, city, standard-time offset in
# hours east of UTC).  Standard time only: a zone's daylight saving is not
# applied, and the layout label says so.
CITIES = [
    ("hnl", "HNL", "Honolulu", -10),
    ("lax", "LA", "Los Angeles", -8),
    ("den", "DEN", "Denver", -7),
    ("chi", "CHI", "Chicago", -6),
    ("nyc", "NYC", "New York", -5),
    ("sao", "SAO", "São Paulo", -3),
    ("azo", "AZO", "Azores", -1),
    ("utc", "UTC", "UTC", 0),
    ("par", "PAR", "Paris", 1),
    ("cai", "CAI", "Cairo", 2),
    ("mow", "MOW", "Moscow", 3),
    ("dxb", "DXB", "Dubai", 4),
    ("khi", "KHI", "Karachi", 5),
    ("bom", "BOM", "Mumbai", 5.5),
    ("dac", "DAC", "Dhaka", 6),
    ("bkk", "BKK", "Bangkok", 7),
    ("hkg", "HKG", "Hong Kong", 8),
    ("tokyo", "TOKYO", "Tokyo", 9),
    ("syd", "SYD", "Sydney", 10),
    ("akl", "AKL", "Auckland", 12),
]


def offset_label(hours):
    sign = "-" if hours < 0 else "+"
    whole, frac = divmod(abs(hours), 1)
    return f"{sign}{int(whole)}" + (f":{int(frac * 60):02d}" if frac else "")


layouts = []
styles = []
for entry, dial, city, hours in CITIES:
    lid = f"tz_{entry}"
    off = int(round(hours * 3600))
    # seconds since the zone's midnight: local clock to UTC through the
    # watch's own offset, then to the zone; `+ 86400` keeps `%` positive
    zone_sec = (f"(((time.hour * 3600 + time.minute * 60 - time.utc_offset "
                f"{'-' if off < 0 else '+'} {abs(off)}) % 86400 + 86400) % 86400)")
    zone_min = f"({zone_sec} / 60)"
    zone_h = f"({zone_sec} / 3600)"
    layouts.append(f"""  {lid}:
    label: "{city} {offset_label(hours)} (standard time)"
    elements:
      {lid}_hand:
        type: gauge
        style: needle
        value: {q(zone_min)}
        max: 1440
        at: {{ anchor: center, dx: 43.5%r, dy: -10%r }}
        start_angle: 0deg
        sweep: 360deg
        color: {q(f'({zone_h} >= 6 and {zone_h} < 18) ? color.gold : color.grey')}
        needle:
          blade: {{ type: line, at: {{ dy: 3%r }}, to: {{ dy: -18.5%r }}, thickness: 2px }}
          hub: {{ type: circle, radius: 1.5%r }}
      {lid}_label:
        type: text
        text: "{dial}"
        font: font.t7
        at: {{ anchor: center, dx: 43.5%r, dy: 1%r }}
        color: color.grey
""")
    styles.append(f'      {lid}: {{ label: "2nd zone · {city}", layout: {lid} }}')

yaml = f"""# Solaria -- every front-dial indication of the Vacheron Constantin Les
# Cabinotiers Solaria Ultra Grand Complication that a Garmin watch face can
# compute from the clock, the calendar, the watch's astronomy (astro.*),
# the position of its weather report and the sunrise/sunset complications.
#
# Generated by gen.py beside this file (the shared expressions are
# fragments there); edit the generator, then rerun it.
#
# yaml-language-server: $schema=../../../schema/wfb-face-2.schema.json

format: 2

face:
  id: 7eacd6b4-4002-419b-a30c-c657db09743c
  name: Solaria
  version: 1.0.0

build:
  targets: [fenix8solar47mm, fenix8solar51mm]

resources:
  palette:
    bg: "#000000"
    white: "#FFFFFF"
    grey: "#AAAAAA"
    dim: "#555555"
    gold: "#FFAA00"
    red: "#FF0000"
    green: "#00AA55"

  fonts:
    t7: {{ face: [RobotoCondensedBold], size: 7%r }}
    t8: {{ face: [RobotoCondensedBold], size: 8%r }}
    t9: {{ face: [RobotoCondensedBold], size: 9%r }}

  hand_sets:
    main:
      hour:
        color: color.white
        parts:
          blade:
            # a baton: a slim stem, then a parallel blade to a pointed tip
            type: polygon
            mirror: x
            points:
              - {{ dx: -1.3%r, dy: 8%r }}
              - {{ dx: -1.3%r, dy: -12%r }}
              - {{ dx: -2.8%r, dy: -17%r }}
              - {{ dx: -2.8%r, dy: -50%r }}
              - {{ dy: -58%r }}
          facet:
            type: polygon
            mirror: x
            color: color.dim
            points:
              - {{ dx: -0.9%r, dy: -18%r }}
              - {{ dx: -0.9%r, dy: -49%r }}
              - {{ dy: -53%r }}
      minute:
        color: color.white
        parts:
          blade:
            type: polygon
            mirror: x
            points:
              - {{ dx: -1.2%r, dy: 8%r }}
              - {{ dx: -1.2%r, dy: -14%r }}
              - {{ dx: -2.5%r, dy: -19%r }}
              - {{ dx: -2.5%r, dy: -78%r }}
              - {{ dy: -86%r }}
          facet:
            type: polygon
            mirror: x
            color: color.dim
            points:
              - {{ dx: -0.8%r, dy: -20%r }}
              - {{ dx: -0.8%r, dy: -77%r }}
              - {{ dy: -81%r }}

# ----------------------------------------------------------------------------
# Fixed furniture: drawn once into the static buffer.
static:
  background:
    type: rectangle
    at: {{ anchor: center }}
    size: {{ width: 100%, height: 100% }}
    color: color.bg

  # -- periphery: a 24-hour sun dial, midnight at the bottom, noon at the top --
  rim_ring:
    type: circle
    at: {{ anchor: center }}
    radius: 95%r
    filled: false
    thickness: 5.5%r
    color: color.white
  rim_hours:
    type: pattern
    pattern: radial
    at: {{ anchor: center }}
    count: 24
    start: 180deg
    color: color.white
    parts:
      tick: {{ type: line, at: {{ dy: -93.5%r }}, to: {{ dy: -91%r }}, thickness: 1px }}
  rim_numerals:
    type: pattern
    pattern: radial
    at: {{ anchor: center }}
    count: 12
    start: 180deg
    skip: [0]
    color: color.bg
    lint: {{ allow: [contrast, safe-area, off-screen], reason: "black on the white ring beneath, which the lint does not see; the numerals' box corners cross the rim, their ink does not" }}
    parts:
      numeral:
        type: text
        text: "{{copy * 2}}"
        font: font.t7
        at: {{ dy: -94%r }}

  # -- 12 o'clock: perpetual calendar ------------------------------------------
  cal_ring:
    type: circle
    at: {{ anchor: center, dy: -57%r }}
    radius: 25.5%r
    filled: false
    thickness: 8.5%r
    color: color.white
  cal_week_ring:
    type: circle
    at: {{ anchor: center, dy: -57%r }}
    radius: 31.5%r
    filled: false
    thickness: 1px
    color: color.dim
    lint: {{ allow: [contrast], reason: "subdued by design: a night tone, not a reading" }}
  cal_week_marks:
    type: pattern
    pattern: radial
    at: {{ anchor: center, dy: -57%r }}
    count: 4
    color: color.green
    parts:
      tick: {{ type: line, at: {{ dy: -30.5%r }}, to: {{ dy: -32.5%r }}, thickness: 2px }}
  cal_ticks:
    type: pattern
    pattern: radial
    at: {{ anchor: center, dy: -57%r }}
    count: 31
    step_angle: 11.6129deg
    color: color.bg
    parts:
      tick: {{ type: line, at: {{ dy: -29.75%r }}, to: {{ dy: -27.5%r }}, thickness: 1px }}
  cal_numerals:
    type: pattern
    pattern: radial
    at: {{ anchor: center, dy: -57%r }}
    count: 6
    start: 46.4516deg
    step_angle: 58.0645deg
    color: color.bg
    lint: {{ allow: [contrast], reason: "black on the white ring beneath, which the lint does not see" }}
    parts:
      numeral: {{ type: text, text: "{{copy * 5 + 5}}", font: font.t7, at: {{ dy: -24.5%r }} }}
  cal_one:
    type: text
    text: "1"
    font: font.t7
    at: {{ anchor: center, dy: -81.5%r }}
    color: color.bg
    lint: {{ allow: [contrast], reason: "black on the white ring beneath, which the lint does not see" }}

  # -- 3 o'clock: second time zone, 24 h, midnight at the top ------------------
  tz_night:
    type: arc
    at: {{ anchor: center, dx: 43.5%r, dy: -10%r }}
    radius: 23%r
    thickness: 6.5%r
    start_angle: 270deg
    sweep: 180deg
    color: color.dim
    lint: {{ allow: [contrast], reason: "subdued by design: a night tone, not a reading" }}
  tz_day:
    type: arc
    at: {{ anchor: center, dx: 43.5%r, dy: -10%r }}
    radius: 23%r
    thickness: 6.5%r
    start_angle: 90deg
    sweep: 180deg
    color: color.white
  tz_ticks:
    type: pattern
    pattern: radial
    at: {{ anchor: center, dx: 43.5%r, dy: -10%r }}
    count: 12
    color: color.grey
    parts:
      tick: {{ type: line, at: {{ dy: -19%r }}, to: {{ dy: -17%r }}, thickness: 1px }}
  tz_numerals:
    # even hours on the ring: white over the night half, black over the day half
    type: pattern
    pattern: radial
    at: {{ anchor: center, dx: 43.5%r, dy: -10%r }}
    count: 12
    skip: [3, 9]
    color: "copy > 3 and copy < 9 ? color.bg : color.white"
    lint: {{ allow: [contrast], reason: "black on the white ring beneath, which the lint does not see" }}
    parts:
      numeral: {{ type: text, text: "{{(copy == 0 ? 24 : copy * 2)}}", font: font.t7, at: {{ dy: -23%r }} }}
  tz_6: {{ type: text, text: "6", font: font.t7, at: {{ anchor: center, dx: 20.5%r, dy: -10%r }}, color: color.gold }}
  tz_18: {{ type: text, text: "18", font: font.t7, at: {{ anchor: center, dx: 66.5%r, dy: -10%r }}, color: color.gold }}

  # -- 9 o'clock: moon age scale, tide ----------------------------------------
  moon_scale:
    type: arc
    at: {{ anchor: center, dx: -43.5%r, dy: -10%r }}
    radius: 24.5%r
    thickness: 3%r
    start_angle: 285deg
    sweep: 150deg
    color: color.white
  moon_scale_ticks:
    type: pattern
    pattern: radial
    at: {{ anchor: center, dx: -43.5%r, dy: -10%r }}
    count: 7
    start: 285deg
    step_angle: 25deg
    color: color.bg
    parts:
      tick: {{ type: line, at: {{ dy: -26%r }}, to: {{ dy: -23%r }}, thickness: 1px }}
  moon_0: {{ type: text, text: "0", font: font.t7, at: {pol(-43.5, -10.0, 285.0, 30.0)}, color: color.grey }}
  moon_15: {{ type: text, text: "15", font: font.t7, at: {pol(-43.5, -10.0, 0.0, 30.0)}, color: color.grey }}
  moon_29: {{ type: text, text: "29", font: font.t7, at: {pol(-43.5, -10.0, 75.0, 30.0)}, color: color.grey }}
  tide_high: {{ type: text, text: "HIGH", font: font.t7, at: {{ anchor: center, dx: -43.5%r, dy: -1.5%r }}, color: color.grey }}
  tide_low: {{ type: text, text: "LOW", font: font.t7, at: {{ anchor: center, dx: -43.5%r, dy: 20%r }}, color: color.grey }}
  tide_ring:
    type: circle
    at: {{ anchor: center, dx: -43.5%r, dy: 9%r }}
    radius: 6%r
    filled: false
    thickness: 1px
    color: color.dim
    lint: {{ allow: [contrast], reason: "subdued by design: a night tone, not a reading" }}

  # -- 6 o'clock: solar counter ----------------------------------------------
  eot_scale:
    type: arc
    at: {{ anchor: center, dy: 44%r }}
    radius: 26%r
    thickness: 1.5%r
    start_angle: 300deg
    sweep: 120deg
    color: color.white
  eot_ticks:
    type: pattern
    pattern: radial
    at: {{ anchor: center, dy: 44%r }}
    count: 3
    start: 300deg
    step_angle: 60deg
    color: color.white
    parts:
      tick: {{ type: line, at: {{ dy: -27%r }}, to: {{ dy: -24%r }}, thickness: 1px }}
  eot_minus: {{ type: text, text: "-16", font: font.t7, at: {pol(0.0, 44.0, 292.0, 17.5)}, color: color.grey }}
  eot_plus: {{ type: text, text: "+14", font: font.t7, at: {pol(0.0, 44.0, 68.0, 17.5)}, color: color.grey }}
  eot_label:
    type: text
    text: "EQUATION"
    font: font.t7
    at: {{ anchor: center, dy: 44%r }}
    color: color.grey
    curve: {{ style: radial, angle: 0deg, radius: 29.5%r, direction: clockwise }}
  dec_scale:
    type: arc
    at: {{ anchor: center, dy: 44%r }}
    radius: 26%r
    thickness: 1.5%r
    start_angle: 65deg
    sweep: 60deg
    color: color.red
  dec_ticks:
    type: pattern
    pattern: radial
    at: {{ anchor: center, dy: 44%r }}
    count: 3
    start: 65deg
    step_angle: 30deg
    color: color.red
    parts:
      tick: {{ type: line, at: {{ dy: -27%r }}, to: {{ dy: -24%r }}, thickness: 1px }}
  dec_s: {{ type: text, text: "S", font: font.t7, at: {pol(0.0, 44.0, 56.0, 23.0)}, color: color.red }}
  dec_n: {{ type: text, text: "N", font: font.t7, at: {pol(0.0, 44.0, 131.0, 23.5)}, color: color.red }}
  earth:
    type: circle
    at: {{ anchor: center, dy: 44%r }}
    radius: 6.5%r
    color: color.grey
  earth_meridian:
    type: line
    at: {{ anchor: center, dy: 37.5%r }}
    to: {{ anchor: center, dy: 50.5%r }}
    thickness: 1px
    color: color.dim
    lint: {{ allow: [contrast], reason: "subdued by design: a night tone, not a reading" }}
  dec_label:
    type: text
    text: "DECL"
    font: font.t7
    at: {{ anchor: center, dy: 44%r }}
    color: color.grey
    curve: {{ style: radial, angle: 97deg, radius: 29.5%r, direction: clockwise }}
  culm_label:
    type: text
    text: "CULM"
    font: font.t7
    at: {{ anchor: center, dy: 44%r }}
    color: color.grey
    curve: {{ style: radial, angle: 232deg, radius: 29.5%r, direction: counter_clockwise }}
  sid_label: {{ type: text, text: "SIDEREAL", font: font.t7, at: {{ anchor: center, dx: -58%r, dy: 31%r }}, color: color.grey }}
  res_label: {{ type: text, text: "RESERVE", font: font.t7, at: {{ anchor: center, dx: 58%r, dy: 31%r }}, color: color.grey }}

# ----------------------------------------------------------------------------
elements:
  # -- periphery: night over the gold band, sunrise/sunset pointers, the sun --
  night_before_sunrise:
    # midnight to sunrise, painted over the static white ring (no track of its own)
    type: gauge
    style: arc
    value: complication.sunrise
    max: 86400
    at: {{ anchor: center }}
    radius: 95%r
    thickness: 5.5%r
    start_angle: 180deg
    sweep: 360deg
    color: color.dim
    absent: hide
    lint: {{ allow: [contrast], reason: "subdued by design: a night tone, not a reading" }}
  night_after_sunset:
    type: gauge
    style: arc
    value: 86400 - complication.sunset
    max: 86400
    at: {{ anchor: center }}
    radius: 95%r
    thickness: 5.5%r
    start_angle: 180deg
    sweep: -360deg
    color: color.dim
    absent: hide
    lint: {{ allow: [contrast], reason: "subdued by design: a night tone, not a reading" }}
  rim_night_numerals:
    # the even hours that fall in the night, white over the grey sector (the
    # static black copies underneath are covered exactly)
    type: pattern
    pattern: radial
    at: {{ anchor: center }}
    count: 12
    start: 180deg
    skip: [0]
    color: color.white
    absent: hide
    lint: {{ allow: [safe-area, off-screen], reason: "the numerals' box corners cross the rim, their ink does not" }}
    parts:
      numeral:
        type: text
        text: "{{copy * 2}}"
        font: font.t7
        at: {{ dy: -94%r }}
        visible: "copy * 7200 < complication.sunrise or copy * 7200 >= complication.sunset"
  sunrise_pointer:
    type: gauge
    style: needle
    value: complication.sunrise
    max: 86400
    at: {{ anchor: center }}
    start_angle: 180deg
    sweep: 360deg
    color: color.gold
    absent: {{ value: 0.25 }}
    needle:
      tip:
        type: polygon
        points: [{{ dx: -2.2%r, dy: -85%r }}, {{ dy: -90.5%r }}, {{ dx: 2.2%r, dy: -85%r }}]
  sunset_pointer:
    type: gauge
    style: needle
    value: complication.sunset
    max: 86400
    at: {{ anchor: center }}
    start_angle: 180deg
    sweep: 360deg
    color: color.gold
    absent: {{ value: 0.75 }}
    needle:
      tip:
        type: polygon
        points: [{{ dx: -2.2%r, dy: -85%r }}, {{ dy: -90.5%r }}, {{ dx: 2.2%r, dy: -85%r }}]
  sun_position:
    type: gauge
    style: needle
    value: time.hour * 3600 + time.minute * 60
    max: 86400
    at: {{ anchor: center }}
    start_angle: 180deg
    sweep: 360deg
    color: color.gold
    needle:
      sun: {{ type: circle, at: {{ dy: -94.5%r }}, radius: 2.5%r }}
      sun_rim: {{ type: circle, at: {{ dy: -94.5%r }}, radius: 3.1%r, filled: false, thickness: 1px, color: color.bg }}
  sun_night:
    # painted over the gold sun between sunset and sunrise: day/night for the reference city
    type: gauge
    style: needle
    value: time.hour * 3600 + time.minute * 60
    max: 86400
    at: {{ anchor: center }}
    start_angle: 180deg
    sweep: 360deg
    color: color.bg
    visible: {q(f'not {DAY_NOW}')}
    needle:
      sun: {{ type: circle, at: {{ dy: -94.5%r }}, radius: 2.5%r }}
      sun_rim: {{ type: circle, at: {{ dy: -94.5%r }}, radius: 3.1%r, filled: false, thickness: 1px, color: color.white }}
    lint: {{ allow: [contrast], reason: "subdued by design: a night tone, not a reading" }}

  # -- 12 o'clock: perpetual calendar ------------------------------------------
  calendar:
    type: group
    at: {{ anchor: center, dy: -57%r }}
    size: {{ width: 44%r, height: 44%r }}
    on_hold: date
    children:
      year: {{ type: text, text: "{{date.year:d}}", font: font.t8, at: {{ anchor: center, dx: -3%r, dy: -12%r }}, color: color.white }}
      leap:
        type: text
        text: "LY"
        font: font.t7
        at: {{ anchor: center, dx: 13%r, dy: -12%r }}
        color: color.green
        visible: {q(LEAP)}
      weekday: {{ type: text, text: "{{date.today:%a}}", font: font.t8, at: {{ anchor: center, dx: -10.5%r }}, color: color.white }}
      month: {{ type: text, text: "{{date.today:%b}}", font: font.t8, at: {{ anchor: center, dx: 10.5%r }}, color: color.white }}
      week_day:
        type: text
        text: {q('W{' + WEEK + ':d} D{' + ISODOW + ':d}')}
        font: font.t7
        at: {{ anchor: center, dy: 11%r }}
        color: color.green
  date_hand:
    type: gauge
    style: needle
    value: date.day - 1
    max: 30
    at: {{ anchor: center, dy: -57%r }}
    start_angle: 0deg
    sweep: 348.387deg
    color: color.red
    needle:
      blade: {{ type: line, at: {{ dy: 4%r }}, to: {{ dy: -23%r }}, thickness: 2px }}
      hub: {{ type: circle, radius: 1.5%r }}
  week_hand:
    type: gauge
    style: needle
    value: {q(WEEK + ' - 1')}
    max: 52
    at: {{ anchor: center, dy: -57%r }}
    start_angle: 0deg
    sweep: 360deg
    color: color.green
    needle:
      tip: {{ type: line, at: {{ dy: -29.5%r }}, to: {{ dy: -33.5%r }}, thickness: 2px }}

  # -- 9 o'clock: moon phase and age, tide, spring/neap -----------------------
  moon_disc:
    type: circle
    at: {{ anchor: center, dx: -43.5%r, dy: -16.5%r }}
    radius: 6.5%r
    color: color.white
  # The dark half: a shadow disc swung across the moon by a needle gauge
  # (the one data-driven position the format has).  Northern-hemisphere
  # view: waxing, a shadow on an axis 36%r below the moon moves left from
  # the moon's centre until clear of it over the first half lunation (the
  # lit side grows from the right); waning, a second one comes in from the
  # right over the second half.
  moon_waxing:
    type: gauge
    style: needle
    value: {AGE}
    max: {HALF}
    at: {{ anchor: center, dx: -43.5%r, dy: 20%r }}
    start_angle: 0deg
    sweep: -21.2deg
    color: color.bg
    visible: {q(f'{AGE} < {HALF}')}
    needle:
      shadow: {{ type: circle, at: {{ dy: -36.5%r }}, radius: 6.7%r }}
  moon_waning:
    type: gauge
    style: needle
    value: {q(f'{AGE} - {HALF}')}
    max: {HALF}
    at: {{ anchor: center, dx: -43.5%r, dy: 20%r }}
    start_angle: 21.2deg
    sweep: -21.2deg
    color: color.bg
    visible: {q(f'{AGE} >= {HALF}')}
    needle:
      shadow: {{ type: circle, at: {{ dy: -36.5%r }}, radius: 6.7%r }}
  moon_age_hand:
    type: gauge
    style: needle
    value: {AGE}
    max: {LUN}
    at: {{ anchor: center, dx: -43.5%r, dy: -10%r }}
    start_angle: 285deg
    sweep: 150deg
    color: color.gold
    needle:
      tip: {{ type: line, at: {{ dy: -21%r }}, to: {{ dy: -27.5%r }}, thickness: 2px }}
  tide_hand:
    type: gauge
    style: needle
    value: {q(TIDE)}
    max: 745
    at: {{ anchor: center, dx: -43.5%r, dy: 9%r }}
    start_angle: 0deg
    sweep: 360deg
    color: color.gold
    needle:
      blade: {{ type: line, at: {{ dy: 1.5%r }}, to: {{ dy: -5.5%r }}, thickness: 2px }}
      hub: {{ type: circle, radius: 1.2%r }}
  spring:
    type: text
    text: "ST"
    font: font.t7
    at: {{ anchor: center, dx: -57.5%r, dy: 9%r }}
    color: {q(f'{SPRING} ? color.green : color.dim')}
  neap:
    type: text
    text: "NT"
    font: font.t7
    at: {{ anchor: center, dx: -29.5%r, dy: 9%r }}
    color: {q(f'{SPRING} ? color.dim : color.green')}

  # -- 6 o'clock: solar counter ----------------------------------------------
  eot_hand:
    type: gauge
    style: needle
    value: {q(f'{EOT} + 16')}
    max: 30
    at: {{ anchor: center, dy: 44%r }}
    start_angle: 300deg
    sweep: 120deg
    color: color.gold
    needle:
      blade: {{ type: line, at: {{ dy: 0%r }}, to: {{ dy: -25%r }}, thickness: 2px }}
  dec_hand:
    type: gauge
    style: needle
    value: {q(f'{DEC} + 23.44')}
    max: 46.88
    at: {{ anchor: center, dy: 44%r }}
    start_angle: 65deg
    sweep: 60deg
    color: color.red
    needle:
      blade: {{ type: line, at: {{ dy: 0%r }}, to: {{ dy: -25%r }}, thickness: 2px }}
  height:
    # the sun's height at culmination, 0 .. 90 degrees over the left sector;
    # the whole scale goes with the reading, which needs a position
    type: group
    at: {{ anchor: center, dy: 44%r }}
    size: {{ width: 66%r, height: 66%r }}
    visible: "astro.sun_noon_altitude <= 90"
    children:
      scale:
        type: arc
        at: {{ anchor: center }}
        radius: 26%r
        thickness: 1.5%r
        start_angle: 240deg
        sweep: 60deg
        color: color.white
      ticks:
        type: pattern
        pattern: radial
        at: {{ anchor: center }}
        count: 3
        start: 240deg
        step_angle: 30deg
        color: color.white
        parts:
          tick: {{ type: line, at: {{ dy: -27%r }}, to: {{ dy: -24%r }}, thickness: 1px }}
      zero: {{ type: text, text: "0", font: font.t7, at: {pol(0.0, 0.0, 248.0, 17.5)}, color: color.grey }}
      ninety: {{ type: text, text: "90", font: font.t7, at: {pol(0.0, 0.0, 304.5, 32.0)}, color: color.grey }}
      label:
        type: text
        text: "HEIGHT"
        font: font.t7
        at: {{ anchor: center }}
        color: color.grey
        curve: {{ style: radial, angle: 275deg, radius: 29.5%r, direction: clockwise }}
      hand:
        type: gauge
        style: needle
        value: astro.sun_noon_altitude
        max: 90
        at: {{ anchor: center }}
        start_angle: 240deg
        sweep: 60deg
        color: color.white
        absent: hide
        needle:
          blade: {{ type: line, at: {{ dy: 0%r }}, to: {{ dy: -25%r }}, thickness: 2px }}
  sol_hub: {{ type: circle, at: {{ anchor: center, dy: 44%r }}, radius: 1.5%r, color: color.white }}
  culmination:
    type: text
    text: {q('{' + CULM + ':%H:%M}')}
    font: font.t8
    at: {{ anchor: center, dx: -15%r, dy: 65%r }}
    color: color.white
    absent: {{ text: "--:--" }}
  season:
    type: text
    text: {q('{' + SEASON + '}')}
    font: font.t7
    at: {{ anchor: center, dx: 1%r, dy: 56%r }}
    color: color.grey
  zodiac:
    type: text
    text: {q('{' + ZOD + '}')}
    font: font.t8
    at: {{ anchor: center, dx: 15%r, dy: 65%r }}
    color: color.white

  # -- between the counters --------------------------------------------------
  sidereal:
    type: text
    text: {q('{' + LST_SEC + ':%H:%M}')}
    font: font.t8
    at: {{ anchor: center, dx: -58%r, dy: 40%r }}
    color: color.white
    absent: {{ text: "--:--" }}
  reserve:
    type: gauge
    style: arc
    value: system.battery
    max: 100
    at: {{ anchor: center, dx: 58%r, dy: 45%r }}
    radius: 9%r
    thickness: 3%r
    start_angle: 265deg
    sweep: 190deg
    color: "system.battery < 20 ? color.red : color.green"
    track_color: color.dim
    on_hold: battery
  reserve_value:
    type: text
    text: "{{system.battery:d}}"
    font: font.t7
    at: {{ anchor: center, dx: 58%r, dy: 46%r }}
    color: color.white
  alarm:
    type: icon
    icon: alarm
    size: 7%r
    at: {{ anchor: center, dx: 50%r, dy: 61%r }}
    color: color.grey
    visible: "device.alarm_count > 0"
  dnd:
    type: icon
    icon: dnd
    size: 7%r
    at: {{ anchor: center, dx: 62%r, dy: 61%r }}
    color: color.grey
    visible: "device.do_not_disturb"
  sunrise:
    type: group
    at: {{ anchor: center, dx: -31%r, dy: 72%r }}
    size: {{ width: 32%r, height: 10%r }}
    on_hold: sunrise
    children:
      sunrise_icon: {{ type: icon, icon: sunrise, size: 7%r, at: {{ anchor: left }}, align: left, color: color.gold }}
      sunrise_time:
        type: text
        text: "{{complication.sunrise:%H:%M}}"
        font: font.t8
        at: {{ anchor: right }}
        align: right
        color: color.white
        absent: {{ text: "--:--" }}
  sunset:
    type: group
    at: {{ anchor: center, dx: 31%r, dy: 72%r }}
    size: {{ width: 32%r, height: 10%r }}
    on_hold: sunset
    children:
      sunset_icon: {{ type: icon, icon: sunset, size: 7%r, at: {{ anchor: left }}, align: left, color: color.gold }}
      sunset_time:
        type: text
        text: "{{complication.sunset:%H:%M}}"
        font: font.t8
        at: {{ anchor: right }}
        align: right
        color: color.white
        absent: {{ text: "--:--" }}
  day_length:
    type: text
    text: "{{complication.sunset - complication.sunrise:%-Hh%M}}"
    font: font.t7
    at: {{ anchor: center, dy: 82%r }}
    color: color.grey
    absent: {{ text: "--" }}

  # -- the hands -------------------------------------------------------------
  hands:
    type: hands
    set: main
    at: {{ anchor: center }}
    outline: {{ color: color.bg }}
    lint: {{ allow: [contrast], reason: "a background-coloured ring parts the hands from the white rings; the dark facet is the hands lume channel" }}
  hub: {{ type: circle, at: {{ anchor: center }}, radius: 4.5%r, color: color.grey }}
  hub_ring: {{ type: circle, at: {{ anchor: center }}, radius: 4.5%r, filled: false, thickness: 1px, color: color.white }}
  hub_pin: {{ type: circle, at: {{ anchor: center }}, radius: 1.5%r, color: color.bg }}

# ----------------------------------------------------------------------------
# The second time zone: one layout per city, each hand reading the zone's
# clock from the watch's own UTC offset, picked on the Styles axis.
layouts:
{"".join(layouts)}
config:
  style:
    default: tz_utc
    choices:
{chr(10).join(styles)}
"""

with open(OUT, "w") as f:
    f.write(yaml)
print(f"wrote {OUT} ({len(yaml)} bytes)")
