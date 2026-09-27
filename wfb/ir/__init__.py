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
re-exports every public name from all three, so callers can `import wfb.ir`
without knowing which submodule a name lives in; private helpers stay in
their own submodule.
"""

from __future__ import annotations

from .naming import (
    local_name, config_field, config_data_ids, element_const_prefix,
    element_method_name, static_group_method, complication_slot_icon_method,
    complication_slot_hold_method, graph_series_field, graph_min_field,
    graph_max_field, graph_built_field, graph_rebuild_method,
    font_resource_id, config_label_id, config_style_label_id,
)
from .model import (
    MODES, HOLD_AUTO, PATTERN_LOOP_INDEX, GRAPH_AREA_MAX_SAMPLES, SYSTEM_FONTS,
    MAX_OUTLINE_WIDTH,
    ROLE_VALUE, ROLE_MAX, ROLE_MIN, ROLE_FALLBACK, ROLE_COLOR, ROLE_TRACK_COLOR,
    ROLE_ICON_COLOR, ROLE_OUTLINE_COLOR, ROLE_UNIT_LABEL, ROLE_PART_VISIBLE, ROLE_PART_TEXT, ROLE_VISIBLE,
    Position, Size, Expression, FontSpec, Curve, Outline, AodOverride, ColorRole,
    aod_color_choice, aod_outline_choice, disc_perimeter_offsets,
    CONFIG_SYMBOL, ConfigChoice, ConfigAxis,
    CONFIG_AXES, ConfigColor, ColorScheme, LayoutDecl, StyleEntry, ConfigStyle,
    ConfigDataSlot, Element, Group, Shape, HandPart, AnyHandPart, PolygonPart, RectanglePart, LinePart, CirclePart,
    ArcPart, TextPart, Hand, HandSet, HandsElement,
    PatternElement, Text, Progress, IconElement, ComplicationSlot, Graph, Face,
    walk_elements, authored_draw_order, draw_sort_key, draw_order, never_together,
)
from .builder import (
    HAND_PART_GEOMETRY_KEYS, HAND_PART_FILLED_SHAPES,
    HAND_PART_NO_UNFILLED, HAND_PART_REJECTED_SHAPES, PATTERN_PART_GEOMETRY_KEYS,
    PATTERN_PART_REJECTED_SHAPES, CURVE_STYLE_KEYS, Builder, build,
)

__all__ = [
    "local_name", "config_field", "config_data_ids", "element_const_prefix",
    "element_method_name", "static_group_method", "complication_slot_icon_method",
    "complication_slot_hold_method", "graph_series_field", "graph_min_field",
    "graph_max_field", "graph_built_field", "graph_rebuild_method",
    "font_resource_id", "config_label_id", "config_style_label_id",
    "MODES", "HOLD_AUTO", "PATTERN_LOOP_INDEX", "GRAPH_AREA_MAX_SAMPLES", "SYSTEM_FONTS",
    "MAX_OUTLINE_WIDTH",
    "ROLE_VALUE", "ROLE_MAX", "ROLE_MIN", "ROLE_FALLBACK", "ROLE_COLOR", "ROLE_TRACK_COLOR",
    "ROLE_ICON_COLOR", "ROLE_OUTLINE_COLOR", "ROLE_UNIT_LABEL", "ROLE_PART_VISIBLE", "ROLE_PART_TEXT",
    "ROLE_VISIBLE",
    "Position", "Size", "Expression", "FontSpec", "Curve", "Outline", "AodOverride", "ColorRole",
    "aod_color_choice", "aod_outline_choice", "disc_perimeter_offsets",
    "CONFIG_SYMBOL", "ConfigChoice", "ConfigAxis",
    "CONFIG_AXES", "ConfigColor", "ColorScheme", "LayoutDecl", "StyleEntry", "ConfigStyle",
    "ConfigDataSlot", "Element", "Group", "Shape", "HandPart", "AnyHandPart", "PolygonPart", "RectanglePart", "LinePart", "CirclePart",
    "ArcPart", "TextPart", "Hand", "HandSet", "HandsElement",
    "PatternElement", "Text", "Progress", "IconElement", "ComplicationSlot", "Graph", "Face",
    "walk_elements", "authored_draw_order", "draw_sort_key", "draw_order", "never_together",
    "HAND_PART_GEOMETRY_KEYS", "HAND_PART_FILLED_SHAPES",
    "HAND_PART_NO_UNFILLED", "HAND_PART_REJECTED_SHAPES", "PATTERN_PART_GEOMETRY_KEYS",
    "PATTERN_PART_REJECTED_SHAPES", "CURVE_STYLE_KEYS", "Builder", "build",
]
