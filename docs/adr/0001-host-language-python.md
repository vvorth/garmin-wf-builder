# ADR 0001 — Host language: Python

- **Status:** Accepted
- **Date:** 2026-09-04
- **Decides:** the implementation language for the compiler, CLI, preview
  renderer and asset pipelines. Not the *output* language, which is Monkey C.

## Context

The brief says "you choose, justify it, but not TypeScript/Node". Constraints
that actually bear on the choice, from Phase 0:

- The asset pipeline is the hardest dependency. We must subset a TTF/OTF into an
  AngelCode `.fnt` + PNG atlas (`02-features-feasibility.md` §7), and quantise
  bitmaps to device palettes at 1/2/4/8/16 BPP (§1). Both need mature font and
  image libraries; writing either from scratch is a project in itself.
- The preview renderer must share layout semantics with codegen or the two will
  drift (Phase 3.8 explicitly asks for this). Sharing is far easier inside one
  language and one process than across a language boundary.
- The AMOLED linter needs to rasterise the always-on layout and integrate
  pixel/luminance ratios (`01-platform-capabilities.md` §4) — again image work.
- The device database is derived by parsing SDK-shipped HTML/JSON
  (`tools/research/*.py` already do this in Python).
- Distribution is personal sideload for one developer on macOS and Linux, so
  single-binary distribution has low value. This removes the main argument for
  Rust or Go.

## Decision

**Python** (3.11+), with `Pillow` for imaging, `fontTools` for font subsetting,
and a JSON Schema validator for the format.

## Rationale

1. **The asset pipeline decides it.** `fontTools` is the reference
   implementation for font subsetting and `Pillow` is the obvious choice for
   palette quantisation and rasterisation. In Rust or Go we would end up
   shelling out to Python or binding C libraries for exactly these steps, which
   concedes the benefit while adding a boundary.
2. **Preview/codegen fidelity.** Both consume the same layout IR in-process. A
   shared IR across a FFI or subprocess boundary is where drift is born, and the
   brief calls out drift as a risk worth a dedicated check.
3. **Continuity with existing work.** The sibling Dashboard project already has
   `tools/preview.py` (694 lines, parses `Theme.mc` at runtime and renders a MIP
   preview) and `tools/make_clock_font.py`. That is a working, relevant preview
   renderer to learn from and partially port — a real head start.
4. **Research-heavy codebase.** Phase 0 showed how much of this work is parsing
   Garmin's artefacts and iterating on findings. Python's iteration speed
   matters more here than runtime performance; the compiler runs for a fraction
   of a second against `monkeyc`'s multi-second JVM start.

## Consequences

**Accepted costs:**

- Users need a Python environment. Mitigated with `uv`/`pipx` install and a
  pinned lockfile; acceptable for a personal tool, and would need revisiting if
  this were ever distributed broadly.
- No compiler-enforced exhaustiveness over IR node types the way Rust's enums
  would give. Mitigated by: strict type hints checked in CI (`mypy --strict`),
  and the JSON Schema as the real validation boundary. IR correctness is
  enforced by golden-file tests either way.
- Runtime performance is irrelevant at this scale but would matter if a live GUI
  preview needed 60 fps rendering. The editor is Phase 3.8; if it needs that, the
  renderer can move to the browser (canvas) while Python stays the compiler.

**Follow-on decisions:** package boundaries (`schema/`, `compiler/`, `devices/`,
`cli/`, `editor/`) are Python packages in one repo with one lockfile. The
`runtime-lib/` barrel remains hand-written Monkey C and is not affected.

## Alternatives rejected

- **Rust** — best distribution story and the strongest IR modelling, but weak
  font/image tooling for our specific pipeline and slower iteration on a
  research-shaped problem. Reconsider if this becomes a widely distributed tool.
- **Go** — good CLI ergonomics and easy cross-compilation, but the weakest of
  the three for font subsetting and image processing, which is the part we
  cannot avoid.
- **TypeScript/Node** — excluded by the brief. (Noted that the nearest prior art,
  `tobwil/garmincreator`, is Next.js/TypeScript and stalled at device breadth —
  a problem of device data, not language.)
