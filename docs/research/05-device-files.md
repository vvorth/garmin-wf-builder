# 0.5 — Device files: measured facts

Written after the per-device definitions were copied in from the user's host SDK
(`~/Library/Application Support/Garmin/ConnectIQ/Devices/`) and installed to
`~/.Garmin/ConnectIQ/Devices/`. Everything here is **measured or read from the
device files**, not inferred from prose.

Devices available: `fenix7pro`, `fenix7x`, `fenix7xpro`, `fenix7xpronowifi`,
**`fenix8solar47mm`**, **`fenix8solar51mm`**, `fenix9prosolar47mm`,
`fenix9prosolar51mm`, **`fr955`** (9 total; the three targets are present).

Each device directory contains `compiler.json`, `simulator.json`,
`personality.mss`, `<id>.bin`, and — most importantly — **`<id>.api.debug.xml`,
the device's own API surface**.

---

## 1. The toolchain works end-to-end in this sandbox

```
$ monkeyc -f monkey.jungle -d fenix8solar47mm -o dash.prg -y developer_key.der -w
WARNING: …/source/Data.mc:628,6: Cannot determine if container access is using container type.
WARNING: …/source/Data.mc:629,6: Cannot determine if container access is using container type.
BUILD SUCCESSFUL
```

This **conclusively disproves** the sibling Dashboard project's `CLAUDE.md`
claim that "the face cannot be compiled in a sandboxed Claude Code session". SDK
download, developer key generation via plain OpenSSL, and a real device-targeted
build all work. Only the *device definitions* were ever gated, and they are
obtained by copying from a host installation.

(The two warnings are pre-existing in the Dashboard source, not caused by us.)

---

## 2. The `onTap` finding, verified at the strongest available level

Phase 0 concluded from the documentation's "Supported Devices" lists that
`fr955` lacks `WatchFaceDelegate.onTap`. The device files confirm it from the
device's own API definition:

| Device | API level | `WatchFaceDelegate` members |
|---|---|---|
| `fenix8solar47mm` | 6.0 (CIQ 6.0.2) | `getComplicationDrawable`, `handleEvent`, `onPress`, **`onTap`** |
| `fr955` | 5.2 (CIQ 5.2.0) | `handleEvent`, `onPress` |

A naive grep finds `onTap` in `fr955.api.debug.xml`, but its parent is
`Toybox_WatchUi_InputDelegate` — the *app* input path — not
`Toybox_WatchUi_WatchFaceDelegate`.

### Why this matters more than the finding itself

**`fr955` runs API level 5.2.0, which is *above* `onTap`'s documented "since"
of 5.1.0 — and still does not have the symbol.**

So API-level gating is **not sufficient** to determine availability. A framework
that emitted `onTap` whenever `minApiVersion >= 5.1.0` would produce a face that
compiles cleanly for `fr955` and silently never responds to taps. This is the
same silent-failure class as a missing permission.

**Consequence for the framework:** availability must be resolved against the
**per-device `api.debug.xml`**, not against API level, and not against the
documentation's product-name lists.

This also **resolves open question 9** in `00-summary.md`. The lossy
product-name→device-id join used to build the Phase 0 capability matrix should
not be repaired — it should be *replaced*. The per-device `api.debug.xml` gives
exact, machine-readable, per-device symbol availability with no name matching at
all. The Phase 0 matrix stays as a research artefact; the shipped device database
must be built from the device files.

---

## 3. Memory: measured, and the limit is subtler than "PRG size"

`monkeyc --build-stats 0` on the Dashboard face for `fenix8solar47mm`:

```
Data:
  Foreground:      2 602 bytes
Code:
  Foreground:     13 520 bytes
Extended Code:
  Page Size:       4 096 bytes
  Number of Pages:     0
  Total Size:          0 bytes
Total PRG Size:  126 348 bytes
Build Time:      3.594 seconds
```

Against `compiler.json` for the same device:

- `watchFace` `memoryLimit`: **131 072 B**
- `maxPrgFilespace`: **67 108 864 B** (64 MB)
- `codePageSize`: 4 096 B

**Interpretation, stated carefully.** Data + Code foreground is 16 122 B, which
is comfortably inside 131 072 B. Total PRG size is 126 348 B, which is 96% of
131 072 B but only 0.2% of the 64 MB `maxPrgFilespace`. The PRG is dominated by
the bitmap clock-font atlas, a resource stored in the file and loaded on demand.

The two numbers therefore measure different things, and **which one the 131 072 B
`memoryLimit` actually constrains is not settled by this experiment**. The
plausible reading is that `memoryLimit` governs *runtime* memory — code, data,
and resources currently loaded — while `maxPrgFilespace` governs file size. That
would mean the Dashboard face has ample headroom, not 4% remaining.

