# Developing garmin-wf-builder

Setup details, the command list, the shape of the generated code, the
repository layout and the tests. For what the tool does and how to write a
face, start with the [README](../README.md) and the [guide](README.md).

**Targets:** any Garmin watch that can run a watch face (136 of the 164
devices in the Connect IQ reference) and whose device definition is installed.
**Verification devices:** fēnix 8 Solar 47 mm / 51 mm, Forerunner 955 — the
three that are built and measured against here, not the limit of what is
supported.
**Distribution:** personal sideload.

## Start here

| If you want… | Read |
|---|---|
| the feature tour and the author's guide | [`README.md`](../README.md), then [`docs/README.md`](README.md) |
| to take over this project | **`CLAUDE.md`** — full handoff context |
| to write a design | [`docs/guide/`](guide/), and the schema in [`schema/`](../schema/) |
| what the platform will not do | [`docs/limitations.md`](limitations.md) |
| to run it without installing anything | [`docs/container.md`](container.md) |
| the decisions and why | [`docs/adr/README.md`](adr/README.md), then `0001`–`0009` |
| the platform research | [`docs/research/00-summary.md`](research/00-summary.md), then `01`–`05` |

## Setup

Either install locally:

```sh
./tools/setup-env.sh
```

…or use the container, which needs nothing on the host but Docker and your own
copy of the device definitions:

```sh
docker build -t garmin-wf-builder .
docker run --rm -v "$PWD:/work" \
  -v "$HOME/Library/Application Support/Garmin/ConnectIQ/Devices:/devices:ro" \
  -v wfb-keys:/keys \
  garmin-wf-builder build examples/features/graph/face.yaml
```

See [`docs/container.md`](container.md). The local install:

Installs the Connect IQ SDK 9.2.0, generates a developer key, installs the device
definitions, copies Garmin's own font files in from `vendor/fonts/` if present
(optional — see below), downloads the Nerd Fonts icon font
(`tools/fetch-icon-font.py`, pinned and hash-checked; the font is not committed)
and prefetches the registry's system-font stand-ins the same way
(`tools/fetch-system-fonts.py`; see `docs/lore/toolchain.md`), and creates
`.venv` with the host dependencies.

The SDK downloads freely. **Device definitions cannot be downloaded** —
`api.gcs.garmin.com` returns HTTP 401 and needs a Garmin SSO login that cannot be
completed headlessly. Get them with Garmin's SDK Manager
([Step 1: get the device definitions](guide/getting-started.md#step-1-get-the-device-definitions)). The script
takes them from `vendor/devices/` (gitignored, because they are your own licensed
copy), from `~/Library/Application Support/Garmin/ConnectIQ/Devices`, or from
wherever they already are at `~/.Garmin/ConnectIQ/Devices`.

**Garmin's own font files are the same shape, but optional**: free stand-ins
(`wfb/fonts/registry.json`) work without them. If the SDK Manager install also
has a `Fonts` directory, the script copies it from `vendor/fonts/` (gitignored,
same reasoning as `vendor/devices/`) into `~/.Garmin/ConnectIQ/Fonts`
incrementally. `wfb doctor` reports which root it found (`--fonts DIR` or
`WFB_FONTS` override it); a device's real file there outranks the
registry's stand-in for every build/preview consumer that consults it (plan
09 R1b). See `docs/lore/toolchain.md`.

**Without the Garmin font root, `wfb preview` draws stand-in typefaces for
any face the registry has no exact match for** — not merely "an estimate",
a genuinely different family's letterforms (`wfb.fonts.fallback`'s own
`"substitute"`/`"none"` match levels). `wfb preview` names exactly which
fonts this happened to, once per run, on stderr; `wfb doctor` reports the
same thing as one line next to the root it did or did not find. `--fonts
DIR` on either command points at a root without installing it system-wide
(plan 12 R1/R3). On `wfb preview`, that one root reaches layout measurement
and every lint that depends on it too, not only the pixels drawn (`Device.
fonts_root`, owned by the `DeviceDatabase` the command builds -- plan 18
item 8): a box is always sized from the same file it is then drawn with.

**Platforms.** `setup-env.sh` is tested on Linux only. It downloads the Linux
SDK, and it appends `CIQ_SDK`/`PATH` to `/etc/sandbox-persistent.sh` when that
file exists and is writable (the development sandbox). Otherwise it prints the
two exports for you to add to your shell profile. It checks for `curl`,
`unzip`, `openssl`, `python3` and `java` before doing anything, and a missing
device folder produces step-by-step instructions rather than a bare error. On macOS, use the Docker image; it is
tested with OrbStack. Windows is untested.

