# CLAUDE.md — garmin-wf-builder

Turn-one guidance for Claude Code. **This file is loaded into every session,
so it is kept short on purpose**: detail lives in files read on demand. Add
new lore to those files, not here. Only lift a fact into this file when every
future session needs it on turn one.

| When you need… | Read |
|---|---|
| a platform constraint's full text and citations | `docs/lore/platform-constraints.md` (same numbering as §4) |
| build/SDK/environment facts, `.prg` measurement, SDK doc paths | `docs/lore/toolchain.md` |
| Monkey C compiler quirks | `docs/lore/monkeyc.md` (auto-loaded in `wfb/emit/`, `runtime-lib/`) |
| codegen, IR, jungle/manifest, YAML-loader lore | `docs/lore/codegen.md` (auto-loaded in `wfb/`) |
| what shipped, was removed, or is missing | `docs/limitations.md` §2 (**authoritative**), `docs/lore/roadmap.md` |
| the working agreement with the incident behind each rule | `docs/lore/working-agreement.md` |
| proposals written but not built | `docs/plans/` (none open; built plans are deleted — see `docs/CLAUDE.md`) |
| the session-by-session narrative | `docs/history.md` — only for a specific past decision, never as background reading |

`CLAUDE.md` files in `wfb/`, `wfb/emit/`, `runtime-lib/`, `tests/`,
`examples/` and `docs/` load automatically when you work there. `.ignore`
keeps history, golden files, probes, vendored files and build output out of
broad searches. They are still readable by explicit path.

---

## 1. What this project is

A **watchface builder framework for Garmin Connect IQ**: YAML design and data
bindings in, a compilable, sideloadable watch face (`.prg`) out.
**Targets:** `fenix8solar47mm`, `fenix8solar51mm`, `fr955`. Personal sideload
only. Hosts: macOS and Linux (containerised). Language: Python (ADR 0001).

**Research-then-build:** the user asked for readable reasoning, so
`docs/research/` and `docs/adr/` are deliverables, not scaffolding.

| Phase | State |
|---|---|
| 0 research (`docs/research/00`–`09`) | complete, reviewed |
| 1 ADRs (`docs/adr/0001`–`0009`) | complete, reviewed |
| 2 thin vertical slice | complete; the `.prg` runs in the user's host simulator |
| 3 breadth | in progress: all 8 element types (analog hands added 2026-09-14, plan 04), `static:`, `antialias:`, all four `config:` axes, `on_hold:` shipped — see §6 |

Where things live: `wfb/` is the compiler, `runtime-lib/` the Monkey C support
barrel, `schema/` the published schema, and `examples/` the example faces.
`docs/format.md` is the format reference, `docs/limitations.md` records the
platform and linter limits, and `docs/container.md` covers the Docker image.

---

## 2. Environment setup — do this first

```sh
./tools/setup-env.sh
```

It installs the SDK 9.2.0 at `~/ciq/sdks/9.2.0`, the developer key at
`~/ciq/developer_key.der`, the device definitions at
`~/.Garmin/ConnectIQ/Devices/`, `CIQ_SDK` and `PATH` in
`/etc/sandbox-persistent.sh`, and `.venv/`. On Debian/Ubuntu, `venv` needs
`python3-venv`, or the script falls back to `uv`.

**Device definitions cannot be downloaded:** Garmin's API returns 401 without
an SSO login. They are vendored at `vendor/devices/`, which is
**gitignored on purpose** because it is the user's licensed copy: it travels
with the directory, not with git. If they are missing, ask the user to run
this on their host:

```sh
cp -R ~/Library/Application\ Support/Garmin/ConnectIQ/Devices \
      ~/claude/garmin-watchface-protomolecule/.devices-import
```

**Filesystem quirk:** a tracked file can transiently vanish. You get
`FileNotFoundError`, and `git status` reports it deleted. It has never been
real data loss. Run `git checkout HEAD -- <path>` and move on, without
investigating. Full account: `docs/lore/toolchain.md`.

---

## 3. Building

```sh
./.venv/bin/python wfb.py build examples/graph/face.yaml   # 3 signed .prg, warning-free
$CIQ_SDK/bin/monkeyc -f monkey.jungle -d fenix8solar47mm \
    -o out.prg -y ~/ciq/developer_key.der -w -l 3          # generated jungle sets -O 3z itself
$CIQ_SDK/bin/monkeyc … --build-stats 0                     # memory: the figure that counts
```

- **It builds fine in the sandbox.** The sibling project's `CLAUDE.md` says
  it cannot. That claim is false; do not import it.
- **The simulator will not run in this container.** The cause is missing
  webkit/soup libraries, and on 22.04 it segfaults on push. Do not spend a
  session on it. Use `wfb preview`, or ask the user to run the simulator on
  their host.
- `Invalid device id specified` means the device files are missing **or**
  Java's `user.home` is wrong (it comes from passwd, not `$HOME`).
