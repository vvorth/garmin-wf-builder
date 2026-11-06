# Toolchain, environment and measurement lore

The full text behind root `CLAUDE.md` §2, §3 and §8. Add new lore here, not to `CLAUDE.md`.

---

## 3. Ground truth about the build — corrected

> **The face builds fine in a sandboxed Claude Code session.** Verified:
>
> ```
> $ monkeyc -f monkey.jungle -d fenix8solar47mm -o dash.prg -y ~/ciq/developer_key.der -w
> BUILD SUCCESSFUL
> ```

**The sibling project `~/claude/garmin-watchface-protomolecule/CLAUDE.md` claims
the opposite** — that `developer.garmin.com` is egress-blocked and the face
cannot be compiled in a sandbox. **Both claims are false**
(`docs/research/05-device-files.md` §1). That file has not been
corrected because the user asked to leave that repo untouched. Do not import its
build claims into this project.

Reference build commands:

```sh
export CIQ_SDK=~/ciq/sdks/9.2.0          # whatever setup-env.sh installed
$CIQ_SDK/bin/monkeyc -f monkey.jungle -d fenix8solar47mm \
    -o out.prg -y ~/ciq/developer_key.der -w -l 3 -O z
$CIQ_SDK/bin/monkeyc … --build-stats 0     # memory measurement
$CIQ_SDK/bin/connectiq                     # launch simulator (GUI)
$CIQ_SDK/bin/monkeydo out.prg fenix8solar47mm   # push to a RUNNING simulator
```

`monkeyc` runs fine on **OpenJDK 25**. No Java version pinning was needed.

**Driving the simulator (`ts/src/simulate.ts`).** On macOS the simulator is
`bin/ConnectIQ.app`, and `bin/connectiq` is just `open -a` on it; on Linux it
is the bare `bin/simulator` binary. Either way it listens on the first free
TCP port of 127.0.0.1:1234–1238, and that range is exactly what `monkeydo`
probes (`ShellUtils.findSimulatorPort` in `bin/monkeybrains.jar`, read with
`javap -c`), so a port that answers is the readiness check on both OSes; a
process-name check is not. **`monkeydo` does not return once the app loads:**
it stays attached, printing the app's `System.println` output, until the app
terminates, the simulator closes, or an error (bad signature, launch failure,
app crash) makes it exit non-zero (`MonkeyDoDeux.execute`). It prints nothing
on success. `wfb simulate` therefore runs it in the background, logging to
`simulator.log` beside the `.prg`, and calls the push good once it has
survived a few seconds with the simulator still up.

---

### A filesystem quirk: tracked files can transiently vanish, harmlessly

Observed twice in one session, on different files each time (`wfb/
icon_catalog.py` once; `runtime-lib/WfbCache.mc` and `runtime-lib/
WfbWeather.mc` together another time; `tests/test_weather_barrel.py` and
`tests/test_weather_codegen.py` together a third): a file `git` correctly
tracks and has committed becomes briefly unreadable — `open()` on the exact
path raises `FileNotFoundError`, `os.listdir()` on its parent directory does
not list it, `import` of it fails — with `git status` then reporting it as
"deleted" even though nothing deleted it and no commit changed it. This is a
transient directory-entry/host-mount coherence issue in the sandbox, not
data loss: `git fsck` finds every affected object present and healthy every
time this happened, and the fix is always the same one-liner:

```sh
git checkout HEAD -- <path>
```

**Do this before assuming a file is genuinely gone or a commit is broken.**
It has never once actually been gone. If `git status` shows a file deleted
that you did not delete and have no reason to believe was deleted, restore
it this way and move on — do not investigate further, do not treat it as
evidence of a bad commit or a corrupted checkout, and do not skip a step
that depends on the file being there just because one check caught it mid-
glitch.

---

## Measurement / build lore

**Measurement / build lore:**

