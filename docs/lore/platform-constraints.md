# Platform constraints — full text

Moved verbatim out of `CLAUDE.md` on 2026-09-13 (§4) so the file every
session loads stays small. `CLAUDE.md` keeps a short summary and the **same
numbering**, so an older citation such as "CLAUDE.md §6" or "CLAUDE.md
constraint 6" for this material resolves here. Keep adding to this file,
not back into `CLAUDE.md`.

---

## 4. Platform constraints that will bite you

These are the findings that shaped every decision. Full detail and citations in
`docs/research/`. **Do not re-litigate these without new evidence.**

1. **There is no device-side renderer.** WFF/Facer/Fitbit all rely on a renderer
   already on the device; Garmin ships none. This is *why* the architecture is
   codegen (ADR 0003) — an interpreter would have to ship inside the same
   128 KB the design must fit in.

2. **Watch faces get 131 072 B (128 KB)** on all three targets — one sixth of
   the 786 432 B the same hardware gives a watch app. 28 of 164 documented
   devices cannot run a watch face at all.

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
   the symbol table alone and got this wrong — see `docs/history.md`'s
   carousel-interaction session for the correction in full.
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
   add an axis (the editor's group label is Garmin's). **Decided 2026-09-13:**
   colours *and* widget layouts share Styles as **explicitly listed entries**
   (each names a layout, a colour scheme, or both); background colour does not
   move to Data Color. **Built 2026-09-13** -- see plan 01 (the decision
   and the rejected options) and plan 02 (the design and the build plan:
   `layouts:` form A, `config: style:` replacing `config: colors:` outright,
   no shim); both were deleted once built, see `docs/CLAUDE.md`.
   `examples/styles/face.yaml` is the worked example.

10. **`alphaBlendingSupport: false`** on all three targets. No transparency.

11. **The graphics pool is separate** — `graphicsResourcePoolSize` is 1 MB,
    distinct from the 128 KB app limit. Makes `BufferedBitmap` cheaper than feared.

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
