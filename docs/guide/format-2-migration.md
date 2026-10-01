# Moving a face to format 2

Format 2 is the only format the compiler reads. A `format: 1` file is a
build error that names the one command that fixes it:

```sh
wfb migrate --in-place my-face.yaml     # rewrite the file
wfb migrate my-face.yaml                # print the format 2 version instead
wfb migrate --check faces/              # exit 1 if any *.yaml would change
```

The migrator rewrites the file once. **Comments, key order and quoting
survive**, and the face it writes generates the same Monkey C and the same
preview as the original did: format 2 renames and regroups, it does not
change what a face draws. A file already in format 2 passes through
unchanged.

## What it refuses

Some format 1 files cannot be rewritten faithfully. The migrator then
writes nothing and reports the line, the reason and what to change by hand:

- **`static: true` on an element nested inside a group.** Format 2 has no
  static flag, only the `static:` block ([Elements](elements.md#static--draw-it-once-then-blit-it)).
  A flagged element directly under `elements:` is moved into that scope's
  `static:` block for you; a nested one needs you to decide where it goes.
- **A `modes:` value other than `[active]` or `[active, low_power]`.**
  Format 2 has one switch, `sleep_update: true`
  ([Power modes](modes-and-interaction.md)).
- **A palette entry with the same name as a colour-scheme role.** Format 2
  names both as `color.<name>`, and refuses a name that means two things
  ([Colours](colors.md#colour-references)). Rename the palette entry, then
  run the migrator again.
- **A literal `text:` or `format:` with a `{`/`}` it cannot prove is
  literal.**

## Every rename

### Top level

| Format 1 | Format 2 |
|---|---|
| `format: 1` | `format: 2` |
| `targets:` | `build: {targets:}` |
| `fonts:` | `resources: {fonts:}` (entries unchanged, except `if_unavailable:` → `unsupported:`) |
| `palette:` | `resources: {palette:}` (entries unchanged) |
| `hands:` | `resources: {hand_sets:}` (parts: `shape:` → `type:`) |
| `color_scheme: {x: {label, colors}}` | `theme: {schemes: {x: {label, colors}}}` (values `palette.y` → `color.y`) |
| `antialias:`, `min_1px:` | `defaults: {antialias:, min_1px:}` |
| `aod: {default:}` | `defaults: {aod:}` |
| `aod: {dim:, mask:, lint:}` | unchanged |
| `config: {accent_color:, data_color:}` | unchanged keys; `default:`/`choices:` values `palette.y` → `color.y` |
| `config: {style: {choices: {x: {colors:}}}}` | `…{x: {scheme:}}` |
| `config: {data:}` | `config: {slots:}` |
| slot `default:`/`choices:` `complication.x` | `x` |
| slot choice `{type:, icon:, glyph:}` | `{type:, icon:}` (`icon:` takes a name, `"U+XXXX"` or `none`) |
| `static:`, `elements:`, `layouts:` | unchanged, mapping form only |

### Colour and slot references

| Format 1 | Format 2 |
|---|---|
| `palette.x` | `color.x` |
| `config.colors.r` | `color.r` |
| `config.accent_color` | `color.accent` (or the axis's `role:`) |
| `config.data_color` | `color.data` (or the axis's `role:`) |
| `slot: config.data.x` | `slot: x` |

### Every element

| Format 1 | Format 2 |
|---|---|
| list item `- id: x` + keys | mapping entry `x:` + keys |
| `static: true` | removed; the element moves into its scope's `static:` block |
| `modes: [active]` | omitted (the default) |
| `modes: [active, low_power]` | `sleep_update: true` |
| `vertical_align: v` | `align: v` |
| `align: h` + `vertical_align: v` | `align: v_h` (`top_left` …), or `align: h` when `v` is `center`, or `align: v` when `h` is `center` |
| `if_unavailable:` | `unsupported:` |
| `when_absent: hide` | `absent: hide` |
| `when_absent: placeholder` + `placeholder: s` | `absent: s` |
| `when_absent: fallback` + `fallback: e` | `absent: {value: e}` |
| `aod: {…}` | unchanged, with the per-kind renames below applied inside it |

### Per element type

| Format 1 | Format 2 |
|---|---|
| `type: shape` + `shape: s` | `type: s` |
| `shape: rounded_rectangle` | `type: rectangle` (keeping its `corner_radius:`) |
| `type: text` + `text: s` | `text: s`, with `{`/`}` doubled |
| `type: text` + `value: e` (+ `format: f`) | one `text:` template: `f` with `e` inside its placeholder (`"{e}"` when there was no `format:`); a top-level ternary gets parentheses |
| text `aod: {format: f}` | `aod: {text: …}`, built the same way from the element's own expression |
| `type: icon` + `glyph: g` | `icon: g` |
| `type: icon` + `icon_for: e` | `icon: {for: e}` |
| `type: complication_slot` | `type: data` |
| `icon_size`/`icon_position`/`icon_gap`/`icon_color` | `icon: {size, position, gap, color}` (inside `aod:` too) |
| `type: progress` | `type: gauge` |
| `type: hands` + `hands: s` | `set: s` |
| hand, pattern and `needle:` parts `shape: s` | `type: s` |
| a pattern's or part's `text`/`value`/`format` | as for `type: text` |

A `text:` template is covered in [Text](text.md#the-text-template), and
`color.<name>` in [Colours](colors.md#colour-references).

## Reserved for later

Format 2 fixes the vocabulary for features that are designed but not yet
built, so adding them later breaks nothing. Writing one today is a friendly
"not implemented" error rather than an unknown key:

| Reserved | What it will be |
|---|---|
| `resources: {components:}`, and `use:`/`with:` on an element | reusable element groups with parameters |
| `effects:` on an element | drop shadows and similar |
| `outline:` on a hand, pattern or needle part | the text outline, on parts |
| `parts:`, `arrange:`, `requires:`, `fallback:` on `type: data` | a data widget built from an icon, value, label, graph or gauge |
| a `[ {when: …, value: …}, …, {else: …} ]` list as any value | values chosen by rules over live data |
| `overrides:` | per-device adjustments |

`docs/limitations.md` §2 is the authoritative list.