- **A `.prg`'s size depends on the path it was built at.** Identical
  generated source built to two output directories whose names differ in
  length produced files 80 B apart, with `source/` byte-identical under
  `diff -r` — not non-determinism (eight runs at one fixed path are
  byte-stable), a dependency on an input nobody thinks of as one, because a
  `.prg` embeds the paths it was built from. This has already invalidated
  two agents' reported memory-cost numbers in one session. **Prefer
  `--build-stats`** (deterministic, and the only figure that counts against
  the 128 KB budget) for anything emitted as code; take file-size
  comparisons only at equal-length paths, and only for costs
  `--build-stats` cannot see (a resource like a baked font).
- **`monkeyc` writes its intermediates beside the `-o` file**, not beside
  the jungle: `gen/`, `internal-mir/` and `external-mir/` appear in the
  output file's directory (SDK 9.2.0, checked 2026-10-04). Two runs that
  share an output directory share those, so `wfb build` gives each
  device's run its own directory under the build directory's `.monkeyc/`
  and moves the `.prg` and `.prg.debug.xml` up afterwards; that is what
  lets the devices compile in parallel. The `.prg` then embeds that path
  (the size finding above), which `--build-stats` does not see.
- **`--build-stats 0` changed layout in SDK 9.3.0.** Through 9.2.0 it
  grouped by section (`Data:` / `Foreground: N bytes`, then `Code:` /
  `Foreground: N bytes`); 9.3.0 groups by segment under a `Device:` line
  (`Foreground:` / `Code: N bytes` / `Data: N bytes`, then `Extended
  Code:`). Its `Total: … of 786432 available` is not the watch-face limit.
  `checkMemory` in `ts/src/lint.ts` reads both layouts; before it did, every
  9.3.0 build warned that its memory went unchecked. The slow suite now
  fails if any build leaves a device unmeasured.
- **SDK 9.3.0 checks a symbol against the device's API level** (checked
  2026-10-25): `Value '$.Toybox.System.DISPLAY_MODE_OFF' is not supported
  for device 'venu'` unless a `has` check naming it or its module encloses
  the use; `--Eno-invalid-symbol` does not lift it. The generator writes
  every guard that way (constraint 6d), and every example builds with
  nothing from `monkeyc` on 9.3.0 and on 9.2.0.
- **The goldens follow the device reference**, so an SDK whose reference
  adds or changes a device page moves them: 9.3.0's gives `fenix947mm` a
  page, changing its `Layout.mc` in every example. They are made with the
  reference of the SDK `tools/setup-env.sh` installs (9.3.0 now) and the
  vendored device files; regenerate after either changes
  (`node ts/tools/goldens.ts`).
- **`monkeyc -e` (`--package-app`) is the Store export** (SDK 9.3.0,
  checked 2026-10-25), and `wfb export` runs it with `-r`:
  - one run compiles **once per part number** listed for each manifest
    product (a device with two part numbers builds twice), printing a
    `Build Stats:` block per build, each naming its `Device:`;
  - it **stops at the first device that fails to compile**, so one bad
    device fails the whole export; `--all-devices` drops the devices that
    cannot draw the design before it runs, and a device measured over its
    memory limit afterwards, then runs it again (`dropUnsupported` in
    `ts/src/build.ts`), but a `monkeyc` error of its own still fails it;
  - a device with no real part number is dropped with `WARNING: Device '…'
    is being ignored by the package tool` (`IqPackager.removeSimProducts`
    in `bin/monkeybrains.jar`);
  - like a `.prg` build, it writes `gen/`, `internal-mir/` and
    `external-mir/` beside the `-o` file, so `wfb export` stages it under
    `.monkeyc/` too;
  - the `.iq` is a **7z archive**: `manifest.xml` (monkeyc's rewrite of
    ours, adding `apiVersion` and, per part number, `partNumber`,
    `filename`, `minFirmwareVersion`, `connectIqVersion` and RSA-4096
    signatures), `manifest.sig2`, `dev_key.pub`, and `<part
    number>/<name>.prg` with its `debug.xml` per part number (the
    `debug.xml` is packaged even with `-r`).

  The manifest has **no app version**: the bundled
  `com/garmin/monkeybrains/manifest/manifest.xsd` gives `iq:application`
  only `entry`, `id`, `launcherIcon`, `name`, `type` and `minSdkVersion`
  (`minApiLevel` is read too), so the Store's upload form takes the version.
  The Store registers an app by its `id` for good and refuses a second app
  with one already registered, a beta app included (forum thread
  `forums.garmin.com/developer/connect-iq/f/connect-iq-web-store/437376`,
  fetched 2026-10-25); `wfb export --id` exists for that. Garmin's own
  steps (`doc/docs/Core_Topics/Publishing_to_the_Store.html`): list every
  product in the manifest, export the `.iq`, upload it.
