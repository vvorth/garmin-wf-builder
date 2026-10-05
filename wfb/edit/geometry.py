"""Geometry edits on one device: a drag in device pixels written back in
the author's own units, to the key that sets it on that device.

**The override target.** An element's `overrides:` patch
for a device id is merged over its `shape:` patch, and both over the
element's own keys, key by key. Patching a key the viewed device does not
read would change nothing on screen, so a drag writes the most specific
source of the key for that device: the device-id override, then the
`shape:` override, then the element's own key. A caller may instead name
the scope ("all targets", "this device", "this shape"); the override is
then created when it does not exist yet.

**Units.** Every unit is linear in pixels, so a pixel
delta is a division: `px` 1, `%r` the screen's minor radius / 100, `%` the
parent box's extent on that axis / 100, `pt` the font's pixel height. A
polar `at:` is re-expressed about its anchor: a new angle and radius. The
value is rounded to the coarsest step that still lands on the dragged
pixel on this device, and that is checked by placing the patched text
through the real layout, never assumed.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path as FilePath
from typing import TYPE_CHECKING, Any, Callable, Literal

from ..devices import Device
from ..ir import Element, Face, Group
from ..ir.model import Position, Shape
from ..layout import Placed, ResolvedFace, Resolver
from ..units import Axis, Box, Length, UnitError
from .gate import Loaded, load_text
from .patch import Patch, number, set_scalars, set_value

if TYPE_CHECKING:
    from ..emit.resources import BakeMemo
from .spans import Path, Refused, SpanIndex, dotted, index_for, is_element

Scope = Literal["auto", "all", "device", "shape"]

#: Rounding steps, coarsest first, per unit.
LENGTH_STEPS: dict[str, tuple[float, ...]] = {
    "px": (10, 5, 1, 0.5, 0.1),
    "%": (10, 5, 1, 0.5, 0.1, 0.05, 0.01),
    "%r": (10, 5, 1, 0.5, 0.1, 0.05, 0.01),
    "pt": (1, 0.5, 0.1, 0.05, 0.01),
}
ANGLE_STEPS: dict[str, tuple[float, ...]] = {
    "deg": (15, 5, 1, 0.5, 0.1, 0.05, 0.01),
    "rad": (0.1, 0.05, 0.01, 0.005, 0.001, 0.0005),
    "turn": (0.05, 0.01, 0.005, 0.001, 0.0005, 0.0001),
}
_DEGREES_PER = {"deg": 1.0, "rad": 180.0 / math.pi, "turn": 360.0}

#: The extent keys a resize may change, and what it measures on the
#: placed element to check that it landed.
EXTENTS: dict[tuple[str, ...], Callable[[Placed], int]] = {
    ("size", "width"): lambda p: _sized(p, 0),
    ("size", "height"): lambda p: _sized(p, 1),
    ("radius",): lambda p: int(getattr(p, "radius")),
    ("thickness",): lambda p: int(getattr(p, "thickness")),
}


def _sized(placed: Placed, axis: int) -> int:
    """The extent `size:` gave: a gauge records it, since its ticks grow its
    box past it; every other boxed kind's box is it."""
    size = getattr(placed, "size", None)
    if isinstance(size, tuple) and len(size) == 2:
        return int(size[axis])
    box = placed.inner_box
    return box.width if axis == 0 else box.height


# -- the override target ----------------------------------------------------------

def selector_paths(device: Device) -> tuple[Path, Path]:
    return ("overrides", device.id), ("overrides", f"shape:{device.shape}")


def target(index: SpanIndex, element: Path, key: Path, device: Device,
           scope: Scope = "auto") -> Path:
    """The author path a geometry ``key`` (`("at", "dy")`) of ``element`` is
    written to on ``device``: for "auto", the most specific source that
    exists; otherwise the named scope's, which may not exist yet."""
    by_device, by_shape = selector_paths(device)
    if scope == "device":
        return element + by_device + key
    if scope == "shape":
        return element + by_shape + key
    if scope == "auto":
        for selector in (by_device, by_shape):
            if index.get(element + selector + key) is not None:
                return element + selector + key
    return element + key


