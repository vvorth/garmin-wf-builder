# 20 — Rectangular and semi-octagon screens

**Status: in progress. Slice 0 done for 7 of the 13 devices; slices 1–3
and 5 done (2026-09-27); slice 4 needs decision D1.** Delete this file once every
slice has shipped (`docs/CLAUDE.md`).

Research: `docs/research/16-screen-shapes.md`. In short: 21 non-round
devices can run a face, and realistically **13 are reachable at the 3.1.0
floor** (5 rectangles: `venusq`, `venusqm`, `venusq2`, `venusq2m`, `venux1`;
8 semi-octagons: the Instinct 2/2S/2X/3/Crossover/E family and `descentg1`).
Seven are installed (slice 0), but no non-round code path has yet been
exercised against them. Semi-round (`fr230`/`235`/`630`/`735xt`) is out of scope
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
- **D2: `anchor: subscreen` -- decided and built (2026-09-27).** It places
  an element relative to the Instinct subscreen box, with `%` lengths
  relative to that box. On a device with no subscreen the element is a
  build error unless `if_unavailable: hide`, the choice a `face:` font
  already offers.
- **D3 (no decision needed, recorded):** the first 2-colour rule is "black
  and white are the only safe colours", because that is true whatever the
  firmware's mapping turns out to be. The device files agree: each
  semi-octagon's `compiler.json` `palette` is exactly `000000`, `FFFFFF`
  (research 16 §5).

## 2. What changes, by slice

### Slice 0 — device files: done for 7 of 13

Installed 2026-09-27: `venusq`, `venusq2`, `venux1`, `instinct2`,
`instinct2x`, `instinct3solar45mm`, `instincte45mm`, all above the 3.1.0
floor. Facts in research 16 §1.1, §3–§5. Not installed: `venusqm`,
`venusq2m`, `instinct2s`, `instinctcrossover`, `instincte40mm`,
`descentg1`. They are optional: each installed sibling shares its shape,
and the slices below need one of each shape. `instinct2s` (163×156) and
`instincte40mm` (166×166) are the only semi-octagons at another
resolution, so they are the ones worth adding for slice 2. To add them
later, on macOS (download them in the SDK Manager first):

```sh
cd ~/Library/Application\ Support/Garmin/ConnectIQ/Devices
cp -R venusqm venusq2m instinct2s instinctcrossover instincte40mm descentg1 \
      ~/claude/garmin-wf-builder/vendor/devices/
```

then `./tools/setup-env.sh`.

### Slice 1 — rectangles, exercised: done

No format change. Every `examples/features/*` face plus `showcase`, built
for `venusq2` and `venux1`, and nothing broke in the compiler. The errors
it raised are all correct capability diagnostics:
- `venusq2` has no `Graphics.getVectorFont`, so `outline`, `vector-text`
  and `showcase` refuse their `face:` fonts there;
- `styles` uses `modes: [low_power]`, which both AMOLED rectangles refuse
  (`partial-update`);
- every face without `aod:` gets `aod-empty` on the AMOLED rectangles.

What was added: `tests/test_screen_rectangle.py`, which resolves, lints and
previews on `venusq2`. That screen is 320×360, so the tests catch a
width/height swap, and both kinds of swap were checked to turn them red.
`examples/features/align/` gained a `venusq2` target (plus `aod: show` on its
hands) and a second screenshot in `docs/guide/placement.md`. `wfb devices`
widened its shape column for `semi-octagon`.

What the previews showed: system fonts do not scale with `%r`, and the Venu
Sq family's are large for their screens. So `align`'s date and steps
outgrow their `%r`-sized cards on `venusq`/`venusq2`, though not on
`venux1`. That is the case slice 4's `overrides:` is for. Separately,
`venusq2`'s SDK reference understates its font heights by 22–30%; its `.cft`
files are right, and layout already prefers them (research 10 §10.6).

### Slice 2 — the skin mask: done

`wfb.visible_area.visible_mask(device)` reads the skin's alpha inside
`display.location` (`Device.skin_path`/`display_location`), cached per skin.
It returns `None` when the skin is missing or does not fit. It is a
function, not the proposed `Device.visible_mask`, because `wfb.devices`
never imports Pillow.

