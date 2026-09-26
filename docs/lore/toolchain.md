# Toolchain, environment and measurement lore

The full text behind root `CLAUDE.md` §2, §3, §6 and §8, with the same
numbering. Add new lore here, not to `CLAUDE.md`.

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
export CIQ_SDK=~/ciq/sdks/9.2.0
$CIQ_SDK/bin/monkeyc -f monkey.jungle -d fenix8solar47mm \
    -o out.prg -y ~/ciq/developer_key.der -w -l 3 -O z
$CIQ_SDK/bin/monkeyc … --build-stats 0     # memory measurement
$CIQ_SDK/bin/connectiq                     # launch simulator (GUI)
$CIQ_SDK/bin/monkeydo out.prg fenix8solar47mm   # push to a RUNNING simulator
```

`monkeyc` runs fine on **OpenJDK 25**. No Java version pinning was needed.

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

## Measurement / build lore (formerly §6 "Hard-won facts")

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
- Compiling a `<watchface-config>` makes this SDK's JVM print a four-line
  `sun.misc.Unsafe` notice using `monkeyc`'s own bare `WARNING:` prefix.
  `wfb/build.py` strips exactly that line shape and nothing else — this is
  the one thing that could silently defeat this project's warning-free bar,
  so it is driven red both ways (a real warning must still surface; the
  notice must not).
- A Styles config entry costs about 9 B data, 28 B code, ~61 B of `.prg` —
  so a Styles cross-product (several `color_scheme:`s, say) is a UX cost to
  weigh, never a memory one.
- **2026-09-13: `monkeyc` 9.2.0 labels each string constant by its Java
  `String.hashCode()`, and crashes when two *different* strings share one.**
  The symptom is only "A critical error has occurred"; with
  `--debug-log-level 3 --debug-log-output` it is `ERROR: assembler:
  Redefinition of label (data) str___<N>`
  (`com.garmin.monkeybrains.compiler2.CompilerException`, from
  `Compiler2.assembleProject`), where `N` is the hash. VERIFIED: the label
  printed, `str___1798574`, is exactly the hash of both the `distance` glyph
  (U+F08F0) and the `temperature` glyph (U+F050F), and a slot whose
  `choices:` lists just those two types crashes on its own. A glyph above the
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
  - **What the compiler does about it** (`wfb/emit/strhash.py`): after
    generating a project, `wfb.emit.project` hashes every string literal in
    the generated sources and the copied barrel. A colliding glyph in
    `IconGlyphs.mc` is emitted as `(0xf050f).toChar().toString()` instead
    of a literal (`Lang.Number.toChar`, API 1.3.0, in `api.debug.xml`), so
    only the colliding keys change and every other design generates
    byte-identical output. A collision it cannot rewrite (for example two
    static `icon:` elements, whose glyphs are literals in the view) is a
    `string-label` build error naming both strings, instead of a monkeyc
    crash. `choices: any` + `icon_size:` (all 42 types) builds warning-free
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
| Connect IQ SDK 9.2.0 | `~/ciq/sdks/9.2.0` | Downloaded unauthenticated from `developer.garmin.com`. 204 MB. |
| Developer key | `~/ciq/developer_key.der` | Plain OpenSSL RSA → PKCS#8 DER. No Garmin tooling needed. |
| **Device definitions** | `~/.Garmin/ConnectIQ/Devices/` | **Cannot be downloaded.** See below. |
| Garmin's own font files (optional) | `~/.Garmin/ConnectIQ/Fonts/` | Also cannot be downloaded; copied from `vendor/fonts/` the same incremental way, if present. See below. |
| System-font registry stand-ins | `wfb/assets/system-fonts/` | Free fonts, downloaded and hash-checked by `tools/fetch-system-fonts.py`. |
| Env vars | `/etc/sandbox-persistent.sh` | `CIQ_SDK`, and SDK `bin/` on `PATH`. |
| Python venv | `.venv/` | `ruamel.yaml`, `jsonschema`, `pillow`, `fonttools`, `pytest`. |

On Debian/Ubuntu, `python3 -m venv` needs `python3-venv` installed separately;
the script says so and falls back to `uv venv` when `uv` is available.

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
api-gating/`), and, since plan 14 slice 0 (2026-09-23), the project's first
two AMOLED devices, `fenix847mm` and `fenix947mm` (research 11 §3.6).
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
against `fenix5`'s own `api.debug.xml` (`wfb/emit/manifest.py`,
`wfb.build.select_devices`, `wfb/fonts/registry.json`; see `tests/CLAUDE.md`
for what was pre-existing before that fix). Re-run `setup-env.sh` after
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

