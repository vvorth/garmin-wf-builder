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

**`when_absent:` governs a *value*, and is a different axis from `visible:`**
(ADR 0004 §1). A nullable source read by a visibility condition takes no policy
and cannot be given one: absence there means hidden, full stop, because a
placeholder is a substitute value and existence has no substitute. The two
compose independently — an element can be visible while its value is absent, in
which case `visible:` lets it through and `when_absent:` decides what it shows.
The one place they interact is reported rather than merged: a `placeholder:`
whose nullable sources are *all* also read by `visible:` can never be drawn, and
that is a warning, the same one a nullable `color:` already earns.

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

> **Amended — see "Amendment (2026-09-09): the refresh-tier concept is
> deleted" at the end of this document.** The section below is kept because
> it is what was decided and built, the same precedent ADR 0006 §6 set for
> its own superseded text. It no longer describes the compiler: `catalog.
> Tier`, `Reader.tier`, `Reader.ttl_seconds` and `runtime-lib/WfbCache.mc` do
> not exist any more, and there is no `event`-tier cached field either.

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

## Amendment (2026-09-09): the refresh-tier concept is deleted

**What changed.** Section 5's `frame`/`slow`/`event` tier system — a TTL
cache for `slow`-tier reads and a per-type cached field fed by a
subscription callback for `event`-tier ones — is gone in its entirety:
`catalog.Tier`, `Reader.tier`, `Reader.ttl_seconds`, `Source.tier`,
`wfb/ir.py`'s `_check_tiers` and its `refresh-tier` diagnostic, and
`runtime-lib/WfbCache.mc` are all deleted. Every source is now read the same
way: a plain call, hoisted once per distinct reader per element method
(unchanged from before — two elements sharing one reader still share one
call), every single frame, with nothing cached inside the generated face.

**Why.** The premise of Section 5 was that some Garmin API calls are too
expensive to make every frame, so this compiler should cache them itself.
That premise does not hold up against the SDK's own documentation: `Toybox/
Weather.html` describes `getCurrentConditions()` as "get the **most recently
cached** weather conditions" — not "fetch weather conditions" — meaning the
platform is already doing the caching this ADR proposed doing a second time,
inside a 128 KB budget that has no room to spend on redundancy. This was the
user's own observation, and it is correct: verified by reading the cited SDK
page directly rather than assumed from the original ADR's framing.

**Consequence for check 12 (ADR 0008) and ADR 0006 §5.** The rule "an error
if a `low_power` element reads a non-`frame`-tier source" is gone along with
the tiers it referred to. `weather.*` and `complication.*` (the renamed,
widened form of what this ADR called `event`-tier sources — see below) may
now be bound from `low_power`/`always_on` elements. **The platform limit this
rule protected has not gone away**: exceeding the `onPartialUpdate` power
budget still calls `onPowerBudgetExceeded` and disables partial updates
**permanently**, for the app's remaining lifecycle (`01-platform-
capabilities.md` §2, CLAUDE.md constraint 4). What changed is only who
enforces staying under it — previously this ADR's hard compile-time rule,
now solely ADR 0008 check 9's suppressible `partial-update-budget`
heuristic, whose warning text was strengthened in the same change to name a
`weather.*`/`complication.*` read on a `low_power` element as the case to
check first. This is a real, deliberate weakening of a guarantee the
compiler used to make unconditionally, accepted by the user with that
tradeoff stated plainly, not a silent regression.

**What replaced the `event` tier specifically.** Complications
(`Toybox.Complications`, API 4.2.0) are now read by the same plain pull every
other source uses — `WfbComplications.valueOf(new Complications.Id(...))` —
cast to the source's declared type because `Complications.Complication.value`
is a union (`String or Number or Float or Long or Double or Null`). Evidence
this is sound: Garmin's own sample, `$CIQ_SDK/samples/ConfigurableWatchFace/
source/ConfigurationWatchFaceView.mc`, calls `Complications.getComplication
(id).value` from `updateConfiguration`, which runs *before* the first
`subscribeToUpdates` call and, in edit mode, without ever subscribing —
confirmed compiling in a standalone probe,
`docs/research/probes/complication-pull/`, `BUILD SUCCESSFUL` under `-l 3` on
two of the three targets. The per-type cached field and the `onUpdate`-time
`switch` are gone. A subscription (`WfbComplications.subscribe`, once per
bound type, in `onLayout`) is deliberately kept regardless — its callback's
entire body is now `WatchUi.requestUpdate()` — because whether a pulled
value would *stay* fresh with no subscription at all is genuinely
**unverified**: this project's sandbox has no working Connect IQ simulator
(`01-platform-capabilities.md` / `docs/limitations.md` §2), so there is no
way to observe staleness directly, and the cost of keeping the subscription
(one extra line per bound type, nothing per frame) was judged cheap insurance
against a silent-staleness failure of exactly the kind this whole project
exists to prevent.

**All 42 `COMPLICATION_TYPE_*` values are now catalogue sources**, under a
`complication.<name>` namespace, generated from one table
(`wfb/complications.py`'s `TYPES`) rather than the nine hand-picked ones
Section 5's original text implicitly scoped `event`-tier sources to. The nine
that used to be reachable under a direct-looking path (`body_battery.
current`, `weather.sunrise`, and so on) are renamed to their `complication.*`
form; the old path now raises a `source-renamed` build error rather than
"unknown data source". One rule governs the whole catalogue with no
exceptions: `complication.<type>` is *always* read through `Toybox.
Complications`; every other path is *always* a direct API read — see
`docs/format.md`'s "The `complication.*` namespace" section and
`docs/limitations.md` §2/§3 for the per-device gating gap this widened.

**What of the original still stands.** Section 1 (typed, namespaced
catalogue), Section 2 (guarded null handling), Section 3 (silent-permission
protection), and Section 4 (declarative formatting) are untouched. The
catalogue-regeneration-from-SDK consequence in the main "Consequences"
section above is also untouched — it was never built, tier or no tier
(`docs/limitations.md` §2). Complication units (metres, m/s, °C, seconds,
percent) are still taken verbatim from the SDK's own Type table, unconverted,
matching this ADR's Context point 4.
