# Probe: can a target on an older API level use a feature that raised the manifest floor, if that feature is disabled per device?

**Answer: yes. Keep `minApiLevel` at the generator's base floor, and gate each
newer feature per device with a runtime `has`-guard in the shared view, not a
per-device source split.** The manifest floor is not per-device: it is one
number shared by every target in `manifest.xml`, so a feature cannot raise it
without locking out every older target. The floor therefore stays at the
lowest level the *ungated* code needs (`3.2.0`). What used to raise it,
`Complications`, is guarded the same way this project already guards
`WatchFaceConfig` and `createBufferedBitmap`. VERIFIED: the build compiles.
UNVERIFIED: the runtime behaviour (see "Open question" below).

## The failure, and its cause

Adding `fenix6` (API 3.4.5) to `examples/dashboard/face.yaml`'s `targets:`
fails:

```
error[monkeyc]: Device 'fenix6' does not support API Level '4.2.0'. Try
updating the device ..., changing the minimum API level, or removing the
device from your manifest file.
```

`wfb/emit/manifest.py` raises `minApiLevel` to `4.2.0` for any complication
use -- a `complication.*` read, a `config: data:` slot, or `on_hold:` ->
`Complications.exitTo` (`"complications": "4.2.0"`, `wfb/emit/manifest.py:46`)
-- and `manifest.xml` is one file shared by every target, so every device is
held to the highest floor any target needs.
`$CIQ_SDK/doc/docs/Core_Topics/Manifest_and_Permissions.html`: "The minApiLevel
field specifies the minimum Connect IQ API level that your app is compatible
with. ... only the major and minor versions are considered when determining
device support."

Hand-lowering the generated manifest to `minApiLevel="3.2.0"` and building
directly (`monkeyc -f monkey.jungle -d fenix6 -o f6.prg -y
~/ciq/developer_key.der -w`) is `BUILD SUCCESSFUL`, warning-free, 9 243 B
foreground code. Consistent with `../device-symbol-gate/`: `monkeyc` resolves
against the SDK-wide API, so the manifest floor was the only compile-time
barrier. The hazard moves to runtime: executing a symbol the device lacks
fails on the wrist, not at build time.

(Side finding, fixed in the same branch: `fr255` also failed to build, with
`unknown device`, because `tools/setup-env.sh` skipped installing newly
vendored devices whenever the destination already had some -- see
`tools/setup-env.sh`.)

## What the fenix6 build actually touches that fenix6 lacks

Diffing the compiled program's `<symbolTable>` (entries with id >= 0x800000
are API symbols) against `fenix6.api.debug.xml` (`apisyms.py`, below) finds
`Complications`, `WatchFaceConfig`, `createBufferedBitmap`, `onPress`,
`onWatchFaceConfigEdited`. `WatchFaceConfig` and `createBufferedBitmap` were
already runtime-guarded (`Application has :WatchFaceConfig`, `Graphics has
:createBufferedBitmap`); `onPress`/`onWatchFaceConfigEdited` are the face's
own callback overrides, never invoked on a device that lacks them.
**`Complications` was unguarded**: `onLayout`'s
`registerComplicationChangeCallback`/`subscribe` and `onUpdate`'s
`WfbComplications.valueOf(new Complications.Id(...))` would crash on fenix6.

Modules present on `fenix8solar47mm` and absent on `fenix6`: `ActivityPrompts`,
`Complications`, `Media`, `Notifications`, `ScanCode`, `WatchFaceConfig` (336
functions, 47 classes in total; `absent_scan.py`, below). Class *fields* are
per-device too, and the catalogue reads them unguarded: `ActivityMonitor.
Info.stressScore` is absent on `fenix6`, `floorsClimbed` absent on `fr245`.
Fields are not `<functionEntry>`s; they appear in a device's `<symbolTable>`
as `<entry field="true" symbol="stressScore"/>` -- bare names, so absence is
exact and presence approximate.

## The symbol table over-approximates -- a diagnostic, not a guard

In probe variants where every executed `Complications` call was removed from
the fenix6 build, `Complications` still appeared in its symbol table because
of `import Toybox.Complications;` and type annotations (`as
Complications.Complication?`) -- both erased at runtime. Fully qualifying the
types did not remove it either. `apisyms.py`'s output is useful for finding
what to check; it is never proof that a build is safe.

## Two SDK-documented gating mechanisms, both probed to compile

* **Runtime `has`** (`$CIQ_SDK/doc/docs/Monkey_C/Functions.html`: "The `has`
  operator lets you check if a given object has a symbol ... `if ( Toybox has
  :Magnetometer )`") is already the house pattern (`setAntiAlias`,
  `createBufferedBitmap`, `WatchFaceConfig`).
