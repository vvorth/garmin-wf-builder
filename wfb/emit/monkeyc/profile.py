"""`wfb build --profile`: draw-time instrumentation for the active frame.

The watch has one clock a watch face can read, `System.getTimer()`, in whole
milliseconds (`$CIQ_SDK/doc/Toybox/System.html`), and one memory figure,
`System.getSystemStats().usedMemory`/`totalMemory`.  A single draw call is
usually well under a millisecond, so one call cannot be timed; instead each
frame times **one** entry, drawn ``reps`` times in a row, and accumulates the
milliseconds and the repetitions across frames.  The average per call,
``ms * 1000 / reps`` microseconds, sharpens the longer the face runs: the
timer's phase is independent of when a frame starts, so the rounding
averages out.  Timing one entry per frame keeps each frame's extra work to
``reps - 1`` draws of one element, well inside the watchdog.

An entry is every element drawn in the active frame, in draw order, plus one
per outlined group for its ring pass (`view.Rings`), plus a ``(loop)``
baseline -- the same loop with nothing in it, the overhead to subtract.
Only entries of the layout on screen are timed and shown.

Profiling is a build of its own, never a default: the instrumentation costs
code and changes what a frame does.  The static buffer is off in it, so
static content is drawn -- and timed -- live like everything else.
"""

from __future__ import annotations

from dataclasses import dataclass

from ...ir import Face, element_method_name, element_ring_method
from ...ir.rings import RingGroup, ring_groups
from ...layout import Placed, ResolvedFace
from ...units import IntBox


#: What `wfb build --profile` repeats an entry by, unless told otherwise.
DEFAULT_REPS = 10  # `wfb.cli.DEFAULT_PROFILE_REPS` is the same number

#: Fields the instrumented view adds.
NEXT = "_profNext"
MS = "_profMs"
REPS = "_profReps"
FRAME = "_profFrame"


@dataclass(frozen=True)
class Entry:
    """One timed thing: an element's draw call, a group's ring pass, or the
    empty-loop baseline (``placed`` is `None`)."""

    label: str
    #: The element, or the outlined group, whose box the label sits on.
    placed: Placed | None
    #: `face.layouts` index, or -1 for shared content (and the baseline).
    layout: int
    #: A ring pass's `ring<Id>` methods, one per member.
    members: tuple[str, ...] = ()


@dataclass(frozen=True)
class ProfilePlan:
    reps: int
    entries: tuple[Entry, ...]
    #: Whether the face has `layouts:`, so `_configLayout` exists to filter by.
    layouts: bool

    def index(self, label: str) -> int:
        return next(i for i, entry in enumerate(self.entries) if entry.label == label)


def plan(resolved: ResolvedFace, rings: list[RingGroup], reps: int) -> ProfilePlan:
    """The entries of the active frame, in draw order, for ``resolved``.
    Device-independent -- the order and the ids are the same on every
    target -- so the shared view and each device's `Layout` agree."""
    face = resolved.face
    by_id = {placed.id: placed for placed in resolved.items}

    def layout_index(placed: Placed) -> int:
        layout = placed.element.layout
        return face.layouts.index(layout) if layout is not None else -1

    drawn = [p for p in resolved.items if p.kind != "group" and "active" in p.element.modes]
    entries: list[Entry] = [Entry("(loop)", None, -1)]
    started: set[str] = set()
    for placed in drawn:
        for ring in rings:
            members = [p for p in drawn if p.id in ring.ids]
            if members and members[0] is placed and ring.group.id not in started:
                started.add(ring.group.id)
                group = by_id[ring.group.id]
                entries.append(Entry(f"{ring.group.id}.ring", group, layout_index(members[0]),
                                     tuple(element_ring_method(p.id, ring.width_of(p.id))
                                           for p in members)))
        entries.append(Entry(placed.id, placed, layout_index(placed)))
    return ProfilePlan(reps, tuple(entries), bool(face.layouts))


def code_report(profile: ProfilePlan, face: Face, sizes: dict[str, int]) -> list[str]:
    """The build-time half of profiling: each entry's code, in bytes, from
    `wfb.build.method_code_sizes` -- its `draw<Id>` method (an element's
    own ring included), or for a ring pass every member's `ring<Id>` -- and
    each layout's total, what a layout costs against the memory limit."""
    view = f"{face.entry}View"
    lines = [f"{'entry':<28} {'code':>7}"]
    per_layout: dict[int, int] = {}
    for entry in profile.entries[1:]:
        if entry.members:
            size = sum(sizes.get(f"{view}.{method}", 0) for method in entry.members)
        else:
            size = sizes.get(f"{view}.{element_method_name(entry.label)}", 0)
        per_layout[entry.layout] = per_layout.get(entry.layout, 0) + size
        lines.append(f"{entry.label:<28} {size:>6} B")
    lines.append("")
    for index, total in sorted(per_layout.items()):
        name = "(shared)" if index < 0 else f"layout {face.layouts[index]}"
        lines.append(f"{name:<28} {total:>6} B")
    return lines


def plan_for(resolved: ResolvedFace, reps: int) -> ProfilePlan:
    return plan(resolved, ring_groups(resolved.face.elements), reps)


def label_box(entry: Entry) -> IntBox:
    """Where an entry's reading is drawn: above its element's (or group's)
    own box.  The baseline has no box: the header line shows it."""
    if entry.placed is None:
        return IntBox(0, 0, 0, 0)
    return entry.placed.inner_box


def layout_lines(resolved: ResolvedFace, profile: ProfilePlan) -> list[str]:
    """This device's `Layout` constants for the overlay: each entry's label
    anchor (the centre of its box's top edge), each entry's layout index,
    and the header line's anchor."""
    device = resolved.device
    xs, ys = [], []
    for entry in profile.entries:
        box = label_box(entry)
        xs.append(str(box.x + box.width // 2))
        ys.append(str(box.y))
    layouts = ", ".join(str(entry.layout) for entry in profile.entries)
    return [
        f"const PROF_X as Array<Number> = [{', '.join(xs)}] as Array<Number>;",
        f"const PROF_Y as Array<Number> = [{', '.join(ys)}] as Array<Number>;",
        f"const PROF_LAYOUT as Array<Number> = [{layouts}] as Array<Number>;",
        f"const PROF_HEAD_X as Number = {device.width // 2};",
        f"const PROF_HEAD_Y as Number = {device.height // 8};",
    ]