# -- units ----------------------------------------------------------------------

@dataclass(frozen=True)
class Spelling:
    """How the author writes a value: its unit, and whether as a bare
    number (`12`, read as `px` or `deg`) rather than a string."""

    unit: str
    bare: bool = False

    def write(self, value: float) -> Any:
        if self.bare:
            return int(value) if float(value).is_integer() else float(number(value))
        return f"{number(value)}{self.unit}"


def length_spelling(raw: Any) -> Spelling:
    length = Length.parse(raw)
    return Spelling(length.unit, bare=not isinstance(raw, str))


def angle_spelling(raw: Any) -> Spelling:
    if not isinstance(raw, str):
        return Spelling("deg", bare=True)
    text = raw.strip()
    unit = next((u for u in ("turn", "rad", "deg") if text.endswith(u)), "deg")
    return Spelling(unit, bare=not text.endswith(unit))


def px_per_unit(unit: str, *, axis: Axis, parent: Box, minor_radius: float,
                font_px: float | None = None) -> float:
    if unit == "px":
        return 1.0
    if unit == "%r":
        return minor_radius / 100.0
    if unit == "%":
        extent = {Axis.X: parent.width, Axis.Y: parent.height}.get(
            axis, min(parent.width, parent.height))
        return extent / 100.0
    if unit == "pt":
        if font_px is None:
            raise Refused("a pt length has no pixel size here; write it in px, % or %r")
        return font_px
    raise Refused(f"unknown unit {unit!r}")


def rounded(value: float, step: float) -> float:
    return round(round(value / step) * step, 6)


def candidates(ideal: float, steps: tuple[float, ...], px_per: float) -> list[float]:
    """``ideal`` rounded to each step, coarsest first, keeping only those
    within half a pixel of it (the rest cannot land) and each once."""
    out: list[float] = []
    for step in steps:
        value = rounded(ideal, step)
        if abs(value - ideal) * abs(px_per) < 0.5 and value not in out:
            out.append(value)
    finest = rounded(ideal, steps[-1])
    if finest not in out:
        out.append(finest)
    return out


# -- the viewed device --------------------------------------------------------------

