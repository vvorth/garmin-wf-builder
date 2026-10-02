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
    from ..layout import ResolvedFace, RotatablePart
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


@dataclass(frozen=True)
class FloatLit:
    """A `Float` literal, spelt as `mc_float` spells one (`0.5`,
    `1.5707963267948966`), with ``suffix`` after it (`0.5f`)."""

    value: float
    suffix: str = ""


@dataclass(frozen=True)
class NumLocal:
    """A number local an earlier `Let` (or a `For`) assigned."""

    name: str


@dataclass(frozen=True)
class Read:
    """A bound expression's own compiled code (`Expression.code`), at the
    sample readings on the host; absent when the expression is."""

    expr: "Expression"


@dataclass(frozen=True)
class Bin:
    """``a <op> b``, printed bare: a kind adds a `Paren` where the code has
    one.  The evaluator reads a chain of them the way Monkey C parses the
    printed text (`*`, `/` and `%` before `+` and `-`, left to right), and
    `/` of two `Number`s truncates."""

    op: str
    a: "Num"
    b: "Num"


@dataclass(frozen=True)
class Paren:
    """``(<inner>)``."""

    inner: "Num"


@dataclass(frozen=True)
class Call:
    """``fn(<args>)``: a `Math` or barrel function the evaluator has a
    transcription of (`wfb.draw.barrel.CALLS`)."""

    fn: str
    args: tuple["Num", ...]


@dataclass(frozen=True)
class Conv:
    """``<inner>.toNumber()`` (truncating toward zero) or
    ``<inner>.toFloat()``; ``method`` names which."""

    inner: "Num"
    method: str


@dataclass(frozen=True)
class NumPick:
    """``(<cond>) ? <then> : <otherwise>``, a number chosen at runtime."""

    cond: "Cond"
    then: "Num"
    otherwise: "Num"


@dataclass(frozen=True)
class FontDrop:
    """``base``, less the font's own height for `vertical_align: bottom`
    (`glyph_y_expr`), wherever in a call the code subtracts it.  The host
    places the line by its `vertical_align` itself, so this evaluates to
    ``base``."""

    base: "Num"
    valign: str
    font: str


@dataclass(frozen=True)
class HandAngle:
    """``WfbHands.<function>(clock)``: a hand's angle from the clock, and on
    the host from the sample time (`time.hour`/`minute`/`second`) through
    the twin `barrel.HAND_ANGLES` names by ``hand``."""

    function: str
    hand: str


Num: "TypeAlias" = Union[Const, Lit, Shifted, Grown, AodPick, FloatLit, NumLocal, Read, Bin,
                         Paren, Call, Conv, NumPick, FontDrop, HandAngle]


# -- conditions -----------------------------------------------------------------


@dataclass(frozen=True)
class Present:
    """``a != null && b != null`` over the reading locals ``guards`` (the
    element's value guards).  On the host they are present when every one
    of ``probes``, the expressions they are read for, evaluates."""

    guards: tuple[str, ...]
    probes: tuple["Expression", ...]


@dataclass(frozen=True)
class LocalsSet:
    """``a != null && b != null`` over locals the program assigned."""

    names: tuple[str, ...]


@dataclass(frozen=True)
class Cmp:
    """``a <op> b``: a comparison of two numbers."""

    op: str
    a: "Num"
    b: "Num"


@dataclass(frozen=True)
class NotPulsing:
    """``_pulsing != <unique>``: the native editor is not animating the
    config slot ``unique`` (the editor's drawable draws it while it does).
    Never the case on the host."""

    unique: int


@dataclass(frozen=True)
class AnyOf:
    """``a || b || ...``."""

    conds: tuple["Cond", ...]


@dataclass(frozen=True)
class Truthy:
    """An expression's own compiled code as the condition (`visible:`):
    false on the host when it is absent, as `Renderer.visible` decides."""

    expr: "Expression"


