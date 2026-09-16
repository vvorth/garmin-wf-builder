"""The IR's data model: module-level constants and every dataclass -- the
element tree (`Element` and its kind-specific subclasses), `Face` itself,
fonts, on-device config, and analog hands/patterns -- plus the tree/draw-order
helpers (`walk_elements`, `authored_draw_order`, `draw_sort_key`, `draw_order`,
`never_together`) that read that tree, and `_drawn_copies`, the pure
computation :meth:`PatternElement.drawn_indices` shares with
`wfb.ir.builder.Builder._build_pattern_element`.  The semantic pass that
builds a `Face` from YAML is :mod:`wfb.ir.builder`; nothing here validates
anything.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from .. import catalog, expr, icons, units
from ..diagnostics import Span
from ..palette import Color
from ..series import SeriesDef
from ..units import Angle, Length
from .naming import _pascal, config_field, font_resource_id

MODES = ("active", "low_power", "always_on")

#: `on_hold: auto` -- resolved later, once the element has a value binding to
#: resolve *from* (SPEC.md D3).  A plain string rather than a dedicated
#: sentinel object so it survives unchanged through `Element.on_hold`, typed
#: `str | None` -- and safe to compare against, because `"auto"` is not and
#: will not become a real `wfb.complications.TYPES` key (constant names are
#: SCREAMING_SNAKE_CASE lowercased, and Garmin's own type table has no
#: `COMPLICATION_TYPE_AUTO`).
HOLD_AUTO = "auto"

#: The Monkey C a pattern colour's `copy` compiles to: the index of the loop
#: `wfb.emit.monkeyc._emit_pattern` draws the copies in (`for (var i = 0; ...)`).
PATTERN_LOOP_INDEX = "i"

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
    #: The declared size, always a :class:`~wfb.units.Length`: `12px` is twelve
    #: pixels on every device, `18%r` is a fraction of each device's own minor
    #: radius.  Restricted to :data:`wfb.units.SIZE_UNITS` -- the same `px`/`%r`
    #: an `icon`'s `size:` allows, and for the same reason (the sheet is
    #: rasterised before any element is placed, so there is no parent box to
    #: take a `%` of and no font in scope to take a `pt` of).
    #:
    #: There used to be a second spelling, a bare number meaning em pixels on
    #: the *reference* device (the smallest target) scaled per device by a
    #: `scale:` flag.  Removed: `%r` is that same transparent scaling, spelled
    #: directly instead of through an unnamed reference screen, and `px` is
    #: what `scale: false` used to give.  `Builder._font_size` is where a bare
    #: number is now rejected, with the exact `%r` conversion.
    size: Length
    glyphs: str | None
    antialias: bool
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

    def pixel_size(self, minor_radius: float) -> int:
        """The nominal em size this font's sheet is rasterised at, on a device
        whose screen has this minor radius.  The size is always a `Length`
        now, so its own unit already says whether it is per-device -- there is
        no reference device to consult any more.
        """
        return units.pixel_size(self.size, minor_radius)


# --------------------------------------------------------------------------
# on-device configuration (ADR 0006 1, amended)


#: The runtime symbol that gates the whole feature -- a device without it
#: (fr955) still compiles every line below; it just never calls it.  Checked
#: with `Device.has_symbol`, never an API-level compare: fr955 reports 5.2.0,
#: above the editor's documented 5.1.0, and still has no editor at all
#: (CLAUDE.md constraint 6, and `docs/research/probes/watchface-config/`).
CONFIG_SYMBOL = "Toybox.Application.WatchFaceConfig.getSettings"


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
    picked on-device through a `config: style:` entry's `colors:`
    (docs/research/09 §3).

    A colour *scheme* is several colours moving together, and no native
    colour axis carries more than one colour, so a scheme rides **Styles** --
    the one axis Garmin gives no meaning to at all.  `colors` keeps the
    author's own declared order (a plain dict), which is cosmetic only: the
    generated `resolveStyle` assigns one field per role regardless of order.
    """

    name: str
    label: str | None
    #: role name -> colour, in declared order.  Every accepted scheme in one
    #: design shares an identical key set -- `Builder._build_color_scheme`
    #: rejects any that does not, before this is ever constructed for it.
    colors: dict[str, Color]
    span: Span | None = None


