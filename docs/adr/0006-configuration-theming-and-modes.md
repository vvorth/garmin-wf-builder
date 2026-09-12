# ADR 0006 — Configuration, theming, modes and interactivity

- **Status:** Accepted
- **Date:** 2026-09-04
- **Decides:** how an author declares user-editable properties, where those are
  edited, how palettes work, and how elements behave in low-power mode.

## Context

Phase 0 found the on-device story is much narrower than the brief assumes
(`02-features-feasibility.md` §6). The native watch-face editor is **API 5.1.0,
fēnix 8 and newer**, and exposes exactly four axes:

| Axis | Allows |
|---|---|
| Styles | enumerated author-defined variants, by number |
| Data | per-complication-slot type choice (or `allowAny`) |
| Data Colour | **one** colour, from a list or any |
| Accent Colour | **one** colour, from a list or any |

Maximum **four saved configurations** per face. There is no per-element colour
editing and no arbitrary data rebinding.

**User decision (2026-09-04):** target the **native editor plus phone-side
settings only**. No generated on-device settings menu.

**User decision (2026-09-04):** interaction is **tap where available, hold on
fr955** — the compiler generates both paths from one declaration.

> The premise of that decision turned out to be false: no device delivers a tap
> to a live watch face. It is hold everywhere, which needs one path, not two.
> See the amendment in §6.

## Decision

### 1. Three declared config surfaces, one declaration

> **Amended (2026-09-11): the colour half of this shipped, deliberately
> narrower than the design below.** The original text imagined arbitrary
> author-chosen property names, a `type:`/`edit:` pair per property, a phone-
> side settings surface, and a Data (complication-slot) axis alongside the two
> colours -- then had to *enforce* "at most one colour may be the accent, at
> most one the data colour" as a separate rule, because nothing about that
> shape said so on its own.
>
> Garmin's editor has exactly one accent-colour axis and one data-colour axis,
> full stop -- there is no third to declare and no naming choice that changes
> that. So the shipped format makes **the axis itself the key**:
>
> ```yaml
> config:
>   accent_color:
>     default: "#FF8000"
>     choices: any                       # the editor's own full colour picker
>   data_color:
>     default: "#FFFFFF"
>     choices:                           # or an explicit list
>       - { color: "#FFFFFF", label: "White" }
>       - { color: "#00FFFF", label: "Aqua" }
>       - { color: "#FFAA00", label: "Amber" }
> ```
>
> `accent_color`/`data_color` are the only two keys the block accepts -- a
> schema error, not a build-time uniqueness rule, is what happens to a third.
> No `type:` (every entry here is a colour; there is nothing else to declare
> yet), no `edit:` (there is exactly one surface implemented: the native
> editor), no phone-side settings axis, no Data/complication-slot axis. Each
> entry needs `default:` (a literal colour, compiled into the view as the
> starting value -- and the *only* value a device with no native editor, i.e.
> `fr955`, ever shows) and `choices:` (`any` for the editor's own picker, or
> an explicit `{color, label}` list, where `default:` must be one of the
> listed colours).
>
> Elements reference a declared entry as an ordinary colour expression, the
> same as a palette entry: `color: config.accent_color`. `wfb/expr.py`'s
> `Binding.kind == "config"` -- declared in ADR 0005 and never used until
> now -- is what makes this a `constant=None` binding: unlike a palette entry,
> the view field it names is user-editable at runtime, so `fold` must never
> inline it.
>
> **`palette:` still may not reference `config.*`.** A palette entry compiles
> to a Monkey C `const`; turning one into a runtime-read field is a bigger
> change than this amendment makes, so `bg: config.accent_color` stays a build
> error whose note points at writing `color: config.accent_color` directly
> instead.
>
> Generated per device, not shared, and gated by `Device.has_symbol`, never an
> API-level compare -- the same constraint 6 (CLAUDE.md) that `on_hold:`
> already had to learn from: `fr955` reports ConnectIQ 5.2.0, above the
> editor's own documented 5.1.0, and still has no editor. A target with no
> editor keeps its declared `default:` forever, once again a real, user-facing
> consequence of §2 below rather than a defect -- and the suppressible
> `config-unsupported` warning says so at build time. See
> `docs/research/probes/watchface-config/` for the probe this rests on, and
> `docs/format.md`'s "Configuration" section for the full author-facing
> reference.
>
> Styles, the Data axis, and phone-side settings are still exactly as
> undecided as the "Open" section below says; this amendment does not touch
> them.

