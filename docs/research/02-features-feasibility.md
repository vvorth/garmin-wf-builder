# 0.2 — Feasibility of the specific requested features

Same sourcing convention as `01-platform-capabilities.md`. **[verified]** means
read from the SDK on disk (`doc/Toybox/**`, `doc/docs/**`, `bin/api.debug.xml`);
**[docs]** means asserted by Garmin prose; **[open]** means unresolved.

Target devices throughout: `fenix8solar47mm`, `fenix8solar51mm`, `fr955`.

> **Headline:** two of the requested features do not reach all three target
> devices, and one requirement is supported only in a much narrower shape than
> the prompt assumes. Details in §5 and §6.

---

## 1. Icons

**Options and their real costs.**

Bit depths supported: 1, 2, 4, 8, 16 BPP. From
`doc/docs/Connect_IQ_FAQ/How_Do_I_Optimize_Bitmaps.html` **[verified]**, for a
100×100 image:

| Bit depth | Colours | Size |
|---|---|---|
| 1 | 2 | 1.22 KB |
| 2 | 4 | 2.44 KB |
| 4 | 16 | 4.88 KB |
| 8 | 256 | 9.77 KB |
| 16 | 65536 | 19.53 KB |

Device palette classes are 16-colour, RGB222 (64 colours — all three targets),
and RGB565. `Dc.setColor` takes RGB888 and always maps to the nearest available
device colour.

**Assessment for a builder.** A watch face has 128 KB total on the targets. A
handful of 8 BPP icons at 40×40 (1.56 KB each) is affordable; a library of
dozens is not, and shipping every *possible* icon is impossible. Three
strategies:

1. **Drawn vector primitives** (`fillPolygon`, `fillCircle`, `drawLine`). Zero
   resource bytes, scales with screen size for free, costs only bytecode.
   Best fit for a builder that must offer a large catalogue but embed only what
   is used — the "embed only the used ones" problem disappears because there is
   nothing to embed.
2. **Icon font** — one bitmap `.fnt` with the used glyphs subsetted. Amortises
   the atlas across many icons and gets colour-by-`setColor` for free (fonts are
   single-channel, see §7). Good when icons are numerous and static.
3. **Bitmap resources**, per-device via resource qualifiers, at the lowest bit
   depth that preserves the design.

**Recommendation:** primitives first, icon font second, bitmaps last. This
matches what the existing Dashboard face already does (`source/Icons.mc` draws
from primitives) and is the only approach that scales across 148–480 px screens
without per-device asset generation.

---

## 2. Data values

All confirmed present in `bin/api.debug.xml` and `doc/Toybox/` **[verified]**.
Modules available: `Activity`, `ActivityMonitor`, `ActivityPrompts`,
`ActivityRecording`, `Ant`, `AntPlus`, `Application`, `Attention`,
`Authentication`, `Background`, `BluetoothLowEnergy`, `Communications`,
`Complications`, `Cryptography`, `FitContributor`, `Graphics`, `Lang`, `Math`,
`Media`, `Notifications`, `PersistedContent`, `PersistedLocations`, `Position`,
`ScanCode`, `Sensor`, `SensorHistory`, `SensorLogging`, `StringUtil`, `System`,
`Test`, `Time`, `Timer`, `UserProfile`, `WatchUi`, `Weather`.

### `ActivityMonitor.Info` — every field is nullable

`steps`, `stepGoal`, `calories`, `distance`, `floorsClimbed`,
`floorsClimbedGoal`, `floorsDescended`, `metersClimbed`, `metersDescended`,
`activeMinutesDay`, `activeMinutesWeek`, `activeMinutesWeekGoal`,
`moveBarLevel`, `respirationRate`, `stressScore`, `timeToRecovery`,
`isSleepMode`, `pushes`, `pushGoal`, `pushDistance`.

Every single one is typed `… or Null`. **The schema must treat "no value" as the
normal case, not an error path.** A generated face that assumes a reading exists
will crash on a device that lacks the sensor. This argues for a formatting layer
where every binding declares its absent-value rendering.