class View:
    """One design's text placed on one device: the face, its baked fonts and
    its resolved layout, with the author index for the same text."""

    def __init__(self, path: FilePath, text: str, device: Device, *,
                 loaded: Loaded | None = None, resolved: ResolvedFace | None = None,
                 memo: "BakeMemo | None" = None) -> None:
        """``loaded`` and ``resolved`` are ``text`` already loaded and placed
        on ``device``, when the caller has them (an editor's analysis);
        ``memo`` reuses font sheets."""
        from ..emit.resources import bake_fonts

        self.path = path
        self.device = device
        self.memo = memo
        self.tried: Loaded | None = None
        self.index = index_for(text)
        self.loaded = loaded if loaded is not None and loaded.text == text else load_text(
            path, text)
        if self.loaded.face is None:
            raise Refused("the design does not load: "
                          + "; ".join(d.message for d in self.loaded.errors[:1]))
        self.face: Face = self.loaded.face
        if resolved is not None and resolved.face is self.face:
            self.fonts = resolved.fonts
            self.resolved = resolved
        else:
            self.fonts = (bake_fonts(self.face, device) if memo is None
                          else bake_fonts(self.face, device, memo))
            self.resolved = self.place(self.loaded)

    def place(self, loaded: Loaded, rebake: bool = False) -> ResolvedFace:
        from ..emit.resources import bake_fonts
        from ..layout import resolve

        assert loaded.face is not None
        if rebake:
            fonts = (bake_fonts(loaded.face, self.device) if self.memo is None
                     else bake_fonts(loaded.face, self.device, self.memo))
        else:
            fonts = self.fonts
        return resolve(loaded.face, self.device, fonts)

    def placed(self, element_id: str, resolved: ResolvedFace | None = None) -> Placed:
        for item in (resolved or self.resolved).items:
            if item.id == element_id:
                return item
        raise Refused(f"{element_id} is not drawn on {self.device.id}")

    def element(self, element_id: str) -> Element:
        for element in self.face.walk():
            if element.id == element_id:
                return element
        raise Refused(f"there is no element called {element_id}")

    def author_path(self, element_id: str) -> Path:
        entry = self.index.at_span(self.element(element_id).span)
        if entry is None or not is_element(self.index, entry):
            # the `static:` block's own group, or a layout's: a container,
            # not an element with geometry of its own
            raise Refused(f"{element_id} is a block, not an element: move what is in it")
        return entry.path

    def effective(self, element_id: str) -> Element:
        """The element with this device's overrides merged in."""
        return Resolver(self.face, self.device, self.fonts).for_device(self.element(element_id))

    def parent_box(self, element_id: str) -> Box:
        element = self.element(element_id)
        parent = _parent_group(self.face.elements, element)
        if parent is not None:
            b = self.placed(parent.id).box
            return Box(b.x, b.y, b.width, b.height)
        if element.in_subscreen and self.device.subscreen is not None:
            return Box(*self.device.subscreen)
        return Box(0, 0, self.device.width, self.device.height)

    def try_patch(self, patch: Patch, element_id: str, rebake: bool = False) -> Placed | None:
        loaded = load_text(self.path, patch.text)
        #: The last text placed, loaded: what a caller's gate can reuse.
        self.tried = loaded
        if loaded.face is None:
            return None
        return self.placed(element_id, self.place(loaded, rebake))


def _parent_group(elements: list[Element], target: Element) -> Group | None:
    for element in elements:
        if isinstance(element, Group):
            if any(child is target or child.id == target.id for child in element.items):
                return element
            found = _parent_group(element.items, target)
            if found is not None:
                return found
    return None


# -- moves and resizes ----------------------------------------------------------------

@dataclass(frozen=True)
class Converted:
    """A geometry edit in the author's units: the patch, and whether placing
    it put the element on the dragged pixel on the viewed device."""

    patch: Patch
    landed: bool


@dataclass(frozen=True)
class _Key:
    """One author key a move or resize writes: where it is read from on this
    device, where it is written, and its candidate values, coarsest first."""

    write: Path
    spelling: Spelling
    values: list[float]


def _apply(index: SpanIndex, keys: list[_Key], level: int) -> Patch:
    whats = ", ".join(dotted(k.write) for k in keys)
    values = [(k.write, k.spelling.write(k.values[min(level, len(k.values) - 1)])) for k in keys]
    # keys already written are rewritten in place, with no index between them
    together = set_scalars(index, values)
    if together is not None:
        return Patch(together.text, together.expected, f"set {whats}")
    patch: Patch | None = None
    current = index
    for key in keys:
        value = key.spelling.write(key.values[min(level, len(key.values) - 1)])
        patch = set_value(current, key.write, value)
        current = index_for(patch.text)
    assert patch is not None
    return Patch(patch.text, patch.expected, f"set {whats}")


def _settle(view: View, keys: list[_Key], element_id: str,
            landed: Callable[[Placed], bool], rebake: bool = False) -> Converted:
    if not keys:
        return Converted(Patch(view.index.text, view.index.data, "nothing to change"), True)
    levels = max(len(k.values) for k in keys)
    patch = None
    for level in range(levels):
        patch = _apply(view.index, keys, level)
        placed = view.try_patch(patch, element_id, rebake)
        if placed is not None and landed(placed):
            return Converted(patch, True)
    assert patch is not None
    return Converted(patch, False)


