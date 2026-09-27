# 16 — Rectangular, semi-octagon and semi-round screens

**Question.** The project's scope is Garmin watch faces in general (root
`CLAUDE.md` §1), but everything built so far has been exercised on round
screens only. What would it take to support the other three shapes the
platform has, which devices are they, and what is actually blocking each?

**Status:** research; feeds `docs/plans/20-screen-shapes.md`. Every
behavioural claim is marked **VERIFIED** (read from the SDK, the device
files or the repo, or measured here) or **UNVERIFIED**.

---

## 1. The fleet: 21 non-round devices can run a face

From `docs/research/data/devices-index.json` (the SDK's own
`Device_Reference/*.html`, extracted), counting devices with a watch-face
memory limit. **VERIFIED.**

| Shape | Face-capable | Devices | Panel | Face memory |
|---|---|---|---|---|
| `round` | 115 | — | — | — |
| `rectangle` | 9 | `venusq` 240×240, `venusqm` 240×240, `venusq2`/`venusq2m` 320×360, `venux1` 448×486 (all 65 536 colours, touch); `epix` 205×148, `vivoactive` 205×148 (64 colours, touch); `vivoactive_hr` 148×205 (64, touch); `fr920xt` 205×148 (14) | mixed | 64 KB – 1 MB |
| `semi-octagon` | 8 | `instinct2`, `instinct2x`, `instinct3solar45mm`, `instinctcrossover`, `instincte45mm`, `descentg1` (176×176); `instinct2s` 163×156; `instincte40mm` 166×166 | **2 colours**, no touch | 65 536 B, all |
| `semi-round` | 4 | `fr230`, `fr235`, `fr630`, `fr735xt` (215×180) | 14 colours | 65 536 B, all |

28 further rectangular devices (Edge, Oregon and similar) cannot run a face
at all. 115 + 9 + 8 + 4 = 136, which matches root `CLAUDE.md` §1.

**7 of these 21 are installed** (2026-09-27): `venusq`, `venusq2`,
`venux1`, `instinct2`, `instinct2x`, `instinct3solar45mm`, `instincte45mm`
(VERIFIED, `ls vendor/devices`). `venusqm`, `venusq2m`, `instinct2s`,
`instinctcrossover`, `instincte40mm` and `descentg1` are not; every
statement below about them is still from the reference alone. Two more
Instinct-branded devices came with them, `instinct3amoled50mm` (416×416)
and `instinctcrossoveramoled` (390×390), and both are **round** AMOLED
(`simulator.json` `display.shape`, VERIFIED): an Instinct is not
necessarily a semi-octagon. The test suite has no rectangular or
semi-shaped device fixture yet (VERIFIED, `grep` over `tests/`).

### 1.1 How much of the list is reachable at the 3.1.0 floor

The shared manifest floor is 3.1.0, and a device below it is a friendly
build error (`wfb.build.select_devices`, root `CLAUDE.md` 6e). A device's
API level is the `connectIQVersion` of its `compiler.json` `partNumbers`
entries; `wfb devices` prints the highest. For the installed seven
(**VERIFIED**, `compiler.json`, `wfb devices`):

| Device | API | `deviceFamily` | Display | Colours | Face memory |
|---|---|---|---|---|---|
| `venusq` | 3.3.6 (one part number 3.3.1) | `rectangle-240x240` | `lcd` | 65 536 | 98 304 B |
| `venusq2` | 5.0.0 | `rectangle-320x360` | `amoled` | 65 536 | 131 072 B |
| `venux1` | 6.0.2 | `rectangle-448x486` | `amoled` | 65 536 | 131 072 B |
| `instinct2` | 3.4.2 (one part number 3.2.7) | `semioctagon-176x176` | `mip` | 2 | 65 536 B |
| `instinct2x` | 3.4.3 | `semioctagon-176x176` | `mip` | 2 | 65 536 B |
| `instinct3solar45mm` | 6.0.2 | `semioctagon-176x176` | `mip` | 2 | 65 536 B |
| `instincte45mm` | 6.0.2 | `semioctagon-176x176` | `mip` | 2 | 65 536 B |

