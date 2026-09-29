# 22 — Format 2: a designed revision of the YAML format

**Status: approved for implementation (decisions F1–F7 and Q1–Q5, and
the names in §2, 2026-09-28). Being built on branch `format-2`, one commit
per slice; progress is recorded under each slice in §6. Slices 0–4 are
done: format 2 is the only format the compiler reads.** Delete this file once
slice 5 has shipped (`docs/CLAUDE.md`).

**Goal.** Format 1 grew one feature at a time. Format 2 fixes its naming
and hierarchy in one designed break:

- one colour namespace;
- platform-shaped names replaced by author-shaped ones;
- one spelling per idea;
- a grouped top level.

It also reserves the vocabulary for the concepts research 18 proposes
(`docs/research/18-device-independent-face-model.md`), so those can be built
later without another break.

**What does not change.** Format 2 is a **front-end change**. The v2
document is validated against a v2 schema on the author's own lines, then
`wfb/desugar.py` lowers it into the internal shape `wfb/ir/builder/`
already reads. The IR, layout, lint, codegen and preview do not change,
so **a v1 face and its migrated v2 face generate byte-identical projects
and pixel-identical previews**. `tools/snapshot.py` proves that (§6).
Renaming the builder's own internal key names is out of scope.

---

## 1. Decisions

| # | Question | Decision (2026-09-28) |
|---|---|---|
| F1 | Style cross-product sugar | **No.** Not every scheme suits every layout; style entries stay an explicit list of (layout, scheme) pairs |
| F2 | `static` | **Explicit, block form only.** `static:` blocks (top level and per layout) stay; the `static: true` flag is removed. An advisory `static-candidate` lint is a later, separate item (§5) |
| F3 | Colour references | **One namespace, `color.<name>`**: a role first, then a palette swatch; a name that is both is a build error (§3.2) |
| F4 | Format 1 files | **`wfb migrate` rewrites them once; then the compiler reads format 2 only.** `format: 1` becomes a friendly error naming `wfb migrate`. ADR 0009 gets a dated amendment (§7) |
| F5 | Rollout | Migrator first. Both formats compile side by side for one slice, then one switch-over commit (§6). *Not asked; the plan's default* |
| F6 | Scope | **Renames and regrouping now.** New concepts are designed here (§5), reserved as friendly "not implemented" errors, and built later, each under its own plan |
| F7 | Order | **Format 2 first**, then plan 20's `overrides:` (D1), `when:` and the data widget, all in v2 vocabulary |
| Q1 | Slot-drawing elements inside a layout | **Keep the face-wide rule.** The SDK would allow a per-layout position (the editor's hit-test and drawable are the face's own code: `Core_Topics/Editing_Watch_Faces_On_Device.html`, `WatchUi/WatchFaceDelegate.html`), but it is not wanted |
| Q2 | `%` vs `%r` | **Leave as is.** No lint, no change |
| Q3 | A null reading in a `text:` template | **One `absent:` per element.** Any null reading makes the element absent, which is today's semantics |
| Q4 | Component parameters | **Plain substitution.** `params:` with defaults; `$name` stands for any whole value; no logic inside a component |
| Q5 | Power-state overrides vs `when:` | **Two mechanisms.** The per-element `aod:` block (build time, its own draw path) stays. `when:` rule lists (runtime data) may not test the power state |

## 2. Names (approved 2026-09-28)