- **`$CIQ_SDK/bin/monkeyc` is a bash script that runs `java` as its child,
  not by `exec`** (SDK 9.2.0, checked 2026-10-04; 9.3.0 the same: `java
  -Xms1g -Dfile.encoding=UTF-8 -Dapple.awt.UIElement=true -classpath
  "$MB_HOME"/monkeybrains.jar com.garmin.monkeybrains.Monkeybrains "$@"`).
  `subprocess.run`'s timeout kills only the script, so a hung build used to
  leave its JVM (`-Xms1g`) running after wfb reported it stopped; the
  editor, which runs `wfb build`, left `monkeyc` itself behind too. Since
  2026-11-02 `wfb` runs that JVM command itself (`monkeycCommand` in
  `ts/src/sdk.ts`), with no script in between; both still run it through
  `run` in `ts/src/node_build.ts`, which starts it in its own process group and
  kills the group on a timeout or an interrupt. A process that left the
  group (`setsid`) survives that kill and may hold the output pipes open,
  so the wait for them after the kill is bounded (5 s) rather than
  unbounded.
- Compiling a `<watchface-config>` makes this SDK's JVM print a four-line
  `sun.misc.Unsafe` notice using `monkeyc`'s own bare `WARNING:` prefix.
  `ts/src/build.ts` strips exactly that line shape and nothing else — this is
  the one thing that could silently defeat this project's warning-free bar,
  so it is driven red both ways (a real warning must still surface; the
  notice must not).
- A Styles config entry costs about 9 B data, 28 B code, ~61 B of `.prg` —
  so a Styles cross-product (several schemes, say) is a UX cost to
  weigh, never a memory one.
- **2026-09-13: `monkeyc` 9.2.0 labels each string constant by its Java
  `String.hashCode()`, and crashes when two *different* strings share one.**
  The symptom is only "A critical error has occurred"; with
  `--debug-log-level 3 --debug-log-output` it is `ERROR: assembler:
  Redefinition of label (data) str___<N>`
  (`com.garmin.monkeybrains.compiler2.CompilerException`, from
  `Compiler2.assembleProject`), where `N` is the hash. VERIFIED: the label
  printed, `str___1798574`, is exactly the hash of both the `distance` glyph
  (U+F08F0) and Material Design's thermometer (U+F050F, then the
  `temperature` glyph), and a slot whose `choices:` listed just those two
  types crashed on its own. A glyph above the
  BMP is two UTF-16 units `(hi, lo)` hashing to `31*hi + lo`, so two
  Material Design glyphs 993 codepoints apart often collide; any two strings
  in the program can, in principle.
  - **The first diagnosis was wrong and is recorded so nobody repeats it.**
    The session that hit this bisected by *number of slot choices* and
    concluded "38 types build, 39 crash, not purely a count". The count was
    a proxy: the choices that tipped it over happened to add the second
    colliding glyph, and the substitution that "avoided" it dropped
    `distance`. The label number recurring across unrelated projects was
    the clue, because it is the hash of the string, not of the project.
  - **What the compiler does about it** (`ts/src/emit/strhash.ts`): after
    generating a project, `ts/src/emit/project.ts` hashes every string literal in
    the generated sources and the copied barrel. A colliding glyph in
    `IconGlyphs.mc` is emitted as `(0xf050f).toChar().toString()` instead
    of a literal (`Lang.Number.toChar`, API 1.3.0, in `api.debug.xml`), so
    only the colliding keys change and every other design generates
    byte-identical output. A collision it cannot rewrite (for example two
    static `icon:` elements, whose glyphs are literals in the view) is a
    `string-label` build error naming both strings, instead of a monkeyc
    crash. `choices: any` + `icon: {size:}` (all 42 types) builds warning-free
    on all three targets this way. **Unverified on a device:** that
    `toChar` on a supplementary-plane codepoint draws the right glyph (no
    simulator, no watch).
