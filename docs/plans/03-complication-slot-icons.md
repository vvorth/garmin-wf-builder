# Plan 03 — Icons beside a `complication_slot` reading

- **Date:** 2026-09-13
- **Status:** ~~findings only; no plan chosen, nothing built.~~ ~~Plan chosen
  2026-09-13 (§6): options 1 + 2 + 3, with 4 replaced by a coverage test.~~
  **Built 2026-09-13.** §1–§5 are the findings as first recorded, left in
  place; §6 is what shipped, amended in place with three same-day scope
  additions (§6.1/§6.3/§6.6's dated notes) and the `choices: any` +
  `icon_size:` finding (§6.7). Unverified on-device (no simulator, no
  watch); `choices: any` + `icon_size:` is schema/IR-correct but not
  shippable, see §6.7 and `docs/lore/toolchain.md`.
- **Ask:** "how can I use a data element (mostly returned as text/number) and
  draw an appropriate icon for it beside it?", about the Data axis
  (`config: data:` + `type: complication_slot`). The user had not used the
  Data selector before. `examples/slots/face.yaml` is the only example that
  defines it.

---

## 1. How it works today: `icon_size:` is the whole switch

```yaml
- id: top_reading
  type: complication_slot
  slot: config.data.top
  font: FONT_SMALL
  icon_size: 8%r        # present = draw an icon; omit = no icon
  color: palette.fg     # ONE colour, used for icon and text
  label: short          # none | short | long
  unit: true
  when_absent: placeholder
  placeholder: "--"
```

The runtime path, from the generated draw method in `wfb/emit/monkeyc.py`
around lines 2120–2192:

1. `chosenId.getType()` returns the type the wearer picked. A generated
   per-element switch (`complication_slot_icon_method(element.id)`) maps it
   to a **catalogue icon name**, or `null`.
2. `IconGlyphs.glyph(iconName)` turns the name into the character. This is
   the same "which name, then which glyph" split the dynamic weather icon
   uses.
3. The reading text is built from `pulled.value.toString()`, with an optional
   `shortLabel`/`longLabel` before it and `WfbComplications.unitSuffix(pulled.unit)`
   after it.
4. `dc.setColor(element.color, …)` is called **once** (line 2176), so icon and
   text always share one colour.
5. Widths come from `dc.getTextWidthInPixels`. The pair is centred **at
   runtime** on `Layout.<ID>_CX`: the icon is drawn left-justified first, then
   the text starts at `startX + iconWidth`. Both are vertically centred on
   `_CY`.
6. The gap is `COMPLICATION_SLOT_ICON_GAP = 4` px (`wfb/layout.py:155`). It
   is also used in layout's box sizing (`wfb/layout.py:521`), so the geometry
   lints see the same width.
7. **The icon stays when the reading is absent.** `when_absent: hide` blanks
   only the text, because the icon depends on the *pick*, not the value.

`complicationSlotElement`'s schema keys, in full: `id`, `type`, `slot`,
`font`, `icon_size`, `color`, `label`, `unit`, `when_absent`, `placeholder`,
`format` (always rejected), `at`, `modes`, `z`, `on_hold` (`auto` only),
`visible`, `static` (always rejected), `antialias`, `lint`, `overrides`.
**There is no `icon_color`, icon position, gap or per-choice icon key.**

---

## 2. The limits

1. **Only 8 of the 42 complication types have an icon.**
   `COMPLICATION_ICON` (`wfb/icons.py:509`) maps these types to catalogue
   names:

   | type | icon name |
   |---|---|
   | `battery` | `battery` |
   | `steps` | `steps` |
   | `calories` | `flame` |
   | `floors_climbed` | `floors` |
   | `notification_count` | `notification` |
   | `heart_rate` | `heart` |
   | `weekly_run_distance` | `distance` |
   | `weekly_bike_distance` | `distance` |

   Every other type **silently draws text only**: no warning, no error.
   The unmapped types are `altitude`, `body_battery`, `calendar_events`,
   `current_temperature`, `current_weather`, `date`, `forecast_weather_1day`
   /`2day`/`3day`, `high_low_temperature`, `intensity_minutes`,
   `last_golf_round_score`, `pulse_ox`, the eight `race_pace_predictor_*`/
   `race_predictor_*`, `recovery_time`, `respiration_rate`,
   `sea_level_pressure`, `sleep_score`, `solar_input`, `stress`, `sunrise`,
   `sunset`, `training_status`, `vo2max_bike`, `vo2max_run`,
   `weekday_monthday` and `wheelchair_pushes`.
   `icon_for_complication()` (`wfb/icons.py:521`) is the reverse lookup.
2. **Why the map is small: the *named* catalogue is small.** `icons.CATALOG`
   holds `alarm`, `battery`, `distance`, `dnd`, `flame`, `floors`, `heart`,
   `notification`, `phone`, `steps`, plus about 48 `weather_*` names. The
   vendored Nerd Fonts build has about 10,000 glyphs, reachable on an `icon`
   element as `glyph: "U+XXXX"`, but `COMPLICATION_ICON` maps only to *names*.
   The stated policy (`docs/format.md`, "The Data axis") is that a type stays
   unmapped when no glyph reads unambiguously as that metric, or when the
   icon would depend on the *value* rather than the type (the weather types).
3. **`icon_size:` is rejected with `choices: any`.** With `allowAny` the
   wearer may pick any type, including a Connect IQ complication, so the
   icon set is unbounded and nothing can be baked.
4. **Heights follow the default choice.** The baked icon font carries every
   mapped choice's glyph, normalised to the *default* choice's ink height,
   the same trade-off as `WEATHER_BAKE_REFERENCE_GLYPH`. Other choices'
   icons can render slightly larger or smaller.
5. **The layout is fixed:** icon on the left, 4 px gap, same colour, both
   centred as one unit.
6. **`icon_for:` on a plain `icon` element does not help.** Its schema
   description says it accepts only a `weather.condition*` source.

---

## 3. The workaround available today, with no code change

For a *fixed* metric, meaning not wearer-selectable, pair an `icon` element
(`icon: <name>` or `glyph: "U+XXXX"`) with a `text` element bound to
`complication.<type>`. This gives full control of colour and position, and
works for any glyph in the Nerd Fonts set. The cost: the wearer cannot
repoint it on the watch. `on_hold: <type>` still works on either element.

---

## 4. Options, not yet chosen

| # | Option | Gives | Cost / risk |
|---|---|---|---|
| 1 | **Extend `CATALOG` + `COMPLICATION_ICON`** with glyphs for more types (body battery, stress, sunrise/sunset, altitude, pulse ox, temperature, …) | icons for more types with no YAML change | a Python change per type; someone has to pick an unambiguous Nerd Fonts glyph each time; still no control per design |
| 2 | **Per-choice icon in YAML**: `config: data: <slot>: choices:` accepts `{ type: complication.stress, icon: stress_glyph }` or `{ type: …, icon: { glyph: "U+F0xxx" } }` next to today's bare `complication.<name>` | full control per design, any glyph, no Python catalogue edit; the per-choice override beats `COMPLICATION_ICON`, which stays the fallback | a schema `oneOf` on choice items; baking must add each override glyph; `choices: any` still cannot have icons |
| 3 | **Presentation keys on `complication_slot`**: `icon_color:`, `icon_position: left \| right \| above`, `icon_gap:` | native-looking variants (the icon in accent colour, the icon above the number) | the runtime centring code (`monkeyc.py` around 2176–2192) and the layout box size (`layout.py:521`) both need a branch per position, and must stay in step (ADR 0004 anti-drift); `wfb/preview.py`'s slot renderer too |
| 4 | **A lint for a mapped-nothing choice**: warn when `icon_size:` is set and a listed choice has no icon | turns limit 1's silent text-only into a diagnostic | small; independent of 1–3; arguably should exist regardless |

**The leaning offered to the user (not accepted yet):** 2, because it is the
most flexible and needs no catalogue curation, plus 4 so the gap is never
silent. Option 3 is independent and can follow if a design needs it.

Before building any of them, follow the house rules: drive each new
diagnostic red; build warning-free with real `monkeyc` on all three targets;
use `--build-stats` for cost; check the supplementary-plane glyph `filter=`
hazard in `wfb/emit/resources.py` (CLAUDE.md §6), since many Nerd Fonts
glyphs are above the BMP.

---

## 5. Unverified

As for everything on the Data axis: how the icon actually looks on the
wrist, and whether the editor's highlight lines up with the icon-plus-text
box. There is no simulator in this container and no watch.

---

## 6. Chosen plan (2026-09-13)

The user's direction, in their words: "think of the way to place icon to the
right, on top … there has to be an option to set the distance between text
and icon as well. map all available complications to some icon … i will
review and adjust later. and make per-choice icon in yaml as well, as a way
to override defaults and define what's not in catalog."

So: **option 1** (every type mapped), **option 2** (per-choice icon in
YAML), **option 3** narrowed to what was asked (`icon_position:` and
`icon_gap:`; no `icon_color:`), and **option 4's lint dropped**: once all 42
types are mapped, the only choice without an icon is one whose author wrote
`icon: none`, which is explicit, not silent. A test that `COMPLICATION_ICON`
covers every `complications.TYPES` key replaces the lint as the guard.

### 6.1 Format

```yaml
config:
  data:
    top:
      default: complication.steps
      choices:
        - complication.steps                               # catalogue default icon
        - { type: complication.stress, glyph: "U+F1341" }  # any font glyph
        - { type: complication.heart_rate, icon: heart }   # any catalogue name
        - { type: complication.calories, icon: none }      # explicitly no icon

elements:
  - id: top_reading
    type: complication_slot
    slot: config.data.top
    icon_size: 8%r
    icon_position: top     # left (default) | right | top | bottom
    icon_gap: 2px          # px or %r; default 4px, today's constant
    icon_color: palette.accent  # defaults to color: when omitted
```

**Same-day scope additions, 2026-09-13, user direction** (recorded here
rather than silently folded into the text above, per house style): "think of
the way to place icon to the right, on top … there has to be an option to set
the distance between text and icon as well … map all available complications
to some icon … make per-choice icon in yaml" was the original ask; mid-build
the user added three more: **include `bottom`** (mirrors `top` exactly: text
above, icon below, same geometry function, same `getFontHeight` stacking, gap
dropped when there is no icon); **allow `icon_size:` with `choices: any`**
(§6.1's last bullet below is superseded by this); and **add `icon_color:`**
(a colour expression, validated exactly like `color:`, defaulting to
`color:` when omitted). All three shipped; see §6.3/§6.6 for what changed.

- **A `choices:` item** is either today's bare `complication.<name>` or a
  mapping `{ type: complication.<name>, icon: <catalogue name> | none }` or
  `{ type: complication.<name>, glyph: "U+XXXX" }` (`icon` and `glyph` are
  mutually exclusive; neither means "the catalogue default", same as the
  bare form). `icon:`/`glyph:` mean exactly what they mean on an `icon`
  element, and are validated by the same code: an unknown name is an error
  with suggestions, a glyph not in the font is an error, a glyph that *is* a
  catalogue entry warns "say `icon: <name>`".
- **Not a desugar rewrite.** The mapping form carries information the bare
  form cannot express, so it is not an alternative spelling of it;
  `_build_config_data` accepts both shapes directly.
- A type listed twice (in either shape) is an IR error; the schema's
  `uniqueItems` cannot see through mixed shapes.
- `default:` stays a bare `complication.<name>` and must match some choice's
  type.
- `icon_position:` / `icon_gap:` / `icon_color:` without `icon_size:` —
  **chosen: an error** naming why (none of the three means anything with no
  icon to place, space or colour), the same style `font:`'s `align:` without
  `monospace: true` already uses. Checked against whether the author wrote
  `icon_size:` at all (not against whatever it resolved to), so a separate
  mistake in `icon_size:` itself is not doubled up with this one.
  `icon_gap:` must be px or %r and non-negative, like `icon_size:`.
- `choices: any` + `icon_size:` **was going to stay an error**, until the
  user asked for it lifted mid-build (see the dated note above). **Shipped
  2026-09-13:** `any` resolves against the whole of `COMPLICATION_ICON`; a
  CIQ-app complication (or a future native type this table does not yet
  know) simply draws no icon. See §6.6/§6.7 for the real-`monkeyc` finding
  this uncovered.
- `icon_color:` is included in the element's `_own_expressions()`, so the
  palette/config-colour lints and `wfb/lint.py`'s `_users_of` (extended from
  `("color", "track_color")` to include `"icon_color"`) see it exactly like
  `color:`.

### 6.2 One resolution helper, not four copies

Today the comprehension `{name: icons.COMPLICATION_ICON[name] for name in
slot.choices if name in icons.COMPLICATION_ICON}` is duplicated in
`wfb/layout.py`, `wfb/emit/resources.py`, `wfb/emit/monkeyc.py` (twice) and
`wfb/preview.py`. Replace every copy with one helper, e.g.
`ConfigDataSlot.icons -> dict[type_name, SlotIcon]` where
`SlotIcon(key, codepoint)`:

- the per-choice override wins; `icon: none` removes the entry;
- otherwise `COMPLICATION_ICON` supplies the catalogue name;
- `key` is the **catalogue name**, or the canonical `"U+XXXX"` spelling for
  a `glyph:` override.

`key` is what the generated `iconFor<Id>()` switch returns, and
`IconGlyphs.glyph()` gains a `case "U+F1341": return "…";` for each glyph
override in the design. This keeps the device-side "which name, then which
glyph" split intact (`wfb/icons.py` module docstring): the per-slot switch
still returns an ASCII key, and a character is written only in
`IconGlyphs.mc`.

### 6.3 Placement: one geometry, three consumers

The pair's geometry lives in three places that must agree (ADR 0004
anti-drift): the layout box (`wfb/layout.py`), the host preview
(`wfb/preview.py`) and the generated runtime code (`wfb/emit/monkeyc.py`).

