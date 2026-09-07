# 0.7 — A data carousel, and what the platform will actually give you

The request: reproduce the horizontal data carousel from the **stock fr955
watch face** — several data sources laid out as a row of icons, the active one
centred with its value shown next to it, left/right presses rotating the row
with a short slide animation, and pressing the centred item opening that
item's glance.

The stock face is **native firmware, not Connect IQ**, so nothing about it is
evidence that a CIQ face can do the same. This document establishes what a CIQ
watch face can actually do, one requirement at a time, against the SDK's own
docs and a **working prototype built through the real toolchain** (§5).

Everything here is verified. Where a claim could not be verified without
hardware, it is marked **[open]** rather than assumed.

---

## 0. The headline, before the detail

Four of the five requirements are achievable on **all three targets**,
including `fr955`. The fifth is not achievable on **any** device, and it is
not the one the project's existing notes would predict:

| Requirement | Verdict |
|---|---|
| Row of icons, active one centred, its value beside it | **yes** — pure layout, no new platform capability |
| Rotate to previous / next | **yes**, by **touch and hold** with coordinates |
| Rotate by **tap** | **no — on any device, including the fēnix 8 Solars** |
| Short slide animation | **yes**, but only while the face is awake (§3) |
| Press the centred item to open its glance | **yes**, `Complications.exitTo` |
| Remember the selection across restarts | **yes**, `Application.Storage` |

**The correction that matters: `WatchFaceDelegate.onTap` never fires on a
watch face that is merely being looked at.** It fires only inside the
on-device watch-face config editor. That contradicted what this project shipped
as `on_tap:`, which has been corrected in the same change as this document;
see §6.

---

## 1. Input: a live watch face receives exactly one gesture

### 1a. `onTap` is config-mode only

`doc/Toybox/WatchUi/WatchFaceDelegate.html`, the `onTap` entry, in full:

> A screen tap event has occurred.
> **Only available in WatchFace config mode.**
> Can be overridden by application to change the selected complication,
> using `WatchFaceDelegate.setSelectedComplication()`

The same sentence appears on exactly two other members of that class,
`getComplicationDrawable` and `onWatchFaceConfigEdited` — both of which are
unambiguously part of the on-device editor (ADR 0006 §3, `Editing_Watch_Faces_
On_Device.html`). `onTap` keeps that company, not `onPress`'s.

