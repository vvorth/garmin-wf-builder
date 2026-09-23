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

> **Amended — see "Amendment (2026-09-15): `copy`, one name bound in one
> place".** The operators and functions are unchanged; one reference name was
> added, in `type: pattern` colours only.

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
`wfb/ir/`'s `_check_tiers` and its `refresh-tier` diagnostic, and
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
now be bound from `low_power` elements (or an AMOLED `aod:` override's
`visible:`, plan 14 — `always_on` itself was removed outright, see that
plan's D3). **The platform limit this
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
`docs/guide/data.md`'s "The `complication.*` namespace" section and
`docs/limitations.md` §2/§3 for the per-device gating gap this widened.

**What of the original still stands.** Section 1 (typed, namespaced
catalogue), Section 2 (guarded null handling), Section 3 (silent-permission
protection), and Section 4 (declarative formatting) are untouched. The
catalogue-regeneration-from-SDK consequence in the main "Consequences"
section above is also untouched — it was never built, tier or no tier
(`docs/limitations.md` §2). Complication units (metres, m/s, °C, seconds,
percent) are still taken verbatim from the SDK's own Type table, unconverted,
matching this ADR's Context point 4.

## Amendment (2026-09-15): `copy`, one name bound in one place

**What changed.** Inside a `type: pattern` element's colours (its `color:` and
each part's), the expression scope has one extra name: `copy`, a non-null
Number, the index of the copy being drawn. It compiles to the index of the
generated draw loop (`for (var i = 0; ...)`), so
`copy == (date.weekday + 5) % 7 ? palette.on : palette.off` becomes a ternary
over `i` and a local read before the loop. It is still compiled rather than
interpreted, and there is still no evaluator on the device. Everywhere else,
`copy` is unbound and `check` reports it with its own message ("only defined
in a 'type: pattern' colour"), not "unknown data source". In the same change,
a pattern colour may read any source that is **never absent**. One that can
be absent is still refused, because a pattern has no `when_absent:` (§3).
A new catalogue entry, `date.weekday` (1 = Sunday .. 7 = Saturday, read under
`FORMAT_SHORT` and cast to `Number` as §1's complication values are), is the
number such a colour compares against.

**Why this is not "growing the language".** No operator, function, loop or
state was added. A pattern *is* the loop, and ADR 0004 §7 already has the
device run it. `copy` only names the loop's index, which that code already
had, so a colour can depend on it. The alternative within the rule above is
one element per copy, which is exactly what patterns were built to replace:
seven `visible:`-gated circles to light today's dot in a week row.
`examples/features/patterns/face.yaml`'s `week_dots` did not show the day until this
change, and it could not be fixed in the YAML.

**What stays true.** A hand colour still reads no data at all (§5.4 of plan
04). A colour that reads a source still keeps its element out of `static:`.
A colour that reads only `copy` may be static, because a copy's index never
changes.

## Amendment (2026-09-15): `when_absent: hide` on a pattern, and per-copy part `visible:`

**What changed.** Two related relaxations, both requested by the user
against `examples/features/patterns/face.yaml`'s `test_visibility` (a 5-copy move-bar
row):

1. A pattern's colours (the element's own and every part's) may now read a
   source that **can** be absent, provided the pattern declares
   `when_absent: hide`. Absence then hides the whole pattern -- every copy,
   every part -- because the reading is taken once per frame, before the
   copy loop, so its absence is a fact about the frame, not about any one
   copy. The generated code is the null guard every element already gets
   (`if (x == null) { return; }`), emitted before the loop. There is no
   `placeholder:`/`fallback:`: a pattern has no single value to substitute
   one for, only existence.
2. A pattern part gains its own `visible:`, a boolean expression evaluated
   **per copy**, with `copy` bound the same as in a colour: false hides that
   part for that one copy only. A source that can be absent, read here, is
   governed by the pattern's `when_absent: hide` -- the whole pattern hides
   -- not by "absent means this part is hidden," which is what the same
   nullable reading would mean inside an *ordinary* element's `visible:`.
   This is a deliberate difference from element-level `visible:`, for the
   same per-frame-not-per-copy reason as (1).

**Why the previous amendment's own refusal no longer holds.** The
first 2026-09-15 amendment above refused a pattern colour reading an absent-able
source with one specific reason: "hiding every copy because one reading
went missing would be a silent no-op." That reasoning is about *silence* --
a reading vanishing and the whole pattern quietly disappearing with no
policy on record. It does not hold once the author writes
`when_absent: hide` explicitly: the policy is then declared, required by the
compiler (`Builder._check_pattern_absence`), and reported as a note if it
turns out to do nothing -- so it is never silent, the same standard every
other element's `when_absent:` is already held to (§3: "every binding
declares what absence renders as"). The old rule was a *blanket* refusal
in place of a policy; this amendment replaces the blanket refusal with the
policy itself.

**Why this is not "growing the language" either.** Still no operator,
function, loop, assignment or state. `visible:` on a part reuses the exact
boolean-expression machinery (`Builder._visible`) the element level already
has; the only addition is compiling it inside the pattern's `copy`-bound
scope, alongside a colour, instead of outside it. The `when_absent:` field
itself is not new syntax -- `text` and `progress` already have one; a
pattern's is simply restricted to `hide` in the schema (`enum: ["hide"]`),
the same restricted-enum precedent `progressElement`'s own `when_absent:`
(`hide`/`fallback`, no `placeholder`) already set.

**What stays true.** A hand colour still reads no data at all, absent-able
or not -- this amendment is pattern-only. Element-level `visible:` is
unchanged: "absent means hidden," no policy, and `copy` is still unbound
there (compiled before the pattern builder's `copy` binding opens). §3's
"every binding declares what absence renders as" is honoured, not
relaxed -- a pattern's binding is now `hide`, spelled out, rather than an
unconditional compiler refusal standing in for a policy nobody could
actually choose.

## Amendment (2026-09-15): a target device lacking a binding entirely is absence too

**What changed.** §3 wrote "every binding declares what absence renders
as" for a **nullable** reading -- the SDK's own contract, that the *call*
can return null on any device that has it. There is a second, narrower kind
of absence this ADR did not name: a *target device that does not have the
binding at all* -- lacks `Toybox.Complications` outright (`fenix6`,
`fr245`), or lacks one particular field of a reader that is otherwise
present (`ActivityMonitor.Info.stressScore` on `fenix6`,
`floorsClimbed`/`floorsClimbedGoal`/`batteryInDays`/`ambientPressure` on
`fr245`) -- discovered while adding `fenix6` back to `examples/dashboard/
face.yaml`'s `targets:` (`docs/research/probes/api-gating/`; the ADR 0006
sixth amendment covers the `Complications`-module half of the same
finding). This amendment folds that second kind into the *same* contract
rather than inventing a second one: **a binding a target device lacks reads
as absent on that device**, through the very same `when_absent:` path a
null reading already takes -- `hide`/`placeholder`/`fallback` on an
ordinary source, and the pattern-level `when_absent: hide` the amendment
above just added, apply identically whether the value came back null at
runtime or the device could never have supplied it at all. The author
writes one policy; which of the two reasons triggered it is invisible to
`when_absent:`, on purpose -- a design that binds `activity.
stress_score` does not need a *second* absence policy for "and also
fenix6 specifically."

**Why one contract, not two.** The alternative -- a build error on a
target that lacks a binding -- was rejected by the user for the same
reason a hand-written Dashboard face already treats every sensor as
optional (§3's own framing, "matching the practice the sibling Dashboard
project arrived at by hand"): a value being unavailable on *some* watch is
not a design defect, it is the platform. Constraint 8 ("every data field is
nullable, absence is normal," root `CLAUDE.md` §4) already said this for
runtime nulls; extending it to compile-time-known per-device gaps is not a
new principle, only a wider set of reasons a value can be missing.

**What is new at the mechanism level, not the policy level.**
`wfb.availability` (new module) is what tells `wfb/emit/monkeyc/`'s
codegen *which* device gaps exist for a given design, aggregated over every
target in one build (`compute_guards`) so the one shared generated view
still emits one guard per gap, not one per device. See
`docs/lore/codegen.md` for the mechanism and `docs/lore/platform-
constraints.md` constraint 6d for the platform fact this rests on
(`monkeyc` cannot catch this at compile time; only a device's own
`api.debug.xml` can). The build **warns** rather than failing (lint
`api-gated`) -- unchanged from every other absence in this ADR, which has
never been a build error either.

**What is unaffected.** A reader *function* some device lacks (none exist
today among the readers this project uses) is still a hard build error, not
folded into this contract -- the generator can gate a whole module or a
bare field, because that is what a device's symbol table exposes
structurally, but it has no mechanism to gate one function call out of a
reader's `call` expression while keeping the rest, so that case is not
"absence," it is "not buildable yet." See `wfb/catalog.py`'s `Reader.
requires` docstring.

## Amendment (2026-09-15): `copy` in a pattern text part's `value:`

**What changed.** `copy` is now also bound in a `shape: text` pattern
part's `value:` (plan 06, `git show f5155d7:docs/plans/06-pattern-text-and-group-align.md`).
It compiles the same way it does in a colour: the draw loop's `i`, then
`formatting.emit` builds the string on the watch, once per copy. §2 holds:
the value is compiled, not interpreted, on the device.

**What is new is a host-side use of the same tree.** Such a `value:` may read
**only** `copy` and literals. The compiler therefore evaluates it on the host
for every copy index (`expr.evaluate` plus `formatting.render`, the preview's
own path), because it needs every string at build time: a custom font is
subsetted to the glyphs the design draws, and a pattern's extent is its
measured ink. The device and the host evaluate one tree, so they agree
wherever Python and Monkey C arithmetic agree. **UNVERIFIED:** the sign of
`%` on a negative left side. Python gives `-1 % 12 == 11`, while a
Java-style truncation would give `-1`, and the SDK's `Basic_Syntax.html`
does not say which Monkey C does. This is not specific to text parts, since
constant folding and the preview already rely on Python's `%`.
`docs/guide/patterns.md` tells authors to keep the left side non-negative.

**Why data is still refused there.** A string that depends on a reading
cannot be known at build time. Its glyph subset and extent would then have
to be guessed, as a `text` element guesses from `formatting.widest`, and it
would need a `when_absent:` policy. This is deferred, not rejected
(`docs/limitations.md` §2).
