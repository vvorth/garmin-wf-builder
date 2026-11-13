# 42 — Your own glyphs for a dynamic icon: `icons:`

**Status: in progress. D1–D9 decided (2026-11-13; D7–D9 as recommended).** Delete this file once every slice has
shipped (`docs/CLAUDE.md`).

Builds on the icon rules (`ts/src/data/icons.json`'s `rules`, read by
`ts/src/icons.ts`) and on the battery's `variant:`, which already turns
one rule plus a second glyph set into a rule of its own (`expandRule`)
with its own generated chooser and font.

## 1. What it is for

An author can pick a glyph for each state of a dynamic icon, on an icon
element and on a slot choice:

```yaml
battery:
  type: icon
  icon: {for: complication.battery, icons: {0: battery_outline, 20: battery_low, 40: battery_medium, 60: battery_high, 80: battery}}
  absent: {icon: battery_classic}

config:
  slots:
    left:
      default: battery
      choices:
        - {type: battery, icons: {0: battery_outline, 50: battery_medium, 90: battery}, absent: {icon: battery_classic}}
        - {type: notification_count, icons: {0: bell, 1: bell_ring}}
        - {type: current_weather, icons: {weather_rainy: umbrella}}
        - steps
```

## 2. Decisions

### Decided (2026-11-13)

- **D1: keys follow the reading.** A rule over an ordered number
  (battery, solar, notification and alarm counts) is keyed by the reading
  where each glyph starts: `0`, `20`, `40`, … for a level, `0` and `1`
  (one and up) for a count.
- **D2: the keys define the bands.** `icons:` is a complete set: its keys
  are the band starts, so five keys on solar give solar five bands, and
  uneven bands work (`{0: a, 10: b, 50: c, 90: d}`). It is never merged
  with the rule's built-in bands.
- **D3: `off`/`on` is the only spelling for an on/off reading** (dnd,
  phone); `0`/`1` there is an error naming `off`/`on`, and `off`/`on` on a
  count is an error naming `0`/`1`. The loader is YAML 1.2, so `off` and
  `on` stay strings (checked 2026-11-13).
- **D4: weather and moon are keyed by built-in glyph name** and overlay
  the rule: `{weather_rainy: umbrella}` replaces that glyph for every
  condition the rule draws it for; names not given keep their glyph.
  `weather_unknown` is the glyph for an unrecognised condition as well as
  the rule's plain glyph.
- **D5: the key is `icons:`**, on `icon: {for:}` and on a slot choice.
  Values are written as `icon:` is: a catalogue name or
  `{codepoint: "U+XXXX"}`.
- **D6: the no-reading glyph stays `absent:`**, never a key inside
  `icons:`. A slot choice gains `absent:` (`hide`, or `{icon: <glyph>}`),
  as an element already has. `icons:` and `variant:` are refused together,
  as are `icons:` and a choice's own `icon:`.

### Decided as recommended (2026-11-13)

- **D7: element `absent:` against a choice's `absent:`.** An icon element
  drawing a slot (`slot:`) and that slot's chosen type can both say what
  to draw without a reading. The element's wins, because it
  is the more specific drawing; the choice's applies where the element
  says nothing; the rule's plain glyph applies where neither does.
- **D8: `none` as a value.** `{0: none, 20: battery_low, …}` would draw
  nothing in a band. Not in this plan (`absent: hide`
  covers the no-reading case); add it later if a face needs it.
- **D9: sharing.** Two elements or choices with the same set (same rule,
  same keys and glyphs) share one generated chooser and font. Each distinct set by order of first use
  (`batteryCustom1Icon`) is named by order of first use, which is deterministic and gives the shared view
  the same symbols on every device.

## 3. Rules and their keys

| Rule | Reading | Keys | `icons:` is |
|---|---|---|---|
| battery | 0–100 Float | numbers from `0` up to `100` | the complete set (D2) |
| solar | 0–100 | numbers from `0` up to `100` | the complete set |
| notification | count | whole numbers from `0` | the complete set |
| alarm | count | whole numbers from `0` | the complete set |
| dnd | on/off | `off`, `on` (both required) | the complete set |
| phone | on/off | `off`, `on` (both required) | the complete set |
| moon | age in days, cyclic | its glyph names (`moon_new` … `moon_waning_crescent`) | an overlay (D4) |
| weather | condition value | its glyph names (`weather_sunny` …, `weather_unknown`) | an overlay |

Checks, all compiler errors naming the rule's keys (a JSON Schema cannot
see a rule):

- a numeric set needs its lowest key at the bottom of the reading (`0`),
  at least two keys, and none above a level's top (`100`); a count's keys
  are whole numbers;
- an on/off set has exactly `off` and `on`;
- an overlay key must be a glyph the rule draws (`ruleNames`), at least
  one key;