All seven are above the floor. Note `deviceFamily` spells the shape
`semioctagon`, without the hyphen `simulator.json` uses (platform
constraint 14: read it, never derive it). `venusq` is an LCD, a display
type no installed round device has. The four semi-octagons also set
`antiAliasedFontSupport: false`.

Still **UNVERIFIED**, from Garmin's public device pages plus the SDK's own
"Since" stamps:

- **Semi-round (4) and the three 205×148/148×205 rectangles plus `fr920xt`
  (4)** are 2014–2016 products. They are almost certainly Connect IQ 1.x/2.x
  devices, below the floor, and so already friendly errors. If so, only
  **5 rectangles and 8 semi-octagons are realistic targets.**
- The six missing devices (above) are 2021–2025 products and very likely
  3.x–6.x, like their installed siblings.

`System.SCREEN_SHAPE_SEMI_OCTAGON` is "API Level 3.3.0"
(`$CIQ_SDK/doc/Toybox/System.html`, VERIFIED), below one `instinct2` part
number. That does not matter here: the compiler reads the shape from
`simulator.json` at build time and never asks the device.

---

## 2. What the compiler does per shape today

Read from the code. **VERIFIED.**

| Stage | `round` | `rectangle` | `semi-*` |
|---|---|---|---|
| `Device.shape` (`wfb/devices.py`) | read from `simulator.json` `display.shape` | same | same |
| Visible-area test (`wfb/layout.py` `inside_visible_area_for`) | inscribed circle minus `BEZEL_MARGIN` | the skin mask (§3), else the framebuffer | the skin mask, else `None`, "not checked" |
| `safe_area()` | inscribed square | the framebuffer | `None` |
| `safe-area` lint (`wfb/lint.py`) | checked, shape-aware ink reach | checked against the skin, 1 px tolerance | checked against the skin, 1 px tolerance; a "not checked" note without one |
| Preview crop (`wfb/preview.py` `_mask_shape`) | round crop | the skin mask | the skin mask |
| AOD burn-in denominator (`wfb/lint.py` `_aod_burn_in_mask`) | the disc | the skin's visible pixels | the skin's visible pixels |
| Palette legality (`wfb/palette.py` `is_palette_legal`) | 64-colour rule | 64-colour rule on 64-colour panels | black/white only on 2-colour panels (`palette-mono`); "not checked" on 8 or 14 |
| `%r` (`docs/guide/placement.md`) | minor radius | half the shorter side | half the shorter side |

A device whose skin is missing, or whose `display.location` does not match
its resolution, falls back to the framebuffer (rectangle) or "not checked"
(semi-shapes), so no answer is guessed. `tests/test_visible_area.py` pins
each path, and `tests/test_screen_rectangle.py` the rectangle's geometry.

---

## 3. Visible-area geometry: the simulator skin already encodes it

