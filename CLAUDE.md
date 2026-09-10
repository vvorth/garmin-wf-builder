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
| Phase 3 — breadth | **In progress.** See "Phase 3 — breadth" in §6 for the numbered, kept-current checklist of what has shipped and what remains. |

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
   in WatchFace config mode". A whole shipped feature was designed around the
   symbol table alone and got this wrong (see the carousel session below).
   `has_symbol` answers "can I call it", never "will it be called".

6c. **A live watch face receives one gesture: touch and hold (`onPress`).**
   No tap, no swipe, no keys. `ClickEvent.getCoordinates()` is the only way to
   give one hold more than one meaning. Anything modelled on a *stock* Garmin
   face's tap behaviour is modelled on native firmware this API does not
   expose.

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
| Semantic pass: sources, types, null policy | `wfb/ir.py`, `wfb/catalog.py`, `wfb/expr.py` | no |
| Per-device layout resolve | `wfb/layout.py` | device files only |
| Lint | `wfb/lint.py` | device files only |
| Font baking (TTF → BMFont, subsetted) | `wfb/fonts/` | no |
| Codegen: Monkey C, resources, manifest, jungle | `wfb/emit/` | no |
| `monkeyc`, and the measured memory check | `wfb/build.py` | **yes** |
| Host-side preview | `wfb/preview.py` | no |

458 tests. Only the ones marked `slow` invoke `monkeyc`.

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

### Authoring ergonomics — researched, decision pending

`docs/research/06-authoring-ergonomics.md` evaluates the two options the user
raised (a visual GUI builder, and an LLM skill that works from a sketch) plus
seven alternatives, against four experiments run on the real toolchain.

The finding that drives it: **the project already owns a fast, honest feedback
loop** — `wfb validate` (413 ms) and `wfb preview` (615 ms), both needing no
Garmin toolchain, with diagnostics that name the fix. A deliberately naive design
was corrected to valid in **four rounds using only the compiler's own error
messages**.

**Both were done** (commits after Phase 2): the frictions, then the skill.

The skill is **model-agnostic and lives at `skills/watchface-builder.md`** — one
self-contained document for any assistant with file access and a shell.
`.claude/skills/watchface-from-image/SKILL.md` is a thin adapter that delegates to
it, so the two cannot drift; `tests/test_skill.py` enforces that the adapter
stays thin and that every font, icon, template and command the document names
actually exists.

Two supporting changes make it portable: `wfb doctor` reports what is installed
and what to do about what is not, and `wfb.py` re-executes itself under the
project's virtualenv so `python3 /path/to/wfb.py` works from any directory with
any interpreter. A third, added later, makes the tool self-describing:
`wfb help`, `wfb help <command>` and `wfb <command> help` all print that
command's own docstring (`wfb/cli.py`'s `_command()`), so an unfamiliar
caller never has to fall back to a markdown doc to learn what a flag does.

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
5. **Interactivity** (ADR 0006 §6) — **partially shipped.** `on_hold:` exists on
   every element: touch and hold it, and `Complications.exitTo` opens that
   complication's glance. One target per element, resolved per device against
   its own symbol table rather than an API level.

   **This is not "tap where available, hold on fr955" — that premise was
   false, and both ADR 0006 §6 and this file used to repeat it.** A live watch
   face receives exactly one gesture on every device: touch and hold.
   `WatchFaceDelegate.onTap` is documented "Only available in WatchFace config
   mode" and fires solely inside the on-device editor. The key was renamed
   `on_tap:` → `on_hold:` and the dead `onTap` handler deleted; see
   `docs/research/07-carousel-interaction.md` §1 and §6.

   ~~What has not shipped is the rest of §6's vision: an element that
   **cycles** through several complications.~~ **That shipped too, as
   `type: carousel`** — a row of readings the wearer picks between, the
   centred one showing its value. The ADR's "hold-to-cycle and hold-to-launch
   conflict on fr955" warning turned out to be obsolete *and* dissolvable: the
   conflict is universal now that tap is gone, and it is resolved by
   **geometry** rather than by rejecting the combination — the element's box is
   cut into thirds, so hold-left = previous, hold-right = next, hold-centre =
   `exitTo`, all off `ClickEvent.getCoordinates()`. Nothing needs rejecting;
   the compiler lays out zones and lints their reachability. See the session
   note below, `docs/format.md`'s `carousel` section, and
   `examples/carousel/`.

   Still missing from §6: the *other* half of `complication_slot` — a slot
   whose **type** the wearer changes in the on-device editor, which needs the
   `config:` block (item 4 above), not this.
6. ~~Complications and the `event` refresh tier.~~ **Shipped, and then the
   refresh-tier concept itself was deleted outright** — see the session note
   below, "The TTL cache is gone, complications are pulled not cached, and
   all 42 types are sources". `weather.*`'s `slow` tier and its TTL cache
   (`WfbCache.mc`) and complications' `event` tier and its per-type cached
   field are both gone; every source, `complication.*` included, is now a
   plain per-frame read, and every source is bindable from `low_power`/
   `always_on` elements. `wfb/catalog.py`'s `Tier` enum, `Reader.tier`,
   `Reader.ttl_seconds` and `wfb/ir.py`'s `_check_tiers` no longer exist.
7. **Generate the data-source catalogue from the SDK** (ADR 0005 §1). It is
   hand-written today; a drifted catalogue would silently mis-declare permissions.
8. The GUI (ADR 0002), last, once the schema has stabilised.
9. **Primitives, fonts, visibility, authoring form and static buffers** —
   **shipped**, see the session note at the end of this section.

**A six-feature session, orchestrated one task at a time.** All six were
user-requested, specified up front, and built by a subagent each, integrated
and committed between tasks so a failure never spanned two features. The rules
every task obeyed — real `monkeyc` on all three targets and **warning-free**,
not merely successful; every new error driven red against violating input
before it was believed; `tests/golden/` forbidden to move; preview and device
kept in step — are worth reusing verbatim. Two of them caught real problems
that a passing test would not have.

1. **`shape:` gained `arc`, `ellipse` and `polygon`**, which is every remaining
   `Dc` primitive the schema had no access to. `filled:` on an `arc` is an
   error naming constraint 3 above; `filled: false` on a `polygon` is an error
   because `Dc` has **no `drawPolygon`**. `fillPolygon`'s 64-point cap is the
   SDK's own, quoted. The angle conversion is now one function,
   `layout.garmin_arc`, shared with `progress`, so the 12-o'clock-zero
   convention is not implemented twice.

   Fixed a silent bug found while writing it: **`filled: false` was parsed,
   validated and then ignored** on `rectangle` and `rounded_rectangle` — only
   `circle` ever branched on it. Nothing in the repo used `filled:`, so no
   design moved.

   Probe result worth keeping (`docs/research/probes/polygon-const/`):
   `Graphics.Point2D` is a fixed-size **tuple** type, not `Array<Number>`.
   Declaring the generated constant `Array<Array<Number>>` compiles the
   constant fine and then fails at the `fillPolygon` **call site**.

2. **A font's `size:` is now a `Length`** — `18%r` bakes 23 px on a 260 px
   screen and 25 px on a 280 px one. `%` and `pt` are refused (a font has no
   parent box; `pt` is defined in terms of a font). A bare number keeps its
   exact old meaning: the arithmetic is character-for-character the old
   formula, relocated, and every golden artefact byte-compares the same.
   `icons.pixel_size` moved to `wfb/units.py` and is now the single
   `Length -> px` resolver for both the icon and font paths.

   **Deliberately not unified: `icons.bake_size`'s ink-height normalisation
   stays icon-only**, and its docstring now says why. It searches for the
   nominal size whose *one glyph's* ink bbox hits a target height — right for
   an independently-placed icon drawn from ten aggregated third-party sets
   with different em-square padding, wrong for text, where line height,
   baseline and the relative proportions of different glyphs are the point.

3. **`monospace: true` + `align:` on a `fonts:` entry.** The cell is measured
   from the glyphs actually baked, floored at the widest ink, rather than
   trusted from the font's `post` table — so it works on a proportional source,
   not only on a font that calls itself monospaced. Costs nothing at runtime;
   the device just reads advances out of the `.fnt`.

   **The near-miss worth recording**: the obvious test, `"00:00"` vs `"11:11"`,
   **cannot go red** — Open Sans's figures are already tabular, every digit
   19 px. A test built on it would have passed forever against a broken
   implementation. The pair that actually drives it is `Fri 11:11` /
   `Wed 00:00` (132 px vs 164 px proportional, both 279 px monospaced).

4. **`visible:`, a conditional that hides an element or a whole group.** Must
   type as `BOOLEAN` — `visible: activity.steps` is an error naming the type.
   **Absent means hidden**, folded into one guard
   (`if (x == null || !(cond)) { return; }`) rather than a new `when_absent:`
   axis, because there is no meaningful placeholder for existence. That
   `monkeyc` narrows a local across `||` under `-l 3` was probed against a real
   build before the single-guard form was relied on.

   A group's condition is conjoined into every descendant **in the IR, not the
   emitter**. A group emits no draw method and `resolved.items` is flat, so
   pushing the AST down is what makes reader hoisting, permission derivation,
   the preview's evaluator and the linter's folding all work unchanged.

   **`on_hold:` on a hidden element is documented, not gated**, and the
   reasoning is the transferable part: the delegate has no `Dc` and none of
   `onUpdate`'s hoisted locals, so gating means a second copy of the read plan
   in a second file, free to drift — and `onPress` runs at *touch* time, not
   draw time, so a re-evaluated condition answers about a different moment than
   the pixels on screen.

