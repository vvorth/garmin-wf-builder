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
| **Phase 2** — thin vertical slice | **Complete.** Builds end to end for all three targets; the `.prg` is confirmed running in the simulator on the user's host. |
| Phase 3 — breadth | **Not started.** This is the next work. |

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
| Semantic pass: sources, types, null policy, tiers | `wfb/ir.py`, `wfb/catalog.py`, `wfb/expr.py` | no |
| Per-device layout resolve | `wfb/layout.py` | device files only |
| Lint | `wfb/lint.py` | device files only |
| Font baking (TTF → BMFont, subsetted) | `wfb/fonts/` | no |
| Codegen: Monkey C, resources, manifest, jungle | `wfb/emit/` | no |
| `monkeyc`, and the measured memory check | `wfb/build.py` | **yes** |
| Host-side preview | `wfb/preview.py` | no |

181 tests. Only the ones marked `slow` invoke `monkeyc`.

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
11. **The simulator will not run in this container.** It links against
   `libwebkit2gtk-4.0` and `libsoup-2.4`, which current distributions no longer
   ship, and even with those supplied it segfaults on app load under Xvfb with
   software OpenGL — reproduced with an **unmodified SDK sample `.prg`**, so it is
   the environment, not generated output. `wfb preview` covers the gap; see
   `docs/limitations.md` §2.

### Authoring ergonomics — researched, decision pending

`docs/research/06-authoring-ergonomics.md` evaluates the two options the user
raised (a visual GUI builder, and an LLM skill that works from a sketch) plus
seven alternatives, against four experiments run on the real toolchain.

The finding that drives it: **the project already owns a fast, honest feedback
loop** — `wfb validate` (413 ms) and `wfb preview` (615 ms), both needing no
Garmin toolchain, with diagnostics that name the fix. A deliberately naive design
was corrected to valid in **four rounds using only the compiler's own error
messages**.

**Both were done** (commits after Phase 2): the frictions, then the skill at
`.claude/skills/watchface-from-image/`. `tests/test_skill.py` keeps the skill
honest — it checks that the reference card is a valid design, that every font,
icon, template and command it names exists, and that it still insists on the
validate/preview loop.

Original recommendation: **cheap frictions first, then the skill; defer the GUI.** Two
measured reasons the GUI is not yet right:

- **Unit round-tripping.** A drag produces pixels, but the format's value is
  proportional. `-80.6px`, `-31%` and `-62%r` are identical on the 47 mm and
  differ on the 51 mm — a GUI that writes px back silently destroys the
  cross-device correctness ADR 0004 exists to provide.
- **Schema churn.** Phase 3 grows the element vocabulary 50 % (6 → 9) and adds
  config, overrides and interactivity. A property panel is per-property work.
  ADR 0002 already put the GUI last; the measurement confirms that ordering.

When the GUI is built, build it as a **thin client over `preview.py`** — an HTML
canvas reimplementation would create a *third* renderer and forfeit ADR 0004's
anti-drift guarantee.

### Phase 3 — breadth

`docs/limitations.md` §2 is the authoritative list of what is missing. In rough
dependency order:

1. **Per-device `overrides`** (ADR 0004 §4). Already parsed and validated, not yet
   applied. Doing this first keeps the element work below from being redone.
2. **The `raw` escape hatch** (ADR 0007). The seam most likely to break as codegen
   evolves, so it wants golden tests from day one.
3. **Remaining elements**: `image`, `complication_slot`, `segments` and `scale`
   progress styles.
4. **Configuration** (ADR 0006): the `config:` block, `<watchface-config>`,
   `settings.xml`/`properties.xml`, and the four-axis build-time checks.
5. **Interactivity** (ADR 0006 §6): tap where available, hold on fr955, from one
   declaration — and the compiler must **reject** `on_hold: launch` combined with
   hold-to-cycle on fr955 rather than silently preferring one.
6. **Complications and the `slow`/`event` refresh tiers**, with the TTL cache in
   the barrel.
7. **Generate the data-source catalogue from the SDK** (ADR 0005 §1). It is
   hand-written today; a drifted catalogue would silently mis-declare permissions.
8. The GUI (ADR 0002), last, once the schema has stabilised.

Use the sibling Dashboard face as the forcing function: **"can the schema express
Dashboard?"** is the right question to drive Phase 3 scope.

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

### Documentation discipline

Prose is part of the deliverable. When a change makes any of these stale, update
it **in the same commit**: `docs/research/*`, `docs/adr/*`, this file, and
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
