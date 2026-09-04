# 0.3 — Toolchain

Everything here was exercised against a real SDK installed in this environment,
except where marked **[open]**.

**Installed:** Connect IQ SDK 9.2.0 at `~/ciq/sdks/9.2.0`
(`CIQ_SDK` and `PATH` are set in `/etc/sandbox-persistent.sh`).

---

## 1. Obtaining the SDK — and the one thing that is actually gated

The prompt's sibling project asserts the SDK is unobtainable in a sandbox. That
is **incorrect as of this investigation** and the claim has been corrected.

Verified working, unauthenticated:

```
GET https://developer.garmin.com/downloads/connect-iq/sdks/sdks.json   → 200
GET .../sdks/connectiq-sdk-lin-9.2.0-2026-06-09-92a1605b2.zip          → 200, 204 MB
GET .../sdk-manager/connectiq-sdk-manager-linux.zip                    → 200
```

`sdks.json` is a plain catalogue — version, release date, and the mac/windows/linux
filenames — which makes SDK acquisition fully scriptable. Ten releases are listed,
8.1.0 (Mar 2025) through 9.2.0 (Jun 2026).

**What *is* gated: per-device definitions.** The SDK zip contains the compiler,
simulator and docs but **no `Devices/` directory**. Device files are fetched
separately by the SDK Manager from

```
https://api.gcs.garmin.com/ciq-product-onboarding/devices   → HTTP 401
```

401, not 403 — the host is reachable, the request is unauthenticated. The SDK
Manager binary references `sso.garmin.com/sso/embed` and `api.gcs.garmin.com`,
so device downloads require a Garmin account OAuth flow that cannot be completed
headlessly. (`monkeynet.garmin.com`, also referenced, does not resolve publicly.)

**Consequence:** without device files, nothing device-targeted builds:

```
$ monkeyc -f monkey.jungle -d fenix8solar47mm -o out.prg -y dev.der
ERROR: Invalid device id specified: 'fenix8solar47mm'
```

For this project the device files are being copied from the user's host SDK
installation (`~/Library/Application Support/Garmin/ConnectIQ/Devices/` on macOS).
Any CI story must solve the same problem — see "CI" below.

---

## 2. The tools

From `$CIQ_SDK/bin/`:

| Tool | Purpose |
|---|---|
| `monkeyc` | The compiler. Java-based front end over `monkeybrains.jar`. |
| `monkeydo` | Pushes and runs a `.prg` on a **already-running** simulator. |
| `connectiq` | Launches the simulator (`simulator` binary on Linux, `ConnectIQ.app` on macOS). |
| `barrelbuild` / `barreltest` | Build and test Monkey Barrels (shared libraries). |
| `monkeydoc` | Documentation generator. |
| `monkeygraph` / `monkeymotion` / `mdd` / `era` | Profiling/graphing, animation, device debug, exception report analysis. |
| `api.debug.xml`, `api.db`, `api.mir` | The API definition. Machine-readable — see §5. |
| `resources.xsd` | XSD for all resource XML. The generator should validate against this. |

**Java:** `monkeyc --version` runs correctly under **OpenJDK 25** in this
environment, printing `Connect IQ Compiler version: 9.2.0`. No version pinning
was needed.

### `monkeyc` options that matter for a generator

```
-f, --jungles <arg>       Jungle files
-d, --device <arg>        Target device
-o, --output <arg>        Output .prg / .iq
-y, --private-key <arg>   Developer key (DER)
-e, --package-app         Produce an .iq application package
-r, --release             Release build
-w                        Enable warnings
-l, --typecheck <arg>     0=off, 1=gradual, 2=informative, 3=strict
-O, --optimization <arg>  0=none, 1=basic, 2=fast, 3=slow;
                          p=optimize performance, z=optimize code space
    --build-stats <arg>   Print build stats [0=basic]
    --no-gen-styles       Skip the Rez.Styles module
    --disable-api-has-check-removal
                          Do not optimise out `has` checks
```

Three of these are directly load-bearing for this project:

