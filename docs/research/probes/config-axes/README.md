# Probe: everything the native editor's four axes can carry at once

**Answer: all of it compiles, on every target, and the whole thing costs
2.8% of the budget — but the four axes are a hard ceiling, and only *one* of
them can carry author-defined content.**

`BUILD SUCCESSFUL`, warning-free, under `-l 3`, on `fenix8solar47mm`,
`fenix8solar51mm` **and** `fr955` (which has no editor at all), at
**1,241 B data + 2,386 B code = 3,627 B** for:

* **12 `<style>` entries**, decoded by arithmetic into three independent
  author-defined axes (a colour *scheme*, and two content picks);
* a three-role colour scheme (`bg`/`fg`/`dim`) resolved from the decoded style;
* **two `<complication>` slots**, each with its own list of allowed types;
* an icon chosen at runtime from **`Complications.Id.getType()`** — the thing
  that lets one authored slot template serve every metric the wearer can pick;
* `shortLabel` and `unit` read off the pulled `Complication`;
* `<accentColors allowAny="true"/>` and a labelled `<dataColors>` list;
* edit-mode detection, `onTap` + `setSelectedComplication`, and
  **`getComplicationDrawable`** returning a `ComplicationDrawableRef` — the
  editor's "pulsing" highlight, which this project had previously left as a
  documented gap.

## The five things it settles

1. **`Complications.Id.getType()` works on the id the wearer picked**, and
   `switch`ing on it against `Complications.COMPLICATION_TYPE_*` typechecks
   under `-l 3`. This is what makes "one authored slot template, icon inferred
   from the chosen metric" possible — the alternative, one authored group per
   allowed type, multiplies the design by the size of the choice list.

2. **`getComplicationDrawable` is buildable from a generated `Drawable`
   subclass that delegates back to the view's own per-slot draw method**, so
   there is still exactly one implementation of what a slot looks like.
   `+134 B data, +414 B code` over the same probe without it. The SDK sample's
   own comment (`samples/ConfigurableWatchFace/source/ComplicationDrawable.mc`)
   is what makes this necessary rather than optional if the editor's animated
   highlight is wanted: *"This prevents the complication from being drawn on
   the watch face while it is pulsing."* The view must **hide** the slot it
   handed over, or it is drawn twice during the animation.

3. **Styles are nearly free in memory, and the cost of the cross-product is
   entirely a UX cost.** Measured at one fixed path (see the warning below):
   1 style + 1 label → 1,052 B data / 97,052 B `.prg`; 12 styles + 12 labels →
   1,151 B data / 97,724 B `.prg`. That is **+9 B data and +61 B `.prg` per
   style**, and **no code growth at all** (1,972 B either way). A 64-entry
   cross-product would cost well under 600 B. What it costs instead is a flat
   editor list of 64 combinatorial labels.

4. **`fr955` compiles every line of it** — `WatchFaceConfig`,
   `ComplicationDrawableRef`, `Graphics.BoundingBox`, `setSelectedComplication`
   — and simply keeps the compiled-in defaults, exactly as
   `../device-symbol-gate/` predicts. No per-device source split.

5. **The JVM `sun.misc.Unsafe` notice is caused by `<watchface-config>`,
   independently reconfirmed here**: the two fēnix targets (which get the
   resource) print it and `fr955` (which does not) prints nothing. That is the
   noise `wfb/build.py` filters.

**Negative control, so the above is worth something:** changing `id.getType()`
to `id.getTypo()` in the same build fails with
`Undefined symbol ':getTypo' detected.` — `-l 3` is live.

## What it deliberately does NOT settle

**Every behavioural question about the editor**, as always: no simulator runs
in this container (`docs/limitations.md` §2) and there is no watch. Whether the
highlight animates, whether the previews are instant, whether `onTap`'s hit
regions read correctly, and whether the wearer's four saved configurations
behave as expected are all **UNVERIFIED**.

One structural finding is *not* from a build and should be read as a
documentation result: **there is no way to ask which saved configuration is
active.** `getSettings(null)` returns the active `Settings` and `Settings`
carries no id; `getIds()` returns ids but `Id` exposes only `equals`. So
anything the face persists itself (`Application.Storage`) is **global across
the wearer's up-to-four configurations**, while everything on the four axes is
per-configuration. A value-comparison heuristic against each id's settings is
possible and ambiguous whenever two configurations agree.

## A measurement warning, repeated because it already bit this repo once

A `.prg`'s size depends on the **length of the path it was built at**
(`../antialias/` §6). Every `.prg` figure above was taken from builds at one
fixed directory, changing only the input under test. Prefer `--build-stats`,
which is path-independent — but note it moves only for emitted code, so a
resource-only change (adding styles and their labels) has no honest instrument
except file size taken at an unchanging path.

## Rebuilding it

Drop `ProbeApp.mc`, `ProbeView.mc`, `ProbeDelegate.mc`, `SlotDrawable.mc` and a
copy of `runtime-lib/WfbComplications.mc` into `source/`, `watchface.xml` into
`resources-<device>/configs/` (fēnix 8 targets only), `strings.xml` into
`resources/strings/`, declare `<iq:uses-permission id="ComplicationSubscriber"/>`
and `minApiLevel="4.2.0"`, then:

```sh
$CIQ_SDK/bin/monkeyc -f monkey.jungle -d fenix8solar47mm \
    -o probe.prg -y ~/ciq/developer_key.der -w -l 3 --build-stats 0
```