@dataclass(frozen=True)
class NotSleeping:
    """``!_sleeping``: the face is awake, so neither the asleep nor the
    always-on frame."""


Cond: "TypeAlias" = Union[Present, LocalsSet, Cmp, NotPulsing, AnyOf, Truthy, NotSleeping]


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


@dataclass(frozen=True)
class PerCopy:
    """A pattern text part's string: ``printed`` on the watch, and on the
    host the copy's own string, rendered at build time (``texts[i]`` for
    the loop's ``var``)."""

    printed: "Str"
    texts: tuple[str, ...]
    var: str = "i"


Str: "TypeAlias" = Union[StrLit, Reading, Concat, Local, AodStr, IconChoice, PerCopy]


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


@dataclass(frozen=True)
class AodPart:
    """One part's own colour ``expr`` of a `hands`/`pattern`/needle element:
    the element-level `aod: {color: ...}` reaches every part, and `dim:`
    dims each part's own colour (`AodStyle.part_color`, `Renderer.aod_color`
    with ``key="color"``)."""

    element: "Element"
    expr: "Expression | None"


@dataclass(frozen=True)
class PaintPick:
    """``(<cond>) ? <then> : <otherwise>``, a colour chosen at runtime."""

    cond: Cond
    then: "Paint"
    otherwise: "Paint"


Paint: "TypeAlias" = Union[Color, AodRestyled, AodDimmed, AodPaint, RingColor, AodPart, PaintPick]


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
    """`dc.setColor(<color>, Graphics.COLOR_TRANSPARENT)`, with ``note`` as a
    trailing comment."""

    color: "Paint"
    note: str = ""


@dataclass(frozen=True)
class SetPen:
    """`dc.setPenWidth(<width>)`; ``None`` resets it to 1.  ``note`` is a
    trailing comment."""

    width: Num | None
    note: str = ""


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
    points: tuple[tuple[float, float], ...]


@dataclass(frozen=True)
class ArcSpan:
    """`WfbArc.drawSpan`: ``start`` and ``sweep`` in Garmin's convention,
    exactly the arguments the watch gets.  ``pen_first``: the pen ends the
    call's first line rather than starting its second."""

    cx: Num
    cy: Num
    radius: Num
    pen: Num
    start: Num
    sweep: Num
    pen_first: bool = False


@dataclass(frozen=True)
class ArcProgress:
    """`WfbArc.drawProgress`: ``fraction`` of the span `ArcSpan` would
    draw, nothing at or below zero, the whole span above one."""

    cx: Num
    cy: Num
    radius: Num
    pen: Num
    start: Num
    sweep: Num
    fraction: Num


@dataclass(frozen=True)
class Part:
    """One polygon, line or circle part of a hand, a needle or a pattern
    copy, through the barrel: rotated about the locals ``cx``/``cy`` by
    ``sin``/``cos`` (``radial``, `WfbGeom.fillRotated` and the rest), or
    translated by ``ox``/``oy``.  ``ring``: the part's ``ring`` px
    `outline:` ring instead (`WfbRing`, `WfbRingWide`), in whatever colour
    is set.  A stroked part draws in ``pen``, set around the call unless
    ``set_pen`` is false.  ``prefix`` names its `Layout` constants."""

    part: "RotatablePart"
    prefix: str
    radial: bool
    pen: Num
    set_pen: bool = True
    ring: int | None = None
    #: A filled circle's ring stamped rather than grown: only ever the
    #: preview side of a `Disagreement`, never printed.
    stamp: bool = False


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
    angle: Num | None = None
    radius: Const | None = None
    direction: str | None = None
    box: "IntBox | None" = None
    #: Whether the printer subtracts a `bottom` line's font height from
    #: ``y`` itself; false when ``y`` already says where (a `FontDrop`).
    shift_y: bool = True
    #: The call's `x` on a line of its own, as a pattern's text part prints it.
    split_x: bool = False


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
    """``if (<local> != null) { <body> }``.  A loaded font is null on the
    host only when ``present`` says so (a vector font this device does not
    resolve, `if_unavailable: hide`); otherwise the evaluator runs the
    body."""

    local: str
    body: tuple["Op", ...]
    present: bool = True


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
class Let:
    """``var <name> = <value>;``, with ``note`` as a trailing comment."""

    name: str
    value: Num
    note: str = ""


