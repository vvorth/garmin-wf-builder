"""The intermediate representation, and the semantic pass that produces it.

Stage 2 of validation (ADR 0008): everything that is device-independent.  Data
sources are resolved against the catalogue, expressions are type-checked and
compiled, null handling is required where the platform makes absence normal, and
refresh tiers are enforced against the mode an element draws in.

Nothing here knows a screen size.  Per-device work happens in :mod:`wfb.layout`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from . import catalog, complications, expr, icons
from .catalog import Source, Tier, Type
from .diagnostics import Bag, Span
from .palette import Color, ColorError
from .units import Angle, Length, UnitError
from .yamlsrc import YamlDocument

MODES = ("active", "low_power", "always_on")

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
    size: float
    glyphs: str | None
    antialias: bool
    scale: bool
    span: Span | None

    @property
    def resource_id(self) -> str:
        return font_resource_id(self.name)


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
    #: A `wfb.complications` name this element launches when tapped (ADR 0006
    #: §6).  The platform offers exactly one door out of a watch face --
    #: `Complications.exitTo` -- so an interactive element names a complication
    #: type and the watch opens whatever glance owns it.
    on_tap: str | None = None

    @property
    def symbol(self) -> str:
        """The stable Monkey C symbol derived from the element id (ADR 0003)."""
        return _pascal(self.id)

    def children(self) -> list["Element"]:
        return []

    def expressions(self) -> list[Expression]:
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
    thickness: Length | None = None
    color: Expression | None = None
    filled: bool = True

    def expressions(self) -> list[Expression]:
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

    def expressions(self) -> list[Expression]:
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

    def expressions(self) -> list[Expression]:
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

    def expressions(self) -> list[Expression]:
        return [e for e in (self.color, self.value_for) if e]


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
        out: list[Element] = []

        def visit(items: list[Element]) -> None:
            for item in items:
                out.append(item)
                visit(item.children())

        visit(self.elements)
        return out

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
            source = base / str(spec["source"])
            if not source.exists():
                self.bag.error(
                    "font",
                    f"font {name!r}: source file not found: {spec['source']}",
                    self.doc.span(spec, "source"),
                    notes=[f"resolved against the design file, to {source}"],
                )
                continue
            self.fonts[name] = FontSpec(
                name=name,
                source=source,
                size=float(spec["size"]),
                glyphs=spec.get("glyphs"),
                antialias=bool(spec.get("antialias", False)),
                scale=bool(spec.get("scale", True)),
                span=span,
            )

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
            on_tap=self._tap_target(node),
        )

        builders = {
            "group": self._build_group,
            "shape": self._build_shape,
            "text": self._build_text,
            "progress": self._build_progress,
            "icon": self._build_icon,
        }
        builder = builders.get(node["type"])
        if builder is None:  # unreachable once the schema has run
            self.bag.error("element", f"unsupported element type {node['type']!r}", span)
            return None
        element = builder(node, common, path)
        if element is not None:
            self._check_tiers(element)
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
        candidates = (element_const_prefix(element_id), element_method_name(element_id))
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

    def _tap_target(self, node: dict) -> str | None:
        """Validate `on_tap:` against the launchable complication table.

        A watch face cannot open an arbitrary app; `Complications.exitTo` is
        the only exit the platform offers, so the value here names a
        complication *type* and the watch opens whatever owns it.  Checked
        against :mod:`wfb.complications`, which is generated from the SDK's own
        `COMPLICATION_TYPE_*` table -- an invented name would compile to an
        undefined symbol, so catching it here points at the author's line
        instead of a generated one.
        """
        raw = node.get("on_tap")
        if raw is None:
            return None
        name = str(raw)
        if complications.get(name) is not None:
            return name
        near = complications.suggest(name)
        notes = []
        if near:
            notes.append("did you mean: " + ", ".join(near) + "?")
        notes.append("run `wfb complications` for the full list of "
                     f"{len(complications.LAUNCHABLE)} launch targets")
        self.bag.error(
            "on-tap",
            f"unknown tap target {name!r}",
            self.doc.span(node, "on_tap"),
            notes=notes,
        )
        return None

    def _build_group(self, node: dict, common: dict, path: tuple) -> Element:
        return Group(
            **common,
            size=self._size(node.get("size")),
            items=self._build_elements(node["children"], path + ("children",)),
        )

    def _build_shape(self, node: dict, common: dict, path: tuple) -> Element:
        shape = node["shape"]
        element = Shape(
            **common,
            shape=shape,
            size=self._size(node.get("size")),
            radius=self._length(node, "radius"),
            corner_radius=self._length(node, "corner_radius"),
            to=self._position(node.get("to"), node, "to") if "to" in node else None,
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
        return element

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
        if size is not None and size.unit not in icons.SIZE_UNITS:
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
                e is not bound and e.nullable for e in element.expressions()
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
        """
        policy = getattr(element, "when_absent", None)
        if policy not in ("placeholder", "fallback"):
            return
        value_sources = self._nullable_sources(value_bindings)
        if not value_sources:
            return
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

    def _check_tiers(self, element: Element) -> None:
        """ADR 0005 5 / lint check 12: low-power draws may read only frame-tier sources.

        ``onPartialUpdate`` runs under a budget whose overrun permanently
        disables partial updates for the rest of the app lifecycle, so this is
        an error rather than a warning, and it is not suppressible.
        """
        if "low_power" not in element.modes and "always_on" not in element.modes:
            return
        for expression in element.expressions():
            for path in expression.sources:
                source = catalog.get(path)
                if source and source.tier is not Tier.FRAME:
                    self.bag.error(
                        "refresh-tier",
                        f"{element.id}: {path!r} is a '{source.tier.value}'-tier source and "
                        f"cannot be read in low-power mode",
                        expression.span or element.span,
                        notes=[
                            "onPartialUpdate runs under a strict budget, and exceeding it calls "
                            "onPowerBudgetExceeded and disables partial updates permanently",
                            "read it in 'active' mode, or bind a frame-tier source instead",
                        ],
                    )

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
                "expression",
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

    def _resolve_font(self, node: dict, element: Text) -> None:
        raw = node.get("font")
        if raw is None:
            return
        span = self.doc.span(node, "font")
        name = str(raw)
        if name.startswith("font."):
            key = name[len("font."):]
            if key not in self.fonts:
                known = ", ".join(f"font.{n}" for n in sorted(self.fonts)) or "(none declared)"
                self.bag.error("font", f"unknown font {name!r}", span,
                               notes=[f"declared fonts: {known}"])
                return
            element.font, element.font_is_custom = key, True
            return
        if name not in SYSTEM_FONTS:
            self.bag.error(
                "font", f"unknown font {name!r}", span,
                notes=["use 'font.<name>' for a custom font, or a system font: "
                       + ", ".join(SYSTEM_FONTS)],
            )
            return
        element.font, element.font_is_custom = name, False

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
    parts = [p for p in element_id.replace("-", "_").split("_") if p]
    return "draw" + "".join(p[:1].upper() + p[1:] for p in parts)


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