- Details for all of this are in `docs/lore/toolchain.md` and
  `docs/lore/codegen.md` (Phase 2 findings 1–11).

---

## 4. Platform constraints that will bite you

One line each. The full text and citations are in
`docs/lore/platform-constraints.md`, with **the same numbers**. **Do not
re-litigate these without new evidence.**

1. **No device-side renderer**, which is why this is codegen (ADR 0003).
2. **Watch faces get 131 072 B (128 KB)** on all targets, a sixth of a watch
   app's. 28 of 164 devices cannot run a face at all.
3. **No filled arc.** Rings are `setPenWidth` + `drawArc` only: no caps, no
   annulus, no gradient.
4. **An `onPartialUpdate` overrun is permanent** for the app's lifetime.
   `setClip` is charged by clip *area*.
5. **AMOLED forbids `onPartialUpdate`.** The targets are MIP, but 74/164
   devices are AMOLED-class.
6. **API level does not decide availability.** Resolve symbols against
   `<id>.api.debug.xml` by fully qualified parent. (`fr955` is 5.2.0 and
   lacks `WatchFaceDelegate.onTap`.)
   - **6b.** **A symbol being present does not mean it gets called:** read the
     prose. `WatchFaceDelegate.onTap` fires only in config mode.
   - **6c.** **A live face gets one gesture: touch and hold (`onPress`).** No
     tap, swipe or keys. `ClickEvent.getCoordinates()` is the only way to
     multiplex it.
   - **6d.** **`monkeyc` checks the SDK-wide API, not the device's.** A shared
     view may use target-only APIs guarded at runtime, and nothing but
     `has_symbol` plus a lint catches an absent symbol.
7. **A missing permission fails silently** (the API returns null), so the
   compiler derives `manifest.xml` permissions.
8. **Every data field is nullable.** Absence is normal.
9. **On-device config has four axes** (API 5.1.0, fēnix 8+): Styles, Data
   (complication slots), one data colour and one accent colour, with at most
   four saved configurations. **`fr955` has none.**
   - **9b.** The Data axis takes Garmin complication types only.
     Author-defined selectable content rides Styles (`styleId` is opaque and
     global).
   - **9c.** **All four axes are in use; none is free.** **Decided and built
     2026-09-13:** colours *and* widget layouts share Styles as explicitly
     listed entries. See `docs/format.md`; `examples/styles/face.yaml`.
10. **`alphaBlendingSupport: false`**: no transparency.
11. **The graphics pool (1 MB) is separate** from the 128 KB, so a
    `BufferedBitmap` is cheap.
12. **`onSettingsChanged` fires only for Garmin Connect pushes.** Invalidate
    caches explicitly.
13. **64-colour MIP palette:** each channel must be `00`/`55`/`AA`/`FF`, or
    the colour dithers.
14. **`deviceFamily` in `compiler.json` is the resource-qualifier directory
    name.** Read it; do not derive it.
    - **14b.** **Four plottable series only**: HR history,
      `ActivityMonitor.getHistory`, hourly and daily forecast.
      `SensorHistory` is closed to faces, and solar has no history.

---

## 5. Decisions already made

Full reasoning is in `docs/adr/`, indexed with its through-line in
`docs/adr/README.md`.

| ADR | Decision |
|---|---|
| 0001 | Host language **Python** |
| 0002 | **YAML canonical**, published JSON Schema; GUI is a lossless editor over it |
| 0003 | **Code generation**, not an interpreter; small hand-written barrel allowed |
| 0004 | Element model; **anchors + relative/polar units**, resolved at build time |
| 0005 | Typed data catalogue; **expressions compile to Monkey C** |
| 0006 | Config surfaces, palettes, power modes, interactivity |
| 0007 | **Narrow bounded escape hatch** (`raw`) |
| 0008 | Lints with **explicit confidence levels**; memory measured, not estimated |
| 0009 | Format versioning and forward compatibility |

**User decisions:**
- **Interaction:** `on_hold:` everywhere, touch-and-hold only. The original
  tap/hold split was superseded by research (6b/6c).
- **On-device config:** the native editor plus phone settings only, with no
  generated on-device menu, so fr955 gets no on-device config (accepted
  knowingly).
- **Repo:** a sibling directory; the Dashboard face repo is left untouched.
  `forums.garmin.com` and `developer.android.com` are allowlisted.

---

## 6. Pipeline and current state

| Stage | Module | Toolchain? |
|---|---|---|
| YAML load with source spans | `wfb/yamlsrc.py` | no |
| JSON Schema, reported on author lines | `wfb/validate.py` | no |
| Semantic pass (sources, types, nulls) | `wfb/ir.py`, `wfb/catalog.py`, `wfb/expr.py` | no |
| Mapping form → list form, other sugar | `wfb/desugar.py` | no |
| Per-device layout resolve | `wfb/layout.py` | device files |
| Lint | `wfb/lint.py` | device files |
| Font baking (TTF → BMFont) | `wfb/fonts/` | no |
| Codegen: Monkey C, resources, manifest, jungle | `wfb/emit/` | no |
| `monkeyc` + measured memory | `wfb/build.py` | **yes** |
| Host-side preview | `wfb/preview.py` | no |

