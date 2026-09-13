# CLAUDE.md — garmin-wf-builder

Guidance for Claude Code working in this repository. **Read this file fully
before doing anything.** It condenses a completed research phase; re-deriving it
costs hours and the sources are partly unreachable without setup.

**This file is the durable half of the project's memory.** The full,
chronological session-by-session narrative — every feature built, every bug
found and fixed, every wrong turn and its correction — lives in
[`docs/history.md`](docs/history.md), not here. It was split out because it had
grown to 83% of this file's size and was being re-read in full at the start of
every session for a payoff of a handful of facts. **This is a relocation, not a
deletion**: the house style below of leaving a superseded account in place and
adding a correction next to it (rather than deleting it, because the original
reasoning is instructive) is exactly why that narrative still exists in full —
it just lives in the companion file now. When you finish a session that is
worth recording, add its account to `docs/history.md` (with a heading, appended
in chronological order), and lift into this file only the handful of facts that
change what a future session needs to know on turn one. Do not re-inline
history here; that is the mistake this split exists to undo.

---

## 1. What this project is

A **watchface builder framework for Garmin Connect IQ**: a user declares a watch
face's design and data bindings in YAML, and the framework generates a
compilable, sideloadable Connect IQ watch face (`.prg`).

**Target devices:** `fenix8solar47mm`, `fenix8solar51mm`, `fr955`.
**Distribution goal:** personal sideload only (no store submission for now).
**Host OS:** macOS and Linux (containerised).
**Host language:** Python (ADR 0001).

This is a **research-then-build** project. The user explicitly asked for
reasoning to be readable, not just code — `docs/research/` and `docs/adr/` are
part of the deliverable, not scaffolding.

### Status

| Phase | State |
|---|---|
| **Phase 0** — research | **Complete.** `docs/research/00`–`05`. Reviewed by the user. |
| **Phase 1** — ADRs | **Complete.** `docs/adr/0001`–`0009`. Reviewed by the user. |
| **Phase 2** — thin vertical slice | **Complete.** Builds end to end for all three targets; the `.prg` is confirmed running in the simulator on the user's host. |
| Phase 3 — breadth | **In progress, and broad.** All seven element types (`group`, `shape`, `text`, `progress`, `icon`, `graph`, `complication_slot`) plus `static:`, `antialias:`, all four `config:` axes and universal `on_hold:` interactivity have shipped. `type: carousel` shipped and was later **removed outright** on the user's decision. See "Phase 3 roadmap" in §6 for the live checklist of what remains, and [`docs/history.md`](docs/history.md) for the full session-by-session account of how it got here. |

The compiler lives in `wfb/`, the support barrel in `runtime-lib/`, the published
schema in `schema/`, and the example face in `examples/slice/`. `docs/format.md`
is the format reference; `docs/limitations.md` records what the platform and the
linter will not do; `docs/container.md` covers the Docker image, which builds
faces with nothing installed on the host but Docker and the device definitions.

---

## 2. Environment setup — do this first

The environment is **not** in the repo. Rebuild it with:

```sh
./tools/setup-env.sh
```

That script downloads the SDK, generates a developer key, and installs the
device definitions. What it sets up, and why each part matters:

| Piece | Location | Notes |
|---|---|---|
| Connect IQ SDK 9.2.0 | `~/ciq/sdks/9.2.0` | Downloaded unauthenticated from `developer.garmin.com`. 204 MB. |
| Developer key | `~/ciq/developer_key.der` | Plain OpenSSL RSA → PKCS#8 DER. No Garmin tooling needed. |
| **Device definitions** | `~/.Garmin/ConnectIQ/Devices/` | **Cannot be downloaded.** See below. |
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
host, `~/Library/Application Support/Garmin/ConnectIQ/Devices/`). 9 devices,
21 MB, including all three targets. `setup-env.sh` installs them.

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

## 3. Ground truth about the build — corrected

> **The face builds fine in a sandboxed Claude Code session.** Verified:
>
> ```
> $ monkeyc -f monkey.jungle -d fenix8solar47mm -o dash.prg -y ~/ciq/developer_key.der -w
> BUILD SUCCESSFUL
> ```

**The sibling project `~/claude/garmin-watchface-protomolecule/CLAUDE.md` claims
the opposite** — that `developer.garmin.com` is egress-blocked and the face
cannot be compiled in a sandbox. **Both claims are false** and were disproved in
this session (`docs/research/05-device-files.md` §1). That file has not been
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

