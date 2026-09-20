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
what it exercises, and [`docs/format.md`](../docs/format.md) is the
reference.

[`system-fonts/`](system-fonts/) holds three calibration faces (`text/`,
`numbers/`, `numbers-large/`). They draw every system font as a fixed sample
on a guide line, so `wfb preview` can be compared against a simulator
screenshot pixel for pixel. They have no clock and no data, and they are
split across three faces because the largest fonts cannot share one screen.