Running `wfb` and the full command list moved to
[`docs/guide/preview-and-cli.md`](guide/preview-and-cli.md).

## What the generated code looks like

```monkeyc
//! `step_ring` -- an arc progress indicator.
//!
//! Bound to `activity.steps` and `activity.step_goal`.
//! When the value is absent: hide.
//! Drawn in: active.
private function drawStepRing(dc as Dc, activity as ActivityMonitor.Info) as Void {
    // the values this element is bound to
    var activitySteps = activity.steps;
    var activityStepGoal = activity.stepGoal;

    // when_absent: hide
    if (activitySteps == null || activityStepGoal == null) {
        return;
    }

    // the unfilled track
    dc.setColor(Palette.TRACK, Graphics.COLOR_TRANSPARENT);
    WfbArc.drawSpan(dc, Layout.STEP_RING_CX, Layout.STEP_RING_CY, Layout.STEP_RING_RADIUS,
                    Layout.STEP_RING_THICKNESS, Layout.STEP_RING_START, Layout.STEP_RING_SWEEP);

    // the filled portion
    dc.setColor(Palette.ACCENT, Graphics.COLOR_TRANSPARENT);
    WfbArc.drawProgress(dc, Layout.STEP_RING_CX, Layout.STEP_RING_CY, Layout.STEP_RING_RADIUS,
                        Layout.STEP_RING_THICKNESS, Layout.STEP_RING_START, Layout.STEP_RING_SWEEP,
                        WfbMath.percent(activitySteps, activityStepGoal) / 100.0);
}
```

Readable output is a requirement, not a nicety: it is what gets debugged when
something misbehaves on the wrist, and it is the substrate the escape hatch will
drop into. Symbol names derive from element ids, every block cites its YAML
element, layout constants are named rather than inlined, and every nullable read
is guarded with the `when_absent:` policy that produced the guard.

## Layout

```
wfb/                  the compiler
  yamlsrc.py            YAML loading that keeps source spans
  validate.py           JSON Schema, reported against the author's lines
  catalog.py            the typed data-source catalogue
  expr.py               the expression language -> Monkey C
  ir/                   the IR (model.py, naming.py) and the semantic pass (builder.py)
  kinds/                one module per element kind: its own build, resolve, preview,
                        emit and layout-constant code, an ElementKind subclass each
  layout.py             relative units -> absolute pixels, per device
  lint.py               ADR 0008's checks, each with a stated confidence
  fonts/                TrueType -> BMFont sheet, subsetted to the used glyphs
  fonts/registry.json   device font name -> free-font-key mapping (docs/research/10-system-fonts.md)
  fonts/fetch_system.py stdlib-only fetch/cache/Garmin-font-root logic driven by registry.json
  icons.py              icon sizing and resolution over the Nerd Fonts icon font
  icon_catalog.py       the icon name -> codepoint table, data only
  assets/icons/         the "Symbols Only" icon font, downloaded by tools/fetch-icon-font.py
  assets/system-fonts/  registry.json's free stand-ins for Garmin's system fonts,
                        downloaded by tools/fetch-system-fonts.py
  emit/                 Monkey C, resources, manifest, jungle
  preview.py            host-side renderer over the resolved IR
  build.py, cli.py      the pipeline and `wfb`
runtime-lib/          the hand-written support barrel the generated code calls
schema/               the published JSON Schema (a shipped artefact)
examples/             example faces; `examples/README.md` is the index
examples/dashboard/   one of the four faces built to be worn (with
                      showcase/, analog-custom/ and enduro/)
examples/features/    one face per format feature, written as each landed
examples/system-fonts/  the three system-font calibration faces
tests/                ? tests; only the `slow` ones need the Garmin toolchain
tests/fixtures/slice/ the Phase 2 slice: the golden files' source design
tools/                setup, font fetchers, docs-shots.py, snapshot.py (output snapshots)
docs/                 README.md (hub), guide/ (format reference), limitations, ADRs, research
```

## Element kinds

Each element kind (`group`, `shape`, `text`, `progress`, `icon`, `graph`,
`complication_slot`, `hands`, `pattern`) is one module in `wfb/kinds/`,
holding one subclass of `wfb.kinds.ElementKind` (`TextKind`, `PatternKind`,
...) and an instance of it as the module's `KIND`. A stage never switches on
kind: it asks the registry (`kinds.for_element`, `kinds.for_placed`) and
calls a method. The base class is the interface: every method's signature
and docstring is there, and every method but `build`, `resolve`,
`draw_preview` and `emit_draw` has a default meaning "nothing to do here",
so a kind overrides only where it differs. **Adding a tenth kind** is an IR
class (`wfb/ir/model.py`), a `Placed` class (`wfb/layout.py`), one kind
module and its schema entry; `tests/test_kinds.py` fails until all four
agree.

