"""Registry of per-element-kind behaviour.

Every element kind (`group`, `shape`, `text`, `progress`, `icon`, `graph`,
`complication_slot`, `hands`, `pattern`) is one :class:`ElementKind`
subclass: the methods a stage (the builder, layout, preview, emit, lint)
calls instead of switching on `isinstance`/`kind ==`.  A new kind is an IR
class (`wfb.ir.model`), a `Placed` class (`wfb.layout`), one module here and
its schema entry; no stage needs a new branch.  `docs/development.md`,
"Adding an element kind", walks through one.

The registry is loaded **lazily**: the first call to :func:`get`,
:func:`for_element`, :func:`for_placed` or :func:`all` imports the nine kind
modules, in schema order, each of which sets its own module-level `KIND`
(an instance of its subclass).  This module itself imports no stage module
at the top level -- a stage module imports this package (never a kind
submodule directly) and only ever looks a kind up at call time, so importing
this package can never re-enter a stage module that is still mid-import.
"""

from __future__ import annotations

import importlib
from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass
from typing import Any, Callable, ClassVar, Generic, TYPE_CHECKING, TypeVar, cast

if TYPE_CHECKING:
    from typing import TypeAlias

    from ..diagnostics import Span
    from ..draw.program import DrawContext, Op
    from ..emit.monkeyc.layout_constants import Constants
    from ..ir.builder import Builder
    from ..ir.model import Curve, Element, Expression, Face
    from ..layout import Placed, PlacedPattern, ResolvedFont, Resolver
    from ..units import Box, Length

    #: `(label, colour, ring, allow_backdrop_match)`, one per ink an element
    #: draws -- :meth:`ElementKind.contrast_subjects`.
    ContrastSubject: TypeAlias = "tuple[str, Expression | None, Expression | None, bool]"


#: Kind names, in schema/declaration order -- the order the first lookup
#: imports the nine kind modules in.  `tests/test_kinds.py` pins this
#: against the schema's own element discriminators.
_NAMES: tuple[str, ...] = (
    "group", "shape", "text", "progress", "icon", "graph",
    "complication_slot", "hands", "pattern",
)


#: The `type:`s one kind, `shape`, draws.
PRIMITIVES: tuple[str, ...] = ("rectangle", "circle", "line", "arc", "ellipse", "polygon")


def kind_of(node: Mapping[str, Any]) -> Any:
    """The kind that builds an element node: its `type:`, except that every
    primitive (`type: rectangle`, `circle`, ...) is the `shape` kind's."""
    written = node.get("type")
    return "shape" if written in PRIMITIVES else written


def shape_of(node: Mapping[str, Any]) -> str | None:
    """A primitive's shape: its `type:`, with a `rectangle` that writes
    `corner_radius:` told apart as `rounded_rectangle`; `None` for any
    other kind."""
    written = node.get("type")
    if written not in PRIMITIVES:
        return None
    return "rounded_rectangle" if written == "rectangle" and "corner_radius" in node \
        else str(written)


# -- text runs ----------------------------------------------------------------


@dataclass(frozen=True)
class IconFont:
    """How to bake a synthetic icon font (`wfb.emit.resources.icon_font_specs`):
    the declared `size:`, the glyphs the sheet holds (in bake order), the one
    glyph its nominal size is measured against (`wfb.icons.bake_size`), and
    whether it is anti-aliased."""

    #: `None`: the element wrote no `size:` (`units.pixel_size`'s default).
    size: "Length | None"
    glyphs: str
    reference: str
    antialias: bool