ADR 0004's Open section says the semi-shape geometry is "resolvable from the
device files' screen shape data once available". `simulator.json` has no
polygon or mask field: `display` holds `isTouch`, `landscapeOrientation`,
`location` (the panel's rectangle inside the skin image) and `shape`
(VERIFIED, `fr955`). But `simulator.json`'s `image` key names a skin PNG
(`fr955.png`, 396×548 RGBA), and **the skin is transparent exactly where
the panel shows through** (VERIFIED): inside `display.location`, alpha is 0
at the panel's centre and 255 at the bezel corners.

Measured by comparing the transparent pixels inside `display.location`
against an ideal inscribed circle (**VERIFIED**, this session):

| Device | Panel | Transparent px | Ideal circle px | Mismatched px |
|---|---|---|---|---|
| `fenix8solar51mm` | 280×280 | 61 572 | 61 572 | **0** |
| `fr955` | 260×260 | 53 362 | 53 096 | 266 (0.5%) |
| `venu` | 390×390 | 119 045 | 119 488 | 443 (0.4%) |

The mismatches are a one-pixel anti-aliased rim. So **the skin's alpha
channel is a per-device visible-area mask**, at the panel's own
resolution, with no geometry to guess.

The non-round skins (**VERIFIED**, 2026-09-27, alpha < 128 counted as
visible):

| Device | Panel | Visible px | What the mask shows |
|---|---|---|---|
| `venusq`, `venusq2` | 240×240, 320×360 | all but 84 | a rectangle with slightly rounded corners |
| `venux1` | 448×486 | all but 4 078 (1.9%) | a rectangle with visibly rounded corners |
| `instinct2`, `instinct2x` | 176×176 | 26 942 (87.0%) | the octagon, plus the subscreen as a separate disc behind an opaque ring |
| `instinct3solar45mm`, `instincte45mm` | 176×176 | 26 481 (85.5%) | the same, inside a 1-px opaque border on all four edges |

So the mask is two connected regions on a semi-octagon: the main face and
the subscreen disc (§4). A rectangle's mask is not quite the framebuffer:
`venux1`'s corners hide about 2% of it. The Instinct 3/E border contradicts
`simulator.json`'s own subscreen box, which starts at row 0 (§4); it is
most likely a skin-drawing artifact, and a mask-based lint should tolerate
a 1-px rim rather than trust it.

This replaces "define safe-area geometry per shape" with one
shape-independent mechanism: load the mask, test ink against it. The
existing round test (a circle minus `BEZEL_MARGIN`) becomes a special case
that could stay as it is. `BEZEL_MARGIN` is a design margin, not something
the skin encodes.

---

## 4. The Instinct subscreen

`WatchUi.getSubscreen() as Graphics.BoundingBox or Null`: "Get the subscreen
area in the display … null if no subscreen is present or if a virtual
subscreen is present but not used for normal views." API 3.2.7. Listed
devices: Descent G1, Instinct 2, 2S, 2X, 3 Solar 45/50mm, E 40mm, E 45mm —
**exactly the eight semi-octagon devices** (`$CIQ_SDK/doc/Toybox/WatchUi.html`,
VERIFIED; the symbol is `functionEntry name="getSubscreen" parent="WatchUi"`
in `$CIQ_SDK/bin/api.debug.xml`, VERIFIED).

What that means for a face:

- The subscreen is the small round window in the top-right corner. It is
  part of the same framebuffer: a face draws into it with ordinary `Dc` calls
  at the box's coordinates. Stock Instinct faces put a gauge or a number
  there. The API returns a *box*, and the visible part is the circle
  inscribed in it: the skin's transparent subscreen region fills its
  bounding box's inscribed disc to within 1% (**VERIFIED**, the four
  installed skins, §3).
- **The box is in `simulator.json`**, as a top-level
  `subscreen.location` in skin coordinates (**VERIFIED**). Minus
  `display.location`, it is **x=113, y=0, 62×62 on all four installed
  semi-octagons**: `instinct2` (212−99, 164−164), `instinct2x` (same),
  `instinct3solar45mm` (214−101, 158−158), `instincte45mm` (223−110,
  173−173). The skin mask agrees to within its 1-px anti-aliased rim. So
  the box is a build-time fact read from a declared field, with no mask
  analysis needed. That `getSubscreen()` returns the same box at runtime
  is **UNVERIFIED** (no simulator, no watch), but the simulator draws its
  subscreen from this field. The box is **not** in the device reference
  (VERIFIED: `instinct2.json`'s attributes are size, shape, colours,
  touch, buttons and icon size only).
- The two round AMOLED Instincts have a `subscreen` key in
  `simulator.json` too, but it is a different thing: an `image` and
  overlays for the simulator's dial window, with no `location`
  (VERIFIED). A reader must key on `subscreen.location`, not on
  `subscreen`.
- It is a natural **anchor**. Placement is anchor-relative (ADR 0004 §2), so
  `at: { anchor: subscreen }` with a `%` relative to the subscreen box, not
  the screen, would let one design put its seconds or battery into the
  window on all eight devices. On a device without a subscreen it is a
  build-time fact, so the element can be an error or hidden per device.

## 5. Two-colour and fourteen-colour panels