| position | runtime arithmetic (both centred on `_CX`/`_CY`) | layout box |
|---|---|---|
| `left` | today's code: icon left-justified at `startX`, text at `startX + iconW + gap` | `w = iconW + gap + textW`, `h = max` |
| `right` | text at `startX`, icon at `startX + textW + gap` | same as left |
| `top` | `TEXT_JUSTIFY_CENTER`; icon at `(CX, startY)`, text at `(CX, startY + iconH + gap)`, where `startY = CY - (iconH + gap + textH)/2`; heights from `dc.getFontHeight()` | `w = max(iconW, textW)`, `h = iconH + gap + textH` |
| `bottom` (added 2026-09-13, user direction) | mirrors `top`: text at `(CX, startY)`, icon at `(CX, startY + textH + gap)` | same as `top` |

- When the chosen type has no icon (`icon: none`), the gap is dropped too and
  the text centres alone, as today.
- `Dc.getFontHeight` is confirmed in `$CIQ_SDK/bin/api.debug.xml`
  (`parent="Dc"`, API 1.0.0), so it is safe on all three targets.
- For `top`, the gap is measured between the two **font line boxes**, not the
  ink, so a system font's internal leading adds to it. Document this; do not
  try to correct it.
- `layout.py` exports one pure function computing the pair's offsets and
  extent from `(position, iconW, iconH, textW, textH, gap)`. Layout and
  preview both call it. The emitter mirrors it in Monkey C, and a test pins
  each position's generated branch.