@dataclass(frozen=True)
class LayoutDecl:
    """One declared `layouts:` entry -- a named widget set (plan 02
    §12.1, §12.2).  Form A only: an author never writes
    membership on an element.

    By the time this reaches the IR, `wfb/desugar.py`'s `_layouts_block` has
    already folded this entry's own `static:`/`elements:` into two synthetic
    groups appended to the top-level `elements:`, found again here by their
    reserved id (`wfb.desugar.layout_ids`) and walked to set `Element.layout`
    (`Builder._assign_layouts`) -- so this carries little beyond the name
    itself and the entry's own `lint:`, consulted by a later phase's
    `unreachable-layout` (plan 02 §12.6): a layout has no element of its own
    to hang `lint:` on, so its own body is the suppression site, the same
    reasoning a `config: style:` entry's own `lint:` follows for
    `duplicate-style`.
    """

    name: str
    lint_allow: frozenset[str] = frozenset()
    lint_reason: str | None = None
    span: Span | None = None


@dataclass(frozen=True)
class StyleEntry:
    """One `config: style:` entry -- one line of the editor's Style list
    (plan 02 §4.1, §12.4).

    Every entry carries at least one of `layout`/`colors` (`Builder.
    _build_config_style` rejects one with neither), and either may be
    `None` -- a colour-only entry, a layout-only entry, or both.  Codegen for
    `layout` is Phase 3 (`resolveStyle` gains a `_configLayout = N;` line
    alongside the colour assignments, plan 02 §6.4); Phase 2 only resolves
    and validates it.
    """

    name: str
    label: str | None
    #: A declared `color_scheme:` name, bare (`dark`, not `color_scheme.
    #: dark` -- that qualifying form is for expressions, and there is
    #: exactly one thing `colors:` can name here, so it buys nothing).
    #: `None` for a layout-only entry.
    colors: str | None
    #: A declared `layouts:` name, bare, the same reasoning as `colors`.
    #: `None` for a colour-only entry, and always `None` when the design
    #: declares no `layouts:` at all.
    layout: str | None = None
    lint_allow: frozenset[str] = frozenset()
    lint_reason: str | None = None
    span: Span | None = None


