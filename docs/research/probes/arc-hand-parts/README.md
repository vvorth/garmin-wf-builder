# Probe: does an arc part of a hand hold together as the hand turns?

**Answer: yes for a single arc at any radius, pen and sweep, at every
half-degree of the hour hand and every step of a 31- or 60-step needle;
no for arcs that merely touch end to end (a serpentine hand), which come
apart by a pixel at some angles unless each bend overlaps its joints by
about 10° and is drawn with a pen of 2 px or more.** Measured in `wfb
preview` (the shapes fitted to simulator captures,
`docs/lore/rendering.md`; an arc's end pixels are the one part of
`drawArc` not fitted), `fenix8solar47mm`, 2026-11-05. UNVERIFIED on a
watch or in the simulator: the seams where an arc meets another part.

## Why this was asked

`dc.drawArc` takes whole degrees and truncates every parameter toward
zero. A hand's angle is a half degree every other minute (the hour hand)
or any fraction (a needle), and an arc part's turned centre is a Float.
The question was whether the rounding shows: an arc lagging its hand,
breaking into pieces, or opening a gap where it meets a stem or another
arc.

## What was run

`study.ts` (A single arcs on the hour, minute and date hands), `study2.ts`
(hand lengths of 130, 65 and 32 px; 31- and 60-step needles; fourteen
awkward cases; a full ring against a circle part; a hand arc against a
fixed `type: arc`; the half-degree overlay; `outline:`; serpentine hands),
`study3.ts` (mending a serpentine: overlap and joint dots, by pen),
`study4.ts` (zoomed joints) and `study5.ts` (the smallest overlap that
holds, by bend angle, radius and pen). Run each from `ts/` with
`WFB_NO_GARMIN_FONTS=1 node ../docs/research/probes/arc-hand-parts/<file>`.
Every frame is rendered at scale 1 and read back by colour: a part's
pixel count, how many 8-connected pieces it makes, and for the single-arc
studies the mean angle of its pixels against the hand's.

## Findings

1. **A single arc never breaks.** Every case in `summary.txt` and
   `summary2.txt` keeps one piece at all 720 half-degree hour angles:
   crescent tips at 130/65/32 px, a 2 px ring at the tip, 1° and 2°
   sweeps, a start of 350° sweeping through 0°, a negative sweep, a start
   written as −370°, even and 9 px pens, a polar `at:`, a full ring. The
   pixel count of an arc varies by at most 3 (17 for the 26 px crescent
   whose circle touches the rim, where the preview clips it).
2. **The half-degree rounding is exactly half a degree.** Over the 360
   half-degree frames the halo's and the crescent's mean angle sits
   −0.50° from the hand; over the 360 whole-degree frames, 0.00°. The
   per-frame scatter (±2–3°) is the rasterisation of a 24-pixel arc, the
   same at both parities. `D-half-degree-overlay.png` shows frames k and
   k+1 overlaid: the stem moves (red/green edges), the arc does not.
3. **On a whole degree a hand arc is pixel-identical to a fixed `type:
   arc`** at the composed angle (D2, 0 differing pixels at seven
   minutes). So `WfbArc.drawSpan`'s rounding and the preview's agree with
   the static path.
4. **A full-ring arc part is not an unfilled circle part** (D1: 96 vs 84
   pixels, 98 differing): the fitted rules differ (`drawArc` at pen 1 is
   `drawCircle`'s ring at r − ½). Use one or the other for a loop, not a
   mix.
5. **Chained arcs come apart.** A serpentine of four 12 px semicircles at
   pen 2 is in pieces at 8 of 60 seconds (whole degrees, so not the
   rounding): each arc's centre is truncated on its own, so two arcs that
   should share an end point land a pixel apart. Pen 1 bends are apart at
   54 of 60 seconds. `G-table.md` has every pen/bend/overlap combination:
   overlapping each bend 5–10° past both joints with pen ≥ 2 brings every
   case to 0 broken frames out of 720 (10° for 4 px bends); overlap never
   mends pen 1 (10–50% broken at 20°). Joint dots mend too but the 16-part
   cap on a hand leaves no room for them past five bends.
   `Z-serpentine-joints.png` shows the joints at 6× before and after.
6. **The overlap a joint needs is about half a pixel of arc, whatever the
   bend angle or pen above 1 px** (`study5.ts`, `H-min-overlap.md`: 180°,
   120° and 90° bends of 4, 8, 16 and 32 px, pens 1–3, tangent-continuous
   chains, every whole degree of the hour hand). The smallest overlap with
   no broken frame was 0.42–0.56 px along the arc in every pen-2 and pen-3
   row: 6° at 4 px, 3–4° at 8 px, 2° at 16 px, 1° at 32 px. Pen 2 and pen
   3 needed the same overlap, and the bend angle changed nothing. **Pen 1
   never held**: no overlap up to 30° brought any pen-1 chain to zero
   broken frames (a 1 px ring is only diagonally connected, so a one-pixel
   offset between neighbours is always a nick). A dot of half the pen at
   each joint mended every pen-2 and pen-3 chain but two (120° bends at
   4 and 32 px, pen 2: 8 and 9 broken of 360) and left pen 1 broken at
   1–40% of angles.
7. **`outline:` round a crescent hand** rings the stem and the crescent
   as two closed rings at every angle (E1, ring pieces always 2).
8. **The 16-part cap per hand** is what bounds a serpentine, not the
   drawing: twelve 4 px bends plus a root and a tip fit; with a dot at
   each joint they do not.

## Files

| file | what |
|---|---|
| `summary.txt`, `summary2.txt` | the printed statistics of `study.ts` and `study2.ts` |
| `G-table.md` | serpentine mending: broken frames per hand/pen/overlap |
| `H-min-overlap.md` | the smallest overlap with no broken frame, by bend angle, radius and pen, and joint dots instead |
| `hour-zoom.png` | a crescent hour hand at twelve angles, 5× |
| `A-lengths.png` | crescent hands with tips 130, 65 and 32 px from the axis |
| `B-needle-60.png` | a moon-tipped needle over 60 steps |
| `C-cases.png` | the awkward cases at four angles |
| `D-half-degree-overlay.png` | frame k (red) over k+1 (green), white where both |
| `G-mending.png`, `Z-serpentine-joints.png` | serpentine joints, unmended beside mended |
