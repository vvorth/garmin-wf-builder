"""The IR's data model: module-level constants and every dataclass -- the
element tree (`Element` and its kind-specific subclasses), `Face` itself,
fonts, on-device config, and analog hands/patterns -- plus the tree/draw-order
helpers (`walk_elements`, `authored_draw_order`, `draw_sort_key`, `draw_order`,
`never_together`) that read that tree, and `drawn_copies`, the pure
computation :meth:`PatternElement.drawn_indices` shares with
`wfb.kinds.pattern.PatternKind.build`.  The semantic pass that
builds a `Face` from YAML is :mod:`wfb.ir.builder`; nothing here validates
anything.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import ClassVar, Literal

from .. import catalog, expr, icons, units
from ..diagnostics import Span
from ..palette import Color
from ..series import SeriesDef
from ..units import Angle, Length
from .naming import _pascal, config_field, font_resource_id

#: `always_on` was removed outright (plan 14 D3): the AMOLED sleep frame is
#: `aod:` now, not a mode to opt an element into. `modes:` means only the two
#: MIP partial-update modes.
MODES = ("active", "low_power")

#: `Element.bound_expressions()` role tags (plan 19 A2): what a compiled
#: expression *is*, not just that it exists.  Each is read by exactly the
#: downstream logic named on it, so a role is added here once, not
#: re-derived per reader:
#:
#: * `ROLE_VALUE` -- `Text.value`, `Progress.value`, `IconElement.value_for`.
#:   `Element.VALUE_ROLES` (a per-kind subset of the roles below) is what a
#:   `when_absent:` policy actually governs (`ReadPlan._value_expressions`);
#:   `Builder._hold_auto_sources` reads every `ROLE_VALUE` expression
#:   directly, regardless of `VALUE_ROLES` -- the two ask different
#:   questions (root docs, `docs/lore/codegen.md`) and only happen to share
#:   a tag for "the expression this element is about".
#: * `ROLE_MAX`/`ROLE_MIN` -- `Progress.maximum`, `Graph.max`/`Graph.min`.
#: * `ROLE_FALLBACK` -- a `when_absent: fallback` substitute.
#: * `ROLE_COLOR`/`ROLE_TRACK_COLOR`/`ROLE_ICON_COLOR` -- any element's own
#:   `color:`/`track_color:`/`icon_color:`, and each colour folded into
#:   `HandsElement.colors`/`PatternElement.colors` (tagged `ROLE_COLOR`).
#: * `ROLE_OUTLINE_COLOR` -- `Text.outline.color`.
#: * `ROLE_UNIT_LABEL` -- `Text.unit_label`, what `format:`'s `{unit}` shows.
#: * `ROLE_PART_VISIBLE`/`ROLE_PART_TEXT` -- a pattern part's own
#:   `visible:`/`text_value`.
#: * `ROLE_VISIBLE` -- `Element.visible`, appended by `bound_expressions()`
#:   itself rather than by any `_own_roles()`, so every subclass states only
#:   its own kind-specific roles.
ROLE_VALUE = "value"
ROLE_MAX = "max"
ROLE_MIN = "min"
ROLE_FALLBACK = "fallback"
ROLE_COLOR = "color"
ROLE_TRACK_COLOR = "track_color"
ROLE_ICON_COLOR = "icon_color"
ROLE_OUTLINE_COLOR = "outline_color"
ROLE_UNIT_LABEL = "unit_label"
ROLE_PART_VISIBLE = "part_visible"
ROLE_PART_TEXT = "part_text"
ROLE_VISIBLE = "visible"

#: `on_hold: auto` -- resolved once the element has a value binding to
#: resolve from (`Builder._resolve_hold_auto`).  A plain string, so it fits
#: `Element.on_hold: str | None`; Garmin has no `COMPLICATION_TYPE_AUTO`, so
#: it can never collide with a real `wfb.complications.TYPES` key.
HOLD_AUTO = "auto"

#: The Monkey C a pattern colour's `copy` compiles to: the index of the loop
#: `wfb.kinds.pattern.PatternKind.emit_draw` draws the copies in (`for (var i = 0; ...)`).
PATTERN_LOOP_INDEX = "i"

#: `Dc.fillPolygon`'s own 64-point limit, already recorded for `shape:
#: polygon` -- a filled graph closes its outline with two extra corners, so
#: the usable sample count is 62, not 64 (`docs/research/probes/graph-series/`).
GRAPH_AREA_MAX_SAMPLES = 62


#: `outline:`'s cap (plan 15 D6): every offset set research 14 measured
#: (`docs/research/14-stamped-ring-text.md` §1, §4.1) stops at r=3.
#: `Builder.build_outline` enforces it with an error citing that evidence.
MAX_OUTLINE_WIDTH = 3

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
    ast: expr.Node | None = None

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
        if not isinstance(node.right.value, (int, float)):
            return 1.0
        factor = float(node.right.value)
        if factor == 0:
            return 1.0
        return (1.0 / factor) if node.op == "/" else factor

    @property
    def is_constant(self) -> bool:
        return self.constant is not None


@dataclass
class FontSpec:
    """One `fonts:` entry -- a **baked** bitmap sheet (`source:`) or a
    **vector** device-resident face (`face:`, plan 11).  The two are
    mutually exclusive and jointly required (`schema/wfb-face-1.schema.json`
    `$defs/font`'s own `oneOf`), so exactly one of `source`/`face` is set on
    any `FontSpec` that reaches the IR -- see :attr:`is_baked`/:attr:`is_vector`,
    which every downstream reader should test instead of `source is None`
    directly, so a third font kind (should one ever exist) only needs a
    third predicate, not an audit of every `is None` check in the compiler.
    """

    name: str
    #: The declared size: `12px` on every device, or `18%r` of each device's
    #: minor radius.  Restricted to :data:`wfb.units.SIZE_UNITS` -- a sheet is
    #: rasterised before any element is placed, so there is no box for `%`
    #: nor font for `pt` (`Builder._font_size`).  A vector font shares the
    #: rule, so :meth:`pixel_size` resolves both kinds the same way.
    size: Length
    span: Span | None
    #: A baked font's own TrueType/OpenType source path, or `None` for a
    #: vector font (:attr:`face` below).  Mutually exclusive with `face`.
    source: Path | None = None
    #: **Baked only.** `None` lets the compiler derive the glyph set from
    #: every string the design can render.
    glyphs: str | None = None
    #: **Baked only.** Bitmap fonts default to 1-bit to save runtime RAM.
    antialias: bool = False
    #: **Baked only.** Bake every glyph at one shared advance, so a clock
    #: does not shift as its digits change (`wfb.fonts.bmfont.bake`).
    monospace: bool = False
    #: **Baked only.** Where a glyph's ink sits inside that shared cell.
    #: Meaningless, and therefore an error, without :attr:`monospace`.
    align: str = "center"
    #: **Vector only** (plan 11 §2.1): candidate device-resident face names,
    #: in author order.  Resolved per device to the one face it publishes
    #: (`wfb.availability.vector_font_face`) -- never Garmin's own runtime
    #: array fallback, which would leave the build unable to say which face
    #: renders, or to measure against it.
    face: tuple[str, ...] | None = None
    #: **Vector only.** `"error"` (the default) or `"hide"` -- what to do on
    #: a device that publishes none of the listed faces.  An element using
    #: this font may override it (`Text.if_unavailable`,
    #: `TextPart.if_unavailable`).
    if_unavailable: str | None = None

    @property
    def is_baked(self) -> bool:
        """A bitmap sheet rasterised from `source` at build time."""
        return self.source is not None

    @property
    def is_vector(self) -> bool:
        """A device-resident face reached through `Graphics.getVectorFont`,
        never rasterised by this compiler at all."""
        return self.face is not None

    @property
    def resource_id(self) -> str:
        """The baked font resource id -- meaningless on a vector font,
        which has no `<font>` resource; callers that care use
        :attr:`is_baked` to tell the two apart first."""
        return font_resource_id(self.name)

    def pixel_size(self, minor_radius: float) -> int:
        """The pixel height this font draws at, on a device whose screen has
        this minor radius -- for a baked font, the nominal em size its sheet
        is rasterised at; for a vector font, the `:size` handed to
        `Graphics.getVectorFont` directly, with nothing rasterised at build
        time at all.  Either way the size is a `Length`, so its own unit
        already says whether it is per-device, and this is the one place
        both font kinds resolve it.
        """
        return units.pixel_size(self.size, minor_radius)


@dataclass(frozen=True)
class Curve:
    """`curve:` on a `text` element (plan 11 §2.2) -- bends the text along a
    straight line (`style: angled`, `Dc.drawAngledText`) or around a circle
    (`style: radial`, `Dc.drawRadialText`).  Both calls refuse a resource
    font outright ("These APIs only support scalable fonts and do not
    support custom fonts loaded as resources", `$CIQ_SDK/doc/docs/
    Core_Topics/Graphics.html` §Scalable Fonts), so `Builder.build_curve`
    requires `font:` to name a `face:` (vector) `FontSpec`.  Also carried by
    a pattern's `shape: text` part (`TextPart.curve`).
    """

    #: `"angled"` | `"radial"`.
    style: str
    #: **Not one convention.**  For `radial`, a *position*: where around the
    #: circle the text starts, 12-o'clock-zero/clockwise-positive like every
    #: other angle in the format.  For `angled`, a *rotation* of the
    #: baseline from level, clockwise positive -- `0deg` is level text, not
    #: "pointing at 12", so the common case needs no `90deg`.
    #: `wfb.layout.garmin_curve_angle` is the one place either converts to
    #: Garmin's convention.
    angle: Angle
    #: `radial` only -- the circle's radius, an ordinary per-device layout
    #: length.  `None` on `angled` (`Builder._check_curve_keys` rejects it).
    radius: Length | None = None
    #: `radial` only -- `"clockwise"` (default) | `"counter_clockwise"`.
    direction: str | None = None


@dataclass(frozen=True)
class Outline:
    """`outline:` on a `text` element or a pattern's `shape: text` part
    (plan 15): the stamped ring research 14 measured.  `color` follows
    `color:`'s own grammar (`Builder.color_expression`); `width` is whole
    pixels, 1 to :data:`MAX_OUTLINE_WIDTH`.
    """

    color: Expression
    width: int = 2


@dataclass(frozen=True)
class AodOverride:
    """The resolved `aod:` override for one element (plan 14 §2-§3): element
    wins key by key over its nearest ancestor group's own `aod:`, which wins
    over the face's `aod: default:` -- `Builder._resolve_aod`.
    `Element.aod` is `None` when the element is hidden in AOD; a drawn
    element always gets one of these, every field `None` meaning "drawn,
    unrestyled".  Each value is resolved by the same machinery as the
    element's own property of that name.

    `hands`/`pattern`: `color`/`thickness` apply uniformly to every part
    (§5.1); there is no per-part override.
    """

    color: Expression | None = None
    track_color: Expression | None = None
    icon_color: Expression | None = None
    thickness: Length | None = None
    bar_width: Length | None = None
    filled: bool | None = None
    font: str | None = None
    font_is_custom: bool = False
    format: str | None = None
    #: `text` only: the AOD frame's own `outline:` ring, replacing the awake
    #: one whole -- `None` when unset (the awake ring carries over, see
    #: `aod_outline_choice`).  `outline_none` is an explicit `outline: none`.
    outline: Outline | None = None
    outline_none: bool = False
    #: The full "does this draw in AOD" gate: the element's own effective
    #: `visible:` AND the winning `aod: {visible: ...}`, or `None` when
    #: neither exists.  Read by the `aod-empty` lint and `wfb preview --aod`.
    visible: Expression | None = None
    #: Just the `aod: {visible: ...}` half of `visible` -- all codegen needs
    #: to add, since the element's method already checks its own `visible:`.
    visible_override: Expression | None = None


@dataclass(frozen=True)
class ColorRole:
    """One colour an element draws with, tagged with what role it plays
    (`Element.color_roles()`, plan 19 A2): `wfb.lint`'s palette-declaration
    and contrast checks read this instead of separately deciding "which
    colours does this element draw" (`_users_of`/`_contrast_subjects`/
    `_outlined_interiors` were three separate answers to that question
    before this).
    """

    #: The element id, or `"<id>.parts[<i>]"` for a pattern part -- the
    #: same label strings `wfb.lint._contrast_subjects` already prints.
    label: str
    expression: Expression
    #: `"ink"` | `"ring"` | `"track"` | `"icon"`.
    role: str
    #: A glyph's ink may not exactly match its backdrop on purpose -- an
    #: invisible glyph is a mistake -- where a filled shape's may (a
    #: punched-out hole, an "off" indicator).  `wfb.lint._contrast_subjects`'
    #: own `allow_backdrop_match`, inverted.
    is_glyph: bool
    #: `True` for a colour from the element's resolved `aod:` override
    #: rather than its awake one.
    aod: bool = False


def aod_color_choice(aod: AodOverride | None, key: str, dim_set: bool) -> tuple[str, Expression | None]:
    """The one decision behind an AOD-shown colour role (`color`/
    `track_color`/`icon_color`, or a `hands`/`pattern` part's own colour
    under the element-level override -- plan 14 §4.2/§4.5, plan 19 A1):
    this element's own `aod:` override for ``key`` wins if it set one;
    else, when the face has an `aod: {dim: ...}` at all, the awake colour
    is dimmed; else the awake colour is unchanged.

    Returns which of the three applies -- ``"override"``, ``"dim"`` or
    ``"awake"`` -- and, for ``"override"``, that override's own
    `Expression`.  This is the pure decision only: `wfb.preview.aod_color`
    (rendering the AOD frame, gated on `PreviewOptions.aod`) turns it into
    an RGB triple, and `wfb.emit.monkeyc.common.AodStyle.color`/
    `.part_color` (gated on whether this *build* emits AOD code at all)
    turn it into Monkey C -- each keeps its own gate and its own way of
    producing a colour, since one evaluates and the other prints code, but
    neither re-derives which of the three cases applies.
    """
    if aod is not None:
        override = getattr(aod, key)
        if override is not None:
            return "override", override
    if dim_set:
        return "dim", None
    return "awake", None


def aod_outline_choice(awake: Outline | None, aod: AodOverride | None,
                       dim_set: bool) -> tuple[Outline | None, str]:
    """The ring a `text` element draws in the AOD frame, and how its colour
    is chosen -- `aod_color_choice`'s rule, applied to the ring as a whole
    (an `aod: {outline: ...}` replaces the awake ring outright; it is never
    merged key by key with it).

    Returns ``(ring, choice)``: ``ring`` is `None` for no ring at all (none
    awake and none in `aod:`, or an explicit `aod: {outline: none}`);
    ``choice`` is ``"override"`` for the `aod:` block's own ring (its colour
    is the author's final word, never dimmed), else ``"dim"``/``"awake"``
    for the awake ring carried over, dimmed exactly like every other
    colour the AOD frame draws when the face has `aod: {dim: ...}`.
    `wfb.kinds.text` reads it for both codegen and `wfb preview --aod`.
    """
    if aod is not None and aod.outline_none:
        return None, "override"
    if aod is not None and aod.outline is not None:
        return aod.outline, "override"
    return awake, ("dim" if dim_set else "awake")


def disc_perimeter_offsets(radius: int) -> tuple[tuple[int, int], ...]:
    """The stamped-ring offset table for one ring width, in pixels
    (research 14 §1, plan 15 D3): every integer `(dx, dy)` on the outer
    shell of a disc of this radius, `(r-1)**2 < dx**2 + dy**2 <= r**2` --
    4/8/16 points at r=1/2/3.  The only offset set this format emits.

    The one source of truth for both `wfb.emit.monkeyc.layout_constants`
    (`OUTLINE_OFFSETS_<W>`) and `wfb.preview`'s stamp loop.
    """
    lo = (radius - 1) * (radius - 1)
    hi = radius * radius
    out: list[tuple[int, int]] = []
    for dx in range(-radius, radius + 1):
        for dy in range(-radius, radius + 1):
            d2 = dx * dx + dy * dy
            if lo < d2 <= hi:
                out.append((dx, dy))
    return tuple(out)


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
    """One declared `layouts:` entry -- a named widget set.  Form A only: an
    author never writes membership on an element.

    By the time this reaches the IR, `wfb/desugar.py`'s `_layouts_block` has
    already folded this entry's own `static:`/`elements:` into two synthetic
    groups appended to the top-level `elements:`, found again here by their
    reserved id (`wfb.desugar.layout_ids`) and walked to set `Element.layout`
    (`Builder._assign_layouts`) -- so this carries little beyond the name
    itself and the entry's own `lint:`, consulted by `unreachable-layout`: a
    layout has no element of its own to hang `lint:` on, so its own body is
    the suppression site, the same reasoning a `config: style:` entry's own
    `lint:` follows for `duplicate-style`.
    """

    name: str
    lint_allow: frozenset[str] = frozenset()
    lint_reason: str | None = None
    span: Span | None = None


@dataclass(frozen=True)
class StyleEntry:
    """One `config: style:` entry -- one line of the editor's Style list.

    Every entry carries at least one of `layout`/`colors` (`Builder.
    _build_config_style` rejects one with neither), and either may be
    `None` -- a colour-only entry, a layout-only entry, or both.  A
    layout-carrying entry makes `resolveStyle` set `_configLayout` alongside
    the colour assignments; a colour-only entry emits no such line.
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
    (docs/research/09 §3, ADR 0006 1's amendment).  `config: colors:` is not
    a key; the schema rejects it.

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
    #: Per-choice icon override: `wfb.complications.TYPES` key ->
    #: `wfb.icons.SlotIcon`, or `None` for an explicit
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
        up with one -- the single resolution point `wfb.layout`,
        `wfb.emit.resources`, `wfb.emit.monkeyc` and `wfb.preview` all read
        instead of each resolving a slot's icon its own way.

        A per-choice override in `icon_overrides` wins outright over the
        catalogue default; an explicit `icon: none` override removes the
        entry rather than falling back to one. `choices: any` (allowed
        together with `icon_size:`) resolves against the *whole* of
        `wfb.icons.COMPLICATION_ICON` -- every native type this compiler
        knows an icon for -- since there is no author `choices:` list to
        intersect against; a Connect IQ-app complication, or any native type
        a future SDK adds that this table does not yet know, simply is not a
        key here and draws no icon, the same "unmapped means text-only, not
        an error" contract every other unmapped type already has.
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
    #: The `bound_expressions()` roles a `when_absent:` policy on this kind
    #: governs (plan 19 A2) -- `{ROLE_VALUE}` for `Text`, `{ROLE_VALUE,
    #: ROLE_MAX}` for `Progress`, empty for every other kind, which has no
    #: `when_absent:` field at all.  `ReadPlan._value_expressions` reads
    #: this directly; `Builder._hold_auto_sources` does not (see
    #: `ROLE_VALUE`'s own docstring for why the two differ).
    VALUE_ROLES: ClassVar[frozenset[str]] = frozenset()

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
    #: all.  **Absent means hidden** (no `when_absent:` applies).  A group's
    #: is conjoined into every descendant's own (`Builder.push_visible`),
    #: since a group draws nothing itself; the copy left on the group is what
    #: the `dead-element` lint reports against.
    visible: Expression | None = None
    #: `static: true` as the author wrote it -- this element is the *root* of a
    #: static subtree, drawn once into an offscreen buffer and blitted every
    #: frame afterwards.  On a `group` it covers the subtree; on a leaf it is a
    #: subtree of one.
    static: bool = False
    #: The id of the static root this element belongs to, itself included, or
    #: None.  Set by `Builder._apply_static`: once layout flattens the tree,
    #: the emitter still needs to know which buffer draws each element.
    static_root: str | None = None
    #: Where this element's static root sits in the *authored* draw order,
    #: or None outside a static subtree (`Builder._rank_static`).  Read only
    #: by :func:`draw_sort_key`, to keep each root's members one run.
    static_rank: int | None = None
    #: The declared `layouts:` name this element belongs to, or `None` for
    #: shared content.  Stamped by `Builder._assign_layouts` (there is no
    #: element-level membership key); read by :func:`draw_sort_key` and by
    #: codegen's layout guards.
    layout: str | None = None
    #: Inherited boolean flags: `<key>` is what the author wrote (`None` =
    #: inherit from the enclosing group, or the face default), and
    #: `resolved_<key>` the answer `Builder._resolve_inherited_flag` stamps
    #: on every element.  `antialias:` is accepted on `group`, `shape`,
    #: `progress` and `icon` (a `text` shares its `fonts:` resource, so it
    #: cannot vary per element -- `wfb.kinds.text._reject_text_antialias`).
    antialias: bool | None = None
    resolved_antialias: bool = False
    #: `min_1px:` is accepted on `group`, `shape`, `progress`, `graph`,
    #: `hands` and `pattern`; a hand/pattern part may carry its own
    #: (`HandPart.min_1px`, which inherits `resolved_min_1px`).
    min_1px: bool | None = None
    resolved_min_1px: bool = False
    #: The placement box's edge (or centre) that sits at `at:`.  The schema
    #: decides which kinds accept it; `wfb.layout` applies it through
    #: `alignment_shift` (box-drawn kinds) or `Resolver.justify` (glyph-drawn
    #: kinds), and a `complication_slot` mirrors it at runtime.
    align: str = "center"
    vertical_align: str = "center"
    #: `aod:` as written on this element alone (`Builder._build_aod_authored`):
    #: `None` for none or `hide` (see `aod_own_hide`), else the parsed dict
    #: (`{}` for `show`).  Read by `Builder._resolve_aod`, and by the
    #: `aod-unreachable` lint, which needs what was written, not the result.
    aod_own: dict[str, object] | None = None
    #: `aod: hide` written on this element; sticky for every descendant.
    aod_own_hide: bool = False
    #: An *ancestor* wrote `aod: hide` (for `aod-unreachable`).
    aod_ancestor_hidden: bool = False
    #: The resolved override, or `None` when this element does not draw in
    #: AOD (`Builder._resolve_aod`).  Every downstream consumer reads this
    #: and never re-walks the ancestry.
    aod: "AodOverride | None" = None

    @property
    def symbol(self) -> str:
        """The stable Monkey C symbol derived from the element id (ADR 0003)."""
        return _pascal(self.id)

    def children(self) -> list["Element"]:
        return []

    def bound_expressions(self) -> list[tuple[str, Expression]]:
        """Every compiled expression on this element, tagged with its role
        (plan 19 A2), `visible:` included.

        Kind-specific roles come from :meth:`_own_roles`; this wrapper
        appends `(ROLE_VISIBLE, visible)` itself, so a subclass only ever
        states its own kind-specific roles, and so permission derivation,
        barrel collection and the read plan pick a visibility binding up
        for free, exactly as they do a conditional colour.
        """
        out = self._own_roles()
        if self.visible is not None:
            out.append((ROLE_VISIBLE, self.visible))
        return out

    def expressions(self) -> list[Expression]:
        """Every compiled expression on this element, `visible:` included --
        :meth:`bound_expressions` with the role dropped.  Kept as its own
        method since most callers (permission derivation, barrel
        collection) want the plain list, not what each expression is."""
        return [expression for _, expression in self.bound_expressions()]

    def _own_roles(self) -> list[tuple[str, Expression]]:
        return []

    def color_roles(self) -> list["ColorRole"]:
        """Every colour this element draws with, one :class:`ColorRole` each
        (plan 19 A2): its own ink/track/icon colours, a `Text`'s outline
        ring, and its resolved `aod:` override's colours -- in that order.
        `wfb.lint`'s palette-declaration and contrast checks read this
        instead of separately deciding "which colours does this element
        draw" (`_users_of`/`_contrast_subjects`/`_outlined_interiors` were
        three separate answers to that question before this).

        Generic over every kind whose colours are plain fields
        (`Shape`/`Text`/`Progress`/`IconElement`/`ComplicationSlot`/`Graph`,
        and `Group`, which has none): `getattr` covers the gap between
        kinds rather than an `isinstance` ladder.  `HandsElement`/
        `PatternElement` override this outright -- neither has a plain
        `color:` a generic reader could find; their effective colours live
        on `.colors`/`.parts` instead (`wfb.ir.builder.hands.HandParts._build_hand`/
        `wfb.kinds.pattern.PatternKind.build`).
        """
        is_glyph = self.kind != "shape"
        out: list[ColorRole] = []
        color = getattr(self, "color", None)
        if color is not None:
            out.append(ColorRole(self.id, color, "ink", is_glyph))
        track_color = getattr(self, "track_color", None)
        if track_color is not None:
            out.append(ColorRole(self.id, track_color, "track", is_glyph))
        icon_color = getattr(self, "icon_color", None)
        if icon_color is not None:
            out.append(ColorRole(self.id, icon_color, "icon", is_glyph))
        outline = getattr(self, "outline", None)
        if outline is not None:
            out.append(ColorRole(self.id, outline.color, "ring", is_glyph))
        if self.aod is not None:
            for field_name, role in (
                ("color", "ink"), ("track_color", "track"), ("icon_color", "icon"),
            ):
                override = getattr(self.aod, field_name)
                if override is not None:
                    out.append(ColorRole(self.id, override, role, is_glyph, aod=True))
            if self.aod.outline is not None:
                out.append(ColorRole(self.id, self.aod.outline.color, "ring", is_glyph, aod=True))
        return out


@dataclass
class Group(Element):
    size: Size = field(default_factory=Size)
    items: list[Element] = field(default_factory=list)
    #: `align`/`vertical_align`, inherited from `Element`, pick which
    #: horizontal/vertical edge of the group's own box sits at `at:` (or the
    #: centre, the default).  Children resolve against the box this
    #: produces.

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

    def _own_roles(self) -> list[tuple[str, Expression]]:
        return [(ROLE_COLOR, e) for e in (self.color,) if e]


@dataclass
class HandPart:
    """One primitive of a hand, or of a `type: pattern` template, in its own
    frame: origin = the axis (or the pattern's `at:`), drawn pointing at 12
    o'clock.  Positions have no `anchor` -- the schema's `handPosition` never
    accepts one, so the origin is the only reference point a part's
    coordinates can be measured from.  One subclass per `shape:`
    (`Builder.build_hand_part`); ``shape`` names it.  `arc` and `text` are
    pattern-only (`HAND_PART_REJECTED_SHAPES`).
    """

    shape: ClassVar[str]
    #: Always set once built -- the part's own `color:`, or its hand's
    #: default: a part left with no colour is a build error, so by the time
    #: a `HandPart` exists this is never `None`.
    color: Expression | None = None
    span: Span | None = None
    #: Pattern parts only -- a boolean evaluated per copy (`copy` in scope):
    #: false hides this part for this copy only.  `None` when not authored
    #: or constant `true`; a constant `false` is kept, so codegen emits
    #: nothing for it and the `dead-element` lint names it.
    visible: Expression | None = None
    #: `min_1px:` as authored, or `None` to inherit.  Deliberately no
    #: `resolved_` twin: one `HandSet` can be placed by several `type: hands`
    #: elements that resolve `min_1px` differently, so
    #: `Resolver._resolve_hand_part` resolves it per placement.
    min_1px: bool | None = None


@dataclass
class PolygonPart(HandPart):
    shape: ClassVar[Literal["polygon"]] = "polygon"
    #: 3-64 vertices, each measured from the origin.
    points: list[Position] = field(default_factory=list)
    #: Always `True`: `filled: false` is refused (no `drawPolygon`).
    filled: bool = True


@dataclass
class RectanglePart(HandPart):
    shape: ClassVar[Literal["rectangle"]] = "rectangle"
    #: The centre, default the origin; `align:`/`vertical_align:` move the
    #: `size:` box off it (`Resolver._hand_part_geometry`).
    at: Position = field(default_factory=Position)
    size: Size = field(default_factory=Size)
    #: Always `True`: a rectangle part becomes a polygon at build time.
    filled: bool = True
    align: str = "center"
    vertical_align: str = "center"


@dataclass
class LinePart(HandPart):
    shape: ClassVar[Literal["line"]] = "line"
    at: Position = field(default_factory=Position)
    #: The end point.
    to: Position | None = None
    thickness: Length | None = None


@dataclass
class CirclePart(HandPart):
    shape: ClassVar[Literal["circle"]] = "circle"
    at: Position = field(default_factory=Position)
    radius: Length | None = None
    #: Pen width, when not `filled`.
    thickness: Length | None = None
    filled: bool = True
    align: str = "center"
    vertical_align: str = "center"


@dataclass
class ArcPart(HandPart):
    """Pattern-only; always centred on the copy's own origin (no `at:`)."""

    shape: ClassVar[Literal["arc"]] = "arc"
    radius: Length | None = None
    thickness: Length | None = None
    #: Author degrees, same convention `Shape.start_angle`/`.sweep` use.
    start_angle: Angle | None = None
    sweep: Angle | None = None


@dataclass
class TextPart(HandPart):
    """Pattern-only (`Builder._build_text_part`): upright glyphs whose anchor
    turns (radial) or steps (linear) with the copy.  `value:` may read only
    `copy`; exactly one of `text_value`/`text_literal` is set."""

    shape: ClassVar[Literal["text"]] = "text"
    at: Position = field(default_factory=Position)
    text_value: Expression | None = None
    #: `text:` -- a fixed string, the same for every copy.
    text_literal: str | None = None
    #: `format:` -- the numeric format of a `text` element, applies to
    #: `text_value` only (rejected alongside `text_literal`).
    format: str | None = None
    font: str = "FONT_MEDIUM"
    font_is_custom: bool = False
    align: str = "center"
    vertical_align: str = "center"
    #: The host-rendered string for every copy index `0..count-1`, set by
    #: `wfb.kinds.pattern._render_pattern_texts` once `count:` is known.
    texts: tuple[str, ...] = ()
    #: `curve:` (vector font only), authored in the template's own local
    #: frame: a radial pattern's per-copy rotation composes with it
    #: downstream, so one angle serves every copy.
    curve: "Curve | None" = None
    #: Overrides the (vector) font's own `if_unavailable:`; `None` inherits.
    #: Per part, since each text part may name a different font.
    if_unavailable: str | None = None
    #: `outline:` -- `Text.outline`'s stamped ring, offset in screen space
    #: from this copy's already transformed anchor.  Its colour joins
    #: `PatternElement.colors`, so absence is policed for the whole pattern.
    outline: "Outline | None" = None


#: Any one hand, needle or pattern part: `part.shape == "text"` narrows it.
AnyHandPart = PolygonPart | RectanglePart | LinePart | CirclePart | ArcPart | TextPart


@dataclass
class Hand:
    """`hour:`/`minute:`/`second:` inside a `hands:` set -- a default colour
    for its parts, plus the parts themselves, in draw order."""

    parts: list[AnyHandPart] = field(default_factory=list)
    #: The hand's own `color:`, before a part's own overrides it -- kept
    #: mainly for `docs`/introspection; every `HandPart.color` above is
    #: already the *effective* colour, so codegen never has to fall back to
    #: this itself.
    color: Expression | None = None


@dataclass
class HandSet:
    """One named `hands:` entry -- a shape, like a `fonts:` entry, not
    something drawn on its own.  Placed on screen by a `type: hands`
    element naming it.
    """

    name: str
    hour: Hand | None = None
    minute: Hand | None = None
    second: Hand | None = None
    span: Span | None = None

    def hands(self) -> list[tuple[str, Hand]]:
        """The declared hands, in fixed draw order: hour, then minute, then
        second -- never author order, because the platform has no notion of
        drawing a minute hand under an hour hand on purpose."""
        return [(name, hand) for name, hand in
                (("hour", self.hour), ("minute", self.minute), ("second", self.second))
                if hand is not None]


@dataclass
class HandsElement(Element):
    """`type: hands` -- places a declared `hands:` set on screen, axis at
    `at:`.  `_own_roles` tags every effective part colour (already resolved
    at build time, `wfb.kinds.hands.HandsKind.build`) `ROLE_COLOR`, so
    permissions, the barrel, the read plan and the config-user lints pick
    them up exactly the way a shape's own `color:` does.
    """

    hands: str = ""
    #: `awake` (drawn only while awake), `never` (not drawn at all), or
    #: `None` when the set has no second hand at all -- there is nothing to
    #: gate.  `seconds: always` never reaches the IR: `wfb/validate.py`
    #: refuses it before the schema even runs.
    seconds: str | None = None
    #: Every effective colour (hand-level default, and each part's own
    #: override) this element's set uses, deduplicated in first-use order.
    colors: tuple[Expression, ...] = ()

    def _own_roles(self) -> list[tuple[str, Expression]]:
        return [(ROLE_COLOR, e) for e in self.colors]

    def color_roles(self) -> list[ColorRole]:
        """Every effective part colour, ink-labelled by this element's own
        id: the IR has no per-part structure for a `hands` set (unlike
        `PatternElement.parts`) -- hand sets live on `Face.hands`, keyed by
        name, not on the placing element -- so there is no finer label to
        give each colour than the element that draws them all.  A `hands`
        element accepts no `track_color:`/`icon_color:`/outline at all, so
        those roles never apply here; its resolved `aod:` override (`color`/
        `thickness` uniformly, plan 14 §5.1 -- no `track_color`/`icon_color`
        key even reaches this element's `AodOverride`) still does.
        """
        out = [ColorRole(self.id, e, "ink", False) for e in self.colors]
        if self.aod is not None and self.aod.color is not None:
            out.append(ColorRole(self.id, self.aod.color, "ink", False, aod=True))
        return out


@dataclass
class PatternElement(Element):
    """`type: pattern` -- one template of 1-16 primitives, drawn repeatedly:
    turned about `at:` (`pattern: radial`) or stepped along `{dx, dy}`
    (`pattern: linear`).  The template is authored like a hand part
    (`Builder.build_hand_part`); the repeat is layout arithmetic the device
    performs, as for hands (ADR 0004).  `step_angle`/`start_angle` are
    already-defaulted, device-independent degrees.
    """

    pattern: str = "radial"
    count: int = 1
    #: Radial only: `step:` as authored, or `360deg / count` when omitted --
    #: already resolved, so nothing downstream re-derives the default.
    step_angle: float = 0.0
    #: Radial only: `start:`, default `0deg`.
    start_angle: float = 0.0
    #: Linear and grid: `step: {dx, dy}` -- an ordinary `Position` used for
    #: its `dx`/`dy` alone (no anchor, no polar form reaches here); on a
    #: grid, `dx` is between columns and `dy` between rows.
    step: Position | None = None
    #: Grid only: copies per row; copy `i` is column `i % columns`, row
    #: `i // columns`.
    columns: int | None = None
    skip: tuple[int, ...] = ()
    skip_every: int | None = None
    parts: list[AnyHandPart] = field(default_factory=list)
    #: The element's own `color:` -- the default every part without one of
    #: its own inherits, before overrides (mirrors `Hand.color`).
    color: Expression | None = None
    #: Every effective colour (the element default, each part's own, and
    #: each part's `outline.color`), deduplicated in first-use order.
    colors: tuple[Expression, ...] = ()
    #: `when_absent: hide` as authored, or `None` (schema: `enum: ["hide"]`,
    #: the only value -- a pattern has no placeholder/fallback, see
    #: `wfb.kinds.pattern._check_pattern_absence`).  Required once any colour or part
    #: `visible:` reads a source that can be absent; absence then hides the
    #: whole pattern, every copy and every part, because the reading is
    #: taken once per frame, before the loop.
    when_absent: str | None = None

    def drawn_indices(self) -> tuple[int, ...]:
        """Copy indices actually drawn, ascending: `0..count-1` minus `skip`
        and minus every multiple of `skip_every`.  A pattern with
        nothing left to draw is a build error (`wfb.kinds.pattern.PatternKind.build`,
        which computes the same thing through :func:`drawn_copies` before
        this element exists, to report an empty result), so this is never
        empty for an element that reached the IR."""
        return drawn_copies(self.count, self.skip, self.skip_every)

    def _own_roles(self) -> list[tuple[str, Expression]]:
        out: list[tuple[str, Expression]] = [(ROLE_COLOR, e) for e in self.colors]
        for part in self.parts:
            if part.visible is not None:
                out.append((ROLE_PART_VISIBLE, part.visible))
            if part.shape == "text" and part.text_value is not None:
                out.append((ROLE_PART_TEXT, part.text_value))
        return out

    def color_roles(self) -> list[ColorRole]:
        """The element default (ink, label = the element id), then each
        part's own colour and, for a `shape: text` part, its `outline.color`
        ring (`TextPart.outline`; no other part shape has one). Yields the same *set* `.colors` above
        collects (`wfb.kinds.pattern.PatternKind.build`'s `dedup_append` calls: the
        default, then each part's already-effective colour, then each
        part's own outline colour) -- `part.color` is already the effective
        colour (the part's own, or this element's default when it declared
        none, `Builder.build_hand_part`), so nothing here re-derives it.

        Deliberately not what `wfb.lint._contrast_subjects`' pattern branch
        reads: that check judges only what a part actually paints with, so
        it stays on `placed.parts` directly rather than this -- the element
        default above is drawn by *some* part only when at least one part
        left `color:` unset, and folding it in here regardless would check
        a colour that may never reach the screen at all when every part
        overrides its own.
        """
        is_glyph = self.kind != "shape"
        out: list[ColorRole] = []
        if self.color is not None:
            out.append(ColorRole(self.id, self.color, "ink", is_glyph))
        for index, part in enumerate(self.parts):
            label = f"{self.id}.parts[{index}]"
            part_is_glyph = part.shape == "text"
            if part.color is not None:
                out.append(ColorRole(label, part.color, "ink", part_is_glyph))
            if part.shape == "text" and part.outline is not None:
                out.append(ColorRole(label, part.outline.color, "ring", part_is_glyph))
        if self.aod is not None and self.aod.color is not None:
            out.append(ColorRole(self.id, self.aod.color, "ink", is_glyph, aod=True))
        return out


@dataclass
class Text(Element):
    value: Expression | None = None
    literal: str | None = None
    format: str | None = None
    font: str = "FONT_MEDIUM"
    font_is_custom: bool = False
    color: Expression | None = None
    when_absent: str | None = None
    placeholder: str | None = None
    fallback: Expression | None = None
    #: `curve:`, or `None` for upright text; needs a `face:` (vector) font.
    curve: "Curve | None" = None
    #: Overrides a vector font's own `FontSpec.if_unavailable`; `None`
    #: inherits it.  Rejected on a baked or system font.
    if_unavailable: str | None = None
    #: `outline:` (plan 15), or `None` for a plain fill; wraps whichever
    #: draw call `curve:` selects.
    outline: "Outline | None" = None
    #: `units:` (`auto`/`metric`/`statute`), or `None`.  When set, `value`
    #: is already the converted expression (`wfb.conversion`), and the
    #: fields below describe its display.
    units: str | None = None
    #: The String expression `format:`'s `{unit}` renders ("km" or "mi").
    unit_label: Expression | None = None
    #: Every label `unit_label` can take, and the digits before the decimal
    #: point the converted value can reach -- for the overflow lint and a
    #: baked font's glyph subset.
    unit_labels: tuple[str, ...] = ()
    unit_digits: int | None = None

    #: `when_absent:` governs `value:` alone -- the same substitutable
    #: binding `ROLE_VALUE` tags below.
    VALUE_ROLES: ClassVar[frozenset[str]] = frozenset({ROLE_VALUE})

    def _own_roles(self) -> list[tuple[str, Expression]]:
        out = [(role, e) for role, e in (
            (ROLE_VALUE, self.value), (ROLE_COLOR, self.color), (ROLE_FALLBACK, self.fallback),
        ) if e]
        if self.outline is not None:
            out.append((ROLE_OUTLINE_COLOR, self.outline.color))
        if self.unit_label is not None:
            out.append((ROLE_UNIT_LABEL, self.unit_label))
        return out


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
    #: `style: needle` only: the needle's parts, authored like an analog
    #: hand's (pointing at 12, the axis at the origin), each with its
    #: effective colour -- its own, or the element's `color:`.
    needle: tuple["AnyHandPart", ...] = ()
    #: `style: segments` only: how many cells, and the space between two.
    count: int | None = None
    gap: Length | None = None
    #: `style: scale` only: `(to, colour)` zones along the track, `to` a
    #: fraction of the full scale, strictly increasing; and the value dot's
    #: radius (`None` for the track's own thickness or height).
    bands: tuple[tuple[float, Expression], ...] = ()
    pointer: Length | None = None

    @property
    def geometry(self) -> str:
        """What the track is: ``"arc"``, ``"bar"`` or ``"needle"``.
        `segments`/`scale` are whichever of an arc or a bar their keys
        describe (a `radius:` means an arc)."""
        if self.style in ("arc", "bar", "needle"):
            return self.style
        return "arc" if self.radius is not None else "bar"

    #: `when_absent:` governs the fraction `value:`/`maximum:` compute
    #: together -- one nullable reading is as absent as the other from the
    #: fraction's own point of view (`wfb.kinds.progress.ProgressKind.build`).
    VALUE_ROLES: ClassVar[frozenset[str]] = frozenset({ROLE_VALUE, ROLE_MAX})

    def _own_roles(self) -> list[tuple[str, Expression]]:
        out = [(role, e) for role, e in (
            (ROLE_VALUE, self.value), (ROLE_MAX, self.maximum),
            (ROLE_COLOR, self.color), (ROLE_TRACK_COLOR, self.track_color),
            (ROLE_FALLBACK, self.fallback),
        ) if e]
        # A needle part's own colour (never data: `Builder.owned_color`)
        # still has to reach permission derivation and the barrel scan.
        out.extend((ROLE_COLOR, part.color) for part in self.needle
                   if part.color is not None and part.color is not self.color)
        out.extend((ROLE_COLOR, color) for _, color in self.bands)
        return out

    def color_roles(self) -> list["ColorRole"]:
        """Every colour, a needle part's own (`<id>.needle[<i>]`) and a scale
        band's (`<id>.bands[<i>]`, a track colour) included."""
        out = super().color_roles()
        for index, part in enumerate(self.needle):
            if part.color is not None and part.color is not self.color:
                out.append(ColorRole(f"{self.id}.needle[{index}]", part.color, "ink", False))
        for index, (_, color) in enumerate(self.bands):
            out.append(ColorRole(f"{self.id}.bands[{index}]", color, "track", False))
        return out


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
    #: `wfb.icons.GARMIN_WEATHER_CONDITION_ICON`.
    value_for: Expression | None = None
    size: Length | None = None
    color: Expression | None = None

    @property
    def is_dynamic(self) -> bool:
        return self.value_for is not None

    def _own_roles(self) -> list[tuple[str, Expression]]:
        return [(role, e) for role, e in (
            (ROLE_COLOR, self.color), (ROLE_VALUE, self.value_for),
        ) if e]


@dataclass
class ComplicationSlot(Element):
    """`type: complication_slot` -- the element half of the native Data axis
    (docs/research/09-data-library-and-config-axes.md §4): draws whichever
    complication the wearer currently has this `slot:` pointed at.

    Not a `Text` variant and not a bound `value:` expression: which
    complication type is showing is the wearer's runtime choice, so there
    is no fixed source to bind at build time.  Everything drawn comes from a
    fresh `WfbComplications.valueOf(<slot field>)` pull every frame.  No
    `format:` (`wfb.kinds.complication_slot.ComplicationSlotKind.build` says why).
    """

    #: The declared `config: data:` slot name this element shows (the part
    #: after `config.data.`), resolved and validated by
    #: `wfb.kinds.complication_slot._resolve_slot_reference`.
    slot: str = ""
    font: str = "FONT_SMALL"
    font_is_custom: bool = False
    #: Visual height of the icon chosen from the wearer's pick
    #: (`ConfigDataSlot.icons`), or `None` to draw no icon.
    icon_size: Length | None = None
    color: Expression | None = None
    #: `left` (default) | `right` | `top` | `bottom` -- where the icon sits
    #: relative to the reading.  This, `icon_gap` and `icon_color` need
    #: `icon_size:`.
    icon_position: str = "left"
    #: Pixel/`%r` gap between icon and reading, or `None` for the fixed
    #: `wfb.layout.COMPLICATION_SLOT_ICON_GAP` -- kept `None` so only an
    #: authored gap becomes a per-device `Layout.<ID>_ICON_GAP` constant.
    icon_gap: Length | None = None
    #: The icon's own colour, or `None` to share `color:`.  Neither colour
    #: may be nullable: `when_absent:` governs only the pulled reading.
    icon_color: Expression | None = None
    #: `none` (default) | `short` | `long` -- `Complication.shortLabel`/
    #: `.longLabel`, read alongside the value, never authored.
    label: str = "none"
    #: Append `Complication.unit`'s suffix (`WfbComplications.mc`'s
    #: `unitSuffix`) after the value.
    unit: bool = False
    #: `hide` (default) | `placeholder`.  "hide" blanks only the reading and
    #: keeps the icon, which still says what the slot is pointed at.
    when_absent: str = "hide"
    placeholder: str | None = None

    def _own_roles(self) -> list[tuple[str, Expression]]:
        return [(role, e) for role, e in (
            (ROLE_COLOR, self.color), (ROLE_ICON_COLOR, self.icon_color),
        ) if e]


@dataclass
class Graph(Element):
    """`type: graph` -- a time series drawn as a line, a filled area or bars.

    Modelled on `Progress`: one element with a `style:` discriminator, because
    the *drawing* is what varies, not the acquisition. Unlike `Progress`,
    there is no single bound `value:`/`max:` pair -- `series:` names an entry
    in the :mod:`wfb.series` catalogue, and the actual samples are acquired
    and cached on-device (`runtime-lib/WfbSeries.mc`, rebuilt once a minute),
    never through the expression compiler. `color:`, `min:` and `max:` *are*
    ordinary bound expressions (`_own_roles` below), because a fixed
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
    #: many buckets `WfbSeries.binHeartRate` fills.  Deliberately not derived
    #: from the resolved pixel width: the generated view is shared by every
    #: target, so a per-device loop bound would be wrong on all but one.
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
    #: The build-time upper bound on samples drawn (`wfb.kinds.graph._graph_sample_count`):
    #: device-independent, so the `style: area` cap and a documented-maximum
    #: overrun are build errors.
    sample_count: int = 0

    def _own_roles(self) -> list[tuple[str, Expression]]:
        return [(role, e) for role, e in (
            (ROLE_COLOR, self.color), (ROLE_MIN, self.min), (ROLE_MAX, self.max),
        ) if e]


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
    #: The face-wide `antialias:`/`min_1px:` defaults -- already folded into
    #: every element's `resolved_*` (and `FontSpec.antialias`) by build time.
    antialias: bool = False
    min_1px: bool = False
    #: `config:` colour axes, keyed by name (`accent_color`/`data_color`).
    #: Test `has_config`, not this, for "is on-device config in use".
    config: dict[str, ConfigColor] = field(default_factory=dict)
    #: Accepted long-form `palette:` entries' labels, keyed by name.
    palette_labels: dict[str, str] = field(default_factory=dict)
    #: Accepted `color_scheme:` entries, keyed by name.
    color_scheme: dict[str, ColorScheme] = field(default_factory=dict)
    #: Declared `layouts:` names, in declaration order.  Empty when the
    #: design declares no `layouts:` at all.  Every element's `layout`
    #: (when not `None`) is one of these names.
    layouts: tuple[str, ...] = ()
    #: `layouts:` entries, keyed by name -- each one's own `lint:`, consulted
    #: by `unreachable-layout`.  Empty exactly when `layouts` is.
    layout_decls: dict[str, LayoutDecl] = field(default_factory=dict)
    #: The `config: style:` axis, or `None` when it was never declared (or
    #: was declared and rejected).  Unlike `config`, this is not a dict --
    #: there is exactly one Styles axis, not a table of them.
    config_style: ConfigStyle | None = None
    #: `config: data:` slots, keyed by name.  A third, independent way to
    #: turn on the whole on-device-config feature -- see `has_config`.
    config_data: dict[str, ConfigDataSlot] = field(default_factory=dict)
    #: `hands:` entries, keyed by name.
    hands: dict[str, HandSet] = field(default_factory=dict)
    #: Top-level `aod: default:` -- `True` for `hide` (the default).  Applies
    #: only where nothing along an element's ancestry wrote an `aod:`.
    aod_default_hide: bool = True
    #: `aod: lint:` -- suppresses a face-level AOD lint (`aod-empty`).
    aod_lint_allow: frozenset[str] = frozenset()
    aod_lint_reason: str | None = None
    #: `aod: dim:` luminance scale for the AOD frame (plan 14 §4.5); `None`
    #: for both "absent" and `dim: 1`, so the generated source is identical.
    aod_dim: float | None = None
    #: `aod: mask:` (plan 16) -- the moving 2x2 pixel mask over the AOD
    #: frame; on unless `mask: false`.
    aod_mask: bool = True

    @property
    def has_config(self) -> bool:
        """Single on/off switch for the whole on-device-config feature.

        Three independent things can turn it on: a declared `accent_color:`/
        `data_color:` (`self.config`), a declared `config: style:` (`self.
        config_style`), or a declared `config: data:` (`self.
        config_data`).  Every emitter site that cares -- `needs_delegate`,
        the view's config fields/`applyConfig`/`onLayout`, the static-buffer
        repaint flag, the generated `<watchface-config>` resource,
        `check_config_support` -- goes through this rather than testing
        `bool(face.config)` alone, so a design declaring only
        `color_scheme:`/`config: style:`/`config: data:` (no colour axis at
        all) still gets a delegate, `applyConfig` and the generated resource.
        """
        return bool(self.config) or self.config_style is not None or bool(self.config_data)

    def style_label(self, entry: "StyleEntry") -> str | None:
        """The label the generated `<style>` and preview both show for one
        `config: style:` entry.

        An entry's own `label:` wins.  Failing that, an entry that names only
        a `colors:` scheme (no `layout:`) falls back to that scheme's own
        `label:`.  A layout-carrying entry gets no fallback, colour-only or
        not -- a scheme's own label was never written with a layout in mind.
        The one place this fallback is computed -- every reader calls this
        rather than re-deriving it, so the two can never drift.
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


def drawn_copies(
    count: int, skip: tuple[int, ...], skip_every: int | None,
) -> tuple[int, ...]:
    """Copy indices actually drawn, ascending: `0..count-1` minus `skip` and
    minus every multiple of `skip_every` -- the pure computation
    :meth:`PatternElement.drawn_indices` and `wfb.kinds.pattern.PatternKind.build`
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
    (shared content, then layout content) so the *fixed* layer rule is
    never itself reported as something the hoist swapped: a layout element
    with a low `z:` sorting after a shared element with a high one is the
    rule working as designed, not a surprise `check_static_overlap` should
    flag.
    """
    drawn = [e for e in walk_elements(elements) if e.kind != "group"]
    return sorted(drawn, key=lambda e: (
        0 if e.layout is None else 1,
        e.z if e.z is not None else 0,
    ))


def draw_sort_key(element: Element) -> tuple[int, int, int, int]:
    """The sort key that puts an element in draw order, static content first.

    The static buffer is opaque and full-screen (`docs/research/probes/
    static-buffer/`), so its blit erases whatever was drawn under it.
    Static content must therefore *be* a contiguous prefix of draw order:
    this function makes it one, here, by sorting, rather than requiring the
    author to have written it that way. The only thing the author is told
    is what changed -- `warning[static-overlap]`, on the pairs whose
    relative order the hoist actually swapped *and* whose boxes overlap,
    where it can make a visible difference.

    Four ranks, in order:

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
    because they belong to different layouts: two elements are never on
    screen together exactly when both have a layout and the two layouts
    differ.  Shared content (`layout is
    None`) is on screen in every layout, so it is never exempted this way --
    only a *pair of layout elements*, and only when their layouts disagree.

    The one place this question is asked -- every pairwise "are these ever
    on screen together" lint check (`hold-overlap`, `static-overlap`) calls
    this rather than open-coding the `is not None and is not None and !=`
    it would otherwise repeat at each call site.
    """
    return a.layout is not None and b.layout is not None and a.layout != b.layout
