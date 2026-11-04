# 36 — Icon rules: one table from a source's reading to a glyph

**Status: planned, not started. D1–D9 decided (2026-11-04).** Delete this
file once every slice has shipped (`docs/CLAUDE.md`).

## 0. Why

A dynamic icon (`icon: {for:}`, a slot's icon, a `type: data` element's
icon) is "a reading → a catalogue name → a glyph". Three families exist
today and each is wired by hand, in different places:

| family | sources | tables | watch | preview |
|---|---|---|---|---|
| weather condition | `weather.condition*` (`catalog.json`'s `weather_condition_sources`) | `GARMIN_WEATHER_CONDITION_ICON` (`icons.json`) | `runtime-lib/WfbWeather.mc`, hand-written, twin-checked by `barrel.test.ts` | `icons.chooseWeatherIcon` |
| level (0–100) | `icons.LEVEL_SOURCES` | `icons.LEVEL_ICONS` | generated `IconGlyphs.<x>Level()` | `icons.levelIconName` |
| count (empty at 0) | `icons.COUNT_SOURCES` | `icons.COUNT_ICONS` | generated `IconGlyphs.<x>Count()` | `icons.countIconName` |

And a complication *type* carries its own copy of the choice, keyed by
type name rather than source: `complications.ICON_CONDITION`,
`ICON_WHEN_ZERO`, `ICON_LEVEL`, read by `ConfigDataSlot.conditionIcons`/
`zeroIcons`/`levelIcons`, two per-family loops in `kinds/data.ts`
(`slotSampleGlyph`, `slotIconRun`), per-family `case` lines in
`emit/monkeyc/data.ts`, three branches in `kinds/icon.ts` (`forSources`,
`dynamicTag`, `dynamicReference`, `textRuns`, `lower`, `describe`), two
`IconChoice` cases in `draw/evaluator.ts` and `draw/printer.ts`, and three
hand-written capability strings in `studio/inspect.ts`. Adding the count
family (commit 02aa027) touched ten files. The editor cannot offer `for:`
at all: nothing tells it which sources qualify (`docs/guide/studio.md`,
"a key written in a shape its control does not take").

The user's framing (2026-11-04): *the rule should be the source's own
property, next to the source, not a separate piece of code that knows
about the source.* This plan builds that: one declarative rule per source,
every consumer reading it, and the editor listing it.

## 1. Decisions

### Decided (2026-11-04)

- **D1: two rule kinds, `steps` and `table`.** A `steps` rule orders its
  glyphs along a numeric reading, split one of two ways:
  - equal `bands` over `range: [lo, hi]`, the reading truncated into
    one and clamped (battery 5 over 0–100, solar 9, moon 8 over 0–29.53,
    cyclic, see D3);
  - `thresholds: [t…]`, band *k* being the count of thresholds `≤`
    reading: a count is `thresholds: [1]` (0 / 1+), a boolean is read as
    0/1 with the same threshold.
  On/off icons are a two-step `steps`, not a kind of their own. A
  `table` rule maps an enumeration's values to names one by one (the 54
  `Weather.CONDITION_*` values), with `unknown` for a value outside the
  map; it stays its own kind because its glyphs have no order and no
  reading falls "between" two of them.
- **D2: the first new rules are notifications, alarms, do-not-disturb,
  phone, moon phase.** Not day/night from `astro.sun_altitude`, not a
  charging icon (`visible: system.charging` + a fixed `battery_charging`
  icon is the author's job, and layering it on the battery level would
  be a composite rule this plan does not build).
- **D3: moon phases are the MDI set** (`md-moon_new` U+F0F64,
  `_waxing_crescent` U+F0F67, `_first_quarter` U+F0F61,
  `_waxing_gibbous` U+F0F68, `_full` U+F0F62, `_waning_gibbous` U+F0F66,
  `_last_quarter` U+F0F63, `_waning_crescent` U+F0F65), reviewed against
  the Weather Icons set on a baked sheet: MDI's crescents read at small
  sizes, Weather Icons' thin ones do not. Eight equal bands over
  `astro.moon_age`'s 0–29.53 d, **cyclic and centred**: band 0 is the
  half-band either side of 0 (new moon), so age 28.5 is new, not waning
  crescent. A new `cyclic: true` flag on the rule; nothing else uses it.
- **D4: do-not-disturb is `bell` (off) / `bell_off` (on)**, `md-bell`
  U+F009A and the catalogue's existing `dnd` glyph (`md-bell_off`
  U+F009B). `dnd` keeps its name as the plain icon; `bell` is a new
  catalogue entry. Alarms: `alarm` (existing, `md-alarm` U+F0020) /
  `alarm_off` (`md-alarm_off` U+F0023) with `thresholds: [1]` on
  `device.alarm_count` — 0 alarms shows the struck one. Phone:
  `phone_connected` (`md-bluetooth` U+F00AF) / `phone_disconnected`
  (`md-bluetooth_off` U+F00B2) on `device.phone_connected`, what
  Garmin's own status row uses. Notifications keep
  `notification`/`notification_none`.
