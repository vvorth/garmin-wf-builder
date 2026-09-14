# Plan 02 — Styles: layouts, colour schemes, or both

- **Date:** 2026-09-13
- **Status:** built 2026-09-13, all three phases (§12.8). `examples/styles/
  face.yaml` is the worked example; §12 has the measured `--build-stats`
  figures and the deviations found while building it.
- **Status:** (superseded) approved for building, 2026-09-13. The user
  answered §11 and added one restriction; **§12 records the decisions and
  the build plan that supersedes §7**. Where §12 disagrees with an earlier
  section, §12 wins. The earlier sections are kept as written, per house
  style.
- **Status:** (superseded) proposal. The axis decision is made (below). The
  YAML shape and naming await the user's review (§11). Nothing here is built.
- **Ask:** on a stock face, the native **Style** option changes *which
  elements are drawn* (a digital clock in one style, analog hands in
  another), not just colours. Plan how to build that, and how to write it in
  YAML. The user proposed two shapes: **(A)** a top-level container holding
  one sub-container per layout, drawn on top of the shared static content
  and elements, and itself allowed to be static; or **(B)** every element
  stays in `static:`/`elements:` and a property binds it to a layout.
- **Decided by the user (2026-09-13):** colours and layouts **share the
  Styles axis**, as explicitly listed entries. Each entry changes the colour
  scheme only, the layout only, or both.
  [Plan 01](01-background-color.md) records why there was no free axis to
  put layouts on separately.
- **Builds on:** research 08 §4, which sketched per-element variants; research
  09 §3, §5.1 and §5.4; ADR 0006 §1; the shipped `color_scheme:`/`config:
  colors:` machinery.

**An earlier draft of this plan** (same date, before the decision) gave
layouts the whole Styles axis, and used `styles:` as both the content block
and the element key. It was rewritten rather than amended, because the
decision changes the declaration model throughout. What survives unchanged is
the A-desugars-to-B recommendation (§4) and all of §5.3–§5.6 and §6.

---

## 1. What the platform gives

- **There are four editable axes, and all four are in use.** Styles holds
  this plan. Data holds `config: data:` complication slots (see
  `examples/slots/face.yaml`). Accent Color and Data Color are the two
  colour axes. None can be added
  (`bin/resources.xsd`, `watchfaceConfigType`).
- `WatchFaceConfig.Settings.styleId` is an **opaque `Number`**, and Garmin
  gives it no meaning (research 09 §3). This plan makes it mean "entry *i*
  of `config: style:`", and each entry decodes to a layout and/or a colour
  scheme.
- **A style is global.** One number selects the whole face's look. Every
  area of the face responds to that same number (research 08 §4).
- **It is per saved configuration.** Each of the wearer's four saved faces
  keeps its own entry (research 09 §5.4), which is the behaviour a stock face
  has.
- **One `<style>` entry costs about 9 B data and ~61 B `.prg`**, with no code
  growth (research 09 §3). Entries are nearly free. **Content is not:**
  every layout's elements, fonts and code are in the `.prg` together, so the
  128 KB budget is the **sum** over layouts. `--build-stats` measures that
  correctly, so the existing memory check needs no change.
- **A device without the native editor keeps the default entry forever.** On
  fr955 every other layout is dead weight; §6.8 covers how to strip it.

---

## 2. A prerequisite the example needs, flagged early

**The format has no analog hands today.** No element draws at an angle bound
to the time. `at: { angle: }` and `start_angle:` are build-time constants
(`schema/wfb-face-1.schema.json` `$defs/angle`). The mechanism here does not
depend on hands: it works identically for "big digital clock" vs. "small
clock + three rings". But the digital-vs-analog face that motivates it also
needs a separate element, such as a `type: hand` (a `polygon` rotated at
runtime by an angle expression). That is its own plan. The examples below
mark hands `# needs type: hand (§2)`, and the `examples/styles/` face this
plan ships uses two digital layouts instead.

---

## 3. Three names, three concepts

The decision creates three concepts, and each gets its own word:

| Concept | YAML | Garmin | Existing? |
|---|---|---|---|
| a named **set of widgets** | `layouts:` (top level), `layouts: [..]` (element) | none; ours | new |
| a named **set of colour roles** | `color_scheme:` | none; ours | shipped |
| an **entry in the editor's Style list** | `config: style:` | `<style id label>` | new, replaces `config: colors:` |

`layouts` rather than `styles` for the widget sets, for two reasons:

- **"Style" means exactly one thing: Garmin's axis.** A Styles entry is a
  *combination*, and its layout is one half of it. Using one word for both
  would make "a style with no style" a sentence the docs have to write.