* **Build-time `excludeAnnotations`** (`$CIQ_SDK/doc/docs/Core_Topics/
  Build_Configuration.html`'s "Feeling Excluded": `(:roundVersion)`/
  `(:regularVersion)` twins with `base.excludeAnnotations = roundVersion` /
  `round.excludeAnnotations = regularVersion` in `monkey.jungle`; product ids
  are valid qualifiers per `Reference_Guides/Jungle_Reference.html`). Probed
  by annotating `module WfbComplications` `(:wfb_complications)`, splitting
  the view's complication subscribe/read into `(:wfb_complications)`/
  `(:wfb_no_complications)` twin functions, plus `base.excludeAnnotations =
  wfb_no_complications` and `fenix6.excludeAnnotations = wfb_complications`:
  `fenix6` and `fenix8solar47mm` both `BUILD SUCCESSFUL`, `fenix8`'s symbol
  table unchanged. A per-device `const` in `source-<id>/Layout.mc` with `if
  (Layout.HAS_COMPLICATIONS)` also compiled, but the shared barrel module
  still carried the references (the over-approximation above), so it settles
  nothing runtime `has` doesn't.

## `wfb devices` (SDK 9.2.0 device files)

| device | API level | watch-face limit |
|---|---|---|
| `fenix6` | 3.4.5 | 112 KB |
| `fenix6xpro` | 3.4.5 | 128 KB |
| `fr245` | 3.3.6 | 96 KB |
| `fr255`, `fr955`, `fenix7pro`/`7x`/`7xpro`/`7xpronowifi` | 5.2.0 | 128 KB |
| `fenix8solar47mm`/`51mm` | 6.0.2 | 128 KB |
| `fenix9prosolar47mm`/`51mm` | 6.0.3 | 128 KB |

Nuance to constraint 2 ("128 KB on all targets"): `fr245`'s watch-face limit
is 96 KB, a quarter less -- still true of the three primary targets
(`fenix8solar47mm`, `fenix8solar51mm`, `fr955`).

## Decision (user, 2026-09-15)

Runtime `has`-guards in the one shared view -- not annotation exclusion --
because it is the existing house pattern, keeps the "no per-device source
split" conclusion of `../device-symbol-gate/`, and is the simplest codegen;
the cost is a few bytes per guard, emitted only when at least one target
lacks the symbol. Policy: an unavailable binding reads as absent on that
device (constraint 8's contract, the element's `when_absent` path), `on_hold:`
never fires there, config colours and styles keep their defaults (no editor),
a `config: data:` slot shows absence (its default is itself a `Complications`
read), and the build warns (a lint) rather than failing. The manifest floor
stays at the generator's base `3.2.0`.

## Does the low floor cost a newer watch anything? No: `minApiLevel` is not in the `.prg`

VERIFIED, 2026-09-15. The generated dashboard project was compiled for
`fenix8solar47mm` four times in the **same directory**, changing nothing but
the manifest's `minApiLevel` (`3.2.0`, `4.2.0`, `5.1.0`, `6.0.0`). The four
signed `.prg` files are **byte-identical** (`cmp -l`: 0 bytes differ), and so
are their `.prg.debug.xml` files. Rebuilding the same directory twice is also
0 bytes, so the build is deterministic and the comparison is meaningful.

The field is not stored in the compiled program at all. Walking the PRG
sections of an earlier run (built in different directories) shows the header
(`0xd000d00d`), code (`0xc0debabe`) and data (`0xda7ababe`) sections
identical. Only the debug section, which embeds the build directory's
absolute path, and the signature (`0xe1c0de12`, whose input changed) differed.

So `minApiLevel` does exactly what the SDK page says and nothing more: it
decides which products `monkeyc` agrees to build for (the `Device 'fenix6'
does not support API Level '4.2.0'` error), and it would be the Store's
compatibility filter for an exported `.iq` (`wfb package` is not built). It
enables nothing and changes nothing on a device above the floor.

What a newer watch *does* pay comes from the guards, not the floor, and only
when some target lacks the API. The dashboard's fenix8 build is 38 B larger
with `fenix6` in `targets:`, plus one `Toybox has :Complications` lookup per
frame. A design whose targets all have everything generates the same code it
always did.

## Open question, stated honestly

Runtime behaviour on a real `fenix6` -- that `import Toybox.Complications;`
and type annotations referencing a missing module are harmless at load time,
and that `Toybox has :Complications` is `false` there -- is the SDK docs'
idiom, not observed. The simulator cannot run in this container (`CLAUDE.md`
section 3). Confirm in the host simulator with the `fenix6` device before
relying on it.

## Rebuilding it

```sh
# reproduce the failure (add fenix6 to examples/dashboard/face.yaml's targets: first)
./.venv/bin/python wfb.py build examples/dashboard/face.yaml

# confirm the manifest floor is the only compile-time barrier: hand-edit the
# generated manifest.xml's minApiLevel down to 3.2.0, then
$CIQ_SDK/bin/monkeyc -f monkey.jungle -d fenix6 -o f6.prg -y ~/ciq/developer_key.der -w

# what the build touches that fenix6 lacks
python3 docs/research/probes/api-gating/apisyms.py \
    build/dashboard/dashboard-fr955.prg.debug.xml fr955

# full module/class/field diff, and where the project's source references them
python3 docs/research/probes/api-gating/absent_scan.py \
    build/dashboard fenix8solar47mm fr955
```

Both scripts resolve `vendor/devices/` relative to the repo root (override
with `CIQ_VENDOR_DEVICES`); point them at any `<device>.api.debug.xml` pair
and any built project directory.
