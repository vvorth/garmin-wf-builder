"""Registry of per-element-kind behaviour.

Every element kind (`group`, `shape`, `text`, `progress`, `icon`, `graph`,
`complication_slot`, `hands`, `pattern`) is one :class:`ElementKind`: a
bundle of hooks a stage (the builder, layout, preview, emit, lint) calls
instead of switching on `isinstance`/`kind ==`.  A new kind is an IR class
(`wfb.ir.model`), a `Placed` class (`wfb.layout`), one module here and its
schema entry; no stage needs a new branch.

The registry is loaded **lazily**: the first call to :func:`get`,
:func:`for_element`, :func:`for_placed` or :func:`all` imports the nine kind
modules, in schema order, each of which sets its own module-level `KIND`.
This module itself imports no stage module at the top level -- a stage
module imports this package (never a kind submodule directly) and only ever
looks a kind up at call time, so importing this package can never re-enter a
stage module that is still mid-import.
"""

from __future__ import annotations

import importlib
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Callable

if TYPE_CHECKING:
    from ..ir.model import Element
    from ..layout import Ink, Placed


#: Kind names, in schema/declaration order -- the order the first lookup
#: imports the nine kind modules in.  `tests/test_kinds.py` pins this
#: against the schema's own element discriminators.
_NAMES: tuple[str, ...] = (
    "group", "shape", "text", "progress", "icon", "graph",
    "complication_slot", "hands", "pattern",
)


def _default_describe(placed: "Placed") -> str:
    return placed.element.kind


def _default_contrast_subjects(placed: "Placed"):
    """`lint.check_contrast`'s fall-through arm: every kind but `hands`/
    `pattern` has no finer label to give than `Element.color_roles()`
    itself already reports."""
    element = placed.element
    non_aod = [role for role in element.color_roles() if not role.aod]
    ink = next((role for role in non_aod if role.role == "ink"), None)
    ring = next((role for role in non_aod if role.role == "ring"), None)
    allow_backdrop_match = not ink.is_glyph if ink is not None else placed.kind == "shape"
    yield (placed.id, ink.expression if ink is not None else None,
           ring.expression if ring is not None else None, allow_backdrop_match)


