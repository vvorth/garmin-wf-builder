# Probe: which `has` checks does SDK 9.3.0's `monkeyc` accept around a symbol a device's API level predates?

**Answer: a `has` check naming the symbol, or a module or class enclosing
it, written so it lexically encloses the use: the condition of an
enclosing `if`, a ternary's condition, or an earlier operand of the same
`&&` chain.** Nothing else counts reliably. VERIFIED by building this
project with `monkeyc` 9.3.0 and 9.2.0 (2026-10-25); 9.2.0 accepts every
case below, 9.3.0 rejects the ones marked no. Runtime behaviour is not
what this probe measures: every case is a runtime guard that already
worked on the watch under 9.2.0.

## The failure

SDK 9.3.0 (`doc/docs/Readme/History.html`, "Compiler Changes": *Improve
typecheck diagnostics when using APIs that do not meet the target device's
minimum API level*) turned the generated faces' runtime guards into
compile errors:

```
FeatureAODView.mc:46,12: Value '$.Toybox.System.DISPLAY_MODE_OFF' is not supported for device 'venu'.
SlotText.mc:40,12: Value '$.Toybox.Complications.COMPLICATION_TYPE_SLEEP_SCORE' is not supported for device 'fr955'.
FeatureAlignDelegate.mc:50,12: Value '$.Toybox.Application.WatchFaceConfig' is not supported for device 'venusq2'.
```

The check is by **API level, not by the device's symbol table**: the
symbol's `Since:` in the SDK's Toybox docs against the device's
`compiler.json` level. `COMPLICATION_TYPE_SLEEP_SCORE` is 6.0.2 and `fr955`
5.2.0; `DISPLAY_MODE_OFF` is 5.0.0 and `venu` 3.3.6; `WatchFaceConfig` is
5.1.0, so `venusq2` (5.0.0) fails while `fr955` (5.2.0) passes although
`fr955.api.debug.xml` lacks `WatchFaceConfig.getSettings`.

## Cases (`source/ProbeView.mc`, `source/ProbeDelegate.mc`)

Built for `venu` (3.3.6: no `Toybox.Complications`, no `DISPLAY_MODE_OFF`),
`venusq2` (5.0.0: no native editor), `fr955` (5.2.0: no
`COMPLICATION_TYPE_SLEEP_SCORE`) and `fenix8solar47mm` (6.0.3: everything).

| Case | Form | 9.3.0 |
|---|---|---|
| C1 | `if (Toybox has :Complications) { Complications.getComplication(...) }` | yes |
| C2 | `(Toybox has :Complications) ? Complications.X : null` | yes |
| C3 | `var h = Toybox has :Complications;` then `h ? ... : null` | yes here; **no** in the generated view (below) |
| C4 | `(Toybox has :Complications) && Complications.X != null` | yes |
| C5 | a `Complication`'s field (`got.value`) inside C1 | yes |
| C6 | `catch (ex instanceof Complications.ComplicationNotFoundException)` inside C1 | yes |
| C7 | `if (!(Toybox has :Complications)) { return 0; }` then the use | **no** |
| C8 | a helper with no check, called only from inside one | **no** |
| D1 | `(System has :getDisplayMode) && ... == System.DISPLAY_MODE_OFF` | **no** |
| D2 | D1 plus `(System has :DISPLAY_MODE_OFF)` | yes |
| S1 | `COMPLICATION_TYPE_SLEEP_SCORE` inside only `Toybox has :Complications`, on `fr955` | yes |
| S2 | S1 plus `Complications has :COMPLICATION_TYPE_SLEEP_SCORE` | yes |
| W1 | `ComplicationRef.uniqueIdentifier` inside `Application has :WatchFaceConfig` | yes |
| E1 | `WatchUi.WATCH_FACE_CONFIG_TYPE_COMPLICATION` inside `Application has :WatchFaceConfig` | **no** |
| E2 | `setSelectedComplication(1)` with no check | **no** |
| E3 | `(WatchUi has :WATCH_FACE_CONFIG_TYPE_COMPLICATION) && ...` | yes |
| E4 | `if (self has :setSelectedComplication)` | **no** |
| E5 | `if (WatchUi.WatchFaceDelegate has :setSelectedComplication)` | yes |
| E6 | `if (box has :addRectangle)`, on the instance | yes |
| E7 | `if (WatchUi has :ComplicationDrawableRef)` around `new WatchUi.ComplicationDrawableRef(...)` | yes |
| E8 | `box.addRectangle` inside `Application has :WatchFaceConfig` | **no** |
| T1 | a field or parameter *typed* with an absent class | yes: types are not checked |
| X1 | a method annotated `(:editor)`, excluded by the jungle's `venu.excludeAnnotations` | yes on 9.3.0; 9.2.0 rejects X2's call to it |

So a check covers the symbol it names and everything inside it (S1, W1),
and nothing beside it (D1, E1, E8). A check reached by flow rather than by
enclosure does not count (C7, C8).

**C3 is not to be relied on.** In this probe a local holding the check
passes, even with an unrelated statement or an `else` between (C3b-C3f);
in the generated view the identical shape
(`var hasComplications = Toybox has :Complications;` then
`hasComplications ? WfbComplications.valueOf(new Complications.Id(...)) : null`)
is rejected on `venu`, and writing the check out in the ternary fixes it.
The difference was not isolated; the generator writes every check inline.

## Reproduce

```sh
cd docs/research/probes/sdk93-has-guards
for d in venu venusq2 fr955 fenix8solar47mm; do
  ~/ciq/sdks/9.3.0/bin/monkeyc -f monkey.jungle -d $d -o /tmp/p.prg -y ~/ciq/developer_key.der -l 3
done
```

The launcher icon is `venu`'s size, so the other devices may warn about it.
