# garmin-wf-builder

A watch face builder framework for Garmin Connect IQ: declare a watch face's
design and data bindings in YAML, get a compilable, sideloadable `.prg`.

**Targets:** fēnix 8 Solar 47 mm / 51 mm, Forerunner 955.
**Distribution:** personal sideload.
**Status:** Phase 2 complete — an end-to-end vertical slice builds and compiles.

```sh
./tools/setup-env.sh
./.venv/bin/python wfb.py build examples/slice/face.yaml
```

```
generated  build/slice
built      slice-fenix8solar47mm.prg  2,834 B / 131,072 B (2.2%)
built      slice-fenix8solar51mm.prg  2,835 B / 131,072 B (2.2%)
built      slice-fr955.prg            2,834 B / 131,072 B (2.2%)
```

One command takes [`examples/slice/face.yaml`](examples/slice/face.yaml) through
schema validation, a typed semantic pass, per-device layout resolution, twelve
lint checks, font baking, Monkey C generation and `monkeyc` — for three devices,
with no warnings.

---

## Start here

| If you want… | Read |
|---|---|
| to take over this project | **`CLAUDE.md`** — full handoff context |
| to write a design | [`docs/format.md`](docs/format.md), and the schema in [`schema/`](schema/) |
| what the platform will not do | [`docs/limitations.md`](docs/limitations.md) |
| to run it without installing anything | [`docs/container.md`](docs/container.md) |
| the decisions and why | [`docs/adr/README.md`](docs/adr/README.md), then `0001`–`0009` |
| the platform research | [`docs/research/00-summary.md`](docs/research/00-summary.md), then `01`–`05` |

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
  garmin-wf-builder build examples/slice/face.yaml
```

See [`docs/container.md`](docs/container.md). The local install:

Installs the Connect IQ SDK 9.2.0, generates a developer key, installs the device
definitions, and creates `.venv` with the host dependencies.

The SDK downloads freely. **Device definitions cannot be downloaded** —
`api.gcs.garmin.com` returns HTTP 401 and needs a Garmin SSO login that cannot be
completed headlessly. They are vendored in `vendor/devices/` (gitignored: they
are the user's own licensed copy). See `CLAUDE.md` §2.

## Commands

```sh
wfb new       "My Face" [-t minimal|dashboard]   # start from a known-good template
wfb build     design.yaml [-d DEVICE] [-o DIR] [--no-compile]
wfb validate  design.yaml          # everything except codegen; no toolchain needed
wfb preview   design.yaml [--watch]  # render to PNG; no toolchain, no simulator
wfb simulate  design.yaml          # launch the simulator and push the built face
wfb devices                        # installed device definitions and their limits
wfb sources                        # the data-source catalogue, and the icon names
wfb complications                  # what an element's `on_tap:` may launch
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

## Building a face with an AI assistant

[`skills/watchface-builder.md`](skills/watchface-builder.md) is a single
self-contained document that lets **any** assistant with file access and a shell
build a watch face — from a picture, a sketch, or a description. Point a model at
it:

> Read `skills/watchface-builder.md` and follow it to build me this watch face.
> [attach an image, or describe what you want]

It works because the compiler is a good feedback loop, not because the model
guesses well. The procedure interviews you about what a picture cannot say, reads
positions off the image as fractions of the dial, then iterates against
`wfb validate` and `wfb preview` until the render matches. It names only real
commands, assumes no particular working directory, and starts with `wfb doctor`
so a half-configured environment is reported rather than blundered into.

In Claude Code the skill is registered under `.claude/skills/` and triggers on
its own — share a picture and say *"build me this watch face"*. That file is a
thin adapter over the same document, so the two cannot drift.

The reasoning behind this — and why a visual GUI builder is deferred — is in
[`docs/research/06-authoring-ergonomics.md`](docs/research/06-authoring-ergonomics.md).

`wfb preview` renders from the **same resolved geometry** the generated Monkey C
uses, so the two cannot disagree about position — which is what makes it a useful
check and not a second implementation.

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
skills/               model-agnostic instructions for building a face with an LLM
wfb/                  the compiler
  yamlsrc.py            YAML loading that keeps source spans
  validate.py           JSON Schema, reported against the author's lines
  catalog.py            the typed data-source catalogue
  expr.py               the expression language -> Monkey C
  ir.py                 the IR, and the semantic pass
  layout.py             relative units -> absolute pixels, per device
  lint.py               ADR 0008's checks, each with a stated confidence
  fonts/                TrueType -> BMFont sheet, subsetted to the used glyphs
  icons.py              icon sizing and resolution over a vendored Nerd Font
  icon_catalog.py       the icon name -> codepoint table, data only
  assets/icons/         the vendored "Symbols Only" font (MIT; see its README)
  emit/                 Monkey C, resources, manifest, jungle
  preview.py            host-side renderer over the resolved IR
  build.py, cli.py      the pipeline and `wfb`
runtime-lib/          the hand-written support barrel the generated code calls
schema/               the published JSON Schema (a shipped artefact)
examples/slice/       the Phase 2 example face -- the smallest end-to-end path
examples/dashboard/   a dense multi-row face: separators, a two-tone clock,
                      conditional colours, a badge and three arcs
tests/                458 tests; only the `slow` ones need the Garmin toolchain
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
only a generator can exploit. The reasoning is in [`docs/adr/`](docs/adr/).

## What is next

Phase 3 — breadth: the remaining element types, per-device overrides, the `raw`
escape hatch, configuration surfaces, complications and interactivity. See
[`docs/limitations.md`](docs/limitations.md) §2 for the full list and `CLAUDE.md`
§6 for the ordering.
