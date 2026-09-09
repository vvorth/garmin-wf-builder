# ADR 0007 — The escape hatch

- **Status:** Accepted
- **Date:** 2026-09-04
- **Decides:** what happens when the format cannot express what the author wants.

## Context

This ADR exists because of the clearest lesson in the prior art. Google's Watch
Face Format is purely declarative with no executable code, and the developer
backlash was precisely that it "does not allow for more complex features or
animations" (`04-prior-art.md` §1). Google absorbed that because they could make
WFF mandatory — Wear OS 5 dropped the alternatives.

**We have no such leverage.** If an author hits the ceiling of our YAML and has
no way forward, they abandon the tool and go back to hand-written Monkey C,
taking the whole design with them. Every escape-hatch-free declarative format
either has a captive audience or a small problem domain. We have neither.

Countervailing risk: an unrestricted escape hatch destroys the guarantees that
justify the format — the compiler can no longer compute clip rectangles,
permissions, memory estimates or AMOLED ratios if arbitrary code draws
arbitrarily.

## Decision

Provide a **narrow, declared, statically-bounded** escape hatch: a `raw` element
that contributes hand-written Monkey C, but must declare everything the compiler
needs to keep reasoning.

```yaml
- id: sparkline
  type: raw
  bounds: { anchor: center, dy: 20%, width: 60%, height: 12% }
  modes: [active]
  reads: [heart_rate.history]        # drives permissions
  draws: custom/Sparkline.mc:drawSparkline
  est_bytes: 900                     # optional, for the memory linter
```

The contract:

- **`bounds` is mandatory.** The compiler treats it as opaque but occupied — it
  still computes clip rectangles, overlap and safe-area checks, and AMOLED
  ratios (assuming worst case: fully lit).
- **`reads` is mandatory.** Permissions stay derivable, so the
  silent-permission-failure protection (ADR 0005) is not lost. (`reads` no
  longer also drives a refresh-tier placement decision — ADR 0005's amendment
  deleted that concept; every source, including whatever a `raw` element
  declares here, is read the same plain way.)
- **`draws` names a function** with a fixed signature, given the `Dc`, the
  resolved bounds and the values it declared. The generator emits the call and
  the null guards.
- The file is copied into the build and compiled normally; it participates in
  `excludeAnnotations` like generated code.

### What is deliberately *not* offered

- No inline Monkey C in YAML. Code lives in `.mc` files with real tooling.
- No hooks into `onUpdate`/`onPartialUpdate` directly — a `raw` element draws
  within its bounds and nothing else. It cannot restructure the frame.
- No unbounded elements. Refusing `bounds` is refusing the hatch.

### Honest degradation

Using `raw` costs guarantees, and the build says so once, plainly:

```
note: 1 raw element ('sparkline') — memory estimate and AMOLED
      luminance are worst-case approximations for this element.
```

This keeps the linter's other claims honest rather than quietly weakening them.

## Consequences

- The ceiling stops being a cliff: an author who needs one exotic element keeps
  the other 95% of the design declarative.
- The generated code must remain readable for the hatch to be usable at all,
  which reinforces the readability requirement in ADR 0003.
- Golden-file tests must cover `raw` wiring, since it is the seam most likely to
  break as codegen evolves.
- Faces using `raw` are less portable across devices, by construction. Acceptable
  and stated.

## Alternatives rejected

- **No escape hatch** — the WFF failure mode, without Google's ability to force
  migration.
- **Arbitrary code injection into lifecycle methods** — forfeits every static
  guarantee, which is the entire value proposition.
- **"Eject to a plain Connect IQ project"** — a one-way door. Useful as an
  additional `eject` CLI command later, but it is a migration path, not an
  escape hatch: it does not let an author keep using the tool.