The SDK's own sample agrees. `samples/ConfigurableWatchFace/source/
ConfigurationWatchFaceDelegate.mc` is the only watch face in the SDK that
implements `onTap`, and all it does is tell the *editor* which slot the user
picked:

```monkey-c
function onTap(clickEvent as ClickEvent) as Boolean {
    var coords = clickEvent.getCoordinates();
    var selectedComplication = _view.getTappedComplication(coords[0], coords[1]);
    if (selectedComplication != null) {
        setSelectedComplication(selectedComplication);   // editor highlight
        return true;
    }
    return false;
}
```

There is no sample, anywhere in the SDK, of a watch face acting on a tap during
normal display.

Garmin's own forum guidance says the same thing plainly — "CIQ watchfaces only
support `WatchfaceDelegate.onPress()` (long-press), not any of the other touch
input methods", and "watch faces are purposely designed to be limited to
complications, due to the fact you can only detect a press-and-hold, not a tap"
([Any way to listen for input for a watch face?][f1],
[Thoughts on System 6 onPress() for watch faces][f2],
[Press and hold on watch face complications to open detailed view][f3]).

### 1b. `onPress` is the whole input surface

`onPress` — touch **and hold** — carries no config-mode caveat, is documented
since API 4.2.0, and is present on all three targets. `Core_Topics/
Complications.html` documents it as the sanctioned "Hold to Launch" mechanism
and gives the `exitTo` recipe verbatim.

`ClickEvent.getCoordinates()` returns `[x, y]`, so a single hold can mean
different things in different places. That is the entire degree of freedom
available.

### 1c. Everything else is closed

* **Swipe / drag / flick.** `WatchFaceDelegate` declares six methods and none
  of them is a swipe. `onSwipe` lives on `BehaviorDelegate`/`InputDelegate`,
  which a watch face never installs.
* **Buttons.** No `onKey` on `WatchFaceDelegate`; the physical keys belong to
  the system on the watch-face screen.
* **`WatchUi.configureTouchEvents`.** Documented "only allowed for Watch Apps
  and Audio Content Providers when running in the foreground mode."

Symbols resolved against each target's own `api.debug.xml` (the discipline
CLAUDE.md constraint 6 exists for), not against API levels:

| Symbol | fenix8solar47mm | fenix8solar51mm | fr955 |
|---|---|---|---|
| `WatchFaceDelegate.onPress` | yes | yes | **yes** |
| `WatchFaceDelegate.onTap` | yes *(config mode only)* | yes *(config mode only)* | no |
| `WatchFaceDelegate.setSelectedComplication` | yes | yes | no |
| `WatchUi.animate` | yes | yes | yes |
| `WatchUi.cancelAllAnimations` | yes | yes | yes |
| `WatchUi.requestUpdate` | yes | yes | yes |
| `Timer.Timer.start` | yes | yes | yes |
| `Application.Storage.getValue` / `setValue` | yes | yes | yes |
| `Complications.exitTo` | yes | yes | yes |
| `ClickEvent.getCoordinates` | yes | yes | yes |

Reproduce with `wfb devices`, or:

```sh
./.venv/bin/python -c "from wfb.devices import DeviceDatabase; \
d = DeviceDatabase.discover().get('fr955'); \
print(d.has_symbol('Toybox.WatchUi.WatchFaceDelegate.onTap'))"
```

---

## 2. The one real design decision: partitioning the hold

One gesture must carry three meanings — previous, next, and launch. The only
discriminator is the touch coordinate, so the choice is how to cut up the
carousel's own box.

**Option A — three zones (recommended).** Hold the left third → previous, the
right third → next, the middle third → `exitTo` the centred item's
complication. Closest to the reference behaviour, all three meanings reachable,
one gesture.

**Option B — advance only.** Hold anywhere on the carousel → next. Simplest
and the most forgiving hit region, but the carousel then has no exit, which
throws away the most useful thing a complication binding offers.

**Option C — launch only.** What the project shipped before this: hold an
element, open its glance. No carousel. Still available, as `on_hold:` on any
element; the carousel is an addition to it, not a replacement.

Option A also **dissolves a problem ADR 0006 §6 raised and could not solve**.
The ADR says `on_activate: cycle` together with `on_hold: launch` "conflict on
fr955, where hold is the activation gesture", and that "the compiler must
reject that combination". With `onTap` gone from the picture the conflict is
no longer an fr955 quirk — it is universal — but it is also no longer a
conflict, because the two meanings are separated by **geometry** rather than by
gesture. The compiler does not have to reject anything; it has to lay out
zones and warn when they are too small to hit. That is a strictly better
outcome, arrived at from a worse premise.

**What the zones cost.** Three zones across a carousel roughly 90 % of screen
width is ~78 px per zone on the 260 px targets — comfortably larger than a
fingertip. Zones are already computable: `wfb/layout.py` resolves every
element's box, and `_hold_constants` in `wfb/emit/monkeyc.py` already emits hit
rectangles from it.

---

## 3. Animation: real, but only while the watch is awake

`doc/Toybox/WatchUi/WatchFace.html` is explicit about the two power states:

> A WatchFace will run in a high power mode for a short period when responding
> to a gesture (i.e., raising the watch to check the time) or when returning to
> the watch face from another application. **While in high power mode, the watch
> face will perform full screen updates every second via calls to `onUpdate()`,
> and the application will have access to timers and animations.**
> […] After this period in high power mode (typically about ten seconds), the
> system will call `onEnterSleep()` […] **The application will not have access
> to timers or animations while in low power mode.**

And `WatchUi.animate()` carries the matching hazard:

> Will cause an app crash if called from background or data field app, **or from
> watch face while in low power mode**.

So animation is available exactly when it is wanted and nowhere else — the user
must be touching the screen to rotate the carousel, and touching the screen is
one of the actions that puts the face in high power mode
([forum][f4]). During that window `onUpdate` already runs every second, and
`animate()` raises it further for the duration of the animation.

**This makes one thing mandatory in generated code, not optional:** the slide
must be guarded on the sleep state, and must degrade to an instant jump rather
than crash. The generated view already tracks `_sleeping` (added when
`modes: [always_on]` was fixed), so the guard has a home:

```monkey-c
if (_sleeping) {
    slide = 0;              // no timers, no animations in low power mode
    WatchUi.requestUpdate();
    return;
}
WatchUi.cancelAllAnimations();
slide = direction * PITCH;
WatchUi.animate(self, :slide, WatchUi.ANIM_TYPE_EASE_OUT,
                direction * PITCH, 0, 0.3, method(:onSlideDone));
