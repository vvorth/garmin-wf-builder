# examples/

Loaded automatically when working in `examples/`. `README.md` here is the
user-facing index.

**Layout (reorganised 2026-09-20).** Four faces at the top level were built
to be worn -- `dashboard/`, `showcase/`, `analog-custom/` and `enduro/`
(work in progress). `features/` holds one face per format feature, written
as each landed, and `system-fonts/` holds the three calibration faces.
`big-clock-3/` was deleted by the user the same day. Anything that walks the
examples must recurse: `tests/test_templates.py` uses `rglob`, and a flat
`examples/*/face.yaml` glob now sweeps up only the four wearable faces.

Every example lints clean on every target. Where a design deliberately
touches the bezel or accepts a platform gap (no on-device editor, no
Complications), the element says so with `lint: {allow: [...], reason:}`.

## `features/`

Each face's header comment explains what it exercises, and every face here
is named `Feature <thing>` (2026-09-20) so a sideloaded build is obviously a
demo on the watch -- keep that convention for new ones; it also decides the
`.prg` name (`feature-graph-fr955.prg`). `features/slots/` is
the only one using the Data axis (`config: data:`), `features/config/` the
colour axes and `color_scheme:`, `features/styles/` `layouts:` and `config:
style:` (widget-set switching, not just colour).

`features/analog/` is analog hands (plan 04, 2026-09-14) -- two hand sets in
two layouts, an off-centre small-seconds subdial, all four rotatable part
shapes, and a `config.*` hand colour. **Keep it the generated plan-04
design**: `tests/test_hands_*.py` assert against it, and it was restored
from `bf1e4d0` on 2026-09-20 after a session's worth of hand-tuning had
drifted it away from them. That hand-tuned work lives on as the wearable
`analog-custom/`, which the tests do not read.

`features/patterns/` is `type: pattern` (plan 05, 2026-09-14) -- radial and
linear repeats, every part shape including `arc`, `start:`,
`skip:`/`skip_every:`, in and out of `static:`, a per-copy colour (`copy` +
`date.weekday`: `week_dots` lights today, 2026-09-15), `when_absent: hide`
with a per-copy part `visible:` (`test_visibility`, a move-bar row,
2026-09-15), and `shape: text` parts (plan 06, 2026-09-15: `hour_numerals`,
a radial ring, and `weekday_labels`, a linear row).

`features/align/` is `align:`/`vertical_align:` as one placement rule on
every accepting kind (plan 07, 2026-09-15) -- an hour/minute dial with four
diagonal readouts (`complication_slot`, a `group`, a `graph`, `text`), each
aligned to grow away from the centre, covering all four
`align`×`vertical_align` combinations, plus every accepting shape, both
`progress` styles, a static `icon`, and aligned hand/pattern parts.

