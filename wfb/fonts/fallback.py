"""A stand-in for a device system font, for measuring and previewing.

Custom fonts are baked from a real TrueType source, so their metrics are exact.
**System fonts are not**: the device reference publishes each `FONT_*` symbol's
pixel *height* per device, but not its per-glyph advances, and the actual
typefaces -- Pridi, Roboto Condensed, Bionic -- are neither installed on the host
nor shipped in the SDK (the SDK carries three sample fonts, none of them device
faces).

So the width of system-font text is an estimate however it is arrived at.  This
module makes it a *good* estimate: a real scalable typeface, scaled so its line
height matches the pixel height the device publishes, measured per character
rather than assumed as a flat coefficient per character.

The same font is used by :mod:`wfb.layout` to measure and by :mod:`wfb.preview`
to draw, so the estimate and the picture cannot disagree -- the same reason the
preview consumes the resolved IR rather than laying out again (ADR 0004).

Pillow's bundled default face is used, so nothing has to be vendored or found on
the host.  It is *not* metrically identical to any Garmin face, and every
diagnostic derived from it stays labelled as an estimate.
"""

from __future__ import annotations

from functools import lru_cache

from PIL import ImageFont

#: Nominal em size used to probe the face's height ratio.
_PROBE = 100


@lru_cache(maxsize=64)
def font_for_height(pixel_height: int) -> ImageFont.FreeTypeFont | None:
    """A font whose line height is as close as possible to ``pixel_height``."""
    if pixel_height <= 0:
        return None
    try:
        probe = ImageFont.load_default(size=_PROBE)
        ascent, descent = probe.getmetrics()
        natural = ascent + descent
        if natural <= 0:
            return None
        size = max(6, round(_PROBE * pixel_height / natural))
        return ImageFont.load_default(size=size)
    except Exception:
        # Pillow older than 10.1 has no scalable default; callers fall back to
        # the crude estimate rather than failing a build over a preview detail.
        return None


#: Used only when even the fallback face is unavailable.  A flat coefficient per
#: character -- the estimate this module exists to improve on.
CRUDE_WIDTH_RATIO = 0.55


def measure(text: str, pixel_height: int) -> tuple[int, bool]:
    """Estimate the pixel width of ``text`` at ``pixel_height``.

    Returns ``(width, from_real_metrics)``.  ``from_real_metrics`` is ``False``
    when the crude coefficient had to be used, which callers report differently.
    """
    if not text:
        return 0, True
    face = font_for_height(pixel_height)
    if face is None:
        return round(len(text) * pixel_height * CRUDE_WIDTH_RATIO), False
    return round(face.getlength(text)), True