- `icon_gap:` resolves per device (a `%r` gap is a different pixel count per
  screen), so when authored it becomes a per-device `Layout.<ID>_ICON_GAP`
  constant rather than a literal in the shared view class, the same reason
  `icons.font_key` is keyed by the *declared* length.
- **Byte-identical output when the new keys are omitted.** A design that
  writes none of `icon_position:`/`icon_gap:`/per-choice icons must generate
  exactly today's Monkey C, which is why `left` keeps today's code verbatim and
  an unauthored gap stays the inline `4`. Adding icons to `COMPLICATION_ICON`
  is the one intended output change for existing designs.

### 6.4 The catalogue mapping (option 1)

These are first picks for the user to review, chosen from a contact sheet
rendered at 16 px and 40 px from the vendored font. Every codepoint is read
from the font's own cmap/`post` names. All are Material Design Icons (above
the BMP; `wfb/emit/resources.py` already omits `filter=` for those). Each
gets a new `wfb/icon_catalog.py` entry, in that file's own `\U000fXXXX` +
`# preview:` convention.

| type(s) | new catalogue name | glyph |
|---|---|---|
| `body_battery` | `body_battery` | `md-battery_heart_variant` U+F1211 |
| `stress` | `stress` | `md-head_flash` U+F1340 |
| `sunrise` | `sunrise` | `md-weather_sunset_up` U+F059C |
| `sunset` | `sunset` | `md-weather_sunset_down` U+F059B |
| `altitude` | `altitude` | `md-image_filter_hdr` (mountains) U+F02F5 |
| `sea_level_pressure` | `pressure` | `md-gauge` U+F029A |
| `current_temperature` | `temperature` | `md-thermometer` U+F050F |
| `high_low_temperature` | `temperature_range` | `md-thermometer_lines` U+F0510 |
| `calendar_events` | `calendar_event` | `md-calendar_clock` U+F00F0 |
| `date` | `calendar` | `md-calendar_month` U+F0E17 |
| `weekday_monthday` | `calendar_day` | `md-calendar_today` U+F00F6 |
| `intensity_minutes` | `intensity` | `md-run_fast` U+F046E |
| `vo2max_run` | `run` | `md-run` U+F070E |
| `vo2max_bike` | `bike` | `md-bike` U+F00A3 |
| `respiration_rate` | `lungs` | `md-lungs` U+F1084 |
| `pulse_ox` | `pulse_ox` | `md-water_percent` U+F058E |
| `recovery_time` | `recovery` | `md-timer_sand` U+F051F |
| `training_status` | `training` | `md-chart_line` U+F012A |
| `race_predictor_5k`/`10k`/`half_marathon`/`marathon` | `finish_flag` | `md-flag_checkered` U+F023C |
| `race_pace_predictor_5k`/`10k`/`half_marathon`/`marathon` | `pace` | `md-speedometer` U+F04C5 |
| `sleep_score` | `sleep` | `md-bed` U+F02E3 |
| `solar_input` | `solar` | `md-white_balance_sunny` U+F05A8 |
| `wheelchair_pushes` | `wheelchair` | `md-wheelchair_accessibility` U+F05A4 |
| `last_golf_round_score` | `golf` | `md-golf` U+F0823 |
| `current_weather`, `forecast_weather_1day`/`2day`/`3day` | `weather` | `md-weather_partly_cloudy` U+F0595 |

