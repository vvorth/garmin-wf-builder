"""Spike: one draw program for `type: text`, printed as Monkey C and
evaluated into Pillow, against today's two hand-written halves.

Backs docs/research/28-editor-open-questions.md §7. Scope, as for the
`shape` spike: the awake frame (no `aod:` code), with the element's own
`outline:` ring. It covers every font route a `text` element has --
a baked `fonts:` entry, a system `FONT_*`, a `face:` (vector) font upright,
`curve: angled` and `curve: radial` -- and every value route: a literal, a
formatted reading, several readings concatenated, and a `placeholder`/
`fallback` substitution under the element's null guards. A ring is drawn
from its baked ring font where the build has one, else stamped.

For every text element in every example face (except the user's
playground) on fenix8solar47mm:

- **text**: the printer against `TextKind.emit_draw(..., NO_AOD)` with the
  same `value_guards` the view passes, byte for byte;
- **pixels**: the evaluator against `Renderer.render_element`, at 1x and 2x.

The element's `visible:`/absence guards are printed by the view's wrapper
(`wfb.emit.monkeyc.view`), outside the kind, in both today's code and here;
the evaluator applies them as one "skip" check, as the `shape` spike does.

    ./.venv/bin/python docs/research/probes/draw-program/spike_text.py
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
from wfb import expr, formatting, kinds, preview  # noqa: E402
from wfb.catalog import Type  # noqa: E402
from wfb.devices import DeviceDatabase  # noqa: E402
from wfb.emit.monkeyc import shapes  # noqa: E402
from wfb.emit.monkeyc.common import NO_AOD, const_prefix, font_field, glyph_y_expr, mc_color  # noqa: E402
from wfb.emit.monkeyc.readplan import ReadPlan  # noqa: E402
from wfb.emit.monkeyc.view import _NO_GUARDS  # noqa: E402,F401
from wfb.emit.writer import Writer  # noqa: E402
from wfb.ir import disc_perimeter_offsets  # noqa: E402
from wfb.ir.model import Expression  # noqa: E402
from wfb.kinds.text import baked_ring, baked_ring_local  # noqa: E402

OUT: list[str] = []


def say(line: str = "") -> None:
    print(line)
    OUT.append(line)


# -- values: a string the op draws ----------------------------------------------

@dataclass(frozen=True)
class Lit:
    text: str


@dataclass(frozen=True)
class Reading:
    spec: str
    value: Expression
    unit: Expression | None = None


@dataclass(frozen=True)
class Concat:
    parts: tuple[Lit | Reading, ...]


@dataclass(frozen=True)
class Var:
    name: str


Str = Lit | Reading | Concat | Var


def str_code(s: Str) -> str:
    if isinstance(s, Lit):
        return f'"{s.text}"'
    if isinstance(s, Reading):
        return formatting.emit(s.spec, s.value.code, s.value.value.type,
                               unit_code=s.unit.code if s.unit is not None else None)
    if isinstance(s, Concat):
        return " + ".join(str_code(p) for p in s.parts)
    return s.name


def str_eval(s: Str, values: dict, env: dict) -> str | None:
    if isinstance(s, Lit):
        return s.text
    if isinstance(s, Reading):
        t = s.value.value.type
        if t in (Type.TIME, Type.DATE):
            return formatting.render(s.spec, None, t, values)
        v = expr.evaluate(s.value.ast, values) if s.value.ast else None
        if v is None:
            return None
        unit = (str(expr.evaluate(s.unit.ast, values))
                if s.unit is not None and s.unit.ast is not None else None)
        return formatting.render(s.spec, v, t, values, unit_text=unit)
    if isinstance(s, Concat):
        parts = [str_eval(p, values, env) for p in s.parts]
        return None if any(p is None for p in parts) else "".join(parts)  # type: ignore[arg-type]
    return env[s.name]


# -- ops ----------------------------------------------------------------------------

@dataclass(frozen=True)
class Font:
    """Where a draw's font comes from: a view field (baked or vector,
    nullable) or a system `Graphics.FONT_*`."""
    code: str                       # the Monkey C a call names it by
    baked: str | None = None        # resolved.fonts key (baked sheet)
    metric: object = None           # FontMetric, for a system or vector face


@dataclass(frozen=True)
class Comment:
    text: str


@dataclass(frozen=True)
class LetText:                      # var text = initial; if (guards) { text = value; }
    initial: Str
    value: Str
    guards: tuple[str, ...]


@dataclass(frozen=True)
class LoadFont:                     # var <local> = _<field>; + a null check
    local: str
    field: str
    on_null: str                    # "return" (baked) or "wrap" (vector / ring font)


@dataclass(frozen=True)
class SetColor:
    expr: Expression | None


@dataclass(frozen=True)
class Text:                         # dc.drawText / drawAngledText / drawRadialText
    x: str
    y: str
    dx: int
    dy: int
    font: Font
    text: Str
    justify: tuple[str, ...]
    valign: str
    style: str | None = None        # None, "angled", "radial"
    angle: str | None = None
    angle_value: float = 0.0
    radius: str | None = None
    radius_value: int = 0
    direction: str | None = None
    box: object = None              # the preview's "no glyph source" outline


@dataclass(frozen=True)
class Block:                        # if (<local> != null) { body }
    test: str
    body: tuple


@dataclass(frozen=True)
class Blank:
    pass


def lower(resolved, placed, value_guards) -> list:
    e = placed.element
    p = const_prefix(placed.id)
    X, Y = f"Layout.{p}_X", f"Layout.{p}_Y"
    ops: list = []
    if e.literal is not None:
        text: Str = Lit(e.literal)
    else:
        segs = e.segments()
        first = Reading(e.format or "{}", e.value, e.unit_label)
        text = first if len(segs) == 1 else Concat((first,) + tuple(
            Reading(spec, v) for v, spec in segs[1:]))
        if e.when_absent in ("placeholder", "fallback") and value_guards:
            if e.when_absent == "placeholder":
                ops.append(Comment("when_absent: placeholder"))
                initial: Str = Lit(e.placeholder)
            else:
                initial = Reading(e.format or "{}", e.fallback, e.unit_label)
                ops.append(Comment("when_absent: fallback"))
            ops += [LetText(initial, text, tuple(value_guards)), Blank()]
            text = Var("text")

    vector = placed.font.is_vector
    if vector:
        font = Font("font", metric=placed.font.metric)
    elif placed.font.is_custom:
        font = Font("font", baked=placed.font.reference, metric=placed.font.metric)
        ops += [LoadFont("font", font_field(placed.font.reference), "return"), Blank()]
    else:
        font = Font(f"Graphics.{placed.font.reference}", metric=placed.font.metric)

    curve = placed.curve
    common = dict(font=font, text=text, justify=tuple(placed.justify), valign=e.vertical_align,
                  style=curve.style, box=placed.inner_box)
    if curve.style is not None:
        common.update(angle=f"Layout.{p}_ANGLE", angle_value=curve.angle_garmin,
                      direction=curve.direction)
        if curve.style == "radial":
            common.update(radius=f"Layout.{p}_RADIUS", radius_value=curve.radius_px)

    def draw(dx: int, dy: int, f: Font = font) -> Text:
        return Text(X, Y, dx, dy, **{**common, "font": f})

    body: list = []
    outline = e.outline
    if outline is not None:
        ring_font = None if vector else baked_ring(e, resolved.face, outline.width)
        if ring_font is None:
            body.append(SetColor(outline.color))
            body += [draw(dx, dy) for dx, dy in disc_perimeter_offsets(outline.width)]
        else:
            local = baked_ring_local(outline.width)
            rf = Font(local, baked=ring_font, metric=placed.font.metric)
            body.append(LoadFont(local, font_field(ring_font), "wrap"))
            body.append(Block(f"{local} != null", (SetColor(outline.color), draw(0, 0, rf))))
        body.append(Blank())
    body += [SetColor(e.color), draw(0, 0)]
    if vector:
        ops += [LoadFont("font", font_field(placed.font.reference), "wrap"),
                Block("font != null", tuple(body))]
    else:
        ops += body
    return ops


# -- backend 1: Monkey C ----------------------------------------------------------

def print_mc(ops: list) -> str:
    w = Writer()
    _print(w, ops)
    return w.render()


def _shift(expr_: str, d: int) -> str:
    return shapes.shifted(expr_, d)


def _print(w: Writer, ops) -> None:
    for op in ops:
        if isinstance(op, Comment):
            w.comment(op.text)
        elif isinstance(op, LetText):
            w.line(f"var text = {str_code(op.initial)};")
            with w.block(f"if ({' && '.join(f'{g} != null' for g in op.guards)})"):
                w.line(f"text = {str_code(op.value)};")
        elif isinstance(op, LoadFont):
            w.line(f"var {op.local} = _{op.field};")
            if op.on_null == "return":
                with w.block(f"if ({op.local} == null)"):
                    w.line("return;  // the font resource failed to load")
        elif isinstance(op, SetColor):
            w.line(f"dc.setColor({mc_color(op.expr)}, Graphics.COLOR_TRANSPARENT);")
        elif isinstance(op, Block):
            with w.block(f"if ({op.test})"):
                _print(w, op.body)
        elif isinstance(op, Blank):
            w.blank()
        elif isinstance(op, Text):
            x, y = _shift(op.x, op.dx), _shift(op.y, op.dy)
            justify = " | ".join(f"Graphics.{f}" for f in op.justify)
            value = str_code(op.text)
            if op.style == "angled":
                w.call("dc.drawAngledText", [f"{x}, {y}, {op.font.code}, {value}",
                                             f"{justify}, {op.angle}"])
            elif op.style == "radial":
                direction = shapes.RADIAL_DIRECTION[op.direction or "clockwise"]
                radius = shapes.radial_radius_expr(op.radius, op.valign, op.direction,
                                                   op.font.code)
                w.call("dc.drawRadialText", [f"{x}, {y}, {op.font.code}, {value}",
                                             f"{justify}, {op.angle}, {radius}",
                                             f"Graphics.{direction}"])
            else:
                w.call("dc.drawText", [f"{x}, {glyph_y_expr(y, op.valign, op.font.code)}, "
                                       f"{op.font.code}", value, justify])


# -- backend 2: Pillow, emulating Dc's text calls --------------------------------

def evaluate(ops, renderer, consts: dict[str, float], env: dict | None = None) -> None:
    env = {} if env is None else env
    state = {"color": (255, 255, 255)}

    def num(name: str) -> float:
        return consts[name.removeprefix("Layout.")]

    for op in ops:
        if isinstance(op, LetText):
            value = str_eval(op.value, renderer.values, env)
            env["text"] = value if value is not None else str_eval(op.initial, renderer.values, env)
        elif isinstance(op, SetColor):
            state["color"] = renderer.color(op.expr)
        elif isinstance(op, Block):
            evaluate(op.body, renderer, consts, env)
        elif isinstance(op, Text):
            text = str_eval(op.text, renderer.values, env)
            if text is None:
                continue
            anchor = (int(num(op.x)) + op.dx, int(num(op.y)) + op.dy)
            align = ("left" if "TEXT_JUSTIFY_LEFT" in op.justify
                     else "right" if "TEXT_JUSTIFY_RIGHT" in op.justify else "center")
            box = op.box if (op.dx, op.dy) == (0, 0) else None
            if op.style is not None or (op.font.baked is None and op.font.code == "font"):
                renderer.draw_vector_text(text, anchor, align, op.valign, op.font.metric,
                                          state["color"], op.style, op.angle_value,
                                          op.radius_value, op.direction, box=box)
            else:
                font = renderer.resolved.fonts.get(op.font.baked) if op.font.baked else None
                renderer.draw_text(font, text, anchor, align, op.valign,
                                   None if font is not None else op.font.metric,
                                   state["color"], box=box)


# -- comparison ---------------------------------------------------------------------

def today_mc(resolved, placed, plan) -> str:
    w = Writer()
    kinds.for_placed(placed).emit_draw(w, resolved, placed, plan.value_guards(placed), plan,
                                       NO_AOD)
    return w.render()


def pixels(resolved, placed, scale: int, program: bool, plan) -> Image.Image:
    renderer, _ = renderer_for(resolved)
    image = Image.new("RGB", (resolved.device.width * scale, resolved.device.height * scale))
    renderer.image, renderer.draw, renderer.scale = image, ImageDraw.Draw(image), scale
    renderer.options = replace(renderer.options, scale=scale)
    if not program:
        renderer.render_element(placed)
        return renderer.image
    e = placed.element
    # The view's wrapper guards: `visible:`, and "hide" when the value is absent.
    if not renderer.shows(placed):
        return renderer.image
    ops = lower(resolved, placed, plan.value_guards(placed))
    if e.literal is None and e.when_absent not in ("placeholder", "fallback"):
        probe = Concat(tuple(Reading(s, v) for v, s in e.segments()))
        if str_eval(probe, renderer.values, {}) is None:
            return renderer.image
    p = const_prefix(placed.id)
    consts = {n: v for n, v, _ in kinds.for_placed(placed).layout_constants(p, placed)}
    evaluate(ops, renderer, consts)
    return renderer.image


def differing(a: Image.Image, b: Image.Image) -> int:
    d = ImageChops.difference(a, b).convert("L")
    return sum(1 for v in d.tobytes() if v)


def main() -> None:
    db = DeviceDatabase.discover()
    faces = sorted(f for f in glob.glob("examples/**/face.yaml", recursive=True)
                   if "examples/dashboard/" not in f)
    say("## A. every text element in the examples (awake frame, own outline ring)")
    n = text_same = 0
    px_same = {1: 0, 2: 0}
    routes: dict[str, int] = {}
    misses: list[str] = []
    for path in faces:
        resolved = resolve(db, path)
        if resolved is None:
            continue
        plan = ReadPlan(resolved, _NO_GUARDS)
        for placed in resolved.shown_items:
            if placed.kind != "text" or placed.element.aod is not None:
                continue
            e = placed.element
            n += 1
            font = ("vector" if placed.font.is_vector else
                    "baked" if placed.font.is_custom else "system")
            route = (f"{font}{'/' + placed.curve.style if placed.curve.style else ''}"
                     f"{' literal' if e.literal is not None else ' +more' if e.more else ''}"
                     f"{' ' + e.when_absent if e.when_absent in ('placeholder', 'fallback') else ''}"
                     f"{' +ring' if e.outline else ''}")
            routes[route] = routes.get(route, 0) + 1
            if print_mc(lower(resolved, placed, plan.value_guards(placed))) == \
                    today_mc(resolved, placed, plan):
                text_same += 1
            else:
                misses.append(f"text  {path} {placed.id} ({route})")
            for scale in (1, 2):
                d = differing(pixels(resolved, placed, scale, False, plan),
                              pixels(resolved, placed, scale, True, plan))
                if d == 0:
                    px_same[scale] += 1
                else:
                    misses.append(f"px@{scale} {path} {placed.id} ({route}): {d} px differ")
    say(f"{n} text elements by route: " + ", ".join(f"{k} {v}" for k, v in sorted(routes.items())))
    say(f"Monkey C byte-identical to emit_draw: {text_same}/{n}")
    say(f"pixels identical to draw_preview: {px_same[1]}/{n} at 1x, {px_same[2]}/{n} at 2x")
    for m in misses:
        say("  " + m)
    Path(__file__).with_name("spike_text_results.txt").write_text("\n".join(OUT) + "\n",
                                                                  encoding="utf-8")


if __name__ == "__main__":
    main()
