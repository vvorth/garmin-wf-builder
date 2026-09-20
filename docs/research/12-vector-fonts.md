# 12 — Vector fonts: can a watch face ship its own TTF?

Asked directly: can a `.ttf`/`.otf` travel *inside* the built `.prg` and be
rasterised by the watch at draw time, instead of being pre-baked to a bitmap
sheet at build time, on the devices that support it?

**No.** Connect IQ has exactly two font paths, and neither one accepts an
app-supplied outline font. What it does have — `Graphics.getVectorFont()` — is
scalable text drawn from **fonts already resident on the watch**, from a fixed
catalogue of Garmin's own faces. That is a genuinely useful feature, and this
document models it, but it is not "ship your own font".

Every behavioural claim below is marked **VERIFIED** (checked against the SDK
files in `$CIQ_SDK`, the installed device definitions, or a probe that actually
built) or **UNVERIFIED**, per `docs/CLAUDE.md`. The probe is
`docs/research/probes/vector-fonts/`.

---

## 1. The two font paths, and why neither ships a TTF

**VERIFIED.** The whole surface, enumerated from the SDK-wide symbol table
(`$CIQ_SDK/bin/api.debug.xml`, every function whose name contains `Font`):

```
getFontAscent   parent="Graphics"      getFontHeight  parent="Dc"
getFontDescent  parent="Graphics"      getFontHeight  parent="Graphics"
getVectorFont   parent="Graphics"      setFont        parent="Text"
                                       setFont        parent="TextArea"
```

There is **no API that takes font bytes** — no load-from-`BLOB`, no
load-from-file, no `Media`/`Storage` route into the font system. A font
reaches the screen in one of exactly two ways:

1. **A compiled-in bitmap resource.** `WatchUi.loadResource(Rez.Fonts.X)`
   over a `<font>` resource. The resource compiler's own XSD
   (`$CIQ_SDK/bin/resources.xsd`, `fontType`) accepts only:

   ```xml
   <xs:complexType name="fontType">
       <xs:attribute name="id"          type="xs:string"  use="required" />
       <xs:attribute name="filename"    type="xs:string"  use="optional" />
       <xs:attribute name="filter"      type="xs:string"  use="optional" />
       <xs:attribute name="antialias"   type="xs:boolean" use="optional" />
       <xs:attribute name="scope"       type="uiScopeOptions" use="optional" />
       <xs:attribute name="personality" type="xs:string"  use="optional" />
   </xs:complexType>
   ```

   and `filename` is documented as a "BMFont generated .fnt file"
   (`$CIQ_SDK/doc/docs/Core_Topics/Resources.html` §Fonts: "The resource
   compiler reads fonts in TXT or PNG format"). The compiler backs this up:
   `com/garmin/monkeybrains/resourcecompiler/fonts/FontProcessor.processFont`
   takes a `BMFont` — the parsed `.fnt` — and nothing else. There is no
   TrueType rasteriser anywhere on that path.

2. **A device-resident scalable face**, via `Graphics.getVectorFont()`. This
   is the "vector font" feature, and §2 is about it.

The SDK says the same thing in prose, and is worth quoting because it also
closes the door on the most attractive workaround
(`$CIQ_SDK/doc/docs/Core_Topics/Graphics.html` §Scalable Fonts):

> Scalable fonts work with `Dc.drawText()` but can also be used with the
> `Dc.drawAngledText()` and `Dc.drawRadialText()`. **These APIs only support
> scalable fonts and do not support custom fonts loaded as resources.**

So the two paths do not meet in the middle: an app-supplied font can never be
drawn rotated or along an arc, and a rotatable font can never be app-supplied.

### 1.1 The `TTFont` class in the compiler is not what its name suggests

**VERIFIED**, and worth recording because the name is a trap for the next
person who greps the jar. `monkeybrains.jar` contains
`com/garmin/monkeybrains/resourcecompiler/fonts/TTFont.class`, which looks
like TrueType support in the resource compiler. It is not. Its string
constants (`javap -p -constants`) give the whole game away:

```java
TTF_FORMAT   = "'#<font name>:<size>', '#<font name>,<font name>,...:<size>' for a list of font face names"
GRAPHICS_GET_VECTOR_FONT = "Graphics.getVectorFont"
CAST_GRAPHICS_VECTOR_FONT = "as Graphics.VectorFont"
OPTION_FACE  = ":face"
OPTION_SIZE  = ":size"
```

It is a **layout-XML reference syntax**: writing `font="#RobotoCondensedBold:24"`
on a layout element makes the resource compiler emit a
`Graphics.getVectorFont({:face => ..., :size => ...})` call. It names a face
the *device* has; it never reads a font file. Its validation
(`TTFont.validateTTFont`) calls `ResourceCompilerContext.hasTTFontSupport()`
and fails the build with `Vector fonts are not supported by device '%s'` —
which is the build-time gate described in §3.

---

## 2. What `getVectorFont` actually is

**VERIFIED** (`$CIQ_SDK/doc/Toybox/Graphics.html`,
`$CIQ_SDK/bin/api.debug.xml`).

```
Graphics.getVectorFont(options as Graphics.VectorFontOptions) as Graphics.VectorFont or Null

VectorFontOptions as {
    :face  as Lang.String or Lang.Array<Lang.String>,   # face name, or acceptable alternatives
    :size  as Lang.Numeric,                             # height in pixels, positive
    :font  as Graphics.FontDefinition or Graphics.VectorFont,   # CIQ 5.1.0+
    :scale as Lang.Float                                        # CIQ 5.1.0+
}
```

- **Since API 4.2.1** (the class and the method both; the Core Topics table
  says 4.2.2 for the same method — the SDK is internally inconsistent by one
  patch level, and 4.2.1 is what `api.debug.xml` records).
- `:size` is **in pixels**, any positive value — this is the real prize. One
  face renders at any size with no re-baking and no per-size sheet.
- Returns **null**, rather than throwing, when the device cannot supply the
  face. Callers must null-check; the SDK's own sample does.
- `:face` takes an **array of acceptable faces**, tried in order — a built-in
  fallback chain.
- `:font`/`:scale` (CIQ 5.1.0+) scale an existing font rather than naming one.

The faces are Garmin's, fixed in the firmware. The SDK's `TrueTypeFonts`
sample (`$CIQ_SDK/samples/TrueTypeFonts/source/TrueTypeFontsApp.mc`) hardcodes
the complete vocabulary as `ALL_FACE_NAMES` — 27 names — and discovers which
exist by asking for each one and keeping the non-null answers:

```monkeyc
var font = Graphics.getVectorFont({:face => face, :size => 16});
if (font != null) { names.add(face); }
```

That is the only runtime discovery mechanism: there is no "list the faces"
call.

---

## 3. Modelling the requirement: four independent gates

This is the part that matters for a builder that targets the fleet rather
than three watches. Vector-font availability is **not** one condition, and in
particular it is **not** an API-level test. Four things must all hold, and
they are checked in different places:

| # | Gate | Where it is decided | How a build checks it |
|---|---|---|---|
| 1 | The `Graphics.getVectorFont` symbol exists on the device | per device, **not** per API level | `<id>.api.debug.xml` — `Device.has_symbol("Graphics.getVectorFont")` |
| 2 | The device publishes ≥1 scalable face | per device | `simulator.json` entries with `type: "system_ttf"` |
| 3 | The *specific* face is one of them | per device | the `name` field of those entries |
| 4 | The call still returns non-null | runtime | `if (font != null)` |

Gate 1 is `CLAUDE.md` constraint 6 in its purest form. **VERIFIED**: `fenix6`
and `fr245` have `name="getVectorFont"` **zero** times in their own
`api.debug.xml`, while `fenix7pro` has it once. An API-level comparison would
get this wrong in both directions.

### 3.1 Two machine-readable sources, and they agree

**VERIFIED.** The per-device face list is available offline, two ways, with no
scraping:

1. **`simulator.json`** (`~/.Garmin/ConnectIQ/Devices/<id>/simulator.json`):
   in the `ww` font set, entries carry `type: "ttf"` (a *system* font the
   firmware renders from an outline — `xtiny`, `numberHot`, …, not
   app-addressable by face name) or **`type: "system_ttf"`** (the scalable
   faces exposed to `getVectorFont`, whose `name` **is** the `:face` string).
   On `fenix8solar47mm`, the `system_ttf` names are `RobotoCondensedBold`,
   `RobotoCondensedRegular`, `RobotoCondensedRegularItalic`, `BionicSemiBold`,
   plus nine CJK/Thai/Arabic/Hebrew/Armenian faces.

2. **The scraped device reference** (`docs/research/data/devices/<id>.json`,
   all 164 devices): `fonts.default.scalable` is a dict whose **keys** are
   exactly those `:face` names, each with the `face`/`font` columns from
   Garmin's published table.

The two agree on `fenix8solar47mm`, `fenix8solar51mm` and `fr955` (checked
name by name), and both agree with the sample's `ALL_FACE_NAMES`. `wfb`
already reads `simulator.json`'s `ww` block
(`Device._simulator_ww_fonts`, `wfb/devices.py:395`) but currently keeps only
the fixed bitmap fonts; the `system_ttf` rows are right there beside them.

### 3.2 How much of the fleet has it: 44 of 136

**VERIFIED**, computed over all 164 scraped device files:

| | devices |
|---|---|
| total devices in the reference | 164 |
| **cannot run a watch face at all** | 28 |
| can run a watch face | **136** |
| …and publish ≥1 scalable face | **44** |
| …and publish none | **92** |

So **two thirds of the watch-face-capable fleet has no vector fonts at all**.
This is the single most important number in this document: vector fonts can
only ever be an *enhancement with a bitmap fallback*, never the mechanism.

The 44:

```
approachs7042mm, approachs7047mm, bounce2, d2mach1, d2mach2, d2mach2pro,
descentmk343mm, descentmk351mm, enduro3, epix2, epix2pro42mm, epix2pro47mm,
epix2pro51mm, fenix7, fenix7pro, fenix7pronowifi, fenix7s, fenix7spro,
fenix7x, fenix7xpro, fenix7xpronowifi, fenix843mm, fenix847mm, fenix8pro47mm,
fenix8solar47mm, fenix8solar51mm, fenixe, fr165, fr165m, fr265, fr265s,
fr57042mm, fr57047mm, fr955, fr965, fr970, marq2, marq2aviator, venu3,
venu3s, venu441mm, venu445mm, venux1, vivoactive6
```

### 3.3 The face catalogue is small, Garmin's, and uneven

**VERIFIED.** Latin-script scalable faces, by how many watch-face-capable
devices publish each:

| face | devices | | face | devices |
|---|---|---|---|---|
| `RobotoCondensedBold` | 41 | | `BionicMedium` | 7 |
| `RobotoCondensedRegular` | 41 | | `RobotoMedium` | 7 |
| `BionicBold` | 34 | | `YantramanavRegular` | 5 |
| `RobotoRegular` | 20 | | `RobotoCondensedRegularItalic` | 4 |
| `Swiss721Bold` | 19 | | `ExoSemiBold` | 3 |
| `Swiss721Regular` | 19 | | `BionicSemiBold` | 3 |
| `RobotoItalic` | 18 | | `RobotoBlack` | 1 |
| | | | `TomorrowBold` | 1 |

Only `RobotoCondensed` Bold/Regular is close to dependable (41 of the 44).
Everything else needs a fallback chain, which is exactly why `:face` accepts
an array. The remaining faces are CJK, Thai, Arabic, Hebrew and Armenian
script fonts, already catalogued as deliberately unmapped in
`wfb/fonts/registry.json` and `docs/research/10-system-fonts.md` §6.

**There is no way to add a face to this list.** A design that wants Chivo
Mono, Dynalight or Questrial — the typefaces this project's own examples use —
cannot have them as vector fonts, on any device, ever.

---

## 4. What it costs, measured

**VERIFIED** by `docs/research/probes/vector-fonts/`, three builds that differ
only in one class, SDK 9.2.0, `-O 3z`, `--typecheck strict`, `-w -l 3`,
**warning-free on every device below**. Figures are `--build-stats 0`
foreground data/code, plus total `.prg` size.

`fenix8solar47mm` (identical on `fenix8solar51mm` and `fr955`):

| variant | data | code | `.prg` | vs. baseline |
|---|---|---|---|---|
| baseline — system bitmap `FONT_NUMBER_HOT` | 429 B | 304 B | 90,684 B | — |
| **vector** — `getVectorFont` at 68 px, guarded | 461 B | 400 B | 90,940 B | **+32 / +96 / +256** |
| **baked** — BMFont sheet, 68 px, 11 glyphs | 491 B | 359 B | 91,884 B | **+62 / +55 / +1,200** |
| baked — same, 95-glyph Latin set | 491 B | 359 B | 96,476 B | +62 / +55 / **+5,792** |

And the negative control — the *same guarded vector source* built for two
devices that have no vector fonts at all:

| device | variant | data | code | `.prg` |
|---|---|---|---|---|
| `fenix6` | baseline | 972 B | 413 B | 90,476 B |
| `fenix6` | vector (guarded, falls back) | 978 B | 458 B | 90,620 B |
| `fr245` | baseline | 972 B | 413 B | 90,476 B |
| `fr245` | vector (guarded, falls back) | 978 B | 458 B | 90,620 B |

Three things follow, and the third is the one that changes the conclusion:

1. **One source can serve the whole fleet.** The `Graphics has :getVectorFont`
   guard plus a null check compiles warning-free on devices where the symbol
   does not exist, and costs **+6 B data / +45 B code** to carry there. This
   is the `has_symbol` discipline of constraint 6d working as designed.
2. **Growing the glyph set is what costs**, not the mechanism: 11 glyphs at
   68 px is +1,200 B of `.prg`, and 95 glyphs is +5,792 B. A vector font is
   flat regardless of how many characters get drawn.
3. **But the baked sheet does not land in the 128 KB.** Measured data and code
   were *identical* (491/359) for the 11-glyph and 95-glyph builds — only the
   `.prg` grew. That matches the SDK: since API 4.0.0 "when you load a bitmap
   or font at runtime, the resource will load into the graphics pool"
   (`Core_Topics/Graphics.html`), which is the separate 1 MB pool of
   constraint 11, not the watch-face budget. And `.prg` size is not scarce:
   `maxPrgFilespace` is **67,108,864 B** on every installed device that
   declares it.

   **UNVERIFIED:** the actual runtime heap and pool occupancy of each variant.
   That needs the simulator, which does not survive `monkeydo` here
   (`CLAUDE.md` §3). `--build-stats` measures static data and code only.

So the memory argument for vector fonts — the intuitive one, "stop shipping
bitmaps and save the budget" — **is largely wrong on modern devices**, which
are precisely the devices that have vector fonts. The bitmap sheet is already
out of the tight budget on every device that could have used a vector font
instead.

---

## 5. Feasibility for `wfb`

### 5.1 What the question was, and the honest answer

Shipping a TTF inside the `.prg` for on-watch rasterisation is **impossible**,
not merely unimplemented, on every Garmin device. The build-time bake in
`wfb/fonts/bmfont.py` is not a workaround for a missing feature; it is the
only mechanism the platform has for a font the author chose.

### 5.2 What adopting `getVectorFont` would actually buy

Ranked by what it is worth, not by how it sounds:

1. **Rotated and curved text** (`Dc.drawAngledText`, `Dc.drawRadialText`),
   which is **impossible** with a baked font — the SDK refuses it explicitly
   (§1). This is a capability the project does not have and cannot otherwise
   get: `docs/limitations.md` already records "a bitmap font cannot turn, so
   only the anchor turns" for analog text parts. Text around the bezel, or a
   label that follows a hand, needs this.
2. **Size at runtime rather than at build time** — a font whose size responds
   to a `config:` choice, or one face used at six sizes without six sheets.
   Today each size is its own baked resource.
3. **`.prg` filespace**, which is abundant, and **graphics-pool pressure**,
   which is real but rarely binding at 1 MB.

What it costs: the author gives up the typeface. Fourteen Latin faces exist,
`RobotoCondensed` is the only dependable one, and nothing can be added.

### 5.3 The shape that was built (plan 11)

**Built, not merely sketched: `docs/plans/11-vector-text.md` is the design
record, and `docs/format.md`'s `fonts:`/`curve:` sections are the shipped
reference.** A `fonts:` entry can now name a **second kind of font**,
resolved per device: `face:` instead of `source:`, reached through
`Graphics.getVectorFont` at draw time with nothing rasterised for it at
build time. A `text` element gains `curve: {style: angled | radial, ...}`
to bend it along a line or around a circle through
`Dc.drawAngledText`/`Dc.drawRadialText`, the only way to get rotated or
curved text at all.

```yaml
fonts:
  clock:
    source: assets/ChivoMono-Bold.ttf    # unchanged: always baked
    size: 22%r
  bezel:
    face: [RobotoCondensedBold, RobotoCondensedRegular]   # device-resident
    size: 18%r
    if_unavailable: hide                  # default: error
```

**This section's own earlier sketch proposed a `fallback:` to a baked font
on the 92 devices with no scalable face at all. That was explicitly
rejected by the user, and it is not what shipped.** A design that asks for
a face a target does not have is a build error (`if_unavailable: error`,
the default), naming the device, the requested face(s), and what that
device actually publishes; an author who wants the element optional says so
in one word, per element or per font (`if_unavailable: hide`). The reasons,
weighed and decided before any code was written:

* **A silent fallback hides a real gap.** Swapping a baked sheet in for a
  missing vector face keeps the *element* on screen but changes its
  typeface, size behaviour and (for a curved element) its very shape
  without the build ever saying so — the opposite of this project's
  "warning-free means actually correct" bar.
* **It only ever half-works anyway.** A `fallback:` could keep a plain
  upright reading legible, but `curve:`'s whole point — rotation — has no
  baked equivalent at all (§1); the fallback would silently turn a curved
  element into an upright one, a layout change bigger than a typeface swap.
* **One word already says what a fallback would have tried to say.**
  `if_unavailable: hide` gets the same outcome — the design still builds,
  the element just is not there on the devices that lack it — without a
  second font, a second measured extent, and a second rendering path to
  keep in sync with the first.

What the compiler actually does, matching §3's four gates: resolves `face:`
(a name, or a list tried in author order) against each target device's
`system_ttf` names at build time (gates 2/3), independent of any element's
`curve:` — `Graphics.getVectorFont` is constructed once per font name in
the shared view, not once per element; emits a `Graphics has
:getVectorFont` guard around that construction only when some target in the
build fails to resolve it (gate 1, the "no guard for a thing every target
has" philosophy — a design whose targets all support it generates the plain
form); and refuses `monospace:`, `glyphs:`, `align:` and `antialias:` on a
`face:` entry, since all four are properties of baking a sheet a vector
font never has. Gate 4 — `Graphics.getVectorFont` returning `null` even
when every build-time gate passed — has no build-time guard at all, because
the platform offers none: the generated code always null-checks before
drawing, identically whether `if_unavailable:` is `error` or `hide`, so
`error` is a build-time guarantee that a face was published, never a
runtime guarantee the element is on the wrist. Preview parity was
achievable exactly as predicted — `vendor/fonts/` already held Garmin's
real `RobotoCondensed-Bold.ttf`, and `wfb/fonts/registry.json` already
mapped free stand-ins for hosts without it — plus one thing this section did
not anticipate needing: `wfb preview`'s radial glyph-facing model
(`clockwise` outward, `counter_clockwise` inward) is inferred from
text-on-a-path convention and Garmin's own `TrueTypeFontsRadialText.mc`
sample, not verified on a device or simulator (neither runs in this
environment), and is recorded as an open question in `docs/format.md` and
`docs/limitations.md` rather than asserted as fact.

**What was not built in this slice:** a pattern's own `shape: text` part
cannot take `curve:` yet — only a `text` element can (plan 11 §5 slice 2,
not yet landed). The original recommendation below is otherwise exactly
what was decided: worth building for `drawAngledText`/`drawRadialText` — the
capability that is otherwise unreachable — and not as a memory measure,
which §4 shows it mostly is not; adopting it purely to swap one
straight-line text mechanism for another would have bought a worse
typeface on two-thirds of the fleet for nothing.

---

## 6. Sources

| Claim | Source |
|---|---|
| `<font>` accepts only a BMFont `.fnt` | `$CIQ_SDK/bin/resources.xsd` `fontType`; `$CIQ_SDK/doc/docs/Core_Topics/Resources.html` §Fonts |
| no font-from-bytes API | `$CIQ_SDK/bin/api.debug.xml`, all `*Font*` functions |
| angled/radial text refuses resource fonts | `$CIQ_SDK/doc/docs/Core_Topics/Graphics.html` §Scalable Fonts |
| `getVectorFont` signature, API 4.2.1, supported-device list | `$CIQ_SDK/doc/Toybox/Graphics.html`; `$CIQ_SDK/doc/Toybox/Graphics/VectorFont.html`; `$CIQ_SDK/bin/api.debug.xml` |
| `#face:size` layout syntax, `hasTTFontSupport` | `monkeybrains.jar`, `com/garmin/monkeybrains/resourcecompiler/fonts/TTFont.class`; `com/garmin/connectiq/common/devices/Device.supportsTTFont` |
| face vocabulary and runtime discovery | `$CIQ_SDK/samples/TrueTypeFonts/` |
| per-device faces | `~/.Garmin/ConnectIQ/Devices/<id>/simulator.json` (`type: "system_ttf"`); `docs/research/data/devices/<id>.json` (`fonts.default.scalable`) |
| 44/136, face counts | computed over `docs/research/data/devices/*.json` |
| all measurements | `docs/research/probes/vector-fonts/` |
