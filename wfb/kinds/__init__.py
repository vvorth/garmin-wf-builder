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
from typing import TYPE_CHECKING, Callable, ClassVar

if TYPE_CHECKING:
    from ..diagnostics import Span
    from ..emit.monkeyc.common import AodStyle
    from ..emit.monkeyc.layout_constants import Constants
    from ..emit.monkeyc.readplan import ReadPlan
    from ..emit.writer import Writer
    from ..ir.builder import Builder
    from ..ir.model import Curve, Element, Face
    from ..layout import Placed, ResolvedFace, Resolver
    from ..preview import Renderer
    from ..units import Box, Length


#: Kind names, in schema/declaration order -- the order the first lookup
#: imports the nine kind modules in.  `tests/test_kinds.py` pins this
#: against the schema's own element discriminators.
_NAMES: tuple[str, ...] = (
    "group", "shape", "text", "progress", "icon", "graph",
    "complication_slot", "hands", "pattern",
)


# -- text runs ----------------------------------------------------------------


@dataclass(frozen=True)
class IconFont:
    """How to bake a synthetic icon font (`wfb.emit.resources.icon_font_specs`):
    the declared `size:`, the glyphs the sheet holds (in bake order), the one
    glyph its nominal size is measured against (`wfb.icons.bake_size`), and
    whether it is anti-aliased."""

    size: "Length"
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
    #: Where the run's `font:`/`if_unavailable:` were written.
    span: "Span | None" = None
    #: The run's own `if_unavailable:`, which wins over its font's, and its
    #: own `curve:`, whose style decides which draw call gate 1 needs.
    if_unavailable: str | None = None
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


def placed_font(placed: "Placed", run: TextRun):
    """The `ResolvedFont` layout decided for `run` on this device."""
    if run.part_index is not None:
        return placed.parts[run.part_index].font
    return placed.font


# -- the kind interface -------------------------------------------------------


class ElementKind:
    """One element kind's behaviour.  A kind module subclasses this, sets the
    three class attributes that name it, overrides `build`/`resolve`/
    `draw_preview`/`emit_draw`, and assigns an instance to its module-level
    `KIND`.

    Every other method and attribute has a default meaning "nothing to do
    here", so a kind overrides only where it actually differs.  `group` is
    the one kind that overrides none of the four drawing methods: the stages
    recurse into it structurally (`Resolver._resolve_list`) or skip it.
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

    # -- semantic pass (wfb.ir.builder) --

    def build(self, b: "Builder", node: dict, common: dict, path: tuple) -> "Element | None":
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

    def resolve(self, r: "Resolver", element: "Element", parent: "Box",
                depth: int) -> "Placed":
        """Resolve one element for one device, inside its parent's box."""
        raise NotImplementedError(f"{self.name}: resolve")

    def circular_extent(self, placed: "Placed") -> tuple[float, float, float] | None:
        """`(cx, cy, radius)` for a genuinely round element
        (`layout.circular_extent`), else `None`."""
        return None

    # -- fonts (resources, emit, lint) --

    def text_runs(self, element: "Element", face: "Face") -> list[TextRun]:
        """Everything this element draws in a font it names -- see
        :class:`TextRun`.  A pure function of the design, so it answers
        before any device is resolved (glyph baking, vector-font guards) as
        well as after."""
        return []

    # -- preview (wfb.preview) --

    def draw_preview(self, renderer: "Renderer", placed: "Placed") -> None:
        """Draw one placed element in `wfb preview`, the way the generated
        code draws it on the watch."""
        raise NotImplementedError(f"{self.name}: draw_preview")

    # -- codegen (wfb.emit) --

    def emit_draw(self, w: "Writer", resolved: "ResolvedFace", placed: "Placed",
                  value_guards: list[str] | None, plan: "ReadPlan",
                  aod: "AodStyle") -> None:
        """Emit the Monkey C drawing body of `draw<Id>`
        (`view._emit_element_method`), after the element's own guards.
        `value_guards` names the locals the value's own absence depends on
        (`None` for a `complication_slot`, whose reading is a fresh per-frame
        pull that emits its own guards); `aod` restyles the draw for the
        always-on frame."""
        raise NotImplementedError(f"{self.name}: emit_draw")

    def describe(self, placed: "Placed") -> str:
        """A short phrase for generated doc comments (`common._describe`)."""
        return placed.element.kind

    def layout_constants(self, prefix: str, placed: "Placed") -> "Constants":
        """This element's per-device `Layout` constants."""
        return []

    # -- lint (wfb.lint) --

    def contrast_subjects(self, placed: "Placed") -> Iterator[tuple]:
        """Every `(label, colour, ring, allow_backdrop_match)` this element
        draws, for `lint.check_contrast`.

        By default the element's own ink (or ring), then a complication
        slot's `icon_color`, labelled by its key, which may not match the
        backdrop exactly -- the same rule a glyph's own ink follows.  A
        progress `track_color` is not judged: a track is decoration meant to
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
                yield (f"{placed.id}.icon_color", role.expression, None, False)


# -- the registry -------------------------------------------------------------


_by_name: dict[str, ElementKind] = {}
_by_ir_class: dict[type, ElementKind] = {}
_by_placed_class: dict[type, ElementKind] = {}


def _load() -> None:
    if _by_name:
        return
    for name in _NAMES:
        kind: ElementKind = importlib.import_module(f"{__name__}.{name}").KIND
        _by_name[kind.name] = kind
        _by_ir_class[kind.ir_class] = kind
        _by_placed_class[kind.placed_class] = kind


def get(name: str) -> ElementKind:
    _load()
    return _by_name[name]


def for_element(element: "Element") -> ElementKind:
    _load()
    return _by_ir_class[type(element)]


def for_placed(placed: "Placed") -> ElementKind:
    _load()
    return _by_placed_class[type(placed)]


def all() -> tuple[ElementKind, ...]:
    _load()
    return tuple(_by_name[name] for name in _NAMES)


def names() -> tuple[str, ...]:
    return _NAMES