- **D5: `absent:` on `type: icon`**, `hide` or `{icon: <name or
  {codepoint:}>}`, on an icon with `for:` or `slot:` only (a fixed icon
  has no reading). No `absent:` keeps today's behaviour, the rule's
  `plain` glyph. `hide` is kept: it costs nothing and is the vocabulary
  every other element has. `{text:}` and `{value:}` are refused with an
  error naming `{icon:}`. On a slot icon it applies when the *pick's*
  reading is absent, the one case where a slot icon follows the reading
  rather than the type.
- **D6: the rule lives in `icons.json`, keyed by source path.**
  `catalog.json` describes how a source is *read*; `icons.json` already
  owns every name → glyph fact, and the rule is one more. A complication
  type has no rule of its own: it inherits its `complication.<type>`
  source's (`ICON_CONDITION`'s "a temperature follows the current
  condition" becomes a `follows: weather.condition` field on that
  source's rule).
- **D7: the weather table is generated from the rule** like every other
  chooser; `runtime-lib/WfbWeather.mc` and its twin test in
  `barrel.test.ts` go. Measured cost to check in slice 1: the generated
  `IconGlyphs.weatherCondition()` against today's `WfbWeather.chooseIcon`
  on the showcase face, `--build-stats 0`; expected within a few bytes
  (same 54 `case`s, one module instead of two).
- **D8: the editor lists rules from the same table** (slice 5): the icon
  picker's third tab, "follows data", one row per source with a rule,
  shown as the strip of glyphs it can draw.
- **D9: output must not move where the rule is unchanged.** Battery,
  solar and count icons, and every slot icon, produce byte-identical
  Monkey C and pixels after the refactor; the goldens prove it. Only the
  weather chooser's home changes (D7), and that is the one golden diff
  slice 1 may carry.

## 2. The rule

