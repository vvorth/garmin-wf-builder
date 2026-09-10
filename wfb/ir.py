"""The intermediate representation, and the semantic pass that produces it.

Stage 2 of validation (ADR 0008): everything that is device-independent.  Data
sources are resolved against the catalogue, expressions are type-checked and
compiled, and null handling is required where the platform makes absence
normal.  (There used to be a third thing here, a per-source refresh cadence
enforced against the mode an element draws in -- deleted along with the
runtime TTL cache it existed to protect: every value already comes from a
Garmin SDK call that caches it itself, so a plain per-frame read is correct
everywhere now, including under `onPartialUpdate`.  The suppressible
`partial-update-budget` lint, not this file, is where that tradeoff is
managed today.)

Nothing here knows a screen size.  Per-device work happens in :mod:`wfb.layout`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from . import catalog, complications, expr, icons, units
from .catalog import Source, Type
from .diagnostics import Bag, Span
from .palette import Color, ColorError
from .units import Angle, Length, UnitError
from .yamlsrc import YamlDocument

MODES = ("active", "low_power", "always_on")

#: `on_hold: auto` / a carousel item's `launch: auto` -- resolved later, once
#: the element (or item) has a value binding to resolve *from* (SPEC.md D3).
#: A plain string rather than a dedicated sentinel object so it survives
#: unchanged through `Element.on_hold`/`CarouselItem.launch`, both typed
#: `str | None` -- and safe to compare against, because `"auto"` is not and
#: will not become a real `wfb.complications.TYPES` key (constant names are
#: SCREAMING_SNAKE_CASE lowercased, and Garmin's own type table has no
#: `COMPLICATION_TYPE_AUTO`).
HOLD_AUTO = "auto"

#: Which geometry keys each `shape:` actually reads.  Anything outside its own
#: row is parsed by the schema and then dropped on the floor -- the bug
#: `filled:` had on a rectangle for several phases, and the reason a
#: `radius:` typed onto a rounded_rectangle used to do nothing at all.
#:
#: `color:` and `filled:` are common to every shape and are not listed;
#: `filled:` has its own refusals on `arc` and `polygon`.  `thickness:` is
#: handled separately below, because whether it is read depends on `filled:`
#: rather than on the shape alone.
SHAPE_GEOMETRY_KEYS = {
    "rectangle": frozenset({"size"}),
    "rounded_rectangle": frozenset({"size", "corner_radius"}),
    "circle": frozenset({"radius"}),
    "ellipse": frozenset({"size"}),
    "line": frozenset({"to"}),
    "arc": frozenset({"radius", "start_angle", "sweep"}),
    "polygon": frozenset({"points"}),
}

#: Every geometry key, for the "not used by this shape" check.
_ALL_SHAPE_GEOMETRY_KEYS = frozenset().union(*SHAPE_GEOMETRY_KEYS.values())


#: System fonts an author may name directly, instead of a baked custom font.
SYSTEM_FONTS = (
    "FONT_XTINY", "FONT_TINY", "FONT_SMALL", "FONT_MEDIUM", "FONT_LARGE",
    "FONT_NUMBER_MILD", "FONT_NUMBER_MEDIUM", "FONT_NUMBER_HOT",
    "FONT_NUMBER_THAI_HOT", "FONT_SYSTEM_MEDIUM", "FONT_SYSTEM_LARGE",
)


# --------------------------------------------------------------------------
# leaf value types


@dataclass(frozen=True)
class Position:
    anchor: str = "center"
    dx: Length | None = None
    dy: Length | None = None
    angle: Angle | None = None
    radius: Length | None = None

    @property
    def is_polar(self) -> bool:
        return self.angle is not None


@dataclass(frozen=True)
class Size:
    width: Length | None = None
    height: Length | None = None


@dataclass
class Expression:
    """A compiled expression: the author's text, and the Monkey C it became."""

    text: str
    code: str
    value: expr.Value
    #: Catalogue paths this expression reads, in first-use order.
    sources: tuple[str, ...]
    #: Support-barrel functions and Toybox modules the emitted code needs.
    barrel: frozenset[str]
    modules: frozenset[str]
    span: Span | None
    #: Set when the whole expression folded to a build-time constant.
    constant: object | None = None
    #: The folded syntax tree, kept so the host-side preview renderer can
    #: evaluate the same expression the device compiles.  Nothing on the device
    #: ever sees this -- ADR 0005's "no runtime evaluator" is about the watch.
    ast: object | None = None

    @property
    def nullable(self) -> bool:
        return self.value.nullable

    @property
    def scale(self) -> float:
        """The constant factor this expression applies to its source, if any.

        Recognises the `source / 1000` idiom -- steps to thousands, centimetres
        to kilometres -- so the overflow lint sizes the *result* rather than the
        raw reading.  Anything more involved returns 1.0, which is the
        conservative answer.
        """
        node = self.ast
        if not isinstance(node, expr.Binary) or node.op not in ("/", "*"):
            return 1.0
        if not isinstance(node.right, expr.Literal):
            return 1.0
        try:
            factor = float(node.right.value)
        except (TypeError, ValueError):
            return 1.0
        if factor == 0:
            return 1.0
        return (1.0 / factor) if node.op == "/" else factor

    @property
    def is_constant(self) -> bool:
        return self.constant is not None


@dataclass
class FontSpec:
    name: str
    source: Path
    #: The declared size, in one of its two spellings.
    #:
    #: A bare number is the legacy form and keeps its exact meaning: em pixels
    #: on the *reference* device (the smallest target), scaled per device when
    #: :attr:`scale` is true.
    #:
    #: A :class:`~wfb.units.Length` is the newer, recommended one: `12px` is
    #: twelve pixels on every device, `18%r` is a fraction of each device's own
    #: minor radius.  Restricted to :data:`wfb.units.SIZE_UNITS` -- the same
    #: `px`/`%r` an `icon`'s `size:` allows, and for the same reason (the sheet
    #: is rasterised before any element is placed, so there is no parent box to
    #: take a `%` of and no font in scope to take a `pt` of).  A `Length`
    #: forbids :attr:`scale`, because its unit has already said whether the
    #: number is per-device.
    size: float | Length
    glyphs: str | None
    antialias: bool
    scale: bool
    span: Span | None
    #: Bake every glyph at one shared advance, so a clock does not shift as its
    #: digits change (`wfb.fonts.bmfont.bake`).
    monospace: bool = False
    #: Where a glyph's ink sits inside that shared cell.  Meaningless, and
    #: therefore an error, without :attr:`monospace`.
    align: str = "center"

    @property
    def resource_id(self) -> str:
        return font_resource_id(self.name)

    @property
    def size_is_length(self) -> bool:
        return isinstance(self.size, Length)

    def pixel_size(self, minor_radius: float, reference_minor: float | None = None) -> int:
        """The nominal em size this font's sheet is rasterised at, on a device
        whose screen has this minor radius.

        ``reference_minor`` is the smallest target's minor radius, which the
        legacy bare-number form scales against (`wfb.units.scaled_font_size`).
        Pass ``None`` where no such reference is in scope -- `wfb.layout`'s
        fallback for a font that was never baked -- and a bare number is taken
        verbatim, exactly as it was before this method existed.  A `Length`
        never needs it: its unit already says whether it is per-device.
        """
        if isinstance(self.size, Length):
            return units.pixel_size(self.size, minor_radius)
        if self.scale and reference_minor is not None:
            return units.scaled_font_size(self.size, minor_radius, reference_minor)
        return round(self.size)


# --------------------------------------------------------------------------
# elements


@dataclass
class Element:
    id: str
    kind: str
    at: Position
    modes: tuple[str, ...]
    z: int | None
    span: Span | None
    lint_allow: frozenset[str] = frozenset()
    lint_reason: str | None = None
    overrides: dict = field(default_factory=dict)
    #: A `wfb.complications` name this element launches on touch and hold
    #: (ADR 0006 §6).  The platform offers exactly one door out of a watch face
    #: -- `Complications.exitTo` -- so an interactive element names a
    #: complication type and the watch opens whatever glance owns it.  Hold is
    #: also the only gesture there is: `WatchFaceDelegate.onTap` fires solely
    #: inside the on-device config editor, on every device that has it.
    on_hold: str | None = None
    #: `visible:` -- a BOOLEAN expression gating whether this element draws at
    #: all (SPEC.md T5).  A separate axis from `when_absent:`, which governs
    #: the element's *value*: **absent means hidden**, because there is no
    #: meaningful placeholder for existence, so a nullable source read here
    #: contributes a null check to the same guard as the condition itself.
    #:
    #: On a `group` this is also conjoined into every descendant's own
    #: `visible` by `Builder._build_group` -- a group emits no draw method, so
    #: gating the subtree has to happen where the subtree still exists as a
    #: tree.  The copy left on the group itself is what the `dead-element`
    #: lint reports against.
    visible: Expression | None = None
    #: `static: true` as the author wrote it -- this element is the *root* of a
    #: static subtree, drawn once into an offscreen buffer and blitted every
    #: frame afterwards.  On a `group` it covers the subtree; on a leaf it is a
    #: subtree of one.
    static: bool = False
    #: The id of the static root this element belongs to, itself included, or
    #: None.  Set by `Builder._apply_static`, not by the author: the emitter
    #: needs to know, for each *flattened* element, which buffer draws it, and
    #: by the time layout has flattened the tree the subtree is gone -- the
    #: same reason `visible:` is pushed down rather than read off the group
    #: (`_push_visible`).
    static_root: str | None = None

    @property
    def symbol(self) -> str:
        """The stable Monkey C symbol derived from the element id (ADR 0003)."""
        return _pascal(self.id)

    def children(self) -> list["Element"]:
        return []

    def expressions(self) -> list[Expression]:
        """Every compiled expression on this element, `visible:` included.

        Kind-specific expressions come from :meth:`_own_expressions`; this
        wrapper appends `visible` so that permission derivation, barrel
        collection and the read plan pick a visibility binding up for free,
        exactly as they do a conditional colour.
        """
        out = self._own_expressions()
        if self.visible is not None:
            out.append(self.visible)
        return out

    def _own_expressions(self) -> list[Expression]:
        return []


@dataclass
class Group(Element):
    size: Size = field(default_factory=Size)
    items: list[Element] = field(default_factory=list)

    def children(self) -> list[Element]:
        return self.items


@dataclass
class Shape(Element):
    shape: str = "rectangle"
    size: Size = field(default_factory=Size)
    radius: Length | None = None
    corner_radius: Length | None = None
    to: Position | None = None
    #: A polygon's vertices, each resolved against the parent box exactly the
    #: way `to` is.  Empty for every other shape.
    points: list[Position] = field(default_factory=list)
    #: `shape: arc` only.  Author degrees: 12 o'clock is 0, clockwise positive,
    #: the same convention `progress` with `style: arc` uses -- and converted by
    #: the same `wfb.layout.garmin_arc`, so there is exactly one convention.
    start_angle: Angle | None = None
    sweep: Angle | None = None
    thickness: Length | None = None
    color: Expression | None = None
    filled: bool = True

    def _own_expressions(self) -> list[Expression]:
        return [e for e in (self.color,) if e]


