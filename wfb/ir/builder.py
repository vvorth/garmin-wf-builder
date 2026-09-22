"""The semantic pass (ADR 0008 stage 2): `Builder` walks a validated YAML
document and produces a `wfb.ir.model.Face`, resolving data sources against
the catalogue, type-checking and compiling expressions, and requiring null
handling wherever the platform makes absence normal.  Also holds
`_NamedBlock` (the declared/accepted/rejected bookkeeping a named top-level
block keeps), `_dedup_append`, and the per-shape/part/style key and
rejection-reason tables this pass alone consults.

Nothing here knows a screen size -- per-device work happens in
:mod:`wfb.layout`.
"""

from __future__ import annotations

import math
import re
from collections.abc import Callable
from pathlib import Path

from .. import catalog, complications, expr, formatting, icons, series, units
from ..catalog import Type
from ..desugar import layout_ids
from ..diagnostics import Bag, Span
from ..palette import Color, ColorError
from ..series import Acquisition, SeriesDef
from ..units import Angle, Duration, Length, UnitError
from ..yamlsrc import YamlDocument

from .model import (
    ColorScheme, ComplicationSlot, ConfigChoice, ConfigColor, ConfigDataSlot, ConfigStyle,
    Curve, Element, Expression, Face, FontSpec, GRAPH_AREA_MAX_SAMPLES, Graph, Group, HOLD_AUTO,
    Hand, HandPart, HandSet, HandsElement, IconElement, LayoutDecl, MAX_OUTLINE_WIDTH,
    Outline, PATTERN_LOOP_INDEX,
    PatternElement, Position, Progress, SYSTEM_FONTS, Shape, Size, StyleEntry, Text,
    _drawn_copies, authored_draw_order, walk_elements,
)
from .naming import (
    _pascal, complication_slot_hold_method, complication_slot_icon_method, config_field,
    element_const_prefix, element_method_name, local_name, static_group_method,
)

#: Sentinels for `Builder._resolve_choice_icon_override`'s three-way result:
#: a per-choice icon override in a `config: data:` slot's `choices:` mapping
#: form is either "not declared at all" (this dict entry does not exist;
#: fall back to `wfb.icons.COMPLICATION_ICON`), "declared and invalid"
#: (already reported; drop the whole slot like every other rejected
#: `config: data:` entry), or a real `icons.SlotIcon | None` value (`None`
#: itself being the third, legitimate case: `icon: none`).  Two distinct
#: sentinel objects rather than reusing `None` for "not declared": `None`
#: already means the explicit "no icon" a `{type, icon: none}` choice asks
#: for, so it cannot also mean "no override key was present".
_NO_ICON_OVERRIDE = object()
_ICON_OVERRIDE_ERROR = object()

#: Which geometry keys each `shape:` actually reads.  A key outside its own
#: row is parsed by the schema and then dropped on the floor unless
#: `_check_shape_keys` below catches it -- e.g. a `radius:` typed onto a
#: rounded_rectangle instead of `corner_radius:` would otherwise silently do
#: nothing.
#:
#: `color:` and `filled:` are common to every shape and are not listed;
#: `filled:` has its own refusals on `arc` and `polygon`.  `thickness:` is
#: handled separately below, because whether it is read depends on `filled:`
#: rather than on the shape alone.
#:
#: `align`/`vertical_align` are in every row **except** `polygon` and
#: `line`: a polygon has no single `at:` to align on (every vertex is its
#: own position, and it has no `at:` of its own either), and a line's
#: `at:`/`to:` are already its two ends.  Leaving the two keys out of those
#: rows is what makes `_check_shape_keys` below reject them there, through
#: the same "key not used by this shape" sweep every other geometry key
#: goes through.
SHAPE_GEOMETRY_KEYS = {
    "rectangle": frozenset({"size", "align", "vertical_align"}),
    "rounded_rectangle": frozenset({"size", "corner_radius", "align", "vertical_align"}),
    "circle": frozenset({"radius", "align", "vertical_align"}),
    "ellipse": frozenset({"size", "align", "vertical_align"}),
    "line": frozenset({"to"}),
    "arc": frozenset({"radius", "start_angle", "sweep", "align", "vertical_align"}),
    "polygon": frozenset({"points"}),
}

#: The extra reason `_check_shape_keys` appends to the ordinary "not used
#: by this shape" note when the rejected key is `align` or `vertical_align`
#: -- `polygon` and `line` are the only two rows above without either key,
#: so this is a `dict`, not a per-shape branch.
_SHAPE_NO_ALIGNMENT_REASON = {
    "polygon": "every vertex is its own position; there is no single 'at:' "
               "to align on -- a polygon has no 'at:' of its own either",
    "line": "'at:' and 'to:' are the line's two ends",
}

#: Every geometry key, for the "not used by this shape" check.
_ALL_SHAPE_GEOMETRY_KEYS = frozenset().union(*SHAPE_GEOMETRY_KEYS.values())

#: The same precedent as `SHAPE_GEOMETRY_KEYS`, for a hand part -- four
#: primitives, the rotatable ones.  `filled`/`thickness` are handled
#: separately below, exactly as the main `Shape` handles them: which shapes
#: accept `filled` at all is one set, and whether `thickness` is read
#: depends on `filled`, not on the shape alone.  `at` is absent from
#: `polygon`'s own row because a polygon's vertices are each already an
#: absolute position in the hand's frame -- there is no separate centre to
#: place.
#: `align`/`vertical_align` are in the `rectangle` and `circle` rows only --
#: the box-drawn kinds -- resolved at build time, in the part's own frame,
#: by `Resolver._resolve_hand_part` shifting `_hand_point(part.at)` through
#: `wfb.layout.alignment_shift` before rounding.  `polygon` and `line` are
#: left out for the same reason `SHAPE_GEOMETRY_KEYS` leaves them out (a
#: polygon has no single `at:`; a line's `at:`/`to:` are already its two
#: ends), so the "key not used by this shape" sweep in
#: `_check_hand_part_keys` rejects both there for free.
HAND_PART_GEOMETRY_KEYS = {
    "polygon": frozenset({"points"}),
    "rectangle": frozenset({"at", "size", "align", "vertical_align"}),
    "line": frozenset({"at", "to"}),
    "circle": frozenset({"at", "radius", "align", "vertical_align"}),
}
_ALL_HAND_PART_GEOMETRY_KEYS = frozenset().union(*HAND_PART_GEOMETRY_KEYS.values())

#: Which hand part shapes accept `filled:` at all -- `line` has no notion of
#: being filled, so it is left out here the same way `arc` is left out of
#: `filled:`'s acceptance on the main `Shape`.
HAND_PART_FILLED_SHAPES = frozenset({"polygon", "rectangle", "circle"})

#: The two shapes for which `filled: false` is rejected outright -- a hand's
#: rectangle part becomes a polygon at build time, so both share the main
#: `Shape`'s own "no drawPolygon" reasoning.
HAND_PART_NO_UNFILLED = frozenset({"polygon", "rectangle"})

#: `shape:` values a hand part's schema recognises but this compiler does
#: not draw, each with its own platform reason -- accepted by the schema
#: alongside the four real ones (`schema/wfb-face-1.schema.json`,
#: `handPart.shape`) precisely so this dedicated message fires instead of a
#: blunt "not one of ..." enum mismatch naming eight options with no
#: explanation.
HAND_PART_REJECTED_SHAPES = {
    "rounded_rectangle": "no Dc call draws a rotated rounded rectangle -- "
                          "approximate it with 'polygon'",
    "ellipse": "no Dc call draws a rotated ellipse -- approximate it with 'polygon'",
    "arc": "an arc part would need its start angle to rotate with the hand too, "
           "which is not implemented yet (docs/limitations.md) -- "
           "approximate a wedge with 'polygon', or use 'circle' for a disc",
    "text": "a bitmap font cannot rotate",
    "icon": "a bitmap font cannot rotate",
}

#: The same precedent, for a `type: pattern` template part -- the hand
#: vocabulary plus `arc`, which a pattern's copies can rotate the start
#: angle of (`WfbArc.drawSpan` already takes a plain Float start), so it is
#: a real, drawable shape here rather than a `HAND_PART_REJECTED_SHAPES`
#: entry.  `rounded_rectangle`/`ellipse`/`text`/`icon` keep the same
#: platform reasons a hand part gives -- no `Dc` call draws any of the three
#: rotated *or* translated, and a bitmap font cannot do either.
#: `align`/`vertical_align` join `rectangle` and `circle` here the same way
#: they join the hand table above -- resolved at build time in the
#: template's own frame, before `_round_away`, so the turned or stepped
#: copy carries the shift for free.  `polygon`/`line`/`arc` stay without
#: them (arc has no `at` at all -- see its own row's note below).
#: `polygon`/`rectangle`/`line`/`circle` are identical to `HAND_PART_
#: GEOMETRY_KEYS`'s own rows -- inherited by dict expansion rather than
#: repeated -- plus two rows a hand part never reaches at all:
PATTERN_PART_GEOMETRY_KEYS = {
    **HAND_PART_GEOMETRY_KEYS,
    #: No `at` -- an arc part is always centred on the copy's own origin;
    #: `_check_hand_part_keys` reports a use of `at` here through the same
    #: "key not used by this shape" mechanism as any other part, with one
    #: extra note explaining why.
    "arc": frozenset({"radius", "start_angle", "sweep"}),
    #: Upright glyphs whose anchor turns (radial) or steps (linear) with the
    #: copy -- unlike every other row here, a bitmap font cannot itself
    #: rotate or translate, so only the anchor point goes through
    #: `PlacedPattern.transform`, **unless** `font:` names a `face:`
    #: (vector) font and `curve:` is authored too (plan 11 slice 2), in
    #: which case the glyphs themselves turn as well -- see `HandPart.curve`.
    #: `value` xor `text` is enforced by `Builder._build_hand_part`, not this
    #: table (a better message than a schema `oneOf` would give).
    "text": frozenset({"at", "value", "text", "format", "font", "align", "vertical_align",
                       "curve", "if_unavailable"}),
}
_ALL_PATTERN_PART_GEOMETRY_KEYS = frozenset().union(*PATTERN_PART_GEOMETRY_KEYS.values())

#: The extra reason `_check_hand_part_keys` appends to the ordinary
#: "not used by this part" note when the rejected key is `align` or
#: `vertical_align` -- shared by hand and pattern parts, since `polygon` and
#: `line` mean the same thing in both frames (`HAND_PART_GEOMETRY_KEYS` and
#: `PATTERN_PART_GEOMETRY_KEYS` both leave them without either key); `arc`
#: only ever reaches this table on a pattern part -- a hand part rejects
#: `shape: arc` outright, through `HAND_PART_REJECTED_SHAPES`, before this
#: table is ever consulted for one.
_HAND_PART_NO_ALIGNMENT_REASON = {
    "polygon": "every vertex is its own position; there is no single 'at:' "
               "to align on -- a polygon part has no 'at:' of its own either",
    "line": "'at:' and 'to:' are the part's two ends",
    "arc": "an arc part is always centred on the copy's own origin -- there "
           "is no 'at:' to offset in the first place",
}

#: `"text"` is not in this table: a pattern text part's glyphs are drawn
#: upright, and only the anchor point rotates or steps, so "a bitmap font
#: cannot rotate or translate through this loop" does not apply to it.
#: `HAND_PART_REJECTED_SHAPES` keeps its own `"text"` entry: a hand's
#: rotation really would have to spin the glyphs themselves, which is still
#: impossible.
PATTERN_PART_REJECTED_SHAPES = {
    "rounded_rectangle": "no Dc call draws a rotated or translated rounded "
                          "rectangle -- approximate it with 'polygon'",
    "ellipse": "no Dc call draws a rotated or translated ellipse -- "
               "approximate it with 'polygon'",
    "icon": "a bitmap font cannot rotate or translate through this loop",
}

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

#: The same precedent, for `curve:`'s own `style:` discriminator (plan 11
#: §2.2): `radial` is the only style with a circle for `radius:`/
#: `direction:` to describe, so `angled` reads neither. The schema still
#: parses both keys under `style: angled` (rather than rejecting them as
#: unknown) purely so `_check_curve_keys` can name the actual mistake --
#: the same "text-antialias" precedent `_reject_text_antialias` follows.
CURVE_STYLE_KEYS = {
    "angled": frozenset(),
    "radial": frozenset({"radius", "direction"}),
}
_ALL_CURVE_STYLE_KEYS = frozenset().union(*CURVE_STYLE_KEYS.values())

#: Matches `expr.check`'s own "unknown data source" message for exactly
#: `config.colors` or `config.colors.<role>` -- the only two shapes anything
#: under `config.colors.*` can ever fail to resolve as (see `_build_scope`,
#: which binds nothing else there).  Group 1 is `""` for the bare axis, or
#: `.<role>` for a bad role -- `Builder._expression` tells the two apart to
#: give a domain-specific error instead of a generic "did you mean" guess.
_CONFIG_COLORS_RE = re.compile(
    r"^unknown data source 'config\.colors((?:\.[A-Za-z_][A-Za-z0-9_]*)?)'$"
)


# --------------------------------------------------------------------------
# the semantic pass