@dataclass(frozen=True)
class TextRun:
    """One thing an element draws in a font it names: the answer to "what
    text does this element draw, in which font?" that every font-related
    stage derives its own question from (:meth:`ElementKind.text_runs`).

    Only a font the build has to do something about is a run: a custom
    `fonts:` entry (baked or `face:`) or a synthetic icon font.  A system
    `FONT_*` needs nothing baked, loaded or gated, so it is never one.

    - `wfb.emit.resources.glyph_set` bakes each baked font with the union
      of its runs' `glyphs`, and `icon_font_specs` bakes each `icon` run;
    - `wfb.emit.monkeyc.common._loaded_fonts` loads every baked font an
      awake run names, `_vector_fonts_used` builds every `face:` one, and
      `wfb.availability.vector_fonts_used` guards it;
    - `wfb.lint.check_glyphs` checks each of `samples` against the baked
      sheet, and `check_vector_font_availability` reports a `face:` run
      that no face on some target can draw;
    - `wfb.emit.project.generate` emits `IconGlyphs.mc` when any run has a
      `glyph_table`, and `wfb.emit.monkeyc.app.icon_glyph_entries` fills it.
    """

    #: How a diagnostic names this run: the element id, or
    #: `<pattern id>.parts[<i>]` for a pattern's `shape: text` part.
    label: str
    #: A `fonts:` name, or -- when `icon` is set -- a synthetic icon font key
    #: (`wfb.icons.font_key`).
    font: str
    #: Every character a baked `font` must hold for this run.  Ignored for a
    #: `face:` font (nothing to bake) and for an icon run (`icon.glyphs`).
    glyphs: frozenset[str] = frozenset()
    #: The exact strings `check_glyphs` looks up in the baked sheet, and a
    #: note for its error.  Empty: the run is not checked (its content is not
    #: knowable at build time, or it is an icon run).
    samples: tuple[str, ...] = ()
    sample_note: str | None = None
    #: The index of the element's own `parts:` entry this run is, or `None`
    #: for the element itself.  Which of the placed element's resolved fonts
    #: layout decided for this run follows from it: `placed.parts[i].font`,
    #: else `placed.font` (:func:`placed_font`).
    part_index: int | None = None
    #: Where the run's `font:`/`unsupported:` were written.
    span: "Span | None" = None
    #: The run's own `unsupported:`, which wins over its font's, and its
    #: own `curve:`, whose style decides which draw call gate 1 needs.
    unsupported: str | None = None
    curve: "Curve | None" = None
    #: Drawn only in the always-on frame (a `text` element's own `aod: {font:
    #: ...}`): baked like any other run, but loaded on entering sleep
    #: (`common._aod_only_fonts`), not in `onLayout`, and never gated.
    aod_only: bool = False
    #: Set for a synthetic icon font, which this run then bakes.
    icon: IconFont | None = None
    #: The runtime glyph chooser this run draws through (`IconGlyphs.glyph`):
    #: every key it can ask for, mapped to its glyph.  `None` for a run whose
    #: glyph is fixed at build time.
    glyph_table: Mapping[str, str] | None = None

    def is_vector(self, face: "Face") -> bool:
        """Is this run drawn with a `face:` (vector) font?"""
        return self.icon is None and face.fonts[self.font].is_vector


def text_runs(element: "Element", face: "Face") -> list[TextRun]:
    """`element`'s own :meth:`ElementKind.text_runs`."""
    return for_element(element).text_runs(element, face)


def face_text_runs(face: "Face") -> Iterator[tuple["Element", TextRun]]:
    """Every `(element, run)` in the design, whatever device it is placed on."""
    for element in face.walk():
        for run in text_runs(element, face):
            yield element, run


def placed_text_runs(
    items: Iterable["Placed"], face: "Face",
) -> Iterator[tuple["Placed", TextRun]]:
    """Every `(placed, run)` of one device's placed items, in draw order."""
    for placed in items:
        for run in text_runs(placed.element, face):
            yield placed, run


def ring_font_name(font: str, width: int = 1) -> str:
    """The companion font a baked font's ringed glyphs are dilated into
    by ``width`` px (`wfb.fonts.bmfont.dilate`)."""
    return f"{font}_ring_glyphs" if width == 1 else f"{font}_ring{width}_glyphs"


