# Lints and suppression

`wfb validate` and `wfb build` run a linter against every target device. A
warning means the design might not look or behave as intended on that watch —
it never fails the build. Suppress an individual warning deliberately with
`lint: {allow: [...], reason: ...}`; a handful of checks reflect hard
platform limits and can never be suppressed.

## At a glance

Eighteen codes are suppressible. One line each, derived from this chapter,
[`docs/limitations.md`](../limitations.md) §3 and `wfb/lint.py`'s own
messages; see `wfb/lint.py` if unsure.

| Code | Meaning |
|---|---|
| `palette-dither` | a `color:`/`track_color:` isn't an exact MIP palette colour (each channel `00`/`55`/`AA`/`FF`) and dithers |
| `safe-area` | the element's box falls outside the round screen's visible area |
| `off-screen` | the element's box falls partly or fully outside the framebuffer |
| `text-overflow` | the rendered text is wider than its box |
| `contrast` | the element's colour against its backdrop is below the contrast threshold |
| `partial-update-budget` | an element drawn in `low_power` mode risks overrunning the partial-update budget, whose overrun is permanent |
| `hold-overlap` | two elements' `on_hold:` regions overlap, so a touch in the shared area only ever reaches the first |
| `hold-unsupported` | the device has no `WatchFaceDelegate.onPress`, so this `on_hold:` can never fire there |
| `api-gated` | the element's binding names a source, symbol or complication type this device's API lacks; it reads as absent there |
| `dead-element` | the element's `visible:` condition reduces to a constant `false` |
| `graphics-pool` | the face's static buffers are a large share of the shared graphics pool (an estimate) |
| `antialias-dither` | antialiasing resolves to on for an element on a 64-colour device, dithering the soft edge |
| `static-overlap` | hoisting `static:` content to the front of draw order changed which element ends up on top |
| `config-unsupported` | the device lacks the on-device editor (or `Toybox.Complications`), so a config-driven colour or slot can't do what's declared |
| `duplicate-style` | two `config: style:` entries resolve to the same layout/colours and are indistinguishable on the wrist |
| `unreachable-layout` | a `layouts:` entry that no `config: style:` entry names as its `layout:`, so it can never be drawn |
| `sub-pixel-length` | a `%`/`%r` length resolves below 1 px on this device, with `min_1px:` off |
| `font-unavailable` | a `face:` font (or an element using one) with `if_unavailable: hide` fails to resolve a usable face on this device |

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

Eighteen codes are suppressible: `palette-dither`, `safe-area`, `off-screen`,
`text-overflow`, `contrast`, `partial-update-budget`, `hold-overlap`,
`hold-unsupported`, `api-gated`, `dead-element`, `graphics-pool`,
`antialias-dither`, `static-overlap`, `config-unsupported`,
`duplicate-style`, `unreachable-layout`, `sub-pixel-length` and
`font-unavailable` — a `face:` font, or an element using one, that has
`if_unavailable: hide` and fails to resolve a usable face on some target
device (["Vector (`face:`) fonts"](fonts.md#vector-face-fonts-device-resident-scalable-and-turnable)). Under the default
`error` instead, the same failure is a **hard build error and never
suppressible**: an author who wants leniency switches to `hide` outright
rather than silencing a face that will never draw.
`wfb/lint.py`'s `SUPPRESSIBLE` is
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
element that causes them: `palette-dither` on an element whose `color:` or
`track_color:` is exactly `palette.<name>` **or** `config.<name>`,
`partial-update-budget` on any element drawn in `low_power` mode,
`graphics-pool` on the first element declaring `static: true`,
`antialias-dither` on the first element (in document order) whose
`antialias:` resolves to `true` on a 64-colour device, and
`config-unsupported` on an element whose `color:`/`track_color:` is exactly
`config.accent_color`, `config.data_color` or one role of `config.colors.<role>`,
or a `complication_slot` whose `slot:` is exactly `config.data.<name>`, and
`api-gated` on the element whose binding is actually gated -- the one whose
`value:`/`color:`/etc. names the unavailable source path, whose `on_hold:`
names the type, or the `complication_slot` whose `slot:`/`default:`/
`choices:` is affected.
`duplicate-style` and `unreachable-layout` are design-, not element-scoped
either, but there is no element to hang either on at all: `duplicate-style`
goes on the **`config: style:` entry's own** `lint:` (the second entry of
the duplicate pair), and `unreachable-layout` on the **`layouts:` entry's
own** `lint:` -- neither is an element.
`sub-pixel-length` is an ordinary element-scoped diagnostic like the rest
-- **except** that a finding about a hand or pattern **part** goes on the
part's **owning element**, the same element `min_1px:` inherits through
when the part declares none of its own: a part has no `lint:` block to
hang an `allow:` on.
See `docs/limitations.md` 3.

## What gets checked

`wfb validate` and `wfb build` check the design against each device for:
- text overflow
- the round screen's safe area
- contrast
- palette and anti-aliasing dither
- the power cost of low-power updates

Each warning states how confident the check is. When a warning is intended,
keep the design and record why:

```yaml
lint:
  allow: [safe-area]
  reason: "hugs the bezel by design"
```