## 4. Platform constraints that will bite you

These are the findings that shaped every decision. Full detail and citations in
`docs/research/`. **Do not re-litigate these without new evidence.**

1. **There is no device-side renderer.** WFF/Facer/Fitbit all rely on a renderer
   already on the device; Garmin ships none. This is *why* the architecture is
   codegen (ADR 0003) — an interpreter would have to ship inside the same
   128 KB the design must fit in.

2. **Watch faces get 131 072 B (128 KB)** on all three targets — one sixth of
   the 786 432 B the same hardware gives a watch app. 28 of 164 documented
   devices cannot run a watch face at all.

3. **There is no filled-arc primitive.** No `fillArc`, `fillSector` or
   `drawSector` exists anywhere in the API. Rings are `setPenWidth` + `drawArc`
   only — no cap control, no true annulus, no gradient sweep. The schema
   deliberately does not expose `innerRadius`/`outerRadius`.

4. **`onPartialUpdate` overrun is permanent.** Exceeding the budget calls
   `onPowerBudgetExceeded` and disables partial updates **for the remainder of
   the app lifecycle**. Also: `setClip` is charged by *region area* — every
   pixel in the clip counts as modified whenever any does.

5. **AMOLED forbids `onPartialUpdate` entirely.** MIP and AMOLED are structurally
   different low-power paths, not a styling difference. All three targets are
   MIP, but 74/164 devices are AMOLED-class.

6. **API level is NOT sufficient to determine availability.** `fr955` is API
   **5.2.0**, above `onTap`'s documented "since" of **5.1.0**, and still lacks
   `WatchFaceDelegate.onTap`. Always resolve symbols against the device's own
   `<id>.api.debug.xml`, keyed by fully-qualified parent. (`fr955` *does* have
   `InputDelegate.onTap` — a different symbol. Do not be fooled by a bare grep.)

   **6b. And a symbol being present is NOT sufficient either — read its prose.**
   `WatchFaceDelegate.onTap` *is* on both fēnix 8 targets, and it still never
   fires on a face the user is looking at: the SDK entry says "Only available
   in WatchFace config mode". A whole shipped feature (`on_tap:`, and the
   original "tap where available, hold on fr955" design) was designed around
   the symbol table alone and got this wrong — see `docs/history.md`'s
   carousel-interaction session for the correction in full.
   `has_symbol` answers "can I call it", never "will it be called".

6c. **A live watch face receives one gesture: touch and hold (`onPress`).**
   No tap, no swipe, no keys. `ClickEvent.getCoordinates()` is the only way to
   give one hold more than one meaning. Anything modelled on a *stock* Garmin
   face's tap behaviour is modelled on native firmware this API does not
   expose.

6d. **`monkeyc` does not gate on the device's symbol table -- so nothing
   catches an absent symbol at build time.** It resolves names against the
   **SDK-wide** API and checks arity, types and permissions; per-device
   availability it does not check at all. Proof with a clean control
   (`docs/research/probes/device-symbol-gate/`):
   `UserProfile.getFunctionalThresholdPower` is present in
   `fenix8solar47mm.api.debug.xml`, **absent from `fr955.api.debug.xml`**, and
   builds warning-free for `fr955` under `-l 3` -- while a typo in the same
   build is `Undefined symbol`. Two consequences, pulling opposite ways:
   **one shared generated view may reference an API only some targets have**,
   guarded at runtime, with no per-device source split (this is what makes
   on-device config a single view); and **the compiler will never tell you**
   when a binding cannot work on a target -- only `Device.has_symbol` and a
   lint will. Every existing use of `has_symbol` stays correct: it answers
   *what exists on the wrist*, which is the question that was always being
   asked.

7. **A missing permission fails silently.** The API returns null and the element
   never appears, with no diagnostic. The compiler deriving `manifest.xml`
   permissions from bindings is one of the framework's strongest justifications.

8. **Every data field is nullable.** All twenty `ActivityMonitor.Info` fields are
   `… or Null`. Absence is the normal case.

