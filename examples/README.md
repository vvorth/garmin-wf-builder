# Examples

Every directory here holds a `face.yaml` you can build or preview:

```sh
./wfb.py build   examples/<name>/face.yaml
./wfb.py preview examples/<name>/face.yaml
```

The faces fall into two groups. Only three of them were designed as faces
you would actually wear. Almost all the others were generated after a
feature was implemented, to exercise and document that feature. They are
test beds, not designs.

## Faces meant to be used

These are the ones to start from if you want a face on your wrist.

| Face | What it is |
|---|---|
| [`dashboard/`](dashboard/face.yaml) | A dense, row-based digital face: a two-tone clock, weather, heart rate, steps, battery and status rows separated by hairlines, with progress arcs along the bezel. |
| [`analog/`](analog/face.yaml) | A hands-only dial. Several hand sets and colour schemes are switched from the watch's own face editor. |
| [`showcase/`](showcase/face.yaml) | Two faces in one, switched by Styles: a quiet analog dial and a data-rich digital dashboard, sharing two complication "registers" the wearer can re-point. |

## Feature examples

Each of these was written to demonstrate one part of the format. Its
header comment explains what it exercises. `docs/format.md` is the
reference for the features themselves.

| Face | Demonstrates |
|---|---|
| [`align/`](align/face.yaml) | `align:` and `vertical_align:` on every element kind that accepts them |
| [`complications/`](complications/face.yaml) | `complication.*` data bindings and `on_hold: auto` |
| [`config/`](config/face.yaml) | the on-device colour axes (`accent_color`, `data_color`) and `color_scheme:` |
| [`graph/`](graph/face.yaml) | `type: graph` in its line, area and bar styles |
| [`patterns/`](patterns/face.yaml) | `type: pattern`: radial and linear repeats, skips, per-copy colour and text parts |
| [`shapes/`](shapes/face.yaml) | every native primitive `shape` |
| [`slots/`](slots/face.yaml) | the Data axis: `config: data:` and `type: complication_slot` |
| [`styles/`](styles/face.yaml) | `layouts:` switched by `config: style:` |
| [`sun/`](sun/face.yaml) | a daylight `progress` arc computed from `complication.sunrise`/`sunset` (`bar.yaml` draws it as a bar) |

### Calibration faces

These draw every system font as a literal sample on a guide line, so that
`wfb preview` can be compared pixel for pixel against a simulator
screenshot. They have no clock and no data.

| Face | Fonts |
|---|---|
| [`system-fonts/`](system-fonts/face.yaml) | `FONT_XTINY` to `FONT_LARGE` |
| [`system-fonts-numbers/`](system-fonts-numbers/face.yaml) | `FONT_NUMBER_MILD`, `FONT_NUMBER_MEDIUM` |
| [`system-fonts-numbers-large/`](system-fonts-numbers-large/face.yaml) | `FONT_NUMBER_HOT`, `FONT_NUMBER_THAI_HOT` |

### Early starting points

[`big-clock-3/`](big-clock-3/face.yaml) and [`enduro/`](enduro/face.yaml)
are early hand-written drafts: a big clock, a goal ring, two data clusters
and battery. Both currently carry lint findings.
