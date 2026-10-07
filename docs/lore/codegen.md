# Codegen, IR and generated-project lore

Codegen lore, loaded in `wfb/`. Add new lore here, not to `CLAUDE.md`.

---

### Findings from Phase 2 that were not in the research

These cost real time to discover; do not rediscover them.

1. **`-O z` alone is not enough.** It leaves `Rez.Styles` in the build and warns.
   `-O 3z` (or any level ≥ 2) enables the compiler's `constant-folding` and
   `lexical-only-constants` passes, which is what removes it. The generated
   jungle sets `project.optimization = 3z`; the build command must **not** also
   pass `-O`, or monkeyc warns that one specification is ignored.
2. **An empty `<iq:languages/>` costs about 12 KB of foreground data.** Declaring
   `eng` drops it. This is by far the largest single memory win found.
3. **`--no-gen-styles`** removes the `Rez.Styles` module a generated face never uses.
4. **Launcher icons must match `compiler.json`'s `launcherIcon` size per device**
   or every build warns. The generator draws them at the right size.
5. **The BMFont path works with a plain 8-bit grayscale PNG** and a text `.fnt`.
   No AngelCode BMFont tool is needed; Pillow is enough.
6. **`resourcePath` must not be set in the jungle.** The default jungle already
   puts `resources/` and `resources-<device>/` on every device's path; naming
   them again adds every file twice and warns.
7. **Per-device directories are keyed by device id, not `deviceFamily`.**
   `fenix8solar47mm` and `fr955` are both `round-260x260` but have different
   system-font metrics and different API levels, so their resolved `Layout`
   modules genuinely differ. ADR 0004 §3b is still right that `deviceFamily` is
   the resource-qualifier name — it is just not unique enough to key layout on.
8. **Module members take no access modifier.** `hidden` and `private` are
   class-member keywords; the compiler rejects them inside a `module`.
9. **`monkeyc` finds device definitions through Java's `user.home`**, which comes
   from the *passwd entry* of the running uid, not from `$HOME`. Exporting `HOME`
   has no effect. The symptom is `Invalid device id specified`, which looks
   exactly like a missing device directory. Pass `-Duser.home=` via
   `JAVA_TOOL_OPTIONS` when the running uid has no usable passwd home.
10. **`monkeyc` regenerates `$CIQ_SDK/bin/default.jungle` on every invocation**
   and *replaces* the file, so the SDK's `bin/` directory must be writable — a
   read-only SDK fails with `Unable to generate default.jungle: Permission denied`.
11. **The simulator will not run in this container, and "software OpenGL" is
   not why.** It links against `libwebkit2gtk-4.0`, `libsoup-2.4` and
   `libjavascriptcoregtk-4.0`, which current distributions no longer ship. On an
   `ubuntu:22.04` base, which still packages all three, it **starts** and opens
   its window under Xvfb — then segfaults the moment a `.prg` is pushed with
   `monkeydo`, reproduced with an **unmodified SDK sample `.prg`**, so it is the
   environment, not generated output. The backtrace puts the crash on a worker
   thread **inside the simulator's own stripped binary**, with `libGL` not loaded
   at all. Do not spend another session rebasing the image to get the libraries:
   `/dev/shm` size, seccomp, uid, device-mount writability and WebKit's own
   escape hatches are all ruled out by direct test. `wfb preview` covers the gap;
   see `docs/limitations.md` §2.
12. **`manifest.xml`'s `minApiLevel` is one number for the whole build, so a
   per-feature level bump is the wrong lever whenever a design might target
   a device below that level** (`docs/research/probes/api-gating/`). Raising
   it for one feature raises it for *every* target device in the same
   `<iq:products>` block, including one that never touches the feature.
   `ts/src/emit/manifest.ts::BASE_API_LEVEL` (`3.1.0`, the ceiling of
   `fenix5`/`fenix5x` -- ConnectIQ 3.1.6, this project's lowest installed
   ceiling) is the
   *only* level this compiler ever emits; a feature that needs more is
   gated at runtime per device instead (below), never by moving this
   number. A device below the floor is a friendly `target` build error
   (`selectDevices` in `ts/src/build.ts`), not a raw `monkeyc` failure. If a future feature genuinely cannot be runtime-guarded, `api_level()`
   is the one place to raise it again — deliberately kept as a function, not
   a bare constant reference, for exactly that day.

---

## Build-time / codegen lore

**Build-time / codegen lore:**

