# Probe: laying out the 64 MIP colours in two dimensions

Python 3; Pillow for the images. Each script prints
its grid as hex and writes a PNG beside itself when run from this folder.

| Script | What it settles | Run time |
|---|---|---|
| `grid-8x8-search.py` | no 8×8 layout has every neighbour pair one step apart in one channel: an exhaustive depth-first search, prints `none` | under a second |
| `grid-8x8-fold.py` | the folded 8×8 (`palette-8x8.png`): 104 unit steps and 8 two-step blue steps, verified | instant |
| `grid-16x4.py` | the 16×4 hue-by-lightness grid (`palette-16x4.png`): hue chunks, then annealing on CIELAB distance (seeded, so repeatable) | ~10 s |
| `families.py` | the six-family layout the editor's picker uses (`palette-families.png`) | instant |

`picker.png` is the editor's colour picker drawing the family layout,
captured in headless Chromium from `wfb studio` (2026-10-19).

```sh
cd docs/research/probes/mip-palette-layout
python3 -I grid-8x8-search.py
python3 -I families.py
```

The write-up is `docs/research/36-mip-palette-layout.md`.
