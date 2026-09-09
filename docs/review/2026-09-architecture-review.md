# Architecture review — post "delete the TTL cache, open up complications" change

Scope: the change described in SPEC.md (TTL/refresh-tier deletion,
`complication.*` as a 42-entry generated namespace, `on_hold: auto`), reviewed
against the rest of the compiler it touches. Everything below was checked
against the actual code and, where noted, against real `wfb build` /
`monkeyc` output — this session had the real Connect IQ toolchain available
(`$CIQ_SDK` at 9.2.0, device files installed), so "verified" below means an
actual build ran, not just a read of the source.

The review itself changed no code. **The session immediately after it fixed
F1-F4**; see the status section below before reading any finding as current.

---

## Status — read this first

**F1, F2, F3 and F4 are fixed.** F6, F7 and F8 are open. F5 was already stale
when it was written.

The findings below are **left exactly as first written**, in the present tense
they were written in. That is deliberate: what was wrong, and *how it was
established*, is the part worth keeping — several of these were settled by a
real build rather than by reading, and that evidence is what makes them
trustworthy later. Each fixed finding carries a **`FIXED`** note at its head
saying what changed and where; the body after that note describes the code as
it was, not as it is.

If you are looking for the current state of the compiler, read the code and
`docs/limitations.md`, not this file.

| | Finding | Status |
|---|---|---|
| **F1** | `_view` unused warning | **Closed.** The field is now declared only when a carousel reads it (`wfb/emit/monkeyc.py`, `has_carousel`). The constructor *parameter* stays unconditional -- an unused parameter does not warn, verified by build -- so one delegate shape and one construction site still serve every design. The test gap this finding blamed is closed too: `test_a_plain_hold_design_compiles_without_warnings` (slow) compiles a plain `on_hold:` design through real `monkeyc` and asserts **warning-free**, and a fast test pins the field to carousel designs. Both were confirmed to go red against the unfixed emitter before being trusted. |
| **F2** | collision guard | **Closed.** `tests/test_catalog.py::test_reader_and_value_locals_never_collide` checks every `Reader.name`, every `local_name(path)`, the `...Obj` intermediate form, and the emitter's own fixed locals for pairwise uniqueness -- in the fast loop, not behind `slow`. Verified red against the pre-fix naming (all 42 collisions listed by name) and green after. `Builder._check_symbol_collision` was deliberately left alone: it is element-id-scoped by construction, and these collisions are catalogue-scoped. |
| **F3** | per-device gating | **Closed.** `wfb/lint.py::check_complication_availability`, code `complication-gated`: a suppressible warning comparing `complications.TYPES[name].since` against `Device.api_level`, covering both a `complication.*` binding and an `on_hold:`/`launch:` naming a gated type, with different message text for each (a reading that never arrives vs. a hold that does nothing). Emitted through `_emit`, so suppression genuinely works -- verified, since this document's own neighbourhood in CLAUDE.md records two checks that were advertised as suppressible and were not. |
| **F4** | `Reader` means two things | **Closed, documentation only.** The class docstring now names both shapes and says which of the 51 entries is which. No structural change, as this finding itself recommended. |

Commits: `c095538` (F1), `7aebde6` (F2 and F4), `1ba1077` (F3), `11a4781`
(the documentation those three made stale). `pytest -m "not slow"` is 511
passing and `-m slow` is 9 after them, up from 501 and 8.

**One thing each fix was held to, and it is the part worth copying**: every
new guard had to be *seen to fail* against the unfixed code before it was
trusted — the `_view` test against the unconditional emitter, the collision
test against the pre-fix naming, the new warning's suppression against a real
`lint: {allow: [...]}`. A guard nobody has watched fail is not a guard, and
this repo has been bitten by exactly that before (CLAUDE.md records two lint
checks advertised as suppressible that were not).

F5 was already stale when written (see its own note). F6, F7 and F8 are
**open** and untouched — they are collected under "Still open" at the end of
this document.

---

## Summary

