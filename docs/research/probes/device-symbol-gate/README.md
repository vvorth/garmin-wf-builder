# Probe: does `-l 3` reject a symbol the *target device* does not have?

**Answer: no. `monkeyc` resolves against the SDK-wide API, not the device's own
`api.debug.xml`.** This corrects a belief stated in two places in `CLAUDE.md`
and is worth reading before designing anything around per-device availability.

## The negative result, with a clean control

`UserProfile.getFunctionalThresholdPower(sport)` is one of 34 `functionEntry`
symbols present in `fenix8solar47mm.api.debug.xml` and **absent from**
`fr955.api.debug.xml`. `ProbeGate.mc` calls it. It builds `BUILD SUCCESSFUL`,
warning-free, under `-l 3`, **on `fr955`**.

The typechecker is demonstrably live in the same build:

* a deliberate typo (`setSelectedComplicationTypo`) fails with
  `ERROR: fr955: ... Undefined symbol ':setSelectedComplicationTypo' detected.`
* omitting the `sport` argument fails with `Trying to call function ... with
  wrong number of arguments`
* omitting `<iq:uses-permission id="UserProfile"/>` fails with
  `Permission 'UserProfile' required for '$.Toybox.UserProfile'`

So `monkeyc` checks names, arities, types and **permissions** -- and does not
check per-device availability at all.

The same result holds for the whole `Toybox.Application.WatchFaceConfig`
module and for `WatchFaceDelegate.setSelectedComplication`, neither of which
exists in `fr955.api.debug.xml`; see `../watchface-config/`.

## What this changes

**It does not make `Device.has_symbol` useless -- it re-labels what it
answers.** A device's symbol table describes what exists *at runtime*. Calling
an absent symbol still fails on the wrist; it just fails there rather than at
build time. So:

* Every existing use of `has_symbol` stays correct. `check_hold_targets` warns
  that a hold will never fire on a device without `onPress` -- a runtime fact,
  which is exactly what the table reports.
* Constraint 6 in `CLAUDE.md` stays true as written ("API level is NOT
  sufficient to determine availability... resolve symbols against the device's
  own `<id>.api.debug.xml`"). What is false is the unstated corollary the
  project had drifted into: that the compiler would catch it for you.
* One sentence elsewhere **is** false and is corrected in the same commit as
  this probe. `CLAUDE.md`'s anti-aliasing note argues a build-time gate "was
  never an option" partly because "the call would not typecheck under `-l 3` on
  a device lacking the symbol." It would. The conclusion that section reaches
  is still right -- a runtime `Graphics has :setAntiAlias` guard is needed,
  because the failure is a runtime one -- but that reason for it is not.

**Practical consequence, and the reason this probe exists:** one shared,
non-device-specific generated view may reference an API that only some targets
have, provided it is guarded at runtime. No per-device source split, no jungle
`sourcePath` gymnastics. That is what makes the on-device-config work a single
generated view rather than two.

## Rebuilding it

```sh
$CIQ_SDK/bin/monkeyc -f monkey.jungle -d fr955 \
    -o probe.prg -y ~/ciq/developer_key.der -w -l 3
```

with `<iq:uses-permission id="UserProfile"/>` in the manifest. To re-derive the
device-only symbol list:

```python
import re
syms = lambda p: set(re.findall(r'<functionEntry[^>]*name="([^"]+)"', open(p).read()))
a = syms('fenix8solar47mm/fenix8solar47mm.api.debug.xml')
b = syms('fr955/fr955.api.debug.xml')
print(sorted(a - b))
```