9. **On-device config has exactly four axes** (API 5.1.0, fēnix 8+): Styles,
   complication slots, **one** data colour, **one** accent colour. Max four saved
   configurations. No per-element colour editing. **`fr955` is excluded entirely.**

   **9b. The Data axis takes Garmin complication types only** -- there is no way
   to put author-defined content in a `<complication>`'s list. Author-defined
   selectable content therefore rides **Styles**, whose `styleId` is an opaque
   `Number` Garmin gives no meaning to. And a style is *global*, so the naive
   "one `styleId`, therefore one selectable area" is wrong: every area on the
   face can respond to the same number independently. See research 08 §4.

10. **`alphaBlendingSupport: false`** on all three targets. No transparency.

11. **The graphics pool is separate** — `graphicsResourcePoolSize` is 1 MB,
    distinct from the 128 KB app limit. Makes `BufferedBitmap` cheaper than feared.

12. **`onSettingsChanged` fires only for Garmin Connect pushes**, not on-watch
    edits. Any property write needs explicit cache invalidation.

13. **64-colour MIP palette**: each channel must be `0x00`/`0x55`/`0xAA`/`0xFF`
    or the firmware dithers it and it looks grainy.

14b. **A watch face can plot exactly four time series, and solar is not one.**
    `Toybox.SensorHistory` -- the obvious API, and the only route to pressure,
    stress, elevation and Body Battery *as series* -- has an **empty "Watch
    Face" cell** in `Core_Topics/Manifest_and_Permissions.html`'s permission
    table. It still compiles (see constraint 6d), and then fails silently
    (constraint 7). What is open, all permission-free:
    `ActivityMonitor.getHeartRateHistory` (period as a `Duration` *or* a sample
    count; the iterator carries its own `getMin`/`getMax`),
    `ActivityMonitor.getHistory()` (≤ 7 days), `Weather.getHourlyForecast()`
    and `Weather.getDailyForecast()`. **Solar has no history API at all** --
    only `System.Stats.solarIntensity` and `COMPLICATION_TYPE_SOLAR_INPUT`,
    both current values; the chart on a stock fēnix is native firmware.
    Research 08 §1.

14. **`deviceFamily` in `compiler.json` is the resource-qualifier directory
    name** — `round-260x260` (47 mm, fr955) vs `round-280x280` (51 mm). Read it;
    don't derive it.

---

## 5. Decisions already made

Full reasoning in `docs/adr/`. **Read `docs/adr/README.md` first** — it has the
index and the through-line.

| ADR | Decision |
|---|---|
| 0001 | Host language **Python** (Pillow + fontTools drive it) |
| 0002 | **YAML canonical**, published JSON Schema; GUI is a lossless editor over it |
| 0003 | **Code generation**, not an interpreter; small hand-written support barrel allowed |
| 0004 | Element model; **anchors + relative/polar units**, resolved to px at build time |
| 0005 | Typed data catalogue; **expressions compile to Monkey C**, no runtime evaluator |
| 0006 | Config surfaces, palettes, power modes, tap/hold interactivity |
| 0007 | **Narrow bounded escape hatch** (`raw` element) to hand-written Monkey C |
| 0008 | Build-time lints with **explicit confidence levels**; memory measured, not estimated |
| 0009 | Format versioning and forward compatibility |

### Decisions the user made directly

- **Interaction:** tap where available, **hold on fr955**; both generated from
  one declaration. **Superseded by research, not by later preference — see
  constraint 6c above and `docs/history.md`'s carousel-interaction session.**
  `WatchFaceDelegate.onTap` never fires on a live watch face on any device
  (its own SDK entry: "Only available in WatchFace config mode"); the entire
  input surface is touch-and-hold. The key is `on_hold:` everywhere, not a
  tap/hold split.
- **On-device config:** native editor + phone settings only. **No generated
  on-device settings menu.** Consequence, accepted knowingly: **fr955 gets no
  on-device configuration at all.**
- **Host language:** Python.
- **Repo location:** a new sibling directory, leaving the Dashboard face
  untouched.
- **Blocked sources:** allowlisted `forums.garmin.com` and
  `developer.android.com` (both now reachable).

---

## 6. Where Phase 2 landed, and what Phase 3 needs

### The slice works

```sh
./.venv/bin/python wfb.py build examples/slice/face.yaml
# -> three signed .prg files, no warnings, memory measured per device
```

The brief asked for one command taking `example.yaml` (background + digital time
in a custom font + one arc bound to the step goal + one icon) through validate →
generate → `monkeyc`. That works, for all three targets rather than one.