The change itself is clean. The TTL cache is gone with nothing left dangling
(no stray `WfbCache`/`Tier`/`ttl_seconds` references anywhere in `wfb/`), the
complication table is generated from one source of truth
(`wfb/complications.py`) rather than hand-copied, `on_hold: auto` is a small,
well-bounded deferred pass that mirrors the shape of the deleted
`_check_tiers`, and the self-verifying tests (`ALL_CODES` vs. every emitted
diagnostic code, the renamed-source precedent) were extended correctly rather
than bypassed. This is a codebase that mostly does what its own CLAUDE.md
asks: symbols are checked against the SDK, tradeoffs are written down where
they're made, and the fast test suite still passes.

Five things actually matter, in priority order. **Items 1-4 have since been
fixed** (`c095538`, `7aebde6`, `1ba1077`); item 5 was already resolved as it
was being written. They are left in their original wording below — see the
status table above and each finding's own `FIXED` note for what changed.

1. **A concrete, verified bug**: any design using `on_hold:` without a
   `carousel` produces a real `monkeyc` warning (`Member variable '_view' is
   not used`) on every build. Pre-existing (from the carousel session, not
   this change), but unfixed, unlisted anywhere, and untested — no test in
   the repo compiles a plain `on_hold:` design with the real toolchain.
2. **The symbol-collision checker doesn't cover the class of bug it was
   built to prevent.** `_check_symbol_collision` only compares element-id-derived
   names against each other; the exact collision it exists to catch (a
   reader's local vs. a source's local in the same generated scope) hit this
   session in practice and was fixed by a one-off naming convention, not by
   extending the checker. The only safety net left is a `@pytest.mark.slow`
   full-catalogue compile that needs the real toolchain and doesn't run in
   the default test loop.
3. **Per-device complication gating is not just unwired, the wiring wouldn't
   work as sketched.** `catalog.Source.requires` + `Device.has_symbol` is the
   mechanism `docs/limitations.md` already points at, but `has_symbol` only
   indexes *function* symbols scraped from `<functionEntry>` tags in
   `api.debug.xml` — `COMPLICATION_TYPE_*` constants don't appear there at
   all (verified: zero matches for `COMPLICATION_TYPE_BATTERY`, the most
   universal one, in `fenix8solar47mm.api.debug.xml`). The data that *would*
   answer this — `Device.api_level`, already computed from `compiler.json` —
   exists and is currently used for exactly one thing: a column in `wfb
   devices`'s printout.
4. **The catalogue is now half hand-written, half generated, and the seam is
   sound** — verified this is not a real problem, see "Reviewed and found
   sound" below. What *is* worth a second look is that 42 of the 51 `Reader`
   entries now exist to serve exactly one `Source` each, which is a different
   shape than the abstraction was built for. Not broken; worth a naming/shape
   reconsideration.
5. **Documentation drift — caught mid-review, and worth noting *why* it
   doesn't make the findings list.** Earlier in this review `docs/limitations.md`
   and `docs/format.md` still described the deleted TTL/tier mechanism by name
   (`WfbCache.mc`, the old `body_battery.current`-style paths) — a real,
   verified instance of exactly the drift CLAUDE.md's "Documentation
   discipline" section warns against. By the time this document was finished,
   a parallel session (Agent D, editing `docs/**` concurrently) had already
   corrected both files — re-checked, and the relevant paragraphs now
   correctly describe the pull-based, tier-free design. Left in as a footnote
   rather than a numbered finding for that reason: it's evidence the parallel
   split worked, not an open problem. Worth a `grep -rn "WfbCache\|Tier\.SLOW\|ttl_seconds" docs/`
   sanity pass after all three agents land, in case something else was missed.

---

## Findings

### High

#### F1 — `on_hold:` without a `carousel` compiles with a real warning

> **FIXED** in `c095538`. The `_view` field is now declared and assigned only
> when the design has a carousel (`has_carousel` in `emit_delegate`). The
> constructor *parameter* stays unconditional, because an unused parameter
> provably does **not** warn — built both ways to find out — so one delegate
> shape and one `new ...Delegate(view)` call site still serve every design,
> which is what the field's own docstring argued for.
>
> The test gap this finding blames mattered more than the fix.
> `test_a_plain_hold_design_compiles_without_warnings` (slow) now builds a
> plain `on_hold:` design through real `monkeyc` and asserts the build is
> **warning-free**, not merely successful — `wfb/build.py` already turns each
> `WARNING:` line into a bag diagnostic, so that assertion reads the
> compiler's own output rather than a proxy. A fast test pins the field to
> carousel designs, since the fast suite is the default loop. Both were
> confirmed red against the unfixed emitter first.

