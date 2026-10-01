# Probe: what does each complication report in `ranges`?

**Answer at build time: `Complication.ranges` is readable from a watch face.**
`BUILD SUCCESSFUL`, warning-free, `-l 3`, on `fenix8solar47mm`,
`fenix8solar51mm` and `fr955`, SDK 9.2.0. Negative control: `c.ranges` →
`c.rangez` fails with `Undefined symbol ':rangez' detected.`

**Answer at run time, in the simulator: native complications leave
`ranges` null.** Two host-simulator runs as `fenix8solar47mm`
(2026-09-30), the second with steps, floors and intensity minutes past
their goals and a changed step goal: all 41 native types offered reported
`r=null` both times. **On a real fr955**
(2026-10-01), all 40 native types offered reported `r=null` too. No app complication was present, so an app's `<range>` is
untested. The full log and what else it settled are in
`../../24-complication-full-scale.md` §2.4.

## What it does

A complete watch face project. It walks `Complications.getComplications()`
(every complication the device offers, native and app, pulled with no
subscription) and logs, once on load:

```
goals: stepGoal=… floorsClimbedGoal=… activeMinutesWeekGoal=… steps=… floorsClimbed=…
t<type>|v=<value>|u=<unit>|r=<ranges>
```

`<type>` is the `Complications.COMPLICATION_TYPE_*` number; `t0` is an app's
complication, followed by its long label. The screen shows the same rows,
seven per page, turning the page each minute (re-read each minute).

## Building and running

A `.prg` is built for one device; build one per watch, named after it:

```sh
cd docs/research/probes/complication-ranges
$CIQ_SDK/bin/monkeyc -f monkey.jungle -d fr955 \
    -o probe-ranges-fr955.prg -y ~/ciq/developer_key.der -w -l 3
```

Simulator: the log is the simulator's console. Watch: `System.println`
lands in `GARMIN/APPS/LOGS/<NAME>.TXT`, where `<NAME>` is the `.prg`'s own
file name, and only if that file exists before the app runs. For
`probe-ranges-fr955.prg`, create an empty `PROBE-RANGES-FR955.TXT` when
copying the `.prg` into `GARMIN/APPS/`.
