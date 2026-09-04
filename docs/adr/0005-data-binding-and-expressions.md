# ADR 0005 — Data binding, expressions and formatting

- **Status:** Accepted
- **Date:** 2026-09-04
- **Decides:** how values reach the screen, how much computation the format
  allows, and where that computation happens.

## Context

Phase 0 established four facts that dominate this design:

1. **Every data field is nullable.** All twenty `ActivityMonitor.Info` fields are
   typed `… or Null`, and sensors are simply absent on some devices
   (`02-features-feasibility.md` §2). Absence is the normal case, not an error.
2. **A missing permission fails silently** — the API returns null and the element
   never appears, with no diagnostic anywhere. This is the most common
   "works in the simulator, blank on the wrist" failure.
3. **Complications are supported on all three targets** (66 devices, fr955
   included) and are the *only* binding the on-device editor understands.
4. **Complication units are normalised** — metres, m/s, °C, grams — and the
   subscriber is responsible for converting to the user's system settings.

Prior art warns about the expression layer specifically: Facer's flat `#TAG#`
namespace scales to hundreds of undiscoverable tags, while WFF's purely
declarative model drew developer criticism for being unable to express complex
behaviour (`04-prior-art.md` §§1–2).

## Decision

### 1. A typed, namespaced data-source catalogue

Not a flat tag namespace. Sources are addressed by dotted path and carry a type,
a unit, a nullability, and the permission and API level they require:

```yaml
value: activity.steps           # Number,  null-able, no permission
value: activity.step_goal
value: heart_rate.current       # Number,  null-able
value: body_battery.current     # Number,  requires SensorHistory
value: system.battery           # Float,   0..100
value: weather.temperature      # Number,  Celsius, requires Positioning
value: complication.slot1       # bound complication
```

The catalogue is **generated from the SDK**, not hand-maintained, so it carries
each source's real API level and device availability and stays correct across SDK
releases (`03-toolchain.md` §5).

**The compiler derives `manifest.xml` permissions from the bound sources.** This
directly eliminates failure (2) above, and is one of the strongest single
justifications for the whole project.

**Complications are first-class**, as an alternative binding for any slot, and
are preferred where an equivalent exists — because they are the only thing the
native editor can rebind (ADR 0006) and they reach third-party data no direct API
exposes. Unit conversion against `DeviceSettings` is done by the framework, not
the author.

### 2. Expressions compile to Monkey C — there is no runtime evaluator

This is the key consequence of choosing codegen (ADR 0003). Because the compiler
knows the whole design, an expression like

```yaml
color: "heart_rate.current > user.hr_zone4 ? palette.hot : palette.text"
```

becomes a Monkey C ternary over already-fetched locals. **No expression
interpreter ships to the device.** Constant subexpressions are folded at build
time; only genuinely dynamic terms survive.

The language is deliberately small — an *expression* language, not a programming
language:

- literals, and references to data sources, palette entries, and config values
- arithmetic `+ - * / %`, comparison, boolean `and`/`or`/`not`
- ternary `cond ? a : b`
- a fixed function set: `min`, `max`, `clamp`, `round`, `floor`, `abs`,
  `percent(value, goal)`
- **no** loops, no user-defined functions, no assignment, no state

Anything beyond this is a signal to use the escape hatch (ADR 0007) rather than
to grow the language. Growing it is how these formats become unmaintainable.

### 3. Null handling is part of the binding, not an afterthought

Every binding declares what absence renders as. The compiler **requires** this
for nullable sources rather than defaulting silently:

```yaml
- id: hr
  type: text
  value: heart_rate.current
  format: "{:d}"
  when_absent: hide        # hide | placeholder | fallback
  placeholder: "--"
```

`hide` omits the element (and its label, if grouped); `placeholder` draws fixed
text; `fallback` supplies another expression. Generated code guards every read,
so a missing sensor drops its element rather than crashing the face — matching
the practice the sibling Dashboard project arrived at by hand.

### 4. Formatting is declarative and unit-aware

`format` uses Python-style format specs, familiar and unambiguous:

```yaml
format: "{:d}"        # 12345
format: "{:.1f}"      # 8.4
format: "{:%H:%M}"    # time
units: auto           # follow DeviceSettings; or metric | statute
```

Unit conversion (metres → km/mi, °C → °F, m/s → pace) is framework-owned and
driven by `DeviceSettings`. Hand-written faces get this wrong constantly; a
builder should get it right once.

Because font metrics are known per device and language (ADR 0004 §5), the
compiler can check at build time that a formatted value's **widest plausible
rendering** fits its slot — e.g. `{:d}` on `activity.steps` can reach five
digits. That is a Phase 1.4 lint.

### 5. Refresh tiers are declared, not discovered

Each source carries a cost class, and the generator places reads accordingly:

| Tier | Contents | Read |
|---|---|---|
| `frame` | steps, DND, alarms, notification count, battery | every `onUpdate` |
| `slow` | `SensorHistory` walks, Weather, sunrise/sunset | behind a TTL cache |
| `event` | complication callbacks | on subscription callback |

`onPartialUpdate` may read **only** `frame`-tier sources, enforced by the
compiler. This encodes as a build-time rule what the Dashboard project documents
as a discipline — and it protects the budget whose overrun is permanent
(`01-platform-capabilities.md` §2).

## Consequences

- Zero runtime interpretation cost; expression errors are build errors with
  source spans.
- The expression compiler needs a type checker (source types → operator
  validity → target attribute type). This is real work but it is what turns
  "misspelled data source" into a build failure, as the brief requires.
- The catalogue must be regenerated per SDK release; a drifted catalogue would
  silently mis-declare permissions. Treated as a CI check against the SDK.
- Deliberate limitation: no cross-frame state (no "peak HR this hour" unless a
  Garmin API provides it). Expressions are pure functions of current readings.

## Alternatives rejected

- **Facer-style flat `#TAG#` interpolation** — proven to scale badly, and gives
  up type checking and autocomplete, both of which we get free from the schema.
- **A general scripting language** — cannot be evaluated on device without an
  interpreter (rejected in ADR 0003), and evaluating it at build time makes it a
  macro system, which is more power than a layout format should have.
- **Runtime expression blob + tiny evaluator** — the interpreter argument of
  ADR 0003 in miniature, and it lands the cost on the partial-update path.