The eight semi-octagons report `Display Colors: 2` (VERIFIED, reference).
They are monochrome MIP: black and one "on" colour. The four installed ones
declare it in `compiler.json`: `bitsPerPixel: 1` and
`palette: {colors: [000000, FFFFFF, TRANSPARENT, TRANSPARENT],
isResourcePalette: true}` (VERIFIED). That palette is what `monkeyc`
quantises resource bitmaps to, so the device files themselves name black
and white as the only two colours. The four semi-rounds and
`fr920xt` report 14 (VERIFIED). What the firmware does with any other colour
is **UNVERIFIED**: nearest-colour mapping, a luminance threshold or dithering
are all plausible, and the simulator cannot be run to find out (root
`CLAUDE.md` §3).

Consequences for the compiler (built, plan 20 slice 3):

- The reliable rule is **"only `#000000` and `#FFFFFF` are safe"**, which
  is true whatever the mapping is. `Color.is_palette_legal(2)` applies it,
  and any other colour is `palette-mono`, a suppressible warning naming
  the nearer of the two by contrast ratio (the crossover is relative
  luminance ≈ 0.179, `wfb.palette.MONO_CROSSOVER`).
- The preview's `quantise` step snaps a 2-colour device's image to black
  and white by the same rule, and `wfb preview` prints once that the
  mapping is a guess.
- 8- and 14-colour panels still have no rule, and are now reported "not
  checked" rather than passed silently.
- The contrast lint needs nothing new: it already measures the two colours
  it is given.

## 6. Designing for a shape: `overrides:` is already specified

A round design placed on a 320×360 rectangle is centred and correct, but
leaves the corners empty. A design meant for an Instinct needs to avoid the
subscreen. Both need **per-shape variation**, and ADR 0004 §4 already
specifies it:

```yaml
overrides:
  fenix8solar51mm: { at: { anchor: center, dy: -10% } }
  "shape:rectangle": { at: { anchor: top, dy: 8% } }
```

Selectors are a device id or a capability (`shape:`, `colors:`, `touch:`,
`api:`), capability selectors are preferred, overrides deep-merge, and an
unknown device id is a build error. Writing `overrides:` today is a friendly
"not implemented yet" error (`wfb/ir/builder/tree.py:51`, VERIFIED).

Why the build can absorb it cheaply: each device already gets its own
generated `source-<device>/Layout.mc` of resolved constants
(`wfb/emit/jungle.py:52`, `wfb/emit/monkeyc/layout_constants.py`,
VERIFIED). A geometry-only override (`at:`, `size:`, `radius:`, `align:`,
fonts measured per device) changes only those constants, so the shared view
code does not change at all. An override of `visible:`, `color:` or a
structural key would change the shared view and needs a per-device constant
or guard. That is a larger step, and should be the second step.

---

## 7. What stays open

1. **API levels** of the 14 face-capable non-round devices not installed
   (§1.1). Needs their device files; the installed seven are all above the
   floor.
2. **That `getSubscreen()` returns `simulator.json`'s box at runtime**
   (§4). Needs a simulator or a watch.
3. **How a 2-colour panel renders a non-black, non-white colour** (§5).
   Needs a simulator or a watch. Neither is available: the user owns no
   Instinct.
4. **Whether a rectangle AMOLED (`venusq2`, `venux1`) has the same AOD
   rules as round AMOLED.** The burn-in rules are fleet-wide in research 11
   §1, so probably yes. UNVERIFIED.

## 8. Recommendation

1. **Install the device files for the realistic 13** (5 rectangles, 8
   semi-octagons) and let the existing pipeline tell us what breaks. Done
   for 7 of them (§1): 3 rectangles and 4 semi-octagons.
2. **Rectangles next:** tests with a real rectangular device, preview and
   lint verified, and one example target. Nothing new in the format.
3. **Replace per-shape geometry with the skin mask** (§3) for the
   visible-area lint, the preview crop and the burn-in denominator. That
   single mechanism is what makes semi-octagons "checked". Done (§2).
4. **The `palette-mono` lint and 2-colour preview** (§5). Done.
5. **`overrides:` with `shape:` and device-id selectors, geometry keys
   only** (§6). This is the format change the user has to approve; ADR 0004
   already accepted its shape.
6. **`anchor: subscreen`** (§4), after 3–5.

Semi-round is not worth work unless §1.1 turns out wrong: every
semi-round device is very likely below the floor.