@dataclass(frozen=True)
class ConfigStyle:
    """The `config: style:` axis -- an author-named, ordered set of entries
    riding Styles, the one axis Garmin gives no meaning to at all
    (docs/research/09 §3, ADR 0006 1's second amendment, plan 02).
    Replaces `config: colors:`/the old `ConfigColorAxis` outright (plan 02
    §12, decision 3) -- no shim, and `examples/config`/`enduro`/`dashboard`
    are migrated in the same change.

    Shaped differently from :class:`ConfigColor`/:class:`ConfigAxis` on
    purpose: entries are named by the *author*, not by the scheme (or,
    later, layout) they reference, so `default:` names an entry and "default
    must be one of choices" is an identity comparison on the entry name, not
    a scheme-name or colour-value one.  There is no `allow_any` -- Styles has
    no equivalent of the editor's own unrestricted picker.
    """

    #: The default entry's name -- a key into `entries`, by `StyleEntry.name`.
    default: str
    #: In `choices:` order -- also the order `<style id="N">` numbers entries
    #: from, and the order `resolveStyle` tests `style == N` in.
    entries: tuple[StyleEntry, ...]
    span: Span | None = None

    @property
    def default_entry(self) -> StyleEntry:
        return next(e for e in self.entries if e.name == self.default)

    def index(self, name: str) -> int:
        """This entry's `styleId` -- its position in `choices:` order."""
        return next(i for i, e in enumerate(self.entries) if e.name == name)


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
    #: Per-choice icon override (plan 03 §6.1/§6.2): `wfb.complications.
    #: TYPES` key -> `wfb.icons.SlotIcon`, or `None` for an explicit
    #: `icon: none` that removes any catalogue default for that type.  A type
    #: absent from this dict declared no override at all -- `.icons` falls
    #: back to `wfb.icons.COMPLICATION_ICON` for it.  Always empty when
    #: `choices: any` (there is no fixed choice list in the design for an
    #: override to attach to).
    icon_overrides: dict[str, "icons.SlotIcon | None"] = field(default_factory=dict)
    span: Span | None = None

    @property
    def allow_any(self) -> bool:
        return self.choices == "any"

    @property
    def field(self) -> str:
        """The generated view field this slot's chosen `Complications.Id` is
        cached in (`_configDataTop`)."""
        return config_field(f"data_{self.name}")

    @property
    def icons(self) -> dict[str, "icons.SlotIcon"]:
        """`wfb.complications.TYPES` key -> icon, for every choice that ends
        up with one -- the single resolution point plan 03 §6.2 asks for.

        Before this existed, `{name: icons.COMPLICATION_ICON[name] for name
        in slot.choices if name in icons.COMPLICATION_ICON}` was copied into
        `wfb.layout`, `wfb.emit.resources`, `wfb.emit.monkeyc` (twice) and
        `wfb.preview` -- five places that had to agree, by inspection, that
        they resolved a slot's icon the same way. This is now the one place.

        A per-choice override in `icon_overrides` wins outright over the
        catalogue default; an explicit `icon: none` override removes the
        entry rather than falling back to one. `choices: any` (**allowed
        together with `icon_size:` since 2026-09-13**, plan 03 §6.6 --
        previously rejected, see `wfb.ir.Builder._build_complication_slot`'s
        comment at the removed check for the superseded reasoning) resolves
        against the *whole* of `wfb.icons.COMPLICATION_ICON` -- every native
        type this compiler knows an icon for -- since there is no author
        `choices:` list to intersect against; a Connect IQ-app complication,
        or any native type a future SDK adds that this table does not yet
        know, simply is not a key here and draws no icon, the same
        "unmapped means text-only, not an error" contract every other
        unmapped type already has.
        """
        if self.allow_any:
            return {
                name: icons.SlotIcon(catalogue_name, icons.CATALOG[catalogue_name].codepoint)
                for name, catalogue_name in icons.COMPLICATION_ICON.items()
            }
        result: dict[str, icons.SlotIcon] = {}
        for name in self.choices:
            if name in self.icon_overrides:
                override = self.icon_overrides[name]
                if override is not None:
                    result[name] = override
                continue
            catalogue_name = icons.COMPLICATION_ICON.get(name)
            if catalogue_name is not None:
                result[name] = icons.SlotIcon(catalogue_name, icons.CATALOG[catalogue_name].codepoint)
        return result


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
    #: The declared `layouts:` name this element belongs to, or `None` for
    #: shared content drawn in every layout (plan 02
    #: §12.1).  Never set by the author directly -- there is no element-level
    #: membership key (form A only) -- but by `Builder._assign_layouts`,
    #: which walks the two synthetic groups `wfb/desugar.py`'s
    #: `_layouts_block` appended for each declared layout and stamps this on
    #: the group and every descendant, by id.  Read by :func:`draw_sort_key`
    #: (the layer rank: shared content draws below layout content) and, from
    #: Phase 3, by codegen's layout guards.
    layout: str | None = None
    #: `antialias:` as the author wrote it, or `None` to inherit -- from the
    #: enclosing group's own value, or from `Face.antialias` when there is
    #: none.  Accepted only on `group`, `shape`, `progress` and `icon`: `text`
    #: draws through a `fonts:` resource shared by every element that
    #: references it, so anti-aliasing cannot vary per element there
    #: (`Builder._reject_text_antialias`).
    antialias: bool | None = None
    #: The resolved value -- never `None` once `Builder._resolve_antialias`
    #: has run over the whole tree.  What every downstream stage reads: on
    #: `shape`/`progress` this is the flag for anti-aliased `Dc` primitive
    #: drawing (a later stage of this work, not emitted yet -- see
    #: docs/limitations.md); on `icon` it is threaded into
    #: `wfb.icons.font_key` and the baked sheet.
    #: On a `group` nothing reads it directly -- the field exists there only
    #: as the default source `_resolve_antialias` hands to the subtree.
    resolved_antialias: bool = False
    #: `min_1px:` as the author wrote it, or `None` to inherit -- from the
    #: enclosing group's own value, or from `Face.min_1px` when there is
    #: none.  Same shape as `antialias` above (`_resolve_inherited_flag`
    #: resolves both), one level deeper: a hand or pattern part may also
    #: declare its own (`HandPart.min_1px`).  Accepted only on `group`,
    #: `shape`, `progress`, `graph`, `hands` and `pattern` -- not `text`,
    #: `icon` or `complication_slot`, whose font size already floors at 1 px
    #: on its own path (`wfb.units.pixel_size`), no switch involved.
    min_1px: bool | None = None
    #: The resolved value -- never `None` once `Builder._resolve_min_1px` has
    #: run over the whole tree.  Read by `wfb.layout.Resolver` at every
    #: `_extent` call site this element owns, and handed down as the
    #: inherited default to a hand/pattern part's own `min_1px` (which has no
    #: `resolved_` twin of its own -- see `HandPart.min_1px`).
    resolved_min_1px: bool = False
    #: Plan 07: the placement box's horizontal/vertical edge (or centre) that
    #: sits at the point `at:` resolves to -- one rule, on the base class, so
    #: every kind of element carries it the same way (R1/R8). Every accepting
    #: kind reads anything but the default: `group`, `text` and a pattern's
    #: `shape: text` part since phase A; `shape` (rectangle/rounded_rectangle/
    #: ellipse/circle/arc -- not polygon/line), `progress` (both styles) and
    #: `graph` since phase B (2026-09-15); `icon` and `complication_slot`
    #: since phase C (same day); a hand or pattern `rectangle`/`circle` part
    #: since phase D (same day). The schema stays closed on every other kind
    #: (R2/R3). Read by `wfb.layout`'s `alignment_shift` (box-drawn
    #: kinds), `Resolver._justify` (glyph-drawn kinds -- `text`, `icon`, a
    #: pattern's `shape: text` part), or mirrored as runtime arithmetic in
    #: `wfb.emit.monkeyc._emit_complication_slot` (`complication_slot`'s own
    #: ADR 0004 exception) -- never more than one mechanism for the same kind.
    align: str = "center"
    vertical_align: str = "center"

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
    #: `align`/`vertical_align` (which horizontal/vertical edge of the
    #: group's own box sits at `at:`, or the centre) moved onto `Element`
    #: itself 2026-09-15 (plan 07 phase A) -- see the base class.  Children
    #: resolve against the box this produces.  Defaults reproduce today's
    #: always-centred behaviour byte-identically.

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
class HandPart:
    """One primitive of a hand, in the hand's own frame: origin = the axis,
    drawn pointing at 12 o'clock (plan 04 §5.1, §5.2).  `at`/`to`/`points`
    positions have no `anchor` -- the schema's `handPosition` never accepts
    one, so the axis is the only reference point a part's coordinates can be
    measured from (R4).
    """

    shape: str = "polygon"
    #: `polygon` only: 3-64 vertices, each measured from the axis.
    points: list[Position] = field(default_factory=list)
    #: `rectangle`/`line`/`circle`: the part's own centre/start, default the axis.
    at: Position = field(default_factory=Position)
    size: Size = field(default_factory=Size)
    #: `line` only: the end point.
    to: Position | None = None
    thickness: Length | None = None
    radius: Length | None = None
    filled: bool = True
    #: Always set once built -- the part's own `color:`, or its hand's
    #: default: "a part left with no colour is an error" (§5.1), so by the
    #: time a `HandPart` exists this is never `None`.
    color: Expression | None = None
    span: Span | None = None
    #: `arc` only (`type: pattern`'s template, plan 05 §5.2 -- a hand part
    #: rejects `arc` outright, so these stay `None` there).  Author degrees,
    #: same convention `Shape.start_angle`/`.sweep` use.
    start_angle: Angle | None = None
    sweep: Angle | None = None
    #: `type: pattern` template parts only (schema keeps `handPart` closed to
    #: it, `additionalProperties: false`) -- a boolean expression evaluated
    #: per copy, `copy` bound the same as in a colour: false hides this part
    #: for this copy only, other parts and copies unaffected (2026-09-15,
    #: "per-copy part visible:").  `None` when not authored, or when the
    #: condition folded to a build-time constant `true` -- there is nothing
    #: to gate, so `_build_hand_part` drops it rather than keep a no-op
    #: expression around.  A constant `false` is kept (not dropped): codegen
    #: emits no draw code for it, and the `dead-element` lint names it.
    visible: Expression | None = None
    #: `shape: text` template parts only (plan 06 §3 -- schema keeps
    #: `handPart` closed to `shape: text`, so a hand part never sets any of
    #: these).  `value:` compiled in the pattern's `copy`-bound scope; every
    #: `Ref` in it must be `copy` (`Builder._build_hand_part`).  Exactly one
    #: of `text_value`/`text_literal` is set once a text part reaches this
    #: dataclass -- the other stays `None`.
    text_value: Expression | None = None
    #: `text:` -- a fixed string, the same for every copy.
    text_literal: str | None = None
    #: `format:` -- the numeric format of a `text` element, applies to
    #: `text_value` only (rejected alongside `text_literal`).
    format: str | None = None
    font: str = "FONT_MEDIUM"
    font_is_custom: bool = False
    #: Read on `rectangle`/`circle` parts (plan 07 phase D, resolved at build
    #: time by `Resolver._resolve_hand_part` before rounding -- mechanism
    #: (a), the same shift `wfb.layout.alignment_shift` gives every box-drawn
    #: kind) and on `shape: text` parts (plan 06 §3, mechanism (b): the
    #: anchor turns/steps with the copy, but the glyphs stay upright, unlike
    #: a rectangle/circle part's box, which turns with the part).  `_check_
    #: hand_part_keys` rejects both keys on `polygon`, `line` and (pattern
    #: only) `arc`, with the reason (`_HAND_PART_NO_ALIGNMENT_REASON`), so
    #: they are never set to anything but the default there.
    align: str = "center"
    vertical_align: str = "center"
    #: The host-rendered string for every copy index `0..count-1` -- set by
    #: `Builder._build_pattern_element` once the element's `count:` is known
    #: (a part alone does not know it).  Empty until then; empty forever on
    #: a non-text part.
    texts: tuple[str, ...] = ()
    #: `min_1px:` as authored, or `None` to inherit the owning `type: hands`/
    #: `type: pattern` element's own resolved value -- **authored only**,
    #: deliberately with no `resolved_` twin the way `Element.min_1px` gets
    #: one.  A `HandPart` lives inside a shared `HandSet` in `Face.hands`,
    #: which more than one `type: hands` element can place (`hands: <name>`
    #: names it) -- and two placements can resolve `min_1px` differently
    #: (one element's subtree on, the other's off), so a single value
    #: stamped once onto the part in the IR would be wrong for at least one
    #: of them.  `Resolver._resolve_hand_part` computes the effective value
    #: itself, per element instance, at layout time: `part.min_1px if
    #: part.min_1px is not None else <the owning element's resolved_min_1px>`.
    min_1px: bool | None = None