**Tests:** `pytest -m "not slow"`. There are 3 known, pre-existing failures,
listed in `tests/CLAUDE.md`. If that set changes, notice it before blaming
your change.

**Roadmap:** `docs/limitations.md` §2 is authoritative, and the full checklist
is `docs/lore/roadmap.md`. Turn-one summary:

- **Removed outright, with no shim.** Do not assume these exist:
  - `type: carousel`;
  - `on_tap:` (now `on_hold:`);
  - a font `size:` given as a bare number, and `scale:`;
  - a raw pasted character in `icon:`;
  - refresh tiers (`WfbCache.mc`, `catalog.Tier`).
- **Not implemented:**
  - `image` and `raw` elements (friendly error);
  - per-device `overrides` (writing one is a build error);
  - `segments`/`scale` progress styles;
  - unit conversion;
  - **phone settings**: frozen, incomplete, on `wip/phone-settings`. Do not
    resume without asking;
  - catalogue generation from the SDK;
  - `Source.requires`, which is read by nothing;
  - the GUI, which if built must be a thin client over `wfb/preview.py`;
  - `mypy --strict` and CI;
  - `wfb install`/`package`/`migrate`.
- **Recently built:**
  - **Built 2026-09-14** (plan 04): analog hands. `hands:` declares
    named hour/minute/second sets, each hand 1–16 parts of four kinds
    (`polygon`/`rectangle`/`line`/`circle`) drawn at 12 o'clock with the
    axis as origin; `type: hands` places one at its `at:` (off centre
    allowed). Styles pick a set via `layouts:`. The device rotates the
    geometry by the time (ADR 0004 amended; `runtime-lib/WfbHands.mc`).
    `seconds: awake` (default) hides the second hand asleep; `seconds:
    always` is not built. Example: `examples/analog/face.yaml`.
  - **Built 2026-09-13** (plan 02): Styles that switch widget
    layouts. `layouts:` (form A only: a container, with no element-level
    membership key) and `config: style:` (`config: colors:` removed, no
    shim). A `complication_slot` may only be in shared content. The example
    is `examples/styles/face.yaml`.
  - **Built 2026-09-13** (plan 03): complication-slot icons cover
    all 42 native types, plus per-choice overrides and `icon_position:`/
    `icon_gap:`/`icon_color:`, and `choices: any` + `icon_size:`.

**`examples/dashboard/face.yaml` is the user's playground. Leave it alone**,
even when its test is red, unless asked. See `examples/CLAUDE.md`.

**Known-good reference:** `~/claude/garmin-watchface-protomolecule/` is a
working face for the same targets. It is **read-only**, lives on the user's
host (not in the sandbox), and its build claims are false (§3).

---

## 7. Working agreement

The full text, with the incident behind each rule, is in
`docs/lore/working-agreement.md`.

- **Stop and ask** before a decision that changes the project's shape
  (format, architecture, scope cuts): give options, tradeoffs and a
  recommendation, then wait.
- **Never invent an API.** Confirm a symbol in `<id>.api.debug.xml` or the
  SDK docs, or mark it an open question.
- **Cite sources** (SDK paths, API levels) in research and ADRs.
- **Prefer a working thin slice. Flag scope cuts early.** If a requirement
  is impossible, say so, explain why, and propose the closest alternative.
- **A guard nobody has watched fail is not a guard.** Drive every new
  diagnostic red, and cut the whole path, not one branch.
- **The build bar is warning-free**, not merely successful.
- **A test must exercise the contrast it claims.** (`00:00`/`11:11` cannot
  catch broken monospacing; `Fri 11:11`/`Wed 00:00` can.)
- **When a feature has a truthiness on/off switch, a differently shaped new
  member is the bug to look for.** Route through `Face.has_config`-style
  helpers.
- **Parallel work in one tree edits files and never runs `git stash`/`reset`.**
  **Subagents do the work themselves and spawn no helpers.**

### Documentation discipline

When a change makes any of these stale, update them **in the same commit**:
`docs/research/*`, `docs/adr/*`, `docs/lore/*`, this file,
`docs/limitations.md` and `docs/format.md` together with the JSON Schema
(the schema is normative). Append a session account worth keeping to
`docs/history.md`, in chronological order, not here. House style: leave a
superseded account in place and add the correction beside it. More detail is
in `docs/CLAUDE.md`.

---

## 8. Useful SDK paths

Everything is offline in `$CIQ_SDK`, version-pinned; prefer it to the
website. The table is in `docs/lore/toolchain.md`. The two most used entries:
`bin/api.debug.xml` (the SDK-wide symbol table) and `doc/docs/Core_Topics/`.
`tools/research/h2t.py` turns SDK HTML into greppable text.
