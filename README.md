# garmin-wf-builder

A watchface builder framework for Garmin Connect IQ: declare a watch face's
design and data bindings in YAML, get a compilable, sideloadable `.prg`.

**Targets:** fēnix 8 Solar 47 mm / 51 mm, Forerunner 955.
**Distribution:** personal sideload.
**Status:** research and architecture complete; **no framework code yet**.

---

## Start here

| If you want… | Read |
|---|---|
| to take over this project | **`CLAUDE.md`** — full handoff context |
| the decisions and why | `docs/adr/README.md`, then `docs/adr/0001`–`0009` |
| the platform research | `docs/research/00-summary.md`, then `01`–`05` |
| what was measured on real device files | `docs/research/05-device-files.md` |

## Setup

```sh
./tools/setup-env.sh
```

Installs the Connect IQ SDK 9.2.0, generates a developer key, and installs the
device definitions. See `CLAUDE.md` §2 — the SDK downloads freely, but **device
definitions cannot be downloaded** and must come from a host SDK Manager install.

Verify:

```sh
cd ~/claude/garmin-watchface-protomolecule
$CIQ_SDK/bin/monkeyc -f monkey.jungle -d fenix8solar47mm \
    -o /tmp/dash.prg -y ~/ciq/developer_key.der -w
# -> BUILD SUCCESSFUL
```

## Layout

```
CLAUDE.md                     handoff context — read first
docs/research/00..05          Phase 0 findings, with sources
docs/research/data/           164-device DB scraped from SDK docs (superseded
                              for capability checks by vendor/devices/*/api.debug.xml)
docs/adr/0001..0009           Phase 1 architecture decisions
tools/setup-env.sh            rebuild the build environment
tools/research/               research instrumentation (device DB, capability
                              matrix, SDK HTML->text converter)
vendor/devices/               Garmin device definitions (gitignored, 21 MB)
```

## What is decided

Python host language; YAML canonical with a published JSON Schema and a lossless
GUI over it; **code generation** rather than an on-device interpreter;
expressions compiled to Monkey C with no runtime evaluator; anchors and
relative/polar units resolved to pixels at build time; a narrow bounded escape
hatch to hand-written Monkey C; and build-time lints that carry explicit
confidence levels.

The reasoning is in `docs/adr/`. The short version of *why codegen*: Garmin ships
no device-side renderer, so an interpreter would have to live inside the same
**128 KB** the design must fit in — and it would forfeit Garmin's
`excludeAnnotations` dead-code mechanism, which only a generator can exploit.

## What is next

Phase 2 — the thin vertical slice. One device, a minimal face, one command:
`example.yaml` → validate → generate Monkey C + resources + jungle → `monkeyc` →
simulator → screenshot. `CLAUDE.md` §6 has the suggested order.