@dataclass
class Text(Element):
    value: Expression | None = None
    literal: str | None = None
    format: str | None = None
    font: str = "FONT_MEDIUM"
    font_is_custom: bool = False
    color: Expression | None = None
    align: str = "center"
    vertical_align: str = "center"
    when_absent: str | None = None
    placeholder: str | None = None
    fallback: Expression | None = None

    def _own_expressions(self) -> list[Expression]:
        return [e for e in (self.value, self.color, self.fallback) if e]


@dataclass
class Progress(Element):
    style: str = "arc"
    value: Expression | None = None
    maximum: Expression | None = None
    radius: Length | None = None
    thickness: Length | None = None
    start_angle: Angle | None = None
    sweep: Angle | None = None
    size: Size = field(default_factory=Size)
    color: Expression | None = None
    track_color: Expression | None = None
    when_absent: str | None = None
    fallback: Expression | None = None

    def _own_expressions(self) -> list[Expression]:
        return [e for e in (self.value, self.maximum, self.color, self.track_color, self.fallback) if e]


@dataclass
class IconElement(Element):
    icon: str | None = "steps"
    #: The glyph :func:`wfb.icons.resolve_codepoint` resolved ``icon`` to --
    #: what actually gets drawn.  ``icon`` stays around for diagnostics and for
    #: the generated code's comments; this is what baking and codegen use.
    #: Unused when `value_for` is set -- the glyph is chosen on-device instead.
    codepoint: str = "?"
    #: Set instead of `icon`/`codepoint` for a glyph chosen at runtime from a
    #: bound value -- currently only `wfb.catalog.WEATHER_CONDITION_SOURCES`
    #: (`icon_for: weather.condition`, e.g.), resolved through
    #: `WfbWeather.mc`'s lookup, the on-device twin of
    #: `wfb.icons.weather_icon_for_condition`.
    value_for: Expression | None = None
    size: Length | None = None
    color: Expression | None = None

    @property
    def is_dynamic(self) -> bool:
        return self.value_for is not None

    def _own_expressions(self) -> list[Expression]:
        return [e for e in (self.color, self.value_for) if e]


@dataclass
class CarouselItem:
    """One slot in a :class:`Carousel` -- an icon, a reading, and a way out.

    Deliberately not an `Element`: an item has no `at:` of its own.  The
    carousel positions every item from one `pitch:`, which is the whole point
    of it being one element rather than a group of hand-placed ones, and it is
    also what makes the rotation animation a single offset rather than N.
    """

    #: The glyph drawn in this slot, already resolved from `icon:`/`glyph:`.
    codepoint: str
    #: What the author wrote, kept for diagnostics and generated comments.
    icon: str | None
    value: Expression | None = None
    format: str | None = None
    when_absent: str | None = None
    placeholder: str | None = None
    fallback: Expression | None = None
    #: A `wfb.complications` name, opened by a hold on the centre zone.  None
    #: means this item simply consumes the hold and does nothing, which is a
    #: legitimate choice for a reading no glance owns.
    launch: str | None = None
    span: Span | None = None

    def expressions(self) -> list[Expression]:
        return [e for e in (self.value, self.fallback) if e]


@dataclass
class Carousel(Element):
    """A row of data items, the centred one showing its reading.

    Modelled on the stock Forerunner face.  The gesture story is the whole
    reason this is one element: a live watch face receives **only** touch and
    hold (`docs/research/07-carousel-interaction.md` §1), so previous, next and
    "open the glance" have to be told apart by *where* the hold landed.  The
    compiler already knows the resolved box, so it cuts it into three zones and
    the author never writes a coordinate.
    """

    items: list[CarouselItem] = field(default_factory=list)
    size: Size = field(default_factory=Size)
    #: Centre-to-centre spacing between slots.
    pitch: Length | None = None
    #: How many slots are drawn: 1 (no neighbours), 3, or 5.
    slots: int = 3
    icon_size: Length | None = None
    color: Expression | None = None
    #: The neighbouring slots' colour.  Falls back to `color` when unset, which
    #: draws the row flat -- legible, just less obviously a carousel.
    inactive_color: Expression | None = None
    value_font: str = "FONT_SMALL"
    value_font_is_custom: bool = False
    value_color: Expression | None = None
    value_offset: Position | None = None
    #: Seconds the slide animation runs.  0 disables it; it is skipped while
    #: asleep either way, because `WatchUi.animate` crashes the app in low
    #: power mode (`docs/research/07-carousel-interaction.md` §3).
    animate: float = 0.3
    persist: bool = True

    def _own_expressions(self) -> list[Expression]:
        out = [e for e in (self.color, self.inactive_color, self.value_color) if e]
        for item in self.items:
            out.extend(item.expressions())
        return out


@dataclass
class Face:
    format: int
    uuid: str
    name: str
    version: str
    entry: str
    targets: tuple[str, ...]
    palette: dict[str, Color]
    fonts: dict[str, FontSpec]
    elements: list[Element]
    source_path: Path

    def walk(self) -> list[Element]:
        """Every element, parents before children, in document order."""
        return walk_elements(self.elements)

    def draw_order(self) -> list[Element]:
        """Every element that actually draws, in the order it is drawn.

        Document order, then a stable sort by ``z`` -- exactly what
        :class:`wfb.layout.Resolver` does to its flattened ``Placed`` list, and
        with groups dropped for the same reason the emitter skips them: a group
        is a coordinate frame, not something that paints.  Device-independent,
        because ``z`` and document order are, which is what lets the static
        prefix check run once in the IR rather than three times over resolved
        geometry.  ``tests/test_static.py`` pins the two orders together.
        """
        return draw_order(self.elements)

    def static_roots(self) -> list[Element]:
        """The static subtree roots, in document order."""
        return [e for e in self.walk() if e.static]

    def requirements(self) -> catalog.Requirements:
        """Permissions, readers and modules implied by every binding."""
        req = catalog.Requirements()
        for element in self.walk():
            for expression in element.expressions():
                for path in expression.sources:
                    source = catalog.get(path)
                    if source:
                        req.add(source)
        return req

    def barrel_functions(self) -> set[str]:
        used: set[str] = set()
        for element in self.walk():
            for expression in element.expressions():
                used |= expression.barrel
        return used

    def uses_mode(self, mode: str) -> bool:
        return any(mode in element.modes for element in self.walk())


# --------------------------------------------------------------------------
# the semantic pass


