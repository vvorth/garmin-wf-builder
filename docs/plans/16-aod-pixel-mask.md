# 16 — `aod: {mask: ...}`, a moving 2×2 pixel mask over the AOD frame

**Status: proposed, being built slice by slice (2026-09-23).** Delete this
file once every slice has shipped (`docs/CLAUDE.md`).

Research: `docs/research/15-aod-pixel-masks.md`. It replaces `jitter:`,
which was removed on 2026-09-23 (`d20b633`).

## 1. User decisions (2026-09-23)

- **D1: the pattern is the 2×2 tile `((1,0),(0,0))`, and the lit pixel moves
  every minute.** One pixel in each 2×2 tile is lit and the other three are
  forced black. Duty is 25%, and each pixel is lit for 1 minute in 4. The
  thin-line aliasing that research 15 §4 raised against 2×2 masks is
  accepted. AMOLED panels are high-DPI, so a 1 px horizontal or vertical
  line losing half its pixels, or blinking for a minute, is not a real
  problem. Queen-5 is not built.
- **D2: on by default, with an opt-out.** A face-level `aod: {mask: false}`
  turns it off. Omitting `mask:` and writing `mask: true` mean the same
  thing. Every AMOLED AOD frame is masked unless the face opts out.

## 2. The mask, exactly

A pixel (x, y) in device coordinates stays as drawn in minute m only when
`x mod 2 == dx` **and** `y mod 2 == dy`, where

```
phase    = m mod 4          (m = System.getClockTime().min, 0..59)
(dx, dy) = [(0,0), (1,0), (1,1), (0,1)][phase]
```

Every other pixel is forced to black. The cycle moves the lit pixel to a
4-neighbour each minute rather than jumping diagonally. 60 and 1440 are both
multiples of 4, so the cycle stays continuous across the hour and the day.

Properties by construction, whatever the image is:

- No pixel is lit for two consecutive minutes (a longest run of 1).
- Every pixel is lit in at most 1 minute in 4, so the `--heatmap` peak is
  ≤ 25%.
- Lit-pixel count and luminance fall to about 25% of the unmasked frame.

## 3. Device route: black strips, no bitmap

The black set is `{y mod 2 != dy} ∪ {x mod 2 != dx}`, meaning every other
row plus every other column. So the mask is two loops of 1 px
`fillRectangle` calls, drawn in black after every AOD element:

```monkeyc
for (var y = 1 - dy; y < h; y += 2) { dc.fillRectangle(0, y, w, 1); }
for (var x = 1 - dx; x < w; x += 2) { dc.fillRectangle(x, 0, 1, h); }
```

That is about `(w + h) / 2` calls: 454 on a 454×454 panel, once a minute.
Research 15 §5's M2 route (an alpha overlay bitmap) is therefore not
needed. This route needs no alpha, no `BufferedBitmap`, and no
graphics-pool memory. It uses only `Dc.fillRectangle`, `Dc.setColor`,
`Dc.getWidth`/`getHeight` and `System.getClockTime`, which exist on every
device. Anti-aliasing is turned off first (`dc has :setAntiAlias`, the same
guard `applyAntiAlias` uses) so the 1 px strips land on exact pixels.

**UNVERIFIED:**

- The watchdog budget: the limit is unpublished
  (`$CIQ_SDK/doc/docs/Monkey_C/Exceptions_and_Errors.html` says only
  "executed for too long").
- The real per-frame cost.
- How the grain looks on the panel.

The user checks these in the host simulator and on the watch (§6).

## 4. What changes

| Area | Change |
|---|---|
| schema | `$defs/faceAod/properties/mask`: boolean, default `true` |
| IR | `Face.aod_mask: bool = True` (`wfb/ir/model.py`), set in `Builder._build_face_aod` |
| runtime-lib | new `WfbAodMask.mc`, module `WfbAodMask`, `function apply(dc as Dc, minute as Number) as Void`; `BARREL_FILES` entry, pulled in by scanning the generated view for `WfbAodMask.apply(`, the same way `WfbColor.dim(` is |
| codegen | `_emit_aod_body` (`wfb/emit/monkeyc/view.py`) ends with `WfbAodMask.apply(dc, System.getClockTime().min);`, emitted only when `face.aod_mask` **and** the resolved AOD set is non-empty (masking an all-black frame is pure waste) |
| Python twin | new `wfb/aod_mask.py`: `PHASES`, `offset(minute) -> (dx, dy)`, `apply(image, minute, scale=1) -> Image` (scale-aware: device pixel = `(X // scale, Y // scale)`) |
| preview | `render` applies the mask to an `--aod` frame when `face.aod_mask` and `options.aod_mask` (new `PreviewOptions` field, default `True`), using the frame's own minute (`options.time`, else `SAMPLE`'s). `--heatmap` and `--minute` follow automatically. The mask is applied before quantise and round-masking |
| lint | `aod-burn-in` scores the **masked** frame, taking the worst over the 4 phases at each sample time (render unmasked once with `aod_mask=False`, then apply each phase), and solo attribution uses that worst phase. Its note about the 3-minute rule states the by-construction guarantee when the mask is on |
| docs | guide, lints, limitations, research 15/11, lore, root `CLAUDE.md`, examples, ADR 0006 amendment (a new on-by-default format key), screenshots |

Byte-identity guarantees, each tested:

- An all-MIP build is unchanged with or without `mask:` (the `_aod` branch
  isn't emitted at all).
- An AMOLED build with `mask: false` is byte-identical to today's output.

## 5. Slices

Each slice leaves the repo green (the fast suite minus the known failures in
`tests/CLAUDE.md`), warning-free on the verification devices plus
`fenix847mm`, and gets its own commit.

1. **Format + codegen:**
   - schema, IR, runtime-lib, emitter, barrel wiring;
   - tests: emitted-code presence and absence, both byte-identity
     guarantees, and a Python/Monkey C phase-table agreement check;
   - a real `monkeyc` build of `examples/features/aod/face.yaml`, warning-free,
     with `--build-stats` before and after;
   - the guide's format tables.
2. **Host side:** `wfb/aod_mask.py`, preview, heatmap, lint.
   - Tests: preview pixels match §2 exactly, at scale 1 and scale 3.
   - Heatmap peak ≤ 25% on the AOD example.
   - A pixel lit at minute m is black at m+1.
   - The lint's lit fraction on the example drops to about ¼ of the
     unmasked value.
   - `mask: false` restores the old numbers.
3. **Docs closeout:**
   - update the stale text in research 15 (jitter is gone; D1/D2);
   - add an ADR 0006 dated amendment;
   - update limitations, lore, root `CLAUDE.md`, `examples/CLAUDE.md` and
     the example face's comments;
   - regenerate screenshots (`tools/docs-shots.py`);
   - delete this plan and add its row to `docs/CLAUDE.md`.

## 6. Checks only the user can run

- The host simulator's Screen Heat Map on the example: no pixel above 25%
  on-time, and no watchdog trip.
- On the watch: is the grain or the once-a-minute shift visible, and is
  there moiré from the subpixel layout?