**What:** `wfb/emit/monkeyc.py:241` unconditionally declares
`private var _view as <Face>View;` on the generated delegate, and line 245
unconditionally assigns it in `initialize`. The *only* code that ever reads
`_view` is `_emit_carousel_zones` (`wfb/emit/monkeyc.py:293,296,303`) — the
plain `on_hold:` branch in `emit_delegate` (lines ~268–274) reads only
`clickEvent` and `Layout` constants. A design with `on_hold:` on an ordinary
element and no `carousel` anywhere gets a delegate that stores `_view` and
never reads it.

**Verified, not assumed:** built a minimal design
(`format: 1`, one `shape`, one `text` with `on_hold: auto` resolving to
`body_battery`, no carousel) through the real toolchain:

```
warning[monkeyc]: .../ReviewTestDelegate.mc:20: Member variable '_view' is not used.
```

then rebuilt `examples/carousel/face.yaml` the same way — clean, no warning,
because there `_view` genuinely is read. `grep -rn "on_hold" examples/*/face.yaml`
returns nothing, so no example currently exercises the broken combination.

**Why it matters here specifically:** this project's own history (CLAUDE.md
§6) is full of sessions that chased down and eliminated exactly this class of
build noise (`-O 3z` vs `-O z`, the empty `<iq:languages/>` cost, launcher-icon
size warnings) on the theory that a generator has no excuse for output a human
wouldn't have written. A guaranteed warning on a whole documented feature
(interactivity without a carousel) is the same class of thing, just not yet
caught.

**Test gap, also verified:** every test that exercises `on_hold:`
(`tests/test_semantics.py`, `tests/test_lint.py`) calls `wfb.emit.generate()`
directly and inspects the generated text — none of them invoke `monkeyc`. The
only `@pytest.mark.slow` tests that do invoke `monkeyc`
(`tests/test_catalog.py::test_every_catalog_source_compiles`, the carousel/
dashboard example builds) either bind no `on_hold:` at all or bind one
alongside a carousel. `on_hold:` on a plain element has apparently never been
compiled with the real toolchain in this repo's test suite.

