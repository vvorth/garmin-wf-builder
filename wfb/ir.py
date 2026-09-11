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

import re
from dataclasses import dataclass, field
from pathlib import Path

from . import catalog, complications, expr, icons, series, units
from .catalog import Source, Type
from .diagnostics import Bag, Span
from .palette import Color, ColorError
from .series import Acquisition, SeriesDef
from .units import Angle, Duration, Length, UnitError
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

#: Which geometry key each `graph` `style:` actually reads -- the same
#: precedent as `SHAPE_GEOMETRY_KEYS`, and for the same reason: a `bar_width:`
#: on a `style: line` graph was parsed, validated and silently dropped on the
#: floor until this table existed to catch it.
GRAPH_STYLE_KEYS = {
    "line": frozenset({"thickness"}),
    "area": frozenset(),
    "bars": frozenset({"bar_width"}),
}
_ALL_GRAPH_STYLE_KEYS = frozenset().union(*GRAPH_STYLE_KEYS.values())

#: `Dc.fillPolygon`'s own 64-point limit, already recorded for `shape:
#: polygon` -- a filled graph closes its outline with two extra corners, so
#: the usable sample count is 62, not 64 (`docs/research/probes/graph-series/`).
GRAPH_AREA_MAX_SAMPLES = 62


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
# on-device configuration (ADR 0006 1, amended)


#: The runtime symbol that gates the whole feature -- a device without it
#: (fr955) still compiles every line below; it just never calls it.  Checked
#: with `Device.has_symbol`, never an API-level compare: fr955 reports 5.2.0,
#: above the editor's documented 5.1.0, and still has no editor at all
#: (CLAUDE.md constraint 6, and `docs/research/probes/watchface-config/`).
CONFIG_SYMBOL = "Toybox.Application.WatchFaceConfig.getSettings"

#: Matches `expr.check`'s own "unknown data source" message for exactly
#: `config.colors` or `config.colors.<role>` -- the only two shapes anything
#: under `config.colors.*` can ever fail to resolve as (see `_build_scope`,
#: which binds nothing else there).  Group 1 is `""` for the bare axis, or
#: `.<role>` for a bad role -- `Builder._expression` tells the two apart to
#: give a domain-specific error instead of a generic "did you mean" guess.
_CONFIG_COLORS_RE = re.compile(
    r"^unknown data source 'config\.colors((?:\.[A-Za-z_][A-Za-z0-9_]*)?)'$"
)


@dataclass(frozen=True)
class ConfigChoice:
    """One entry in an explicit `choices:` list."""

    color: Color
    label: str | None = None


@dataclass(frozen=True)
class ConfigAxis:
    """What Garmin's own editor calls one colour axis, and how it reads back.

    Garmin gives exactly two colour axes and no way to add a third -- the
    Styles and Data axes are a different shape of thing (ADR 0006 1's
    amendment) -- so this is a fixed table of two, not something a design
    extends.
    """

    #: The `config:` key an author writes (`accent_color`/`data_color`).
    key: str
    #: The `<watchface-config>` child element this axis becomes.
    resource_tag: str
    #: The `WatchFaceConfig.Settings` field this axis reads back as.
    settings_field: str


#: Keyed by the author-facing name; also the iteration order both the
#: generated resource and the generated `applyConfig` follow, so the two
#: cannot list the two axes in different orders.
CONFIG_AXES: dict[str, ConfigAxis] = {
    "accent_color": ConfigAxis("accent_color", "accentColors", "accentColor"),
    "data_color": ConfigAxis("data_color", "dataColors", "complicationColor"),
}


@dataclass(frozen=True)
class ConfigColor:
    """One declared `config:` entry -- `accent_color` or `data_color`."""

    name: str
    default: Color
    #: `"any"`, or the explicit picklist the editor offers.
    choices: "str | tuple[ConfigChoice, ...]"
    span: Span | None = None

    @property
    def allow_any(self) -> bool:
        return self.choices == "any"

    @property
    def axis(self) -> ConfigAxis:
        return CONFIG_AXES[self.name]

    @property
    def field(self) -> str:
        """The generated view field this axis is cached in (`_configAccentColor`)."""
        return config_field(self.name)


@dataclass(frozen=True)
class ColorScheme:
    """One declared `color_scheme:` entry -- a named role -> colour set,
    picked on-device through `config: colors:` (docs/research/09 §3).

    A colour *scheme* is several colours moving together, and no native
    colour axis carries more than one colour, so a scheme rides **Styles** --
    the one axis Garmin gives no meaning to at all.  `colors` keeps the
    author's own declared order (a plain dict), which is cosmetic only: the
    generated `resolveColorScheme` assigns one field per role regardless of
    order.
    """

    name: str
    label: str | None
    #: role name -> colour, in declared order.  Every accepted scheme in one
    #: design shares an identical key set -- `Builder._build_color_scheme`
    #: rejects any that does not, before this is ever constructed for it.
    colors: dict[str, Color]
    span: Span | None = None


@dataclass(frozen=True)
class ConfigColorAxis:
    """The `config: colors:` axis -- a Styles-axis picker over declared
    `color_scheme:` entries (docs/research/09 §3, ADR 0006 1's second
    amendment).

    Shaped differently from :class:`ConfigColor`/:class:`ConfigAxis` on
    purpose: `default:`/`choices:` here name *schemes*, not colours, so
    "default must be one of choices" is an identity comparison on the scheme
    name rather than a colour-value one, and there is no `allow_any` --
    Styles has no equivalent of the editor's own unrestricted colour picker.
    """

    #: A declared `color_scheme:` name (the part after `color_scheme.`).
    default: str
    #: Declared `color_scheme:` names, in `choices:` order -- also the order
    #: `<style id="N">` numbers them from, and the order `resolveColorScheme`
    #: tests `style == N` in.
    choices: tuple[str, ...]
    span: Span | None = None


