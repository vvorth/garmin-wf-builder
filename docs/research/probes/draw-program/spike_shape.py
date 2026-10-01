"""Spike: one draw program for `type: rectangle/circle/ellipse/line/arc/
polygon` (the `shape` kind), printed as Monkey C and evaluated into Pillow,
against today's two hand-written halves.

Backs docs/research/27-draw-program.md §2.5. Scope: the awake frame (no
`aod:` code), with the element's own `outline:` ring. Group rings, AOD
variants and every other kind are out of scope.

For every shape element in every example face (except the user's
playground) on fenix8solar47mm:

- **text**: the program's printer output against
  `ShapeKind.emit_draw(..., NO_AOD)`, byte for byte;
- **pixels**: the program's evaluator against `Renderer.render_element`
  (which runs `ShapeKind.draw_preview`, plus `silhouette`/`dilate` for a
  ring), at 1x and 2x.

Then a synthetic sweep of `shape: arc` start angles on half degrees,
evaluated both ways, because the two halves round the start angle in
different conventions (§2.5 of the research).

    ./.venv/bin/python docs/research/probes/draw-program/spike_shape.py
"""

from __future__ import annotations

import glob
import sys
from dataclasses import dataclass, replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[4]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from PIL import Image, ImageChops, ImageDraw  # noqa: E402

from probe import renderer_for, resolve  # noqa: E402
from wfb import kinds, preview  # noqa: E402
from wfb.devices import DeviceDatabase  # noqa: E402
from wfb.emit.monkeyc.common import NO_AOD, const_prefix, mc_color, plus  # noqa: E402
from wfb.emit.writer import Writer  # noqa: E402
from wfb.ir import disc_perimeter_offsets  # noqa: E402
from wfb.ir.model import Expression  # noqa: E402

OUT: list[str] = []


def say(line: str = "") -> None:
    print(line)
    OUT.append(line)


# -- the program --------------------------------------------------------------
#
# A number is a `Layout` constant (name + this device's value), a literal, or
# either shifted by a build-time integer.  The printer spells the first as
# `Layout.<name>`; the evaluator reads its value.


@dataclass(frozen=True)
class Num:
    value: float
    const: str | None = None      # Layout constant name, or None for a literal
    shift: int = 0
    shift_form: str = "shifted"   # "shifted" (`X - 1`) or "plus" (`X + 2`, `X - 2 * 2`)
    times: int = 1

    def code(self) -> str:
        base = f"Layout.{self.const}" if self.const else _lit(self.value)
        if self.shift_form == "plus":
            return plus(base, str(self.shift), self.times) if self.shift or self.times != 1 else base
        if self.shift == 0:
            return base
        return f"{base} {'+' if self.shift > 0 else '-'} {abs(self.shift)}"

    def eval(self) -> float:
        return self.value + self.shift * self.times

    def moved(self, d: int) -> "Num":
        return replace(self, shift=self.shift + d) if self.shift_form == "shifted" else self

    def grown(self, by: int, times: int = 1) -> "Num":
        return replace(self, shift=by, times=times, shift_form="plus")


def _lit(v: float) -> str:
    return str(int(v)) if float(v).is_integer() else repr(v)


def const(prefix: str, suffix: str, value: float) -> Num:
    return Num(value, f"{prefix}_{suffix}")


# Ops.  `group` is the printer's line wrapping: how many argument groups the
# call is split into, the same `Writer.call` the emitter uses.

@dataclass(frozen=True)
class SetColor:
    expr: Expression | None


@dataclass(frozen=True)
class SetPen:
    width: Num | None             # None: back to 1


@dataclass(frozen=True)
class Prim:
    name: str                     # Dc method, e.g. "fillRectangle"
    args: tuple[tuple[Num, ...], ...]   # wrapped argument groups


@dataclass(frozen=True)
class Polygon:
    const: str
    points: tuple[tuple[int, int], ...]


@dataclass(frozen=True)
class ArcSpan:                    # WfbArc.drawSpan
    cx: Num
    cy: Num
    radius: Num
    pen: Num
    start: Num                    # Garmin convention, as the Layout constant
    sweep: Num


