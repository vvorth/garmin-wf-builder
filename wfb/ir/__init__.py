"""The intermediate representation, and the semantic pass that produces it.

Stage 2 of validation (ADR 0008): everything that is device-independent.  Data
sources are resolved against the catalogue, expressions are type-checked and
compiled, and null handling is required where the platform makes absence
normal.  Every value comes from a Garmin SDK call that caches it itself, so a
plain per-frame read is correct everywhere, including under
`onPartialUpdate`; the suppressible `partial-update-budget` lint is where
that tradeoff is managed.

Nothing here knows a screen size.  Per-device work happens in :mod:`wfb.layout`.

A package: :mod:`wfb.ir.model` holds the constants and dataclasses,
:mod:`wfb.ir.naming` the generated-symbol derivation, and
:mod:`wfb.ir.builder` the semantic pass (`Builder`) itself.  This file
re-exports every name from all three, so callers can `import wfb.ir` without
knowing which submodule a name lives in.
"""

from __future__ import annotations

from .naming import (
    local_name, config_field, config_data_ids, element_const_prefix,
    element_method_name, static_group_method, complication_slot_icon_method,
    complication_slot_hold_method, graph_series_field, graph_min_field,
    graph_max_field, graph_built_field, graph_rebuild_method, _element_suffix,
    _lower_first, _pascal, font_resource_id, config_label_id, config_style_label_id,
)
from .model import (
    MODES, HOLD_AUTO, PATTERN_LOOP_INDEX, GRAPH_AREA_MAX_SAMPLES, SYSTEM_FONTS,
    MAX_OUTLINE_WIDTH,
    Position, Size, Expression, FontSpec, Curve, Outline, disc_perimeter_offsets,
    CONFIG_SYMBOL, ConfigChoice, ConfigAxis,
    CONFIG_AXES, ConfigColor, ColorScheme, LayoutDecl, StyleEntry, ConfigStyle,
    ConfigDataSlot, Element, Group, Shape, HandPart, Hand, HandSet, HandsElement,
    PatternElement, Text, Progress, IconElement, ComplicationSlot, Graph, Face,
    _drawn_copies, walk_elements, authored_draw_order, draw_sort_key, draw_order,
    never_together,
)
from .builder import (
    _NO_ICON_OVERRIDE, _ICON_OVERRIDE_ERROR, SHAPE_GEOMETRY_KEYS,
    _SHAPE_NO_ALIGNMENT_REASON, _ALL_SHAPE_GEOMETRY_KEYS, HAND_PART_GEOMETRY_KEYS,
    _ALL_HAND_PART_GEOMETRY_KEYS, HAND_PART_FILLED_SHAPES, HAND_PART_NO_UNFILLED,
    HAND_PART_REJECTED_SHAPES, PATTERN_PART_GEOMETRY_KEYS,
    _ALL_PATTERN_PART_GEOMETRY_KEYS, _HAND_PART_NO_ALIGNMENT_REASON,
    PATTERN_PART_REJECTED_SHAPES, GRAPH_STYLE_KEYS, _ALL_GRAPH_STYLE_KEYS,
    _CONFIG_COLORS_RE, _NamedBlock, Builder, _dedup_append, _and_paths, build,
    _offset_span,
)

__all__ = [
    "local_name", "config_field", "config_data_ids", "element_const_prefix",
    "element_method_name", "static_group_method", "complication_slot_icon_method",
    "complication_slot_hold_method", "graph_series_field", "graph_min_field",
    "graph_max_field", "graph_built_field", "graph_rebuild_method", "_element_suffix",
    "_lower_first", "_pascal", "font_resource_id", "config_label_id", "config_style_label_id",
    "MODES", "HOLD_AUTO", "PATTERN_LOOP_INDEX", "GRAPH_AREA_MAX_SAMPLES", "SYSTEM_FONTS",
    "MAX_OUTLINE_WIDTH",
    "Position", "Size", "Expression", "FontSpec", "Curve", "Outline", "disc_perimeter_offsets",
    "CONFIG_SYMBOL", "ConfigChoice", "ConfigAxis",
    "CONFIG_AXES", "ConfigColor", "ColorScheme", "LayoutDecl", "StyleEntry", "ConfigStyle",
    "ConfigDataSlot", "Element", "Group", "Shape", "HandPart", "Hand", "HandSet", "HandsElement",
    "PatternElement", "Text", "Progress", "IconElement", "ComplicationSlot", "Graph", "Face",
    "_drawn_copies", "walk_elements", "authored_draw_order", "draw_sort_key", "draw_order",
    "never_together",
    "_NO_ICON_OVERRIDE", "_ICON_OVERRIDE_ERROR", "SHAPE_GEOMETRY_KEYS",
    "_SHAPE_NO_ALIGNMENT_REASON", "_ALL_SHAPE_GEOMETRY_KEYS", "HAND_PART_GEOMETRY_KEYS",
    "_ALL_HAND_PART_GEOMETRY_KEYS", "HAND_PART_FILLED_SHAPES", "HAND_PART_NO_UNFILLED",
    "HAND_PART_REJECTED_SHAPES", "PATTERN_PART_GEOMETRY_KEYS",
    "_ALL_PATTERN_PART_GEOMETRY_KEYS", "_HAND_PART_NO_ALIGNMENT_REASON",
    "PATTERN_PART_REJECTED_SHAPES", "GRAPH_STYLE_KEYS", "_ALL_GRAPH_STYLE_KEYS",
    "_CONFIG_COLORS_RE", "_NamedBlock", "Builder", "_dedup_append", "_and_paths", "build",
    "_offset_span",
]
