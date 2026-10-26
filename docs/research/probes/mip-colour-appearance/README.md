# Probe: how the 64 MIP colours look on a reflective panel

Python 3, standard library; Pillow only for the images. Run from this
folder (`choose.py` and `gen-face.py` import `model.py` beside them).

| Script | What it does | Run time |
|---|---|---|
| `model.py` | the 64 on four panels (a measured 64-colour MIP module, its gamut widened to 23% NTSC, monitor-like steps, an sRGB monitor): L\*, C\*, hue and the nearest neighbour's CIEDE2000 for each; `--png` writes `appearance.png` | instant |
| `choose.py` | the five rules and the deduplication that pick the 27 a `choices: any` colour setting offers; `--png` writes `selection.png` | instant |
| `gen-face.py` | writes `face.yaml`, the 64 as a grid to sideload, a black dot on each dropped colour | instant |
| `measure.py` | reads the 64 swatches out of the four photos of `face.yaml` on a fēnix 8 Solar (`photo-ambient.jpg` at an angle and `photo-close.jpg` square-on, backlight off; `photo-backlight-1.jpg` and `-2.jpg` on); tests the step model by lightness order, fits the gamut with and without the glass's glare, re-runs the selection; `--png` writes `photos.png`; needs NumPy and SciPy | a few seconds |

`face-preview.png` is `wfb preview` of `face.yaml` on `fenix8solar47mm`.

```sh
cd docs/research/probes/mip-colour-appearance
python3 model.py --png
python3 choose.py --png
python3 gen-face.py
python3 measure.py --png
```

The write-ups are `docs/research/37-mip-colour-appearance.md` (the model
and the list) and `docs/research/38-mip-colours-on-a-watch.md` (the photos).