plan 09 (Step A). `wfb/fonts/fetch_system.py` is deliberately
**stdlib-only, no `wfb`/Pillow import** — it must load by
file path (`importlib.util.spec_from_file_location`) before `.venv` exists,
in the Docker SDK stage, and from `wfb doctor` without a rasteriser.

**Name resolution** (`resolve(name, face=None)`) is pure and reads only
`wfb/fonts/registry.json`: an exact `names` hit, then the first matching
`patterns` regex, then, only with `face` given, the `faces` table — the
same order `tests/test_font_registry.py`'s own resolver checks the
committed registry against.

**Fetch/cache.** `ensure(key)` downloads a font-key's pinned TTF into
`${XDG_CACHE_HOME:-~/.cache}/wfb/fonts/<key>.ttf` on demand, checking the
whole download and (for an archive source) every extracted member against
`registry.json`'s pinned SHA-256 before writing anything — one bad hash
refuses the *whole* archive group, not just the one member, so nothing
partial is left behind. An archive shared by several font-keys (the Roboto
release backs nine of them, including every `*-substitute` alias) is
downloaded once per process and every key that needs a member of it is
materialised in the same pass. `path_for(key)`/`tier_for(key)` are the
no-network reads (`wfb doctor` uses these, never `ensure`); `install(keys,
dest)` is the prefetch entry point `tools/fetch-system-fonts.py` and
`setup-env.sh`/the Dockerfile call. `WFB_OFFLINE=1` stops any of this from
reaching the network at all — `tests/conftest.py` sets it for the whole
test session, so a test that needs the online path must `monkeypatch.delenv`
it back off. `WFB_FONTS_MIRROR` overrides every source URL's host, for an
internal mirror that reproduces the same paths.

**Garmin's own font files rank above the registry** (plan 09 R1b): the SDK
Manager's `Fonts` directory (next to `Devices`) is the user's own licensed
copy, vendored at `vendor/fonts/` the same way `vendor/devices/` is —
gitignored, incrementally copied into `~/.Garmin/ConnectIQ/Fonts` by
`setup-env.sh`. `garmin_font_root(override=None)` finds it, first existing
non-empty candidate winning: an explicit override (`--fonts DIR`), then
`WFB_FONTS`, then `vendor/fonts/`, then the three per-OS SDK Manager
locations (`%APPDATA%` only consulted when set, for Windows). It is
optional; without it the registry's free stand-ins are used.

**What that actually costs (plan 12 R1/R3): `wfb preview` draws a
different family's letterforms, not just an estimate of the right one.**
`locate`'s `"garmin"` match and a registry `"exact"`/`"family"` match both
draw the *same* glyph shapes the device does (a free release of the same,
or a closely related, typeface); only `"substitute"` (a different family
entirely, picked for a similar role -- most of Bionic's own weights have
no free release at all and resolve this way absent the root) and `"none"`
(Pillow's own bundled default) actually change what a preview draws.
`wfb preview` records every distinct face a run resolved
(`wfb.preview.render`'s own `used_faces` parameter) and prints one warning
to stderr, naming each `"substitute"`/`"none"` font and what was drawn
instead, whenever any were -- never suppressed by `-q`/`-o -`, since it is
a correctness warning, not progress. `wfb doctor`'s `Garmin fonts` line
states the same consequence next to the root it did or did not find. Both
commands take `--fonts DIR` as a one-off override, same as `WFB_FONTS`.

**One root serves measuring, deriving and drawing.** The font root is
owned by `wfb.devices.DeviceDatabase` (`DeviceDatabase.discover(...,
fonts_root=...)`) and carried by every `Device` it builds
(`Device.fonts_root`). `wfb.layout` measures system and vector text with it
(`fallback.measure`/`line_height`/`ascent`), `Device.system_fonts`' derived
loop locates the fenix 9 family's files with it, and `wfb preview --fonts
DIR` passes the same value to both the database and `PreviewOptions`, so a
box is always sized from the file it is drawn with (plan 18 item 8).
`wfb build`/`validate` take no `--fonts`, so their root is `None`: the
ordinary search order above. `wfb doctor --fonts` only reports what
`garmin_font_root(override)` finds.

The directory is flat: `.ttf`, `.cft` and `.md5` files, each named exactly
after the `simulator.json` `filename` (e.g. `RobotoCondensed-Bold.ttf`,
`FNT_FENIX6_CDPG_ROBOTO_20B.cft`). `garmin_any_file` matches the stem
case-insensitively: `.ttf`/`.otf` first, then `.cft` (decoded by
`wfb/fonts/cft.py`, `docs/research/10-system-fonts.md` §10), then
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