| # | Choice | Why |
|---|---|---|
| N1 | `modes: [active, low_power]` becomes **`sleep_update: true`** (default `false`) | In format 1, `modes:` is not about visibility. `active` means drawn in `onUpdate`, which includes the once-a-minute update while asleep. `low_power` means *also* redrawn every second while a MIP watch sleeps (`onPartialUpdate`) (`docs/guide/modes-and-interaction.md`). Every element is redrawn once a minute while asleep anyway, so the key is a boolean: "also update every second while asleep". It is a build error on an AMOLED target, as `low_power` is today. Names with "interval" were rejected because an element always updates every second while awake, so `update_interval: minute` would mislead. The draft's `show_in:` was wrong and is dropped |
| N2 | Per-element `aod: hide \| show \| {…}` **unchanged** | It already is the per-state override block the draft proposed as `in: {aod: …}` |
| N3 | `align:` takes the nine anchor names (`top_left` … `bottom_right`, `center`); `vertical_align:` is removed. **`anchor:` and `align:` also accept compass aliases**: `N`, `NE`, `E`, `SE`, `S`, `SW`, `W`, `NW` for `top`, `top_right`, `right`, `bottom_right`, `bottom`, `bottom_left`, `left`, `top_left`. Uppercase only; `center` has no alias. The migrator writes the long names | The same vocabulary as `anchor:`. Both v1 keys default to `center`, so v1 `align: left` means v2 `align: left` unchanged, and `align: left` + `vertical_align: top` becomes `align: top_left`. A bare `N` loads as a string with `wfb`'s YAML 1.2 loader (VERIFIED, ruamel round-trip). A YAML 1.1 tool would read `N` as `false`, so a test pins the loader's behaviour and the guide says to quote it (`"N"`) for 1.1 editors |
| N4 | Hand, pattern and needle parts use **`type:`**, like elements | One word for "what primitive" |
| N5 | Primitive element types: `rectangle`, `circle`, `line`, `arc`, `ellipse`, `polygon`; **`rounded_rectangle` removed** (a `rectangle` with `corner_radius:`) | `type: shape` + `shape: X` said the same thing twice |
| N6 | `complication_slot` becomes **`type: data`**; `icon_size`/`icon_position`/`icon_gap`/`icon_color` become `icon: {size, position, gap, color}` | An author-shaped name, and the element research 18's widget extends later (§5) |
| N7 | `progress` becomes **`gauge`**. **`absent: hide` on a gauge keeps the value-independent drawing**: the arc or bar track, every segment unlit (`track_color`), and a scale's track and bands. Only what depends on the value (fill, lit segments, pointer, needle) is hidden, so the face never shows an empty gap. A `needle` gauge has nothing value-independent, so it draws nothing. To hide a gauge completely, use `visible:` (absent means hidden). `unsupported: hide` still hides everything: on a gauge it only concerns `anchor: subscreen`, and with no subscreen there is nowhere to draw a track | It also covers needle, segments and scale. The empty-track behaviour is new (v1 `when_absent: hide` draws nothing), so it has its own slice (§6, slice 4) |
| N8 | `color.<name>` everywhere a colour is named, including scheme values and `config:` choices | "A colour reference is `color.x` or a hex literal", with no exceptions |
| N9 | `config:` colour axes keep their names `accent_color`/`data_color`; they bind roles `accent`/`data` (an optional `role:` renames the role) | `config.data` is gone (it is `slots:` now), so nothing is ambiguous |
| N10 | A slot's `default:`/`choices:` take bare complication names (`steps`), as `on_hold:` already does | One spelling for a complication type |
| N11 | `theme: {schemes: {<name>: {label, colors}}}` | The user's own phrasing. The `colors:` sub-map stays, so a role can't collide with `label` |
| N12 | `resources: {fonts, palette, hand_sets}`, with `components` reserved | Groups declarations that elements refer to |
| N13 | On `type: hands`, `hands: <set>` becomes **`set: <set>`** | Removes the `hands.hands` collision |
| N14 | `if_unavailable:` becomes **`unsupported: hide \| error`** (elements and `fonts:` entries) | Distinct from runtime absence |
| N15 | `when_absent` + `placeholder` + `fallback` become **`absent: hide \| "<text>" \| {value: <expr>}`**. It stays required on a nullable reading | One key for runtime null |
| N16 | `text:` / `value:` + `format:` become **one `text:` template**: `"{expr:spec}"`, `{{`/`}}` for literal braces, a top-level ternary parenthesised. **Format 2.0 accepts zero or one placeholder per text**; more is reserved (§5) | v1 `format:` is already a one-placeholder template (`"{:.1f}k"`); the expression moves inside it |
| N17 | `build: {targets}`; `defaults: {antialias, min_1px, aod}` (the inheritable per-element defaults); the face-wide AOD frame settings `aod: {dim, mask, lint}` stay top level | Build config, element defaults and face settings are three different things |
| N18 | `elements:`, `static:` and `children:` take the **mapping form only** | One spelling |

Unchanged: `face:` (`id`, `name`, `version`, `entry`), `format:`
(now `2`), `fonts:` entries (keys and `font.<name>` references), palette
entry forms, `layouts:` bodies, `lint:`, `z:`, `on_hold:`, `seconds:`,
`units:`, `outline:`, `curve:`, `at:`/`position`, `size:`, `graph`,
`pattern`, `group`, lengths and units, the expression language, data source
names (`complication.*` included), and the reserved `overrides:`.

## 3. Format 2 reference

### 3.1 Shape

