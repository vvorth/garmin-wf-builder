# 0.1 — Platform capabilities and hard constraints

**SDK under study:** Connect IQ 9.2.0 (released 9 June 2026), Linux build
`connectiq-sdk-lin-9.2.0-2026-06-09-92a1605b2.zip`.
**Primary source:** the SDK's own offline documentation, `$CIQ_SDK/doc/docs/…`,
which is the version-pinned copy of what `developer.garmin.com/connect-iq`
serves. Paths below are relative to the SDK root. Every API-level claim is
traceable to `doc/Toybox/**` or `bin/api.debug.xml`.

Confidence markers used throughout: **[verified]** = read directly from the SDK
on disk; **[docs]** = stated in Garmin prose but not independently exercised;
**[open]** = unresolved, see `00-summary.md`.

---

## 1. Watch face lifecycle

A watch face is an `Application.AppBase` whose initial view is a
`WatchUi.WatchFace`. `WatchFace` extends `WatchUi.View`, so it inherits
`onLayout` / `onShow` / `onUpdate` / `onHide`.

| Callback | Meaning | API level | Source |
|---|---|---|---|
| `View.onUpdate(dc)` | Full redraw. Once per minute in low power; once per second in high power. | 1.0.0 | `doc/Toybox/WatchUi/View.html` |
| `WatchFace.onPartialUpdate(dc)` | Called each second in low power **on MIP devices that support it**, under a strict power budget. | 2.3.0 | `doc/docs/Connect_IQ_FAQ/How_Do_I_Get_My_Watch_Face_to_Update_Every_Second.html` |
| `WatchFace.onEnterSleep()` | Device entering low-power mode. | 1.0.0 | `doc/Toybox/WatchUi/WatchFace.html` |
| `WatchFace.onExitSleep()` | Device leaving low-power mode (wrist raise). | 1.0.0 | same |

**The redraw contract.** Garmin's guidance is that a watch face must fully
render on every `onUpdate`; nothing of the previous frame is guaranteed to be
preserved. There is no legal "skip this frame" optimisation — a face that
returns early without drawing can leave the screen blank on some devices.
Framework consequence: the generated runtime must be stateless per frame, and
all caching must be of *data*, never of *rendered output*. **[docs]**

`System.println` / `System.print` are documented as **not executing** inside
`onPartialUpdate` on device (they still work in the simulator). Generated
diagnostics must not rely on them there. **[verified]** — stated in the FAQ
source above.

---

## 2. The partial-update power budget

This is the single most important runtime constraint for a generated face, and
it behaves worse than most people assume.

From `How_Do_I_Get_My_Watch_Face_to_Update_Every_Second.html` **[verified]**:

> The `onPartialUpdate()` method has very strict limits set on execution time,
> and must complete within these limits. If the execution limit is exceeded, the
> `onPowerBudgetExceeded()` method will be invoked in the `WatchFaceDelegate`,
> and **partial updates will stop executing for the remainder of the app
> life-cycle.**

Three consequences the framework must design around:

1. **Failure is permanent, not transient.** One overrun disables per-second
   updates until the face is reloaded. A generated face must therefore be
   conservative by construction, not merely "usually fast".
2. **The budget is on execution time**, measured by the firmware. The exact
   numeric allowance is per-device and is not published in the offline docs —
   it lives in the device files we do not yet have. **[open]**
3. **Clipping is charged per region, not per pixel:**
   > The `Dc.setClip()` method is used to restrict the rendering window […]
   > **All pixels in the active clipping area are considered modified every time
   > any pixel in the clip is modified.**

   So a clip rectangle's *area* is the cost unit. A generated face should emit
   the tightest possible clip around the seconds field, and the compiler can
   compute that rectangle statically from the layout IR and the font metrics.

`Graphics.BufferedBitmap` is the documented escape hatch: render complex
graphics off-screen during `onUpdate` (not time-limited) and blit them during
`onPartialUpdate`. **[docs]**

`WatchFaceDelegate.onPowerBudgetExceeded(powerInfo)` exists and is confirmed
present in `bin/api.debug.xml`. **[verified]**

---

## 3. Memory limits

Watch faces get **far less memory than apps**, and the amount is per-device.
Extracted mechanically from `doc/docs/Device_Reference/*.html` by
`tools/research/extract_device_db.py` into `docs/research/data/`.

Distribution of the **Watch Face** memory limit across all 164 documented
devices:

| Limit | Devices |
|---|---|
| 131072 B (128 KB) | 62 |
| 98304 B (96 KB) | 38 |
| 65536 B (64 KB) | 19 |
| 524288 B (512 KB) | 10 |
| 114688 B (112 KB) | 3 |
| 49152 B (48 KB) | 2 |
| 135168 B (132 KB) | 1 |
| 1048576 B (1 MB) | 1 |
| *no Watch Face app type* | 28 |