- **It avoids a near-collision with `style: arc`** on `progress`, `graph` and
  `shape`, which the earlier draft's element-level `styles:` sat one letter
  away from.

---

## 4. The YAML

### 4.1 Declaring entries

```yaml
color_scheme:                          # unchanged
  dark:  { label: "Dark",  colors: { bg: palette.black, fg: palette.white } }
  light: { label: "Light", colors: { bg: palette.white, fg: palette.black } }

config:
  style:
    default: digital_dark
    choices:                           # editor order; index = styleId
      digital_dark:  { label: "Digital · Dark",  layout: digital, colors: dark }
      digital_light: { label: "Digital · Light", layout: digital, colors: light }
      analog:        { label: "Analog",          layout: analog,  colors: dark }
```

Each entry is **one line of the editor's list**, and the author writes exactly
the entries they want. There is no generated product: two layouts and two
schemes can be three entries, as above, or two, or four.

The two degenerate cases are the same shape with one field omitted:

```yaml
# colours only: today's config: colors:, re-spelled
config:
  style:
    default: dark
    choices:
      dark:  { label: "Dark",  colors: dark }
      light: { label: "Light", colors: light }

# layout only: no color_scheme: in the design at all
config:
  style:
    default: digital
    choices:
      digital: { label: "Digital", layout: digital }
      analog:  { label: "Analog",  layout: analog }
```

### 4.2 Declaring layouts, form A: a container per layout

```yaml
static:                                # shared: in every layout
  backdrop:    { type: shape, shape: rectangle, color: config.colors.bg, ... }
  bezel_ticks: { type: group, children: [...] }

elements:                              # shared: in every layout
  date:    { type: text, value: time.clock, format: "{:%a %d}", color: config.colors.fg, ... }
  battery: { type: text, value: system.battery, ... }

layouts:
  digital:
    static:                            # this layout's own fixed furniture
      steps_track: { type: shape, shape: arc, ... }
    elements:
      clock:     { type: text, value: time.clock, format: "{:%H:%M}", font: big, ... }
      steps_arc: { type: progress, style: arc, value: activity.steps, ... }

  analog:
    static:
      hour_numerals: { type: group, children: [...] }
    elements:
      mini_clock:  { type: text, value: time.clock, format: "{:%H:%M}", font: FONT_TINY, ... }
      hour_hand:   { type: hand, ... }   # needs type: hand (§2)
      minute_hand: { type: hand, ... }   # needs type: hand (§2)
      pin:         { type: shape, shape: circle, ... }
```

Expressions do not change: `config.colors.<role>` still reads the active
entry's scheme, in shared and layout content alike.

### 4.3 Declaring layouts, form B: a per-element property

> **Not built (§12, decision 1).** The user chose form A only. There is no
> element-level `layouts:` key.

```yaml
layouts: [digital, analog]             # declaration only: just the names

static:
  backdrop:      { type: shape, shape: rectangle, color: config.colors.bg, ... }
  bezel_ticks:   { type: group, children: [...] }
  steps_track:   { type: shape, shape: arc, layouts: [digital], ... }
  hour_numerals: { type: group, layouts: [analog], children: [...] }

elements:
  date:        { type: text, ... }
  battery:     { type: text, ... }
  clock:       { type: text, layouts: [digital], ... }
  steps_arc:   { type: progress, style: arc, layouts: [digital], ... }
  mini_clock:  { type: text, layouts: [analog], ... }
  hour_hand:   { type: hand, layouts: [analog], ... }   # needs type: hand (§2)
  minute_hand: { type: hand, layouts: [analog], ... }
  pin:         { type: shape, shape: circle, layouts: [analog], ... }
```

### 4.4 Comparing A and B

| | A. Container | B. Property |
|---|---|---|
| "What does the analog layout show?" | one block to read | scan the whole file for `layouts: [analog]` |
| An element in *some* layouts, e.g. 2 of 3 | duplicate it, or leave it shared | `layouts: [digital, minimal]` |
| Z-order across shared and layout content | fixed: layout content draws above shared content in its layer | anything; it is document order |
| Deleting a layout | delete one block | find and edit every membership |
| Precedent in this format | top-level `static:` block | per-element `modes:` list |
| What codegen and the IR need | a membership per element | a membership per element |

**Both compile to the same thing**: each element carries the set of layouts
it draws in.

---

## 5. Recommendation and semantics

### 5.0 A is sugar over B

> **Superseded (§12.2).** Form A is still a desugar rewrite, but it rewrites
> into reserved-id groups, not into a per-element key. Each element belongs to
> one layout or to none.

