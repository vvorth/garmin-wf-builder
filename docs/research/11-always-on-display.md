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

### 3.2 …but nothing reads the AMOLED API

**VERIFIED** by grep: `requiresBurnInProtection`, `getDisplayMode`,
`DISPLAY_MODE_*` and `onDisplayModeChanged` appear **nowhere** in `wfb/`,
`runtime-lib/` or any generated source — only in
`docs/research/probes/`. AOD is inferred purely from `onEnterSleep`.

That inference is approximately right (§1.1: the constrained frame is the
sleeping one) but it cannot distinguish `DISPLAY_MODE_OFF`, where the face
is drawing into a screen that is off, from real always-on.

### 3.3 `Device.is_amoled` decides exactly one thing

**VERIFIED.** Its only consumer is `supports_partial_update`
(`wfb/devices.py:133-135`), which in turn feeds the `partial-update` error.
Nothing else in the compiler branches on display technology: not layout, not
codegen, not the palette check, not lint beyond that one error.

### 3.4 There is no burn-in check of any kind

**VERIFIED.** `docs/limitations.md` and ADR 0006 §5 both list "the AMOLED
pixel/luminance estimate for `always_on`" as Phase 1.4 — unbuilt. `wfb/lint.py`
contains no luminance, pixel-count or burn-in check; its only
power-related check is `partial-update-budget`, which is MIP-specific (clip
area and operation count under `onPartialUpdate`).

So a design can declare `modes: [always_on]`, build warning-free, and light
60% of an AMOLED screen. Nothing would say a word.

### 3.5 `always_on` is emitted but unexercised

**VERIFIED.** No example under `examples/` and no fixture under
`tests/fixtures/` uses `always_on`; the 13 occurrences across `tests/` are
incidental (`test_hands_codegen.py`, `test_static.py`,
`test_semantics.py`). The path has never been driven by a real design, which
is consistent with §3.2 and §3.4 having gone unnoticed.

### 3.6 Two AMOLED devices are already vendored, and neither is installed

**VERIFIED.** `vendor/devices/` holds 20 devices, of which exactly two are
AMOLED: `fenix847mm` and `fenix947mm`, both `round-454x454`. Neither is
present in `~/.Garmin/ConnectIQ/Devices/`, so neither can be built for
today. `tools/setup-env.sh`'s device install is incremental (root
`CLAUDE.md` §2), so a re-run copies in just those.

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

- **No AMOLED build has been run.** Neither AMOLED device is installed
  (§3.6), so nothing in this document about how a generated AOD face
  *behaves* is verified on device or in the simulator.
- **The luminance rule's exact formula is unpublished.** Garmin says "less
  than 10% of the screen's luminance" without defining the integral,
  the colour space, or whether it is normalised against full white. A
  build-time check must therefore state a chosen formula and label its
  confidence, the way ADR 0008 requires.
- **The 3-minute static-pixel rule cannot be checked from one frame.** It is
  a property of a sequence of frames, so a single rendered AOD frame can
  only show the pixel/luminance rules; the shift guidance (§1.3) is what
  addresses it and it has no static check.
- **Whether `onEnterSleep` and `DISPLAY_MODE_LOW_POWER` ever disagree** on a
  real AMOLED device is unverified.

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

`wfb preview --asleep` already rasterises the real AOD frame to RGB at
device resolution (`wfb/preview.py:201`), with palette quantisation and the
round-bezel mask applied. Lit-pixel fraction and relative luminance are
therefore **measurable, not estimated** — the same stance ADR 0008 takes for
memory ("measured, not estimated") and the only honest way to check a rule
whose failure mode is the screen switching itself off.

Shape: for each AMOLED target, render the AOD frame, compute both metrics,
compare against the 10% rules, and report per-element the way
`partial-update-budget` does. A `--heatmap` render mirrors the simulator's
own tool for the cases §1.5 says are unreachable here.

**Caveat:** §5 — the luminance formula must be chosen and labelled, and the
3-minute rule stays uncheckable.

### E. Pixel shifting (the ≤4 px per minute jitter)

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

### F. Drive the AOD branch from the real API, not only `_sleeping`

Add the FAQ's ladder (§2) behind `wfb/availability.py` guards: skip drawing
entirely on `DISPLAY_MODE_OFF`, take the AOD branch on
`DISPLAY_MODE_LOW_POWER`, and keep `_sleeping` as the fallback for devices
without `getDisplayMode` — which is all three current targets. `AppBase.
onDisplayModeChanged` requests the update.

### G. Prerequisite: add an AMOLED target

Install `fenix847mm` (§3.6, one incremental `tools/setup-env.sh` re-run) and
give it an example face. Without it none of the above is verifiable, and the
AOD path stays exactly as unexercised as §3.5 found it — which is how §3.2
and §3.4 went unnoticed in the first place.

### Recommended sequence

**G → A + B → C → D → F**, with **E deferred**.

Rationale: G first, because a guard nobody has watched fail is not a guard
(root `CLAUDE.md` §7) and today nothing can fail. A + B are the format
change the goal asks for, and they are cheapest before `always_on` has any
users. C makes B's most valuable case nearly free by reusing machinery that
already exists. D is the check that makes an AOD design trustworthy, and it
is measured rather than estimated because the renderer is already there. F
removes the last guess from the runtime. E is a real requirement of §1.3 but
the largest diff and the least verifiable without a device, so it goes last.

The open question for the user, since A changes the format's shape (root
`CLAUDE.md` §7): **does `modes: [always_on]` change meaning (A), or does
`aod:` land alongside the existing opt-in set, leaving `always_on` as it is?**