Note `pushes`/`pushGoal`/`pushDistance`: in wheelchair mode the system
substitutes these for steps/floors, and `COMPLICATION_TYPE_STEPS` /
`COMPLICATION_TYPE_FLOORS_CLIMBED` become `COMPLICATION_TYPE_WHEELCHAIR_PUSHES`
**[verified]**. A builder should surface this rather than hard-coding "steps".

### `SensorHistory` — iterators, permission-gated

`getBodyBatteryHistory`, `getElevationHistory`, `getHeartRateHistory`,
`getOxygenSaturationHistory`, `getPressureHistory`, `getStressHistory`,
`getTemperatureHistory`. Each returns a `SensorHistoryIterator` and each is
individually optional — the documented idiom is a double guard:

```monkeyc
if ((Toybox has :SensorHistory) &&
    (Toybox.SensorHistory has :getBodyBatteryHistory)) { … }
```

Requires the `SensorHistory` permission. Walking an iterator is expensive and
belongs on a slow refresh tier, never in `onPartialUpdate`.

### Other sources

- `Activity.getActivityInfo()` — current HR, altitude, pressure, speed.
- `System.getSystemStats()` — battery, charging, memory. `System.getDeviceSettings()`
  — DND, alarm count, notification count, phone connected, `is24Hour`,
  `requiresBurnInProtection`.
- `Weather.getCurrentConditions()` — condition code, temperature,
  `observationLocationPosition`; sunrise/sunset via `Weather` or computed from
  `Position`. Requires `Positioning` for location-derived values.
- `UserProfile` — user metrics, HR zones.
- `Position` — GPS. Permission-gated.

### Permissions fail silently — a critical framework concern

A missing permission does not raise; the API simply returns null and the element
never appears, with no diagnostic anywhere. This is the single most common
"works in the simulator, blank on device" failure. **The compiler must derive
the permission set from the bound data sources and write `manifest.xml`
itself** — this is one of the strongest arguments for the whole project, because
it eliminates a failure mode that is invisible at runtime.

---

## 3. Complications (`Toybox.Complications`)

Since **API 4.2.0** **[verified]**. Source:
`doc/docs/Core_Topics/Complications.html`.

A publish/subscribe system. **Only watch faces can subscribe**; device apps and
audio content providers publish (up to four each). Requires the
`ComplicationSubscriber` permission.

A `Complication` exposes `complicationId`, `longLabel`, `shortLabel`
(five characters, for radial display), `value`, `unit`, `ranges`, plus
`getIcon()` and `getType()`.

Units are normalised and **the subscriber must convert**: `UNIT_DISTANCE`/
`UNIT_ELEVATION`/`UNIT_HEIGHT` in metres, `UNIT_SPEED` m/s, `UNIT_TEMPERATURE`
°C, `UNIT_WEIGHT` grams. A builder's formatting layer should own this
conversion against `DeviceSettings` unit preferences — hand-written faces get
this wrong constantly.

Lifecycle: `registerComplicationChangeCallback()` then `subscribeToUpdates(id)`.
**All subscriptions terminate on app shutdown and must be re-established on
launch.** `getComplication()` throws `ComplicationNotFoundException` if the
publisher was uninstalled; this must be trapped.

**Should complications be a first-class data source? Yes — decisively.**
Three reasons: they are the unified interface Garmin is investing in; they are
the *only* data binding the on-device editor understands (§6); and they
give access to third-party app data no direct API exposes. The schema should
model a data binding as either a direct API read or a complication subscription,
with complications preferred where an equivalent exists.

`Complications.exitTo(id)` launches the publishing app — the "hold to launch"
behaviour — via `onPress`. See §5.

---

## 4. Progress indicators — all four styles

### 4a. Arc / ring segments — **constrained, read this carefully**

There is **no filled-arc primitive in Connect IQ**. `fillArc`, `fillSector` and
`drawSector` do not exist anywhere in the API **[verified — exhaustive grep of
`doc/Toybox`]**. Available: `drawArc(x, y, r, ARC_CLOCKWISE|ARC_COUNTER_CLOCKWISE,
degreeStart, degreeEnd)` since API 1.2.0.

