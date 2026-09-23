# 11 — Always-on display (AMOLED): the rules, what this compiler already has, and how to close the gap

Written in answer to "how should AOD be implemented here, preferring a
per-element modifier on the existing design over a second hand-built
layout". Covers what Garmin actually requires of an always-on watch face,
which symbols exist on which devices, what `modes: [always_on]` already does
in this repository, where it falls short of the AMOLED rules, and a set of
implementation options with a recommendation (§6).

Every behavioural claim is marked **VERIFIED** (checked against the SDK
files or this repository's own sources on disk) or **UNVERIFIED** (plausible
but not checked), per `docs/CLAUDE.md`. No AMOLED device has been built for
or run at the time of writing — §5 says what that leaves unproven.

---

## 1. Garmin's rules for an always-on face

**VERIFIED**, read from
`$CIQ_SDK/doc/docs/Connect_IQ_FAQ/How_Do_I_Make_a_Watch_Face_for_AMOLED_Products.html`
(API level 3.1.0 and later) and
`$CIQ_SDK/doc/docs/User_Experience_Guidelines/Watch_Faces.html`.

### 1.1 What counts as "on", and when the rules apply

> Pixels in an AMOLED display only draw power when illuminated, so a pixel
> is considered on when rendering any color other than black, and is
> considered off when and only when rendering black pixel.

> Burn-in protection is only activated when Connect IQ watch face is in
> foreground and after system enters sleep mode.

So the constrained frame is exactly the sleeping `onUpdate` frame — the same
frame this compiler already calls `always_on` — and "cost" is measured in
lit pixels, with **black being free**.

### 1.2 The two numeric rules, which differ by device generation

| Device generation | Rule | Source |
|---|---|---|
| Original Venu | **>10% of screen pixels on, or any pixel on longer than 3 minutes → the system shuts the screen off** | FAQ, "What Qualifies as Burn-In" |
| Venu 2 and later | **less than 10% of the screen's *luminance*** | FAQ, "How to Create Always-On Watch Faces" |

The FAQ's own words for the newer rule: "Since the Venu® 2, the rule for
always-on is to use less than 10% of the screen's luminance." The older rule
is a pixel count; the newer one is a luminance integral, so a design can
satisfy one and not the other. A build-time check must know which applies
(§3.4).

The UX guidelines restate the constraint from the other side: "When the
watch face enters always-on mode, the watch face will only update every
minute, and each update is limited to using 10% of the available pixels of
the display."

### 1.3 Garmin's design guidance, verbatim

From `User_Experience_Guidelines/Watch_Faces.html`, "Best Practices":

> - Avoid using much white or blue. Consider using light gray instead.
> - Use fonts with thin line weights.
> - Minimize the use of static elements that never move (e.g., the center
>   post of analog watch hands).
> - If you do have static elements, consider moving elements up to four
>   pixels in any direction every minute while in always-on mode.

The FAQ adds the same three ideas in prose: "drawing the time with a thin
font, shifting the time every minute as not to repeatedly leave the same
pixels on, and not having static tick marks that leave the same pixels on."

The guidelines also state the expectation directly: "Many AMOLED devices
have a setting to disable the gesture that returns the watch face to high
power mode… it is expected that Connect IQ watch faces for AMOLED devices
support always-on mode." An AMOLED target without an AOD path is a
user-visible defect, not an optional extra.

### 1.4 There is no outline-text API

**VERIFIED** by enumerating every `Dc` draw entry in `bin/api.debug.xml`:
`drawText`, `drawAngledText` and `drawRadialText` fill glyphs with one
colour and nothing else. There is no stroke width, outline or text-border
parameter anywhere on them, and the FAQ and guidelines both say "thin font",
never "outline".

The one near-miss is **`Dc.setStroke` (since 4.0.0, present on both the MIP
and AMOLED devices here)**, which despite the name is not a text outline: it
sets the *draw tool* — a `BitmapTexture` or a `0xAARRGGBB` colour — used by
drawing primitives, taking precedence over `setColor()`. Its alpha channel
is interesting for AOD in its own right (see option C), but only on AMOLED,
where `alphaBlendingSupport` is true (§3.7).

