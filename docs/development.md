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
registry's stand-in for every build/preview consumer that consults it. See
`docs/lore/toolchain.md`.

**Without the Garmin font root, `wfb preview` draws stand-in typefaces for
any face the registry has no exact match for** — not merely "an estimate",
a genuinely different family's letterforms (`wfb.fonts.fallback`'s own
`"substitute"`/`"none"` match levels). `wfb preview` names exactly which
fonts this happened to, once per run, on stderr; `wfb doctor` reports the
same thing as one line next to the root it did or did not find. `--fonts
DIR` on either command points at a root without installing it system-wide.
On `wfb preview`, that one root reaches layout measurement
and every lint that depends on it too, not only the pixels drawn (`Device.
fonts_root`, owned by the `DeviceDatabase` the command builds): a box is always sized from the same file it is then drawn with.

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
//! `step_ring` -- an arc gauge.
//!
//! Bound to `activity.steps` and `activity.step_goal`.
//! Absence policy: `absent: hide` -- the track still draws.
private function drawStepRing(dc as Dc, activity as ActivityMonitor.Info) as Void {
    // the values this element is bound to
    var activitySteps = activity.steps;
    var activityStepGoal = activity.stepGoal;

    // the unfilled track
    dc.setColor(Palette.TRACK, Graphics.COLOR_TRANSPARENT);
    WfbArc.drawSpan(dc, Layout.STEP_RING_CX, Layout.STEP_RING_CY, Layout.STEP_RING_RADIUS,
                    Layout.STEP_RING_THICKNESS, Layout.STEP_RING_START, Layout.STEP_RING_SWEEP);

    // the filled portion -- absent: hide, so only while the value is present
    if (activitySteps != null && activityStepGoal != null) {
        dc.setColor(Palette.ACCENT, Graphics.COLOR_TRANSPARENT);
        WfbArc.drawProgress(dc, Layout.STEP_RING_CX, Layout.STEP_RING_CY, Layout.STEP_RING_RADIUS,
                            Layout.STEP_RING_THICKNESS, Layout.STEP_RING_START, Layout.STEP_RING_SWEEP,
                            WfbMath.percent(activitySteps, activityStepGoal) / 100.0);
    }
}
```

Readable output is a requirement, not a nicety: it is what gets debugged when
something misbehaves on the wrist, and it is the substrate the escape hatch will
drop into. Symbol names derive from element ids, every block cites its YAML
element, layout constants are named rather than inlined, and every nullable read
is guarded with the `absent:` policy that produced the guard -- here, as
`absent: hide` on a gauge, around the fill alone, so the track still draws. The
comments quote keys and expressions as the author wrote them (`absent:`,
`color.accent`, `slot: top`), never the compiler's internal names.

## Pipeline

| Stage | Module | Toolchain? |
|---|---|---|
| YAML load with source spans | `wfb/yamlsrc.py` | no |
| JSON Schema, reported on author lines | `wfb/validate.py` | no |
| Format 2 checks the schema cannot make (colours, templates) | `wfb/lower.py` | no |
| Element blocks (`elements:`, `static:`, layouts) → one element list | `wfb/desugar.py` | no |
| Semantic pass (sources, types, nulls) | `wfb/ir/` (`model.py`, `naming.py`, `builder/`), `wfb/catalog.py`, `wfb/expr.py` | no |
| Per-device layout resolve | `wfb/layout.py` | device files |
| Lint | `wfb/lint.py` | device files |
| Font baking (TTF → BMFont) | `wfb/fonts/` | no |
| Draw program: each element's drawing and guards as one program (its kind's `lower`), printed by the view and evaluated by the preview; a frame as layers, with the program as JSON | `wfb/draw/` | no |
| Codegen: Monkey C, resources, manifest, jungle | `wfb/emit/` | no |
| `monkeyc` + measured memory | `wfb/build.py` | **yes** |
| Host-side preview | `wfb/preview.py` | no |

Each element kind's own code, from every stage above, lives in
`wfb/kinds/<kind>.py` behind a registry ("Element kinds", below).

## Layout

```
wfb/                  the compiler
  yamlsrc.py            YAML loading that keeps source spans
  validate.py           JSON Schema, reported against the author's lines
  lower.py              format 2 checks the schema cannot make (colours, templates)
  vocab.py              an absence policy spelled as the author writes it
  template.py           the `text:` template: "{expr:spec}" parsing
  desugar.py            the element mapping form and the `static:` blocks -> one form
  catalog.py            the typed data-source catalogue
  expr.py               the expression language -> Monkey C
  ir/                   the IR (model.py, naming.py) and the semantic pass (builder/,
                        one module per layer of the Builder class)
  kinds/                one module per element kind: its own build, resolve, preview,
                        emit and layout-constant code, an ElementKind subclass each
  layout.py             relative units -> absolute pixels, per device
  lint.py               ADR 0008's checks, each with a stated confidence
  fonts/                TrueType -> BMFont sheet, subsetted to the used glyphs
  fonts/registry.json   device font name -> free-font-key mapping
  fonts/fetch_system.py stdlib-only fetch/cache/Garmin-font-root logic driven by registry.json
  icons.py              icon sizing and resolution over the Nerd Fonts icon font
  icon_catalog.py       the icon name -> codepoint table, data only
  assets/icons/         the "Symbols Only" icon font, downloaded by tools/fetch-icon-font.py
  assets/system-fonts/  registry.json's free stand-ins for Garmin's system fonts,
                        downloaded by tools/fetch-system-fonts.py
  draw/                 an element's drawing as one program: ops, the Monkey C printer,
                        the host evaluator, the barrel's arithmetic transcribed
  edit/                 the editor's patch engine: the span index, text patches, the
                        gate, pixel drags written in the author's units, and
                        structure (blocks, groups, new elements)
  starters.py           the face templates in templates/, for `wfb new`
  emit/                 Monkey C, resources, manifest, jungle
  preview.py            host-side renderer over the resolved IR
  build.py, cli.py      the pipeline and `wfb`
