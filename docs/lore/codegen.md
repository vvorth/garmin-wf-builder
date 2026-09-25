# Codegen, IR and generated-project lore

The full text behind root `CLAUDE.md` §6, with the same numbering. Add new
lore here, not to `CLAUDE.md`.

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
   `wfb/emit/manifest.py::BASE_API_LEVEL` (`3.1.0`, lowered from `3.2.0`
   plan 14 slice 6 once `fenix5`/`fenix5x` -- ConnectIQ 3.1.6, this
   project's lowest installed ceiling -- were installed and audited) is the
   *only* level this compiler ever emits; a feature that needs more is
   gated at runtime per device instead (below), never by moving this
   number. A device below the floor is a friendly `target` build error
   (`wfb.build.select_devices`), not a raw `monkeyc` failure. If a future feature genuinely cannot be runtime-guarded, `api_level()`
   is the one place to raise it again — deliberately kept as a function, not
   a bare constant reference, for exactly that day.

---

## Build-time / codegen lore (formerly §6 "Hard-won facts")

**Build-time / codegen lore:**

- Every **supplementary-plane** glyph (anything above the Basic Multilingual
  Plane — all of Material Design Icons' ~7,000 glyphs, for instance) breaks
  the resource compiler's `<font filter="...">` attribute: it is parsed as
  UTF-16 code units, so a surrogate pair splits into two halves matching no
  real glyph. `wfb/emit/resources.py` omits `filter` entirely for a font
  that needs such a glyph — safe, because the `.fnt` is already subsetted by
  this project's own baking.
- `icons.font_key` (and `wfb/layout.py`, `wfb/emit/resources.py`) is keyed
  by the **declared** size and codepoint, never the resolved pixel size,
  because the generated view class is shared across every target device — a
  device-resolved key produces a different `Rez.Fonts.*` symbol per screen
  size and an `Undefined symbol` error on every device but the one the view
  was generated from.
- ruamel 0.19.1's real API for injecting source-position metadata (the
  obvious guess is wrong): a sequence position needs
  `add_idx_line_col(i, [line, col])` (`lc.data` is `None` until the first
  `add`), and an injected mapping key needs
  `add_kv_line_col(k, [l, c, l, c])` — **four** values, because `key()`
  reads slots 0–1 and `value()` reads 2–3.
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
- **`wfb.availability.Guards`, the per-device API gating this project's one
  shared generated view/delegate needs (2026-09-15).** `compute_guards(face,
  devices) -> Guards(complications: bool, fields: frozenset[str], modules:
  frozenset[str], ...)` is the single place that decides, once per build,
  which `Toybox` modules the shared code must `has`-guard (`modules`:
  `Complications`, and since plan 18 item 2 `Weather`, which
  `fenix5`/`fenix5x` lack; `complications` is kept as the flag the
  complication-only sites read), and which bare field names
  (`Device.has_field`'s namespace, e.g. `stressScore`) need an `x has
  :field` guard -- aggregated over *every* device in the build (`targets:`,
  or whatever `-d` selected, which may name non-targets since 2026-09-18), not
  just the one `wfb.layout.resolve` happened to generate the view from,
  because the view is shared across all of them. A design whose targets all
  support everything it uses gets an empty `Guards` and generates the exact
  same code it always did (golden tests confirm byte-identical output);
  every `emit_view`/`emit_delegate`/`ReadPlan` call site defaults its
  `guards` parameter to a module-level `_NO_GUARDS` constant so every
  pre-existing caller (every test, any single-device caller) is unaffected.
  Guards are emitted at: `onLayout`'s complication subscribe/register loop,
  every module-gated reader pull in `ReadPlan.emit_reads` (one
  `has<Module>` local per module per frame, not per reader), a forecast
  graph's acquisition (`wfb.emit.monkeyc.graph`), `on_hold:`'s
  `Complications.exitTo` (both the fixed-type and `complication_slot`
  `auto` forms), and a `config: data:` slot's `Complications.Id` field. Two
  gotchas the implementation ran into: (1) a **field initialiser** runs
  before any guard could matter (`docs/lore/monkeyc.md`), so a guarded
  `config: data:` field is declared nullable and actually constructed,
  guarded, inside `initialize()` instead of inline; (2) a missing *field*
  (as opposed to a missing module) is keyed by the *first* dotted segment of
  `Source.field_name` -- the nullable intermediate object itself for a
  dotted path like `activeMinutesWeek.total`, since `Device.has_field`
  cannot resolve which class a bare field name belongs to (`wfb.devices.
  Device._fields`'s own presence-is-approximate caveat). See
  `wfb/availability.py`'s module docstring for the full design (two
  consumers: `compute_guards`'s aggregate for codegen, and per-element
  `source_unavailable`/`reader_unavailable` for a lint pass to point at the
  exact YAML line) and `docs/research/probes/api-gating/` for the evidence.
- **One view and one delegate for every target, and a check that they
  really are shared (plan 19 A5, 2026-09-25).** `wfb.build` resolves each
  target once (`resolve_all`), and `wfb.emit.generate(..., resolved=...)`
  reuses those faces instead of baking and resolving again. Whatever the
  shared sources decide per device is decided over the whole build:
  `Guards` (which now also carries `partial_update_unsupported`, the view's
  `onPartialUpdate` decision, which used to read device 0 alone), and
  `needs_icon_glyphs`, a union over every target's placed items. As a
  check, `generate` emits the view and the delegate from every target's
  resolved face and compares each with the first's (`_check_shared`). A
  difference is a `Divergence`, which `wfb.build` reports as a
  `shared-source` build error naming the file, both devices and the first
  differing line. A per-device fact that leaks into a shared source
  therefore fails the build instead of silently following the first
  target, the way the view's `Device: <first>` header and its
  partial-update comment (that device's clip percentage) did until A5. A
  per-device fact belongs in `Layout.mc`. Measured before the change, over
  every example and fixture on its own targets and on all 22 installed
  devices: those two comment lines were the only differences.
- **System-font metrics (plan 09 §4 R2, 2026-09-18): one `FontMetric` per
  `FONT_*` symbol per device, one place turning it into a real face.**
  `wfb.devices.Device.system_fonts` merges the scraped SDK reference table
  (`face`/`font`/`size_px` -- `size_px` is the published *line height*, and
  stays the number layout trusts even after enrichment) with the installed
  device's own `simulator.json` `ww` font set, when the two agree on a
  symbol: a `type: "ttf"` entry with a top-level `ppi` and a point `size`
  contributes `em_px = size * ppi / 72` (`docs/research/10-system-fonts.md`
  §3's verified model), and `ascent_px`/`height_px` when the device file
  states them outright (about a third do). A bitmap-only device (fenix6:
  no `ppi`, no `type` key at all) or a `ww` entry naming a symbol the
  scraped table has nothing for leaves those three `None` -- deliberately:
  `wfb.devices` never imports Pillow/fontTools, so deriving an em from a
  TTF's own `hhea` table happens lazily in `wfb.fonts.fallback` instead,
  only for a symbol actually referenced, and only via a *local* `fontTools`
  import (the same "no dependency beyond what the caller asked for" shape
  `wfb/icons.py` and `wfb/fonts/bmfont.py` already use).
  `wfb.fonts.fallback.system_face(metric, scale=1, fonts_root=None)` is the
  one place a `FontMetric` becomes a Pillow `FreeTypeFont`: it locates the
  real file via `wfb.fonts.fetch_system.locate` (`fonts_root` first --
  `--fonts DIR`, `Device.fonts_root` for every caller that has a device --
  then `WFB_FONTS`/`vendor/fonts/`/the per-OS SDK Manager location, then the
  pinned free-stand-in registry, `wfb.fonts.fetch_system`'s own module
  docstring), derives whatever the metric did not already carry from that
  file's `hhea`/`head` tables, and returns a `SystemFace` whose
  `line_height`/`baseline` are already in the same scaled pixel units as its
  `font` -- `wfb.layout` (measuring, always at `scale=1`, `fallback.measure`/
  `line_height`/`ascent` all taking the same `fonts_root`) and `wfb.preview`
  (drawing, at the preview's own upscale) both go through this one function
  **with the same root** (`Device.fonts_root`, owned by `DeviceDatabase` and
  carried by every `Device` it builds -- plan 18 item 8), so a
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
  `monkeyc`'s input: a `Placed*`'s `font_metric` only feeds `wfb.layout`'s
  own lint boxes and `wfb.preview`'s ink, never a baked pixel position --
  the runtime anchor a `text`/`complication_slot` draws at was already
  unshifted before this (this file, finding 7's sibling reasoning: a glyph
  kind's alignment is a device-side justify, not a build-time box move), so
  the *only* generated-code effect observed is a `_WIDTH` layout constant's
  own comment and value changing where the estimate got more accurate (a
  system font's widest-rendering comment, never referenced elsewhere in the
  generated code) -- confirmed by the golden `Layout.mc` diffs this step
  produced, one line each, nothing else.
- **Derived metrics for a device with no scraped page at all (plan 17,
  2026-09-23): a third source, stdlib `struct` only, that never touches a
  scraped device.** Three installed devices (`fenix947mm`,
  `fenix9prosolar47mm`, `fenix9prosolar51mm`) have no
  `docs/research/data/devices/<id>.json` at all, so `Device.system_fonts`'
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
  `--fonts DIR`'s own value for a `DeviceDatabase` built with it -- plan 18
  item 8). **`wfb.devices` still never imports
  Pillow/fontTools**: `_sfnt_head_hhea` is a from-scratch `struct` reader
  of the sfnt table directory (`numTables` at offset 4, 16-byte table
  records from offset 12, `head.unitsPerEm` at its own offset 18,
  `hhea.ascent`/`descent` at offsets 4/6), cached per resolved path, never
  raising. **No scraped device gains a symbol from this** -- checked
  against every installed device with a scrape, the first loop already
  covers every symbol this loop could otherwise reach, so its own
  `if symbol in metrics: continue` guard always wins first. Importing
  `wfb.fonts.fetch_system` (for `garmin_font_root`/`garmin_any_file`) has
  to happen *lazily*, inside the function that needs it, not at module
  level: `wfb.fonts`' own `__init__` imports `wfb.fonts.fallback`, which
  imports `FontMetric` back out of `wfb.devices` -- a real cycle if
  `wfb.devices` tried to import `wfb.fonts` while still mid-load itself,
  but harmless deferred to call time, since nothing calls
  `Device.system_fonts` until a caller already holds a fully-constructed
  `Device`, long after both modules have finished loading.
- **Vector fonts and `curve:` (plan 11): per-device `Layout` constants, one
  guard for the whole build, one null check that is never omitted.** A used
  `face:` font gets `FONT_<NAME>_FACE`/`_SIZE` in every target device's own
  `Layout.mc` (`wfb.emit.monkeyc.layout_constants._vector_font_constants`):
  `_FACE` is that one device's own resolved face name (`wfb.availability.
  vector_font_face`, empty string when none of the requested candidates is
  published), `_SIZE` its pixel height, both independent of any element's
  `curve:` -- `Graphics.getVectorFont` is constructed once per font name in
  the *shared* view (`onLayout`), not once per drawing element. A third
  constant, `_AVAILABLE`, is emitted **only** for a font at least one target
  in the build fails to resolve (`wfb.availability.Guards.vector_fonts`,
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
  `if_unavailable:` mode**, because the platform gives none: every draw
  call using a vector font (`wfb.emit.monkeyc.shapes._emit_vector_text_
  draw`) captures the field into a local first (`var font = _fontBezel;`)
  and wraps the actual `dc.drawText`/`drawAngledText`/`drawRadialText` in
  `if (font != null)` -- the field-vs-local capture is not optional
  ceremony, it is `docs/lore/monkeyc.md`'s own "type narrowing must go
  through a local, never a repeated field access" rule, and this is one
  more confirmed instance of it (the field, unlike a local, cannot be
  narrowed by an `if` one statement earlier). The constant that guards
  *construction* and the null check that guards every *draw* are answering
  two different questions -- "should this device even try to build the
  font" vs. "did building it actually work" -- and neither is relied on to
  stand in for the other.

- **Vector fonts and `curve:` on a pattern's own `shape: text` part (plan
  11 slice 2): the local-angle-composed-with-the-copy design, and why gate
  4's guard has to move from "once, before the loop" to "once per copy,
  inside it."** Slice 1's own `Curve` dataclass and every build-time gate
  (1-3) are reused unchanged (`wfb.layout.Resolver._resolve_vector_face`/
  `._vector_font_metric`, called from `._resolve_hand_part`'s own `text`
  branch the same way `wfb.kinds.text.resolve` already calls them) -- the
  only new work is the angle's *composition* and one codegen-side behaviour
  change.

  **Composition.** `ResolvedHandPart.curve_angle_garmin` is this part's own
  *local* angle (`HandPart.curve.angle`, run through `wfb.layout.
  garmin_curve_angle`), for copy 0 alone -- never combined with a radial
  pattern's own rotation in `wfb.layout`. That combination is one
  definition, `wfb.kinds.pattern.PatternTextAngle` (plan 19 A1): `local`/`start`/
  `step` are the part's local angle and the pattern's own repeat angle, and
  `copy_curve_angle(index)` is `(local - (start + index * step)) % 360.0`,
  the host evaluator the lint ink box (`wfb.kinds.pattern._pattern_text_ink`) and
  the preview (`wfb.kinds.pattern._pattern_text`) both call. Codegen
  (`wfb.kinds.pattern._emit_pattern_text_angle_expr`) reads the same
  `local`/`start`/`step` off that object but builds Monkey C from them
  instead of calling the evaluator: `g0 = part.curve_angle_garmin -
  element.start_angle`, then `g0 - i * step_deg` per copy, the *exact*
  shape a radial pattern's own `arc` part already used for its
  `start_angle:` (`_emit_pattern_part`'s arc branch, unchanged, one row up
  from the text branch). Deriving the sign: a radial pattern turns
  copy `i` by `element.start_angle + i * element.step_angle` **design**
  degrees, clockwise from 12 -- always a *position*-style rotation of the
  whole template, regardless of the part's own `curve.style`. Composing it
  into a Garmin-space angle by straight subtraction is valid whichever
  style `part.curve_angle_garmin` itself came from: for `radial` it is
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
  (`wfb.kinds.pattern.resolve`), so `g0` reduces to the part's own local
  angle unchanged and no `i *` term is emitted at all -- the "no copy angle
  to compose with" case falls out of the shared formula for free, not a
  separate branch. `wfb.kinds.pattern._pattern_text` calls the same
  `PatternTextAngle.copy_curve_angle`, reading `PlacedPattern.start`/`.step`
  (already `element.start_angle`/`.step_angle` in degrees) instead of
  re-deriving them.

  **Why gate 4's guard cannot stay "load once, early-return before the
  loop."** That is exactly what a *baked* custom font on a pattern text
  part still does (`wfb.kinds.pattern.emit_draw`'s own `text_fonts` pre-loop loading,
  unchanged) -- reasonable there, because a baked resource failing to load
  is a structural failure, essentially never observed. A vector font's
  null is the *ordinary* case under `if_unavailable: hide`, or even under
  `error` (gate 4 has no build-time guarantee at all), and an early
  `return;` before the loop would silently cancel every *other* part of
  the *same* pattern too -- unrelated shapes, unrelated fonts, all sharing
  this one generated draw method. So a vector font's local is still loaded
  once before the loop (`wfb.kinds.pattern.emit_draw`'s new `vector_text_fonts` split),
  but never early-return-guarded; instead `wfb.kinds.pattern.
  _emit_pattern_text_draw` wraps only its own draw call in `if (<local> !=
  null)`, every copy, the same shape `wfb.emit.monkeyc.shapes._emit_
  vector_text_draw` already uses for a standalone element -- and this
  applies even to an *upright* (uncurved) vector-font pattern part, not
  only a curved one: gate 4 does not care whether `curve:` was authored.

  **`style: radial`'s circle is centred on that copy's own anchor**, not a
  fixed point -- the same `at:` reinterpretation a standalone `curve:
  {style: radial}` text element already gives, applied per copy: the
  circle's radius (`curve_radius_px`, a `handLength` -- px/%r only, plan
  11 slice 2's `patternCurve` schema def -- resolved once, the same for
  every copy) gets a `Layout` constant (`<part>_RADIUS`, `wfb.emit.monkeyc.
  layout_constants._hand_part_constants`'s `text` branch), the same as an
  `arc` part's own `_RADIUS`; the angle does not, for the same reason an
  `arc` part's `start_angle`/`sweep` never did -- it is device-independent
  and needs a per-copy runtime term, so it is inlined straight into the
  shared view instead of a per-device `Layout` constant nothing would
  differ across devices for anyway.

- **`outline:`'s stamp offsets (plan 15 slice 1): a build-time-computed,
  loop-not-unroll array, the same "a runtime loop's cost is in the array,
  not the loop body" finding `docs/research/probes/pattern-cost/README.md`
  already established for `drawLine`/`fillPolygon`, now confirmed for
  `drawText` too (`docs/research/14-stamped-ring-text.md` §4.3, a real
  `monkeyc --build-stats` run, warning-free on `fenix8solar47mm`).** The
  offsets themselves (`wfb.ir.disc_perimeter_offsets`) are pure Python,
  never authored: `disc-perimeter` at radius `r` is every integer `(dx,
  dy)` with `(r-1)² < dx²+dy² <= r²`, exactly 4/8/16 points at r=1/2/3 --
  the *only* offset set this format ever emits (no `offsets:` escape
  hatch, D3 of plan 15 §13: `square8` overshoots, `cross4` undershoots
  with a gap that widens as the ring grows and is rotation-variant around
  a radial run). Emitted once per **distinct width actually used
  anywhere in the design** (`OUTLINE_OFFSETS_<W>`, an `Array<Number>`
  flattened `[dx0, dy0, dx1, dy1, ...]`, not `Array<Graphics.Point2D>` --
  `Dc.drawText`'s own `(x, y)` are two separate `Number` arguments, not a
  tuple), the same "keyed by what's declared, deduplicated across
  elements" shape a `face:` font's `_FACE`/`_SIZE` constants and a
  polygon's own `_POINTS` constant already use. Research 14 §4.3 measured
  the loop form as flat in code size at both N=8 and N=16 (only the data
  growing, ~5 B/`Number`) and close to a wash against unrolling at N=8,
  pulling ahead at N=16 -- the loop is the unconditional default, both
  because it is never worse at the sizes this format actually needs and
  because it is the one shape that lets `width:` be a data value rather
  than a rewrite of call sites. The stamp loop (`wfb.emit.monkeyc.shapes.
  _emit_outline_loop`) wraps a caller-supplied per-anchor draw callback,
  shared verbatim between the interior pass and every stamp -- so a
  screen-space anchor shift is the *only* thing that differs between a
  stamp and the interior draw, for every draw-call shape a standalone
  `text` element can take (plain `drawText`, `drawAngledText`,
  `drawRadialText`), exactly research 14 §3.2's "commutes with rotation"
  derivation.

- **`outline:` on a pattern's own `shape: text` part (plan 15 §14 slice
  2): the same stamp loop, one level down, plus a real `monkeyc` finding
  slice 1 never hit.** `HandPart.outline` and `Builder._build_outline`
  are shared verbatim with a standalone `Text.outline` -- the only new
  builder work is threading a pattern's own absence policy through
  (`_build_outline(..., element=None)` for a part: no immediate
  `_check_other_absence`, because a pattern polices absence once for the
  whole element over `PatternElement.colors`, which a part's own
  `outline.color` now feeds into alongside `part.color`). `ResolvedHandPart`
  grows two exploded fields, `outline_width`/`outline_color`, carried
  through from `HandPart.outline` unchanged (the same "explode, don't
  nest" shape `curve_style`/`curve_angle_garmin`/... already use for
  `HandPart.curve`) -- `wfb.kinds.pattern._pattern_text_ink` reads
  `outline_width` as the same `pad` a standalone element's own
  `outline:` passes to `wfb.layout.text_ink` (D9), and
  `wfb.kinds.pattern._emit_pattern_text_draw` reads both fields
  directly, the same way it already reads `part.color`.

  **Screen-space offsets survive both transforms a pattern text part can
  have, because neither is touched by the stamp.** A radial pattern's own
  per-copy rotation is already baked into the anchor by the time
  `_emit_pattern_text_draw` builds `x_expr`/`y_expr` (`WfbGeom.rotatedX`/
  `rotatedY(...)`, or `ox + Layout..._X` for a linear pattern); a part's
  own `curve:` angle is a *separate* argument (`_emit_pattern_text_angle_
  expr`), never folded into `x_expr`/`y_expr` either. So appending
  `+ offsets[i]` to the already-fully-transformed anchor string -- exactly
  what `_emit_pattern_text_call` (split out of the old `_emit_pattern_
  text_draw` so the interior pass and every stamp share one "anchor in,
  draw lines out" callback, the pattern-level twin of `wfb.emit.monkeyc.
  shapes._emit_plain_text_call`/`wfb.kinds.text._emit_vector_draw_call`)
  does -- lands
  the ring in screen space at every copy, at whatever angle that copy's
  own rotation and curve already put it at, with no correction needed.
  Confirmed both by codegen tests reading the actual generated expression
  and by a preview test that samples pixels near each of four rotated
  copies' own independently-computed anchors (`tests/test_pattern_text_
  outline_preview.py::test_every_copy_gets_its_own_ring_not_just_copy_0`).

  **Real `monkeyc` finding: a pattern's own copy loop already owns the
  name `i`, and Monkey C rejects redefining a variable even across
  separate straight-line statements in the same method.** Slice 1's
  `_emit_outline_loop` hardcoded `var i = 0;`/`var offsets = ...;` --
  fine for a standalone element (one generated method per element), but
  every part of one pattern shares a *single* generated method, whose own
  `for (var i = 0; i < element.count; i++)` already claims `i`. Nesting an
  outlined text part's stamp loop inside that failed to compile
  (`Redefinition of variable 'i'`) the moment `tests/fixtures/outline_
  text/face.yaml` gained its first pattern-with-outline element -- caught
  by a real build, not by any Python-level test, since nothing before
  `monkeyc` itself understands Monkey C scoping rules. Fixed by giving
  `_emit_outline_loop` `index_var`/`offsets_var` parameters (default
  `"i"`/`"offsets"`, so every slice-1 caller is byte-for-byte unaffected),
  with the pattern caller deriving unique names from the part's own
  `part_prefix` (`f"outlineI{part_prefix}"`/`f"outlineOffsets{part_
  prefix}"`) -- the same per-part uniqueness `Layout.{part_prefix}_X`
  already relies on, which is also what keeps two outlined text parts in
  the *same* pattern from colliding with each other, not just with the
  copy loop's own `i`.

- **`aod:` restyling (plan 14 slice 2): ternary beats a second method,
  measured per ADR 0008, and an AOD-only font is cheap.** Two candidate
  shapes for reading an `AodOverride` at the draw call site: an inline
  `_aod ? <aod> : <awake>` ternary inside the *one* existing per-element
  method (`_emit_element_method` already calls the same method from both
  the active and AOD branches -- plan 14 slice 1), or a second, fully
  separate method (`draw<Id>Aod`) called from the AOD branch instead. A
  throwaway probe with 8 overridden elements (every override key exercised
  at least once: `color`/`track_color`/`thickness`/`filled`/`format`/`font`/
  `bar_width`, `fenix847mm`, `--build-stats`) measured **4,704 B** (1,026 B
  data + 3,678 B code) for the ternary shape this project actually built,
  against **5,169 B** (1,098 B data + 4,071 B code) for a hand-written
  second-method variant of the exact same design -- the ternary is **465 B
  (9%) smaller**, because every duplicated method repeats its own
  declarations/guards/reads and the two-method call sites (one per branch)
  cost more than one ternary each. Kept the ternary as the unconditional
  default (`wfb.emit.monkeyc.common.AodStyle`, one call site
  per overridable key), matching the plan's own prediction (§4.2) rather
  than just assuming it.

  **A baked font used only by an `aod: {font: ...}` override, never drawn
  while awake, is a second resource** (§4.3): declared under `fonts:` like
  any other, baked unconditionally by `wfb.emit.resources.bake_fonts`
  (which bakes every declared font regardless of whether anything draws
  with it while awake -- `glyph_set` is extended to also collect the
  *override*'s own needed glyphs, through its own `format:` override if it
  has one, so it is never baked with the empty-glyph-set "0123456789"
  fallback), but the view field for it is declared separately
  (`_aod_only_fonts`, `wfb.emit.monkeyc.common`) and loaded **only** inside
  `onEnterSleep`'s own `if (_aod)` branch -- never in `onLayout` -- with the
  field nulled again in `onExitSleep`, so it never sits resident while
  awake. Measured (two otherwise-identical one-clock faces, baked custom
  font, `fenix847mm`, `--build-stats`): **1,209 B** (633 B data + 576 B
  code) with one font used both awake and (unstyled) asleep, **1,301 B**
  (651 B data + 650 B code) once a *second*, AOD-only font is declared and
  overridden in -- a **92 B** difference (0.07% of the 131,072 B budget) for
  the extra field, its conditional load/null bookkeeping, and the font
  ternary at the call site. Confirms the plan's own prediction ("since API
  4.0.0, loaded fonts live in the graphics pool, this should be cheap") --
  the *resource* itself never touches this figure at all (constraint 11);
  what is measured here is purely the bookkeeping around it.

  **Scope actually shipped in slice 2, and what is deliberately deferred:**
  ternaries for every allowlisted key on `shape`/`text`/`progress`/`icon`/
  `graph`, `filled` as an `if (_aod) { <opposite draw> } else { <awake
  draw> } ` branch (`wfb.kinds.shape._emit_filled_toggle`), `format`
  as two fully-formatted value expressions ternaried against each other
  (built before `when_absent:` substitution, so a placeholder/fallback
  still sees the right one), and `hands`/`pattern` `color`/`thickness`
  applied uniformly to every part by ternarying the *existing* per-part/
  hoisted `dc.setColor`/`dc.setPenWidth` call sites against one element-
  level override, never restructuring the hoisting logic itself (plan 14
  §5.1). **Not implemented yet, matching `docs/limitations.md` §2 -- and,
  per house style (CLAUDE.md §7, the same rule per-device `overrides:`
  follows), each is a friendly build error, never a silent no-op**: a
  `pattern`'s own `font:` override (allowlisted, plan 14 §2.3, but a
  pattern's per-copy text font loading has no second-resource slot yet), a
  `complication_slot`'s `font:` override (same reason), any `font:`
  override that names a `face:` (vector) font rather than a baked one (gate
  1-4's own machinery has no AOD-override-aware second face/size constant
  yet), and `aod: {filled: ...}` on `shape: polygon` (there is no outline
  primitive for it to switch to -- the same reason the awake element's own
  `filled: false` is already refused, `wfb.kinds.shape.build`).
  All four are raised on the author's own line: in `Builder._build_aod_authored`
  for an element's own block, and in `Builder._resolve_aod` for a key the
  element inherits from a group (plan 18 item 5; both read one table,
  `Builder._aod_refusal`, so they cannot disagree). A face using one of
  them never reaches codegen or `wfb preview
  --aod` at all -- there is nothing left for either to draw, and the
  runtime fallback code both still carry for the font cases (e.g.
  `wfb.kinds.text._emit_text_draw`'s `is_vector` check) is
  defensive, not a live path.

- **`aod: {dim: ...}` (plan 14 slice 3): the split is `Expression.is_constant`,
  not a choice between two implementations -- and a real `monkeyc` build
  caught a barrel-file omission no Python-level codegen test could.**
  `dim` has to scale a colour that is either a build-time literal
  (`palette.<name>`, a bare hex) or something the device resolves at
  runtime (`config.colors.<role>`, a conditional between several colours).
  Plan §4.5 offered two candidate implementations for the runtime half:
  a small integer-math helper (`dim(color, num, den)`), or precomputing a
  dimmed variant per `color_scheme:` entry. The second was never actually
  built to compare against: `config.colors.<role>` is a *view field* the
  wearer's own on-device pick can repoint at runtime
  (`Builder._define_config_color`, `constant=None` by design), so
  precomputing a dimmed variant would mean a second shadow field kept in
  sync on every `applyConfig`/style edit -- strictly more fields, more
  bookkeeping, and a second place that field and its shadow could drift --
  for a value that is one `Number` and three shifts to compute from the
  field that already exists. The runtime helper (`WfbColor.dim`,
  `runtime-lib/WfbColor.mc`, integer channel math -- never `Float`, so its
  rounding is bit-for-bit the same as the Python half's, `wfb/palette.py`'s
  own `dim_channel` docstring) is what shipped. `Expression.is_constant` --
  already true for a `palette.<name>` reference (`fold_colors=True`'s own
  resolved-constant half, `Builder._expression`) and already `None` for
  `config.colors.<role>` -- is exactly the fact that decides which of the
  two a given colour needs, so `wfb.emit.monkeyc.common._dim_color_code`
  needed no new classification of its own: a constant colour is pre-dimmed
  into a second literal in Python once, at build time
  (`wfb.palette.Color.dim`); anything else calls `WfbColor.dim` at the draw
  site. Measured (`fenix847mm`, `--build-stats`, one `text` element): a
  face with `aod: show` and no `dim:` at all is 1,127 B; the same face with
  `aod: {dim: 0.5}` on a `config.colors.<role>` colour is 1,318 B -- **191 B**
  for the runtime path (the `WfbColor` module, the call site and the
  ternary together). A colour dimmed at build time costs far less: the
  `examples/features/aod/face.yaml` example (one `palette.<name>`-typed
  colour newly dimmed, `accent_dot`, no override of its own) grew from
  2,401 B to 2,415 B on the same device -- **14 B**, a single wider hex
  literal.

  **Whether the generated view ends up calling `WfbColor.dim` at all depends
  on a fact no per-kind IR walk can see**: whether *any* AOD-shown colour,
  across every element and every one of `color`/`track_color`/`icon_color`,
  turned out non-constant with no override. So the barrel set is never
  derived from the IR: `wfb.emit.usage.barrel_modules` (plan 19 A3) scans
  every generated Monkey C source (comments and strings stripped) for a
  `Wfb<Name>.` reference and copies exactly the files named, closed over the
  runtime-lib files themselves -- the same "inspect what was actually
  emitted, don't re-derive it" move `_avoid_string_label_collisions` makes,
  so the copied set cannot drift from the calls codegen wrote. The view's
  `Toybox` imports come from the same scan of the view body
  (`usage.toybox_modules`).
  **This is not a hypothetical:** a real `monkeyc` build of a
  `config.colors.<role>`-dimmed design once failed outright with `Undefined
  symbol ':WfbColor'` under the old ladder, while every Python-level codegen
  test in `tests/test_aod.py` stayed green -- none of them invoke `monkeyc`
  at all, only `wfb.emit.generate` (source text) or `wfb.preview` (a
  render), neither of which would ever notice a missing barrel file.
  `tests/test_aod.py::test_a_runtime_dimmed_colour_compiles_warning_free`
  (`@pytest.mark.slow`) is what actually builds this exact design for real
  and would have caught it -- add a `slow` test alongside any change to how
  the barrel set is decided (not just its Python-level output), because
  that decision only has a real audience once `monkeyc` runs.

- **The `getDisplayMode` ladder (plan 14 slice 6): one `has`-guarded `if`
  at the top of the AOD branch, cheap enough that no ternary-vs-method
  comparison was needed -- unlike slice 2's own restyling decision, there
  is only one reasonable shape here (an early `return;`), so this is a
  measurement of cost, not a choice between two implementations.**
  `wfb.emit.monkeyc.view._emit_aod_body` gained one condition
  (`(System has :getDisplayMode) && (System.getDisplayMode() ==
  System.DISPLAY_MODE_OFF)` on a mixed AMOLED+MIP build, since `monkeyc`
  compiles the one shared view once per device and at least one MIP target
  always lacks the symbol -- `wfb.availability.Guards.display_mode_guarded`,
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
  `wfb/devices.py`'s `Device.DISPLAY_MODE_SYMBOL` docstring for the
  per-device evidence they move together with `getDisplayMode`), so the one
  `has` check on the method call is the whole runtime cost. `Application.
  AppBase.onDisplayModeChanged` was considered and deliberately not
  emitted -- `WatchFace.onUpdate` already runs once a minute while asleep
  regardless of display mode (`Toybox/WatchUi/WatchFace.html`), so the only
  thing the callback would buy is shaving a worst-case one-minute latency
  off a transition away from `DISPLAY_MODE_OFF`, for the cost of one more
  per-device symbol question (`AppBase` gets no override, no test needed
  for one) -- not measured, because nothing was built to measure.

- **`aod: {mask: ...}` (plan 16, the same day): `WfbAodMask.apply` is
  emitted last in the `_aod` branch, after every element the frame draws,
  and only when the resolved AOD set is non-empty** -- masking an
  all-black frame is pure waste, and the same "only emit what could
  matter" shape `_aod` itself already follows for an all-MIP build.
  **The barrel file is pulled in the same general way every barrel file is
  now (above):** whether the view ends up calling `WfbAodMask.apply(` at all
  depends on `Face.aod_mask` *and* the resolved AOD set being non-empty, the
  same two facts the emitter itself checks -- `wfb.emit.usage.barrel_modules`
  scans the already-generated sources for the literal call rather than
  re-deriving that classification, the same "inspect what was emitted,
  don't re-derive it" move that keeps the two from disagreeing.
  **`wfb/aod_mask.py` is this feature's Python twin**, the same
  shared-renderer stance ADR 0004 already takes for layout, extended here
  from layout to a runtime effect: `wfb.preview.render`, `--heatmap`, and
  the `aod-burn-in` lint all go through its `apply`, so there is no second
  implementation of the mask for any of them to drift from. The two phase
  tables (`PHASES` in `wfb/aod_mask.py`, the `dx`/`dy` ternaries in
  `runtime-lib/WfbAodMask.mc`) cannot be hand-kept in sync either --
  `tests/test_aod_mask_preview.py` parses the `dx`/`dy` logic straight out
  of the real `.mc` source rather than re-typing plan 16 §2 a third time,
  the same anti-drift move as the barrel-detection grep above.
  Measured: `examples/features/aod/face.yaml` on `fenix847mm` is
  **2,726 B** with the mask (the default) against **2,447 B** with
  `aod: {mask: false}` -- **+279 B**, warning-free on all four targets.

- **`date.today`'s `format:` bug (found 2026-09-23): under `FORMAT_MEDIUM`
  (the `date` reader), `month` and `day_of_week` are Strings, not Numbers --
  `%b`/`%a` rely on exactly that, but `%m` (numeric, zero-padded month)
  needs a Number and has none to read on `date`. It has to come from
  `date_short` (`dateShort`, `FORMAT_SHORT`) instead, cast `as Number` the
  same way `date.weekday` already reads `dateShort.day_of_week`. Every
  `%m`-using face failed `monkeyc` outright (`Cannot find symbol ':format'
  on type '$.Toybox.Lang.String'`) until this was fixed, because nothing
  had ever compiled every `DATE_CODES` entry in one build.
  `wfb.formatting.DATE_CODES`' `m` row is the one place "which codes need
  a second reader" is decided: its `emit` and its `extra_path` sit side by
  side, and `extra_paths` (which `wfb.emit.monkeyc.readplan.ReadPlan`
  calls to add the extra reader-local parameter) reads that row, so an
  element's generated method and the parameter list supplying it cannot
  drift apart on this again. Every strftime code's Monkey C (`emit`) and
  host rendering (`render`, what `wfb preview` draws) share that same row
  (`wfb.formatting.Code`).
