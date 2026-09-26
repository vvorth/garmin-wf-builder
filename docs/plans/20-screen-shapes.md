# 20 — Rectangular and semi-octagon screens

**Status: proposed (2026-09-26), not started. Slice 0 needs the user;
slices 4 and 5 need decisions D1–D2 first.** Delete this file once every
slice has shipped (`docs/CLAUDE.md`).

Research: `docs/research/16-screen-shapes.md`. In short: 21 non-round
devices can run a face, and realistically **13 are reachable at the 3.1.0
floor** (5 rectangles: `venusq`, `venusqm`, `venusq2`, `venusq2m`, `venux1`;
8 semi-octagons: the Instinct 2/2S/2X/3/Crossover/E family and `descentg1`).
None is installed, and no non-round code path has ever run against real
device files. Semi-round (`fr230`/`235`/`630`/`735xt`) is out of scope
unless slice 0 shows they are above the floor.

## 1. Decisions for the user

- **D1: `overrides:` with the format ADR 0004 §4 already accepted,
  geometry keys only at first.** Selectors are a device id or `shape:<s>`;
  `colors:`/`touch:`/`api:` come later. A geometry-only override changes
  only the per-device `Layout.mc` constants. `visible:`, `color:` and
  structural keys stay a friendly "not implemented yet" error until a
  second step. *Recommended.* The alternative, per-shape `layouts:`
  entries, would reuse the Styles machinery for something that is not a
  wearer choice, and would cost a Styles slot.
- **D2: `anchor: subscreen`**, placing an element relative to the Instinct
  subscreen box, with `%` lengths relative to that box. On a device with no
  subscreen, the element is a build error unless it opts into being hidden
  there, with the same `error|hide` choice a `fonts:` entry's
  `if_unavailable:` already offers. *Recommended*, but only after slice 0
  shows the box can be read at build time.
- **D3 (no decision needed, recorded):** the first 2-colour rule is "black
  and white are the only safe colours", because that is true whatever the
  firmware's mapping turns out to be (research 16 §5).

## 2. What changes, by slice

### Slice 0 — device files (the user, on the host)

Copy the 13 device directories from the SDK Manager's install into
`vendor/devices/`, then run `./tools/setup-env.sh`, which installs new
devices incrementally. On macOS:

```sh
cd ~/Library/Application\ Support/Garmin/ConnectIQ/Devices
cp -R venusq venusqm venusq2 venusq2m venux1 \
      instinct2 instinct2s instinct2x instinct3solar45mm instinctcrossover \
      instincte40mm instincte45mm descentg1 \
      ~/claude/garmin-wf-builder/vendor/devices/
```

Devices the SDK Manager has not downloaded are downloaded there first.
Then record each device's `connectIQVersion`, `deviceFamily`, display type
and whether its skin PNG has a subscreen hole, replacing research 16 §1.1's
UNVERIFIED rows.

### Slice 1 — rectangles, exercised

No format change.

- Build every `examples/features/*` face plus `showcase` for `venusq2` and
  `venux1` (`-d`). Fix what breaks. The research expects font sizing via
  `%r`, `deviceFamily` resource directories and the AMOLED `aod:` path on a
  non-round panel to be the likely spots.
- Add a rectangular device to the test fixtures: resolve, lint and preview
  one design on it. This is the first test anywhere with a non-round
  screen.
- `wfb devices` and `wfb doctor` show shape. They already print it; check
  it reads right.
- Add a `venusq2` target to `examples/features/align/`, the example with
  the most edge-anchored elements, and regenerate its screenshot.

### Slice 2 — the skin mask

- `Device.visible_mask`: the skin PNG's alpha inside `display.location`,
  cached per device, `None` when the skin is missing (research 16 §3).
- `inside_visible_area_for` and `safe-area`: a semi-shape (and any device
  with a mask) tests the element's ink against the mask instead of
  returning "not checked". Round keeps its analytic circle and
  `BEZEL_MARGIN`. A parity test pins the mask to the circle within the
  measured 0.5% on `fr955`, `fenix8solar51mm` and `venu`.
- `wfb preview`: crop to the mask, so a semi-octagon preview shows what the
  bezel hides.
- `aod-burn-in`: the denominator is the mask, which closes `wfb/lint.py`'s
  "not exactly the true visible area on a semi-shape" caveat.
- Drive the new diagnostic red: one element placed under the Instinct bezel
  corner must warn, and the same element on a round device must not.

### Slice 3 — two-colour panels

- New lint `palette-mono`: on a `display_colors == 2` device, any colour
  other than `#000000`/`#FFFFFF` is a warning, suppressible, naming the
  nearest by luminance. `Color.is_palette_legal`/`nearest_legal` gain the
  2-colour rule; 14 colours stays "not checked".
- The preview's `quantise` step snaps to black/white on those devices, and
  prints once that the mapping is a guess.
- One semi-octagon target in a new `examples/features/instinct/` face that
  lints clean, built warning-free.

### Slice 4 — `overrides:` (D1)

- Schema: `overrides:` on any element, keyed by a device id or
  `shape:<round|rectangle|semi-octagon|semi-round>`, whose value is a
  subset of that element's geometry keys (`at`, `size`, `radius`, `align`,
  `vertical_align`, `font` size). Deep-merged at resolve time, device id
  over shape selector over the base.
- Unknown device id, a selector no target matches (a lint:
  `override-unreachable`), and a non-geometry key are each a friendly
  error.
- Resolved in `wfb/layout.py` per device. The emitter needs nothing new,
  because the values are already per-device `Layout.mc` constants. Prove
  that with `tools/snapshot.py`: an override-free face must be
  byte-identical.
- `docs/guide/placement.md` "Per-device and per-shape overrides"; ADR 0004
  §4 amended with a dated note saying what shipped.

### Slice 5 — `anchor: subscreen` (D2)

Only if slice 0 shows the box is readable from the skin mask. Otherwise it
needs a small `Layout` constant filled in from `WatchUi.getSubscreen()` at
runtime, which is a different design and would be re-planned.

## 3. Docs, in the same commits

`docs/limitations.md` §2 "Screen shapes" (rewritten per slice); ADR 0004
Open; `docs/guide/placement.md`; `docs/guide/lints.md` for the new lints;
`docs/lore/roadmap.md`; root `CLAUDE.md` §1 if the reachable-device count
changes.

## 4. Checks only the user can run

- That a 2-colour Instinct renders a non-black, non-white colour the way
  the preview guesses. The user owns no Instinct, so this stays open, and
  the guide says so.
- A rectangle face on a real Venu Sq 2 / Venu X1. Also out of reach; slice 1
  is verified by warning-free builds and preview only.