- Every **supplementary-plane** glyph (anything above the Basic Multilingual
  Plane — all of Material Design Icons' ~7,000 glyphs, for instance) breaks
  the resource compiler's `<font filter="...">` attribute: it is parsed as
  UTF-16 code units, so a surrogate pair splits into two halves matching no
  real glyph. `ts/src/emit/resources.ts` omits `filter` entirely for a font
  that needs such a glyph — safe, because the `.fnt` is already subsetted by
  this project's own baking.
- `icons.font_key` (and `ts/src/layout.ts`, `ts/src/emit/resources.ts`) is keyed
  by the **declared** size and codepoint, never the resolved pixel size,
  because the generated view class is shared across every target device — a
  device-resolved key produces a different `Rez.Fonts.*` symbol per screen
  size and an `Undefined symbol` error on every device but the one the view
  was generated from.
- **A guard inside a kind's drawing wraps, it never returns.** The
  view emits an element's null guards before an `antialias:` override's
  `applyAntiAlias` and restores the default after the drawing, so an early
  `return;` inside it would leave the Dc anti-aliased for every
  later element. A gauge that keeps its track while absent (`absent:
  hide`, `ElementKind.draws_while_absent`) therefore wraps only its
  value-dependent drawing in `if (x != null && y != null) { ... }`, where
  `monkeyc` narrows the locals, confirmed by a strict warning-free build.
- **The builder reads format 2 as written.** The IR builder reads the
  author's own keys and kind names -- `build: {targets:}`, `absent:`,
  `align: top_left`, `type: gauge`, `icon: {for:}`, `color.<name>` -- so a
  diagnostic names a key by the key itself. `ts/src/lower.ts` runs between the
  schema and `ts/src/desugar.ts` and only checks what a JSON Schema cannot (a
  colour name, a template) and spells out a compass alias. Where the IR
  splits one author key into fields, the builder does the split in one
  place: `Readers.alignment` (`align:` into horizontal and vertical),
  `Readers.absence` (`absent:` into policy, placeholder and fallback),
  `Readers.text_readings` (a `text:` template into readings, through
  `readings` in `ts/src/template.ts`). A placeholder's expression is compiled with a
  `yamlsrc.Origin` holding the template and the expression's offset in it,
  so a caret lands inside the template and the message quotes the
  placeholder (`Expression.shown`). The scope binds `color.<swatch>` to its
  palette constant and `color.<role>` to the view field of a scheme role or
  of a colour axis (`ConfigColor.role`). Generated comments quote what the
  author wrote too: `Expression.shown`, `absent` in `ts/src/vocab.ts`, `slot <name>`
  (the Monkey C goldens show any internal name that leaks into a
  comment). A pass over the document must visit each
  node once: a YAML alias shares one node between two keys, and visiting it
  twice reports its mistakes twice (`_Lowering.lowered`).
- Glyph rasterising at small pixel sizes is measurably asymmetric from
  sub-pixel positioning, not curve sampling (a plain square baked lopsided
  is the tell). Rasterising at 16x and box-averaging down cut measured
  per-pixel asymmetry from 16.8% to 0.9%, with cost flat at well under a
  millisecond a glyph. The obvious refinement — padding each glyph
  symmetrically so it lands on a symmetric sample grid — sounded strictly
  better and **measured worse** (1.8% vs 1.5% on average, 24% for one
  glyph); it was dropped. Supersampling alone is the whole fix.
- **A rejected named block's name must still be bound into scope, or every
  reference to it produces a second, misleading error.** This exact
  cascade — one correct error at the real mistake, plus one derived
  "unknown reference" per place that names it, blaming the wrong thing —
  has recurred five separate times as the format grew new named blocks
  (`fonts:`, `config:`, `palette:`, `color_scheme:`, a `config: data:`
  slot). Any *new* named block needs its rejected names bound into scope
  from the moment it is parsed, and the test that proves it is "one error,
  not N."
- **`Guards` in `ts/src/availability.ts`, the per-device API gating this project's one
  shared generated view/delegate needs (2026-09-15).** `compute_guards(face,
  devices) -> Guards(complications: bool, fields: frozenset[str], modules:
  frozenset[str], ...)` is the single place that decides, once per build,
  which `Toybox` modules the shared code must `has`-guard (`modules`:
  `Complications` and `Weather`, which
  `fenix5`/`fenix5x` lack; `complications` is kept as the flag the
  complication-only sites read), and which bare field names
  (`Device.has_field`'s namespace, e.g. `stressScore`) need an `x has
  :field` guard -- aggregated over *every* device in the build (`targets:`,
  or whatever `-d` selected, which may name non-targets since 2026-09-18), not
  just the one `resolve` in `ts/src/layout.ts` happened to generate the view from,
  because the view is shared across all of them. A design whose targets all
  support everything it uses gets an empty `Guards` and generates the exact
  same code it always did (golden tests confirm byte-identical output);
  every `emit_view`/`emit_delegate`/`ReadPlan` call site defaults its
  `guards` parameter to a module-level `_NO_GUARDS` constant so every
  pre-existing caller (every test, any single-device caller) is unaffected.
  Guards are emitted at: `onLayout`'s complication subscribe/register loop,
  every module-gated reader pull `ReadPlan` writes (one
  `has<Module>` local per module per frame, not per reader), a forecast
  graph's acquisition (`ts/src/emit/monkeyc/graph.ts`), `on_hold:`'s
  `Complications.exitTo` (both the fixed-type and `data`
  `auto` forms), and a `config: data:` slot's `Complications.Id` field. Two
  gotchas the implementation ran into: (1) a **field initialiser** runs
  before any guard could matter (`docs/lore/monkeyc.md`), so a guarded
  `config: data:` field is declared nullable and actually constructed,
  guarded, inside `initialize()` instead of inline; (2) a missing *field*
  (as opposed to a missing module) is keyed by the *first* dotted segment of
  `Source.field_name` -- the nullable intermediate object itself for a
  dotted path like `activeMinutesWeek.total`, since `Device.has_field`
  cannot resolve which class a bare field name belongs to (`ts/src/devices/device.ts.
  Device._fields`'s own presence-is-approximate caveat). See
  `ts/src/availability.ts`'s module docstring for the full design (two
  consumers: `compute_guards`'s aggregate for codegen, and per-element
  `source_unavailable`/`reader_unavailable` for a lint pass to point at the
  exact YAML line) and `docs/research/probes/api-gating/` for the evidence.
- **One view and one delegate for every target, and a check that they
  really are shared.** `ts/src/build.ts` resolves each
  target once (`resolve_all`), and `generate(..., resolved=...)`
  reuses those faces instead of baking and resolving again. Whatever the
  shared sources decide per device is decided over the whole build:
  `Guards` (which now also carries `partial_update_unsupported`, the view's
  `onPartialUpdate` decision, which used to read device 0 alone), and
  `needs_icon_glyphs`, a union over every target's placed items. As a
  check, `generate` emits the view and the delegate from every target's
  resolved face and compares each with the first's (`_check_shared`). A
  difference is a `Divergence`, which `ts/src/build.ts` reports as a
  `shared-source` build error naming the file, both devices and the first
  differing line. A per-device fact that leaks into a shared source
  therefore fails the build instead of silently following the first
  target, the way the view's `Device: <first>` header and its
  partial-update comment (that device's clip percentage) once did. A
  per-device fact belongs in `Layout.mc`. Measured before the change, over
  every example and fixture on its own targets and on all 22 installed
  devices: those two comment lines were the only differences.
- **System-font metrics: one `FontMetric` per
  `FONT_*` symbol per device, one place turning it into a real face.**
  `Device.systemFonts` in `ts/src/devices/device.ts` merges the scraped SDK reference table
  (`face`/`font`/`size_px` -- `size_px` is the published *line height*, and
  stays the number layout trusts even after enrichment) with the installed
  device's own `simulator.json` `ww` font set, when the two agree on a
  symbol: a `type: "ttf"` entry with a top-level `ppi` and a point `size`
  contributes `em_px = size * ppi / 72` (`docs/research/10-system-fonts.md`
  §3's verified model), and `ascent_px`/`height_px` when the device file
  states them outright (about a third do). A bitmap-only device (fenix6:
  no `ppi`, no `type` key at all) or a `ww` entry naming a symbol the
  scraped table has nothing for leaves those three `None` -- deliberately:
  deriving an em from a TTF's own `hhea` table happens lazily in
  `ts/src/fonts/fallback.ts` instead, only for a symbol actually referenced.
  `systemFace(metric, scale=1, fonts_root=None)` is the
  one place a `FontMetric` becomes a Pillow `FreeTypeFont`: it locates the
  real file via `locate` in `ts/src/fonts/files.ts` (`fonts_root` first --
  `--fonts DIR`, `Device.fonts_root` for every caller that has a device --
  then `WFB_FONTS`/`vendor/fonts/`/the per-OS SDK Manager location, then the
  pinned free-stand-in registry, `ts/src/fonts/files.ts`'s own module
  docstring), derives whatever the metric did not already carry from that
  file's `hhea`/`head` tables, and returns a `SystemFace` whose
  `line_height`/`baseline` are already in the same scaled pixel units as its
  `font` -- `ts/src/layout.ts` (measuring, always at `scale=1`, `fallback.measure`/
  `line_height`/`ascent` all taking the same `fonts_root`) and `ts/src/preview.ts`
  (drawing, at the renderer's scale -- 1 for every preview frame, which
  is enlarged block-wise afterwards) both go through this one function
  **with the same root** (`Device.fonts_root`, owned by `DeviceDatabase` and
  carried by every `Device` it builds), so a
  monkeypatched `em_px` moves both by
  construction, never one without the other, and a build measures a box
  from the exact file it is then drawn with. The preview draws a
  system-font line from its own line box
  (`top = anchor_y - {top: 0, center: line_height/2, bottom: line_height}`,
  then Pillow's baseline vertical anchor `"s"` at `top + baseline`) instead
  of Pillow's built-in ascender/descender anchors, which measure the
  *stand-in* face's own metrics and would not agree with the line height/
  baseline the metric (not the stand-in) defines. **Widths (2026-09-18,
  calibrated against the simulator; `docs/research/10-system-fonts.md`
  §9):** `SystemFace.advances` gives each glyph its own `hmtx` advance at
  the whole-pixel em (`round(em_px)`), rounded to whole pixels one glyph at
  a time, with no kerning. That is exact on all 36 Roboto probe readings;
  Pillow's own `getlength` was a pixel short per `FONT_TINY` digit. The
  preview draws glyph by glyph on those pen positions, never with Pillow's
  own layout. The test suite sets `WFB_NO_GARMIN_FONTS=1`, so results never
  depend on the user's licensed fonts. None of this reaches
  `monkeyc`'s input: a `Placed*`'s `font.metric` only feeds `ts/src/layout.ts`'s
  own lint boxes and `ts/src/preview.ts`'s ink, never a baked pixel position --
  the runtime anchor a `text`/`data` element draws at was already
  unshifted before this (this file, finding 7's sibling reasoning: a glyph
  kind's alignment is a device-side justify, not a build-time box move), so
  the *only* generated-code effect observed is a `_WIDTH` layout constant's
  own comment and value changing where the estimate got more accurate (a
  system font's widest-rendering comment, never referenced elsewhere in the
  generated code) -- confirmed by the golden `Layout.mc` diffs this step
  produced, one line each, nothing else.
- **Derived metrics for a device with no scraped page at all: a third source, stdlib `struct` only, that never touches a
  scraped device.** Three installed devices (`fenix947mm`,
  `fenix9prosolar47mm`, `fenix9prosolar51mm`) have no
  `.cache/device-reference/devices/<id>.json` at all, so `Device.system_fonts`'
  first two loops leave them empty and every `text` element degraded to
  "not checked" -- `wfb preview` drew no system-font text on them either.
  A third loop derives `size_px` for the 9 standard `FONT_*` symbols
  (`FONT_XTINY`…`FONT_NUMBER_THAI_HOT`) directly from a *located* real
  `.ttf`/`.otf`'s own `head.unitsPerEm`/`hhea.ascent`/`hhea.descent`, with
  the exact same `size_px = round(em_px * (ascent - descent) / upm)` model
  §3's Roboto/Bionic check already verified (`docs/research/
  10-system-fonts.md` §3.1) -- 45/45 exact against every scraped device
  that has the inputs. It fires only for a symbol in the documented
  vocabulary (`_documented_font_symbols`, the union of every scraped
  device's own `fonts.default.fixed` keys), only when neither earlier loop
  already covered the symbol, and only when the file resolves to a real
  `.ttf`/`.otf` under `Device.fonts_root` (`_locate_garmin_outline_font(name,
  self.fonts_root)` -- local files only, never the free-stand-in registry,
  and never a `.cft`: no verified height model for one, per the `.cft`
  finding above; `fonts_root` is `None` for the ordinary search order and
  `--fonts DIR`'s own value for a `DeviceDatabase` built with it).
  The font is read by `ts/src/fonts/sfnt.ts`, a from-scratch reader
  of the sfnt table directory (`numTables` at offset 4, 16-byte table
  records from offset 12, `head.unitsPerEm` at its own offset 18,
  `hhea.ascent`/`descent` at offsets 4/6), cached per resolved path, never
  raising. **No scraped device gains a symbol from this** -- checked
  against every installed device with a scrape, the first loop already
  covers every symbol this loop could otherwise reach, so its own
  first guard always wins.
- **Vector fonts and `curve:`: per-device `Layout` constants, one
  guard for the whole build, one null check that is never omitted.** A used
  `face:` font gets `FONT_<NAME>_FACE`/`_SIZE` in every target device's own
  `Layout.mc` (`ts/src/emit/monkeyc/layout_constants.ts`):
  `_FACE` is that one device's own resolved face name (`vectorFontFace` in
  `ts/src/availability.ts`, empty string when none of the requested candidates is
  published), `_SIZE` its pixel height, both independent of any element's
  `curve:` -- `Graphics.getVectorFont` is constructed once per font name in
  the *shared* view (`onLayout`), not once per drawing element. A third
  constant, `_AVAILABLE`, is emitted **only** for a font at least one target
  in the build fails to resolve (`Guards.vector_fonts` in `ts/src/availability.ts`,
  aggregated across the whole build the same way `Guards.fields` already
  is) -- the same "no guard for a thing every target has" rule the
  `Guards` bullet above states for complications/fields: a design whose
  targets all support the requested face(s) gets the plain, unguarded
  `Graphics.getVectorFont(...)` call, and every device's `Layout.mc` that
  never needs `_AVAILABLE` never defines it. When it is needed, the
  construction is wrapped `if (Layout.FONT_<NAME>_AVAILABLE && (Graphics
  has :getVectorFont))` -- the runtime `has` check and the build-time
  constant are *not* redundant: `has :getVectorFont` is the only one of the
  two a device can answer about itself (constraint 6d -- `monkeyc` checks
  the SDK-wide API, not the device's), while "does this device's own
  catalogue include any of the requested faces" has no runtime query at
  all and can only be decided at build time, per device.

  **Gate 4 -- `Graphics.getVectorFont` returning `null` even when every
  build-time gate passed -- has no guard of any kind, ever, in either
  `unsupported:` mode**, because the platform gives none: every draw
  call using a vector font (`TextKind.lower` in `ts/src/kinds/text.ts`)
  captures the field into a local first (`var font = _fontBezel;`) and wraps the actual `dc.drawText`/`drawAngledText`/`drawRadialText` in
  `if (font != null)` -- the field-vs-local capture is not optional
  ceremony, it is `docs/lore/monkeyc.md`'s own "type narrowing must go
  through a local, never a repeated field access" rule, and this is one
  more confirmed instance of it (the field, unlike a local, cannot be
  narrowed by an `if` one statement earlier). The constant that guards
  *construction* and the null check that guards every *draw* are answering
  two different questions -- "should this device even try to build the
  font" vs. "did building it actually work" -- and neither is relied on to
  stand in for the other.

- **Vector fonts and `curve:` on a pattern's own `shape: text` part: the
  local angle composed with the copy's, and why gate 4's guard is "once
  per copy, inside the loop", not "once, before it".** The element's
  `Curve` dataclass and every build-time gate (1-3) are shared
  (`ts/src/layout.ts`/`._vector_font_metric`,
  called from `._resolve_hand_part`'s own `text` branch the same way
  `TextKind.resolve` in `ts/src/kinds/text.ts` calls them); what differs is the
  angle's *composition* and where the null guard sits.

  **Composition.** `ResolvedTextPart.curve.angle_garmin` is this part's own
  *local* angle (`TextPart.curve.angle`, run through `ts/src/layout.ts.
  garmin_curve_angle`), for copy 0 alone -- never combined with a radial
  pattern's own rotation in `ts/src/layout.ts`. That combination is one
  definition, `PatternTextAngle` in `ts/src/kinds/pattern.ts`: `local`/`start`/
  `step` are the part's local angle and the pattern's own repeat angle, and
  `copy_curve_angle(index)` is `(local - (start + index * step)) % 360.0`,
  the host evaluator the lint ink box (`ts/src/kinds/pattern.ts`)
  calls. The draw program (`ts/src/kinds/pattern.ts`) reads the same
  `local`/`start`/`step` off that object but builds a program value from
  them, which the watch and the preview both compute: `g0 =
  part.curve.angle_garmin - element.start_angle`, then `g0 - i * step_deg`
  per copy, the *exact* shape a radial pattern's own `arc` part uses for
  its `start_angle:` (`_lower_part`'s arc branch). Deriving the sign: a radial pattern turns
  copy `i` by `element.start_angle + i * element.step_angle` **design**
  degrees, clockwise from 12 -- always a *position*-style rotation of the
  whole template, regardless of the part's own `curve.style`. Composing it
  into a Garmin-space angle by straight subtraction is valid whichever
  style `part.curve.angle_garmin` itself came from: for `radial` it is
  `Angle.to_garmin()`'s `90 - degrees` (a position, one fixed offset folded
  in once by the part's own local angle); for `angled` (2026-09-20:
  `curve.angle` redefined as a rotation from upright, not a direction --
  `angle: 0deg` now means level text, not "pointing at 12 o'clock") it is
  `garmin_curve_angle`'s own `-degrees % 360` (a rotation, no offset to
  begin with). Either way, subtracting a *further* design-clockwise delta
  (the copy's own rotation) still just subtracts that same delta in Garmin
  space -- the offset, when there is one, is a constant contributed once by
  the local angle, never re-derived per copy -- so `g0 - i * step_deg`
  composes correctly with no special-casing for which style the part uses.
  A linear pattern's `element.start_angle`/`.step_angle` are always `0.0`
  (`PatternKind.resolve` in `ts/src/kinds/pattern.ts`), so `g0` reduces to the part's own local
  angle unchanged and no `i *` term is emitted at all -- the "no copy angle
  to compose with" case falls out of the shared formula for free, not a
  separate branch.

  **Why gate 4's guard cannot stay "load once, early-return before the
  loop."** That is exactly what a *baked* custom font on a pattern text
  part still does (`PatternKind.lower` in `ts/src/kinds/pattern.ts`'s own `text_fonts` pre-loop loading) -- reasonable there, because a baked resource failing to load
  is a structural failure, essentially never observed. A vector font's
  null is the *ordinary* case under `unsupported: hide`, or even under
  `error` (gate 4 has no build-time guarantee at all), and an early
  `return;` before the loop would silently cancel every *other* part of
  the *same* pattern too -- unrelated shapes, unrelated fonts, all sharing
  this one generated draw method. So a vector font's local is still loaded
  once before the loop (`PatternKind.lower` in `ts/src/kinds/pattern.ts`'s `vector_text_fonts` split),
  but never early-return-guarded; instead `ts/src/kinds/pattern.ts.
  _lower_text_part` wraps only its own draw call in `if (<local> !=
  null)`, every copy, the same shape `TextKind.lower` in `ts/src/kinds/text.ts`
  already uses for a standalone element -- and this
  applies even to an *upright* (uncurved) vector-font pattern part, not
  only a curved one: gate 4 does not care whether `curve:` was authored.

  **`style: radial`'s circle is centred on that copy's own anchor**, not a
  fixed point -- the same `at:` reinterpretation a standalone `curve:
  {style: radial}` text element already gives, applied per copy: the
  circle's radius (`curve.radius_px`, a `handLength` -- px/%r only, the
  schema's `patternCurve` -- resolved once, the same for
  every copy) gets a `Layout` constant (`<part>_RADIUS`, `ts/src/emit/monkeyc/view.ts.
  layout_constants.hand_part_constants`'s `text` branch), the same as an
  `arc` part's own `_RADIUS`; the angle does not, for the same reason an
  `arc` part's `start_angle`/`sweep` never did -- it is device-independent
  and needs a per-copy runtime term, so it is inlined straight into the
  shared view instead of a per-device `Layout` constant nothing would
  differ across devices for anyway.

- **`outline:` (research 14 and 19): a ring of 1, 2 or 3px, drawn one of
  three ways, each measured on a watch (research 19 §4.5-4.6).**
  `RingPass` in `ts/src/emit/monkeyc/common.ts` is the ring's colour as Monkey C --
  an element's own (`own_ring`, dimmed in AOD) or a `ring<Id>` method's
  `ringColor` -- and its width, a build-time number; every `ringed` kind's
  program, lowered under `DrawContext.ring`, draws only its silhouette's ring when given one.
  The offsets of a ring of width `w` are `discPerimeterOffsets(w)`
  (4/8/16 points at 1/2/3px), the one table every path below reads.

  - **Grown**: a filled circle, rectangle or rounded rectangle, a gauge bar
    and a filled circle part draw one copy `w` px larger (`plus()` folds
    the literal into the constant term).
  - **Baked ring font** (below): an icon, or text in a baked font.
  - **Stamp**: everything else draws at every offset point, unrolled --
    `shapes.emit_stamp`/`emit_outline`, one call per point with literal
    offsets (`shapes.shifted`) and the pen set once around them.  A loop
    over an offsets array cost more than its draws on a watch; unrolled,
    there is no table in `Layout`, no index and no local to name.  A
    standalone polygon's shifted copies are `Layout` constants
    (`<P>_RING_0`..`_3` at 1px, `<P>_RING<W>_<i>` wider, one set per width
    it rings at, `Placed.ring_widths`): native fills.  A part of a hand,
    needle or pattern is transformed at runtime, so it goes through
    `WfbRing` (`rotated.emit_part_ring`): the points rotated or translated
    **once** into a fresh array that `shift` moves in place between the
    fills (a `Point2D` element assignment typechecks under `-l 3`, by a
    real build); `lineRotated`/`circleRotated` rotate once and draw four.
    Above 1px the same four functions in `WfbRingWide` walk
    `Layout.OUTLINE_OFFSETS_<W>`, emitted only for a width some
    runtime-transformed element rings at
    (`outlineWidthsUsed`); its `lineRotated` takes the
    line's ends as one array, since a barrel function takes at most nine
    parameters.  That halved the allocation, not the time -- the
    per-vertex work is interpreted either way (§4.6).  `WfbRing` is its
    own barrel module so a face without a ring compiles none of it, and
    `WfbRingWide` its own so a face whose rings are all 1px compiles none
    of that.

  A screen-space shift commutes with everything else a draw call does,
  rotation and `curve:` included (research 14 §3.2): a pattern text part's
  stamp shifts its already-rotated anchor (`WfbGeom.rotatedX(...) - 1`).

  A text whose AOD ring differs in width from its awake one draws each
  under `if (_aod) ... else`; a baked ring is read into a local named per
  width (`ringFont`, `ringFont2`), so the two branches never redeclare it.

  **A `monkeyc` finding caught only by a real build: locals are
  block-scoped, and a second `var` of one name in a scope is
  `Redefinition of variable`.**  The AOD frame's `aod: {visible: ...}`
  guard locals were redeclared per element, which failed as soon as two
  guards read one source (and every outlined
  group member in AOD hits it via its ring call); reusing one declared
  inside another `_configLayout` block is `Undefined symbol`.
  `view._GuardScopes` declares once per scope, afresh in each layout block.

  **A group's ring is `ring<Id>` calls, not a group method.**  A group
  emits no code; its ring pass calls every member's `ring<Id>` (the same
  reads, guards and parameters as `draw<Id>`, plus `ringColor`) just before
  the group's first member in each frame sequence -- active, AOD (each
  under its own `aod: visible` guard), low-power and the static buffer's
  `drawStatic<Id>` (`view.Rings`, `ts/src/ir/rings.ts`).  A member's dilation
  is the sum of every ring it sits in -- its own and each outlined group
  between it and this one -- so one member can need several widths: one
  method each, `ring<Id>` at 1px and `ring<Id>_<W>` wider
  (`element_ring_method`).  The group's colour may not read data: the
  frame methods read only what members bind.

  **A ring is part of the element's draw program** (`wfb/draw/`): the
  preview paints the same grown copy, shifted polygon copies or stamp the
  watch is sent. A filled circle's, rectangle's or rounded rectangle's ring,
  a gauge bar's and a filled circle part's (a needle's, a hand's, a
  pattern's) is a grown copy, and a simulator capture shows the watch draws
  it as such: it is not the stamp, which differs by 4-20 px a shape (research
  28 §7, `docs/research/probes/ring-on-device/`). The preview's
  shapes follow rules fitted to simulator captures; where they still
  differ is in `docs/limitations.md`. An outlined group's ring is each member's
  `ring<Id>` pass at its own width, before the group's first member
  (`Renderer.render_ring`), as the view draws it. `Placed.ring_grow`
  records how far `box` grew for rings; a kind that draws from its own box
  reads `inner_box`.

- **Baked ring fonts (research 19): a ringed icon, or ringed text in a
  baked font, rings in one `drawText`.** `ringFonts(face)` is
  the one answer to "which fonts need a ring companion, with which glyphs"
  (the union over every ringed run, a group member's share included; a
  text with an `aod: {font: ...}` override keeps the stamp).  The build
  bakes each as `<font>_ring_glyphs` at 1px and `<font>_ring<W>_glyphs`
  wider, one per width some element rings at (`ts/src/fonts/bmfont.ts`:
  every glyph dilated by `disc_perimeter_offsets(w)` plus itself, offsets
  `-w`, advance and line metrics unchanged), writes it as an ordinary `<font>`
  resource, and loads it right after its base (`_loaded_fonts`).  The
  resource compiler accepts the resulting negative `xoffset`/`yoffset`
  (a real build on all three targets).  The ring font's glyphs land on
  the base font's under `TEXT_JUSTIFY_VCENTER` -- they share
  `lineHeight`/`base`, which is all the `.fnt` gives it: VERIFIED in the
  Connect IQ simulator (the user's host, 2026-09-29, the profile face),
  not yet on a watch.  The preview draws the same ring font (`text` and
  `icon` are lowered); for an icon that paints exactly what stamping the
  glyph would.

- **`wfb build --profile` (`ts/src/emit/monkeyc/profile.ts`) instruments only the
  active frame.** Every call site becomes `if (_profNext == k) { var t0 =
  ...; for (var r = 0; ...) { call } ... } else { call }`. Each `t0`/`r` is
  declared in its own block, which Monkey C scopes separately (the same
  finding as the AOD guard locals, `view._GuardScopes`). Entry 0 is the
  empty loop, the baseline the overlay subtracts, and it is always
  "shared", so the advance to the next entry drawn in the layout on screen
  always terminates. The static buffer is off in a profiled build, so
  static content is timed live. The entries are device-independent (ids in
  draw order), so the shared view and each device's `PROF_X`/`PROF_Y`
  anchors in `Layout` agree.

- **`aod: {outline: ...}` on a `text` element: the ring is one more AOD
  override, but not a ternary alone, because a ring can exist in one frame
  and not the other.** `ts/src/kinds/text.ts` reads one decision,
  `aodOutlineChoice` in `ts/src/ir/model.ts` (which `wfb preview --aod` reads too), and
  draws the ring once in one of three shapes: both frames ringed -- a
  colour ternary; a ring only in AOD -- under `if (_aod) { ... }`; a ring
  only while awake (`outline: none`) -- under `if (!_aod) { ... }`.  A ring
  carried over from the awake design is dimmed like every AOD colour
  (`AodStyle.dimmed`, also a pattern text part's ring), and so is the
  override's own colour, by the element's resolved `dim:`. Confirmed by a real build of all three shapes, on a
  system and a vector font, warning-free on `fenix847mm` and `fr955`.

- **`aod:` restyling: ternary beats a second method,
  measured per ADR 0008, and an AOD-only font is cheap.** Two candidate
  shapes for reading an `AodOverride` at the draw call site: an inline
  `_aod ? <aod> : <awake>` ternary inside the *one* existing per-element
  method (`_emit_element_method` already calls the same method from both
  the active and AOD branches), or a second, fully
  separate method (`draw<Id>Aod`) called from the AOD branch instead. A
  throwaway probe with 8 overridden elements (every override key exercised
  at least once: `color`/`track_color`/`thickness`/`filled`/`format`/`font`/
  `bar_width`, `fenix847mm`, `--build-stats`) measured **4,704 B** (1,026 B
  data + 3,678 B code) for the ternary shape this project actually built,
  against **5,169 B** (1,098 B data + 4,071 B code) for a hand-written
  second-method variant of the exact same design -- the ternary is **465 B
  (9%) smaller**, because every duplicated method repeats its own
  declarations/guards/reads and the two-method call sites (one per branch)
  cost more than one ternary each. The ternary is the unconditional
  default (`AodStyle` in `ts/src/emit/monkeyc/common.ts`, one call site
  per overridable key).

  **A baked font used only by an `aod: {font: ...}` override, never drawn
  while awake, is a second resource**: declared under `fonts:` like
  any other, baked unconditionally by `bakeFonts` in `ts/src/emit/resources.ts`
  (which bakes every declared font regardless of whether anything draws
  with it while awake -- `glyph_set` is extended to also collect the
  *override*'s own needed glyphs, through its own `format:` override if it
  has one, so it is never baked with the empty-glyph-set "0123456789"
  fallback), but the view field for it is declared separately
  (`_aod_only_fonts`, `ts/src/emit/monkeyc/common.ts`) and loaded **only** inside
  `onEnterSleep`'s own `if (_aod)` branch -- never in `onLayout` -- with the
  field nulled again in `onExitSleep`, so it never sits resident while
  awake. Measured (two otherwise-identical one-clock faces, baked custom
  font, `fenix847mm`, `--build-stats`): **1,209 B** (633 B data + 576 B
  code) with one font used both awake and (unstyled) asleep, **1,301 B**
  (651 B data + 650 B code) once a *second*, AOD-only font is declared and
  overridden in -- a **92 B** difference (0.07% of the 131,072 B budget) for
  the extra field, its conditional load/null bookkeeping, and the font
  ternary at the call site. Cheap, as expected: since API 4.0.0 a loaded
  font lives in the graphics pool, so the *resource* itself never touches this figure at all (constraint 11);
  what is measured here is purely the bookkeeping around it.

  **What is built, and what is not:** ternaries for every allowlisted key on `shape`/`text`/`gauge`/`icon`/
  `graph`, `filled` as an `if (_aod) { <opposite draw> } else { <awake
  draw> } ` branch (`ts/src/kinds/shape.ts`), `format`
  as two fully-formatted value expressions ternaried against each other
  (built before `absent:` substitution, so a placeholder/fallback
  still sees the right one), and `hands`/`pattern` `color`/`thickness`
  applied uniformly to every part by ternarying the *existing* per-part/
  hoisted `dc.setColor`/`dc.setPenWidth` call sites against one element-
  level override, never restructuring the hoisting logic itself. **Not
  implemented yet, matching `docs/limitations.md` §2 -- and,
  per house style (CLAUDE.md §7), each is a friendly build error, never
  a silent no-op**: a
  `pattern`'s own `font:` override (in the schema's allowlist, but a
  pattern's per-copy text font loading has no second-resource slot yet), a
  `data` element's `font:` override (same reason), any `font:`
  override that names a `face:` (vector) font rather than a baked one (gate
  1-4's own machinery has no AOD-override-aware second face/size constant
  yet), and `aod: {filled: ...}` on `shape: polygon` (there is no outline
  primitive for it to switch to -- the same reason the awake element's own
  `filled: false` is already refused, `ShapeKind.build` in `ts/src/kinds/shape.ts`).
  All four are raised on the author's own line: in `Builder.buildAodAuthored`
  for an element's own block, and in `Builder.resolveAod` for a key the
  element inherits from a group (both read one table,
  `Builder.aod_refusal`, so they cannot disagree). A face using one of
  them never reaches codegen or `wfb preview
  --aod` at all -- there is nothing left for either to draw, and the
  runtime fallback code both still carry for the font cases (e.g.
  `TextKind.Font` in `ts/src/kinds/text.ts`'s `is_vector` check) is
  defensive, not a live path.

- **`aod: {dim: ...}`: the split is `Expression.is_constant`,
  not a choice between two implementations -- and a real `monkeyc` build
  caught a barrel-file omission no source-level codegen test could.**
  `dim` has to scale a colour that is either a build-time literal
  (`color.<swatch>`, a bare hex) or something the device resolves at
  runtime (a scheme's `color.<role>`, a conditional between several colours).
  There were two candidate implementations for the runtime half:
  a small integer-math helper (`dim(color, num, den)`), or precomputing a
  dimmed variant per scheme. The second was never built to compare
  against: a scheme's `color.<role>` is a *view field* the
  wearer's own on-device pick can repoint at runtime
  (`Builder.defineConfigColor`, `constant=None` by design), so
  precomputing a dimmed variant would mean a second shadow field kept in
  sync on every `applyConfig`/style edit -- strictly more fields, more
  bookkeeping, and a second place that field and its shadow could drift --
  for a value that is one `Number` and three shifts to compute from the
  field that already exists. The runtime helper (`WfbColor.dim`,
  `runtime-lib/WfbColor.mc`, integer channel math -- never `Float`, so its
  rounding is bit-for-bit the same as the build-time half's in
  `ts/src/palette.ts`) is what shipped. `Expression.is_constant` --
  already true for a `color.<swatch>` reference (`fold_colors=True`'s own
  resolved-constant half, `Builder.expression`) and already `None` for
  a scheme's `color.<role>` -- is exactly the fact that decides which of the
  two a given colour needs, so `ts/src/emit/monkeyc/common.ts`
  needed no new classification of its own: a constant colour is pre-dimmed
  into a second literal once, at build time
  (`Color.dim` in `ts/src/palette.ts`); anything else calls `WfbColor.dim` at the draw
  site. Measured (`fenix847mm`, `--build-stats`, one `text` element): a
  face with `aod: {visible: true}` and no `dim:` at all is 1,127 B; the same face with
  `aod: {dim: 0.5}` on a scheme's `color.<role>` is 1,318 B -- **191 B**
  for the runtime path (the `WfbColor` module, the call site and the
  ternary together). A colour dimmed at build time costs far less: the
  `examples/features/aod/face.yaml` example (one `color.<swatch>`-typed
  colour newly dimmed, `accent_dot`, no override of its own) grew from
  2,401 B to 2,415 B on the same device -- **14 B**, a single wider hex
  literal.

  **Whether the generated view ends up calling `WfbColor.dim` at all depends
  on a fact no per-kind IR walk can see**: whether *any* AOD-shown colour,
  across every element and every one of `color`/`track_color`/`icon_color`,
  turned out non-constant with no override. So the barrel set is never
  derived from the IR: `barrelModules` in `ts/src/emit/usage.ts` scans
  every generated Monkey C source (comments and strings stripped) for a
  `Wfb<Name>.` reference and copies exactly the files named, closed over the
  runtime-lib files themselves -- the same "inspect what was actually
  emitted, don't re-derive it" move `_avoid_string_label_collisions` makes,
  so the copied set cannot drift from the calls codegen wrote. The view's
  `Toybox` imports come from the same scan of the view body
  (`usage.toybox_modules`).
  **This is not a hypothetical:** a real `monkeyc` build of a
  scheme-role-dimmed design once failed outright with `Undefined
  symbol ':WfbColor'` under the old ladder, while every codegen test that
  stops at source text stayed green -- `generate` in `ts/src/emit/project.ts`
  and `ts/src/preview.ts` never notice a missing barrel file. Only a real
  `monkeyc` build catches it: run the slow suite (`npm run test:slow`)
  after any change to how the barrel set is decided, and give a new case a
  design it builds, because that decision only has a real audience once
  `monkeyc` runs.

- **The `getDisplayMode` ladder: one `has`-guarded `if`
  at the top of the AOD branch, cheap enough that no ternary-vs-method
  comparison was needed -- unlike the restyling decision above, there
  is only one reasonable shape here (an early `return;`), so this is a
  measurement of cost, not a choice between two implementations.**
  `ts/src/emit/monkeyc/view.ts` gained one condition
  (`(System has :getDisplayMode) && (System.getDisplayMode() ==
  System.DISPLAY_MODE_OFF)` on a mixed AMOLED+MIP build, since `monkeyc`
  compiles the one shared view once per device and at least one MIP target
  always lacks the symbol -- `Guards.display_mode_guarded` in `ts/src/availability.ts`,
  computed the same way as `Guards.burn_in_field_guarded`) and one `return;`,
  placed before the frame's own black clear so an off panel never pays for
  either. Measured on `examples/features/aod/face.yaml`
  (`fenix847mm`, `monkeyc --build-stats`, real build): **+32 B** for the
  guarded form (the `has` check, the comparison, and the early return),
  measured while the example also used `dim:` and the since-removed
  `jitter:`, so this is the cost against an already-loaded AOD frame, not a
  from-scratch design. With jitter removed the example builds to
  **2,447 B** on `fenix847mm` (2026-09-23), 338 B less, matching jitter's
  own measured cost. No new barrel file, no new resource, no new field: the check
  reads two SDK-wide symbols the view already imports `Toybox.System` for
  (`requiresBurnInProtection`'s own import, `emit_view`'s `aod` branch).
  `DISPLAY_MODE_*`'s three constants needed no separate guard of their own
  (they are plain compile-time fields, not a method call -- see
  `ts/src/devices/device.ts`'s `Device.DISPLAY_MODE_SYMBOL` docstring for the
  per-device evidence they move together with `getDisplayMode`), so the one
  `has` check on the method call is the whole runtime cost. `Application.
  AppBase.onDisplayModeChanged` was considered and deliberately not
  emitted -- `WatchFace.onUpdate` already runs once a minute while asleep
  regardless of display mode (`Toybox/WatchUi/WatchFace.html`), so the only
  thing the callback would buy is shaving a worst-case one-minute latency
  off a transition away from `DISPLAY_MODE_OFF`, for the cost of one more
  per-device symbol question (`AppBase` gets no override, no test needed
  for one) -- not measured, because nothing was built to measure.

- **`defaults: {aod: {mask: ...}}`: `WfbAodMask.apply` is
  emitted last in the `_aod` branch, after every element the frame draws,
  and only when the resolved AOD set is non-empty** -- masking an
  all-black frame is pure waste, and the same "only emit what could
  matter" shape `_aod` itself already follows for an all-MIP build.
  **The barrel file is pulled in the same general way every barrel file is
  now (above):** whether the view ends up calling `WfbAodMask.apply(` at all
  depends on `Face.aod_mask` *and* the resolved AOD set being non-empty, the
  same two facts the emitter itself checks -- `barrelModules` in `ts/src/emit/usage.ts`
  scans the already-generated sources for the literal call rather than
  re-deriving that classification, the same "inspect what was emitted,
  don't re-derive it" move that keeps the two from disagreeing.
  **`ts/src/aod_mask.ts` is this feature's host twin**, the same
  shared-renderer stance ADR 0004 already takes for layout, extended here
  from layout to a runtime effect: `render` in `ts/src/preview.ts`, `--heatmap`, and
  the `aod-burn-in` lint all go through its `apply`, so there is no second
  implementation of the mask for any of them to drift from. The two phase
  tables (`PHASES` in `ts/src/aod_mask.ts`, the `dx`/`dy` ternaries in
  `runtime-lib/WfbAodMask.mc`) must be kept in sync by hand; the preview
  goldens of `examples/features/aod/` move when one changes alone.
  Measured: `examples/features/aod/face.yaml` on `fenix847mm` is
  **2,726 B** with the mask (the default) against **2,447 B** with
  `defaults: {aod: {mask: false}}` -- **+279 B**, warning-free on all four targets.

- **`date.today`'s `format:` bug (found 2026-09-23): under `FORMAT_MEDIUM`
  (the `date` reader), `month` and `day_of_week` are Strings, not Numbers --
  `%b`/`%a` rely on exactly that, but `%m` (numeric, zero-padded month)
  needs a Number and has none to read on `date`. It has to come from
  `date_short` (`dateShort`, `FORMAT_SHORT`) instead, cast `as Number` the
  same way `date.weekday` already reads `dateShort.day_of_week`. Every
  `%m`-using face failed `monkeyc` outright (`Cannot find symbol ':format'
  on type '$.Toybox.Lang.String'`) until this was fixed, because nothing
  had ever compiled every `DATE_CODES` entry in one build.
  `DATE_CODES` in `ts/src/formatting.ts`' `m` row is the one place "which codes need
  a second reader" is decided: its `emit` and its `extra_path` sit side by
  side, and `extra_paths` (which `ReadPlan` in `ts/src/emit/monkeyc/readplan.ts`
  calls to add the extra reader-local parameter) reads that row, so an
  element's generated method and the parameter list supplying it cannot
  drift apart on this again. Every strftime code's Monkey C (`emit`) and
  host rendering (`render`, what `wfb preview` draws) share that same row
  (`Code` in `ts/src/formatting.ts`).

- **The `config:` settings menu (2026-09-27): runtime choice of editor,
  per-device option lists, and two `monkeyc` findings.** Which editor a
  device uses is decided on the watch by `Application has :WatchFaceConfig`,
  the check `onLayout`'s first native read already made, so one shared view
  serves a fēnix 8 (native; `getSettingsView` returns null) and an fr955
  (the menu) with no per-device flag. A data slot's options are per device
  (`choices: any` lists the types the device's API level has), so they live
  in `Layout.mc` (`CONFIG_DATA_<SLOT>_TYPES`/`_LABELS`/`_DEFAULT`) and the
  shared view only indexes them; every property therefore defaults to -1,
  "never chosen", keeping `properties.xml` one shared file while each
  device's default index differs. Real builds found: (1) with every target
  having `Toybox.Complications`, the `has` block around each slot's decode
  is not emitted, so two slots' `var types` share one straight-line scope --
  `Redefinition of variable 'types'` (the same rule the `outline:` finding
  above records); each slot gets its own local (`typesTop`). (2) An empty
  `[]` typed `Array<Complications.Type>` in `Layout.mc` compiles
  warning-free on a device without the module (fenix6), so no second
  shape is needed there.