A thick progress ring is therefore `setPenWidth(n)` + `drawArc`. Consequences
the schema must expose rather than hide:

- Ring thickness is a pen width, not an inner/outer radius pair.
- End caps are whatever the firmware's pen rendering produces; cap style is not
  selectable.
- A true annulus, a tapered ring, or a gradient sweep must be approximated with
  many `fillPolygon` quads — expensive in both bytecode and frame time, and a
  poor fit for `onPartialUpdate`.
- Anti-aliasing is device-gated and unavailable on palette'd `BufferedBitmap`,
  so smooth thick arcs and cheap off-screen buffers conflict.

**Cost:** one `drawArc` is cheap. Polygon-approximated arcs are not.

### 4b. Straight / rectangular bars — **easy**

`fillRectangle` / `fillRoundedRectangle`, optionally clipped. Cheapest of the
four. Trivially expressible and trivially cheap in `onPartialUpdate`.

### 4c. Sequence of discrete shapes filling one by one — **easy**

A loop of `fillCircle` / `fillRectangle` / `fillPolygon`. Cost is linear in
segment count; each is cheap. The generator should unroll small fixed counts and
emit a loop beyond a threshold — a nice codegen win over hand-writing.

### 4d. Tick scale with moving pointer and coloured band — **feasible, most expensive**

Composed of: ticks (`drawLine`, or `fillPolygon` for tapered), the coloured
range band (`drawArc` with pen width on round faces, `fillRectangle` on linear),
and the pointer (`fillPolygon` triangle, or `drawLine` with pen width).

Cost is dominated by tick count. For `onPartialUpdate` this is likely
too expensive to redraw wholesale; the static scale should be pre-rendered into
a `BufferedBitmap` during `onUpdate` and only the pointer redrawn under a tight
clip. **This is a good example of something a compiler can do automatically and
a hand author usually will not.**

Pointer geometry on round faces needs trigonometry the author should not have to
write — `Math.sin`/`cos` are available; the generator should emit precomputed
constant tables where the tick positions are static, trading a little memory for
per-frame CPU.

---

## 5. Interactivity — **your prompt's API level is wrong, and fr955 is excluded**

The prompt states `onTap` and `onPress` are "API level 4.2.0+ on touch devices".
The SDK disagrees. Verified by parsing `doc/Toybox/WatchUi/WatchFaceDelegate.html`:

| Method | Since | Devices | fenix8solar 47/51 | fr955 |
|---|---|---|---|---|
| `onPowerBudgetExceeded` | 2.3.0 | all | yes | yes |
| `onPress` (touch **and hold**) | **4.2.0** | **61** | yes | **yes** |
| `onTap` (touch) | **5.1.0** | **23** | yes | **NO** |
| `setSelectedComplication` | 5.1.0 | 19 | yes | no |
| `onWatchFaceConfigEdited` | 5.1.0 | 19 | yes | no |
| `getComplicationDrawable` | 5.1.0 | 23 | yes | no |

The 23 devices supporting `onTap` are the fēnix 8 family (43 mm, 47/51 mm, Pro,
Solar 47/51), Forerunner 570 42/47 mm, Forerunner 970, and similar recent
hardware. **`Forerunner® 955 / Solar` appears in the `onPress` list and does not
appear in the `onTap` list** — verified by explicit enumeration, not inference.

**Direct consequence for your stated requirement.** "Tapping a data slot cycles
it through a predefined list, like the stock Forerunner faces" is achievable on
both fēnix 8 Solar targets and **not achievable on the fr955**, which is one of
your three named devices. The closest achievable behaviour on fr955 is
touch-and-hold (`onPress`, 4.2.0). Options, for your decision:

- Cycle on **hold** everywhere — one interaction model, works on all three,
  but diverges from the stock-face feel you described.
- Cycle on **tap** where available and **hold** as the fr955 fallback — best
  per-device feel, two code paths, and the framework can generate both from one
  declaration.
- Drop fr955 from the interactive-slot feature and let it render a static slot.

