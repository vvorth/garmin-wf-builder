# 0.4 — Prior art

For each system: what the authoring model is, how data bindings are expressed,
how per-device adaptation is handled, and what went wrong.

> **The single most important structural difference, stated up front.**
> Every mature declarative watch-face format — WFF, Facer, Fitbit — relies on a
> **renderer that already ships on the device**. The author's declaration is
> interpreted at runtime by the platform. **Garmin has no such renderer.** There
> is no system component that will read a layout description and draw it. So a
> Garmin equivalent must either compile the declaration to Monkey C ahead of
> time, or ship its own interpreter *inside the 128 KB watch-face budget* and pay
> for it out of the same allowance as the design. This constrains the
> architecture far more than any schema question, and it is the core input to
> ADR 1.2.

---

## 1. Google Watch Face Format (Wear OS) — the closest analogue

**Authoring model.** Declarative XML, no executable code. Root `<WatchFace>`
with `width`/`height`/`clipShape`, one mandatory `<Scene>`, then `<Group>`
containers holding typed parts. Packaged as an ordinary AAB/APK; the Wear OS
system renderer parses and draws it.

Element vocabulary worth stealing:

| Element | Contents |
|---|---|
| `PartDraw` | `Arc`, `Ellipse`, `Line`, `Rectangle`, `RoundRectangle`; `Fill`, `Stroke`, `WeightedStroke`; `LinearGradient`, `RadialGradient`, `SweepGradient` |
| `PartText` | `Text`, `Font`/`BitmapFont`, `Template`, decorations (`Shadow`, `Outline`, `OutGlow`, `Underline`, `StrikeThrough`), `Upper`/`Lower`, `InlineImage` |
| `PartImage` | `Image`, `Images`, `Photos`, `ImageFilters`/`HsbFilter` |
| `PartAnimatedImage` | `AnimatedImage`, `SequenceImage`, `AnimationController` |
| `AnalogClock` / `DigitalClock` | `HourHand`/`MinuteHand`/`SecondHand`, `Tick`, `Sweep`, `TimeText` |
| `ComplicationSlot` | `Complication`, `Bounding`, `DefaultProviderPolicy` |
| `Transform` | `Animation` (keyframed), `Gyro` (sensor-driven) |
| `Condition` / `Variant` | state-dependent rendering, e.g. ambient mode |
| `UserConfigurations` | `BooleanConfiguration`, `ListConfiguration` |
| `Metadata`, `BitmapFonts` | versioning, font declarations |

**Data binding.** Dynamic expressions bound to attributes, with built-in data
sources for time, weather (v2+), Health Services sensors, complications, and user
configuration. Text uses `Template` with inline expression substitution.

**Per-device adaptation.** Weak. The canvas is a fixed `width`/`height`
coordinate frame and the system scales. There is no anchoring or constraint
system — this is the format's clearest gap and the place our schema should
deliberately diverge, because Garmin's device spread (148–480 px, four screen
shapes) is far wider than Wear OS's.

**Versioning.** Explicit and well handled — WFF 1/2/3/4 map to Wear OS 4/5/5.1/6
(API 33/34/35/36), and the reference marks every feature with its version. Worth
copying wholesale: our schema needs the same "which SDK level does this feature
require" annotation, since Connect IQ features are gated by both API level *and*
device.

**What went wrong — and it is instructive.** Google made WFF *mandatory*: Wear OS 5
drops the older programmatic formats, and future releases gate most complication
access behind WFF. The developer reaction was that the format cannot express
complex features, animations, or interactive designs, because declarative XML
means no executable code. The migration cost was severe — Facer's library of
500 000+ faces reportedly came through as low thousands, much of it hand-ported.

**Lesson for us.** The expressiveness ceiling of a purely declarative format is
the main risk, and Google absorbed it only because they could force migration.
We cannot and should not. Our format must have a defined, honest escape hatch —
an explicit way to drop to hand-written Monkey C for one element — or authors
will hit the ceiling and abandon the tool. This should be an ADR in Phase 1.

`google/watchface` on GitHub provides the official validator/CLI tooling and is
worth studying for how they express build-time validation (memory footprint
checks in particular).

---

## 2. Facer / Watch Face Studio / WatchMaker / Pujie Black — GUI + expressions

**Facer.** Visual canvas editor; every element has an "advanced" panel accepting
tags and expressions. Tags are `#`-delimited (`#DNOW#` = current timestamp in
seconds), combined with arithmetic and a small set of maths functions.
Hundreds of tags.

**Watch Face Studio** (Samsung) — WYSIWYG that emits WFF, with its own tag
expression system including gyro effects.

**Lessons.**

- *An interpolated-string tag language is the pattern that keeps recurring.*
  `#DNOW#`-style substitution inside text templates is easy to learn, diffs
  reasonably, and covers most real needs. Our formatting layer should look like
  this rather than like a general programming language.
- *A flat `#TAG#` namespace does not scale.* Hundreds of undiscoverable tags is
  the known failure mode. A typed, namespaced data-source catalogue with schema
  autocomplete is strictly better, and is achievable because we ship a JSON
  Schema.
- *GUI-first means the file format is an implementation detail*, and these
  formats are consequently undocumented, unstable, and not diffable. This is the
  strongest argument for the prompt's hybrid position: text canonical, GUI as a
  lossless editor over it.

---

## 3. Fitbit SDK, Pebble, AsteroidOS, ZeppOS

- **Fitbit** — SVG for layout plus JavaScript for behaviour, with a JS engine on
  device. Clean separation of structure and logic. Not available to us: Garmin
  has no on-device scripting host, and shipping one inside 128 KB is not viable.
