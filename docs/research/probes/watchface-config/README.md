# Probe: the native on-device watch face editor, end to end

**Answer: it works, it is cheap, and it needs no per-device source split.**
`BUILD SUCCESSFUL`, under `-l 3`, on **both** `fenix8solar47mm` (which has the
editor) and `fr955` (which does not), at **622 B data + 972 B code** for an
accent colour, a data colour, a style and one complication slot together.

## What the editor actually offers

`Core_Topics/Editing_Watch_Faces_On_Device.html`, API 5.1.0, fēnix 8 and newer.
Four axes and no more, with **at most four saved configurations** per face:

| Axis | Resource element | Read back as |
|---|---|---|
| Styles | `<styles><style id label default/>` | `Settings.styleId as Number?` |
| Data | `<data><complication id [allowAny]><type/>` | `Settings.complicationSettings as Array<ComplicationRef>?` |
| Data Colour | `<dataColors [allowAny]><color label default/>` | `Settings.complicationColor as Color?` |
| Accent Colour | `<accentColors [allowAny]><color .../>` | `Settings.accentColor as Color?` |

`$CIQ_SDK/bin/resources.xsd` carries the exact grammar (`watchfaceConfigType`);
`$CIQ_SDK/samples/ConfigurableWatchFace/` is Garmin's own working example and
is worth reading in full before touching this area.

Two things the axis table does not say out loud:

* **A `<color>`'s `label` is a string *resource* reference** (`@Strings.aqua`),
  so a named colour choice implies a generated `<string>` entry. `allowAny="true"`
  needs no names at all and no strings.
* **`styleId` is an opaque `Number` that Garmin gives no meaning to.** What a
  style *selects* is entirely the face's own business -- which elements draw,
  which colours apply, both, or neither.

## The five things this probe settles

1. **One shared generated view serves every target.** `import
   Toybox.Application.WatchFaceConfig;` and `WatchFaceConfig.getSettings(null)`
   compile warning-free **for `fr955`**, whose `api.debug.xml` contains no
   `WatchFaceConfig` module at all (only prose mentions of it). So does
   `WatchFaceDelegate.setSelectedComplication`. See `../device-symbol-gate/` for
   why, with a clean control. No jungle `sourcePath` split, no stub module.
2. **`Application has :WatchFaceConfig` is the guard**, and it compiles on both.
   It is not optional: the SDK sample's own comment says a device without the
   editor "will crash above" at the `getSettings` call. Runtime availability is
   the real gate; the compiler is not.
3. **Every field on the way in is nullable, twice over.** `Settings.accentColor`
   is `Color?` and `Color.color` is `ColorType?`; `styleId` is `Number?`;
   `complicationSettings` is `Array<ComplicationRef>?` and each ref's
   `uniqueIdentifier` and `complicationId` are both nullable again. Every
   default must be compiled in and every read must fall back to it -- which is
   also exactly what makes `fr955` degrade correctly rather than specially.
4. **A complication slot reads like any other complication.** The user's choice
   arrives as a `Complications.Id`, and
   `WfbComplications.valueOf(id).value as Number?` is the same pull this project
   already emits for `complication.*` -- the existing barrel file needed no
   change. `ComplicationSubscriber` and `minApiLevel="4.2.0"` are already
   derived for that.
5. **`<watchface-config>` does not force a `minApiLevel` bump.** The probe's
   manifest declares `3.2.0` (and later `4.2.0`, for the complication read) and
   builds. The generator should therefore place the resource in
   `resources-<device>/` for the devices that support the editor rather than
   raising the floor for every device -- the per-device bundle machinery
   already exists.

## `onTap` is legitimate here, and only here

`docs/research/07-carousel-interaction.md` §1 established that
`WatchFaceDelegate.onTap` never fires on a live watch face -- it is documented
"Only available in WatchFace config mode" -- and the `onTap` handler was deleted
from the emitter as dead code. **This is the config mode it meant.** Inside the
editor, `onTap` plus `setSelectedComplication(id)` is how the face tells the
editor which slot the wearer just pointed at. Emitting it for a face that
declares complication slots is not a reversal of that finding; it is the other
half of it. A face with no slots still emits no `onTap`.

`AppBase.onStart(state)` reports edit mode via
`state[:launchedFromWatchFaceSettingsEditor]`, and
`WatchFaceDelegate.getComplicationDrawable` lets the editor animate a preview of
the selected slot. The probe implements the first and **not** the second: the
return type is `Drawable or ComplicationDrawableRef or Null`, the SDK calls it
"allows you to provide", and this project's generated view draws straight to the
`Dc` rather than through `Drawable` subclasses, so supplying one is real work for
an effect nothing here can see. Left as a documented gap.

## What it deliberately does NOT settle

**Anything about how the editor behaves.** No simulator runs in this container
(`docs/limitations.md` §2) and there is no watch. Whether the editor lists the
slots without `getComplicationDrawable`, whether `onTap`'s hit regions read
correctly, and whether a saved configuration survives as expected are all
**UNVERIFIED**, exactly as the complication-pull probe's freshness question is.
What is verified is that it compiles, what it costs, and that it cannot crash
`fr955`.

## Rebuilding it

Drop `ProbeApp.mc`, `ProbeView.mc`, `ProbeDelegate.mc` and a copy of
`runtime-lib/WfbComplications.mc` into `source/`, `watchface.xml` into
`resources/configs/`, declare `<iq:uses-permission id="ComplicationSubscriber"/>`
and `minApiLevel="4.2.0"`, then:

```sh
$CIQ_SDK/bin/monkeyc -f monkey.jungle -d fr955 \
    -o probe.prg -y ~/ciq/developer_key.der -w -l 3 --build-stats 0
```