- **2026-09-15: a compiled `.prg.debug.xml`'s `<symbolTable>` over-approximates
  what a build actually touches — a diagnostic, never proof a build is
  safe.** `docs/research/probes/api-gating/apisyms.py` diffs a built
  project's `<symbolTable>` (entries with id ≥ `0x800000` are API symbols)
  against a device's own `api.debug.xml` to find what the build references
  that the device might lack — useful for finding what to check. But in a
  probe variant where every *executed* `Complications` reference was
  removed from a `fenix6` build, `Complications` still showed up in the
  compiled symbol table, because of a bare `import Toybox.Complications;`
  and a type annotation (`as Complications.Complication?`) — both erased at
  runtime, neither an actual reference a `fenix6` at runtime would ever
  execute. Fully qualifying the types instead of importing did not remove
  it either. Treat `apisyms.py`'s (and `absent_scan.py`'s) output as a
  worklist to check by hand against what the generated code actually calls,
  not as a pass/fail verdict.

---

- **2026-09-29: a `.prg.debug.xml` gives every method's code size exactly.**
  Each `<functionEntry>` carries `startPc`/`endPc`, and `endPc - startPc + 1`
  summed over every function is `--build-stats`' code figure to within a byte
  (`examples/features/profile/`, fr955: 10,792 against 10,793). Method names
  are XML-escaped and wrapped, as in `<globals/FooView/<>drawBar>`.
  `ts/src/build.ts` reads it, and `wfb build --profile` prints it
  per element. Data (the `Layout` constants, the offset tables) is not in it.
- **2026-09-29: the only clock a face can read is `System.getTimer()`, in
  whole milliseconds** (`$CIQ_SDK/doc/Toybox/System.html`). No per-call cost
  is exposed. The partial-update budget is reported only once it is exceeded
  (`WatchFacePowerInfo.executionTimeAverage`/`executionTimeLimit`, in
  `onPowerBudgetExceeded`). So `--profile` times `REPS` draws of one element
  per frame and averages across frames (`ts/src/emit/monkeyc/profile.ts`).

## 8. Useful SDK paths

Everything below is offline inside `$CIQ_SDK` — **prefer it over the website**,
it is version-pinned to the SDK.

| Path | Contents |
|---|---|
| `doc/docs/Core_Topics/` | Complications, Editing_Watch_Faces_On_Device, Graphics, Layouts, Resources, Build_Configuration, Manifest_and_Permissions, Unit_Testing |
| `doc/docs/Connect_IQ_FAQ/` | AMOLED, Optimize_Bitmaps, Custom_Fonts, Update_Every_Second |
| `doc/docs/Reference_Guides/Jungle_Reference.html` | the jungle build language (the generator emits these) |
| `doc/docs/Device_Reference/*.html` | 164 devices: screen, memory limits, **per-language font pixel metrics** |
| `doc/Toybox/**` | full API docs incl. per-method "Supported Devices" |
| `bin/api.debug.xml` | SDK-wide symbol table |
| `bin/resources.xsd` | XSD for all resource XML — validate generated XML against it |
| `samples/` | 44 samples; `ConfigurableWatchFace`, `Analog`, `TrueTypeFonts` are the relevant ones |

`tools/research/h2t.py` converts the SDK's HTML docs to greppable text — the
fastest way to search them.

---

## 2. Environment setup — do this first

The environment is **not** in the repo. Rebuild it with:

```sh
./tools/setup-env.sh
```

That script downloads the SDK, generates a developer key, and installs the
device definitions. On macOS it instead uses the SDK Manager's own SDK and
device/font folders under `~/Library/Application Support/Garmin/ConnectIQ/`
in place (`docs/development.md`, "Platforms"). What it sets up on Linux, and
why each part matters:

| Piece | Location | Notes |
|---|---|---|
| Connect IQ SDK, newest (9.3.0 as of 2026-11-02) | `~/ciq/sdks/<version>` | Downloaded unauthenticated from `developer.garmin.com`, the newest Linux release its `sdks.json` lists unless `SDK_VERSION` pins one; offline, the newest already installed. A newer SDK replaces `CIQ_SDK`/`PATH` in `/etc/sandbox-persistent.sh`. 204 MB. `wfb` itself needs neither variable: `findSdk` in `ts/src/sdk.ts` takes `--sdk`, then `CIQ_SDK`, then the SDK Manager's `Sdks` folder (the SDK its `current-sdk.cfg` names, else the newest), then `~/ciq/sdks`, and each may be one SDK root or a folder of them. A root is recognised by `bin/monkeybrains.jar`; `monkeyc` is run as the JVM on that jar, exactly as the SDK's own `bin/monkeyc` script runs it, so the script's shell is not needed (the Windows SDK's copy has CRLF line ends). When the SDK's `bin/` is not writable (a read-only mount in the container), the compiler's files (about 26 MB: `bin/` less the GUI programs, `compilerNeeds`) are copied once per release to `$XDG_CACHE_HOME/wfb/sdk/<version>` (`~/.cache/wfb/...`) and compiled from there; `wfb doctor` says so. The cache's `sdks/` (`$XDG_CACHE_HOME/wfb/sdks`) is a further place `findSdk` looks: where `wfb init --download-sdk` puts an SDK it can put nowhere better (the container with no writable `/sdk`). The container's entrypoint downloads the newest SDK when a compiling command finds none and the user has said so (`WFB_ACCEPT_LICENSE=1`, or yes at a terminal); the editor starts without one (`NodeDeviceFiles.discover`'s `allowMissingReference`, since without an SDK there may be no device reference either) and its page offers the download with the agreement read off Garmin's SDK page (`agreementFromPage`, cached a day), after which the server reads the devices again. `init`, `doctor`, the editor's Doctor and, in the container, the compiling commands say when Garmin's `sdks.json` lists a newer release than the one found (`checkForNewerSdk` in `ts/src/init.ts`: the list is cached a day at `<cache>/sdks.json`, a 3 s timeout, silence offline, `WFB_NO_UPDATE_CHECK=1` off; the test harness and CI set it). |
| Developer key | `~/ciq/developer_key.der` | Plain OpenSSL RSA → PKCS#8 DER. No Garmin tooling needed. |
| **Device definitions** | `~/.Garmin/ConnectIQ/Devices/` | **Cannot be downloaded.** See below. |
| Garmin's own font files (optional) | `~/.Garmin/ConnectIQ/Fonts/` | Also cannot be downloaded; copied from `vendor/fonts/` the same incremental way, if present. See below. |
| SDK device reference | `.cache/device-reference/`, or `~/.cache/wfb/device-reference/` when the checkout is not writable | Derived, never committed: `ts/src/devices/reference.ts` parses the SDK's own `doc/docs/Device_Reference/*.html` (one JSON per device, 178 on SDK 9.3.0; `ts/tools/extract-device-reference.ts` is its command line). The only source of each panel's real palette size and per-device system-font pixel metrics, and of the font names `ts/tools/fetch-system-fonts.ts` prefetches, so `setup-env.sh` generates it before the fonts. **`wfb` extracts it itself** (`ensureDeviceReference` in `ts/src/devices/node.ts`, about a second for the fleet, a line on stderr) whenever it is missing or `sdk-version.txt` names another release than the SDK `findSdk` finds, provided that SDK has the pages (a pruned one may not: then what is there is used, and `wfb build` warns). `WFB_DEVICE_REFERENCE` names a folder of pages outright and is never extracted into (the fixture device's). `wfb build` compares `sdk-version.txt` with the SDK it compiles with (`checkSdk` in `ts/src/node_build.ts`: a `sdk` warning when they differ, a note when the reference records none) and writes both into `build-info.json` in the build directory. `wfb` refuses to load devices with no reference at all (`DeviceReferenceMissing`), which now only happens with no SDK installed. |
| System-font and vector-face stand-ins | `ts/assets/system-fonts/` | Free fonts, one or more for every system font and every device-resident scalable face (`ts/src/data/font-registry.json`): 47 keys over 39 files, 28.7 MB installed, about 34 MB downloaded the first time (Noto Sans SC alone is 8.4 MB). `setup-env.sh` installs all of them with `ts/tools/fetch-system-fonts.ts --registry`, each hash-checked and beside its licence text. |
| Env vars | `/etc/sandbox-persistent.sh` | `CIQ_SDK`, and SDK `bin/` on `PATH`. |
| Node 24.22.1 | `~/.local/share/wfb/node-v<version>`, when the `node` on `PATH` cannot run `.ts` files or predates 22.23.4, 24.22.1 or 26.12.1 (the October 2026 security releases) | An official build, checked against `SHASUMS256.txt`, prepended to `PATH`; then `npm ci` in `ts/` (`yaml`, `fflate`, `opentype.js`; `typescript` and `esbuild` for development). |

The icon font, the device reference and the system fonts are fetched or
extracted by the tools in `ts/tools/`, which need `ts/`'s npm dependencies,
so Node is set up before them.

### The Developer Agreement: why the SDK is the user's, not the image's

The Connect IQ SDK page (`https://developer.garmin.com/connect-iq/sdk/`,
read 2026-11-02) carries the **Connect IQ Developer Agreement** (updated
2024-08-06; "By downloading any of the following SDKs, you accept our
license agreement"), which "supersedes and replaces the Garmin CONNECT IQ
SDK License Agreement". Its grant (I.a) is "a limited, non-exclusive,
personal, revocable, non-assignable, non-sublicensable and non-transferable
license to use the Program Materials for the sole purpose of developing and
testing Applications"; its restrictions (I.b) forbid to "rent, lease, lend,
upload to or host on any website or server, sell, redistribute, or
sublicense the Program Materials in whole or in part, or to enable others
to do so", and to "alter or remove any copyright, trademark, or other
proprietary notices". "SDK" (IX.o) is the kit "in object code form ...
including documentation, firmware, software, sample code, tools,
libraries, APIs, data, and files", and "Program Materials" (IX.p) is that
plus everything else Garmin makes available in the programme, the
simulator named. There is no open-source carve-out, and the SDK's own
`resources/readme/licenses/` holds `CIQ-LICENSE-AGREEMENT.html` beside the
third-party notices (LGPL, Apache 2.0, OpenSSL, libpng and others).

Consequences, all built: the Docker image carries no part of the SDK --
not the compiler, not the API database, not the device reference derived
from its pages -- and mounts the user's SDK Manager folder at `/vendor`
(`docs/container.md`); a pruned SDK (`ts/tools/fetch-sdk.ts`) keeps the
licence folder and is only ever the downloader's own copy (the smoke test's
runner); and the device definitions and Garmin's fonts, which the same
agreement covers, stay out for the same reason as well as the 401 below.
Downloading the SDK on one's own machine (`tools/setup-env.sh` on Linux,
`wfb init --download-sdk --accept-license` on a Linux host or in the
container into `/vendor/Sdks`, the SDK Manager elsewhere) is
the ordinary use the agreement grants; each download is the user's own
acceptance, which is why `--accept-license` is required and nothing is
fetched without it.
Images published before 2026-11-02 (`26.10.0`–`26.10.2`, the `dev` tags of
October 2026) contained the pruned SDK and are the project owner's to
withdraw.

### The one thing that is genuinely gated: device definitions

The SDK zip contains the compiler, simulator and docs but **no device files**.
They are fetched by the SDK Manager from
`https://api.gcs.garmin.com/ciq-product-onboarding/devices`, which returns
**HTTP 401** — it needs a Garmin SSO login that cannot be completed headlessly.
(`monkeynet.garmin.com`, also referenced by the SDK Manager, does not resolve
publicly.)

Without them every device-targeted build fails with:

```
ERROR: Invalid device id specified: 'fenix8solar47mm'
```

**They are already vendored** at `vendor/devices/` (copied from the user's macOS
host, `~/Library/Application Support/Garmin/ConnectIQ/Devices/`), including all
three primary targets. `setup-env.sh` installs them.

20 devices are vendored: the three targets plus older-API devices such as
`fenix6`, `fenix6xpro`, `fr245` and `fr255` (`docs/research/probes/
api-gating/`), and the project's first two AMOLED devices, `fenix847mm` and `fenix947mm` (research 11 §3.6).
`setup-env.sh`'s device install is **incremental**: on every run it copies
in whichever device directories under `vendor/devices/` are not yet at the
destination, without touching what is already there — a re-run installs
*every* not-yet-installed vendored device in one pass, not just the one you
wanted (this is how `fenix847mm`'s slice-0 install also brought in
`enduro3`, `fenix5`, `fenix5x`, `fenix947mm`, `vivoactive4` and
`vivoactive4s`). `fenix5`/`fenix5x` (ConnectIQ 3.1.6, this project's lowest
installed ceiling) and `vivoactive4`/`vivoactive4s` initially surfaced three
real gaps this slice-0 install exposed but did not itself fix -- the shared
manifest floor (`3.2.0`) sitting above `fenix5`'s own ceiling, a negative
control (`Weather`/`solarIntensity`) that was not actually universal, and 22
installed `ww` font filenames unmapped in the registry -- all three closed
by lowering `BASE_API_LEVEL` to 3.1.0 and auditing every unguarded API
against `fenix5`'s own `api.debug.xml` (`ts/src/emit/manifest.ts`,
`selectDevices` in `ts/src/build.ts`, `ts/src/data/font-registry.json`). Re-run `setup-env.sh` after
`vendor/devices/` gains a device, or the device builds as `unknown device`.