```yaml
format: 2
face:     { id: 5ca5867b-…, name: Showcase, version: 1.3.0 }
build:    { targets: [fenix8solar47mm, fenix8solar51mm, fr955] }
defaults: { antialias: true, min_1px: false, aod: hide }
aod:      { dim: 0.6, mask: true }         # face-wide AOD frame settings

resources:
  fonts:
    digitalclock: { source: assets/ChivoMono-Bold.ttf, size: 60%r, monospace: true }
  palette:
    black: "#000000"
    white: "#FFFFFF"
    light_gray: "#AAAAAA"
    dark_gray: "#555555"
    red:   { value: "#FF0000", label: Red }
    amber: { value: "#FFAA00", label: Amber }
  hand_sets:
    classic:
      hour:   { color: color.fg, parts: [ { type: polygon, points: [ … ] } ] }
      minute: { color: color.fg, parts: [ { type: rectangle, at: { dy: -34%r }, size: { width: 3%r, height: 78%r } } ] }
      second: { color: color.dim, parts: [ { type: line, at: { dy: 14%r }, to: { dy: -76%r }, thickness: 1px } ] }

theme:
  schemes:
    dark:  { label: Dark,  colors: { bg: color.black, fg: color.white, dim: color.light_gray, surface: color.dark_gray } }
    light: { label: Light, colors: { bg: color.white, fg: color.black, dim: color.dark_gray,  surface: color.light_gray } }

config:
  style:
    default: digital_dark
    choices:                               # explicit pairs (F1)
      analog_dark:   { label: "Analog · Dark",   layout: analog,  scheme: dark }
      digital_dark:  { label: "Digital · Dark",  layout: digital, scheme: dark }
      digital_light: { label: "Digital · Light", layout: digital, scheme: light }
  accent_color: { default: color.red,   choices: [color.red, color.amber] }   # role `accent`
  data_color:   { default: color.amber, choices: any }                        # role `data`
  slots:
    left:  { default: steps, choices: [steps, heart_rate, { type: calories, icon: none }] }
    right: { default: body_battery, choices: any }

static:                                    # shared, drawn once into the buffer, under everything
  background: { type: rectangle, size: { width: 100%, height: 100% }, color: color.bg }
  left_card:  { type: rectangle, at: { anchor: center, dx: -50%r, dy: -23%r },
                size: { width: 42%r, height: 19%r }, corner_radius: 3%r, color: color.surface }

elements:                                  # shared, drawn every frame
  left_register:
    type: data
    slot: left
    at: { anchor: center, dx: -50%r, dy: -30%r }
    font: FONT_XTINY
    icon: { size: 9%r, position: top, gap: 1%r, color: color.data }
    color: color.fg
    absent: "--"
    on_hold: auto

layouts:
  analog:
    static:
      dial_ring: { type: arc, radius: 94%r, thickness: 2px, start_angle: 0deg, sweep: 360deg, color: color.dim }
    elements:
      hands: { type: hands, set: classic, seconds: awake }
      notifications:                       # a group: children in its own frame
        type: group
        at: { anchor: center, dy: -20% }
        size: { width: 25%, height: 25% }
        children:
          icon:  { type: icon, icon: notification, size: 25%r, color: color.dim }
          count: { type: text, text: "{device.notification_count:d}", font: FONT_TINY,
                   at: { dy: -2%r }, color: color.bg, absent: hide }
  digital:
    elements:
      hours:
        type: text
        text: "{time.hour:02d}"
        font: font.digitalclock
        at: { anchor: center, dx: -1%, dy: 7% }
        align: right
        color: color.fg
      steps:
        type: text
        text: "{activity.steps / 1000.0:.1f}k"
        font: FONT_XTINY
        absent: "--"
        sleep_update: true                 # v1 modes: [active, low_power]
        aod: { color: color.dim }
      hr_graph:
        type: graph
        series: heart_rate
        range: 4h
        size: { width: 52%r, height: 17%r }
        color: color.data
```

### 3.2 Colour resolution

`color.<name>` resolves to:

1. **a role**: a key of every scheme's `colors:` (the schemes must already
   declare identical role sets), or the role a colour axis binds
   (`accent_color` binds `accent` and `data_color` binds `data` unless
   `role:` says otherwise). A role's value follows the active style's
   scheme, or the wearer's pick;
2. otherwise, **a palette swatch**.

- **Collisions are errors.** A name that is both a role and a swatch is a
  build error at *both* declarations, never shadowing. So is a scheme role
  named `accent`/`data` while the matching colour axis is declared.
