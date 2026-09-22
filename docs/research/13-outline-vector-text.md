# 13 — Outlined text with vector fonts

`docs/research/11-always-on-display.md` §1.4 concluded that there is no
outline-text API. It was written when the only fonts in scope were
bitmap fonts (baked BMFont sheets and the device's own system fonts). Vector
fonts (`Graphics.getVectorFont`, research 12) were added afterwards, and they
are the one font path where the watch rasterises a real outline at draw time.
This document re-asks the question for that path only:

> Can a watch face draw a vector-font glyph as an **outline** (hollow, or
> ringed in a second colour)? And is that built into the platform, as it
> appears to be for Garmin's own always-on faces on AMOLED?

**Short answer.**

1. **The rendering engine can do it.** Garmin's graphics library, which ships
   inside the SDK simulator, has a real outlined-glyph mode on its TrueType
   path. It uses FreeType's stroker with a fixed 2 px round-join border, and
   draws a two-pass "border in one colour, glyph in another" run. So the
   suspicion is right that outline text is built into the platform's text
   renderer. **VERIFIED** in the simulator binary (§2).
2. **A Connect IQ app cannot switch it on.** The mode is keyed on a style bit in
   the *font record*, not on anything the draw call takes. None of the inputs
   that can reach that bit from Monkey C carries it:
   - `getVectorFont` reads exactly `:face`, `:size`, `:font` and `:scale`;
   - there is no API symbol for it;
   - the device files have no key for it.

   **VERIFIED** for the API surface and the simulator's option parsing (§3).
   **UNVERIFIED** for real firmware (§4).
3. So for this project the conclusion of research 11 §1.4 stands, now covering
   vector fonts too: **outline text is not a draw-time switch**. The workable
   substitutes are listed in §5.

Every claim is marked **VERIFIED** or **UNVERIFIED** per `docs/CLAUDE.md`.
The "probe" is static reverse engineering of `$CIQ_SDK/bin/simulator` (SDK
9.2.0, Linux x86-64). The scripts and the method are in
`docs/research/probes/outline-text-re/`. The simulator itself cannot run an app
here (root `CLAUDE.md` §3), so nothing below was *observed on screen*.

---

## 1. The public API: still nothing

**VERIFIED.** The API has not changed since research 11:

- **`Dc` text calls take no style argument.** `drawText`, `drawAngledText` and
  `drawRadialText` (`$CIQ_SDK/doc/Toybox/Graphics/Dc.html`) take a font, a
  string, a justification mask, and for the curved calls an angle, radius and
  direction.
- **`getVectorFont` takes four options** (`Graphics.html`, `VectorFontOptions`):
  `:face`, `:size`, and since 5.1.0 `:font` and `:scale`.
- **No outline word in the SDK.** Searching the whole SDK
  (`doc/`, `bin/api.mir`, `bin/api.db`, `bin/api.debug.xml`) for
  `outline|stroke|hollow|border` finds only these:
  - `Dc.setStroke`;
  - swim-stroke enums;
  - `highlightBorderColor`;
  - `ComplicationDrawableRef`'s bounding box.

  `api.db`, the symbol table the VM resolves option keys through, has no
  `outline`, `stroke`, `style` or `border` symbol at all.
- **`Dc.setStroke`/`setFill`** (API 4.0.0+) "set draw/fill tool for drawing
  primitives". The docs never say they apply to text. That turns out to be
  half-wrong for the engine (§2.3), and irrelevant for apps (§3).
- **The font catalogues hold no outline faces.** Across all 164 devices'
  scalable-font catalogues (`docs/research/data/devices/*.json`,
  `fonts.*.scalable`) there are 41 distinct face/file pairs. None is an outline
  or hollow design. The closest are the `-Outdoor` cuts (`Roboto-Medium-Outdoor`
  and others, on 7 devices), which are heavier, high-legibility variants, not
  outlines. This matches the installed `simulator.json` files.

## 2. The engine underneath: an outlined-glyph mode exists

The SDK simulator is not a mock renderer. It statically links Garmin's firmware
graphics stack. Its strings name the source trees:
`../../../submodules/technology/graphics/TTF/ttf_intf.cpp`,
`…/monkeybrains/virtual-machine/vm/tvm_gfx_c.cpp`, and `GFX_outgtext_ex2`,
`GFX_set_fcolors` and about 150 other `GFX_*` entry points. Garmin's
`BitbltFontGlyph` and "`--- GFX: Forced Flush …`" diagnostics are in there
too. What follows is read from that code. Addresses are for SDK 9.2.0.

### 2.1 FreeType's stroker is linked, *and actually called*

**VERIFIED.** FreeType is linked statically, including `FT_Stroker_*`,
`FT_Glyph_Stroke`, `FT_Glyph_StrokeBorder` and `FT_Outline_Embolden`. Their
presence alone proves nothing, because `ftstroke.c` ships in FreeType's base
modules. What matters is the callers:

| FreeType call | called from | what it does there |
|---|---|---|
| `FT_Stroker_New` + `FT_Stroker_Set(s, 0x80, ROUND, ROUND, 0)` | TTF engine init (`0xc1ab50`, reached from `ttf_intf.cpp` init) | one global stroker, radius `0x80` in 26.6 fixed point = **2.0 px**, round caps and joins |
| `FT_Glyph_StrokeBorder(&glyph, stroker, inside=0, destroy=1)` | the TTF glyph rasteriser (`0xc1abb0`) | replaces the glyph with its **outside border** (the glyph grown by 2 px) before rasterising |
| `FT_Glyph_Stroke`, `FT_Outline_Embolden`, `FT_GlyphSlot_Embolden` | nothing outside FreeType | unused |

### 2.2 How the rasteriser is told to outline

**VERIFIED.**

- **The rasteriser takes a boolean.** The TTF glyph rasteriser (`0xc1abb0`)
  takes an "outline" boolean as its sixth argument. When it is set, the glyph
  goes through `FT_Glyph_StrokeBorder` and the glyph-cache key gets `| 0x100`,
  so outlined and plain glyphs are cached separately.
- **The layout loop sets it from bit 5.** The boolean comes from bit 5
  (`0x20`) of the text-flags word of the TTF run-layout function (`0xc18540`):
  `outline = (flags >> 5) & 1`. On a 16-bpp surface it is forced off when the
  background colour is transparent (`0xFFFF`).
- **The callers set bit 5 from the font record.** Both callers set bit 5 only
  when **the font record's style byte at offset `+0x30` has bit `0x20`**.
  - `0xc12f90`: `test byte [font+0x30], 0x20; jz …; or ecx, 0x20`.
  - `0xc12ef0`: it passes flags `0x22` instead of `0x02`.
  - The plain `GFX_outgtext` path (`0xc083f0`) makes the same check,
    `cmp byte [font+0x30], 0x20`. That check drives the per-string outline
    state, and it is the path Connect IQ's `drawText` takes (§3.1).

So **"outlined" is a property of the font, not of the draw call.** Nothing in
the text call chain from the VM passes this bit in. It comes only from the font
record.

### 2.3 What an outlined run looks like: a ring, drawn in the *fill* colour

**VERIFIED from the code; the pixels themselves are UNVERIFIED.** When the flag
is set, the layout loop draws the string **twice**:

1. **Outline pass.** Every glyph is drawn through the stroked path (the glyph
   grown by 2 px). The draw colour is swapped for colour slot 3 for this pass:
   `0xbefb40(save, ctx, 0, 3)` copies `ctx+0x80`/`+0xf0` over `ctx+0x68`/`+0xe4`,
   and `0xbefc70` restores it. Slot 3 is the one `GFX_set_fcolors` and
   `SetFillStyleColor` write: the **fill colour**. It is not the background
   (`+0x64`, written by `SetBackgroundColor`) and not the foreground (`+0x68`).
2. **Glyph pass.** The plain glyphs are drawn on top in the normal draw colour.

This is the classic FreeType "outlined text" technique: text in colour A
with a 2 px border in colour B. If the glyph pass is drawn in the background
colour, only the 2 px ring stays lit, which is the hollow look AOD
guidance asks for. The fixed 2 px radius and the round joins suggest it
was built for legible labels (map labels are the textbook user). The
simulator's `edge_map_*` assets fit that reading, but it is a guess.

## 3. Why a Connect IQ face cannot reach it

### 3.1 The call path from `Dc.drawText`

**VERIFIED (direct calls).**

- **`drawText` enters the plain `GFX_outgtext` path.** The `drawText` native
  (`0xd70780` in `tvm_gfx_c.cpp`; it owns the "Anti-aliased font cannot be
  drawn to a paletted buffer" message the docs attach to `drawText`) goes
  `0xd6dab0` → `GFX_outgtext` (`0xc097c0`) → `GFX_outgtext_ex2` (`0xc09510`).
  It passes a zero "rich text" argument, so it always takes that plain path
  (`0xc093a0` → `0xc083f0`).
- **The only outline input on that path is the font record's style byte.** The
  justification mask is split off before `GFX_outgtext`: bit 2 (`VCENTER`) is
  handled in `0xd6dab0`, and values above 2 are rejected.

The vector-text natives (`drawAngledText`/`drawRadialText` candidates `0xd70150`,
`0xd6f610`, `0xd7c390`, `0xd7cbf0`) reach the TTF engine only through function
pointers. Static direct-call analysis does not follow those. **UNVERIFIED** that
they share the same gate, although nothing else in the engine checks for
outline.

### 3.2 Nothing an app controls sets the style bit

**VERIFIED for the simulator.**

- **`getVectorFont` reads four keys, and nothing else.** The native (`0xcb50c0`
  in `tvm_Gfx.cpp`) looks up exactly four option symbols, by their `api.db`
  IDs:
  - `:face` 8392219;
  - `:size` 8388782;
  - `:font` 8389348;
  - `:scale` 8392172.

  It reads no other key. It then gets its font from a platform hook, a
  function pointer in `.bss` that is filled at runtime.
- **The device files cannot declare an outline face.** The simulator parses
  each `simulator.json` font entry for exactly these keys: `size`, `height`,
  `digitHeight`, `ascent`, `descent`, `intLeading`, `scale`, `wide`, `name`,
  `filename`, `type` (`ttf` | `system_ttf`), `narrow` and `prop`. None of them
  is a style or outline key.
- **No instruction in the binary writes `0x20` to a font record's `+0x30`.**
  The byte is only ever *tested* (`scan.py` over all of `.text`). The record
  is filled some other way (a copy, or a platform table), and no path from the
  VM visibly sets that bit.
- **The ring colour may be settable; the switch is not.** Two `tvm_gfx`
  colour-state natives (`0xd6ac10`, `0xd74740`) call `GFX_set_fcolors`. Which
  `Dc` methods they are is **UNVERIFIED**, but `setColor`/`setFill` are the
  obvious candidates. So a face may well be able to set the colour the ring
  *would* be drawn in, but it cannot turn the ring on.

## 4. What is still open

- **Real firmware.** **UNVERIFIED** whether real firmware matches the
  simulator. The simulator embeds the same `technology/graphics` submodule,
  but a watch's firmware font table, which fills font records, could mark some
  system or native-UI fonts as outline-style. **This is the most likely way
  Garmin's own AMOLED always-on faces get outlined digits**, if they use this
  mechanism at all rather than dedicated outline artwork. Even then, a Connect
  IQ `getVectorFont` result would carry that style only if its catalogue entry
  did. No device's published scalable-face list names such a face (§1).
- **What Garmin's native AOD faces actually use.** **UNVERIFIED**, and not
  answerable offline. The forums and the SDK docs say nothing about it.
- **Behaviour on screen.** **UNVERIFIED**. The ring width at small sizes, and
  how the ring interacts with `setAntiAlias`, were not seen. The simulator
  cannot run an app here, and even if it could, no app can switch the mode on.

If the user wants this closed further, the next steps, in order of cost:

1. **Ask Garmin on the developer forum** whether outlined vector text is
   planned for Connect IQ. The engine clearly supports it, so the
   question is concrete.
2. **Try an undocumented hash-key probe on a real watch.** Pass an
   `:outline => true` or `:style => …` option to `getVectorFont`. §3.2 shows
   the simulator ignores unknown keys, so this would test only whether the
   firmware differs. Expect nothing. It is cheap and harmless, but by the
   working agreement ("never invent an API") it can only ever be a probe,
   never shipped code.

## 5. What a face *can* do instead (unchanged in kind, sharper in detail)

All of these are compositions of documented calls. None is a platform outline.

| approach | how | AOD suitability | cost |
|---|---|---|---|
| **Thin face** | a light vector face (`RobotoCondensedRegular` rather than `…Bold`) or a baked thin weight | good: this is what the FAQ and the guidelines actually ask for | none |
| **Stamped ring** | draw the string N times, offset by ±r px in colour A (8 offsets for r = 1, more for r ≥ 2), then once in the background colour on top | the true hollow look, on any font kind, rotated or radial too | N+1 text draws per frame. At the 1-minute AOD cadence that is cheap. Offsets on a curved run move along x/y, not along the curve, so a thick ring on radial text looks uneven |
| **Baked outline sheet** | bake an outline-design TTF, or stroke the glyphs at build time in `wfb/fonts/bmfont.py` (FreeType's stroker is available on the host too) | exact, the cheapest per frame | bitmap only: no `curve:`, no scaling, one more sheet (in the graphics pool, research 12) |

The stamped ring is the only option that works with `curve:` text. If plan 14
(`aod:`) wants "outlined digits", this is the one to model. It needs no new
platform facts: only `drawText`/`drawAngledText`/`drawRadialText` and
`setColor`, all already gated in `wfb/availability.py`.

## Sources

- `$CIQ_SDK/doc/Toybox/Graphics.html` (`getVectorFont`, `VectorFontOptions`),
  `$CIQ_SDK/doc/Toybox/Graphics/Dc.html` (`drawText`, `setFill`, `setStroke`)
- `$CIQ_SDK/bin/api.db`, `api.mir`, `api.debug.xml`: symbol search
- `$CIQ_SDK/bin/simulator` (SDK 9.2.0, Linux): addresses above, method and
  scripts in `docs/research/probes/outline-text-re/`
- `~/.Garmin/ConnectIQ/Devices/*/simulator.json`,
  `docs/research/data/devices/*.json`: font catalogues
- `docs/research/11-always-on-display.md` §1.4, `docs/research/12-vector-fonts.md`