**Fonts are one question.** A kind that draws text says what it draws, and
in which font, as a list of `TextRun`s (`ElementKind.text_runs`): the font,
the glyphs a baked sheet must hold, the exact strings the missing-glyph lint
checks, and, for an icon font, how to bake it. Glyph baking, icon-font
baking, `onLayout`'s font loading, the vector-font guards and lint, the
missing-glyph lint and `IconGlyphs.mc` are all derived from those runs in
their own stage, so a new kind that draws text writes one method, not one
per stage. A `pattern` returns one run per `shape: text` part; `part_index`
is how a stage finds the font layout resolved for that part
(`kinds.placed_font`).

Where code goes:

- A function lives in `wfb/kinds/<kind>.py` if and only if only that kind
  uses it. A helper two kinds share (`Builder._build_hand_part`, preview's
  text blitting, `layout._longer`) stays in its stage module.
- A site goes through the registry if adding a kind would force an edit
  there (a ladder over kinds, a per-kind table, a list of kind names); it
  becomes a method whose default is the ladder's fall-through. A site about
  one kind's own feature (collecting every `complication_slot`, a
  `graph`'s series barrel) stays as it is.
- Kind modules import stage modules and may call their underscored
  helpers; stage modules import the `wfb.kinds` package only, never a kind
  submodule, and read the registry only at call time. The registry loads
  lazily, so this cannot form an import cycle.

## Tests

```sh
./.venv/bin/python -m pytest              # everything
./.venv/bin/python -m pytest -m "not slow" # skip the real monkeyc builds
```

Golden-file tests over the generated Monkey C are the primary compiler test, and
they run with **no Garmin toolchain** — which matters, because the device files
are the scarce resource. Regenerate them after an intentional change with
`pytest tests/test_golden.py --update-golden` and read the diff.

**Snapshots, for a refactor that claims "no output change".** The golden files
cover a few fixtures; `tools/snapshot.py` covers everything the tool produces.
It drives the real CLI over every design in `examples/` and `tests/fixtures/`
and records:

- the generated project for the design's own targets and for two extra
  device mixes (AMOLED and older devices, without compiling);
- the lint on every installed device;
- eight preview variants (default, asleep, all styles, a fixed time, AOD,
  two AOD minutes, the burn-in heatmap);
- every listing and help command, with colour on and off.

About 360 cases; a full run takes about four minutes on four cores.

```sh
./.venv/bin/python tools/snapshot.py save /tmp/before    # before the change
./.venv/bin/python tools/snapshot.py compare /tmp/before # after: exit 0 = identical
./.venv/bin/python tools/snapshot.py compare /tmp/before --only examples/showcase/
```

`compare` prints a unified diff for each changed text output, and the changed
pixel count and bounding box for each changed image. Snapshots taken with
different font roots are not comparable (`--no-garmin-fonts` pins the one the
test suite uses). Paths, `wfb build`'s elapsed time and the UUID `wfb new`
mints are normalised; anything else that differs is a real change.

## What is decided

Python host language; YAML canonical with a published JSON Schema and a lossless
GUI over it; **code generation** rather than an on-device interpreter;
expressions compiled to Monkey C with no runtime evaluator; anchors and
relative/polar units resolved to pixels at build time; a narrow bounded escape
hatch to hand-written Monkey C; and build-time lints that carry explicit
confidence levels.

The short version of *why codegen*: Garmin ships no device-side renderer, so an
interpreter would have to live inside the same **128 KB** the design must fit in
— and it would forfeit Garmin's `excludeAnnotations` dead-code mechanism, which
only a generator can exploit. The reasoning is in [`docs/adr/`](adr/).

## What is next

Phase 3 — breadth: the remaining element types, per-device overrides, the `raw`
escape hatch, and the rest of on-device configuration (the Styles and Data
axes). Complications, interactivity and the two native colour axes have
landed — `on_hold:` (including `on_hold: auto`) on any element, `config:` for
an accent and a data colour edited in the fēnix 8's own on-device editor, and
all 42
complication types as `complication.*` data sources, read by a plain pull with
no cache anywhere in the generated face. See
[`docs/limitations.md`](limitations.md) §2 for the full list and `CLAUDE.md`
§6 for the ordering.