This is exactly what the format already does twice. The top-level `static:`
block is rewritten into a group with `static: true`. The mapping form of
`elements:` is rewritten into the list form by `wfb/desugar.py`, with a test
proving **byte-identical** output. So:

1. **Build B first**: per-element `layouts:` membership, through the IR,
   codegen, lint and preview. It is the only thing the back end ever sees.
2. **Add A in `wfb/desugar.py`.** Each `layouts: <name>: static:` becomes a
   group appended to top-level `static:`, and each `layouts: <name>:
   elements:` becomes a group appended to `elements:`. Both get the reserved
   id `layout_<name>` and carry `layouts: [<name>]`. A design written both
   ways must generate byte-identical Monkey C.
3. **Recommend A in the docs, the templates and the skill.** B stays
   available for multi-layout elements and for unusual z-order.

The draw order that results from A is what the user described:

```
static buffer:   shared static   ->  active layout's static     (one blit)
per frame:       shared elements ->  active layout's elements
```

### 5.1 `config: style:` entries

- `choices:` is an **ordered mapping** of entry name → `{label, layout,
  colors}`. Its order is editor order and the `styleId` mapping (index 0
  first), exactly as `resolveColorScheme` indexes today
  (`wfb/emit/monkeyc.py:1199`). `default:` names one entry. A mapping rather
  than a list gives entries stable names, for `default:`, for diagnostics
  and for `wfb preview --style`.
- **`label:`** is optional, as everywhere else. It becomes `<style label=…>`.
- **`layout:`** names one declared layout. **It is required on every entry
  when `layouts:` is declared, and rejected when it is not.** An entry
  showing only shared content in a face that has layouts would be a silent
  blank-looking face. If that is really wanted, the author can declare an
  empty layout.
- **`colors:`** names one declared `color_scheme:` entry. **It is required on
  every entry when any expression reads `config.colors.*`, and rejected when
  nothing does.** A role must never be undefined for the active entry.
- **At least one of `layout:`/`colors:`** is required per entry.
- **Two entries with the same `(layout, colors)` pair** get the suppressible
  `duplicate-style` warning. They are indistinguishable on the wrist, but a
  designer may want two labels while iterating.
