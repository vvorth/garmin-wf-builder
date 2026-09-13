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

- All seven element types: `group`, `shape` (`rectangle`, `rounded_rectangle`,
  `circle`, `line`, `arc`, `ellipse`, `polygon`), `text`, `progress` (`arc`,
  `bar`), `icon`, `graph` (`line`, `area`, `bars`), `complication_slot`.
- `static:` (paint-once buffering, opaque, later given an ordering rule instead
  of a hard error), `antialias:` (font resource + primitive runtime, two
  unrelated mechanisms under one key), `visible:`, `monospace:` + `align:` on
  fonts, and the mapping form of `elements:`.
- The full data-source catalogue, including all 42 `COMPLICATION_TYPE_*`
  values under `complication.*`, and the icon catalogue sourced from a
  vendored Nerd Fonts build (~10,000 glyphs, plus a named subset).
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
   now a build error**, not a silent no-op (`wfb/ir.py`'s
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
11. **Styles that change which widgets are drawn** (digital vs analog), and
    colour schemes re-spelled as Styles entries -- planned, not built:
    `docs/plans/02-style-layouts.md` (with `docs/plans/01-background-color.md`
    for why). Needs analog hands (`type: hand`, no plan yet) for its
    motivating example; nothing in the format rotates by time today.
12. **Complication-slot icons cover 8 of 42 types** and silently draw text
    only for the rest; icon and text share one colour, fixed left/4 px.
    Findings and options (per-choice `icon:` in YAML recommended, plus a lint):
    `docs/plans/03-complication-slot-icons.md`.

**A previously-recorded loose end, now resolved — noted so nobody goes
looking for the problem again:** commit `614d100` added
`examples/big-clock-3/assets/` (eleven fonts) on a commit that briefly fell
out of `main`'s ancestry. Checked while writing this file: those eleven
fonts are back in the tree and tracked at `HEAD` (`git ls-files
examples/big-clock-3/assets/`), so whatever landed them there since — the
`docs/history.md` entry for the original scare predates it — this is no
longer an open issue.
