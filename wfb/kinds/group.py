"""`type: group` -- draws nothing itself; a positioning box for its children.

A group is handled structurally almost everywhere (`Resolver._resolve_list`
recurses into it directly, `preview.render` and `view._emit_element_method`
filter it out before dispatch), so this kind overrides far fewer methods than
the other eight.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..ir.model import Element, Group
from ..ir.naming import static_group_method
from ..layout import Placed
from . import ElementKind

if TYPE_CHECKING:
    from ..ir.builder import Builder


class GroupKind(ElementKind):
    name = "group"
    ir_class = Group
    placed_class = Placed
    extra_symbols = (static_group_method,)

    def build(self, b: Builder, node: dict, common: dict, path: tuple) -> Element:
        align, vertical_align = b._alignment(node)
        group = Group(
            **common,
            size=b._size(node.get("size")),
            items=b._build_elements(node["children"], path + ("children",)),
            align=align,
            vertical_align=vertical_align,
        )
        b._push_visible(group)
        return group


KIND = GroupKind()
