# Developing garmin-wf-builder

Setup details, the command list, the shape of the generated code, the
repository layout and the tests. For what the tool does and how to write a
face, start with the [README](../README.md).

**Targets:** fēnix 8 Solar 47 mm / 51 mm, Forerunner 955.
**Distribution:** personal sideload.

## Start here

| If you want… | Read |
|---|---|
| a guided tour by example, with screenshots | [`README.md`](../README.md) |
| to take over this project | **`CLAUDE.md`** — full handoff context |
| the full session-by-session history behind it | [`docs/history.md`](history.md) |
| to write a design | [`docs/format.md`](format.md), and the schema in [`schema/`](../schema/) |
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
  garmin-wf-builder build examples/graph/face.yaml
```

See [`docs/container.md`](container.md). The local install:

Installs the Connect IQ SDK 9.2.0, generates a developer key, installs the device
definitions, downloads the Nerd Fonts icon font (`tools/fetch-icon-font.py`,
pinned and hash-checked; the font is not committed), and creates `.venv` with the
host dependencies.

The SDK downloads freely. **Device definitions cannot be downloaded** —
`api.gcs.garmin.com` returns HTTP 401 and needs a Garmin SSO login that cannot be
completed headlessly. Get them with Garmin's SDK Manager
([README step 1](../README.md#step-1-get-the-device-definitions)). The script
takes them from `vendor/devices/` (gitignored, because they are your own licensed
copy), from `~/Library/Application Support/Garmin/ConnectIQ/Devices`, or from
wherever they already are at `~/.Garmin/ConnectIQ/Devices`.

**Platforms.** `setup-env.sh` is tested on Linux only. It downloads the Linux
SDK, and it appends `CIQ_SDK`/`PATH` to `/etc/sandbox-persistent.sh` when that
file is writable (the development sandbox). Otherwise it prints the two exports
for you to add to your shell profile. On macOS, use the Docker image; it is
tested with OrbStack. Windows is untested.

### Running `wfb`

There is no installed `wfb` command. `wfb` in these docs means `wfb.py` at the
repository root. It is executable, and it re-runs itself under the project's
`.venv` when the Python that started it lacks the dependencies. That means an
alias works from any directory, with no venv to activate:

```sh
alias wfb="/path/to/garmin-wf-builder/wfb.py"
```

`./.venv/bin/python wfb.py …` is the same thing, spelled out. In the Docker
image, `wfb` is a real command and is the entrypoint. On a Mac, alias it to the
whole `docker run …` line (README step 2), and run it from the folder that
holds your face, because the container sees only the directory mounted at
`/work`.

## Commands

```sh
wfb new       "My Face" [-t minimal|dashboard]   # start from a known-good template
wfb build     design.yaml [-d DEVICE] [-o DIR] [--no-compile]
wfb validate  design.yaml          # everything except codegen; no toolchain needed
wfb preview   design.yaml [--watch]  # render to PNG; no toolchain, no simulator
wfb simulate  design.yaml          # launch the simulator and push the built face
wfb devices                        # installed device definitions and their limits
wfb sources                        # the data-source catalogue, and the icon names
wfb complications                  # what an element's `on_hold:` may launch
wfb schema    [--path]             # the JSON Schema, for editor setup
wfb doctor                         # what is installed, what is missing, what to do
wfb help      [command]            # every command's own help, from its own docstring
```

`wfb help <command>` and `wfb <command> help` print the same thing as
`wfb <command> --help`, byte for byte, because all three are read from that
command's handler docstring rather than from a hand-written string that could
drift from it.

The quickest start:

```sh
wfb new "My Face"
wfb preview my-face.yaml --watch   # leave this running while you edit
```

`wfb preview` renders from the **same resolved geometry** the generated Monkey C
uses, so the two cannot disagree about position — which is what makes it a useful
check and not a second implementation. Why a visual GUI builder is deferred is
in [`docs/research/06-authoring-ergonomics.md`](research/06-authoring-ergonomics.md).

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
  ir.py                 the IR, and the semantic pass
  layout.py             relative units -> absolute pixels, per device
  lint.py               ADR 0008's checks, each with a stated confidence
  fonts/                TrueType -> BMFont sheet, subsetted to the used glyphs
  icons.py              icon sizing and resolution over the Nerd Fonts icon font
  icon_catalog.py       the icon name -> codepoint table, data only
  assets/icons/         the "Symbols Only" icon font, downloaded by tools/fetch-icon-font.py
  emit/                 Monkey C, resources, manifest, jungle
  preview.py            host-side renderer over the resolved IR
  build.py, cli.py      the pipeline and `wfb`
runtime-lib/          the hand-written support barrel the generated code calls
schema/               the published JSON Schema (a shipped artefact)
examples/             example faces; each one's header comment says what it
                      exercises (`examples/CLAUDE.md` has the index)
examples/dashboard/   a dense multi-row face: separators, a two-tone clock,
                      conditional colours, a badge and three arcs
examples/complications/  complication.* bindings and on_hold: auto
tests/                ? tests; only the `slow` ones need the Garmin toolchain
tests/fixtures/slice/ the Phase 2 slice: the golden files' source design
docs/                 format reference, limitations, ADRs, Phase 0 research
```

## Tests

```sh
./.venv/bin/python -m pytest              # everything
./.venv/bin/python -m pytest -m "not slow" # skip the real monkeyc builds
```

Golden-file tests over the generated Monkey C are the primary compiler test, and
they run with **no Garmin toolchain** — which matters, because the device files
are the scarce resource. Regenerate them after an intentional change with
`pytest tests/test_golden.py --update-golden` and read the diff.

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