> **Second amendment (2026-09-11): the Styles axis shipped too, as
> `color_scheme:` + `config: colors:`** (`docs/research/09-data-library-and-
> config-axes.md` §3). The "Open" bullet directly above -- "whether Styles is
> worth exposing" -- is answered: it is, and cheaply, because it is a single
> opaque `Number` Garmin gives no meaning to at all, unlike the two colour
> axes which each carry a real, Garmin-defined colour.
>
> ```yaml
> color_scheme:
>   dark:
>     label: "Dark"
>     colors: { bg: palette.black, fg: palette.white, dim: palette.dark_gray }
>   light:
>     label: "Light"
>     colors: { bg: palette.white, fg: palette.black, dim: palette.light_gray }
>
> config:
>   colors:
>     default: color_scheme.dark          # must be one of choices:
>     choices:
>       - color_scheme.dark
>       - color_scheme.light
> ```
>
> A colour *scheme* is several colours moving together, and no native colour
> axis carries more than one colour -- `accentColor`/`complicationColor` are
> each a single `Color`, and `Settings` has exactly four fields total
> (`styleId`, `complicationSettings`, `accentColor`, `complicationColor`), so
> there is no fifth axis to add a scheme to. `color_scheme:` therefore rides
> **Styles**, and `config.colors.<role>` is an ordinary colour reference like
> any other, resolved to a generated view field
> (`_configColorsBg`) that a generated `resolveColorScheme(styleId)` assigns
> from a plain `if (style == N)` chain, `choices:` order, index 0 first --
> mirroring `applyConfig`'s existing two-deep-nullable-guard shape for the
> other two axes exactly, per `docs/research/probes/config-axes/`.
>
> **Every `color_scheme:` entry must declare the identical role set**, or
> `config.colors.dim` would be undefined the moment the wearer picked a
> scheme that never declared it -- checked as a build error against the
> *union* of every scheme's own roles, so the report always names whichever
> scheme(s) fall short rather than depending on declaration order.
> `config.colors` used bare (naming the scheme, not a role) and
> `config.colors.<role>` naming an undeclared role are both errors with their
> own domain-specific message, not a generic "unknown data source" -- the
> obvious first failure mode for a feature whose scope-bound names live
> nowhere but inside one design.
>
> **`bool(face.config)` was, until this amendment, the single on/off switch
> for the entire on-device-config feature** across `wfb/emit/monkeyc.py`,
> `wfb/emit/resources.py` and `wfb/lint.py` -- a design declaring only
> `color_scheme:`/`config: colors:` and no colour axis would have silently
> gotten no `<watchface-config>`, no delegate and no `applyConfig` at all.
> Replaced everywhere by `Face.has_config`, and a design with only the Styles
> axis is now covered by its own real-`monkeyc`, warning-free test
> (`tests/test_color_scheme.py`) -- the exact gap CLAUDE.md's own account of
> the delegate's unused `_view` field warns is easy to ship silently, because
> every earlier test inspected generated text rather than compiling it.
>
> Cost, measured at a fixed path (`docs/research/probes/config-axes/README.md`
> already established this at ~9 B data / ~61 B `.prg` per style with no code
> growth; reconfirmed here at a different role count): a design going from no
> `config:` at all to one two-role, two-scheme Styles axis costs **+416 B**
> (turning the feature on: fields, `resolveColorScheme`, `applyConfig`, the
> delegate, the `<styles>` resource); one *additional* scheme on top of that
> costs **+9 B data, +28 B code** -- consistent with the probe's own
> per-style figure. `docs/format.md`'s "Color scheme" section is the
> author-facing reference; `examples/config/face.yaml` now exercises it,
> including the static-buffer repaint case (two roles moving together inside
> a `static:` block, confirmed by a real build rather than assumed).

