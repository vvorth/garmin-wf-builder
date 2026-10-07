# garmin-wf-builder documentation

This is the full documentation for writing watch faces with `wfb`. Each
chapter covers one feature: what it's for, an example with a screenshot, a
table of its YAML keys, then the complete rules. Read the first three
chapters in order; after that, use the rest as a reference.

The JSON Schema, [`schema/wfb-face-2.schema.json`](../schema/wfb-face-2.schema.json),
is the normative definition of the format. The guide explains what the schema
can't: why each key exists, and what the watch does with it.

## The guide

### Start here

| Chapter | Covers |
|---|---|
| [Getting started](guide/getting-started.md) | Installing, device files, `wfb new`, building, sideloading, supported watches, troubleshooting, a glossary |
| [The design file](guide/design-file.md) | The top-level keys of a face, element mappings, versioning |
| [Preview and the command line](guide/preview-and-cli.md) | `wfb preview` and what it can't show, and every `wfb` command in one table |
| [The editor](guide/studio.md) | `wfb studio`: a face edited in the browser, on its screen, in layers and as YAML, with its history; bundles in and out |

### Layout and look

| Chapter | Covers |
|---|---|
| [Placement](guide/placement.md) | `at:`, anchors, polar positions, units (`px`, `%`, `%r`), angles, `align:` and its compass aliases |
| [Colours](guide/colors.md) | `color.<name>`, `palette:`, the 64-colour MIP rule, `theme: schemes:`, conditional colours |
| [The 64 MIP colours, named](guide/mip-palette.md) | Every colour a MIP panel shows exactly, with a name, as palette entries to paste |
| [Fonts](guide/fonts.md) | System fonts, your own TTFs converted to bitmap fonts, `monospace:`, vector (`face:`) fonts, `unsupported:` |

### Elements

| Chapter | Covers |
|---|---|
| [Elements: common keys and groups](guide/elements.md) | The element types, and the keys they share: `visible:`, `static:`, `antialias:`, `min_1px:`, plus `group` |
| [Text](guide/text.md) | `text`: the `text:` template, formats, absent readings, and rotated or radial text with `curve:` |
| [Shapes](guide/shapes.md) | Rectangles, circles, ellipses, arcs, polygons, lines |
| [Icons](guide/icons.md) | Named icons, any Nerd Fonts glyph, weather icons chosen at runtime (`icon: {for:}`) |
| [Gauges and graphs](guide/progress-and-graphs.md) | `gauge` (bar, arc, segments, scale, needle) and `graph` (history series: line, area, bars) |
| [Analog hands](guide/analog-hands.md) | `hand_sets:`, part types, the `hands` element, second-hand behaviour |
| [Patterns](guide/patterns.md) | Radial and linear repeats: ticks, numerals, skipping, text parts |
| [Outlines](guide/outlines.md) | `outline:` on every drawable and on a group: a 1–3 px ring, grown or stamped, openings included |

### Data and behaviour

| Chapter | Covers |
|---|---|
| [Data, expressions and formats](guide/data.md) | Sources (`time.*`, `activity.*`, `weather.*`, `complication.*`, …), expressions, missing values, format strings |
| [On-device configuration](guide/configuration.md) | The four `config:` settings the wearer edits (style, accent colour, data colour, data slots) in the native editor or, without one, the generated settings menu; the `data` element; what each watch supports |
| [Styles and layouts](guide/styles-and-layouts.md) | `layouts:` and named styles that combine a layout with a colour scheme |
| [Power modes and touch and hold](guide/modes-and-interaction.md) | `sleep_update:` (MIP partial updates) and `on_hold:` |
| [Always-on display](guide/always-on-display.md) | `aod:` overrides for an AMOLED target's sleep frame: one block per element, group and `defaults:` (visibility, dimming, restyling), resolution order |

### Checking your design

| Chapter | Covers |
|---|---|
| [Lints and suppression](guide/lints.md) | What `wfb validate` and `wfb build` check, and how to deliberately allow a warning with `lint: allow:` |

## Beyond the guide

| Document | For |
|---|---|
| [`limitations.md`](limitations.md) | What the platform can't do (§1), what isn't built yet (§2, the authoritative list), what the linter doesn't check (§3), and what is built but not yet seen on a watch (§4) |
| [`container.md`](container.md) | Running `wfb` from the Docker image, with no local install |
| [`development.md`](development.md) | Working on `wfb` itself: setup, the generated code, repository layout, tests |
| [`../examples/README.md`](../examples/README.md) | The example faces, and which feature each test face exercises |

## Design record

These explain why `wfb` works the way it does. They're written for
maintainers and curious readers; you don't need them to build a face.

| Directory | What it holds |
|---|---|
| [`adr/`](adr/README.md) | Architecture decision records (ADRs): the decisions, and the reasons for them |
| [`research/`](research/00-summary.md) | Investigations of the Connect IQ platform, with citations to the SDK |
| [`lore/`](lore/) | Maintainer notes: platform constraints, toolchain, compiler quirks, roadmap, working agreement |

The screenshots in these docs come from `wfb preview` on a fēnix 8 Solar
47 mm. To regenerate them, run `node ts/tools/docs-shots.ts`.
