# CLAUDE.md — garmin-wf-builder

Guidance for Claude Code working in this repository. **Read this file fully
before doing anything.** It condenses a completed research phase; re-deriving it
costs hours and the sources are partly unreachable without setup.

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
| **Phase 2** — thin vertical slice | **Not started.** This is the next work. |
| Phase 3 — breadth | Not started. |

**No framework code exists yet.** Only research instrumentation in
`tools/research/`.

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

7. **A missing permission fails silently.** The API returns null and the element
   never appears, with no diagnostic. The compiler deriving `manifest.xml`
   permissions from bindings is one of the framework's strongest justifications.

8. **Every data field is nullable.** All twenty `ActivityMonitor.Info` fields are
   `… or Null`. Absence is the normal case.

9. **On-device config has exactly four axes** (API 5.1.0, fēnix 8+): Styles,
   complication slots, **one** data colour, **one** accent colour. Max four saved
   configurations. No per-element colour editing. **`fr955` is excluded entirely.**

10. **`alphaBlendingSupport: false`** on all three targets. No transparency.

11. **The graphics pool is separate** — `graphicsResourcePoolSize` is 1 MB,
    distinct from the 128 KB app limit. Makes `BufferedBitmap` cheaper than feared.

12. **`onSettingsChanged` fires only for Garmin Connect pushes**, not on-watch
    edits. Any property write needs explicit cache invalidation.

13. **64-colour MIP palette**: each channel must be `0x00`/`0x55`/`0xAA`/`0xFF`
    or the firmware dithers it and it looks grainy.

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
  one declaration.
- **On-device config:** native editor + phone settings only. **No generated
  on-device settings menu.** Consequence, accepted knowingly: **fr955 gets no
  on-device configuration at all.**
- **Host language:** Python.
- **Repo location:** a new sibling directory, leaving the Dashboard face
  untouched.
- **Blocked sources:** allowlisted `forums.garmin.com` and
  `developer.android.com` (both now reachable).

---

## 6. What to do next — Phase 2

The brief's instruction, unchanged:

> Before any breadth, ship an end-to-end path for **one** device and a minimal
> face: `example.yaml` (background + digital time in a custom font + one arc
> bound to step goal + one icon) → validate → generate Monkey C + resources +
> jungle → `monkeyc` build → launch in simulator → screenshot. **One command.
> Fully tested. Do not proceed until this works, and show me the generated
> Monkey C — the user wants to review its quality and readability.**

Suggested order:

1. `schema/` — JSON Schema + YAML loader carrying **source spans** (line/col) for
   diagnostics. ADR 0002 requires errors to point at the YAML.
2. `devices/` — device database built from `~/.Garmin/ConnectIQ/Devices/*/`
   (`compiler.json`, `simulator.json`, `<id>.api.debug.xml`). **Not** from the
   Phase 0 doc-scraped data in `docs/research/data/`, which was superseded.
3. `compiler/` — IR, layout resolver (relative → absolute px per device), Monkey C
   emitter, resource/jungle/manifest emitter.
4. `cli/` — `wfb build` first; `validate`, `preview`, `simulate`, `screenshot`,
   `install`, `package` later.
5. Golden-file tests over generated Monkey C — these run with **no Garmin
   toolchain**, which matters for CI.

**Generated Monkey C must be readable** — the user will review it. Stable symbol
names from element ids, a header citing source + generator version, comments
tying blocks back to YAML elements, named layout constants (no bare numbers).

Target `-l 3` (strict typecheck) and `-O z` (optimise code space) cleanly.

### Known-good reference

`~/claude/garmin-watchface-protomolecule/` is a **working, dense, real** watch
face for the same targets. It builds. Use it as:

- a **validation target** — "can the schema express Dashboard?" is an excellent
  forcing function;
- a source of proven idioms — `source/Data.mc` (refresh tiers, `has` guards),
  `source/Arcs.mc` (pen-width arcs), `source/Icons.mc` (drawn primitives),
  `tools/preview.py` (a 694-line MIP preview renderer worth partially porting).

Treat it as **read-only**. The user asked for it to be left untouched.

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

### Documentation discipline

Prose is part of the deliverable. When a change makes any of these stale, update
it **in the same commit**: `docs/research/*`, `docs/adr/*`, this file, and
(once they exist) `README.md`, `docs/limitations.md`, and the format reference.

`docs/limitations.md` is a required Phase 3 deliverable and does not exist yet.
It must record at minimum: no filled arc; the four-axis / four-configuration
on-device config cap; the fr955 exclusions; single-colour bitmap fonts; no alpha
blending; and what the linter does *not* check.

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