- **`--build-stats`** is the only credible source for "will this face fit in
  128 KB". The Phase 1.4 memory linter should shell out to it rather than
  estimate. **[open until device files land]**
- **`-O z`** optimises for *code space*, which is the correct default for a
  watch face, where memory is the binding constraint rather than speed.
- **`-l 3` (strict)** should be the default for *generated* code. A generator has
  no excuse for producing code that fails strict type checking, and it turns
  schema bugs into build failures.

Note `--disable-api-has-check-removal`: by default the compiler *removes*
`X has :y` checks it can resolve statically for the target device. This is what
makes the `has`-guard idiom free at runtime, and it means the generator should
guard liberally without worrying about cost.

### Developer key

A standard RSA key in PKCS#8 DER. Generated here with plain OpenSSL, no Garmin
tooling required:

```sh
openssl genpkey -algorithm RSA -pkeyopt rsa_keygen_bits:4096 -out developer_key.pem
openssl pkcs8 -topk8 -inform PEM -outform DER \
        -in developer_key.pem -out developer_key.der -nocrypt
```

**Verified** — produced a valid key that `monkeyc` accepted as far as the device
check.

### `.prg` vs `.iq`

- **`.prg`** — a single compiled executable for **one** device. This is what you
  sideload and what the simulator runs.
- **`.iq`** — an application *package* containing builds for every device in the
  manifest plus store metadata, produced with `-e`. This is only for store
  submission.

Since the stated distribution goal is personal sideload, `.prg` is the primary
artefact and `.iq` is a Phase 3 concern.

### Sideloading

Copy the `.prg` to the device's `GARMIN/APPS/` directory over USB/MTP
(`doc/docs/Connect_IQ_Basics/Your_First_App.html`). On Linux this means an MTP
mount; **[open]** whether MTP is workable from inside this sandbox, but it is a
host-side operation for the user regardless, so the CLI's `install` command
should target a mounted path rather than speak MTP itself.

---

## 3. Jungle files — the per-device variation mechanism

Source: `doc/docs/Reference_Guides/Jungle_Reference.html` **[verified]**.
The generator will emit these, so the semantics matter.

Grammar: `qualifier[.property] = value`, one per line, `;`-separated lists,
`$(VAR)` dereference, `#` comments, `.jungle` extension, project root.

**Project qualifiers:** `project.manifest`, `project.optimization`,
`project.typecheck`.

**Device/family qualifier properties:** `sourcePath`, `resourcePath`, `lang`,
`barrelPath`, `annotations`, `excludeAnnotations`, `personality`.

Qualifiers are `base`, a device family, or a device id — increasingly specific.
Paths behave like `PATH`: precedence left to right, later entries can override
earlier ones. The idiom for *adding* rather than replacing is

```
fenix5.resourcePath = $(fenix5.resourcePath);fenix-resources
```

Dereferences are evaluated **lazily**, after all jungle files are processed, per
target device — except when a qualifier dereferences itself during assignment,
which resolves immediately. A generator must respect that distinction or emit
subtly wrong per-device paths.

### Build exclusions — per-device dead code elimination

This is the important one for the codegen-vs-interpreter decision. Annotate
declarations and exclude them per target:

```monkeyc
const experimental = Toybox.Sensor has :AccelerometerData;
(:experimental) function newHotnessLogic() { … }
(:boring)       function oldAndBoringLogic() { … }
```

```
base.excludeAnnotations   = experimental
fenix5.excludeAnnotations = boring
```

Garmin's own framing: *"This may help save memory during app execution on a
device."* So Connect IQ has a **native, first-class mechanism for shipping only
the code a given device needs** — which is precisely what a code generator wants
and precisely what a generic runtime interpreter cannot exploit. This is
material evidence for ADR 1.2.

Combined with resource qualifier directories (`resources-round-260x260/`), the
platform gives per-device specialisation at both the source and resource level
without the generator inventing anything.

---

## 4. Simulator, testing, profiling

### Simulator

