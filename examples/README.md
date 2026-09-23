# Examples

Build or preview any of these:

```sh
./wfb.py build   examples/<path>/face.yaml
./wfb.py preview examples/<path>/face.yaml
```

Four faces here were designed to be worn. The rest are test beds: one was
written for each feature as it landed, to exercise and document it.

## Faces meant to be used

### [`dashboard/`](dashboard/face.yaml)

A dense, row-based digital face, modelled on a working reference face: a
two-tone clock, weather, heart rate, steps and battery in rows separated by
hairlines, with progress arcs along the bezel. The most complete of the
four, and the one whose vocabulary the others borrow.

### [`showcase/`](showcase/face.yaml)

Two faces in one, switched from the watch's own editor: a quiet analog dial
and a data-rich digital dashboard. Both draw over two shared complication
"registers" the wearer can re-point at another metric. It carries more of
the format than any other single face here.

### [`analog-custom/`](analog-custom/face.yaml)

A hand-tuned analog dial, grown out of
[`features/analog/`](features/analog/face.yaml): a custom numeral font, hour
numerals, date windows and four colour schemes. It keeps the generated
design it started from as a second layout.

### [`enduro/`](enduro/face.yaml) — work in progress

A big-clock face with a goal ring, two data clusters and battery, modelled
on the Enduro 3. Hand-written and still being shaped.

## Feature examples

[`features/`](features/) holds one face per part of the format: hands,
patterns, graphs, shapes, alignment, the on-device config axes, complication
slots and layouts. Each was written when that feature landed, so it
demonstrates the feature rather than being a design. Its header comment says
what it exercises, and the [guide](../docs/README.md) is the
reference. Each one's `name:` is `Feature <thing>`, so a sideloaded build
says what it is on the watch.

| Face | Exercises | Guide chapter |
|---|---|---|
| [`features/align/`](features/align/face.yaml) | `align:`/`vertical_align:` on every element kind that takes them | [Placement](../docs/guide/placement.md) |
| [`features/shapes/`](features/shapes/face.yaml) | every native `shape` primitive | [Shapes](../docs/guide/shapes.md) |
| [`features/graph/`](features/graph/face.yaml) | `graph` styles (line, area, bars) and series | [Progress and graphs](../docs/guide/progress-and-graphs.md) |
| [`features/analog/`](features/analog/face.yaml) | `hands:` sets, `type: hands`, a subdial, switched by style | [Analog hands](../docs/guide/analog-hands.md) |
| [`features/patterns/`](features/patterns/face.yaml) | radial and linear `pattern` repeats | [Patterns](../docs/guide/patterns.md) |
| [`features/vector-text/`](features/vector-text/face.yaml) | vector (`face:`) fonts and `curve:` | [Fonts](../docs/guide/fonts.md), [Text](../docs/guide/text.md) |
| [`features/outline/`](features/outline/face.yaml) | `outline:` on a `text` element and a pattern `shape: text` part -- the hollow idiom, a solid-interior ring, and outlined upright/angled/radial text | [Text](../docs/guide/text.md), [Patterns](../docs/guide/patterns.md) |
| [`features/complications/`](features/complications/face.yaml) | `complication.*` bindings and `on_hold: auto` | [Data](../docs/guide/data.md) |
| [`features/sun/`](features/sun/face.yaml) | a daylight `progress` bar computed from `complication.sunrise`/`sunset` expressions (blank in `wfb preview`: no sample data) | [Data](../docs/guide/data.md) |
| [`features/config/`](features/config/face.yaml) | accent/data colour and colour-scheme settings | [Configuration](../docs/guide/configuration.md) |
| [`features/slots/`](features/slots/face.yaml) | the Data setting: `complication_slot`s the wearer re-points | [Configuration](../docs/guide/configuration.md) |
| [`features/styles/`](features/styles/face.yaml) | `layouts:` switched by style | [Styles and layouts](../docs/guide/styles-and-layouts.md) |
| [`features/aod/`](features/aod/face.yaml) | `modes: [always_on]` on an AMOLED target (`fenix847mm`) -- the only example targeting AMOLED so far | [Power modes and touch-and-hold](../docs/guide/modes-and-interaction.md) |

[`system-fonts/`](system-fonts/) holds three calibration faces (`text/`,
`numbers/`, `numbers-large/`). They draw every system font as a fixed sample
on a guide line, so `wfb preview` can be compared against a simulator
screenshot pixel for pixel. They have no clock and no data, and they are
split across three faces because the largest fonts cannot share one screen.