@dataclass(frozen=True)
class ElementKind:
    """One element kind's behaviour, as a bundle of hooks, one per question
    a stage asks about "this kind".  Every hook but the first five (which
    every kind must state outright) defaults to "nothing to do here" -- an
    empty collection, `None`, `False` or a no-op -- so a kind module only
    writes the hooks where it actually differs.
    """

    #: The schema's own discriminator (`type: <name>`).
    name: str
    #: The `wfb.ir.model.Element` subclass this kind builds.
    ir_class: type
    #: The `wfb.layout.Placed` (sub)class this kind resolves to -- the base
    #: `Placed` itself for `group`, which never resolves to a subclass.
    placed_class: type
    #: Builds the IR element from a schema-valid node -- `(b, node, common,
    #: path)` with `b` the `Builder`; only `group` needs `path`.
    build: Callable[..., "Element | None"]
    #: Resolves one element for one device -- `(r, element, parent, depth)`
    #: with `r` the `Resolver`.  `None` for `group`, which
    #: `Resolver._resolve_list` recurses into structurally.
    resolve: Callable[..., "Placed"] | None

    #: Extra Monkey C symbols this kind's generated code may own, beyond the
    #: id's own (a static group's `drawStatic<Id>`, a slot's icon/hold
    #: methods) -- reserved whether or not this element ends up emitting
    #: them, so a collision never appears only after an unrelated edit.
    extra_symbols: tuple[Callable[[str], str], ...] = ()
    #: `(phrase, note)` when this kind can never be `static:`, else `None`:
    #: its picture comes from something that is not an `Expression` (a
    #: series, a wearer's pick, the clock).  `phrase` fills "{id!r} is
    #: {phrase} and cannot be static", so it carries its own article.
    static_forbidden: tuple[str, str] | None = None
    #: `(code, what, notes)` when an `aod:` override's `key` cannot apply to
    #: this kind (`Builder._aod_refusal`), else `None`.
    aod_refusal: Callable[[str, str | None, bool], tuple[str, str, list[str]] | None] = \
        lambda key, shape, literal_text: None

    #: A friendly pre-check run before the schema itself, `(doc, bag,
    #: node)`; true when it reported an error for this node.
    precheck: Callable[..., bool] = lambda doc, bag, node: False

    #: Draws primitives, so `antialias:` reaches it as a runtime
    #: `Dc.setAntiAlias` (`layout.is_antialiased_primitive`); glyph kinds
    #: anti-alias in their baked font instead.
    antialiased: bool = False
    #: `(cx, cy, radius)` for a genuinely round element
    #: (`layout.circular_extent`), else `None`.
    circular_extent: Callable[["Placed"], tuple[float, float, float] | None] = \
        lambda placed: None
    #: The real ink shape where it is tighter than the box
    #: (`layout._shape_ink`), beyond the `circular_extent` disc.
    ink: Callable[..., "Ink | None"] = lambda placed, fonts_root=None: None

    #: Draws one placed element in `wfb preview` -- `(r, placed)` with `r`
    #: the renderer.  `None` for `group`, which draws nothing.
    draw_preview: Callable[..., None] | None = None

    #: Emits the Monkey C drawing body of `draw<Id>` -- `(w, resolved,
    #: placed, value_guards, plan, aod)` (`view._emit_element_method`).
    #: `None` for `group`, which draws nothing.
    emit_draw: Callable[..., None] | None = None
    #: `complication_slot` alone: its reading is a fresh per-frame pull, not
    #: an element-level binding, so it emits its own guards and the element
    #: guard/antialias wrapping around every other kind's `emit_draw` does
    #: not apply to it.
    emits_own_guards: bool = False
    #: A short phrase for generated doc comments (`common._describe`).
    describe: Callable[["Placed"], str] = _default_describe
    #: This element's per-device `Layout` constants, `(prefix, placed)`.
    layout_constants: Callable[..., list] = lambda prefix, placed: []
    #: The bitmap font resources one placed item loads (`common._loaded_fonts`).
    loaded_fonts: Callable[["Placed"], list[str]] = lambda placed: []
    #: The `face:` (vector) fonts one placed item draws with
    #: (`common._vector_fonts_used`).
    vector_fonts: Callable[["Placed"], list[str]] = lambda placed: []
    #: Did this device's vector-font gates fail for the carrier at
    #: `part_index` (`lint._font_unavailable`)?
    font_unavailable: Callable[..., bool] = lambda placed, part_index: False
    #: Reports a `missing-glyph` error for a baked font that lacks a glyph
    #: this element draws -- `(placed, resolved, bag)` (`lint.check_glyphs`).
    check_glyphs: Callable[..., None] = lambda placed, resolved, bag: None

    #: Adds the glyphs this element needs baked -- `(element, face, bucket)`,
    #: where `bucket(font_name)` returns that font's mutable glyph set (or
    #: `None` for a vector font, which has no sheet to subset)
    #: (`resources.glyph_set`).
    glyph_needs: Callable[..., None] = lambda element, face, bucket: None
    #: The icon font this element needs baked, `(key, (size, glyphs,
    #: reference, antialias))`, or `None` (`resources.icon_font_specs`).
    icon_font_need: Callable[..., tuple[str, tuple] | None] = \
        lambda element, face: None

    #: Every custom font name this element (or, for `pattern`, its text
    #: parts) names (`availability.vector_fonts_used`).
    vector_font_names: Callable[["Element"], tuple[str, ...]] = lambda element: ()

    #: `(what, carrier, part_index)` for every `face:`-font-eligible
    #: carrier this element owns -- itself for `text`, each `shape: text`
    #: part for `pattern` (`lint._vector_text_carriers`).
    vector_text_carriers: Callable[["Element"], list] = lambda element: []
    #: Every `(label, colour, ring, allow_backdrop_match)` this element
    #: draws, for `lint.check_contrast`.
    contrast_subjects: Callable[["Placed"], Any] = _default_contrast_subjects

    #: Does this element need `IconGlyphs.mc`, and which entries it adds
    #: (`project.generate`, `app.icon_glyph_entries`).
    needs_icon_glyphs: Callable[..., bool] = lambda element, face: False
    icon_glyph_entries: Callable[..., dict[str, str]] = lambda element, face: {}


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
