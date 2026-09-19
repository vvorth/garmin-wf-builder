# 07 — Interaction on a live watch face

What input and animation a Connect IQ watch face actually gets, verified
against the SDK docs and each target's own `api.debug.xml`. This drives
`on_hold:` (constraint 6c). Claims that need hardware are marked **[open]**.

In short: a face that is being looked at receives **one gesture, touch and
hold** (`onPress`), with coordinates. There is no tap, swipe or key, on any
device. `Complications.exitTo` opens a glance, `Application.Storage`
persists state, and `WatchUi.animate` works only while the face is awake.

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

## 2. Animation: real, but only while the watch is awake

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

So animation is available exactly when it is wanted and nowhere else — a hold
is a touch, and touching the screen is one of the actions that puts the face
in high power mode
([forum][f4]). During that window `onUpdate` already runs every second, and
`animate()` raises it further for the duration of the animation.

**This makes one thing mandatory in generated code, not optional:** any
animation must be guarded on the sleep state, and must degrade to an instant
jump rather than crash. The generated view tracks `_sleeping`:

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
the first animation after a wrist-raise plays. Untestable without hardware:
the simulator does not run in this container (`docs/limitations.md` §2).

`Timer.Timer` + `requestUpdate()` is an equivalent mechanism with the same
restriction and more code; `animate()` is the right choice.

---

## 3. Two lessons from building on it

1. **A symbol being present does not mean it gets called.** `onTap` resolves
   on both fēnix 8 targets and still never fires outside the config editor.
   `Device.has_symbol` answers "can I call it", and only the method's prose
   answers "will it be called" (constraint 6b).
2. **A property passed to `WatchUi.animate` must be public or protected.**
   `animate()` looks it up indirectly by `Symbol`, so a `private var` fails
   with `WARNING: The private symbol 'x' will not be found when using the
   indirect lookup syntax`.

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

[f1]: https://forums.garmin.com/developer/connect-iq/f/discussion/5386/any-way-to-listen-for-input-for-a-watch-face
[f2]: https://forums.garmin.com/developer/connect-iq/f/discussion/315203/thoughts-on-system-6-onpress-for-watch-faces
[f3]: https://forums.garmin.com/developer/connect-iq/f/discussion/284170/press-and-hold-on-watch-face-complications-to-open-detailed-view
[f4]: https://forums.garmin.com/developer/connect-iq/b/news-announcements/posts/changes-to-watch-face-low--and-high-power-modes
