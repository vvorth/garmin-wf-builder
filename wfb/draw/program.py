"""The draw program: what one element draws, as values and ops.

A kind lowers a placed element into a list of ops (`ElementKind.lower`).
Every value an op takes is something both backends can read: the printer
(`wfb.draw.printer`) spells it as Monkey C, the evaluator
(`wfb.draw.evaluator`) computes it on the host.  Nothing here knows any
kind; a kind knows only these types.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Union

if TYPE_CHECKING:
    from typing import TypeAlias

    from ..devices import FontMetric
    from ..emit.monkeyc.common import AodStyle, RingPass
    from ..ir.model import Element, Expression
    from ..layout import ResolvedFace
    from ..units import IntBox


# -- numbers --------------------------------------------------------------------


@dataclass(frozen=True)
class Const:
    """A `Layout` constant: ``Layout.<name>`` on the watch, ``value`` on
    this device."""

    name: str
    value: float


@dataclass(frozen=True)
class Lit:
    """A number written into the call itself."""

    value: float


@dataclass(frozen=True)
class Shifted:
    """``base`` moved ``by`` pixels for one `outline:` stamp:
    ``Layout.P_CX - 1`` (`wfb.emit.monkeyc.shapes.shifted`)."""

    base: "Num"
    by: int


@dataclass(frozen=True)
class Grown:
    """``base`` grown by ``times * by`` for a grown ring copy:
    ``Layout.P_RADIUS + 2`` (`wfb.emit.monkeyc.common.plus`)."""

    base: "Num"
    by: int
    times: int = 1


@dataclass(frozen=True)
class AodPick:
    """``awake``, or ``asleep`` in the always-on frame: an `aod:` override
    of a length (`thickness:`), ``(_aod ? <asleep> : <awake>)`` in a build
    with AOD code (`AodStyle.value`).  ``asleep`` is `None` when the
    element has no override, which prints and evaluates as ``awake``."""

    awake: "Num"
    asleep: "Num | None"


Num: "TypeAlias" = Union[Const, Lit, Shifted, Grown, AodPick]


# -- strings --------------------------------------------------------------------


@dataclass(frozen=True)
class StrLit:
    """A string written into the call: a literal `text:`, a placeholder."""

    text: str


@dataclass(frozen=True)
class Reading:
    """One reading through its format spec (`wfb.formatting.emit` on the
    watch, `wfb.formatting.render` here); absent when the reading is."""

    spec: str
    value: "Expression"
    unit: "Expression | None" = None


@dataclass(frozen=True)
class Concat:
    """Readings and literals drawn as one string; absent when any part is."""

    parts: tuple["StrLit | Reading", ...]


@dataclass(frozen=True)
class Local:
    """A string local an earlier `LetText` assigned."""

    name: str


@dataclass(frozen=True)
class AodStr:
    """``awake``, or ``asleep`` in the always-on frame: a text's `aod:
    {format: ...}`, both strings built up front and ternaried."""

    asleep: "Str"
    awake: "Str"


@dataclass(frozen=True)
class IconChoice:
    """A dynamic icon's glyph: `WfbWeather.chooseIcon` turns the reading
    into a catalogue name (here `wfb.icons.choose_weather_icon`) and
    `IconGlyphs.glyph` that name into the character (`wfb.icons.CATALOG`)."""

    value: "Expression"


Str: "TypeAlias" = Union[StrLit, Reading, Concat, Local, AodStr, IconChoice]


# -- colours and fonts ----------------------------------------------------------


@dataclass(frozen=True)
class Color:
    """A colour expression; `None` is `Graphics.COLOR_WHITE`
    (`wfb.emit.monkeyc.common.mc_color`).  The same in every frame."""

    expr: "Expression | None"


@dataclass(frozen=True)
class AodRestyled:
    """``element``'s own ``key`` colour (`color`, `track_color`,
    `icon_color`) as the always-on frame restyles it: its `aod:` override,
    else dimmed by `aod: {dim: ...}`, else unchanged.  One decision,
    `wfb.ir.aod_color_choice`, which `AodStyle.color` prints and
    `Renderer.aod_color` evaluates."""

    element: "Element"
    key: str


@dataclass(frozen=True)
class AodDimmed:
    """``expr`` dimmed in the always-on frame and unchanged otherwise: a
    colour no `aod:` key reaches, such as an `outline:` ring carried over
    from the awake design (`AodStyle.dimmed`, `Renderer.aod_dimmed`)."""

    element: "Element"
    expr: "Expression | None"


@dataclass(frozen=True)
class AodPaint:
    """``awake``, or ``asleep`` in the always-on frame: a ring whose
    `aod: {outline: ...}` colour replaces the awake one."""

    asleep: "Paint"
    awake: "Paint"


@dataclass(frozen=True)
class RingColor:
    """The `ringColor` parameter of a `ring<Id>` method: an outlined
    group's colour, which the group's ring pass hands its members."""


Paint: "TypeAlias" = Union[Color, AodRestyled, AodDimmed, AodPaint, RingColor]


@dataclass(frozen=True)
class Font:
    """The font a text call names.  ``code`` is how the call spells it (a
    local, or `Graphics.FONT_*`); ``baked`` the `ResolvedFace.fonts` key of
    a baked sheet; ``metric`` the device face a system or vector font
    draws with; ``vector`` whether it is a `face:` font."""

    code: str
    baked: str | None = None
    metric: "FontMetric | None" = None
    vector: bool = False
    #: The font drawn in the always-on frame instead, from an `aod: {font:
    #: ...}` override; ``code`` already names the choice between the two.
    asleep: "Font | None" = None


# -- ops ------------------------------------------------------------------------


@dataclass(frozen=True)
class SetColor:
    """`dc.setColor(<color>, Graphics.COLOR_TRANSPARENT)`."""

    color: "Paint"


@dataclass(frozen=True)
class SetPen:
    """`dc.setPenWidth(<width>)`; ``None`` resets it to 1."""

    width: Num | None


@dataclass(frozen=True)
class Primitive:
    """One `Dc` fill or draw call over numbers: ``name`` is the method
    (`fillRectangle`, `drawCircle`, `drawLine`, ...), ``args`` its
    arguments in the groups the printer wraps them in, one per line."""

    name: str
    args: tuple[tuple[Num, ...], ...]


@dataclass(frozen=True)
class FillPolygon:
    """`dc.fillPolygon(Layout.<const>)`, whose vertices are ``points``."""

    const: str
    points: tuple[tuple[int, int], ...]


@dataclass(frozen=True)
class ArcSpan:
    """`WfbArc.drawSpan`: ``start`` and ``sweep`` in Garmin's convention,
    exactly the arguments the watch gets."""

    cx: Num
    cy: Num
    radius: Num
    pen: Num
    start: Num
    sweep: Num


@dataclass(frozen=True)
class LoadFont:
    """``var <local> = <source>;`` (a font field, or a choice between two),
    then, for ``on_null="return"``, ``if (<local> == null) { return;  //
    <note> }``.  Any other load is followed by an `IfNotNull` block, or by
    nothing.  The host always has the font, so the evaluator skips it."""

    local: str
    source: str
    on_null: str = "return"
    note: str = "the font resource failed to load"


@dataclass(frozen=True)
class Text:
    """`dc.drawText`, or `drawAngledText`/`drawRadialText` under a
    ``style``, at ``x``/``y`` (`Layout` names, already shifted for a
    stamp).  ``valign`` is the element's `vertical_align`, which the
    printer turns into the call's `y` (`glyph_y_expr`) or radius
    (`radial_radius_expr`); ``box`` is the preview's outline when no glyph
    source exists."""

    x: Num
    y: Num
    font: Font
    text: Str
    justify: tuple[str, ...]
    valign: str
    #: The element's `align`, which the preview places the line by; ``None``
    #: reads it off ``justify``.
    align: str | None = None
    style: str | None = None
    angle: Const | None = None
    radius: Const | None = None
    direction: str | None = None
    box: "IntBox | None" = None


@dataclass(frozen=True)
class Glyph:
    """An icon's glyph: on the watch an upright `dc.drawText` at ``x``/``y``,
    printed as `Text` prints one; on the host, the glyph's tile pasted at
    the top-left of the icon's measured box, ``box``, moved as far as
    ``x``/``y`` are from ``origin`` (an `outline:` stamp)."""

    x: Num
    y: Num
    font: Font
    glyph: Str
    justify: tuple[str, ...]
    valign: str
    box: "IntBox"
    origin: tuple[int, int]


@dataclass(frozen=True)
class LetText:
    """``var text = <initial>; if (<guards> != null) { text = <value>; }``:
    a `placeholder:`/`fallback:` substitution.  The evaluator takes
    ``value`` when it is present, else ``initial``."""

    initial: Str
    value: Str
    guards: tuple[str, ...]
    name: str = "text"


@dataclass(frozen=True)
class IfNotNull:
    """``if (<local> != null) { <body> }``.  A loaded font is never null on
    the host, so the evaluator always runs the body."""

    local: str
    body: tuple["Op", ...]


@dataclass(frozen=True)
class IfAod:
    """``if (_aod) { <then> } else { <otherwise> }`` (no `else` when
    ``otherwise`` is empty).  The evaluator takes the branch of the frame it
    paints."""

    then: tuple["Op", ...]
    otherwise: tuple["Op", ...] = ()


@dataclass(frozen=True)
class IfAwake:
    """``if (!_aod) { <body> }``: drawn in every frame but the always-on
    one."""

    body: tuple["Op", ...]


@dataclass(frozen=True)
class Disagreement:
    """A known difference between what the watch is sent (``watch``, which
    the printer writes) and what the host draws (``preview``, which the
    evaluator paints), kept explicit until it is resolved.  ``why`` names
    it.  Every use is meant to go once the difference is settled."""

    watch: tuple["Op", ...]
    preview: tuple["Op", ...]
    why: str


@dataclass(frozen=True)
class Comment:
    """A `//` line, for the printer only."""

    text: str


@dataclass(frozen=True)
class Blank:
    """A blank line, for the printer only."""


Op: "TypeAlias" = Union[SetColor, SetPen, Primitive, FillPolygon, ArcSpan, LoadFont, Text,
                        Glyph, LetText, IfNotNull, IfAod, IfAwake, Disagreement, Comment, Blank]


# -- what lowering is given ------------------------------------------------------


@dataclass(frozen=True)
class DrawContext:
    """Everything a kind's `lower` reads besides the placed element: the
    device's resolved face, how this build restyles for the always-on frame
    (`AodStyle`), the reading locals whose absence substitutes the element's
    value (`ReadPlan.value_guards`), and the outlined group's ring pass to
    draw instead of the element, if any."""

    resolved: "ResolvedFace"
    aod: "AodStyle"
    value_guards: tuple[str, ...] = ()
    ring: "RingPass | None" = None
