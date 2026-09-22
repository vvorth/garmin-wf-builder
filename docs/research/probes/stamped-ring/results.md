# Stamped-ring probe results

font: examples/features/vector-text/assets/ChivoMono-Bold.ttf
freetype-py available: True

## Part 1 -- offset-set comparison, "12:34" at 80px, r = 1, 2, 3

glyph mask: 288x105 px, 5321 lit px (solid)

| r | offsets | draws | missing px | extra px | ring IoU | stamped ring px | ideal ring px | lit ratio (ring/solid) |
|---|---|---|---|---|---|---|---|---|
| 1 | square8 | 8 | 0 | 229 | 0.820 | 1275 | 1046 | 0.240 |
| 1 | cross4 | 4 | 0 | 0 | 1.000 | 1046 | 1046 | 0.197 |
| 1 | disc-filled | 4 | 0 | 0 | 1.000 | 1046 | 1046 | 0.197 |
| 1 | disc-perimeter | 4 | 0 | 0 | 1.000 | 1046 | 1046 | 0.197 |
| 2 | square8 | 8 | 0 | 480 | 0.814 | 2583 | 2103 | 0.485 |
| 2 | cross4 | 4 | 36 | 0 | 0.983 | 2067 | 2103 | 0.388 |
| 2 | disc-filled | 12 | 0 | 0 | 1.000 | 2103 | 2103 | 0.395 |
| 2 | disc-perimeter | 8 | 0 | 0 | 1.000 | 2103 | 2103 | 0.395 |
| 3 | square8 | 8 | 0 | 626 | 0.839 | 3895 | 3269 | 0.732 |
| 3 | cross4 | 4 | 213 | 0 | 0.935 | 3056 | 3269 | 0.574 |
| 3 | disc-filled | 28 | 0 | 0 | 1.000 | 3269 | 3269 | 0.614 |
| 3 | disc-perimeter | 16 | 0 | 0 | 1.000 | 3269 | 3269 | 0.614 |

## Part 2 -- FreeType's own stroker vs. raster dilation

single glyph "2" at 80px, FT_Glyph_Stroke (round cap/join):

| radius px | FT stroke ring px | raster-dilation ring px | ring IoU (FT vs raster) |
|---|---|---|---|
| 1.0 | 269 | 244 | 0.907 |
| 2.0 | 539 | 487 | 0.904 |
| 3.0 | 811 | 771 | 0.951 |

Garmin's own engine (research 13 S2.1) uses a fixed 2.0px round-join stroke. The r=2.0 row above is the directly comparable case.

## Part 3 -- rotation sweep: does offset-set quality depend on glyph angle?

Renders a single glyph ("1", chosen for its one dominant straight stroke), rotates the *mask* by theta (standing in for a radial-text glyph's own per-glyph rotation, which a fixed screen-space offset set cannot track), stamps with each offset set at r=2, and compares against the true dilation of the *rotated* mask (rotation and true dilation commute for a continuous disc, so this isolates the discrete offset set's own directional bias).

| angle deg | offset set | missing px | extra px | ring IoU |
|---|---|---|---|---|
| 0 | square8 | 0 | 39 | 0.929 |
| 0 | cross4 | 7 | 0 | 0.986 |
| 0 | disc-filled | 0 | 0 | 1.000 |
| 0 | disc-perimeter | 0 | 0 | 1.000 |
| 15 | square8 | 0 | 139 | 0.784 |
| 15 | cross4 | 6 | 0 | 0.988 |
| 15 | disc-filled | 0 | 0 | 1.000 |
| 15 | disc-perimeter | 0 | 0 | 1.000 |
| 30 | square8 | 0 | 237 | 0.660 |
| 30 | cross4 | 6 | 0 | 0.987 |
| 30 | disc-filled | 0 | 0 | 1.000 |
| 30 | disc-perimeter | 0 | 0 | 1.000 |
| 45 | square8 | 0 | 332 | 0.536 |
| 45 | cross4 | 0 | 0 | 1.000 |
| 45 | disc-filled | 0 | 0 | 1.000 |
| 45 | disc-perimeter | 0 | 0 | 1.000 |
| 60 | square8 | 0 | 255 | 0.640 |
| 60 | cross4 | 8 | 0 | 0.982 |
| 60 | disc-filled | 0 | 0 | 1.000 |
| 60 | disc-perimeter | 0 | 0 | 1.000 |
| 75 | square8 | 0 | 159 | 0.757 |
| 75 | cross4 | 6 | 0 | 0.988 |
| 75 | disc-filled | 0 | 0 | 1.000 |
| 75 | disc-perimeter | 0 | 0 | 1.000 |
| 90 | square8 | 0 | 39 | 0.929 |
| 90 | cross4 | 7 | 0 | 0.986 |
| 90 | disc-filled | 0 | 0 | 1.000 |
| 90 | disc-perimeter | 0 | 0 | 1.000 |

Spread (max - min ring IoU) across the sweep, per offset set:

| offset set | min IoU | max IoU | spread |
|---|---|---|---|
| square8 | 0.536 | 0.929 | 0.393 |
| cross4 | 0.982 | 1.000 | 0.018 |
| disc-filled | 1.000 | 1.000 | 0.000 |
| disc-perimeter | 1.000 | 1.000 | 0.000 |


## Part 4 -- stamping an anti-aliased glyph: edge alpha after overlap

original AA edge pixels (0<alpha<1): 663, mean alpha there: 0.492
stamped (max-composited) AA edge pixels: 654, mean alpha there: 0.515
Interpretation: max-compositing N opaque stamps thickens the effective edge (more pixels reach alpha 1) and raises the mean alpha of what remains a fractional edge, i.e. the anti-aliased edge gets measurably harder/thicker, never softer -- consistent with N overlapping opaque draws, never additive-blended (constraint 10, no alphaBlendingSupport on MIP).