The weather types get one fixed, type-keyed icon. The value-keyed condition
icon (§2 limit 1's first reason) is still future work. The existing eight
mappings are unchanged.

`COMPLICATION_ICON`'s docstring currently argues for leaving types unmapped.
Per house style, leave that account in place and add the reversal beside it,
dated, citing the user's direction. The "`body_battery` is not `battery`"
caution still holds: it gets its own glyph, not the device-battery one.

### 6.5 Also in scope

- `wfb complications` prints each type's icon name (a new column), so the
  mapping is reviewable from the CLI. **Shipped.**
- A contact sheet of every `COMPLICATION_ICON` entry, committed as
  `docs/plans/03-icon-sheet.png`, for the user's review. **Shipped.**
- `examples/slots/face.yaml` shows `icon_position: right`, `icon_gap: 2px`
  and one per-choice override (`{ type: complication.calories, icon: none
  }`) on `top_reading`, and its header comment is updated to match.
  **`bottom_reading` deliberately does not gain `icon_size:`** despite
  §6.6's lift of the `choices: any` restriction — see §6.7.

### 6.6 Out of scope (flag, do not build)

Value-keyed weather icons; per-choice icon *size*; on-device verification (no
simulator, no watch; §5 still applies).

**2026-09-13, user: include `bottom`, allow `icon_size:` with `choices: any`,
add `icon_color:`.** All three were originally listed here as out of scope
and were added mid-build by explicit user direction; all three shipped (see
§6.1/§6.3). None of the three has a remaining caveat. `choices: any` +
`icon_size:` first appeared to crash `monkeyc`; the real cause was a
string-hash collision between two glyphs, which the compiler now avoids
(see §6.7 and `docs/lore/toolchain.md`). `examples/slots/face.yaml`'s
`bottom_reading` uses it.

### 6.7 Done means

- Fast suite: only the 5 known failures (`tests/CLAUDE.md`). **Met** (1,027
  passed, 5 known failures, verified after every change in this session).
- Every new diagnostic has been driven red, including the coverage test (it
  fails with one `COMPLICATION_ICON` entry removed). **Met** —
  `tests/test_icons.py::test_complication_icon_coverage_actually_fails_without_a_mapping`
  proves the contrast directly, alongside the individually-driven-red tests
  in `tests/test_complication_slot.py` for every new key/error.
- Real `monkeyc` builds of `examples/slots/face.yaml` and of a scratch
  design exercising `right`, `top`, a `%r` gap and a `glyph:` override are
  warning-free on all three targets, with `--build-stats` before/after.
  **Met, with one finding**: `examples/slots/face.yaml` (as shipped, without
  `choices: any` + `icon_size:` on `bottom_reading`) builds warning-free,
  `fenix8solar47mm` at 3,786 B (was 3,827 B before this session's changes —
  the per-choice `icon: none` override removes a switch case, slightly
  *reducing* code size). The scratch design (`icon_position: right` with a
  `%r` gap, `icon_position: top` with `icon_color:`, and a `glyph:`
  override) builds warning-free on all three targets at 3,737 B.
  Trying `choices: any` + `icon_size:` crashed `monkeyc` ("Redefinition
  of label (data) str___1798574"). The build session first bisected it as
  a "~39 types" count threshold; that was wrong. The label is the Java hash
  of a string literal, and the `distance` and `temperature` glyphs share
  it, so any design containing both crashed, including a two-choice slot.
  `wfb/emit/strhash.py` now detects such collisions: a colliding
  `IconGlyphs` glyph is built at runtime with `Number.toChar`, and anything
  else is a `string-label` build error. `choices: any` + `icon_size:`
  (all 42 types) then builds warning-free on all three targets, at 5,104 B
  on `fenix8solar47mm` for a one-slot scratch design, against 2,886 B with
  two choices.
- `wfb preview` renders each position correctly (inspect the PNG). **Met**:
  `left`/`right`/`top`/`bottom` all inspected directly and match the
  authored `icon_position:`.
- These are updated in the same commit: the schema, `docs/format.md`,
  `docs/limitations.md` §2, `docs/lore/roadmap.md` item 12, `CLAUDE.md` §6's
  "Planned, not built" bullet, this plan's status and `docs/history.md`.
  **Met**, plus a new dated finding in `docs/lore/toolchain.md` the original
  "done means" list did not anticipate.