**Generated Monkey C is in `tests/golden/` and rebuilt into `build/slice/`.** It
is the thing the user asked to review.

### Pipeline, and where each piece lives

| Stage | Module | Needs the toolchain? |
|---|---|---|
| YAML load, with source spans | `wfb/yamlsrc.py` | no |
| JSON Schema, reported against the author's lines | `wfb/validate.py` | no |
| Semantic pass: sources, types, null policy | `wfb/ir.py`, `wfb/catalog.py`, `wfb/expr.py` | no |
| Per-device layout resolve | `wfb/layout.py` | device files only |
| Lint | `wfb/lint.py` | device files only |
| Font baking (TTF → BMFont, subsetted) | `wfb/fonts/` | no |
| Codegen: Monkey C, resources, manifest, jungle | `wfb/emit/` | no |
| `monkeyc`, and the measured memory check | `wfb/build.py` | **yes** |
| Host-side preview | `wfb/preview.py` | no |

889 tests under `pytest -m "not slow"` (only the ones marked `slow` invoke
`monkeyc`), of which **5 are pre-existing, known failures, not regressions to
chase**: `test_example_is_clean_on_every_target[dashboard|big-clock-3|antialias|enduro]`
and `test_ir_draw_order_matches_the_resolved_one[enduro]`. `dashboard` is
explicitly the user's own playground (below) and not a defect to fix unasked.
`big-clock-3`, `antialias` and `enduro` are real, user-authored example content
with genuine lint warnings/errors (e.g. a missing `when_absent:` on a nullable
source in `enduro`) that nobody has asked to have cleaned up — treat them the
same way: not automatically a bug report. If this count or failure set ever
changes, that is worth noticing before assuming it is your own change that
broke something.

### Findings from Phase 2 that were not in the research

These cost real time to discover; do not rediscover them.

1. **`-O z` alone is not enough.** It leaves `Rez.Styles` in the build and warns.
   `-O 3z` (or any level ≥ 2) enables the compiler's `constant-folding` and
   `lexical-only-constants` passes, which is what removes it. The generated
   jungle sets `project.optimization = 3z`; the build command must **not** also
   pass `-O`, or monkeyc warns that one specification is ignored.
2. **An empty `<iq:languages/>` costs about 12 KB of foreground data.** Declaring
   `eng` drops it. This is by far the largest single memory win found.
3. **`--no-gen-styles`** removes the `Rez.Styles` module a generated face never uses.
4. **Launcher icons must match `compiler.json`'s `launcherIcon` size per device**
   or every build warns. The generator draws them at the right size.
5. **The BMFont path works with a plain 8-bit grayscale PNG** and a text `.fnt`.
   No AngelCode BMFont tool is needed; Pillow is enough.
6. **`resourcePath` must not be set in the jungle.** The default jungle already
   puts `resources/` and `resources-<device>/` on every device's path; naming
   them again adds every file twice and warns.
7. **Per-device directories are keyed by device id, not `deviceFamily`.**
   `fenix8solar47mm` and `fr955` are both `round-260x260` but have different
   system-font metrics and different API levels, so their resolved `Layout`
   modules genuinely differ. ADR 0004 §3b is still right that `deviceFamily` is
   the resource-qualifier name — it is just not unique enough to key layout on.
8. **Module members take no access modifier.** `hidden` and `private` are
   class-member keywords; the compiler rejects them inside a `module`.
9. **`monkeyc` finds device definitions through Java's `user.home`**, which comes
   from the *passwd entry* of the running uid, not from `$HOME`. Exporting `HOME`
   has no effect. The symptom is `Invalid device id specified`, which looks
   exactly like a missing device directory. Pass `-Duser.home=` via
   `JAVA_TOOL_OPTIONS` when the running uid has no usable passwd home.
10. **`monkeyc` regenerates `$CIQ_SDK/bin/default.jungle` on every invocation**
   and *replaces* the file, so the SDK's `bin/` directory must be writable — a
   read-only SDK fails with `Unable to generate default.jungle: Permission denied`.
