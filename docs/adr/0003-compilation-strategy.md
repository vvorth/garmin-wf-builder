# ADR 0003 — Compilation strategy: code generation

- **Status:** Accepted
- **Date:** 2026-09-04
- **Decides:** how a YAML face becomes something that runs on a watch.

## Context

Three options were posed: codegen, a generic on-device interpreter reading a
serialised layout blob, or a hybrid. The brief says "codegen is likely correct —
prove it." Phase 0 supplies the proof, and it is more one-sided than expected.

### The evidence

**1. There is no device-side renderer.** Every comparable declarative format
depends on one: WFF is drawn by the Wear OS system renderer, Facer by its own
app, Fitbit by an on-device JS engine (`04-prior-art.md`). Garmin ships nothing
equivalent. So the "interpreter" option does not mean *reusing* a platform
runtime — it means **writing one and shipping it inside the face**.

**2. That interpreter competes with the design for the same 128 KB.** The
watch-face memory limit on all three targets is 131072 B — one sixth of the
786432 B the same hardware gives a watch app (`01-platform-capabilities.md` §3).
An interpreter would need: a blob decoder, an element dispatch table, an
expression evaluator, and a data-source registry — all resident, all counted
against the same budget, and all present whether or not a given face uses them.
Codegen emits only the drawing calls a face actually makes.

**3. Monkey C has a native per-device dead-code mechanism that only a generator
can exploit.** Jungle `excludeAnnotations` strips annotated declarations per
target, and Garmin's stated purpose is "to help save memory during app execution
on a device" (`03-toolchain.md` §3). The compiler also removes statically
resolvable `X has :y` checks by default. A generator can annotate and guard
freely, and the platform deletes what the target does not need. An interpreter's
dispatch table is opaque to that analysis — every branch ships.

**4. Per-frame cost matters more here than in most systems.** `onPartialUpdate`
runs under a strict time budget, and exceeding it **permanently disables partial
updates for the rest of the app lifecycle** (`01-platform-capabilities.md` §2).
Interpretation overhead lands directly on the most cost-sensitive path in the
system, and the failure is not graceful degradation but permanent loss of the
feature.

**5. Static knowledge is where a builder's value actually is.** Because the
generator knows the whole design, it can compute things a runtime cannot: exact
clip rectangles for partial updates, the used-glyph set for font subsetting,
hit-test tables, the permission set implied by the bindings, and AMOLED
pixel/luminance ratios. Several of these are the Phase 1.4 lint checks. An
interpreter defers all of it to a device that cannot afford the work.

## Decision

**Code generation.** YAML → validated IR → generated Monkey C + resource XML +
`manifest.xml` + jungle → `monkeyc` → `.prg`.

With one deliberate qualification, which is where the "hybrid" lands:

**A small hand-written Monkey C support barrel (`runtime-lib/`) is permitted for
genuinely shared, data-independent logic** — arc geometry helpers, tick-scale
maths, the `SensorHistory` iterator walk, refresh-tier caching. This is a
*library the generated code calls*, not an interpreter: it contains no dispatch
on serialised layout data, and anything unused is excluded per-device by
annotation.

The distinction that keeps this honest: **generated code decides *what* is
drawn; the barrel only helps with *how*.** If a barrel function ever needs to
branch on the design, that branch belongs in the generator.

## Consequences

- **Generated Monkey C must be readable.** The brief asks to review its quality,
  and it is also the escape-hatch substrate (ADR 0007) and the thing being
  debugged when something misbehaves on device. Requirements: stable symbol
  naming derived from element ids, a header comment citing the source file and
  the generator version, comments tying each drawing block back to its YAML
  element, and layout constants named rather than inlined as bare numbers.
- **Golden-file tests over generated output** are the primary compiler test, and
  are runnable with no Garmin toolchain — which matters given device files are
  the scarce resource (`03-toolchain.md` §6).
- **Build for strictness:** generated code should compile clean at
  `-l 3` (strict type check) with `-w`, and `-O z` (optimise code space) is the
  right default for a memory-bound watch face. A generator has no excuse for
  emitting code that fails strict checking.
- **Per-device specialisation is a first-class output**, not an afterthought:
  the generator emits the jungle, the per-device resource directories, and the
  `excludeAnnotations` sets together.
- **Build time grows with device count** (one `monkeyc` invocation per device,
  each paying JVM startup). Mitigate with parallel invocation and by defaulting
  `build` to one device, with `build --all` explicit.

## Alternatives rejected

- **Pure interpreter** — pays memory and per-frame cost on the two axes the
  platform is most constrained on, forfeits `excludeAnnotations`, and puts
  interpretation overhead on the path whose overrun penalty is permanent. Its
  usual advantage — ship a design without recompiling — is worth little when
  distribution is personal sideload and a build takes seconds.
- **Interpreter with generated constant tables** — halves the memory argument at
  best while keeping the dispatch overhead and the readability loss. Codegen with
  a support barrel achieves the same code reuse without a runtime dispatch layer.