`vendor/devices/` is **gitignored on purpose** — it is the user's own licensed
copy of Garmin's device files, fine to move around their machine but not
something to commit as redistributable. It therefore travels with the *packaged
directory*, not with the git history. If you restore this repo from a git bundle
alone, the device files will be missing and `setup-env.sh` will tell you so.

If they are ever missing, ask the user to run on their **host**:

```sh
cp -R ~/Library/Application\ Support/Garmin/ConnectIQ/Devices \
      ~/claude/garmin-watchface-protomolecule/.devices-import
```

---

### System fonts: registry fetch, cache, and Garmin's own font root

**The compiler never downloads a font.** It reads a stand-in that is
already on disk, in `ts/assets/system-fonts/` (what a prefetch fills) or
the cache `${XDG_CACHE_HOME:-~/.cache}/wfb/fonts/`, and only when the
file matches its pinned SHA-256 (`NodeFontFiles` in `ts/src/fonts/node.ts`;
`wfb doctor` reports which of the two held each key). A missing stand-in
falls back to a substitute face at build time, with a note.

**Name resolution** (`resolveRegistryKey` in `ts/src/fonts/files.ts`) is
pure and reads only `ts/src/data/font-registry.json`: an exact `names` hit,
then the first matching `patterns` regex, then, only with a face given, the
`faces` table.

