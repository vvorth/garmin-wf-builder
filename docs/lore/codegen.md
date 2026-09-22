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
   `wfb/emit/manifest.py::BASE_API_LEVEL` (`3.2.0`) is the *only* level
   this compiler ever emits; a feature that needs more is gated at runtime
   per device instead (below), never by moving this number. If a future feature genuinely cannot be runtime-guarded, `api_level()`
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
  devices) -> Guards(complications: bool, fields: frozenset[str])` is the
  single place that decides, once per build, whether the shared code needs
  a `Toybox has :Complications` guard anywhere, and which bare field names
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
  every complication-reader pull in `ReadPlan.declarations` (one
  `hasComplications` local per frame, not per reader), `on_hold:`'s
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
  `wfb.fonts.fallback.system_face(metric, scale=1)` is the one place a
  `FontMetric` becomes a Pillow `FreeTypeFont`: it locates the real file via
  `wfb.fonts.fetch_system.locate` (the user's own Garmin font root first,
  then the pinned free-stand-in registry, `wfb.fonts.fetch_system`'s own
  module docstring), derives whatever the metric did not already carry from
  that file's `hhea`/`head` tables, and returns a `SystemFace` whose
  `line_height`/`baseline` are already in the same scaled pixel units as its
  `font` -- `wfb.layout` (measuring, always at `scale=1`) and `wfb.preview`
  (drawing, at the preview's own upscale) both go through this one function,
  so a monkeypatched `em_px` moves both by construction, never one without
  the other. The preview draws a system-font line from its own line box
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
  branch the same way `._resolve_text` already calls them) -- the only new
  work is the angle's *composition* and one codegen-side behaviour change.

  **Composition.** `ResolvedHandPart.curve_angle_garmin` is this part's own
  *local* angle (`HandPart.curve.angle`, run through `wfb.layout.
  garmin_curve_angle`), for copy 0 alone -- never combined with a radial
  pattern's own rotation in `wfb.layout`. That combination happens twice,
  independently, at the two places that already know which copy is being
  drawn: codegen (`wfb.emit.monkeyc.rotated._emit_pattern_text_angle_expr`)
  and the lint ink box (`wfb.layout._pattern_part_ink`, given a
  `copy_angle_degrees` computed once per copy by `Resolver._resolve_
  pattern`'s own loop) -- both apply `g0 = part.curve_angle_garmin -
  element.start_angle`, then `g0 - i * step_deg` per copy, the *exact*
  shape a radial pattern's own `arc` part already used for its
  `start_angle:` (`_emit_pattern_part`'s arc branch, unchanged, one row up
  from the new text branch). Deriving the sign: a radial pattern turns
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
  (`Resolver._resolve_pattern`), so `g0` reduces to the part's own local
  angle unchanged and no `i *` term is emitted at all -- the "no copy angle
  to compose with" case falls out of the shared formula for free, not a
  separate branch. `wfb.preview._Renderer._pattern_text` performs the same
  arithmetic a third time, in Python floats rather than generated code,
  reading `PlacedPattern.start`/`.step` (already `element.start_angle`/
  `.step_angle` in degrees) instead of re-deriving them.

  **Why gate 4's guard cannot stay "load once, early-return before the
  loop."** That is exactly what a *baked* custom font on a pattern text
  part still does (`_emit_pattern`'s own `text_fonts` pre-loop loading,
  unchanged) -- reasonable there, because a baked resource failing to load
  is a structural failure, essentially never observed. A vector font's
  null is the *ordinary* case under `if_unavailable: hide`, or even under
  `error` (gate 4 has no build-time guarantee at all), and an early
  `return;` before the loop would silently cancel every *other* part of
  the *same* pattern too -- unrelated shapes, unrelated fonts, all sharing
  this one generated draw method. So a vector font's local is still loaded
  once before the loop (`_emit_pattern`'s new `vector_text_fonts` split),
  but never early-return-guarded; instead `wfb.emit.monkeyc.rotated.
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
  `HandPart.curve`) -- `wfb.layout._pattern_part_ink`/`_pattern_text_ink_
  geometry` read `outline_width` as the same `pad` parameter D9 already
  threads through `rotated_rect_corners`/`radial_text_angle_span`/
  `radial_text_band` for a standalone element's own box growth, and
  `wfb.emit.monkeyc.rotated._emit_pattern_text_draw` reads both fields
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
  shapes._emit_plain_text_call`/`_emit_vector_draw_call`) does -- lands
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