For contrast, on `fenix8solar47mm` the same device allows 786432 B for a Watch
App and 131072 B for a Watch Face — **a watch face gets 1/6th the memory of an
app on the same hardware.** **[verified]**

The three target devices are uniform:

| Device | Watch Face limit | Watch App limit |
|---|---|---|
| `fenix8solar47mm` | 131072 B | 786432 B |
| `fenix8solar51mm` | 131072 B | 786432 B |
| `fr955` | 131072 B | 786432 B |

**28 devices have no Watch Face entry at all** and cannot host a watch face
(Edge computers, handhelds, some golf units). The framework's device database
must treat "can this device even run a watch face" as a first-class predicate.

What consumes the budget: compiled bytecode, resources linked into the `.prg`
(bitmaps, fonts, strings), and the live object graph at runtime. Bitmaps and
custom fonts are the dominant fixed cost — a full-screen 8-bit bitmap at
260×260 is 67 600 B, over half the entire 128 KB budget, which is why drawn
primitives beat bitmaps for a memory-constrained generated face. **[docs +
arithmetic]**

Precise accounting of bytecode size per construct is **[open]** until we can run
`monkeyc --build-stats` against a real device target.

---

## 4. AMOLED vs MIP

Source: `doc/docs/Connect_IQ_FAQ/How_Do_I_Make_a_Watch_Face_for_AMOLED_Products.html`
**[verified]**. These are genuinely different rendering contracts, not a styling
difference.

**Burn-in protection** applies only while a Connect IQ watch face is in the
foreground *and* the system has entered sleep mode.

| Generation | Rule |
|---|---|
| Original Venu | More than **10% of pixels on**, or **any pixel on longer than 3 minutes** → the system shuts the screen off. |
| Venu 2 and later | Less than **10% of the screen's luminance**. |

A pixel counts as "on" when rendering any colour other than black; black is the
only "off" colour.

**The decisive difference for the framework:**

> With MIP screens, you can use [`onPartialUpdate`] to update a portion of the
> screen every second. **With AMOLED screen, this is no longer allowed.**

So the low-power rendering path is structurally different per display
technology, not merely tuned. The IR must carry a distinct always-on
representation, and codegen must emit different low-power branches.

Detection APIs, all confirmed in `api.debug.xml` **[verified]**:

- `DeviceSettings.requiresBurnInProtection` — is protection enforced.
- `System.getDisplayMode()` → `DISPLAY_MODE_HIGH_POWER` / `DISPLAY_MODE_LOW_POWER`
  / `DISPLAY_MODE_OFF`. Used for the Venu-2-and-later luminance rule.

Garmin's own layout advice is explicit and unusually blunt ("could you, like,
not use them? Please?"): maximise black, put gradient dark ends at the outer
edges.

**This is statically checkable.** Both the 10%-pixels rule and the 10%-luminance
rule can be estimated at build time by rasterising the always-on layout in the
preview renderer and integrating. That makes it a strong candidate for the
Phase 1.4 linter, and it is one of the few places where a builder can offer
something hand-written Monkey C does not.

Testing: the simulator ships a burn-in simulation — `File → View Screen Heat
Map` — which compresses a 24-hour run. Enabled only when simulating a watch
face on a protected device. **[docs]**

Target-device relevance: all three of your targets are 64-colour MIP, so AMOLED
is a portability concern rather than an immediate one — but 74 of 164 documented
devices report 65536 colours, so it is most of the addressable market.

---

## 5. Graphics primitives

Complete `Graphics.Dc` instance method set, read from
`doc/Toybox/Graphics/Dc.html` **[verified]**:

**Draw (outline):** `drawArc`, `drawBitmap`, `drawCircle`, `drawEllipse`,
`drawLine`, `drawOffsetBitmap`, `drawPoint`, `drawRectangle`,
`drawRoundedRectangle`, `drawScaledBitmap`, `drawText`, `drawAngledText`,
`drawRadialText`

**Fill:** `fillCircle`, `fillEllipse`, `fillPolygon`, `fillRectangle`,
`fillRoundedRectangle`

**State:** `setColor`, `setPenWidth`, `setAntiAlias`, `setBlendMode`, `setFill`,
`setStroke`, `setClip`, `clearClip`, `clear`

**Metrics:** `getWidth`, `getHeight`, `getFontHeight`, `getTextDimensions`,
`getTextWidthInPixels`

### The single most important gap: there is no filled arc