5. **`elements:` accepts a mapping of id -> element**, as well as the list
   form. Both stay valid; not a format-version bump. Implemented as a
   **desugaring pass** (`wfb/desugar.py`) between the loader and the schema, so
   schema, IR, layout, lint, preview and codegen are untouched — which is what
   makes the gate as strong as it is: a design written both ways produces
   byte-identical generated trees **and identical `.prg` checksums** on all
   three targets. Scope is exactly the two places `$defs/element` is
   referenced (top-level `elements:` and a group's `children:`); a carousel's
   `items:` are slots with no id and are never rewritten.

   ruamel 0.19.1's real API, since the obvious guess is wrong: sequence
   positions need `add_idx_line_col(i, [line, col])` (`lc.data` is `None` until
   the first add), and an injected key needs `add_kv_line_col(k, [l, c, l, c])`
   — **four** values, because `key()` reads slots 0-1 and `value()` reads 2-3.

   **The documented cost**: the JSON Schema is normative and describes only the
   list form, so a schema-aware editor red-underlines a valid mapping-form
   file. `docs/format.md` therefore still recommends the list form, and
   `examples/complications/face.yaml` (converted, as the worked proof) drops
   its `yaml-language-server:` modeline with the reason inline.

6. **`static:` — paint once into a `BufferedBitmap`, then blit.** Both
   spellings the user asked for: `static: true` on any element or group, and a
   top-level `static:` block folded into one static group at the front of draw
   order.

   **The design was decided by a probe, not by preference**
   (`docs/research/probes/static-buffer/`). The attractive version — a
   transparent buffer that can sit anywhere in draw order — **cannot be
   established from the SDK**: `Dc.clear()`'s `COLOR_TRANSPARENT` note is about
   the WatchUi *overlay layer*; the one page explaining where a transparent
   index comes from is about **resource-compiler** bitmaps; `drawBitmap`
   documents no transparency at all; and `alphaBlendingSupport` appears nowhere
   under `doc/` and is `false` on all three targets. Against that:
   `pixelFormat` is `ARGB2222`, so a transparent pixel *is* representable —
   suggestive, not decisive. And `setFill`/`setStroke`/`setBlendMode` are all
   present in the symbol tables **despite** `alphaBlendingSupport: false`,
   which is constraint 6b in miniature. So the **opaque** design shipped:
   full-screen buffer, static content a contiguous prefix of draw order, one
   buffer per face. If transparency later holds, only `_check_static_order`
   relaxes; the codegen does not.

   Two things no doc page gives, found by building: the nullable cast
   `.get() as BufferedBitmap?` compiles, but **narrowing must go through a
   local** — `if (_staticBuffer != null) { _staticBuffer.getDc(); }` fails with
   `Cannot find symbol ':getDc' on type 'Null'` (which doubled as the negative
   control proving `-l 3` was really running). And `BufferedBitmapReference.get`
   is absent from every `api.debug.xml` because it is inherited from
   `ResourceReference`.

   `renderStatic(dc)` fills the buffer in `onLayout` **and** is called directly
   from `onUpdate` when the buffer is null, so a device without
   `createBufferedBitmap`, or a failed pool allocation, still renders.

   A static group's generated method name is now a **third reserved symbol**:
   without it a real build produced `Redefinition of 'drawStaticFoo'` pointing
   at generated line numbers — exactly what `wfb/diagnostics.py` exists to
   prevent.

   **Cost measured, benefit not.** Against a hand-written twin drawing the
   identical picture with no buffer (the two previews are pixel-identical):
   +27 B data, +183 B code, 2,769 -> 2,979 B, plus one pool surface of 67,600 B
   (260x260) / 78,400 B (280x280) out of 1,048,576 B. **The benefit is CPU and
   battery and was not measured** — no simulator (finding 11), no watch.
   Nothing in the docs or the code claims a speedup.

**Still open from this session, deliberately:**

* **Transparency for a static buffer** (item 6). It needs a real device or a
  working simulator, and the whole prefix restriction exists only because of it.
* **`graphics-pool` cannot fire as a warning on any current target** — one
  full-screen buffer is 6.4-7.5% of a 1 MB pool — so its threshold is untested
  against real device data. Its estimate also ignores fonts and bitmaps, which
  share the pool; the reported fraction is a floor.
* **`expr.fold` does not short-circuit `and`/`or`**, so `false and X` is not
  folded to `false`. Output is correct either way and `-O 3z` removes the dead
  branch.
* **`docs/format.md`'s suppressible-code count is hand-maintained prose.**
  `tests/test_lint.py` checks each code is *mentioned*, not that the number is
  right.

**Three of that list were then closed** on the user's instruction, in one
follow-up commit. Each is small, and each was the same shape of problem — a
thing the compiler knew and did not say:

1. **Every geometry key is now checked against the shape that reads it**
   (`ir.SHAPE_GEOMETRY_KEYS`), not just the three the arc/ellipse/polygon work
   added. The one that actually bites is `radius:` on a `rounded_rectangle`
   when `corner_radius:` was meant: the corners came out square and nothing
   said a word. `thickness:` is checked against `filled:` rather than against
   the shape, since a `line` and an `arc` always draw with it and everything
   else only does when outlined. **No example in the repo moved**, dashboard
   included, so the behaviour change cost nothing.
2. **A rejected `fonts:` entry no longer cascades.** `Builder` now tracks
   `declared_fonts` and `rejected_fonts`: a font that was declared and then
   rejected produces exactly one error, at the real mistake, instead of one
   more per element naming it — and a genuine *typo* now gets the full
   declared list, where it used to be told `(none declared)` by a file
   declaring three. The two duplicated resolvers (`text`'s `font:` and
   `carousel`'s `value_font:`) collapsed into one `_font_reference`.
3. **`$defs/commonElement` is gone, and the duplication it was reaching for
   with it.** `z`, `on_tap`, `on_hold`, `static` and `overrides` were each
   written out in full in all six element branches; they are now single `$defs`
   entries referenced from every branch, the way `visible:` already was. Two
   tests keep it that way: one fails on any unreferenced `$defs`, the other on
   any common property defined inline rather than as a `$ref` — so a seventh
   element type cannot reintroduce the drift by copy-pasting a sixth.

**A git note, because it cost the user files.** Commit `614d100` ("test work on
new watchface definition") added `examples/big-clock-3/assets/` — eleven fonts,
ChivoMono and SairaStencil among them. A later fix commit was made on top of
`b1c09d9` rather than `614d100`, so that commit is no longer an ancestor of
`main` and those assets are not in the working tree. Nothing is lost; the
commit is intact in the object store and
`git checkout 614d100 -- examples/big-clock-3` restores it. Left undone
pending the user's decision.

Use the sibling Dashboard face as the forcing function: **"can the schema express
Dashboard?"** is the right question to drive Phase 3 scope.

**That question has now been asked once**, in `examples/dashboard/` — a
deliberate reproduction of the reference face. It gets the row structure, the
polar separators, the two-tone clock, conditional colours, the notification badge
and the arcs. What it cannot express is **all data, not layout**: weather, Body
Battery, sunrise/sunset, and the history graph. Three of those are catalogue
entries; the graph additionally wants a series element, and is the strongest
argument in the codebase for building `raw` (ADR 0007) rather than growing the
schema. `docs/limitations.md` §2 records the detail.

Building it also surfaced that **element overlap is not checked** — a separator
drawn through a row of text validates cleanly and only the preview shows it.
That gap is invisible on a sparse face and constant on a dense one.

**A second, distinct lesson from the same build, worth keeping separate:** the
first pass reused the only icons that existed at the time (`heart`, `steps`,
`flame`) for do-not-disturb and alarm, because that is what the catalogue had.
The result validated and compiled cleanly and was actively misleading — a heart
icon next to a do-not-disturb state reads as a heart-rate alert. This is a
content bug, not a layout bug, and nothing in the tool catches it: an icon
means what its shape says, and there is no substitute for having the right
shape. `skills/watchface-builder.md` §"rules" now warns against this directly.

**That in turn led to a bigger change than a three-icon fix.** Hand-drawing
each icon from `Dc` primitives capped the vocabulary at whatever anyone had
drawn, which is exactly what produced the misuse above — there was nowhere
correct to reach for. `wfb/icons.py` now sources every icon from a vendored
Nerd Fonts "Symbols Only" build (`wfb/assets/icons/`, MIT-licensed, aggregating
several CC BY 4.0 icon sets — attributed in that directory's README), baked
into a per-size bitmap font at build time by the *same* pipeline that bakes an
author's own custom text font. An icon element is a `drawText` call against a
baked glyph, not a hand-written drawing function, so `runtime-lib/WfbIcons.mc`
is gone — deleted, not deprecated — and the six catalogue names are not the
ceiling: `icon:` also accepts any single character from the font's ~10,000
glyphs directly, checked against its cmap at build time the same way a custom
font's coverage is checked. Verified end to end through the real toolchain,
including that `monkeyc` accepts a raw UTF-8 Nerd Font character in a Monkey C
string literal with no escaping. One real bug surfaced and was fixed while
building this: an icon's baked-font *identifier* must be keyed by its
**declared** size (`8%r`), not the pixel size that resolves to per device,
because the generated view class is shared across every target device and a
device-resolved key produced a different `Rez.Fonts.*` symbol per screen size
— an `Undefined symbol` compile error on every device but the one the view was
generated from. `wfb/icons.py`'s `font_key` docstring explains this in full;
it is the same stable-name/per-device-content relationship a declared custom
font already has, applied to something that previously had no declared name at
all. Net effect on the dashboard example: better, correctly-labelled icons
(a real alarm clock and bell-slash instead of a borrowed heart and flame) in a
**smaller** compiled `.prg` (4.0 KB vs. 5.6 KB), because one `drawText` call
against a two-glyph font is cheaper than several hand-written primitive-drawing
functions. Growing the *named* catalogue as real designs need specific common
concepts is still worthwhile (so `wfb sources`/`wfb new` can document them),
but it is no longer the only way forward — the raw-glyph escape hatch is.

**A follow-up session hit exactly the ceiling that raw-glyph escape hatch was
meant to remove, and found a real bug underneath it.** Pasting a raw Material
Design Icons glyph (`nf-md` — the font's largest, most consistent set, ~7,000
glyphs) failed `wfb build` with `error[monkeyc]: Font 'Symbols Nerd Font' does
not have characters in the given filter`, even though the generated `.fnt`
genuinely contained that glyph. Root cause: **every MDI glyph in this font
lives above the Basic Multilingual Plane**, and the generated
`<font filter="...">` resource attribute is parsed by the (Java) resource
compiler as UTF-16 code units — a surrogate pair splits into two halves that
match no real glyph. Not a Monkey C limitation (`monkeyc` compiles such a
character in a string literal without complaint) — a narrow resource-compiler
parsing bug. Fixed in `wfb/emit/resources.py`'s `build_bundle` by omitting
`filter` for any font that needs such a glyph; the `.fnt` file it points at is
already correctly subsetted by this project's own baking, so `filter` was
redundant protection for that font anyway. Verified against a real
`BUILD SUCCESSFUL` and in `wfb preview`, not just compiled.

With that fixed, the catalogue was rebuilt to actually prefer `nf-md`: `heart`,
`flame`, `alarm`, `dnd` and `notification` moved from Font Awesome/Codicons to
Material Design Icons, and four new entries were added (`battery`, `floors`,
`distance`, `phone`). `steps` deliberately did not move — MDI's walking/running
figures read as "activity", not "step count" — see `wfb/icons.py`'s module
docstring for the full reasoning, checked at several sizes before deciding.
A large weather-icon table was added at the same time:
`GARMIN_WEATHER_CONDITION_ICON` maps every one of the 54 documented
`Toybox.Weather.CONDITION_*` values (`doc/Toybox/Weather.html`, API 3.2.0) to a
glyph, deliberately drawn from the font's separate, entirely-BMP "Weather
Icons" set rather than MDI's own `weather_*` glyphs (which are themselves all
supplementary-plane, and cover fewer distinct conditions). `weather_icon_for_condition()`
resolves a condition to a codepoint, with a day/night split for the glyphs
that have one. `weather.*` still has no live data source (`docs/limitations.md`
§2), so none of this is wired to anything yet — it is deliberately just the
mapping, ready for the day a source lands. `METRIC_ICON` and
`icon_for_source()` add the reverse direction: the conventional icon for a
`wfb/catalog.py` data-source path (`activity.steps` → `steps`, and so on), a
default rather than something the compiler enforces.

One authoring lesson from writing this catalogue, worth keeping: **every
codepoint in `wfb/icons.py` must be a `\uXXXX`/`\U000XXXXX` Python escape, never
a pasted literal character.** The glyph is invisible in most tools, which is
also why an escape silently becoming an *empty string* is easy to miss — it
still parses as valid Python, and the failure only surfaces later as a blank
tile or a missing-glyph assertion. Every codepoint the catalogue and the
weather table use was looked up directly against the font's own cmap
(`fontTools.ttLib.TTFont(...).getBestCmap()`), not typed from memory or copied
from a cheat-sheet, for the same reason CLAUDE.md already asks this of Monkey C
symbols: a name is a claim about what exists, and it should be checked, not
assumed.

Last question from that session, answered and worth recording: the vendored
font is the **proportional** "Regular" build, not "Mono" (`font["post"].
isFixedPitch == 0`). This is not a defect here — an icon element draws exactly
one independently-positioned glyph, never packed edge-to-edge against another
character the way monospaced text would be — and advance-width vs. ink-bbox
overhang was checked across every catalogue glyph at several sizes, staying
under 2% either side. See `wfb/assets/icons/README.md` for the detail.

**The user built the pushed change and reported the icons looked too small —
a second, real regression from the same nf-md switch, underneath the one
already fixed.** Measured directly: baking `heart` (now Material Design
Icons) and the old Font Awesome glyph it replaced at the *same* nominal font
size produced ink heights of 8px vs. 9-10px at the sizes this dashboard
actually uses (9-12px) — MDI pads its glyphs inside their em-square more
generously than Font Awesome/Codicons did, a real, systematic convention
difference between icon sets, not a one-off badly-chosen glyph. `size:` on an
`icon` element was, until this fix, literally the font's raw nominal size
handed to the rasteriser (`wfb/layout.py`'s `PlacedIcon.size` docstring said
so directly) — meaning it silently meant a different *visual* height
depending on which of the font's ~10 aggregated icon sets happened to supply
a name's glyph. Fixed by having `wfb/icons.py`'s new `bake_size(codepoint,
target_px)` search (not estimate from one ratio — FreeType hinting rounds
differently at the single-digit-to-low-teens pixel sizes real icons are baked
at) for the nominal font size whose own measured ink-bbox height lands
closest to the declared target, per glyph. Because different icons sharing
one declared `size:` no longer necessarily share one nominal bake size,
`font_key` now also incorporates the codepoint (`wfb/icons.py`, `wfb/layout.py`,
`wfb/emit/resources.py`) — still device-independent for the same reason the
length already was: a codepoint does not vary per device, only the resolved
pixel value fed into `bake_size` does. Cost, measured on `examples/dashboard/`:
+112 B across all three targets (4,110 B -> 4,222 B on `fenix8solar47mm`) for
five separate tiny font resources instead of a few shared ones — negligible
against the 128 KB budget. Golden files updated accordingly
(`tests/golden/resources-fenix8solar47mm__fonts__fonts.xml`,
`tests/golden/source__SliceView.mc`) — the `steps` icon (Font Awesome, already
close to filling its em-square) now bakes 2px larger than its declared `20%r`
to hit the same ink height it always rendered at, which is the fix working
correctly, not a drift.

> **The `slow`/`event` refresh-tier machinery this subsection and the next
> describe was later deleted outright** — see "A later session deleted the
> refresh-tier concept outright..." near the end of this Phase 3 section.
> `WfbCache.mc`, `catalog.Tier`, `Reader.tier` and `Reader.ttl_seconds` no
> longer exist. Left as written below because it is what was decided and
> built at the time, the same precedent the `on_tap:` → `on_hold:` correction
> set.

**The same session asked for a dynamic weather-condition icon (now/today's
overall/tomorrow), and it landed as the first real `slow`-tier source** —
bringing forward roadmap item 6 above rather than leaving it for later,
because the user explicitly chose the "build the general mechanism first"
option over a narrower weather-only shortcut when asked. Verified against
the real SDK docs before writing anything: `Toybox.Weather` is supported on
all three targets, needs **no permission at all** (it does not appear in
`Core_Topics/Manifest_and_Permissions.html`'s table, the same situation as
`Toybox.Activity`), and its 54-value `Condition` enum already matched the
`GARMIN_WEATHER_CONDITION_ICON` table from the icon-catalogue session.

What actually shipped, in dependency order:

1. **`Reader` gained `tier` and `ttl_seconds`** (`wfb/catalog.py`) — every
   source sharing a reader must agree with the reader's own tier, checked in
   `tests/test_catalog.py`, since caching is generated once per *reader*, not
   per source (`ActivityMonitor.getInfo()`-style hoisting, reused for
   staleness).
2. **`Source` gained `array_index`** (and a paired `array_guard`), because
   `weather.condition_today`/`_tomorrow` read `DailyForecast[0]`/`[1]` off one
   shared `getDailyForecast()` array, not a field directly off a reader
   object — the first source shape this project has needed that isn't
   "one call, read a field."
3. **`WfbCache.mc`** (new barrel file): one function, `stale(lastRefresh,
   ttlSeconds)`, comparing UTC-second timestamps rather than `Moment` objects
   so the generated code has nothing to null-check beyond the timestamp
   field itself. `wfb/emit/monkeyc.py`'s `ReadPlan.emit_reads` branches per
   reader tier: a `frame` reader is still called fresh every time; a `slow`
   one is read into a private view field only when `WfbCache.stale(...)`
   says so, exactly the "generated code is reviewed by a human" bar ADR 0003
   sets — nothing about this reads as generated-and-forgotten.
4. **`icon_for:`** (`wfb/ir.py`'s `IconElement`, schema): mutually exclusive
   with `icon:`, chooses the glyph on-device at runtime instead of at build
   time. Deliberately narrow — it accepts only a bare
   `wfb.catalog.WEATHER_CONDITION_SOURCES` reference (checked via the parsed
   AST being a plain `expr.Ref`, not any expression that merely *mentions*
   one of those paths), because arithmetic on a condition enum would silently
   break the glyph lookup rather than fail loudly. Reuses the *existing*
   expression-compiler path (`self._expression(node, "icon_for")`) rather
   than inventing a second one, which is also what made every other piece —
   permission derivation, reader hoisting, null-guard generation — apply to
   an icon's bound value for free, with zero new code in `ReadPlan`.
5. **The font for a dynamic icon bakes every weather glyph, not one**
   (`wfb.icons.WEATHER_GLYPH_SET`, 29 glyphs) — the real glyph is not known
   until runtime. `bake_size` (from the ink-height session above) cannot
   normalize all 29 to one nominal size at once: their ink-height ratios
   span 40–100% of the em-square (measured directly, not assumed), so
   `wfb.icons.WEATHER_BAKE_REFERENCE_GLYPH` picks `"rain"`, the centre of the
   largest tight cluster (12 of 29 glyphs land within a few percent of it),
   deliberately trading a smaller rendering for the rarer conditions
   (dust, sandstorm, "unknown") for a correctly-sized one for the common
   ones. `font_key` gained a second, non-codepoint form
   (`icons.DYNAMIC_WEATHER_TAG`) for this shared, multi-glyph font, alongside
   its existing per-codepoint form.
6. **`WfbWeather.mc`** (new barrel file): `iconGlyph(condition)`, a 54-case
   `switch` mirroring `wfb.icons.weather_icon_for_condition()` glyph-for-glyph
   (day glyphs only — there is no sunrise/sunset source yet to pick the night
   variant on-device). Hand-written rather than generated, matching
   `WfbArc.mc`/`WfbTime.mc`'s reasoning: the mapping is fixed and shared
   across every design, so generating it per-project would just be
   re-deriving the same file. Every codepoint was written via a Python script
   emitting real characters (`chr(codepoint)`), the same discipline as
   `wfb/icons.py` itself, and `tests/test_weather_barrel.py` parses the real
   file and checks all 54 cases against `wfb.icons` directly, so the two
   cannot silently drift apart.

One real, separate bug surfaced and was fixed *while building this*, not
introduced by it: `wfb/ir.py` already had a `_check_tiers` check rejecting a
`slow`/`event`-tier binding from a `low_power`-mode element, written and
wired in before any real `slow`-tier source existed to test it against (its
existing test used a `monkeypatch`-fabricated one). `weather.condition` is
the first real source to exercise it, and it did — confirmed firing, with no
changes needed, before writing a second, real-source-backed test alongside
the fabricated one.

Cost, measured on `examples/dashboard/` (which gained a `weather.condition`
icon in row 2, replacing what had been a real-source stand-in row):
6,054 B on `fenix8solar47mm`, still 4.6% of the 128 KB budget. Verified with
real `monkeyc` builds (`BUILD SUCCESSFUL`, all three targets, including a
design binding all three `weather.*` sources at once) and in `wfb preview`.

**A follow-up session found the weather-icon work above had not actually
finished unifying the catalogue** — the 29 day and 14 night weather glyphs
still lived in their own `_WEATHER_GLYPH`/`_WEATHER_GLYPH_NIGHT`/
`_WEATHER_NAMED` dicts, reachable only through a curated 12-name subset, and
worse, their codepoints were pasted as raw characters rather than the
`\uXXXX`/`\U000XXXXX` escapes every other entry used — exactly the mistake
this catalogue's own docstring already warned against. Fixed by folding every
weather glyph into `CATALOG` directly, as `weather_<condition>` and
`weather_<condition>_night` entries (53 total, up from 22) — an author can
now write `icon: weather_rain_night` directly, not just reach it through
`icon_for:`. Every codepoint was regenerated via a script writing real
characters through `chr(codepoint)`, re-verified against the font's cmap, and
each entry gained a `# preview: <char> (<font glyph name>)` trailing comment
purely for a maintainer's editor to render — invisible to Python, which is
exactly why it does not risk becoming another silent empty-string bug.
Considered and rejected moving the catalogue to a separate YAML/JSON/CSV
resource file for easier maintenance: `wfb/catalog.py`'s data-source
catalogue is the same shape of problem and already solves it as a plain
Python list with inline prose, and a non-Python file would have nowhere to
put the reasoning behind specific choices (why `steps` stayed Font Awesome,
why `rain` is the bake-size reference) without an awkward side-channel.

**A second follow-up caught that the unification above still was not
complete on the device side.** `runtime-lib/WfbWeather.mc`'s `iconGlyph()`
took a condition and returned a raw glyph character directly, baked into its
switch statement by a one-off generation script — a second, parallel,
weather-only glyph table on the Monkey C side, the exact same mistake in a
different language. Fixed by splitting the two concerns the way
`wfb.icons` already split them on the Python side: `WfbWeather.mc` was cut
down to `chooseIcon(condition) as String`, returning only ASCII catalogue
*names* (`"weather_rain"`), never a character — genuinely just the on-device
twin of `GARMIN_WEATHER_CONDITION_ICON` now, nothing else. A new generated
(not hand-written) module, `source/IconGlyphs.mc`, provides
`glyph(name as String) as String`, built by `wfb/emit/monkeyc.py`'s
`emit_icon_glyphs` directly from the catalogue every build, covering every
name a dynamic icon in the design could select — the one and only place a
catalogue name becomes a drawn character on-device, for any icon, not a
weather-specific one. `_emit_icon`'s dynamic path now reads
`IconGlyphs.glyph(WfbWeather.chooseIcon(weatherCondition))`. Confirmed
`switch` on a `String` case label compiles cleanly under `-l 3` (strict
typecheck) with a standalone test before relying on it. The catalogue *data*
also moved to its own file, `wfb/icon_catalog.py` — `wfb/icons.py` keeps only
logic (sizing, resolution, the weather-condition table) and imports `CATALOG`
from it, so "add or change an icon" touches exactly one small, data-only
file. Verified with a real `monkeyc` build and in `wfb preview`, and on
`examples/dashboard/`'s real `weather.condition` icon.

**The data-source catalogue (ADR 0005) grew from 28 to 45 entries** in one
pass — a user-supplied list (current/high/low temperature, precipitation
chance, recovery time, running distance, Body Battery, month, day of week,
altitude, pressure, VO2 max) plus a research pass over the same SDK pages for
what else common watchface designs actually show. Nothing was added on
guesswork: every field's own "Supported Devices" list in the SDK doc was
checked against all three targets by name first (several fields on a page
that is otherwise universal turn out to be gated -- `ambientPressure` and
`vo2maxRunning` needed the check, `altitude` and `restingHeartRate` did not).

What shipped, by reader:

- **`ActivityMonitor.Info` (existing `activity` reader, no new permission)**:
  `stressScore`, `respirationRate`, and -- directly answering the "recovery
  time hours" request -- `timeToRecovery`, described in the SDK doc verbatim
  as "Time to recovery from the last activity, in hours".
- **`Activity.Info` (existing `activity_info` reader, same no-permission
  reasoning as `heart_rate.current`)**: `altitude` and `ambientPressure`, as a
  new `ambient.*` namespace -- these are ambient/environmental readings, not
  device settings, so they did not belong under the existing `device.*`.
- **`Gregorian.Info` (existing `date` reader)**: `month` and `day_of_week` --
  both `Number or String` in the SDK's own type, and under this reader's
  `FORMAT_MEDIUM` they come back as localised strings ("Sep", "Wed"), not
  numbers, so both are `Type.STRING` despite the SDK signature's own
  ambiguity. No new reader needed.
- **`Weather.CurrentConditions` (existing `weather_current` reader)**:
  `temperature`, `feelsLikeTemperature`, and -- found while checking the
  class for the requested fields -- `highTemperature`, `lowTemperature` and
  `precipitationChance` are *also* directly on `CurrentConditions`, not only
  on `DailyForecast[0]` as the existing `weather.condition_today` pattern
  might suggest. Reading them there avoids the array-index/bounds-guard
  machinery entirely for these five, and they piggyback on the exact same
  cached read `weather.condition` already pays for. `humidity` and
  `wind_speed` added from the same object as bonus "commonly shown" fields
  found during the same pass.
- **New `user_profile` reader (`UserProfile.getProfile()`)**: `vo2maxRunning`,
  `vo2maxCycling` and `averageRestingHeartRate` (the historically-calculated
  average, not the user-configured `restingHeartRate` profile setting --
  checked both descriptions before choosing), as a new `user.*` namespace.
  The one namespace here that needs a real permission: `UserProfile` was
  already sitting in `WATCHFACE_PERMISSIONS`, unused, since an earlier phase
  -- confirmed it is genuinely allowed for a Watch Face in the SDK's own
  permission table before relying on that.

**Two requests turned out to be infeasible, and are documented as such rather
than faked or silently dropped:**

- **Body Battery** -- unchanged from the earlier finding: `SensorHistory`
  only, which is not a permission a Watch Face may declare, or a
  Complication, which needs the still-unbuilt `event` tier.
- **Total running-only distance** -- the platform's closest equivalent is
  `COMPLICATION_TYPE_WEEKLY_RUN_DISTANCE`, itself a Complication and a
  *weekly*, not all-time, figure; a true all-time total would need
  `UserProfile.getUserActivityHistory()` aggregated by hand, which is real
  computation ADR 0005 deliberately keeps out of the expression language.
  `activity.distance` (today's ambient distance, every activity type) is the
  nearest thing actually bindable.

Also bumped `weather_current`/`weather_daily`'s TTL from the 900s default to
3600s (an hour), per explicit request and because it was already the right
call independent of that: weather changes, and is refreshed upstream, far
slower than every 15 minutes. `Reader.ttl_seconds` was already a per-reader
field (from the slow-tier session above); this is its first real use as
anything other than the default.

`ReadPlan`'s existing per-reader hoisting meant none of this needed new
codegen machinery -- verified with a real `monkeyc` build across all three
targets binding all 17 new sources in one design (including the two new
`Type.STRING` date fields' `.toString()` calls and the `UserProfile`
permission actually landing in the generated manifest), not just `wfb
validate`.

> **The `event`-tier/cached-field design this subsection describes was later
> replaced by a plain pull read** — see "A later session deleted the
> refresh-tier concept outright..." below. `Complications.exitTo` and the
> per-type subscription for freshness both survive; the cached view field and
> the `switch` in `onComplicationChanged` do not. Left as written, per the
> same precedent noted above.

**A follow-up session made Body Battery bindable by building the `event`
refresh tier (ADR 0005) end to end -- Complications, the one piece of that
ADR that was still 0% built.** `Toybox.Complications` (API 4.2.0) delivers a
value through a subscription callback rather than a call the generator can
hoist into `onUpdate`, so `Reader` gained a fourth case alongside FRAME and
SLOW: `Reader.complication_type` names the `COMPLICATION_TYPE_*` constant,
and `Reader.call` for one of these is not an API call at all but the cached
view field `onComplicationChanged` (generated once, shared by every
complication a design binds) writes into -- `ReadPlan.emit_reads` already
branched on tier, so this only needed the branch condition flipped from
"is FRAME" to "is SLOW", not a new code path: EVENT falls through to the
same `var x = call;` line FRAME uses, since by the time `onUpdate` runs the
value is already sitting in the field. `onLayout` gained one
`registerComplicationChangeCallback` plus one `subscribeToUpdates` per
complication (`WfbComplications.mc`, a new barrel file), and `_features()`
in `wfb/emit/project.py` -- previously a stub returning `set()`
unconditionally, with the `minApiLevel`-bumping machinery it should have
driven already sitting unused in `wfb/emit/manifest.py` -- now actually
detects complication usage from `face.requirements().readers` and wires it
up, so `minApiLevel` correctly reaches 4.2.0 only when a design uses one.

Both an existing generalisation and a real gap surfaced in `wfb/emit/
monkeyc.py` while wiring the element side through. `declarations()` and
`guards()` had silently assumed every `field_name is None` source was
`time.clock`/`date.today` (both handled entirely inside `formatting.py`,
which reads the reader parameter directly and never goes through a
declared local) -- true by accident, not by design, and false the moment a
complication source arrived, since a complication's reader *is* its value
the same way `time.clock`'s is, but for a `Type.NUMBER`/`STRING`/`FLOAT`
source that generic formatting path very much needs its own named local.
Fixed by narrowing the skip to `field_name is None and type in (TIME,
DATE)` in `declarations()`, and dropping the `field_name is not None`
restriction from `guards()` entirely (provably a no-op for time/date, since
neither is ever nullable) -- the same fix both places, once recognised as
one bug rather than two.

Researched all 43 `COMPLICATION_TYPE_*` values (`Toybox/Complications.html`)
against what the catalogue could already read directly, and added nine as
new sources, each genuinely unreachable any other way: `body_battery.current`
(the concrete ask), `system.solar_input`, `weather.sunrise`/`sunset`,
`activity.training_status`, `activity.weekly_run_distance`/
`weekly_bike_distance`, and `activity.sleep_score`, plus
`device.next_calendar_event`. Deliberately left out: everything duplicating
a source already bound directly through `ActivityMonitor`/`Activity`/
`Weather`/`UserProfile` (steps, calories, heart rate, altitude, VO2 max,
recovery time, stress, current/forecast weather, current temperature, and
more -- a direct read is cheaper and needs no subscription), and the niche
ones (eight race-time/race-pace predictors, golf score, wheelchair pushes).
`Activity.Info.currentOxygenSaturation` (pulse ox) was added too, but *not*
as a complication -- `COMPLICATION_TYPE_PULSE_OX` exists, but the value is
already a direct `Activity.Info` field, the same no-permission reasoning as
`heart_rate.current`, so a complication for it would only add a subscription
for no reason. Confirmed present on all three targets by reading its own
"Supported Devices" list directly, the same discipline as every other field
added this project (it is device-gated in the SDK doc, unlike
`currentHeartRate`).

One real device-gating question came up and was resolved by testing, not
assumption: `COMPLICATION_TYPE_SLEEP_SCORE` needs API 6.0.2, above `fr955`'s
own ConnectIQ ceiling (5.2.0, from its `compiler.json` -- confirmed there
rather than guessed, since `docs/research/data/devices/*.json` does not
record this). Rather than drop the source or invent per-device catalogue
gating (a much bigger change), a real standalone `monkeyc` build confirmed
`Complications.subscribeToUpdates` throwing `ComplicationNotFoundException`
is catchable with a typed `catch (ex instanceof ...)` clause under `-l 3`,
so `WfbComplications.mc`'s `subscribe()` wraps every subscription in one,
uniformly, regardless of *why* a device declines a type (a thrown exception
or a `false` return are both covered). `activity.sleep_score` shipped rather
than being dropped, on the strength of that verification: it just never
updates on `fr955`, silently, the same "absence is normal" contract as any
other nullable source. This also surfaced a real, separate, pre-existing
gap worth its own note: `catalog.Source.requires` (`Parent.name` symbols a
binding needs on-device) has existed since the original catalogue and is
set on exactly one source (`device.do_not_disturb`), but nothing anywhere
-- not `wfb/lint.py`, not `wfb/ir.py` -- ever reads it. Recorded in
`docs/limitations.md` §3 rather than fixed now: the runtime behaviour here
(silent absence via the try/catch) is correct on its own, but a build-time
lint would still be strictly better than discovering a blank field on the
wrist, and `requires` is exactly the field such a lint would consult, once
one is written.

Verified end to end with a real design binding ten sources (all nine new
complications plus `pulse_ox.current`) built through the real toolchain
across all three targets: `BUILD SUCCESSFUL`, `minApiLevel="4.2.0"` and
`<iq:uses-permission id="ComplicationSubscriber"/>` both present in the
generated manifest exactly when a complication is bound and absent
otherwise, and `WfbComplications.mc` pulled into the barrel only then too --
not just `wfb validate`.

**That session also went sideways on git** (interactive rebase, aborted, a
partial manual commit, `main` briefly regressed 8 commits behind where it
should have been) and was recovered by resetting `main` back onto the correct
tip and re-committing the Complications work from scratch on top of it, in
three commits (implementation, tests, docs) rather than one -- the history is
clean now, and there is nothing left to do about it; it is recorded only
because the recovery surfaced the filesystem quirk noted in §2.

**A follow-up session made `wfb` self-describing: `wfb help`, `wfb help
<command>` and `wfb <command> help` all now work, and are one command's
docstring away from drifting out of sync with `--help` itself, which they
cannot do because they do not duplicate it.** `_command()`
(`wfb/cli.py`) reads each handler function's docstring once -- the first
line becomes the short summary `wfb --help`'s command table shows, the
whole docstring becomes what `wfb <command> --help` prints -- and
`_rewrite_trailing_help()` turns a trailing `help` into `--help` before
argparse ever sees it, so all three spellings produce byte-identical output
(a test pins this down: `tests/test_cli.py::
test_every_command_help_is_sourced_from_its_own_docstring` fails if anyone
ever reintroduces a hand-written `help=`/`description=` string that could
diverge from the docstring it now always matches). The module docstring at
the top of `wfb/cli.py` is `wfb --help`'s own top-level description for the
same reason. `wfb doctor`, `wfb sources` and `wfb devices` were already the
answer to "what can I bind, what can I target, is my environment ready" --
this closes the last gap, "what does this command actually do," so an
unfamiliar caller (human or model) never has to fall back to a markdown doc
to find out.

**A review session went looking for logical errors rather than building a
feature, and found seven real ones — every one reproduced against the real
toolchain before being believed, and every one now fixed with a test.** They
are recorded here because five of the seven were *silent*: the compiler
accepted the design, generated code, and did the wrong thing without a word.

1. **`when_absent: fallback` was never emitted.** Codegen routed anything that
   was not `placeholder` into the same early `return` as `hide`, so a declared
   fallback silently hid the element — while `wfb/preview.py` *did* evaluate
   it. Preview and device disagreed, which is the one invariant the shared
   resolved geometry exists to guarantee. Fixed for `text` and `progress`, and
   `wfb/layout.py`'s widest-rendering and `wfb/emit/resources.py`'s glyph set
   now include the fallback too — otherwise a subsetted font could be missing
   the very glyphs the fallback needs.
2. **Two element ids could collide into one generated symbol.** `temp_low` and
   `tempLow` both derive `TEMP_LOW`/`drawTempLow`; `wfb/ir.py` only rejected
   duplicate *literal* ids. The build reported "no diagnostics" and then
   `monkeyc` failed with four `Redefinition of ...` errors pointing at
   generated line numbers — exactly the failure `wfb/diagnostics.py` exists to
   prevent. Symbol derivation moved into `wfb/ir.py` (`element_const_prefix`,
   `element_method_name`) so it is checked where ids are checked, and
   `wfb/emit/monkeyc.py` imports it rather than keeping a second copy.
3. **`activity.active_minutes_week` could not compile at all.** Its
   `field_name` is the dotted path `activeMinutesWeek.total`, and the
   intermediate is itself nullable. `Source.intermediate`/`intermediate_guard`
   now express that, and `ReadPlan.declarations` hoists the intermediate into
   its own local first — a single ternary (`(r.f != null) ? r.f.x : null`)
   does **not** work, confirmed standalone: monkeyc's flow typing narrows a
   *local*, not a re-evaluated field-access expression. A new `slow` test
   builds a design binding **every** catalogue source, which is what would
   have caught this; it was the only one of the 55 that failed.
4. **`/` was typed Float on the host and integer-divided on the device.**
   `check()` types any `/` as Float and the preview evaluates it as one, but
   the emitter passed `/` through and Monkey C truncates `Number / Number`.
   `activity.steps / 1000` — the idiom `Expression.scale` explicitly names —
   showed 8.5 in preview and 8 on the wrist. The emitter now coerces when
   neither operand is already a Float.
5. **`when_absent:` only ever covered `value:`.** A nullable source in
   `color:`/`track_color:`/`max:` needed no policy, and codegen then emitted an
   *undeclared* hide guard — a clock bound to `time.hour` vanished whenever a
   conditional colour's heart-rate source was absent. Two further bugs sat
   under this one: `when_absent: placeholder` skipped the guard for *every*
   bound source, so a nullable colour on the same element failed to build; and
   once fixed, a placeholder whose sources are all also read by the colour
   becomes dead text, which now warns rather than sitting there unreachable.
6. **`modes: [always_on]` elements were generated and never called.**
   `onUpdate` filtered on `active`, `onPartialUpdate` on `low_power`, and
   nothing drew `always_on` — while `docs/format.md` documented it plainly and
   `wfb/lint.py` recommended it for AMOLED. The view now tracks `_sleeping`
   and `onUpdate` draws the `always_on` set while asleep, emitting nothing
   extra for designs that do not use it.
7. **`onComplicationChanged` called `getComplication` unguarded.** It throws
   `ComplicationNotFoundException`, and the callback fires when a complication
   "is changed **or becomes unavailable**" — an uncaught throw takes the face
   down. `WfbComplications.valueOf` now wraps it in the same typed catch
   `subscribe` already used. That module's docstring also claimed to "catch"
   `subscribeToUpdates`'s `false` return; it discards it, and now says so.

**Two linter-credibility bugs came out of the same pass.** `palette-dither`
and `partial-update-budget` were listed as suppressible but emitted through
`bag.warning` directly rather than `_emit`, so neither could be suppressed —
and the palette one printed advice that provably did not work (following it
verbatim left the warning in place). Both are now honoured on the elements
that actually cause them: an element whose `color:`/`track_color:` is exactly
`palette.<name>`, or any element drawn in `low_power`. Separately, an unknown
or deliberately-unsuppressible code in `allow:` was accepted in silence; it is
now an error that distinguishes the two cases, backed by `lint.ALL_CODES`,
whose test re-derives the set from the source so it cannot rot.

**One documentation claim was simply false and is now corrected.**
`docs/limitations.md` listed "per-device API availability" under *Checks that
are exact*. `Device.has_symbol` is implemented, correct and unit-tested — and
called from nowhere in the pipeline, as is `catalog.Source.requires`. ADR
0008's check 2 is unimplemented, and the same document said so three headings
lower while claiming the opposite above. ADR 0008's own suppression example
was also written `palette_dither` with an underscore, which the real code
would have rejected — the kind of drift the new `lint-allow` check now catches.

`examples/dashboard/face.yaml` was red on `main` when this started: two WIP
commits added content without re-checking geometry, leaving 25 safe-area and
text-overflow warnings and a comment truncated mid-sentence. Fixed by geometry
alone (no `format:` narrowing, no suppressions), including reordering the
weather row so the two wide `H:`/`L:` labels flank the icon and the narrow
readings take the outer slots a wide label cannot reach without crossing the
bezel.

**A process note worth keeping, because it cost real work.** This session ran
four agents in parallel against one shared working tree. Two of them reached
for `git stash`/`git reset` to test something, which is repo-wide: it wiped
another agent's in-flight edits and a set of documentation changes that had
nothing to do with either. Nothing was permanently lost, but the lesson is
cheap to record and expensive to relearn — **parallel work in one tree must
edit files, never run git commands that touch the working tree.** Disjoint
file ownership is what makes the parallelism safe, and a `git stash` ignores
ownership entirely.

**A later session added `glyph:`, `on_tap:` (since renamed `on_hold:`), and a
rewritten glyph rasteriser.** All three came from the user; the research behind each is below,
because in two of the three the obvious approach was wrong.

**1. `glyph: "U+F0BC"` — a codepoint the catalogue does not name.** `icon:`
already accepted a bare character pasted into the YAML, but that is the exact
hazard `wfb/icon_catalog.py`'s docstring warns about for this project's own
source: the character is invisible in most editors, silently becomes an empty
string when it gets lost in a copy, and is unreviewable in a diff. `glyph:`
takes Unicode's own notation instead, checked against the font's cmap at build
time. A codepoint that *is* in the catalogue is accepted with a note pointing
at the name, which is the better spelling — a name keeps meaning when the
catalogue moves an icon to a different codepoint, which has already happened
once (the Font Awesome to Material Design Icons switch).

**2. `on_tap:` — the one exit a watch face has.** Researched before writing
anything, and the finding that shapes it: a watch face cannot launch an
arbitrary app. The platform offers exactly one door, `Complications.exitTo`,
"launches the app associated with the complication" (API 4.2.0, present on all
three targets). So an interactive element names a **complication type** and the
watch opens whichever glance owns it. `wfb/complications.py` lists all 42,
generated by reading the SDK's own `COMPLICATION_TYPE_*` table rather than
typed out; `wfb complications` prints them.

> **Superseded, and the correction is worth reading in full: see the carousel
> session below.** This session concluded "tap where available, hold on fr955",
> emitted both handlers, and named the key `on_tap:`. All of that rested on
> missing one sentence in `WatchFaceDelegate.onTap`'s own SDK entry — *"Only
> available in WatchFace config mode"*. There is no tap on a live watch face,
> on any device. The key is now `on_hold:`, the `onTap` handler is gone, and
> `check_tap_targets` is `check_hold_targets`. The paragraphs immediately below
> are left as written because the mistake is instructive: every individual fact
> in them was checked against the device symbol tables, and the conclusion was
> still wrong, because the symbol being present was taken as proof the callback
> fires.

Three things were checked against the device symbol tables rather than assumed,
and two of them contradicted the API levels:

* `WatchFaceDelegate.onTap` is documented "since 5.1.0" and is **absent on
  fr955**, which is 5.2.0 — CLAUDE.md constraint 6, confirmed again.
* `onPress` (touch and hold) is documented at the same 5.1.0 and **is** present
  on fr955. So "tap where available, hold on fr955" is exactly implementable,
  which is what ADR 0006 §6 chose. *(Wrong: `onTap` being present says nothing
  about it being called.)*
* A single shared delegate defining **both** handlers compiles cleanly on
  fr955 under `-l 3` — verified with a real standalone build before relying on
  it, since defining a method the parent class does not declare could have been
  rejected. It is not, so one delegate serves every device and the author
  writes one `on_tap:`.

`minApiLevel` therefore comes from `exitTo`'s 4.2.0, **not** `onTap`'s 5.1.0: a
watch below 5.1.0 runs the face perfectly well, it just does not deliver
touches, and nothing emitted references `onTap` in a way the compiler must
resolve. The hit region is deliberately the element's own drawn box — inflating
to a minimum touch size would invent a number Garmin does not publish and would
silently overlap neighbours on a dense face; an author who wants a bigger
target holds a `group`.

This is also **the first thing in the compiler to use `Device.has_symbol`**,
closing part of the gap `docs/limitations.md` §3 records; it now resolves
`onPress` against each target's own `api.debug.xml`. `catalog.Source.requires`
still consults nothing, so ADR 0008's check 2 is only partly built.

**3. The glyph rasteriser was measurably broken, and the obvious fix was the
wrong one.** Round and symmetrical icons came out lopsided. Measured before
touching anything, over 99 glyphs from the vendored font that are provably
symmetric (they mirror exactly when rendered at 256px), across 12 sizes from 8
to 28px: **16.8% of ink pixels landed asymmetrically**. A plain square baked to
7x7 ink inside an 8x8 tile; `md-circle_outline` at 16px was lopsided in every
row.

The cause is **sub-pixel positioning, not curve sampling** — a plain square
coming out wrong is what makes that clear. The outline's true origin is
fractional, `ImageDraw.text` at an integer position drops that fraction, and the
1-bit threshold then turns a half-covered edge pixel into ink on one side and
nothing on the other.

Fixed by rasterising at 16x and box-averaging down, which recovers real
per-pixel coverage before the threshold sees it: **16.8% -> 0.9%** through the
real pipeline. The factor was chosen by measuring rather than picked — asymmetry
falls monotonically (4.5% at 4x, 1.8% at 8x, 1.1% at 16x, 0.7% at 24x) while
cost stays flat at well under a millisecond a glyph, because the work is
per-glyph overhead rather than pixels.

**The obvious refinement made it worse and was dropped.** Padding each glyph
symmetrically so a symmetric shape lands on a symmetric sample grid sounds
strictly better and measured *worse* on average (1.8% vs 1.5% on the first
sample), badly so for individual glyphs — `fae-ring` at 10px went from 0% to
24%. Supersampling alone is the whole fix.

Advances and line metrics deliberately stay at the target size, so this changes
how a glyph looks and never where it sits: no golden file moved, and text
improved as much as icons (`'0'` in Open Sans at 20px went from 44.4%
asymmetric to 0.0%).

**A session asked whether the fr955 stock face's data carousel could be
reproduced, and the research overturned a shipped feature.**
`docs/research/07-carousel-interaction.md` is the document; the probe that
backs it is `docs/research/probes/carousel/`. Read §1 before touching anything
interactive.

The headline: **`WatchFaceDelegate.onTap` never fires on a live watch face, on
any device.** Its SDK entry carries the sentence "Only available in WatchFace
config mode" — the same sentence that marks `getComplicationDrawable` and
`onWatchFaceConfigEdited`, both unambiguously editor-only. The SDK's only
sample implementing it (`samples/ConfigurableWatchFace`) uses it solely to call
`setSelectedComplication`, i.e. to tell the *editor* which slot the user
picked. Garmin's forums say the same thing plainly. So touch and hold
(`onPress`) is the entire input surface a watch face gets: no swipe (that is
`BehaviorDelegate`, which a face never installs), no keys, and
`configureTouchEvents` is watch-apps-only.

**This invalidated ADR 0006 §6's premise and the `on_tap:` feature built on
it.** Fixed in this session, not deferred: the key is renamed **`on_hold:`**
(the old spelling is now an error naming its replacement, `on-tap-renamed`),
the dead `onTap` handler is deleted from the emitter, `check_tap_targets` is
`check_hold_targets` and resolves only `onPress`, and the `tap-unsupported`
note — which said fr955's targets "are reached by touch and hold instead", true
and actively misleading, since it implied the fēnix 8s got taps — is gone
entirely. ADR 0006 §6 carries an amendment rather than a rewrite; `docs/
format.md`, `docs/limitations.md` and constraint 6 above are corrected.

**The instructive part is *how* the original was wrong.** Every individual fact
in it was checked against the device symbol tables, exactly as this file
demands. The error was treating "the symbol is present" as "the callback
fires". Hence new constraint 6b: `has_symbol` answers *can I call it*, never
*will it be called* — read the method's own prose too.

**One thing the correction improved rather than only cost.** ADR 0006 §6 said
hold-to-cycle and hold-to-launch "conflict on fr955" and that the compiler must
reject the combination. With tap gone the conflict is universal — and also no
longer a conflict, because `ClickEvent.getCoordinates()` separates the two
meanings by *geometry*: hold-left = previous, hold-right = next, hold-centre =
`exitTo`. Nothing needs rejecting; the compiler lays out zones.

**On the carousel itself: buildable on all three targets, and cheap.** A
hand-written probe exercising `WatchUi.animate()` on a `WatchFace` subclass,
`cancelAllAnimations`, `Application.Storage` for the index, `onPress` with
three coordinate zones, and `Complications.exitTo` builds `BUILD SUCCESSFUL`
under `-l 3` on all three at **597 B data + 785 B code** — about 1% of budget.
Two things came out of that build a doc page would not have given: the
animated property **must be public or protected** (`animate()` looks it up
indirectly through a `Symbol`; `private` builds but warns that the lookup will
fail), and animation is legal **only while the face is awake** — `animate()` is
documented to *crash the app* in low power mode, so generated code must guard
on the existing `_sleeping` field and degrade to an instant jump. The
interaction and the animation window coincide, since a touch is one of the
things that keeps the face in high power mode, so this works — but it is a
guard, not an assumption. `docs/research/07-carousel-interaction.md` §7
proposes the format.

**The element was then built, in the same session, as `type: carousel`.**
`examples/carousel/` is the worked example; it compiles on all three targets
at **2,887 B (2.2% of budget)** for a whole face — the carousel itself is
about 1.4 KB of that, matching the probe. `wfb preview` renders it.

What it does: a row of icons, the centred item drawn in `color:` with its
reading at `value_offset:`, its neighbours in `inactive_color:`, moved by a
hold and remembered in `Application.Storage`. The pieces, and why each is
where it is:

* **`size:` is the touch target, not the drawn extent** — the one element in
  the format where those differ. It is split into equal thirds, so being
  generous with it costs nothing and makes the zones hittable. This forced a
  real distinction in `wfb/layout.py`: `PlacedCarousel.content_box` is what the
  element paints, and `inside_visible_area_for` reads *that* rather than `box`,
  because otherwise every reasonably-sized carousel warns `safe-area` for a
  touch region that was deliberately large. Reachability is then its own
  check, `check_carousel_zones`, which is the honest place for it: it warns
  when a third is under 40px (a judgement, labelled as one — Garmin publishes
  no minimum touch size) and when a zone reaches under a round screen's bezel
  (exact geometry).
* **`when_absent:` is per *item*, and a carousel is the only element that skips
  the element-level null guard entirely.** Every other element hides as a whole
  when a binding is absent; here that would make the row collapse and the zones
  move under the wearer's finger. Each item's policy is applied inside its own
  `case` instead — `hide` blanks that item's reading and leaves its icon drawn.
  The consequence, made an error rather than left implicit: **a carousel's own
  colours may not be nullable**, since there is no `when_absent:` for the row's
  appearance. `ReadPlan._value_expressions` returns every item's expressions so
  none of them lands in `_other_bound` and re-acquires an element-level guard
  by the back door.
* **Icons are inferred from the data source** where `wfb.icons.METRIC_ICON` has
  a convention, which is the first real use of that table — a row of nine
  readings is exactly where naming nine icons by hand is worst.
* **Each item gets its own single-glyph icon font**, for the same
  per-codepoint `bake_size` reason a standalone icon does. Measured cost on
  the example: four tiny font resources rather than one shared.
* **`launch:` is optional per item**, and `launches_a_glance(face)` is now
  separate from `hold_targets(face)`: a carousel is interactive without
  necessarily opening anything, so a design where no item declares a `launch:`
  gets no `ComplicationSubscriber` permission, no `minApiLevel="4.2.0"`, and no
  `import Toybox.Complications` in the delegate. Confirmed by test, not assumed.
* **The delegate now holds the view** (`new <Face>Delegate(view)`), because a
  zone hit has to call `stepData(-1)` on it. Unconditionally, including for a
  face with no carousel — one delegate shape reads better than two.
* **`_sleeping` is emitted for a carousel too**, not only for `always_on`,
  because the slide has to check it. `WatchUi.animate` crashing the app in low
  power mode is documented, not defensive.
* **`WfbCarousel.mc`** is the new barrel file, and deliberately tiny: wrapping
  an index (`+ count` before the modulo, because Monkey C's `%` keeps the sign
  of its left operand) and clamping a restored one (a rebuild with fewer items
  leaves a stored index past the end). Everything else is generated, because
  everything else is per-device.

One ergonomics fix found while writing the example: `slots:` defaults to
`min(3, len(items))`, not a flat 3, so a two-item carousel is not an error for
taking the default. Asking for more slots than items is still an error — a
wider row would draw one item twice, which reads as a rendering bug.

**A later session deleted the refresh-tier concept outright, on the user's own
explicit instruction, and opened up all 42 complication types as data
sources.** Four agents worked this in parallel against one shared tree
(catalogue, codegen, format/schema, docs+examples — this section is the last
of those), following the "parallel work in one tree must edit files, never run
git commands that touch the working tree" rule the earlier carousel-recovery
session already established. `docs/research/probes/complication-pull/` is the
probe that settled the one genuinely open question before any code was
written; read its README before touching this area again.

1. **The TTL cache is gone.** `runtime-lib/WfbCache.mc` is deleted, and so are
   `catalog.Tier`, `Reader.tier`, `Reader.ttl_seconds`, `Source.tier`, and
   `wfb/ir.py`'s `_check_tiers` and the `refresh-tier` diagnostic. Rationale,
   the user's own and correct: every value already comes from a Garmin API
   that caches it on *its* side — `Toybox/Weather.html` documents
   `getCurrentConditions()` as "get the **most recently cached** weather
   conditions", not "fetch weather conditions" — so a second TTL cache inside
   the 128 KB watch-face budget was buying nothing. Every `Reader` is now a
   plain read, every frame, unconditionally.
2. **Consequence, deliberate and user-approved: `weather.*` and
   `complication.*` may now be bound from `low_power`/`always_on` elements.**
   The hard, unsuppressible compile error is gone. Constraint 4 above
   (`onPartialUpdate` overrun disables partial updates **permanently**, for
   the rest of the app's lifecycle) has not gotten any less true — it is now
   the author's own responsibility to watch for, backed only by the
   suppressible `partial-update-budget` lint, whose note was strengthened in
   this same session to say so explicitly: a `weather.*` or `complication.*`
   read on a `low_power` element is now named as the expensive case to check
   first. This is a real, intentional weakening of a guarantee the compiler
   used to enforce outright — recorded here so it is never mistaken for an
   oversight.
3. **Complications are read by pull, not by callback.** `onUpdate` now calls
   `WfbComplications.valueOf(new Complications.Id(Complications.<TYPE>))`
   exactly like any other reader, and casts the result
   (`as Number?`/`String?`/`Float?`, `Source.cast`) because
   `Complication.value` is `Complications.Value or Null` — a union of
   `String or Number or Float or Long or Double or Null`
   (`Toybox/Complications.html`). There is no per-type cached view field and
   no `switch` anymore. **Evidence, not assumption:** Garmin's own sample,
   `$CIQ_SDK/samples/ConfigurableWatchFace/source/
   ConfigurationWatchFaceView.mc`, calls `Complications.getComplication(id)
   .value` from `updateConfiguration`, which runs *before* the first
   `subscribeToUpdates` and, in edit mode, without ever subscribing at all —
   so a pull needs no subscription in principle. A standalone probe
   (`docs/research/probes/complication-pull/ProbeView.mc`) confirms the exact
   generated shape compiles `BUILD SUCCESSFUL` under `-l 3` on
   `fenix8solar47mm` and `fr955`, including the cast parsing inside a ternary
   branch with no extra parentheses. **Subscription is kept anyway, and is
   explicitly not caching**: `onLayout` still calls `WfbComplications.
   subscribe(...)` once per bound type, but the change callback's entire body
   is now `WatchUi.requestUpdate();` — one line per bound type in `onLayout`,
   nothing per frame. **Whether pull-without-subscribe would also stay fresh
   is UNVERIFIED** — this container has no working simulator (finding 11
   above), so this is a compile-time result only, and the subscription is the
   hedge against that unknown rather than proof it is needed.
4. **All 42 complication types are now data sources**, each in its own
   `complication.<name>` path, generated from one table
   (`wfb/complications.py`'s `TYPES`, transcribed verbatim from
   `Toybox/Complications.html`'s Type table — not hand-copied, the same
   discipline `wfb/icon_catalog.py` already follows and for the same reason).
   **One rule, no exceptions: `complication.<type>` is *always* read through
   `Toybox.Complications`; every other catalogue path is *always* a direct
   API read.** The nine paths that used to reach a complication by a direct-
   looking name (`body_battery.current`, `system.solar_input`,
   `weather.sunrise`/`sunset`, `activity.training_status`,
   `activity.weekly_run_distance`/`weekly_bike_distance`,
   `activity.sleep_score`, `device.next_calendar_event`) are renamed to
   `complication.body_battery`, `complication.solar_input`, and so on — an
   author who types the old path gets a `source-renamed` error naming the
   replacement (`wfb/expr.py`, `catalog.renamed_to`), the same precedent
   `on-tap-renamed` set. No example YAML bound any of the nine before the
   rename (checked first).
5. **`on_hold: auto`** (and a carousel item's `launch: auto`) resolves the
   launch target from the element's own **value** binding — a `text`'s
   `value:`/an `icon`'s `icon_for:`/a `progress`'s `value:`, deliberately
   never `color:`/`track_color:`/`max:`, because a conditional colour's
   heart-rate reference is not what the element is *about*. The new
   `Source.launch_complication` field carries the conventional counterpart
   (set automatically on every `complication.*` source to its own name, and
   by hand on ~20 direct-read sources that have an established one, e.g.
   `activity.steps -> steps`, `weather.condition -> current_weather`).
   Resolution runs in `wfb/ir.py`'s `Builder._resolve_hold_auto`, deferred
   until after the kind-specific builder gives the element a real value
   expression to inspect — the same deferred-second-pass shape
   `_check_tiers` used to run at, before it was deleted. Zero candidates is
   `hold-auto-unresolved`; more than one distinct candidate is
   `hold-auto-ambiguous`; both are errors, not warnings, because guessing
   here would silently open the wrong glance.
6. **New: `carousel-on-hold` error.** A carousel's own box is already cut
   into three hold zones, so an element-level `on_hold:` on a `carousel` used
   to validate cleanly and then be silently dropped by the emitter — nothing
   ever read the field. It is now a build error pointing the author at
   per-item `launch:` (and `launch: auto`) instead.
7. **A real build caught a naming collision before it shipped.** A
   complication reader's local is `<name>Complication` (e.g.
   `bodyBatteryComplication`), not `complication<Name>` — the latter was the
   first attempt, and it collided with the *value* local
   `wfb.ir.local_name` derives from the source path (`complication.
   body_battery` already owns `complicationBodyBattery`), producing
   `Redefinition of variable 'complicationBodyBattery'` from `monkeyc` on all
   three targets. `wfb/catalog.py::_complication_local_name`'s docstring
   records the reasoning in full, and
   `tests/test_catalog.py::test_reader_and_value_locals_never_collide` pins
   the whole family apart in the fast test loop (see the review note below --
   that test did not exist when this paragraph was first written, and the
   claim it makes was optimistic until it did).

All of the above is code-complete and green (`pytest -m "not slow"` and
`pytest -m "slow"`, real `monkeyc`, both pass) — this note is documentation
and a new worked example (`examples/complications/`) written after the fact,
not a description of work still pending.

**A review pass followed immediately, and four of its findings were then
fixed** (`docs/review/2026-09-architecture-review.md`, whose status table
records what closed). Three are worth carrying forward:

1. **Every `on_hold:` design without a `carousel` had been building with a
   real `monkeyc` warning** — `Member variable '_view' is not used.` The
   delegate is handed the view unconditionally but only a carousel's zone
   handler reads it. The field is now conditional; the *parameter* stays
   unconditional, because an unused parameter provably does **not** warn
   (built both ways to find out), so one delegate shape and one
   `new ...Delegate(view)` call site still serve every design. The reason it
   shipped at all is the more useful lesson: **every `on_hold:` test
   inspected generated text, and no test had ever put a plain `on_hold:`
   design through real `monkeyc`.** There is now a `slow` test that does, and
   asserts *warning-free* rather than merely successful — `wfb/build.py`
   already turns each `WARNING:` line into a bag diagnostic, so that
   assertion is on the compiler's own output rather than a proxy for it.
2. **`docs/limitations.md` was pointing at a fix that could not work.** It
   said `catalog.Source.requires` + `Device.has_symbol` was the mechanism for
   per-device source gating. It is not: `has_symbol` indexes only
   `<functionEntry>` symbols, and `COMPLICATION_TYPE_*` are *constants* that
   do not appear in `api.debug.xml` at all — checked directly, including for
   `COMPLICATION_TYPE_BATTERY`, which every target supports. The working
   mechanism is a version comparison (`complications.TYPES[name].since` vs
   `Device.api_level`, both already on disk), now shipped as
   `check_complication_availability` / `complication-gated`, suppressible,
   covering both a `complication.*` binding and an `on_hold:`/`launch:`
   naming a gated type. `Device.api_level` had existed all along with exactly
   one call site: a column in `wfb devices`. **Note the two checks answer
   different questions** — "is this type old enough for this firmware" is not
   "does this symbol exist here", and constraint 6's `onTap` case is the
   standing proof they can disagree.
3. **A guard nobody has watched fail is not a guard.** Each of the three
   fixes above was required to go red against the unfixed code before being
   believed: the `_view` test against the unconditional emitter, the new
   catalogue-wide collision test against the pre-fix naming (it lists all 42
   collisions by name), and the gating check's suppression against a real
   `lint: {allow: [...]}`. That last one matters specifically because this
   file already records two checks that were advertised as suppressible and
   were not, having called `bag.warning` directly instead of `_emit`.

Also closed: the collision class from item 7 above now has a **fast**
catalogue-wide test (`test_reader_and_value_locals_never_collide`) covering
every `Reader.name`, every `local_name(path)`, the `...Obj` intermediate form
and the emitter's own fixed locals — previously the only thing that would
have caught a recurrence was the `slow` full-catalogue build, excluded from
the default loop. `Builder._check_symbol_collision` was deliberately left
alone: it is element-id-scoped by construction, and these collisions are
catalogue-scoped.

Still open from that review: `on_hold:`'s schema description is hand-copied
across seven element-type branches, and the low-severity items below it.

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
