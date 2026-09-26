"""`hands:` sets and the part vocabulary a hand and a `pattern`
template share, with the per-shape key and rejection-reason tables."""

from __future__ import annotations

from typing import Any

from ... import expr
from ...catalog import Type
from ...diagnostics import Span

from ..model import (
    Curve, Expression, AnyHandPart, ArcPart, CirclePart, Hand, HandSet, LinePart,
    PolygonPart, RectanglePart, TextPart,
    Outline, Position,
)
from .state import and_paths
from .config import ConfigAxes

#: The same table for a hand part -- the four rotatable primitives, in the
#: hand's own frame.  `polygon` has no `at`: its vertices are already
#: positions in that frame.  `align`/`vertical_align` only on the
#: box-drawn `rectangle`/`circle` (resolved by
#: `Resolver._resolve_hand_part` before rounding).
HAND_PART_GEOMETRY_KEYS = {
    "polygon": frozenset({"points"}),
    "rectangle": frozenset({"at", "size", "align", "vertical_align"}),
    "line": frozenset({"at", "to"}),
    "circle": frozenset({"at", "radius", "align", "vertical_align"}),
}
_ALL_HAND_PART_GEOMETRY_KEYS = frozenset().union(*HAND_PART_GEOMETRY_KEYS.values())

#: Hand part shapes that accept `filled:` at all (`line` has no notion of it).
HAND_PART_FILLED_SHAPES = frozenset({"polygon", "rectangle", "circle"})

#: Shapes for which `filled: false` is refused -- a rectangle part becomes a
#: polygon at build time, and Dc has no `drawPolygon`.
HAND_PART_NO_UNFILLED = frozenset({"polygon", "rectangle"})

#: `shape:` values the hand-part schema accepts only so that this
#: dedicated message fires instead of a blunt enum mismatch.
HAND_PART_REJECTED_SHAPES = {
    "rounded_rectangle": "no Dc call draws a rotated rounded rectangle -- "
                          "approximate it with 'polygon'",
    "ellipse": "no Dc call draws a rotated ellipse -- approximate it with 'polygon'",
    "arc": "an arc part would need its start angle to rotate with the hand too, "
           "which is not implemented yet (docs/limitations.md) -- "
           "approximate a wedge with 'polygon', or use 'circle' for a disc",
    "text": "a bitmap font cannot rotate",
    "icon": "a bitmap font cannot rotate",
}

#: A `type: pattern` template part: the hand vocabulary plus `arc` (a
#: copy's start angle is a plain runtime Float) and `text` (upright glyphs
#: whose anchor turns or steps with the copy; the glyphs themselves turn
#: too with a `face:` font and `curve:`).  `value` xor `text` is enforced
#: by `Builder._build_text_part`, not this table.
PATTERN_PART_GEOMETRY_KEYS = {
    **HAND_PART_GEOMETRY_KEYS,
    #: No `at` -- an arc part is always centred on the copy's own origin.
    "arc": frozenset({"radius", "start_angle", "sweep"}),
    "text": frozenset({"at", "value", "text", "format", "font", "align", "vertical_align",
                       "curve", "if_unavailable", "outline"}),
}
_ALL_PATTERN_PART_GEOMETRY_KEYS = frozenset().union(*PATTERN_PART_GEOMETRY_KEYS.values())

#: The extra note `_check_hand_part_keys` adds when the rejected key is
#: `align`/`vertical_align` -- shared by hand and pattern parts (`arc` is
#: only ever reached by a pattern part).
_HAND_PART_NO_ALIGNMENT_REASON = {
    "polygon": "every vertex is its own position; there is no single 'at:' "
               "to align on -- a polygon part has no 'at:' of its own either",
    "line": "'at:' and 'to:' are the part's two ends",
    "arc": "an arc part is always centred on the copy's own origin -- there "
           "is no 'at:' to offset in the first place",
}

#: Like `HAND_PART_REJECTED_SHAPES`, minus `arc` and `text`, which a pattern
#: part can draw.
PATTERN_PART_REJECTED_SHAPES = {
    "rounded_rectangle": "no Dc call draws a rotated or translated rounded "
                          "rectangle -- approximate it with 'polygon'",
    "ellipse": "no Dc call draws a rotated or translated ellipse -- "
               "approximate it with 'polygon'",
    "icon": "a bitmap font cannot rotate or translate through this loop",
}