**Prefetch.** `ts/tools/fetch-system-fonts.ts --registry` (what
`setup-env.sh` and the Dockerfile run) installs every key the registry
has, the script faces included, so `fallback: auto` never downloads at
build time. Without the flag it installs only what the installed devices'
system fonts need (`--device ID`, `--all` for every device in the
reference). Each key's pinned source is downloaded, and the download and
(for an archive source) the extracted member are checked against the
pinned SHA-256 before anything is written. Each URL is downloaded once
per run: the Roboto release backs 16 keys, every `*-substitute` alias
among them. Beside each font goes `<source>.LICENSE.txt`: the licence's
name and URL, then its text, from the source's `license_member` in the
same archive or from the `license_url` file. The text is not pinned, and
a licence that cannot be fetched leaves the name and URL alone, with a
note. A key already installed with its pinned bytes, beside its licence,
is left alone and costs no download. Noto Sans SC's stand-in is Adobe's
CFF OpenType, installed under its key's `.ttf` name like every other
file; the readers go by contents, not name. `WFB_FONTS_MIRROR`
overrides every source URL's host, for an internal mirror that
reproduces the same paths.

**Garmin's own font files rank above the registry**: the SDK
Manager's `Fonts` directory (next to `Devices`) is the user's own licensed
copy, vendored at `vendor/fonts/` the same way `vendor/devices/` is —
gitignored, incrementally copied into `~/.Garmin/ConnectIQ/Fonts` by
`setup-env.sh`. `garmin_font_root(override=None)` finds it, first existing
non-empty candidate winning: an explicit override (`--fonts DIR`), then
`WFB_FONTS`, then `vendor/fonts/`, then the three per-OS SDK Manager
locations (`%APPDATA%` only consulted when set, for Windows). It is
optional; without it the registry's free stand-ins are used.