@dataclass
class Hand:
    """`hour:`/`minute:`/`second:` inside a `hands:` set -- a default colour
    for its parts, plus the parts themselves, in draw order (§5.1)."""

    parts: list[HandPart] = field(default_factory=list)
    #: The hand's own `color:`, before a part's own overrides it -- kept
    #: mainly for `docs`/introspection; every `HandPart.color` above is
    #: already the *effective* colour, so codegen never has to fall back to
    #: this itself.
    color: Expression | None = None


@dataclass
class HandSet:
    """One named `hands:` entry -- a shape, like a `fonts:` entry, not
    something drawn on its own (§5.1).  Placed on screen by a `type: hands`
    element naming it.
    """

    name: str
    hour: Hand | None = None
    minute: Hand | None = None
    second: Hand | None = None
    span: Span | None = None

    def hands(self) -> list[tuple[str, Hand]]:
        """The declared hands, in fixed draw order: hour, then minute, then
        second (§5.1) -- never author order, because the platform has no
        notion of drawing a minute hand under an hour hand on purpose."""
        return [(name, hand) for name, hand in
                (("hour", self.hour), ("minute", self.minute), ("second", self.second))
                if hand is not None]


@dataclass
class HandsElement(Element):
    """`type: hands` -- places a declared `hands:` set on screen, axis at
    `at:` (plan 04).  `_own_expressions` returns every effective part colour
    (already resolved at build time, `Builder._build_hands_element`) so
    permissions, the barrel, the read plan and the config-user lints pick
    them up exactly the way a shape's own `color:` does.
    """

    hands: str = ""
    #: `awake` (drawn only while awake), `never` (not drawn at all), or
    #: `None` when the set has no second hand at all -- there is nothing to
    #: gate.  `seconds: always` never reaches the IR: `wfb/validate.py`
    #: refuses it before the schema even runs (§5.6, §11).
    seconds: str | None = None
    #: Every effective colour (hand-level default, and each part's own
    #: override) this element's set uses, deduplicated in first-use order.
    colors: tuple[Expression, ...] = ()

    def _own_expressions(self) -> list[Expression]:
        return list(self.colors)


