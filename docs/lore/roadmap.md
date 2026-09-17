# Phase 3 roadmap — full text

Moved verbatim out of `CLAUDE.md` on 2026-09-13 (§6) so the file every
session loads stays small. `CLAUDE.md` keeps a short summary and the **same
numbering**, so an older citation such as "CLAUDE.md §6" or "CLAUDE.md
constraint 6" for this material resolves here. Keep adding to this file,
not back into `CLAUDE.md`.

---

### Phase 3 roadmap

`docs/limitations.md` §2 ("Not implemented yet") is the **authoritative,
currently-maintained** list of what is missing — read it, do not re-derive this
from memory or from `docs/history.md`'s session log. This checklist is a
turn-one summary of where things stand; if it and `docs/limitations.md`
disagree, `docs/limitations.md` is right and this needs updating.

**Shipped** (each is a session in `docs/history.md`, in dependency order):

- All nine element types: `group`, `shape` (`rectangle`, `rounded_rectangle`,
  `circle`, `line`, `arc`, `ellipse`, `polygon`), `text`, `progress` (`arc`,
  `bar`), `icon`, `graph` (`line`, `area`, `bars`), `complication_slot`,
  `hands` (analog hands, plan 04, 2026-09-14 -- four rotatable primitives
  per hand, rotated on the device by the time, the one exception to "the
  device does no layout arithmetic"), `pattern` (plan 05, 2026-09-14 -- a
  template repeated radially or linearly, transformed on the device per
  copy, the second exception).
- `static:` (paint-once buffering, opaque, later given an ordering rule instead
  of a hard error), `antialias:` (font resource + primitive runtime, two
  unrelated mechanisms under one key), `visible:`, `monospace:` + `align:` on
  fonts, and the mapping form of `elements:`.
- The full data-source catalogue, including all 42 `COMPLICATION_TYPE_*`
  values under `complication.*`, and the icon catalogue sourced from a
  Nerd Fonts build (~10,000 glyphs, plus a named subset), downloaded by setup.
- Interactivity: `on_hold:` on every element (touch-and-hold only — see
  constraint 6c; there is no tap on a live face), `on_hold: auto` resolving a
  launch target from the element's own bound value, and
  `Complications.exitTo`.
- Configuration (ADR 0006), **all four native axes**: `accent_color` and
  `data_color` (direct colour axes), a Styles axis carrying `color_scheme:`
  (several colours moving together — Styles is the only axis Garmin gives no
  meaning to, so it is the only one that can), and the Data axis as
  `complication_slot` elements the wearer re-points on the watch, including
  the native editor's animated highlight (`AppBase.onStart`,
  `WatchFaceDelegate.onTap`+`getComplicationDrawable` — `onTap` fires **only**
  in config mode, which is the one place it is genuinely usable).
- The refresh-tier concept (ADR 0005 §5) shipped and was then **deleted
  outright** on the user's instruction: every source, `weather.*` and
  `complication.*` included, is now a plain per-frame pull read, and may be
  bound from `low_power`/`always_on` elements (previously a hard,
  unsuppressible error). `WfbCache.mc` and `catalog.Tier` no longer exist.

**Built, then removed outright** — read `docs/history.md` before assuming
either still exists:

- **`type: carousel`** (a row of complications the wearer cycles between,
  hold-left/hold-right/hold-centre by geometry) shipped and was then
  **deleted entirely on the user's decision** — no shim, no
  `carousel-removed` error, no schema remnant. Naming it now gets the
  ordinary unknown-element-type error. `runtime-lib/WfbCarousel.mc` and
  `examples/carousel/` are gone.
- **`on_tap:`** was renamed to `on_hold:` when research showed
  `WatchFaceDelegate.onTap` never fires on a live face; the rename shim (the
  friendly "this key is now called X" error) has since been **deleted
  outright** too — the old spelling is now an ordinary unknown-key error.
- **A font's `size:` bare-number + `scale:` spelling** was deleted outright in
  favour of `Length` (`%r`/`px`) always. `scale:` is not a recognised key.
