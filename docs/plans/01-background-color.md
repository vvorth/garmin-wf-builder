# Plan 01 — A background-colour picker that matches the native editor

- **Date:** 2026-09-13
- **Status:** **decided: option A (combined Styles entries). Nothing here is
  built.** Background colour stays on the Styles axis, and each Styles entry
  names a colour scheme, a layout, or both. The design and the work live in
  [Plan 02](02-style-layouts.md). Option B is not being pursued, and its
  probe no longer gates anything. §1–§10 below are the original analysis,
  kept as the reasoning behind the choice.

> **Decision (2026-09-13).** The four native axes are Styles, Data, Accent
> Color and Data Color, and all four were already in use: colour schemes on
> Styles, complication slots on Data. There is no free fourth option for
> layouts, and renaming Styles to "color schemes" in YAML does not create one,
> because the editor's label is Garmin's. The user chose to keep colours and
> layouts on the same axis, as **explicitly listed combinations**. That is
> option A, with one change to its original description: the author lists
> exactly the entries they want (`"Digital · Dark"`, `"Analog"`, …)
> rather than the compiler generating the full layout × scheme product.
> An entry may change colours only, layout only, or both. So the "flat
> product list" cost described for A is under the author's control: a face
> offering three entries shows three entries.
>
> What this gives up, knowingly: no separate swatch-picker menu entry for
> background (option B's one advantage), and Data Color stays free for its
> original purpose. `config: colors:` as a standalone key is proposed to be
> **replaced** by `config: style:` entries with a `colors:` field
> ([Plan 02](02-style-layouts.md) §5.1).
- **Ask:** `config: colors:` (a `color_scheme:` riding the Styles axis) is
  really what a stock Garmin face calls **Bkgd. Color**. Make it match native,
  so the Styles axis is free to do what Styles does on a stock face: change
  *what is drawn* (see [Plan 02](02-style-layouts.md)).
- **Builds on:** research 09 §3 and §7, research 08 §4, ADR 0006 §1,
  `docs/format.md` "Color scheme" / "Configuration".

---

## 1. What native has, and what a Connect IQ face is allowed

| Stock fēnix face (native firmware) | Connect IQ face (`<watchface-config>`) |
|---|---|
| Style: digital, analog, … | **Styles**: `styleId`, an opaque `Number` |
| Data | **Data**: `COMPLICATION_TYPE_*` per slot |
| Accent Color | **Accent Color**: one `ColorType` |
| **Bkgd. Color** | *(does not exist)* |
| *(none)* | **Data Color**: one `ColorType` |

I re-checked this against SDK 9.2.0 for this plan, and every source agrees:

- `bin/resources.xsd` defines `watchfaceConfigType` as an `xs:all` with
  exactly four optional children: `styles`, `data`, `accentColors` and
  `dataColors` (lines 744–751).
- `WatchFaceConfig.Settings` has exactly four fields: `styleId`,
  `complicationSettings`, `accentColor` and `complicationColor`
  (`doc/Toybox/Application/WatchFaceConfig/Settings.html`).
- `bin/api.debug.xml` has exactly four `WATCH_FACE_CONFIG_TYPE_*` constants:
  `STYLE`, `COMPLICATION`, `ACCENT_COLOR` and `COMPLICATION_COLOR`.
- `<styles>`, `<accentColors>` and `<dataColors>` take no `label` attribute.
  Only the individual `<style>`/`<color>` entries do, so Garmin names the
  menu groups and an author cannot rename them.

**So the fifth menu entry, "Bkgd. Color", cannot be added.** That is the
platform's limit, not a gap in this compiler. Three parts of native
behaviour *can* be matched:

1. **A separate menu entry for background, not mixed into Styles.** This
   frees Styles for layouts.
2. **The swatch UX.** On a colour axis the wearer picks from colour swatches.
   On Styles they pick from a text list reading "Dark" and "Light".
3. **Per-saved-configuration.** Each of the wearer's four saved faces keeps
   its own background. Research 09 §5.4: only the four native axes do this.
   Anything the face stores itself is shared by all four.

The only question is which axis carries the background, and what that
costs.

---

## 2. Options

| | A. Keep it on Styles | **B. Ride a colour axis** | C. Phone settings | D. Free colour, roles derived |
|---|---|---|---|---|
| Separate menu entry from layouts | no, one flat product list | **yes** | yes, but on the phone | yes |
| Swatch picker like native | no, a text list | **yes** | no, a dropdown | yes |
| Frees Styles for Plan 02 | no | **yes** | yes | yes |
| Per saved configuration | yes | **yes** | **no**, global | yes |
| Menu entry reads | "Style" | **"Data Color" or "Accent Color"** (Garmin's label) | a setting name | "Data Color" or "Accent Color" |
| Costs the author an axis | no | **yes, the carrier axis** | no | yes |
| `fr955` | default forever | default forever | **works** | default forever |
| Unverified runtime assumption | none | returned colour ≈ declared colour (§6.2) | none | none |
| Built today | yes | no | frozen on `wip/phone-settings` | no |

**A. Keep `color_scheme:` on Styles.** Once Plan 02 puts layouts on Styles
too, the two multiply: 2 layouts × 3 backgrounds is six entries reading
"Digital · Black", "Digital · Gray" and so on. It is cheap (about 9 B of data
per style) and needs no new runtime assumption. The cost is UX: to change
only the background, the wearer has to find the right combination in one
flat list (research 09 §5.1). It is the fallback if B's probe fails.

**B. The scheme rides `dataColors` (or `accentColors`).** Each listed scheme
contributes one `<color>`: the colour of a role the author names as the
**swatch** (normally `bg`), labelled with the scheme's own `label:`. At
runtime the colour the editor returns is matched to the **nearest** declared
swatch, and that scheme's roles are applied. This matches native on two of
the three points, frees Styles, and the wearer sees swatches. The price:

- **The menu says "Data Color" (or "Accent Color"), not "Bkgd. Color".**
  No author control changes that.
- The author gives up that axis for its original purpose.
- It depends on the editor returning a colour close enough to the declared
  one to identify it. §6.2 explains why this is a *nearest* match rather than
  an equality test, and §7 says how to verify it.

Research 09 §7 recorded this idea as "not recommended". That verdict was
given while Styles had nothing better to do. Plan 02 gives Styles a job only
it can do, so it is worth revisiting. The two risks it named are handled
here: equality is replaced by nearest match, and the label is stated
plainly.

**C. Phone-side settings.** This is the only option that works on fr955. But
it is global across saved configurations, it is not on the watch at all,
and its implementation is frozen incomplete on `wip/phone-settings`. It is
the right home for things that are neither per-configuration nor visual. A
background colour is both, so C is wrong for it.

**D. A free colour picker with derived roles.** Use `data_color` with
`choices: any` as the background, and compute the other roles at runtime
(for example, `fg` becomes black or white by luminance). This is the most
native-like: the wearer gets the full palette. But `fg`/`dim` then follow a
rule rather than the designer's choice, a runtime contrast helper is needed,
and the 64-colour legality check cannot run on colours that are only known
at runtime. It is a possible later extension of B (`choices: any` plus a
`derive:` rule), not a replacement.

---

## 3. Recommendation

> **Superseded by the decision at the top of this file.** The user chose A,
> with explicitly listed entries. What follows was the recommendation
> before that decision.

**B, carried on `data_color` by default, gated on the §7 probe. If the probe
fails, fall back to A.**

- `data_color` rather than `accent_color`, because a stock face keeps both
  *Accent Color* and *Bkgd. Color*. Sacrificing Data Color keeps the one
  native entry a Connect IQ face can match exactly. The author can choose
  `on: accent_color` instead.
- The default for `on:` stays `styles`. Every existing design, including
  `examples/config/face.yaml`, which declares `data_color` *and* `colors`,
  keeps building unchanged. Plan 02 is what makes `on: styles` a poor choice,
  and its lint says so at that point (§9).

---

## 4. Proposed YAML

```yaml
palette:
  black:      { value: "#000000", label: "Black" }
  white:      { value: "#FFFFFF", label: "White" }
  navy:       { value: "#000055", label: "Navy" }
  light_gray: { value: "#AAAAAA", label: "Light Gray" }
  dark_gray:  { value: "#555555", label: "Dark Gray" }

color_scheme:
  black:
    label: "Black"                     # becomes the swatch's <color label=...>
    colors: { bg: palette.black, fg: palette.white, dim: palette.dark_gray }
  white:
    label: "White"
    colors: { bg: palette.white, fg: palette.black, dim: palette.light_gray }
  navy:
    label: "Navy"
    colors: { bg: palette.navy,  fg: palette.white, dim: palette.light_gray }

config:
  accent_color:
    default: "#FF5500"
    choices: any
  colors:
    on: data_color                     # styles (default) | data_color | accent_color
    swatch: bg                         # the role whose colour the editor shows
    default: color_scheme.black
    choices: [color_scheme.black, color_scheme.white, color_scheme.navy]

elements:
  - id: backdrop
    type: shape
    shape: rectangle
    at: { anchor: center }
    size: { width: 100%, height: 100% }
    color: config.colors.bg            # unchanged: a role reference
```

Expressions do not change at all: `config.colors.<role>` means the same thing
whichever axis carries the scheme. Only the `config: colors:` block grows two
keys.

`background:` would be a more native-sounding key name than `colors:`. It is
not proposed, because a scheme is several roles and a scheme with no `bg`
role is legitimate. See §10.

---

## 5. Rules

Each rule below is a build error unless marked otherwise. Each must be driven
red against violating input before it counts (CLAUDE.md §7).

1. **`on:`** accepts only `styles`, `data_color` or `accent_color`. Anything
   else is a schema error.
2. **`swatch:` is required when `on:` is a colour axis, and rejected when
   `on: styles`.** It must name a role every scheme declares. The existing
   identical-role-set rule already guarantees that if one scheme has it, all
   do.
3. **The carrier axis cannot also be declared directly.** `colors: on:
   data_color` together with `config: data_color:` is an error at both lines:
   "`data_color` already carries `colors`". Any expression reading
   `config.data_color` gets the same message. The rejected name must stay
   bound in scope so this produces **one error, not N** (CLAUDE.md §6,
   "a rejected named block's name must still be bound").
4. **Swatches must be distinct.** Two listed schemes whose swatch colours are
   equal cannot be told apart by the colour the editor returns, so this is an
   error naming both schemes. Distinct swatches that are *palette neighbours*
   are fine: nearest match separates any two distinct legal colours, because
   the 64-colour grid spaces them 0x55 apart.
5. **`choices: any` is rejected under a colour carrier.** The wearer could
   pick a colour matching no scheme. (Option D would lift this with an
   explicit derivation rule.)
6. **Existing checks carry over unchanged:** `palette-dither` on every role of
   every listed scheme, `default:` must be among `choices:`, and
   `config-unsupported` on fr955.

---

## 6. Codegen

### 6.1 Resource (`wfb/emit/resources.py`, `watchface_config`)

With `on: data_color`, the design emits no `<styles>` entry for the scheme.
Instead:

```xml
<dataColors>
    <color label="@Strings.ConfigScheme0" default="true">0x000000</color>
    <color label="@Strings.ConfigScheme1">0xFFFFFF</color>
    <color label="@Strings.ConfigScheme2">0x000055</color>
</dataColors>
```

One `<color>` per scheme, in `choices:` order, carrying the swatch role's
colour and the scheme's label. The string resources are the ones
`<style label>` already generates today.

### 6.2 View (`wfb/emit/monkeyc.py`, `_emit_apply_config` and `_emit_resolve_color_scheme`)

`resolveColorScheme(index)` is kept as it is: it is already "index → set
every role field". Only what produces the index changes. For a colour
carrier, `applyConfig` reads `settings.complicationColor` (or `.accentColor`)
with the same double null guard the colour axes use today. It then calls a
generated `nearestScheme(color)` that returns the index of the swatch with
the smallest squared RGB distance.

**Why nearest and not `==`:** `Color.color` is documented only as "the opaque
color selected by user from system or custom color palette". Nothing
promises that the value returned equals the `0x000055` that was declared.
Firmware could normalise it, or the palette could quantise it. An equality
test fails silently if that happens: the scheme never changes and there is
no diagnostic, which is exactly the constraint 7 failure shape. A nearest
match gives the identical result when the values *are* equal and still
behaves correctly when they are not. It costs a loop over N constants, and
N is the number of schemes.

A `null` colour, or a device with no editor, leaves the compiled default
scheme in place, exactly as today.

`applyConfig` already calls `repaintStatic()` after any settings change
(`monkeyc.py:1182`), so static content bound to a role repaints with no new
work.

### 6.3 Preview

No change is needed: the preview already renders the default scheme's roles
(`wfb/preview.py:117`). Plan 02 adds a `--style` flag, and `--colors
<scheme>` could come with it (§10).

---

## 7. Phase 0: the probe that gates this

> **No longer gating (B is not being pursued).** Question 4 still matters
> to Plan 02: whether the editor previews a Styles entry live, before
> commit. It is carried there as Plan 02 §9.

This cannot be checked in the container, which has no working simulator
(CLAUDE.md Phase 2 finding 11). It needs the **user's host simulator** or a
**watch**. Extend `docs/research/probes/watchface-config/` into a
`docs/research/probes/bg-color-axis/` that declares three labelled
`<dataColors>` and draws, on screen:

- the raw `settings.complicationColor.color` as hex;
- the index `nearestScheme` picks;
- whether that raw value `==` the declared constant.

It should answer:

| # | Question | Decides |
|---|---|---|
| 1 | What does the editor call the `dataColors` group for a CIQ face? | whether B's label cost is acceptable to the user |
| 2 | Are the `<color label>` strings shown alongside the swatches? | whether scheme labels are visible at all |
| 3 | Is the returned value equal to the declared one? Near it? Something else? | nearest match is required, merely safe, or broken |
| 4 | Is `onWatchFaceConfigEdited` delivered on each swatch *preview*, or only on commit? | whether the background previews live, as native does |

If question 3 turns out "something else" (for example, a palette index), B is
dead: fall back to A and record the finding in research 09 §7.

---

## 8. Work breakdown

> **Superseded.** With A chosen, nothing in this plan is built on its own.
> The colour half of a Styles entry is part of Plan 02 §7, and the
> `resolveColorScheme` machinery is reused as it is. This breakdown is kept
> in case B is ever revisited.

Ordered so that each step is independently green.

1. **Probe** (§7). Record the answers in `docs/research/probes/bg-color-axis/README.md`
   and append a short §8 to research 09. *Stop and show the user question 1's
   answer before continuing.*
2. **Schema:** add `on:` and `swatch:` to `config.colors` in
   `schema/wfb-face-1.schema.json`.
3. **IR** (`wfb/ir.py`, `ConfigColorAxis`): add `carrier` and `swatch`, plus
   rules 2–5 of §5, each with a red-then-green test in
   `tests/test_config*.py`. Test rule 3 as "one error, not N".
   `Face.has_config` must stay true when the only config is a colour-carried
   scheme. That is the truthiness trap recorded in CLAUDE.md §7, so it needs
   an explicit test.
4. **Resources:** emit `<dataColors>`/`<accentColors>` from the scheme, and no
   `<styles>`. Validate the output against `bin/resources.xsd`.
5. **View:** add `nearestScheme` and the new `applyConfig` branch. Add a
   golden test for the generated method.
6. **Real build:** a new `examples/bg-color/face.yaml`, warning-free under
   `-l 3` on all three targets. Record the cost with `--build-stats`, not
   `.prg` size, which is path-dependent (CLAUDE.md §6).
7. **Docs, in the same commit:** `docs/format.md` "Color scheme" and
   "Configuration", ADR 0006 §1 (third amendment), `docs/limitations.md`
   ("no Bkgd. Color axis; a colour-carried scheme is labelled by Garmin"),
   CLAUDE.md constraint 9, and a session entry in `docs/history.md`.

**Size:** small. Steps 2–6 are an extension of shipped machinery. The probe is
the only real unknown.

---

## 9. How this interacts with Plan 02

> **Resolved.** Colours and layouts share Styles, as explicitly listed
> entries. See Plan 02 §5.1. The bullets below describe the situation before
> the decision.

- Plan 02 puts layouts on Styles. If `config: style:` and `config: colors:
  on: styles` are declared together, both want the same axis. Plan 02's
  first phase makes that an error that points here (`on: data_color`). A
  later phase may instead generate the A-style cross-product. The error comes
  first because it is reversible, and a flat product list is a UX decision
  the user should make knowingly.
- If the probe kills B, Plan 02 must build the cross-product. That moves it
  from "later" to "required" and should be decided before Plan 02 phase 1
  ships.

---

## 10. Open questions for the user

> **Answered by the decision at the top.** Questions 1, 2 and 4 are moot
> under A. Question 3, the naming of the colours key, moves to Plan 02 §11.

1. **Is a menu entry labelled "Data Color" acceptable for the background?**
   This is the whole trade in B. Question 1 of the probe shows what it
   actually looks like.
2. **Should the carrier default to `data_color` or `accent_color`?**
   The recommendation is `data_color` (§3).
3. **Keep the key name `colors:`, or rename it to `background:`?** Previous
   renames were done outright with no shim (CLAUDE.md §6), so a rename is
   cheap if wanted.
4. **Option D later?** That is `choices: any` with `fg`/`dim` derived by a
   contrast rule: more native, less designed.
