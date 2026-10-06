# Lints and suppression

`wfb validate` and `wfb build` run a linter against every target device. A
warning means the design might not look or behave as intended on that watch —
it never fails the build. Suppress an individual warning deliberately with
`lint: {allow: [...], reason: ...}` (on a `group`, it covers every member); a handful of checks reflect hard
platform limits and can never be suppressed. One check, `aod-burn-in`, is
the one deliberate exception to "an error always fails the build with no way
out" — see its own paragraph below.

## At a glance

Twenty-three codes are suppressible. One line each, derived from this chapter,
[`docs/limitations.md`](../limitations.md) §3 and `ts/src/lint.ts`'s own
messages; see `ts/src/lint.ts` if unsure.

| Code | Meaning |
|---|---|
| `palette-dither` | a declared colour an element draws isn't an exact MIP palette colour (each channel `00`/`55`/`AA`/`FF`) and dithers |
| `palette-mono` | on a 2-colour panel (the Instinct family), a declared colour an element draws is neither `#000000` nor `#FFFFFF`; how the watch shows it is unverified, and the warning names the nearer of the two |
| `safe-area` | the element's ink falls outside the screen's visible area: the inscribed circle on a round screen, and the simulator skin's visible area on any other shape (one pixel of tolerance) |
| `off-screen` | the element's box falls partly or fully outside the framebuffer |
| `text-overflow` | the rendered text is wider than its box |
| `contrast` | the element's colour against its backdrop is below the contrast threshold — for an `outline:`-bearing element, judged on the ring instead: against the element's own interior always, and against the backdrop when the interior does not read there (hollow text; a backdrop-coloured ring round something that reads is the gap idiom and passes); a `data` element's icon colour is judged too, a gauge's `track_color` is not |
| `partial-update-budget` | an element with `sleep_update: true` risks overrunning the partial-update budget, whose overrun is permanent: a wide clip, a known-expensive read, or a stamped `outline:` ring (4, 8 or 16 more draws each second at 1, 2 or 3px; a grown ring or a baked ring font is not reported) |
| `hold-overlap` | two elements' `on_hold:` regions overlap, so a touch in the shared area only ever reaches the first |
| `hold-unsupported` | the device has no `WatchFaceDelegate.onPress`, so this `on_hold:` can never fire there |
| `api-gated` | the element's binding names a source, symbol or complication type this device's API lacks; it reads as absent there |
| `dead-element` | the element's `visible:` condition reduces to a constant `false` |
| `graphics-pool` | the face's static buffers are a large share of the shared graphics pool (an estimate) |
| `antialias-dither` | antialiasing resolves to on for an element on a 64-colour device, dithering the soft edge |
| `static-overlap` | hoisting `static:` content to the front of draw order changed which element ends up on top |
| `config-unsupported` | the device has neither the on-device editor nor the settings menu (or lacks `Toybox.Complications`), so a config-driven colour or slot can't do what's declared |
| `duplicate-style` | two `config: style:` entries resolve to the same layout/colours and are indistinguishable on the wrist |
| `unreachable-layout` | a `layouts:` entry that no `config: style:` entry names as its `layout:`, so it can never be drawn |
| `sub-pixel-length` | a `%`/`%r` length resolves below 1 px on this device, with `min_1px:` off |
| `font-unavailable` | a `face:` font (or an element using one) with `unsupported: hide` fails to resolve a usable face on this device |
| `text-outline-interior` | an `outline:`-bearing element's (ring-grown) box overlaps an earlier-drawn element in a way that can't be shown to repaint it invisibly -- the interior pass paints over what's underneath, it does not reveal it |
| `aod-unreachable` | an element's own `aod:` (a `show` or an override) can never draw because an ancestor group already writes `aod: hide`, which is sticky |
| `aod-empty` | an AMOLED target where nothing in the design draws in always-on display |
| `override-unreachable` | an [`overrides:`](placement.md#per-device-and-per-shape-overrides) selector matches no device in this build, so it changes nothing |
| `aod-burn-in` | the rendered `--aod` frame -- masked, at its worst of 4 mask phases, unless `aod: {mask: false}` -- lights over 10% of pixels or 10% of luminance (Garmin's rule) at a sampled worst-case time; under the threshold this is an informational `note` instead, naming the same figures |

## Lint suppression

```yaml
lint:
  allow: [palette-dither]
  reason: "deliberate orange accent, matches the brand"
```

`reason` is required — a suppression without a stated reason is how linters get
disabled wholesale. Errors that reflect hard platform limits (missing glyphs,
`hold-auto-ambiguous`/`hold-auto-unresolved`, `api-gated-unguardable`) are
**not** suppressible: silencing one produces a face that does not work.
`off-screen` is not one of these — SDK 9.2.0's `Dc` documents no exception for
an out-of-range draw call, it clips silently the same way `setClip` does, so
drawing partly or fully off the framebuffer is a cropped design, not a broken
one, and the check is a warning like `safe-area`.

**`aod-burn-in` is the one suppressible check whose default severity is
`error`, not `warning`.** Every other error in this list reflects a hard
platform limit — code the generated app would crash on, or a manifest that
would not validate — where silencing the check would ship something that
simply does not work, so none of those are suppressible. Exceeding Garmin's
10% AOD rule is different in kind: it describes a policy the *watch's own
OS* enforces against a face that otherwise builds and runs correctly (worst
case, the system turns always-on off for the app), not anything wrong with
the generated code itself, so it follows the ordinary "acknowledge it, with
a reason" suppression path like every other measured/estimated check
instead of joining the hard-limit errors below.

Twenty-four codes are suppressible: `palette-dither`, `palette-mono`, `safe-area`, `off-screen`,
`text-overflow`, `contrast`, `partial-update-budget`, `hold-overlap`,
`hold-unsupported`, `api-gated`, `dead-element`, `graphics-pool`,
`antialias-dither`, `static-overlap`, `config-unsupported`,
`duplicate-style`, `unreachable-layout`, `sub-pixel-length`,
`text-outline-interior`, `aod-unreachable`, `aod-empty`, `aod-burn-in`,
`override-unreachable` and `font-unavailable` — a `face:` font, or an element using one, that has
`unsupported: hide` and fails to resolve a usable face on some target
device (["Vector (`face:`) fonts"](fonts.md#vector-face-fonts-device-resident-scalable-and-turnable)). Under the default
`error` instead, the same failure is a **hard build error and never
suppressible**: an author who wants leniency switches to `hide` outright
rather than silencing a face that will never draw.
`ts/src/lint.ts`'s `SUPPRESSIBLE` is
the normative list; check there if the two ever disagree. **A code that is not one of them is a
build error**, and the message distinguishes the two ways that happens — a code the compiler does not emit at all (with a "did you mean"
suggestion) versus a real code that is deliberately unsuppressible (with the
reason), so a typo is never mistaken for a check that refuses to be silenced.
**`off-screen` on an element also stands in for `safe-area` on it**: a box
outside the rectangular framebuffer is necessarily outside the visible disc
it contains too, so once an element's `lint: {allow: [off-screen], ...}`
acknowledges the crop, the geometry check does not also raise `safe-area`
for the same box — there is nothing further to acknowledge.

Five of them are not element-scoped diagnostics, so the allow goes on the
element that causes them: `palette-dither` on an element that draws
exactly that `color.<name>` (as its `color:`,
`track_color:`, `icon: {color:}`, a text's `outline: {color:}`, or an `aod:`
override's colour),
`partial-update-budget` on any element with `sleep_update: true`,
`graphics-pool` on any element inside a `static:` block,
`antialias-dither` on the first element (in document order) whose
`antialias:` resolves to `true` on a 64-colour device, and
`config-unsupported` on an element whose `color:`/`track_color:` is exactly
a role a `config:` axis or scheme binds (`color.accent`, `color.data`, a
scheme role), or a `data` element whose `slot:` is affected, and
`api-gated` on the element whose binding is actually gated -- the one whose
placeholder/`value:`/`color:`/etc. names the unavailable source path, whose
`on_hold:` names the type, or the `data` element whose slot's `default:`/
`choices:` is affected.
`duplicate-style` and `unreachable-layout` are design-, not element-scoped
either, but there is no element to hang either on at all: `duplicate-style`
goes on the **`config: style:` entry's own** `lint:` (the second entry of
the duplicate pair), and `unreachable-layout` on the **`layouts:` entry's
own** `lint:` -- neither is an element. `aod-empty` is the same shape, one
level up: it is about the whole face (nothing anywhere draws in AOD), so it
goes on the **face's own `aod:` block's** `lint:` --
`aod: {lint: {allow: [aod-empty], reason: ...}}`, beside `dim:`/`mask:`.
`aod-unreachable`, by contrast, is an ordinary element-scoped
diagnostic: it goes on the element whose own now-dead `aod:` it names.
`aod-burn-in` is element-scoped too, but not on a fixed element the way
`aod-unreachable` is: it goes on whichever AOD-shown element the rendered
worst-case frame actually lit the most pixels for (its own top-ranked
contributor, named in the message) — suppressing it there acknowledges the
element actually responsible, not any one of many the way
`graphics-pool`'s static content is.
`sub-pixel-length` is an ordinary element-scoped diagnostic like the rest
-- **except** that a finding about a hand or pattern **part** goes on the
part's **owning element**, the same element `min_1px:` inherits through
when the part declares none of its own: a part has no `lint:` block to
hang an `allow:` on.
`text-outline-interior` is reported on the `outline:`-bearing element
itself (the one whose interior pass might paint over something), never on
the earlier-drawn element(s) it may overlap. It does not fire on every
overlap: a specific earlier element is left out of the finding when it
provably repaints in the exact colour that's already there — the interior
colour and that element's own colour are the same build-time constant
(the same swatch, or otherwise equal after resolution; a role or anything
that stayed data-conditional can never prove this), **and** that element is
a filled `rectangle`/`circle`/`ellipse` whose own box fully contains the
outlined element's (ring-grown) box — not merely intersects it, since a
colour match with only a *partially* overlapping earlier element (a ring
that crosses just part of the box, say) proves nothing about what the
rest of the box sits on. The common case this quiets is the hollow-text
idiom itself: `color:` repeating the same swatch as the full-screen
background underneath it (`docs/guide/text.md`'s "hollow text" section).
`contrast` judges each element against what is actually behind it: the
last full-screen solid shape drawn before it in the same mode and the same
layout, or the palette swatch `bg` when there is none. So a night layout's text is
judged against the night background, not the day one. Shared content (no
layout) is on screen in every layout, so it is judged against each
layout's background, and a full-screen background shape is never judged
itself. A `data` element's icon colour is judged as well, and like a
glyph's own colour it may not simply match the backdrop. A gauge's
`track_color` is not judged: a track is meant to
recede behind the fill, so a dim one (`#555555` on black is a 2.8 ratio)
is the design, not a mistake. `contrast` also treats an `outline:`-bearing
element differently: it judges the ring against the element's own colour,
and against the backdrop only when that colour does not itself read there
([Outlines](outlines.md#cost-and-the-always-on-frame)); a hand or pattern
part is judged against its element's ring. On a `type: hands`/`type: pattern`
element, `contrast` is checked per **part**, not once for the whole
element -- a `HandsElement` has no `color:` of its own at all (every colour
lives on its hands' own parts) and a `PatternElement`'s `color:` is only
the default a part without its own override inherits -- named
`<id>.<hand>.parts[<i>]`/`<id>.parts[<i>]`, the same convention
`sub-pixel-length` already uses for a part-level finding, and suppressed
the same way: on the owning element, since a part has no `lint:` of its
own. A part whose colour exactly matches the backdrop is not warned about
(the same "deliberately blends in" exemption a primitive element gets),
**except** a `type: text` pattern part, where an exact match is ordinarily
invisible content by mistake rather than by design.
See `docs/limitations.md` 3.

## What gets checked

`wfb validate` and `wfb build` check the design against each device for:
- text overflow
- the round screen's safe area
- contrast
- palette and anti-aliasing dither
- the power cost of sleep updates

Two checks look across every target in the build at once, not one device at
a time: `font-unavailable` (above) and the `shared-view` note. One generated
view serves every target, so in a build with both AMOLED and MIP targets the
AMOLED always-on frame is compiled into the MIP targets too, where it never
runs. The note names them. It is informational, since their measured memory
already includes the cost, and there is nothing to suppress: build the MIP
targets on their own (`-d`) to leave the code out.

Each warning states how confident the check is. When a warning is intended,
keep the design and record why:

```yaml
lint:
  allow: [safe-area]
  reason: "hugs the bezel by design"
```
