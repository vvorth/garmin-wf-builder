# Probe: can a complication be read by *pull*, with no cached field?

**Answer: yes.** `BUILD SUCCESSFUL` under `-l 3` on `fenix8solar47mm` and
`fr955`, SDK 9.2.0.

## Why this was asked

The generated view used to carry one private field per bound complication, plus
a shared `onComplicationChanged` callback with a `switch` that wrote each
incoming value into its field. `onUpdate` then read the field. That is a cache,
and it exists only because the pull direction was assumed unavailable.

It is available. Garmin's own sample proves it:
`$CIQ_SDK/samples/ConfigurableWatchFace/source/ConfigurationWatchFaceView.mc`
calls `Complications.getComplication(id).value` from `updateConfiguration`,
which runs inside `onLayout` **before** the first `subscribeToUpdates`, and
again in edit mode where it never subscribes at all. The comment there says the
snapshot "is sufficient".

## What this probe pins down

`ProbeView.mc` compiles the exact shapes the generator now emits:

```monkeyc
var complicationBodyBattery = WfbComplications.valueOf(
    new Complications.Id(Complications.COMPLICATION_TYPE_BODY_BATTERY));
var bodyBattery = (complicationBodyBattery != null)
    ? complicationBodyBattery.value as Number? : null;
```

Two things it settles that a doc page does not:

1. **The cast is required, and it parses inside a ternary branch with no extra
   parentheses.** `Complication.value` is `Complications.Value or Null`, i.e.
   `String or Number or Float or Long or Double or Null`
   (`Toybox/Complications.html`), so `-l 3` will not let it reach a `Number?`
   local unguarded. `? x.value as Number? : null` is accepted as written --
   also checked with `String?` and `Float?`.
2. **No per-type field and no per-type `switch` are needed.** The callback here
   has one statement, `WatchUi.requestUpdate()`.

## What it deliberately does NOT settle

Whether a complication stays *fresh* with no `subscribeToUpdates` at all.
Nothing in this container can answer that -- the simulator does not run here
(`docs/limitations.md` §2), so this is a compile-time result only. The
subscription is therefore kept: it costs one line per bound type in `onLayout`
and nothing per frame, and dropping it would risk a value that silently never
updates, which is the failure class this project exists to eliminate.

## Rebuilding it

The probe is source-only, like `../carousel/`. Drop `ProbeView.mc` and a copy of
`runtime-lib/WfbComplications.mc` into a minimal watch-face project declaring
`minApiLevel="4.2.0"` and the `ComplicationSubscriber` permission, then:

```sh
$CIQ_SDK/bin/monkeyc -f monkey.jungle -d fenix8solar47mm \
    -o probe.prg -y ~/ciq/developer_key.der -w -l 3
```
