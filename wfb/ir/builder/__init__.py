"""The semantic pass (ADR 0008 stage 2): `Builder` walks a validated YAML
document and produces a `wfb.ir.model.Face`, resolving data sources against
the catalogue, type-checking and compiling expressions, and requiring null
handling wherever the platform makes absence normal.

`Builder` is one class built from layers, one module each.  Every layer
subclasses the one below it, so a layer calls only what sits beneath it,
which is what lets `mypy --strict` check each module on its own:

    state       shared state, `NamedRegistry`, `dedup_append`, `and_paths`
    reading     one key of a node: expressions, colours, lengths, fonts
    absence     `when_absent:` and `format:`
    glyphs      icons, `outline:`, `curve:`, `if_unavailable:`
    visibility  `visible:` and the enclosing groups' conditions
    fonts       the `fonts:` block
    blocks      `layouts:`, `palette:`, `color_scheme:` and the scope
    config      the `config:` axes
    hands       `hands:`, and the parts a hand and a pattern share
    aod         `aod:`, read and resolved down the tree
    static      `static:` subtrees
    tree        the element tree, one node at a time through `wfb.kinds`
    (here)      `Builder.build`, the entry point

A new helper goes in the lowest layer that has everything it calls.

Nothing here knows a screen size -- per-device work happens in
:mod:`wfb.layout`.
"""

from __future__ import annotations

from ...diagnostics import Bag
from ...yamlsrc import YamlDocument
from ..model import Face
from ..naming import _pascal
from .absence import ABSENCE_IS_NORMAL
from .glyphs import CURVE_STYLE_KEYS, ICON_SIZE_NOTE
from .hands import (
    HAND_PART_FILLED_SHAPES, HAND_PART_GEOMETRY_KEYS, HAND_PART_NO_UNFILLED,
    HAND_PART_REJECTED_SHAPES, PATTERN_PART_GEOMETRY_KEYS, PATTERN_PART_REJECTED_SHAPES,
)
from .state import BuilderState, NamedRegistry, and_paths, dedup_append
from .tree import ElementTree

__all__ = [
    "ABSENCE_IS_NORMAL", "Builder", "BuilderState", "CURVE_STYLE_KEYS",
    "HAND_PART_FILLED_SHAPES", "HAND_PART_GEOMETRY_KEYS", "HAND_PART_NO_UNFILLED",
    "HAND_PART_REJECTED_SHAPES", "ICON_SIZE_NOTE", "NamedRegistry",
    "PATTERN_PART_GEOMETRY_KEYS", "PATTERN_PART_REJECTED_SHAPES", "and_paths",
    "build", "dedup_append",
]


class Builder(ElementTree):
    """The semantic pass: a schema-valid document in, a :class:`Face` out,
    every mistake reported to `bag` on the author's own line.

    **Helpers for kind authors.**  A kind's `build` (`wfb.kinds`) gets the
    builder as `b` and reads its node through the public methods below;
    everything underscored belongs to this module.  A helper that can fail
    reports its own error and returns `None` (or an empty default), so the
    kind only checks the result.  `b.doc.span(node, key)` locates a key for
    a diagnostic of the kind's own, and `b.bag` takes it.

    - Reading a key: `expression`, `color_expression`, `length`, `angle`,
      `position`, `size`, `alignment`, `baked_size_length`; `require`
      reports a key the schema cannot require by itself.
    - Absence and `format:`: `check_absence` (the value's own
      `when_absent:`), `check_other_absence` (any other nullable binding),
      `check_reachable_substitute`, `nullable_sources`, `check_format`,
      `check_format_spec`, `check_format_not_on_literal`.
    - Fonts and icons: `resolve_font`, `is_vector_font`, `font_kind_note`,
      `check_if_unavailable`, `build_curve`, `build_outline`,
      `resolve_icon_name`, `resolve_icon_glyph`.
    - Structure: `build_elements` and `push_visible` (a group's children),
      `build_hand_part` and `owned_color` (a hand's or a pattern's parts),
      `check_foreign_keys` (a key that belongs to another `shape:` or
      `style:`), `aod_refusal`.

    Module level: `dedup_append`, `and_paths`, `ABSENCE_IS_NORMAL`,
    `ICON_SIZE_NOTE`.
    """

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
        # `palette.*`/`config.*` through the same `color_expression` an
        # element's own `color:` uses, and it needs `self.scope` in place.
        # They need to run before `build_elements` so a `type: hands`
        # element can resolve `hands: <name>` against `self.hand_sets` the
        # same build pass.
        self._build_hands(data.get("hands") or {})

        elements = self.build_elements(data.get("elements") or [], ("elements",))
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
        # a descendant's value type, `check_format_spec`) -- the same gate
        # every earlier build stage already gets, so a bad inherited format
        # stops the build here rather than reaching `resolve`/`generate`
        # with a `Face` the bag has already condemned.
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
            palette=dict(self.palette),
            palette_labels=dict(self.palette_labels),
            fonts=dict(self.fonts),
            elements=elements,
            source_path=self.doc.path,
            antialias=self.face_antialias,
            min_1px=self.face_min_1px,
            config=self.config,
            color_scheme=dict(self.color_scheme),
            layouts=tuple(self.layouts),
            layout_decls=dict(self.layouts),
            config_style=self.config_style,
            config_data=dict(self.config_data),
            hands=dict(self.hand_sets),
            aod_default_hide=self.face_aod_default_hide,
            aod_lint_allow=self.face_aod_lint_allow,
            aod_lint_reason=self.face_aod_lint_reason,
            aod_dim=self.face_aod_dim,
            aod_mask=self.face_aod_mask,
        )


def build(doc: YamlDocument, bag: Bag) -> Face | None:
    return Builder(doc, bag).build()