def _position_keys(view: View, element_id: str, element: Path, prefix: str,
                   position: Position, dx: float, dy: float, scope: Scope) -> list[_Key]:
    """The keys a move of ``position`` (`at:` or a line's `to:`) by
    ``(dx, dy)`` px writes, with their candidate values."""
    parent = view.parent_box(element_id)
    minor = view.device.minor_radius
    index = view.index

    def source(key: str) -> Any:
        entry = index.get(target(index, element, (prefix, key), view.device))
        return _data(index, entry.path) if entry is not None else None

    keys: list[_Key] = []
    if position.is_polar:
        assert position.angle is not None and position.radius is not None
        r_raw, a_raw = source("radius"), source("angle")
        r_spell = length_spelling(r_raw if r_raw is not None else str(position.radius))
        a_spell = angle_spelling(a_raw if a_raw is not None else f"{position.angle.degrees:g}deg")
        r_per = px_per_unit(r_spell.unit, axis=Axis.MINOR, parent=parent, minor_radius=minor)
        r_px = position.radius.resolve(box=parent, axis=Axis.MINOR, minor_radius=minor)
        theta = math.radians(position.angle.degrees)
        ox, oy = r_px * math.sin(theta) + dx, -r_px * math.cos(theta) + dy
        new_r = math.hypot(ox, oy)
        new_deg = math.degrees(math.atan2(ox, -oy)) if new_r else position.angle.degrees
        # stay on the author's side of the circle: 350deg dragged a little
        # clockwise is 352deg, not -8deg
        new_deg += 360.0 * round((position.angle.degrees - new_deg) / 360.0)
        per_deg = _DEGREES_PER[a_spell.unit]
        a_per = math.radians(per_deg) * max(new_r, 1.0)
        keys.append(_Key(target(index, element, (prefix, "angle"), view.device, scope), a_spell,
                         candidates(new_deg / per_deg, ANGLE_STEPS[a_spell.unit], a_per)))
        keys.append(_Key(target(index, element, (prefix, "radius"), view.device, scope), r_spell,
                         candidates(new_r / r_per, LENGTH_STEPS[r_spell.unit], r_per)))
        return keys
    for key, delta, axis, length in (("dx", dx, Axis.X, position.dx),
                                     ("dy", dy, Axis.Y, position.dy)):
        if not delta:
            continue
        raw = source(key)
        if raw is not None:
            spelling = length_spelling(raw)
        else:
            sibling = source("dy" if key == "dx" else "dx")
            spelling = length_spelling(sibling) if sibling is not None else Spelling("%r")
        if spelling.unit == "pt":
            raise Refused(f"{dotted(element + (prefix, key))} is in pt, which has no "
                          "pixel size for a position; write it in px, % or %r")
        per = px_per_unit(spelling.unit, axis=axis, parent=parent, minor_radius=minor)
        current = length.resolve(box=parent, axis=axis, minor_radius=minor) / per if length else 0.0
        keys.append(_Key(target(index, element, (prefix, key), view.device, scope), spelling,
                         candidates(current + delta / per, LENGTH_STEPS[spelling.unit], per)))
    return keys


def _data(index: SpanIndex, path: Path) -> Any:
    data = index.data
    for step in path:
        data = data[step]
    return data


Part = Literal["both", "at", "to"]


def move(view: View, element_id: str, dx: int, dy: int, scope: Scope = "auto",
         part: Part = "both") -> Converted:
    """Move ``element_id`` by ``(dx, dy)`` device pixels on the view's
    device: its `at:` (and a line's `to:`) rewritten in the author's units.
    A line's ``part`` "at" or "to" moves that end alone."""
    element = view.author_path(element_id)
    effective = view.effective(element_id)
    if isinstance(effective, Shape) and effective.shape == "polygon":
        raise Refused(f"{element_id} is a polygon: move its points: in the text")
    line = isinstance(effective, Shape) and effective.shape == "line"
    if part != "both" and not line:
        raise Refused(f"{element_id} is not a line: it has no ends to move apart")
    before = view.placed(element_id)
    keys: list[_Key] = []
    checks: list[Callable[[Placed], bool]] = []
    if part in ("both", "at"):
        keys += _position_keys(view, element_id, element, "at", effective.at, dx, dy, scope)
        goal = (before.center[0] + dx, before.center[1] + dy)
        checks.append(lambda p: p.center == goal)
    if line and part in ("both", "to"):
        assert isinstance(effective, Shape)
        to = effective.to or Position()
        keys += _position_keys(view, element_id, element, "to", to, dx, dy, scope)
        end = getattr(before, "end")
        end_goal = (end[0] + dx, end[1] + dy)
        checks.append(lambda p: getattr(p, "end") == end_goal)
    return _settle(view, keys, element_id, lambda p: all(c(p) for c in checks))