class Builder:
    def __init__(self, doc: YamlDocument, bag: Bag) -> None:
        self.doc = doc
        self.bag = bag
        self.palette: dict[str, Color] = {}
        self.fonts: dict[str, FontSpec] = {}
        #: Every name in the `fonts:` block, whether or not it survived
        #: `_build_fonts`.  A rejected entry is still a *declared* one, and
        #: saying otherwise is how the old `unknown font` note came to tell an
        #: author "declared fonts: (none declared)" about a file declaring three.
        self.declared_fonts: dict[str, Span | None] = {}
        #: Declared names that failed their own check.  Every element naming
        #: one would otherwise raise a second, derived error blaming the
        #: element for a mistake made in the `fonts:` block.
        self.rejected_fonts: set[str] = set()
        self.scope = expr.Scope()
        self.seen_ids: dict[str, Span | None] = {}
        #: Derived Monkey C symbol -> the element id and span that claimed it
        #: first. Two distinct ids can still generate the same symbol
        #: (`temp_low` and `tempLow` both become `TEMP_LOW`), which the
        #: compiler must catch itself rather than let `monkeyc` discover it
        #: through a `Redefinition of ...` error pointing at generated code.
        self.seen_symbols: dict[str, tuple[str, Span | None]] = {}

    # -- entry point ------------------------------------------------------

    def build(self) -> Face | None:
        data = self.doc.data
        self._build_palette(data.get("palette") or {})
        self._build_fonts(data.get("fonts") or {})
        self._build_scope()

        elements = self._build_elements(data.get("elements") or [], ("elements",))
        if not self.bag.ok():
            return None
        self._apply_static(elements)
        if not self.bag.ok():
            return None

        face = data["face"]
        name = face["name"]
        return Face(
            format=int(data["format"]),
            uuid=face["id"],
            name=name,
            version=face.get("version", "1.0.0"),
            entry=face.get("entry") or _pascal(name) or "WatchFace",
            targets=tuple(data["targets"]),
            palette=self.palette,
            fonts=self.fonts,
            elements=elements,
            source_path=self.doc.path,
        )

    # -- palette, fonts, scope --------------------------------------------

    def _build_palette(self, raw: dict) -> None:
        for name, value in raw.items():
            span = self.doc.span(raw, name)
            if isinstance(value, str) and value.startswith(("palette.", "config.")):
                self.bag.error(
                    "palette",
                    f"palette entry {name!r} refers to {value!r}",
                    span,
                    notes=["palette entries must be literal colours in this format version"],
                )
                continue
            try:
                self.palette[name] = Color.parse(value, what=f"palette.{name}")
            except ColorError as exc:
                self.bag.error("palette", str(exc), span)

    def _build_fonts(self, raw: dict) -> None:
        base = self.doc.path.parent
        for name, spec in raw.items():
            span = self.doc.span(raw, name)
            self.declared_fonts[name] = span
            source = base / str(spec["source"])
            if not source.exists():
                self.bag.error(
                    "font",
                    f"font {name!r}: source file not found: {spec['source']}",
                    self.doc.span(spec, "source"),
                    notes=[f"resolved against the design file, to {source}"],
                )
                self.rejected_fonts.add(name)
                continue
            size = self._font_size(name, spec)
            if size is None:
                self.rejected_fonts.add(name)
                continue
            scale = bool(spec.get("scale", True))
            if isinstance(size, Length):
                if "scale" in spec:
                    self.bag.error(
                        "font",
                        f"font {name!r}: 'scale' cannot be combined with a size "
                        f"given as a length ({size})",
                        self.doc.span(spec, "scale"),
                        notes=[
                            "the unit already decides: 'px' is the same pixel count on "
                            "every device, '%r' is a fraction of each device's own screen",
                            "drop 'scale', or go back to a bare number for the "
                            "reference-device-plus-scale-factor meaning",
                        ],
                    )
                    self.rejected_fonts.add(name)
                    continue
                # Meaningless for a length, and left false so nothing downstream
                # can consult it and get a "scaled" answer for a size that is
                # already per-device by construction.
                scale = False
            monospace = bool(spec.get("monospace", False))
            if "align" in spec and not monospace:
                self.bag.error(
                    "font",
                    f"font {name!r}: 'align' needs 'monospace: true'",
                    self.doc.span(spec, "align"),
                    notes=[
                        "align says where a glyph's ink sits inside its cell, and a "
                        "proportional font has no cell -- every glyph is exactly as "
                        "wide as it needs to be",
                        "add 'monospace: true', or drop 'align'",
                    ],
                )
                self.rejected_fonts.add(name)
                continue
            self.fonts[name] = FontSpec(
                name=name,
                source=source,
                size=size,
                glyphs=spec.get("glyphs"),
                antialias=bool(spec.get("antialias", False)),
                scale=scale,
                span=span,
                monospace=monospace,
                align=str(spec.get("align", "center")),
            )

    def _font_size(self, name: str, spec: dict) -> float | Length | None:
        """`fonts.<name>.size`, in whichever of its two spellings was used.

        A bare number stays a `float` -- deliberately not normalised into a
        `Length`, because the two mean genuinely different things: the number
        is pixels *on the reference device* and is scaled from there, while
        `12px` is twelve pixels everywhere.  Collapsing them would have to pick
        one of those meanings and silently change every design written against
        the other.
        """
        raw = spec["size"]
        if isinstance(raw, (int, float)) and not isinstance(raw, bool):
            if float(raw) <= 0:
                self.bag.error(
                    "font", f"font {name!r}: size must be greater than zero",
                    self.doc.span(spec, "size"),
                )
                return None
            return float(raw)
        try:
            size = Length.parse(raw, what=f"font {name!r}: size")
        except UnitError as exc:
            self.bag.error("units", str(exc), self.doc.span(spec, "size"))
            return None
        if size.unit not in units.SIZE_UNITS:
            self.bag.error(
                "font",
                f"font {name!r}: size must be px or %r, not {size.unit}",
                self.doc.span(spec, "size"),
                notes=[
                    "a font's sheet is rasterised before any element is placed, so its "
                    "size cannot depend on a parent box (%) or on a font (pt) -- there "
                    "is no box yet, and the font being sized is the one 'pt' would "
                    "measure against",
                    "use '%r' for a size that follows the screen, e.g. '18%r'",
                ],
            )
            return None
        if size.value <= 0:
            self.bag.error(
                "font", f"font {name!r}: size must be greater than zero",
                self.doc.span(spec, "size"),
            )
            return None
        return size

    def _build_scope(self) -> None:
        """Populate the expression scope: catalogue sources, then the palette.

        Nullable sources bind to a *guarded local* named after the source, not
        to the raw API read.  The generator declares that local behind a null
        check, so the emitted expression never dereferences a null.
        """
        for path, source in catalog.CATALOG.items():
            self.scope.define(
                path,
                expr.Binding(
                    expr.Value(source.type, source.guard_needed),
                    code=local_name(path),
                    kind="source",
                ),
            )
        for name, color in self.palette.items():
            self.scope.define(
                f"palette.{name}",
                expr.Binding(
                    expr.Value(Type.COLOR),
                    code=f"Palette.{name.upper()}",
                    constant=color.value,
                    kind="palette",
                ),
            )
        self.scope.used.clear()

    # -- elements ---------------------------------------------------------

    def _build_elements(self, raw: list, path: tuple) -> list[Element]:
        out: list[Element] = []
        for index, node in enumerate(raw):
            element = self._build_element(node, path + (index,))
            if element is not None:
                out.append(element)
        return out

    def _build_element(self, node: dict, path: tuple) -> Element | None:
        span = self.doc.span_for_path(list(path))
        element_id = node["id"]
        if element_id in self.seen_ids:
            first = self.seen_ids[element_id]
            self.bag.error(
                "duplicate-id",
                f"duplicate element id {element_id!r}",
                self.doc.span(node, "id"),
                notes=[f"first declared at {first}"] if first else [],
            )
            return None
        self.seen_ids[element_id] = span
        if not self._check_symbol_collision(element_id, node, span):
            return None

        common = dict(
            id=element_id,
            kind=node["type"],
            at=self._position(node.get("at"), node, "at"),
            modes=tuple(node.get("modes") or ("active",)),
            z=node.get("z"),
            span=span,
            lint_allow=frozenset((node.get("lint") or {}).get("allow", ())),
            lint_reason=(node.get("lint") or {}).get("reason"),
            overrides=dict(node.get("overrides") or {}),
            on_hold=self._hold_target(node),
            visible=self._visible(node),
            static=bool(node.get("static", False)),
        )

        builders = {
            "group": self._build_group,
            "shape": self._build_shape,
            "text": self._build_text,
            "progress": self._build_progress,
            "icon": self._build_icon,
            "carousel": self._build_carousel,
        }
        builder = builders.get(node["type"])
        if builder is None:  # unreachable once the schema has run
            self.bag.error("element", f"unsupported element type {node['type']!r}", span)
            return None
        element = builder(node, common, path)
        if element is not None:
            self._resolve_hold_auto(element)
        return element

    def _check_symbol_collision(self, element_id: str, node: dict, span: Span | None) -> bool:
        """Reject two distinct ids that derive the same Monkey C symbol.

        ``_build_element`` above already rejects a literal duplicate id; this
        catches the case the emitter would otherwise discover on the
        generator's behalf, four `Redefinition of ...` errors deep, pointing
        at *generated* line numbers rather than the author's YAML -- exactly
        what the diagnostics module exists to prevent.  Checked against both
        derived forms (`element_const_prefix`, `element_method_name`) because
        they fold case and separators independently; in practice they collide
        together, but there is no reason to assume that stays true forever.
        """
        candidates = [element_const_prefix(element_id), element_method_name(element_id)]
        if node.get("type") == "group":
            # A group may become a static subtree root, which owns a third
            # symbol.  Reserved unconditionally, like the two above: whether a
            # group is static is the author's to change later, and a name that
            # only collides after an unrelated edit is the worst kind.
            candidates.append(static_group_method(element_id))
        collisions: list[tuple[str, str, Span | None]] = []
        for symbol in candidates:
            claimed = self.seen_symbols.get(symbol)
            if claimed is not None and claimed[0] != element_id:
                collisions.append((symbol, claimed[0], claimed[1]))
        if collisions:
            other_id = collisions[0][1]
            other_span = collisions[0][2]
            symbols = ", ".join(repr(symbol) for symbol, _, _ in collisions)
            notes = ["element ids only need to be distinct as literal strings today, "
                     "but codegen derives one Monkey C symbol per id, folding case and "
                     "separators away -- 'temp_low' and 'tempLow' both become 'TEMP_LOW'"]
            if other_span is not None:
                notes.insert(0, f"{other_id!r} first declared at {other_span}")
            self.bag.error(
                "duplicate-id",
                f"element id {element_id!r} generates the same Monkey C symbol as "
                f"{other_id!r} ({symbols})",
                self.doc.span(node, "id") or span,
                notes=notes,
            )
            return False
        for symbol in candidates:
            self.seen_symbols[symbol] = (element_id, span)
        return True
        return ok

    def _hold_target(self, node: dict) -> str | None:
        """Validate `on_hold:` against the launchable complication table.

        A watch face cannot open an arbitrary app; `Complications.exitTo` is
        the only exit the platform offers, so the value here names a
        complication *type* and the watch opens whatever owns it.  Checked
        against :mod:`wfb.complications`, which is generated from the SDK's own
        `COMPLICATION_TYPE_*` table -- an invented name would compile to an
        undefined symbol, so catching it here points at the author's line
        instead of a generated one.

        `on_tap:` was this key's name until the gesture was researched
        properly (`docs/research/07-carousel-interaction.md` 1a): a live watch
        face never receives a tap, because `WatchFaceDelegate.onTap` fires
        only inside the on-device config editor.  The old spelling is still
        accepted by the schema purely so the rename can be reported here,
        against the author's own line.

        `on_hold: auto` is validated here only as far as recognising the
        sentinel and passing it through unresolved -- this runs from
        `common`, *before* the kind-specific builder gives the element a
        value binding to resolve `auto` from.  `Builder._resolve_hold_auto`
        does the actual resolution once the element is fully built (SPEC.md
        D3), the same deferred-pass shape `_check_tiers` used to run at
        (deleted along with the per-source refresh-cadence concept -- see
        CLAUDE.md's Phase 3 notes on this session).
        """
        if "on_tap" in node:
            self.bag.error(
                "on-tap-renamed",
                "'on_tap:' has been renamed to 'on_hold:'",
                self.doc.span(node, "on_tap"),
                notes=["a live watch face never receives a tap -- "
                       "WatchFaceDelegate.onTap fires only in the on-device config "
                       "editor, so this was always delivered by touch and hold",
                       "the value is unchanged; only the key name moves"],
            )
            return None
        raw = node.get("on_hold")
        if raw is None:
            return None
        name = str(raw)
        if name == HOLD_AUTO:
            return HOLD_AUTO
        if complications.get(name) is not None:
            return name
        near = complications.suggest(name)
        notes = []
        if near:
            notes.append("did you mean: " + ", ".join(near) + "?")
        notes.append("run `wfb complications` for the full list of "
                     f"{len(complications.TYPES)} launch targets")
        self.bag.error(
            "on-hold",
            f"unknown hold target {name!r}",
            self.doc.span(node, "on_hold"),
            notes=notes,
        )
        return None

    def _resolve_hold_auto(self, element: Element) -> None:
        """Resolve `on_hold: auto` and a carousel item's `launch: auto`.

        Deferred here, called from `_build_element` right after the
        kind-specific builder returns -- exactly where `_check_tiers` used to
        run before the per-source refresh-cadence concept was deleted, and for the same
        reason: this needs a *fully-built* element, since `_hold_target`
        (called from `common`, before the builder runs) has no value binding
        yet to resolve `auto` from.

        By the time this returns, `element.on_hold` (and every carousel
        item's `launch`) is either a real `wfb.complications.TYPES` key or
        `None` -- never the `HOLD_AUTO` sentinel -- so
        `wfb/emit/monkeyc.py`, which indexes `complications.TYPES` with it
        directly, needs no change at all.
        """
        if isinstance(element, Carousel) and element.on_hold is not None:
            # A carousel's whole box is cut into three hold zones
            # (`_emit_carousel_zones`), so there is no leftover hold for an
            # element-level `on_hold:` to mean anything -- the emitter branches
            # to the zones and never reads the field.  Until this check it was
            # accepted in silence and dropped, which is precisely how a design
            # loses something it asked for (ADR 0009).  `auto` lands here too
            # and gets this message rather than the generic "nothing to resolve
            # from", which would be true but unhelpful.
            self.bag.error(
                "carousel-on-hold",
                f"{element.id}: a carousel cannot take 'on_hold:'",
                element.span,
                notes=["a carousel already uses the whole hold gesture: left and "
                       "right cycle the row, and the centre opens the selected "
                       "item's target",
                       "put 'launch:' on the item that should open something "
                       "instead -- 'launch: auto' resolves it from that item's "
                       "own value"],
            )
            element.on_hold = None
        if element.on_hold == HOLD_AUTO:
            element.on_hold = self._resolve_auto_target(
                element.id, "on_hold", self._hold_auto_sources(element), element.span)
        if isinstance(element, Carousel):
            for index, item in enumerate(element.items):
                if item.launch != HOLD_AUTO:
                    continue
                sources = item.value.sources if item.value is not None else ()
                item.launch = self._resolve_auto_target(
                    f"{element.id}: item {index}", "launch", sources,
                    item.span or element.span)

    @staticmethod
    def _hold_auto_sources(element: Element) -> tuple[str, ...]:
        """The catalogue paths `on_hold: auto` may resolve from, for one element.

        SPEC.md D3: the element's own **value** expression(s) only --
        deliberately not `color:`/`max:`, since a conditional colour's
        reference is not what the element is *about*.  A `text`'s `value:`,
        a `progress`'s `value:` (not `max:`), and an `icon`'s `icon_for:`
        (not a static `icon:`/`glyph:`, which reads no source at all).

        This intentionally is **not** `wfb.emit.monkeyc.ReadPlan.
        _value_expressions` reused: that helper answers a different question
        (which expressions a `when_absent:` policy governs) and its answer
        differs from this one in exactly the two ways SPEC.md calls out --
        `Progress` there includes `max:` too (one absent reading is as
        absent as the other, for a fill *fraction*), and it does not cover
        `IconElement` at all (an icon has no `when_absent:` to govern).
        Forcing one shape onto both questions would make one of them wrong,
        so this stays a second, smaller helper rather than an import.
        """
        if isinstance(element, Text):
            return element.value.sources if element.value is not None else ()
        if isinstance(element, Progress):
            return element.value.sources if element.value is not None else ()
        if isinstance(element, IconElement):
            return element.value_for.sources if element.value_for is not None else ()
        return ()

    def _resolve_auto_target(self, label: str, key: str, sources: tuple[str, ...],
                             span: Span | None) -> str | None:
        """Resolve `auto` to exactly one `wfb.complications.TYPES` name.

        SPEC.md D3's three outcomes: exactly one distinct non-None
        `Source.launch_complication` among ``sources`` resolves; zero
        (including no value binding at all) is `hold-auto-unresolved`; more
        than one distinct is `hold-auto-ambiguous`.  Both are errors, not
        warnings -- guessing here would silently open the wrong glance, which
        is exactly the class of failure this compiler exists to prevent.
        """
        found: dict[str, str] = {}
        for path in sources:
            source = catalog.get(path)
            target = source.launch_complication if source is not None else None
            if target is not None and target not in found:
                found[target] = path
        if len(found) == 1:
            return next(iter(found))
        bound = ", ".join(repr(p) for p in sources) if sources else "(none)"
        if not found:
            self.bag.error(
                "hold-auto-unresolved",
                f"{label}: '{key}: auto' could not resolve a hold target -- "
                f"bound source(s): {bound}",
                span,
                notes=[
                    "none of this element's bound source(s) has a conventional "
                    "complication counterpart (wfb.catalog.Source.launch_complication)",
                    "name a target explicitly instead of 'auto' -- run "
                    "`wfb complications` for the full list",
                ],
            )
            return None
        candidates = ", ".join(repr(name) for name in sorted(found))
        self.bag.error(
            "hold-auto-ambiguous",
            f"{label}: 'auto' is ambiguous between {candidates} -- "
            f"bound source(s): {bound}",
            span,
            notes=["name one explicitly instead of 'auto' -- run "
                   "`wfb complications` for the full list"],
        )
        return None

    def _visible(self, node: dict) -> Expression | None:
        """Compile and type-check `visible:`.

        The one requirement beyond a normal expression is the static type: a
        gate that is not a boolean is a mistake the author wants named, not a
        truthiness rule invented on their behalf (Monkey C has no truthy
        Number, so `visible: activity.steps` would not even compile).

        Deliberately no `when_absent:` companion.  `when_absent:` chooses a
        substitute *value*; there is no substitute for existence, so a
        nullable source here means exactly one thing -- absent is hidden --
        and the emitter folds the null check into the same guard as the
        condition.
        """
        expression = self._expression(node, "visible")
        if expression is None:
            return None
        if expression.value.type is not Type.BOOLEAN:
            self.bag.error(
                "type",
                f"visible must be a boolean, got {expression.value}",
                expression.span,
                notes=["write a condition: a comparison ('activity.steps > 0'), "
                       "'and'/'or'/'not', or a '?:' whose branches are booleans",
                       "there is no truthiness rule -- a Number is not a condition"],
            )
            return None
        return expression

    def _conjoin_visible(self, outer: Expression, inner: Expression | None) -> Expression | None:
        """``outer and inner`` as one real :class:`Expression`.

        This is how a group gates its subtree.  A `group` emits no draw method
        of its own (`wfb.emit.monkeyc` skips `kind == "group"`) and
        `wfb.layout` flattens the tree, so by the time anything downstream sees
        the design there is no subtree left to gate -- the conjunction has to
        happen here, while the parent still owns its children.

        Building a genuine `Expression` rather than splicing code strings is
        what makes every consumer work unchanged: `ReadPlan` hoists the
        group's readers and null-checks its locals because `sources` names
        them, `wfb.preview.evaluate` walks the merged `ast`, and the linter's
        constant folding sees through the whole conjunction.  Nested groups
        compose because the inner group has already conjoined its own
        condition into its children before the outer one runs.
        """
        if inner is None:
            return outer
        combined = expr.Binary("and", outer.ast, inner.ast)
        try:
            value = expr.check(combined, self.scope)
            folded = expr.fold(combined, self.scope, fold_colors=False)
            code = expr.emit(folded, self.scope)
        except expr.ExprError as exc:  # unreachable: both halves already checked
            self.bag.error(exc.code or "expression", f"visible: {exc.message}",
                           inner.span or outer.span, notes=exc.notes)
            return inner
        constant = folded.value if isinstance(folded, expr.Literal) else None
        return Expression(
            # Parenthesised: this text is what diagnostics and the generated
            # doc comment show, and `a or b and c` read back flat would claim
            # a precedence the emitted code (correctly) does not have.
            text=f"({outer.text}) and ({inner.text})",
            code=code,
            value=value,
            sources=tuple(sorted(set(outer.sources) | set(inner.sources))),
            barrel=outer.barrel | inner.barrel,
            modules=outer.modules | inner.modules,
            # The child's own line where it has one: that is where an author
            # reading a `dead-element` warning expects to look first.
            span=inner.span or outer.span,
            constant=constant,
            ast=folded,
        )

    def _push_visible(self, group: "Group") -> None:
        """Conjoin a group's `visible:` into every element beneath it.

        Every *descendant*, not just the direct children: an inner group has
        already pushed its own condition down by the time the outer group is
        built, so touching only the inner `Group` object would leave the
        grandchildren ungated.  Pushing into the inner group as well keeps its
        own record honest -- it is what `dead-element` reports against, and
        what `wfb preview` would consult if groups ever drew anything.
        """
        if group.visible is None:
            return

        def visit(items: list[Element]) -> None:
            for child in items:
                child.visible = self._conjoin_visible(group.visible, child.visible)
                visit(child.children())

        visit(group.items)

    # -- static subtrees ---------------------------------------------------

    def _apply_static(self, elements: list[Element]) -> None:
        """Mark, then check, every `static: true` subtree.

        A static subtree is drawn once into an offscreen ``BufferedBitmap`` and
        blitted every frame afterwards.  The buffer is **opaque and
        full-screen**, because transparency could not be established from the
        SDK and cannot be observed in this container -- the whole argument is in
        `docs/research/probes/static-buffer/`.  Everything checked here follows
        from that one decision plus "the buffer is filled exactly once":

        * a binding would make the content change, and the buffer would not;
        * a carousel holds a selection, which is a binding by another name;
        * `low_power` would charge the blit against the partial-update budget by
          clip *area* (CLAUDE.md constraint 4), which is the whole screen here;
        * a nested `static:` is a second buffer for content the outer one
          already draws;
        * mixed `modes:` inside one buffer would blit elements into a mode they
          asked not to be drawn in;
        * and an opaque blit erases whatever is under it, so the static content
          has to come first.

        Every one of these is an error rather than a warning: each is a design
        that would compile and then be silently wrong on the wrist, which is the
        failure mode this compiler exists to remove.
        """
        roots = [e for e in walk_elements(elements) if e.static]
        if not roots:
            return
        for root in roots:
            self._mark_static(root, root)
        if not self._check_static_subtrees(roots):
            return
        self._check_static_modes(roots)
        self._check_static_order(elements, roots)

    def _mark_static(self, root: Element, element: Element) -> None:
        if element is not root and element.static:
            self.bag.error(
                "static",
                f"{element.id!r} declares `static: true` inside the static "
                f"subtree of {root.id!r}",
                element.span,
                notes=[f"{root.id!r} already draws it into the same buffer",
                       "delete the inner `static: true`"],
            )
            return
        element.static_root = root.id
        for child in element.children():
            self._mark_static(root, child)

    def _check_static_subtrees(self, roots: list[Element]) -> bool:
        ok = True
        for root in roots:
            for element in walk_elements([root]):
                if isinstance(element, Carousel):
                    self.bag.error(
                        "static",
                        f"{element.id!r} is a carousel and cannot be static",
                        element.span,
                        notes=["a carousel remembers which item is centred and "
                               "redraws when the wearer moves it -- a buffer "
                               "filled once would freeze it",
                               f"take it out of {root.id!r}"
                               if element is not root else
                               "drop `static: true` from it"],
                    )
                    ok = False
                    continue
                for expression in element.expressions():
                    if not expression.sources:
                        continue
                    where = ("visible" if expression is element.visible
                             else "a value")
                    self.bag.error(
                        "static",
                        f"{element.id!r} binds {where} to "
                        f"{_and_paths(expression.sources)} inside the static "
                        f"subtree of {root.id!r}",
                        expression.span or element.span,
                        notes=["a static subtree is drawn once, into a buffer "
                               "that is never refilled -- a reading bound here "
                               "would freeze at whatever it was on the first "
                               "frame",
                               "move this element out of the static group, or "
                               "replace the binding with a constant"],
                    )
                    ok = False
                if "low_power" in element.modes:
                    self.bag.error(
                        "static",
                        f"{element.id!r} is static and declares "
                        "`modes: [... low_power ...]`",
                        element.span,
                        notes=["onPartialUpdate is charged by clip *area*, and "
                               "the buffer is the whole screen -- one blit a "
                               "second would spend the power budget, which is "
                               "disabled permanently once exceeded",
                               "`active` and `always_on` are both fine"],
                    )
                    ok = False
        return ok

    def _check_static_modes(self, roots: list[Element]) -> None:
        """One buffer, so one mode set: everything static must agree."""
        reference: Element | None = None
        for root in roots:
            for element in walk_elements([root]):
                if element.kind == "group":
                    continue  # a group paints nothing; its modes gate nothing
                if reference is None:
                    reference = element
                elif set(element.modes) != set(reference.modes):
                    self.bag.error(
                        "static",
                        f"{element.id!r} draws in "
                        f"{', '.join(element.modes)} but the static "
                        f"{reference.id!r} draws in "
                        f"{', '.join(reference.modes)}",
                        element.span,
                        notes=["all static content shares one buffer, and a "
                               "buffer is blitted as a whole -- so every "
                               "element in it must draw in the same modes",
                               f"give both the same `modes:`, or take "
                               f"{element.id!r} out of the static content"],
                    )

    def _check_static_order(self, elements: list[Element], roots: list[Element]) -> None:
        """Static content must be a contiguous prefix of draw order.

        The buffer is opaque and full-screen (probe question (a)), so its blit
        overwrites every pixel under it.  Anything drawn before it would
        disappear.  Reported here, against the first element that is out of
        place, rather than left to be discovered on the wrist.
        """
        order = draw_order(elements)
        static_ids = {e.id for e in walk_elements(roots) if e.kind != "group"}
        if not static_ids:
            return
        count = len(static_ids)
        prefix = order[:count]
        stray = [e for e in prefix if e.id not in static_ids]
        if stray:
            first_static = next((e for e in order if e.id in static_ids), None)
            self.bag.error(
                "static",
                f"{stray[0].id!r} is drawn before, or in between, the static "
                "content",
                stray[0].span,
                notes=["static content is buffered into one opaque full-screen "
                       "bitmap, so it must be drawn first -- the blit would "
                       "erase anything under it",
                       f"move {stray[0].id!r} after the static content, or give "
                       "it a higher `z:`"]
                + ([f"the static content starts at {first_static.id!r}"]
                   if first_static is not None else []),
            )
            return
        # Two static roots may not interleave either.  Each is emitted as one
        # `drawStatic<Id>` called in order, so an element of root A drawn
        # between two of root B would end up painted out of order inside the
        # buffer -- silently, since the blit looks the same either way.
        seen: set[str] = set()
        previous: str | None = None
        for element in prefix:
            root = element.static_root
            if root == previous:
                continue
            if root in seen:
                self.bag.error(
                    "static",
                    f"the static content of {root!r} is split apart by "
                    f"{previous!r}",
                    element.span,
                    notes=["each static group is painted into the buffer in one "
                           "run, so two of them cannot interleave",
                           "usually a `z:` on one of the elements is what "
                           "reordered them"],
                )
                return
            seen.add(root)
            previous = root

    def _build_group(self, node: dict, common: dict, path: tuple) -> Element:
        group = Group(
            **common,
            size=self._size(node.get("size")),
            items=self._build_elements(node["children"], path + ("children",)),
        )
        self._push_visible(group)
        return group

    def _build_shape(self, node: dict, common: dict, path: tuple) -> Element:
        shape = node["shape"]
        raw_points = node.get("points") or []
        element = Shape(
            **common,
            shape=shape,
            size=self._size(node.get("size")),
            radius=self._length(node, "radius"),
            corner_radius=self._length(node, "corner_radius"),
            to=self._position(node.get("to"), node, "to") if "to" in node else None,
            points=[self._position(raw, node, "points")
                    for raw in raw_points if isinstance(raw, dict)],
            start_angle=self._angle(node, "start_angle"),
            sweep=self._angle(node, "sweep"),
            thickness=self._length(node, "thickness"),
            color=self._color_expression(node, "color"),
            filled=bool(node.get("filled", True)),
        )
        if shape == "circle" and element.radius is None:
            self._require(node, "radius", "a circle needs a radius")
        if shape == "rectangle" and (element.size.width is None or element.size.height is None):
            self._require(node, "size", "a rectangle needs size.width and size.height")
        if shape == "rounded_rectangle" and element.corner_radius is None:
            self._require(node, "corner_radius", "a rounded rectangle needs a corner_radius")
        if shape == "line" and element.to is None:
            self._require(node, "to", "a line needs a 'to' position")
        self._check_shape_keys(node, shape)
        if shape == "arc":
            if element.radius is None:
                self._require(node, "radius", "an arc needs a radius")
            if "filled" in node:
                # CLAUDE.md constraint 3: there is no fillArc, fillSector or
                # drawSector anywhere in the API.  Silently ignoring `filled:`
                # here would promise a solid sector the platform cannot draw.
                self.bag.error(
                    "element",
                    "'filled' is not accepted on 'shape: arc' -- Connect IQ has no "
                    "filled-arc primitive",
                    self.doc.span(node, "filled") or self.doc.span(node),
                    notes=["there is no fillArc, fillSector or drawSector in "
                           "Toybox.Graphics.Dc: an arc is setPenWidth + drawArc and "
                           "nothing else, so 'thickness' is its only weight control",
                           "for a solid disc use 'shape: circle'; for a solid wedge, "
                           "approximate it with 'shape: polygon'"],
                )
        if shape == "ellipse" and (element.size.width is None or element.size.height is None):
            self._require(node, "size", "an ellipse needs size.width and size.height")
        if shape == "polygon":
            if len(element.points) < 3:
                self._require(node, "points", "a polygon needs at least 3 points")
            if not element.filled:
                # Dc has fillPolygon and no drawPolygon -- confirmed against
                # $CIQ_SDK/doc/Toybox/Graphics/Dc.html and each target's own
                # api.debug.xml.  An outline would have to be emitted as N
                # drawLine calls, which is a different element, not this one.
                self.bag.error(
                    "element",
                    "'filled: false' is not accepted on 'shape: polygon' -- "
                    "Toybox.Graphics.Dc has fillPolygon but no drawPolygon",
                    self.doc.span(node, "filled") or self.doc.span(node),
                    notes=["for an outline, draw the edges as 'shape: line' "
                           "elements, which is what a drawPolygon would have "
                           "compiled to anyway"],
                )
        return element

    def _check_shape_keys(self, node: dict, shape: str) -> None:
        """Reject a geometry key the chosen `shape:` does not read.

        Every one of these was previously parsed by the schema, resolved into
        the IR, and then never looked at -- so `shape: rounded_rectangle` with
        a `radius:` (rather than `corner_radius:`) drew square corners and said
        nothing, and `thickness:` on a shape left filled did nothing at all.
        That is the same silent-key class as the `filled:` bug, and ADR 0009's
        rule applies to it: a design must not quietly lose something it asked
        for.

        `thickness:` is checked separately from the table because whether it
        is read depends on `filled:`, not on the shape: a `line` and an `arc`
        always use it, any other shape uses it only when outlined.
        """
        for key in sorted(_ALL_SHAPE_GEOMETRY_KEYS - SHAPE_GEOMETRY_KEYS[shape]):
            if key not in node:
                continue
            owners = sorted(s for s, keys in SHAPE_GEOMETRY_KEYS.items() if key in keys)
            notes = [
                f"'shape: {shape}' reads: "
                + (", ".join(sorted(SHAPE_GEOMETRY_KEYS[shape])) or "(no geometry keys)"),
                f"{key!r} belongs to " + " and ".join(f"'shape: {s}'" for s in owners),
            ]
            self.bag.error(
                "element",
                f"{key!r} is not used by 'shape: {shape}'",
                self.doc.span(node, key) or self.doc.span(node),
                notes=notes,
            )
        if "thickness" in node and shape not in ("line", "arc") \
                and bool(node.get("filled", True)):
            self.bag.error(
                "element",
                f"'thickness' is not used by a filled 'shape: {shape}'",
                self.doc.span(node, "thickness") or self.doc.span(node),
                notes=["thickness is the pen width of an outline; a filled shape has "
                       "no outline to draw",
                       "add 'filled: false' to outline this shape, or drop "
                       "'thickness'"],
            )

    def _build_text(self, node: dict, common: dict, path: tuple) -> Element:
        value = self._expression(node, "value") if "value" in node else None
        element = Text(
            **common,
            value=value,
            literal=node.get("text"),
            format=node.get("format"),
            color=self._color_expression(node, "color"),
            align=node.get("align", "center"),
            vertical_align=node.get("vertical_align", "center"),
            when_absent=node.get("when_absent"),
            placeholder=node.get("placeholder"),
            fallback=self._expression(node, "fallback") if "fallback" in node else None,
        )
        self._resolve_font(node, element)
        if value is not None:
            self._check_absence(node, element, value, element.when_absent, element.placeholder,
                                element.fallback)
            self._check_format(node, value, element.format)
        self._check_other_absence(node, element, "color", element.color)
        self._check_reachable_substitute(node, element, "'color'",
                                         (element.value,), (element.color,))
        return element

    def _build_progress(self, node: dict, common: dict, path: tuple) -> Element:
        value = self._expression(node, "value")
        maximum = self._expression(node, "max")
        element = Progress(
            **common,
            style=node["style"],
            value=value,
            maximum=maximum,
            radius=self._length(node, "radius"),
            thickness=self._length(node, "thickness"),
            start_angle=self._angle(node, "start_angle"),
            sweep=self._angle(node, "sweep"),
            size=self._size(node.get("size")),
            color=self._color_expression(node, "color"),
            track_color=self._color_expression(node, "track_color"),
            when_absent=node.get("when_absent"),
            fallback=self._expression(node, "fallback") if "fallback" in node else None,
        )
        for name, bound in (("value", value), ("max", maximum)):
            if bound and not bound.value.type.is_numeric():
                self.bag.error(
                    "type",
                    f"progress {name} must be a number, got {bound.value}",
                    self.doc.span(node, name),
                )
        if value is not None or maximum is not None:
            combined = expr.Value(
                Type.NUMBER,
                bool((value and value.nullable) or (maximum and maximum.nullable)),
            )
            probe = Expression("value/max", "", combined, (), frozenset(), frozenset(), None)
            self._check_absence(node, element, probe, element.when_absent, None, element.fallback,
                                key="value")
            self._check_fallback_fraction(node, element)
        self._check_other_absence(node, element, "color", element.color)
        self._check_other_absence(node, element, "track_color", element.track_color)
        self._check_reachable_substitute(node, element, "'color'/'track_color'",
                                         (element.value, element.maximum),
                                         (element.color, element.track_color))
        return element

    def _build_icon(self, node: dict, common: dict, path: tuple) -> Element:
        name = node.get("icon")
        has_icon_for = "icon_for" in node
        has_glyph = "glyph" in node
        chosen = [k for k in ("icon", "icon_for", "glyph") if k in node]
        if len(chosen) != 1:
            self.bag.error(
                "icon",
                "an icon element needs exactly one of 'icon', 'glyph' or 'icon_for'"
                + (f" -- got {', '.join(repr(k) for k in chosen)}" if chosen else ""),
                self.doc.span(node),
                notes=["'icon' names a glyph from the built-in catalogue (run "
                       "`wfb sources` for the list)",
                       "'glyph' is any codepoint in the vendored icon font, written "
                       "'U+XXXX' -- for the ~10,000 glyphs the catalogue does not name",
                       "'icon_for' chooses one at runtime from a bound value -- see "
                       "wfb.catalog.WEATHER_CONDITION_SOURCES for what it accepts"],
            )

        size = self._length(node, "size")
        if size is not None and size.unit not in units.SIZE_UNITS:
            self.bag.error(
                "icon",
                f"icon size must be px or %r, not {size.unit}",
                self.doc.span(node, "size"),
                notes=["an icon's font is baked once, before layout runs, so its size "
                       "cannot depend on a parent box (%) or an element's own font (pt)"],
            )
            size = None

        if has_icon_for:
            value_for = self._expression(node, "icon_for")
            if value_for is not None and (
                not isinstance(value_for.ast, expr.Ref)
                or len(value_for.sources) != 1
                or value_for.sources[0] not in catalog.WEATHER_CONDITION_SOURCES
            ):
                self.bag.error(
                    "icon",
                    f"icon_for must be exactly one of: "
                    f"{', '.join(sorted(catalog.WEATHER_CONDITION_SOURCES))} "
                    f"-- not {value_for.text!r}",
                    self.doc.span(node, "icon_for"),
                    notes=["arithmetic or a conditional would break the "
                           "condition-to-glyph lookup, which needs the raw "
                           "Weather.CONDITION_* value"],
                )
                value_for = None
            return IconElement(
                **common,
                icon=None,
                codepoint=icons.FALLBACK_CODEPOINT,
                value_for=value_for,
                size=size,
                color=self._color_expression(node, "color"),
            )

        if has_glyph:
            return self._build_glyph_icon(node, common, size)

        codepoint = icons.resolve_codepoint(name) if name is not None else None
        if codepoint is None:
            self.bag.error(
                "icon",
                f"unknown icon {name!r}",
                self.doc.span(node, "icon"),
                notes=[
                    "the catalogue has: " + ", ".join(icons.names()),
                    "or use any single character from the vendored icon font "
                    "directly -- see wfb/assets/icons/README.md",
                ],
            )
            codepoint = icons.FALLBACK_CODEPOINT

        return IconElement(
            **common,
            icon=name,
            codepoint=codepoint,
            size=size,
            color=self._color_expression(node, "color"),
        )

    def _build_glyph_icon(self, node: dict, common: dict, size) -> Element:
        """`glyph: "U+F0BC"` -- a codepoint the catalogue does not name.

        The same escape hatch `icon:`'s bare-character form offers, spelled so
        that it survives a code review: `U+F0BC` is greppable and visible,
        where the character itself renders as a blank box (or nothing) in most
        editors and diffs.  Everything downstream -- baking, sizing, the
        per-codepoint font key -- is identical once it is a character, because
        this is exactly what a catalogue name resolves to.
        """
        raw = str(node.get("glyph"))
        span = self.doc.span(node, "glyph")
        character = icons.parse_codepoint(raw)
        if character is None:
            self.bag.error(
                "icon",
                f"glyph must be a codepoint written 'U+XXXX', not {raw!r}",
                span,
                notes=["e.g. glyph: \"U+F0BC\" -- 1 to 6 hex digits, case-insensitive",
                       "to use a name from the built-in catalogue, write 'icon:' instead"],
            )
            character = icons.FALLBACK_CODEPOINT
        elif not icons.font_has(character):
            self.bag.error(
                "icon",
                f"the icon font has no glyph at {raw.upper()}",
                span,
                notes=[
                    "checked against the vendored font's own character map, the same "
                    "way a custom text font's coverage is checked",
                    "https://www.nerdfonts.com/cheat-sheet lists the codepoints this "
                    "font actually carries",
                ],
            )
            character = icons.FALLBACK_CODEPOINT
        else:
            named = icons.name_for_codepoint(character)
            if named is not None:
                self.bag.note(
                    "icon",
                    f"glyph {raw.upper()} is in the catalogue as {named!r} -- "
                    f"'icon: {named}' says the same thing and survives a font update",
                    span,
                )
        return IconElement(
            **common,
            icon=raw.upper(),
            codepoint=character,
            size=size,
            color=self._color_expression(node, "color"),
        )

    def _build_carousel(self, node: dict, common: dict, path: tuple) -> Element:
        """`type: carousel` -- a row of readings, one of them selected.

        ADR 0006 §6 as amended: the item list is fixed by the design, the
        *selection* belongs to the wearer, and a hold moves it.  Everything an
        item needs is validated here rather than in the emitter, because the
        generated `switch` over items has no natural place to report an error
        against the author's own line.
        """
        icon_size = self._length(node, "icon_size")
        if icon_size is not None and icon_size.unit not in units.SIZE_UNITS:
            self.bag.error(
                "carousel",
                f"icon_size must be px or %r, not {icon_size.unit}",
                self.doc.span(node, "icon_size"),
                notes=["an icon's font is baked once, before layout runs, so its size "
                       "cannot depend on a parent box (%) or an element's own font (pt)"],
            )
            icon_size = None

        raw_items = node.get("items") or []
        # Three by default -- the selected item plus a neighbour either side --
        # but never more than there are items, so a two-item carousel is not an
        # error just for taking the default.
        slots = int(node.get("slots", min(3, max(1, len(raw_items)))))
        items = [self._carousel_item(raw, index, node)
                 for index, raw in enumerate(raw_items)]

        element = Carousel(
            **common,
            items=items,
            size=self._size(node.get("size")),
            pitch=self._length(node, "pitch"),
            slots=slots,
            icon_size=icon_size,
            color=self._color_expression(node, "color"),
            inactive_color=self._color_expression(node, "inactive_color"),
            value_color=self._color_expression(node, "value_color"),
            value_offset=(self._position(node.get("value_offset"), node, "value_offset")
                          if "value_offset" in node else None),
            animate=float(node.get("animate", 0.3)),
            persist=bool(node.get("persist", True)),
        )
        self._resolve_carousel_font(node, element)

        if len(items) < 2:
            self.bag.error(
                "carousel",
                f"{element.id}: a carousel needs at least two items, got {len(items)}",
                self.doc.span(node, "items"),
                notes=["with one item there is nothing to rotate to -- use an 'icon' "
                       "plus a 'text' element instead, which costs less"],
            )
        if slots > len(items):
            # Drawing more slots than there are items would show the same item
            # twice in one row, which reads as a rendering bug rather than a
            # short list.
            self.bag.error(
                "carousel",
                f"{element.id}: slots ({slots}) exceeds the number of items ({len(items)})",
                self.doc.span(node, "slots"),
                notes=[f"with {len(items)} items, at most {len(items)} slots can show "
                       "distinct readings; a wider row would repeat one"],
            )
        for key, bound in (("color", element.color),
                           ("inactive_color", element.inactive_color),
                           ("value_color", element.value_color)):
            if bound is not None and bound.nullable:
                self.bag.error(
                    "carousel",
                    f"{element.id}: {key!r} reads {bound.text!r}, which can be absent",
                    self.doc.span(node, key),
                    notes=["a carousel colour has no 'when_absent:' of its own -- an "
                           "item's policy governs that item's reading, not the whole "
                           "row's appearance",
                           "guard it in the expression instead, e.g. "
                           "\"x != null and x > 100 ? palette.hot : palette.fg\""],
                )
        return element

    def _carousel_item(self, raw: dict, index: int, parent: dict) -> CarouselItem:
        span = self.doc.span(raw)
        chosen = [k for k in ("icon", "glyph") if k in raw]
        if len(chosen) > 1:
            self.bag.error(
                "carousel",
                f"item {index}: 'icon' and 'glyph' are mutually exclusive",
                span,
            )
        codepoint = icons.FALLBACK_CODEPOINT
        label: str | None = None
        if "glyph" in raw:
            label = str(raw["glyph"]).upper()
            parsed = icons.parse_codepoint(str(raw["glyph"]))
            if parsed is None or not icons.font_has(parsed):
                self.bag.error(
                    "carousel",
                    f"item {index}: no glyph at {label}",
                    self.doc.span(raw, "glyph"),
                    notes=["write it 'U+XXXX'; checked against the vendored font's own "
                           "character map"],
                )
            else:
                codepoint = parsed
        elif "icon" in raw:
            label = str(raw["icon"])
            resolved = icons.resolve_codepoint(label)
            if resolved is None:
                self.bag.error(
                    "carousel",
                    f"item {index}: unknown icon {label!r}",
                    self.doc.span(raw, "icon"),
                    notes=["run `wfb sources` for the catalogue, or use 'glyph: \"U+XXXX\"'"],
                )
            else:
                codepoint = resolved

        value = self._expression(raw, "value") if "value" in raw else None
        if label is None and value is not None and value.sources:
            # No icon named: fall back to the conventional one for the source
            # (`wfb.icons.icon_for_source`), which is the whole reason that
            # table exists.  A carousel row is exactly the place an author
            # should not have to name nine icons by hand.
            suggested = icons.METRIC_ICON.get(value.sources[0])
            if suggested is not None:
                label = suggested
                codepoint = icons.resolve_codepoint(suggested) or codepoint
        if label is None:
            self.bag.error(
                "carousel",
                f"item {index}: needs an 'icon:' or 'glyph:'",
                span,
                notes=["the icon is only inferred from 'value:' when the catalogue has "
                       "a conventional one for that source"],
            )

        launch = raw.get("launch")
        if launch is not None:
            launch = str(launch)
            # `auto` is resolved later, once `value` (just above) is a real
            # Expression -- see `Builder._resolve_hold_auto` -- not checked
            # against the complication table here.
            if launch != HOLD_AUTO and complications.get(launch) is None:
                near = complications.suggest(launch)
                self.bag.error(
                    "carousel",
                    f"item {index}: unknown launch target {launch!r}",
                    self.doc.span(raw, "launch"),
                    notes=(["did you mean: " + ", ".join(near) + "?"] if near else [])
                    + [f"run `wfb complications` for the full list of "
                       f"{len(complications.TYPES)} launch targets"],
                )
                launch = None

        item = CarouselItem(
            codepoint=codepoint,
            icon=label,
            value=value,
            format=raw.get("format"),
            when_absent=raw.get("when_absent"),
            placeholder=raw.get("placeholder"),
            fallback=self._expression(raw, "fallback") if "fallback" in raw else None,
            launch=launch,
            span=span,
        )
        if value is not None:
            self._check_item_absence(raw, index, item, value)
            self._check_format(raw, value, item.format)
        return item

    def _check_item_absence(self, raw: dict, index: int, item: CarouselItem,
                            bound: Expression) -> None:
        """ADR 0005 §3, scoped to one carousel item.

        Deliberately not :meth:`_check_absence`: that one reasons about *the
        element's* other bindings ("this policy still does work because the
        colour is nullable too"), which is the wrong scope here.  An item's
        policy governs an item's reading and nothing else -- a carousel colour
        is rejected outright if it is nullable, precisely so this stays a
        per-item question.
        """
        if not bound.nullable:
            if item.when_absent is not None:
                self.bag.note(
                    "when-absent",
                    f"item {index}: 'when_absent' has no effect -- "
                    f"{bound.text} is never absent",
                    self.doc.span(raw, "when_absent"),
                )
            return
        if item.when_absent is None:
            self.bag.error(
                "when-absent",
                f"item {index}: {bound.text!r} can be absent, so 'when_absent:' is required",
                self.doc.span(raw, "value"),
                notes=[
                    "every ActivityMonitor field is nullable and sensors are simply "
                    "missing on some devices, so absence is the normal case",
                    "on a carousel item, 'hide' leaves the slot's icon drawn and its "
                    "reading blank -- the row does not collapse",
                    "choose one of: hide | placeholder (with 'placeholder:') | fallback "
                    "(with 'fallback:')",
                ],
            )
            return
        if item.when_absent == "placeholder" and item.placeholder is None:
            self._require(raw, "placeholder",
                          "when_absent: placeholder needs a 'placeholder:' string")
        if item.when_absent == "fallback" and item.fallback is None:
            self._require(raw, "fallback",
                          "when_absent: fallback needs a 'fallback:' expression")
        if item.when_absent == "fallback" and item.fallback is not None \
                and item.fallback.nullable:
            self.bag.error(
                "when-absent",
                f"item {index}: the fallback expression can itself be absent",
                self.doc.span(raw, "fallback"),
                notes=["a fallback must always produce a value"],
            )

    def _resolve_carousel_font(self, node: dict, element: Carousel) -> None:
        """`value_font:` -- literally the same resolution `text`'s `font:` uses."""
        raw = node.get("value_font")
        if raw is None:
            return
        resolved = self._font_reference(str(raw), self.doc.span(node, "value_font"))
        if resolved is not None:
            element.value_font, element.value_font_is_custom = resolved

    # -- shared checks ----------------------------------------------------

    def _check_absence(self, node: dict, element: Element, bound: Expression,
                       when_absent: str | None, placeholder: str | None,
                       fallback: Expression | None, key: str = "value") -> None:
        """ADR 0005 3: null handling is part of the binding, not an afterthought."""
        if not bound.nullable:
            # Only "no effect" if nothing *else* on the element is nullable
            # either: since `_check_other_absence`, a nullable colour or max
            # requires a policy too, so a `when_absent:` sitting next to a
            # non-nullable value can be doing real work.  Saying it has no
            # effect there would contradict the error the author just fixed.
            others_nullable = any(
                e is not bound and e is not element.visible and e.nullable
                for e in element.expressions()
            )
            if when_absent is not None and not others_nullable:
                self.bag.note(
                    "when-absent",
                    f"{element.id}: 'when_absent' has no effect -- {bound.text} is never absent",
                    self.doc.span(node, "when_absent"),
                )
            return
        if when_absent is None:
            self.bag.error(
                "when-absent",
                f"{element.id}: {bound.text!r} can be absent, so 'when_absent:' is required",
                self.doc.span(node, key),
                notes=[
                    "every ActivityMonitor field is nullable and sensors are simply missing on "
                    "some devices, so absence is the normal case, not an error",
                    "choose one of: hide | placeholder (with 'placeholder:') | fallback "
                    "(with 'fallback:')",
                ],
            )
            return
        if when_absent == "placeholder" and placeholder is None:
            self._require(node, "placeholder", "when_absent: placeholder needs a 'placeholder:' string")
        if when_absent == "fallback" and fallback is None:
            self._require(node, "fallback", "when_absent: fallback needs a 'fallback:' expression")
        if when_absent == "fallback" and fallback is not None and fallback.nullable:
            self.bag.error(
                "when-absent",
                f"{element.id}: the fallback expression can itself be absent",
                self.doc.span(node, "fallback"),
                notes=["a fallback must always produce a value"],
            )

    def _check_other_absence(self, node: dict, element: Element, key: str,
                             bound: Expression | None) -> None:
        """A nullable binding outside `value` still needs an explicit `when_absent:`.

        `_check_absence` above only ever ran for `value` -- a nullable
        `color`/`track_color` sailed through validation with no policy at
        all, and codegen (`wfb.emit.monkeyc`'s `ReadPlan.other_guards`)
        always treats an absent non-value binding as 'hide', regardless of
        which policy is chosen for the value, because there is no sensible
        placeholder or fallback for a colour. The requirement here is only
        that the author has consciously picked *something*, the same ADR
        0005 3 contract `value` already has -- not that the chosen policy's
        exact semantics (placeholder text, a substitute number) apply to a
        colour, which they do not.
        """
        if bound is None or not bound.nullable:
            return
        if getattr(element, "when_absent", None) is not None:
            return
        self.bag.error(
            "when-absent",
            f"{element.id}: {key!r} reads {bound.text!r}, which can be absent, so "
            "'when_absent:' is required",
            self.doc.span(node, key),
            notes=[
                "every ActivityMonitor field is nullable and sensors are simply missing on "
                "some devices, so absence is the normal case, not an error",
                f"'when_absent:' is required once anything on this element is nullable, not "
                f"just 'value' -- a nullable {key} always hides the element when absent, "
                "regardless of which policy is chosen for the bound value",
                "choose one of: hide | placeholder (with 'placeholder:') | fallback "
                "(with 'fallback:')",
            ],
        )

    def _check_reachable_substitute(self, node: dict, element: Element, key: str,
                                    value_bindings: tuple[Expression | None, ...],
                                    other_bindings: tuple[Expression | None, ...]) -> None:
        """Warn when a `placeholder:`/`fallback:` can never actually be drawn.

        A nullable non-value binding hides the whole element (see
        `_check_other_absence`), and that guard runs *before* the value's own
        substitute.  So if every nullable source behind the value is also read
        by a colour or max, the element is already gone by the time the
        substitute would be chosen, and the author's `placeholder:` is dead
        text -- declared, accepted, and impossible to see.

        Not an error: the design still behaves sensibly (it hides), and the
        fix is a judgement call -- drop the substitute, or stop reading the
        same source from the colour.  But saying nothing here would be the
        very failure this compiler exists to prevent, one level down.

        `visible:` joins the "other" bindings here for exactly the same
        reason, and with a stronger claim behind it: absence in a visibility
        condition means hidden by definition, and that guard is emitted before
        everything else in the method.  A placeholder for a reading the
        element's own visibility already depends on is unreachable text.  The
        label only grows when the element actually has a `visible:`, so no
        existing message moves.
        """
        policy = getattr(element, "when_absent", None)
        if policy not in ("placeholder", "fallback"):
            return
        value_sources = self._nullable_sources(value_bindings)
        if not value_sources:
            return
        if element.visible is not None:
            other_bindings = other_bindings + (element.visible,)
            key = f"{key}/'visible'"
        other_sources = self._nullable_sources(other_bindings)
        if not value_sources <= other_sources:
            return
        shared = ", ".join(sorted(value_sources))
        self.bag.warning(
            "when-absent",
            f"{element.id}: the {policy} can never be drawn -- {shared} is also read by "
            f"{key}, which hides the element whenever it is absent",
            self.doc.span(node, policy if policy == "fallback" else "placeholder")
            or self.doc.span(node, key),
            notes=[
                f"a nullable {key} always hides the element, and that guard runs before "
                f"the value's own {policy}",
                f"either drop the {policy}, or stop reading {shared} from {key} so the "
                "element can still draw when the reading is missing",
            ],
            confidence="exact -- the same guard order codegen emits",
        )

    @staticmethod
    def _nullable_sources(bindings: tuple[Expression | None, ...]) -> set[str]:
        """Catalogue paths among `bindings` that the generated code null-checks."""
        out: set[str] = set()
        for bound in bindings:
            if bound is None:
                continue
            for path in bound.sources:
                source = catalog.get(path)
                if source is not None and source.guard_needed:
                    out.add(path)
        return out

    def _check_fallback_fraction(self, node: dict, element: Progress) -> None:
        """A `progress` fallback is a **fill fraction**, so it must be 0.0-1.0.

        This is the one place `fallback:` means something other than "the
        value" -- for a progress, either the value or the max can be the
        absent reading, so the outcome is the only well-defined substitute
        (see `wfb/emit/monkeyc.py`'s `_fallback_fraction`).  That makes an
        out-of-range constant a plausible mistake -- writing the *step count*
        you wanted rather than the fraction -- and it is the one path not
        already clamped by `WfbMath.percent`, so a bar could be drawn wider
        than its own box.  Only a build-time constant is checked here; a
        computed fallback is clamped on device instead.
        """
        fallback = element.fallback
        if element.when_absent != "fallback" or fallback is None or not fallback.is_constant:
            return
        try:
            value = float(fallback.constant)
        except (TypeError, ValueError):
            return
        if 0.0 <= value <= 1.0:
            return
        self.bag.error(
            "when-absent",
            f"{element.id}: a progress fallback is a fill fraction, so it must be "
            f"between 0.0 and 1.0 -- got {fallback.text}",
            self.doc.span(node, "fallback"),
            notes=[
                "unlike a text fallback, which supplies the value and is then "
                "formatted, a progress fallback supplies the filled proportion "
                "directly: either the value or the max can be the absent reading, "
                "so the outcome is the only well-defined thing to substitute",
                "for 'half full' write 0.5, not the reading you would have shown",
            ],
        )

    def _check_format(self, node: dict, bound: Expression, spec: str | None) -> None:
        span = self.doc.span(node, "format")
        if spec is None:
            if bound.value.type.is_formatted():
                example = "{:%a %e %b}" if bound.value.type is Type.DATE else "{:%H:%M}"
                self.bag.error(
                    "format",
                    f"a {bound.value.type.value} value needs a 'format:', e.g. '{example}'",
                    self.doc.span(node, "value"),
                )
            return
        from . import formatting

        coded = formatting.is_time_spec(spec)
        if coded and not bound.value.type.is_formatted():
            self.bag.error(
                "format",
                f"strftime-style format {spec!r} needs a time or date value, got {bound.value}",
                span,
            )
        elif not coded and bound.value.type.is_formatted():
            example = "{:%a %e %b}" if bound.value.type is Type.DATE else "{:%H:%M}"
            self.bag.error(
                "format",
                f"a {bound.value.type.value} value needs a strftime-style format "
                f"such as '{example}'",
                span,
            )
        elif coded:
            # Catch a date spec on a clock value and the reverse: both parse, and
            # the wrong one silently renders nonsense (%M is minute, not month).
            codes = formatting.DATE_CODES if bound.value.type is Type.DATE else formatting.TIME_CODES
            try:
                formatting.parse_time(formatting._strip_braces(spec), codes)
            except formatting.FormatError as exc:
                self.bag.error("format", str(exc), span)

    def _require(self, node: dict, key: str, message: str) -> None:
        self.bag.error("element", message, self.doc.span(node, key) or self.doc.span(node))

    # -- coercion helpers -------------------------------------------------

    def _expression(self, node: dict, key: str) -> Expression | None:
        raw = node.get(key)
        if raw is None:
            return None
        span = self.doc.span(node, key)
        text = str(raw)
        before = set(self.scope.used)
        self.scope.used.clear()
        try:
            node_ast = expr.parse(text)
            value = expr.check(node_ast, self.scope)
            # Emit from a fold that keeps palette names; derive the build-time
            # constant, which the linter needs, from a fold that resolves them.
            folded = expr.fold(node_ast, self.scope, fold_colors=False)
            code = expr.emit(folded, self.scope)
            resolved = expr.fold(node_ast, self.scope)
        except expr.ExprError as exc:
            self.bag.error(
                exc.code or "expression",
                f"{key}: {exc.message}",
                _offset_span(span, text, exc.offset),
                notes=exc.notes,
            )
            self.scope.used |= before
            return None
        used = [p for p in self.scope.used if p in catalog.CATALOG]
        self.scope.used |= before
        barrel = {c.name for c in expr.walk(folded)
                  if isinstance(c, expr.Call) and c.name in expr.CALL_BARREL}
        modules = {expr.CALL_MODULES[c.name] for c in expr.walk(folded)
                   if isinstance(c, expr.Call) and c.name in expr.CALL_MODULES}
        constant = resolved.value if isinstance(resolved, expr.Literal) else None
        return Expression(
            text=text, code=code, value=value, sources=tuple(sorted(used)),
            barrel=frozenset(barrel), modules=frozenset(modules), span=span, constant=constant,
            ast=folded,
        )

    def _color_expression(self, node: dict, key: str) -> Expression | None:
        raw = node.get(key)
        if raw is None:
            return None
        span = self.doc.span(node, key)
        text = str(raw)
        # A bare hex literal is not expression syntax; accept it and say so.
        if text.startswith("#"):
            try:
                color = Color.parse(text, what=key)
            except ColorError as exc:
                self.bag.error("color", str(exc), span)
                return None
            self.bag.note(
                "raw-color",
                f"{key}: {text} is a literal colour -- prefer a named palette entry",
                span,
                notes=["palette entries keep a design's colours consistent and lintable"],
            )
            return Expression(text, color.as_monkeyc(), expr.Value(Type.COLOR), (),
                              frozenset(), frozenset(), span, constant=color.value,
                              ast=expr.Literal(color.value, Type.COLOR))
        bound = self._expression(node, key)
        if bound is not None and bound.value.type is not Type.COLOR:
            self.bag.error(
                "type", f"{key} must be a colour, got {bound.value}", span,
                notes=["known palette entries: " + (", ".join(f"palette.{n}" for n in sorted(self.palette)) or "(none)")],
            )
            return None
        return bound

    def _font_reference(self, name: str, span: Span | None) -> tuple[str, bool] | None:
        """Resolve a `font:`/`value_font:` name to ``(reference, is_custom)``.

        Shared by `text`'s `font:` and `carousel`'s `value_font:`, which had
        the same fifteen lines twice and so could disagree about what a font
        name means.

        Returns ``None`` when the name does not resolve.  The one subtlety is
        what happens for a font that *was* declared and then rejected by
        `_build_fonts` (a missing `source:`, a bad `size:`, `align:` without
        `monospace:`): the build is already failing, with an error pointing at
        the real mistake in the `fonts:` block, so this stays quiet rather than
        adding one more error per element blaming the element for it.  The old
        behaviour was worse than noisy -- it reported `declared fonts: (none
        declared)` from a file that declared several, because a rejected entry
        never reached `self.fonts`.
        """
        if not name.startswith("font."):
            if name in SYSTEM_FONTS:
                return name, False
            self.bag.error(
                "font", f"unknown font {name!r}", span,
                notes=["use 'font.<name>' for a custom font, or a system font: "
                       + ", ".join(SYSTEM_FONTS)],
            )
            return None
        key = name[len("font."):]
        if key in self.fonts:
            return key, True
        if key in self.rejected_fonts:
            return None
        known = ", ".join(f"font.{n}" for n in sorted(self.declared_fonts)) or "(none declared)"
        self.bag.error("font", f"unknown font {name!r}", span,
                       notes=[f"declared fonts: {known}"])
        return None

    def _resolve_font(self, node: dict, element: Text) -> None:
        raw = node.get("font")
        if raw is None:
            return
        resolved = self._font_reference(str(raw), self.doc.span(node, "font"))
        if resolved is not None:
            element.font, element.font_is_custom = resolved

    def _position(self, raw: dict | None, node: dict, key: str) -> Position:
        if raw is None:
            return Position()
        span = self.doc.span(node, key)
        try:
            return Position(
                anchor=raw.get("anchor", "center"),
                dx=Length.parse(raw["dx"], what="dx") if "dx" in raw else None,
                dy=Length.parse(raw["dy"], what="dy") if "dy" in raw else None,
                angle=Angle.parse(raw["angle"], what="angle") if "angle" in raw else None,
                radius=Length.parse(raw["radius"], what="radius") if "radius" in raw else None,
            )
        except UnitError as exc:
            self.bag.error("units", str(exc), span)
            return Position()

    def _size(self, raw: dict | None) -> Size:
        if raw is None:
            return Size()
        try:
            return Size(
                width=Length.parse(raw["width"], what="width") if "width" in raw else None,
                height=Length.parse(raw["height"], what="height") if "height" in raw else None,
            )
        except UnitError as exc:
            self.bag.error("units", str(exc), self.doc.span(raw))
            return Size()

    def _length(self, node: dict, key: str) -> Length | None:
        if key not in node:
            return None
        try:
            return Length.parse(node[key], what=key)
        except UnitError as exc:
            self.bag.error("units", str(exc), self.doc.span(node, key))
            return None

    def _angle(self, node: dict, key: str) -> Angle | None:
        if key not in node:
            return None
        try:
            return Angle.parse(node[key], what=key)
        except UnitError as exc:
            self.bag.error("units", str(exc), self.doc.span(node, key))
            return None


