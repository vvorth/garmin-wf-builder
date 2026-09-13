# Codegen, IR and generated-project lore

Moved verbatim out of `CLAUDE.md` on 2026-09-13 (§6 "Findings from Phase 2" and "Hard-won facts") so the file every
session loads stays small. `CLAUDE.md` keeps a short summary and the **same
numbering**, so an older citation such as "CLAUDE.md §6" or "CLAUDE.md
constraint 6" for this material resolves here. Keep adding to this file,
not back into `CLAUDE.md`.

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