@dataclass(frozen=True)
class Blank:
    pass


Op = SetColor | SetPen | Prim | Polygon | ArcSpan | Blank


# -- lowering: one place that decides what a shape draws ----------------------

_FILLABLE = {
    "rectangle": ("Rectangle", (("X", "Y"), ("WIDTH", "HEIGHT"))),
    "rounded_rectangle": ("RoundedRectangle", (("X", "Y"), ("WIDTH", "HEIGHT"), ("CORNER",))),
    "ellipse": ("Ellipse", (("CX", "CY"), ("RX", "RY"))),
    "circle": ("Circle", (("CX", "CY", "RADIUS"),)),
}
_GROWN = {"circle", "rectangle", "rounded_rectangle"}


def constants(placed) -> dict[str, float]:
    p = const_prefix(placed.id)
    return {name: value for name, value, _ in kinds.for_placed(placed).layout_constants(p, placed)}


def lower(placed) -> list[Op]:
    e = placed.element
    p = const_prefix(placed.id)
    c = constants(placed)
    C = lambda s: const(p, s, c[f"{p}_{s}"])  # noqa: E731

    def thickness() -> Num:
        if e.shape == "circle":
            return Num(placed.thickness)          # inlined literal, never a constant
        return C("THICKNESS")

    def primitive(dx: int, dy: int, set_pen: bool) -> list[Op]:
        if e.shape in _FILLABLE:
            name, groups = _FILLABLE[e.shape]
            first = groups[0]
            g0 = (C(first[0]).moved(dx), C(first[1]).moved(dy)) + tuple(C(s) for s in first[2:])
            args = (g0,) + tuple(tuple(C(s) for s in g) for g in groups[1:])
            if e.filled:
                return [Prim(f"fill{name}", args)]
            body: list[Op] = [Prim(f"draw{name}", args)]
            return ([SetPen(thickness())] + body + [SetPen(None)]) if set_pen else body
        if e.shape == "arc":
            return [ArcSpan(C("CX").moved(dx), C("CY").moved(dy), C("RADIUS"), C("THICKNESS"),
                            C("START"), C("SWEEP"))]
        if e.shape == "polygon":
            return [Polygon(f"{p}_POINTS", tuple((x + dx, y + dy) for x, y in placed.points))]
        if e.shape == "line":
            body = [Prim("drawLine", ((C("CX").moved(dx), C("CY").moved(dy),
                                       C("END_X").moved(dx), C("END_Y").moved(dy)),))]
            return ([SetPen(C("THICKNESS"))] + body + [SetPen(None)]) if set_pen else body
        raise AssertionError(e.shape)

    ops: list[Op] = []
    outline = e.outline
    if outline is not None:
        width = outline.width
        if e.shape in _GROWN and e.filled:
            ops.append(SetColor(outline.color))
            if e.shape == "circle":
                ops.append(Prim("fillCircle", ((C("CX"), C("CY"), C("RADIUS").grown(width)),)))
            else:
                corner = (C("CORNER").grown(width) if e.shape == "rounded_rectangle"
                          else Num(width))
                ops.append(Prim("fillRoundedRectangle", (
                    (C("X").grown(width, -1), C("Y").grown(width, -1)),
                    (C("WIDTH").grown(width, 2), C("HEIGHT").grown(width, 2)),
                    (corner,))))
        elif e.shape == "polygon":
            ops.append(SetColor(outline.color))
            for i, (dx, dy) in enumerate(disc_perimeter_offsets(width)):
                name = f"{p}_RING_{i}" if width == 1 else f"{p}_RING{width}_{i}"
                ops.append(Polygon(name, tuple((x + dx, y + dy) for x, y in placed.points)))
        else:
            pen = (C("THICKNESS") if e.shape == "line"
                   else thickness() if e.shape in _FILLABLE and not e.filled else None)
            if pen is not None:
                ops.append(SetPen(pen))
            ops.append(SetColor(outline.color))
            for dx, dy in disc_perimeter_offsets(width):
                ops += primitive(dx, dy, set_pen=pen is None)
            if pen is not None:
                ops.append(SetPen(None))
        ops.append(Blank())
    ops.append(SetColor(e.color))
    ops += primitive(0, 0, set_pen=True)
    return ops