def _and_paths(paths: tuple[str, ...]) -> str:
    """``'a'``, ``'a' and 'b'``, ``'a', 'b' and 'c'`` -- for a diagnostic."""
    quoted = [repr(path) for path in paths]
    if len(quoted) == 1:
        return quoted[0]
    return ", ".join(quoted[:-1]) + " and " + quoted[-1]


def walk_elements(elements: list[Element]) -> list[Element]:
    """Flatten a tree of elements, parents before children, in document order."""
    out: list[Element] = []

    def visit(items: list[Element]) -> None:
        for item in items:
            out.append(item)
            visit(item.children())

    visit(elements)
    return out


def draw_order(elements: list[Element]) -> list[Element]:
    """The flattened, ``z``-sorted list of elements that actually paint.

    Shared by :meth:`Face.draw_order` and :meth:`Builder._apply_static`, which
    runs before there is a :class:`Face` to ask.
    """
    drawn = [e for e in walk_elements(elements) if e.kind != "group"]
    return sorted(drawn, key=lambda e: (e.z if e.z is not None else 0,))


def build(doc: YamlDocument, bag: Bag) -> Face | None:
    return Builder(doc, bag).build()


# --------------------------------------------------------------------------
# helpers


def local_name(source_path: str) -> str:
    """The generated local variable holding one source's value.

    ``activity.step_goal`` -> ``activityStepGoal``.  Stable and derived, so the
    generated code reads the same way the YAML does.
    """
    parts = source_path.replace(".", "_").split("_")
    return parts[0] + "".join(p.capitalize() for p in parts[1:])