class HandParts(ConfigAxes):
    """The `hands:` block and hand/pattern parts."""

    # -- hands --------------------------------------------------------------

    def _build_hands(self, raw: dict[str, Any]) -> None:
        """`hands:` -- named analog-hand sets, declared once, placed by name.

        The same declared/rejected cascade every other named block keeps
        (`fonts:`, `color_scheme:`, `layouts:`, via `NamedRegistry`): a set
        rejected for its own fault stays bound in `hand_sets.declared`,
        so a `type: hands` element naming it gets exactly one error, at the
        real mistake (`docs/lore/codegen.md`).
        """
        for name, spec in raw.items():
            span = self.doc.span(raw, name)
            self.hand_sets.declare(name, span)
            ok = True
            hands: dict[str, Hand | None] = {}
            for hand_name in ("hour", "minute", "second"):
                if hand_name not in spec:
                    hands[hand_name] = None
                    continue
                hand = self._build_hand(spec[hand_name], name, hand_name)
                if hand is None:
                    ok = False
                    continue
                hands[hand_name] = hand
            if ok and all(hand is None for hand in hands.values()):
                self.bag.error(
                    "hands",
                    f"hands.{name}: declares none of hour, minute or second",
                    span,
                    notes=["a hand set is a shape, like a fonts: entry -- it needs at "
                           "least one hand to be worth placing",
                           "a set with only 'second:' is a valid small-seconds subdial"],
                )
                ok = False
            if not ok:
                self.hand_sets.reject(name)
                continue
            self.hand_sets[name] = HandSet(
                name=name, hour=hands["hour"], minute=hands["minute"],
                second=hands["second"], span=span,
            )

    def _build_hand(self, spec: dict[str, Any], set_name: str, hand_name: str) -> Hand | None:
        """One `hour:`/`minute:`/`second:` entry of a `hands:` set."""
        where = f"hands.{set_name}.{hand_name}"
        hand_color, color_failed = self.owned_color(spec, where, hand=True)
        ok = not color_failed
        parts: list[AnyHandPart] = []
        for index, raw_part in enumerate(spec.get("parts") or []):
            part = self.build_hand_part(raw_part, where, index, hand_color, color_failed)
            if part is None:
                ok = False
                continue
            parts.append(part)
        if not ok:
            return None
        return Hand(parts=parts, color=hand_color)

    def owned_color(
        self, node: dict[str, Any], where: str, *, hand: bool,
    ) -> tuple[Expression | None, bool]:
        """`color:` on a hand, a pattern, or one of their parts, as
        `(color, failed)`.

        `failed` means `color:` was written and did not survive (its error
        already reported) -- kept apart from "not declared" so a part with
        no colour of its own does not also get a cascading "no colour" error
        for a mistake made one level up ("one error, not N").  A hand colour
        (`hand=True`) additionally may not read data at all
        (`_reject_hand_data_color`).
        """
        if "color" not in node:
            return None, False
        color = self.color_expression(node, "color")
        if color is None:
            return None, True
        if hand and self._reject_hand_data_color(color, where, self.doc.span(node, "color")):
            return None, True
        return color, False

    def _reject_hand_data_color(self, color: Expression, where: str, span: Span | None) -> bool:
        """A hand colour may not read a data source at all -- a hand is
        about the time, with no `when_absent:` to fall back through if a
        reading it named turned out absent.

        Hand-only: a pattern colour may read any source; the pattern-wide
        absence policy is `wfb.kinds.pattern._check_pattern_absence`, one
        error for the whole element.  Returns whether the colour was rejected.
        """
        if not color.sources:
            return False
        self.bag.error(
            "hands",
            f"{where}.color: a hand colour cannot read data ({and_paths(color.sources)})",
            span or color.span,
            notes=["allowed: palette entries, literal colours and config.* "
                   "(accent_color, data_color, colors.<role>) -- and conditionals "
                   "over those",
                   "a hand has no 'when_absent:' to fall back through if the "
                   "reading it named turned out absent"],
        )
        return True

    def build_hand_part(
        self, node: dict[str, Any], where: str, index: int,
        default_color: Expression | None, default_color_failed: bool,
        *, context: str = "hand",
    ) -> AnyHandPart | None:
        """One primitive of a hand, or of a `type: pattern` template -- the
        same per-shape precedent as `wfb.kinds.shape.ShapeKind.build`/
        `wfb.kinds.shape._check_shape_keys`, scoped to the
        rotatable-or-translatable primitives.  `context`
        (`"hand"`/`"pattern"`) selects the vocabulary: a hand part rejects
        `arc` and `text` outright; a pattern part accepts both.
        `default_color` is the owning hand's/pattern's own `color:`, and
        `default_color_failed` says it was written and rejected
        (`owned_color`).
        """
        is_hand = context == "hand"
        noun = "hand" if is_hand else "pattern"
        rejected_shapes = HAND_PART_REJECTED_SHAPES if is_hand else PATTERN_PART_REJECTED_SHAPES
        geometry_keys = HAND_PART_GEOMETRY_KEYS if is_hand else PATTERN_PART_GEOMETRY_KEYS
        part_where = f"{where}.parts[{index}]"
        shape = node.get("shape")
        span = self.doc.span(node)
        if shape in rejected_shapes:
            self.bag.error(
                "element",
                f"{part_where}: 'shape: {shape}' is not accepted on a {noun} part -- "
                f"{rejected_shapes[shape]}",
                self.doc.span(node, "shape") or span,
                notes=["the rotatable primitives are: " + ", ".join(sorted(geometry_keys))],
            )
            return None
        if shape not in geometry_keys:  # unreachable once the schema has run
            self.bag.error("hands" if is_hand else "pattern",
                           f"{part_where}: not a valid {noun} part", span)
            return None

        part_color, part_color_failed = self.owned_color(node, part_where, hand=is_hand)
        ok = not part_color_failed
        effective_color = part_color if part_color is not None else default_color
        if effective_color is None and not default_color_failed and not part_color_failed:
            owner = "its hand" if is_hand else "this pattern"
            self.bag.error(
                "hands" if is_hand else "pattern",
                f"{part_where}: no colour -- neither this part nor {owner} "
                "declares 'color:'",
                span,
                notes=[f"set 'color:' on the part, or on the {noun} as a default "
                       "every part without one inherits"],
            )
            ok = False

        # `visible:` -- pattern parts only (the schema keeps `handPart`
        # closed to it), compiled in the caller's `copy`-bound scope.  A
        # constant `true` is dropped (nothing to gate); a constant `false`
        # is kept, so the `dead-element` lint and codegen both see it.
        part_visible: Expression | None = None
        if not is_hand and "visible" in node:
            part_visible = self._visible(node)
            if part_visible is None:
                ok = False
            elif part_visible.constant is not None and part_visible.constant:
                part_visible = None

        raw_points = node.get("points") or []
        points = [self.position(raw, node, "points")
                  for raw in raw_points if isinstance(raw, dict)]
        at = self.position(node.get("at"), node, "at") if "at" in node else Position()
        size = self.size(node.get("size"))
        to = self.position(node.get("to"), node, "to") if "to" in node else None
        thickness = self.length(node, "thickness")
        radius = self.length(node, "radius")
        filled = bool(node.get("filled", True))
        start_angle = self.angle(node, "start_angle") if shape == "arc" else None
        sweep = self.angle(node, "sweep") if shape == "arc" else None

        if shape == "polygon" and len(points) < 3:
            self.require(node, "points", f"{part_where}: a polygon part needs points")
            ok = False
        if shape == "rectangle" and (size.width is None or size.height is None):
            self.require(node, "size", f"{part_where}: a rectangle part needs size.width and size.height")
            ok = False
        if shape == "line" and to is None:
            self.require(node, "to", f"{part_where}: a line part needs a 'to' position")
            ok = False
        if shape == "circle" and radius is None:
            self.require(node, "radius", f"{part_where}: a circle part needs a radius")
            ok = False
        if shape == "arc" and radius is None:
            self.require(node, "radius", f"{part_where}: an arc part needs a radius")
            ok = False

        if not self._check_hand_part_keys(node, shape, part_where, context=context):
            ok = False

        if "filled" in node and shape in HAND_PART_NO_UNFILLED and not filled:
            self.bag.error(
                "element",
                f"{part_where}: 'filled: false' is not accepted on a {noun} "
                f"'shape: {shape}' part -- Toybox.Graphics.Dc has fillPolygon "
                "but no drawPolygon",
                self.doc.span(node, "filled") or span,
                notes=(["a rectangle part becomes a polygon at build time, so "
                        "the same platform limit applies"]
                       if shape == "rectangle" else []),
            )
            ok = False

        align, vertical_align = self.alignment(node)
        text_fields: dict[str, Any] = {}
        if shape == "text":
            built = self._build_text_part(node, part_where, vertical_align)
            if built is None:
                ok = False
            else:
                text_fields = built

        if not ok:
            return None
        common: dict[str, Any] = dict(
            color=effective_color, span=span, visible=part_visible,
            min_1px=(bool(node["min_1px"]) if "min_1px" in node else None),
        )
        if shape == "polygon":
            return PolygonPart(**common, points=points, filled=filled)
        if shape == "rectangle":
            return RectanglePart(**common, at=at, size=size, filled=filled,
                                 align=align, vertical_align=vertical_align)
        if shape == "line":
            return LinePart(**common, at=at, to=to, thickness=thickness)
        if shape == "circle":
            return CirclePart(**common, at=at, radius=radius, thickness=thickness, filled=filled,
                              align=align, vertical_align=vertical_align)
        if shape == "arc":
            return ArcPart(**common, radius=radius, thickness=thickness,
                           start_angle=start_angle, sweep=sweep)
        return TextPart(**common, at=at, align=align, vertical_align=vertical_align,
                        **text_fields)

    def _build_text_part(
        self, node: dict[str, Any], part_where: str, vertical_align: str,
    ) -> dict[str, object] | None:
        """The `shape: text` half of a pattern part, as `TextPart` keyword
        arguments, or `None` once any of its own checks failed (each already
        reported).  Upright glyphs whose anchor turns (radial) or steps
        (linear) with the copy -- only a pattern reaches this, since
        `HAND_PART_REJECTED_SHAPES` refuses `text` on a hand.  Every check
        runs, so each mistake gets its own error, and none gets two.
        """
        ok = True
        text_value: Expression | None = None
        text_literal: str | None = None
        text_format: str | None = None
        has_value = "value" in node
        if has_value == ("text" in node):  # both, or neither
            self.bag.error(
                "pattern",
                f"{part_where}: a text part needs exactly one of "
                "'value:' (an expression; 'copy' is in scope) or "
                "'text:' (a fixed string)",
                self.doc.span(node),
            )
            ok = False
        elif has_value:
            value = self.expression(node, "value")
            if value is None:
                ok = False  # expression already reported the real mistake
            else:
                assert value.ast is not None  # every compiled expression keeps its tree
                bad_refs = sorted({
                    ref.path for ref in expr.walk(value.ast)
                    if isinstance(ref, expr.Ref) and ref.path != expr.COPY
                })
                if bad_refs:
                    self.bag.error(
                        "pattern",
                        f"{part_where}.value: a pattern text part's value "
                        "may read only 'copy', not " + ", ".join(bad_refs),
                        value.span,
                        notes=["every copy's string must be known at build "
                               "time, for font subsetting and extents",
                               "data in a pattern text part is not "
                               "implemented (docs/limitations.md)"],
                    )
                    ok = False
                elif value.value.type not in (Type.NUMBER, Type.FLOAT, Type.STRING):
                    self.bag.error(
                        "pattern",
                        f"{part_where}.value: must be a number or a "
                        f"string, got {value.value}",
                        value.span,
                    )
                    ok = False
                else:
                    text_value = value
                    if "format" in node:
                        text_format = node.get("format")
                        self.check_format(node, value, text_format)
        elif not self.check_format_not_on_literal(node, part_where):
            ok = False
        else:
            text_literal = str(node.get("text"))

        font, font_is_custom, font_ok = "FONT_MEDIUM", False, True
        if "font" in node:
            resolved = self._font_reference(str(node["font"]), self.doc.span(node, "font"))
            if resolved is None:
                ok = font_ok = False  # _font_reference already reported it
            else:
                font, font_is_custom = resolved
        font_is_vector = self.is_vector_font(font, font_is_custom)

        curve: Curve | None = None
        if "curve" in node:
            curve = self.build_curve(
                node, part_where, vertical_align=vertical_align, font_ok=font_ok,
                font_is_vector=font_is_vector)
            if curve is None:
                ok = False
        if font_ok and "if_unavailable" in node:
            self.check_if_unavailable(node, part_where, font_is_vector)

        # A failed `outline:` aborts the part; `outline: none` (or no key)
        # is not a failure.  Absence is deferred to
        # `wfb.kinds.pattern._check_pattern_absence`
        # (`build_outline`'s own docstring).
        outline: Outline | None = None
        if "outline" in node:
            outline = self.build_outline(node, "outline", part_where)
            if outline is None and node.get("outline") not in (None, "none"):
                ok = False

        if not ok:
            return None
        return dict(
            text_value=text_value, text_literal=text_literal, format=text_format,
            font=font, font_is_custom=font_is_custom, curve=curve,
            if_unavailable=node.get("if_unavailable"), outline=outline,
        )

    def _check_hand_part_keys(
        self, node: dict[str, Any], shape: str, part_where: str, *, context: str = "hand",
    ) -> bool:
        """Reject a geometry key this part's `shape:` does not read, plus the
        separately-handled `thickness`/`filled` rules -- the same "a key a
        part's shape does not read is an error" precedent as
        `wfb.kinds.shape._check_shape_keys`.  Also how an `arc` pattern part's `at:`
        is refused: `at` is not in `PATTERN_PART_GEOMETRY_KEYS["arc"]`, so it
        falls out of the same "key belongs to another shape" sweep as any
        other misplaced key, with one extra note explaining the platform
        reason.
        """
        is_hand = context == "hand"
        noun = "hand" if is_hand else "pattern"
        geometry_keys = HAND_PART_GEOMETRY_KEYS if is_hand else PATTERN_PART_GEOMETRY_KEYS
        all_keys = _ALL_HAND_PART_GEOMETRY_KEYS if is_hand else _ALL_PATTERN_PART_GEOMETRY_KEYS

        def extra_notes(key: str) -> list[str]:
            notes = []
            if not is_hand and shape == "arc" and key == "at":
                notes.append("an arc part is always centred on the copy's own "
                             "origin -- there is no separate centre to offset")
            if key in ("align", "vertical_align") and shape in _HAND_PART_NO_ALIGNMENT_REASON:
                notes.append(_HAND_PART_NO_ALIGNMENT_REASON[shape])
            return notes

        ok = self.check_foreign_keys(
            node, shape, geometry_keys, all_keys, code="element", disc="shape",
            prefix=f"{part_where}: ", qualifier=f"a {noun} ", suffix=" part",
            extra_notes=extra_notes,
        )
        filled = bool(node.get("filled", True))
        thickness_always = {"line"} if is_hand else {"line", "arc"}
        thickness_ok = shape in thickness_always or (shape == "circle" and not filled)
        if "thickness" in node and not thickness_ok:
            reason = ("a filled 'shape: circle' part" if shape == "circle"
                      else f"a {noun} 'shape: {shape}' part")
            only = "'line'" + (" and 'arc'" if not is_hand else "")
            self.bag.error(
                "element",
                f"{part_where}: 'thickness' is not used by {reason}",
                self.doc.span(node, "thickness") or self.doc.span(node),
                notes=["thickness is the pen width of an outline; add 'filled: false' "
                       "to a circle part to outline it, or drop 'thickness'"]
                      if shape == "circle" else
                      [f"only {only} and an unfilled 'circle' part read 'thickness'"],
            )
            ok = False
        if "filled" in node and shape not in HAND_PART_FILLED_SHAPES:
            if shape == "line":
                filled_note = "a line has no notion of being filled or not"
            elif shape == "text":
                filled_note = "glyphs have no notion of being filled or not"
            else:
                filled_note = ("an arc has no notion of being filled or not -- "
                               "Toybox.Graphics.Dc has no filled-arc primitive")
            self.bag.error(
                "element",
                f"{part_where}: 'filled' is not used by a {noun} 'shape: {shape}' part",
                self.doc.span(node, "filled") or self.doc.span(node),
                notes=[filled_note],
            )
            ok = False
        return ok
