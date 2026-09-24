"""`type: group` -- draws nothing itself; a positioning box for its children.

A group is handled structurally almost everywhere (`Resolver._resolve_list`
recurses into it directly, `preview.render` and `view._emit_element_method`
filter it out before dispatch), so this kind carries far fewer hooks than
the other eight.
"""

from __future__ import annotations

from ..ir.builder import Builder
from ..ir.model import Group
from ..ir.naming import static_group_method
from ..layout import Placed
from . import ElementKind

KIND = ElementKind(
    name="group",
    ir_class=Group,
    placed_class=Placed,
    build=Builder._build_group,
    resolve=None,
    extra_symbols=(static_group_method,),
)
