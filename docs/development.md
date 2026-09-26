# Developing garmin-wf-builder

Setup details, the command list, the shape of the generated code, the
repository layout and the tests. For what the tool does and how to write a
face, start with the [README](../README.md) and the [guide](README.md).

**Targets:** any Garmin watch that can run a watch face (136 of the 164
devices in the Connect IQ reference) and whose device definition is installed.
**Verification devices:** fēnix 8 Solar 47 mm / 51 mm, Forerunner 955 — the
three that are built and measured against here, not the limit of what is
supported.
**Distribution:** personal sideload.

## Start here

| If you want… | Read |
|---|---|
| the feature tour and the author's guide | [`README.md`](../README.md), then [`docs/README.md`](README.md) |
| to take over this project | **`CLAUDE.md`** — full handoff context |
| to write a design | [`docs/guide/`](guide/), and the schema in [`schema/`](../schema/) |
| what the platform will not do | [`docs/limitations.md`](limitations.md) |
| to run it without installing anything | [`docs/container.md`](container.md) |
| the decisions and why | [`docs/adr/README.md`](adr/README.md), then `0001`–`0009` |
| the platform research | [`docs/research/00-summary.md`](research/00-summary.md), then `01`–`05` |

## Setup

Either install locally:

```sh
./tools/setup-env.sh
```

…or use the container, which needs nothing on the host but Docker and your own
copy of the device definitions:

```sh
docker build -t garmin-wf-builder .
docker run --rm -v "$PWD:/work" \
  -v "$HOME/Library/Application Support/Garmin/ConnectIQ/Devices:/devices:ro" \
  -v wfb-keys:/keys \
  garmin-wf-builder build examples/features/graph/face.yaml
```

See [`docs/container.md`](container.md). The local install:

Installs the Connect IQ SDK 9.2.0 (on macOS: finds the SDK Manager's own
install), generates a developer key, installs the device definitions (on macOS:
reads the SDK Manager's in place), copies Garmin's own font files in from
`vendor/fonts/` if present (Linux only, optional — see below), downloads the Nerd Fonts icon font
(`tools/fetch-icon-font.py`, pinned and hash-checked; the font is not committed)
and prefetches the registry's system-font stand-ins the same way
(`tools/fetch-system-fonts.py`; see `docs/lore/toolchain.md`), and creates
`.venv` with the host dependencies.

The SDK downloads freely. **Device definitions cannot be downloaded** —
`api.gcs.garmin.com` returns HTTP 401 and needs a Garmin SSO login that cannot be
completed headlessly. Get them with Garmin's SDK Manager
([Step 1: get the device definitions](guide/getting-started.md#step-1-get-the-device-definitions)). The script
takes them from `vendor/devices/` (gitignored, because they are your own licensed
copy), from `~/Library/Application Support/Garmin/ConnectIQ/Devices`, or from
wherever they already are at `~/.Garmin/ConnectIQ/Devices`.

**Garmin's own font files are the same shape, but optional**: free stand-ins
(`wfb/fonts/registry.json`) work without them. If the SDK Manager install also
has a `Fonts` directory, the script copies it from `vendor/fonts/` (gitignored,
same reasoning as `vendor/devices/`) into `~/.Garmin/ConnectIQ/Fonts`
incrementally. `wfb doctor` reports which root it found (`--fonts DIR` or
`WFB_FONTS` override it); a device's real file there outranks the
registry's stand-in for every build/preview consumer that consults it (plan
09 R1b). See `docs/lore/toolchain.md`.

**Without the Garmin font root, `wfb preview` draws stand-in typefaces for
any face the registry has no exact match for** — not merely "an estimate",
a genuinely different family's letterforms (`wfb.fonts.fallback`'s own
`"substitute"`/`"none"` match levels). `wfb preview` names exactly which
fonts this happened to, once per run, on stderr; `wfb doctor` reports the
same thing as one line next to the root it did or did not find. `--fonts
DIR` on either command points at a root without installing it system-wide
(plan 12 R1/R3). On `wfb preview`, that one root reaches layout measurement
and every lint that depends on it too, not only the pixels drawn (`Device.
fonts_root`, owned by the `DeviceDatabase` the command builds -- plan 18
item 8): a box is always sized from the same file it is then drawn with.

**Platforms.** `setup-env.sh` runs on Linux and macOS (`uname -s`). On Linux
it downloads the Linux SDK and copies devices and fonts into
`~/.Garmin/ConnectIQ`. On macOS it never downloads or copies either: the SDK
is the SDK Manager's own
`~/Library/Application Support/Garmin/ConnectIQ/Sdks/connectiq-sdk-mac-9.2.0-*`,
and devices and fonts are read in place from that tree, which `monkeyc` and
`wfb` both look in already; a device in `vendor/devices/` that the SDK Manager
lacks is reported, not copied. It appends `CIQ_SDK`/`PATH` to
`/etc/sandbox-persistent.sh` on Linux when that file exists and is writable
(the development sandbox); otherwise it prints the two exports, quoted since
the macOS path holds a space, for your shell profile. It checks for `openssl`,
a working `java` (macOS has a `java` stub with no runtime behind it), Python
3.11 or newer (trying `python3`, then `python3.14` down to `python3.11`,
since macOS's own `python3` is older), and on Linux `curl` and `unzip`,
before doing anything; a missing SDK or device folder produces step-by-step
instructions rather than a bare error. The macOS branch was checked in the
Linux sandbox with a faked `uname` and a fake `Library` tree, under bash 5.
It is written for macOS's bash 3.2 (no empty-array expansion under `set -u`)
but has not run under 3.2 there yet. The Docker image works on macOS too,
tested with OrbStack. Windows is untested.

Running `wfb` and the full command list moved to
[`docs/guide/preview-and-cli.md`](guide/preview-and-cli.md).

## What the generated code looks like

```monkeyc
//! `step_ring` -- an arc progress indicator.
//!
//! Bound to `activity.steps` and `activity.step_goal`.
//! When the value is absent: hide.
//! Drawn in: active.
private function drawStepRing(dc as Dc, activity as ActivityMonitor.Info) as Void {
    // the values this element is bound to
    var activitySteps = activity.steps;
    var activityStepGoal = activity.stepGoal;

    // when_absent: hide
    if (activitySteps == null || activityStepGoal == null) {
        return;
    }

    // the unfilled track
    dc.setColor(Palette.TRACK, Graphics.COLOR_TRANSPARENT);
    WfbArc.drawSpan(dc, Layout.STEP_RING_CX, Layout.STEP_RING_CY, Layout.STEP_RING_RADIUS,
                    Layout.STEP_RING_THICKNESS, Layout.STEP_RING_START, Layout.STEP_RING_SWEEP);

    // the filled portion
    dc.setColor(Palette.ACCENT, Graphics.COLOR_TRANSPARENT);
    WfbArc.drawProgress(dc, Layout.STEP_RING_CX, Layout.STEP_RING_CY, Layout.STEP_RING_RADIUS,
                        Layout.STEP_RING_THICKNESS, Layout.STEP_RING_START, Layout.STEP_RING_SWEEP,
                        WfbMath.percent(activitySteps, activityStepGoal) / 100.0);
}
```

Readable output is a requirement, not a nicety: it is what gets debugged when
something misbehaves on the wrist, and it is the substrate the escape hatch will
drop into. Symbol names derive from element ids, every block cites its YAML
element, layout constants are named rather than inlined, and every nullable read
is guarded with the `when_absent:` policy that produced the guard.

## Layout

```
wfb/                  the compiler
  yamlsrc.py            YAML loading that keeps source spans
  validate.py           JSON Schema, reported against the author's lines
  catalog.py            the typed data-source catalogue
  expr.py               the expression language -> Monkey C
  ir/                   the IR (model.py, naming.py) and the semantic pass (builder.py)
  kinds/                one module per element kind: its own build, resolve, preview,
                        emit and layout-constant code, an ElementKind subclass each
  layout.py             relative units -> absolute pixels, per device
  lint.py               ADR 0008's checks, each with a stated confidence
  fonts/                TrueType -> BMFont sheet, subsetted to the used glyphs
  fonts/registry.json   device font name -> free-font-key mapping (docs/research/10-system-fonts.md)
  fonts/fetch_system.py stdlib-only fetch/cache/Garmin-font-root logic driven by registry.json
  icons.py              icon sizing and resolution over the Nerd Fonts icon font
  icon_catalog.py       the icon name -> codepoint table, data only
  assets/icons/         the "Symbols Only" icon font, downloaded by tools/fetch-icon-font.py
  assets/system-fonts/  registry.json's free stand-ins for Garmin's system fonts,
                        downloaded by tools/fetch-system-fonts.py
  emit/                 Monkey C, resources, manifest, jungle
  preview.py            host-side renderer over the resolved IR
  build.py, cli.py      the pipeline and `wfb`
runtime-lib/          the hand-written support barrel the generated code calls
schema/               the published JSON Schema (a shipped artefact)
examples/             example faces; `examples/README.md` is the index
examples/dashboard/   one of the four faces built to be worn (with
                      showcase/, analog-custom/ and enduro/)
examples/features/    one face per format feature, written as each landed
examples/system-fonts/  the three system-font calibration faces
tests/                ? tests; only the `slow` ones need the Garmin toolchain
tests/fixtures/slice/ the Phase 2 slice: the golden files' source design
tools/                setup, font fetchers, docs-shots.py, snapshot.py (output snapshots),
                      typecheck.py (mypy --strict against its baseline)
docs/                 README.md (hub), guide/ (format reference), limitations, ADRs, research
```

## Element kinds

Each element kind (`group`, `shape`, `text`, `progress`, `icon`, `graph`,
`complication_slot`, `hands`, `pattern`) is one module in `wfb/kinds/`,
holding one subclass of `wfb.kinds.ElementKind` (`TextKind`, `PatternKind`,
...) and an instance of it as the module's `KIND`. A stage never switches on
kind: it asks the registry (`kinds.for_element`, `kinds.for_placed`) and
calls a method. The base class is the interface: every method's signature
and docstring is there, and every method but `build`, `resolve`,
`draw_preview` and `emit_draw` has a default meaning "nothing to do here",
so a kind overrides only where it differs. **Adding a tenth kind** is an IR
class (`wfb/ir/model.py`), a `Placed` class (`wfb/layout.py`), one kind
module, its name in `wfb.kinds._NAMES` and its schema entry;
`tests/test_kinds.py` fails until they agree. "Adding an element kind",
below, walks through one.

**Fonts are one question.** A kind that draws text says what it draws, and
in which font, as a list of `TextRun`s (`ElementKind.text_runs`): the font,
the glyphs a baked sheet must hold, the exact strings the missing-glyph lint
checks, and, for an icon font, how to bake it. Glyph baking, icon-font
baking, `onLayout`'s font loading, the vector-font guards and lint, the
missing-glyph lint and `IconGlyphs.mc` are all derived from those runs in
their own stage, so a new kind that draws text writes one method, not one
per stage. A `pattern` returns one run per `shape: text` part; `part_index`
is how a stage finds the font layout resolved for that part
(`kinds.placed_font`).

Where code goes:

- A function lives in `wfb/kinds/<kind>.py` if and only if only that kind
  uses it. A helper two kinds share (`Builder.build_hand_part`, preview's
  text blitting, `layout.longer`) stays in its stage module.
- A site goes through the registry if adding a kind would force an edit
  there (a ladder over kinds, a per-kind table, a list of kind names); it
  becomes a method whose default is the ladder's fall-through. A site about
  one kind's own feature stays at its call site as an `isinstance` check,
  when no second kind would plausibly need it: collecting every
  `complication_slot`, a `graph`'s series barrel, a curved `text`
  element's rotated ink (`layout._shape_ink`), a `complication_slot`
  emitting its own guards (`view._emit_element_method`). A friendly
  pre-schema message for one kind's common mistake is a `_check_*`
  function in `wfb/validate.py`, beside the others.
- Kind modules import stage modules and call only their public names
  ("Helpers for kind authors", below); an underscored name is private to
  its own module. Stage modules import the `wfb.kinds` package only, never
  a kind submodule, and read the registry only at call time. The registry
  loads lazily, so this cannot form an import cycle.

### Adding an element kind

A worked example: `type: dot`, a filled disc with a `radius:` and a `color:`.
It is the smallest complete kind. It is not part of the format (a new
element type is a format decision), but every step below was built into the
tree on 2026-09-25, and with it `wfb validate`, `wfb preview` (awake and
`--aod`) and a real `monkeyc` build were warning-free on `fenix8solar47mm`,
`fr955` and `fenix847mm`, and the fast suite was unchanged. Nothing else in
the compiler had to change: every stage reached it through the registry.

**1. The schema** (`schema/wfb-face-1.schema.json`). Add a `$defs` entry and
reference it from `$defs.element.oneOf`. `additionalProperties` is `false`
on every element, so an element restates the keys every kind accepts; copy
them from `shapeElement`. `aod:` takes a per-kind `aod<Kind>` definition that
lists which keys an override may restyle; `aodIcon` (colour and `visible:`)
fits a one-colour kind.

```json
"dotElement": {
  "type": "object",
  "required": ["id", "type", "radius"],
  "additionalProperties": false,
  "properties": {
    "id": {"$ref": "#/$defs/identifier"},
    "type": {"const": "dot"},
    "radius": {"$ref": "#/$defs/length"},
    "color": {"$ref": "#/$defs/colorExpression"},
    "at": {"$ref": "#/$defs/position"},
    "modes": {"$ref": "#/$defs/modes"},
    "z": {"$ref": "#/$defs/zOrder"},
    "on_hold": {"$ref": "#/$defs/onHold"},
    "visible": {"$ref": "#/$defs/visible"},
    "static": {"$ref": "#/$defs/staticFlag"},
    "antialias": {"$ref": "#/$defs/antialias"},
    "min_1px": {"$ref": "#/$defs/min_1px"},
    "lint": {"$ref": "#/$defs/lint"},
    "aod": {"$ref": "#/$defs/aodIcon"},
    "overrides": {"$ref": "#/$defs/overrides"}
  }
}
```

`wfb.validate.ELEMENT_TYPES` is read from `element.oneOf`, so the schema's
order is the kind order.

**2. The name** (`wfb/kinds/__init__.py`). Append `"dot"` to `_NAMES`, in the
same position as its `oneOf` entry.

**3. The IR class** (`wfb/ir/model.py`). A dataclass subclass of `Element`
holding what `build` parsed. The shared fields (`id`, `at`, `visible`,
`aod`, ...) are inherited. `_own_roles` lists the element's bound
expressions, which is what reader hoisting, null guards, permissions and
the palette lints read; `Element.color_roles` finds a field named `color`
(or `track_color`, `icon_color`, `outline`) by itself.

```python
@dataclass
class Dot(Element):
    """`type: dot` -- a filled disc."""

    radius: Length | None = None
    color: Expression | None = None

    def _own_roles(self) -> list[tuple[str, Expression]]:
        return [(ROLE_COLOR, self.color)] if self.color else []
```

**4. The `Placed` class** (`wfb/layout.py`). What `resolve` worked out for
one device, in whole pixels. `element`, `box` (what the lints check),
`center` and `depth` are inherited.

```python
@dataclass
class PlacedDot(Placed):
    radius: int = 0
```

**5. The kind module** (`wfb/kinds/dot.py`), the whole of it:

```python
"""`type: dot` -- a filled disc of a given radius."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..ir.model import Dot
from ..layout import PlacedDot
from ..units import Axis, Box
from ..emit.monkeyc.common import const_prefix
from . import ElementKind

if TYPE_CHECKING:
    from ..ir.builder import Builder
    from ..layout import Resolver
    from ..preview import Renderer


class DotKind(ElementKind):
    name = "dot"
    ir_class = Dot
    placed_class = PlacedDot
    antialiased = True  # drawn with a primitive, so `antialias:` applies

    def build(self, b: Builder, node: dict, common: dict, path: tuple) -> Dot:
        return Dot(
            **common,
            radius=b.length(node, "radius"),
            color=b.color_expression(node, "color"),
        )

    def resolve(self, r: Resolver, element: Dot, parent: Box, depth: int) -> PlacedDot:
        cx, cy = r.point(element.at, parent)
        radius = round(r.extent(element.radius, parent, Axis.MINOR, 0,
                                min_1px=element.resolved_min_1px, what="radius"))
        box = Box(cx - radius, cy - radius, 2 * radius, 2 * radius)
        return PlacedDot(element, box.rounded(), (round(cx), round(cy)), depth, radius=radius)

    def circular_extent(self, placed: PlacedDot):
        return (placed.center[0], placed.center[1], placed.radius)

    def draw_preview(self, renderer: Renderer, placed: PlacedDot) -> None:
        element = placed.element
        s = renderer.scale
        (cx, cy), r = placed.center, placed.radius
        renderer.draw.ellipse([(cx - r) * s, (cy - r) * s, (cx + r) * s, (cy + r) * s],
                              fill=renderer.aod_color(element, "color", element.color))

    def emit_draw(self, w, resolved, placed: PlacedDot, value_guards, plan, aod) -> None:
        prefix = const_prefix(placed.id)
        w.line(f"dc.setColor({aod.color(placed.element, 'color')}, Graphics.COLOR_TRANSPARENT);")
        w.line(f"dc.fillCircle(Layout.{prefix}_CX, Layout.{prefix}_CY, Layout.{prefix}_RADIUS);")

    def describe(self, placed: PlacedDot) -> str:
        return "a dot"

    def layout_constants(self, prefix: str, placed: PlacedDot):
        return [
            (f"{prefix}_CX", placed.center[0], ""),
            (f"{prefix}_CY", placed.center[1], ""),
            (f"{prefix}_RADIUS", placed.radius, ""),
        ]


KIND = DotKind()
```

What each part is for:

- `build` turns the schema-valid node into the IR class. `common` already
  holds every shared field; pass it through with `**common`. Report a
  semantic error with `b.bag.error(...)` or `b.require(node, key, why)`.
- `resolve` places the element inside its parent's box for one device.
  `r.point` resolves `at:`; `r.extent` resolves a length along an axis
  (`%r` against the minor radius, `%` against the parent). The `box` is
  what the safe-area, overlap and luminance lints check, so make it cover
  every pixel the element can touch.
- `layout_constants` is the only way a per-device number reaches the
  generated code: the view is shared by every target, so `emit_draw` must
  read `Layout.<PREFIX>_*`, never a pixel literal (a literal that differs
  between targets fails the build as a `shared-source` error).
- `emit_draw` writes the body of the generated `draw<Id>(dc)`. The caller
  has already emitted the element's reads, its `visible:` and null guards
  and its `antialias:`. `aod.color(element, key)` gives the colour code with
  the AOD override and `dim:` applied; for an awake-only build it is the
  plain colour.
- `draw_preview` draws the same thing with Pillow, from the same `Placed`
  fields, at `renderer.scale`. `renderer.aod_color` is `aod.color`'s twin.

The rest of the interface you can ignore until the kind needs it; each
default means "nothing to do here":

| Method or attribute | Override when the kind... |
|---|---|
| `antialiased` | draws primitives (`drawCircle`, `fillPolygon`, ...), so `antialias:` becomes `Dc.setAntiAlias`; a glyph kind anti-aliases in its font instead |
| `circular_extent` | is round: the safe-area lint then checks the disc, not the box corners |
| `text_runs` | draws text or an icon glyph in a font it names: see "Fonts are one question" above |
| `static_forbidden` | can never be `static:` (its picture is a series, the clock or a wearer's pick) |
| `aod_refusal` | accepts an `aod:` key in the schema it cannot honour in some configuration |
| `extra_symbols` | emits Monkey C symbols beyond its own `draw<Id>` |
| `contrast_subjects` | draws more than one ink the contrast lint should judge separately (`hands`, `pattern`) |

The contrast lint treats every kind but `shape` as glyph ink
(`Element.color_roles`), which forbids an exact backdrop match; a kind
drawn as a solid primitive may want the `shape` rule instead.

After the code, a kind is a format change like any other: the guide
chapter and the schema together (root `CLAUDE.md` §7), a face in
`examples/features/`, and tests that drive its diagnostics red.

### Helpers for kind authors

Each stage hands a kind its own public helpers. Their signatures and
docstrings are in the code; the class docstrings of `Builder`, `Resolver`
and `Renderer` index them the same way. A name with a leading
underscore is private to its module, so a kind never calls one.

**`build`: the `Builder` (`b`, `wfb/ir/builder.py`).** A helper that can
fail reports its own error and returns `None` or an empty default.
`b.doc.span(node, key)` locates a key for a diagnostic of the kind's own,
and `b.bag` takes it.

| Helpers | For |
|---|---|
| `expression`, `color_expression`, `length`, `angle`, `position`, `size`, `alignment`, `baked_size_length` | reading one key of the node |
| `require` | a key the schema cannot require by itself |
| `check_absence`, `check_other_absence`, `check_reachable_substitute`, `nullable_sources` | `when_absent:` for the value and for every other nullable binding |
| `check_format`, `check_format_spec`, `check_format_not_on_literal` | `format:` |
| `resolve_font`, `is_vector_font`, `font_kind_note`, `check_if_unavailable`, `build_curve`, `build_outline` | `font:`, `if_unavailable:`, `curve:`, `outline:` |
| `resolve_icon_name`, `resolve_icon_glyph` | `icon:` |
| `build_elements`, `push_visible` | a group's children |
| `build_hand_part`, `owned_color` | a hand's or a pattern's `parts:` |
| `check_foreign_keys` | a key that belongs to another `shape:` or `style:` |
| `aod_refusal` | an `aod:` key the element cannot honour |
| `dedup_append`, `and_paths`, `ABSENCE_IS_NORMAL`, `ICON_SIZE_NOTE` (module level) | collecting colours, and diagnostic wording |

**`resolve`: the `Resolver` (`r`, `wfb/layout.py`).** `r.face`, `r.device`
and `r.fonts` (the baked fonts) are there to read.

| Helpers | For |
|---|---|
| `point` | an `at:` position |
| `length` | a length used as a position (`dx:`, `to:`, a polygon point) |
| `extent` | a size, thickness or radius: clamped by `min_1px:`, recorded for the `sub-pixel-length` lint |
| `aod_extent` | an `aod:` override of an extent |
| `sized_box` | the "size, then align" box of a `size:`-placed kind |
| `text_font`, `font_for_ref`, `justify` | a `font:` reference (with or without the vector-font gates), and `TEXT_JUSTIFY_*` flags |
| `resolve_parts` | a hand's or a pattern's `parts:` |
| `alignment_shift`, `arc_box`, `stroke_pad`, `longer`, `text_ink`, `resolved_curve`, `round_half_away` (module level) | shared geometry |

**`draw_preview`: the `Renderer` (`wfb/preview.py`).** `renderer.draw` is
the Pillow `ImageDraw`, `renderer.scale` the upscale every device pixel is
multiplied by, and `renderer.values` the sample readings.

| Helpers | For |
|---|---|
| `color`, `visible` | evaluating a colour or a `visible:` expression |
| `aod_color`, `aod_field`, `aod_geometry` | the same with the element's `aod:` override and `dim:` applied under `--aod` |
| `draw_text`, `draw_vector_text`, `draw_outlined`, `glyph_source`, `paste_glyph` | text in a baked, system or `face:` font, and its `outline:` |
| `rect`, `hand_part` | a box in preview pixels; one part of a hand or of a pattern copy |
| `baked_glyph`, `arc_span` (module level) | a baked font's glyph box; an arc in Pillow's angles |

**`emit_draw` and `layout_constants`: `wfb/emit/monkeyc/`.** `aod` is an
`AodStyle`: `aod.color(element, key)`, `aod.layout(prefix, suffix,
has_override)`, `aod.value(override, awake_code)` and
`aod.part_color(element, color)` restyle a draw call for the always-on
frame and return the awake code unchanged in an awake-only build.

| Module | Helpers |
|---|---|
| `common` | `const_prefix` (the `Layout.<PREFIX>_*` prefix of an id), `font_field`, `aod_font_field`, `mc_color`, `mc_float`, `glyph_y_expr`, `article`, `and_list` |
| `layout_constants` | `box_constants`, `arc_constants`, `hand_part_constants`, `aod_thickness_constant`, `EVERY_PART_NOTE` |
| `shapes` | `emit_arc_span`, `thickness_expr`, `emit_plain_text_call`, `emit_outline_loop`, `radial_radius_expr`, `RADIAL_DIRECTION` |
| `rotated` | `emit_transformed_part`, `aod_thickness_override` (a hand or pattern part) |

## Tests

```sh
./.venv/bin/python -m pytest              # everything but the type check
./.venv/bin/python -m pytest -m "not slow" # skip the real monkeyc builds
./.venv/bin/python -m pytest -m typecheck  # mypy --strict, against its baseline
```

**The type check is its own test set.** `pytest -m typecheck` runs
`mypy --strict` over `wfb/` as `mypy.ini` configures it and compares the
result with `tests/mypy-baseline.txt`, known errors recorded without line
numbers. `wfb/` is clean, so the baseline is empty and any error fails the
check. It also fails on a baseline entry no longer reported, so a baseline
only shrinks: after fixing errors, run
`./.venv/bin/python tools/typecheck.py --update` and commit the smaller
file. `tools/typecheck.py` alone prints the same report. The result depends
on the versions of mypy and of the libraries' type information; the
baseline records them, and a failure names any that differ.

Golden-file tests over the generated Monkey C are the primary compiler test, and
they run with **no Garmin toolchain** — which matters, because the device files
are the scarce resource. Regenerate them after an intentional change with
`pytest tests/test_golden.py --update-golden` and read the diff.

**Snapshots, for a refactor that claims "no output change".** The golden files
cover a few fixtures; `tools/snapshot.py` covers everything the tool produces.
It drives the real CLI over every design in `examples/` and `tests/fixtures/`
and records:

- the generated project for the design's own targets and for two extra
  device mixes (AMOLED and older devices, without compiling);
- the lint on every installed device;
- eight preview variants (default, asleep, all styles, a fixed time, AOD,
  two AOD minutes, the burn-in heatmap);
- every listing and help command, with colour on and off.

About 360 cases; a full run takes about four minutes on four cores.

```sh
./.venv/bin/python tools/snapshot.py save /tmp/before    # before the change
./.venv/bin/python tools/snapshot.py compare /tmp/before # after: exit 0 = identical
./.venv/bin/python tools/snapshot.py compare /tmp/before --only examples/showcase/
```

`compare` prints a unified diff for each changed text output, and the changed
pixel count and bounding box for each changed image. Snapshots taken with
different font roots are not comparable (`--no-garmin-fonts` pins the one the
test suite uses). Paths, `wfb build`'s elapsed time and the UUID `wfb new`
mints are normalised; anything else that differs is a real change.

## What is decided

Python host language; YAML canonical with a published JSON Schema and a lossless
GUI over it; **code generation** rather than an on-device interpreter;
expressions compiled to Monkey C with no runtime evaluator; anchors and
relative/polar units resolved to pixels at build time; a narrow bounded escape
hatch to hand-written Monkey C; and build-time lints that carry explicit
confidence levels.

The short version of *why codegen*: Garmin ships no device-side renderer, so an
interpreter would have to live inside the same **128 KB** the design must fit in
— and it would forfeit Garmin's `excludeAnnotations` dead-code mechanism, which
only a generator can exploit. The reasoning is in [`docs/adr/`](adr/).

## What is next

Phase 3 — breadth: the remaining element types, per-device overrides, the `raw`
escape hatch, and the rest of on-device configuration (the Styles and Data
axes). Complications, interactivity and the two native colour axes have
landed — `on_hold:` (including `on_hold: auto`) on any element, `config:` for
an accent and a data colour edited in the fēnix 8's own on-device editor, and
all 42
complication types as `complication.*` data sources, read by a plain pull with
no cache anywhere in the generated face. See
[`docs/limitations.md`](limitations.md) §2 for the full list and `CLAUDE.md`
§6 for the ordering.