- **Swatches only where a literal is needed.** Where a build-time literal is
  required (scheme values, colour-axis `default:`/`choices:`, palette-rule
  checks), `color.<name>` must resolve to a swatch; a role there is an error
  naming why.
- **Inside expressions:** `color.<name>` is a reference like any other, so
  `"activity.steps > 9000 ? color.accent : color.fg"` is valid.

### 3.3 Text templates (N16)

- `text: "literal"` is a fixed string. `{` and `}` are written `{{` and
  `}}`.
- `text: "{expr}"` and `text: "{expr:spec}"`: one placeholder. The
  expression ends at the first `:` outside parentheses, brackets and quotes,
  so a ternary must be parenthesised: `"{(x > 0 ? x : 0):d}"`. `spec` is
  exactly v1's `format:` spec, strftime and duration forms included.
- Literal text around the placeholder is allowed, as in v1: `"{…:.1f}k"`.
- `units:` applies when the one placeholder is exactly one source with a
  physical quantity, as in v1.
- **Two or more placeholders are a friendly "not implemented" error** in
  format 2.0 (§5).
- The same rules apply to a pattern text part. An `aod:` override's
  `text:` may change the literal text and the spec, but not the placeholder's
  expression. That is v1's rule for `format:` overrides, now applied to the
  template.

### 3.4 Complete v1 → v2 mapping

**Top level**

| v1 | v2 |
|---|---|
| `format: 1` | `format: 2` |
| `targets:` | `build: {targets:}` |
| `fonts:` | `resources: {fonts:}` (entries unchanged, except `if_unavailable:` → `unsupported:`) |
| `palette:` | `resources: {palette:}` (entries unchanged) |
| `hands:` | `resources: {hand_sets:}` (parts: `shape:` → `type:`) |
| `color_scheme: {x: {label, colors}}` | `theme: {schemes: {x: {label, colors}}}` (values `palette.y` → `color.y`) |
| `antialias:`, `min_1px:` | `defaults: {antialias:, min_1px:}` |
| `aod: {default:}` | `defaults: {aod:}` |
| `aod: {dim:, mask:, lint:}` | `aod: {dim:, mask:, lint:}` (unchanged) |
| `config: {accent_color:, data_color:}` | unchanged keys; `default:`/`choices:` values `palette.y` → `color.y` |
| `config: {style: {choices: {x: {colors:}}}}` | `…{x: {scheme:}}` |
| `config: {data:}` | `config: {slots:}` |
| slot `default:`/`choices:` `complication.x` | `x` |
| slot choice `{type:, icon:, glyph:}` | `{type:, icon:}` (`icon:` takes a name, `"U+XXXX"` or `none`) |
| `static:`, `elements:`, `layouts:` | unchanged, mapping form only |

**References inside expressions and colour values**

| v1 | v2 |
|---|---|
| `palette.x` | `color.x` |
| `config.colors.r` | `color.r` |
| `config.accent_color` | `color.accent` (or its `role:`) |
| `config.data_color` | `color.data` (or its `role:`) |
| `slot: config.data.x` | `slot: x` |

**Every element**

| v1 | v2 |
|---|---|
| list item `- id: x` + keys | mapping entry `x:` + keys |
| `static: true` | removed. The migrator moves a flagged element that is a direct entry of a scope's `elements:` into that scope's `static:` block, appended in authored order. It refuses a nested flagged element (§4) |
| `modes: [active]` | omitted (the default) |
| `modes: [active, low_power]` | `sleep_update: true` |
| any other `modes:` value | the migrator refuses (§4) |
| `align: h` | `align: h` (unchanged) |
| `vertical_align: v` | `align: v` |
| `align: h` + `vertical_align: v` | `align: v_h` (`top_left` …), or `align: h` when `v` is `center`, or `align: v` when `h` is `center` |
| `if_unavailable:` | `unsupported:` |
| `when_absent: hide` | `absent: hide` |
| `when_absent: placeholder` + `placeholder: s` | `absent: s` |
| `when_absent: fallback` + `fallback: e` | `absent: {value: e}` |
| `aod: {…}` | unchanged, with the per-kind renames below applied inside it |

**Per kind**