**Size:** contained fix — gate the field declaration and assignment on
`bool(monkeyc.carousels(face))` (already computed at line 179), or on whatever
condition decides a carousel step-method needs the view. The delegate's own
docstring ("Held even by a face with no carousel... an unused field costs
nothing measurable") is about code size, not about the compiler warning it
also produces — worth correcting once this is fixed either way.

**Category:** pre-existing (introduced when the delegate started holding the
view, in the carousel session before this one), not caused by this session's
diff. Newly verified and previously unlisted.

---

### Medium-High

#### F2 — the symbol-collision checker doesn't see the class of bug that just hit it

> **FIXED** in `7aebde6`, though not in the place this finding's own "Size"
> note left open. `tests/test_catalog.py::test_reader_and_value_locals_never_collide`
> builds an identifier→origins registry over every `Reader.name`, every
> `local_name(path)`, the `...Obj` intermediate form, and the fixed locals the
> emitter itself writes into that scope — found by reading
> `wfb/emit/monkeyc.py` rather than guessed (`dc`, `font`, `text`, `fraction`,
> `filled`, `item`, `x`, `valueFont`, `glyphFont`). A collision fails with both
> origins named. It runs in the **fast** loop, which is the whole point: the
> only previous net was the `slow` full-catalogue build.
>
> Verified red against the pre-fix naming, listing all 42 collisions, then
> green. `Builder._check_symbol_collision` was deliberately left untouched —
> it is element-id-scoped by construction and these collisions are
> catalogue-scoped, so extending it would have meant importing catalogue
> internals into a function whose whole job is comparing two derivations of
> one id.
>
> The check treats the catalogue as one flat namespace rather than tracking
> which readers and sources actually co-occur in a scope: which of them a
> future design will bind together cannot be known here, so it is deliberately
> more conservative than the bug requires.

**What:** `wfb/ir.py:546` (`Builder._check_symbol_collision`) exists, per its
own docstring, to catch "two distinct ids [that] derive the same Monkey C
symbol" before the emitter discovers it "four `Redefinition of ...` errors
deep." It checks exactly two derived forms per element id —
`element_const_prefix` and `element_method_name` (`wfb/ir.py:558`) — against
each other, across ids.

It says nothing about `catalog.Reader.name` or `wfb.ir.local_name(path)`,
which are the two symbol families that actually collided in this session
(per REVIEW-SEED.md item 1, and confirmed by the fix that's now in the code):
a `complication.*` reader's parameter name and its matching source's value
local both wanted `complicationBodyBattery`. `wfb/catalog.py:188-209`
(`_complication_local_name`) fixes this by suffixing every complication
reader's local with `Complication` — a real, working fix for the one family
that collided, with a docstring that says outright "the general gap is open"
would be accurate, though it doesn't say that; it says "tests/test_catalog.py
pins this apart, so the collision cannot come back silently" (line 203).

**That claim is optimistic.** I looked for a test that would catch a
*regression* of this specific collision (e.g. asserting
`_complication_local_name(name) != local_name(f"complication.{name}")` for
all 42 names, or diffing `READERS` locals against `CATALOG` locals globally)
and found none — `tests/test_catalog.py` has no such test by name (I checked
every `def test_` in the file). What *would* catch a reintroduced collision is
`tests/test_catalog.py:408`'s `test_every_catalog_source_compiles`, which
binds every catalogue entry and requires `BUILD SUCCESSFUL` — but it's
`@pytest.mark.slow`, needs the real SDK, and is excluded by
`pytest -m "not slow"` (CLAUDE.md's own stated test command, and this repo's
default loop). `tests/test_complications_codegen.py`'s tests assert exact
generated strings for two hand-picked designs (`BODY_BATTERY`,
`TWO_COMPLICATIONS`) — real coverage for those two, not a general check.

**Why it matters:** the collision surface is bigger than one naming
convention protects against. Symbols sharing one generated element-method
scope, derived independently, with nothing checking them against each other,
now include: `catalog.Reader.name` (51 of them), `wfb.ir.local_name(path)`
(88 catalogue paths), the `{local_name(path)}Obj` intermediate-object suffix
(`wfb/emit/monkeyc.py:1410`), and fixed emitter-chosen names like `"text"`,
`"complication"`. A future catalogue addition — hand-written or generated —
that happens to collide with any of these would be caught only by the slow
full-catalogue build, not by the fast suite, not by a targeted unit test, and
not by `Builder._check_symbol_collision` (which only ever looks at element
ids).

**Size:** contained. A single fast test (or a build-time assertion inside
`wfb/catalog.py` at import time) that computes every `Reader.name` and every
`local_name(path)` and asserts they're pairwise distinct would close this for
the catalogue side; it wouldn't need the toolchain, so it could run in the
default loop rather than only in the slow one.

---

#### F3 — per-device complication gating: the natural fix (`requires` + `has_symbol`) doesn't actually work

> **FIXED** in `1ba1077`, using the mechanism this finding identified rather
> than the one `docs/limitations.md` had been recommending.
> `wfb/lint.py::check_complication_availability` (code `complication-gated`)
> compares `complications.TYPES[name].since` against `Device.api_level` and
> warns, suppressibly. It covers **both** directions with different message
> text, because the consequences differ: a `complication.*` binding is a
> reading that never arrives, an `on_hold:`/`launch:` is a gesture that does
> nothing. Each message names the device, the type, the level required and the
> level available, so the author can decide "fine, it degrades" or "drop it"
> without leaving the diagnostic.
>
> A warning rather than an error, deliberately: the runtime already degrades
> correctly on its own, so a design knowingly accepting a blank field on one
> target should not be forced to drop a source that works on the other two.
> It goes through `_emit`, and the suppression was exercised rather than
> assumed — this repo has shipped checks advertised as suppressible that were
> not, having called `bag.warning` directly.
>
> `Device.api_level`'s one call site (a column in `wfb devices`) is now two.
> `_version_key` became public `version_key` for the comparison.
>
> **The `requires` gap this finding sits inside is still open** for ordinary
> data sources, and the two checks answer genuinely different questions —
> "old enough for this firmware" is not "this symbol exists here", and
> constraint 6's `onTap` case is the standing proof they can disagree. Whoever
> writes the ordinary-source check should expect a separate mechanism, not an
> extension of this one. `docs/limitations.md` now says so where it used to
> point at the dead end.

**What:** `catalog.Source.requires` (`wfb/catalog.py:242`, doc comment: "the
target device") is set on exactly one source
(`device.do_not_disturb`, `wfb/catalog.py:356`) and read by nothing in
`wfb/ir.py`, `wfb/lint.py`, or `wfb/emit/*` — confirmed by grep, zero hits for
`.requires` outside its own definition and that one call site. This is
already recorded in `docs/limitations.md` §3 as a known gap, and REVIEW-SEED
item 2 correctly flags that this session's 42 new complication sources
multiply the surface it should be guarding.

**What I checked beyond the seed note:** whether the obvious fix — wire
`requires` through `Device.has_symbol`, which is real and used by
`check_hold_targets` (`wfb/lint.py:536`) — would actually answer the
question. It doesn't. `Device.has_symbol` (`wfb/devices.py:208`) matches
against `functions`, built by scraping `<functionEntry parent=".."
name="..">` tags out of the device's `api.debug.xml`
(`wfb/devices.py` `_symbols`, ~176-190). `COMPLICATION_TYPE_*` are constants,
not functions, and don't appear in that scrape at all:

```
$ grep -o '.\{40\}COMPLICATION_TYPE_BATTERY.\{40\}' \
    ~/.Garmin/ConnectIQ/Devices/fenix8solar47mm/fenix8solar47mm.api.debug.xml
(no output)
```

...for `COMPLICATION_TYPE_BATTERY`, the one type every target is documented to
support unconditionally. Confirmed the same absence for
`COMPLICATION_TYPE_SLEEP_SCORE` and `COMPLICATION_TYPE_BODY_BATTERY` on both
`fenix8solar47mm` and `fr955`. So `has_symbol` cannot answer "does this device
support this complication type" no matter how it's wired up — the debug XML
this project already parses simply doesn't carry that information.

**What actually would work, and is sitting unused:** `Device.api_level`
(`wfb/devices.py:154`) computes the device's own ConnectIQ ceiling from
`compiler.json`'s `connectIQVersion` — the exact mechanism CLAUDE.md's own
Phase 3 notes describe using by hand to confirm `fr955` tops out at 5.2.0,
below `sleep_score`'s 6.0.2 requirement. I confirmed it's live and correct:

```
fenix8solar47mm 6.0.2
fenix8solar51mm 6.0.2
fr955            5.2.0
```

...which matches CLAUDE.md's numbers exactly. But `Device.api_level` has
exactly one call site in the whole compiler: `wfb/cli.py:595`, formatting a
column in `wfb devices`'s printout. It never touches `wfb/lint.py` or
`wfb/ir.py`. Of the 42 complication types, three have a `since` above the
4.2.0 floor (`wheelchair_pushes` 4.2.3, `last_golf_round_score` 5.0.0,
`sleep_score` 6.0.2 — `wfb/complications.py:200-206`), so today's actual blast
radius is one type on one device (`sleep_score` on `fr955`) — but the
mechanism to catch this, or the next one the SDK adds above some target's
ceiling, doesn't exist, and the two `on_hold`-adjacent lint checks that do
exist don't cover it either: `check_hold_targets` (`wfb/lint.py:536`) checks
only whether the device has `WatchFaceDelegate.onPress` at all, not whether a
specific complication type is real on it.

**Size:** contained, once framed this way. A version-string comparison
(`complications.TYPES[name].since` vs. `device.api_level`, both already
plain `"X.Y.Z"` strings, and `wfb/devices.py` already has a private
`_version_key` sorter to reuse or expose) is a small addition — a lint check
in the same shape as `check_hold_targets`, suppressible the same way. The
work is mostly deciding where it plugs in (a `complication.*` binding, and
separately `on_hold:`/`launch:` naming a gated type), not building new
infrastructure.

---

### Medium

#### F4 — `Reader` now means two different things, and 82% of instances are the smaller one

> **FIXED** in `7aebde6`, documentation only, exactly as this finding
> recommended. `Reader`'s class docstring now names both shapes — the original
> shared accessor several sources read fields off (9 of 51), and the
> single-use complication wrapper whose `call` is the whole read (42 of 51) —
> with `complication_type` as the discriminator, and states why the 42 are
> generated from a loop despite sharing nothing: catalogue drift is the
> failure this project fights. No structural change, no new field; generated
> output is byte-identical.

**What:** `catalog.Reader` (`wfb/catalog.py:97`) was designed, per its own
docstring, for "fetching `ActivityMonitor.getInfo()` once per frame and
reading three fields off it" — sharing one API call across several `Source`
entries. Checked the actual shape post-change:

```
READERS entries:        51
complication.* readers: 42  (one per complications.TYPES entry, via the loop at wfb/catalog.py:216-226)
CATALOG entries:        88
```

42 of 51 readers (82%) exist to serve exactly one `Source` each — a
`complication.*` reader's `call` is a whole
`WfbComplications.valueOf(new Complications.Id(Complications.<CONSTANT>))`
expression, generated per-type rather than a shared accessor multiple sources
read fields off. `ReadPlan`'s hoisting (`wfb/emit/monkeyc.py:1173` on) still
works correctly for this shape — verified via the real build above, one `var
bodyBatteryComplication = WfbComplications.valueOf(...)` line, one dependent
value local — but the sharing benefit the abstraction exists for (one call,
many fields) never applies to any of the 42.

**This is not broken.** It costs nothing measurable (verified: a
one-complication face builds at 1,362 B against the 128 KB budget, in line
with every other single-binding face this project has measured), and
generating the 42 from a loop rather than hand-copying them is exactly right
per the project's own stated discipline against catalogue drift.

**Why it's worth a second look anyway:** "Reader" as a name and a mental model
now covers both "a shared, reusable API call" and "a single-use wrapper that
exists only so `ReadPlan`'s declare/guard/parameter pipeline has something to
key off of." A reader working on this catalogue six months from now, seeing
`READERS` and reading the class docstring, would reasonably expect sharing
that doesn't exist for 82% of the table. Worth naming the distinction
explicitly (a subtype, a flag, or just an updated docstring) rather than
letting the two shapes look identical.

**Size:** documentation/naming, or a small structural split if the two shapes
diverge further later — not urgent, no behavioural risk today.

---

*(F5 was a documentation-drift finding — `docs/limitations.md` and
`docs/format.md` still described the deleted `WfbCache.mc`/tier mechanism and
the old `body_battery.current`-style paths when this review started. A
parallel agent corrected both files before this document was finished; see
the summary's item 5 footnote rather than a separate write-up here, since
re-checking it turned up nothing left to report.)*

---

### Low / nitpicks

#### F6 — `on_hold:`'s schema description is hand-duplicated across 7 element-type branches

`schema/wfb-face-1.schema.json` defines `on_hold` inline, with a full
description string, once per element-type subschema (`group`, `shape`,
`text`, `progress`, `icon`, `carousel`, and the icon/glyph variant) — 7
occurrences, confirmed byte-identical after this session's edit
(`grep -c '"on_hold"'` → 7, all 7 description strings equal). The schema
already has a `$defs` section and uses `$ref` for other fields shared across
every element (`identifier`, `position`, `modes`, `lint` — see
`schema/wfb-face-1.schema.json:64` on), so `on_hold` is an outlier: any future
wording change needs 7 synchronized hand-edits, with nothing checking they
stay in sync. This session's edit *did* keep all 7 identical — this is a
"the pattern is a hazard," not "this edit made a mistake," note.

**Size:** one-line-ish — extract to a `$defs/onHold` and `$ref` it, same
pattern as `modes`/`lint`.

#### F7 — `_features()` only ever adds one feature name, from two independent branches

`wfb/emit/project.py:143-160`: `features: set[str] = set()` gets `"complications"`
added from two different conditions (a bound complication reader; a design
that launches a glance) — correct today because `set.add` is idempotent and
both really do mean "need 4.2.0 for `Toybox.Complications`," but the shape
(a `set[str]` of feature names, `FEATURE_API_LEVELS` keyed by name in
`wfb/emit/manifest.py`) reads like it's built to grow, and right now nothing
in the code distinguishes "this design reads a complication value" from
"this design launches one" downstream — both collapse to the same string.
Not a problem yet; flagging so the next feature added here doesn't assume
more granularity exists than does.

#### F8 — `on_hold: auto`'s sentinel is checked before the real-name lookup

`wfb/ir.py:628-629` (`_hold_target`): `if name == HOLD_AUTO: return HOLD_AUTO`
runs before `complications.get(name)`. Harmless today because `"auto"` is not
and has never been one of the 42 `COMPLICATION_TYPE_*` names (confirmed by
reading `wfb/complications.py`'s full table), but there's no test pinning that
invariant, and the order means a hypothetical future type named `auto` would
be silently shadowed by the sentinel rather than reachable. Extremely
unlikely to matter — Garmin's constants are `COMPLICATION_TYPE_*`-derived,
lowercased, and "auto" doesn't fit that pattern — but a one-line test
(`assert "auto" not in complications.TYPES`) would make the assumption
explicit instead of implicit.

---

## Reviewed and found sound

Listing what I checked and did *not* find a problem with, since a
findings-only list gives no signal about coverage:

- **`wfb.complications` / `wfb.catalog` seam.** The "must not import back"
  circular-dependency constraint is real and respected — `complications.py`
  expresses `value_type` as a plain string precisely so it doesn't need to
  import `catalog.Type`, and `catalog.py`'s
  `_COMPLICATION_VALUE_TYPE`/`_COMPLICATION_CAST` dicts are the one place that
  translation happens. Clean, and the reasoning is in both docstrings, not
  just one.
- **The `RENAMED_SOURCES` / `source-renamed` mechanism.** Traced end to end:
  `wfb/catalog.py:568` → `wfb/expr.py`'s new `ExprError.code` →
  `wfb/ir.py:1473-1475`'s `exc.code or "expression"` fallback →
  `tests/test_lint.py`'s `_EXPR_ERROR_CODE_RE`/`_BAG_CALL_FALLBACK_RE`
  extensions to the self-verifying `ALL_CODES` test. This is exactly the
  `on_tap:` → `on_hold:` precedent reused correctly, and the test that keeps
  `lint.ALL_CODES` honest was extended rather than worked around.
- **The `Source.cast` contract.** Deliberately *not* baked into `read_expr`
  (per its own docstring) so the emitter controls where the cast lands
  relative to a ternary guard — verified against real generated output
  (`(bodyBatteryComplication != null) ? bodyBatteryComplication.value as
  Number? : null`) and it typechecks under `-l 3` in a real build. Correct
  division of responsibility between `catalog.py` ("what to read") and
  `emit/monkeyc.py` ("how it sits in the surrounding expression").
- **The pull-vs-subscribe design in `WfbComplications.mc`.** Checked the SDK
  doc text directly (`h2t.py` on `Toybox/Complications.html`): `subscribeToUpdates`
  is documented to return `Lang.Boolean`, "true if subscribed successfully,
  false if given complication could not be subscribed to" — matches the
  module header's claim exactly, and the decision to discard that `false`
  (nothing useful to do differently) is sound given `valueOf` already treats
  "never subscribed" and "declined" identically.
- **`on_hold: auto` resolution** (`wfb/ir.py:646-765`). The three-outcome
  contract (resolve / `hold-auto-unresolved` / `hold-auto-ambiguous`) is
  fully tested (`tests/test_semantics.py:1085-1199`, six scenarios including
  the carousel-item variant and the color/max exclusion), and I verified the
  actual generated output for one case end to end through a real build (see
  F1's test design) — it resolved `body_battery` correctly and compiled to
  `Complications.exitTo(...COMPLICATION_TYPE_BODY_BATTERY)`.
- **`ReadPlan`'s per-mode reader deduplication.** Readers used by multiple
  elements *within one mode* are deduplicated (`_readers_for_mode`,
  `wfb/emit/monkeyc.py:1244-1257`); the lack of dedup *across* modes
  (`active`/`low_power`/`always_on`) that REVIEW-SEED flagged is correct
  behaviour, not a gap — those are genuinely separate generated methods
  (`onUpdate` vs. `onPartialUpdate`) with no shared scope to dedupe into.
- **`check_partial_update_budget`'s honesty about its own limits**
  (`wfb/lint.py:397-450`). It measures clip *area* only (matching the
  documented platform mechanic exactly — `setClip` is charged by region area)
  and says so in its own `confidence="HEURISTIC..."` line, including an
  explicit note pointing an author at `weather.*`/`complication.*` bindings
  as "the expensive case to look at first" now that the hard tier
  restriction is gone. This is ADR 0008's "explicit confidence levels"
  principle actually being followed, not just stated.
- **Fast test suite.** `pytest -m "not slow"` passes clean, exit 0, after
  this change, on top of Agent D's and Agent C's in-flight parallel edits.
- **No dangling references.** Grepped the whole `wfb/` tree for
  `WfbCache`, `Tier`, `ttl_seconds`, `LAUNCHABLE`, `_check_tiers` outside of
  explanatory comments/docstrings that reference the deleted concept by name
  on purpose (e.g., "the same deferred-pass shape `_check_tiers` used to run
  at") — nothing left over that the deletion should have caught and didn't.

---

## Still open

The three recommendations this section originally carried — fix F1, settle
F3's mechanism, close F2 with a fast test — were all done in the session that
followed, so they are replaced here by what is genuinely still outstanding.
None is urgent; all three are small.

1. **F6 — `on_hold:`'s schema description is hand-copied across seven
   element-type branches** in `schema/wfb-face-1.schema.json`. The schema is
   normative, so seven copies of one sentence is seven chances to drift.
   Extract to `$defs/onHold` and `$ref` it, the same pattern `modes`/`lint`
   already use. This is the largest of the three and still small.
2. **F7 — `_features()` collapses two distinct conditions to one string.**
   Reading a complication value and launching one both add `"complications"`,
   which is correct today (both mean "needs 4.2.0 for `Toybox.Complications`")
   but the `set[str]` shape reads as if it carries more granularity than it
   does. Worth knowing before the next feature is added there.
3. **F8 — `on_hold: auto`'s sentinel is checked before the real-name lookup,
   with nothing pinning the assumption.** Harmless: `"auto"` is not one of the
   42 type names and Garmin's constants could not produce it. A one-line
   `assert "auto" not in complications.TYPES` would make the invariant
   explicit rather than implicit, which is this repo's usual standard for
   assumptions of exactly this kind.

## If you read one thing from this review later

Not a finding — a pattern, which is the part most likely to repeat.

**Three of the four fixed findings were invisible to the test suite for the
same structural reason: the tests inspected generated text instead of
compiling it.** F1 shipped a guaranteed compiler warning because every
`on_hold:` test read strings out of `emit.generate()` and none ran `monkeyc`.
F2's collision was caught only by a `slow` build excluded from the default
loop. F3's whole class of problem is invisible at any level short of the
device's own files.

Generated code has two audiences — the human reading a diff, and the compiler
— and this repo's tests were thorough about the first and thin about the
second. The cheap correction is not "more slow tests" but *one* real build per
feature seam, asserting **warning-free** rather than merely successful, since
`wfb/build.py` already surfaces every `monkeyc` warning as a diagnostic. That
is what `test_a_plain_hold_design_compiles_without_warnings` now does for
`on_hold:`, and the same shape would fit any future seam that emits code no
existing example exercises.