def ring_widths(element: "Element", face: "Face") -> list[int]:
    """Every width ``element`` draws a ring at, in first-seen order: its own
    `outline:`, a text's `aod: {outline: ...}`, and its share of each
    outlined group it sits in (`wfb.ir.rings`, the widths summed)."""
    from ..ir.rings import ring_groups

    out: list[int] = []
    rings = [element.outline]
    if element.kind == "text" and element.aod is not None:
        rings.append(element.aod.outline)
    for outline in rings:
        if outline is not None and outline.width not in out:
            out.append(outline.width)
    for ring in ring_groups(face.elements):
        if element.id in ring.ids:
            width = ring.width_of(element.id)
            if width not in out:
                out.append(width)
    return out


def ring_font(element: "Element", face: "Face",
              width: int) -> tuple[str, str, frozenset[str]] | None:
    """``(ring font, base font, glyphs)`` when ``element``'s ``width`` px
    ring is one `drawText` in a baked ring font rather than a stamp
    (research 19 §4.5): an icon, or a `text` element in a baked font.  A
    text whose `aod: {font: ...}` changes the font in the always-on frame
    keeps the stamp: its ring font would be the wrong one there.  A
    pattern's text parts keep the stamp too."""
    aod = element.aod
    if element.kind == "text" and aod is not None and aod.font is not None:
        return None
    for run in text_runs(element, face):
        if run.part_index is not None or run.aod_only:
            continue
        if run.icon is not None:
            return ring_font_name(run.font, width), run.font, frozenset(run.icon.glyphs)
        if element.kind == "text" and not run.is_vector(face):
            return ring_font_name(run.font, width), run.font, run.glyphs
    return None


def ring_fonts(face: "Face") -> dict[str, tuple[str, frozenset[str], int]]:
    """Every ring font the design needs: ring font -> (base font, the glyphs
    ringed runs draw with it, the ring's width), glyphs merged across
    elements."""
    out: dict[str, tuple[str, frozenset[str], int]] = {}
    for element in face.walk():
        for width in ring_widths(element, face):
            found = ring_font(element, face, width)
            if found is None:
                continue
            name, base, glyphs = found
            _, seen, _ = out.get(name, (base, frozenset(), width))
            out[name] = (base, seen | glyphs, width)
    return out


def placed_font(placed: "Placed", run: TextRun) -> "ResolvedFont":
    """The `ResolvedFont` layout decided for `run` on this device: a
    pattern part's, or the element's own."""
    if run.part_index is not None:
        part = cast("PlacedPattern", placed).parts[run.part_index]
        assert part.shape == "text", run.label  # only a text part names a font
        return part.font
    font: ResolvedFont | None = getattr(placed, "font", None)
    assert font is not None, run.label  # a run's element always resolves a font
    return font


# -- the kind interface -------------------------------------------------------


#: The IR element class and the placed class one kind handles.
E = TypeVar("E", bound="Element")
P = TypeVar("P", bound="Placed")


