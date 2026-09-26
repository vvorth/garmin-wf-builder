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

**None of these 21 is installed.** `vendor/devices/` holds 22 devices, all
round (VERIFIED, `ls vendor/devices`). So no code path for a non-round
screen has ever run against a real `compiler.json`, `simulator.json` or
`api.debug.xml`. The test suite has no rectangular or semi-shaped device
fixture either (VERIFIED, `grep` over `tests/`).

### 1.1 How much of the list is reachable at the 3.1.0 floor

The shared manifest floor is 3.1.0, and a device below it is a friendly
build error (`wfb.build.select_devices`, root `CLAUDE.md` 6e). API levels
live in each device's `compiler.json`, which is not installed for any of
these. The rows below are therefore **UNVERIFIED** until the files land,
and come from Garmin's public device pages plus the SDK's own "Since"
stamps:

- **Semi-round (4) and the three 205×148/148×205 rectangles plus `fr920xt`
  (4)** are 2014–2016 products. They are almost certainly Connect IQ 1.x/2.x
  devices, below the floor, and so already friendly errors. If so, only
  **5 rectangles and 8 semi-octagons are realistic targets.**
- **Semi-octagon** needs at least 3.3.0: `System.SCREEN_SHAPE_SEMI_OCTAGON`
  is "API Level 3.3.0" (`$CIQ_SDK/doc/Toybox/System.html`, VERIFIED), and
  `WatchUi.getSubscreen` is 3.2.7 (below).
- **`venusq`/`venusqm`/`venusq2`/`venusq2m`/`venux1`** are 2020–2025
  products, 3.x–5.x.

The first slice of the plan installs the files and replaces this section
with `compiler.json` facts.

---

## 2. What the compiler does per shape today

Read from the code. **VERIFIED.**

| Stage | `round` | `rectangle` | `semi-*` |
|---|---|---|---|
| `Device.shape` (`wfb/devices.py:224`) | read from `simulator.json` `display.shape` | same | same |
| Visible-area test (`wfb/layout.py` `inside_visible_area`) | inscribed circle minus `BEZEL_MARGIN` | the framebuffer | `None`, "not checked" |
| `safe_area()` | inscribed square | the framebuffer | `None` |
| `safe-area` lint (`wfb/lint.py:822–846`) | checked, shape-aware ink reach | framebuffer bounds (`off-screen`) | a "not checked" note |
| Preview mask (`wfb/preview.py:305`, `:404`) | round crop | none (full frame, correct) | none (**wrong**: shows pixels the bezel hides) |
| AOD burn-in denominator (`wfb/lint.py:1510`) | the disc | the framebuffer (correct) | the framebuffer ("not exactly the true visible area") |
| Palette legality (`wfb/palette.py` `is_palette_legal`) | 64-colour rule | 64-colour rule on 64-colour panels, else nothing | **nothing** on 2- or 14-colour panels |
| `%r` (`docs/guide/placement.md`) | minor radius | half the shorter side | half the shorter side |

So a rectangle is *designed* to work already. It is simply unexercised. The
semi-shapes are honestly refused as "not checked" rather than guessed, as
ADR 0004 §3 asks.

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
resolution, with no geometry to guess. For a semi-octagon it would also
show the subscreen window (§4) as a hole in the mask, if the skin draws it
that way: **UNVERIFIED** until an Instinct skin is installed.

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
  there. The API returns a *box*, and the visible part is a circle inscribed
  in it (**UNVERIFIED**: Garmin's product imagery, not the SDK).
- The box's coordinates differ per model. They are available at runtime
  and, if the skin has a hole there, at build time from the mask (§3). They
  are **not** in the device reference (VERIFIED: `instinct2.json`'s
  attributes are size, shape, colours, touch, buttons and icon size only).
- It is a natural **anchor**. Placement is anchor-relative (ADR 0004 §2), so
  `at: { anchor: subscreen }` with a `%` relative to the subscreen box, not
  the screen, would let one design put its seconds or battery into the
  window on all eight devices. On a device without a subscreen it is a
  build-time fact, so the element can be an error or hidden per device.

## 5. Two-colour and fourteen-colour panels

The eight semi-octagons report `Display Colors: 2` (VERIFIED, reference).
They are monochrome MIP: black and one "on" colour. The four semi-rounds and
`fr920xt` report 14 (VERIFIED). What the firmware does with any other colour
is **UNVERIFIED**: nearest-colour mapping, a luminance threshold or dithering
are all plausible, and the simulator cannot be run to find out (root
`CLAUDE.md` §3).

Consequences for the compiler:

- `Color.is_palette_legal` accepts every colour on a panel that is not
  64-colour, deliberately: "no rule for any other palette size is guessed
  at" (`wfb/palette.py`). On a 2-colour panel, a design that is fine on a
  fēnix can therefore turn into an unreadable blob with no warning.
- The first reliable rule is **"only `#000000` and `#FFFFFF` are safe"**,
  which is certainly true whatever the mapping is. That makes a new
  per-device palette lint, `palette-mono`, with a clear "use black or white"
  fix. The preview's `quantise` step should then snap to those two, by
  luminance, and say it is guessing.
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

1. **API levels** of all 21 devices (§1.1). Needs the device files.
2. **The subscreen's shape and whether the skin shows it as a hole** (§3,
   §4). Needs an Instinct skin.
3. **How a 2-colour panel renders a non-black, non-white colour** (§5).
   Needs a simulator or a watch. Neither is available: the user owns no
   Instinct.
4. **Whether a rectangle AMOLED (`venusq2`, `venux1`) has the same AOD
   rules as round AMOLED.** The burn-in rules are fleet-wide in research 11
   §1, so probably yes. UNVERIFIED.

## 8. Recommendation

1. **Install the device files for the realistic 13** (5 rectangles, 8
   semi-octagons) and let the existing pipeline tell us what breaks. This
   costs nothing but the user copying files. It turns §1.1 into facts, and
   is the cheapest way to find rectangle bugs.
2. **Rectangles next:** tests with a real rectangular device, preview and
   lint verified, and one example target. Nothing new in the format.
3. **Replace per-shape geometry with the skin mask** (§3) for the
   visible-area lint, the preview crop and the burn-in denominator. That
   single mechanism is what makes semi-octagons "checked".
4. **The `palette-mono` lint and 2-colour preview** (§5).
5. **`overrides:` with `shape:` and device-id selectors, geometry keys
   only** (§6). This is the format change the user has to approve; ADR 0004
   already accepted its shape.
6. **`anchor: subscreen`** (§4), after 3–5.

Semi-round is not worth work unless §1.1 turns out wrong: every
semi-round device is very likely below the floor.
