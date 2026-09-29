"""Outlined groups (research 19, plan 23 D5): which leaves an outlined
`group`'s ring goes round, and how far each is dilated.

A group's ring is the union of its members' dilations, drawn just before the
group's first member -- every member's ring, then every member.  A member's
dilation includes its own ring and every outlined group between it and this
one, so the ring goes round what is actually drawn: the width is the sum.
Codegen (`wfb.emit.monkeyc.view`) and the preview (`wfb.preview`) both read
this one answer.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass

from .model import Element, Group


@dataclass(frozen=True)
class RingGroup:
    """One outlined group, and every leaf it rings with its total width."""

    group: Group
    #: ``(leaf, width)`` in authored order: the leaf's dilation for this
    #: group's pass, in px.
    members: tuple[tuple[Element, int], ...]

    @property
    def ids(self) -> frozenset[str]:
        return frozenset(leaf.id for leaf, _ in self.members)

    def width_of(self, element_id: str) -> int:
        return next(width for leaf, width in self.members if leaf.id == element_id)


def ring_groups(elements: list[Element]) -> list[RingGroup]:
    """Every outlined group under ``elements``, outermost first."""
    out: list[RingGroup] = []

    def walk(element: Element) -> None:
        if isinstance(element, Group):
            if element.outline is not None:
                out.append(RingGroup(element, tuple(_leaves(element, element.outline.width))))
            for child in element.items:
                walk(child)

    for element in elements:
        walk(element)
    return out


def _leaves(group: Group, width: int) -> Iterator[tuple[Element, int]]:
    for child in group.items:
        own = child.outline.width if child.outline is not None else 0
        if isinstance(child, Group):
            yield from _leaves(child, width + own)
        else:
            yield child, width + own