11. **The simulator will not run in this container, and "software OpenGL" is
   not why.** It links against `libwebkit2gtk-4.0`, `libsoup-2.4` and
   `libjavascriptcoregtk-4.0`, which current distributions no longer ship. On an
   `ubuntu:22.04` base, which still packages all three, it **starts** and opens
   its window under Xvfb — then segfaults the moment a `.prg` is pushed with
   `monkeydo`, reproduced with an **unmodified SDK sample `.prg`**, so it is the
   environment, not generated output. The backtrace puts the crash on a worker
   thread **inside the simulator's own stripped binary**, with `libGL` not loaded
   at all. Do not spend another session rebasing the image to get the libraries:
   `/dev/shm` size, seccomp, uid, device-mount writability and WebKit's own
   escape hatches are all ruled out by direct test. `wfb preview` covers the gap;
   see `docs/limitations.md` §2.

### Phase 3 roadmap

`docs/limitations.md` §2 ("Not implemented yet") is the **authoritative,
currently-maintained** list of what is missing — read it, do not re-derive this
from memory or from `docs/history.md`'s session log. This checklist is a
turn-one summary of where things stand; if it and `docs/limitations.md`
disagree, `docs/limitations.md` is right and this needs updating.

**Shipped** (each is a session in `docs/history.md`, in dependency order):

- All seven element types: `group`, `shape` (`rectangle`, `rounded_rectangle`,
  `circle`, `line`, `arc`, `ellipse`, `polygon`), `text`, `progress` (`arc`,
  `bar`), `icon`, `graph` (`line`, `area`, `bars`), `complication_slot`.
- `static:` (paint-once buffering, opaque, later given an ordering rule instead
  of a hard error), `antialias:` (font resource + primitive runtime, two
  unrelated mechanisms under one key), `visible:`, `monospace:` + `align:` on
  fonts, and the mapping form of `elements:`.
- The full data-source catalogue, including all 42 `COMPLICATION_TYPE_*`
  values under `complication.*`, and the icon catalogue sourced from a
  vendored Nerd Fonts build (~10,000 glyphs, plus a named subset).
- Interactivity: `on_hold:` on every element (touch-and-hold only — see
  constraint 6c; there is no tap on a live face), `on_hold: auto` resolving a
  launch target from the element's own bound value, and
  `Complications.exitTo`.
- Configuration (ADR 0006), **all four native axes**: `accent_color` and
  `data_color` (direct colour axes), a Styles axis carrying `color_scheme:`
  (several colours moving together — Styles is the only axis Garmin gives no
  meaning to, so it is the only one that can), and the Data axis as
  `complication_slot` elements the wearer re-points on the watch, including
  the native editor's animated highlight (`AppBase.onStart`,
  `WatchFaceDelegate.onTap`+`getComplicationDrawable` — `onTap` fires **only**
  in config mode, which is the one place it is genuinely usable).
- The refresh-tier concept (ADR 0005 §5) shipped and was then **deleted
  outright** on the user's instruction: every source, `weather.*` and
  `complication.*` included, is now a plain per-frame pull read, and may be
  bound from `low_power`/`always_on` elements (previously a hard,
  unsuppressible error). `WfbCache.mc` and `catalog.Tier` no longer exist.

**Built, then removed outright** — read `docs/history.md` before assuming
either still exists:

- **`type: carousel`** (a row of complications the wearer cycles between,
  hold-left/hold-right/hold-centre by geometry) shipped and was then
  **deleted entirely on the user's decision** — no shim, no
  `carousel-removed` error, no schema remnant. Naming it now gets the
  ordinary unknown-element-type error. `runtime-lib/WfbCarousel.mc` and
  `examples/carousel/` are gone.
- **`on_tap:`** was renamed to `on_hold:` when research showed
  `WatchFaceDelegate.onTap` never fires on a live face; the rename shim (the
  friendly "this key is now called X" error) has since been **deleted
  outright** too — the old spelling is now an ordinary unknown-key error.
- **A font's `size:` bare-number + `scale:` spelling** was deleted outright in
  favour of `Length` (`%r`/`px`) always. `scale:` is not a recognised key.