@dataclass(frozen=True)
class ConfigDataSlot:
    """One declared `config: data: <name>:` entry -- a native complication
    slot the wearer re-points at a different Garmin metric, on the watch
    (docs/research/09-data-library-and-config-axes.md §4).

    Shaped like :class:`ConfigColor` (a compiled-in default plus either an
    explicit orderable list or the editor's own unrestricted picker), but
    `default:`/`choices:` name `wfb.complications.TYPES` keys, not colours --
    the same table `on_hold:` and `catalog`'s `complication.*` sources
    already resolve against, not a second one.
    """

    name: str
    #: A `wfb.complications.TYPES` key -- compiled into the view as the
    #: starting `Complications.Id`, and the only one a device with no native
    #: editor (fr955) ever shows.  Not a fallback path; the path.
    default: str
    #: `"any"`, or the explicit picklist the editor offers, as
    #: `wfb.complications.TYPES` keys in `choices:` order.
    choices: "str | tuple[str, ...]"
    span: Span | None = None

    @property
    def allow_any(self) -> bool:
        return self.choices == "any"

    @property
    def field(self) -> str:
        """The generated view field this slot's chosen `Complications.Id` is
        cached in (`_configDataTop`)."""
        return config_field(f"data_{self.name}")


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
    #: Where this element's static root sits in the design's *authored* draw
    #: order, or None outside a static subtree.  Set alongside `static_root` by
    #: `Builder._apply_static`, and read only by :func:`draw_sort_key`: static
    #: content is hoisted to the front of draw order, and this is what keeps
    #: each root's members one unbroken run there, ordered the way the author's
    #: own `z:` ordered the roots themselves.
    static_rank: int | None = None
    #: `antialias:` as the author wrote it, or `None` to inherit -- from the
    #: enclosing group's own value, or from `Face.antialias` when there is
    #: none.  Accepted only on `group`, `shape`, `progress`, `icon` and
    #: `carousel`: `text` draws through a `fonts:` resource shared by every
    #: element that references it, so anti-aliasing cannot vary per element
    #: there (`Builder._reject_text_antialias`).
    antialias: bool | None = None
    #: The resolved value -- never `None` once `Builder._resolve_antialias`
    #: has run over the whole tree.  What every downstream stage reads: on
    #: `shape`/`progress` this is the flag for anti-aliased `Dc` primitive
    #: drawing (a later stage of this work, not emitted yet -- see
    #: docs/limitations.md); on `icon`, and on a `carousel`'s per-item icon
    #: fonts, it is threaded into `wfb.icons.font_key` and the baked sheet.
    #: On a `group` nothing reads it directly -- the field exists there only
    #: as the default source `_resolve_antialias` hands to the subtree.
    resolved_antialias: bool = False

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
class ComplicationSlot(Element):
    """`type: complication_slot` -- the element half of the native Data axis
    (docs/research/09-data-library-and-config-axes.md §4): draws whichever
    complication the wearer currently has this `slot:` pointed at.

    Deliberately not a `Text`/`IconElement` variant, and deliberately not
    reached through `wfb.catalog`/an ordinary bound `value:` expression at
    all: which complication *type* is showing is chosen by the wearer at
    runtime (`Complications.Id.getType()` only resolves on-device), so there
    is no fixed source for the expression compiler to bind at build time.
    Everything this element draws comes from a fresh
    `WfbComplications.valueOf(<slot field>)` pull, every frame, exactly the
    "complications are pulled, not cached" contract every other
    `complication.*` reader already has (CLAUDE.md).

    No `format:` -- see `Builder._build_complication_slot`'s rejection for
    why: `Complications.Complication.value` is a `String or Number or Float
    or Long or Double` union whose concrete shape genuinely varies by which
    choice the wearer picked, so a format string written for one choice
    would be silently wrong for another.  This element always renders
    `value.toString()`, plus whatever `label:`/`unit:` add.
    """

    #: The declared `config: data:` slot name this element shows (the part
    #: after `config.data.`), resolved and validated by
    #: `Builder._resolve_slot_reference`.
    slot: str = ""
    font: str = "FONT_SMALL"
    font_is_custom: bool = False
    #: Visual height of the icon chosen from the wearer's pick, or `None` to
    #: draw no icon at all.  Resolved on-device from `Complications.Id.
    #: getType()` through `wfb.icons.COMPLICATION_ICON` -- see
    #: `wfb.emit.monkeyc._emit_complication_slot`.
    icon_size: Length | None = None
    color: Expression | None = None
    #: `none` (default) | `short` | `long` -- `Complication.shortLabel`/
    #: `.longLabel`, read alongside the value, never authored.
    label: str = "none"
    #: Append `Complication.unit`'s suffix (`WfbComplications.mc`'s
    #: `unitSuffix`) after the value.
    unit: bool = False
    #: `hide` (default) | `placeholder`.  Unlike every other element's
    #: `when_absent:`, "hide" here blanks only the *reading* and leaves the
    #: icon drawn -- the same carve-out a carousel item's own `when_absent:`
    #: makes, and for the same reason: the icon says which metric the slot is
    #: pointed at, which is still true even on a frame the reading itself
    #: could not be pulled.
    when_absent: str = "hide"
    placeholder: str | None = None

    def _own_expressions(self) -> list[Expression]:
        return [e for e in (self.color,) if e]


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
class Graph(Element):
    """`type: graph` -- a time series drawn as a line, a filled area or bars.

    Modelled on `Progress`: one element with a `style:` discriminator, because
    the *drawing* is what varies, not the acquisition. Unlike `Progress`,
    there is no single bound `value:`/`max:` pair -- `series:` names an entry
    in the :mod:`wfb.series` catalogue, and the actual samples are acquired
    and cached on-device (`runtime-lib/WfbSeries.mc`, rebuilt once a minute),
    never through the expression compiler. `color:`, `min:` and `max:` *are*
    ordinary bound expressions (`_own_expressions` below), because a fixed
    bound or a conditional colour is exactly the same kind of thing on a graph
    as on any other element.
    """

    series: str = ""
    #: The SDK catalogue entry `series:` resolved to.  Kept on the element
    #: (rather than re-looked-up downstream) the same way `IconElement.
    #: codepoint` keeps `wfb.icons.resolve_codepoint`'s answer -- one lookup,
    #: at build time, against a table that can reject a name.
    series_def: SeriesDef | None = None
    #: "duration" (`range:` was `30m`/`4h`/`7d`) or "count" (a bare integer).
    range_kind: str = "duration"
    #: Seconds for a duration range; the sample count itself for a count one.
    range_value: int = 0
    #: Time-binned series only (`heart_rate` with a duration range) -- how
    #: many buckets `WfbSeries.binHeartRate` fills. Default 40.
    #:
    #: Deliberately **not** derived from the element's resolved pixel width,
    #: even though a pixel-per-bucket count is the obvious default someone
    #: might reach for instead: `wfb/emit/project.py` generates one view
    #: shared across every target device (`_emit_antialias_helper`'s
    #: docstring states this same constraint for a different feature -- "the
    #: decision cannot become a per-device constant"), and a resolved width
    #: differs per device the same way a resolved font size does. This is
    #: exactly `wfb.icons.font_key`'s reasoning for keying an icon font by
    #: its *declared* size rather than the pixel size it resolves to --
    #: baking a per-device value into a name (or, here, a loop bound) two
    #: devices' generated code must share produces an `Undefined symbol` (or,
    #: here, a wrong-length array) on every device but the one the view
    #: happened to be generated from. `buckets:` therefore stays an authored
    #: number, device-independent by construction, the same way `range:` is.
    buckets: int = 40
    style: str = "line"
    thickness: Length | None = None
    bar_width: Length | None = None
    #: `True` unless the author gave a fixed `min:`/`max:` -- see `min`/`max`
    #: below. Not the same axis as nullability: an *auto* bound is computed
    #: on-device from the series itself, a fixed one compiles like any other
    #: expression.
    min_auto: bool = True
    max_auto: bool = True
    min: Expression | None = None
    max: Expression | None = None
    size: Size = field(default_factory=Size)
    color: Expression | None = None
    #: The build-time-known upper bound on how many samples this graph can
    #: draw -- `buckets` for a time-binned duration range, the requested
    #: count otherwise, converted from a duration for an array-backed series
    #: using its own `interval_seconds`. Device-independent (it depends only
    #: on `range:`/`buckets:` and the series' own documented shape, never on
    #: a screen size), which is why it is resolved once here rather than in
    #: `wfb.layout` -- and why the 62-sample `style: area` cap and a
    #: documented-maximum overrun (`getHistory()`'s 7) are both build errors,
    #: not something a device-by-device pass could catch differently.
    sample_count: int = 0

    def _own_expressions(self) -> list[Expression]:
        return [e for e in (self.color, self.min, self.max) if e]


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
    #: The top-level `antialias:` default (§R1) -- what a font, icon or
    #: primitive-drawing element inherits when it declares no `antialias:`
    #: of its own.  Already folded into every element's own
    #: `resolved_antialias` and every `fonts:` entry's `FontSpec.antialias`
    #: by build time; kept here mainly so a re-render (preview, a future
    #: `wfb explain`) does not need to re-derive it.
    antialias: bool = False
    #: `config:` entries, keyed by axis name (`accent_color`/`data_color`).
    #: Empty on every design that declares no `config:` block, which is what
    #: keeps every existing golden file and generated project unchanged --
    #: every emitter below treats this dict as the single on/off switch for
    #: the whole feature.
    config: dict[str, ConfigColor] = field(default_factory=dict)
    #: Long-form `palette:` entries' labels, keyed by name.  Only entries
    #: declared with the `{value, label}` form and an actual `label:` appear
    #: here; a short-form entry (`name: "#RRGGBB"`) contributes nothing.
    #: `config:` already resolves a `palette.<name>` choice's label into its
    #: own `ConfigChoice.label` at build time, so nothing downstream reads
    #: this to render `config:` -- it exists for anything else (`wfb
    #: explain`) that wants a palette entry's label without re-parsing the
    #: source.
    palette_labels: dict[str, str] = field(default_factory=dict)
    #: `color_scheme:` entries, keyed by name.  Only accepted schemes appear
    #: here -- one with a role-set mismatch is dropped by
    #: `Builder._build_color_scheme` the same way a bad `config:` axis never
    #: reaches `Face.config`.
    color_scheme: dict[str, ColorScheme] = field(default_factory=dict)
    #: The `config: colors:` axis, or `None` when it was never declared (or
    #: was declared and rejected).  Unlike `config`, this is not a dict --
    #: there is exactly one Styles axis, not a table of them.
    config_colors: ConfigColorAxis | None = None
    #: `config: data:` slots, keyed by name.  A third, independent way to
    #: turn on the whole on-device-config feature -- see `has_config`.
    config_data: dict[str, ConfigDataSlot] = field(default_factory=dict)

    @property
    def has_config(self) -> bool:
        """Single on/off switch for the whole on-device-config feature.

        Three independent things can turn it on: a declared `accent_color:`/
        `data_color:` (`self.config`), a declared `config: colors:`
        (`self.config_colors`), or a declared `config: data:` (`self.
        config_data`).  Every emitter site that used to test `bool(face.
        config)` alone -- `needs_delegate`, the view's config fields/
        `applyConfig`/`onLayout`, the static-buffer repaint flag, the
        generated `<watchface-config>` resource, `check_config_support` --
        now goes through this instead, so a design declaring only
        `color_scheme:`/`config: colors:`/`config: data:` (no colour axis at
        all) still gets a delegate, `applyConfig` and the generated resource.
        See CLAUDE.md's own "Integration risk" note on this task for why
        every site matters.
        """
        return bool(self.config) or self.config_colors is not None or bool(self.config_data)

    def walk(self) -> list[Element]:
        """Every element, parents before children, in document order."""
        return walk_elements(self.elements)

    def draw_order(self) -> list[Element]:
        """Every element that actually draws, in the order it is drawn.

        Static content first, then document order stable-sorted by ``z`` --
        exactly what :class:`wfb.layout.Resolver` does to its flattened
        ``Placed`` list, because both call :func:`draw_sort_key`.  Groups are
        dropped for the same reason the emitter skips them: a group is a
        coordinate frame, not something that paints.  Device-independent,
        because every part of the key is.  ``tests/test_static.py`` pins the
        two orders together.
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
        #: Long-form `palette:` entries' labels, keyed by name.  Only the
        #: accepted entries with a `label:` appear here -- a rejected entry
        #: has neither a colour nor a label, and a short-form/unlabelled
        #: entry has a colour but no label.  Consulted only when a `config:`
        #: `default:`/`choices:` names the entry as `palette.<name>`, which
        #: is the one place a palette entry's label reaches beyond the
        #: palette itself.
        self.palette_labels: dict[str, str] = {}
        self.config: dict[str, ConfigColor] = {}
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
        #: Every name in the `palette:` block, whether or not it survived
        #: `_build_palette` -- the same "declared vs accepted" split
        #: `declared_fonts`/`rejected_fonts` keep, needed now that a
        #: `config:` `default:`/`choices:` entry can name a palette entry
        #: and must get exactly one error when that name was rejected.
        self.declared_palette: dict[str, Span | None] = {}
        self.rejected_palette: set[str] = set()
        #: `config:` axes that were declared and then rejected.  Bound into
        #: scope anyway (`_build_scope`) so the author gets exactly one error,
        #: at the real mistake -- the same cascade fix `rejected_fonts` above
        #: exists for, and for the same reason: a second 'unknown data source'
        #: error points at a correct line and blames the wrong thing.
        self.rejected_config: set[str] = set()
        #: `color_scheme:` entries, and the same declared/rejected split
        #: `declared_palette`/`rejected_palette` keep -- a scheme with a bad
        #: role colour or a role-set mismatch is rejected, and `config:
        #: colors:` referencing it by name must get exactly one error, not a
        #: second one blaming the reference.
        self.color_scheme: dict[str, ColorScheme] = {}
        self.declared_color_scheme: dict[str, Span | None] = {}
        self.rejected_color_scheme: set[str] = set()
        #: The `config: colors:` axis, once built -- `None` until then, and
        #: still `None` if it was declared and rejected (see
        #: `rejected_config`, which gets `"colors"` added in that case).
        self.config_colors: ConfigColorAxis | None = None
        #: The roles a `config.colors.<role>` reference may name, once known
        #: -- set in `_build_scope`, consulted only by `_expression`'s
        #: dedicated error for a bad or missing role (see its own docstring).
        #: `None` means "no `config: colors:` axis at all", not "zero roles".
        self._config_colors_roles: tuple[str, ...] | None = None
        #: `config: data:` slots, keyed by name -- the same declared/rejected
        #: split every other `config:` sub-block keeps, so a `slot:` naming a
        #: slot that was declared and then rejected (a bad default/choice
        #: reference) gets exactly one error, at the real mistake, not a
        #: second one blaming the element that references it.
        self.config_data: dict[str, ConfigDataSlot] = {}
        self.declared_config_data: dict[str, Span | None] = {}
        self.rejected_config_data: set[str] = set()
        self.scope = expr.Scope()
        self.seen_ids: dict[str, Span | None] = {}
        #: Derived Monkey C symbol -> the element id and span that claimed it
        #: first. Two distinct ids can still generate the same symbol
        #: (`temp_low` and `tempLow` both become `TEMP_LOW`), which the
        #: compiler must catch itself rather than let `monkeyc` discover it
        #: through a `Redefinition of ...` error pointing at generated code.
        self.seen_symbols: dict[str, tuple[str, Span | None]] = {}
        #: The top-level `antialias:` default, read first in `build()` --
        #: `_build_fonts` needs it (R5: a `fonts:` entry with no `antialias:`
        #: of its own follows the face) and it is not otherwise in scope by
        #: the time that method runs.
        self.face_antialias = False

    # -- entry point ------------------------------------------------------

    def build(self) -> Face | None:
        data = self.doc.data
        self.face_antialias = bool(data.get("antialias", False))
        self._build_palette(data.get("palette") or {})
        self._build_color_scheme(data.get("color_scheme") or {})
        self._build_config(data.get("config") or {})
        self._build_fonts(data.get("fonts") or {})
        self._build_scope()

        elements = self._build_elements(data.get("elements") or [], ("elements",))
        if not self.bag.ok():
            return None
        self._apply_static(elements)
        if not self.bag.ok():
            return None
        self._resolve_antialias(elements)

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
            palette_labels=dict(self.palette_labels),
            fonts=self.fonts,
            elements=elements,
            source_path=self.doc.path,
            antialias=self.face_antialias,
            config=self.config,
            color_scheme=self.color_scheme,
            config_colors=self.config_colors,
            config_data=self.config_data,
        )

    # -- palette, config, fonts, scope -------------------------------------

    def _build_palette(self, raw: dict) -> None:
        """`palette:` -- named colours, in either of two spellings.

        The short form, `name: "#RRGGBB"`, is unchanged.  The long form,
        `name: {value: "#RRGGBB", label: "..."}`, adds a label with no other
        effect here -- it only matters once a `config:` entry references this
        entry as `palette.<name>` (`_palette_reference`), which is where the
        label becomes a generated `<string>`, exactly as an inline `label:`
        on a `config:` choice already does.
        """
        for name, value in raw.items():
            span = self.doc.span(raw, name)
            self.declared_palette[name] = span
            if isinstance(value, dict):
                raw_value = value.get("value")
                value_span = self.doc.span(value, "value") or span
                label = value.get("label")
            else:
                raw_value = value
                value_span = span
                label = None
            if isinstance(raw_value, str) and raw_value.startswith(("palette.", "config.")):
                self.bag.error(
                    "palette",
                    f"palette entry {name!r} refers to {raw_value!r}",
                    value_span,
                    notes=[
                        "palette entries must be literal colours in this format version",
                        "reference a config entry directly from 'color:'/'track_color:' "
                        "instead -- e.g. 'color: config.accent_color' -- rather than "
                        "through a palette entry",
                    ],
                )
                self.rejected_palette.add(name)
                continue
            try:
                self.palette[name] = Color.parse(raw_value, what=f"palette.{name}")
            except ColorError as exc:
                self.bag.error("palette", str(exc), value_span)
                self.rejected_palette.add(name)
                continue
            if label is not None:
                self.palette_labels[name] = label

    def _palette_reference(self, name: str, span: Span | None) -> Color | None:
        """Resolve a `palette.<name>` reference used where a build-time literal
        colour is required -- a `config:` entry's own `default:`/`choices:`.

        Returns ``None`` when the name does not resolve, either because it was
        never declared or because it *was* declared and then rejected by
        `_build_palette` (an out-of-range colour, a `config.*` reference).  In
        the rejected case this stays quiet: the real mistake already has its
        own error pointing at the `palette:` block, and the same
        `rejected_fonts`/`rejected_config` cascade fix applies here -- one
        error at the real mistake, not one more per reference blaming the
        wrong line.
        """
        key = name[len("palette."):]
        if key in self.palette:
            return self.palette[key]
        if key in self.rejected_palette:
            return None
        known = ", ".join(f"palette.{n}" for n in sorted(self.declared_palette)) or "(none declared)"
        self.bag.error("config", f"unknown palette entry {name!r}", span,
                       notes=[f"declared palette entries: {known}"])
        return None

    def _resolve_config_color(self, raw: object, what: str, span: Span | None) -> Color | None:
        """A `config:` `default:`/`choices:` colour: a literal hex, or a
        `palette.<name>` reference resolved through `_palette_reference`."""
        if isinstance(raw, str) and raw.startswith("palette."):
            return self._palette_reference(raw, span)
        try:
            return Color.parse(raw, what=what)
        except ColorError as exc:
            self.bag.error("config", str(exc), span)
            return None

    def _build_color_scheme(self, raw: dict) -> None:
        """`color_scheme:` -- named role -> colour sets, picked on-device via
        `config: colors:` (docs/research/09 §3, ADR 0006 1's second
        amendment).

        A role's colour is resolved exactly like a `config:` axis's own
        `default:`/`choices:` colour (`_resolve_config_color`): a literal
        hex, or a `palette.<name>` reference, with the identical
        declared/rejected cascade behaviour a bad palette reference already
        has everywhere else.

        Every accepted scheme must declare the identical role set, checked
        here against the union of every scheme's own roles -- a scheme
        missing one that another has would leave `config.colors.<role>`
        undefined whenever the wearer picks the one that lacks it.  Checked
        with the union rather than an arbitrary "first" scheme so the report
        does not depend on declaration order: whichever scheme(s) fall short
        of what the others collectively declare are the ones named.
        """
        role_sets: dict[str, dict[str, Color]] = {}
        for name, spec in raw.items():
            span = self.doc.span(raw, name)
            self.declared_color_scheme[name] = span
            label = spec.get("label")
            raw_colors = spec["colors"]
            colors: dict[str, Color] = {}
            ok = True
            for role in raw_colors:
                role_span = self.doc.span(raw_colors, role)
                color = self._resolve_config_color(
                    raw_colors[role], f"color_scheme.{name}.colors.{role}", role_span)
                if color is None:
                    ok = False
                    continue
                colors[role] = color
            if not ok:
                self.rejected_color_scheme.add(name)
                continue
            self.color_scheme[name] = ColorScheme(name=name, label=label, colors=colors, span=span)
            role_sets[name] = colors

        if len(role_sets) < 2:
            return
        union: set[str] = set()
        for colors in role_sets.values():
            union |= set(colors)
        for name, colors in role_sets.items():
            missing = union - set(colors)
            if not missing:
                continue
            self.bag.error(
                "color-scheme",
                f"color_scheme.{name}: missing role(s) "
                f"{', '.join(sorted(missing))} -- every color_scheme entry "
                "must declare the same roles",
                self.color_scheme[name].span,
                notes=[
                    f"color_scheme.{name} declares: "
                    + (", ".join(sorted(colors)) or "(none)"),
                    "otherwise 'config.colors.<role>' would be undefined "
                    "whenever the wearer picks the scheme that lacks it",
                ],
            )
            self.rejected_color_scheme.add(name)
            del self.color_scheme[name]

    def _scheme_reference(self, raw: object, span: Span | None) -> str | None:
        """Resolve a `color_scheme.<name>` reference used from `config:
        colors:`'s own `default:`/`choices:`.

        Same declared/rejected cascade `_palette_reference` already has: a
        name that was declared and then rejected (a bad role colour, a
        role-set mismatch) gets no second error here, because the real
        mistake already has its own error pointing at the `color_scheme:`
        block.
        """
        if not (isinstance(raw, str) and raw.startswith("color_scheme.")):
            self.bag.error(
                "config",
                f"config.colors: expected a 'color_scheme.<name>' reference, got {raw!r}",
                span,
            )
            return None
        key = raw[len("color_scheme."):]
        if key in self.color_scheme:
            return key
        if key in self.rejected_color_scheme:
            return None
        known = ", ".join(f"color_scheme.{n}" for n in sorted(self.declared_color_scheme)) \
            or "(none declared)"
        self.bag.error(
            "config", f"unknown color scheme {raw!r}", span,
            notes=[f"declared color schemes: {known}"],
        )
        return None

    def _build_config_colors(self, spec: dict, span: Span | None) -> None:
        """`config: colors:` -- a Styles-axis picker over declared
        `color_scheme:` entries (docs/research/09 §3).

        Unlike `accent_color`/`data_color`, `default:`/`choices:` name
        *schemes*, not colours -- so "default must be one of choices" here is
        an identity comparison on the scheme name, not a colour-value one.
        Garmin still defines no behaviour for a default outside the list.
        """
        default_span = self.doc.span(spec, "default")
        default_name = self._scheme_reference(spec["default"], default_span)
        if default_name is None:
            self.rejected_config.add("colors")
            return

        raw_choices = spec["choices"]
        choices: list[str] = []
        ok = True
        for index, item in enumerate(raw_choices):
            item_span = self.doc.span(raw_choices, index)
            name = self._scheme_reference(item, item_span)
            if name is None:
                ok = False
                continue
            choices.append(name)
        if not ok:
            self.rejected_config.add("colors")
            return

        if default_name not in choices:
            self.bag.error(
                "config",
                f"config.colors: default {spec['default']!r} is not one of 'choices:'",
                default_span,
                notes=[
                    "the on-device editor marks one listed style as the user's "
                    "default (the generated <style default=\"true\">) -- Garmin "
                    "defines no behaviour for a default that is not in the list",
                    "add it to 'choices:', or change 'default:' to match a "
                    "scheme already there",
                    "listed schemes: "
                    + ", ".join(f"color_scheme.{n}" for n in choices),
                ],
            )
            self.rejected_config.add("colors")
            return

        self.config_colors = ConfigColorAxis(
            default=default_name, choices=tuple(choices), span=span)

    def _complication_reference(self, raw: object, what: str, span: Span | None) -> str | None:
        """Resolve a `complication.<name>` reference used from `config: data:`'s
        own `default:`/`choices:`, against :mod:`wfb.complications` -- the same
        table `on_hold:` and `catalog`'s `complication.*` sources already
        resolve against, not a second one (docs/research/09 §4).
        """
        if not (isinstance(raw, str) and raw.startswith("complication.")):
            self.bag.error("config", f"{what}: expected a 'complication.<name>' "
                                     f"reference, got {raw!r}", span)
            return None
        name = raw[len("complication."):]
        if complications.get(name) is not None:
            return name
        near = complications.suggest(name)
        notes = []
        if near:
            notes.append("did you mean: " + ", ".join(near) + "?")
        notes.append(f"run `wfb complications` for the full list of "
                     f"{len(complications.TYPES)} types")
        self.bag.error("config", f"{what}: unknown complication type {raw!r}", span, notes=notes)
        return None

    def _build_config_data(self, raw: dict, block_span: Span | None) -> None:
        """`config: data:` -- named native complication slots
        (docs/research/09-data-library-and-config-axes.md §4).

        Shaped like `_build_config`'s colour-axis loop: a compiled-in
        `default:` plus either `"any"` (the editor's own unrestricted
        complication picker) or an explicit, orderable `choices:` list --
        except every name here is a `complication.<name>` reference into
        :mod:`wfb.complications` rather than a colour.
        """
        for name, spec in raw.items():
            span = self.doc.span(raw, name)
            self.declared_config_data[name] = span
            default_span = self.doc.span(spec, "default")
            default = self._complication_reference(
                spec["default"], f"config.data.{name}.default", default_span)
            if default is None:
                self.rejected_config_data.add(name)
                continue

            raw_choices = spec["choices"]
            if raw_choices == "any":
                self.config_data[name] = ConfigDataSlot(
                    name=name, default=default, choices="any", span=span)
                continue

            choices: list[str] = []
            ok = True
            for index, item in enumerate(raw_choices):
                item_span = self.doc.span(raw_choices, index)
                resolved = self._complication_reference(
                    item, f"config.data.{name}.choices[{index}]", item_span)
                if resolved is None:
                    ok = False
                    continue
                choices.append(resolved)
            if not ok:
                self.rejected_config_data.add(name)
                continue

            if default not in choices:
                self.bag.error(
                    "config",
                    f"config.data.{name}: default {spec['default']!r} is not "
                    "one of 'choices:'",
                    default_span,
                    notes=[
                        "the on-device editor marks one listed type as the user's "
                        "default (the generated <type default=\"true\">) -- Garmin "
                        "defines no behaviour for a default that is not in the list",
                        "add it to 'choices:', or change 'default:' to match a "
                        "type already there",
                        "listed types: " + ", ".join(f"complication.{n}" for n in choices),
                    ],
                )
                self.rejected_config_data.add(name)
                continue

            self.config_data[name] = ConfigDataSlot(
                name=name, default=default, choices=tuple(choices), span=span)

    def _resolve_slot_reference(self, raw: str, span: Span | None) -> ConfigDataSlot | None:
        """Resolve a `complication_slot`'s `slot: config.data.<name>` reference.

        The same declared/rejected cascade every other `config:` sub-block
        keeps: a name that was declared and then rejected (a bad default/
        choice reference, or a default not among choices) gets no second
        error here, because the real mistake already has its own error
        reported against the `config: data:` block.
        """
        if not raw.startswith("config.data."):
            self.bag.error(
                "complication-slot",
                f"slot: expected 'config.data.<name>', got {raw!r}",
                span,
            )
            return None
        name = raw[len("config.data."):]
        if name in self.config_data:
            return self.config_data[name]
        if name in self.rejected_config_data:
            return None
        known = ", ".join(f"config.data.{n}" for n in sorted(self.declared_config_data)) \
            or "(none declared)"
        self.bag.error(
            "complication-slot", f"unknown slot {raw!r}", span,
            notes=[f"declared slots: {known}"],
        )
        return None

    def _build_config(self, raw: dict) -> None:
        """`config:` -- the native editor's colour axes, the Styles axis, and
        the Data axis (ADR 0006 1, twice amended; docs/research/09 §4).

        `accent_color`/`data_color` read back as a single `Color`; `colors`
        picks a declared `color_scheme:` entry instead (`_build_config_colors`)
        -- a different enough shape that it does not fit `ConfigAxis`/
        `ConfigColor` at all; `data` is a mapping of named slots, each built by
        `_build_config_data`.  Only these four keys reach here: the schema's
        `additionalProperties: false` on `config:` rejects anything else
        before the IR ever sees it, the same division of labour `_build_fonts`
        and `_build_palette` already rely on for their own blocks.
        """
        for name, spec in raw.items():
            span = self.doc.span(raw, name)
            if name == "colors":
                self._build_config_colors(spec, span)
                continue
            if name == "data":
                self._build_config_data(spec, span)
                continue
            default_span = self.doc.span(spec, "default")
            default = self._resolve_config_color(
                spec["default"], f"config.{name}.default", default_span)
            if default is None:
                self.rejected_config.add(name)
                continue

            raw_choices = spec["choices"]
            if raw_choices == "any":
                self.config[name] = ConfigColor(name=name, default=default, choices="any",
                                                span=span)
                continue

            choices: list[ConfigChoice] = []
            ok = True
            for index, item in enumerate(raw_choices):
                item_span = self.doc.span(raw_choices, index)
                if isinstance(item, str):
                    # A bare `palette.<name>` reference -- the schema accepts
                    # nothing else as a plain string here.  Contributes the
                    # entry's colour and, if it has one, its label.
                    color = self._palette_reference(item, item_span)
                    if color is None:
                        ok = False
                        continue
                    choices.append(ConfigChoice(
                        color=color,
                        label=self.palette_labels.get(item[len("palette."):]),
                    ))
                    continue
                try:
                    color = Color.parse(item["color"], what=f"config.{name}.choices[{index}]")
                except ColorError as exc:
                    self.bag.error("config", str(exc), self.doc.span(item, "color"))
                    ok = False
                    continue
                choices.append(ConfigChoice(color=color, label=item.get("label")))
            if not ok:
                self.rejected_config.add(name)
                continue

            if not any(choice.color == default for choice in choices):
                self.bag.error(
                    "config",
                    f"config.{name}: default {spec['default']!r} is not one of 'choices:'",
                    default_span,
                    notes=[
                        "the on-device editor marks one listed colour as the user's "
                        "default (the generated <color default=\"true\">) -- Garmin "
                        "defines no behaviour for a default that is not in the list",
                        "add it to 'choices:', or change 'default:' to match a colour "
                        "already there",
                        "listed colours: " + ", ".join(str(c.color) for c in choices),
                    ],
                )
                self.rejected_config.add(name)
                continue

            self.config[name] = ConfigColor(name=name, default=default,
                                            choices=tuple(choices), span=span)

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
                # R5: a font with no `antialias:` of its own follows the
                # face-wide default rather than a hardcoded False, exactly
                # the same inherit-once-and-freeze a font's `size:` gets from
                # its own `scale:` -- there is nothing further beneath a
                # `fonts:` entry to inherit from, so this is resolved here,
                # not deferred to a tree walk the way an element's is.
                antialias=bool(spec.get("antialias", self.face_antialias)),
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
        """Populate the expression scope: catalogue sources, palette, config.

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
        for name in sorted(self.rejected_palette):
            # Declared, then rejected above (an out-of-range colour, or a
            # `config.*`/`palette.*` reference `_build_palette` refuses).
            # Bound into scope anyway so an element's `color: palette.<name>`
            # gets the one real error already reported against the
            # `palette:` block, not a second "unknown data source" blaming
            # the element for a mistake made elsewhere -- the same cascade
            # fix `rejected_fonts`/`rejected_config` exist for, in the same
            # shape.  Nothing is emitted from a design that has an error, so
            # the placeholder value here is never reached.
            self.scope.define(
                f"palette.{name}",
                expr.Binding(
                    expr.Value(Type.COLOR),
                    code=f"Palette.{name.upper()}",
                    constant=0,
                    kind="palette",
                ),
            )
        for name, entry in self.config.items():
            self.scope.define(
                f"config.{name}",
                expr.Binding(
                    expr.Value(Type.COLOR),
                    code=entry.field,
                    # `constant=None` is deliberate, unlike a palette entry: the
                    # view field this reads is user-editable at runtime (on a
                    # device with the native editor), so `fold` must never
                    # inline it as the declared default -- `expr.fold`'s Ref
                    # branch only substitutes when `binding.constant` is set.
                    constant=None,
                    kind="config",
                ),
            )
        for name in sorted(self.rejected_config - {"colors"}):
            # Declared, then rejected above.  Binding it anyway keeps the one
            # real error the only error: without this, every `color:
            # config.<name>` in the design adds an "unknown data source" that
            # is true only because the compiler threw the axis away -- the
            # cascade `rejected_fonts` already exists to prevent, in the same
            # shape.  Nothing is emitted from a design that has an error, so
            # the field name here is never reached.  `"colors"` is excluded --
            # it is not a single-colour axis, so it cannot use `config_field`
            # the way every other rejected axis does, and is handled in the
            # `config.colors.<role>` block below instead.
            self.scope.define(
                f"config.{name}",
                expr.Binding(
                    expr.Value(Type.COLOR),
                    code=config_field(name),
                    constant=None,
                    kind="config",
                ),
            )

        # `config.colors.<role>` -- one binding per role of a declared
        # `config: colors:` axis, deliberately *not* one binding for the bare
        # `config.colors` (a scheme is not a colour; see `_expression`'s
        # dedicated error for that and for a bad role, both keyed off
        # `self._config_colors_roles`).
        if self.config_colors is not None:
            default_scheme = self.color_scheme[self.config_colors.default]
            self._config_colors_roles = tuple(sorted(default_scheme.colors))
            for role, color in default_scheme.colors.items():
                self.scope.define(
                    f"config.colors.{role}",
                    expr.Binding(
                        expr.Value(Type.COLOR),
                        code=config_field(f"colors_{role}"),
                        constant=None,
                        kind="config",
                    ),
                )
        elif "colors" in self.rejected_config:
            # The axis itself was declared and rejected (a bad default/choice
            # reference, or a default not among choices) -- the same cascade
            # as above, generalised to a multi-role axis: bind whatever roles
            # a surviving `color_scheme:` entry still declares, so a
            # `color: config.colors.<role>` reference gets the one real error
            # already reported against `config:`, not a second one.
            roles: set[str] = set()
            for scheme in self.color_scheme.values():
                roles |= set(scheme.colors)
            if roles:
                self._config_colors_roles = tuple(sorted(roles))
                for role in self._config_colors_roles:
                    self.scope.define(
                        f"config.colors.{role}",
                        expr.Binding(
                            expr.Value(Type.COLOR),
                            code=config_field(f"colors_{role}"),
                            constant=None,
                            kind="config",
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
            antialias=(bool(node["antialias"]) if "antialias" in node else None),
        )

        builders = {
            "group": self._build_group,
            "shape": self._build_shape,
            "text": self._build_text,
            "progress": self._build_progress,
            "icon": self._build_icon,
            "carousel": self._build_carousel,
            "graph": self._build_graph,
            "complication_slot": self._build_complication_slot,
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
        if node.get("type") == "complication_slot":
            # Only emitted when `icon_size:` is set, but reserved for every
            # `complication_slot` regardless -- the same "an unrelated later
            # edit must not introduce a collision" reasoning as the group
            # case just above.
            candidates.append(complication_slot_icon_method(element_id))
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

    def _resolve_antialias(self, elements: list[Element]) -> None:
        """Resolve `antialias:` as an inherited *default*, root to leaf.

        Deliberately a single top-down pass over the finished tree, called
        once from `build()`, rather than pushed per group the way
        `_push_visible` is: `visible:` *conjoins*, so composing it bottom-up
        as each group finishes building is safe and even necessary (an inner
        group has already folded its own condition into its children before
        the outer one runs). `antialias:` is a plain override, not something
        that accumulates -- the nearest enclosing declaration simply wins --
        so there is nothing to compose, and threading "does an ancestor
        further up still have to hand this element a default" through the
        bottom-up build order would need more bookkeeping than a second,
        independent walk over the tree that already exists in full.

        A child's own `antialias:` always wins outright over its group's
        (unlike `visible:`, there is no meaningful "AND" of two booleans that
        both mean "should this look soft" -- one of them is simply what the
        author asked for here), which is exactly what leaving `inherited`
        unchanged for an element that declares its own value, and only
        substituting it for one that left `antialias:` as `None`, gives.
        """
        def visit(items: list[Element], inherited: bool) -> None:
            for element in items:
                resolved = element.antialias if element.antialias is not None else inherited
                element.resolved_antialias = resolved
                if isinstance(element, Group):
                    visit(element.items, resolved)

        visit(elements, self.face_antialias)

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
          asked not to be drawn in.

        Every one of these is an error rather than a warning: each is a design
        that would compile and then be silently wrong on the wrist, which is the
        failure mode this compiler exists to remove.

        The one restriction that is *not* an error any more is draw order.  An
        opaque blit erases whatever is under it, so static content has to come
        first -- but "has to come first" is something the compiler can simply
        arrange, and now does: :func:`draw_sort_key` hoists it, and the author
        hears about it only where the hoist can change the picture
        (`warning[static-overlap]`, `wfb.lint.check_static_overlap`).  Ranking
        the roots here is the whole of what the hoist needs from this pass.
        """
        roots = [e for e in walk_elements(elements) if e.static]
        if not roots:
            return
        for root in roots:
            self._mark_static(root, root)
        self._rank_static(elements, roots)
        if not self._check_static_subtrees(roots):
            return
        self._check_static_modes(roots)

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
                if isinstance(element, Graph):
                    # A graph's series isn't an `Expression` -- it is
                    # recomputed on-device every minute -- so the generic
                    # "nothing here may read a data source" check just below
                    # would never see it. Checked explicitly for the same
                    # reason a carousel is: a buffer filled once would freeze
                    # a picture that is supposed to move.
                    self.bag.error(
                        "static",
                        f"{element.id!r} is a graph and cannot be static",
                        element.span,
                        notes=["a graph's series is recomputed once a minute -- a "
                               "buffer filled once would freeze it at whatever it "
                               "showed on the first frame",
                               f"take it out of {root.id!r}"
                               if element is not root else
                               "drop `static: true` from it"],
                    )
                    ok = False
                    continue
                if isinstance(element, ComplicationSlot):
                    # Its reading is not an `Expression` either -- it is a
                    # fresh `WfbComplications.valueOf` pull every frame, and
                    # the wearer can repoint the slot at a different metric on
                    # a device with the native editor at any time -- so the
                    # same "would freeze it" reasoning as a carousel/graph
                    # applies, for the same reason the generic source check
                    # below would never catch it.
                    self.bag.error(
                        "static",
                        f"{element.id!r} is a complication_slot and cannot be static",
                        element.span,
                        notes=["its reading is pulled fresh every frame, and the "
                               "wearer can repoint it to a different complication "
                               "at any time -- a buffer filled once would freeze "
                               "both",
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

    def _rank_static(self, elements: list[Element], roots: list[Element]) -> None:
        """Number the static roots by where the author's own draw order put them.

        Each root's rank is the authored draw-order position of its
        first-drawn member, and every element of the subtree carries it.
        :func:`draw_sort_key` then hoists the static content as a block,
        keeping each root's members contiguous and the roots in the order the
        author put them -- rather than in document order, which a `z:` on one
        of the roots may well have overruled.
        """
        position = {id(e): i for i, e in enumerate(authored_draw_order(elements))}
        for root in roots:
            members = [e for e in walk_elements([root]) if e.kind != "group"]
            rank = min((position[id(e)] for e in members if id(e) in position),
                       default=len(position))
            for element in walk_elements([root]):
                element.static_rank = rank

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
        if "antialias" in node:
            self._reject_text_antialias(node, element)
        if value is not None:
            self._check_absence(node, element, value, element.when_absent, element.placeholder,
                                element.fallback)
            self._check_format(node, value, element.format)
        self._check_other_absence(node, element, "color", element.color)
        self._check_reachable_substitute(node, element, "'color'",
                                         (element.value,), (element.color,))
        return element

    def _reject_text_antialias(self, node: dict, element: Text) -> None:
        """`antialias:` on a `text` element -- a per-element key on a shared resource.

        A text element draws through a font declared in `fonts:`, and that
        font is one bitmap resource shared by every element that references
        it (`font: font.clock` is a name, not a private copy) -- so
        anti-aliasing cannot vary per element the way it can on a shape's own
        outline or an icon's own, per-glyph font.  The schema still parses
        `antialias:` here rather than rejecting it as an unknown key, purely
        so this can name the actual font instead of jsonschema's generic
        "unknown key" message -- the same trick `on_tap:` uses to report its
        own rename against the author's line, and for the same reason: by
        the time `_resolve_font` above has run, `element.font` is the real
        answer, not a guess.
        """
        span = self.doc.span(node, "antialias")
        if element.font_is_custom:
            notes = [f"put it on 'fonts: {element.font}: antialias:' instead -- "
                     f"the font this element references"]
        else:
            notes = [f"this element uses the system font {element.font!r}, which "
                     "has no 'antialias:' of its own to set -- only a custom "
                     "'fonts:' entry does"]
        self.bag.error(
            "text-antialias",
            f"{element.id}: 'antialias:' is not accepted on a 'text' element",
            span,
            notes=notes,
        )

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

    def _build_complication_slot(self, node: dict, common: dict, path: tuple) -> Element:
        """`type: complication_slot` -- the element half of the native Data
        axis (docs/research/09-data-library-and-config-axes.md §4).

        Most of what makes every other element kind checkable at build time
        -- a fixed source, a static type -- does not exist here: which
        `complication.<name>` the wearer picked is only known on-device.  So
        this validates the *slot reference* and the authoring keys that do
        not depend on the choice (`icon_size:`/`choices: any`, `format:`),
        and leaves everything about the pulled value itself to
        `wfb.emit.monkeyc._emit_complication_slot`, which reads it fresh
        every frame the same way any other `complication.*` source does.
        """
        slot_raw = node["slot"]
        slot = self._resolve_slot_reference(str(slot_raw), self.doc.span(node, "slot"))

        icon_size = self._length(node, "icon_size")
        if icon_size is not None and icon_size.unit not in units.SIZE_UNITS:
            self.bag.error(
                "complication-slot",
                f"icon_size must be px or %r, not {icon_size.unit}",
                self.doc.span(node, "icon_size"),
                notes=["an icon's font is baked once, before layout runs, so its size "
                       "cannot depend on a parent box (%) or an element's own font (pt)"],
            )
            icon_size = None
        if icon_size is not None and slot is not None and slot.allow_any:
            self.bag.error(
                "complication-slot",
                f"{common['id']}: 'icon_size:' cannot be combined with a slot "
                f"whose 'choices:' is 'any' ({slot_raw!r})",
                self.doc.span(node, "icon_size"),
                notes=[
                    "'choices: any' hands the wearer the editor's own unrestricted "
                    "complication picker, so the set of types -- and therefore icons "
                    "-- a slot could need is unbounded, and nothing can be baked "
                    "ahead of time",
                    "drop 'icon_size:' (the slot then draws no icon), or give this "
                    "slot an explicit 'choices:' list instead of 'any'",
                ],
            )
            icon_size = None

        if "format" in node:
            self.bag.error(
                "complication-slot",
                f"{common['id']}: 'format:' is not accepted on a 'complication_slot'",
                self.doc.span(node, "format"),
                notes=[
                    "Complications.Complication.value is a String or Number or "
                    "Float or Long or Double union whose concrete type genuinely "
                    "varies by which choice the wearer picks -- a format string "
                    "written for one choice would be silently wrong for another",
                    "this element always renders 'value.toString()'; use 'label:' "
                    "and/or 'unit:' for the extra context a format string would "
                    "otherwise add",
                ],
            )

        color = self._color_expression(node, "color")
        element = ComplicationSlot(
            **common,
            slot=(slot.name if slot is not None else str(slot_raw)),
            icon_size=icon_size,
            color=color,
            label=node.get("label", "none"),
            unit=bool(node.get("unit", False)),
            when_absent=node.get("when_absent", "hide"),
            placeholder=node.get("placeholder"),
        )
        self._resolve_font(node, element)

        if element.on_hold is not None:
            self.bag.error(
                "complication-slot",
                f"{element.id}: 'on_hold:' is not accepted on a 'complication_slot' yet",
                element.span,
                notes=[
                    "nothing about the platform prevents it -- `Complications.exitTo` "
                    "takes a `Complications.Id`, and this slot already holds one, so "
                    "holding it would open whichever glance the wearer's own choice "
                    "belongs to.  It is simply not built yet",
                    "this is unrelated to the editor's animated highlight "
                    "(getComplicationDrawable/onTap), which fires only inside the "
                    "on-device editor and never on a face being looked at "
                    "(docs/research/07-carousel-interaction.md §1)",
                    "drop 'on_hold:' for now",
                ],
            )
            element.on_hold = None

        if color is None:
            self._require(node, "color", "a complication_slot needs a color")
        elif color.nullable:
            self.bag.error(
                "complication-slot",
                f"{element.id}: 'color:' reads {color.text!r}, which can be absent",
                self.doc.span(node, "color"),
                notes=[
                    "a complication_slot's colour has no 'when_absent:' of its own "
                    "-- 'when_absent:'/'placeholder:' governs the pulled reading, "
                    "not the element's appearance",
                    "guard it in the expression instead, e.g. "
                    "\"x != null and x > 100 ? palette.hot : palette.fg\"",
                ],
            )

        if element.when_absent == "placeholder" and element.placeholder is None:
            self._require(node, "placeholder", "when_absent: placeholder needs a 'placeholder:'")

        return element

    def _build_graph(self, node: dict, common: dict, path: tuple) -> Element:
        """`type: graph` -- a time series over a data source and a range.

        The four validation questions here are independent of each other and
        of layout (nothing below reads a device or a box): which series,
        which range, whether `buckets:` means anything for that combination,
        and whether the resulting sample count fits the chosen `style:`.
        """
        name = node.get("series")
        src = series.get(name) if name else None
        if src is None:
            reason = series.unavailable_reason(str(name)) if name else None
            if reason is not None:
                # Not a typo -- a real quantity the platform will not serve as
                # a history.  Saying "unknown" would send the author hunting
                # for a spelling mistake that does not exist.
                self.bag.error(
                    "graph",
                    f"{name!r} cannot be plotted on a watch face",
                    self.doc.span(node, "series"),
                    notes=[reason,
                           "run `wfb series` for what a watch face can plot",
                           "docs/research/08-graphs-and-configuration.md §1 has "
                           "the evidence"],
                )
            else:
                near = series.suggest(str(name)) if name else []
                self.bag.error(
                    "graph",
                    f"unknown series {name!r}",
                    self.doc.span(node, "series"),
                    notes=(["did you mean: " + ", ".join(near) + "?"] if near else [])
                    + ["run `wfb series` for the full list"],
                )

        range_kind, range_value = self._graph_range(node, src)
        buckets = int(node.get("buckets", 40))
        heart_rate_duration = (
            src is not None and src.acquisition is Acquisition.HEART_RATE
            and range_kind == "duration"
        )
        if "buckets" in node and not heart_rate_duration:
            reason = (
                "a count range does not bin by time" if src is not None
                and src.acquisition is Acquisition.HEART_RATE
                else f"{name!r} is not time-binned" if src is not None
                else "the series is unknown"
            )
            self.bag.error(
                "graph",
                f"'buckets' has no effect here -- {reason}",
                self.doc.span(node, "buckets"),
                notes=["'buckets:' only means something for a time-binned series read "
                       "over a duration -- 'heart_rate' with a 'range:' such as '4h'",
                       "drop 'buckets:', or change 'range:' to a duration"],
            )
        if buckets < 1:
            self.bag.error(
                "graph", "'buckets' must be at least 1", self.doc.span(node, "buckets"),
            )
            buckets = 40

        style = node.get("style", "line")
        thickness = self._length(node, "thickness")
        bar_width = self._length(node, "bar_width")
        self._check_graph_style_keys(node, style)

        min_expr, min_auto = self._graph_bound(node, "min")
        max_expr, max_auto = self._graph_bound(node, "max")
        if (min_expr is not None and min_expr.is_constant
                and max_expr is not None and max_expr.is_constant):
            try:
                lo, hi = float(min_expr.constant), float(max_expr.constant)
            except (TypeError, ValueError):
                lo = hi = None
            if lo is not None and lo >= hi:
                self.bag.error(
                    "graph",
                    f"min ({min_expr.text}) must be less than max ({max_expr.text})",
                    self.doc.span(node, "max") or self.doc.span(node),
                )

        sample_count = self._graph_sample_count(node, src, range_kind, range_value, buckets)
        if style == "area" and sample_count > GRAPH_AREA_MAX_SAMPLES:
            self.bag.error(
                "graph",
                f"a 'style: area' graph can plot at most {GRAPH_AREA_MAX_SAMPLES} "
                f"samples (Dc.fillPolygon's own 64-point limit, minus the two "
                f"corners that close the outline), but this graph requests "
                f"{sample_count}",
                self.doc.span(node, "range") or self.doc.span(node),
                notes=["use 'style: line' instead, or shorten 'range:'/'buckets:'"],
            )

        element = Graph(
            **common,
            series=str(name) if name is not None else "",
            series_def=src,
            range_kind=range_kind,
            range_value=range_value,
            buckets=buckets,
            style=style,
            thickness=thickness,
            bar_width=bar_width,
            min_auto=min_auto,
            max_auto=max_auto,
            min=min_expr,
            max=max_expr,
            size=self._size(node.get("size")),
            color=self._color_expression(node, "color"),
            sample_count=sample_count,
        )
        # No `_check_other_absence` here, deliberately: a graph has no
        # `when_absent:` field to require, the same as `shape` and `icon`
        # (only `text`/`progress` have a value-substitution policy for
        # `_check_other_absence` to guard against being silently insufficient
        # for a *different* nullable binding). A nullable `color:`/`min:`/
        # `max:` still gets a real guard -- `wfb.emit.monkeyc.ReadPlan.guards`
        # is generic over `element.expressions()` and does not consult
        # `when_absent` at all when the element has none.
        return element

    def _graph_range(self, node: dict, src: SeriesDef | None) -> tuple[str, int]:
        """Parse `range:` -- a duration string or a bare integer sample count."""
        raw = node.get("range")
        if isinstance(raw, bool):
            self.bag.error("units", "range must be a duration or an integer count",
                           self.doc.span(node, "range"))
            return "count", 0
        if isinstance(raw, int):
            if raw < 1:
                self.bag.error("graph", "range must be at least 1 sample",
                               self.doc.span(node, "range"))
                return "count", 1
            return "count", raw
        if isinstance(raw, str):
            try:
                duration = Duration.parse(raw, what="range")
            except UnitError as exc:
                self.bag.error("units", str(exc), self.doc.span(node, "range"))
                return "duration", 0
            return "duration", duration.seconds
        self.bag.error(
            "units",
            f"range must be a duration ('30m', '4h', '7d') or an integer sample "
            f"count, got {raw!r}",
            self.doc.span(node, "range"),
        )
        return "count", 0

    def _graph_sample_count(self, node: dict, src: SeriesDef | None, range_kind: str,
                            range_value: int, buckets: int) -> int:
        """The build-time-known upper bound on this graph's sample count.

        `range: 14d` on `steps` is an error, not a clamp (SPEC.md): silently
        drawing 7 when 14 was asked for is exactly the quiet wrongness this
        compiler exists to remove.  Only checked against a *documented*
        maximum (`SeriesDef.max_count`) -- the forecast arrays document none,
        so a design asking for more than the provider actually has simply
        gets fewer, bounds-checked at runtime the same way `weather.
        condition_today`/`_tomorrow` already are.
        """
        if src is None:
            return max(1, range_value if range_kind == "count" else buckets)
        if src.acquisition is Acquisition.HEART_RATE:
            return buckets if range_kind == "duration" else max(1, range_value)
        if range_kind == "count":
            count = max(1, range_value)
        else:
            interval = src.interval_seconds or 1
            count = max(1, -(-range_value // interval))  # ceiling division
        if src.max_count is not None and count > src.max_count:
            self.bag.error(
                "graph",
                f"'{src.name}' requests {count} entries, but returns at most "
                f"{src.max_count}",
                self.doc.span(node, "range"),
                notes=[f"{src.source_ref} documents the cap directly",
                       "shorten 'range:', or lower the sample count"],
            )
        return count

    def _check_graph_style_keys(self, node: dict, style: str) -> None:
        if style not in GRAPH_STYLE_KEYS:
            return  # the schema has already rejected an unknown style
        for key in sorted(_ALL_GRAPH_STYLE_KEYS - GRAPH_STYLE_KEYS[style]):
            if key not in node:
                continue
            owners = sorted(s for s, keys in GRAPH_STYLE_KEYS.items() if key in keys)
            self.bag.error(
                "graph",
                f"{key!r} is not used by 'style: {style}'",
                self.doc.span(node, key) or self.doc.span(node),
                notes=[f"'style: {style}' reads: "
                       + (", ".join(sorted(GRAPH_STYLE_KEYS[style])) or "(nothing)"),
                       f"{key!r} belongs to " + " and ".join(f"'style: {s}'" for s in owners)],
            )

    def _graph_bound(self, node: dict, key: str) -> tuple[Expression | None, bool]:
        """`min:`/`max:` -- `auto` (the default) or a compiled numeric expression."""
        raw = node.get(key)
        if raw is None or (isinstance(raw, str) and raw.strip() == "auto"):
            return None, True
        expression = self._expression(node, key)
        if expression is not None and not expression.value.type.is_numeric():
            self.bag.error(
                "type", f"graph {key} must be a number, got {expression.value}",
                self.doc.span(node, key),
            )
            return None, False
        return expression, False

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
            message, notes, code_ = exc.message, exc.notes, exc.code or "expression"
            # `config.colors` (a scheme, used bare) and `config.colors.<bad
            # role>` both reach here as an ordinary "unknown data source" --
            # nothing under `config.colors.*` is bound in scope except the
            # roles a real axis actually has (`_build_scope`).  Overridden
            # with a domain-specific message rather than left as a generic
            # typo report, which would otherwise be the only diagnostic a
            # `color: config.colors` (missing its role) or a misspelled role
            # ever gets -- "much less helpful", per the brief this shipped
            # against.
            if self._config_colors_roles is not None:
                match = _CONFIG_COLORS_RE.match(message)
                if match is not None:
                    roles = ", ".join(f"config.colors.{r}" for r in self._config_colors_roles)
                    code_ = "config"
                    if match.group(1) == "":
                        message = "config.colors is a colour scheme, not a colour"
                        notes = [f"reference a role instead: {roles}"]
                    else:
                        message = f"config.colors has no role {match.group(1)[1:]!r}"
                        notes = [f"declared roles: {roles}"]
            self.bag.error(
                code_,
                f"{key}: {message}",
                _offset_span(span, text, exc.offset),
                notes=notes,
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


def authored_draw_order(elements: list[Element]) -> list[Element]:
    """Draw order as the author wrote it: document order, stable-sorted by ``z``.

    This is draw order *before* the static hoist.  Nothing draws in it -- it
    exists so :func:`wfb.lint.check_static_overlap` can say which pairs of
    elements the hoist swapped, and so :meth:`Builder._apply_static` can rank
    the static roots by where the author actually put them rather than by
    where they happen to appear in the document.
    """
    drawn = [e for e in walk_elements(elements) if e.kind != "group"]
    return sorted(drawn, key=lambda e: (e.z if e.z is not None else 0,))


def draw_sort_key(element: Element) -> tuple:
    """The sort key that puts an element in draw order, static content first.

    The static buffer is opaque and full-screen (`docs/research/probes/
    static-buffer/`), so its blit erases whatever was drawn under it.  That
    used to be an error -- static content had to *be* a contiguous prefix of
    draw order, and a design where it was not simply failed to build.  It is
    now a **rule** instead: static content is *made* the prefix, here, by
    sorting, and the only thing the author is told is what changed --
    `warning[static-overlap]`, on the pairs whose relative order the hoist
    actually swapped *and* whose boxes overlap, where it can make a visible
    difference.

    Three ranks, in order:

    * ``0`` for static content, ``1`` for everything else -- the hoist itself;
    * ``static_rank``, the position of the element's own root in the authored
      order, which keeps each root's members one unbroken run (the emitter
      writes one ``drawStatic<Id>`` per root and calls each once, so two roots
      interleaving would emit one method twice) and keeps the roots themselves
      in the order the author's `z:` put them;
    * ``z``, then document order as the stable-sort tiebreak, exactly as before.

    Device-independent, because every part of it is -- which is what lets
    :meth:`Face.draw_order` and :class:`wfb.layout.Resolver` share it and stay
    in step (`tests/test_static.py` pins the two together).
    """
    z = element.z if element.z is not None else 0
    if element.static_root is None:
        return (1, 0, z)
    return (0, element.static_rank if element.static_rank is not None else 0, z)


def draw_order(elements: list[Element]) -> list[Element]:
    """The flattened list of elements that actually paint, in drawing order.

    Shared by :meth:`Face.draw_order` and :class:`wfb.layout.Resolver` through
    :func:`draw_sort_key`.
    """
    drawn = [e for e in walk_elements(elements) if e.kind != "group"]
    return sorted(drawn, key=draw_sort_key)


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


def config_field(name: str) -> str:
    """The view field a `config:` axis is cached in (``_configAccentColor``).

    Module-level rather than only a `ConfigColor` property because
    `Builder._build_scope` has to name the field for an axis that was
    *rejected* -- there is no `ConfigColor` for one of those, and deriving it
    a second time inline would be the same kind of duplicated symbol
    derivation `element_const_prefix`/`element_method_name` were moved here to
    stop (a mismatch between two copies is a `Redefinition` from `monkeyc`
    pointing at a generated line number).
    """
    return "_config" + _pascal(name)


def config_data_ids(face: "Face") -> dict[str, int]:
    """`config: data:` slot name -> the `<complication id="N">` this slot is
    emitted under, 1-based in declaration order (`docs/research/probes/
    config-axes/watchface.xml` numbers from 1, following the SDK's own
    sample).  Module-level, and derived from `face.config_data` rather than
    stored on `ConfigDataSlot` itself, so `wfb.emit.resources.config_resource`
    (writing the ids into the resource) and `wfb.emit.monkeyc._emit_apply_config`
    (matching `ComplicationRef.uniqueIdentifier` back against them) cannot
    silently number the same design's slots two different ways.
    """
    return {name: index for index, name in enumerate(face.config_data, start=1)}


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


def complication_slot_icon_method(element_id: str) -> str:
    """The private method that resolves one `complication_slot`'s icon glyph
    from a `Complications.Type` (``iconForTopReading``).

    A generated method, not an inline mutable local, because Monkey C locals
    cannot be given an explicit ``as String?`` type (verified: "Invalid
    explicit typing of a local variable" from a real build) -- there is no
    way to declare a local that starts `null` and is later assigned a
    `String` without one. Returning through a function whose own signature
    declares `String?` sidesteps that entirely: the call site's local infers
    its type from the function's declared return type instead.  Only emitted
    for a slot that actually draws an icon (`icon_size:` set); reserved here
    regardless, the same way `static_group_method` is reserved for every
    `group` whether or not it ends up static, so a later edit adding
    `icon_size:` cannot make an existing id collide with itself.
    """
    return "iconFor" + _element_suffix(element_id)


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


def graph_series_field(element_id: str) -> str:
    """The view field holding a graph's cached series (``hrGraphSeries``)."""
    return _lower_first(_element_suffix(element_id)) + "Series"


def graph_min_field(element_id: str) -> str:
    """The view field holding a graph's auto-computed minimum, when
    `min_auto` is set -- unused, and not emitted, otherwise."""
    return _lower_first(_element_suffix(element_id)) + "Min"


def graph_max_field(element_id: str) -> str:
    return _lower_first(_element_suffix(element_id)) + "Max"


def graph_built_field(element_id: str) -> str:
    """The minute-of-last-rebuild field a graph checks every frame
    (``hrGraphBuiltAt``) -- see `runtime-lib/WfbSeries.mc`'s module docstring
    for why this is not the TTL cache this project deleted."""
    return _lower_first(_element_suffix(element_id)) + "BuiltAt"


def graph_rebuild_method(element_id: str) -> str:
    """The private method that recomputes one graph's series (``rebuildHrGraph``)."""
    return "rebuild" + _element_suffix(element_id)


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


def config_label_id(axis: str, index: int) -> str:
    """The `<string>` resource id a labelled `config:` choice is emitted
    under (`ConfigDataColor0`), referenced from `<color label="@Strings...">`.

    Keyed by axis and position rather than by the label text itself: two
    choices could share a label (unlikely, but nothing forbids it), and a
    position-derived id is what every other generated symbol in this project
    already does (`element_const_prefix` and friends) rather than hashing
    author text.
    """
    return f"Config{_pascal(axis)}{index}"


def config_style_label_id(index: int) -> str:
    """The `<string>` resource id a labelled `color_scheme:` entry's Styles
    label is emitted under (`ConfigStyle0`), referenced from `<style
    label="@Strings...">`.

    Keyed by position, the same reasoning `config_label_id` already gives:
    two schemes could share a label, and a position-derived id matches every
    other generated symbol in this project rather than hashing author text.
    """
    return f"ConfigStyle{index}"


def _offset_span(span: Span | None, text: str, offset: int) -> Span | None:
    """Shift a span to point inside the expression string, not just at its key."""
    if span is None:
        return None
    return Span(span.path, span.line, span.col + offset)