Vector fonts do not change this. Garmin's text engine *does* have an
outlined-glyph mode on its TrueType path: a fixed 2 px FreeType stroke, drawn
as a ring in the fill colour under the glyph. But the mode is keyed on the font
record, and nothing a Connect IQ app passes in can set it. The evidence and
the workarounds are in `docs/research/13-outline-vector-text.md`.

Consequently "draw only the outline of the font" is **not implementable as a
draw-time switch**. The two things that *are* implementable here:

1. **A thin-weight font for AOD.** `wfb/fonts/` bakes TTF → BMFont already,
   so an AOD font is one more bake of a lighter weight. Its cost is a second
   glyph set in the 128 KB app budget, nothing else.
2. **A hollow look**, only by baking an outline-style TTF (one whose glyphs
   are drawn as outlines in the typeface itself) as its own font.

A custom bitmap font is single-channel grayscale — one colour per glyph
(`docs/limitations.md`, "Single-colour bitmap fonts") — so a two-tone
"outline plus fill" needs two fonts overlaid, which is the opposite of the
goal: it lights *more* pixels.

### 1.5 Testing

The simulator ships a burn-in simulation: **File → View Screen Heat Map**,
which runs a simulated 24-hour period in minutes. The FAQ notes the menu
item "is only enabled when simulating a WatchFace on a device that supports
screen protection". **UNVERIFIED here**: the simulator does not survive
`monkeydo` in any environment tried in this project (root `CLAUDE.md` §3), so
this tool is reachable only on the user's host.

---

## 2. The API, and which devices have it

**VERIFIED** against `$CIQ_SDK/bin/api.debug.xml` and the per-device symbol
tables under `vendor/devices/<id>/<id>.api.debug.xml` — per-device, never by
API level (root `CLAUDE.md` constraint 6).

| Symbol | Parent | Notes |
|---|---|---|
| `getDisplayMode()` | `System` | returns `DISPLAY_MODE_HIGH_POWER` / `DISPLAY_MODE_LOW_POWER` / `DISPLAY_MODE_OFF` |
| `DISPLAY_MODE_*` | `System` | three fields |
| `requiresBurnInProtection` | `System.DeviceSettings` | the original-Venu rule's detector |
| `onDisplayModeChanged()` | `Application.AppBase` | since 5.0.0; documented "only available in AMOLED or LCD screen products" |

Per-device availability, counted directly in each device's own symbol table:

| Device | `displayType` | `getDisplayMode` | `DISPLAY_MODE_*` | `onDisplayModeChanged` | `requiresBurnInProtection` |
|---|---|---|---|---|---|
| `fenix847mm` | amoled | yes | yes | yes | yes |
| `fenix947mm` | amoled | yes | yes | yes | yes |
| `fenix8solar47mm` | mip | **no** | **no** | **no** | yes |
| `fr955` | mip | **no** | **no** | **no** | yes |

This split is exactly what `wfb/availability.py` exists for: the shared
generated view is one file across every target, `monkeyc` checks the
SDK-wide API rather than the device's (constraint 6d), and only a `has`
guard keeps a MIP target from executing a symbol it does not have.

