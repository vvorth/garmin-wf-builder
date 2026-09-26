"""Host-side twin of `runtime-lib/WfbAodMask.mc` (plan 16): the moving 2x2
pixel mask over the AOD frame, applied here by `wfb.preview.render` (and so
`--heatmap`/`--minute`) and by `wfb.lint.check_aod_burn_in`, so both agree
with the device to the pixel about which minute keeps which pixel lit --
ADR 0004's anti-drift stance, extended from layout to this too. There is no
second implementation of the mask for either of those callers to drift
from; both go through `apply` below.

The mask, exactly (plan 16 §2): in minute `m`, `phase = m mod 4` selects
`(dx, dy)` from the fixed 4-cycle `PHASES`. Device pixel `(x, y)` keeps its
drawn colour iff `x mod 2 == dx` and `y mod 2 == dy`; every other pixel
becomes pure black. Each step moves the lit pixel to a 4-neighbour, never a
diagonal jump, and both 60 and 1440 are multiples of 4, so the cycle stays
continuous across the hour and the day.

The two must never drift on the phase table itself:
`tests/test_aod_mask_preview.py` (extending slice 1's own
`tests/test_aod_mask.py`) parses `PHASES`'s dx/dy logic straight out of the
real `runtime-lib/WfbAodMask.mc` source, rather than re-typing plan 16 §2 a
third time.
"""

from __future__ import annotations

import math
from functools import lru_cache

from PIL import Image

#: `[(dx, dy), ...]` indexed by `minute % 4` -- plan 16 §2, mirrored from
#: `runtime-lib/WfbAodMask.mc`'s own `dx`/`dy` expressions.
PHASES: tuple[tuple[int, int], ...] = ((0, 0), (1, 0), (1, 1), (0, 1))


def offset(minute: int) -> tuple[int, int]:
    """`(dx, dy)` for clock minute `minute` (0-59, or any integer -- only
    `minute % 4` matters, exactly as `WfbAodMask.apply`'s own `phase =
    minute % 4` does on the device)."""
    return PHASES[minute % 4]


@lru_cache(maxsize=64)
def _tiled_mask(dx: int, dy: int, width: int, height: int) -> Image.Image:
    """An `"L"` image of `width`x`height` **device** pixels: 255 at every
    pixel with `x % 2 == dx and y % 2 == dy`, 0 everywhere else.

    Built by doubling a 2x2 seed tile (`Image.paste` into a canvas twice
    its own size, on all four quadrants, repeated) rather than a per-pixel
    loop or a Python loop over every 2x2 repeat -- `O(log(max(width,
    height)))` paste calls regardless of image size, then one final crop
    to the exact size (the doubling can overshoot by at most one tile).

    Cached on `(dx, dy, width, height)`: `--heatmap` renders 1,440 frames
    that cycle through only 4 distinct phases at one fixed device
    resolution, so this is built at most 4 times a run, never once per
    frame -- the thing that keeps a 1,440-frame render fast.
    """
    tile = Image.new("L", (2, 2), 0)
    tile.putpixel((dx, dy), 255)
    while tile.width < width or tile.height < height:
        bigger = Image.new("L", (tile.width * 2, tile.height * 2), 0)
        bigger.paste(tile, (0, 0))
        bigger.paste(tile, (tile.width, 0))
        bigger.paste(tile, (0, tile.height))
        bigger.paste(tile, (tile.width, tile.height))
        tile = bigger
    return tile.crop((0, 0, width, height))


def apply(image: Image.Image, minute: int, scale: int = 1) -> Image.Image:
    """A new image with the mask applied for clock minute `minute`.

    At `scale` s, image pixel `(X, Y)` belongs to device pixel `(X // s, Y
    // s)` -- `wfb.preview.render`'s own `PreviewOptions.scale`, or `1` for
    `wfb.lint.check_aod_burn_in`'s unscaled renders. A device pixel keeps
    its drawn colour iff `X // s % 2 == dx and Y // s % 2 == dy`
    (`offset(minute)`); every other pixel of `image` becomes pure black.

    Built from a device-resolution mask (`_tiled_mask`, cheap and cached)
    upscaled `s`x with `Image.Resampling.NEAREST` -- an exact block replication, never
    a blur, so every pixel of one `s`x`s` device-pixel block gets the same
    verdict -- then composited against solid black (`Image.composite`, the
    mask's 0/255 values select one image or the other outright, with no
    partial blending since neither value is ever in between). No per-pixel
    Python loop over the full image anywhere in this path, which is what
    keeps a 1,440-frame `--heatmap` run fast.
    """
    dx, dy = offset(minute)
    scale = max(1, scale)
    width, height = image.size
    device_w = math.ceil(width / scale)
    device_h = math.ceil(height / scale)
    mask = _tiled_mask(dx, dy, device_w, device_h)
    if scale != 1:
        mask = mask.resize((device_w * scale, device_h * scale), Image.Resampling.NEAREST)
    if mask.size != image.size:
        mask = mask.crop((0, 0, width, height))
    black = Image.new(image.mode, image.size, 0)
    return Image.composite(image, black, mask)