- **`config: colors:` is replaced outright** by `config: style:` entries that
  carry `colors:`, with no shim. Today's `config: colors: {default: color_scheme.dark,
  choices: [...]}` is an unknown-key error after this, matching how
  `on_tap:`, `carousel` and `scale:` were removed (CLAUDE.md §6).
  `examples/config/face.yaml` is migrated in the same commit. The
  alternative, keeping `config: colors:` as sugar for colour-only entries, is
  listed in §11. It gives two spellings of one Styles axis, which can
  collide, and that is the reason it is not recommended.
- **Existing rules carry over to schemes:** identical role sets,
  `palette-dither` on every role of every scheme *an entry references*, and
  `config-unsupported` on fr955.

### 5.2 Layout membership rules

> **Simplified (§12.1).** With form A only, membership never nests or
> intersects, so the push-down and empty-intersection rules below do not
> apply. The rules for names, unreachable layouts, "no `config: style:`" and
> `visible:` still hold.

- **On a group, `layouts:` is pushed down and intersected** with each child's
  own set, the same way `visible:` is conjoined (`wfb/ir.py`,
  `_push_visible`).
- An **empty intersection** means the element draws in no layout. That gets
  the suppressible `dead-element` warning, as a constant-false `visible:`
  does.
- A layout name that is **undeclared**, or declared and rejected, is an error
  listing the declared names. Rejected names stay bound, so the result is
  **one error, not N** (CLAUDE.md §6). The same applies to entry names and
  scheme names in `config: style:`.
- A declared layout **no entry references** gets the suppressible
  `unreachable-layout` warning: its content ships in the `.prg` and can never
  be drawn. A declared layout with no content is legitimate, as the "shared
  content only" case above.
- `layouts:` declared with no `config: style:` is an error ("nothing lets the
  wearer pick a layout").
- **`visible:` composes with it:** the guard is layout membership *and*
  `visible:`.

### 5.3 Static content

**Layout membership is not a data binding.** It is a config value, like a
config colour, and those are already allowed in static content because
`applyConfig` repaints the buffer on every edit
(`wfb/emit/monkeyc.py:1182`). So layout-specific static content needs:

- no second buffer and no extra graphics pool, because `renderStatic` gains
  `if (layout == N)` guards around each layout's run;
- no new repaint logic, because an entry change reaches `applyConfig`, which
  already calls `repaintStatic()`.

The static rules (no bindings, no `graph`/`complication_slot`, no
`low_power`, one `modes:` per buffer) apply unchanged, across layouts
included.

### 5.4 Interactivity (`on_hold:`)

**This differs from `visible:`, and deliberately.** `visible:` keeps its hold
region while hidden, because the delegate cannot see that frame's readings.
The *layout* is a view field, and the delegate already holds `_view`. So
each hold hit test is guarded by layout membership, and **a hold on an
element of an inactive layout does nothing**. `hold-overlap` stops reporting
pairs whose layout sets are disjoint (§6.6).

### 5.5 `complication_slot` in a layout

> **Superseded by the user, 2026-09-13 (§12, decision 6).** A
> `complication_slot` is **not allowed** in layout content. Only the shared
> top-level `elements:` may hold one. The analysis below is kept because it
> explains the question that decision avoids.

The Data axis is face-wide, since `<data><complication id=…>` is declared
once. So:

- **one slot may be drawn by different elements in different layouts**
  (digital shows `config.data.top` at the top, analog at the bottom), and the
  wearer's pick carries across an entry change. Before building, check that
  nothing assumes one element per slot: `drawableFor(unique)` and the `onTap`
  hit test must resolve to the element in the *current* layout;
- a slot drawn by **no element in the current layout** is still listed by
  the editor. It is skipped by `onTap` and `getComplicationDrawable` returns
  `null`. Whether the editor then behaves sensibly is **UNVERIFIED** (§9).

### 5.6 Modes

This is orthogonal: `modes:` and `layouts:` are independent filters, and
`onPartialUpdate` gets the same layout guards as `onUpdate`.

---

## 6. Implementation

### 6.1 Schema (`schema/wfb-face-1.schema.json`)

- a top-level `layouts:` block, either a list of names (form B) or a mapping
  of name → `{static, elements}` (form A);
- an element-level `layouts:` string array, accepted by **every** element
  type. Common keys such as `modes` are currently repeated in each element's
  definition, not shared, so add it to all seven and add a test that walks
  the schema and fails if any element type lacks it;
- `config.style` with `default` and an ordered `choices` mapping of
  `{label, layout, colors}`;
- remove `config.colors`.

### 6.2 Desugar (`wfb/desugar.py`)

Rewrite form A into form B (§5.0). Normalise a form-A `layouts:` mapping to
the form-B name list. The source spans of the rewritten groups must point at
the author's own lines, using the ruamel `add_kv_line_col` four-value trick
(CLAUDE.md §6).

### 6.3 IR (`wfb/ir.py`)

- `Face.layouts`: an ordered list of names.
- `Face.config_style`: an ordered list of `StyleEntry(name, label, layout:
  str | None, colors: str | None)` plus the default. This replaces
  `ConfigColorAxis`.
- `Element.layouts: frozenset[str] | None`, where `None` means all layouts.
  Pushed down next to `_push_visible`.
- `Face.has_config` must turn on for a design whose only config is
  `config: style:`. That is the truthiness trap (CLAUDE.md §7), so it needs
  an explicit test.
- In the static checks (`_check_static_subtrees`), layout membership must
  **not** count as a binding.

### 6.4 View codegen (`wfb/emit/monkeyc.py`)

- **Decode one `styleId` into two things**, in a generated
  `resolveStyle(style)` that extends today's `resolveColorScheme`:

  ```monkeyc
  if (style == 0) {                    // digital_dark
      _configLayout = 0;               // layouts.digital
      _configColorsBg = 0x000000;      // color_scheme.dark
      _configColorsFg = 0xFFFFFF;
  }
  if (style == 1) { ... }              // digital_light
  if (style == 2) { ... }              // analog
  ```

  `applyConfig` range-checks `styleId` first, as it does today. If the design
  has layouts but no schemes, the colour assignments are simply absent, and
  vice versa.
- **Guards test the layout, never the entry.** Five entries over two layouts
  still produce two-way guards. Consecutive draw calls with the same layout
  set share one guard:

  ```monkeyc
  drawDate(dc, clock, settings);
  drawBattery(dc, stats);
  if (_configLayout == 0) {            // layouts: [digital]
      drawClock(dc, clock, settings);
      drawStepsArc(dc, activity);
  }
  if (_configLayout == 1) {            // layouts: [analog]
      drawMiniClock(dc, clock, settings);
      drawPin(dc);
  }
  ```

  A multi-layout set emits `||`, and a set covering every layout emits no
  guard. The same guards apply in `renderStatic` and `onPartialUpdate`.
- **Per-frame reads:** a source read only by an inactive layout is wasted
  work. Phase 1 reads everything, as today. Moving reads inside the guards
  is a later optimisation, and only worth doing if it is measured.
- The delegate's hold hit tests use the same guard through `_view` (§5.4).
  The view needs a public accessor, because `private` blocks cross-class
  access (CLAUDE.md §6).

### 6.5 Resources (`wfb/emit/resources.py`)

Emit one `<style id="i" label="@Strings.ConfigStyle<i>"/>` per entry, with
`default="true"` on the default. This is the same element today's scheme
styles emit; only the source of the label changes.

### 6.6 Lint (`wfb/lint.py`)

**Two elements with disjoint layout sets are never on screen together.**
Every *pairwise* check skips them: `overlap`, `static-overlap` and
`hold-overlap`. A digital clock and analog hands share the centre on
purpose. *Per-element* checks (text overflow, safe area, `palette-dither`)
run once, regardless of layout.

New suppressible codes: `duplicate-style` and `unreachable-layout`.
`config-unsupported` on fr955 names the non-default entries as unreachable.

### 6.7 Preview (`wfb/preview.py`, `wfb/cli.py`)

`wfb preview --style <entry>` renders one entry (layout plus scheme), and
defaults to the default entry. `--all-styles` lays every entry out side by
side in one PNG. This is the same renderer run N times, with no second
renderer, so ADR 0004's anti-drift guarantee holds.

### 6.8 Memory

- **Fonts:** `onLayout` loads every font, so a font used by one layout still
  occupies heap in the others. Phase 1 loads everything and **measures**. If
  the measurement shows a problem, a later phase loads a layout's fonts
  lazily in `applyConfig` and nulls the others (ADR 0008: measured, not
  estimated).
- **Stripping unreachable layouts on fr955** (optional, later). Monkey C's
  `excludeAnnotations` jungle property (`Reference_Guides/Jungle_Reference.html`,
  "Excluded Annotations") removes annotated members per device. Excluding a
  method its caller still names would be an undefined symbol, so this needs
  two annotated versions of a per-layout dispatcher, with one excluded per
  device. That is the shape the SDK's own example uses. **It needs a probe**,
  and is only worth doing if fr955 runs short of memory.

---

## 7. Phases

> **Superseded by §12.8.** Form B and Phase 4 are gone. The remaining work is
> re-cut into three phases.

Each step ends green. Every new diagnostic is driven red first, and each
real build must be warning-free on all three targets.

**Phase 1: colour-only entries (a re-spelling of shipped behaviour).**

1. Schema and IR: `config: style:` with `colors:` only; remove
   `config: colors:`; entry-name, scheme-name and "one error, not N" tests.
2. Codegen: `resolveStyle` replaces `resolveColorScheme`. The generated
   Monkey C for a migrated `examples/config/face.yaml` should differ only in
   names. Diff the golden output to prove it.
3. Migrate `examples/config/face.yaml` and `docs/format.md` "Color scheme" and
   "Configuration".

This is deliberately first. It lands the new declaration model with zero new
runtime behaviour, so anything that breaks is the re-spelling and not a
layout.

**Phase 2: layouts, form B.**

4. Schema and IR: `layouts:` (name list), element `layouts:`, `layout:` on
   entries, and the §5.1/§5.2 rules; `has_config`; the static exemption.
5. Codegen: `_configLayout`, grouped guards in `onUpdate`, `renderStatic`
   and `onPartialUpdate`, and layout-aware hold hit tests. Plus golden tests.
6. Lint: skip disjoint pairs, `duplicate-style`, `unreachable-layout`.
7. `examples/styles/face.yaml`: two digital layouts (§2) × two schemes, as
   three entries, each layout with its own static and dynamic content, and one
   element in both. Real `monkeyc` builds on all three targets, with
   `--build-stats` recorded.
8. Preview: `--style` and `--all-styles`.

**Phase 3: form A.** Desugar, a byte-identical test against the Phase 2
example rewritten in form A, a source-span test, and a switch of the example
and docs to form A.

**Phase 4: slots in layouts** (§5.5).

**Later, each only on a measurement or a request:** lazy per-layout fonts, the
fr955 annotation strip, and guarded reads.

**Docs, in the same commits:** `docs/format.md` (new "Styles and layouts"
section, replacing "Color scheme"'s `config: colors:` half); ADR 0006 §1
(amended: the Styles axis carries entries of layout × scheme); research 08 §4
and research 09 §3 (notes that the sketch shipped, and in what shape);
`docs/limitations.md`; CLAUDE.md constraint 9 and §6's roadmap; the `wfb new`
templates and the `watchface-from-image` skill; a session entry in
`docs/history.md`.

**Size:** Phase 1 is small. Phase 2 is medium: it touches every stage, but
each change follows an existing pattern (`modes:`, `visible:`,
`resolveColorScheme`). Phase 3 is small.

---

## 8. What was considered and not chosen

- **Separate axes for background and layout** (Plan 01 option B: the scheme
  on Data Color). This gives a swatch picker, but the menu reads "Data
  Color" and it costs the data colour. Declined by the user in favour of
  combined entries.
- **A generated layout × scheme product** (research 09 §5.1's arithmetic
  decode). It needs no per-entry authoring, but the list grows
  multiplicatively and the author cannot drop combinations that look bad.
  Explicit entries cost one line each and subsume it.
- **Layouts on their own `styles:` word** (this plan's earlier draft). See §3.

---

## 9. What cannot be verified here

The container has no simulator and no watch (CLAUDE.md Phase 2 finding 11),
so every **behavioural** claim needs the user's host simulator or a watch:

- that the editor lists the `<style>` labels and previews each entry live as
  the wearer scrolls, which depends on `onWatchFaceConfigEdited` arriving
  before commit (carried over from Plan 01 §7, question 4);
- that a slot absent from the current layout (§5.5) leaves the editor usable;
- that the static buffer repaints promptly on an entry change. It is
  expected to, since it shares the config-colour path, but that path is
  itself unverified on-device.

What *can* be verified here is what the project already verifies: a
warning-free build on all three targets, golden output, the cost from
`--build-stats`, and the preview.

---

## 10. Explicitly out of scope

- **Analog hands** (§2): a separate element and a separate plan.
- **Per-layout `config: data:` slot lists.** The Data axis is face-wide;
  there is no per-style list to generate.
- **Hold-to-cycle styles.** Declined by the user (research 08 §4), and
  `type: carousel` was removed.
- **Phone-side selection:** that is `wip/phone-settings`, which is frozen. Do
  not resume it without asking.

---

## 11. Open questions for the user

1. **A, B, or both, with A desugaring to B?** The recommendation is both
   (§5.0).
2. **Names:** `layouts:` for widget sets, `config: style:` for editor
   entries, and `colors:`/`layout:` fields on an entry. Should
   `config.colors.<role>` in expressions stay as it is, or become something
   like `scheme.<role>`? The recommendation is to leave it, since every
   existing design reads it.
3. **Replace `config: colors:` outright** (recommended, §5.1), or keep it as
   sugar for colour-only entries?
4. **In form A, may a layout's elements interleave with shared ones**, for
   example with a `z:`? Or is "layout content always above shared" the rule,
   with B as the escape route? The recommendation is the fixed rule.
5. **Which example should Phase 2 ship**, given that analog hands do not exist
   yet: two digital layouts, or should hands be planned first?

---

## 12. Decisions of 2026-09-13 and the build plan

### The user's answers

1. **Form A only.** Layouts are declared as containers
   (`layouts: <name>: {static, elements}`). Form B (§4.3), the element-level
   `layouts: [..]` key, is **not built**. Authors cannot write membership on
   an element. Form B's escape routes (an element in 2 of 3 layouts, unusual
   z-order) are not available. An element in several layouts is written once
   per layout, or put in shared content.
2. **Names** as §11 question 2 recommended: `layouts:` for widget sets,
   `config: style:` for editor entries, and `layout:`/`colors:` on an entry.
   `config.colors.<role>` in expressions is unchanged.
3. **`config: colors:` is removed outright**, with no shim. The three designs
   that use it are migrated in the same change: `examples/config`,
   `examples/enduro`, and `examples/dashboard`. For `dashboard`, the user's
   playground, the user explicitly permitted rewriting **only its `config:
   colors:` block**.
4. **Z-order is fixed:** layout content always draws above shared content, in
   its own layer (static and dynamic). There is no `z:` interleaving across
   the two. A `z:` still orders content *within* the shared content, or
   *within* one layout's content.
5. **Example:** two digital layouts. Analog hands stay out of scope (§2).
6. **New restriction: a `complication_slot` is not allowed in layout
   content.** Only the shared top-level `elements:` may hold one. This
   supersedes §5.5 and Phase 4. It is also simpler: the Data axis is
   face-wide, `drawableFor`/`onTap` need no per-layout dispatch, and the
   unverified "slot absent from the current layout" editor question (§9)
   cannot arise.

### 12.1 Membership model

Every element carries `Element.layout: str | None`. `None` means shared,
drawn in every layout. A name means it is drawn only while that layout is
active. Form A cannot nest one layout inside another, so there is no push-down
intersection, no empty set and no `dead-element` case (§5.2's first two
rules). Two elements are *never on screen together* exactly when both have a
layout and the two layouts differ.

### 12.2 Desugar (`wfb/desugar.py`)

It runs after the mapping-form rewrite and the top-level `static:` block.

- For each `layouts: <name>:` body in declaration order, `static:` (if
  present and non-empty) becomes `{id: layout_<name>_static, type: group,
  static: true, children: [...]}`. `elements:` (if present and non-empty)
  becomes `{id: layout_<name>, type: group, children: [...]}`. Both are
  **appended** to `elements:`, static first. Their content goes through the
  same mapping-form rewrite first.
- The `static:`/`elements:` keys are then removed from the body, and
  anything else in it (`lint:`, or an unknown key for the schema to report)
  stays. After desugar, `layouts:` is a mapping of name to `{}` (or to
  `{lint: ...}`). That is what carries the declared names and their order
  into the IR, empty layouts included.
- Spans use the `_static_block` technique: each group's position is that of
  the author's `static:`/`elements:` key, and the appended sequence indices
  get `add_idx_line_col`.
- **Reserved ids.** One helper defines the naming convention, and the IR
  imports it. An author id equal to a generated one is an error, and so are
  two layouts generating the same id (`digital` + `static` against a layout
  named `digital_static`). The error names both.

The IR assigns `layout = <name>` to each reserved group and every descendant,
by id. This happens right after `_build_elements` and **before** the static
checks, so a slot in a layout's `static:` gets the layout error only.

### 12.3 Draw order

`draw_sort_key` gains a layer rank `L` (0 for shared content, 1 for layout
content): `(0, L, static_rank, z)` for static content and `(1, L, 0, z)`
otherwise. `authored_draw_order` sorts by `(L, z)`, so `static-overlap` does
not report the fixed rule as a hoist. With `L = 0` everywhere, existing designs
order exactly as before, and their golden files do not move.

### 12.4 `config: style:` entries (revises §5.1)

- `choices:` is an ordered mapping of entry name to `{label?, layout?,
  colors?, lint?}`. `default:` names an entry. `colors:` and `layout:` take
  **bare names** (`colors: dark`, `layout: digital`), as in §4.1.
- **`colors:` is all-or-none across entries.** When some entries have it and
  others do not, that is one error at the first entry that differs. Reading
  `config.colors.<role>` when no entry carries `colors:` is the existing
  unknown-reference error, with a note. The rule "rejected when nothing reads
  `config.colors.*`" in §5.1 is **dropped**; today's behaviour for an unread
  scheme is kept.
- **`layout:` is required on every entry when `layouts:` is declared, and
  rejected when it is not.** Each entry needs at least one of
  `layout:`/`colors:`.
- **Label fallback:** an entry with no `label:` and **only** `colors:` takes
  its scheme's `label:`. That makes the migration of a `config: colors:` block
  a pure re-spelling with identical `<style>` resources. An entry with a
  `layout:` gets no fallback.
- One error, not N, as before: an entry naming an undeclared scheme or layout
  rejects the whole `config: style:`. A rejected `config: style:` then
  produces no second error from `config.colors.<role>` readers, from
  `default:`, or from "`layouts:` with no `config: style:`".

### 12.5 The slot rule

A `complication_slot` whose `layout` is not `None` is an error: one per slot,
at the slot's own line. The note says that the Data axis is face-wide and the
slot belongs in the top-level `elements:`. Tests cover three paths: directly
in `layouts.<n>.elements`, nested in a group there, and in
`layouts.<n>.static`. The last must yield the layout error alone, not also the
static one.

### 12.6 Suppression sites

`duplicate-style` and `unreachable-layout` are design-level, not
element-level, so there is no element `lint:` for them. They are suppressed by
a `lint: {allow: [...], reason: ...}` on the **style entry** (the second of a
duplicate pair) and on the **layout body** respectively. Both are checked
once per design, not once per target. `check_lint_allow` validates both new
sites.

### 12.7 Lint corrections to §6.6

The pairwise checks that exist are `hold-overlap` and `static-overlap`. There
is no general `overlap` check. Both skip pairs in different layouts.
`config-unsupported` on a device with no editor also names the non-default
style entries as unreachable. Its suppression stays with the elements that
bind `config.*` colours or slots, as today.

### 12.8 Phases (replaces §7)

Every phase ends with the fast suite at exactly the five known failures. In
every phase, the generated projects for `examples/slots`, `examples/slice`
and `examples/static` stay **byte-identical** to the pre-work baseline.

**Phase 1: `config: style:`, colours only.** Schema, IR, codegen
(`resolveStyle`), resources, lint (`duplicate-style`, scheme dither,
`config-unsupported`), preview defaults, and the migration of `config`,
`enduro` and `dashboard` (the config block only). `docs/format.md` is
updated. The migrated `examples/config` output differs from the baseline only
in names and comments, and the diff is shown.

**Phase 2: layouts, front end.** The `layouts:` schema, desugar, IR
membership, `layout:` on entries, every §5.2/§12 diagnostic (driven red),
the slot rule, `has_config`, draw order, and the static exemption. No
codegen yet: a design with layouts may fail to generate at this point, but
not silently. A clear "not implemented yet" is acceptable only as an
intermediate state inside the phase sequence.

**Phase 3: layouts, back end.** `_configLayout`, `resolveStyle`'s layout
half, grouped guards in `onUpdate`/`renderStatic`/`onPartialUpdate`, the
guarded hold hit test through a public view accessor, the lint pair skips,
`unreachable-layout`, `wfb preview --style`/`--all-styles`, and
`examples/styles/face.yaml`: shared static and elements (including a
`complication_slot`), two layouts with their own static and dynamic content,
two schemes and three entries. It must build warning-free with real
`monkeyc` on all three targets, with `--build-stats` recorded. The full docs
sweep from §7's "Docs" paragraph also lands here, minus the templates and the
skill, which do not mention config today.

---

## §12.9 What shipped, measured (2026-09-13)

All three phases built, in one session each. Two front-end fixes landed in
Phase 2 after independent review found them: an empty `static: []`/
`elements: []` inside a `layouts:` body was skipped but the key was not
popped, which left it for the schema's `minItems: 1` to wrongly reject
("treated as absent" now really pops it); and the reserved-id collision
check only scanned the top-level `elements:` list, missing an author id
nested inside a shared group's own `children:` -- both fixed with a
dedicated test each (`tests/test_layouts.py`).

**Deviations from this plan, all minor:**

- §6.4's own example shows `_configLayout = 0;` on its own line inside the
  `if (style == 0)` block, with the naming comment (`// layouts.digital`)
  *trailing* each line. What shipped keeps Phase 1/2's own convention
  instead: one *leading* block comment per entry naming everything it sets
  (`// big_dark -- color_scheme.dark, layouts.big`), then the assignments.
  Chosen for consistency with the already-reviewed Phase 1/2 code rather
  than introducing a second comment style partway through one function.