@dataclass
class PatternElement(Element):
    """`type: pattern` -- one template of 1-16 primitives, drawn repeatedly:
    turned about `at:` (`pattern: radial`) or stepped along `{dx, dy}`
    (`pattern: linear`) (plan 05).  The template is authored exactly like a
    hand part (`Builder._build_hand_part`, parameterised by context), and
    the repeat itself is the one piece of layout arithmetic the *device*
    performs, the same bargain ADR 0004 already struck for hands -- `step_angle`/
    `start_angle` are plain device-independent degrees, already defaulted,
    so `wfb.layout` never has to ask "was `step:` written" again.
    """

    pattern: str = "radial"
    count: int = 1
    #: Radial only: `step:` as authored, or `360deg / count` when omitted --
    #: already resolved, so nothing downstream re-derives the default.
    step_angle: float = 0.0
    #: Radial only: `start:`, default `0deg`.
    start_angle: float = 0.0
    #: Linear only: `step: {dx, dy}` -- an ordinary `Position` used for its
    #: `dx`/`dy` alone (no anchor, no polar form reaches here).
    step: Position | None = None
    skip: tuple[int, ...] = ()
    skip_every: int | None = None
    parts: list[HandPart] = field(default_factory=list)
    #: The element's own `color:` -- the default every part without one of
    #: its own inherits, before overrides (mirrors `Hand.color`).
    color: Expression | None = None
    #: Every effective colour (the element default, and each part's own
    #: override) this pattern uses, deduplicated in first-use order --
    #: `HandsElement.colors`'s own precedent.
    colors: tuple[Expression, ...] = ()
    #: `when_absent: hide` as authored, or `None` (schema: `enum: ["hide"]`,
    #: the only value -- a pattern has no placeholder/fallback, see
    #: `Builder._check_pattern_absence`).  Required once any colour or part
    #: `visible:` reads a source that can be absent (2026-09-15); absence
    #: then hides the whole pattern, every copy and every part, because the
    #: reading is taken once per frame, before the loop.
    when_absent: str | None = None

    def drawn_indices(self) -> tuple[int, ...]:
        """Copy indices actually drawn, ascending: `0..count-1` minus `skip`
        and minus every multiple of `skip_every` (§5.1).  A pattern with
        nothing left to draw is a build error (`Builder._build_pattern_element`,
        which computes the same thing through :func:`_drawn_copies` before
        this element exists, to report an empty result), so this is never
        empty for an element that reached the IR."""
        return _drawn_copies(self.count, self.skip, self.skip_every)

    def _own_expressions(self) -> list[Expression]:
        out = list(self.colors)
        for part in self.parts:
            if part.visible is not None:
                out.append(part.visible)
            if part.text_value is not None:
                out.append(part.text_value)
        return out