- **`icon:` no longer accepts a pasted raw character** — only a catalogue name
  or `glyph: "U+XXXX"`, because a pasted glyph is invisible in most editors
  and silently becomes an empty string when lost in a copy (the same hazard
  `wfb/icon_catalog.py`'s own docstring warns its authors about).

**Still not implemented** (see `docs/limitations.md` §2 for the full table
and the ADR each is specified in):

1. **`image` elements** and **the `raw` escape hatch** (ADR 0007) — both give
   a friendly "not implemented yet" error rather than an unknown-key error.
2. **Per-device `overrides`** — parsed and validated, but **writing one is
   now a build error**, not a silent no-op (`wfb/ir.py`'s
   `_check_overrides`). This is a correction, not the original plan: a
   design naming a device that does not exist, or keys no element has, used
   to pass `wfb validate` with no diagnostic at all.
3. **`segments` and `scale` progress styles** (only `arc`/`bar` exist).
4. **Automatic unit conversion** (`units: auto`/`metric`/`statute`) — ADR
   0005 §4 states this as framework-owned; no code exists. Authors convert
   by hand (`examples/dashboard/face.yaml`'s `activity.distance / 100000.0`).
5. **Phone-side settings** (`settings.xml`/`properties.xml`) — the only
   mechanism that would give `fr955` any on-device configuration at all.
   **Started and deliberately frozen, incomplete, on branch
   `wip/phone-settings`** (roughly 1,000 lines across `wfb/ir.py`,
   `wfb/emit/{monkeyc,resources,project,manifest}.py`, `wfb/layout.py`,
   `wfb/lint.py` and the schema). It was cut off by a rate limit partway
   through and the user chose to freeze rather than finish: **treat none of
   it as working** — nothing was driven red, no real `monkeyc` build was run
   against it. `backup/pre-integrate` is a second safety pointer at the
   pre-rebase tip. Do not resume it without checking with the user first.
6. **Catalogue generation from the SDK** (ADR 0005 §1) — hand-written today;
   a drift here would silently mis-declare permissions.
7. **`catalog.Source.requires`** is set (on a handful of sources) and read by
   **nothing** — `wfb/lint.py`'s `check_complication_availability` solves the
   adjacent problem (API-level gating for `complication.*`) by a different
   mechanism (`ComplicationType.since` vs. `Device.api_level`), not by
   reading `requires`. ADR 0008's check 2 ("unsupported API for a targeted
   device") is therefore only partly built.
8. **The GUI** (ADR 0002), deliberately last. Two measured reasons it still
   is not right — unit round-tripping (a drag produces pixels; the format's
   values are proportional and device-dependent) and schema churn (Phase 3
   grew the element vocabulary from 6 to 7, plus config/overrides/
   interactivity) — are in `docs/history.md`'s authoring-ergonomics session.
   **If it is ever built, build it as a thin client over `wfb/preview.py`** —
   an HTML canvas reimplementation would be a second renderer and forfeit
   ADR 0004's anti-drift guarantee.
9. **`mypy --strict` in CI** (ADR 0001's stated mitigation for Python's lack
   of compile-time exhaustiveness over IR node types) — there is no CI
   configuration in the repo at all, and `mypy` is not even a dev dependency.
10. **`wfb install`, `package`, `migrate`** — named in the original brief,
    not built.

**A previously-recorded loose end, now resolved — noted so nobody goes
looking for the problem again:** commit `614d100` added
`examples/big-clock-3/assets/` (eleven fonts) on a commit that briefly fell
out of `main`'s ancestry. Checked while writing this file: those eleven
fonts are back in the tree and tracked at `HEAD` (`git ls-files
examples/big-clock-3/assets/`), so whatever landed them there since — the
`docs/history.md` entry for the original scare predates it — this is no
longer an open issue.

### Hard-won facts recorded nowhere else

These cost real build cycles to find and are not written down anywhere but
here and `docs/history.md` (where each has the full story, probe, and
citation). Losing them means re-discovering them the expensive way.

**Monkey C / compiler behaviour:**

- `Graphics.Point2D` is a fixed-size **tuple**, not `Array<Number>` —
  declaring the generated constant `Array<Array<Number>>` compiles the
  constant fine and then fails at the `fillPolygon` **call site**.
- Type narrowing must go through a **local**, never a repeated field access —
  `_staticBuffer.getDc()` fails even after a null check on the field itself;
  `pulled.value` must be captured into a local first, every time.
- Monkey C has **no explicitly-typed local**: `var x as String? = null` is
  rejected outright.
- An unused **parameter** does not warn; an unused **member variable** does.
  (This is why a delegate takes a `view` parameter unconditionally but only
  holds a `_view` field when something actually reads it.)
- `switch` on a `String` case label compiles cleanly under `-l 3`.
- A typed `catch (ex instanceof ...)` clause works under `-l 3`, and catches
  both a thrown exception and a plain `false` return can be handled uniformly
  by wrapping the call, regardless of *why* a device declines.
- `BufferedBitmapReference.get` is absent from every `api.debug.xml` because
  it is inherited from `ResourceReference` — absence there does not mean the
  method does not exist.
- A helper method must not share a name with the API it wraps: a private
  `setAntiAlias` makes `:setAntiAlias` resolve to **itself**, and warns on
  every target ("will not be found when using the indirect lookup syntax").
  `applyAntiAlias` is warning-free.
- `WatchUi.animate` is documented to **crash the app** in low power mode, and
  the animated property must be public or protected — `animate()` looks it up
  indirectly through a `Symbol`, which a `private` member fails silently
  under (builds, but the lookup fails at runtime).
- `private` genuinely blocks a cross-class method call (confirmed by building
  both ways: dropping the modifier turns `Cannot find symbol ':method'` into
  a clean build) — a generated dispatcher that another generated class must
  call needs to be `public`, even when every other method like it stays
  `private`.
- Switching on `Complications.Id.getType()` — the type the *wearer* picked —
  typechecks under `-l 3` like any other enum switch, which is what lets one
  authored template serve every choice in a re-pointable complication slot
  instead of needing one generated variant per possible choice.

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

**Build-time / codegen lore:**

- Every **supplementary-plane** glyph (anything above the Basic Multilingual
  Plane — all of Material Design Icons' ~7,000 glyphs, for instance) breaks
  the resource compiler's `<font filter="...">` attribute: it is parsed as
  UTF-16 code units, so a surrogate pair splits into two halves matching no
  real glyph. `wfb/emit/resources.py` omits `filter` entirely for a font
  that needs such a glyph — safe, because the `.fnt` is already subsetted by
  this project's own baking.
- `icons.font_key` (and `wfb/layout.py`, `wfb/emit/resources.py`) is keyed
  by the **declared** size and codepoint, never the resolved pixel size,
  because the generated view class is shared across every target device — a
  device-resolved key produces a different `Rez.Fonts.*` symbol per screen
  size and an `Undefined symbol` error on every device but the one the view
  was generated from.
- ruamel 0.19.1's real API for injecting source-position metadata (the
  obvious guess is wrong): a sequence position needs
  `add_idx_line_col(i, [line, col])` (`lc.data` is `None` until the first
  `add`), and an injected mapping key needs
  `add_kv_line_col(k, [l, c, l, c])` — **four** values, because `key()`
  reads slots 0–1 and `value()` reads 2–3.
- Glyph rasterising at small pixel sizes is measurably asymmetric from
  sub-pixel positioning, not curve sampling (a plain square baked lopsided
  is the tell). Rasterising at 16x and box-averaging down cut measured
  per-pixel asymmetry from 16.8% to 0.9%, with cost flat at well under a
  millisecond a glyph. The obvious refinement — padding each glyph
  symmetrically so it lands on a symmetric sample grid — sounded strictly
  better and **measured worse** (1.8% vs 1.5% on average, 24% for one
  glyph); it was dropped. Supersampling alone is the whole fix.
- **A rejected named block's name must still be bound into scope, or every
  reference to it produces a second, misleading error.** This exact
  cascade — one correct error at the real mistake, plus one derived
  "unknown reference" per place that names it, blaming the wrong thing —
  has recurred five separate times as the format grew new named blocks
  (`fonts:`, `config:`, `palette:`, `color_scheme:`, a `config: data:`
  slot). Any *new* named block needs its rejected names bound into scope
  from the moment it is parsed, and the test that proves it is "one error,
  not N."

### `examples/dashboard/face.yaml` is the user's own playground

The user edits this file directly between sessions and has said explicitly:
**it is a playground, leave it alone.** Do not proactively "fix" its lint
warnings, geometry or content — even a broken `wfb validate` or a failing
`test_example_is_clean_on_every_target[dashboard]` is not, by itself, a defect
to correct unless asked. Two sessions have now found this test red on `main`
at the start of work; in one, fixing it was explicitly in scope (a review
task) and the geometry fix was welcomed, in the other the user later edited
the file further and the instruction was to leave it be going forward. When in
doubt here, ask rather than assume — this is the one file in the repo where
"the test suite is red" is not automatically a bug report.

### Known-good reference

`~/claude/garmin-watchface-protomolecule/` is a **working, dense, real** watch
face for the same targets. It builds. Use it as:

- a **validation target** — "can the schema express Dashboard?";
- a source of proven idioms — `source/Data.mc` (refresh tiers, `has` guards),
  `source/Arcs.mc` (pen-width arcs), `source/Icons.mc` (drawn primitives),
  `tools/preview.py` (a 694-line MIP preview renderer worth partially porting).

Treat it as **read-only**. The user asked for it to be left untouched. Note it is
not present in a fresh sandbox — it lives on the user's host.

---

## 7. Working agreement

- **Stop and ask** when a decision materially changes the project's shape
  (authoring format, architecture, scope cuts). Present options with tradeoffs,
  give a recommendation, then wait.
- **Never invent an API.** If a Monkey C symbol cannot be confirmed in
  `<id>.api.debug.xml` or the SDK docs, say so and mark it an open question.
  This rule has already caught a real error (constraint 6 above).
- **Cite sources** — SDK file paths and API levels — in research and ADRs.
- **Prefer a working thin vertical slice** over broad scaffolding.
- **Flag scope cuts early** rather than silently building something smaller.
- If a user requirement turns out to be impossible or badly supported, say so
  directly, explain why, and propose the closest achievable alternative. This has
  already happened three times (tap on fr955, on-device config scope, filled arcs).
- **A guard nobody has watched fail is not a guard.** Drive every new
  diagnostic red against violating input before believing it — and cut the
  whole path, not one branch, or a second branch quietly answers instead and
  a passing test suite means nothing about the fix.
- **The bar for a real build is warning-free, not merely successful.** A
  `monkeyc` run that exits 0 with a warning still failed this project's own
  standard; `wfb/build.py` turns each `WARNING:` line into a diagnostic
  specifically so this is checkable in an assertion, not eyeballed.
- **The obvious test can fail to exercise the thing it is meant to test.**
  `"00:00"` vs `"11:11"` cannot detect a broken monospace-font implementation,
  because Open Sans's figures are already tabular — every digit the same
  width regardless of monospacing. The pair that actually drives it is
  `Fri 11:11` / `Wed 00:00`. When a test can pass against a knowingly-broken
  implementation, it is testing the wrong contrast.
- **"Over-estimating a box is safe" does not transfer** from a bounded
  quantity (a digit count) to an unbounded, localised device string (a
  complication's own label/unit text) — padding for the former produced a
  spurious geometry error on an ordinary design using the latter.
- **When a feature has a truthiness-based on/off switch, adding a
  differently-shaped member to it is the bug to look for.** (`bool(face.
  config)` gated the entire configuration feature in nine places across
  three modules; adding an axis that was not a `ConfigColor` would have
  silently produced no `<watchface-config>` for a design using only the new
  axis, had it not been routed through one shared `Face.has_config` first.)
- **Parallel work in one shared tree must edit files, never run git commands
  that touch the working tree.** `git stash`/`git reset` are repo-wide and
  ignore file ownership; one has already wiped another agent's in-flight
  edits here. Disjoint file ownership is what makes parallelism safe, and a
  stash discards that guarantee for everyone, not just the agent running it.
- **A subagent working in this tree does the work itself and does not spawn
  further helpers.** Two "research-only" subagents once wrote code
  concurrently into the same file and left it holding two conflicting
  definitions. Spawning discards the same disjoint-ownership guarantee one
  level up.

### Documentation discipline

Prose is part of the deliverable. When a change makes any of these stale, update
it **in the same commit**: `docs/research/*`, `docs/adr/*`, this file,
`docs/history.md` (append new session accounts there, not here), and
(once they exist) `README.md`, `docs/limitations.md`, and the format reference.

`docs/limitations.md` exists and is current. It records: no filled arc; the
four-axis / four-configuration on-device config cap; the fr955 exclusions;
single-colour bitmap fonts; no alpha blending; the 64-colour palette rule; what
is not implemented yet; and — separately — **what the linter does not check**,
including the two checks (memory and the partial-update budget) that are
deliberately not allowed to sound exact.

`docs/format.md` is the author-facing format reference. Keep it and the JSON
Schema in step: the schema is normative, the prose explains why.

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
