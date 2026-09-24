# On-device configuration

Garmin's fēnix 8 watches have a native on-device face editor with four
user-editable axes: an accent colour, a data colour, Styles (author-named
entries), and Data (named complication slots the wearer repoints at any
Garmin metric). The wearer can save up to four configurations. `fr955` has
no on-device editor at all, so it always shows the compiled-in defaults.
`config:` declares which of these axes a design uses.

## At a glance

| Key | Where | Values | Default | Meaning |
|---|---|---|---|---|
| `accent_color:` | `config:` | `default:` + `choices: any` or a list | — | the one native accent-colour axis |
| `data_color:` | `config:` | `default:` + `choices: any` or a list | — | the one native data-colour axis |
| `style:` | `config:` | ordered mapping of named entries | — | [the Styles axis](#all-four-axes-are-wired-up) |
| `data:` | `config:` | mapping of named slots | — | [the Data axis](#the-data-axis) |
| `default:` | a `config:` axis/entry | hex/`palette.*` colour, entry name, or `complication.*` type | — | starting value; must be in `choices:` when explicit |
| `choices:` | a `config:` axis/entry | `any`, or an explicit list | — | the editor's picklist |
| `label:` | a `style:` entry | string | falls back to the scheme's own `label:` | shown in the editor's Styles list |
| `colors:` | a `style:` entry | bare `color_scheme:` name | — | required unless `layout:` given; all-or-none per `choices:` list |
| `layout:` | a `style:` entry | bare `layouts:` name | — | see [Styles and layouts](styles-and-layouts.md) |
| `slot:` | `complication_slot` | `config.data.<name>` | required | which declared slot this element draws |
| `icon_size:` | `complication_slot` | length, px or `%r` | omit = no icon | icon height, chosen on-device |
| `icon_position:` / `icon_gap:` / `icon_color:` | `complication_slot` | `left`/`right`/`top`/`bottom`; px/`%r`; colour | `left`; `4px`; = `color:` | icon placement, gap and colour — need `icon_size:` |
| `label:` / `unit:` | `complication_slot` | `none`/`short`/`long`; boolean | `none`; `false` | `Complication.shortLabel`/`.longLabel`; `.unit` suffix |
| `when_absent:` | `complication_slot` | `hide` / `placeholder` | `hide` | blanks only the reading; the icon still draws |
| `on_hold:` | `complication_slot` | `auto` only | — | resolves to the wearer's current pick, on every hold |

## Example

```yaml
color_scheme:
  dark:  { label: "Dark",  colors: { bg: palette.black, fg: palette.white, ... } }
  light: { label: "Light", colors: { bg: palette.white, fg: palette.black, ... } }

config:
  style:                             # layout × colour scheme, as named entries
    default: digital_dark
    choices:
      analog_dark:  { label: "Analog · Dark",  layout: analog,  colors: dark }
      digital_dark: { label: "Digital · Dark", layout: digital, colors: dark }
  accent_color: { default: palette.red,   choices: [palette.red, palette.lime_green, ...] }
  data_color:   { default: palette.amber, choices: [palette.amber, palette.magenta, ...] }
  data:
    left_register:
      default: complication.steps
      choices: [complication.steps, complication.heart_rate,
                { type: complication.calories, icon: none }]
    right_register: { default: complication.body_battery, choices: any }
```

![three accent / data colour / slot selections](../screenshots/showcase-config.png)

*Left: the defaults (red accent, amber data colour). Middle: lime accent,
magenta data colour, and the left slot set to heart rate. Right: magenta
accent, cyan data colour, and the right slot set to calories.*

The wearer picks these in the fēnix 8's native face editor, which saves up to
four configurations. The fr955 has no on-device editor, so it always shows the
defaults.

## Configuration

```yaml
palette:
  aqua: { value: "#00FFFF", label: "Aqua" }
  amber: { value: "#FFAA00", label: "Amber" }

color_scheme:
  dark:
    label: "Dark"
    colors: { bg: "#000000", fg: "#FFFFFF" }
  light:
    label: "Light"
    colors: { bg: "#FFFFFF", fg: "#000000" }

config:
  accent_color:
    default: "#FF8000"
    choices: any                       # the editor's own full colour picker
  data_color:
    default: palette.aqua              # a palette reference, or a literal hex
    choices:                           # or an explicit list
      - palette.aqua                   # a bare palette reference ...
      - palette.amber
      - { color: "#FFFFFF", label: "White" }   # ... or the inline form
  style:
    default: dark                      # names a choices: entry, not a scheme
    choices:                           # an ORDERED mapping -- index = styleId
      dark:  { colors: dark }          # a bare color_scheme name
      light: { label: "Light!", colors: light }
  data:
    top:
      default: complication.steps      # a wfb.complications type -- see below
      choices:
        - complication.steps
        - complication.heart_rate
        - complication.calories
    bottom:
      default: complication.body_battery
      choices: any                     # the editor's own full complication picker
```

Four user-editable axes, read through the fēnix 8's **native on-device watch
face editor** (`Core_Topics/Editing_Watch_Faces_On_Device.html`, API 5.1.0).
All four keys are optional, and `accent_color`/`data_color`/`style`/`data`
are the **only** keys this block accepts -- Garmin's editor offers exactly one
accent colour, one data colour, one Styles axis and one Data axis, and
nothing else. Declaring anything else is a schema error naming what is
accepted.

`style` is shaped differently from the other two colour keys, and replaces
the earlier `config: colors:` outright (removed, no shim): `choices:` is an
**ordered mapping of author-chosen entry name -> entry**, not a list, so
`default:` names one *entry* (a `choices:` key), not a colour or a scheme --
and an entry's own `colors:` is what names a declared `color_scheme:` entry,
as a **bare name** (`colors: dark`, not `color_scheme.dark`). Editor order is
declaration order, and it is also the `<style id="N">` numbering
`resolveStyle` decodes `styleId` against (index 0 first) -- see [Color
scheme](colors.md#color-scheme). Every entry needs at least one of `colors:`/`layout:` -- the
second names a declared `layouts:` entry, the same bare-name spelling; see
[Styles and layouts](styles-and-layouts.md#styles-and-layouts). **`colors:` is all-or-none across every entry in
one `choices:`**, independent of `layout:` -- a design cannot mix an entry
that has `colors:` with one that does not; the first entry that violates
this is one error, not one per offending entry. `data` is shaped differently
again: it is a **mapping of
named slots**, each with its own `default:`/`choices:` naming
`complication.<name>` types (the same table `on_hold:` and the
`complication.*` data-source namespace already resolve against -- run `wfb
complications` for the full list); see "The Data axis" below for the slot
names, and the `complication_slot` element that draws one. Everything in the
rest of this section describes `accent_color`/`data_color`; `style`'s/
`data`'s own rules are in this section (below) and "The Data axis"
respectively.

**Label fallback.** An entry's own `label:` is shown in the editor's Styles
list. An entry with **no** `label:` and only `colors:` (no `layout:`) falls
back to that scheme's own `label:` instead -- this is what makes migrating a
`config: colors:` block a pure re-spelling: the generated `<style
label=...>` text does not move. A layout-carrying entry gets no fallback,
colour or not; an entry with neither gets no `label` attribute, same as
everywhere else a label is optional.

**`default:` must name a `choices:` entry** (not a scheme, not a colour) --
Garmin defines no behaviour for a default outside the list, and the error
lists the declared entry names.

**`duplicate-style` (suppressible).** Two entries that resolve to the same
`colors:` (and, from a later format, the same `layout:`) are indistinguishable
on the wrist. This is a warning, not an error -- a designer may still want two
labels while iterating -- reported once per design at the second entry of the
pair, and suppressed with `lint: {allow: [duplicate-style], reason: ...}` on
that **entry** (not on an element: `style:` entries have no element of their
own to hang `lint:` on otherwise).

Each entry needs both `default:` and `choices:`. `default:` is a literal
`#RRGGBB`/`#RGB` or a `palette.<name>` reference, compiled into the view as the
starting value either way -- once resolved, a palette reference and a literal
are the same colour to every check below. `choices:` is either the literal
string `any`, which hands the wearer the editor's own unrestricted colour
picker, or an explicit list whose items are each **either** a bare
`palette.<name>` reference **or** an inline `{color, label}`. A bare palette
reference contributes that entry's colour and, if the entry declared one, its
`label:` -- unlabelled long-form entries and the short form both produce an
unlabelled choice, same as omitting `label:` on the inline form. **When
`choices:` is an explicit list, `default:` must be one of the listed
colours** -- compared by colour value, so `default: palette.aqua` matches a
listed `palette.aqua` (or an inline choice with the identical hex) equally --
the editor marks one listed colour `default="true"`, and Garmin defines no
behaviour for a default that is not in the list.

**Naming a palette entry that was never declared, or was declared and
rejected (an out-of-range colour, a `config.*` reference), is an error** at
the `default:`/`choices:` line, naming every entry `palette:` actually
declares.

Reference a declared entry as an ordinary colour expression, exactly like a
palette entry:

```yaml
color: config.accent_color
color: heart_rate.current > 120 ? config.accent_color : palette.dim
```

### All four axes are wired up

Garmin's editor has four axes total -- Styles, Data, Data Colour, Accent
Colour (`docs/adr/0006-configuration-theming-and-modes.md` §1) -- and all four
are wired up: the two colour axes, **Styles**, which carries no colour of
its own and is the only axis Garmin gives no meaning to at all
(`docs/research/09-data-library-and-config-axes.md` §3, which is exactly why
this compiler gives each `config: style:` entry a meaning -- today a declared
`color_scheme:`, read back through `config.colors.<role>`), and **Data** --
named native complication slots, `config.data.<name>`, drawn by a `type:
complication_slot` element (see "The Data axis" below). `accent_color`/
`data_color`/`data` are keyed by the axis itself rather than an author-chosen
name, because Garmin gives exactly one of each (`data` alone is a mapping,
because Garmin's Data axis itself holds several independent slots); `style`
is the odd one out, an author-named, ordered set of entries, because Styles
is the one axis with no meaning of its own for this compiler to key on.

**The editor's own animated highlight is built too**, and it is
automatic: any design with at least one `complication_slot` element gets
`AppBase.onStart`'s edit-mode detection, `WatchFaceDelegate.onTap` +
`setSelectedComplication` (hit-testing each slot's own resolved box), and
`WatchFaceDelegate.getComplicationDrawable` returning a generated
`<Face>SlotDrawable` that delegates straight back to the view's own per-slot
draw method -- so there is exactly one implementation of what a slot looks
like, drawn either by `onUpdate` or by the editor's own `Drawable`. A design
with no `complication_slot` element gets none of this: `onTap` (unlike
`onPress`) never fires on a live face (research 07 §1), so all of it would be
dead weight there. **No behaviour of any of this is verified** -- see "What
this compiler cannot tell you" below.

### The Data axis

```yaml
config:
  data:
    top:
      default: complication.steps
      choices:
        - complication.steps
        - complication.heart_rate
        - { type: complication.calories, icon: none }
        - { type: complication.stress, glyph: "U+F1340" }
    bottom:
      default: complication.body_battery
      choices: any

elements:
  - id: top_reading
    type: complication_slot
    slot: config.data.top
    at: { anchor: center, dy: -20% }
    font: FONT_SMALL
    icon_size: 8%r          # omit to draw no icon
    icon_position: right    # left (default) | right | top | bottom
    icon_gap: 2px            # px or %r; default 4px, today's fixed gap
    icon_color: palette.accent  # defaults to color: when omitted
    color: palette.fg
    label: short             # none (default) | short | long
    unit: true                # append Complication.unit's suffix
    when_absent: placeholder
    placeholder: "--"
```

Each `data:` entry is a **named slot** with its own `default:`/`choices:`,
resolved exactly like `on_hold:` against :mod:`wfb.complications`' table (run
`wfb complications`) -- `default:` compiles into the view as the starting
`Complications.Id`, and is the only type a device with no native editor
(fr955) ever shows. `choices:` is either an explicit, orderable list (which
`default:` must belong to) or the literal string `any`, handing the wearer the
editor's own unrestricted complication picker.

**A `choices:` list item** is either a bare `complication.<name>` reference
(today's only form) or a mapping naming the same reference plus a per-choice
icon override (plan 03 §6.1/§6.2): `{ type: complication.<name>, icon:
<catalogue name> }`, `{ type: complication.<name>, icon: none }` (explicitly
draw no icon for this one choice, even though the catalogue maps it), or
`{ type: complication.<name>, glyph: "U+XXXX" }` (any codepoint the vendored
font has, for a glyph the catalogue does not name). `icon:`/`glyph:` are
mutually exclusive and validated exactly like a plain `icon` element's own
`icon:`/`glyph:` -- an unknown catalogue name is an error with suggestions, a
glyph outside the font's character map is an error, and a glyph that
duplicates a catalogue entry gets the same "say `icon: <name>` instead" note.
A choice with neither key keeps the catalogue default
(`wfb.icons.COMPLICATION_ICON`), same as the bare form. **A type listed more
than once across the whole `choices:` list -- in either shape -- is an IR
error**: the schema's own `uniqueItems` only catches two identical bare
entries, not a bare reference and a mapping-form entry naming the same type.

`type: complication_slot` draws one slot, naming it as `slot:
config.data.<name>`. Unlike every other element, **which complication is
showing is not known at build time** -- the wearer picks it on-device, and
`Complications.Id.getType()` only resolves at runtime -- so this element binds
no ordinary `value:` expression at all. Instead:

* **`color:`** is an ordinary colour expression, but it must not be nullable
  -- there is no `when_absent:` for the element's own appearance, only for the
  reading (see below).
* **No `format:`.** `Complications.Complication.value` is a `String or Number
  or Float or Long or Double` union whose concrete type genuinely varies by
  which choice the wearer makes -- a format string written for one choice
  would be silently wrong for another. `format:` is a schema error naming
  this reason. The value renders through `WfbComplications.formatValue`:
  `toString()` for a Number, Long or String; a Float or Double is rounded to
  three significant figures without dropping integer digits, then loses its
  trailing zeros (12.879 -> `12.9`, 101325.0 -> `101325`). Floats need this
  because Monkey C's `Float.toString()` always prints six decimals. Observed
  in the simulator: steps at or above 10,000 arrive as a Float in
  thousands with the unit string `"K"`, so they draw as `12.9K`.
* **`label:`** (`none` default, `short`, `long`) draws `Complication.
  shortLabel`/`.longLabel` before the value, when the device supplies one.
* **`unit:`** (`false` default) appends `Complication.unit`'s suffix after the
  value, when the device supplies one -- a raw `String` unit (a user
  complication may supply one directly) is used verbatim; the documented
  `Complications.Unit` enum is translated through a small, SDK-transcribed
  table (`m`, `m/s`, `°C`, `g`, ...; see `wfb/complications.py`'s
  `UNIT_SUFFIX` and `runtime-lib/WfbComplications.mc`'s `unitSuffix`).
* **`when_absent:`** is `hide` (default) or `placeholder` (needs
  `placeholder:`) -- and unlike every other element, `hide` blanks only the
  *reading*, leaving the icon drawn: the icon says which metric the slot is
  pointed at, which stays true even on a frame the reading itself could not be
  pulled.
* **`icon_size:`** (omit to draw no icon) chooses the icon **on-device**, from
  the wearer's picked *type* alone -- `Complications.Id.getType()`, `switch`ed
  against a table of catalogue names (`wfb.icons.COMPLICATION_ICON`, or a
  per-choice override), then `IconGlyphs.glyph()` turns the name (or a
  `glyph:` override's canonical `U+XXXX` spelling) into a character, exactly
  the same "which name, then which glyph" split a dynamic weather icon uses.
  **All 42 native complication types have a catalogue icon** -- an author can still suppress one explicitly
  with a per-choice `icon: none`, and a Connect IQ-app complication (outside
  `wfb.complications.TYPES` entirely) simply draws no icon, since this
  compiler cannot know what it is. Run `wfb complications` for the current
  mapping (it lists each type's catalogue icon alongside its Monkey C
  constant).
  **`choices: any` + `icon_size:` is accepted**: `any` resolves against the
  whole of `wfb.icons.COMPLICATION_ICON`. It builds warning-free on all three targets. A Connect IQ-app
  complication picked in such a slot draws its reading with no icon.
  (monkeyc 9.2.0 crashes when two different string literals share a Java
  hash code, and some icon glyphs do, such as `distance` and
  `temperature`. The compiler handles that for slot and weather icons
  itself; see `docs/lore/toolchain.md`. The one case it cannot fix is
  reported as a `string-label` build error, listed below.)
* **`icon_position:`** (`left` default, `right`, `top`, `bottom`) places the
  icon relative to the reading; **`icon_gap:`** (px or `%r`, non-negative;
  default 4px, today's fixed gap) sets the space between them. Both need
  `icon_size:` -- an error naming why, without it, since neither means
  anything with no icon to place or space. `top`/`bottom` stack the pair
  vertically and centre both horizontally, using `Dc.getFontHeight` for each
  piece's height -- the gap is measured between the two font *line boxes*,
  not the ink, so a system font's internal leading adds to it (not
  corrected). When the wearer's current pick has no icon (an explicit
  `icon: none`, or the whole slot mapped nothing), the gap drops too and the
  reading centres alone, in every position.
* **`icon_color:`** the icon's own colour, distinct from `color:` (the
  reading's). Must not be nullable, for the same reason `color:` must not be.
  Needs `icon_size:` -- an error naming why, without it. Defaults to
  `color:` when omitted -- one shared colour for icon and reading alike,
  today's only behaviour, and what an unauthored design keeps generating
  byte-for-byte.
* The icon and the reading are centred together, as one pair, on this
  element's own anchor -- at **runtime**, via `Dc.getTextWidthInPixels`/
  `Dc.getFontHeight`, because the actual text is not known until the value
  is pulled. This is the one element in the format whose drawn position is
  not fully resolved at build time (ADR 0004's one deliberate exception, and
  for exactly that reason); the geometry lints below size its box from the
  value alone (see "What this compiler cannot tell you"). The pair's
  geometry -- for every `icon_position:` -- is computed by one pure function,
  `wfb.layout.complication_slot_pair_geometry`, shared by the layout
  resolver (the estimated box) and `wfb preview`, and mirrored (not called
  -- the real text is not known at build time) by the generated Monkey C.
  **`align`/`vertical_align`** follow the one placement rule every accepting
  kind shares: [Placement: `at:` and `align:`](placement.md#placement-at-and-align) --
  but because the pair is measured on the device, its alignment arithmetic
  runs there too, for every `icon_position:`, rather than moving a
  build-time box (the same runtime exception as the centring above).
* A `complication_slot` **cannot be static** (its reading changes every frame,
  and the wearer can repoint it at any time) -- an error, naming why.
* **`on_hold:`** accepts exactly one value here: **`auto`**. Touch and hold
  opens whichever glance the wearer's *current* pick belongs to
  (`Complications.exitTo` on this slot's own field), resolved fresh on every
  hold rather than a fixed name baked in at build time -- unlike every other
  element's `on_hold: auto`, which resolves once, at build time, to a single
  `wfb.complications.TYPES` name via `Source.launch_complication`. A fixed
  target (`on_hold: heart_rate`, say) is a schema-and-IR error naming why: it
  would silently disagree with what is on screen the moment the wearer
  repoints the slot. To always launch one fixed glance regardless of what a
  slot currently shows, bind a plain `text`/`icon` element to the matching
  `complication.<name>` source and put `on_hold: <name>` there instead. No
  `on_hold:` at all is a legitimate choice -- holding does nothing.

Font baking follows the same "multi-glyph font" shape a dynamic weather icon
already needs: the text font must carry every character *any* declared choice
could render (there is no per-choice `format:` to size against), and the icon
font -- when `icon_size:` is set -- carries every mapped choice's glyph,
normalised to the *default* choice's own ink height (the same one-reference-
glyph trade-off `WEATHER_BAKE_REFERENCE_GLYPH` makes for the weather set: no
single nominal size fits every icon set's glyphs equally, so the other
choices render at whatever height that nominal size gives them).

### What each device does with it

The generated resource (`<watchface-config>`, one `<accentColors>`/
`<dataColors>`/`<styles>`/`<data>` per declared axis) is emitted **only for a
device with the native editor** -- checked with `Device.has_symbol`, never an
API-level compare: `fr955` reports ConnectIQ 5.2.0, above the editor's own
documented 5.1.0, and still has no editor at all (see CLAUDE.md constraint 6,
and `docs/research/probes/watchface-config/`). Declaring `config:` forces no
`minApiLevel` bump on any device, `data:` included: `manifest.xml`'s
`minApiLevel` is one number shared by every target device in the build, so it
stays at the generator's own base floor (`3.1.0`) regardless of what a design
uses (`wfb/emit/manifest.py::BASE_API_LEVEL`). A `data:` slot needs
`Toybox.Complications` (`Complications.Id`, `COMPLICATION_TYPE_*`) the same as
any other complication use, but a target device that lacks the module gets a
runtime `Toybox has :Complications` guard in the generated code instead of a
raised manifest floor -- see "The `complication.*` namespace" and "Holding an
element" below for the full mechanism, and the `api-gated` lint entry just
below for what an author sees on such a device.

**A device with no native editor keeps every declared default forever** -- the
compiled-in colours and the default scheme's role colours always; a slot's
default complication type too, **provided the device can still resolve it**
-- it is read through `Toybox.Complications` the same as any other choice,
so a device that lacks that module as well (fenix6, fenix6xpro, fr245 today)
cannot "keep" it either, and the slot shows its absent state instead. This is
a real, user-facing consequence of the chosen scope
(`docs/adr/0006-configuration-theming-and-modes.md` §2), not a bug, and the
compiler says so: the suppressible `config-unsupported` warning fires once
per such target, naming the device and the entries (roles, slots) affected,
worded accordingly for a slot that cannot resolve its default either; see
`api-gated` below for the same fact from the slot's own side, reported
independently rather than folded into this one.

### Lint

* An unknown key under `config:` -- schema error, naming what is accepted.
* `default:`/`choices:` naming an undeclared (or declared-and-rejected)
  `palette.<name>` -- error, naming the declared palette entries.
* `default:` not among an explicit `choices:` list -- error. For `style`,
  this compares **entry names**, not scheme names or colour values -- two
  entries may legitimately reference the same scheme (see `duplicate-style`
  below).
* A `style` entry with no `colors:` (today, every entry needs one), or some
  entries with `colors:` and others without -- one error, at the first entry
  that lacks it.
* A `style` entry's `colors:` naming an undeclared (or declared-and-rejected)
  `color_scheme:` entry -- error, naming the declared schemes.
* `duplicate-style` (suppressible) -- two `style` entries resolve to the same
  `colors:` -- warning, once per design, at the second entry of the pair;
  suppress on that entry's own `lint:`.
* Every declared colour goes through the same 64-colour palette-legality check
  a `palette:` entry gets: `default:` always (it is the only value a device
  with no native editor ever shows), plus every listed `choices:` colour when
  `choices:` is an explicit list (`choices: any` has no list to check) --
  and, for `style`, every role of every scheme some entry actually
  references (a scheme no entry references is unreachable on any device, so
  it is not checked). Reported as `palette-dither` against whichever
  element draws exactly `config.<name>`/`config.colors.<role>` -- as its
  `color:`/`track_color:`/`icon_color:`, a text's `outline: {color: ...}`,
  or an `aod:` override's colour (a plain `palette.<name>` reference is
  checked the same way, against the same fields).
* `config-unsupported` (suppressible) -- at least one target has no native
  editor, so the declared defaults are all that device ever shows (now
  including every slot's default); when `style` has more than one entry, the
  message also names the non-default entries as unreachable on that device.
* `data:`'s `default:`/`choices:` naming an unknown `complication.<name>` --
  error, with a near-miss suggestion, the same as an `on_hold:` typo.
* `data:`'s `default:` not among an explicit `choices:` list -- error, the
  same shape as the colour axes'.
* A `complication_slot`'s `slot:` naming an undeclared (or declared-and-
  rejected) `config.data.<name>` -- error, naming the declared slots.
* `format:` on a `complication_slot` -- error, naming why (see "The Data
  axis").
* `string-label` -- two different string literals in the generated program
  share a Java hash code, which monkeyc 9.2.0 crashes on (see "The Data
  axis" and `docs/lore/toolchain.md`). A colliding slot or weather icon
  glyph is fixed automatically, so this error only reaches you for a
  collision the compiler cannot rewrite, such as two static `icon` elements
  showing `distance` and `temperature`. It names both strings; change one.
* `icon_position:`/`icon_gap:`/`icon_color:` without `icon_size:` -- error,
  naming why (none of the three means anything with no icon to place, space
  or colour).
* `icon_gap:` in a unit other than px/`%r`, or negative -- error, the same
  restriction `icon_size:` has.
* A per-choice `icon:`/`glyph:` naming an unknown catalogue entry, an
  out-of-font codepoint, or both keys at once -- error, the same messages a
  plain `icon` element's own `icon:`/`glyph:` get.
* A `complication.<name>` type listed more than once in one slot's
  `choices:`, in either shape -- error, naming where it was already listed.
* `static:` on a `complication_slot` -- a permanent error: the whole point of
  a slot is that its content changes, and static content is painted once.
* `on_hold:` on a `complication_slot` naming anything other than `auto` --
  error, naming why (see "The Data axis" above) and pointing at the
  alternative (a plain element bound to the matching `complication.<name>`).
* `api-gated` (suppressible) -- *any* catalogue binding a target device
  cannot actually provide, resolved against that device's own
  `api.debug.xml` rather than an API level (`wfb/availability.py`; CLAUDE.md
  constraint 6/6e). Five shapes, all WARNING, all reading as absent rather
  than failing the build:
  - a `value:`/`color:`/etc. source path whose reader needs a `Toybox`
    module (`Complications`, `Weather`) or a field the device's own symbol
    table lacks -- covers every `complication.*` and `weather.*` read this
    way, for free, via its reader's module gate (`fenix5`/`fenix5x` lack
    `Toybox.Weather`);
  - a forecast `graph` (`forecast_*`/`daily_*` series) on a device with no
    `Toybox.Weather` -- the guarded acquisition yields nothing and the graph
    draws empty there;
  - a complication *type* newer than the device's own ConnectIQ ceiling,
    checked against `wfb.complications.ComplicationType.since`
    (`COMPLICATION_TYPE_*` values are constants with no entry in
    `api.debug.xml` at all, so a level compare is the only thing that can
    catch this one), skipped when the device lacks
    `Toybox.Complications` outright (the module-gap case above already said
    so, more fundamentally);
  - `on_hold:` on a device with no `Toybox.Complications` -- the hold
    compiles in but does nothing there, unless `hold-unsupported` already
    covers that same element (the device also lacks `onPress`) -- "it never
    fires" stays true either way, so this one really is the same fact twice;
  - a `complication_slot`'s slot on a device with no `Toybox.Complications`
    -- it shows its absent state forever, **never** its declared `default:`
    (the default is itself read through `Toybox.Complications`, so a device
    missing the module cannot resolve it either). This does **not** dedupe
    against `config-unsupported`: that warning, when it *also* fires because
    the device lacks the native editor too, says the slot "keeps its
    declared default" -- true only when the default can still resolve, so
    on a device missing both (fenix6, fenix6xpro, fr245 today) the two
    warnings report different halves of the truth and both fire, with
    `config-unsupported`'s own wording adjusted to say "shows as absent"
    for such a slot rather than "keeps its declared default".

  A fifth shape, `api-gated-unguardable`, is a build **ERROR** and
  deliberately **not** suppressible: it means a reader's own function symbol
  (as opposed to a module or a field) is missing on a target device. The
  generated code only ever guards a module or a field at runtime
  (`wfb.availability.compute_guards`) -- there is no guard for an individual
  function, so "reads as absent" would be a lie; the call would run
  unguarded and crash on that device. No device this project vendors
  triggers it today: the one real gap that used to (`fenix5`'s missing
  `Toybox.Weather`) is a whole-module gap, guarded like `Complications`.

### What this compiler cannot tell you

**No behaviour of the editor is verified anywhere in this project.** There is
no simulator in this container and no watch (`docs/limitations.md` §2); every
claim above is a compile-time result (schema, IR, a real `monkeyc` build) or a
byte cost, never a description of what the editor's UI actually does.

**A `complication_slot`'s geometry is sized from its value alone.** `label:`
and a `String`-typed `unit:` are localised device strings with no documented
upper bound -- unlike a digit count, padding for them would either be
routinely wrong or, picked generously, turn an ordinary slot into a spurious
`off-screen` warning (confirmed directly: an 8-character placeholder
pushed a comfortably-fitting design off the framebuffer). So the safe-area/
off-screen/overflow checks do not account for `label:`/`unit:` width at all --
a slot whose label or unit runs long on the real device can overflow further
than the compiler warned about.

**The editor's animated highlight is handed the same estimated box, for the
same reason.** `getComplicationDrawable` needs a fixed `Graphics.BoundingBox`
up front, before anything is pulled, so it reuses the geometry lints'
estimate rather than the actual drawn extent (which, as above, is not known
until runtime). Whether that estimated box actually lines up with what is
drawn under the editor's animation is unverified along with everything else
about the editor.

**`on_hold: auto` on a `complication_slot` is a third shape of `auto`,
different from every other element's.** Every other element's `auto`
resolves once, at build time, to a fixed `wfb.complications.TYPES` name
(`Source.launch_complication`); a slot's resolves on-device, every hold,
from whatever `Complications.Id` the wearer currently has it pointed at.
Both compile to `Complications.exitTo`, but a slot's is never a build-time
constant -- there is nothing for `wfb complications`/`wfb validate` to name
as "the" target of a slot's hold, because there isn't one.

### `complication_slot`

Draws the native **Data axis**'s current pick — a slot the wearer re-points
at a different Garmin metric, on the watch. Documented in full under
[Configuration → The Data axis](#the-data-axis), alongside `config: data:`,
the block that declares a slot's own `default:`/`choices:` — the two cannot
be understood apart from each other, since the element only ever draws a
declared slot.

## See also

- [`examples/features/config/face.yaml`](../../examples/features/config/face.yaml) — accent/data colour axes and a `style:` entry over a static colour role.
- [`examples/features/slots/face.yaml`](../../examples/features/slots/face.yaml) — two `config: data:` slots, icon overrides.
- [Styles and layouts](styles-and-layouts.md) — `layout:` on a `style:` entry, and the `layouts:` bodies it points at.
- [Data](data.md) — the `complication.*` source namespace and the `complication_slot` element.
