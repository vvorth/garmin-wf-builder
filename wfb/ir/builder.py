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

import re
from collections.abc import Callable
from pathlib import Path

from .. import catalog, complications, expr, formatting, icons, kinds, units
from ..catalog import Type
from ..desugar import layout_ids
from ..diagnostics import Bag, Span
from ..palette import Color, ColorError
from ..units import Angle, Length, UnitError
from ..yamlsrc import YamlDocument

from .model import (
    AodOverride, ColorScheme, ComplicationSlot, ConfigChoice, ConfigColor, ConfigDataSlot,
    ConfigStyle, Curve, Element, Expression, Face, FontSpec, Group,
    HOLD_AUTO, Hand, HandPart, HandSet, LayoutDecl, MAX_OUTLINE_WIDTH,
    Outline, ROLE_VALUE, ROLE_VISIBLE,
    PatternElement, Position, SYSTEM_FONTS, Shape, Size, StyleEntry, Text,
    authored_draw_order, walk_elements,
)
from .naming import (
    _pascal, config_field, element_const_prefix, element_method_name, local_name,
)

#: Sentinels for `Builder._resolve_choice_icon_override`'s result: "no
#: `icon:`/`glyph:` override declared" and "declared, invalid, already
#: reported".  Not `None`, which is itself a legitimate answer
#: (`icon: none`, an explicit "no icon").
_NO_ICON_OVERRIDE = object()
_ICON_OVERRIDE_ERROR = object()

#: The same table for a hand part -- the four rotatable primitives, in the
#: hand's own frame.  `polygon` has no `at`: its vertices are already
#: positions in that frame.  `align`/`vertical_align` only on the
#: box-drawn `rectangle`/`circle` (resolved by
#: `Resolver._resolve_hand_part` before rounding).
HAND_PART_GEOMETRY_KEYS = {
    "polygon": frozenset({"points"}),
    "rectangle": frozenset({"at", "size", "align", "vertical_align"}),
    "line": frozenset({"at", "to"}),
    "circle": frozenset({"at", "radius", "align", "vertical_align"}),
}
_ALL_HAND_PART_GEOMETRY_KEYS = frozenset().union(*HAND_PART_GEOMETRY_KEYS.values())

#: Hand part shapes that accept `filled:` at all (`line` has no notion of it).
HAND_PART_FILLED_SHAPES = frozenset({"polygon", "rectangle", "circle"})

#: Shapes for which `filled: false` is refused -- a rectangle part becomes a
#: polygon at build time, and Dc has no `drawPolygon`.
HAND_PART_NO_UNFILLED = frozenset({"polygon", "rectangle"})

#: `shape:` values the hand-part schema accepts only so that this
#: dedicated message fires instead of a blunt enum mismatch.
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

#: A `type: pattern` template part: the hand vocabulary plus `arc` (a
#: copy's start angle is a plain runtime Float) and `text` (upright glyphs
#: whose anchor turns or steps with the copy; the glyphs themselves turn
#: too with a `face:` font and `curve:`).  `value` xor `text` is enforced
#: by `Builder._build_text_part`, not this table.
PATTERN_PART_GEOMETRY_KEYS = {
    **HAND_PART_GEOMETRY_KEYS,
    #: No `at` -- an arc part is always centred on the copy's own origin.
    "arc": frozenset({"radius", "start_angle", "sweep"}),
    "text": frozenset({"at", "value", "text", "format", "font", "align", "vertical_align",
                       "curve", "if_unavailable", "outline"}),
}
_ALL_PATTERN_PART_GEOMETRY_KEYS = frozenset().union(*PATTERN_PART_GEOMETRY_KEYS.values())

#: The extra note `_check_hand_part_keys` adds when the rejected key is
#: `align`/`vertical_align` -- shared by hand and pattern parts (`arc` is
#: only ever reached by a pattern part).
_HAND_PART_NO_ALIGNMENT_REASON = {
    "polygon": "every vertex is its own position; there is no single 'at:' "
               "to align on -- a polygon part has no 'at:' of its own either",
    "line": "'at:' and 'to:' are the part's two ends",
    "arc": "an arc part is always centred on the copy's own origin -- there "
           "is no 'at:' to offset in the first place",
}

#: Like `HAND_PART_REJECTED_SHAPES`, minus `arc` and `text`, which a pattern
#: part can draw.
PATTERN_PART_REJECTED_SHAPES = {
    "rounded_rectangle": "no Dc call draws a rotated or translated rounded "
                          "rectangle -- approximate it with 'polygon'",
    "ellipse": "no Dc call draws a rotated or translated ellipse -- "
               "approximate it with 'polygon'",
    "icon": "a bitmap font cannot rotate or translate through this loop",
}

#: Which key each `curve:` `style:` reads: only `radial` has a circle for
#: `radius:`/`direction:` to describe.  The schema still parses both under
#: `angled` so `_check_curve_keys` can name the actual mistake.
CURVE_STYLE_KEYS = {
    "angled": frozenset(),
    "radial": frozenset({"radius", "direction"}),
}
_ALL_CURVE_STYLE_KEYS = frozenset().union(*CURVE_STYLE_KEYS.values())

#: Shared notes of every "can be absent, so 'when_absent:' is required" error.
_ABSENCE_IS_NORMAL = ("every ActivityMonitor field is nullable and sensors are simply missing "
                      "on some devices, so absence is the normal case, not an error")
_WHEN_ABSENT_CHOICES = ("choose one of: hide | placeholder (with 'placeholder:') | fallback "
                        "(with 'fallback:')")

#: The note on an icon size given in a unit other than `px`/`%r`.
_ICON_SIZE_NOTE = ("an icon's font is baked once, before layout runs, so its size "
                   "cannot depend on a parent box (%) or an element's own font (pt)")

#: Matches `expr.check`'s "unknown data source" message for exactly
#: `config.colors` or `config.colors.<role>`.  Group 1 is `""` for the bare
#: axis, or `.<role>` for a bad role -- `Builder._expression` turns either
#: into a domain-specific error.
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