**What that actually costs: `wfb preview` draws a
different family's letterforms, not just an estimate of the right one.**
`locate`'s `"garmin"` match and a registry `"exact"`/`"family"` match both
draw the *same* glyph shapes the device does (a free release of the same,
or a closely related, typeface); only `"substitute"` (a different family
entirely: Amiri for Sakkal Majalla and Arimo for Swiss 721 Hebrew, picked
by look; Roboto Condensed Bold for Bionic Cond and the older proprietary
number faces, picked by role) and `"none"`
(Pillow's own bundled default) actually change what a preview draws.
`wfb preview` records every distinct face a run resolved
(`render` in `ts/src/preview.ts`'s own `used_faces` parameter) and prints one warning
to stderr, naming each `"substitute"`/`"none"` font and what was drawn
instead, whenever any were -- never suppressed by `-q`/`-o -`, since it is
a correctness warning, not progress. `wfb doctor`'s `Garmin fonts` line
states the same consequence next to the root it did or did not find. Both
commands take `--fonts DIR` as a one-off override, same as `WFB_FONTS`.

**A `family` match can still move digits.** Bionic, the fēnix 8's
`FONT_NUMBER_*` face, is Rajdhani with its digits redrawn to one tabular
width (0.516 em), every other glyph Rajdhani's own outline, so its
stand-in is Rajdhani (`family`). Without Garmin's files a preview draws
Bionic's letterforms but Rajdhani's proportional digit advances, and the
layout measures digit strings narrow: about 6% over ten digits, a third
for `11:11`. On the metrics probe's 16 Bionic readings that is 296 px of
total error, against 20 px with Garmin's own file (research 40 §4.1).
`wfb preview` does not warn of it, since the match is not `substitute`.

**One root serves measuring, deriving and drawing.** The font root is
owned by `DeviceDatabase` in `ts/src/devices/device.ts` (`DeviceDatabase.discover(...,
fonts_root=...)`) and carried by every `Device` it builds
(`Device.fonts_root`). `ts/src/layout.ts` measures system and vector text with it
(`fallback.measure`/`line_height`/`ascent`), `Device.system_fonts`' derived
loop locates the fenix 9 family's files with it, and `wfb preview --fonts
DIR` passes the same value to both the database and `PreviewOptions`, so a
box is always sized from the file it is drawn with.
`wfb build`/`validate` take no `--fonts`, so their root is `None`: the
ordinary search order above. `wfb doctor --fonts` only reports what
`garmin_font_root(override)` finds.

The directory is flat: `.ttf`, `.cft` and `.md5` files, each named exactly
after the `simulator.json` `filename` (e.g. `RobotoCondensed-Bold.ttf`,
`FNT_FENIX6_CDPG_ROBOTO_20B.cft`). `garmin_any_file` matches the stem
case-insensitively: `.ttf`/`.otf` first, then `.cft` (decoded by
`ts/src/fonts/cft.ts`, `docs/research/10-system-fonts.md` §10), then
`"FNT_" + name` for scraped-only names. `locate(name, face=None,
fonts_root=None)` is the one lookup that puts Garmin's root ahead of the
registry. `WFB_NO_GARMIN_FONTS=1` makes discovery ignore everything but an
explicit override; the test suite sets it.

---

### Known-good reference

`~/claude/garmin-watchface-protomolecule/` is a **working, dense, real** watch
face for the same targets. It builds. Use it as:

- a **validation target** — "can the schema express Dashboard?";
- a source of proven idioms — `source/Data.mc` (refresh tiers, `has` guards),
  `source/Arcs.mc` (pen-width arcs), `source/Icons.mc` (drawn primitives),
  `tools/preview.py` (a 694-line MIP preview renderer worth partially porting).

Treat it as **read-only**. The user asked for it to be left untouched. Note it is
not present in a fresh sandbox — it lives on the user's host.