class _NamedBlock:
    """The declared/accepted/rejected bookkeeping a named top-level block
    keeps -- `fonts:`, `palette:`, `layouts:`, `color_scheme:`,
    `config: data:` and `hands:` each build one of these as they parse their
    own entries.

    `declared` is every name the block saw, whether or not it survived; a
    rejected entry is still a *declared* one, so a reference to a name that
    was declared and then rejected can be told apart from one that was never
    declared at all.  `rejected` is the subset that failed the block's own
    check.  A resolver elsewhere first looks a name up in whatever dict the
    block's *accepted* values actually live in (`self.fonts`, `self.palette`,
    ... -- shaped differently per block, so that lookup stays at the call
    site); once that misses, :meth:`unknown` gives the shared "one error, not
    N" cascade tail: a name that was declared and then rejected here stays
    quiet, because the real mistake already has its own error against this
    block, and anything else is `unknown X`, with a note listing every
    declared name (`docs/lore/codegen.md`).
    """

    def __init__(self) -> None:
        self.declared: dict[str, Span | None] = {}
        self.rejected: set[str] = set()

    def declare(self, name: str, span: Span | None) -> None:
        self.declared[name] = span

    def reject(self, name: str) -> None:
        self.rejected.add(name)

    def unknown(
        self, bag: Bag, name: str, span: Span | None, *,
        code: str, message: str, note: str, prefix: str = "",
    ) -> None:
        """Report the shared "unknown X" diagnostic for `name`, or stay
        quiet when it was declared and then rejected here.  `message` is the
        error's full text; `note` is the fixed lead-in for the one note
        ("declared palette entries", "declared fonts", ...), followed by the
        declared names, sorted and `prefix`-qualified (`"palette."`,
        `"font."`, `"config.data."`, or `""`), or "(none declared)".
        """
        if name in self.rejected:
            return
        known = ", ".join(f"{prefix}{n}" for n in sorted(self.declared)) or "(none declared)"
        bag.error(code, message, span, notes=[f"{note}: {known}"])


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
        #: `_build_fonts` -- see `_NamedBlock`'s own docstring for why a
        #: rejected entry stays declared.
        self.fonts_block = _NamedBlock()
        #: The same split for `palette:`, needed now that a `config:`
        #: `default:`/`choices:` entry can name a palette entry and must get
        #: exactly one error when that name was rejected.
        self.palette_block = _NamedBlock()
        #: `config:` axes that were declared and then rejected.  Bound into
        #: scope anyway (`_build_scope`) so the author gets exactly one error,
        #: at the real mistake -- the same cascade fix every `_NamedBlock`
        #: exists for, and for the same reason: a second 'unknown data
        #: source' error points at a correct line and blames the wrong
        #: thing.  Partial (no `declared` dict of its own): every rejected
        #: name is already a key of `self.config`'s own source block, so
        #: there is nothing a second dict would add.
        self.rejected_config: set[str] = set()
        #: `layouts:` entries, in declaration order -- `layouts_block` keeps
        #: the same declared/rejected split every other named block keeps, so
        #: a `config: style:` entry's `layout:` must get exactly one error
        #: when it names a layout that was declared and then rejected, not a
        #: second one blaming the reference.  Built by `_build_layouts`,
        #: before `_build_color_scheme`/`_build_config`, so a style entry can
        #: resolve `layout:` the same build pass it resolves `colors:` in.
        self.layouts: list[LayoutDecl] = []
        self.layouts_block = _NamedBlock()
        #: `color_scheme:` entries, and the same declared/rejected split
        #: `palette_block` keeps -- a scheme with a bad role colour or a
        #: role-set mismatch is rejected, and a `config: style:` entry's
        #: `colors:` referencing it by name must get exactly one error, not a
        #: second one blaming the reference.
        self.color_scheme: dict[str, ColorScheme] = {}
        self.color_scheme_block = _NamedBlock()
        #: The `config: style:` axis, once built -- `None` until then, and
        #: still `None` if it was declared and rejected (see
        #: `rejected_config`, which gets `"style"` added in that case).
        self.config_style: ConfigStyle | None = None
        #: The roles a `config.colors.<role>` reference may name, once known
        #: -- set in `_build_scope`, consulted only by `_expression`'s
        #: dedicated error for a bad or missing role (see its own docstring).
        #: `None` means "no `config: style:` axis at all", not "zero roles".
        #: Named for the expression namespace (`config.colors.*`), not the
        #: `config: style:` block that declares it.
        self._config_colors_roles: tuple[str, ...] | None = None
        #: `config: data:` slots, keyed by name -- the same declared/rejected
        #: split every other `config:` sub-block keeps, so a `slot:` naming a
        #: slot that was declared and then rejected (a bad default/choice
        #: reference) gets exactly one error, at the real mistake, not a
        #: second one blaming the element that references it.
        self.config_data: dict[str, ConfigDataSlot] = {}
        self.config_data_block = _NamedBlock()
        #: `hands:` entries, and the same declared/rejected split every other
        #: named block keeps -- a `type: hands` element naming a set that was
        #: declared and then rejected gets exactly one error, at the real
        #: mistake, not a second one blaming the element.
        self.hand_sets: dict[str, HandSet] = {}
        self.hand_sets_block = _NamedBlock()
        self.scope = expr.Scope()
        self.seen_ids: dict[str, Span | None] = {}
        #: Derived Monkey C symbol -> the element id and span that claimed it
        #: first. Two distinct ids can still generate the same symbol
        #: (`temp_low` and `tempLow` both become `TEMP_LOW`), which the
        #: compiler must catch itself rather than let `monkeyc` discover it
        #: through a `Redefinition of ...` error pointing at generated code.
        self.seen_symbols: dict[str, tuple[str, Span | None]] = {}
        #: The top-level `antialias:` default, read first in `build()` --
        #: `_build_fonts` needs it (a `fonts:` entry with no `antialias:` of
        #: its own follows the face) and it is not otherwise in scope by the
        #: time that method runs.
        self.face_antialias = False
        #: The top-level `min_1px:` default, read first in `build()` for the
        #: same reason `face_antialias` above is -- nothing needs it before
        #: element resolution runs, but keeping the two read together avoids
        #: a second one-off special case later.
        self.face_min_1px = False

    # -- entry point ------------------------------------------------------

    def build(self) -> Face | None:
        data = self.doc.data
        self.face_antialias = bool(data.get("antialias", False))
        self.face_min_1px = bool(data.get("min_1px", False))
        # Layouts first: a `config: style:` entry's `layout:` resolves
        # against the declared names, the same build pass its `colors:`
        # resolves against `color_scheme:`.
        self._build_layouts(data.get("layouts") or {})
        self._build_palette(data.get("palette") or {})
        self._build_color_scheme(data.get("color_scheme") or {})
        self._build_config(data.get("config") or {})
        self._check_layouts_reachable(data)
        self._build_fonts(data.get("fonts") or {})
        self._build_scope()
        # Hands need the scope built first: a hand's `color:` may read
        # `palette.*`/`config.*` through the same `_color_expression` an
        # element's own `color:` uses, and it needs `self.scope` in place.
        # They need to run before `_build_elements` so a `type: hands`
        # element can resolve `hands: <name>` against `self.hand_sets` the
        # same build pass.
        self._build_hands(data.get("hands") or {})

        elements = self._build_elements(data.get("elements") or [], ("elements",))
        if not self.bag.ok():
            return None
        # Before `_apply_static`: a `complication_slot` inside a layout's own
        # `static:` must get the layout error alone, not also the
        # static-subtree one, so `Element.layout` has to be assigned -- and
        # the slot rule applied -- while the tree is still whole.
        self._assign_layouts(elements)
        if not self.bag.ok():
            return None
        self._apply_static(elements)
        if not self.bag.ok():
            return None
        self._resolve_antialias(elements)
        self._resolve_min_1px(elements)

        face = data["face"]
        name = face["name"]
        accepted_layouts = tuple(
            n for n in self.layouts_block.declared if n not in self.layouts_block.rejected)
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
            min_1px=self.face_min_1px,
            config=self.config,
            color_scheme=self.color_scheme,
            layouts=accepted_layouts,
            layout_decls={l.name: l for l in self.layouts if l.name in accepted_layouts},
            config_style=self.config_style,
            config_data=self.config_data,
            hands=self.hand_sets,
        )

    # -- layouts, palette, config, fonts, scope -----------------------------

    def _build_layouts(self, raw: dict) -> None:
        """`layouts:` -- named widget sets, declared as containers, form A
        only.

        Post-desugar, each body is just `{}` or `{lint: ...}` --
        `wfb/desugar.py`'s `_layouts_block` has already folded `static:`/
        `elements:` into synthetic groups appended to the top-level
        `elements:`, found again by their reserved id
        (`wfb.desugar.layout_ids`) and walked to set `Element.layout` once
        `elements` itself exists (`_assign_layouts`, called later in
        `build()`).  So this only records the *names*, in declaration order,
        plus each layout's own `lint:` (consulted by the lint pass's
        `unreachable-layout`).

        A layout body has little of its own that can be rejected today --
        unlike `fonts:`/`palette:`/`color_scheme:`, nothing here resolves a
        colour or a reference -- but the declared/rejected split exists
        anyway: a `config: style:` entry's `layout:` must follow the same
        "one error, not N" cascade discipline every other named block gets
        (CLAUDE.md, docs/lore/codegen.md).
        """
        for name, spec in raw.items():
            span = self.doc.span(raw, name)
            self.layouts_block.declare(name, span)
            self.layouts.append(LayoutDecl(
                name=name,
                lint_allow=frozenset((spec.get("lint") or {}).get("allow", ())),
                lint_reason=(spec.get("lint") or {}).get("reason"),
                span=span,
            ))

    def _assign_layouts(self, elements: list[Element]) -> None:
        """Stamp `Element.layout` on each layout's synthetic groups and their
        descendants, by the reserved id `wfb.desugar.layout_ids` defines,
        then apply the slot rule.

        Runs right after `_build_elements`, before `_apply_static` -- see
        `build()`'s own comment for why the ordering matters.  Only the
        *top-level* synthetic groups are looked up by id: `layout_ids`
        always mints a top-level id (the desugar rewrite appends both groups
        straight onto the top-level `elements:`, never nested), so a linear
        scan of `elements` is enough; :func:`walk_elements` then reaches
        every descendant from there.
        """
        if self.layouts:
            by_id = {e.id: e for e in elements}
            for decl in self.layouts:
                if decl.name in self.layouts_block.rejected:
                    continue
                for generated_id in layout_ids(decl.name):
                    group = by_id.get(generated_id)
                    if group is None:
                        continue  # this layout declared no static:/elements: of that kind
                    for element in walk_elements([group]):
                        element.layout = decl.name

        for element in walk_elements(elements):
            if isinstance(element, ComplicationSlot) and element.layout is not None:
                self.bag.error(
                    "layouts",
                    f"{element.id!r}: a complication_slot may not be inside "
                    f"layout {element.layout!r} content",
                    element.span,
                    notes=[
                        "the Data axis is face-wide -- one <complication "
                        "id=...> however many layouts read it -- so a slot "
                        "belongs in the shared top-level 'elements:', not "
                        "inside a 'layouts:' body",
                        "docs/guide/styles-and-layouts.md",
                    ],
                )

    def _check_layouts_reachable(self, data: dict) -> None:
        """`layouts:` declared with no `config: style:` entry ever naming one
        as its `layout:` is an error -- nothing lets the wearer pick it.

        Called after `_build_config`, once `self.config_style`/
        `self.rejected_config` are both known.  A `config: style:` that was
        declared and then rejected gives no second error here: the real
        mistake already has its own error pointing at `config:` -- the usual
        cascade discipline.
        """
        if not self.layouts:
            return
        if self.config_style is not None or "style" in self.rejected_config:
            return
        self.bag.error(
            "layouts",
            "layouts: is declared, but no 'config: style:' entry ever names "
            "one as its 'layout:' -- nothing lets the wearer pick it",
            self.doc.span(data, "layouts", of="key"),
            notes=["declared layouts: " + ", ".join(d.name for d in self.layouts),
                   "add a 'config: style:' block with an entry naming one, "
                   "or remove 'layouts:'"],
        )

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
            self.palette_block.declare(name, span)
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
                self.palette_block.reject(name)
                continue
            try:
                self.palette[name] = Color.parse(raw_value, what=f"palette.{name}")
            except ColorError as exc:
                self.bag.error("palette", str(exc), value_span)
                self.palette_block.reject(name)
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
        own error pointing at the `palette:` block, and the same cascade fix
        every `_NamedBlock` applies here -- one error at the real mistake,
        not one more per reference blaming the wrong line.
        """
        key = name[len("palette."):]
        if key in self.palette:
            return self.palette[key]
        self.palette_block.unknown(
            self.bag, key, span, code="config",
            message=f"unknown palette entry {name!r}",
            note="declared palette entries", prefix="palette.",
        )
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
        a `config: style:` entry's own `colors:` (docs/research/09 §3,
        ADR 0006 1's second amendment).

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
            self.color_scheme_block.declare(name, span)
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
                self.color_scheme_block.reject(name)
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
            self.color_scheme_block.reject(name)
            del self.color_scheme[name]

    def _scheme_reference(self, name: str, span: Span | None) -> str | None:
        """Resolve a bare `color_scheme:` name used from a `config: style:`
        entry's own `colors:`.

        Bare, not `color_scheme.<name>` -- that qualifying form is for
        expressions (`color: color_scheme.dark` is not even legal there
        either; it is `config.colors.<role>`), and there is exactly one thing
        `colors:` can name here, so a prefix buys nothing.  The schema's own
        `$defs/identifier` already rejects a non-identifier value before this
        ever runs, so this only ever sees a plausible name.

        Same declared/rejected cascade `_palette_reference` already has: a
        name that was declared and then rejected (a bad role colour, a
        role-set mismatch) gets no second error here, because the real
        mistake already has its own error pointing at the `color_scheme:`
        block.
        """
        if name in self.color_scheme:
            return name
        self.color_scheme_block.unknown(
            self.bag, name, span, code="config",
            message=f"unknown color scheme {name!r}",
            note="declared color_scheme entries",
        )
        return None

    def _layout_reference(self, name: str, span: Span | None) -> str | None:
        """Resolve a bare `layouts:` name used from a `config: style:`
        entry's own `layout:`.

        Same declared/rejected cascade `_scheme_reference` already has for
        `colors:` -- there is currently little that can reject a *declared*
        layout (`_build_layouts`), but the cascade exists anyway so a future
        rejection needs no change here.
        """
        if name in self.layouts_block.declared and name not in self.layouts_block.rejected:
            return name
        self.layouts_block.unknown(
            self.bag, name, span, code="config",
            message=f"unknown layout {name!r}", note="declared layouts",
        )
        return None

    def _build_config_style(self, spec: dict, span: Span | None) -> None:
        """`config: style:` -- an author-named, ordered set of entries riding
        Styles, the one axis Garmin gives no meaning to at all
        (docs/research/09 §3).  `config: colors:` is not a key; the schema
        rejects it.

        Unlike `accent_color`/`data_color`, entries are named by the
        *author* -- `choices:` is an ordered mapping, not a list -- so
        `default:` names an entry and "default must be one of choices" is an
        identity comparison on the entry name, not a scheme-name or
        colour-value one.

        Three uniform-shape passes, each rejecting the whole block at its
        first violation -- one error, not N (CLAUDE.md, docs/lore/codegen.md):

        1. every entry needs at least one of `layout:`/`colors:`;
        2. `layout:` is required on every entry once this design declares
           `layouts:`, and rejected when it does not -- an entry showing
           only shared content in a design that has layouts would be a
           silent blank-looking face;
        3. `colors:` is all-or-none across entries, independent of
           `layout:` -- a role must never be undefined for the entry the
           wearer picked.
        """
        raw_choices = spec["choices"]
        has_layouts = bool(self.layouts)

        for name, item in raw_choices.items():
            if "layout" in item or "colors" in item:
                continue
            self.bag.error(
                "config",
                f"config.style.choices.{name}: needs at least one of "
                "'layout:'/'colors:'",
                self.doc.span(raw_choices, name),
            )
            self.rejected_config.add("style")
            return

        for name, item in raw_choices.items():
            item_span = self.doc.span(raw_choices, name)
            has_layout = "layout" in item
            if has_layouts and not has_layout:
                self.bag.error(
                    "config",
                    f"config.style.choices.{name}: needs 'layout:' -- this "
                    "design declares 'layouts:', so every entry must pick one",
                    item_span,
                    notes=["declared layouts: "
                           + ", ".join(d.name for d in self.layouts)],
                )
                self.rejected_config.add("style")
                return
            if not has_layouts and has_layout:
                self.bag.error(
                    "config",
                    f"config.style.choices.{name}: 'layout:' is set, but "
                    "this design declares no 'layouts:' at all",
                    self.doc.span(item, "layout") or item_span,
                    notes=["remove 'layout:', or add a 'layouts:' block"],
                )
                self.rejected_config.add("style")
                return

        baseline_name = next(iter(raw_choices))
        baseline_has_colors = "colors" in raw_choices[baseline_name]
        for name, item in raw_choices.items():
            has_colors = "colors" in item
            if has_colors == baseline_has_colors:
                continue
            item_span = self.doc.span(raw_choices, name)
            if has_colors:
                message = (f"config.style.choices.{name}: declares "
                           f"'colors:', but 'choices.{baseline_name}' does not")
            else:
                message = (f"config.style.choices.{name}: needs 'colors:' "
                           f"-- 'choices.{baseline_name}' declares one")
            self.bag.error(
                "config", message, item_span,
                notes=["'colors:' must be declared on every entry, or none"],
            )
            self.rejected_config.add("style")
            return

        entries: list[StyleEntry] = []
        ok = True
        for name, item in raw_choices.items():
            item_span = self.doc.span(raw_choices, name)
            entry_ok = True
            colors_name: str | None = None
            if "colors" in item:
                color_span = self.doc.span(item, "colors") or item_span
                colors_name = self._scheme_reference(item["colors"], color_span)
                if colors_name is None:
                    entry_ok = False
            layout_name: str | None = None
            if "layout" in item:
                layout_span = self.doc.span(item, "layout") or item_span
                layout_name = self._layout_reference(item["layout"], layout_span)
                if layout_name is None:
                    entry_ok = False
            if not entry_ok:
                ok = False
                continue
            entries.append(StyleEntry(
                name=name,
                label=item.get("label"),
                colors=colors_name,
                layout=layout_name,
                lint_allow=frozenset((item.get("lint") or {}).get("allow", ())),
                lint_reason=(item.get("lint") or {}).get("reason"),
                span=item_span,
            ))
        if not ok:
            self.rejected_config.add("style")
            return

        default_name = spec["default"]
        by_name = {e.name: e for e in entries}
        if default_name not in by_name:
            self.bag.error(
                "config",
                f"config.style: default {default_name!r} is not one of 'choices:'",
                self.doc.span(spec, "default"),
                notes=[
                    "the on-device editor marks one listed entry as the user's "
                    "default (the generated <style default=\"true\">) -- Garmin "
                    "defines no behaviour for a default that is not in the list",
                    "add it to 'choices:', or change 'default:' to match an "
                    "entry already there",
                    "declared entries: " + ", ".join(by_name),
                ],
            )
            self.rejected_config.add("style")
            return

        self.config_style = ConfigStyle(
            default=default_name, entries=tuple(entries), span=span)

    @staticmethod
    def _complication_suggestion_notes(name: str, noun: str) -> list[str]:
        """The shared "unknown complication" notes: a "did you mean: ...?"
        when :func:`wfb.complications.suggest` finds a near match, then
        "run `wfb complications` for the full list of N <noun>" -- built
        identically by `_complication_reference` (`noun="types"`) and
        `_hold_target` (`noun="launch targets"`), which name the same table
        for two different reasons.
        """
        near = complications.suggest(name)
        notes = []
        if near:
            notes.append("did you mean: " + ", ".join(near) + "?")
        notes.append(f"run `wfb complications` for the full list of "
                     f"{len(complications.TYPES)} {noun}")
        return notes

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
        notes = self._complication_suggestion_notes(name, "types")
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
            self.config_data_block.declare(name, span)
            default_span = self.doc.span(spec, "default")
            default = self._complication_reference(
                spec["default"], f"config.data.{name}.default", default_span)
            if default is None:
                self.config_data_block.reject(name)
                continue

            raw_choices = spec["choices"]
            if raw_choices == "any":
                self.config_data[name] = ConfigDataSlot(
                    name=name, default=default, choices="any", span=span)
                continue

            choices: list[str] = []
            icon_overrides: dict[str, icons.SlotIcon | None] = {}
            seen: dict[str, int] = {}
            ok = True
            for index, item in enumerate(raw_choices):
                item_span = self.doc.span(raw_choices, index)
                if isinstance(item, dict):
                    # The mapping form: `{type: complication.<name>,
                    # icon: ...}` or `{..., glyph: ...}` -- carries
                    # information the bare string form cannot express, so
                    # this is not a desugar rewrite of it (docs/lore/
                    # codegen.md's desugar note does not apply here).
                    type_span = self.doc.span(item, "type") if "type" in item else item_span
                    resolved = self._complication_reference(
                        item.get("type"), f"config.data.{name}.choices[{index}].type",
                        type_span)
                    if resolved is None:
                        ok = False
                        continue
                    override = self._resolve_choice_icon_override(
                        item, f"config.data.{name}.choices[{index}]", item_span)
                    if override is _ICON_OVERRIDE_ERROR:
                        ok = False
                        continue
                    if override is not _NO_ICON_OVERRIDE:
                        icon_overrides[resolved] = override
                else:
                    resolved = self._complication_reference(
                        item, f"config.data.{name}.choices[{index}]", item_span)
                    if resolved is None:
                        ok = False
                        continue
                if resolved in seen:
                    self.bag.error(
                        "config",
                        f"config.data.{name}.choices: complication.{resolved} is "
                        "listed more than once",
                        item_span,
                        notes=[
                            f"already listed at choices[{seen[resolved]}]",
                            "a type can appear at most once in 'choices:', "
                            "regardless of which shape (a bare reference or "
                            "{type, icon}/{type, glyph}) each appearance uses -- "
                            "the schema's own 'uniqueItems' cannot see through "
                            "the two different shapes",
                        ],
                    )
                    ok = False
                    continue
                seen[resolved] = index
                choices.append(resolved)
            if not ok:
                self.config_data_block.reject(name)
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
                self.config_data_block.reject(name)
                continue

            self.config_data[name] = ConfigDataSlot(
                name=name, default=default, choices=tuple(choices),
                icon_overrides=icon_overrides, span=span)

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
        self.config_data_block.unknown(
            self.bag, name, span, code="complication-slot",
            message=f"unknown slot {raw!r}",
            note="declared slots", prefix="config.data.",
        )
        return None

    def _build_config(self, raw: dict) -> None:
        """`config:` -- the native editor's colour axes, the Styles axis, and
        the Data axis (ADR 0006 1, twice amended; docs/research/09 §4).

        `accent_color`/`data_color` read back as a single `Color`; `style`
        picks author-named entries, each naming a declared `color_scheme:`
        entry (`_build_config_style`) -- a different enough shape that it
        does not fit `ConfigAxis`/`ConfigColor` at all; `data` is a mapping
        of named slots, each built by `_build_config_data`.  Only these four
        keys reach here: the schema's `additionalProperties: false` on
        `config:` rejects anything else before the IR ever sees it, the same
        division of labour `_build_fonts` and `_build_palette` already rely
        on for their own blocks.
        """
        for name, spec in raw.items():
            span = self.doc.span(raw, name)
            if name == "style":
                self._build_config_style(spec, span)
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
            self.fonts_block.declare(name, span)
            # The schema's own `oneOf` (`$defs/font`) already tells "neither"
            # and "both" apart from a single valid kind, naming the missing
            # half rather than reading as an unknown key -- so by the time
            # this runs, exactly one of `source`/`face` is present.
            if "face" in spec:
                font = self._build_vector_font(name, spec, span)
            else:
                font = self._build_baked_font(name, spec, base, span)
            if font is None:
                self.fonts_block.reject(name)
                continue
            self.fonts[name] = font

    def _build_baked_font(
        self, name: str, spec: dict, base: Path, span: Span | None,
    ) -> FontSpec | None:
        source = base / str(spec["source"])
        if not source.exists():
            self.bag.error(
                "font",
                f"font {name!r}: source file not found: {spec['source']}",
                self.doc.span(spec, "source"),
                notes=[f"resolved against the design file, to {source}"],
            )
            return None
        size = self._font_size(name, spec)
        if size is None:
            return None
        # `scale:` is not a key the schema recognises -- `%r`/`px`
        # already say whether a length is per-device, so a design
        # writing it gets the ordinary unknown-key schema error before
        # this stage ever runs.
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
            return None
        if "if_unavailable" in spec:
            self.bag.error(
                "font",
                f"font {name!r}: 'if_unavailable:' is not accepted on a baked font",
                self.doc.span(spec, "if_unavailable"),
                notes=[
                    "'if_unavailable:' governs a device-resident 'face:' font "
                    "failing to publish a face -- a baked font is rasterised from "
                    "your own 'source:' at build time, so it is never unavailable "
                    "on any device",
                    "drop 'if_unavailable:', or switch this entry to 'face:' if "
                    "you meant a device-resident font",
                ],
            )
            return None
        return FontSpec(
            name=name,
            source=source,
            size=size,
            glyphs=spec.get("glyphs"),
            # A font with no `antialias:` of its own follows the
            # face-wide default rather than a hardcoded False -- there is
            # nothing further beneath a `fonts:` entry to inherit from, so
            # this is resolved here, not deferred to a tree walk the way an
            # element's is.
            antialias=bool(spec.get("antialias", self.face_antialias)),
            span=span,
            monospace=monospace,
            align=str(spec.get("align", "center")),
        )

    #: `fonts.<name>` keys that only mean something while baking a sheet --
    #: rejected on a `face:` (vector) entry by `_build_vector_font`, each
    #: with its own "why" rather than a bare "unknown key" (the schema
    #: still parses all four there for exactly this reason, the same
    #: "text-antialias" precedent `_reject_text_antialias` follows).
    _VECTOR_FONT_BAKING_KEYS = ("glyphs", "monospace", "align", "antialias")

    def _build_vector_font(self, name: str, spec: dict, span: Span | None) -> FontSpec | None:
        """`fonts.<name>.face:` -- a device-resident scalable face (plan 11
        §2.1), resolved per device later (`wfb.layout`, a later slice); here
        only the author-facing shape is checked.
        """
        ok = True
        for key in self._VECTOR_FONT_BAKING_KEYS:
            if key not in spec:
                continue
            self.bag.error(
                "font",
                f"font {name!r}: {key!r} is not accepted on a 'face:' font",
                self.doc.span(spec, key),
                notes=[
                    f"{key!r} is a property of baking a bitmap sheet, and a "
                    "vector font has no sheet -- it is drawn straight from the "
                    "device's own resident face, at any size, with nothing "
                    "rasterised at build time",
                    "drop it, or switch this entry to 'source:' if you meant a "
                    "baked font",
                ],
            )
            ok = False
        size = self._font_size(name, spec)
        if size is None:
            ok = False
        if not ok:
            return None
        raw_face = spec["face"]
        face = (raw_face,) if isinstance(raw_face, str) else tuple(raw_face)
        return FontSpec(
            name=name,
            size=size,
            span=span,
            face=face,
            if_unavailable=str(spec.get("if_unavailable", "error")),
        )

    def _font_size(self, name: str, spec: dict) -> Length | None:
        """`fonts.<name>.size`, as a `Length`.

        A bare number is rejected here, with the exact `%r`/`px` conversion
        named in the error, rather than accepted and silently reinterpreted:
        this stage of the compiler has no device knowledge at all (the
        module docstring: "nothing here knows a screen size"), so it cannot
        look up a target's minor radius and hand back a computed number --
        only the rule to apply by hand.
        """
        raw = spec["size"]
        if isinstance(raw, (int, float)) and not isinstance(raw, bool):
            self.bag.error(
                "font",
                f"font {name!r}: size must be a length such as '18%r' or "
                f"'12px', not a bare number ({raw!r})",
                self.doc.span(spec, "size"),
                notes=[
                    f"size: {raw!r} used to mean {raw!r}px on the smallest "
                    "target, scaled per device by the ratio of minor radii "
                    "-- the exact equivalent is (size / <smallest target's "
                    "minor radius, in px> * 100)%r, e.g. 68 on a 130px minor "
                    "radius (fenix8solar47mm, fr955) is 52.3076923077%r",
                    "for the same pixel count on every device instead -- "
                    "what 'scale: false' used to give you -- use 'px', "
                    f"e.g. '{raw!r}px'",
                ],
            )
            return None
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

    # -- hands --------------------------------------------------------------

    def _build_hands(self, raw: dict) -> None:
        """`hands:` -- named analog-hand sets, declared once, placed by name.

        The same declared/rejected cascade every other named block keeps
        (`fonts:`, `color_scheme:`, `layouts:`, via `_NamedBlock`): a set
        rejected for its own fault stays bound in `hand_sets_block.declared`,
        so a `type: hands` element naming it gets exactly one error, at the
        real mistake (`docs/lore/codegen.md`).
        """
        for name, spec in raw.items():
            span = self.doc.span(raw, name)
            self.hand_sets_block.declare(name, span)
            ok = True
            hands: dict[str, Hand | None] = {}
            for hand_name in ("hour", "minute", "second"):
                if hand_name not in spec:
                    hands[hand_name] = None
                    continue
                hand = self._build_hand(spec[hand_name], name, hand_name)
                if hand is None:
                    ok = False
                    continue
                hands[hand_name] = hand
            if hands.get("hour") is None and hands.get("minute") is None \
                    and hands.get("second") is None and ok:
                self.bag.error(
                    "hands",
                    f"hands.{name}: declares none of hour, minute or second",
                    span,
                    notes=["a hand set is a shape, like a fonts: entry -- it needs at "
                           "least one hand to be worth placing",
                           "a set with only 'second:' is a valid small-seconds subdial"],
                )
                ok = False
            if not ok:
                self.hand_sets_block.reject(name)
                continue
            self.hand_sets[name] = HandSet(
                name=name, hour=hands["hour"], minute=hands["minute"],
                second=hands["second"], span=span,
            )

    def _build_hand(self, spec: dict, set_name: str, hand_name: str) -> Hand | None:
        """One `hour:`/`minute:`/`second:` entry of a `hands:` set."""
        where = f"hands.{set_name}.{hand_name}"
        ok = True
        hand_color: Expression | None = None
        # Whether `color:` was written at all and failed its own check --
        # distinguished from "simply not declared" so a part with no colour
        # of its own does not also get a redundant, cascading "no colour"
        # error blaming it for a mistake made one level up (the same "one
        # error, not N" discipline `docs/lore/codegen.md` names).
        color_declared_and_failed = False
        if "color" in spec:
            hand_color = self._color_expression(spec, "color")
            if hand_color is None:
                ok = False
                color_declared_and_failed = True
            else:
                rejected = self._reject_hand_data_color(hand_color, where, self.doc.span(spec, "color"))
                if rejected:
                    hand_color = None
                    ok = False
                    color_declared_and_failed = True
        parts: list[HandPart] = []
        for index, raw_part in enumerate(spec.get("parts") or []):
            part = self._build_hand_part(
                raw_part, where, index, hand_color, color_declared_and_failed)
            if part is None:
                ok = False
                continue
            parts.append(part)
        if not ok:
            return None
        return Hand(parts=parts, color=hand_color)

    def _reject_hand_data_color(self, color: Expression, where: str, span: Span | None) -> bool:
        """A hand colour may not read a data source at all -- a hand is
        about the time, with no `when_absent:` to fall back through if a
        reading it named turned out absent.

        Hand-only: a pattern colour may read any source, absent-able or
        not -- the pattern-wide absence policy lives in
        `_check_pattern_absence` instead, which reports **one** error
        covering every colour and part `visible:` on the element, not a
        rejection per expression.  Returns whether the colour was rejected.
        """
        if not color.sources:
            return False
        self.bag.error(
            "hands",
            f"{where}.color: a hand colour cannot read data ({_and_paths(color.sources)})",
            span or color.span,
            notes=["allowed: palette entries, literal colours and config.* "
                   "(accent_color, data_color, colors.<role>) -- and conditionals "
                   "over those",
                   "a hand has no 'when_absent:' to fall back through if the "
                   "reading it named turned out absent"],
        )
        return True

    def _build_hand_part(
        self, node: dict, where: str, index: int,
        default_color: Expression | None, color_declared_and_failed: bool,
        *, context: str = "hand",
    ) -> HandPart | None:
        """One primitive of a hand, or of a `type: pattern` template -- the
        same per-shape precedent as `_build_shape`/`_check_shape_keys`,
        scoped to the rotatable-or-translatable primitives.  `context`
        selects which vocabulary applies: a hand part rejects `arc` outright
        (no runtime support for a rotating start angle); a pattern part
        accepts it, through the pattern barrel.  Hand behaviour is
        unchanged by this parameter -- every table it reads defaults to the
        hand's own, so `context="hand"` (every existing caller) takes
        exactly the same code path.
        """
        is_hand = context == "hand"
        noun = "hand" if is_hand else "pattern"
        rejected_shapes = HAND_PART_REJECTED_SHAPES if is_hand else PATTERN_PART_REJECTED_SHAPES
        geometry_keys = HAND_PART_GEOMETRY_KEYS if is_hand else PATTERN_PART_GEOMETRY_KEYS
        part_where = f"{where}.parts[{index}]"
        shape = node.get("shape")
        span = self.doc.span(node) if isinstance(node, dict) else None
        if isinstance(node, dict) and shape in rejected_shapes:
            self.bag.error(
                "element",
                f"{part_where}: 'shape: {shape}' is not accepted on a {noun} part -- "
                f"{rejected_shapes[shape]}",
                self.doc.span(node, "shape") or span,
                notes=["the rotatable primitives are: " + ", ".join(sorted(geometry_keys))],
            )
            return None
        if not isinstance(node, dict) or shape not in geometry_keys:
            # Unreachable once the schema has run (shape is a closed enum);
            # kept so a malformed node from a future schema slip fails loudly
            # here rather than with an AttributeError three lines down.
            self.bag.error("hands" if is_hand else "pattern",
                           f"{part_where}: not a valid {noun} part", span)
            return None

        ok = True
        part_color = self._color_expression(node, "color") if "color" in node else None
        if is_hand and part_color is not None and self._reject_hand_data_color(
                part_color, part_where, self.doc.span(node, "color")):
            part_color = None
            ok = False
        elif "color" in node and part_color is None:
            ok = False  # _color_expression already reported the real mistake
        effective_color = part_color if part_color is not None else default_color
        if effective_color is None and not color_declared_and_failed \
                and not ("color" in node and part_color is None):
            owner = "its hand" if is_hand else "this pattern"
            self.bag.error(
                "hands" if is_hand else "pattern",
                f"{part_where}: no colour -- neither this part nor {owner} "
                "declares 'color:'",
                span,
                notes=[f"set 'color:' on the part, or on the {noun} as a default "
                       "every part without one inherits"],
            )
            ok = False

        # `visible:`: pattern parts only -- the schema keeps `handPart`
        # closed to it, so `context == "hand"` never sees the key at all.
        # Compiled inside the caller's `copy`-bound scope
        # (`Builder._build_pattern_element`), the same as a colour.  A
        # constant `true` is dropped (nothing to gate); a constant `false`
        # is kept, so the `dead-element` lint and codegen (which emits no
        # draw code for it) both see it.
        part_visible: Expression | None = None
        if not is_hand and "visible" in node:
            part_visible = self._visible(node)
            if part_visible is None:
                ok = False
            elif part_visible.constant is not None and part_visible.constant:
                part_visible = None

        raw_points = node.get("points") or []
        points = [self._position(raw, node, "points")
                  for raw in raw_points if isinstance(raw, dict)]
        at = self._position(node.get("at"), node, "at") if "at" in node else Position()
        size = self._size(node.get("size"))
        to = self._position(node.get("to"), node, "to") if "to" in node else None
        thickness = self._length(node, "thickness")
        radius = self._length(node, "radius")
        filled = bool(node.get("filled", True))
        start_angle = self._angle(node, "start_angle") if shape == "arc" else None
        sweep = self._angle(node, "sweep") if shape == "arc" else None

        if shape == "polygon" and len(points) < 3:
            self._require(node, "points", f"{part_where}: a polygon part needs points")
            ok = False
        if shape == "rectangle" and (size.width is None or size.height is None):
            self._require(node, "size", f"{part_where}: a rectangle part needs size.width and size.height")
            ok = False
        if shape == "line" and to is None:
            self._require(node, "to", f"{part_where}: a line part needs a 'to' position")
            ok = False
        if shape == "circle" and radius is None:
            self._require(node, "radius", f"{part_where}: a circle part needs a radius")
            ok = False
        if shape == "arc" and radius is None:
            self._require(node, "radius", f"{part_where}: an arc part needs a radius")
            ok = False

        if not self._check_hand_part_keys(node, shape, part_where, context=context):
            ok = False

        if "filled" in node and shape in HAND_PART_NO_UNFILLED and not filled:
            self.bag.error(
                "element",
                f"{part_where}: 'filled: false' is not accepted on a {noun} "
                f"'shape: {shape}' part -- Toybox.Graphics.Dc has fillPolygon "
                "but no drawPolygon",
                self.doc.span(node, "filled") or span,
                notes=(["a rectangle part becomes a polygon at build time, so "
                        "the same platform limit applies"]
                       if shape == "rectangle" else []),
            )
            ok = False

        # Computed early (moved ahead of the `shape: text` block below) so
        # `vertical_align` is already known when `curve:` needs to reject
        # `bottom` under it -- the same value is reused, unchanged, at the
        # `HandPart(...)` construction at the end of this method.
        align, vertical_align = self._alignment(node)

        # `shape: text`: upright glyphs whose anchor turns (radial) or
        # steps (linear) with the copy -- reachable only in a
        # pattern's template, since `HAND_PART_REJECTED_SHAPES` still refuses
        # `text` on a hand outright.  Each branch below is exclusive of the
        # others ("one error, not N", docs/lore/codegen.md): a design with
        # exactly one mistake here gets exactly one error.
        text_value: Expression | None = None
        text_literal: str | None = None
        text_format: str | None = None
        text_font = "FONT_MEDIUM"
        text_font_is_custom = False
        text_curve: Curve | None = None
        text_if_unavailable: str | None = None
        if shape == "text":
            has_value = "value" in node
            has_text = "text" in node
            if has_value == has_text:  # both, or neither
                self.bag.error(
                    "pattern",
                    f"{part_where}: a text part needs exactly one of "
                    "'value:' (an expression; 'copy' is in scope) or "
                    "'text:' (a fixed string)",
                    span,
                )
                ok = False
            elif has_value:
                value = self._expression(node, "value")
                if value is None:
                    ok = False  # _expression already reported the real mistake
                else:
                    bad_refs = sorted({
                        ref.path for ref in expr.walk(value.ast)
                        if isinstance(ref, expr.Ref) and ref.path != expr.COPY
                    })
                    if bad_refs:
                        self.bag.error(
                            "pattern",
                            f"{part_where}.value: a pattern text part's value "
                            "may read only 'copy', not " + ", ".join(bad_refs),
                            value.span,
                            notes=["every copy's string must be known at build "
                                   "time, for font subsetting and extents",
                                   "data in a pattern text part is not "
                                   "implemented (docs/limitations.md)"],
                        )
                        ok = False
                    elif value.value.type not in (Type.NUMBER, Type.FLOAT, Type.STRING):
                        self.bag.error(
                            "pattern",
                            f"{part_where}.value: must be a number or a "
                            f"string, got {value.value}",
                            value.span,
                        )
                        ok = False
                    else:
                        text_value = value
                        if "format" in node:
                            text_format = node.get("format")
                            self._check_format(node, value, text_format)
            else:  # has_text
                if "format" in node:
                    self.bag.error(
                        "pattern",
                        f"{part_where}.format: 'format:' applies only to "
                        "'value:', not a fixed 'text:'",
                        self.doc.span(node, "format"),
                    )
                    ok = False
                else:
                    text_literal = str(node.get("text"))

            font_ok = True
            if "font" in node:
                resolved = self._font_reference(str(node["font"]), self.doc.span(node, "font"))
                if resolved is None:
                    ok = False  # _font_reference already reported the real mistake
                    font_ok = False
                else:
                    text_font, text_font_is_custom = resolved
            font_is_vector = text_font_is_custom and self.fonts[text_font].is_vector

            # `curve:` (plan 11 slice 2): the same bend a `text` element's
            # own `curve:` gives it -- see `_build_pattern_curve` for how
            # the authored angle composes with a radial pattern's own
            # per-copy rotation.  `font_ok` mirrors `_build_curve`'s own
            # parameter: skip the "needs a face: font" check when the font
            # reference itself already failed, so a design with one mistake
            # here gets one error, not two.
            if "curve" in node:
                text_curve = self._build_pattern_curve(
                    node, part_where, font_is_vector, vertical_align, font_ok)
                if text_curve is None:
                    ok = False
            if font_ok and "if_unavailable" in node:
                self._check_pattern_text_if_unavailable(node, part_where, font_is_vector)
            text_if_unavailable = node.get("if_unavailable")

        if not ok:
            return None
        return HandPart(
            shape=shape, points=points, at=at, size=size, to=to,
            thickness=thickness, radius=radius, filled=filled,
            color=effective_color, span=span,
            start_angle=start_angle, sweep=sweep,
            visible=part_visible,
            text_value=text_value, text_literal=text_literal, format=text_format,
            font=text_font, font_is_custom=text_font_is_custom,
            curve=text_curve, if_unavailable=text_if_unavailable,
            align=align, vertical_align=vertical_align,
            min_1px=(bool(node["min_1px"]) if "min_1px" in node else None),
        )

    def _check_hand_part_keys(
        self, node: dict, shape: str, part_where: str, *, context: str = "hand",
    ) -> bool:
        """Reject a geometry key this part's `shape:` does not read, plus the
        separately-handled `thickness`/`filled` rules -- the same "a key a
        part's shape does not read is an error" precedent as
        `Builder._check_shape_keys`.  Also how an `arc` pattern part's `at:`
        is refused: `at` is not in `PATTERN_PART_GEOMETRY_KEYS["arc"]`, so it
        falls out of the same "key belongs to another shape" sweep as any
        other misplaced key, with one extra note explaining the platform
        reason.
        """
        is_hand = context == "hand"
        noun = "hand" if is_hand else "pattern"
        geometry_keys = HAND_PART_GEOMETRY_KEYS if is_hand else PATTERN_PART_GEOMETRY_KEYS
        all_keys = _ALL_HAND_PART_GEOMETRY_KEYS if is_hand else _ALL_PATTERN_PART_GEOMETRY_KEYS

        def extra_notes(key: str) -> list[str]:
            notes = []
            if not is_hand and shape == "arc" and key == "at":
                notes.append("an arc part is always centred on the copy's own "
                             "origin -- there is no separate centre to offset")
            if key in ("align", "vertical_align") and shape in _HAND_PART_NO_ALIGNMENT_REASON:
                notes.append(_HAND_PART_NO_ALIGNMENT_REASON[shape])
            return notes

        ok = self._check_foreign_keys(
            node, shape, geometry_keys, all_keys, code="element", disc="shape",
            prefix=f"{part_where}: ", qualifier=f"a {noun} ", suffix=" part",
            extra_notes=extra_notes,
        )
        filled = bool(node.get("filled", True))
        thickness_always = {"line"} if is_hand else {"line", "arc"}
        thickness_ok = shape in thickness_always or (shape == "circle" and not filled)
        if "thickness" in node and not thickness_ok:
            reason = ("a filled 'shape: circle' part" if shape == "circle"
                      else f"a {noun} 'shape: {shape}' part")
            only = "'line'" + (" and 'arc'" if not is_hand else "")
            self.bag.error(
                "element",
                f"{part_where}: 'thickness' is not used by {reason}",
                self.doc.span(node, "thickness") or self.doc.span(node),
                notes=["thickness is the pen width of an outline; add 'filled: false' "
                       "to a circle part to outline it, or drop 'thickness'"]
                      if shape == "circle" else
                      [f"only {only} and an unfilled 'circle' part read 'thickness'"],
            )
            ok = False
        if "filled" in node and shape not in HAND_PART_FILLED_SHAPES:
            if shape == "line":
                filled_note = "a line has no notion of being filled or not"
            elif shape == "text":
                filled_note = "glyphs have no notion of being filled or not"
            else:
                filled_note = ("an arc has no notion of being filled or not -- "
                               "Toybox.Graphics.Dc has no filled-arc primitive")
            self.bag.error(
                "element",
                f"{part_where}: 'filled' is not used by a {noun} 'shape: {shape}' part",
                self.doc.span(node, "filled") or self.doc.span(node),
                notes=[filled_note],
            )
            ok = False
        return ok

    def _define_palette_color(self, name: str, constant: int) -> None:
        """Bind `palette.<name>` to its Monkey C constant -- shared by an
        accepted palette entry (`constant` is its real value) and a
        declared-then-rejected one (`constant=0`, a placeholder: nothing is
        emitted from a design that has an error, so it is never reached --
        see the two call sites in `_build_scope` for the cascade this binds
        into scope for).
        """
        self.scope.define(
            f"palette.{name}",
            expr.Binding(
                expr.Value(Type.COLOR),
                code=f"Palette.{name.upper()}",
                constant=constant,
                kind="palette",
            ),
        )

    def _define_config_color(self, path: str, code: str) -> None:
        """Bind `path` (`config.<name>` or `config.colors.<role>`) to the
        view field `code` reads back from -- shared by every accepted or
        declared-then-rejected config colour binding in `_build_scope`.

        `constant=None` is deliberate, unlike a palette entry: the view
        field this reads is user-editable at runtime (on a device with the
        native editor), so `fold` must never inline it as the declared
        default -- `expr.fold`'s Ref branch only substitutes when
        `binding.constant` is set.
        """
        self.scope.define(
            path,
            expr.Binding(expr.Value(Type.COLOR), code=code, constant=None, kind="config"),
        )

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
            self._define_palette_color(name, color.value)
        for name in sorted(self.palette_block.rejected):
            # Declared, then rejected above (an out-of-range colour, or a
            # `config.*`/`palette.*` reference `_build_palette` refuses).
            # Bound into scope anyway so an element's `color: palette.<name>`
            # gets the one real error already reported against the
            # `palette:` block, not a second "unknown data source" blaming
            # the element for a mistake made elsewhere -- the same cascade
            # fix every `_NamedBlock` exists for, in the same shape.
            # Nothing is emitted from a design that has an error, so the
            # placeholder value here is never reached.
            self._define_palette_color(name, 0)
        for name, entry in self.config.items():
            self._define_config_color(f"config.{name}", entry.field)
        for name in sorted(self.rejected_config - {"style"}):
            # Declared, then rejected above.  Binding it anyway keeps the one
            # real error the only error: without this, every `color:
            # config.<name>` in the design adds an "unknown data source" that
            # is true only because the compiler threw the axis away -- the
            # cascade every `_NamedBlock` already exists to prevent, in the
            # same shape.  Nothing is emitted from a design that has an
            # error, so the field name here is never reached.  `"style"` is
            # excluded --
            # it is not a single-colour axis, so it cannot use `config_field`
            # the way every other rejected axis does, and is handled in the
            # `config.colors.<role>` block below instead.
            self._define_config_color(f"config.{name}", config_field(name))

        # `config.colors.<role>` -- one binding per role of the *default*
        # entry's declared `config: style:` scheme, deliberately *not* one
        # binding for the bare `config.colors` (a scheme is not a colour; see
        # `_expression`'s dedicated error for that and for a bad role, both
        # keyed off `self._config_colors_roles`).  A layout-only default
        # entry (`colors is None`) binds no roles at all -- there is no
        # scheme to read one from, so `config.colors.<role>` is legitimately
        # undefined here, the ordinary "unknown data source" error rather
        # than a special one.
        if self.config_style is not None and self.config_style.default_entry.colors is not None:
            default_scheme = self.color_scheme[self.config_style.default_entry.colors]
            self._config_colors_roles = tuple(sorted(default_scheme.colors))
            for role in default_scheme.colors:
                self._define_config_color(f"config.colors.{role}", config_field(f"colors_{role}"))
        elif "style" in self.rejected_config:
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
                    self._define_config_color(f"config.colors.{role}", config_field(f"colors_{role}"))
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
        if node.get("overrides"):
            # Parsed and stored, but applied by nothing (ADR 0004 4 is still
            # unbuilt).  Accepting it silently would be the worst of the
            # three options: a misspelled device id and an invented key both
            # validate clean, and the author would be left believing a
            # per-device tweak landed.
            self.bag.error(
                "overrides",
                f"{element_id}: per-device 'overrides:' is not implemented yet, "
                "so this would be silently ignored",
                self.doc.span(node, "overrides") or span,
                notes=["ADR 0004 4 specifies it; nothing reads it yet -- see "
                       "docs/limitations.md 2",
                       "until it lands, express a per-device difference with a "
                       "relative unit (%r, %) rather than a fixed px"],
            )
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
            on_hold=self._hold_target(node),
            visible=self._visible(node),
            static=bool(node.get("static", False)),
            antialias=(bool(node["antialias"]) if "antialias" in node else None),
            min_1px=(bool(node["min_1px"]) if "min_1px" in node else None),
        )

        builders = {
            "group": self._build_group,
            "shape": self._build_shape,
            "text": self._build_text,
            "progress": self._build_progress,
            "icon": self._build_icon,
            "graph": self._build_graph,
            "complication_slot": self._build_complication_slot,
            "hands": self._build_hands_element,
            "pattern": self._build_pattern_element,
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
            # Only emitted when `icon_size:` is set (icon method) or
            # `on_hold: auto` is declared (hold method), but both reserved
            # for every `complication_slot` regardless -- the same "an
            # unrelated later edit must not introduce a collision" reasoning
            # as the group case just above.
            candidates.append(complication_slot_icon_method(element_id))
            candidates.append(complication_slot_hold_method(element_id))
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

    def _hold_target(self, node: dict) -> str | None:
        """Validate `on_hold:` against the launchable complication table.

        A watch face cannot open an arbitrary app; `Complications.exitTo` is
        the only exit the platform offers, so the value here names a
        complication *type* and the watch opens whatever owns it.  Checked
        against :mod:`wfb.complications`, which is generated from the SDK's own
        `COMPLICATION_TYPE_*` table -- an invented name would compile to an
        undefined symbol, so catching it here points at the author's line
        instead of a generated one.

        `on_hold: auto` is validated here only as far as recognising the
        sentinel and passing it through unresolved -- this runs from
        `common`, *before* the kind-specific builder gives the element a
        value binding to resolve `auto` from.  `Builder._resolve_hold_auto`
        does the actual resolution once the element is fully built.
        """
        raw = node.get("on_hold")
        if raw is None:
            return None
        name = str(raw)
        if name == HOLD_AUTO:
            return HOLD_AUTO
        if complications.get(name) is not None:
            return name
        notes = self._complication_suggestion_notes(name, "launch targets")
        self.bag.error(
            "on-hold",
            f"unknown hold target {name!r}",
            self.doc.span(node, "on_hold"),
            notes=notes,
        )
        return None

    def _resolve_hold_auto(self, element: Element) -> None:
        """Resolve `on_hold: auto`.

        Deferred here, called from `_build_element` right after the
        kind-specific builder returns: this needs a *fully-built* element,
        since `_hold_target` (called from `common`, before the builder runs)
        has no value binding yet to resolve `auto` from.

        By the time this returns, `element.on_hold` is either a real
        `wfb.complications.TYPES` key or `None` -- never the `HOLD_AUTO`
        sentinel -- so `wfb/emit/monkeyc.py`, which indexes
        `complications.TYPES` with it directly, needs no change at all.
        """
        if isinstance(element, ComplicationSlot):
            # `Builder._build_complication_slot` has already restricted this
            # element to `on_hold: auto` or nothing -- and unlike every other
            # element's `auto`, a slot's is never resolved to a fixed
            # `wfb.complications.TYPES` name here: the wearer can repoint the
            # slot at any moment, so the launch target has to be read fresh
            # from the slot's own field on the device, not baked in at build
            # time.  `wfb.emit.monkeyc.emit_delegate` special-cases
            # `ComplicationSlot` for exactly this reason, so `HOLD_AUTO` is
            # left in place rather than turned into a `complications.TYPES`
            # key the way it would be for a `Text`/`Progress`/`IconElement`.
            return
        if element.on_hold == HOLD_AUTO:
            element.on_hold = self._resolve_auto_target(
                element.id, "on_hold", self._hold_auto_sources(element), element.span)

    @staticmethod
    def _hold_auto_sources(element: Element) -> tuple[str, ...]:
        """The catalogue paths `on_hold: auto` may resolve from, for one element.

        The element's own **value** expression(s) only -- deliberately not
        `color:`/`max:`, since a conditional colour's reference is not what
        the element is *about*.  A `text`'s `value:`, a `progress`'s
        `value:` (not `max:`), and an `icon`'s `icon_for:` (not a static
        `icon:`/`glyph:`, which reads no source at all).

        This intentionally is **not** `wfb.emit.monkeyc.ReadPlan.
        _value_expressions` reused: that helper answers a different question
        (which expressions a `when_absent:` policy governs) and its answer
        differs from this one in two ways -- `Progress` there includes
        `max:` too (one absent reading is as absent as the other, for a
        fill *fraction*), and it does not cover `IconElement` at all (an
        icon has no `when_absent:` to govern).  Forcing one shape onto both
        questions would make one of them wrong, so this stays a second,
        smaller helper rather than an import.
        """
        if isinstance(element, (Text, Progress)):
            return element.value.sources if element.value is not None else ()
        if isinstance(element, IconElement):
            return element.value_for.sources if element.value_for is not None else ()
        return ()

    def _resolve_auto_target(self, label: str, key: str, sources: tuple[str, ...],
                             span: Span | None) -> str | None:
        """Resolve `auto` to exactly one `wfb.complications.TYPES` name.

        Three outcomes: exactly one distinct non-None
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

    def _alignment(self, node: dict) -> tuple[str, str]:
        """`(align, vertical_align)`, defaulting to `"center"`/`"center"` --
        the one place that reads the two keys, a placement property of every
        kind that has a placement box.  The schema is normative on which
        values reach here (`$defs/align`/`$defs/verticalAlign`; `baseline`
        is not in the schema -- `wfb.validate`'s friendly rename error
        catches it first), so this is a plain lookup with no validation of
        its own.  Shared by every accepting kind's builder -- `_build_group`,
        `_build_text`, `_build_hand_part`'s `shape: text`/`rectangle`/
        `circle` branches, `_build_shape`, `_build_progress`, `_build_graph`,
        `_build_icon` and `_build_complication_slot` -- instead of each
        reading the two keys itself.
        """
        return node.get("align", "center"), node.get("vertical_align", "center")

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

        Reused verbatim for a `type: pattern` part's own `visible:`, with
        `copy` bound in scope -- but there "absent is hidden" means the whole
        *pattern* is hidden, not just this part: `_check_pattern_absence`
        governs that, not this method, because the reading is taken once per
        frame, before the loop, so its absence is not a per-copy fact.
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

    def _resolve_inherited_flag(
        self, elements: list[Element], *, authored: str, resolved: str, default: bool,
    ) -> None:
        """Resolve a boolean key as an inherited *default*, root to leaf --
        shared by `antialias:` and `min_1px:`, which are identical in shape:
        `authored` names the field holding what the author wrote (`None` =
        inherit), `resolved` the field to stamp the answer into, `default`
        the face-wide default the root of the tree inherits.

        Deliberately a single top-down pass over the finished tree, called
        once from `build()` for each key, rather than pushed per group the
        way `_push_visible` is: `visible:` *conjoins*, so composing it
        bottom-up as each group finishes building is safe and even necessary
        (an inner group has already folded its own condition into its
        children before the outer one runs).  Neither `antialias:` nor
        `min_1px:` accumulates -- the nearest enclosing declaration simply
        wins -- so there is nothing to compose, and threading "does an
        ancestor further up still have to hand this element a default"
        through the bottom-up build order would need more bookkeeping than a
        second, independent walk over the finished tree.  That is also why
        this is one helper with two callers rather than one walk that
        resolves both keys at once: they are two unrelated inherited
        defaults that happen to share a shape, not one feature, and a future
        third one (or a change to just one of them) should not have to touch
        the other's call site.

        A child's own value always wins outright over its group's (unlike
        `visible:`, there is no meaningful "AND" of two booleans that both
        mean "should this look soft" or "should this clamp" -- one of them is
        simply what the author asked for here), which is exactly what
        leaving `inherited` unchanged for an element that declares its own
        value, and only substituting it for one that left the key as `None`,
        gives.
        """
        def visit(items: list[Element], inherited: bool) -> None:
            for element in items:
                authored_value = getattr(element, authored)
                resolved_value = authored_value if authored_value is not None else inherited
                setattr(element, resolved, resolved_value)
                if isinstance(element, Group):
                    visit(element.items, resolved_value)

        visit(elements, default)

    def _resolve_antialias(self, elements: list[Element]) -> None:
        """`antialias:` -- see `_resolve_inherited_flag`, which does the work."""
        self._resolve_inherited_flag(
            elements, authored="antialias", resolved="resolved_antialias",
            default=self.face_antialias,
        )

    def _resolve_min_1px(self, elements: list[Element]) -> None:
        """`min_1px:` -- see `_resolve_inherited_flag`, which does
        the work. A hand/pattern part's own `min_1px` is resolved separately,
        per element instance, at layout time (`HandPart.min_1px`'s docstring
        explains why it has no `resolved_` twin here)."""
        self._resolve_inherited_flag(
            elements, authored="min_1px", resolved="resolved_min_1px",
            default=self.face_min_1px,
        )

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

    #: `_check_static_subtrees`'s per-kind "cannot be static" table: each of
    #: these reads its picture from something that is not an `Expression` at
    #: all -- a graph's series, a complication_slot's pull, a hand's clock
    #: angle -- so the generic "nothing here may read a data source" sweep
    #: the method falls through to below would never catch any of them.
    #: `phrase` fills "{element.id!r} is {phrase} and cannot be static", so
    #: it carries its own article ("a graph", but "analog hands" -- hands
    #: are plural, not "a analog hands").
    _STATIC_FORBIDDEN_KINDS: tuple[tuple[type, str, str], ...] = (
        (Graph, "a graph",
         "a graph's series is recomputed once a minute -- a buffer filled "
         "once would freeze it at whatever it showed on the first frame"),
        (ComplicationSlot, "a complication_slot",
         "its reading is pulled fresh every frame, and the wearer can "
         "repoint it to a different complication at any time -- a buffer "
         "filled once would freeze both"),
        (HandsElement, "analog hands",
         "a hand's angle is the time -- a buffer filled once would freeze "
         "it at whatever it showed on the first frame"),
    )

    def _check_static_subtrees(self, roots: list[Element]) -> bool:
        ok = True
        for root in roots:
            for element in walk_elements([root]):
                forbidden = next(
                    (entry for entry in self._STATIC_FORBIDDEN_KINDS
                     if isinstance(element, entry[0])),
                    None,
                )
                if forbidden is not None:
                    _, phrase, note = forbidden
                    self.bag.error(
                        "static",
                        f"{element.id!r} is {phrase} and cannot be static",
                        element.span,
                        notes=[note,
                               f"take it out of {root.id!r}"
                               if element is not root else
                               "drop `static: true` from it"],
                    )
                    ok = False
                    continue
                for expression in element.expressions():
                    if not expression.sources:
                        continue
                    is_part_visible = (
                        isinstance(element, PatternElement)
                        and any(expression is p.visible for p in element.parts)
                    )
                    where = ("visible" if expression is element.visible or is_part_visible
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
        align, vertical_align = self._alignment(node)
        group = Group(
            **common,
            size=self._size(node.get("size")),
            items=self._build_elements(node["children"], path + ("children",)),
            align=align,
            vertical_align=vertical_align,
        )
        self._push_visible(group)
        return group

    def _build_shape(self, node: dict, common: dict, path: tuple) -> Element:
        shape = node["shape"]
        raw_points = node.get("points") or []
        align, vertical_align = self._alignment(node)
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
            align=align,
            vertical_align=vertical_align,
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

    def _check_foreign_keys(
        self, node: dict, chosen: str, table: dict[str, frozenset[str]],
        all_keys: frozenset[str], *, code: str, disc: str,
        prefix: str = "", qualifier: str = "", suffix: str = "",
        empty_label: str = "(no geometry keys)",
        extra_notes: Callable[[str], list[str]] | None = None,
    ) -> bool:
        """Reject a key from another row of `table` that `chosen`'s own row
        does not read -- the shared "key not used by this X" sweep
        `_check_shape_keys`, `_check_hand_part_keys` and
        `_check_graph_style_keys` each specialise, for `disc` (the
        discriminator word: `shape`/`style`) in `'{disc}: {chosen}'`.

        `prefix`/`qualifier`/`suffix` build the message around that quoted
        phrase (``f"{prefix}{key!r} is not used by {qualifier}'{disc}:
        {chosen}'{suffix}"``) so each caller keeps its own exact wording;
        `extra_notes(key)` appends any further, caller-specific notes (an
        alignment or an arc-centring reason) after the two standard ones.
        Returns whether every key present belonged to `chosen`'s own row.
        """
        ok = True
        for key in sorted(all_keys - table[chosen]):
            if key not in node:
                continue
            owners = sorted(s for s, keys in table.items() if key in keys)
            notes = [
                f"'{disc}: {chosen}' reads: "
                + (", ".join(sorted(table[chosen])) or empty_label),
                f"{key!r} belongs to " + " and ".join(f"'{disc}: {s}'" for s in owners),
            ]
            if extra_notes is not None:
                notes.extend(extra_notes(key))
            self.bag.error(
                code,
                f"{prefix}{key!r} is not used by {qualifier}'{disc}: {chosen}'{suffix}",
                self.doc.span(node, key) or self.doc.span(node),
                notes=notes,
            )
            ok = False
        return ok

    def _check_shape_keys(self, node: dict, shape: str) -> None:
        """Reject a geometry key the chosen `shape:` does not read.

        Without this check, an unread key would be parsed by the schema,
        resolved into the IR, and then never looked at -- so `shape:
        rounded_rectangle` with a `radius:` (rather than `corner_radius:`)
        would draw square corners and say nothing, and `thickness:` on a
        shape left filled would do nothing at all.  ADR 0009's rule applies:
        a design must not quietly lose something it asked for.

        `thickness:` is checked separately from the table because whether it
        is read depends on `filled:`, not on the shape: a `line` and an `arc`
        always use it, any other shape uses it only when outlined.
        """
        self._check_foreign_keys(
            node, shape, SHAPE_GEOMETRY_KEYS, _ALL_SHAPE_GEOMETRY_KEYS,
            code="element", disc="shape",
            extra_notes=lambda key: (
                [_SHAPE_NO_ALIGNMENT_REASON[shape]]
                if key in ("align", "vertical_align") and shape in _SHAPE_NO_ALIGNMENT_REASON
                else []
            ),
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

    def _build_hands_element(self, node: dict, common: dict, path: tuple) -> Element | None:
        """`type: hands` -- places a declared `hands:` set on screen.

        `common["at"]` is already the axis (resolved exactly like any
        element's `at:`); there is no `size:` to build, because the
        element's extent is the disc it sweeps, computed later in
        `wfb.layout`, not a box.
        """
        name = node["hands"]
        element_id = common["id"]
        hand_set = self.hand_sets.get(name)
        if hand_set is None:
            self.hand_sets_block.unknown(
                self.bag, name, self.doc.span(node, "hands"), code="hands",
                message=f"{element_id}: unknown hand set {name!r}",
                note="declared hand sets",
            )
            return None

        seconds = node.get("seconds")
        if seconds is not None and hand_set.second is None:
            declared = ", ".join(n for n, _ in hand_set.hands()) or "(none)"
            self.bag.error(
                "hands",
                f"{element_id}: 'seconds: {seconds}' needs a second hand, but "
                f"hands.{name} declares none",
                self.doc.span(node, "seconds"),
                notes=[f"hands.{name} declares: {declared}"],
            )
            return None
        if seconds is None and hand_set.second is not None:
            seconds = "awake"  # the default
        if seconds == "never" and hand_set.hour is None and hand_set.minute is None:
            # The one combination that draws nothing at all -- refused rather
            # than generated as a method with no drawing in it (no silent
            # no-ops, CLAUDE.md §7).
            self.bag.error(
                "hands",
                f"{element_id}: 'seconds: never' on hands.{name}, which has only a "
                "second hand, draws nothing",
                self.doc.span(node, "seconds"),
                notes=["remove the element, or place a set with an hour or minute hand"],
            )
            return None

        if "low_power" in common["modes"]:
            self.bag.error(
                "hands",
                f"{element_id}: 'modes:' may not include 'low_power' on analog hands",
                self.doc.span(node, "modes") or common["span"],
                notes=["the hour and minute hands never need it -- they change once a "
                       "minute, and the sleeping onUpdate already redraws them",
                       "a second hand while asleep is 'seconds: always', which is not "
                       "implemented yet (docs/limitations.md)"],
            )
            return None

        colors: list[Expression] = []
        for hand_name, hand in hand_set.hands():
            if hand_name == "second" and seconds == "never":
                continue  # never drawn, so its colours reach no lint and no read
            _dedup_append(colors, hand.color)
            for part in hand.parts:
                _dedup_append(colors, part.color)

        return HandsElement(**common, hands=name, seconds=seconds, colors=tuple(colors))

    def _build_pattern_element(self, node: dict, common: dict, path: tuple) -> Element | None:
        """`type: pattern` -- one template, drawn `count:` times, turned
        about `at:` (`pattern: radial`) or stepped along `{dx, dy}`
        (`pattern: linear`).

        Every check here is a build-time error, each driven red by its own
        test: a mismatched `step:`/`start:` shape for this pattern kind, a
        zero or self-overlapping radial step, an out-of-range or
        exhaustive `skip:`/`skip_every:`, `low_power`, and the part rules
        `_build_hand_part` already enforces.  Every branch below returns
        `None` on its own violation rather than falling through to the next
        check, so a design with exactly one mistake gets exactly one error
        (`docs/lore/codegen.md`, "one error, not N").
        """
        element_id = common["id"]
        pattern_kind = node["pattern"]
        count = node["count"]

        if "low_power" in common["modes"]:
            self.bag.error(
                "pattern",
                f"{element_id}: 'modes:' may not include 'low_power' on a pattern",
                self.doc.span(node, "modes") or common["span"],
                notes=["a fixed pattern gains nothing from onPartialUpdate -- its "
                       "geometry never changes -- and its clip would be its whole "
                       "extent"],
            )
            return None

        step_raw = node.get("step")
        if pattern_kind == "radial":
            if isinstance(step_raw, dict):
                self.bag.error(
                    "pattern",
                    f"{element_id}.step: 'pattern: radial' takes an angle for "
                    "'step:' (default 360deg / count), not {dx, dy}",
                    self.doc.span(node, "step"),
                    notes=["'{dx, dy}' is for 'pattern: linear'"],
                )
                return None
            if step_raw is None:
                step_degrees = 360.0 / count
            else:
                step_angle = self._angle(node, "step")
                if step_angle is None:
                    return None  # _angle already reported the real mistake
                step_degrees = step_angle.degrees
            start_angle = self._angle(node, "start") if "start" in node else None
            if "start" in node and start_angle is None:
                return None  # _angle already reported the real mistake
            start_degrees = start_angle.degrees if start_angle is not None else 0.0

            if step_degrees == 0.0:
                self.bag.error(
                    "pattern",
                    f"{element_id}.step: 'step: 0deg' draws every copy on top "
                    "of copy 0",
                    self.doc.span(node, "step") or common["span"],
                    notes=["a radial pattern's whole point is turning between "
                           "copies -- give it a nonzero step, or write one "
                           "element if a single copy is all you want"],
                )
                return None
            if count > 1:
                span = abs(step_degrees) * (count - 1)
                if span >= 360.0 - 1e-9:
                    wrap_index = min(count - 1, math.ceil(360.0 / abs(step_degrees)))
                    self.bag.error(
                        "pattern",
                        f"{element_id}: copies 0 and {wrap_index} land on the same "
                        f"angle -- 'step:' x (count - 1) = {span:g}deg reaches a "
                        "full turn",
                        self.doc.span(node, "step") or common["span"],
                        notes=[f"count: {count}, step: {step_degrees:g}deg -- "
                               "reduce count or step so the copies do not wrap "
                               "past 360deg"],
                    )
                    return None
            step_position = None
        else:
            if "start" in node:
                self.bag.error(
                    "pattern",
                    f"{element_id}.start: not accepted on 'pattern: linear' -- "
                    "only a radial pattern has a start copy angle",
                    self.doc.span(node, "start"),
                    notes=["'step: {dx, dy}' already places copy 0 relative to 'at:'"],
                )
                return None
            if step_raw is None:
                self.bag.error(
                    "pattern",
                    f"{element_id}.step: a linear pattern needs a "
                    "'step: {dx, dy}' between copies",
                    self.doc.span(node) or common["span"],
                    notes=["radial's angle default (360deg / count) has no linear "
                           "equivalent -- there is no natural spacing to assume"],
                )
                return None
            if not isinstance(step_raw, dict):
                self.bag.error(
                    "pattern",
                    f"{element_id}.step: 'pattern: linear' takes {{dx, dy}} for "
                    "'step:', not an angle",
                    self.doc.span(node, "step"),
                    notes=["an angle 'step:' is for 'pattern: radial'"],
                )
                return None
            step_position = self._position(step_raw, node, "step")
            step_degrees = 0.0
            start_degrees = 0.0

        skip = tuple(sorted({int(i) for i in (node.get("skip") or [])}))
        out_of_range = [i for i in skip if i >= count]
        if out_of_range:
            self.bag.error(
                "pattern",
                f"{element_id}.skip: index" + ("es" if len(out_of_range) > 1 else "")
                + f" {', '.join(str(i) for i in out_of_range)} out of range for "
                f"'count: {count}' (0..{count - 1})",
                self.doc.span(node, "skip"),
            )
            return None
        skip_every = node.get("skip_every")
        if skip_every is not None and skip_every > count:
            self.bag.error(
                "pattern",
                f"{element_id}.skip_every: {skip_every} is greater than "
                f"'count: {count}', so it skips nothing",
                self.doc.span(node, "skip_every"),
            )
            return None
        drawn = _drawn_copies(count, skip, skip_every)
        if not drawn:
            self.bag.error(
                "pattern",
                f"{element_id}: 'skip:'/'skip_every:' leave every copy undrawn",
                self.doc.span(node, "skip_every") or self.doc.span(node, "skip")
                or common["span"],
                notes=["remove the element, or skip fewer copies"],
            )
            return None

        ok = True
        element_color: Expression | None = None
        color_declared_and_failed = False
        parts: list[HandPart] = []
        # `copy` -- the index of the copy being drawn -- exists only here,
        # compiled to the generated loop's own index (`_emit_pattern`).
        self.scope.define(expr.COPY, expr.Binding(
            expr.Value(Type.NUMBER), code=PATTERN_LOOP_INDEX, kind="copy"))
        try:
            if "color" in node:
                element_color = self._color_expression(node, "color")
                if element_color is None:
                    ok = False
                    color_declared_and_failed = True
                # `_reject_hand_data_color` does not run here: a pattern
                # colour may read any source, absent-able or not --
                # `_check_pattern_absence` below is the one place that
                # polices absence, for the element as a whole.

            for index, raw_part in enumerate(node.get("parts") or []):
                part = self._build_hand_part(
                    raw_part, element_id, index, element_color, color_declared_and_failed,
                    context="pattern",
                )
                if part is None:
                    ok = False
                    continue
                parts.append(part)
        finally:
            del self.scope.bindings[expr.COPY]

        if ok:
            # Per-copy strings: computed once here, device-independently,
            # the same evaluation the host preview does for an ordinary
            # `text` element (`wfb.preview._text_value`) -- what makes a
            # text part's font subset, its measured extent, and the glyph
            # lint all exact.  `copy` does not need to be scope-bound for
            # this: `expr.evaluate` walks the already-compiled tree directly
            # against a plain dict.
            for part in parts:
                if part.shape != "text":
                    continue
                if part.text_literal is not None:
                    part.texts = (part.text_literal,) * count
                    continue
                texts: list[str] = []
                for i in range(count):
                    value = expr.evaluate(part.text_value.ast, {expr.COPY: i})
                    if value is None:
                        self.bag.error(
                            "pattern",
                            f"{element_id}: a pattern text part's value could "
                            f"not be evaluated for copy {i}",
                            part.text_value.span,
                            notes=["expected a copy-only expression to "
                                   "evaluate for every copy index"],
                        )
                        ok = False
                        break
                    texts.append(formatting.render(
                        part.format or "{}", value, part.text_value.value.type))
                else:
                    part.texts = tuple(texts)

        if not ok:
            return None

        colors: list[Expression] = []
        _dedup_append(colors, element_color)
        for part in parts:
            _dedup_append(colors, part.color)

        element = PatternElement(
            **common,
            pattern=pattern_kind,
            count=count,
            step_angle=step_degrees,
            start_angle=start_degrees,
            step=step_position,
            skip=skip,
            skip_every=skip_every,
            parts=parts,
            color=element_color,
            colors=tuple(colors),
            when_absent=node.get("when_absent"),
        )
        self._check_pattern_absence(node, element)
        return element

    def _check_pattern_absence(self, node: dict, element: PatternElement) -> None:
        """One element-level `when_absent:` check for a pattern, in place of
        a per-colour refusal: a pattern colour may read a source that can be
        absent, so the compiler needs a policy from the author instead of a
        blanket rejection.

        Collects every nullable colour (the element's own `color:`, and
        each part's) and every nullable part `visible:` -- deliberately
        **not** the element's own `visible:`, which keeps its ordinary
        "absent means hidden, no policy" rule (`_visible`'s own docstring) --
        and reports **one** error naming every nullable source found, not
        one per expression, the same "one error, not N" discipline
        `docs/lore/codegen.md` asks for everywhere else.  The wording is the
        house `_check_other_absence` style, adapted: a pattern has no
        `placeholder:`/`fallback:` to offer, only `hide`, and absence hides
        the *whole* pattern (every copy, every part), not just the one
        binding that went missing -- the reading is taken once per frame,
        before the loop.

        The mirror case -- `when_absent: hide` declared but nothing on the
        pattern is ever absent -- reuses `_check_absence`'s own "has no
        effect" wording, so both notes read the same across every element
        kind that has one.
        """
        nullable: list[Expression] = []
        for expression in element.colors:
            if expression.nullable and expression not in nullable:
                nullable.append(expression)
        for part in element.parts:
            if part.visible is not None and part.visible.nullable \
                    and part.visible not in nullable:
                nullable.append(part.visible)

        if nullable:
            if element.when_absent is not None:
                return
            sources = tuple(sorted({
                p for expression in nullable for p in expression.sources
                if catalog.CATALOG[p].guard_needed
            }))
            first = nullable[0]
            self.bag.error(
                "when-absent",
                f"{element.id}: reads {_and_paths(sources)}, which can be "
                "absent, so 'when_absent: hide' is required",
                first.span,
                notes=[
                    "every ActivityMonitor field is nullable and sensors are "
                    "simply missing on some devices, so absence is the normal "
                    "case, not an error",
                    "a pattern has no placeholder or fallback -- absence hides "
                    "the whole pattern, every copy and every part, because the "
                    "reading is taken once per frame, before the loop",
                    "add 'when_absent: hide' to the pattern",
                ],
            )
            return
        if element.when_absent is not None:
            self.bag.note(
                "when-absent",
                f"{element.id}: 'when_absent' has no effect -- nothing this "
                "pattern reads is ever absent",
                self.doc.span(node, "when_absent"),
            )

    def _build_text(self, node: dict, common: dict, path: tuple) -> Element:
        value = self._expression(node, "value") if "value" in node else None
        align, vertical_align = self._alignment(node)
        element = Text(
            **common,
            value=value,
            literal=node.get("text"),
            format=node.get("format"),
            color=self._color_expression(node, "color"),
            align=align,
            vertical_align=vertical_align,
            when_absent=node.get("when_absent"),
            placeholder=node.get("placeholder"),
            fallback=self._expression(node, "fallback") if "fallback" in node else None,
            if_unavailable=node.get("if_unavailable"),
        )
        font_ok = self._resolve_font(node, element)
        if "antialias" in node:
            self._reject_text_antialias(node, element)
        if "curve" in node:
            element.curve = self._build_curve(node, element, font_ok)
        if font_ok and "if_unavailable" in node:
            self._check_text_if_unavailable(node, element)
        if "outline" in node:
            element.outline = self._build_outline(node, "outline", element)
        if value is not None:
            self._check_absence(node, element, value, element.when_absent, element.placeholder,
                                element.fallback)
            self._check_format(node, value, element.format)
        self._check_other_absence(node, element, "color", element.color)
        self._check_reachable_substitute(node, element, "'color'",
                                         (element.value,), (element.color,))
        return element

    def _build_outline(self, node: dict, key: str, element: Text) -> Outline | None:
        """`outline:` on a `text` element (plan 15 §2.3-2.4, §14 slice 1) --
        the stamped ring research 14 measured: the element's string drawn N
        times at small pixel offsets in `outline.color`, then once more,
        unshifted, in the element's own `color:` -- the interior pass it
        already had.

        Two spellings collapse to one `Outline` here (D7, plan 15 §13): a
        bare colour expression (shorthand -- `width: 2` implied, the same
        "the colour is the field that matters most of the time" precedent
        `$defs/configChoice` already gives a `config:` `choices:` entry) or
        an explicit `{color, width}` mapping. `outline.color` goes through
        the very same `_color_expression` `color:` itself uses (D8) -- full
        parity by construction, not a second, narrower implementation.
        `width` is capped at `MAX_OUTLINE_WIDTH` with a build error, not a
        schema `maximum`, so the message can cite the measured evidence the
        cap rests on (D6) the way `_check_curve_font` cites the SDK
        sentence it enforces.
        """
        raw = node.get(key)
        if raw is None or raw == "none":
            return None
        span = self.doc.span(node, key)
        if isinstance(raw, dict):
            color = self._color_expression(raw, "color")
            color_span = self.doc.span(raw, "color") or span
            width = raw.get("width", 2)
            width_span = self.doc.span(raw, "width") or span
        else:
            color = self._color_expression(node, key)
            color_span = span
            width = 2
            width_span = span
        if color is None:
            return None
        if width > MAX_OUTLINE_WIDTH:
            self.bag.error(
                "text-outline",
                f"{element.id}: 'outline: width: {width}' is more than "
                f"{MAX_OUTLINE_WIDTH}px",
                width_span,
                notes=[
                    "every offset set research 14 measured stops at "
                    f"{MAX_OUTLINE_WIDTH}px -- a wider ring was never evidenced "
                    "(docs/research/14-stamped-ring-text.md §1)",
                    "the ring/solid pixel ratio keeps climbing past this width "
                    "with no measurement to say it still reads as an outline "
                    "rather than a second, blockier glyph (§4.1)",
                ],
            )
            return None
        self._check_other_absence(node, element, "outline.color", color, span=color_span)
        return Outline(color=color, width=width)

    def _reject_text_antialias(self, node: dict, element: Text) -> None:
        """`antialias:` on a `text` element -- a per-element key on a shared resource.

        A text element draws through a font declared in `fonts:`, and that
        font is one bitmap resource shared by every element that references
        it (`font: font.clock` is a name, not a private copy) -- so
        anti-aliasing cannot vary per element the way it can on a shape's own
        outline or an icon's own, per-glyph font.  The schema still parses
        `antialias:` here rather than rejecting it as an unknown key, purely
        so this can name the actual font instead of jsonschema's generic
        "unknown key" message: by the time `_resolve_font` above has run,
        `element.font` is the real answer, not a guess.
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

    def _check_curve_keys(self, node: dict, style: str) -> None:
        """Reject a `curve:` key the chosen `style:` does not read -- the same
        `_check_shape_keys`/`_check_graph_style_keys` precedent (`radius:`/
        `direction:` only mean something with a circle to describe, and
        `style: angled` has none).
        """
        if style not in CURVE_STYLE_KEYS:
            return  # the schema has already rejected an unknown style
        self._check_foreign_keys(
            node, style, CURVE_STYLE_KEYS, _ALL_CURVE_STYLE_KEYS,
            code="text-curve", disc="style", empty_label="(nothing)",
            extra_notes=lambda key: (
                ["an angled line has no circle for it to describe -- "
                 "'radius:'/'direction:' only mean something with 'style: radial'"]
                if style == "angled" else []
            ),
        )

    def _build_curve(self, node: dict, element: Text, font_ok: bool) -> Curve | None:
        """`curve:` on a `text` element (plan 11 §2.2): bends it along a line
        (`style: angled`) or around a circle (`style: radial`).  `font_ok` is
        `_resolve_font`'s own answer for this element -- when it is `False`
        the font reference itself already failed and has its own error, so
        the font-kind check below is skipped rather than piling a second,
        misleading error onto the same mistake (the `_NamedBlock` cascade
        discipline, `docs/lore/codegen.md`).
        """
        raw = node["curve"]
        span = self.doc.span(node, "curve")
        style = raw["style"]
        self._check_curve_keys(raw, style)
        angle = self._angle(raw, "angle")
        if angle is None:
            return None
        radius = self._length(raw, "radius") if style == "radial" else None
        direction = str(raw.get("direction", "clockwise")) if style == "radial" else None
        if font_ok:
            self._check_curve_font(element, span)
        if element.vertical_align == "bottom" and style == "angled":
            self.bag.error(
                "text-curve",
                f"{element.id}: 'vertical_align: bottom' is not accepted under "
                "'curve: {style: angled}'",
                self.doc.span(node, "vertical_align") or span,
                notes=[
                    "an upright text's 'bottom' is implemented by subtracting the "
                    "font's own height from the anchor in screen space -- once the "
                    "baseline is rotated that subtraction no longer points along "
                    "the text's own vertical axis, so the ink would land somewhere "
                    "this compiler cannot predict",
                    "use 'top' or 'center' instead ('curve: {style: radial}' "
                    "accepts all three)",
                ],
            )
        return Curve(style=style, angle=angle, radius=radius, direction=direction)

    def _font_kind_note(self, element: Text) -> str:
        """The one-line description of `element`'s resolved font used by both
        `_check_curve_font` and `_check_text_if_unavailable` -- both need to
        say what kind of font a font: reference actually is, once resolved."""
        if element.font_is_custom:
            return (f"'font: font.{element.font}' is a baked bitmap font, "
                    "declared with 'source:'")
        return f"'font: {element.font}' is one of the platform's fixed system fonts"

    def _check_curve_font(self, element: Text, span: Span | None) -> None:
        """`curve:` requires `font:` to name a `face:` (vector) font --
        `Dc.drawAngledText`/`Dc.drawRadialText` refuse a resource font
        outright.  Only called once `font_ok` says the reference itself
        resolved, so `self.fonts[element.font]` is safe to index when
        `font_is_custom` is true (`_font_reference` only ever returns a
        custom reference for a name already present in `self.fonts`).
        """
        if element.font_is_custom and self.fonts[element.font].is_vector:
            return
        self.bag.error(
            "text-curve",
            f"{element.id}: 'curve:' needs a 'face:' (vector) font",
            span,
            notes=[
                "\"These APIs only support scalable fonts and do not support "
                "custom fonts loaded as resources\" ($CIQ_SDK/doc/docs/"
                "Core_Topics/Graphics.html §Scalable Fonts)",
                self._font_kind_note(element),
                "declare this font with 'face:' instead of 'source:', or point "
                "'font:' at one that already does",
            ],
        )

    def _check_text_if_unavailable(self, node: dict, element: Text) -> None:
        """`if_unavailable:` on a `text` element -- only meaningful when the
        referenced font is a `face:` (vector) font: nothing about a baked or
        system font can ever be unavailable, so accepting this would promise
        a check that never runs (the same reasoning `_build_baked_font`
        applies to the key on the `fonts:` entry itself).  Only called once
        `font_ok` says the reference resolved -- see `_check_curve_font`.
        """
        if element.font_is_custom and self.fonts[element.font].is_vector:
            return
        self.bag.error(
            "text-curve",
            f"{element.id}: 'if_unavailable:' is not accepted here",
            self.doc.span(node, "if_unavailable"),
            notes=[
                "'if_unavailable:' governs a device-resident 'face:' font "
                "failing to publish a face on some target device -- nothing "
                "about a baked or system font can ever be unavailable",
                self._font_kind_note(element),
                "drop 'if_unavailable:', or point 'font:' at a 'face:' font",
            ],
        )

    def _build_pattern_curve(
        self, node: dict, part_where: str, font_is_vector: bool, vertical_align: str,
        font_ok: bool,
    ) -> Curve | None:
        """`curve:` on a pattern's `shape: text` part (plan 11 slice 2) --
        the same bend `Builder._build_curve` gives a standalone `text`
        element, reusing its `angle:`/`radius:`/`direction:` parsing and
        `_check_curve_keys`.  `font_is_vector`/`font_ok` mirror `_build_
        curve`'s own `element.font_is_custom and self.fonts[...].is_vector`
        check and its `font_ok` parameter respectively.

        **What is different from a `text` element, and the real design
        decision of this slice:** the angle authored here is in the
        template's own *local* frame, exactly as a radial pattern's own
        `arc` part authors `start_angle` for copy 0 alone and lets the
        device add `i * step` at runtime (`wfb.emit.monkeyc.rotated.
        _emit_pattern_part`'s arc branch). `wfb.layout.Resolver.
        _resolve_hand_part` stores this angle un-composed (`part.curve_
        angle_garmin`, this part's own local Garmin-converted angle); the
        composition with the copy's own rotation -- `part.curve_angle_
        garmin - (element.start_angle + i * element.step_angle)` -- happens
        at codegen time (`_emit_pattern_text_angle_expr`) and, for the lint
        boxes, at layout time (`wfb.layout._pattern_part_ink`). This is what
        lets twelve hour numerals share one `angle: 0deg` (tangent to each
        copy's own radius) instead of the author writing twelve different
        angles -- the whole point of putting `curve:` on the *part* rather
        than asking for one `text` element per numeral. A `pattern: linear`
        template never rotates at all (`element.start_angle`/`.step_angle`
        are always `0.0` there, `wfb.layout.Resolver._resolve_pattern`), so
        every copy simply keeps this part's own local angle unchanged --
        the "no copy angle to compose with" case falls out of the same
        formula for free, with no special-casing needed here.
        """
        raw = node["curve"]
        span = self.doc.span(node, "curve")
        style = raw["style"]
        self._check_curve_keys(raw, style)
        angle = self._angle(raw, "angle")
        if angle is None:
            return None
        radius = self._length(raw, "radius") if style == "radial" else None
        direction = str(raw.get("direction", "clockwise")) if style == "radial" else None
        if font_ok and not font_is_vector:
            self.bag.error(
                "text-curve",
                f"{part_where}: 'curve:' needs a 'face:' (vector) font",
                span,
                notes=[
                    "\"These APIs only support scalable fonts and do not support "
                    "custom fonts loaded as resources\" ($CIQ_SDK/doc/docs/"
                    "Core_Topics/Graphics.html §Scalable Fonts)",
                    "declare this font with 'face:' instead of 'source:', or point "
                    "'font:' at one that already does",
                ],
            )
        if vertical_align == "bottom" and style == "angled":
            self.bag.error(
                "text-curve",
                f"{part_where}: 'vertical_align: bottom' is not accepted under "
                "'curve: {style: angled}'",
                self.doc.span(node, "vertical_align") or span,
                notes=[
                    "an upright text's 'bottom' is implemented by subtracting the "
                    "font's own height from the anchor in screen space -- once the "
                    "baseline is rotated that subtraction no longer points along "
                    "the text's own vertical axis, so the ink would land somewhere "
                    "this compiler cannot predict",
                    "use 'top' or 'center' instead ('curve: {style: radial}' "
                    "accepts all three)",
                ],
            )
        return Curve(style=style, angle=angle, radius=radius, direction=direction)

    def _check_pattern_text_if_unavailable(
        self, node: dict, part_where: str, font_is_vector: bool,
    ) -> None:
        """`if_unavailable:` on a pattern's `shape: text` part -- the same
        "only meaningful on a face: font" rule `_check_text_if_unavailable`
        gives a standalone `text` element's own key.  Only called once
        `font_ok` says the font reference itself resolved (mirrors `_check_
        text_if_unavailable`'s own precondition).
        """
        if font_is_vector:
            return
        self.bag.error(
            "text-curve",
            f"{part_where}: 'if_unavailable:' is not accepted here",
            self.doc.span(node, "if_unavailable"),
            notes=[
                "'if_unavailable:' governs a device-resident 'face:' font "
                "failing to publish a face on some target device -- nothing "
                "about a baked or system font can ever be unavailable",
                "drop 'if_unavailable:', or point 'font:' at a 'face:' font",
            ],
        )

    def _build_progress(self, node: dict, common: dict, path: tuple) -> Element:
        value = self._expression(node, "value")
        maximum = self._expression(node, "max")
        align, vertical_align = self._alignment(node)
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
            align=align,
            vertical_align=vertical_align,
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

    def _resolve_icon_name(self, name: str, span: Span | None) -> str | None:
        """A catalogue name -> its codepoint, or `None` plus a reported error.

        The shared "unknown icon" diagnostic: used by `_build_icon`'s own
        inline check and by a `complication_slot` choice's `icon:` override
        (`_resolve_choice_icon_override`), so both report the exact same
        message rather than a second, slightly-different one for what is
        the same mistake either place it is made.
        """
        codepoint = icons.resolve_codepoint(name)
        if codepoint is None:
            self.bag.error(
                "icon",
                f"unknown icon {name!r}",
                span,
                notes=[
                    "the catalogue has: " + ", ".join(icons.names()),
                    "for a glyph the catalogue does not name, write "
                    "'glyph: \"U+XXXX\"' instead -- see wfb/assets/icons/README.md",
                ],
            )
        return codepoint

    def _resolve_icon_glyph(self, raw: str, span: Span | None) -> str | None:
        """`"U+F0BC"` -> the character, or `None` plus a reported error.

        The shared `glyph:` diagnostics: used by `_build_glyph_icon`'s own
        inline checks and by a `complication_slot` choice's `glyph:`
        override (`_resolve_choice_icon_override`), which needs the
        identical "not that notation" / "not in the font" messages, not a
        second copy of them.
        The "this glyph is already a catalogue name" note is a `bag.note`,
        not an error, so it does not affect the caller's success/failure
        return either way.
        """
        character = icons.parse_codepoint(raw)
        if character is None:
            self.bag.error(
                "icon",
                f"glyph must be a codepoint written 'U+XXXX', not {raw!r}",
                span,
                notes=["e.g. glyph: \"U+F0BC\" -- 1 to 6 hex digits, case-insensitive",
                       "to use a name from the built-in catalogue, write 'icon:' instead"],
            )
            return None
        if not icons.font_has(character):
            self.bag.error(
                "icon",
                f"the icon font has no glyph at {raw.upper()}",
                span,
                notes=[
                    "checked against the icon font's own character map, the same "
                    "way a custom text font's coverage is checked",
                    "https://www.nerdfonts.com/cheat-sheet lists the codepoints this "
                    "font actually carries",
                ],
            )
            return None
        named = icons.name_for_codepoint(character)
        if named is not None:
            self.bag.note(
                "icon",
                f"glyph {raw.upper()} is in the catalogue as {named!r} -- "
                f"'icon: {named}' says the same thing and survives a font update",
                span,
            )
        return character

    def _resolve_choice_icon_override(
        self, item: dict, what: str, fallback_span: Span | None,
    ) -> "icons.SlotIcon | None | object":
        """A `config: data:` choice's own `icon:`/`glyph:`, if it declares
        one.

        Returns `_NO_ICON_OVERRIDE` when the choice names neither key (fall
        back to `wfb.icons.COMPLICATION_ICON`), `_ICON_OVERRIDE_ERROR` when
        one was named and did not resolve (already reported; the caller
        rejects the whole slot the same way any other bad choice does),
        `None` for an explicit `icon: none` (remove any catalogue default),
        or a real `icons.SlotIcon`.  Reuses `_resolve_icon_name`/
        `_resolve_icon_glyph` -- the exact validation (and messages) a plain
        `icon` element's own `icon:`/`glyph:` get -- rather than a second,
        parallel set of diagnostics for what is the same two keys.
        """
        has_icon = "icon" in item
        has_glyph = "glyph" in item
        if not has_icon and not has_glyph:
            return _NO_ICON_OVERRIDE
        if has_icon and has_glyph:
            self.bag.error(
                "config",
                f"{what}: 'icon:' and 'glyph:' are mutually exclusive",
                fallback_span,
                notes=["'icon:' names a catalogue entry; 'glyph:' is any codepoint "
                       "in the icon font -- pick one"],
            )
            return _ICON_OVERRIDE_ERROR
        if has_icon:
            raw_icon = item["icon"]
            span = self.doc.span(item, "icon") or fallback_span
            if raw_icon == "none":
                return None
            if not isinstance(raw_icon, str):
                self.bag.error(
                    "config", f"{what}.icon: expected a string, got {raw_icon!r}", span)
                return _ICON_OVERRIDE_ERROR
            codepoint = self._resolve_icon_name(raw_icon, span)
            if codepoint is None:
                return _ICON_OVERRIDE_ERROR
            return icons.SlotIcon(raw_icon, codepoint)
        raw_glyph = str(item["glyph"])
        span = self.doc.span(item, "glyph") or fallback_span
        character = self._resolve_icon_glyph(raw_glyph, span)
        if character is None:
            return _ICON_OVERRIDE_ERROR
        return icons.SlotIcon(icons.codepoint_key(character), character)

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
                       "'glyph' is any codepoint in the icon font, written "
                       "'U+XXXX' -- for the ~10,000 glyphs the catalogue does not name",
                       "'icon_for' chooses one at runtime from a bound value -- see "
                       "wfb.catalog.WEATHER_CONDITION_SOURCES for what it accepts"],
            )

        size = self._baked_size_length(
            node, "size", code="icon", label="icon size",
            note="an icon's font is baked once, before layout runs, so its size "
                 "cannot depend on a parent box (%) or an element's own font (pt)",
        )

        align, vertical_align = self._alignment(node)
        # Shared by every branch below: `**placement` is the four keys an
        # `IconElement` needs regardless of which of 'icon'/'icon_for'/
        # 'glyph' chose it -- one `_color_expression(node, "color")` call
        # instead of one per branch.
        placement = dict(
            size=size, color=self._color_expression(node, "color"),
            align=align, vertical_align=vertical_align,
        )

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
                **common, icon=None, codepoint=icons.FALLBACK_CODEPOINT,
                value_for=value_for, **placement,
            )

        if has_glyph:
            return self._build_glyph_icon(node, common, placement)

        codepoint = self._resolve_icon_name(name, self.doc.span(node, "icon"))
        if codepoint is None:
            codepoint = icons.FALLBACK_CODEPOINT

        return IconElement(**common, icon=name, codepoint=codepoint, **placement)

    def _build_glyph_icon(self, node: dict, common: dict, placement: dict) -> Element:
        """`glyph: "U+F0BC"` -- a codepoint the catalogue does not name.

        The only way to reach a glyph the catalogue does not name, and spelled
        so that it survives a code review: `U+F0BC` is greppable and visible,
        where the character itself renders as a blank box (or nothing) in
        most editors and diffs.  `icon:` does not accept a raw pasted
        character; this is the one place a codepoint outside the catalogue
        belongs.  Everything downstream -- baking, sizing, the per-codepoint
        font key -- is identical once it is a character, because this is
        exactly what a catalogue name resolves to.
        """
        raw = str(node.get("glyph"))
        span = self.doc.span(node, "glyph")
        character = self._resolve_icon_glyph(raw, span)
        if character is None:
            character = icons.FALLBACK_CODEPOINT
        return IconElement(**common, icon=raw.upper(), codepoint=character, **placement)

    def _check_slot_color_absence(
        self, node: dict, element: "ComplicationSlot", key: str,
        color: Expression | None, note: str,
    ) -> None:
        """A complication_slot's `color:`/`icon_color:` may not read
        anything absent-able -- neither has a `when_absent:` of its own to
        fall back through, unlike the pulled reading itself (shared by both
        colours in `_build_complication_slot`; `note` carries the one
        wording difference between them -- "colour ... its own" vs.
        "colours ... their own" -- so the messages stay exactly what they
        were before this was one method).
        """
        if color is None or not color.nullable:
            return
        self.bag.error(
            "complication-slot",
            f"{element.id}: '{key}:' reads {color.text!r}, which can be absent",
            self.doc.span(node, key),
            notes=[
                note,
                "guard it in the expression instead, e.g. "
                "\"x != null and x > 100 ? palette.hot : palette.fg\"",
            ],
        )

    def _build_complication_slot(self, node: dict, common: dict, path: tuple) -> Element:
        """`type: complication_slot` -- the element half of the native Data
        axis (docs/research/09-data-library-and-config-axes.md §4).

        Most of what makes every other element kind checkable at build time
        -- a fixed source, a static type -- does not exist here: which
        `complication.<name>` the wearer picked is only known on-device.  So
        this validates the *slot reference* and the authoring keys that do
        not depend on the choice (`icon_size:`, `format:`), and leaves
        everything about the pulled value itself to
        `wfb.emit.monkeyc._emit_complication_slot`, which reads it fresh
        every frame the same way any other `complication.*` source does.
        """
        slot_raw = node["slot"]
        slot = self._resolve_slot_reference(str(slot_raw), self.doc.span(node, "slot"))

        icon_size = self._baked_size_length(
            node, "icon_size", code="complication-slot", label="icon_size",
            note="an icon's font is baked once, before layout runs, so its size "
                 "cannot depend on a parent box (%) or an element's own font (pt)",
        )
        # 'icon_size:' + 'choices: any' resolves against
        # `wfb.icons.COMPLICATION_ICON`, which covers all 42 native types
        # (`ConfigDataSlot.icons`); a Connect IQ-app complication (or any
        # native type a future SDK adds that this table does not yet know)
        # simply is not one of the switch's cases and draws no icon, the
        # same "unmapped means text-only" contract every other slot already
        # has for an individual choice.

        icon_position = node.get("icon_position", "left")
        icon_gap = self._baked_size_length(
            node, "icon_gap", code="complication-slot", label="icon_gap",
            note="the same restriction 'icon_size:' has -- an icon's font is "
                 "baked once, before layout runs, so the gap that sits "
                 "against it cannot depend on a parent box (%) or an "
                 "element's own font (pt)",
        )
        if icon_gap is not None and icon_gap.value < 0:
            self.bag.error(
                "complication-slot",
                f"icon_gap must not be negative, got {icon_gap.value:g}{icon_gap.unit}",
                self.doc.span(node, "icon_gap"),
            )
            icon_gap = None

        icon_color = self._color_expression(node, "icon_color")

        # None of 'icon_position:'/'icon_gap:'/'icon_color:' means anything
        # without an icon to place, space or colour -- checked against
        # whether the author wrote 'icon_size:' at all, not against whatever
        # it resolved to, so a *different* mistake in 'icon_size:' (a bad
        # unit, say) is reported once, not doubled up with a second "needs
        # icon_size:" complaint about the same missing icon.
        if "icon_size" not in node:
            for key in ("icon_position", "icon_gap", "icon_color"):
                if key not in node:
                    continue
                self.bag.error(
                    "complication-slot",
                    f"{common['id']}: '{key}:' needs 'icon_size:'",
                    self.doc.span(node, key),
                    notes=[f"'{key}:' only means something for the icon this slot draws, "
                           "and there is no icon to place, space or colour without "
                           "'icon_size:'",
                           f"add 'icon_size:', or drop '{key}:'"],
                )
            icon_position = "left"
            icon_gap = None
            icon_color = None

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
                    "this element renders the value as the watch reports it "
                    "(a Float rounded to three significant figures); use 'label:' "
                    "and/or 'unit:' for the extra context a format string would "
                    "otherwise add",
                ],
            )

        color = self._color_expression(node, "color")
        align, vertical_align = self._alignment(node)
        element = ComplicationSlot(
            **common,
            slot=(slot.name if slot is not None else str(slot_raw)),
            icon_size=icon_size,
            color=color,
            icon_position=icon_position,
            icon_gap=icon_gap,
            icon_color=icon_color,
            label=node.get("label", "none"),
            unit=bool(node.get("unit", False)),
            when_absent=node.get("when_absent", "hide"),
            placeholder=node.get("placeholder"),
            align=align,
            vertical_align=vertical_align,
        )
        font_ok = self._resolve_font(node, element)
        if font_ok and element.font_is_custom and self.fonts[element.font].is_vector:
            # A `face:` (vector) font is only drawable through
            # `Dc.drawText`/`drawAngledText`/`drawRadialText` on a `text`
            # element (`Builder._check_curve_font`, `Text.curve`) --
            # `_emit_complication_slot` has no equivalent path for one, and
            # nothing about "the next slice" applies here the way it does
            # to a pattern's `shape: text` part (`_build_hand_part`): a
            # complication_slot's reading is never known at build time, so
            # there is no string to bake a sheet or measure a vector face
            # against either way.
            self.bag.error(
                "complication-slot",
                f"{element.id}: 'font: font.{element.font}' is a 'face:' "
                "(vector) font -- not accepted on a complication_slot",
                self.doc.span(node, "font"),
                notes=[
                    "a vector font is drawn straight from the device's own "
                    "resident face through Dc.drawText/drawAngledText/"
                    "drawRadialText -- a complication_slot draws its reading "
                    "through a different path that only accepts a baked "
                    "bitmap font or one of the platform's fixed system fonts",
                    "a vector font is only usable on a 'text' element",
                    "declare this font with 'source:' instead, or point "
                    "'font:' at a baked or system font",
                ],
            )

        if element.on_hold is not None and element.on_hold != HOLD_AUTO:
            # A slot always shows whatever the wearer picked, so a *fixed*
            # hold target would silently disagree with what is on screen the
            # moment the wearer repoints it -- exactly the "an icon means
            # what its shape says" trap CLAUDE.md already records for content
            # bugs, transplanted onto a launch target instead of a picture.
            # `auto` is the only spelling that cannot go stale, because it is
            # resolved on-device from this slot's own current id
            # (`Complications.exitTo` on `config_field("data_" + slot)`), not
            # from `Source.launch_complication` at build time the way every
            # other element's `auto` is (`Builder._hold_auto_sources`
            # deliberately does not cover `ComplicationSlot` for exactly this
            # reason -- see `Builder._resolve_hold_auto`).
            self.bag.error(
                "complication-slot",
                f"{element.id}: 'on_hold:' on a complication_slot only accepts "
                f"'auto', not {element.on_hold!r}",
                element.span,
                notes=[
                    "a slot already draws whatever complication the wearer chose in "
                    "the native editor -- opening a fixed, different glance on hold "
                    "would silently disagree with what is on screen the moment the "
                    "wearer repoints it",
                    "'on_hold: auto' opens the glance the wearer's own current pick "
                    "belongs to (Complications.exitTo on this slot's own id), "
                    "resolved fresh on every hold rather than fixed at build time",
                    "to always launch one fixed glance regardless of what this slot "
                    "shows, bind a plain 'text'/'icon' element to the matching "
                    "'complication.<name>' source and put 'on_hold: <name>' there "
                    "instead",
                ],
            )
            element.on_hold = None

        if color is None:
            self._require(node, "color", "a complication_slot needs a color")
        else:
            self._check_slot_color_absence(
                node, element, "color", color,
                "a complication_slot's colour has no 'when_absent:' of its own "
                "-- 'when_absent:'/'placeholder:' governs the pulled reading, "
                "not the element's appearance",
            )

        self._check_slot_color_absence(
            node, element, "icon_color", icon_color,
            "a complication_slot's colours have no 'when_absent:' of their "
            "own -- 'when_absent:'/'placeholder:' governs the pulled "
            "reading, not the element's appearance",
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

        align, vertical_align = self._alignment(node)
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
            align=align,
            vertical_align=vertical_align,
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

        `range: 14d` on `steps` is an error, not a clamp: silently drawing 7
        when 14 was asked for is exactly the quiet wrongness this
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
        self._check_foreign_keys(
            node, style, GRAPH_STYLE_KEYS, _ALL_GRAPH_STYLE_KEYS,
            code="graph", disc="style", empty_label="(nothing)",
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
                             bound: Expression | None, span: Span | None = None) -> None:
        """A nullable binding outside `value` still needs an explicit `when_absent:`.

        `_check_absence` above only ever runs for `value` -- without this
        check, a nullable `color`/`track_color` would sail through
        validation with no policy at all.  Codegen (`wfb.emit.monkeyc`'s
        `ReadPlan.other_guards`) always treats an absent non-value binding
        as 'hide', regardless of which policy is chosen for the value,
        because there is no sensible placeholder or fallback for a colour.
        The requirement here is only that the author has consciously picked
        *something*, the same ADR 0005 3 contract `value` already has -- not
        that the chosen policy's exact semantics (placeholder text, a
        substitute number) apply to a colour, which they do not.

        `span` overrides `self.doc.span(node, key)` -- needed for a binding
        that does not live at `node[key]` directly, such as `outline.color`
        (`key` is `'outline.color'` for the message, but the real YAML node
        is `outline:`'s own sub-mapping, or `node['outline']` itself under
        the shorthand spelling; `Builder._build_outline` works out which and
        passes the right span in).
        """
        if bound is None or not bound.nullable:
            return
        if getattr(element, "when_absent", None) is not None:
            return
        self.bag.error(
            "when-absent",
            f"{element.id}: {key!r} reads {bound.text!r}, which can be absent, so "
            "'when_absent:' is required",
            span if span is not None else self.doc.span(node, key),
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
                formatting.parse_time(formatting.strip_braces(spec), codes)
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
        syntax_error = False
        try:
            try:
                node_ast = expr.parse(text)
            except expr.ExprError:
                # A *syntax* failure, as opposed to an unknown source or a type
                # error below.  Worth telling apart: `value: XX%` is almost
                # always someone reaching for literal text, while
                # `value: activity.stepss` is a real typo in a real expression
                # and must not be told to use `text:` instead.
                syntax_error = True
                raise
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
            # typo report: a bare `color: config.colors` (missing its role)
            # or a misspelled role deserves better than a "did you mean"
            # guess against an unrelated name.
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
            if syntax_error and key == "value":
                notes = list(notes) + [
                    "'value:' is an expression over data sources, not literal text -- "
                    "for a fixed string use 'text:' instead:\n"
                    '    text: "XX%"',
                    "note that YAML strips the quotes, so `value: 'XX%'` reaches the "
                    "expression parser as a bare XX%",
                ]
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

        Shared by every element's `font:` (`text`, `complication_slot`), so
        they cannot disagree about what a font name means.

        Returns ``None`` when the name does not resolve.  The one subtlety is
        what happens for a font that *was* declared and then rejected by
        `_build_fonts` (a missing `source:`, a bad `size:`, `align:` without
        `monospace:`): the build is already failing, with an error pointing
        at the real mistake in the `fonts:` block, so this stays quiet
        rather than adding one more error per element blaming the element
        for it -- see `_NamedBlock`'s docstring for why the name still
        resolves here.
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
        self.fonts_block.unknown(
            self.bag, key, span, code="font",
            message=f"unknown font {name!r}",
            note="declared fonts", prefix="font.",
        )
        return None

    def _resolve_font(self, node: dict, element: Text | HandPart) -> bool:
        """Set `.font`/`.font_is_custom` from `node["font"]`, shared by a
        `Text` element and a `shape: text` pattern part -- both carry the
        same two fields, so this is the one place either can go through
        `_font_reference` without a second copy of its diagnostic.

        Returns whether the reference is trustworthy: `True` when no
        `font:` was written at all (the element keeps its class-default
        system font) or the name resolved; `False` only when an explicit
        `font:` failed to resolve, which already has its own error against
        the real mistake. A `Text`-only caller (`_build_curve`,
        `_check_text_if_unavailable`) uses this to skip a further
        font-kind check that would otherwise blame `element.font`'s
        untouched default for a mistake reported one line up -- the same
        "declared and rejected stays quiet" cascade `_NamedBlock` follows.
        """
        raw = node.get("font")
        if raw is None:
            return True
        resolved = self._font_reference(str(raw), self.doc.span(node, "font"))
        if resolved is not None:
            element.font, element.font_is_custom = resolved
            return True
        return False

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

    def _baked_size_length(
        self, node: dict, key: str, *, code: str, label: str, note: str,
    ) -> Length | None:
        """`key`'s length, rejected unless it is `px`/`%r` -- shared by every
        size baked before layout runs: an icon's own `size:`
        (`_build_icon`), and a complication_slot's `icon_size:`/`icon_gap:`
        (`_build_complication_slot`).  `label` is the quantity name the
        message leads with (``'icon size'``/``'icon_size'``
        /``'icon_gap'``); `note` is the one explanatory note, worded enough
        differently between the three ("its size" vs. "the gap that sits
        against it") that this takes it as a parameter rather than deriving
        one.
        """
        length = self._length(node, key)
        if length is not None and length.unit not in units.SIZE_UNITS:
            self.bag.error(code, f"{label} must be px or %r, not {length.unit}",
                           self.doc.span(node, key), notes=[note])
            return None
        return length

    def _angle(self, node: dict, key: str) -> Angle | None:
        if key not in node:
            return None
        try:
            return Angle.parse(node[key], what=key)
        except UnitError as exc:
            self.bag.error("units", str(exc), self.doc.span(node, key))
            return None


def _dedup_append(colors: list[Expression], color: Expression | None) -> None:
    """Append `color` to `colors` in first-use order, unless it is `None` or
    already present -- the "every effective colour, deduplicated" accumulation
    `HandsElement.colors`/`PatternElement.colors` each build."""
    if color is not None and color not in colors:
        colors.append(color)


def _and_paths(paths: tuple[str, ...]) -> str:
    """``'a'``, ``'a' and 'b'``, ``'a', 'b' and 'c'`` -- for a diagnostic."""
    quoted = [repr(path) for path in paths]
    if len(quoted) == 1:
        return quoted[0]
    return ", ".join(quoted[:-1]) + " and " + quoted[-1]


def build(doc: YamlDocument, bag: Bag) -> Face | None:
    return Builder(doc, bag).build()


def _offset_span(span: Span | None, text: str, offset: int) -> Span | None:
    """Shift a span to point inside the expression string, not just at its key."""
    if span is None:
        return None
    return Span(span.path, span.line, span.col + offset)
