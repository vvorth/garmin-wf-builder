# Plan 03 — Icons beside a `complication_slot` reading

- **Date:** 2026-09-13
- **Status:** **findings only; no plan chosen, nothing built.** Recorded so the
  next session does not re-derive how slot icons work today and where they
  stop. §4 lists the options; the user has not picked one.
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