- `inside_visible_area_for`, and so `safe-area` and `text-overflow`: on
  any non-round screen with a mask, an element fails when a pixel of its
  ink (the same `Ink` shapes the round check uses, which gained `contains`)
  lands on a pixel the skin covers along with all 8 of its neighbours.
  That one-pixel tolerance absorbs the anti-aliased rim and the Instinct 3/E
  border. Round keeps the circle and `BEZEL_MARGIN`; a test pins every
  pixel where the round skins disagree with the circle to within 1.5 px of
  the circle's edge, on `fr955`, `fenix8solar51mm` and `venu`.
- `wfb preview` greys out what the skin covers, on every non-round shape.
- The `aod-burn-in` denominator is the skin's visible pixels.
- Driven red: a dot on the Instinct subscreen's ring warns there and not on
  `fenix8solar47mm`, and a dot in the subscreen window does not warn.
  `venux1`'s rounded corner warns. Cutting each of the three paths turns
  its own test red (`tests/test_visible_area.py`).

A hand is tested as a disc of its full length, as on round screens, so a
minute hand long enough to pass under the subscreen ring is a finding.
It does pass under the ring once an hour.

### Slice 3 — two-colour panels: done

- `Color.is_palette_legal(2)` is black/white only, and `nearest_legal(2)`
  picks whichever of the two has the lower contrast ratio
  (`MONO_CROSSOVER`, relative luminance ≈ 0.179). `palette-mono` is its
  own suppressible warning, not a variant of `palette-dither`, because
  the harm is an unverified mapping rather than dithering. It covers
  `palette:`, `config:` colours and `color_scheme:` roles, through the
  same helper as `palette-dither`. 8/14/unknown sizes are a "not checked"
  note (`has_palette_rule`) instead of passing silently.
- `wfb preview` snaps a 2-colour device to black and white by the same
  crossover, and prints once per run that the mapping is a guess.
- `examples/features/instinct/` targets the four installed semi-octagons.
  It lints clean, builds warning-free (the project's first semi-octagon
  `.prg`s), and is shown in `docs/guide/colors.md`.
- Driven red: cutting the 2-colour rule, the code choice or the preview
  snap each fails its own tests (`tests/test_palette_mono.py`,
  `tests/test_palette.py`).

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

### Slice 5 — `anchor: subscreen` (D2): done

- `Device.subscreen` is `simulator.json` `subscreen.location` minus
  `display.location`. It also requires `WatchUi.getSubscreen` in the
  device's own symbol table: `instinct3amoled50mm` declares a box but has a
  virtual window, no symbol and no ring in its skin, so it has no
  subscreen (research 16 §4 corrected).
- The resolver gives a top-level `anchor: subscreen` element (a group
  takes its subtree along) the window's box as its parent. `%` is then of
  the window; `%r` stays the screen's. `anchor: subscreen` anywhere else (a
  child, `to:`, `points:`, a pattern `step:`) is an error, and so is an
  element's `if_unavailable:` with nothing that can be unavailable.
- `if_unavailable:` moved to every element. On a target without a window,
  `error` (the default) fails the build, naming the devices, from
  `lint.check_subscreen_availability`, cross-device like
  `font-unavailable`. `hide` is a note: the resolver still places the
  element (at the screen's centre, so every constant exists), marks it in
  `ResolvedFace.hidden`, and the lints and preview skip it
  (`shown_items`). Codegen emits `<ID>_SHOWN` per device and an early
  return in the draw method, only when some target lacks the window
  (`Guards.subscreen_hidden`). A hidden hold region is empty.
  `clip_for` leaves hidden items out, but never down to no clip.
- `examples/features/instinct` uses it (identical positions, identical
  `.prg` sizes). `tests/test_subscreen.py` drives every path red,
  including the `lint.run` filter (a hidden group's hold region would
  otherwise overlap the clock's on the round device). A mixed
  Instinct+fēnix build with `hide` compiles warning-free (`slow`), and the
  `tools/snapshot.py` comparison against the previous commit shows no
  output change for any face that does not use it.

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