def element_const_prefix(element_id: str) -> str:
    """The layout-constant prefix codegen derives from an element id.

    ``temp_low`` and ``tempLow`` both become ``TEMP_LOW``: separators are
    folded to ``_`` and a case boundary is treated as an implicit one, so
    that a design read either camelCase or snake_case still produces the
    Monkey C convention (`SCREAMING_SNAKE_CASE` constants).  That folding is
    exactly why two distinct ids can collide -- see
    :meth:`Builder._check_symbol_collision`, the one place this is checked.
    """
    out = []
    for index, char in enumerate(element_id):
        if char.isupper() and index and not element_id[index - 1].isupper():
            out.append("_")
        out.append(char.upper() if char.isalnum() else "_")
    return "".join(out)


def element_method_name(element_id: str) -> str:
    """The private draw method codegen derives from an element id (``drawTempLow``)."""
    return "draw" + _element_suffix(element_id)


def static_group_method(element_id: str) -> str:
    """The method that paints one static subtree (``drawStaticTicks``).

    A root already called ``static`` -- which is the id the top-level
    ``static:`` block is desugared under -- gives ``drawStatic``, not
    ``drawStaticStatic``: the prefix says what the method *is*, and repeating a
    word the id already carries is not something a person would write
    (ADR 0003).  Only a `group` root gets one of these; a static leaf is drawn
    by its own `draw<Id>` straight from `renderStatic`, because a wrapper around
    a single call is noise.

    Derived here rather than in the emitter for the same reason every other
    generated symbol is: :meth:`Builder._check_symbol_collision` has to see, in
    one place, every symbol an id can produce.
    """
    suffix = _element_suffix(element_id)
    return "drawStatic" if suffix == "Static" else "drawStatic" + suffix