ts/                   the compiler, being ported to TypeScript stage by stage
                      (ts/CLAUDE.md): one package for the browser and Node
  src/                  the port, module for module beside wfb/; browser.ts is the
                        browser bundle's entry (npm run bundle -> dist/wfb.js);
                        cli.ts is `wfb` (node ts/src/cli.ts; wfb.py studio runs it);
                        studio/ the editor's worker (the history store, open
                        documents, the requests; npm run bundle -> dist/worker.js)
                        and its server (devices, fonts, builds);
                        edit/yaml.ts reproduces ruamel's node tree and data
                        from the yaml package; py.ts holds Python's semantics
                        (rounding, repr, json.dumps) where output depends on them
  tools/                parity.ts (each ported stage against the oracle), compare.ts,
                        stages.ts (the stage table and each stage's port)
  test/                 node:test tests (npm test); cases/ holds inputs the oracle
                        dumps beside the faces (yaml/: YAML edge cases)
  app/                  the editor's page (wfb studio): plain ES modules, its
                        vendor/ files built by tools/vendor-studio-frontend.sh,
                        CodeMirror from tools/studio-frontend/
runtime-lib/          the hand-written support barrel the generated code calls
schema/               the published JSON Schema (a shipped artefact)
examples/             example faces; `examples/README.md` is the index
examples/dashboard/   one of the four faces built to be worn (with
                      showcase/, analog-custom/ and enduro/)
examples/features/    one face per format feature, written as each landed
examples/system-fonts/  the three system-font calibration faces
tests/                ? tests; only the `slow` ones need the Garmin toolchain
tests/fixtures/slice/ the Phase 2 slice: the golden files' source design
tools/                setup, font fetchers, extract-device-reference.py, docs-shots.py,
                      snapshot.py (output snapshots), typecheck.py (mypy --strict
                      against its baseline), oracle.py (every pipeline stage's
                      output as JSON, for ts/'s parity runner; oracle_patches.py
                      is its battery of editor operations, oracle_cases.py its
                      seeded broken designs), capture_designs.py (every design
                      the fast suite loads, as more parity cases)
.cache/device-reference/  derived, not committed: the SDK's device reference pages as
                      JSON, regenerated by tools/setup-env.sh
.cache/oracle/        derived, not committed: tools/oracle.py's dump
.cache/test-designs/  derived, not committed: tools/capture_designs.py's capture
docs/                 README.md (hub), guide/ (format reference), limitations, ADRs, research
```

## Element kinds

Each element kind (`group`, `shape`, `text`, `gauge`, `icon`, `graph`,
`data`, `hands`, `pattern`) is one module in `wfb/kinds/`, named as the
author writes its `type:`, except that the six primitive types (`rectangle`,
`circle`, ...) are all the `shape` kind's (`wfb.kinds.kind_of`). Each module holds one subclass of `wfb.kinds.ElementKind` (`TextKind`, `PatternKind`,
...) and an instance of it as the module's `KIND`. A stage never switches on
kind: it asks the registry (`kinds.for_element`, `kinds.for_placed`) and
calls a method. The base class is the interface: every method's signature
and docstring is there, and every method but `build`, `resolve` and
`lower` has a default meaning "nothing to do here",
so a kind overrides only where it differs. **Adding a tenth kind** is an IR
class (`wfb/ir/model.py`), a `Placed` class (`wfb/layout.py`), one kind
module, its name in `wfb.kinds._NAMES` and its schema entry;
`tests/test_kinds.py` fails until they agree. "Adding an element kind",
below, walks through one.

**Drawing is one program per element (`wfb/draw/`).** A kind's `lower`
returns the element's drawing as a list of ops (`wfb.draw.program`):
`SetColor`, `SetPen`, the `Dc` primitives, the barrel's drawing calls, text
calls, locals, loops and conditions over values the watch computes, and
`_aod` blocks. `wfb.draw.program` puts the element's own guards around it
(`visible:`, the null guard its `absent:` policy asks for, and the
`antialias:` bracket). The view prints the result as the body of
`draw<Id>` after its reads (`wfb.draw.printer`, through `emit_body`), and
the preview paints it (`wfb.draw.evaluator`, through `paint`), so the two
cannot disagree: a value prints bare and the evaluator reads it the way
Monkey C parses the printed text. Every kind that draws lowers; `group`
draws nothing itself. `wfb.draw.drawn_text` gives the string an element
draws at given readings, without painting it.

**A frame as layers (`wfb.draw.layers`).** `layers(resolved, options)`
returns each element `wfb.preview.render` draws as its own transparent RGBA
image, in draw order, with an outlined group's ring as one more layer just
before its first member. `compose` stacks them and runs the whole-frame
steps once: the black ground, the AOD mask, the palette, the bezel and the
skin (`wfb.preview.finish_frame`). Stacking equals `render` before the
palette snap to within one level per channel, and only anti-aliased edges
round (`tests/test_draw_layers.py`). A lowered element's layer also carries
its program as JSON for that frame (`wfb.draw.jsonform.to_json`). Readings,
colours and always-on choices are folded, and `Layout` constants stay named
beside their values. Text and icons arrive laid out: each `text` or
`glyph` op carries a `run`, the tiles the renderer would paste (a glyph's
mask, or a rotated vector run's RGBA image), each at a whole-pixel offset
from the op's anchor. The renderer records them instead of painting while
its `stamps` is a list (`wfb.preview.Stamp`), and a frame's layers share one
`jsonform.Tiles` store, which packs to raw RGBA bytes for a browser.
`jsonform.rasterise` is the reference reader of that JSON: for every
lowered element it paints exactly what the evaluator paints. The editor's
browser reader, `ts/app/raster.js`, reproduces Pillow's
primitives and its paste byte for byte, and equals `rasterise` on every
element of the examples (`tests/test_studio_raster.py`, which needs Node).
The editor's frame (`ts/src/studio/document.ts`, `Document.frame`) carries its
layers this way: `layers(..., paint_all=False)` paints only a layer with an
op outside `BROWSER_OPS` (an outlined group's ring), and the browser draws
the rest, works out where each leaves ink for hit-testing (`raster.inkOf`,
equal to the matte's alpha), and redraws the face from them during a move
(`raster.translateOps`). Which elements a frame draws is one
function, `wfb.draw.frames.frame_members`, read by the view, its read plan
and the preview. The evaluator computes a barrel call with its
Python transcription (`wfb.draw.barrel`). Each transcription is checked
against the `.mc` source and swept against a model of the pixels the watch
draws (`ts/test/barrel.test.ts`).

**Fonts are one question.** A kind that draws text says what it draws, and
in which font, as a list of `TextRun`s (`ElementKind.text_runs`): the font,
the glyphs a baked sheet must hold, the exact strings the missing-glyph lint
checks, and, for an icon font, how to bake it. Glyph baking, icon-font
baking, `onLayout`'s font loading, the vector-font guards and lint, the
missing-glyph lint and `IconGlyphs.mc` are all derived from those runs in
their own stage, so a new kind that draws text writes one method, not one
per stage. A `pattern` returns one run per `type: text` part; `part_index`
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
  `data` element, a `graph`'s series barrel, a curved `text`
  element's rotated ink (`layout._shape_ink`), a `data` element
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
Its drawing was then a pair of methods, one for the view and one for the
preview; the `lower` below replaced them on 2026-10-02 and prints the same
two calls.

**1. The schema** (`schema/wfb-face-2.schema.json`). Add a `$defs` entry and
reference it from `$defs.element.oneOf`. `additionalProperties` is `false`
on every element, so an element restates the keys every kind accepts; copy
them from `circleElement`. The id is the element's key, so it is not a
property. The kind's name is its `type:`. `aod:` takes a per-kind `aod<Kind>` definition that
lists which keys an override may restyle; `aodIcon` (colour and `visible:`)
fits a one-colour kind.

```json
"dotElement": {
  "type": "object",
  "required": ["type", "radius"],
  "additionalProperties": false,
  "properties": {
    "type": {"const": "dot"},
    "radius": {"$ref": "#/$defs/length"},
    "color": {"$ref": "#/$defs/colorExpression"},
    "at": {"$ref": "#/$defs/position"},
    "sleep_update": {"$ref": "#/$defs/sleepUpdate"},
    "z": {"$ref": "#/$defs/zOrder"},
    "on_hold": {"$ref": "#/$defs/onHold"},
    "visible": {"$ref": "#/$defs/visible"},
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

from ..draw.program import AodRestyled, Const, DrawContext, Op, Primitive, SetColor
from ..ir.model import Dot
from ..layout import PlacedDot
from ..units import Axis, Box
from ..emit.monkeyc.common import const_prefix
from . import ElementKind

if TYPE_CHECKING:
    from ..ir.builder import Builder
    from ..layout import Resolver


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

    def lower(self, ctx: DrawContext, placed: PlacedDot) -> list[Op]:
        prefix = const_prefix(placed.id)
        return [
            SetColor(AodRestyled(placed.element, "color")),
            Primitive("fillCircle", ((Const(f"{prefix}_CX", placed.center[0]),
                                      Const(f"{prefix}_CY", placed.center[1]),
                                      Const(f"{prefix}_RADIUS", placed.radius)),)),
        ]

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
  generated code: the view is shared by every target, so a program names
  `Layout.<PREFIX>_*` (a `Const`, with this device's value beside it), never
  a pixel literal (a literal that differs between targets fails the build as
  a `shared-source` error).
- `lower` is the drawing, once: the view prints it as the body of
  `draw<Id>(dc)` after the element's reads, guards and `antialias:`, and the
  preview evaluates it. `AodRestyled(element, key)` is a colour with the AOD
  override and `dim:` applied, printed as the plain colour in an awake-only
  build. With `ctx.ring`, it draws only the element's share of an outlined
  group's ring.

The rest of the interface you can ignore until the kind needs it; each
default means "nothing to do here":

| Method or attribute | Override when the kind... |
|---|---|
| `antialiased` | draws primitives (`drawCircle`, `fillPolygon`, ...), so `antialias:` becomes `Dc.setAntiAlias`; a glyph kind anti-aliases in its font instead |
| `circular_extent` | is round: the safe-area lint then checks the disc, not the box corners |
| `text_runs` | draws text or an icon glyph in a font it names: see "Fonts are one question" above |
| `static_forbidden` | can never be in a `static:` block (its picture is a series, the clock or a wearer's pick) |
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

**`build`: the `Builder` (`b`, `wfb/ir/builder/`).** A helper that can
fail reports its own error and returns `None` or an empty default.
`b.doc.span(node, key)` locates a key for a diagnostic of the kind's own,
and `b.bag` takes it. `Builder` is one class stacked from layers, one
module each (`reading`, `absence`, `glyphs`, ... `tree`), and each layer
calls only the layers beneath it. A new helper goes in the lowest layer
that has everything it calls; the package docstring lists the order.

| Helpers | For |
|---|---|
| `expression`, `color_expression`, `length`, `angle`, `position`, `size`, `alignment`, `baked_size_length` | reading one key of the node |
| `require` | a key the schema cannot require by itself |
| `check_absence`, `check_other_absence`, `check_reachable_substitute`, `nullable_sources` | `absent:` for the value and for every other nullable binding |
| `check_format`, `check_format_spec`, `check_format_not_on_literal` | a `text:` template's format spec |
| `resolve_font`, `is_vector_font`, `font_kind_note`, `check_unsupported`, `build_curve`, `build_outline` | `font:`, `unsupported:`, `curve:`, `outline:` |
| `resolve_icon_name`, `resolve_icon_glyph` | `icon:` |
| `build_elements`, `push_visible` | a group's children |
| `build_hand_part`, `owned_color` | a hand's or a pattern's `parts:` |
| `check_foreign_keys` | a key that belongs to another primitive type or `style:` |
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

**`lower`: the draw program (`wfb/draw/program.py`).** `ctx` is a
`DrawContext`: the resolved face, the build's `AodStyle`, the value's
guard locals, the ring pass to draw instead, if any. A program is built
from these, each printed by `wfb.draw.printer` and evaluated by
`wfb.draw.evaluator`; a new one needs both.

| Ops and values | For |
|---|---|
| `Const`, `Lit`, `FloatLit`, `Shifted`, `Grown`, `AodPick` | `Layout` constants, literals, a stamp's or a ring's offset, an `aod:` length |
| `NumLocal`, `Read`, `Bin`, `Paren`, `Call`, `Conv`, `NumPick` | numbers the watch computes: a reading, arithmetic, a barrel or `Math` call (`wfb.draw.barrel.CALLS`) |
| `Color`, `AodRestyled`, `AodDimmed`, `AodPart`, `AodPaint`, `PaintPick`, `RingColor` | colours, restyled for the always-on frame |
| `SetColor`, `SetPen`, `Primitive`, `FillPolygon`, `ArcSpan`, `ArcProgress`, `Part` | `Dc` calls and the barrel's drawing calls |
| `Text`, `Glyph`, `LoadFont`, `LetText`, `Font` and the `Str` values | text and icons |
| `Let`, `Assign`, `If`, `For`, `Continue`, `Return`, `IfAod`, `IfAwake`, `IfNotNull` and the `Cond` values | locals, loops and conditions |

**`layout_constants`: `wfb/emit/monkeyc/`.** The printer spells a program's
always-on choices through the build's `AodStyle` (`aod.color`, `aod.layout`,
`aod.value`, `aod.part_color`), which returns the awake code unchanged in an
awake-only build.

| Module | Helpers |
|---|---|
| `common` | `const_prefix` (the `Layout.<PREFIX>_*` prefix of an id), `font_field`, `aod_font_field`, `mc_color`, `mc_float`, `glyph_y_expr`, `article`, `and_list` |
| `layout_constants` | `box_constants`, `arc_constants`, `hand_part_constants`, `aod_thickness_constant`, `EVERY_PART_NOTE` |
| `shapes` | `emit_arc_span`, `thickness_expr`, `emit_plain_text_call`, `emit_outline_loop`, `radial_radius_expr`, `RADIAL_DIRECTION` |
| `rotated` | `emit_transformed_part`, `emit_part_ring`, `aod_thickness_override` (a hand, needle or pattern part, which the printer writes for a `Part`) |

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

**Node 24 is needed** for the editor's front-end tests and for `ts/`.
`tools/setup-env.sh` installs an official build when the Node on `PATH`
cannot run `.ts` files (a distribution build may lack type stripping), and
prepends it to `PATH`.
- `tests/test_studio_raster.py` holds the browser's rasteriser
  (`ts/app/raster.js`) to Pillow byte for byte.
- `tests/test_ts.py` runs `ts/`'s own tests and its type check.

Both fail rather than skip without Node.

**The TypeScript port is held to the Python compiler stage by stage.**
`tools/oracle.py` dumps what Python produces at each stage boundary for
every design in `examples/` and `tests/fixtures/`, on its targets and the
AMOLED `fenix847mm`. It also dumps the load stages, the lint and the baked
fonts of every design the fast test suite loads, which
`tools/capture_designs.py` captures (thousands of small designs, most
written to hit one diagnostic). `npm run parity` in
`ts/` runs each ported stage over the same cases and compares:

```sh
./.venv/bin/python tools/capture_designs.py        # the suite's designs, about 6 min
./.venv/bin/python tools/oracle.py                 # all stages
./.venv/bin/python tools/oracle.py --stage spans   # one stage
./.venv/bin/python tools/oracle.py --captured      # the captured designs alone
cd ts && npm run parity -- spans data              # these stages; exit 0 = equal
cd ts && npm run parity -- --allow-missing         # tolerate stages not ported yet
cd ts && npm test && npm run typecheck             # ts/'s own tests, tsc --noEmit
```

The table counts each stage's cases as equal, deviated (equal once a
recorded deviation in `ts/tools/stages.ts` is applied), differ, failed or
missing, then shows the first differences by JSON path. Rerun the oracle
after a change to `wfb/`: its `index.json` records the commit it came from.
Two deviations are text rendered from outlines rather than by FreeType, and
two reports put a figure on them: `node tools/bake-report.ts` (baked glyphs,
per font) and `node tools/text-report.ts` (the preview's system-font and
vector-font runs, as ink overlap and offset), both saved under
`docs/research/probes/typescript-stack/`.

Golden-file tests over the generated Monkey C are the primary compiler test, and
they run with **no Garmin toolchain** — which matters, because the device files
are the scarce resource (`ts/test/golden-monkeyc.test.ts`, the files in
`ts/test/goldens/monkeyc/`). `ts/test/goldens.test.ts` freezes the rest: every
diagnostic of the corpus of small designs the tests wrote
(`ts/test/corpus/designs.json.gz`), and every example's and fixture's
diagnostics, generated project and previews, by hash. Regenerate them after an
intentional change with `WFB_UPDATE_GOLDENS=1 npm test` (in `ts/`) and read the
diff of `ts/test/goldens/`.

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
[`docs/limitations.md`](limitations.md) §2 for the full list and
[`docs/lore/roadmap.md`](lore/roadmap.md) for what shipped.