Hit-testing is manual: `ClickEvent` gives coordinates and the face must own its
own regions. That is a good fit for a builder — the compiler already knows every
element's bounding box and can emit the hit-test table for free, which is
tedious and error-prone by hand.

**Simulator reliability for touch is [open]** — historically unreliable, and we
cannot test it until the device files are available.

---

## 6. On-device configuration — **supported, but far narrower than assumed**

Since **API 5.1.0**, "fēnix 8 and newer". Source:
`doc/docs/Core_Topics/Editing_Watch_Faces_On_Device.html` **[verified]**.

The native editor lets a user take a face, configure it, and save the result as
a new face in their list — **up to four configurations** per watch face.

The configuration surface is **exactly four axes, and no more**:

| Axis | What it allows |
|---|---|
| **Styles** | An enumerated list of author-defined stylistic variants, identified by number. |
| **Data** | Per-complication-slot choice of complication type. `allowAny="true"` accepts any system complication. |
| **Data Color** | **One** colour applied to data, from an author-defined list or `allowAny`. |
| **Accent Color** | **One** configurable accent colour, from a list or `allowAny`. |

Declared in resources, which is ideal for codegen:

```xml
<watchface-config>
  <styles>
    <style id="0" label="@Strings.AppName" default="true"/>
  </styles>
  <data>
    <complication id="1">
      <type default="true">Complications.COMPLICATION_TYPE_STEPS</type>
      <type>Complications.COMPLICATION_TYPE_HEART_RATE</type>
    </complication>
    <complication id="3" allowAny="true" />
  </data>
  <dataColors>
    <color label="@Strings.aqua">0x00FFFF</color>
    <color default="true">0xFFFFFF</color>
  </dataColors>
  <accentColors allowAny="true"/>
</watchface-config>
```

Read at runtime with `WatchFaceConfig.getSettings(null)`. Editing mode is
detected via options in `AppBase.onStart()`.

### Where this lands against your requirement

You asked that "colours and displayed data can be changed **from the watch
itself**, without a phone." That is supported on the fēnix 8 Solar targets — but
**not in the general form the requirement implies**:

- You get **one data colour and one accent colour**, not per-element colour
  choice. A face with "make the HR ring red and the battery arc green,
  independently, on-device" cannot be expressed through the native editor.
- Data is configurable **only through complication slots** — a slot's *type*
  changes, not an arbitrary binding. Anything you can't express as a
  complication isn't on-device configurable.
- **Max four saved configurations.**
- **fr955 is excluded entirely** (5.1.0, fēnix 8 and newer).

**Fallbacks for everything outside those four axes**, in descending fidelity:
on-device settings menus (`Properties` + a generated settings view), phone-side
`resources/settings/settings.xml` pushed via Garmin Connect, and
`Application.Storage` for state the user changes by interacting with the face
itself (e.g. the tapped-slot selection from §5).

Note the settings caching trap already documented in the sibling Dashboard
project: `onSettingsChanged` fires only for Garmin Connect pushes, not on-watch
edits, so any property write needs explicit cache invalidation.

**Framework consequence.** The config schema in ADR 1.3 must model these as
*three distinct capability tiers* — native editor / on-device menu / phone
settings — and the compiler must be able to tell an author at build time "this
property cannot be edited on-device on your target set", rather than letting
them discover it on the wrist.

---

## 7. Custom fonts

### Bitmap fonts are the only way to ship your own typeface

Connect IQ has no runtime rasteriser for author-supplied fonts. Custom fonts
ship as an AngelCode BMFont `.fnt` plus a PNG atlas, declared in
`resources/fonts/`. Source:
`doc/docs/Connect_IQ_FAQ/How_Do_I_Use_Custom_Fonts.html` **[verified]**, which
names BMFont as the tool.

Two hard constraints from that page:

- **One colour per font.** *"Connect IQ supports only one color in custom fonts.
  This is because the font's PNG is a grayscale image and therefore has only one
  channel."* Multi-colour text requires drawing two overlaid fonts (a border
  mask and a fill mask). The schema should either expose that as an explicit
  two-layer text element or refuse to promise multi-colour text.