# -- backend 1: Monkey C ------------------------------------------------------

def print_mc(ops: list[Op]) -> str:
    w = Writer()
    for op in ops:
        if isinstance(op, SetColor):
            w.line(f"dc.setColor({mc_color(op.expr)}, Graphics.COLOR_TRANSPARENT);")
        elif isinstance(op, SetPen):
            w.line(f"dc.setPenWidth({op.width.code() if op.width else '1'});")
        elif isinstance(op, Prim):
            w.call(f"dc.{op.name}", [", ".join(n.code() for n in g) for g in op.args])
        elif isinstance(op, Polygon):
            w.line(f"dc.fillPolygon(Layout.{op.const});")
        elif isinstance(op, ArcSpan):
            w.call("WfbArc.drawSpan", [
                f"dc, {op.cx.code()}, {op.cy.code()}, {op.radius.code()}",
                f"{op.pen.code()}, {op.start.code()}, {op.sweep.code()}"])
        elif isinstance(op, Blank):
            w.blank()
    return w.render()


# -- backend 2: Pillow, emulating Dc ------------------------------------------

def round_away(d: float) -> int:
    return int(d - 0.5) if d < 0 else int(d + 0.5)


def garmin_arc_to_pillow(start_g: float, sweep: float) -> tuple[int, int] | None:
    """`WfbArc.drawSpan`'s own arithmetic, then Garmin degrees (ccw from 3)
    turned into Pillow's (cw from 3)."""
    s = max(-360, min(360, round_away(sweep)))
    if s == 0:
        return None
    start = round_away(start_g) % 360
    if abs(s) == 360:
        return (-start, -start + 360)
    end = (start - s) % 360
    a, b = (-start, -end) if s > 0 else (-end, -start)   # clockwise in Pillow from a to b
    while b <= a:
        b += 360
    return (a, b)


def evaluate(ops: list[Op], renderer: preview.Renderer) -> None:
    s = renderer.scale
    d = renderer.draw
    color = (255, 255, 255)
    pen = 1
    for op in ops:
        if isinstance(op, SetColor):
            color = renderer.color(op.expr)
        elif isinstance(op, SetPen):
            pen = int(op.width.eval()) if op.width else 1
        elif isinstance(op, Prim):
            v = [n.eval() for g in op.args for n in g]
            fill = op.name.startswith("fill")
            width = max(1, pen * s)
            shape = op.name[4:]
            if shape in ("Rectangle", "RoundedRectangle"):
                x, y, w_, h = v[:4]
                box = [x * s, y * s, (x + w_) * s - 1, (y + h) * s - 1]
                if shape == "Rectangle":
                    d.rectangle(box, fill=color) if fill else d.rectangle(box, outline=color, width=width)
                else:
                    r = v[4] * s
                    (d.rounded_rectangle(box, radius=r, fill=color) if fill
                     else d.rounded_rectangle(box, radius=r, outline=color, width=width))
            elif shape in ("Circle", "Ellipse"):
                cx, cy = v[0], v[1]
                rx, ry = (v[2], v[2]) if shape == "Circle" else (v[2], v[3])
                box = [(cx - rx) * s, (cy - ry) * s, (cx + rx) * s, (cy + ry) * s]
                d.ellipse(box, fill=color) if fill else d.ellipse(box, outline=color, width=width)
            elif shape == "Line":
                d.line([v[0] * s, v[1] * s, v[2] * s, v[3] * s], fill=color, width=width)
            else:
                raise AssertionError(op.name)
        elif isinstance(op, Polygon):
            if len(op.points) >= 3:
                d.polygon([(x * s, y * s) for x, y in op.points], fill=color)
        elif isinstance(op, ArcSpan):
            r = op.radius.eval() * s
            span = garmin_arc_to_pillow(op.start.eval(), op.sweep.eval())
            if r > 0 and span is not None:
                cx, cy = op.cx.eval() * s, op.cy.eval() * s
                d.arc([cx - r, cy - r, cx + r, cy + r], *span, fill=color,
                      width=max(1, int(op.pen.eval()) * s))