@dataclass(frozen=True)
class Assign:
    """``<name> = <value>;``."""

    name: str
    value: Num


@dataclass(frozen=True)
class If:
    """``if (<cond>) { <then> } else { <otherwise> }`` (no `else` when
    ``otherwise`` is empty)."""

    cond: Cond
    then: tuple["Op", ...]
    otherwise: tuple["Op", ...] = ()


@dataclass(frozen=True)
class For:
    """``for (var <var> = 0; <var> < <bound>; <var>++) { <body> }``.  With
    ``copy``, the loop is a pattern's copies: on the host the readings bind
    `copy` to ``var`` for each one (`wfb.expr.COPY`)."""

    var: str
    bound: Num
    body: tuple["Op", ...]
    copy: bool = False


@dataclass(frozen=True)
class Continue:
    """``continue;``: the next turn of the innermost `For`."""


@dataclass(frozen=True)
class LetSlotPick:
    """The wearer's pick on a `config: slots:` slot and its scale, as the
    locals ``chosenId``, ``chosenType``, ``pulled`` and ``scale``: the slot's
    `Complications.Id` field, its type, `WfbComplications.valueOf` and
    `<module>.scale(chosenType, pulled)`, null-safe where `Complications`
    may be absent (``guarded``).  On the host ``pulled`` is a complication
    whose value is ``sample``, the slot's `default:` reading, and ``scale``
    the twin of its scale, `None` when its pick has none or there is no
    such slot."""

    field: str
    module: str
    guarded: bool
    sample: object
    scale: tuple[float, float] | None


@dataclass(frozen=True)
class LetAutoScale:
    """``var scale = (<reader> != null) ? <module>.scale(Complications.<constant>,
    <reader>) : null;``: `max: auto`'s scale, the one of complication type
    ``type_name``, for the reading ``value`` (`wfb.complications.scale_for`
    with the preview's sample wearer on the host)."""

    reader: str
    module: str
    constant: str
    type_name: str
    value: "Expression"


@dataclass(frozen=True)
class WrapperGuard:
    """The view's own guard around a `draw<Id>` body (`view.
    _emit_element_method`), which the view prints and the printer
    therefore does not: on the host, nothing more is drawn when any of
    ``probes`` is absent, or any of the catalogue ``sources`` has no sample
    reading."""

    probes: tuple["Expression", ...]
    sources: tuple[str, ...] = ()


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


Op: "TypeAlias" = Union[SetColor, SetPen, Primitive, FillPolygon, ArcSpan, ArcProgress, Part,
                        LoadFont, Text, Glyph, LetText, IfNotNull, IfAod, IfAwake, Let, Assign,
                        If, For, Continue, LetSlotPick, LetAutoScale, WrapperGuard, Disagreement, Comment,
                        Blank]


# -- what lowering is given ------------------------------------------------------


@dataclass(frozen=True)
class DrawContext:
    """Everything a kind's `lower` reads besides the placed element: the
    device's resolved face, how this build restyles for the always-on frame
    (`AodStyle`), the reading locals whose absence substitutes the element's
    value (`ReadPlan.value_guards`), the outlined group's ring pass to draw
    instead of the element, if any, and the build's device guards the code
    depends on."""

    resolved: "ResolvedFace"
    aod: "AodStyle"
    value_guards: tuple[str, ...] = ()
    ring: "RingPass | None" = None
    #: `Toybox.Complications` may be absent on some target, so a slot's
    #: `Complications.Id` field may be null (`Guards.complications`).
    complications_guarded: bool = False