@dataclass
class Text(Element):
    value: Expression | None = None
    literal: str | None = None
    format: str | None = None
    font: str = "FONT_MEDIUM"
    font_is_custom: bool = False
    color: Expression | None = None
    #: `align`/`vertical_align` moved onto `Element` 2026-09-15 (plan 07
    #: phase A) -- see the base class.
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
    would be silently wrong for another.  This element renders the value
    through `WfbComplications.formatValue` (`toString()`, except a Float or
    Double, which is rounded to three significant figures), plus whatever
    `label:`/`unit:` add.
    """

    #: The declared `config: data:` slot name this element shows (the part
    #: after `config.data.`), resolved and validated by
    #: `Builder._resolve_slot_reference`.
    slot: str = ""
    font: str = "FONT_SMALL"
    font_is_custom: bool = False
    #: Visual height of the icon chosen from the wearer's pick, or `None` to
    #: draw no icon at all.  Resolved on-device from `Complications.Id.
    #: getType()` through `slot.icons` (`wfb.ir.ConfigDataSlot.icons`,
    #: itself built from `wfb.icons.COMPLICATION_ICON` plus any per-choice
    #: override) -- see `wfb.emit.monkeyc._emit_complication_slot`.
    icon_size: Length | None = None
    color: Expression | None = None
    #: `left` (default) | `right` | `top` | `bottom` -- where the icon sits
    #: relative to the reading (plan 03 §6.1/§6.3).  Rejected, together with
    #: `icon_gap:`/`icon_color:`, when `icon_size:` is not declared at all
    #: (`Builder._build_complication_slot`) -- none of the three means
    #: anything without an icon to place, colour or space.
    icon_position: str = "left"
    #: Pixel/`%r` gap between icon and reading, or `None` for today's fixed
    #: `wfb.layout.COMPLICATION_SLOT_ICON_GAP` (4px).  Kept `None` rather
    #: than always resolving to that constant so a design that never
    #: mentions `icon_gap:` gets byte-identical generated code to before
    #: this key existed -- the literal `4` stays inline; only an *authored*
    #: gap becomes a per-device `Layout.<ID>_ICON_GAP` constant, the same
    #: "declared vs. resolved, and only when it matters" reasoning
    #: `wfb.icons.font_key` already applies to a font size.
    icon_gap: Length | None = None
    #: The icon's own colour, or `None` to share `color:` (today's only
    #: behaviour, and what an unauthored design keeps generating).  Must not
    #: be nullable, exactly like `color:` -- there is no `when_absent:` for
    #: either colour, only for the pulled reading.
    icon_color: Expression | None = None
    #: `none` (default) | `short` | `long` -- `Complication.shortLabel`/
    #: `.longLabel`, read alongside the value, never authored.
    label: str = "none"
    #: Append `Complication.unit`'s suffix (`WfbComplications.mc`'s
    #: `unitSuffix`) after the value.
    unit: bool = False
    #: `hide` (default) | `placeholder`.  Unlike every other element's
    #: `when_absent:`, "hide" here blanks only the *reading* and leaves the
    #: icon drawn: the icon says which metric the slot is pointed at, which
    #: is still true even on a frame the reading itself could not be pulled.
    when_absent: str = "hide"
    placeholder: str | None = None

    def _own_expressions(self) -> list[Expression]:
        return [e for e in (self.color, self.icon_color) if e]


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
    #: The top-level `min_1px:` default (plan 08) -- what a `group`, `shape`,
    #: `progress`, `graph`, `hands` or `pattern` element inherits when it
    #: declares no `min_1px:` of its own.  Already folded into every
    #: element's own `resolved_min_1px` by build time; kept here for the
    #: same "no need to re-derive it" reason `antialias` above is.  Defaults
    #: to `False`, which is also the switch's off position -- a face that
    #: never mentions `min_1px:` compiles to byte-identical output.
    min_1px: bool = False
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
    #: Declared `layouts:` names, in declaration order (plan 02
    #: §12.1).  Empty when the design declares no
    #: `layouts:` at all.  Every element's `layout` (when not `None`) is one
    #: of these names.
    layouts: tuple[str, ...] = ()
    #: `layouts:` entries, keyed by name -- each one's own `lint:`, consulted
    #: by a later phase's `unreachable-layout`.  Empty exactly when `layouts`
    #: is.
    layout_decls: dict[str, LayoutDecl] = field(default_factory=dict)
    #: The `config: style:` axis, or `None` when it was never declared (or
    #: was declared and rejected).  Unlike `config`, this is not a dict --
    #: there is exactly one Styles axis, not a table of them.
    config_style: ConfigStyle | None = None
    #: `config: data:` slots, keyed by name.  A third, independent way to
    #: turn on the whole on-device-config feature -- see `has_config`.
    config_data: dict[str, ConfigDataSlot] = field(default_factory=dict)
    #: `hands:` entries, keyed by name (plan 04).  Empty on a design with no
    #: analog hands, which is what keeps every existing golden file and
    #: generated project byte-identical.
    hands: dict[str, HandSet] = field(default_factory=dict)

    @property
    def has_config(self) -> bool:
        """Single on/off switch for the whole on-device-config feature.

        Three independent things can turn it on: a declared `accent_color:`/
        `data_color:` (`self.config`), a declared `config: style:` (`self.
        config_style`), or a declared `config: data:` (`self.
        config_data`).  Every emitter site that used to test `bool(face.
        config)` alone -- `needs_delegate`, the view's config fields/
        `applyConfig`/`onLayout`, the static-buffer repaint flag, the
        generated `<watchface-config>` resource, `check_config_support` --
        now goes through this instead, so a design declaring only
        `color_scheme:`/`config: style:`/`config: data:` (no colour axis at
        all) still gets a delegate, `applyConfig` and the generated resource.
        See CLAUDE.md's own "Integration risk" note on this task for why
        every site matters.
        """
        return bool(self.config) or self.config_style is not None or bool(self.config_data)

    def style_label(self, entry: "StyleEntry") -> str | None:
        """The label the generated `<style>` and (a later phase's) preview
        both show for one `config: style:` entry.

        An entry's own `label:` wins.  Failing that, an entry that names only
        a `colors:` scheme (no `layout:`) falls back to that scheme's own
        `label:`, which is what makes migrating a `config: colors:` block a
        pure re-spelling: the generated `<style label=...>` text does not
        move (plan 02 §12.4).  A layout-carrying
        entry gets no fallback, colour-only or not -- §12.4 restricts it to
        colours-only entries on purpose, since a scheme's own label was
        never written with a layout in mind.  The one place this fallback is
        computed -- every reader calls this rather than re-deriving it, so
        the two can never drift.
        """
        if entry.label is not None:
            return entry.label
        if entry.colors is not None and entry.layout is None:
            return self.color_scheme[entry.colors].label
        return None

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


def _drawn_copies(
    count: int, skip: tuple[int, ...], skip_every: int | None,
) -> tuple[int, ...]:
    """Copy indices actually drawn, ascending: `0..count-1` minus `skip` and
    minus every multiple of `skip_every` (§5.1) -- the pure computation
    :meth:`PatternElement.drawn_indices` and `Builder._build_pattern_element`
    (which needs the answer before the element exists, to report an empty
    result as a build error) share.
    """
    return tuple(
        i for i in range(count)
        if i not in skip and (skip_every is None or i % skip_every != 0)
    )


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
    """Draw order as the author wrote it: layer, then document order
    stable-sorted by ``z``.

    This is draw order *before* the static hoist.  Nothing draws in it -- it
    exists so :func:`wfb.lint.check_static_overlap` can say which pairs of
    elements the hoist swapped, and so :meth:`Builder._apply_static` can rank
    the static roots by where the author actually put them rather than by
    where they happen to appear in the document.  Sorted by layer first
    (shared content, then layout content -- plan 02
    §12.3) so the *fixed* layer rule is never itself reported as something
    the hoist swapped: a layout element with a low `z:` sorting after a
    shared element with a high one is the rule working as designed, not a
    surprise `check_static_overlap` should flag.
    """
    drawn = [e for e in walk_elements(elements) if e.kind != "group"]
    return sorted(drawn, key=lambda e: (
        0 if e.layout is None else 1,
        e.z if e.z is not None else 0,
    ))


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

    Four ranks, in order (plan 02 §12.3):

    * ``0`` for static content, ``1`` for everything else -- the hoist itself;
    * the **layer** rank ``L`` -- ``0`` for shared content, ``1`` for layout
      content -- so layout content always draws above shared content, within
      each of the two buffers this and the rank above already split it into.
      With ``L = 0`` everywhere (a design with no `layouts:`), this changes
      nothing: every existing golden file and generated project is
      byte-identical;
    * ``static_rank``, the position of the element's own root in the authored
      order, which keeps each root's members one unbroken run (the emitter
      writes one ``drawStatic<Id>`` per root and calls each once, so two roots
      interleaving would emit one method twice) and keeps the roots themselves
      in the order the author's `z:` put them -- ``0`` for non-static content,
      where it plays no role;
    * ``z``, then document order as the stable-sort tiebreak, exactly as before.

    Device-independent, because every part of it is -- which is what lets
    :meth:`Face.draw_order` and :class:`wfb.layout.Resolver` share it and stay
    in step (`tests/test_static.py` pins the two together).
    """
    layer = 0 if element.layout is None else 1
    z = element.z if element.z is not None else 0
    if element.static_root is None:
        return (1, layer, 0, z)
    return (0, layer, element.static_rank if element.static_rank is not None else 0, z)


def draw_order(elements: list[Element]) -> list[Element]:
    """The flattened list of elements that actually paint, in drawing order.

    Shared by :meth:`Face.draw_order` and :class:`wfb.layout.Resolver` through
    :func:`draw_sort_key`.
    """
    drawn = [e for e in walk_elements(elements) if e.kind != "group"]
    return sorted(drawn, key=draw_sort_key)


def never_together(a: Element, b: Element) -> bool:
    """True only when `a` and `b` can never be on screen at the same time
    because they belong to different layouts (plan 02
    §12.1): "two elements are never on screen together exactly when both
    have a layout and the two layouts differ."  Shared content (`layout is
    None`) is on screen in every layout, so it is never exempted this way --
    only a *pair of layout elements*, and only when their layouts disagree.

    The one place this question is asked -- every pairwise "are these ever
    on screen together" lint check (`hold-overlap`, `static-overlap`) calls
    this rather than open-coding the `is not None and is not None and !=`
    it would otherwise repeat at each call site.
    """
    return a.layout is not None and b.layout is not None and a.layout != b.layout
