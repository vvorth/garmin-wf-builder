# 23 — `outline:` on every drawable

**Status:** in progress on branch `outline-everything`. The research is
`docs/research/19-outline-everything.md`. Delete this file once every slice
has landed (`docs/CLAUDE.md`).

## 1. Decisions (user, 2026-09-29)

- **D1. One key.** One `outline:` key on every drawable and on `group`, with
  the grammar text already has: `none`, a colour (2 px implied), or
  `{color, width: 1–3}`.
- **D2. The enlarged copy only where it is mathematically the dilation:**
  - a filled `circle` (`r + w`);
  - a filled `rectangle` (a rounded rectangle, corner radius `w`, grown by
    `w`);
  - a rounded `rectangle` (corner radius recalculated to `r + w`).

  Everything else uses the stamp, the exact dilation of the drawn pixels:
  - ellipses, whose offset curve is not an ellipse;
  - stroked shapes;
  - lines and arcs, whose end caps are undocumented;
  - polygons, which have sharp angles;
  - glyphs.
- **D3. Hands outline whole.** Each hand is ringed as one silhouette: every
  part's ring, then its parts.
- **D4. Order:** icon, shape, hands, group, then pattern and gauge.
  `data` and `graph` get a friendly "not implemented" error.
- **D5. A group's ring includes its members' own rings.** The group pass
  dilates each member by the group's width plus the member's own ring
  width (and plus any outlined group in between).

## 2. Mechanism

- **IR.** `Element.outline`, built generically in
  `ElementTree._build_element` (text keeps building its own). Each kind's
  `ElementKind.outline` says whether it accepts one.
- **Codegen.**
  - Each outline-capable kind's `emit_draw` takes a `ring: RingPass | None`.
    With a ring, the kind emits only its silhouette dilated by
    `ring.width`, in `ring.color` (analytic or stamp, per D2).
  - An element's own ring is drawn by its own method, ahead of its interior.
  - A group's ring pass is a `ring<Id>(dc{args}, offsets, width, color)`
    method per member, with the member's own guard preamble. The frame
    methods call these for every member of an outlined group, just before
    the group's first member. An outlined group's members must all be
    static or all dynamic.
- **Layout.** A ring grows the element's box by its width. A group's ring
  grows every member's box by the group's width.
- **Preview.** An outlined element or group is rendered as a layer. Its
  touched-pixel mask is stamped at the `disc-perimeter` offsets in the ring
  colour, then the layer is pasted. This is the stamp's own arithmetic, so
  it previews the analytic cases to within rasterisation.
- **AOD.** The awake ring carries over into the AOD frame, dimmed like
  every AOD colour. `aod: {outline: ...}` stays text-only.

## 3. Slices

1. IR, schema and lowering; icon and shape rings; preview; box growth.
2. Hands.
3. Group two-pass.
4. `pattern` (each copy ringed whole, like a hand) and `gauge`, element-level.
   Per-part `outline:` on non-text parts stays reserved.
5. Docs sweep, example face and screenshot; delete this plan.
