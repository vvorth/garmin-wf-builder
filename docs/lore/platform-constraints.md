# Platform constraints — full text

The full text behind root `CLAUDE.md` §4, with the same numbering. Add new
lore here, not to `CLAUDE.md`.

---

## 4. Platform constraints that will bite you

These are the findings that shaped every decision. Full detail and citations in
`docs/research/`. **Do not re-litigate these without new evidence.**

1. **There is no device-side renderer.** WFF/Facer/Fitbit all rely on a renderer
   already on the device; Garmin ships none. This is *why* the architecture is
   codegen (ADR 0003) — an interpreter would have to ship inside the same
   128 KB the design must fit in.

2. **The watch-face memory limit is a per-device number. Read it; do not
   assume 128 KB.** 131 072 B — one sixth of the 786 432 B the same hardware
   gives a watch app — is the *most common* value, not the rule. Across the
   **136 of 164** documented devices that can run a watch face at all
   (computed over `docs/research/data/devices/*.json`, SDK 9.2.0):

   | limit | devices |
   |---|---|
   | 131 072 B (128 KB) | 62 |
   | 98 304 B (96 KB) | 38 |
   | 65 536 B (64 KB) | 19 |
   | 524 288 B (512 KB) | 10 |
   | 114 688 B (112 KB) | 3 |
   | 49 152 B (48 KB) | 2 |
   | 135 168 B, 1 048 576 B | 1 each |

   So the budget spans **48 KB to 1 MB, a factor of 21**, and a design that
   fits comfortably on a fēnix 8 can be impossible on the 21 devices at or
   below 64 KB. `Device.watchface_memory_limit` (`wfb/devices.py`) already
   reads the real figure out of each `compiler.json`; nothing should hardcode
   131 072.

   The three verification devices (`fenix8solar47mm`/`51mm`, `fr955`) all sit
   at 128 KB, which is exactly why measurements taken on them are not a
   safety argument for anything else. Among the other vendored devices,
   `fr245` is **96 KB** and `fenix6` **112 KB** — adding either to `targets:`
   needs its own `--build-stats` check
   (`docs/research/probes/api-gating/`). `examples/dashboard/face.yaml`, the
   largest example, measured 14 817 B on `fenix6`: comfortable, but a
   per-design fact rather than a guarantee.

3. **There is no filled-arc primitive.** No `fillArc`, `fillSector` or
   `drawSector` exists anywhere in the API. Rings are `setPenWidth` + `drawArc`
   only — no cap control, no true annulus, no gradient sweep. The schema
   deliberately does not expose `innerRadius`/`outerRadius`.

4. **`onPartialUpdate` overrun is permanent.** Exceeding the budget calls
   `onPowerBudgetExceeded` and disables partial updates **for the remainder of
   the app lifecycle**. Also: `setClip` is charged by *region area* — every
   pixel in the clip counts as modified whenever any does.

5. **AMOLED forbids `onPartialUpdate` entirely.** MIP and AMOLED are structurally
   different low-power paths, not a styling difference. All three targets are
   MIP, but 74/164 devices are AMOLED-class.

6. **API level is NOT sufficient to determine availability.** `fr955` is API
   **5.2.0**, above `onTap`'s documented "since" of **5.1.0**, and still lacks
   `WatchFaceDelegate.onTap`. Always resolve symbols against the device's own
   `<id>.api.debug.xml`, keyed by fully-qualified parent. (`fr955` *does* have
   `InputDelegate.onTap` — a different symbol. Do not be fooled by a bare grep.)

   **6b. And a symbol being present is NOT sufficient either — read its prose.**
   `WatchFaceDelegate.onTap` *is* on both fēnix 8 targets, and it still never
   fires on a face the user is looking at: the SDK entry says "Only available
   in WatchFace config mode". A whole shipped feature (`on_tap:`, and the
   original "tap where available, hold on fr955" design) was designed around
   the symbol table alone and got this wrong — see
   `docs/research/07-carousel-interaction.md` §1.
   `has_symbol` answers "can I call it", never "will it be called".

6c. **A live watch face receives one gesture: touch and hold (`onPress`).**
   No tap, no swipe, no keys. `ClickEvent.getCoordinates()` is the only way to
   give one hold more than one meaning. Anything modelled on a *stock* Garmin
   face's tap behaviour is modelled on native firmware this API does not
   expose.

