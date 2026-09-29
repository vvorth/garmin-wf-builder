"""Outlined groups (research 19): which leaves an outlined `group`'s ring goes
round.

A group's ring is the union of its members' 1px dilations, drawn just before
the group's first member -- every member's ring, then every member.  Every
ring is :data:`OUTLINE_WIDTH` px, so a member of an outlined group carries
no ring of its own and no outlined group nests inside another: either would
make the group's ring go round a ring, 2px from the member
(`ElementTree.check_group_outlines` refuses both).  Codegen
(`wfb.emit.monkeyc.view`) and the preview (`wfb.preview`) both read this one
answer.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass

from .model import Element, Group


@dataclass(frozen=True)
class RingGroup:
    """One outlined group, and every leaf it rings, in authored order."""

    group: Group
    members: tuple[Element, ...]

    @property
    def ids(self) -> frozenset[str]:
        return frozenset(leaf.id for leaf in self.members)


def ring_groups(elements: list[Element]) -> list[RingGroup]:
    """Every outlined group under ``elements``, outermost first."""
    out: list[RingGroup] = []

    def walk(element: Element) -> None:
        if isinstance(element, Group):
            if element.outline is not None:
                out.append(RingGroup(element, tuple(_leaves(element))))
            for child in element.items:
                walk(child)

    for element in elements:
        walk(element)
    return out


def _leaves(group: Group) -> Iterator[Element]:
    for child in group.items:
        if isinstance(child, Group):
            yield from _leaves(child)
        else:
            yield child


def ringed_below(group: Group) -> Iterator[Element]:
    """Every element under ``group`` that has an `outline:` of its own --
    a leaf, or a nested group."""
    for child in group.items:
        if child.outline is not None:
            yield child
        if isinstance(child, Group):
            yield from ringed_below(child)