```

**[open]** Whether `onPress` can be delivered *before* `onExitSleep` — i.e.
whether `_sleeping` can still read `true` at the moment the hold arrives. It
does not matter for correctness here (the guard takes the safe branch either
way, at worst skipping an animation the user asked for), but it decides whether
the first rotation after a wrist-raise animates. Untestable without hardware:
the simulator does not run in this container (`docs/limitations.md` §2).

`Timer.Timer` + `requestUpdate()` is an equivalent mechanism with the same
restriction and more code; `animate()` is the right choice.

---

## 4. Data: read only the item you are showing

A carousel of *n* items displays one value. Reading all *n* every frame is
waste that grows with the item count, and some of the interesting sources
(`body_battery.current`, `weather.*`) are `event`- or `slow`-tier and carry a
subscription or a cache each.

The right shape is a `switch` on the selected index around the value read and
its formatting, so an unselected item costs only its icon glyph — which is
static, needs no read at all, and is already just a `drawText` against a baked
font (`wfb/icons.py`).

**What was built, and why it is less than this section expected.** The
`switch` on the selected index is there, around the *formatting*. The reads
themselves are not gated, and gating them would have been a mistake: `ReadPlan`
hoists per **reader**, not per source, and a carousel's items typically share
one — `ActivityMonitor.getInfo()` is a single call whether the row shows one of
its fields or six. Gating that behind a `switch` would save nothing and would
duplicate the reader hoisting into every `case`. What is genuinely per-item —
`.format()` on the value, and the item's own null policy — *is* inside the
switch, so an unselected item costs only its icon glyph.

Where the cost would be real is a row mixing `event`- or `slow`-tier sources,
which carry a subscription or a cached read each. That cost is not avoidable by
gating either: a complication subscription must be registered in `onLayout` for
**all** items regardless of selection, because a subscription is not a read,
and a `slow` read is already cached behind its TTL rather than taken per frame.
So the honest summary is that the saving this section anticipated mostly does
not exist, and the code is simpler for not chasing it.

Icons for the items come for free: `METRIC_ICON` / `icon_for_source()` in
`wfb/icons.py` already map a catalogue data-source path to its conventional
glyph, so `items:` need not name an icon unless the author wants a different
one.

---

## 5. The prototype: it compiles, and it is small

A hand-written probe exercising every claim above was built through the real
toolchain — `WatchUi.animate` on a `WatchFace` subclass,
`cancelAllAnimations`, `Application.Storage` round-tripping the index,
`onPress` with three coordinate zones, and `Complications.exitTo` on an
array-indexed complication type — under **strict typechecking**:

```sh
monkeyc -f monkey.jungle -d <target> -o carousel.prg \
        -y ~/ciq/developer_key.der -w -l 3 --build-stats 0