# -- comparison ---------------------------------------------------------------

def today_mc(resolved, placed) -> str:
    w = Writer()
    kinds.for_placed(placed).emit_draw(w, resolved, placed, None, None, NO_AOD)  # type: ignore[arg-type]
    return w.render()


def pixels(resolved, placed, scale: int, program: bool) -> Image.Image:
    renderer, _ = renderer_for(resolved)
    size = (resolved.device.width * scale, resolved.device.height * scale)
    image = Image.new("RGB", size, (0, 0, 0))
    renderer.image, renderer.draw, renderer.scale = image, ImageDraw.Draw(image), scale
    renderer.options = replace(renderer.options, scale=scale)
    if program:
        # The `visible:` guard wraps `draw<Id>` in the view (`wfb.emit.
        # monkeyc.view`), outside the kind; a program would carry it as one
        # op, which here is the renderer's own check.
        if renderer.shows(placed):
            evaluate(lower(placed), renderer)
    else:
        renderer.render_element(placed)
    return renderer.image


def differing(a: Image.Image, b: Image.Image) -> int:
    diff = ImageChops.difference(a, b).convert("L").point(lambda v: 255 if v else 0)
    return sum(1 for v in diff.tobytes() if v)


def main() -> None:
    db = DeviceDatabase.discover()
    faces = sorted(f for f in glob.glob("examples/**/face.yaml", recursive=True)
                   if "examples/dashboard/" not in f)
    say("## A. every shape element in the examples (awake frame, own outline ring)")
    n = text_same = 0
    px_same = {1: 0, 2: 0}
    mismatches: list[str] = []
    by_shape: dict[str, int] = {}
    for path in faces:
        resolved = resolve(db, path)
        if resolved is None:
            continue
        for placed in resolved.shown_items:
            if placed.kind != "shape" or placed.element.aod is not None:
                continue
            n += 1
            e = placed.element
            tag = f"{e.shape}{'+ring' if e.outline else ''}{'' if e.filled else ' outlined'}"
            by_shape[tag] = by_shape.get(tag, 0) + 1
            ops = lower(placed)
            if print_mc(ops) == today_mc(resolved, placed):
                text_same += 1
            else:
                mismatches.append(f"text  {path} {placed.id} ({tag})")
            for scale in (1, 2):
                diff = differing(pixels(resolved, placed, scale, False),
                                 pixels(resolved, placed, scale, True))
                if diff == 0:
                    px_same[scale] += 1
                else:
                    mismatches.append(f"px@{scale} {path} {placed.id} ({tag}): {diff} px differ")
    say(f"{n} shape elements: " + ", ".join(f"{k} {v}" for k, v in sorted(by_shape.items())))
    say(f"Monkey C byte-identical to emit_draw: {text_same}/{n}")
    say(f"pixels identical to draw_preview: {px_same[1]}/{n} at 1x, {px_same[2]}/{n} at 2x")
    for m in mismatches:
        say("  " + m)
    say()

    say("## B. shape: arc start angles on half degrees: today's preview vs WfbArc.drawSpan's arithmetic")
    disagree = []
    for tenths in range(0, 3600, 5):
        start = tenths / 10
        for sweep in (90.0, -90.0, 45.5):
            today = preview.arc_span(start, sweep)
            garmin_start = (90.0 - start) % 360.0
            device = garmin_arc_to_pillow(garmin_start, sweep)
            norm = lambda t: None if t is None else ((t[0] % 360), (t[1] - t[0]))  # noqa: E731
            if norm(today) != norm(device):
                disagree.append((start, sweep, today, device))
    say(f"{len(disagree)} of {720 * 3} (start, sweep) pairs draw a different span")
    for start, sweep, today, device in disagree[:6]:
        say(f"  start {start:g}, sweep {sweep:g}: preview {today}, device {device} (Pillow degrees)")
    Path(__file__).with_name("spike_results.txt").write_text("\n".join(OUT) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