`features/aod/` (plan 14 slice 0, 2026-09-23; `aod:` slices 1-4, 2026-09-23)
is the first, and so far only, example to add a fourth target, `fenix847mm`
-- the first AMOLED device this project has ever built for. An ordinary
small face (digital time, a date, a battery ring, a bezel) rather than a
format-feature dump: a face-wide `aod: {default: hide, dim: 0.6}` hides
everything but `clock`, a small accent dot and the battery ring -- the
canonical "everything off but the time" AOD shape (plan 14 §3), plus enough
variety to exercise slice 2's restyling and slice 3's dimming: `clock`
overrides `color:`/`format:`/`font:` (its own `color:` override is the
author's final word, left undimmed by `dim: 0.6`), `accent_dot` flips
`filled:` from a solid disc to a thin ring *and* carries no `color:`
override of its own, so its awake blue is dimmed automatically -- the
contrast that makes the face-wide `dim:` visible against `clock`'s explicit
one -- `battery_ring` overrides `color:`/`thickness:` to a thinner, dimmer
arc, and `info` (a `group` wrapping `date_text`) carries an explicit `aod:
hide` that its own child's `aod: show` cannot undo -- deliberately, to
demonstrate the one asymmetry in plan 14 §3, which is why that child needs
`lint: {allow: [aod-unreachable]}`. Every one of those overrides is now
actually read by codegen (slice 2, `docs/lore/codegen.md`), not just
resolved, and `dim:` reaches every colour the AOD frame draws that has no
override, exactly as slice 3 documents. The three MIP verification devices
are unaffected by `aod:` at all -- their generated source is byte-identical
to a build with no `aod:` keys (`tests/test_aod.py`). Slice 4's burn-in
lint (`aod-burn-in`) stays clean on it: a `note` (5.8% lit, 0.5% luminance
at its own sampled worst case), not a warning or an error.

## `system-fonts/`

`text/`, `numbers/` and `numbers-large/` (plan 09 step C, 2026-09-18) are
calibration faces, not design showcases: every `FONT_*` system font this
project measures (`wfb.devices.Device.system_fonts`, plan 09) drawn as a
short literal digits/glyphs sample on a 1px guide line, `align: left` at a
common `px` x so left edges compare across a real simulator screenshot and
`wfb preview`'s own PNG pixel-for-pixel (plan 09 S7, open until the user
sends screenshots). `text/` holds FONT_XTINY..FONT_LARGE plus a
`vertical_align: center` and a `vertical_align: bottom` repeat of
FONT_XTINY, all on one screen. The four `FONT_NUMBER_*` sizes do not fit one
screen together -- even the lighter pair's own line heights leave little
room, and the heaviest pair (FONT_NUMBER_HOT + FONT_NUMBER_THAI_HOT, up to
129px tall) genuinely cannot share a round 260/280px screen with a common
left x at any position (checked by brute-force search over the placement,
not assumed) -- so they split into `numbers/` (MILD, MEDIUM, plus one
`center` demo) and `numbers-large/` (HOT, THAI_HOT, no demo row -- there is
no room for one). All three build warning-free on all three targets; every
row's placement was checked against this project's own round-screen
visible-area math before being written down, not eyeballed. `fr245` is a
target only so its `.cft` fonts can be measured; its smaller screen crops
rows the other targets fit, accepted per element with `lint: {allow}`.

## The wearable four

`showcase/` is the widest single face here: three `layouts:` switched by
Styles -- a quiet classic three-hand `analog` dial (`hands:`, a radial tick
`pattern`, twelve numerals as one `shape: text` pattern part), a
data-rich `digital` dashboard (a monospaced two-tone clock, a weather row
with a dynamic `icon_for:` condition icon, a heart-rate `graph`,
`group`+`on_hold:` icon/value clusters, both `progress` styles, and a
conditional-colour status row), and a vintage `roman` dial (plan 13,
2026-09-21: big roman numerals curved tangent to their own radius with a
device-resident `face:` font and `curve:`, a second `hands:` set --
`vintage` -- with Breguet/moon-style hour and minute hands, the two
shared registers doubling as sub-dials at 2 and 10 o'clock (`skip: [2,
10]` on the numeral ring -- a `complication_slot` can't move, so the
numeral gives way instead), and a mechanical-looking day/date aperture --
a light well with dark text and a 1 px frame, reading as a wheel cut
through the dial rather than a UI chip, since `alphaBlendingSupport` is
false and nothing can be cut out) -- plus
two shared `complication_slot` "registers" (the Data axis, one with
per-choice icon overrides, one `choices: any`), several `color_scheme:`
entries and the `config: style:` entries pairing them with the three
layouts, and several-colour `accent_color`/`data_color` axes. Builds
warning-free on all three targets at 16.8% of the 128 KB budget.

The Phase 2 slice is no longer an example: it is the test fixture
`tests/fixtures/slice/`.

### `examples/dashboard/face.yaml` is the user's own playground

The user edits this file directly between sessions and has said explicitly:
**it is a playground, leave it alone.** Do not proactively "fix" its lint
warnings, geometry or content — even a broken `wfb validate` or a failing
`test_example_is_clean_on_every_target[dashboard]` is not, by itself, a defect
to correct unless asked. Two sessions have now found this test red on `main`
at the start of work; in one, fixing it was explicitly in scope (a review
task) and the geometry fix was welcomed, in the other the user later edited
the file further and the instruction was to leave it be going forward. When in
doubt here, ask rather than assume — this is the one file in the repo where
"the test suite is red" is not automatically a bug report.