`grep -rn "fillArc\|fillSector\|drawSector"` across the entire `doc/Toybox`
tree returns **nothing**. **[verified]**

Connect IQ has `drawArc` and `ARC_CLOCKWISE` / `ARC_COUNTER_CLOCKWISE`
(API 1.2.0) but **no filled-sector or filled-annulus primitive at all**. A thick
progress ring must be built from `setPenWidth` + `drawArc`. That has real
consequences the schema must not paper over:

- Ring thickness is limited to what pen width renders acceptably.
- Pen-width arcs have square-ish ends and no mitre control, so the "cap" style
  of a progress ring is not freely choosable.
- A true annulus with independent inner/outer radii, or a gradient sweep, must
  be approximated — typically by many small `fillPolygon` quads, which costs
  both bytecode and per-frame time.

This is exactly the sort of thing a declarative format can over-promise. See
`docs/limitations.md` when it is written.

### Anti-aliasing

`setAntiAlias(enabled)` exists but is **device-gated** — the docs enumerate
supported devices explicitly, so it must be behind a `Graphics.Dc has
:setAntiAlias` check. **[verified]**

One important restriction, quoted directly: *"This method is not supported for a
`BufferedBitmap` that has a palette."* Since palette'd buffered bitmaps are the
memory-efficient choice on MIP, **anti-aliasing and cheap off-screen buffers are
mutually exclusive** in the common case. The framework must pick per element.

### Colour depth

From the extracted device database **[verified]**:

| `Display Colors` | Devices | Interpretation |
|---|---|---|
| 65536 | 74 | 16-bit, typically AMOLED |
| 64 | 68 | MIP, 2 bits/channel |
| 14 | 9 | legacy palette |
| 8 | 3 | legacy palette |
| 2 | 10 | 1-bit monochrome |

The 64-colour MIP palette means each channel is one of `0x00`, `0x55`, `0xAA`,
`0xFF`; anything else is dithered by the firmware and looks grainy. All three
target devices are 64-colour. **Palette legality is compile-time checkable** and
belongs in the linter.

`BitmapTexture` via `setFill`/`setStroke` is available for textured fills.
`setBlendMode` exists for compositing. Both are **[open]** as to device coverage.

---

## 6. Layouts and resources

Resources are XML under `resources/`, compiled into a generated `Rez` symbol
tree (`Rez.Strings.AppName`, `Rez.Fonts.Foo`, `Rez.Drawables.Bar`). Every
referenced `Rez.*` symbol must exist or the build fails. The schema is shipped
in the SDK as `bin/resources.xsd`, which the generator can validate its emitted
XML against before invoking `monkeyc`. **[verified]** — file present on disk.

Resource qualifiers work by directory naming, e.g.
`resources-round-260x260/`, letting one project carry per-shape/per-size
variants. Combined with jungle `resourcePath` manipulation this is the
per-device adaptation mechanism. See `03-toolchain.md`.

Layout XML vs. drawing in code: layouts are declarative positioning of
`Drawable`s. For a *generated* face, layout XML is largely redundant — the
generator already knows every position and can emit direct `dc.*` calls, which
avoids the `Rez`-layout object graph at runtime and saves memory. Recommendation
deferred to ADR 1.2, but the evidence points to emitting drawing code.

### Screen shapes

The device database reports four shapes, one more than the prompt assumed
**[verified]**:

| Shape | Devices |
|---|---|
| `round` | 115 |
| `rectangle` | 37 |
| `semi-octagon` | 8 |
| `semi-round` | 4 |

Resolutions span 148 px to 480 px wide. The most common are 240×240 (38),
390×390 (20), 260×260 (13), 454×454 (12).

Note that `fenix8solar51mm` is **280×280**, not 260×260 like the 47 mm — so even
within one product family a single fixed-pixel design does not transfer. This is
direct evidence for a relative/anchored coordinate system rather than absolute
pixels.

---

## Sources

- Connect IQ SDK 9.2.0, offline docs (`doc/docs/`, `doc/Toybox/`), downloaded
  from `https://developer.garmin.com/downloads/connect-iq/sdks/sdks.json`
- `doc/docs/Connect_IQ_FAQ/How_Do_I_Get_My_Watch_Face_to_Update_Every_Second.html`
- `doc/docs/Connect_IQ_FAQ/How_Do_I_Make_a_Watch_Face_for_AMOLED_Products.html`
- `doc/Toybox/Graphics/Dc.html`, `doc/Toybox/Graphics.html`
- `doc/docs/Device_Reference/*.html` (164 devices) → `docs/research/data/`
- `bin/api.debug.xml` — symbol existence checks