`connectiq` launches it; `monkeydo <prg> <device_id>` pushes to a **running**
instance. So automation is two processes, not one, and the simulator is a GUI
application — headless CI needs `Xvfb` or equivalent. **[open]** — untested
until device files land.

Screenshot capture is a simulator feature; whether it is drivable from the
command line without a GUI session is **[open]** and directly affects the Phase 2
"screenshot" step and the Phase 3 screenshot-regression tests.

The simulator also provides the AMOLED burn-in heat map
(`File → View Screen Heat Map`), enabled only for watch faces on
burn-in-protected devices.

### Unit testing — "Run No Evil" (`Toybox.Test`)

Source: `doc/docs/Core_Topics/Unit_Testing.html` **[verified]**.

- **Simulator-only.** There is no on-device or host-native test runner.
- Asserts (`Test.assert`, `Test.assertMessage`, `Test.assertNotEqual`,
  `Test.assertNotEqualMessage`) always run in the simulator and are **stripped by
  the compiler in release builds**.
- Unit tests run independently; a crashing test is marked failed and the suite
  continues. Run via `monkeydo <prg> <device> -t [test_name]`.

**Strategic consequence.** Because Monkey C tests need a simulator and a device
file, they are the *slowest and least available* tests in this project. The
compiler, schema and IR must therefore be testable in the host language with no
Garmin toolchain at all, with golden-file tests over generated Monkey C, and
`Toybox.Test` reserved for the thin hand-written runtime barrel. This shapes the
package boundaries in Phase 1.

### Profiling

`-k/--profile` enables profiling support; `monkeygraph` and the VS Code extension
consume the output. Useful later for validating the `onPartialUpdate` budget
empirically. **[open]**

---

## 5. `api.debug.xml` — mechanical symbol verification

`bin/api.debug.xml` (1.4 MB) enumerates the API surface. This directly satisfies
the project's "never invent an API" rule: **every Monkey C symbol the generator
emits can be checked against this file at build time**, offline, before ever
invoking `monkeyc`.

Spot-checked and confirmed present: `Complications`, `WatchFaceConfig`,
`onPartialUpdate`, `onPowerBudgetExceeded`, `onWatchFaceConfigEdited`,
`setSelectedComplication`, `onTap`.

Better still, the per-method **"Supported Devices"** lists in `doc/Toybox/**`
give device-level availability, not just API level — that is how §5 of
`02-features-feasibility.md` established that `fr955` supports `onPress` but not
`onTap`. Combining the two yields a real "is this symbol usable on this target?"
check, which is the Phase 1.4 "unsupported API used for a targeted device"
linter.

**Recommendation:** the framework should ship a generated symbol/availability
database derived from the SDK, refreshed per SDK release, rather than hand-maintained
capability tables.

---

## 6. CI

Two obstacles, in order of severity:

1. **Device files require authenticated download.** Any CI runner needs them.
   Options: cache them as a CI artefact/secret (licence terms **[open]** — needs
   review of the Connect IQ licence agreement before redistribution, even
   privately); or run device-targeted builds only on a developer machine and
   restrict CI to host-language tests plus generated-code golden files.
2. **The simulator is a GUI app.** Screenshot regression needs a virtual display.

The honest near-term position: **CI can fully test the compiler, schema, IR and
generated-source golden files with no Garmin toolchain at all.** Device builds
and screenshot diffs are a developer-machine or self-hosted-runner concern.
Sequencing the project so the Garmin-dependent steps are the *last* link in the
chain is therefore not just convenient but necessary.

---

## Sources

- SDK 9.2.0 `bin/` (`monkeyc --help`, `monkeydo`, `connectiq`, `version.txt`)
- `doc/docs/Reference_Guides/Jungle_Reference.html`
- `doc/docs/Core_Topics/Unit_Testing.html`
- `doc/docs/Core_Topics/Publishing_to_the_Store.html`
- `doc/docs/Connect_IQ_Basics/Your_First_App.html`
- `doc/docs/Monkey_C/Compiler_Options.html`
- Live HTTP probes of `developer.garmin.com` and `api.gcs.garmin.com`, Sep 2026