#: The angle keys `turn` writes, and what it reads back on the placed element.
ANGLES = frozenset({"start_angle", "sweep"})


def turn(view: View, element_id: str, key: str, degrees: float,
         scope: Scope = "auto") -> Converted:
    """Set an arc's ``key`` (`start_angle` or `sweep`) to ``degrees`` (12
    o'clock = 0, clockwise) on the view's device, in the author's unit,
    rounded to the coarsest step within half a degree."""
    if key not in ANGLES:
        raise Refused(f"{key} is not start_angle or sweep")
    element = view.author_path(element_id)
    effective = view.effective(element_id)
    # every shape carries the angle fields; only an arc draws them
    shape = getattr(effective, "shape", None)
    if (shape is not None and shape != "arc") or not hasattr(effective, key) \
            or not hasattr(view.placed(element_id), key):
        raise Refused(f"{element_id} has no {key}")
    entry = view.index.get(target(view.index, element, (key,), view.device))
    spelling = (angle_spelling(_data(view.index, entry.path)) if entry is not None
                else Spelling("deg"))
    per = _DEGREES_PER[spelling.unit]
    keys = [_Key(target(view.index, element, (key,), view.device, scope), spelling,
                 candidates(degrees / per, ANGLE_STEPS[spelling.unit], per))]
    return _settle(view, keys, element_id,
                   lambda p: abs(float(getattr(p, key)) - degrees) < 0.5)


def resize(view: View, element_id: str, key: tuple[str, ...], delta: int,
           scope: Scope = "auto") -> Converted:
    """Change the extent ``key`` (`("size", "width")`, `("radius",)`,
    `("thickness",)`) of ``element_id`` by ``delta`` device pixels, as the
    view's device measures it."""
    if key not in EXTENTS:
        raise Refused(f"{dotted(key)} is not a size, radius or thickness")
    element = view.author_path(element_id)
    effective = view.effective(element_id)
    length: Any = effective
    for step in key:
        length = getattr(length, step, None)
    if not isinstance(length, Length):
        raise Refused(f"{element_id} has no {dotted(key)} to resize")
    measure = EXTENTS[key]
    before = view.placed(element_id)
    goal = measure(before) + delta
    if goal < 1:
        raise Refused(f"{element_id}'s {dotted(key)} cannot be smaller than 1 px")
    entry = view.index.get(target(view.index, element, key, view.device))
    spelling = (length_spelling(_data(view.index, entry.path)) if entry is not None
                else Spelling(length.unit))
    axis = {"width": Axis.X, "height": Axis.Y}.get(key[-1], Axis.MINOR)
    per = px_per_unit(spelling.unit, axis=axis, parent=view.parent_box(element_id),
                      minor_radius=view.device.minor_radius)
    try:
        current = length.resolve(box=view.parent_box(element_id), axis=axis,
                                 minor_radius=view.device.minor_radius) / per
    except UnitError as exc:
        raise Refused(str(exc)) from None
    keys = [_Key(target(view.index, element, key, view.device, scope), spelling,
                 candidates(current + delta / per, LENGTH_STEPS[spelling.unit], per))]
    return _settle(view, keys, element_id, lambda p: measure(p) == goal,
                   rebake=effective.kind == "icon")
