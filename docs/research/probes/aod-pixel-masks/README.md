# Probe: pixel-pattern masks for the AOD frame

Host-side simulation behind `docs/research/15-aod-pixel-masks.md`. It uses
no Connect IQ build: frames come from `wfb.preview.render`, the renderer
that `wfb preview --aod` and the `aod-burn-in` lint use, at device
resolution, `fenix847mm`, with `aod_mask=False` -- since plan 16 shipped,
`render()` applies the shipped mask by default, so this probe renders the
raw unmasked frame and applies every candidate mask itself (§`frames()` in
`sim.py`) to keep every row of the comparison table on the same footing.

- `sim.py <design> [minutes]` renders the AOD frame for each minute from
  10:00 and applies every mask in `MASKS`, including `"shipped(25%)"` -- the
  4-phase, 25%-duty moving 2×2 pixel mask that shipped as `aod: {mask:
  ...}` (plan 16): one pixel per on-screen 2×2 tile stays lit, stepping to
  a 4-neighbour each minute. `wfb.aod_mask` is the real implementation;
  `m_shipped` here is an independent host-side reimplementation used only
  to place it in this comparison table alongside the candidates that were
  never built. For each mask it prints:
  - `lit_max`: peak lit-pixel fraction inside the round mask.
  - `lum_max`: peak mean Rec. 709 relative luminance.
  - `longest_run`: longest run of consecutive lit minutes for any pixel.
  - `share_over_3min`: share of ever-lit pixels with a run over 3.
  - `retention`: share of the unmasked lit pixels still lit.
  - `isolated_px`: share of shown pixels with no lit 4-neighbour.
- `lines.py` checks 1 px horizontal, vertical, 45° and anti-diagonal lines
  at every phase alignment. For each mask and line it reports the worst
  visible share and how many (alignment, minute) pairs lose the line
  completely.
- `aod_nojitter.yaml` is `examples/features/aod/face.yaml` without
  `jitter:`.
- `showcase_show_dim04.yaml` is `examples/showcase` with `fenix847mm` and
  `aod: {default: show, dim: 0.4}`, the plan-14 D2 measurement copy.

Run it from this directory with the repo's `.venv/bin/python`.