class ElementKind(Generic[E, P]):
    """One element kind's behaviour.  A kind module subclasses this, sets the
    three class attributes that name it, overrides `build`/`resolve` and
    `lower` (its drawing as one program, `wfb.draw`), and assigns an
    instance to its module-level `KIND`.

    Every other method and attribute has a default meaning "nothing to do
    here", so a kind overrides only where it actually differs.  `group` is
    the one kind that does not lower: the stages recurse into it
    structurally (`Resolver._resolve_list`) or skip it.
    """

    #: The schema's own discriminator (`type: <name>`).
    name: ClassVar[str]
    #: The `wfb.ir.model.Element` subclass this kind builds.
    ir_class: ClassVar[type]
    #: The `wfb.layout.Placed` (sub)class this kind resolves to -- the base
    #: `Placed` itself for `group`, which never resolves to a subclass.
    placed_class: ClassVar[type]

    #: Extra Monkey C symbols this kind's generated code may own, beyond the
    #: id's own (a static group's `drawStatic<Id>`, a slot's icon/hold
    #: methods) -- reserved whether or not this element ends up emitting
    #: them, so a collision never appears only after an unrelated edit.
    extra_symbols: ClassVar[tuple[Callable[[str], str], ...]] = ()
    #: `(phrase, note)` when this kind can never be `static:`, else `None`:
    #: its picture comes from something that is not an `Expression` (a
    #: series, a wearer's pick, the clock).  `phrase` fills "{id!r} is
    #: {phrase} and cannot be static", so it carries its own article.
    static_forbidden: ClassVar[tuple[str, str] | None] = None
    #: Draws primitives, so `antialias:` reaches it as a runtime
    #: `Dc.setAntiAlias` (`layout.is_antialiased_primitive`); glyph kinds
    #: anti-alias in their baked font instead.
    antialiased: ClassVar[bool] = False
    #: Draws an `outline:` ring: `lower` honours `DrawContext.ring`,
    #: so this kind can carry its own `outline:` and be a member of an
    #: outlined group.  The schema decides who may *write* one.
    ringed: ClassVar[bool] = False

    def ring_draws(self, element: E, face: "Face") -> int:
        """How many extra draws of the element its widest ring costs: one
        per `disc_perimeter_offsets` point for a stamp (the default; 4 at
        1px, 8 at 2px, 16 at 3px), 1 for a grown copy or a baked ring font
        (`ring_fonts`).  The `partial-update-budget` lint reads it
        (research 19 §4.5)."""
        from ..ir.model import disc_perimeter_offsets

        return len(disc_perimeter_offsets(max(ring_widths(element, face), default=1)))

    def ring_refusal(self, element: E) -> str | None:
        """Why this element, of a `ringed` kind, cannot draw an `outline:`
        ring yet, or `None` when it can -- a friendly build error on its
        own `outline:` and on an outlined group it sits in."""
        return None

    # -- semantic pass (wfb.ir.builder) --

    def build(self, b: "Builder", node: dict[str, Any], common: dict[str, Any], path: tuple[str | int, ...]) -> "Element | None":
        """Build the IR element from a schema-valid node.  `common` holds the
        fields every kind shares (`id`, `at`, `visible`, `aod`, ...) for the
        IR class's constructor; `path` is the node's schema path (only
        `group` needs it, to build its children)."""
        raise NotImplementedError(f"{self.name}: build")

    def aod_refusal(self, key: str, shape: str | None,
                    literal_text: bool) -> tuple[str, str, list[str]] | None:
        """`(code, what, notes)` when an `aod:` override's `key` cannot apply
        to this kind (`Builder.aod_refusal`), else `None`.  `shape` is a
        `shape` element's own `shape:`, `literal_text` whether a `text`
        element has a fixed `text:`."""
        return None

    # -- layout (wfb.layout) --

    def resolve(self, r: "Resolver", element: E, parent: "Box",
                depth: int) -> "Placed":
        """Resolve one element for one device, inside its parent's box."""
        raise NotImplementedError(f"{self.name}: resolve")

    def hidden_reason(self, placed: P) -> str | None:
        """Why this device does not draw `placed` at all -- a
        `wfb.layout.HIDDEN_BY_*` code, which `Resolver` records in
        `ResolvedFace.hidden` -- or `None` when it draws."""
        return None

    def circular_extent(self, placed: P) -> tuple[float, float, float] | None:
        """`(cx, cy, radius)` for a genuinely round element
        (`layout.circular_extent`), else `None`."""
        return None

    # -- fonts (resources, emit, lint) --

    def text_runs(self, element: E, face: "Face") -> list[TextRun]:
        """Everything this element draws in a font it names -- see
        :class:`TextRun`.  A pure function of the design, so it answers
        before any device is resolved (glyph baking, vector-font guards) as
        well as after."""
        return []

    # -- the draw program (wfb.draw) --

    def lower(self, ctx: "DrawContext", placed: P) -> "list[Op]":
        """This element's draw program: what `draw<Id>` (or, with
        `ctx.ring`, `ring<Id>`) draws after its guards, as ops the printer
        writes and the preview evaluates (`wfb.draw`).  Every kind that
        draws overrides it; `group` draws nothing itself."""
        raise NotImplementedError(f"{self.name}: lower")


    # -- codegen (wfb.emit) --

    def draws_while_absent(self, element: E) -> bool:
        """Whether the element still draws something when its value is
        absent under `absent: hide` -- a gauge's track.  When true, the
        element's program guards only its other bindings, and `lower` guards
        the value-dependent drawing itself (`DrawContext.value_guards`)."""
        return False

    def describe(self, placed: P) -> str:
        """A short phrase for generated doc comments (`common._describe`)."""
        return placed.element.kind

    def layout_constants(self, prefix: str, placed: P) -> "Constants":
        """This element's per-device `Layout` constants."""
        return []

    def live_handle(self, placed: P, handle: dict[str, Any]) -> dict[str, Any] | None:
        """What an editor may redraw by itself while ``handle`` (one of
        `wfb.studio.drag.handles`) is dragged, before the server has placed
        the edit: ``{"consts": {name: per_px}}``, each `Layout` constant
        moving by ``per_px`` device pixels for every pixel the extent
        grows, or ``{"angle": name}``, the arc constant a turn sets.
        `None`, the default, wherever the outcome depends on layout the
        editor does not have (a centred box's edges re-round about a
        fractional centre); the editor then draws an outline.  Every
        declaration must predict the server's own edit exactly
        (`tests/test_studio_raster.py`)."""
        return None

    # -- lint (wfb.lint) --

    def contrast_subjects(self, placed: P) -> Iterator[ContrastSubject]:
        """Every `(label, colour, ring, allow_backdrop_match)` this element
        draws, for `lint.check_contrast`.

        By default the element's own ink (or ring), then a `data` element's
        icon colour, labelled `<id>.icon.color`, which may not match the
        backdrop exactly -- the same rule a glyph's own ink follows.  A
        gauge's `track_color` is not judged: a track is decoration meant to
        recede behind the fill (every track in the examples is `#555555` on
        black, a 2.8 ratio, by design)."""
        element = placed.element
        non_aod = [role for role in element.color_roles() if not role.aod]
        ink = next((role for role in non_aod if role.role == "ink"), None)
        ring = next((role for role in non_aod if role.role == "ring"), None)
        allow_backdrop_match = not ink.is_glyph if ink is not None else placed.kind == "shape"
        yield (placed.id, ink.expression if ink is not None else None,
               ring.expression if ring is not None else None, allow_backdrop_match)
        for role in non_aod:
            if role.role == "icon":
                yield (f"{placed.id}.icon.color", role.expression, None, False)


# -- the registry -------------------------------------------------------------


#: A kind of any element; the registry hands these out by name or class.
AnyKind = ElementKind[Any, Any]

_by_name: dict[str, AnyKind] = {}
_by_ir_class: dict[type, AnyKind] = {}
_by_placed_class: dict[type, AnyKind] = {}


def _load() -> None:
    if _by_name:
        return
    for name in _NAMES:
        kind: AnyKind = importlib.import_module(f"{__name__}.{name}").KIND
        _by_name[kind.name] = kind
        _by_ir_class[kind.ir_class] = kind
        _by_placed_class[kind.placed_class] = kind


def get(name: str) -> AnyKind:
    _load()
    return _by_name[name]


def for_element(element: "Element") -> AnyKind:
    _load()
    return _by_ir_class[type(element)]


def for_placed(placed: "Placed") -> AnyKind:
    _load()
    return _by_placed_class[type(placed)]


def all() -> tuple[AnyKind, ...]:
    _load()
    return tuple(_by_name[name] for name in _NAMES)


def names() -> tuple[str, ...]:
    return _NAMES