**Open (supersedes question 2):** establish empirically what counts against
`memoryLimit` — in particular whether a loaded font resource is charged against
it, and whether `Extended Code` pages change the accounting. Resolvable by
building a face with a deliberately oversized resource and observing where it
fails, in the simulator. Until then the memory linter must report the measured
figures and say which limit each is compared against, rather than emitting a
single confident "fits / does not fit".

---

## 4. The graphics pool is separate from the app memory limit

`simulator.json` reports `graphicsResourcePoolSize: 1 048 576` (**1 MB**) on all
three targets — an order of magnitude larger than the 128 KB watch-face limit,
and evidently a distinct budget.

This materially improves the `BufferedBitmap` strategy in
`02-features-feasibility.md` §4d and ADR 0006 §5: pre-rendering a static tick
scale or background into a buffered bitmap draws on the graphics pool rather
than the app's 128 KB. **Partially resolves open question 7**; the exact
accounting and whether palette'd buffers are charged differently remain open.

---

## 5. Per-device capability data now available

From `compiler.json` / `simulator.json` for the three targets:

| | `fenix8solar47mm` | `fenix8solar51mm` | `fr955` |
|---|---|---|---|
| `deviceFamily` | `round-260x260` | **`round-280x280`** | `round-260x260` |
| `deviceGroup` | API level 6.0 | API level 6.0 | **API level 5.2** |
| `connectIQVersion` | 6.0.2 | 6.0.2 | 5.2.0 |
| `displayType` | mip | mip | mip |
| `bitsPerPixel` | 8 | 8 | 8 |
| watchFace `memoryLimit` | 131 072 | 131 072 | 131 072 |
| `alphaBlendingSupport` | **false** | **false** | **false** |
| `enhancedGraphicSupport` | true | true | true |
| `graphicsResourcePoolSize` | 1 048 576 | 1 048 576 | 1 048 576 |
| `appStorageCapacity` | 10 485 760 | 10 485 760 | 10 485 760 |
| `watchdogCount` | 240 000 | 240 000 | 240 000 |
| `ppi` | 202 | 202 | 200 |

Notes:

- **`deviceFamily` is exactly the resource-qualifier directory name**
  (`round-260x260`), which is what the generator must emit for per-device
  resources. `fenix8solar51mm` is `round-280x280`, confirming that a bitmap font
  baked for 260×260 is wrong there — the drift already present in the sibling
  Dashboard project, which ships only one font size.
- **`alphaBlendingSupport: false` on all three targets.** Any schema feature
  implying transparency or alpha compositing must be gated on this. Relevant to
  `setBlendMode`, which is present in the API but constrained here.
- `watchdogCount: 240 000` is present but its units and relationship to the
  `onPartialUpdate` budget are **not documented**. It is *plausibly* the
  execution-budget counter, and it is the only budget-shaped number in the device
  files. **Not asserted** — open question 1 stays open, now with a concrete
  candidate to test against `onPowerBudgetExceeded`.

### `sensorHistory` — Body Battery and stress are absent

`simulator.json` lists, identically on all three targets:

| type | interval (s) | samples |
|---|---|---|
| `heartrate` | 60 | 360 |
| `elevation` | 120 | 180 |
| `temperature` | 120 | 180 |
| `pressure` | 120 | 180 |
| `pulseox` | 3600 | 168 |

**There is no `bodybattery` or `stress` entry**, although
`SensorHistory.getBodyBatteryHistory` exists in the API and the sibling Dashboard
face uses it. The most likely explanation is that this block configures the
*simulator's synthetic data*, not device capability — so Body Battery would read
null in the simulator while working on the wrist.

That distinction matters for the framework's test story: **a simulator run is not
sufficient evidence that a data binding works**, and screenshot-regression tests
must not treat a null Body Battery as a regression. Flagged as an open question.

---

## 6. Updated open questions

| # | Status |
|---|---|
| 1 — partial-update power budget | **still open**; candidate found (`watchdogCount: 240000`), units unknown |
| 2 — memory accounting | **superseded** by §3; now "what counts against `memoryLimit`" |
| 3 — device definitions | **RESOLVED** — copied from host, 9 devices, all 3 targets |
| 4 — headless simulator / CLI screenshots | still open; now testable |
| 5 — `onTap` reliable in simulator | still open; now testable |
| 6 — fr955 Complications | **RESOLVED** — present in `fr955.api.debug.xml` |
| 7 — `BufferedBitmap` cost | **partially resolved** — separate 1 MB graphics pool |
| 8 — `setBlendMode` semantics | narrowed — `alphaBlendingSupport: false` on all targets |
| 9 — capability matrix name join | **RESOLVED by replacement** — use per-device `api.debug.xml` |
| 10 — font licensing | unchanged (product decision) |
| **new** | what counts against `memoryLimit` (§3) |
| **new** | does `SensorHistory` Body Battery read null in the simulator? (§5) |