- **`icon:` no longer accepts a pasted raw character** — only a catalogue name
  or `glyph: "U+XXXX"`, because a pasted glyph is invisible in most editors
  and silently becomes an empty string when lost in a copy (the same hazard
  `wfb/icon_catalog.py`'s own docstring warns its authors about).

**Still not implemented** (see `docs/limitations.md` §2 for the full table
and the ADR each is specified in):

1. **`image` elements** and **the `raw` escape hatch** (ADR 0007) — both give
   a friendly "not implemented yet" error rather than an unknown-key error.
2. **Per-device `overrides`** — parsed and validated, but **writing one is
   now a build error**, not a silent no-op (`wfb/ir/`'s
   `_check_overrides`). This is a correction, not the original plan: a
   design naming a device that does not exist, or keys no element has, used
   to pass `wfb validate` with no diagnostic at all.
3. **`segments` and `scale` progress styles** (only `arc`/`bar` exist).
4. **Automatic unit conversion** (`units: auto`/`metric`/`statute`) — ADR
   0005 §4 states this as framework-owned; no code exists. Authors convert
   by hand (`examples/dashboard/face.yaml`'s `activity.distance / 100000.0`).
5. **Phone-side settings** (`settings.xml`/`properties.xml`) — the only
   mechanism that would give `fr955` any on-device configuration at all.
   **Started and deliberately frozen, incomplete, on branch
   `wip/phone-settings`** (roughly 1,000 lines across `wfb/ir.py`,
   `wfb/emit/{monkeyc,resources,project,manifest}.py`, `wfb/layout.py`,
   `wfb/lint.py` and the schema). It was cut off by a rate limit partway
   through and the user chose to freeze rather than finish: **treat none of
   it as working** — nothing was driven red, no real `monkeyc` build was run
   against it. `backup/pre-integrate` is a second safety pointer at the
   pre-rebase tip. Do not resume it without checking with the user first.
6. **Catalogue generation from the SDK** (ADR 0005 §1) — hand-written today;
   a drift here would silently mis-declare permissions.
7. **`catalog.Source.requires`** is set (on a handful of sources) and read by
   **nothing** — `wfb/lint.py`'s `check_complication_availability` solves the
   adjacent problem (API-level gating for `complication.*`) by a different
   mechanism (`ComplicationType.since` vs. `Device.api_level`), not by
   reading `requires`. ADR 0008's check 2 ("unsupported API for a targeted
   device") is therefore only partly built.
8. **The GUI** (ADR 0002), deliberately last. Two measured reasons it still
   is not right — unit round-tripping (a drag produces pixels; the format's
   values are proportional and device-dependent) and schema churn (Phase 3
   grew the element vocabulary from 6 to 7, plus config/overrides/
   interactivity) — are in `docs/history.md`'s authoring-ergonomics session.
   **If it is ever built, build it as a thin client over `wfb/preview.py`** —
   an HTML canvas reimplementation would be a second renderer and forfeit
   ADR 0004's anti-drift guarantee.
9. **`mypy --strict` in CI** (ADR 0001's stated mitigation for Python's lack
   of compile-time exhaustiveness over IR node types) — there is no CI
   configuration in the repo at all, and `mypy` is not even a dev dependency.
10. **`wfb install`, `package`, `migrate`** — named in the original brief,
    not built.
11. **Superseded — built 2026-09-13** (plan 02, all three phases; ADR
    0006 §1 fifth amendment): `layouts:` (form A only --
    a container, no element-level membership key) and `config: style:`
    (`config: colors:` removed outright, no shim) now both ship, colours and
    widget-set switching alike, over the same Styles axis. `examples/styles/
    face.yaml` is the worked example -- two digital layouts, since analog
    hands (`type: hand`) still do not exist and were never a blocker: the
    mechanism does not need them, only the originally-imagined motivating
    example did. *Original text, describing the pre-build state, kept
    below:*
    ~~Styles that change which widgets are drawn~~ (digital vs analog), and
    colour schemes re-spelled as Styles entries -- planned, not built:
    plan 02 (with plan 01 for why). Needs analog hands (`type: hand`, no
    plan yet) for its motivating example; nothing in the format rotates by time today.

    **Correction (2026-09-14, plan 04): analog hands have since shipped.**
    Both mentions of "`type: hand`... still do not exist" above are now
    stale -- see item 13 below. `examples/analog/face.yaml` is the
    motivating example plan 02 imagined but did not need: two hand sets,
    switched by Styles the same way `examples/styles/face.yaml` switches
    digital widgets.
12. **Built 2026-09-13** (plan 03, §6 is what shipped): complication-slot icons now cover all 42 native types
    (`wfb.icons.COMPLICATION_ICON`), with per-choice `icon:`/`glyph:`/
    `icon: none` overrides in `config: data:`'s `choices:`, and
    `icon_position:` (`left`/`right`/`top`/`bottom`)/`icon_gap:`/
    `icon_color:` on the element. `choices: any` + `icon_size:` is also now
    accepted, and builds once the monkeyc string-hash collision it exposed
    is avoided (`docs/lore/toolchain.md`, `wfb/emit/strhash.py`).
    Unverified on-device (no simulator, no watch).
13. **Built 2026-09-14** (plan 04): analog hands, the eighth element type.
    `hands:` declares named hour/minute/second sets of up to 16 primitives
    each (`polygon`/`rectangle`/`line`/`circle` -- the four `Dc` calls a
    vertex can rotate through), drawn pointing at 12 o'clock with the axis
    as the frame's origin; `type: hands` places a set on screen at an
    author-chosen (possibly off-centre) axis, switching with Styles through
    `layouts:` exactly like plan 02's widgets do, with no new mechanism.
    The device rotates the resolved geometry by the time every frame -- the
    one exception to "the device does no layout arithmetic" (ADR 0004,
    amended) -- through the new `runtime-lib/WfbHands.mc` barrel.
    `seconds: awake` (the default) hides the second hand while asleep,
    sharing the `_sleeping` field `always_on` already introduced (ADR 0006
    §5, amended); `seconds: always` (a second hand while asleep) is not
    implemented (`docs/limitations.md` §2). `examples/analog/face.yaml` is
    the worked example. Unverified on-device (no simulator, no watch): what
    any of it looks like, and whether the second hand actually vanishes on
    the first sleeping frame.
14. **Built 2026-09-14** (plan 05): patterns, the ninth element type.
    `type: pattern` repeats a template of 1–16 parts -- the hand-part
    vocabulary plus an `arc` centred on the origin -- either turned about
    `at:` (`pattern: radial`: `count`, `step` defaulting to 360°/count,
    `start`) or stepped along a whole-pixel `{dx, dy}` (`pattern:
    linear`), with `skip:`/`skip_every:` to leave copies out. The watch
    loops over the copies and transforms the resolved template, because
    baking them measured about 30x the memory
    (`docs/research/probes/pattern-cost/`; ADR 0004 §7). Hands' rotate
    helpers moved into the shared `runtime-lib/WfbGeom.mc`.
    `examples/patterns/face.yaml` is the worked example. Not built: text
    parts (numerals), `pattern: grid`, data-driven colours
    (`docs/limitations.md` §2). Unverified on-device.
    *(Text parts reading `copy` were built 2026-09-15, item 19.)*
15. **Built 2026-09-15:** per-copy pattern colours. A pattern's `color:`
    may read `copy` (the index of the copy being drawn, bound nowhere
    else) and any source that is never absent. A source that can be
    absent is still refused, so item 14's "data-driven colours" is now
    only that half. The new numeric source `date.weekday` (1 = Sunday ..
    7 = Saturday, a `FORMAT_SHORT` reader) made `week_dots` in
    `examples/patterns/face.yaml` show today instead of seven identical
    dots. Unverified on-device.
16. **Built 2026-09-15** (same day, second change): `when_absent: hide` on
    a pattern, and per-copy part `visible:`. Item 15's "still refused"
    absent-able colour is now allowed, given `when_absent: hide` on the
    pattern -- absence then hides the whole pattern (every copy, every
    part), checked once per frame before the loop, because a pattern has
    no placeholder/fallback to substitute. A part also gains its own
    `visible:`, a boolean expression evaluated per copy with `copy` bound
    the same as in a colour; a nullable source read there is likewise
    governed by the pattern's `when_absent: hide`, not by "absent hides
    this one part," which is what the same reading would mean in an
    ordinary element's `visible:` -- a deliberate difference, explained in
    ADR 0005's second 2026-09-15 amendment. `examples/patterns/face.yaml`'s
    `test_visibility` (a 5-copy move-bar row) is the worked example: an
    always-drawn track, plus a lit part gated by
    `visible: "copy <= activity.move_bar_level-1"`. Verified: warning-free
    builds on all three targets (4,321-4,323 B, up from 3,581-3,583 B --
    the `test_visibility` element itself, not per-byte overhead of the new
    feature), and the same for `complication.battery` in place of
    `activity.move_bar_level` (5,232-5,234 B, the `ComplicationSubscriber`
    subscription and `minApiLevel: 4.2.0` included). Unverified on-device.
    **2026-09-15 correction (later the same day, item 17):** that
    `minApiLevel: 4.2.0` is no longer what a build of this design produces —
    the manifest floor stopped moving for complications; see item 17. The
    `ComplicationSubscriber` permission and the measured byte counts are
    otherwise unaffected.
17. **Built 2026-09-15** (same day, third change): per-device API gating,
    closing the TODO left on `examples/dashboard/face.yaml` earlier that day
    (`c0939f9`) when `fenix6` was pulled from `targets:` because it could
    not build. Cause: `manifest.xml`'s `minApiLevel` is one number shared by
    every target device in a build, and it was raised to 4.2.0 whenever a
    design used a complication (a `complication.*` read, a `config: data:`
    slot, or `on_hold:` → `Complications.exitTo`) — locking out any target
    below 4.2.0 even when that target never touched the feature. Fix: the
    floor now always stays at the generator's base level, `3.2.0`
    (`wfb/emit/manifest.py::BASE_API_LEVEL`; `FEATURE_API_LEVELS` and
    `wfb/emit/project.py::_features()` deleted), and every complication
    touch in the one shared generated view/delegate is guarded at runtime
    instead — `Toybox has :Complications` around `onLayout`'s
    subscribe/register loop, every complication-reader pull, `on_hold:`'s
    `exitTo`, and a `config: data:` slot's `Complications.Id` field (built
    in `initialize()`, not as a field initialiser, which runs before any
    guard could matter); `x has :field` for a bare field some target lacks
    (`stressScore` on `fenix6`; `floorsClimbed`, `floorsClimbedGoal`,
    `batteryInDays`, `ambientPressure` on `fr245`). New module
    `wfb/availability.py` is the one place that checks a design's bindings
    against a device's own `api.debug.xml`
    (`Device.has_symbol`/`has_module`/`has_field`, the last two new) and
    aggregates the result over every target in a build
    (`compute_guards` → `Guards`), so a design whose targets all support
    everything it uses still generates byte-identical code. Policy (user
    decision): an unavailable binding reads as absent on that device (the
    element's own `when_absent`), `on_hold:` never fires there, and the
    build **warns** (lint `api-gated`, replacing `complication-gated`) —
    not a build error. `docs/research/probes/api-gating/` is the evidence
    record; ADR 0005's "a target device lacking a binding entirely is
    absence too" amendment and ADR 0006's sixth amendment are the decision
    record. `examples/dashboard/face.yaml` targets `fenix6` again.
    **Open follow-ups:** runtime behaviour on a real pre-4.2.0 device —
    that a `has`-guarded reference to an absent module is harmless at load
    time, and that `has` itself reads `false` there — is the SDK docs'
    idiom, UNVERIFIED (no simulator in this container); a reader *function*
    a device lacks (none exist today) is still a hard build error, because
    the generator can only gate whole modules and bare fields, not one
    function call inside a reader's `call` expression.
18. **Built 2026-09-15** (plan 06, fourth change): `align:`/`vertical_align:`
    on a `group`. `align: left | center | right` and `vertical_align: top |
    center | bottom` say which edge of the group's box sits at `at:`. The
    default is centred, unchanged. Resolved entirely at build time
    (`wfb/layout.py::_group_box`), and only `group` has the keys.
19. **Built 2026-09-15** (plan 06, fifth change): text parts in a pattern,
    closing item 14's "text parts (numerals)". A `shape: text` part has
    `value:` (an expression that may read only `copy`) or `text:`, plus
    `format`/`font`/`align`/`vertical_align`. Its anchor turns or steps
    with the copy and is rounded half up (`WfbGeom.drawTextRotated` on the
    watch, `wfb.layout.pattern_text_anchor` on the host). The glyphs stay
    upright. Every copy's string is rendered at build time for the glyph
    subset, the extent, the `missing-glyph` lint and the preview, so text
    parts that read data are not built (`docs/limitations.md` §2).
    `examples/patterns/face.yaml` has 12 numerals and a weekday-initial
    row, both in one custom font. It builds warning-free on all three
    targets, at 4,933 B (+471 B) on `fenix8solar47mm`. Unverified
    on-device.

**A previously-recorded loose end, now resolved — noted so nobody goes
looking for the problem again:** commit `614d100` added
`examples/big-clock-3/assets/` (eleven fonts) on a commit that briefly fell
out of `main`'s ancestry. Checked while writing this file: those eleven
fonts are back in the tree and tracked at `HEAD` (`git ls-files
examples/big-clock-3/assets/`), so whatever landed them there since — the
`docs/history.md` entry for the original scare predates it — this is no
longer an open issue.