6d. **`monkeyc` does not gate on the device's symbol table -- so nothing
   catches an absent symbol at build time.** It resolves names against the
   **SDK-wide** API and checks arity, types and permissions; per-device
   availability it does not check at all. Proof with a clean control
   (`docs/research/probes/device-symbol-gate/`):
   `UserProfile.getFunctionalThresholdPower` is present in
   `fenix8solar47mm.api.debug.xml`, **absent from `fr955.api.debug.xml`**, and
   builds warning-free for `fr955` under `-l 3` -- while a typo in the same
   build is `Undefined symbol`. Two consequences, pulling opposite ways:
   **one shared generated view may reference an API only some targets have**,
   guarded at runtime, with no per-device source split (this is what makes
   on-device config a single view); and **the compiler will never tell you**
   when a binding cannot work on a target -- only `Device.has_symbol` and a
   lint will. Every existing use of `has_symbol` stays correct: it answers
   *what exists on the wrist*, which is the question that was always being
   asked.

6e. **Modules and class *fields* are per-device too, not just functions, and
   the manifest floor cannot express any of it.** Discovered adding `fenix6`
   (ConnectIQ 3.4.5) back to `examples/dashboard/face.yaml`'s `targets:`
   (`docs/research/probes/api-gating/README.md`): `fenix6` and `fr245` lack
   the `Toybox.Complications` **module** entirely (`<dataEntry
   type="module">`, `wfb.devices.Device.has_module`, new), not merely one
   function in it, and `fenix6` separately lacks the **field**
   `ActivityMonitor.Info.stressScore` (`fr245` lacks `floorsClimbed`,
   `floorsClimbedGoal`, `batteryInDays`, `ambientPressure`) — a class field
   lives in the device's `<symbolTable>` as a bare `<entry field="true"
   symbol="…"/>`, with no owning class recorded, so absence is exact but
   presence is only approximate (two unrelated classes could share a field
   name; `wfb.devices.Device.has_field`'s own docstring). Separately,
   `manifest.xml`'s `minApiLevel` is **one number for the whole build**,
   shared by every target device in `<iq:products>` — it cannot say "4.2.0
   for this device, 3.2.0 for that one," so a feature that raised it would
   lock out *every* target below that level in the same build, including one
   that never touches the feature. So the floor stays fixed at the generator's base level always
   (`wfb/emit/manifest.py::BASE_API_LEVEL`, `3.1.0`) and gates the module and
   the fields at runtime instead (`Toybox has :Complications`, `x has
   :stressScore`), aggregated over every target by `wfb.availability.
   compute_guards` so the one shared generated view emits a guard only when
   at least one target actually needs it. **The symbol table over-
   approximates presence**, the same way `has_symbol` already does for
   functions (6d): a probe that removed every executed `Complications` call
   from a `fenix6` build still found `Complications` in its compiled
   `<symbolTable>`, from `import Toybox.Complications;` and a type
   annotation alone, both erased at runtime — so it is a diagnostic for
   finding what to check, never proof that a build is safe. Runtime
   behaviour on real `fenix6`/`fr245` hardware — that a `has`-guarded
   reference to an absent module is harmless at load time, and that `has`
   itself reads `false` there — is the SDK docs' idiom, UNVERIFIED (no
   simulator in this container, finding 11 below).

7. **A missing permission fails silently.** The API returns null and the element
   never appears, with no diagnostic. The compiler deriving `manifest.xml`
   permissions from bindings is one of the framework's strongest justifications.

8. **Every data field is nullable.** All twenty `ActivityMonitor.Info` fields are
   `… or Null`. Absence is the normal case.

9. **On-device config has exactly four axes** (API 5.1.0, fēnix 8+): Styles,
   complication slots, **one** data colour, **one** accent colour. Max four saved
   configurations. No per-element colour editing. **`fr955` is excluded entirely.**

   **9b. The Data axis takes Garmin complication types only** -- there is no way
   to put author-defined content in a `<complication>`'s list. Author-defined
   selectable content therefore rides **Styles**, whose `styleId` is an opaque
   `Number` Garmin gives no meaning to. And a style is *global*, so the naive
   "one `styleId`, therefore one selectable area" is wrong: every area on the
   face can respond to the same number independently. See research 08 §4.

   **9c. All four axes are already spoken for -- there is no free one for
   layouts.** Styles carries colour schemes, Data carries `config: data:`
   complication slots, plus the two colour axes. Renaming a YAML key does not
   add an axis (the editor's group label is Garmin's). So colours *and* widget
   layouts share Styles as **explicitly listed entries** (each names a
   layout, a colour scheme, or both); background colour does not move to
   Data Color. Plans 01–02 hold the rejected options (`docs/CLAUDE.md`);
   `examples/features/styles/face.yaml` is the worked example.

10. **`alphaBlendingSupport: false`** on all three verification devices. No
    transparency. Per device, like everything else: read the flag.

11. **The graphics pool is separate** — `graphicsResourcePoolSize` is 1 MB,
    distinct from the app's own limit. Makes `BufferedBitmap` cheaper than
    feared, and, from API 4.0.0, a bitmap or font resource loaded at runtime
    goes there too: "when you load a bitmap or font at runtime, the resource
    will load into the graphics pool"
    (`$CIQ_SDK/doc/docs/Core_Topics/Graphics.html`). Measured corroboration —
    a baked font sheet grown from 11 to 95 glyphs left `--build-stats` data
    and code byte-identical and only grew the `.prg`
    (`docs/research/probes/vector-fonts/`).

12. **`onSettingsChanged` fires only for Garmin Connect pushes**, not on-watch
    edits. Any property write needs explicit cache invalidation.

13. **64-colour MIP palette**: each channel must be `0x00`/`0x55`/`0xAA`/`0xFF`
    or the firmware dithers it and it looks grainy.

14b. **A watch face can plot exactly four time series, and solar is not one.**
    `Toybox.SensorHistory` -- the obvious API, and the only route to pressure,
    stress, elevation and Body Battery *as series* -- has an **empty "Watch
    Face" cell** in `Core_Topics/Manifest_and_Permissions.html`'s permission
    table. It still compiles (see constraint 6d), and then fails silently
    (constraint 7). What is open, all permission-free:
    `ActivityMonitor.getHeartRateHistory` (period as a `Duration` *or* a sample
    count; the iterator carries its own `getMin`/`getMax`),
    `ActivityMonitor.getHistory()` (≤ 7 days), `Weather.getHourlyForecast()`
    and `Weather.getDailyForecast()`. **Solar has no history API at all** --
    only `System.Stats.solarIntensity` and `COMPLICATION_TYPE_SOLAR_INPUT`,
    both current values; the chart on a stock fēnix is native firmware.
    Research 08 §1.

14. **`deviceFamily` in `compiler.json` is the resource-qualifier directory
    name** — `round-260x260` (47 mm, fr955) vs `round-280x280` (51 mm). Read it;
    don't derive it.

15. **A watch face cannot ship its own outline font.** Connect IQ has two font
    paths and neither accepts an app-supplied `.ttf`/`.otf`:

    - **`<font>` resources take a BMFont `.fnt` and nothing else.** The
      resource compiler's own XSD (`$CIQ_SDK/bin/resources.xsd`, `fontType`)
      allows `id`/`filename`/`filter`/`antialias`/`scope`/`personality`, and
      `Core_Topics/Resources.html` §Fonts documents `filename` as a "BMFont
      generated .fnt file". `FontProcessor.processFont` in `monkeybrains.jar`
      takes a parsed `BMFont`; there is no TrueType rasteriser on that path.
      (The jar's `resourcecompiler/fonts/TTFont.class` is *not* one: it
      implements the layout-XML syntax `font="#FaceName:size"`, which emits a
      `Graphics.getVectorFont` call.)
    - **No API loads font bytes.** Every `*Font*` function in
      `$CIQ_SDK/bin/api.debug.xml` is `getFontAscent`, `getFontDescent`,
      `getFontHeight`, `getVectorFont`, `Text.setFont` and `TextArea.setFont`.

    So an author's typeface is always baked at build time
    (`wfb/fonts/bmfont.py`). **`Graphics.getVectorFont`** (API 4.2.1,
    `:face` + `:size` in pixels, returns null when unavailable) draws
    scalable text from **Garmin's own device-resident faces only** — roughly
    14 Latin faces, of which only `RobotoCondensedBold`/`Regular` is close to
    dependable, on **44 of the 136** watch-face-capable devices. Nothing can
    be added to that catalogue.

    Two consequences worth keeping straight. It is the **only** way to draw
    rotated or curved text — `Dc.drawAngledText`/`drawRadialText` "only
    support scalable fonts and do not support custom fonts loaded as
    resources" (`Core_Topics/Graphics.html`). And it is **not** a memory win:
    per constraint 11 a baked sheet already sits in the graphics pool rather
    than the watch-face budget. Measurements, the four availability gates and
    the full face/device inventory: `docs/research/12-vector-fonts.md`,
    `docs/research/probes/vector-fonts/`.