The FAQ's own recommended shape is a three-way ladder — `DeviceSettings has
:requiresBurnInProtection`, then `System has :getDisplayMode`, then the
mode switch — with a plain MIP render as the outermost fallback.

---

## 3. What this repository already has

### 3.1 The mode axis exists and is wired end to end

**VERIFIED** by reading the sources:

| Fact | Where |
|---|---|
| `MODES = ("active", "low_power", "always_on")` | `wfb/ir/model.py:24` |
| `modes:` defaults to `("active",)` per element | `wfb/ir/builder.py:1752` |
| `onUpdate` emits `if (_sleeping) { always_on set } else { active set }` | `wfb/emit/monkeyc/view.py:247`, `:830` |
| `_sleeping` is set only by `onEnterSleep`/`onExitSleep` | `wfb/emit/monkeyc/view.py:945` (`_emit_sleep_hooks`) |
| `wfb preview --asleep` renders the `always_on` frame host-side, at device resolution | `wfb/preview.py:201` |
| `Device.is_amoled` | `wfb/devices.py:129` |
| AMOLED + a `low_power` element → hard error, note pointing at `always_on` | `wfb/lint.py:1175` |

`_sleeping` is shared by two independent reasons — `always_on` membership
and an `awake`-only second hand — documented in ADR 0006 §5's 2026-09-14
note and in `view.py:247`'s comment.

**Superseded 2026-09-23 (plan 14 slice 1):** `always_on` was removed from
`modes:` outright (D3; `always_on` in `modes:` is now a schema error naming
`aod:`), and every row of the table above describes the pre-slice-1 shape.
`onUpdate` now branches on a new `_aod` field instead (true while
`_sleeping` **and** the device requires burn-in protection), the resolved
`aod:` set replaces `always_on` membership, `wfb preview --aod` replaces
that half of `--asleep` (which still exists, narrowed to just hiding an
`awake`-only second hand), and the AMOLED+`low_power` hard error now points
at `aod:`. See `docs/guide/always-on-display.md` and plan 14 §3-§4.

### 3.2 …but nothing reads the AMOLED API

**VERIFIED** by grep: `requiresBurnInProtection`, `getDisplayMode`,
`DISPLAY_MODE_*` and `onDisplayModeChanged` appear **nowhere** in `wfb/`,
`runtime-lib/` or any generated source — only in
`docs/research/probes/`. AOD is inferred purely from `onEnterSleep`.

That inference is approximately right (§1.1: the constrained frame is the
sleeping one) but it cannot distinguish `DISPLAY_MODE_OFF`, where the face
is drawing into a screen that is off, from real always-on.

**Superseded 2026-09-23 (plan 14 slice 1):** this is no longer true.
`System.getDeviceSettings().requiresBurnInProtection` is now read, once per
sleep/wake transition, guarded by `Device.has_field` per D1
(`wfb/emit/monkeyc/view.py`'s `_emit_sleep_hooks`, `wfb/availability.py`'s
`Guards.burn_in_field_guarded`) -- but only `requiresBurnInProtection`;
`getDisplayMode`/`DISPLAY_MODE_*`/`onDisplayModeChanged` (§6 option F) are
still unread, so the `DISPLAY_MODE_OFF` distinction this paragraph names
remains open.

**Superseded again 2026-09-23 (plan 14 slice 6, §6 option F):** the
`DISPLAY_MODE_OFF` distinction is closed. `System.getDisplayMode()` is now
read at the top of the AOD frame, on a device that has the symbol
(`has`-guarded per device when some target lacks it, `wfb.availability.
Guards.display_mode_guarded`, mirroring `burn_in_field_guarded`); a result
of `DISPLAY_MODE_OFF` returns before any drawing, including the frame's own
black clear. `DISPLAY_MODE_*`'s three constants are read too (as the
comparison's own right-hand side); `Application.AppBase.onDisplayModeChanged`
is still unread, by deliberate choice, not an oversight -- see ADR 0006's
2026-09-23 amendment for why (`WatchFace.onUpdate` already runs once a
minute while asleep regardless of display mode, so the callback would only
shave a worst-case one-minute latency on a mode transition, at the cost of
one more per-device symbol question). `docs/guide/always-on-display.md`
"The `getDisplayMode` ladder" is the author-facing description.

### 3.3 `Device.is_amoled` decides exactly one thing

**VERIFIED.** Its only consumer is `supports_partial_update`
(`wfb/devices.py:133-135`), which in turn feeds the `partial-update` error.
Nothing else in the compiler branches on display technology: not layout, not
codegen, not the palette check, not lint beyond that one error.

**Superseded 2026-09-23 (plan 14 slice 1):** `Device.is_amoled` gained a
second consumer, `wfb.availability.compute_guards`'s `amoled_target`
(`any(device.is_amoled for device in devices)`), the build-time half of
D1: it decides whether the shared view carries `_aod`/its sleep-hook
plumbing/its `onUpdate` branch at all, and is the byte-identical guarantee
for an all-MIP build (§4.1's own test, `tests/test_aod.py`).

### 3.4 The burn-in check: built, plan 14 slice 4 (2026-09-23)

**Superseded.** `wfb/lint.py`'s `check_aod_burn_in` (code `aod-burn-in`,
ADR 0008 check 8) now exists. It renders the resolved `aod:` set through
`wfb.preview.render` -- the same function `wfb preview --aod` uses, no
second renderer -- at a sampled worst-case frame (`10:08`/`20:08`, full
battery, `wfb.preview.SAMPLE`'s other defaults unchanged; see §1.5/§5
below for why sampling rather than every minute) and scores, over the
round-masked display area:

- **lit-pixel fraction**: the share of pixels that are not pure black,
  matching §1.1's own quoted definition exactly ("a pixel is considered on
  when rendering any color other than black") -- not a brightness
  threshold of this compiler's own invention.
- **luminance fraction**: the mean relative luminance across the same
  pixels (`wfb.palette.Color.relative_luminance`, Rec. 709 primaries over
  sRGB-decoded channels -- the same WCAG-style formula the contrast lint
  already used), as a fraction of full white. Garmin's own integral is
  still unpublished (§5 below), so this is a stated, reused choice, not a
  claim of matching Garmin's firmware.

§1.2's two device-generation rules (original Venu: lit-pixel count; Venu 2+:
luminance) are both checked at once, since neither `compiler.json` nor
`simulator.json` records which generation a target device is -- exceeding
either fraction is the finding, which can only ever be as strict as, never
looser than, whichever single rule actually applies to a given panel.
Reported per element (§6 D's own goal): every AOD-shown element is
re-rendered alone and ranked by its own lit-pixel count, and the
diagnostic is anchored at the biggest contributor's own source line. Over
10% is `error`, code `aod-burn-in` -- deliberately suppressible, unlike
this project's other AMOLED hard error, since exceeding it breaks nothing
the compiler emits (ADR 0008's amendment has the full reasoning). Under
10% is a `note` stating both figures.

So a design that writes `aod: show` everywhere and would have lit 60% of
an AMOLED screen now fails the build with that exact figure instead of
shipping silently -- the gap this section used to describe is closed. What
is *not* closed, when the mask is off (`aod: {mask: false}`): the 3-minute
static-pixel rule (§1.2, §5) is a property of a sequence of frames, and
this renders exactly one (or two, at two sampled times). `wfb preview
--heatmap` approximates it over a day. **With the mask on (the default),
the rule holds by construction** -- the mitigation slice 5's jitter once
aimed for, and research 15's pixel masks then compared, is built as
`aod: {mask: ...}` (plan 16), and this lint scores the masked frame at its
worst of four phases (`docs/guide/lints.md`, `docs/research/
15-aod-pixel-masks.md` §7).

### 3.5 `always_on` was emitted but unexercised; now has one caller

**VERIFIED** at the time of writing: no example under `examples/` and no
fixture under `tests/fixtures/` used `always_on`; the 13 occurrences across
`tests/` were incidental (`test_hands_codegen.py`, `test_static.py`,
`test_semantics.py`). The path had never been driven by a real design,
consistent with §3.2 and §3.4 having gone unnoticed. **Since plan 14 slice 0
(2026-09-23)**, `examples/features/aod/face.yaml` puts the digital clock in
`modes: [active, always_on]`, so the path had one real caller, on all
four of that example's targets including `fenix847mm`; no AMOLED-specific
codegen existed yet at that point (slice 2 is still the restyling work),
so it was still §4's gap, not a fix for it.

**Superseded 2026-09-23 (plan 14 slice 1):** `always_on` was removed
outright (D3) and `examples/features/aod/face.yaml` now uses `aod: {color:
...}` on the clock instead, with a face-wide `aod: {default: hide}`. The
`_aod` gate this section's gap named is now built (moved up from plan 14
§4.1 into slice 1) -- see §3.1/§3.3's own superseded notes above.

### 3.6 Two AMOLED devices are vendored; `fenix847mm` is now installed

**VERIFIED.** `vendor/devices/` holds 20 devices, of which exactly two are
AMOLED: `fenix847mm` and `fenix947mm`, both `round-454x454`. Neither was
present in `~/.Garmin/ConnectIQ/Devices/` at the time of writing. Plan 14
slice 0 (2026-09-23) re-ran `tools/setup-env.sh` — incremental (root
`CLAUDE.md` §2) — which installed `fenix847mm` (and, in the same pass,
every other not-yet-installed vendored device, `fenix947mm` included).
`fenix847mm` now has a build: `examples/features/aod/face.yaml`,
warning-free, 2,061 B of its 131,072 B watch-face limit (1.6%).

### 3.7 Three MIP constraints do not hold on those AMOLED devices

**VERIFIED** from `vendor/devices/fenix847mm/compiler.json`:

| Field | `fenix847mm` (amoled) | `fenix8solar47mm` (mip) |
|---|---|---|
| `alphaBlendingSupport` | **`true`** | `false` |
| `bitsPerPixel` | **16** | 8 (64-colour panel) |
| `enhancedGraphicSupport` | `true` | — |
| `deviceFamily` | `round-454x454` | `round-260x260` |
| `watchFace` `memoryLimit` | 131 072 | 131 072 |

Root `CLAUDE.md` constraint 10 (no transparency) and constraint 13 (the
64-colour `00`/`55`/`AA`/`FF` palette rule) are therefore **MIP-only facts**,
not platform facts. The memory budget is unchanged at 128 KB, but the screen
is 454² against 260² — 3.05× the pixels — which matters for any full-screen
buffer (§4, option E2).

---

## 4. The gap, stated plainly

Today's `always_on` is a **second element set you opt into**: `modes:`
defaults to `("active",)` (`builder.py:1752`), so the AOD set starts empty
and every element that should appear must be re-declared into it. And there
is no per-element styling delta anywhere in the model — `Element` carries
`modes`, `visible`, `static`, `layout`, colours and geometry, but nothing
that varies *by mode*. Whatever is declared into `always_on` draws with
identical colours, fonts and pen widths to the awake frame.

That is precisely the "build a whole new layout and call it AOD" shape, and
it fails §1 on its own terms: the compiler offers no way to express any of
Garmin's four pieces of guidance (§1.3) except by hiding elements outright.

---

## 5. What is not proven here

- **No AMOLED build has been run on device or in the simulator.**
  `fenix847mm` is now installed and has a `monkeyc` build (§3.6), but that
  is a host-side compile only — nothing in this document about how a
  generated AOD face *behaves* is verified on a real panel or in the
  simulator (root `CLAUDE.md` §3: the simulator does not survive
  `monkeydo` in this project).
- **The luminance rule's exact formula is unpublished.** Garmin says "less
  than 10% of the screen's luminance" without defining the integral,
  the colour space, or whether it is normalised against full white. A
  build-time check must therefore state a chosen formula and label its
  confidence, the way ADR 0008 requires -- done, plan 14 slice 4 (§3.4):
  `wfb.palette.Color.relative_luminance` (Rec. 709/WCAG over sRGB-decoded
  channels), labelled `estimate` on the diagnostic, since it is this
  compiler's own reused choice, not Garmin's actual formula.
- **The 3-minute static-pixel rule cannot be checked from one frame.** It is
  a property of a sequence of frames, so a single rendered AOD frame can
  only show the pixel/luminance rules; the shift guidance (§1.3) is what
  addresses it and it has no static check.
- **Whether `onEnterSleep` and `DISPLAY_MODE_LOW_POWER` ever disagree** on a
  real AMOLED device is unverified. Plan 14 slice 6 (§6 F) added a
  `DISPLAY_MODE_OFF` check *inside* the window `onEnterSleep`'s own
  `requiresBurnInProtection` read already opens -- it narrows that window,
  it does not answer whether the window's own edges (`onEnterSleep`/
  `onExitSleep` firing) ever land at a different moment than a
  `DISPLAY_MODE_LOW_POWER`/`_HIGH_POWER` transition would. This is now
  recorded in `docs/limitations.md` §3 as well, alongside every other AOD
  claim this project cannot verify without real AMOLED hardware.

---

## 6. Options, and the recommendation

These are composable axes, not rival designs. A/B/C are the format change;
D is the guard; F is correctness; E and G are supporting work.

### A. Invert membership: AOD derives from the active set

`always_on` stops being a set to opt into and becomes *the active set, minus
what is marked off, plus per-element overrides*. This is a format-visible
semantic change to `modes: [always_on]` — but §3.5 says no example, fixture
or user design uses it, so the migration cost is close to zero, and it will
never be cheaper than now.

**For:** one design, not two; the AOD frame cannot silently drift from the
awake one; matches the stated goal.
**Against:** changes the meaning of an already-published (if unused) format
key; needs a face-level default policy (`show` or `hide`) that authors must
learn.

### B. A per-element and per-group `aod:` modifier

```yaml
aod: hide                                             # drop it in AOD
aod: {color: "#555555", font: clock_thin, width: 1}   # or restyle it
```

Group inheritance follows the existing `visible:` push-down precedent
(`Builder._push_visible`): a group emits no draw method, so the subtree must
be walked while it is still a tree (`wfb/ir/model.py`'s `visible`
docstring). This is the mechanism A needs, and it is the direct expression
of Garmin's guidance: thin font, grey instead of white, thinner pen.

**Codegen choice, to be measured not assumed:** a second method variant per
overridden element (costs code memory) against an `aod as Boolean` parameter
(costs a branch per draw call). Both fit the existing one-method-per-element
shape (`view.py`'s `_emit_element_method`).

### C. Carry the overrides on the existing colour-role indirection

`color_scheme:` plus `config.colors.<role>` already swaps colour roles at
runtime through the generated `applyConfig`. A reserved AOD scheme that
takes over while `_sleeping` delivers "avoid white and blue, use light grey"
across a whole face with almost no new machinery, and leaves element draw
methods byte-identical.

**For:** cheapest possible version of the most valuable single rule.
**Against:** colours only — no hiding, no geometry, no font swap. It
complements B rather than replacing it.

**A variant worth measuring:** on AMOLED, `alphaBlendingSupport` is true
(§3.7) and `Dc.setStroke` takes a `0xAARRGGBB` draw tool (§1.4), so an AOD
scheme could be expressed as *an alpha applied to the awake colours* rather
than a second set of hand-picked greys — one number per face instead of one
colour per role. **UNVERIFIED**: whether the burn-in meter measures the
blended result (which is what reaches the panel, so it should) has not been
checked, and this is AMOLED-only by construction.

### D. A measured burn-in lint, built on the host renderer

`wfb preview --aod` (plan 14 slice 1; this option originally named
`--asleep`, since renarrowed to a plain "hide the second hand" flag) already
rasterises the real AOD frame to RGB at device resolution
(`wfb/preview.py`), with palette quantisation and the round-bezel mask
applied. Lit-pixel fraction and relative luminance are
therefore **measurable, not estimated** — the same stance ADR 0008 takes for
memory ("measured, not estimated") and the only honest way to check a rule
whose failure mode is the screen switching itself off.

Shape: for each AMOLED target, render the AOD frame, compute both metrics,
compare against the 10% rules, and report per-element the way
`partial-update-budget` does. A `--heatmap` render mirrors the simulator's
own tool for the cases §1.5 says are unreachable here.

**Caveat:** §5 — the luminance formula must be chosen and labelled, and the
3-minute rule stays uncheckable.

### E. Pixel shifting (the ≤4 px per minute jitter) — built as plan 14 slice 5, removed 2026-09-23

Option 1 below shipped and was then removed to cut codegen complexity. The
replacement is built: `aod: {mask: ...}`, a moving 2×2 pixel mask (plan 16,
research 15 §7), on by default. The analysis below is kept as the record of
the options that were not taken.

Layout coordinates are compile-time constants in `Layout.mc` and draw calls
reference them directly (`wfb/emit/monkeyc/layout_constants.py`), so a shift
is not free. Three ways:

1. **Offset arguments on the AOD path** — emit `Layout.FOO_X + _aodDx`.
   Touches every emitter; costs no memory.
2. **Draw the AOD frame into a `BufferedBitmap` and blit it at `(dx, dy)`** —
   one place, reusing the static-buffer machinery (`view.py:363`), and the
   graphics pool is separate from the 128 KB (constraint 11). But a 454×454
   surface at 16 bpp is ≈412 KB of the 1 MB pool (**UNVERIFIED**: the
   per-surface overhead the pool adds is undocumented — see
   `wfb/devices.py:169`'s note), and the frame changes every minute anyway.
3. **Per-element opt-in** — only elements marked shiftable take an offset.

**Recommendation: defer.** It is the one piece that does not pay for itself
until a real AMOLED design is on a wrist, and E1 is a large mechanical diff
through every emitter.

### F. Drive the AOD branch from the real API, not only `_sleeping` — **built, plan 14 slice 6**

Add the FAQ's ladder (§2) behind `wfb/availability.py` guards: skip drawing
entirely on `DISPLAY_MODE_OFF`, take the AOD branch on
`DISPLAY_MODE_LOW_POWER`, and keep `_sleeping` as the fallback for devices
without `getDisplayMode` — which is all three MIP verification targets.

**Built almost exactly as described**, with one deliberate narrowing:
`System.getDisplayMode()` is read at the top of `_emit_aod_body`, guarded by
`System has :getDisplayMode` on any build where some target lacks the
symbol (`wfb.availability.Guards.display_mode_guarded`, computed the same
way as `burn_in_field_guarded`); `DISPLAY_MODE_OFF` returns immediately,
before the frame's own black clear (nothing an off panel could show is
worth even that); `DISPLAY_MODE_LOW_POWER` needed no new branch at all --
it is exactly the AOD frame this project already draws while `_aod`, so the
ladder is one early exit added to the existing path, not a second path.
**Not built:** `AppBase.onDisplayModeChanged` requesting an update on a
mode change -- a deliberate choice, not an oversight (ADR 0006's
2026-09-23 amendment has the full reasoning): `WatchFace.onUpdate` already
runs once a minute while asleep regardless of which display mode that
minute lands in, so the callback would only shave a worst-case one-minute
latency off a transition away from `DISPLAY_MODE_OFF`, at the cost of one
more per-device symbol question for unproven benefit. `docs/guide/
always-on-display.md` "The `getDisplayMode` ladder" is the author-facing
description; `tests/test_aod.py`'s slice-6 tests are the coverage.

### G. Prerequisite: add an AMOLED target

Install `fenix847mm` (§3.6, one incremental `tools/setup-env.sh` re-run) and
give it an example face. Without it none of the above is verifiable, and the
AOD path stays exactly as unexercised as §3.5 found it — which is how §3.2
and §3.4 went unnoticed in the first place.

### Recommended sequence

**G → A + B → C → D → F**, all built (plan 14 slices 0-4 and 6).

Rationale: G first, because a guard nobody has watched fail is not a guard
(root `CLAUDE.md` §7) and today nothing can fail. A + B are the format
change the goal asks for, and they are cheapest before `always_on` has any
users. C makes B's most valuable case nearly free by reusing machinery that
already exists. D is the check that makes an AOD design trustworthy, and it
is measured rather than estimated because the renderer is already there. F,
removing the last guess from the runtime, landed as slice 6, closing plan 14
out. E (jitter) landed as slice 5 and was removed again on 2026-09-23 to cut
codegen complexity; its replacement, `aod: {mask: ...}` (research 15,
plan 16), shipped the same day.

The question A posed the user -- does `modes: [always_on]` change meaning,
or does `aod:` land alongside the existing opt-in set -- was answered by a
third option neither A nor the question anticipated: `aod:` *replaces*
`modes: [always_on]` outright (plan 14 D3, ADR 0006's 2026-09-23
amendment).