- **Fixed pixel size.** A bitmap font is baked at one size, so a design that
  targets 260×260 and 280×280 needs *two* generated font resources selected by
  resource qualifier. This is exactly the drift risk in the sibling Dashboard
  project, whose clock font is baked for 260×260 while `fenix8solar51mm` is
  280×280.

Glyph subsetting is the main memory lever and is fully automatable: the compiler
knows every string and format pattern in the layout, so it can compute the exact
used-glyph set (often just `0123456789:` plus a few letters) and bake only
those. **This is one of the clearest wins for a builder over hand-authoring.**

### But scalable *system* fonts do exist — and cover all three targets

`Graphics.getVectorFont({:face, :size, :font, :scale})` returns a
`Graphics.VectorFont`, since **API 4.2.1** **[verified]**. `:font` and `:scale`
are 5.1.0+. Returns `null` when unavailable, so it must be null-checked.

**All three target devices are in the supported list**, including
`Forerunner® 955 / Solar`. **[verified]**

Crucially, these are **device-resident faces selected by name**, not fonts you
supply. The per-device font tables in `doc/docs/Device_Reference/*.html` list the
available scalable faces — on `fenix8solar47mm` these include `BionicSemiBold`,
`RobotoCondensedBold`, `RobotoCondensedRegular`, `RobotoCondensedRegularItalic`,
`NotoSansSCMedium`, `KosugiRegular`, `NanumGothicExtraBold`, `PridiSemiBoldGarmin`,
and the Noto Arabic/Armenian/Hebrew families.

So the accurate statement — correcting a claim in the sibling project's
`CLAUDE.md` — is: *Connect IQ cannot rasterise a font you ship, but it can scale
fonts the device already has.* Vector fonts also unlock `drawAngledText` and
`drawRadialText`, which have no bitmap-font equivalent.

**Framework consequence.** Text should be a three-way choice resolved per
device: fixed system font (cheapest, zero bytes), scalable system vector font
(free, resolution-independent, 4.2.1+), or a generated subsetted bitmap font
(costs memory, but the only way to get a specific typeface). The compiler can
pick automatically and fall back where a device lacks vector support.

### Per-device, per-language font metrics are published

The device reference pages give, for every device *and every language*, each
`FONT_*` symbol's face, **pixel size**, and underlying font file — e.g. on
`fenix8solar47mm` for Korean, `FONT_XTINY` is NanumGothic-Bold at 21 px,
`FONT_MEDIUM` at 38 px. Extracted into `docs/research/data/devices/*.json`.

This means **the compiler can predict text extents at build time** without
running the device, which makes "does this label overflow its slot on this
device in this language?" a static check. That is a significant validation and
preview-fidelity win, and it is not something hand authors can easily do.

### Licensing

Baking a typeface into a `.fnt`/PNG atlas is font *embedding* and is governed by
the font's licence. SIL OFL permits it; many commercial licences do not, and
some require the reserved-name rule. The builder should require an explicit
licence declaration per font asset and should propagate it into the packaged
output. Not legal advice; flagged as a product requirement.

---

## Summary of feasibility

| Feature | Verdict |
|---|---|
| Icons | **Yes** — prefer drawn primitives; bitmaps affordable only in small numbers |
| Data values | **Yes** — but every field nullable; permissions fail silently |
| Complications | **Yes** — 4.2.0, should be first-class |
| Bars, discrete shapes | **Yes** — cheap |
| Arc/ring | **Yes, constrained** — no filled arc exists; pen-width only |
| Tick + pointer + band | **Yes** — most expensive; needs BufferedBitmap strategy |
| Tap to cycle | **Partial** — 5.1.0/23 devices; **not on fr955** |
| Hold to launch | **Yes** — 4.2.0/61 devices, all three targets |
| On-device config | **Partial** — 4 fixed axes only; **not on fr955** |
| Custom bitmap fonts | **Yes** — single colour, fixed size, subsettable |
| Scalable system fonts | **Yes** — 4.2.1, all three targets, but device faces only |