```

| Target | Result | Foreground data | Foreground code |
|---|---|---|---|
| `fenix8solar47mm` | `BUILD SUCCESSFUL` | 597 B | 785 B |
| `fenix8solar51mm` | `BUILD SUCCESSFUL` | 597 B | 785 B |
| `fr955` | `BUILD SUCCESSFUL` | 597 B | 785 B |

1,382 B for an entire face whose only content is the carousel — about **1 % of
the 131,072 B budget**. Nothing here is expensive.

Two findings came out of the build that a doc page would not have given:

1. **The animated property must be public or protected.** `animate()` takes a
   `Symbol` and looks the property up indirectly, so a `private var` fails —
   loudly, which is the good case:

   ```
   WARNING: The private symbol 'slide' will not be found when using the
   indirect lookup syntax ':slide'. Consider making 'slide' public /
   protected or use a direct reference 'self.slide'.
   ```

   Generated code must therefore expose the slide offset as a public member of
   the view. Reviewable, but worth knowing before writing the emitter.

2. **`fr955` builds a delegate that defines only `onPress`** with no complaint,
   which is the shape a carousel wants everywhere now that `onTap` is known to
   be useless outside config mode.

---

## 6. A shipped feature was misdocumented and partly dead — now fixed

`on_tap:` (commit `f037bd6`) emitted **both** `onTap` and `onPress` and treated
them as equivalent. `docs/format.md` sold that as a feature:

> **One declaration, two behaviours.** […] the same `on_tap:` is a tap where
> tap exists and a touch-and-hold where it does not

That is not what happened. On every device, `on_tap:` was reached by **touch
and hold only**. The `onTap` handler compiled, linked, and was never called
outside the config editor — harmless, but dead.

**What is instructive is *how* the mistake was made.** Every individual fact in
that session was checked against the device symbol tables, which is exactly the
discipline CLAUDE.md demands. The error was one step further on: treating *the
symbol is present* as *the callback fires*. `Device.has_symbol` answers the
first question and cannot answer the second; the method's own prose has to be
read too. CLAUDE.md constraint 6b now says so.

**Corrected in this change**, since none of it is a judgement call:

* The key is renamed **`on_tap:` → `on_hold:`**. The old spelling stays in the
  schema solely so `wfb validate` can report the rename (`on-tap-renamed`)
  against the author's own line rather than as a generic "additional property"
  error that names no replacement.
* The emitter no longer produces an `onTap` handler at all.
* `check_tap_targets` is `check_hold_targets` and resolves only
  `WatchFaceDelegate.onPress`. The `tap-unsupported` note — "fr955 has no
  `WatchFaceDelegate.onTap`, so its N tap target(s) are reached by touch and
  hold instead", true and actively misleading, because it implied the other two
  targets got taps — is gone. `hold-unsupported` fires only when a device has
  no `onPress` at all, which none of the nine vendored devices does but a great
  many products do.
* `docs/format.md`, `docs/limitations.md`, CLAUDE.md §4 and §6, and ADR 0006 §6
  are corrected. ADR 0006 carries an **amendment** above its original text
  rather than a rewrite: the decision that was made is a matter of record, and
  the premise it rested on is worth seeing.

Nothing generated was ever *broken*: the intended behaviour — hold an element,
open its glance — worked on all three targets, because the `onPress` path
carried it. Only the story was wrong.

## 7. The format it led to — built

Proposed here, then built in the same session. `examples/carousel/` is the
worked example and `docs/format.md`'s `carousel` section is the reference; what
follows is the shape and the decisions behind it.

```yaml
- id: data
  type: carousel
  at: { anchor: center, dy: 20% }
  size: { width: 62%, height: 22% }   # the TOUCH target, not the drawn extent
  pitch: 22%r
  slots: 3                            # defaults to min(3, items)
  icon_size: 9%r
  color: palette.accent
  inactive_color: palette.dim
  value_font: FONT_SMALL
  value_color: palette.fg
  value_offset: { anchor: center, dy: 34% }
  animate: 0.3
  persist: true
  items:
    - value: heart_rate.current       # icon inferred from the source
      format: "{:d}"
      when_absent: placeholder
      placeholder: "--"
      launch: heart_rate
    - value: activity.steps
      format: "{:d}"
      when_absent: fallback
      fallback: "0"
      launch: steps
    - icon: battery
      value: system.battery
      format: "{:.0f}%"               # no launch: centre-hold opens nothing