| v1 | v2 |
|---|---|
| `type: shape` + `shape: s` | `type: s` |
| `shape: rounded_rectangle` | `type: rectangle` (its `corner_radius:` already present) |
| `type: text` + `text: s` | `text: s` with braces doubled |
| `type: text` + `value: e` (+ `format: f`) | `text:` = `f` with `e` inserted into its placeholder (default `"{e}"`); a top-level ternary gets parentheses |
| text `aod: {format: f}` | `aod: {text: …}` built the same way from the element's own expression |
| `type: icon` + `glyph: g` | `icon: g` |
| `type: icon` + `icon_for: e` | `icon: {for: e}` |
| `type: complication_slot` | `type: data` |
| `icon_size`/`icon_position`/`icon_gap`/`icon_color` | `icon: {size, position, gap, color}` (also inside its `aod:`: `icon_color` → `icon: {color}`) |
| `type: progress` | `type: gauge` (keys unchanged apart from `absent:`) |
| `type: hands` + `hands: s` | `set: s` |
| hand, pattern and `needle:` parts `shape: s` | `type: s` |
| pattern / part `text`/`value`/`format` | as for `type: text` |
| pattern `when_absent: hide` | `absent: hide` |

## 4. `wfb migrate`

- **Behaviour.** `wfb migrate FILE…` prints the v2 document to stdout;
  `--in-place` rewrites the file; `--check` exits 1 if a file would change.
  It works on the ruamel round-trip tree (`wfb/yamlsrc.py`'s loader), so
  **comments, key order and quoting survive**. The examples depend on their
  comments.
- **Mechanics.** It lives in `wfb/migrate.py` as an ordered list of small
  rule functions, one per row group of §3.4. Expression references
  (`palette.`, `config.colors.`, `config.accent_color`, `config.data_color`)
  are rewritten token by token through `wfb.expr`'s tokenizer, never with a
  regular expression, so a string literal or a longer identifier is never
  touched.
- **Idempotent:** a v2 file passes through unchanged.
- **Refusals.** It refuses, with the file, the line, the reason and what to
  do by hand, and leaves the file untouched:
  - a `static: true` element nested inside a non-static group;
  - a `modes:` value other than `[active]` or `[active, low_power]`;
  - a colour role/swatch name collision the v2 rules would reject;
  - a value with a top-level `{`/`}` that it can't prove is literal text.
- **Fragments mode:** it also works on a YAML fragment with no `format:`,
  which is how most test inputs are written (§6, slice 3).
- **Not a validator.** Its output is compiled like any v2 file. A v1 file
  that was invalid gives a v2 file that is invalid in the same way.

## 5. Designed, reserved, built later (F6)

Each item below is a **friendly "not implemented" build error** in format
2.0, like `overrides:` today. The vocabulary is fixed now, so building one
later is additive. Each needs its own plan before it is built.

| Item | Reserved syntax | Notes |
|---|---|---|
| Several readings in one text | `text: "{time.hour:02d}:{time.minute:02d}"` | Q3: any null → the element's `absent:` |
| Components | `resources: {components: {card: {params: {width: 42%r}, body: {…}}}}`; `use: card` + `with: {width: 30%r}` on an element | Q4: `$name` substitutes a whole value; the use site may also set `at:`, `align:`, `z:` and `visible:` |
| Effects | `effects: {shadow: {color:, dx:, dy:}}` on any element | Replaces the duplicated shadow elements in the showcase's `top_data` |
| Outline on parts | `outline:` on hand, pattern and needle parts | Replaces the doubled `vintage` hand parts |
| Data-widget parts | `type: data` + `parts: [icon, value, label, graph, gauge]`, `arrange: stack \| row \| icon_left`, `requires:`/`fallback:` | Research 18 §10. A graph part needs a complication-type → series map (research 18 §7) |
| `when:` rule lists | any property: `[ {when: <bool expr>, value: …}, …, {else: …} ]` | Q5: may not read the power state |
| Per-device overrides | `overrides:` as ADR 0004 §4 specifies, in v2 key names | Plan 20 D1, rebased onto v2 (F7) |
| `static-candidate` lint | a new advisory lint | F2. Not a format change, so it may be built at any time |

## 6. Slices

Every slice keeps the fast suite green, `mypy --strict` clean over `wfb/`
(`pytest -m typecheck`), and a real `monkeyc` build warning-free on the
three verification devices.

**Slice 0 — baseline.** *Done 2026-09-28.*
- On `main` before any change: `tools/snapshot.py save`, and record the
  commit in this plan.
- Saved from `6cfb9b6` to `build/snapshots/format2-baseline` (gitignored,
  so local to this checkout; re-create it with `git worktree add` at that
  commit and the same command if it is lost): 441 cases, 0 errored,
  5,787 artifacts.

**Slice 1 — the migrator.**
- `wfb/migrate.py`, the `migrate` CLI command, and tests:
  - one test per §3.4 row;
  - each refusal, driven red first;
  - idempotence;
  - comment preservation;
  - fragments.
- No compiler change.
- Check: `wfb migrate --check` over every example and `wfb/templates/*.yaml`
  migrates everything without a refusal, or each refusal is expected and
  written down here.
- *Done 2026-09-28.* `wfb/migrate.py`, `wfb/template.py` (the v2 template
  parser, shared with slice 2) and `tests/test_migrate.py`. Every example,
  template and fixture migrates and re-migrates unchanged, except two,
  both refused for the §3.2 colour collision and both expected:
  `examples/enduro/face.yaml` (palette `bg`, `fg`, `dim`, `dark` are also
  scheme roles) and `examples/features/config/face.yaml` (palette `bg`,
  `text`). Slice 3 renames those palette entries by hand before migrating.
  Decided while building: a group's `aod: {format:}` becomes
  `aod: {text: "{:spec}"}`, a placeholder with no expression, standing for
  each descendant's own; a text element's `aod:` template repeats the
  element's expression. `{unit}` stays the unit label, not a placeholder.
  The refusals also cover a v1 format with no field or with two, a
  `static: true` inside a `static:` block, and the placeholder text `hide`
  (which would read as `absent: hide`).

**Slice 2 — format 2 alongside format 1.**
- Add `schema/wfb-face-2.schema.json`, normative, with every description
  in v2 terms.
- Dispatch on `format:`. A v2 document is schema-checked on the author's
  own lines, then `desugar` lowers it into the internal shape the builder
  already reads, keeping source spans on every moved node.
- Every §5 key gets its friendly error.
- **Every diagnostic that names a key must name the v2 key when the input
  is v2.** Add a test that runs the error-fixture corpus through v2 and
  fails on any removed v1 key name in a message. Drive it red before fixing
  the messages.
- Tests:
  - **the round-trip property**: for every example, template and fixture,
    `lower(migrate(v1))` equals the v1 document's own desugared form;
  - **output identity**: for every example and template, the migrated v2
    face and the v1 face generate byte-identical projects and
    pixel-identical previews.
- *Done 2026-09-29.* `schema/wfb-face-2.schema.json` (derived once from the
  v1 schema by a throwaway script, then edited by hand; normative from now
  on), `wfb/lower.py`, `wfb/vocab.py`, format-aware `wfb/validate.py`, and
  `tests/test_format2.py`. For every example, template and fixture but the
  two slice 1 refusals: the twin reports the same diagnostic codes, lowers to
  the same internal document, and generates byte-identical projects and
  pixel-identical default previews -- **except one line per generated file**,
  its header naming the source file and `(format N)`. Slice 3's snapshot
  compare will show that header line changed in every generated source;
  nothing else.
  - The message scan was driven red first: five of its cases failed
    (`absent-missing`, `data-default-not-in-choices`, `data-icon-color-nullable`,
    `data-format`, `absent-placeholder-on-gauge`) before the messages were
    reworded. Messages are now in format 2 terms for every input, format 1
    too -- it is deleted next slice -- and the tests asserting the old text
    were updated here rather than in slice 3.
  - A second, broader check ran by hand (not committed): every design the
    fast suite loads, migrated and loaded again as v2. It found three
    migrator bugs (an element carrying both `value:` and `text:`, or two
    icon keys, was silently collapsed into a valid one; a v1 group with the
    reserved id `static` and the flag collided with the block), all fixed
    with tests, and 138 distinct diagnostics naming a v1 key, reworded. What
    it still reports is schema errors naming a v1 key the (invalid, migrated
    as is) input really contains, each with a note giving the v2 spelling.
  - Decided while building: an expression in a v2 file that still says
    `palette.x` or `config.*` is an error naming its `color.` spelling; a
    template's parentheses round a ternary are template syntax, stripped
    when lowered; `align: <v>` lowers to `vertical_align:` alone, so
    `align: center` + `vertical_align: v` in v1 and `align: v` in v2 lower
    to documents that differ only in that default (the round-trip test
    normalises it); `vocab.refs` names an axis's colour by its default role
    (`color.accent`), not a `role:` the author renamed it to.
  - `tools/snapshot.py compare` against slice 0: 369 cases unchanged, 72
    changed, 2 added (`cli/help-migrate`). Every change is stdout or stderr
    -- the reworded diagnostics, `wfb help` listing `migrate`, and `wfb
    sources`/`wfb series` in format 2 terms. No generated file or preview
    image changed.

**Slice 3 — switch over, one commit (F5).**
- Migrate:
  - every example, **`examples/dashboard/face.yaml` included** (the user
    approved migrating their playground, 2026-09-28; no other edit to it);
  - `wfb/templates/*.yaml`, `README.md`, and every YAML snippet in
    `docs/guide/`;
  - the test inputs. About 135 inline faces in 76 test files, mostly
    Python string literals and fragments: a throwaway script finds string
    constants through Python's `ast`, migrates them in fragments mode and
    replaces them by exact source span. f-strings and concatenations it
    can't handle are listed and done by hand. Tests that assert v1 message
    text are updated by hand.
- `format: 1` becomes a friendly error naming `wfb migrate`. Delete
  `schema/wfb-face-1.schema.json` and the v1 front-end paths: v1-only
  `wfb/validate.py` checks, the list form, and the `static: true` flag. The
  migrator keeps its own knowledge of v1.
- Same commit (§7): the docs.
- Check: `tools/snapshot.py compare` against slice 0. Generated projects
  and previews must be identical. Lint and CLI output may differ only in key
  names; review the diff and record it here. Run `tools/docs-shots.py`;
  the screenshots must be unchanged.

- *Done 2026-09-29.* Every example (the dashboard playground included,
  migrated and nothing else), template, fixture, `README.md` and guide
  snippet is format 2; `format: 1` is an error naming `wfb migrate`;
  `schema/wfb-face-1.schema.json` is deleted. The enduro and config faces'
  colliding palette entries were renamed by hand first (enduro's to
  `old_*`, config's `bg`/`text` to `black`/`white`).
  - Tests: the inline faces went through the throwaway converter
    (string constants by source span, fragments mode), then by hand where
    it could not reach (f-strings, concatenations, `.replace()` targets);
    a static check then found every `.replace()` whose target no longer
    occurred in its string. Tests of format 1 concepts only (the list form,
    the `static: true` flag, v1 twin comparisons) were deleted or rewritten
    against the format 2 construct that replaced them; the slice 2 corpus
    twin tests went with format 1, and this snapshot compare carries that
    proof now. The message scan gained `scheme-role-dither` and
    `config-unsupported` cases (with `fenix5`, which has neither editor
    nor menu).
  - Found and fixed while switching over: a YAML alias shared by two
    elements was lowered twice (the second pass read its own output as a
    format 1 colour); a non-identifier key said only "has the wrong shape";
    the `graphics-pool` warning could no longer be suppressed at all (its
    root is the block's synthetic group, so the allow is now honoured on
    any element inside a `static:` block); the migrator wrote a
    `"\uF09B"` escape back as the raw character; and several messages
    still spoke format 1 (`{:zz}` format errors, `<id>.icon_color`,
    `slot config.data.x`). Two pre-existing doc/example bugs went too: a
    graph example with `at: {x:, y:}`, and schema modelines one directory
    short under `examples/features/` and `examples/system-fonts/`.
  - The slow suite: green apart from
    `test_every_installed_device_at_the_floor_or_above_builds_warning_free`
    on the four Instinct devices, which fails identically on `c97710d`
    (its design is not black and white and does not fit a semi-octagon
    screen) -- pre-existing, not caused by this slice, left for its own fix.
  - `tools/snapshot.py compare` against slice 0: 149 cases unchanged, 292
    changed, 2 added (`cli/help-migrate`). Generated projects: every file's
    header says `(format 2)` (1,192 lines), and nothing else changed except
    the two renamed palettes (`Palette.mc`, and the config face's view
    naming `Palette.WHITE` and its menu labels). No preview image changed.
    Diagnostics differ in key names (`absent:`, `unsupported:`,
    `sleep_update: true`, `slot 'top'`) and source positions; the CLI in
    `wfb help` listing `migrate`, `wfb doctor`'s schema path, `wfb schema`,
    `wfb new`'s format 2 output and `wfb sources`' colour rows.
    `tools/docs-shots.py` (its config variants now in format 2 terms)
    regenerates every screenshot byte-identical.
  - §7's root `CLAUDE.md` step keeps this plan's row, reworded, until
    slice 5 deletes the plan.

**Slice 4 — an absent gauge keeps its track (N7).**
- `absent: hide` on a `gauge` draws the value-independent parts (§2 N7) in
  both codegen and preview, through one shared definition of "which parts
  depend on the value" (plan 19 A1's pattern), with a parity test.
- Tests: for each style (arc, bar, segments, scale, needle), a face whose
  value is absent draws exactly the track parts. The lint's ink and
  visible-area checks include the track while absent.
- Check: the snapshot differs from slice 3 **only** for faces with a gauge
  under `absent: hide`. List those cases here. Update
  `docs/guide/progress-and-graphs.md` and ADR 0005 in the same commit.

- *Done 2026-09-29.* `wfb.kinds.progress.keeps_track` is the one
  definition (`absent: hide` and not a needle); codegen reads it through a
  new `ElementKind.draws_while_absent` hook, so the view emits only the
  non-value guards and the kind wraps the fill, the lit-cell count and the
  pointer in `if (value != null && max != null) { ... }` -- a wrap, not an
  early `return`, which would skip an `antialias:` override's restore. The
  preview reads the same predicate, and now also hides a gauge whole when a
  nullable colour is absent, as the device's guard does (it drew such a
  colour white before). `tests/test_gauge_absent.py`: per style, the
  preview keeps the track and drops the fill; the generated method draws the
  track before the value's own guard and never returns early; a needle and
  a nullable colour still hide whole; codegen and preview agree on the
  predicate; and a real `monkeyc` build of all four track styles under
  `antialias: true` is warning-free. Every one of those fast tests fails
  with `keeps_track` returning `False`. The lint needed no change: a
  gauge's box already covers its whole track. The schema's `absent`
  description, the gauge chapter, `data.md`, ADR 0005's amendment and the
  lore say so.
  - Snapshot against slice 3: 407 cases unchanged, 36 changed, all of them
    the nine designs with a gauge under `absent: hide`
    (`examples/dashboard`, `enduro`, `features/align`, `features/progress`,
    `features/styles`, `features/sun/bar` and `face`, `showcase`, and
    `tests/fixtures/slice`) plus `wfb schema` for the description: the
    generated view (and its golden, `SliceView.mc`) and, where the preview's
    sample data has no reading, the preview image -- `dashboard`'s body
    battery arc and both sun faces now show their track. No diagnostic
    changed. `tools/docs-shots.py` regenerates every screenshot unchanged.

**Slice 5 — tidy.**
- Remove front-end code only v1 reached.
- Rename any internal builder key where it helps readability, each rename
  proven output-identical by the snapshot.
- Then delete this plan and add its row to `docs/CLAUDE.md`'s built-plans
  table.

## 7. Documentation (same commit as slice 3)

- **`schema/wfb-face-2.schema.json`**: the normative reference.
- **Every chapter in `docs/guide/`**: YAML snippets, key tables, and
  `styles-and-layouts.md`, `configuration.md`, `placement.md`,
  `modes-and-interaction.md`, `text.md`, `elements.md`, `icons.md`,
  `analog-hands.md`, `patterns.md` and `progress-and-graphs.md` in
  substance. Add a short `docs/guide/format-2-migration.md` (the §3.4
  table plus `wfb migrate`), and a row for it in `docs/README.md`.
- **`README.md`**: the quick-start face.
- **ADR amendments**, each dated:
  - 0009: v1 is migrated, not kept for a major; §5's deprecation path is
    superseded for this break;
  - 0004: element vocabulary, `align:`, parts `type:`;
  - 0005: `text:` templates, `absent:`;
  - 0006: `color.` namespace, `theme:`, `config: slots:`, `sleep_update:`, the
    static flag removed.
- **Root `CLAUDE.md`**: §6's "removed outright" list gains the v1 keys (as
  "migrated by `wfb migrate`"); remove this plan's row from the table; §5
  user decisions.
- **`docs/limitations.md` §2**: the §5 reserved items.
- **`docs/lore/codegen.md`**: the lowering step and the round-trip test.
- **`docs/research/`**: left as written. Those are dated investigations
  whose v1 snippets are evidence, not reference.

## 8. Risks

- **Source spans through lowering.** An error must still point at the
  author's v2 line. `desugar` already does this for the mapping form, so
  follow its pattern, and give the slice 2 message-scan test a case per
  moved key.
- **Expression rewriting.** Token-level only (§4). The round-trip
  property test is the guard.
- **Test churn.** Slice 3's script handles the mechanical bulk. What it
  can't handle is listed, not guessed.
- **Placement of the static block.** A flagged element moved into `static:`
  keeps its authored order among static roots. The output identity check
  in slice 2 proves it for every corpus case that uses the flag (20 test
  sites, no example).