- each value is checked as `icon:` is (catalogue name, codepoint in the
  font, the "say `icon: <name>`" note for a codepoint the catalogue names);
- `icons:` with `variant:`, or with a choice's own `icon:`, is refused;
  `icons:` on a slot choice whose type follows no rule is refused, as
  `variant:` is today.

`wfb sources` and the editor show each built-in set in the same key form
(battery: `0: battery_20, 20: battery_40, …, 80: battery`; solar's band
starts as the first whole reading in each band, `0, 12, 23, …, 89`), so an
author can copy one and edit it.

## 4. What changes, by slice

### Slice 1 — rules a face owns (no format change)

- `icons.ts`: `stateKeys(rule)` (each built-in glyph's key, §3) and
  `customRule(family, icons)`, which builds an `IconRule` from a family
  and an author's set: a numeric set becomes a `steps` rule with
  `thresholds` (sorted keys after the first) and no `range`; an on/off set
  a `[1]` thresholds rule; an overlay the family's own rule with `map` or
  `steps` names replaced.
- The face holds its derived rules (`Face.icon_rules`, by name), and every
  place that looks a rule up by name goes through one lookup that tries
  the face's first, then `RULES`: `iconRules`/`emitRuleFunction`
  (`ts/src/emit/monkeyc/app.ts`), `IconChoice` in the evaluator and the
  printer (`ts/src/draw/evaluator.ts`, `ts/src/draw/printer.ts`), the
  slot's icon method (`ts/src/emit/monkeyc/data.ts`).
- Goldens unchanged: no face has a set yet.

### Slice 2 — a threshold chooser for a Float reading

The threshold chooser today tests `value instanceof Lang.Number`, so a
Float (`system.battery`) would always fall through to the plain glyph,
in the generated `IconGlyphs` function and in the slot's inline chain.
A rule whose sources are not all whole-number sources gets numeric
comparisons instead (`if (value != null && value < 20) { return …; }`),
and the inline chain the same. `levelBand` already counts thresholds at
or below a Float, so the preview needs nothing. Counts keep today's code
(goldens unchanged); a test drives a synthetic Float threshold rule
through both paths and a real build.

### Slice 3 — `icons:` on `icon: {for:}`

Schema (`icons:` beside `for:`/`variant:`: an object whose values are
icon spellings; numeric keys arrive as numbers and the validator treats
keys as strings, so the schema says only "keys and icon values" and the
builder checks keys), the builder's checks (§3), each driven red, then
preview and generated code tests, and a build warning-free on the three
targets.

### Slice 4 — `icons:` and `absent:` on a slot choice

- The slot's choice parsing (`ts/src/ir/builder/config.ts`) reads both;
  `ConfigDataSlot` keeps the derived rule per type and the choice's
  absent glyph, which replaces the type's plain glyph in the icon method's
  no-reading return and in `icons` (as `variant:`'s classic plain glyph
  already does).
- A weather set on a temperature choice (`current_temperature`,
  `high_low_temperature`): today that case returns
  `WfbConditions.iconOr(WfbConditions.<reader>(), "<plain>")`, and the
  barrel calls `IconGlyphs.weatherIcon` by name. With a set, the case reads
  the condition itself and calls the set's own chooser
  (`var c = WfbConditions.<reader>(); return c != null ? IconGlyphs.<set>(c) : "<plain>";`);
  the barrel is unchanged.
- D7 settles which `absent:` wins on a `slot:` icon.

### Slice 5 — the editor

- `IconRuleWord` gains each glyph's key; the vocabulary carries it.
- The icon picker's follows data tab: a rule's row offers "own glyphs…",
  which writes `icons:` seeded with the built-in set (or the variant
  shown), and an icon following a set shows a state editor: one line per
  key (the key, a glyph picker, ×), "+ band" with a number box for a
  numeric set, no add or remove for on/off, and for an overlay a line per
  glyph name with the built-in greyed until replaced.
- The slot card: a choice following a rule gets the same editor, and an
  `absent:` control like the element's footer.
- Page tests click each control; one browser test writes a set and reads
  the YAML back.

### Slice 6 — docs and an example

`docs/guide/icons.md` (a section "Your own glyphs: `icons:`", the at a
glance row, the follows data tab), `docs/guide/configuration.md` (the
choice shapes, `absent:` on a choice), `docs/guide/studio.md`, the schema
descriptions, `docs/lore/roadmap.md`, `wfb sources` printing keys, and
`examples/features/status/` gaining one custom set so a build and the
preview goldens cover it.

## 5. Checks only the user can run

- A face with a custom battery set (numeric thresholds on a Float) and a
  custom weather set on a temperature slot choice, run in the simulator on
  the host: each band's glyph at readings either side of each key, and the
  `absent:` glyph with the complication's data missing.