> **Third amendment (2026-09-11): the Data axis shipped too, as
> `config: data:` + `type: complication_slot`** (`docs/research/09-data-
> library-and-config-axes.md` §4). All four of Garmin's axes are now
> declared, and the "Open" bullet below that named the Data axis as
> outstanding is closed.
>
> ```yaml
> config:
>   data:
>     top:
>       default: complication.steps
>       choices:
>         - complication.steps
>         - complication.heart_rate
>         - complication.calories
>     bottom:
>       default: complication.body_battery
>       choices: any
>
> elements:
>   - id: top_reading
>     type: complication_slot
>     slot: config.data.top
>     icon_size: 8%r
>     color: palette.fg
> ```
>
> Unlike the two colour axes and Styles, `data:` is a **mapping of named
> slots** rather than one fixed key -- Garmin's own Data axis holds several
> independent complication slots, not one value, so there is no single
> `config.data` the way there is one `config.accent_color`. Each slot's
> `default:`/`choices:` name `wfb.complications.TYPES` keys -- the same table
> `on_hold:` and the `complication.*` data-source namespace already resolve
> against, not a third one.
>
> **This is the first axis with a dedicated drawing element**, because unlike
> a colour, *which complication is showing* is not known until the wearer
> picks it on-device (`Complications.Id.getType()` only resolves at
> runtime) -- there is no fixed source for the expression compiler to bind,
> so `complication_slot` pulls through `WfbComplications.valueOf` directly
> and renders `value.toString()` (no `format:` -- an error naming why: the
> value's concrete type varies by choice). The icon is chosen the same way,
> on-device, from the type alone, through a generated per-slot lookup method
> (`wfb.icons.COMPLICATION_ICON` -> a catalogue name -> `IconGlyphs.glyph`)
> -- verified in `docs/research/probes/config-axes/ProbeView.mc`'s `iconFor`,
> and the reason it is a *method* rather than an inline local: Monkey C
> locals cannot be given an explicit `as String?` type, confirmed by a real
> build ("Invalid explicit typing of a local variable").
>
> **Not built, deliberately separate:** the editor's own animated highlight
> on a slot (`getComplicationDrawable`/`onTap`/`setSelectedComplication`,
> `docs/research/09 §4`) -- a different seam (a generated `WatchUi.Drawable`
> subclass) from drawing a slot's current pick, which is what shipped here.
> `Device.has_symbol(CONFIG_SYMBOL)` still gates the whole feature per
> device, unchanged; `Face.has_config` now has three independent triggers
> rather than two.
>
> Cost, measured through the real toolchain rather than assumed: a design
> with two slots (one an explicit three-choice list with an icon, one
> `allowAny` with none) compiles to 2.2% of the 128 KB budget on all three
> targets, `minApiLevel="4.2.0"` and `ComplicationSubscriber` both present
> even though the design binds no ordinary `complication.<name>` catalogue
> source at all -- a slot is not a catalogue reader, so `_features()`/
> `permissions()` had to add it as a second, independent trigger alongside
> "reads a `complication.*` source". `docs/format.md`'s "Configuration → The
> Data axis" is the full author-facing reference; `examples/slots/face.yaml`
> exercises both slot shapes.

> **Fourth amendment (2026-09-11): `on_hold:` and the editor's animated
> highlight both shipped on `complication_slot`, closing the two gaps the
> third amendment left open.**
>
> `on_hold: auto` is the only spelling this element accepts -- a fixed name
> is an error naming why (it would silently disagree with what the wearer's
> own pick shows). Unlike every other element's `auto`, which resolves once
> at build time to a fixed `wfb.complications.TYPES` name via `Source.
> launch_complication`, a slot's resolves on-device, on every hold, from
> whatever `Complications.Id` the wearer currently has it pointed at --
> `Complications.exitTo(_view.holdTargetForTopReading())`, not a name looked
> up in a table. Nothing about the platform ever prevented this; it was
> simply sequenced after the drawing half.
>
> The editor's own animated highlight -- called "not built, deliberately
> separate" in the third amendment -- is now built too, for **any** design
> with at least one `complication_slot` element, regardless of whether that
> element also declares `on_hold:`: `AppBase.onStart` detects edit mode
> (`state[:launchedFromWatchFaceSettingsEditor]`, verbatim from the SDK
> sample), `WatchFaceDelegate.onTap` + `setSelectedComplication` hit-test
> each slot's own resolved box, and `getComplicationDrawable` returns a
> generated `<Face>SlotDrawable` that delegates straight back to the view's
> own per-slot draw method -- one implementation of what a slot looks like,
> two callers. The view hides the slot the editor is animating (a `_pulsing`
> field, checked first in every `complication_slot`'s draw method), matching
> the SDK sample's own comment on why that is mandatory rather than optional.
> A design with no `complication_slot` gets none of this: `onTap` never
> fires on a live face (research 07 §1), so it would be dead weight there.
>
> Cost, measured on `examples/slots/face.yaml` at a fixed path,
> `fenix8solar47mm`: the editor machinery alone (both slots, neither with
> `on_hold:`) is **+161 B data, +693 B code** over the same design without
> it; adding `on_hold: auto` to one slot costs a further **+9 B data, +90 B
> code** on top of that -- matching the third amendment's per-style-sized
> costs in kind, if not in exact figure (this is new code, not a resource
> entry). **No behaviour of any of it is verified** -- whether the highlight
> actually animates, whether it lines up with what is drawn, and whether
> `onTap`'s hit regions read correctly on a real touchscreen are all
> UNVERIFIED, same as every other editor claim in this ADR. What is verified:
> real `monkeyc`, warning-free, on all three targets, `fr955` included --
> which has no editor at all and never calls any of `onStart`'s flag,
> `onTap` or `getComplicationDrawable`.
>
> `docs/format.md`'s "Configuration → The Data axis" carries the full
> author-facing description; `examples/slots/face.yaml` now declares
> `on_hold: auto` on one of its two slots.

An author declares a property once and states where it may be edited. The
compiler emits the right artefact for each surface and **fails the build if a
surface is unavailable on a targeted device** rather than silently dropping it.

*Original text below, superseded for the colour axes by the amendment above --
kept because it is what was decided and imagined at the time, the same
precedent §6's `on_tap:` correction set.*

```yaml
config:
  accent:
    type: color
    default: "#FF8000"
    edit: [device_native, phone]     # -> <accentColors>, and settings.xml
  data_color:
    type: color
    default: "#FFFFFF"
    choices: ["#FFFFFF", "#00FFFF", "#FFFF00"]
    edit: [device_native, phone]     # -> <dataColors>
  slot1:
    type: complication
    allow: [steps, heart_rate, current_weather]
    edit: [device_native, phone]     # -> <data><complication>
  show_seconds:
    type: bool
    default: true
    edit: [phone]                    # -> settings.xml only
```

Emitted artefacts:

- `edit: device_native` → the `<watchface-config>` resource, read at runtime with
  `WatchFaceConfig.getSettings(null)`, plus the `onWatchFaceConfigEdited` and
  `setSelectedComplication` wiring.
- `edit: phone` → `resources/settings/settings.xml` + `properties.xml`, pushed
  via Garmin Connect.

**Enforced constraints**, checked at build time so they cannot be discovered on
the wrist:

- At most **one** `color` property may be `device_native` as the data colour, and
  at most one as the accent colour. Declaring a third is a build error naming the
  four-axis limitation.
- `device_native` on a target below API 5.1.0 is a build error, with the
  offending device named.
- Non-complication data properties cannot be `device_native`.

### 2. fr955 has no on-device configuration — stated plainly

This follows directly from the chosen scope. The fēnix 8 Solar pair get the
native editor; **the fr955 gets phone-side settings only**, because it is
excluded from the 5.1.0 editor entirely. A design targeting all three is
therefore configurable on the wrist on two of three devices.

This is a consequence of the decision, not a defect, but it must appear in
`docs/limitations.md` and in the build output, so it is never a surprise. The
generated-on-device-menu option that would have covered fr955 was considered and
declined; if that changes, it slots in as a fourth `edit` surface without
disturbing the declaration format.

### 3. Property caching and invalidation

`onSettingsChanged` fires **only** for Garmin Connect pushes, not for on-watch
edits. Any code path that writes a property must explicitly invalidate the cache
or the change silently does not take effect — a trap the sibling Dashboard
project documents from experience.

The generated runtime therefore owns property caching centrally and invalidates
on: `onSettingsChanged`, `onWatchFaceConfigEdited`, and any internal write
(e.g. a tap cycling a slot). Authors never touch this.

### 4. Theming

Palettes are named and resolved at build time:

```yaml
palette:
  bg: "#000000"
  text: "#FFFFFF"
  hot: "#FF5500"
  accent: config.accent          # a runtime-configurable entry
```

Entries resolving to literals become Monkey C constants. Entries bound to config
are read at runtime. Elements reference `palette.hot`, never a raw hex value.

**Palette legality is linted** (Phase 1.4): on a 64-colour device each channel
must be one of `0x00/0x55/0xAA/0xFF`, or the firmware dithers it and it looks
grainy. The linter warns with the nearest legal colour, and an explicit
`allow_dither: true` silences it for a deliberate choice.

### 5. Modes — active, low power, always-on

Because AMOLED forbids `onPartialUpdate` entirely while MIP depends on it
(`01-platform-capabilities.md` §4), mode is a structural property of the IR, not
styling.

```yaml
- id: seconds
  type: text
  value: time.second
  modes: [active, low_power]     # omitted from always_on
```

Modes: `active` (high power, `onUpdate` each second), `low_power` (MIP,
`onPartialUpdate` each second), `always_on` (AMOLED burn-in-constrained).
Default is `[active]` for anything not explicitly marked.

The compiler derives from this:

- the tight `setClip` rectangle around all `low_power` elements — computed from
  resolved geometry and font metrics, and the reason clip cost (charged by
  region area) can be minimised automatically;
- whether a `BufferedBitmap` background is worth pre-rendering in `onUpdate` —
  and this is cheaper than feared: `graphicsResourcePoolSize` is **1 MB on all
  three targets**, a budget separate from the 128 KB watch-face limit
  (`05-device-files.md` §4). **This shipped, as `static:`** — see the note at
  the end of this section;
- the AMOLED pixel/luminance estimate for `always_on` (Phase 1.4);
- ~~an error if a `low_power` element reads a non-`frame`-tier source
  (ADR 0005).~~ **No longer true — see ADR 0005's "Amendment (2026-09-09):
  the refresh-tier concept is deleted".** The tier system this bullet refers
  to is gone; any source may be bound from a `low_power` element now. The
  platform limit behind the old rule (`onPartialUpdate` budget overrun is
  permanent) is unchanged, but it is enforced by ADR 0008 check 9's
  suppressible heuristic alone, not a hard compile-time rule.

#### Note (2026-09-09): the `BufferedBitmap` bullet shipped, as `static:`

The third bullet above is now a feature rather than a possibility.
`static: true` on any element, and a top-level `static:` block beside
`elements:`, mark content that never changes; the compiler paints it once into a
full-screen `Graphics.BufferedBitmap` in `onLayout` and blits it each
`onUpdate`. `docs/format.md` is the author-facing reference and
`docs/research/probes/static-buffer/` is the probe that settled the design.

Three things about it belong in this ADR rather than only in the reference,
because they are decisions and not documentation:

1. **The compiler does not decide "whether it is worth it" — the author
   declares it.** The bullet above imagined the compiler working that out. It
   cannot: the benefit is CPU time per frame, and this project has no way to
   measure CPU time (no simulator in the container, no watch). A compiler that
   silently buffered what it guessed was expensive would be trading a *measured*
   1 MB pool for an *unmeasured* saving. Declaring it keeps the trade visible.

2. **The buffer is opaque, and static content is therefore a contiguous
   prefix of draw order.** Whether a `COLOR_TRANSPARENT`-cleared buffer blits
   transparently on a device with `alphaBlendingSupport: false` could not be
   established from the SDK and cannot be run here — the evidence both ways is
   in the probe's README, labelled UNVERIFIED in the same way ADR 0005's
   complication-pull question was. The provable design shipped instead. One
   consequence: exactly one buffer per face.

   > **Amended (2026-09-10): the prefix is arranged, not demanded.** This
   > originally shipped as `error[static]` — a design that wrote a dynamic
   > element ahead of its static content simply did not build. That was the
   > wrong call, for a reason that is visible in the sentence above: there is no
   > order in which anything can be *under* an opaque full-screen blit, so
   > "static content first" is not a choice the format offers and never was a
   > constraint the author could satisfy differently. The compiler now sorts it
   > (`wfb.ir.draw_sort_key`), keeping each `static:` root one unbroken run, and
   > reports only the part the author cannot see for themselves: the
   > suppressible `static-overlap` warning, for pairs the hoist swapped whose
   > boxes overlap on that device. Nothing about the codegen or the opaque
   > design changed.

3. **The benefit is unmeasured and is not claimed anywhere.** What is verified:
   it compiles warning-free under `-l 3` on all three targets; the fallback path
   (`Graphics has :createBufferedBitmap`, plus a null check on `.get()`) draws
   the same content through the same generated method, so a device without the
   API still renders correctly; and the byte cost is +9 B data / +147 B code
   plus a full screen of pool. ADR 0008's rule that a check must not overclaim
   applies to features too: the `graphics-pool` lint reports the pool cost as an
   **estimate**, because bytes per pixel for a `BufferedBitmap` is not published
   and it uses the display's `bitsPerPixel` as a proxy.

### 6. Interactivity

> **Amended after `docs/research/07-carousel-interaction.md`.** The original
> text below the rule is kept because it is what was decided and built; it
> rested on a wrong reading of the SDK and the correction is substantial.

**What was wrong.** This section assumed two gestures — tap on the newer
watches, hold on `fr955` — and shaped the whole design around choosing between
them. There is only one. `WatchFaceDelegate.onTap` is documented **"Only
available in WatchFace config mode"**: it exists on the fēnix 8 targets and
fires solely inside the on-device editor, telling it which complication slot
the user picked (`samples/ConfigurableWatchFace`). A face that is merely being
looked at never receives a tap, on any device. `onPress` — touch and hold — is
the entire input surface, and all three targets have it.

**Consequences of the correction.**

- "Tap where available, hold on fr955" is not a real distinction. It is **hold,
  everywhere**. The per-device symbol resolution is still right and still
  necessary — `onPress` is absent on the many products with no touchscreen —
  it just no longer chooses between two mechanisms.
- The shipped key `on_tap:` is renamed **`on_hold:`**; the old spelling is an
  error naming its replacement.
- The compiler emits `onPress` only. An `onTap` handler would be dead code that
  also tells its reader something untrue.
- `minApiLevel` comes from `exitTo`'s 4.2.0, never `onTap`'s 5.1.0.

**The conflict rule below is obsolete, and in a useful direction.** It said
`on_hold: launch` and hold-to-cycle conflict on `fr955` and that the compiler
"must reject that combination". With tap gone the conflict is universal rather
than device-specific — but it is also no longer a conflict, because
`ClickEvent.getCoordinates()` separates the two meanings by **geometry**
instead of by gesture. A cycling element partitions its own box: hold the left
third for previous, the right third for next, the middle for `exitTo`. The
compiler lays out zones and warns when one is too small to hit; it rejects
nothing. See research 07 §2.

> **Fifth amendment: the cycling element built from the above,
> `type: carousel`, was removed outright, on the user's decision.** It
> shipped, worked, and was deleted anyway — not because it was broken, but
> because it turned out to be the single largest feature by surface area
> while opting out of nearly every shared mechanism this compiler otherwise
> gives every element: its own touch model (the three-zone geometry
> described just above, rather than a plain `on_hold:` target), its own
> runtime barrel file (`WfbCarousel.mc`), its own absence rule (the only
> element that skipped the ordinary element-level null guard in favour of a
> per-item one), its own font-resolution path, its own layout-box
> distinction (`content_box` vs. `box`, which existed only so the safe-area
> lint would not fire on a deliberately oversized touch target), its own
> lint check (`carousel-zone`), and hard exclusions from `static:` and from
> element-level `antialias:`. It was also the only element that persisted
> state, and `docs/research/09-data-library-and-config-axes.md` §5.4
> established that `Application.Storage` is **global across all four of the
> wearer's saved configurations** — so the selected item leaked between
> saved faces, a real behavioural wart with no fix available on this
> platform. Every one of those special cases is now simply gone rather than
> maintained for one element. `docs/format.md`'s `carousel` section, the
> `carousel-zone` lint, `examples/carousel/`, and the runtime barrel file are
> all deleted; `on_hold:` (§6 above, unaffected) remains every other
> element's whole interactivity story. See CLAUDE.md's Phase 3 notes for the
> session that removed it and the measured size of the deletion.

---

*Original text, superseded above:*

Declared per element, compiled to whichever mechanism the target supports:

```yaml
- id: slot1
  type: complication_slot
  cycle: [steps, heart_rate, body_battery]
  on_activate: cycle             # tap where available, else hold
  on_hold: launch                # Complications.exitTo()
```

Per the decision, `on_activate: cycle` generates:

- **`onTap`** on devices in the 5.1.0 tap set (both fēnix 8 Solar targets);
- **`onPress`** on devices with 4.2.0 hold but no tap (**fr955**);
- nothing, with a build warning, on devices with neither.

Hit regions are generated from resolved element geometry — the compiler already
knows every bounding box, so the hit-test table costs the author nothing. The
selected slot persists in `Application.Storage` and survives restarts.

Note `on_hold: launch` and hold-to-cycle **conflict on fr955**, where hold is the
activation gesture. The compiler must reject that combination for a device where
both map to `onPress`, rather than silently preferring one.

## Consequences

- One declaration drives up to three generated artefacts; they cannot drift.
- Several genuine platform limits become build errors instead of wrist
  surprises — the four-axis cap, and the per-device symbol gate. (The
  hold-gesture conflict this originally listed turned out not to exist; see the
  amendment in §6.)
- `docs/limitations.md` must state the four-axis cap, the four-configuration
  cap, and the fr955 exclusion.
- (§1 amendment) The two colour axes shipped as `config:`, narrower than the
  arbitrary-property design this ADR originally described — see the amendment
  for what changed and why. `docs/format.md` "Configuration" is the
  author-facing reference; `docs/limitations.md` states that no behaviour of
  the editor itself is verified anywhere in this project.
- (§1 second amendment) The Styles axis shipped as `color_scheme:` +
  `config: colors:` — the "is Styles worth exposing" question the Open
  section below used to ask is answered, and closed. `docs/format.md` "Color
  scheme" is the author-facing reference.
- (§1 third amendment) The Data axis shipped as `config: data:` +
  `type: complication_slot` — all four of Garmin's axes are now declared.
  `docs/format.md` "Configuration → The Data axis" is the author-facing
  reference; the editor's own animated highlight on a slot was, at that
  point, a separate, unbuilt task (see the amendment and
  `docs/limitations.md`).
- (§1 fourth amendment) `on_hold: auto` and the editor's own animated
  highlight (`AppBase.onStart`/`WatchFaceDelegate.onTap`+
  `getComplicationDrawable`) both shipped on `complication_slot`, closing the
  gap the third amendment left open. `docs/format.md` "Configuration → The
  Data axis" carries the update; no behaviour of the editor is verified,
  same as every other `config:` claim.
- (§6 fifth amendment) `type: carousel`, the cycling element §6's geometry
  correction made possible, shipped and was then removed outright on the
  user's decision — the largest single feature by surface area, and the
  only element that opted out of the null guard, font resolution, layout-box
  and static/antialias rules every other element shares. See the amendment
  for the reasons and CLAUDE.md for the deletion session.

## Open

- A phone-side settings surface, still undecided — the four `config:`
  amendments implemented the two colour axes, Styles and Data (drawing and
  interactivity alike), which is all four of Garmin's native-editor axes;
  phone settings would be a separate mechanism (`settings.xml`/
  `properties.xml`) and is the only route that reaches `fr955`.
