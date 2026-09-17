"""Monkey C generation.

ADR 0003 sets the bar: the generated code is reviewed, debugged and extended by
a human, so it must read as though someone wrote it.  Concretely --

* symbol names are derived from element ids, so they are stable across builds;
* a header cites the source file and the generator version;
* every drawing block carries a comment naming the YAML element it came from;
* layout constants are named in a per-device ``Layout`` module rather than
  inlined as bare numbers;
* every nullable read is guarded, and the guard states the ``when_absent``
  policy that produced it.

The code targets ``-l 3`` (strict typecheck) cleanly.  A generator has no excuse
for emitting code that fails strict checking.
"""

from __future__ import annotations

from .common import (
    _BASE_IMPORTS, _NO_GUARDS, SourceFile, source_label, header, McLiteral, hold_targets,
    complication_slots, needs_delegate, _editor_slot_pairs, CONFIG_LAYOUT_METHOD,
    _pattern_needs_math, _glyph_y_expr, _const_prefix, _method, _field, _color, _mc_bool,
    _mc_float, _loaded_fonts, _describe, _and_list, _article, _mc_type, _mc_number
)
from .app import emit_app, emit_palette, emit_icon_glyphs, icon_glyph_entries
from .delegate import (
    _emit_on_watchface_config_edited, _emit_exit_to, emit_delegate, _emit_on_tap,
    _emit_get_complication_drawable
)
from .layout_constants import (
    emit_layout, _hands_needs_graphics, _pattern_needs_graphics, _hold_constants,
    _box_constants, _arc_constants, _layout_constants, _hand_part_constants
)
from .readplan import ReadPlan
from .view import (
    STATIC_FIELD, STATIC_RENDER, REPAINT_STATIC_METHOD, StaticPlan, static_plan,
    _antialias_default, _emit_antialias_helper, _has_partial_update, emit_view,
    _sleep_flag_doc, _emit_static_field, _emit_static_allocation, _emit_static_blit,
    _emit_static_methods, _emit_fields, _emit_config_fields, _emit_apply_config,
    _emit_config_layout_accessor, RESOLVE_STYLE_METHOD, CONFIG_LAYOUT_FIELD,
    _emit_resolve_style, _emit_initialize, _emit_complication_subscribe_lines, _emit_on_layout,
    _emit_on_update, _emit_layout_guarded_calls, _draw_calls, _emit_mode_body,
    _emit_on_partial_update, _emit_sleep_hooks, _emit_complication_callback,
    _emit_element_method, _method_doc, _negated, _negatable, _emit_visible_guard, _emit_guard
)
from .shapes import (
    _emit_arc_span, _emit_shape, _emit_text, _emit_text_draw, _emit_progress,
    _fallback_fraction, _fraction, _emit_icon
)
from .rotated import (
    _HAND_ANGLE_FUNCTIONS, _emit_hands, _emit_one_hand, _emit_rotated_part,
    _pattern_skip_condition, _pattern_angle_expr, _emit_pattern_part, _emit_pattern
)
from .complication_slot import (
    _emit_pulsing_field, _emit_complication_slot_editor_methods, emit_slot_drawable,
    _emit_complication_slot_hold_method, _emit_complication_slot_icon_method,
    _emit_complication_slot
)
from .graph import (
    _emit_graph_fields, _emit_graph, _emit_graph_rebuild, _emit_hr_rebuild,
    _emit_array_rebuild
)

#: Every top-level name the old single-file module defined, private ones
#: included -- tests and `wfb/emit/project.py`/`manifest.py` reach them through
#: this package attribute (see the monkeypatch constraint in the split plan).
__all__ = [
    '_BASE_IMPORTS', '_NO_GUARDS', 'SourceFile', 'source_label', 'header', 'McLiteral',
    'hold_targets', 'complication_slots', 'needs_delegate', '_editor_slot_pairs',
    'CONFIG_LAYOUT_METHOD', '_pattern_needs_math', '_glyph_y_expr', '_const_prefix', '_method',
    '_field', '_color', '_mc_bool', '_mc_float', '_loaded_fonts', '_describe', '_and_list',
    '_article', '_mc_type', '_mc_number', 'emit_app', 'emit_palette', 'emit_icon_glyphs',
    'icon_glyph_entries', '_emit_on_watchface_config_edited', '_emit_exit_to', 'emit_delegate',
    '_emit_on_tap', '_emit_get_complication_drawable', 'emit_layout', '_hands_needs_graphics',
    '_pattern_needs_graphics', '_hold_constants', '_box_constants', '_arc_constants',
    '_layout_constants', '_hand_part_constants', 'ReadPlan', 'STATIC_FIELD', 'STATIC_RENDER',
    'REPAINT_STATIC_METHOD', 'StaticPlan', 'static_plan', '_antialias_default',
    '_emit_antialias_helper', '_has_partial_update', 'emit_view', '_sleep_flag_doc',
    '_emit_static_field', '_emit_static_allocation', '_emit_static_blit',
    '_emit_static_methods', '_emit_fields', '_emit_config_fields', '_emit_apply_config',
    '_emit_config_layout_accessor', 'RESOLVE_STYLE_METHOD', 'CONFIG_LAYOUT_FIELD',
    '_emit_resolve_style', '_emit_initialize', '_emit_complication_subscribe_lines',
    '_emit_on_layout', '_emit_on_update', '_emit_layout_guarded_calls', '_draw_calls',
    '_emit_mode_body', '_emit_on_partial_update', '_emit_sleep_hooks',
    '_emit_complication_callback', '_emit_element_method', '_method_doc', '_negated',
    '_negatable', '_emit_visible_guard', '_emit_guard', '_emit_arc_span', '_emit_shape',
    '_emit_text', '_emit_text_draw', '_emit_progress', '_fallback_fraction', '_fraction',
    '_emit_icon', '_HAND_ANGLE_FUNCTIONS', '_emit_hands', '_emit_one_hand',
    '_emit_rotated_part', '_pattern_skip_condition', '_pattern_angle_expr',
    '_emit_pattern_part', '_emit_pattern', '_emit_pulsing_field',
    '_emit_complication_slot_editor_methods', 'emit_slot_drawable',
    '_emit_complication_slot_hold_method', '_emit_complication_slot_icon_method',
    '_emit_complication_slot', '_emit_graph_fields', '_emit_graph', '_emit_graph_rebuild',
    '_emit_hr_rebuild', '_emit_array_rebuild'
]