def _aod_kind(element: Element) -> tuple[str | None, str | None, bool]:
    """``(kind, shape, literal_text)`` of a built element, in the same terms
    `Builder._aod_refusal` reads off a raw node.  `shape`/`literal_text` are
    each one kind's own extra fact (a `Shape`'s own `.shape`, a `Text`'s own
    "was this a fixed 'text:'"); every other kind passes `None`/`False`,
    which is also what its own `aod_refusal` hook ignores."""
    kind = kinds.for_element(element)
    shape = element.shape if isinstance(element, Shape) else None
    literal_text = isinstance(element, Text) and element.value is None
    return kind.name, shape, literal_text


class Builder:
    def __init__(self, doc: YamlDocument, bag: Bag) -> None:
        self.doc = doc
        self.bag = bag
        # Named top-level blocks: each keeps its accepted values plus a
        # `_NamedBlock` of every declared name, so a reference to a
        # declared-then-rejected entry stays quiet ("one error, not N",
        # `docs/lore/codegen.md`).
        self.palette: dict[str, Color] = {}
        #: Accepted long-form `palette:` entries' labels, keyed by name --
        #: read when a `config:` choice names `palette.<name>`.
        self.palette_labels: dict[str, str] = {}
        self.palette_block = _NamedBlock()
        self.fonts: dict[str, FontSpec] = {}
        self.fonts_block = _NamedBlock()
        #: `layouts:` entries in declaration order; built before `config:`
        #: so a style entry's `layout:` resolves in the same pass.
        self.layouts: list[LayoutDecl] = []
        self.layouts_block = _NamedBlock()
        self.color_scheme: dict[str, ColorScheme] = {}
        self.color_scheme_block = _NamedBlock()
        self.config_data: dict[str, ConfigDataSlot] = {}
        self.config_data_block = _NamedBlock()
        self.hand_sets: dict[str, HandSet] = {}
        self.hand_sets_block = _NamedBlock()
        #: `accent_color`/`data_color` axes.  A rejected axis (or `"style"`)
        #: goes in `rejected_config` instead, and is still bound into scope
        #: by `_build_scope` for the same cascade reason.
        self.config: dict[str, ConfigColor] = {}
        self.rejected_config: set[str] = set()
        #: The `config: style:` axis; `None` if undeclared or rejected.
        self.config_style: ConfigStyle | None = None
        #: The roles `config.colors.<role>` may name, set by `_build_scope`
        #: for `_expression`'s dedicated error; `None` means no Styles
        #: colours at all, not zero roles.
        self._config_colors_roles: tuple[str, ...] | None = None
        self.scope = expr.Scope()
        self.seen_ids: dict[str, Span | None] = {}
        #: Derived Monkey C symbol -> the element id and span that claimed it
        #: first (`_check_symbol_collision`).
        self.seen_symbols: dict[str, tuple[str, Span | None]] = {}
        # Face-wide defaults, read first in `build()`: `_build_fonts` needs
        # `face_antialias`; the tree passes need the rest.
        self.face_antialias = False
        self.face_min_1px = False
        self.face_aod_default_hide = True
        self.face_aod_lint_allow: frozenset[str] = frozenset()
        self.face_aod_lint_reason: str | None = None
        #: `None` for both an absent `aod: dim:` and `dim: 1` (`Face.aod_dim`).
        self.face_aod_dim: float | None = None
        self.face_aod_mask: bool = True

    # -- entry point ------------------------------------------------------

    def build(self) -> Face | None:
        data = self.doc.data
        self.face_antialias = bool(data.get("antialias", False))
        self.face_min_1px = bool(data.get("min_1px", False))
        self._build_face_aod(data.get("aod") or {})
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
        self._resolve_inherited_flag(elements, "antialias", self.face_antialias)
        self._resolve_inherited_flag(elements, "min_1px", self.face_min_1px)
        self._resolve_aod(elements)
        # `_resolve_aod` is the one resolution walk above that can itself add
        # an error (a group's inherited `aod: {format: ...}` checked against
        # a descendant's value type, `_check_format_spec`) -- the same gate
        # every earlier build stage already gets, so a bad inherited format
        # stops the build here rather than reaching `resolve`/`generate`
        # with a `Face` the bag has already condemned.
        if not self.bag.ok():
            return None

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
            aod_default_hide=self.face_aod_default_hide,
            aod_lint_allow=self.face_aod_lint_allow,
            aod_lint_reason=self.face_aod_lint_reason,
            aod_dim=self.face_aod_dim,
            aod_mask=self.face_aod_mask,
        )

    # -- layouts, palette, config, fonts, scope -----------------------------

    def _build_layouts(self, raw: dict) -> None:
        """`layouts:` -- named widget sets, form A only.

        Post-desugar each body is just `{}` or `{lint: ...}`: `wfb.desugar`
        has already folded its `static:`/`elements:` into synthetic
        top-level groups (`layout_ids`), which `_assign_layouts` walks
        later.  So this records only the names, in declaration order, and
        each layout's own `lint:` (for `unreachable-layout`).  Nothing can
        reject a layout today, but it keeps a `_NamedBlock` like every other
        named block, so a future rejection cascades correctly.
        """
        for name, spec in raw.items():
            span = self.doc.span(raw, name)
            self.layouts_block.declare(name, span)
            self.layouts.append(LayoutDecl(
                name=name,
                **_lint_suppression(spec),
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
                **_lint_suppression(item),
                span=item_span,
            ))
        if not ok:
            self.rejected_config.add("style")
            return

        default_name = spec["default"]
        by_name = {e.name: e for e in entries}
        if default_name not in by_name:
            self._default_not_in_choices(
                "config.style", default_name, self.doc.span(spec, "default"),
                noun="entry", tag="style", listed="declared entries: " + ", ".join(by_name))
            self.rejected_config.add("style")
            return

        self.config_style = ConfigStyle(
            default=default_name, entries=tuple(entries), span=span)

    def _default_not_in_choices(
        self, where: str, default: object, span: Span | None, *,
        noun: str, tag: str, listed: str,
    ) -> None:
        """The shared "default is not one of 'choices:'" error every
        `config:` axis gives (`accent_color`/`data_color`, `style`, a `data`
        slot).  `tag` is the generated resource element the editor reads
        the default from; `listed` the closing note naming what is there."""
        article = "an" if noun[0] in "aeiou" else "a"
        self.bag.error(
            "config",
            f"{where}: default {default!r} is not one of 'choices:'",
            span,
            notes=[
                f"the on-device editor marks one listed {noun} as the user's "
                f"default (the generated <{tag} default=\"true\">) -- Garmin "
                "defines no behaviour for a default that is not in the list",
                f"add it to 'choices:', or change 'default:' to match {article} "
                f"{noun} already there",
                listed,
            ],
        )

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
                    # `{type: complication.<name>, icon:/glyph: ...}` --
                    # carries more than the bare form, so it is not sugar.
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
                self._default_not_in_choices(
                    f"config.data.{name}", spec["default"], default_span,
                    noun="type", tag="type",
                    listed="listed types: " + ", ".join(f"complication.{n}" for n in choices))
                self.config_data_block.reject(name)
                continue

            self.config_data[name] = ConfigDataSlot(
                name=name, default=default, choices=tuple(choices),
                icon_overrides=icon_overrides, span=span)

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
                self._default_not_in_choices(
                    f"config.{name}", spec["default"], default_span,
                    noun="colour", tag="color",
                    listed="listed colours: " + ", ".join(str(c.color) for c in choices))
                self.rejected_config.add(name)
                continue

            self.config[name] = ConfigColor(name=name, default=default,
                                            choices=tuple(choices), span=span)

    def _build_fonts(self, raw: dict) -> None:
        base = self.doc.path.parent
        for name, spec in raw.items():
            span = self.doc.span(raw, name)
            self.fonts_block.declare(name, span)
            # The schema's `oneOf` guarantees exactly one of `source`/`face`.
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
            # No tree to inherit through: the face default applies directly.
            antialias=bool(spec.get("antialias", self.face_antialias)),
            span=span,
            monospace=monospace,
            align=str(spec.get("align", "center")),
        )

    #: `fonts.<name>` keys that only mean something while baking a sheet --
    #: rejected on a `face:` (vector) entry by `_build_vector_font`, each
    #: with its own "why" rather than a bare "unknown key" (the schema
    #: still parses all four there for exactly this reason, the same
    #: "text-antialias" precedent `wfb.kinds.text._reject_text_antialias` follows).
    _VECTOR_FONT_BAKING_KEYS = ("glyphs", "monospace", "align", "antialias")

    def _build_vector_font(self, name: str, spec: dict, span: Span | None) -> FontSpec | None:
        """`fonts.<name>.face:` -- a device-resident scalable face (plan 11
        §2.1), resolved per device later (`wfb.availability.
        vector_font_face`); here only the author-facing shape is checked.
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
            if ok and all(hand is None for hand in hands.values()):
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
        hand_color, color_failed = self._owned_color(spec, where, hand=True)
        ok = not color_failed
        parts: list[HandPart] = []
        for index, raw_part in enumerate(spec.get("parts") or []):
            part = self._build_hand_part(raw_part, where, index, hand_color, color_failed)
            if part is None:
                ok = False
                continue
            parts.append(part)
        if not ok:
            return None
        return Hand(parts=parts, color=hand_color)

    def _owned_color(
        self, node: dict, where: str, *, hand: bool,
    ) -> tuple[Expression | None, bool]:
        """`color:` on a hand, a pattern, or one of their parts, as
        `(color, failed)`.

        `failed` means `color:` was written and did not survive (its error
        already reported) -- kept apart from "not declared" so a part with
        no colour of its own does not also get a cascading "no colour" error
        for a mistake made one level up ("one error, not N").  A hand colour
        (`hand=True`) additionally may not read data at all
        (`_reject_hand_data_color`).
        """
        if "color" not in node:
            return None, False
        color = self._color_expression(node, "color")
        if color is None:
            return None, True
        if hand and self._reject_hand_data_color(color, where, self.doc.span(node, "color")):
            return None, True
        return color, False

    def _reject_hand_data_color(self, color: Expression, where: str, span: Span | None) -> bool:
        """A hand colour may not read a data source at all -- a hand is
        about the time, with no `when_absent:` to fall back through if a
        reading it named turned out absent.

        Hand-only: a pattern colour may read any source; the pattern-wide
        absence policy is `wfb.kinds.pattern._check_pattern_absence`, one
        error for the whole element.  Returns whether the colour was rejected.
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
        default_color: Expression | None, default_color_failed: bool,
        *, context: str = "hand",
    ) -> HandPart | None:
        """One primitive of a hand, or of a `type: pattern` template -- the
        same per-shape precedent as `wfb.kinds.shape.build`/
        `wfb.kinds.shape._check_shape_keys`, scoped to the
        rotatable-or-translatable primitives.  `context`
        (`"hand"`/`"pattern"`) selects the vocabulary: a hand part rejects
        `arc` and `text` outright; a pattern part accepts both.
        `default_color` is the owning hand's/pattern's own `color:`, and
        `default_color_failed` says it was written and rejected
        (`_owned_color`).
        """
        is_hand = context == "hand"
        noun = "hand" if is_hand else "pattern"
        rejected_shapes = HAND_PART_REJECTED_SHAPES if is_hand else PATTERN_PART_REJECTED_SHAPES
        geometry_keys = HAND_PART_GEOMETRY_KEYS if is_hand else PATTERN_PART_GEOMETRY_KEYS
        part_where = f"{where}.parts[{index}]"
        shape = node.get("shape")
        span = self.doc.span(node)
        if shape in rejected_shapes:
            self.bag.error(
                "element",
                f"{part_where}: 'shape: {shape}' is not accepted on a {noun} part -- "
                f"{rejected_shapes[shape]}",
                self.doc.span(node, "shape") or span,
                notes=["the rotatable primitives are: " + ", ".join(sorted(geometry_keys))],
            )
            return None
        if shape not in geometry_keys:  # unreachable once the schema has run
            self.bag.error("hands" if is_hand else "pattern",
                           f"{part_where}: not a valid {noun} part", span)
            return None

        part_color, part_color_failed = self._owned_color(node, part_where, hand=is_hand)
        ok = not part_color_failed
        effective_color = part_color if part_color is not None else default_color
        if effective_color is None and not default_color_failed and not part_color_failed:
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

        # `visible:` -- pattern parts only (the schema keeps `handPart`
        # closed to it), compiled in the caller's `copy`-bound scope.  A
        # constant `true` is dropped (nothing to gate); a constant `false`
        # is kept, so the `dead-element` lint and codegen both see it.
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

        align, vertical_align = self._alignment(node)
        text_fields: dict[str, object] = {}
        if shape == "text":
            built = self._build_text_part(node, part_where, vertical_align)
            if built is None:
                ok = False
            else:
                text_fields = built

        if not ok:
            return None
        return HandPart(
            shape=shape, points=points, at=at, size=size, to=to,
            thickness=thickness, radius=radius, filled=filled,
            color=effective_color, span=span,
            start_angle=start_angle, sweep=sweep,
            visible=part_visible,
            align=align, vertical_align=vertical_align,
            min_1px=(bool(node["min_1px"]) if "min_1px" in node else None),
            **text_fields,
        )

    def _build_text_part(
        self, node: dict, part_where: str, vertical_align: str,
    ) -> dict[str, object] | None:
        """The `shape: text` half of a pattern part, as `HandPart` keyword
        arguments, or `None` once any of its own checks failed (each already
        reported).  Upright glyphs whose anchor turns (radial) or steps
        (linear) with the copy -- only a pattern reaches this, since
        `HAND_PART_REJECTED_SHAPES` refuses `text` on a hand.  Every check
        runs, so each mistake gets its own error, and none gets two.
        """
        ok = True
        text_value: Expression | None = None
        text_literal: str | None = None
        text_format: str | None = None
        has_value = "value" in node
        if has_value == ("text" in node):  # both, or neither
            self.bag.error(
                "pattern",
                f"{part_where}: a text part needs exactly one of "
                "'value:' (an expression; 'copy' is in scope) or "
                "'text:' (a fixed string)",
                self.doc.span(node),
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
        elif not self._check_format_not_on_literal(node, part_where):
            ok = False
        else:
            text_literal = str(node.get("text"))

        font, font_is_custom, font_ok = "FONT_MEDIUM", False, True
        if "font" in node:
            resolved = self._font_reference(str(node["font"]), self.doc.span(node, "font"))
            if resolved is None:
                ok = font_ok = False  # _font_reference already reported it
            else:
                font, font_is_custom = resolved
        font_is_vector = self._is_vector_font(font, font_is_custom)

        curve: Curve | None = None
        if "curve" in node:
            curve = self._build_curve(
                node, part_where, vertical_align=vertical_align, font_ok=font_ok,
                font_is_vector=font_is_vector)
            if curve is None:
                ok = False
        if font_ok and "if_unavailable" in node:
            self._check_if_unavailable(node, part_where, font_is_vector)

        # A failed `outline:` aborts the part; `outline: none` (or no key)
        # is not a failure.  Absence is deferred to
        # `wfb.kinds.pattern._check_pattern_absence`
        # (`_build_outline`'s own docstring).
        outline: Outline | None = None
        if "outline" in node:
            outline = self._build_outline(node, "outline", part_where)
            if outline is None and node.get("outline") not in (None, "none"):
                ok = False

        if not ok:
            return None
        return dict(
            text_value=text_value, text_literal=text_literal, format=text_format,
            font=font, font_is_custom=font_is_custom, curve=curve,
            if_unavailable=node.get("if_unavailable"), outline=outline,
        )

    def _check_hand_part_keys(
        self, node: dict, shape: str, part_where: str, *, context: str = "hand",
    ) -> bool:
        """Reject a geometry key this part's `shape:` does not read, plus the
        separately-handled `thickness`/`filled` rules -- the same "a key a
        part's shape does not read is an error" precedent as
        `wfb.kinds.shape._check_shape_keys`.  Also how an `arc` pattern part's `at:`
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
            expr.Binding(expr.Value(Type.COLOR), code=code, constant=None),
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
                ),
            )
        for name, color in self.palette.items():
            self._define_palette_color(name, color.value)
        # Declared-then-rejected palette entries and `config:` axes are bound
        # too, so a reference to one gets only the real error already
        # reported against its block, not a second "unknown data source"
        # (the `_NamedBlock` cascade).  A design with an error emits
        # nothing, so the placeholder constant/field is never reached.
        for name in sorted(self.palette_block.rejected):
            self._define_palette_color(name, 0)
        for name, entry in self.config.items():
            self._define_config_color(f"config.{name}", entry.field)
        for name in sorted(self.rejected_config - {"style"}):
            # (`style` is not a single colour; its roles are bound below.)
            self._define_config_color(f"config.{name}", config_field(name))

        # `config.colors.<role>` -- one binding per role of the default
        # style entry's scheme, and none for the bare `config.colors` (a
        # scheme is not a colour; `_expression` gives both mistakes a
        # dedicated error).  A layout-only default entry binds no roles.
        if self.config_style is not None and self.config_style.default_entry.colors is not None:
            default_scheme = self.color_scheme[self.config_style.default_entry.colors]
            self._config_colors_roles = tuple(sorted(default_scheme.colors))
            for role in default_scheme.colors:
                self._define_config_color(f"config.colors.{role}", config_field(f"colors_{role}"))
        elif "style" in self.rejected_config:
            # The same cascade for a rejected Styles axis: bind every role a
            # surviving `color_scheme:` entry declares.
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

        aod_own_hide, aod_own = self._build_aod_authored(node)
        common = dict(
            id=element_id,
            kind=node["type"],
            at=self._position(node.get("at"), node, "at"),
            modes=tuple(node.get("modes") or ("active",)),
            z=node.get("z"),
            span=span,
            **_lint_suppression(node),
            on_hold=self._hold_target(node),
            visible=self._visible(node),
            static=bool(node.get("static", False)),
            antialias=(bool(node["antialias"]) if "antialias" in node else None),
            min_1px=(bool(node["min_1px"]) if "min_1px" in node else None),
            aod_own_hide=aod_own_hide,
            aod_own=aod_own,
        )

        if node["type"] not in kinds.names():  # unreachable once the schema has run
            self.bag.error("element", f"unsupported element type {node['type']!r}", span)
            return None
        element = kinds.get(node["type"]).build(self, node, common, path)
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
        node_kind = node.get("type")
        extra_symbols = kinds.get(node_kind).extra_symbols if node_kind in kinds.names() else ()
        candidates = [element_const_prefix(element_id), element_method_name(element_id)]
        candidates += [derive(element_id) for derive in extra_symbols]
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

        Afterwards `element.on_hold` is a real `wfb.complications.TYPES`
        key or `None` -- never `HOLD_AUTO`, except on a `complication_slot`.
        """
        if isinstance(element, ComplicationSlot):
            # A slot's `auto` stays `HOLD_AUTO`: the wearer can repoint the
            # slot at any moment, so the delegate reads the launch target
            # from the slot's own field on the device (`emit_delegate`).
            return
        if element.on_hold == HOLD_AUTO:
            element.on_hold = self._resolve_auto_target(
                element.id, "on_hold", self._hold_auto_sources(element), element.span)

    @staticmethod
    def _hold_auto_sources(element: Element) -> tuple[str, ...]:
        """The catalogue paths `on_hold: auto` may resolve from, for one element.

        Every `ROLE_VALUE`-tagged bound expression's sources (plan 19 A2) --
        deliberately not `color:`/`max:`, since a conditional colour's
        reference is not what the element is *about*.  A `text`'s `value:`,
        a `progress`'s `value:` (not `max:`), and an `icon`'s `icon_for:`
        (not a static `icon:`/`glyph:`, which reads no source at all) are
        each the one `ROLE_VALUE` expression their kind ever tags.

        Deliberately not `element.VALUE_ROLES`, the set `ReadPlan.
        _value_expressions` reads instead: that answers a different
        question (what a `when_absent:` policy governs -- it adds
        `Progress.max`, and has none at all for `IconElement`), so the two
        read the *tag* the same expressions share, not the *kind-specific
        subset* the other one narrows to.
        """
        for role, expression in element.bound_expressions():
            if role == ROLE_VALUE:
                return expression.sources
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
        the one place every kind with a placement box reads the two keys.
        The schema is normative on which values reach here, so this is a
        plain lookup.
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
        *pattern* is hidden, not just this part:
        `wfb.kinds.pattern._check_pattern_absence`
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

    def _conjoin_visible(
        self, outer: Expression | None, inner: Expression | None,
    ) -> Expression | None:
        """``outer and inner`` as one real :class:`Expression`; either may be
        absent (`_make_aod_override` conjoins an optional `aod: visible:`).

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
        if outer is None:
            return inner
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

    # -- always-on display (`aod:`, plan 14) --------------------------------

    def _build_face_aod(self, raw: dict) -> None:
        """Top-level `aod:` (plan 14 §2.2): `default:`, `dim:` (§4.5), `mask:`
        (plan 16 §4)."""
        self.face_aod_default_hide = raw.get("default", "hide") == "hide"
        lint = _lint_suppression(raw)
        self.face_aod_lint_allow = lint["lint_allow"]
        self.face_aod_lint_reason = lint["lint_reason"]
        dim_raw = raw.get("dim")
        # `dim: 1` means "no dimming", exactly like no `dim:` -- both become
        # `None`, which keeps the generated source byte-identical.
        self.face_aod_dim = None if dim_raw is None or float(dim_raw) == 1.0 else float(dim_raw)
        self.face_aod_mask = bool(raw.get("mask", True))

    def _aod_refusal(self, key: str, kind: str | None, shape: str | None,
                     literal_text: bool) -> tuple[str, str, list[str]] | None:
        """``(code, what, notes)`` when an `aod:` override's `key` cannot
        apply to an element of this kind, else ``None`` -- the one table
        both an element's own block (`_build_aod_authored`,
        `wfb.kinds.text.build`) and a key it inherits from a group
        (`_resolve_aod`) are checked
        against, so the two cannot drift (plan 18 item 5).  Each kind's own
        refusal rule lives on its `ElementKind.aod_refusal` hook."""
        if kind is None or kind not in kinds.names():
            return None
        return kinds.get(kind).aod_refusal(key, shape, literal_text)

    def _build_aod_authored(self, node: dict) -> tuple[bool, dict[str, object] | None]:
        """Parse one element/group's own `aod:` (plan 14 §2.1) into
        ``(hide, keys)``: ``hide`` is `True` only for the literal `aod: hide`;
        ``keys`` is `None` when nothing but that was written (or nothing at
        all), or the resolved key -> value dict an `aod: show` (`{}`) or an
        override block produced.

        One parser for every kind: the schema's per-kind `aod<Kind>` `$defs`
        already restrict which keys may appear.  Every value resolves
        through the same machinery as the element's own property of that
        name (`_color_expression`, `_length`, `_font_reference` -- kept as
        its `(name, is_custom)` pair, `_visible`).
        """
        raw = node.get("aod")
        if raw is None:
            return False, None
        if raw == "hide":
            return True, None
        if raw == "show":
            return False, {}
        element_id = node.get("id", "?")
        keys: dict[str, object] = {}
        for key in ("color", "track_color", "icon_color"):
            if key in raw:
                keys[key] = self._color_expression(raw, key)
        for key in ("thickness", "bar_width"):
            if key in raw:
                keys[key] = self._length(raw, key)
        kind, shape = node.get("type"), node.get("shape")
        if "filled" in raw:
            refusal = self._aod_refusal("filled", kind, shape, literal_text=False)
            if refusal is not None:
                code, what, notes = refusal
                self.bag.error(code, f"{element_id}: {what}",
                               self.doc.span(raw, "filled") or self.doc.span(node, "aod"),
                               notes=notes)
            else:
                keys["filled"] = bool(raw["filled"])
        if "font" in raw:
            refusal = self._aod_refusal("font", kind, shape, literal_text=False)
            if refusal is not None:
                code, what, notes = refusal
                self.bag.error(code, f"{element_id}: {what}",
                               self.doc.span(raw, "font") or self.doc.span(node, "aod"),
                               notes=notes)
            else:
                resolved = self._font_reference(str(raw["font"]), self.doc.span(raw, "font"))
                if resolved is not None and self._is_vector_font(*resolved):
                    self.bag.error(
                        "aod",
                        f"{element_id}: an 'aod: {{font: ...}}' override "
                        f"naming a 'face:' (vector) font is not implemented yet "
                        f"(plan 14)",
                        self.doc.span(raw, "font"),
                        notes=[f"{resolved[0]!r} is declared with 'face:', not 'source:' "
                               "-- name a baked font instead, or drop the override "
                               "for now"],
                    )
                elif resolved is not None:
                    keys["font"] = resolved
        if "format" in raw:
            keys["format"] = raw["format"]
        if "visible" in raw:
            keys["visible"] = self._visible(raw)
        return False, keys

    def _make_aod_override(self, element: Element, keys: dict[str, object]) -> AodOverride:
        """Build the `AodOverride` a *drawn* (non-hidden) element gets, from
        its fully key-by-key-resolved `keys` (`_resolve_aod`)."""
        font = keys.get("font")
        font_name, font_is_custom = font if font is not None else (None, False)
        own_visible = keys.get("visible")
        return AodOverride(
            color=keys.get("color"),
            track_color=keys.get("track_color"),
            icon_color=keys.get("icon_color"),
            thickness=keys.get("thickness"),
            bar_width=keys.get("bar_width"),
            filled=keys.get("filled"),
            font=font_name,
            font_is_custom=font_is_custom,
            format=keys.get("format"),
            visible=self._conjoin_visible(element.visible, own_visible),
            visible_override=own_visible,
        )

    def _resolve_aod(self, elements: list[Element]) -> None:
        """Resolve `aod:` over the whole tree (plan 14 §3): element wins key
        by key over its nearest ancestor group's own `aod:`, which wins over
        the face's `aod: default:`.

        A top-down walk, like `_resolve_inherited_flag`, but tracking two
        things down the tree rather than one:

        * ``forced_hidden`` -- sticky once an *explicit* `aod: hide` is seen
          (own or inherited): every descendant is hidden regardless of what
          it writes itself, mirroring `visible:`'s own group-conjoins-down
          precedent, one level stricter (nothing can undo it below).
        * ``nearest`` -- the most recently seen explicit `aod: show`/override
          dict on the path from the root to here, replaced wholesale (not
          merged) by a nearer one when a deeper group writes its own; `None`
          exactly when nothing along the ancestry has spoken yet, which is
          what lets the face default apply only there.

        `aod_ancestor_hidden` is stamped on every element for the
        `aod-unreachable` lint, which must tell "an ancestor's hide buried my
        own override" apart from "no `aod:` of my own".

        A key an element inherits (rather than writes) is checked here
        against the same per-kind refusals its own block would get
        (`_aod_refusal`), because only here has a group's key reached the
        element: one error per element, on the element, naming the group,
        and the key is dropped (plan 18 item 5).
        """
        def visit(items: list[Element], forced_hidden: bool,
                 nearest: dict[str, object] | None, nearest_from: Element | None) -> None:
            for element in items:
                element.aod_ancestor_hidden = forced_hidden
                own_hide = element.aod_own_hide
                own = element.aod_own
                if forced_hidden or own_hide:
                    hidden = True
                elif own is not None or nearest is not None:
                    hidden = False
                else:
                    hidden = self.face_aod_default_hide
                child_forced_hidden = forced_hidden or own_hide
                child_nearest = own if own is not None else nearest
                child_nearest_from = element if own is not None else nearest_from
                if hidden:
                    element.aod = None
                else:
                    effective = dict(nearest or {})
                    if nearest_from is not None:
                        self._refuse_inherited_aod_keys(element, effective, own, nearest_from)
                    if own is not None:
                        effective.update(own)
                    element.aod = self._make_aod_override(element, effective)
                    fmt = effective.get("format")
                    if (fmt is not None and isinstance(element, Text) and element.value is not None
                            and not (own is not None and "format" in own)):
                        # Inherited from a group, whose block may reach
                        # several kinds and value types -- only checkable
                        # here.  An element's own one `wfb.kinds.text.build` checked.
                        self._check_format_spec(element.value, str(fmt), element.span)
                visit(element.children(), child_forced_hidden, child_nearest,
                      child_nearest_from)

        visit(elements, False, None, None)

    def _refuse_inherited_aod_keys(self, element: Element, inherited: dict[str, object],
                                   own: dict[str, object] | None, group: Element) -> None:
        """Report, and drop from ``inherited``, every key ``group``'s own
        `aod:` passed down that ``element`` cannot take and does not
        override itself."""
        kind, shape, literal = _aod_kind(element)
        for key in sorted(inherited):
            if own is not None and key in own:
                continue
            refusal = self._aod_refusal(key, kind, shape, literal)
            if refusal is None:
                continue
            code, what, notes = refusal
            where = f"line {group.span.line}" if group.span is not None else "its own 'aod:'"
            self.bag.error(
                code,
                f"{element.id}: {what}, inherited from group {group.id!r}",
                element.span,
                notes=[f"group {group.id!r} sets 'aod: {{{key}: ...}}' ({where}) for every "
                       f"element below it", *notes,
                       f"move the group's '{key}' onto the elements that can take it"],
            )
            del inherited[key]

    def _resolve_inherited_flag(self, elements: list[Element], key: str, default: bool) -> None:
        """Resolve a boolean key as an inherited default, root to leaf --
        `antialias:` and `min_1px:`.  `Element.<key>` holds what the author
        wrote (`None` = inherit); the answer is stamped into
        `Element.resolved_<key>`, with `default` (the face-wide value) at the
        root.  The nearest declaration wins outright -- unlike `visible:`,
        nothing accumulates -- which is why this is a walk over the finished
        tree rather than a push per group the way `_push_visible` is.
        """
        resolved = f"resolved_{key}"

        def visit(items: list[Element], inherited: bool) -> None:
            for element in items:
                authored_value = getattr(element, key)
                resolved_value = authored_value if authored_value is not None else inherited
                setattr(element, resolved, resolved_value)
                visit(element.children(), resolved_value)

        visit(elements, default)

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
        self._check_static_subtrees(roots)

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

    def _check_static_subtrees(self, roots: list[Element]) -> None:
        """A kind whose own `static_forbidden` hook is set (`graph`,
        `complication_slot`, `hands`) reads its picture from something that
        is not an `Expression` at all -- a series, a wearer's runtime pick,
        the clock -- so the generic "nothing here may read a data source"
        sweep below would never catch any of them on its own."""
        for root in roots:
            for element in walk_elements([root]):
                forbidden = kinds.for_element(element).static_forbidden
                if forbidden is not None:
                    phrase, note = forbidden
                    self.bag.error(
                        "static",
                        f"{element.id!r} is {phrase} and cannot be static",
                        element.span,
                        notes=[note,
                               f"take it out of {root.id!r}"
                               if element is not root else
                               "drop `static: true` from it"],
                    )
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
                               "`active` is fine -- and 'aod:' governs the AMOLED "
                               "sleep frame independently of `modes:`"],
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

    def _check_foreign_keys(
        self, node: dict, chosen: str, table: dict[str, frozenset[str]],
        all_keys: frozenset[str], *, code: str, disc: str,
        prefix: str = "", qualifier: str = "", suffix: str = "",
        empty_label: str = "(no geometry keys)",
        extra_notes: Callable[[str], list[str]] | None = None,
    ) -> bool:
        """Reject a key from another row of `table` that `chosen`'s own row
        does not read -- the shared "key not used by this X" sweep
        `wfb.kinds.shape._check_shape_keys`, `_check_hand_part_keys` and
        `wfb.kinds.graph._check_graph_style_keys` each specialise, for `disc`
        (the discriminator word: `shape`/`style`) in `'{disc}: {chosen}'`.

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


    def _build_outline(
        self, node: dict, key: str, label: str, *, element: Element | None = None,
    ) -> Outline | None:
        """`outline:` (plan 15) on a `text` element, or -- with
        `element=None` -- on a pattern's `shape: text` part: the stamped ring
        research 14 measured, drawn N times at small pixel offsets in
        `outline.color`, then once more, unshifted, in the fill colour.

        Two spellings collapse to one `Outline` (D7): a bare colour
        expression (`width: 2` implied) or an explicit `{color, width}`
        mapping.  `outline.color` goes through the same `_color_expression`
        `color:` uses (D8).  `width` is capped at `MAX_OUTLINE_WIDTH` with a
        build error rather than a schema `maximum`, so the message can cite
        the evidence the cap rests on (D6).  `label` leads the width-cap
        error (the element id, or the part's `part_where`).

        **Absence.** A `text` element (`element` given) gets its own
        `_check_other_absence` here.  A pattern part does not: a pattern
        polices absence once for the whole element over
        `PatternElement.colors` (`wfb.kinds.pattern._check_pattern_absence`),
        which the caller folds `outline.color` into -- checking here too
        would double-report the same source.
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
                f"{label}: 'outline: width: {width}' is more than "
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
        if element is not None:
            self._check_other_absence(node, element, "outline.color", color, span=color_span)
        return Outline(color=color, width=width)

    def _check_curve_keys(self, node: dict, style: str) -> None:
        """Reject a `curve:` key the chosen `style:` does not read -- the same
        `wfb.kinds.shape._check_shape_keys` precedent (`radius:`/`direction:`
        only mean something with a circle to describe, and `style: angled`
        has none).
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

    def _is_vector_font(self, font: str, is_custom: bool) -> bool:
        """Whether a resolved `(font, is_custom)` reference names a `face:`
        (vector) font.  Safe to call on any resolved reference:
        `_font_reference` only returns a custom name already in `self.fonts`,
        and an unresolved one keeps the system-font default."""
        return is_custom and self.fonts[font].is_vector

    @staticmethod
    def _font_kind_note(font: str, is_custom: bool) -> str:
        """What kind of (non-vector) font a `text` element's `font:` resolved
        to -- the extra note `_build_curve`/`_check_if_unavailable` add for
        a `text` element."""
        if is_custom:
            return f"'font: font.{font}' is a baked bitmap font, declared with 'source:'"
        return f"'font: {font}' is one of the platform's fixed system fonts"

    def _build_curve(
        self, node: dict, label: str, *, vertical_align: str, font_ok: bool,
        font_is_vector: bool, font_note: str | None = None,
    ) -> Curve | None:
        """`curve:` (plan 11) on a `text` element or a pattern's `shape: text`
        part: bends the text along a line (`style: angled`) or around a
        circle (`style: radial`).  `label` leads every message (the element
        id, or the part's `part_where`).

        `Dc.drawAngledText`/`drawRadialText` refuse a resource font, so
        `font:` must name a `face:` font -- checked only when `font_ok`: a
        font reference that itself failed already has its own error (the
        `_NamedBlock` cascade discipline).  `font_note` is the extra
        "what this font is" note a `text` element's message carries.

        On a pattern part the angle is authored in the template's own local
        frame; a radial pattern's per-copy rotation composes with it
        downstream (`wfb.kinds.pattern._pattern_part_ink`, `wfb.kinds.
        pattern._emit_pattern_text_angle_expr`), so twelve hour numerals
        share one authored angle.
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
                f"{label}: 'curve:' needs a 'face:' (vector) font",
                span,
                notes=[
                    "\"These APIs only support scalable fonts and do not support "
                    "custom fonts loaded as resources\" ($CIQ_SDK/doc/docs/"
                    "Core_Topics/Graphics.html §Scalable Fonts)",
                    *([font_note] if font_note is not None else []),
                    "declare this font with 'face:' instead of 'source:', or point "
                    "'font:' at one that already does",
                ],
            )
        if vertical_align == "bottom" and style == "angled":
            self.bag.error(
                "text-curve",
                f"{label}: 'vertical_align: bottom' is not accepted under "
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

    def _check_if_unavailable(
        self, node: dict, label: str, font_is_vector: bool, font_note: str | None = None,
    ) -> None:
        """`if_unavailable:` on a `text` element or a pattern's `shape: text`
        part -- only meaningful when the font is a `face:` (vector) font:
        nothing about a baked or system font can ever be unavailable, so
        accepting it would promise a check that never runs (the same
        reasoning `_build_baked_font` applies to the key on a `fonts:` entry).
        Callers only reach this once the font reference itself resolved.
        """
        if font_is_vector:
            return
        self.bag.error(
            "text-curve",
            f"{label}: 'if_unavailable:' is not accepted here",
            self.doc.span(node, "if_unavailable"),
            notes=[
                "'if_unavailable:' governs a device-resident 'face:' font "
                "failing to publish a face on some target device -- nothing "
                "about a baked or system font can ever be unavailable",
                *([font_note] if font_note is not None else []),
                "drop 'if_unavailable:', or point 'font:' at a 'face:' font",
            ],
        )

    def _resolve_icon_name(self, name: str, span: Span | None) -> str | None:
        """A catalogue name -> its codepoint, or `None` plus a reported error.

        The shared "unknown icon" diagnostic: used by `wfb.kinds.icon.build`'s
        own inline check and by a `complication_slot` choice's `icon:` override
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

        The shared `glyph:` diagnostics: used by `wfb.kinds.icon._build_glyph_icon`'s
        own inline checks and by a `complication_slot` choice's `glyph:`
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
            # Every *other* bound expression, `visible:` excluded -- it has
            # its own "absent means hidden" rule with no `when_absent:` of
            # its own to speak of (plan 19 A2: read by role, not identity,
            # so this reads the same as the isinstance-free form below).
            others_nullable = any(
                expression is not bound and role != ROLE_VISIBLE and expression.nullable
                for role, expression in element.bound_expressions()
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
                    _ABSENCE_IS_NORMAL,
                    _WHEN_ABSENT_CHOICES,
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
                _ABSENCE_IS_NORMAL,
                f"'when_absent:' is required once anything on this element is nullable, not "
                f"just 'value' -- a nullable {key} always hides the element when absent, "
                "regardless of which policy is chosen for the bound value",
                _WHEN_ABSENT_CHOICES,
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
        self._check_format_spec(bound, spec, span)

    def _check_format_spec(self, bound: Expression, spec: str, span: Span | None) -> None:
        """The coded-vs-type checks a `format:` spec needs against the value
        it formats -- factored out of `_check_format` so an `aod: {format:
        ...}` override (which has no "was 'format:' omitted" case of its
        own: it is only ever consulted once a spec was actually written)
        can run through the exact same checks the awake `format:` gets,
        rather than a second, narrower implementation. An earlier pass left
        an override's spec unchecked entirely, so a malformed one reached
        `formatting.emit`/`formatting.render` as a raw, unhandled
        `FormatError` instead of a diagnostic on the author's line."""
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

    def _check_format_not_on_literal(self, node: dict, label: str) -> bool:
        """`format:` is meaningless without a bound `value:` to format --
        shared by a `text` element and a pattern's own `shape: text` part,
        which both take the same `text:` spelling for a fixed string.
        Returns `False` (having already reported it) when `format:` was
        written anyway, `True` otherwise."""
        if "format" not in node:
            return True
        self.bag.error(
            "format",
            f"{label}.format: 'format:' applies only to 'value:', not a fixed 'text:'",
            self.doc.span(node, "format"),
        )
        return False

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

    def _resolve_font(self, node: dict, element: Text | ComplicationSlot) -> bool:
        """Set `.font`/`.font_is_custom` from `node["font"]`.

        Returns whether the reference is trustworthy: `True` when no
        `font:` was written at all (the element keeps its class-default
        system font) or the name resolved; `False` only when an explicit
        `font:` failed to resolve, which already has its own error.  Callers
        use it to skip a further font-kind check that would otherwise blame
        the untouched default for a mistake reported one line up -- the
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
        (`wfb.kinds.icon.build`), and a complication_slot's `icon_size:`/`icon_gap:`
        (`wfb.kinds.complication_slot.build`).  `label` is the quantity name the
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


def _lint_suppression(node: dict) -> dict[str, object]:
    """A node's own `lint: {allow, reason}`, as the `lint_allow`/
    `lint_reason` keyword arguments every carrier of one takes."""
    lint = node.get("lint") or {}
    return {"lint_allow": frozenset(lint.get("allow", ())), "lint_reason": lint.get("reason")}


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
