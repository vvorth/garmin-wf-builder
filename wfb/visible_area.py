"""A screen's visible area, read from the simulator skin (research 16 §3).

The skin PNG a device's `simulator.json` names is transparent exactly where
the panel shows through: inside `display.location`, alpha 0 is lit panel and
alpha 255 is bezel. That makes it a per-device mask at the panel's own
resolution, with no per-shape geometry to guess: the Instinct octagon, its
subscreen window (a separate transparent disc behind an opaque ring), and a
rectangle's rounded corners all come out of one mechanism.

Three callers use it on any screen that is not round -- round keeps its
analytic circle, which the skin matches to within its anti-aliased rim
(`tests/test_visible_area.py` pins that):

- `wfb.layout.inside_visible_area_for`, the `safe-area`/`text-overflow`
  test, via :meth:`VisibleMask.admits`;
- `wfb.preview`, which crops to :meth:`VisibleMask.image`;
- `wfb.lint`'s `aod-burn-in`, whose denominator is the visible pixels.

Separately, `wfb preview --skin` sets a render into the whole skin
(:func:`skin`, `wfb.preview.frame_in_skin`), on every shape, round
included.

The lint allows one pixel of tolerance (:attr:`VisibleMask.hidden`): the
skins anti-alias their edges, and the Instinct 3/E skins draw a 1-px opaque
border that their own declared subscreen box contradicts (research 16 §3).
The preview and the burn-in denominator use the mask as drawn.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

from PIL import Image, ImageFilter

if TYPE_CHECKING:
    from .devices import Device

#: A skin pixel counts as panel below this alpha.
ALPHA_VISIBLE_BELOW = 128


class _Ink(Protocol):
    def bounds(self) -> tuple[float, float, float, float]: ...
    def contains(self, px: float, py: float) -> bool: ...


@dataclass(frozen=True)
class VisibleMask:
    """One device's visible area at panel resolution.

    ``visible`` is row-major, one byte per pixel, 1 where the panel shows.
    ``hidden`` maps a row to the columns the lint treats as hidden: pixels
    the skin covers whose every 8-neighbour is covered too, so an edge one
    pixel off either way is not a finding.
    """

    width: int
    height: int
    visible: bytes
    hidden: dict[int, tuple[int, ...]]

    @property
    def visible_count(self) -> int:
        return sum(self.visible)

    def image(self) -> Image.Image:
        """An ``L`` image, 255 where the panel shows and 0 elsewhere."""
        return Image.frombytes("L", (self.width, self.height),
                               bytes(255 if v else 0 for v in self.visible))

    def admits(self, ink: _Ink) -> bool:
        """Does no pixel the ink covers (tested at pixel centres) fall on
        a hidden pixel?"""
        left, top, right, bottom = ink.bounds()
        for y in range(max(0, int(top) - 1), min(self.height, int(bottom) + 2)):
            for x in self.hidden.get(y, ()):
                if left - 1 <= x <= right + 1 and ink.contains(x + 0.5, y + 0.5):
                    return False
        return True


def skin(device: "Device") -> tuple[Path, tuple[int, int, int, int]] | None:
    """The device's skin PNG and the panel's ``(x, y, width, height)`` in
    it, or ``None`` when either is missing or the location is not the
    panel's own size. Whether the location fits inside the image is left to
    the caller, which has to open the file to know."""
    path = device.skin_path
    location = device.display_location
    if path is None or location is None:
        return None
    if location[2:] != (device.width, device.height):
        return None
    return path, location


def visible_mask(device: "Device") -> VisibleMask | None:
    """The device's mask, or ``None`` when its skin or panel location is
    missing, or the location does not fit the skin at the panel's size."""
    found = skin(device)
    if found is None:
        return None
    return _load(str(found[0]), found[1])


@lru_cache(maxsize=None)
def _load(skin: str, location: tuple[int, int, int, int]) -> VisibleMask | None:
    x, y, width, height = location
    try:
        with Image.open(skin) as image:
            if x < 0 or y < 0 or x + width > image.width or y + height > image.height:
                return None
            alpha = image.convert("RGBA").crop((x, y, x + width, y + height)).getchannel("A")
    except OSError:
        return None
    covered = alpha.point(lambda a: 0 if a < ALPHA_VISIBLE_BELOW else 255)
    visible = bytes(0 if v else 1 for v in covered.tobytes())
    # Hidden with tolerance: covered, and so is every 8-neighbour. MinFilter
    # replicates the edge, so the framebuffer's own border counts as covered
    # only when the pixels inside it are.
    firmly = covered.filter(ImageFilter.MinFilter(3)).tobytes()
    hidden: dict[int, list[int]] = {}
    for index, value in enumerate(firmly):
        if value:
            hidden.setdefault(index // width, []).append(index % width)
    return VisibleMask(width, height, visible,
                       {row: tuple(cols) for row, cols in hidden.items()})
