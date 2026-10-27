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
copy of the device definitions (`docker build -t garmin-wf-builder .` builds
the same image from the checkout):

```sh
docker run --rm -v "$PWD:/work" \
  -v "$HOME/Library/Application Support/Garmin/ConnectIQ/Devices:/devices:ro" \
  -v wfb-keys:/keys \
  vvorth/garmin-wf-builder build examples/features/graph/face.yaml
```

See [`docs/container.md`](container.md). The local install:

Installs the newest Connect IQ SDK in Garmin's `sdks.json`, or the one
`SDK_VERSION=x.y.z` names (on macOS: finds the SDK Manager's newest
install), generates a developer key, installs the device definitions (on macOS:
reads the SDK Manager's in place), copies Garmin's own font files in from
`vendor/fonts/` if present (Linux only, optional — see below), downloads the Nerd Fonts icon font
(`ts/tools/fetch-icon-font.ts`, pinned and hash-checked; the font is not committed)
and prefetches the registry's system-font stand-ins the same way
(`ts/tools/fetch-system-fonts.ts`; see `docs/lore/toolchain.md`), and
installs Node 24.22.1 when the one on `PATH` cannot run TypeScript or is
unpatched, with `ts/`'s npm dependencies.

The SDK downloads freely. **Device definitions cannot be downloaded** —
`api.gcs.garmin.com` returns HTTP 401 and needs a Garmin SSO login that cannot be
completed headlessly. Get them with Garmin's SDK Manager
([Step 1: get the device definitions](guide/getting-started.md#step-1-get-the-device-definitions)). The script
takes them from `vendor/devices/` (gitignored, because they are your own licensed
copy), from `~/Library/Application Support/Garmin/ConnectIQ/Devices`, or from
wherever they already are at `~/.Garmin/ConnectIQ/Devices`.

**Garmin's own font files are the same shape, but optional**: free stand-ins
(`ts/src/data/font-registry.json`) work without them. If the SDK Manager install also
has a `Fonts` directory, the script copies it from `vendor/fonts/` (gitignored,
same reasoning as `vendor/devices/`) into `~/.Garmin/ConnectIQ/Fonts`
incrementally. `wfb doctor` reports which root it found (`--fonts DIR` or
`WFB_FONTS` override it); a device's real file there outranks the
registry's stand-in for every build/preview consumer that consults it. See
`docs/lore/toolchain.md`.

**Without the Garmin font root, `wfb preview` draws stand-in typefaces for
any face the registry has no exact match for** — not merely "an estimate",
a genuinely different family's letterforms (`ts/src/fonts/fallback.ts`'s own
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
`~/Library/Application Support/Garmin/ConnectIQ/Sdks/connectiq-sdk-mac-<version>-*`,
and devices and fonts are read in place from that tree, which `monkeyc` and
`wfb` both look in already; a device in `vendor/devices/` that the SDK Manager
lacks is reported, not copied. It appends `CIQ_SDK`/`PATH` to
`/etc/sandbox-persistent.sh` on Linux when that file exists and is writable
(the development sandbox); otherwise it prints the two exports, quoted since
the macOS path holds a space, for your shell profile. It checks for `openssl`,
a working `java` (macOS has a `java` stub with no runtime behind it), and on
Linux `curl` and `unzip`,
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
| YAML load with source spans | `ts/src/yamlsrc.ts` | no |
| JSON Schema, reported on author lines | `ts/src/validate.ts` | no |
| Format 2 checks the schema cannot make (colours, templates, a rule list's shape); a rule list → the `?:` chain it stands for | `ts/src/lower.ts` | no |
| Element blocks (`elements:`, `static:`, layouts) → one element list; a hand's, pattern's or needle's `parts:` mapping → one list with each part's `id`; a text's inline `font:` → a `resources: fonts:` entry | `ts/src/desugar.ts` | no |
| Semantic pass (sources, types, nulls) | `ts/src/ir/` (`model.ts`, `naming.ts`, `builder/`), `ts/src/catalog.ts`, `ts/src/expr.ts` | no |
| Per-device layout resolve | `ts/src/layout.ts` | device files |
| Lint | `ts/src/lint.ts` | device files |
| Font baking (TTF → BMFont) | `ts/src/fonts/` | no |
| Draw program: each element's drawing and guards as one program (its kind's `lower`), printed by the view and evaluated by the preview; a frame as layers, with the program as JSON | `ts/src/draw/` | no |
| Codegen: Monkey C, resources, manifest, jungle | `ts/src/emit/` | no |
| `monkeyc` + measured memory | `ts/src/build.ts` | **yes** |
| Host-side preview | `ts/src/preview.ts` | no |

Each element kind's own code, from every stage above, lives in
`ts/src/kinds/<kind>.ts` behind a registry ("Element kinds", below).

## Layout

```
wfb                   the entry point: runs ts/src/cli.ts under Node
ts/                   the compiler, its tests and tools: one package for the
                      browser and Node (ts/CLAUDE.md)
  src/                  the compiler
    yamlsrc.ts            YAML loading that keeps source spans
    validate.ts           JSON Schema, reported against the author's lines
    lower.ts              format 2 checks the schema cannot make (colours, templates); rule lists -> ?:
    vocab.ts              an absence policy spelled as the author writes it
    template.ts           the `text:` template: "{expr:spec}" parsing
    desugar.ts            the element mapping form, the `static:` blocks and inline fonts -> one form
    catalog.ts            the typed data-source catalogue
    expr.ts               the expression language -> Monkey C
    ir/                   the IR (model.ts, naming.ts) and the semantic pass (builder/,
                          one module per layer of the Builder class)
    kinds/                one module per element kind: its own build, resolve, draw
                          and layout-constant code, an ElementKind subclass each
    layout.ts             relative units -> absolute pixels, per device
    lint.ts               ADR 0008's checks, each with a stated confidence
    fonts/                TrueType -> BMFont sheet, subsetted to the used glyphs;
                          the Garmin font root and the registry's stand-ins
    icons.ts              icon sizing and resolution over the Nerd Fonts icon font
    draw/                 an element's drawing as one program: ops, the Monkey C printer,
                          the host evaluator, the barrel's arithmetic transcribed
    raster/               the preview's rasteriser: Garmin's own rules (garmin.ts)
                          where simulator captures pin them, Pillow's elsewhere
    edit/                 the editor's patch engine: the span index, text patches (a
                          key set, removed or renamed; a list item inserted, removed
                          or moved), the gate, pixel drags written in the author's
                          units, and structure (blocks, groups, new elements)
    emit/                 Monkey C, resources, manifest, jungle
    preview.ts            the host-side renderer over the resolved IR
    build.ts, node_build.ts  the pipeline, and writing and compiling a project (Node)
    cli.ts                `wfb`, over node:util's parseArgs; term.ts behind it
    studio/               the editor's worker (the history store, open documents, the
                          requests), its server (devices, fonts, builds) and its
                          service worker (sw.ts, the offline copy);
                          protocol.ts is the page/worker contract, every request
                          and answer as TypeScript interfaces; parts.ts the parts of
                          hands, patterns and needles as the tree, the entered
                          frame and a drag see them
    browser.ts            the browser bundle's entry (npm run bundle -> dist/wfb.js)
    data/                 tables the browser needs without a file system
                          (font-registry.json: device font name -> free font)
    py.ts                 Python's semantics (rounding, quoting, json.dumps) where
                          output depends on them
  app/                  the editor's page (wfb studio): TypeScript with htm
                        templates over Preact (npm), main.ts its entry, which the
                        studio server bundles with esbuild as /dist/app.js (also
                        npm run bundle -> dist/app.js), every module strict
                        TypeScript; store.ts holds the editor's state (one
                        EditorStore, read through useStore), outbox.ts and
                        textsync.ts the pure rules it runs; form.ts the
                        generic form over the inspector's field tree, with
                        template-editor.ts (a text: template as chips) and
                        condition-editor.ts (a value that follows data as
                        rows, written as a rule list); vendor/
                        holds CodeMirror (built from tools/studio-frontend/ by
                        tools/vendor-studio-frontend.sh) and marked
  templates/            the starters for `wfb new` and the hand presets
  assets/               downloaded, not committed: the icon font (icons/) and the
                        registry's system-font stand-ins (system-fonts/)
  tools/                setup-env's fetchers, fetch-sdk.ts (the Docker image),
                        goldens.ts, export-data.ts, docs-shots.ts, studio-shots.ts,
                        build.ts and more
  test/                 node:test tests (npm test, test/CLAUDE.md); fixtures/ the
                        designs the goldens and font tests build (fixtures/slice/,
                        the Phase 2 slice, is the Monkey C goldens' source) and
                        fixtures/devices/, the fixture device wfbtest
  slow/                 the monkeyc suite (npm run test:slow)
  browser/              the Playwright suite over wfb studio's pages (npm run test:browser):
                        harness.ts starts the server and headless Chromium
runtime-lib/          the hand-written support barrel the generated code calls
schema/               the published JSON Schema (a shipped artefact)
examples/             example faces; `examples/README.md` is the index
examples/dashboard/   one of the four faces built to be worn (with
                      showcase/, analog-custom/ and enduro/)
examples/features/    one face per format feature, written as each landed
examples/system-fonts/  the three system-font calibration faces
tools/                setup-env.sh, the front-end vendoring, and research/ (stdlib
                      Python research scripts)
docker/               the image's entrypoint
.cache/device-reference/  derived, not committed: the SDK's device reference pages as
                      JSON, regenerated by tools/setup-env.sh
docs/                 README.md (hub), guide/ (format reference), limitations, ADRs, research
```

## Element kinds

Each element kind (`group`, `shape`, `text`, `gauge`, `icon`, `graph`,
`data`, `hands`, `pattern`) is one module in `ts/src/kinds/`, named as the
author writes its `type:`, except that the six primitive types (`rectangle`,
`circle`, ...) are all the `shape` kind's (`kindOf` in `ts/src/kinds/index.ts`). Each module holds one subclass of `ElementKind` in `ts/src/kinds/index.ts` (`TextKind`, `PatternKind`,
...) and an instance of it as the module's `KIND`. A stage never switches on
kind: it asks the registry (`kinds.for_element`, `kinds.for_placed`) and
calls a method. The base class is the interface: every method's signature
and docstring is there, and every method but `build`, `resolve` and
`lower` has a default meaning "nothing to do here",
so a kind overrides only where it differs. **Adding a tenth kind** is an IR
class (`ts/src/ir/model.ts`), a `Placed` class (`ts/src/layout.ts`), one kind
module, its name in `NAMES` in `ts/src/kinds/base.ts` and its schema entry;
`ts/test/kinds.test.ts` fails until they agree. "Adding an element kind",
below, walks through one.

**Drawing is one program per element (`ts/src/draw/`).** A kind's `lower`
returns the element's drawing as a list of ops (`ts/src/draw/program.ts`):
`SetColor`, `SetPen`, the `Dc` primitives, the barrel's drawing calls, text
calls, locals, loops and conditions over values the watch computes, and
`_aod` blocks. `ts/src/draw/program.ts` puts the element's own guards around it
(`visible:`, the null guard its `absent:` policy asks for, and the
`antialias:` bracket). The view prints the result as the body of
`draw<Id>` after its reads (`ts/src/draw/printer.ts`, through `emit_body`), and
the preview paints it (`ts/src/draw/evaluator.ts`, through `paint`), so the two
cannot disagree: a value prints bare and the evaluator reads it the way
Monkey C parses the printed text. Every kind that draws lowers; `group`
draws nothing itself. `drawnText` in `ts/src/draw/index.ts` gives the string an element
draws at given readings, without painting it.

**A frame as layers (`ts/src/draw/layers.ts`).** `layers(resolved, options)`
returns each element `render` in `ts/src/preview.ts` draws as its own transparent RGBA
image, in draw order, with an outlined group's ring as one more layer just
before its first member. `compose` stacks them and runs the whole-frame
steps once: the black ground, the AOD mask, the palette, the bezel and the
skin (`finishFrame` in `ts/src/preview.ts`). Stacking equals `render` before the
palette snap to within one level per channel, and only anti-aliased edges
round. A lowered element's layer also carries
its program as JSON for that frame (`toJson` in `ts/src/draw/jsonform.ts`). Readings,
colours and always-on choices are folded, and `Layout` constants stay named
beside their values. Text and icons arrive laid out: each `text` or
`glyph` op carries a `run`, the tiles the renderer would paste (a glyph's
mask, or a rotated vector run's RGBA image), each at a whole-pixel offset
from the op's anchor. The renderer records them instead of painting while
its `stamps` is a list (`Stamp` in `ts/src/preview.ts`), and a frame's layers share one
`jsonform.Tiles` store, which packs to raw RGBA bytes for a browser.
`jsonform.rasterise` is the reference reader of that JSON: for every
lowered element it paints exactly what the evaluator paints. The editor's
browser reader is the preview's rasteriser itself (`ts/src/raster/`:
Garmin's own rules in `garmin.ts` where simulator captures pin them,
Pillow's primitives and paste elsewhere), which `wfb studio` bundles for
the page from `ts/src/raster/canvas.ts`.
The editor's frame (`ts/src/studio/document.ts`, `Document.frame`; its shape
is `Frame` in `ts/src/studio/protocol.ts`, as every payload the worker
sends to the page is) carries its
layers this way: `layers(..., paint_all=False)` paints only a layer with an
op outside `BROWSER_OPS` (an outlined group's ring), and the browser draws
the rest, works out where each leaves ink for hit-testing (`raster.inkOf`,
equal to the matte's alpha), and redraws the face from them during a move
(`raster.translateOps`). Which elements a frame draws is one
function, `frameMembers` in `ts/src/draw/frames.ts`, read by the view, its read plan
and the preview. A frame asked for with `enter` (the tree path of a `hands`,
`pattern` or `style: needle` element) is that element's local frame
(`ts/src/studio/parts.ts`): `Frame.local` gives the axis, one `%r` in pixels
and the angle the parts are drawn at (a hand's at the frame's time, a radial
pattern's first drawn copy, a needle's at the sample reading, taken from
the needle's own draw program); `items` lists only the element's parts
(every hand's, for a hands element), each named by its tree path joined with
`/`, placed where the frame draws it, with the handles its own shape has
(`partGeometry` in `drag.ts`: `vertex` and `segment` handles on a polygon,
the reflected half of a `mirror: x` part shown `mirrored` and not
draggable, size handles turned with a rectangle or circle, an arc's angle
handles at the arc's screen angle, a line's ends), plus the element itself
undrawn; the image is the whole face with everything but the entered
element dimmed to 35% (`layers(..., paintAll)`, every other layer's alpha
scaled, then `compose`), and `layers` holds the element's own layer alone.
The hand-set thumbnail route (`handset`, `Document.handSetImage`) is kept
as it was for the Face tab. A frame asked for with `hidden` (element ids the
editor hides, `FrameArgs.hidden`) leaves those elements and everything
written inside them out of its image (`layers(..., paintAll)` without them,
then `compose`) and its layers, and lists them undrawn with no handles; the
page keeps which elements are hidden and which locked in the face's
editor-only state (`FaceUiState`, the `ui_state` request), beside the face
and never in its text, and the canvas passes over a locked element.

The Layers tree (`Document.tree`) lists, under a `hands` element, its set's
hands (`kind: "hand"`, their paths under `resources: hand_sets:`) each with
its parts, and under a `pattern` or a needle gauge its parts directly
(`kind: "part"`, `type` the part's own). A part's path ends in `parts` (a
needle's `needle`) and its id, or, in the list form the format keeps as
shorthand, its index; such a part's id is the compiler's `partN`. Every
request names a part by that path, never by name: parts of different hands
may share names. The evaluator computes a barrel call with its
transcription (`ts/src/draw/barrel.ts`). Each transcription is checked
against the `.mc` source and swept against a model of the pixels the watch
draws (`ts/test/barrel.test.ts`).

The editor's inspector (`ts/src/studio/inspect.ts`, `inspect`; its shape is
`Inspect` in `protocol.ts`) answers for one element, one device and one
editing context (`frame`: awake, asleep or AOD; `style`); given a hand's or
a part's path (`subject`: `hand`, `part`), it answers the hand's keys
(`color`, `parts`) or the part's from its own schema branch (`handPart`,
`patternPart`), narrowed to the keys its type reads by the compiler's own
tables, read as written: a part has no overrides and no `aod:` block, so
`aod_keys` is empty, `overrides` has no entry, and the context's frame does
not change what it reads. Given a `resources: fonts:` entry's path
(`subject: "font"`), it answers that entry's `bakedFont` or `vectorFont`
branch (by `source:` or `face:`), without the keys the schema keeps there
only to name the mistake ("Baked-font key. A build error here"), and a
`face:` name's widget is `face`; the Face tab's Fonts section renders it
with the same form, its edits the generic ops with the entry as their
element target. Its `fields` are a
tree generated from the element's schema branch: each node's `kind` is
`scalar` (with the control its `$defs` entry picks, `widget`), `object`
(`children`, every property present or not; one whose keys the author names,
such as `overrides:` by selector, lists the keys present and a new key's
template as `item`), `list` (`item` the template, `items` one per item) or
`choice` (`branches`, each a field, and `chosen` the branch the value's shape
matches: const, type, required keys). `$ref`s resolve through `$defs` at
every level, an `allOf` whose first branch is a `$ref` reads as that branch,
and the tree is cut at depth 6 (`truncated`). Only a key the schema lacks is
raw (`unknown`). Every field carries `effective`: the value the context reads
and its provenance (`own`, `override` with the selector, `aod`, `group` with
the group's id, `defaults`, `absent`). Awake, that is the most specific
override the viewed device has, else the element's own key, a mapping merged
key by key; in the AOD frame, the `aod:` cascade the compiler resolves
(`ir/builder/aod.ts`): the element's own block, else the nearest ancestor
group's block, else `defaults: {aod:}` for `visible` and `dim`, else the awake
value, with a group's `visible: false` sticky (the built face's
`aod_ancestor_hidden` decides it where the face loads). `aod_keys` lists the
keys the element's kind may restyle there, from the schema's per-kind `aod*`
def. The worker's edits (`EDITS` in `ts/src/studio/document.ts`, `EditOp` in
`protocol.ts`) take an element target with a scope: `all` the element's own
key, `device`/`shape`/`display` a geometry key's override, `aod` the key in
the element's `aod:` block (refused, naming the keys allowed, for one its
kind cannot restyle). A part's or a hand's path is an element target in the
`all` scope only: any other scope is refused ("a part has no overrides").
Beside `set`, `remove`, `rename` and the list-item ops,
`move_key` reorders a mapping entry among its siblings (block or flow; a
`parts:` entry too, so parts draw in the order shown; a part of the list
form is refused, naming `move_item`),
`rename_layout` renames a layout and every style's `layout:`, and
`delete_layout` removes a layout with the styles picking it (moving the
default to `also_default`, or refused naming it); each is one gated patch
and a batch step. A named op stays only where it carries format knowledge
the page should not repeat (a reference renamed everywhere, a refusal of
what would dangle, a swatch found or named, a preset or a set's data the
page does not hold); a change that is only primitives is a batch the page
composes: + Layout (`addLayoutSteps` in `ts/app/values.ts`: the layout,
and the styles that keep it reachable, `set` with `block`), the default
style (one `set`, the gate refusing a name no style has), and accepting a
lint warning (`lintSteps`).
A drag (`Document.drag`, `ts/src/edit/geometry.ts`) names an element by id
or a part by its tree path joined with `/`, the entered frame's item id. On
an element: `move` (its `at:`, a line's `to:` with it, or every point of a
polygon), `resize` (a size, a radius, a thickness, or a text's
`["font", "size"]`: the size of its inline font, or of its `fonts:` entry
when no other element uses it, the landing search baking the fonts again
at each candidate, so that handle is never `live`), `turn`, and on a
polygon `vertex` (one point, by a
screen delta), `add_vertex` (a point inserted after another, at a screen
position, written in the unit its neighbours use with their `anchor:`) and
`remove_vertex` (never below three points). On a part, the same gestures
through the part's own resolved geometry (`PartTarget`, `partOf`): the
screen delta is turned into the part's frame by the angle it is drawn at
(`toLocal`; `DragArgs.time` names the frame's time, the sample moment when
absent), lengths resolve against the zero-sized `HAND_FRAME` (so px and
`%r`), and the landing search checks the resolved part's own points, rounded
half away as the layout rounds them. A `mirror: x` part's point on the axis
keeps `dx` unwritten, and the whole part moves along its axis only; a
rectangle part's size and a circle's radius resize, a line's ends move apart,
an arc part turns (`start_angle` from the screen angle, `sweep` as the
author's value) and does not move. A part takes the `auto` and `all` scopes
only. The history names a part by its element: "move hour.blade of clock by
(+2, -3) px on fr955", "move vertex 2 of chevron ...", "add a vertex to ...".

The page renders the tree with the generic form (`ts/app/form.ts`, `Form`):
a field by its kind, with the control the widget names, a fieldset, a list
with its item ops or a segmented control over the branches. The store
(`ts/app/store.ts`) asks for the tree with the context's device, frame and
style and asks again when one changes; the form decides each edit's scope
from that context: `aod` for a restyled key in the AOD frame (the others
read-only there), Edit for's override scope for a geometry key, else `all`;
a hand's or a part's keys are always its own (`all`), in every frame.
Two keys get editors of their own: a `template` widget is the chip editor
(`ts/app/template-editor.ts`), which reads the template through the
compiler's `parseTemplate` and writes it whole; a field with `rules` (the
rule-list family its `$defs` entry admits: `value`, `color`, `boolean`) is
the condition editor (`ts/app/condition-editor.ts`), which reads a rule
list or a `?:` chain through `expr.ts`'s `parse` and writes a rule list,
rewriting one already written in place (`ruleListSteps`: leaf `set`s,
`insert_item`, `remove_item`, sent as one batch with any `use_color` a
picked hex needs). The pickers read the catalogue from the vocabulary
(`Words.source_info`, `Words.format_codes`).

The page names a selection by an element's id, or a hand's or part's tree
path joined with `/` (`ts/app/tree.ts`, `selectionId`), the entered frame's
item id; the store's `context.entered` is the element entered (its tree
path), which the frame ask carries as `enter`, and `selection.vertex` the
polygon point picked on the face or in Properties. Layers (`ts/app/layers.ts`)
lists hands and parts under their element, enters it (✎, double-click),
dims every row outside it while entered, leaves it (its ✓) and
reorders parts with one `move_key`; the canvas (`ts/app/canvas.ts`) draws
the entered frame's axis, ring and ray over the ghost, picks parts by their
boxes, and turns `vertex` and `segment` handles into the point gestures,
previewing a polygon's outline with the point moved or added; a drag inside
an entered element carries the frame's time (`DragArgs.time`). Escape
leaves the entered element before it deselects; Delete removes a picked
vertex before it deletes the selection.

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

- A function lives in `ts/src/kinds/<kind>.ts` if and only if only that kind
  uses it. A helper two kinds share (`Builder.build_hand_part`, preview's
  text blitting, `layout.longer`) stays in its stage module.
- A site goes through the registry if adding a kind would force an edit
  there (a ladder over kinds, a per-kind table, a list of kind names); it
  becomes a method whose default is the ladder's fall-through. A site about
  one kind's own feature stays at its call site as an `isinstance` check,
  when no second kind would plausibly need it: collecting every
  `data` element, a `graph`'s series barrel, a curved `text`
  element's rotated ink (`shapeInk`), a `data` element
  emitting its own guards (`emitElementMethod`). A friendly
  pre-schema message for one kind's common mistake is a `_check_*`
  function in `ts/src/validate.ts`, beside the others.
- Kind modules import stage modules and call only their public names
  ("Helpers for kind authors", below); an underscored name is private to
  its own module. Stage modules import the `ts/src/kinds/index.ts` package only, never
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

`ELEMENT_TYPES` in `ts/src/validate.ts` is read from `element.oneOf`, so the schema's
order is the kind order.

**2. The name** (`ts/src/kinds/base.ts`). Append `"dot"` to `NAMES`, in the
same position as its `oneOf` entry, and import the module in
`ts/src/kinds/index.ts`.

**3. The IR class** (`ts/src/ir/model.ts`). A subclass of `Element` holding
what `build` parsed. The shared fields (`id`, `at`, `visible`, `aod`, ...)
are inherited. `ownRoles` lists the element's bound expressions, which is
what reader hoisting, null guards, permissions and the palette lints read;
`Element.colorRoles` finds a field named `color` (or `track_color`,
`icon_color`, `outline`) by itself.

```ts
/** `type: dot` -- a filled disc. */
export class Dot extends Element {
  radius: Length | null = null;
  color: Expression | null = null;

  static create(init: Partial<Dot>): Dot { return make(Dot, init); }

  protected override ownRoles(): [string, Expression][] {
    return this.color ? [[ROLE_COLOR, this.color]] : [];
  }
}
```

**4. The `Placed` class** (`ts/src/layout.ts`). What `resolve` worked out for
one device, in whole pixels. `element`, `box` (what the lints check),
`center` and `depth` are inherited.

```ts
export class PlacedDot extends Placed {
  declare element: Dot;
  radius = 0;
}
```

**5. The kind module** (`ts/src/kinds/dot.ts`), the whole of it:

```ts
// `type: dot`: a filled disc of a given radius.
import type { Data, DataKey } from "../edit/yaml.ts";
import type { Builder } from "../ir/builder/index.ts";
import { Dot, type Element } from "../ir/model.ts";
import { type Placed, PlacedDot, type Resolver } from "../layout.ts";
import { AodRestyled, Const, type DrawContext, type Op, Primitive, SetColor } from "../draw/program.ts";
import { constPrefix } from "../emit/monkeyc/common.ts";
import type { Constants } from "../emit/monkeyc/layout_constants.ts";
import { Box } from "../units.ts";
import { roundHalfEven as round } from "../py.ts";
import { type Common, ElementKind, register, type SchemaPath } from "./base.ts";

class DotKind extends ElementKind<Dot> {
  readonly name = "dot";
  readonly irClass = Dot;
  override readonly antialiased = true; // drawn with a primitive, so `antialias:` applies

  build(b: Builder, node: Map<DataKey, Data>, common: Common, _path: SchemaPath): Element {
    return Dot.create({ ...common, radius: b.length(node, "radius"), color: b.colorExpression(node, "color") });
  }

  override resolve(r: Resolver, element: Dot, parent: Box, depth: number): Placed {
    const [cx, cy] = r.point(element.at, parent);
    const radius = round(r.extent(element.radius, parent, "minor", 0, null, element.resolved_min_1px, "radius"));
    const box = new Box(cx - radius, cy - radius, 2 * radius, 2 * radius);
    return PlacedDot.create({ element, box: box.rounded(), center: [round(cx), round(cy)], depth, radius });
  }

  override circularExtent(placed: Placed): [number, number, number] {
    const p = placed as PlacedDot;
    return [p.center[0], p.center[1], p.radius];
  }

  override lower(_ctx: DrawContext, placed: Placed): Op[] {
    const p = placed as PlacedDot, prefix = constPrefix(p.id);
    return [
      SetColor(AodRestyled(p.element, "color")),
      Primitive("fillCircle", [[Const(`${prefix}_CX`, p.center[0]), Const(`${prefix}_CY`, p.center[1]),
        Const(`${prefix}_RADIUS`, p.radius)]]),
    ];
  }

  override describe(_placed: Placed): string {
    return "a dot";
  }

  override layoutConstants(prefix: string, placed: Placed): Constants {
    const p = placed as PlacedDot;
    return [[`${prefix}_CX`, p.center[0], ""], [`${prefix}_CY`, p.center[1], ""], [`${prefix}_RADIUS`, p.radius, ""]];
  }
}

register(new DotKind());
```

What each part is for:

- `build` turns the schema-valid node into the IR class. `common` already
  holds every shared field; spread it in with `...common`. Report a
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
  group's ring. The printer (`ts/src/draw/printer.ts`) and the evaluator
  (`ts/src/draw/evaluator.ts`) both read it.

The rest of the interface you can ignore until the kind needs it; each
default means "nothing to do here":

| Method or attribute | Override when the kind... |
|---|---|
| `antialiased` | draws primitives (`drawCircle`, `fillPolygon`, ...), so `antialias:` becomes `Dc.setAntiAlias`; a glyph kind anti-aliases in its font instead |
| `circularExtent` | is round: the safe-area lint then checks the disc, not the box corners |
| `textRuns` | draws text or an icon glyph in a font it names: see "Fonts are one question" above |
| `staticForbidden` | can never be in a `static:` block (its picture is a series, the clock or a wearer's pick) |
| `aodRefusal` | accepts an `aod:` key in the schema it cannot honour in some configuration |
| `extraSymbols` | emits Monkey C symbols beyond its own `draw<Id>` |
| `contrastSubjects` | draws more than one ink the contrast lint should judge separately (`hands`, `pattern`) |

The contrast lint treats every kind but `shape` as glyph ink
(`Element.colorRoles`), which forbids an exact backdrop match; a kind
drawn as a solid primitive may want the `shape` rule instead.

After the code, a kind is a format change like any other: the guide
chapter and the schema together (root `CLAUDE.md` §7), a face in
`examples/features/`, and tests that drive its diagnostics red.

### Helpers for kind authors

Each stage hands a kind its own public helpers. Their signatures and
docstrings are in the code; the class docstrings of `Builder`, `Resolver`
and `Renderer` index them the same way. A name with a leading
underscore is private to its module, so a kind never calls one.

**`build`: the `Builder` (`b`, `ts/src/ir/builder/`).** A helper that can
fail reports its own error and returns `None` or an empty default.
`b.doc.span(node, key)` locates a key for a diagnostic of the kind's own,
and `b.bag` takes it. `Builder` is one class stacked from layers, one
module each (`reading`, `absence`, `glyphs`, ... `tree`), and each layer
calls only the layers beneath it. A new helper goes in the lowest layer
that has everything it calls; `index.ts` lists the order.

| Helpers | For |
|---|---|
| `expression`, `colorExpression`, `length`, `angle`, `position`, `size`, `alignment`, `bakedSizeLength` | reading one key of the node |
| `require` | a key the schema cannot require by itself |
| `checkAbsence`, `checkOtherAbsence`, `checkReachableSubstitute`, `nullableSources` | `absent:` for the value and for every other nullable binding |
| `checkFormat`, `checkFormatSpec` | a `text:` template's format spec |
| `resolveFont`, `isVectorFont`, `fontKindNote`, `checkUnsupported`, `buildCurve`, `buildOutline` | `font:`, `unsupported:`, `curve:`, `outline:` |
| `resolveIconName`, `resolveIconGlyph` | `icon:` |
| `buildElements`, `pushVisible` | a group's children |
| `buildHandPart`, `ownedColor` | a hand's or a pattern's `parts:` |
| `checkForeignKeys` | a key that belongs to another primitive type or `style:` |
| `aodRefusal` | an `aod:` key the element cannot honour |
| `dedupAppend`, `andPaths`, `ABSENCE_IS_NORMAL`, `ICON_SIZE_NOTE` (module level) | collecting colours, and diagnostic wording |

**`resolve`: the `Resolver` (`r`, `ts/src/layout.ts`).** `r.face`, `r.device`
and `r.fonts` (the baked fonts) are there to read.

| Helpers | For |
|---|---|
| `point` | an `at:` position |
| `length` | a length used as a position (`dx:`, `to:`, a polygon point) |
| `extent` | a size, thickness or radius: clamped by `min_1px:`, recorded for the `sub-pixel-length` lint |
| `aodExtent` | an `aod:` override of an extent |
| `sizedBox` | the "size, then align" box of a `size:`-placed kind |
| `textFont`, `fontForRef`, `justify` | a `font:` reference (with or without the vector-font gates), and `TEXT_JUSTIFY_*` flags |
| `resolveParts` | a hand's or a pattern's `parts:` |
| `alignmentShift`, `arcBox`, `strokePad`, `longer`, `textInk`, `resolvedCurve`, `roundHalfAway` (module level) | shared geometry |

**`lower`: the draw program (`ts/src/draw/program.ts`).** `ctx` is a
`DrawContext`: the resolved face, the build's `AodStyle`, the value's
guard locals, the ring pass to draw instead, if any. A program is built
from these, each printed by `ts/src/draw/printer.ts` and evaluated by
`ts/src/draw/evaluator.ts`; a new one needs both.

| Ops and values | For |
|---|---|
| `Const`, `Lit`, `FloatLit`, `Shifted`, `Grown`, `AodPick` | `Layout` constants, literals, a stamp's or a ring's offset, an `aod:` length |
| `NumLocal`, `Read`, `Bin`, `Paren`, `Call`, `Conv`, `NumPick` | numbers the watch computes: a reading, arithmetic, a barrel or `Math` call (`CALLS` in `ts/src/draw/barrel.ts`) |
| `Color`, `AodRestyled`, `AodDimmed`, `AodPart`, `AodPaint`, `PaintPick`, `RingColor` | colours, restyled for the always-on frame |
| `SetColor`, `SetPen`, `Primitive`, `FillPolygon`, `ArcSpan`, `ArcProgress`, `Part` | `Dc` calls and the barrel's drawing calls |
| `Text`, `Glyph`, `LoadFont`, `LetText`, `Font` and the `Str` values | text and icons |
| `Let`, `Assign`, `If`, `For`, `Continue`, `Return`, `IfAod`, `IfAwake`, `IfNotNull` and the `Cond` values | locals, loops and conditions |

**`layoutConstants`: `ts/src/emit/monkeyc/`.** The printer spells a program's
always-on choices through the build's `AodStyle` (`aod.color`, `aod.layout`,
`aod.value`, `aod.part_color`), which returns the awake code unchanged in an
awake-only build.

| Module | Helpers |
|---|---|
| `common` | `constPrefix` (the `Layout.<PREFIX>_*` prefix of an id), `fontField`, `aodFontField`, `mcColor`, `mcFloat`, `glyphYExpr`, `article`, `andList` |
| `layoutConstants` | `boxConstants`, `arcConstants`, `handPartConstants`, `aodThicknessConstant`, `EVERY_PART_NOTE` |
| `shapes` | `thicknessExpr`, `radialRadiusExpr`, `RADIAL_DIRECTION` |
| `rotated` | `emitTransformedPart`, `emitPartRing`, `aodThicknessOverride` (a hand, needle or pattern part, which the printer writes for a `Part`) |

## Tests

```sh
cd ts
npm test                 # the fast suite: node:test over test/, no Garmin toolchain
npm run typecheck        # tsc, strict; then app/ (tsconfig.app.json, strict)
npm run test:slow        # every slow-test design, example and fixture through monkeyc
npm run test:browser     # the editor's pages in headless Chromium, against a real wfb studio (ts/browser/)
```

**Node 22.23.4+, 24.22.1+ or 26.12.1+ is needed** (or a later major): the
releases before them carry known security vulnerabilities, so `wfb` refuses
to run on one (all but `wfb doctor`, which reports it) and `npm ci` refuses
to install (`ts/.npmrc` sets `engine-strict`). `ts/src/node_version.ts` holds
the table. `tools/setup-env.sh` installs an official 24.22.1 when the Node on
`PATH` is older or cannot run `.ts` files (a distribution build may lack type
stripping), and prepends it to `PATH`; CI asks `setup-node` for `^24.22.1`. How the tests are organised is
`ts/test/CLAUDE.md`.

Golden-file tests over the generated Monkey C are the primary compiler test, and
they run with **no Garmin toolchain** — which matters, because the device files
are the scarce resource (`ts/test/golden-monkeyc.test.ts`, the files in
`ts/test/goldens/monkeyc/`). `ts/test/goldens.test.ts` freezes the rest: every
diagnostic of a corpus of 2,820 small designs, most written to hit one
diagnostic (`ts/test/corpus/designs.json.gz`), and every example's and
fixture's diagnostics, generated project and previews, by hash. They are also
the proof that a refactor changed no output. Regenerate them after an
intentional change with `WFB_UPDATE_GOLDENS=1 npm test` (in `ts/`) and read the
diff of `ts/test/goldens/`.

The slow suite builds every design with the real `monkeyc` and asserts no
`monkeyc` diagnostic and a `.prg` for every device: the build bar is
warning-free, not merely successful. `ts/slow/` holds it, over
`ts/test/corpus/slow-designs.json.gz` and every example and fixture, and
runs `wfb preview --heatmap`, which renders every minute of an hour.

The browser suite (`ts/browser/`, `npm run test:browser`, not part of `npm
test`) drives `wfb studio`'s pages with Playwright in headless Chromium,
against the real server and worker: every example and template opened as a
`.yaml` or a zip, each element type selected and moved, every handle, the
Properties controls, the data editors (a template's chips, a condition's
rows, a text's own font and its size handle), the Layers actions (search,
lock and hide-in-editor, checked against the pixels the page shows and
across a reload), "accept here…" on a lint warning, every Face-tab section
(a palette label, a colour setting's inline choices), the YAML
tab (valid, invalid, a compiler error, the two-tab conflict), the view
controls, Ctrl+K, history, download and one `monkeyc` build. Every
assertion reads the face's YAML text back from the worker as well as the
DOM. Each test file starts its own server on a free port in 8780–8789 and
one browser context; `ts/browser/harness.ts` holds the helpers. It needs the
device definitions (without them every test is skipped, with a message
naming `tools/setup-env.sh`), Chromium (`npx playwright install chromium`,
or `PLAYWRIGHT_BROWSERS_PATH` pointing at one) and, for the build test,
`CIQ_SDK`. A failed test leaves a screenshot in `ts/browser/shots/`. It
takes about six minutes.

**The fixture device.** `ts/test/fixtures/devices/` holds `wfbtest`, a
round 260x260 MIP watch the project wrote itself (`compiler.json`,
`simulator.json`, a skin, its own symbol table and its device-reference
page; no Garmin file, its `README.md` says what each gives). Its system
fonts name the registry's free stand-ins, and its symbol table lists every
module, function and field the compiler asks about.
`ts/test/fixture-device.test.ts` loads, resolves, lints, generates and draws
designs on it with no other device visible. Two environment variables make
it the only device anything else sees:

```sh
export WFB_DEVICES="$PWD/ts/test/fixtures/devices"              # the device folders
export WFB_DEVICE_REFERENCE="$PWD/ts/test/fixtures/devices/reference"  # their reference pages
```

With them, every example but `features/instinct` (wfbtest has no
subscreen) resolves, lints clean and draws once its `targets:` name
`wfbtest`, and `wfb studio` opens, draws and edits such a design. `monkeyc`
does not know the id (`Invalid device id specified: 'wfbtest'`), so builds
stay on real devices. The rest of the fast suite and the browser suite are
written against the verification devices by name, and the goldens are
frozen on them, so they need the real device files.

### Continuous integration

Work lands on `main`, the development branch (pull requests target it);
the `release` branch holds the latest release and only ever moves to a
released `main` commit. Five workflows in `.github/workflows/`:

| Workflow | When | What |
|---|---|---|
| `check.yml` | called by `ci.yml` and `release.yml` | the type check and the fast suite on the fixture device, below; `npm audit` warns, and fails only a release |
| `ci.yml` | every pull request, every push to `main` and `release` | `check.yml`, then the Docker image (`docker.yml`) on pull requests and `main`. A push to `main` publishes `vvorth/garmin-wf-builder:dev` and `dev-<commit>`, and keeps the newest ten `dev-<commit>` tags. A check that already passed on the same commit (a merged pull request, `release` fast-forwarded) is not repeated |
| `docker.yml` | called by `ci.yml` and `release.yml` | builds the image for `linux/amd64` and `linux/arm64`, each on a runner of its own architecture, runs `tools/image-smoke-test.sh` on it, and with a tag to publish pushes both and joins them into one multi-arch tag |
| `release.yml` | by hand: Actions → Release → Run workflow | releases the head of `main` as `YY.M.N` (`26.10.0`, `26.10.1`, …; `N` counts the month's releases): runs the check (audit strict) and the image test, fast-forwards `release` to that commit and tags it `vYY.M.N`, writes a GitHub release listing the commits since the previous tag, publishes the image as `<version>` and `latest`, and sets the Docker Hub page's overview to `DOCKERHUB.md` and its short description |
| `audit.yml` | weekly, and by hand | `npm audit` of `ts/` on `main`; Dependabot (`.github/dependabot.yml`) opens the updates against `main`: every action update in one pull request, npm's minor and patch updates in another and its major ones in a third, never a major `@types/node` (the types follow Node 24) |

A release commits nothing: its version is the tag, the GitHub release and
the image's `org.opencontainers.image.version` label. `ts/src/version.ts`
is the compiler's own version, which every generated file's header names
(and so every golden), and changes by hand. Publishing needs two
repository secrets, `DOCKERHUB_USERNAME` and `DOCKERHUB_TOKEN` (a Docker
Hub access token with Read & Write, plus Delete for the `dev-<commit>`
clean-up and the Docker Hub page, each of which otherwise warns and fails
on its own).

`tools/image-smoke-test.sh IMAGE` runs the image with the fixture device
mounted at `/devices`: `wfb --version`, `java -version`, `monkeyc
--version`, then the slice fixture retargeted at `wfbtest` through `wfb
build --no-compile` and `wfb preview`. `monkeyc` does not know `wfbtest`,
so no `.prg` is compiled in CI.

`check.yml` runs on Node 24.22.1 or a later 24, with **no Garmin file at all**: Garmin's device
definitions are the owner's licensed copy and are never in the repository
(root `CLAUDE.md` §2). It runs on the project's own fixture device,
`wfbtest` (`ts/test/fixtures/devices/`), which `WFB_DEVICES` and
`WFB_DEVICE_REFERENCE` make the only device anything sees, and installs no
SDK, Java, device reference or Chromium: `npm ci`, the icon font and the
three system-font stand-ins `wfbtest` names (`tools/fetch-system-fonts.ts`),
then `npm run typecheck` and the fast suite's files that need no real
device.

The test step lists every file in `ts/test/`. Those that name a real device
are listed **commented out**, each group with its reason, as is the browser
suite's step:

| Runs in CI, on the fixture alone | Commented out: needs the owner's devices |
|---|---|
| `bake`, `bundle`, `data`, `doc-citations`, `draw`, `emit`, `expr`, `fixture-device`, `gate`, `kinds`, `lint`, `page-app`, `page-face`, `page-layers`, `page-modules`, `page-store`, `palette`, `py`, `units`, `uuid`, `yaml` | `aod`, `availability`, `barrel`, `cli`, `devices`, `diagnostics`, `edit`, `formatting`, `garmin-raster`, `geometry`, `golden-monkeyc`, `goldens`, `hold`, `layout`, `overrides`, `page-accept`, `page-panels`, `parameter-limits`, `protocol`, `studio`, `studio-canvas`, `studio-edits`, `studio-panels`, and the browser suite |

The second column's files name real devices (the verification devices,
`fenix847mm`, and the goldens' whole set), so on the fixture alone they
fail, mostly with `unknown device '…'.  Installed: wfbtest`. They fail
rather than skip on purpose: a skip would let a missing device turn a test
off unnoticed in the full run too. They, the browser suite and the slow
suite run locally after `tools/setup-env.sh`; `npm test` there runs every
file. A new test file that needs no real device goes in the active list; a
test that needs one goes in a file of the commented list (as `page-accept`
holds the one page test whose lint warning is measured on real watches).
To run CI's set by hand, with no Garmin file visible:

```sh
cd ts
WFB_DEVICES="$PWD/test/fixtures/devices" WFB_DEVICE_REFERENCE="$PWD/test/fixtures/devices/reference" \
  WFB_NO_GARMIN_FONTS=1 node --test test/bake.test.ts test/bundle.test.ts …   # the workflow's active list
```

## What is decided

TypeScript on Node as the host language (ADR 0001, amended); YAML canonical with a published JSON Schema and a lossless
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