def carousel_step_method(element_id: str) -> str:
    """The public method the delegate calls to move a carousel (``stepTempLow``).

    Public, unlike every draw method, because it is called from the delegate.
    Derived here rather than in the emitter for the same reason the others are:
    :meth:`Builder._check_symbol_collision` has to be able to see every symbol
    an id produces, in one place.
    """
    return "step" + _element_suffix(element_id)


def carousel_index_field(element_id: str) -> str:
    """The view field holding a carousel's selected index (``tempLowIndex``)."""
    return _lower_first(_element_suffix(element_id)) + "Index"


def carousel_slide_field(element_id: str) -> str:
    """The view field holding a carousel's slide offset (``tempLowSlide``).

    Public on the view, which is not a style choice: ``WatchUi.animate`` takes
    a ``Symbol`` and looks the property up indirectly, and a ``private`` member
    is not found that way -- monkeyc warns about exactly this, verified on a
    real build (`docs/research/07-carousel-interaction.md` §5).
    """
    return _lower_first(_element_suffix(element_id)) + "Slide"


def carousel_slide_done_method(element_id: str) -> str:
    """The animation-complete callback for a carousel (``onTempLowSlideDone``)."""
    return "on" + _element_suffix(element_id) + "SlideDone"


def _element_suffix(element_id: str) -> str:
    parts = [p for p in element_id.replace("-", "_").split("_") if p]
    return "".join(p[:1].upper() + p[1:] for p in parts)


def _lower_first(text: str) -> str:
    return text[:1].lower() + text[1:]


def _pascal(text: str) -> str:
    cleaned = "".join(c if c.isalnum() else " " for c in text)
    return "".join(word[:1].upper() + word[1:] for word in cleaned.split())


def font_resource_id(name: str) -> str:
    """The Monkey C resource id a font named ``name`` is emitted under.

    Shared between author-declared custom fonts (:class:`FontSpec`) and the
    synthetic per-size icon fonts (:mod:`wfb.icons`), so both are addressed the
    same way in generated code without either needing to know the other exists.
    """
    return f"Font{_pascal(name)}"


def _offset_span(span: Span | None, text: str, offset: int) -> Span | None:
    """Shift a span to point inside the expression string, not just at its key."""
    if span is None:
        return None
    return Span(span.path, span.line, span.col + offset)