```

**The open questions in the draft of this section, and how they were answered.**

* *Where does the value text live — a child element, or a sub-layout the
  carousel owns?* **The carousel owns it** (`value_font:`, `value_color:`,
  `value_offset:`). A child element would have been more composable and more in
  keeping with ADR 0004, but it needs a new kind of cross-element reference
  (`value: carousel.data`) for a pairing that is never anything but one-to-one.
  Owning it also makes the icon/reading pair impossible to desynchronise.
* *Does a carousel participate in `modes:`?* Yes, unchanged — the existing
  refresh-tier check governs what it may bind in `low_power`, and the
  partial-update clip already charges by area. Nothing carousel-specific was
  needed.
* *Should `persist:` default on?* Yes. It is what the stock face does, and a
  carousel whose selection resets on every restart is worse than useless.
  `persist: false` opts out.
* *How does this interact with `<watchface-config>` slots?* It does not, yet,
  and that is the honest split: the carousel is the wearer choosing between
  readings the *design* fixed; a config slot is the wearer choosing what a slot
  reads at all. The second still needs the `config:` block. The carousel's real
  value remains highest on `fr955`, which has no on-device config at all.

**Two things the build settled that the proposal could not.**

1. **A carousel's box is its touch target, and that had to become a distinct
   concept.** Sizing the hit region generously is correct — it is split into
   thirds — but the generic safe-area check reads an element's box, so every
   reasonably-sized carousel warned about a region it was never going to paint.
   `PlacedCarousel.content_box` is now what the element actually draws, and
   `inside_visible_area_for` reads that; reachability of the *zones* became its
   own check, `check_carousel_zones`, which is where it belonged anyway.
2. **A carousel is the only element that skips the element-level null guard.**
   Every other element hides as a whole when a binding is absent. Doing that
   here would collapse the row and move the zones out from under the wearer's
   finger, so each item's `when_absent:` is applied inside its own `case`
   instead. The consequence is an error rather than a silent asymmetry: a
   carousel's own colours may not be nullable, because there is no
   `when_absent:` for the row's appearance.

## 8. Outcome

All three steps done in the session that produced this document.

1. ~~**Correct the `onTap` story first.**~~ **Done** — see §6.
2. ~~**Amend ADR 0006 §6.**~~ **Done.** Its `on_activate: cycle` /
   `on_hold: launch` conflict rule was obsolete: the conflict is universal, and
   geometry resolves it. The zone model is recorded there now.
3. ~~**Then the element.**~~ **Done** — `type: carousel`, §7. Most of it was
   work this project already knew how to do (layout resolution, hit rectangles,
   icon glyphs, per-item null policies); the genuinely new pieces were the
   touch-target/drawn-extent split, the per-item guard scoping, and one small
   runtime-lib addition (`WfbCarousel.mc`).

Measured on `examples/carousel/`: **2,887 B on all three targets, 2.2 % of the
131,072 B budget**, for a whole face. The carousel itself is about 1.4 KB of
that, matching §5's probe.

`raw` (ADR 0007) was not the right escape hatch here, and building it confirmed
why: a carousel resolves geometry per device, resolves symbols per device, and
lints its own reachability. Hand-written Monkey C would have forfeited all
three.

---

## Sources

SDK 9.2.0, offline under `$CIQ_SDK`:

* `doc/Toybox/WatchUi/WatchFaceDelegate.html` — `onTap` config-mode caveat,
  `onPress` device list
* `doc/Toybox/WatchUi/WatchFace.html` — high/low power contract
* `doc/Toybox/WatchUi.html` — `animate`, `cancelAllAnimations`,
  `requestUpdate`, `configureTouchEvents`
* `doc/Toybox/WatchUi/ClickEvent.html` — `getCoordinates`
* `doc/Toybox/Timer.html`, `doc/Toybox/Timer/Timer.html`
* `doc/docs/Core_Topics/Complications.html` — "Hold to Launch", `exitTo`
* `doc/docs/Core_Topics/Editing_Watch_Faces_On_Device.html`
* `samples/ConfigurableWatchFace/source/ConfigurationWatchFaceDelegate.mc`
* `~/.Garmin/ConnectIQ/Devices/<id>/<id>.api.debug.xml` for all three targets

Forum corroboration:

* [f1] https://forums.garmin.com/developer/connect-iq/f/discussion/5386/any-way-to-listen-for-input-for-a-watch-face
* [f2] https://forums.garmin.com/developer/connect-iq/f/discussion/315203/thoughts-on-system-6-onpress-for-watch-faces
* [f3] https://forums.garmin.com/developer/connect-iq/f/discussion/284170/press-and-hold-on-watch-face-complications-to-open-detailed-view
* [f4] https://forums.garmin.com/developer/connect-iq/b/news-announcements/posts/changes-to-watch-face-low--and-high-power-modes

The reference screenshot (`preview.redd.it`) is blocked by this sandbox's
network policy and was not retrieved; the behaviour described in §0 is the
requester's own description of it.

[f1]: https://forums.garmin.com/developer/connect-iq/f/discussion/5386/any-way-to-listen-for-input-for-a-watch-face
[f2]: https://forums.garmin.com/developer/connect-iq/f/discussion/315203/thoughts-on-system-6-onpress-for-watch-faces
[f3]: https://forums.garmin.com/developer/connect-iq/f/discussion/284170/press-and-hold-on-watch-face-complications-to-open-detailed-view
[f4]: https://forums.garmin.com/developer/connect-iq/b/news-announcements/posts/changes-to-watch-face-low--and-high-power-modes