- §6.4 also describes a `||`-joined guard for "a multi-layout set" (an
  element belonging to more than one layout). That case cannot arise under
  form A (§12.1: `Element.layout` is `str | None`, never a set) -- it was
  relevant only to form B, which §12 decision 1 dropped. The shipped guard
  helper (`_emit_layout_guarded_calls`) emits a single `==` test; the `||`
  case is simply unreachable, not implemented-and-untested.
- `check_config_support`'s message went empty/ungrammatical for the edge
  case of a layout-only default entry with no other `config:` axis or slot
  at all (`"...so  keep their declared defaults here"`) -- found by a
  coordinator hand-probe during Phase 2 review, fixed with a three-way
  branch on whether there is a colour/slot name to report at all, and a
  test pinning it (`tests/test_layouts.py`).

**Measured, real `monkeyc`, `--build-stats`, all three targets, all three
warning-free:**

| Design | fenix8solar47mm | fenix8solar51mm | fr955 |
|---|---|---|---|
| `examples/config/face.yaml` (colour axes only, no `layouts:`) | 2,477 B (1.9%) | 2,478 B (1.9%) | 2,477 B (1.9%) |
| `examples/slots/face.yaml` (Data axis, no `layouts:`) | 6,661 B (5.1%) | 6,662 B (5.1%) | 6,668 B (5.1%) |
| `examples/styles/face.yaml` (two layouts, three entries, a shared slot) | 5,206 B (4.0%) | 5,207 B (4.0%) | 5,206 B (4.0%) |

`config`/`slots` are unchanged by this plan (no `layouts:`) and are listed
to show the byte-identity claim held under a real build, not only
`--no-compile`. `styles` is not a clean isolated "cost of layouts" delta
against either -- it simply draws more content (two static roots, two
schemes, a slot, a hold target) -- so it is reported as its own absolute,
measured figure rather than a subtraction dressed up as one, the same
restraint ADR 0006 §1's own amendments practise.

`slots`/`slice`/`static`/`config`/`dashboard`'s **generated projects** were
confirmed byte-identical to the pre-Phase-1 baseline (or, for `config`/
`dashboard`, to the end of Phase 1) after every phase, `--no-compile` and,
for `slots`/`config`, through a real `monkeyc` build too.
