# draw-program probe

Backs `docs/research/27-draw-program.md`. Host-side only: it needs the
device files that `tools/setup-env.sh` installs, but no Garmin toolchain and
no simulator.

    ./.venv/bin/python docs/research/probes/draw-program/probe.py
    ./.venv/bin/python docs/research/probes/draw-program/spike_shape.py

`probe.py` writes `results.txt` (§2.1–§2.4 of the research):

1. **Per-element cost.** Each drawn element alone through
   `Renderer.render_element`, at 2×, minimum of five warm runs.
2. **Coupling.** Per face: elements in outlined groups, with their own
   `outline:`, in `static:`, scoped to a `layouts:` entry, bound to a slot,
   with `overrides:` or `aod:`; elements by kind.
3. **Vocabulary.** Every `dc.*` and `Wfb*.*` call and every `if`/`for`/
   `else`/`switch` in the generated views (`wfb build --no-compile`).
4. **Recorded calls.** Every Pillow call each element makes, through a proxy
   around `Renderer.draw` and `Renderer.image`.

`spike_shape.py` writes `spike_results.txt` (§2.5): the `shape` kind lowered
once into a small program, printed as Monkey C and compared byte for byte
with `ShapeKind.emit_draw`, then evaluated in Pillow and compared pixel for
pixel with `draw_preview` at 1× and 2×; and a sweep of half-degree arc start
angles through `preview.arc_span` and `WfbArc.drawSpan`'s arithmetic.

`layers.py` writes `layers_results.txt` (§5.4): every element, and every
outlined group's ring, rendered alone onto black and onto white; its colour
and coverage recovered from the pair; the layers stacked in draw order and
compared with `preview.render`, before and after quantise and the bezel
mask.

`spike_text.py` writes `spike_text_results.txt`
(`docs/research/28-editor-open-questions.md` §6): the same spike for
`type: text`, covering every font and value route, against
`TextKind.emit_draw` and `draw_preview`.

`examples/dashboard` is skipped (it is the user's playground).