In `icons.json`, beside `catalog`, `garmin_weather_condition_icon` (which
becomes the weather rule's `map`) and `complication_icon`:

```json
"rules": {
  "battery": {
    "kind": "steps", "label": "Battery", "plain": "battery",
    "sources": ["system.battery", "complication.battery"],
    "range": [0, 100], "steps": ["battery_level_0", "battery_level_1", "battery_level_2", "battery_level_3", "battery_level_4"]
  },
  "solar": {
    "kind": "steps", "label": "Solar input", "plain": "solar",
    "sources": ["complication.solar_input"],
    "range": [0, 100], "steps": ["solar_level_0", "…", "solar_level_8"]
  },
  "notification": {
    "kind": "steps", "label": "Notifications", "plain": "notification",
    "sources": ["device.notification_count", "complication.notification_count"],
    "thresholds": [1], "steps": ["notification_none", "notification"]
  },
  "alarm": { "kind": "steps", "label": "Alarms", "plain": "alarm", "sources": ["device.alarm_count"], "thresholds": [1], "steps": ["alarm_off", "alarm"] },
  "dnd": { "kind": "steps", "label": "Do not disturb", "plain": "bell", "sources": ["device.do_not_disturb"], "thresholds": [1], "steps": ["bell", "dnd"] },
  "phone": { "kind": "steps", "label": "Phone", "plain": "phone_connected", "sources": ["device.phone_connected"], "thresholds": [1], "steps": ["phone_disconnected", "phone_connected"] },
  "moon": {
    "kind": "steps", "label": "Moon phase", "plain": "moon_new",
    "sources": ["astro.moon_age"],
    "range": [0, 29.530588], "cyclic": true,
    "steps": ["moon_new", "moon_waxing_crescent", "moon_first_quarter", "moon_waxing_gibbous", "moon_full", "moon_waning_gibbous", "moon_last_quarter", "moon_waning_crescent"]
  },
  "weather": {
    "kind": "table", "label": "Weather", "plain": "weather_unknown",
    "sources": ["weather.condition", "weather.condition_today", "weather.condition_tomorrow",
                "complication.current_weather", "complication.forecast_weather_1day", "complication.forecast_weather_2day", "complication.forecast_weather_3day"],
    "map": { "0": "weather_sunny", "…": "…", "53": "weather_unknown" },
    "follows": { "complication.current_temperature": "weather.condition", "complication.high_low_temperature": "weather.condition_today" }
  }
}
```

A `steps` rule has `steps` and exactly one of `range` or `thresholds`;
a `table` rule has `map` (`data.test.ts` checks the shape; a name in
`steps`/`map`/`plain` must be a catalogue entry). The glyph for a
reading:

- `steps` with `range`: band `trunc((v - lo) * N / (hi - lo))`, clamped
  to `[0, N-1]`; with `cyclic`, `trunc((v - lo) / (hi - lo) * N + 0.5)
  mod N`, so band 0 is centred on `lo`. (`levelBand` today is the
  non-cyclic case.)
- `steps` with `thresholds`: band = the count of thresholds `≤ v` (a
  boolean is 0/1).
- `table`: the map's entry, else `plain` (`weather_unknown`).
- No reading: `plain`, for either kind.

In TypeScript, `icons.RULES: Map<name, IconRule>` and
`icons.RULE_OF_SOURCE: Map<sourcePath, IconRule>` replace
`LEVEL_ICONS`/`LEVEL_SOURCES`/`COUNT_ICONS`/`COUNT_SOURCES`/
`GARMIN_WEATHER_CONDITION_ICON`/`chooseWeatherIcon`, and
`complications.ICON_CONDITION`/`ICON_WHEN_ZERO`/`ICON_LEVEL` go: a type's
rule is `RULE_OF_SOURCE.get("complication." + type)`, and `follows` is on
the rule. One `icons.ruleIconName(rule, reading)` serves the preview, one
`ruleGlyphTable(rule)` the font, one generated `IconGlyphs.<rule>(value)`
the watch (today's `emitLevelFunction`, taking all three splits), one
`IconChoice(value, rule)` the draw program. `TextRun.levels`/`counts`
become `rules`. `ConfigDataSlot` keeps one `rules` set.

## 3. Slices

Each slice is one commit, `npm test` green, goldens regenerated only
where the slice's text says so, docs in the same commit.

1. **The rule table, and every consumer on it.** `icons.json` `rules` for
   battery, solar, notification, weather; the TypeScript above; the
   weather chooser generated (D7), `WfbWeather.mc` and its twin test
   removed, `runtime-lib.json` regenerated; `levelBand` generalised;
   `kinds/icon.ts`, `kinds/data.ts`, `emit/monkeyc/data.ts`,
   `draw/evaluator.ts`, `draw/printer.ts`, `studio/inspect.ts` each
   reduced to one path. Goldens: byte-identical except the weather
   chooser's module (D9); the showcase's `--build-stats 0` before and
   after goes in the commit message. `level-icons.test.ts` and
   `dynamic-icons.test.ts` keep passing unchanged, which is the proof the
   families still behave.
2. **`absent:` on `type: icon`** (D5): schema, builder (`checkAbsence`
   for the icon's own reading, `{text:}`/`{value:}` refused), the font
   bakes the substitute, `drawsWhileAbsent` reads the policy, the slot
   icon's absent branch, the preview. Diagnostics driven red:
   `absent:` on a fixed icon, `{text:}` on an icon, an unknown
   substitute name. Guide: `icons.md`'s absence paragraph becomes the
   `absent:` section.
3. **New rules: alarm, dnd, phone, moon** (D2–D4): catalogue entries
   `bell`, `alarm_off`, `phone_connected`, `phone_disconnected`, the
   eight `moon_*`; `cyclic` in the band maths with a test that age
   29.0 and 0.5 are both `moon_new` and 14.77 is `moon_full`;
   `sample.ts` already has `astro.moon_age`; a preview test per rule at
   both sides of each threshold. `icons.md` "A level icon" and "A count
   icon" fold into one "An icon that follows a reading" section with the
   rule table; `docs/limitations.md` §2's slot-icon paragraph rewritten;
   `wfb sources` prints the rule a source carries.
4. **`examples/features/`: a status row.** One example with the
   notification, alarm, dnd and phone icons in a row and the moon beside
   the date, warning-free on the three verification devices,
   screenshotted for the guide (`tools/docs-shots.ts`).
5. **The editor's "follows data" tab** (D8): `Words.icon_rules` from the
   table (`{rule, label, sources[], glyphs[]}`), `inspect.ts` treating
   `{for:}` as the icon widget's third spelling, `IconPop`'s tab switch
   (catalogue · code · follows data), the glyph strip per row, the chip
   showing the rule's label and mini-strip for an icon that follows data,
   the catalogue grid's "follows data" corner mark on a rule's plain
   glyph, and the `absent:` footer when the picked source can be absent.
   Tests: `protocol.test.ts` for `icon_rules`, a `page-panels` test
   clicking a row and reading the YAML, one browser-suite step.
   `studio.md` updated; the "edited as the YAML it is written as" line no
   longer names `icon:`.

## 4. Out of scope, recorded

- Day/night from `astro.sun_altitude`, a charging icon, any composite
  rule (charging over the battery level) — not built (D2).
- A rule over an author's own source (an expression): `for:` keeps taking
  a bare source only.
- Zone-coloured icons (a heart that follows the HR zone's colour) belong
  with plan 25 §6's zone colouring, not here.

## 5. Checks before "done"

- `npm test`, `npm run typecheck`, `npm run test:slow` (every example
  compiles with `monkeyc`), `npm run test:browser` for slice 5.
- The status-row example sideloaded on `fenix8solar47mm` by the user:
  the moon's phase against a calendar, the four status icons toggled by
  pairing/unpairing the phone, setting an alarm, DND on, a notification
  cleared — one photo per state in the commit that closes the plan.