- **Pebble** — C SDK with a layer/window model, plus community frameworks and
  the Pebble.js / Rocky.js JavaScript layers. Closest to Garmin in memory
  constraints (Pebble faces ran in tens of KB), and its "layer tree that redraws
  on invalidate" model is a good conceptual match for our IR.
- **AsteroidOS** — QML watch faces; declarative with a real property-binding
  engine underneath. Elegant, but again presumes a runtime we do not have.
- **ZeppOS** — JS-based watchface API plus a visual tool; per-device screen
  parameters passed to the app.

**Common thread.** Every one of these that achieved a pleasant authoring
experience did so by shipping a runtime. The one platform that most resembles
Garmin's constraints — Pebble — is also the one where the community mostly wrote
C by hand and used frameworks as *libraries*, not as generators. That is a
caution worth holding onto.

---

## 4. Garmin-specific attempts

**`tobwil/garmincreator`** — the closest direct precedent found: a browser
drag-and-drop editor (Next.js 14 / TypeScript / Tailwind / Zustand) that stores
designs as JSON widget definitions and generates a complete compilable Connect IQ
project via a template engine in `lib/codegen/monkeyc.ts`.

*Maturity: 0 stars, 4 commits, 4 AMOLED devices supported (FR 970/965,
fēnix 8/8S), "50+ device profiles" listed as future work.* Early-stage
experiment rather than a working tool — but its architecture (JSON design →
template codegen → real project) validates the codegen approach, and its
stalling point is instructive: **it stalled exactly at device breadth**, which
is the hard part and the reason `00-summary.md` treats the device database as a
first-class deliverable rather than a detail.

**Open-source faces rather than frameworks.** `okdar/smartarcs` (SmartArcs
Origin / Active / Trip) is a well-regarded arc-based family. `dbcm/KISSFace`,
`aurpelai/garmin-watchface-template` and `garmin/connectiq-apps` (Garmin's own
sample collection) are the other reference points.

Notably, a Garmin forum thread is titled *"Open Sourcing a watch face — Almost
nobody does it"*, which matches what the search surfaced: **there is no
established Garmin watch-face framework.** The ecosystem is hand-written Monkey C
plus per-project templates. That is simultaneously the opportunity and the
warning — nobody has done this, and the reasons may not all be accidental.

**Face It** is Garmin's own consumer-facing face customiser. It consumes Connect
IQ complications (per `doc/docs/Core_Topics/Complications.html`), which is
another reason to treat complications as first-class: publishing them makes data
available to Face It faces as well as our own.

---

## What to steal, and what to avoid

**Steal:**

- WFF's element taxonomy (`PartDraw`/`PartText`/`PartImage`, grouped, with
  `Condition`/`Variant` for mode-dependent rendering) — it is a well-shaped
  vocabulary that maps cleanly onto Garmin's `Dc` primitives.
- WFF's explicit per-feature version annotation, extended to *device* gating as
  well as API level, since Garmin needs both.
- Facer's interpolated-template formatting, but namespaced and schema-typed.
- WFF's build-time validation posture (validate memory and format before you can
  ship).

**Avoid:**

- WFF's fixed-canvas coordinate model — insufficient for Garmin's device spread.
- Facer's flat undiscoverable tag namespace.
- GUI-first design where the file format is incidental.
- Any assumption of a device-side runtime. This is the one that kills naive
  ports of the other systems' architectures.

**Design consequences carried into Phase 1:** the no-device-renderer fact drives
ADR 1.2 toward codegen; the device-spread gap drives ADR 1.3's coordinate system
toward anchors/relative units; and WFF's expressiveness backlash drives an
explicit escape-hatch ADR.

---

## Sources

- [Watch Face Format overview](https://developer.android.com/training/wearables/wff)
- [WFF WatchFace element reference](https://developer.android.com/training/wearables/wff/watch-face)
- [google/watchface (official WFF tooling)](https://github.com/google/watchface)
- [Upcoming changes to Wear OS watch faces (Android Developers Blog)](https://android-developers.googleblog.com/2025/06/upcoming-changes-to-wear-os-watch-faces.html)
- [Wear OS 5 drops support for old watch faces](https://www.androidheadlines.com/2024/07/wear-os-5-drops-support-for-old-watch-faces-only-wff-allowed.html)
- [Wear OS watch face complications changes](https://9to5google.com/2024/02/27/wear-watch-face-complications/)
- [Wear OS 6 / Facer return](https://www.androidcentral.com/apps-software/wear-os/wear-os-6-will-bring-facer-back-onto-android-watches)
- [Facer Creator — Expressions](https://help.facercreator.io/hc/en-us/articles/4412585031963-Expressions)
- [Facer Creator — Tags](https://help.facercreator.io/hc/en-us/articles/4412565593755-Tags)
- [Watch Face Studio (Samsung)](https://developer.samsung.com/watch-face-studio/overview.html)
- [Samsung codelab — tag expressions](https://developer.samsung.com/codelab/watch-face-studio/tag-expression.html)
- [tobwil/garmincreator](https://github.com/tobwil/garmincreator)
- [okdar/smartarcs](https://github.com/okdar/smartarcs)
- [garmin/connectiq-apps](https://github.com/garmin/connectiq-apps)
- [dbcm/KISSFace](https://github.com/dbcm/KISSFace)
- [aurpelai/garmin-watchface-template](https://github.com/aurpelai/garmin-watchface-template)
- [Garmin forum — "Open Sourcing a watch face - Almost nobody does it"](https://forums.garmin.com/developer/connect-iq/f/discussion/320246/open-sourcing-a-watch-face---almost-nobody-does-it)
