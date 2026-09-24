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

from .app import emit_app, emit_icon_glyphs, emit_palette, icon_glyph_entries
from .common import (
    SourceFile, _mc_number, _mc_type, complication_slots, hold_targets, needs_delegate,
)
from .complication_slot import emit_slot_drawable
from .delegate import emit_delegate
from .layout_constants import emit_layout
from .readplan import ReadPlan
from .view import emit_view

#: The package's surface: the `emit_*` entry points `wfb/emit/project.py`
#: calls (and tests monkeypatch, as `wfb.emit.monkeyc.<name>`), plus the few
#: helpers callers outside this package use. Everything else is imported
#: from its own submodule.
__all__ = [
    "ReadPlan", "SourceFile", "_mc_number", "_mc_type", "complication_slots", "emit_app",
    "emit_delegate", "emit_icon_glyphs", "emit_layout", "emit_palette", "emit_slot_drawable",
    "emit_view", "hold_targets", "icon_glyph_entries", "needs_delegate",
]
