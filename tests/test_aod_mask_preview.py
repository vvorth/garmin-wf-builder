"""`aod: {mask: ...}` (plan 16 slice 2): the host-side twin
(`wfb/aod_mask.py`), preview integration (`wfb/preview.py`) and the
burn-in lint's masked scoring (`wfb/lint.py::check_aod_burn_in`). Slice 1
(`tests/test_aod_mask.py`) covers format + codegen only.

Each test names, in its own docstring, the contrast it drives -- the same
discipline `tests/test_aod.py` documents at its own top
(`docs/lore/working-agreement.md`: a guard nobody has watched fail is not a
guard).
"""

from __future__ import annotations

import re
from dataclasses import replace as dc_replace
from pathlib import Path

from tests.test_diagnostics import load
from wfb import aod_mask, lint
from wfb.diagnostics import Bag
from wfb.emit.resources import bake_fonts
from wfb.layout import resolve
from wfb.preview import PreviewOptions, render, render_aod_heatmap

ROOT = Path(__file__).resolve().parent.parent

BASE = """
format: 1
face:
  id: 7f3c1e92-4a5b-4d81-9e6f-2b0c8d4a1f57
  name: Test
targets: [fenix847mm]
palette:
  bg: "#000000"
  fg: "#FFFFFF"
"""

#: One AOD-shown disc, big enough to leave plenty of non-black pixels to
#: check the phase rule against.
_DISC = """
elements:
  - id: disc
    type: shape
    shape: circle
    at: {anchor: center}
    radius: 80%r
    filled: true
    color: palette.fg
    aod: show
"""


def _resolved(text, write_design, bag, db, device_id="fenix847mm"):
    face = load(write_design(text), bag)
    assert face is not None, bag.render()
    device = db.get(device_id)
    return resolve(face, device, bake_fonts(face, device))


def _example(bag, db, device_id="fenix847mm"):
    face = load(ROOT / "examples" / "features" / "aod" / "face.yaml", bag)
    assert face is not None, bag.render()
    device = db.get(device_id)
    return resolve(face, device, bake_fonts(face, device))


# --------------------------------------------------------------------------
# the phase table: Python and Monkey C must never drift (same discipline as
# slice 1's own `test_phase_table_matches_the_plan`, extended to this
# module's own `PHASES`)


def test_phases_match_the_device_source():
    """`wfb.aod_mask.PHASES` must equal the dx/dy logic parsed straight out
    of `runtime-lib/WfbAodMask.mc` -- not re-typed from the plan a third
    time. Must fail against a `PHASES` with a transposed dx/dy or a
    reordered phase."""
    text = (ROOT / "runtime-lib" / "WfbAodMask.mc").read_text()
    dx_match = re.search(r"var dx = \((?P<cond>.*?)\) \? 1 : 0;", text)
    dy_match = re.search(r"var dy = \((?P<cond>.*?)\) \? 1 : 0;", text)
    assert dx_match, text
    assert dy_match, text

    def _as_python(cond: str) -> str:
        return cond.replace("||", " or ").replace("&&", " and ")

    for phase in range(4):
        env = {"phase": phase}
        dx = 1 if eval(_as_python(dx_match.group("cond")), {}, env) else 0  # noqa: S307
        dy = 1 if eval(_as_python(dy_match.group("cond")), {}, env) else 0  # noqa: S307
        assert aod_mask.PHASES[phase] == (dx, dy)


# --------------------------------------------------------------------------
# `wfb.aod_mask.apply` in isolation: the mask, exactly, at two scales


def test_apply_keeps_exactly_the_phase_pixels_at_scale_1():
    """A solid white image at scale 1: for each minute 0-3, exactly the
    pixels with `x % 2 == dx` and `y % 2 == dy` stay white, every other
    pixel is pure black. Must fail against a mask that is inverted,
    off-by-one, or ignores the minute."""
    from PIL import Image

    for minute in range(4):
        dx, dy = aod_mask.PHASES[minute]
        image = Image.new("RGB", (8, 8), (255, 255, 255))
        out = aod_mask.apply(image, minute)
        px = out.load()
        for y in range(8):
            for x in range(8):
                expected = (255, 255, 255) if (x % 2 == dx and y % 2 == dy) else (0, 0, 0)
                assert px[x, y] == expected, (minute, x, y, px[x, y], expected)


def test_apply_keeps_whole_blocks_at_scale_3():
    """At scale 3, a device pixel is a 3x3 block of image pixels: the kept
    region must be exactly the s x s blocks of kept device pixels, not a
    single kept pixel per block or a shifted block. Must fail against an
    implementation that only scales the *kept-pixel* pattern to scale 1
    (e.g. one lit pixel per 2x2 device tile, not per 2x2 *block* tile)."""
    from PIL import Image

    scale = 3
    minute = 2  # (dx, dy) = (1, 1)
    dx, dy = aod_mask.PHASES[minute]
    size = 4 * scale  # a 4x4 device-pixel grid
    image = Image.new("RGB", (size, size), (255, 255, 255))
    out = aod_mask.apply(image, minute, scale=scale)
    px = out.load()
    for y in range(size):
        for x in range(size):
            device_x, device_y = x // scale, y // scale
            expected = (255, 255, 255) if (device_x % 2 == dx and device_y % 2 == dy) \
                else (0, 0, 0)
            assert px[x, y] == expected, (x, y, px[x, y], expected)


# --------------------------------------------------------------------------
# preview integration: `render(--aod)` matches the mask exactly, and the
# lit pixel moves off every minute


def test_render_aod_obeys_the_phase_rule_for_its_own_minute(write_design, bag, db):
    """Every non-black pixel of a masked `--aod` render must satisfy the
    phase rule for the render's own minute. Must fail against a preview
    that never applies the mask, or applies the wrong minute's phase."""
    resolved = _resolved(BASE + _DISC, write_design, bag, db)
    options = PreviewOptions(scale=1, mask_shape=False, aod=True, time=(8, 37, 0))
    image = render(resolved, options)
    dx, dy = aod_mask.offset(37)
    px = image.load()
    w, h = image.size
    for y in range(h):
        for x in range(w):
            if px[x, y] != (0, 0, 0):
                assert x % 2 == dx and y % 2 == dy, (x, y, px[x, y])


def test_render_aod_pixel_lit_at_minute_m_is_black_at_m_plus_1(write_design, bag, db):
    """A pixel lit at minute m must be black at minute m+1 -- the "no pixel
    lit two consecutive minutes" guarantee plan 16 promises. Must fail
    against a preview that reuses the same phase for consecutive minutes."""
    resolved = _resolved(BASE + _DISC, write_design, bag, db)
    options_m = PreviewOptions(scale=1, mask_shape=False, aod=True, time=(8, 37, 0))
    image_m = render(resolved, options_m)
    px_m = image_m.load()
    lit = next(
        (x, y) for y in range(image_m.height) for x in range(image_m.width)
        if px_m[x, y] != (0, 0, 0)
    )
    options_m1 = PreviewOptions(scale=1, mask_shape=False, aod=True, time=(8, 38, 0))
    image_m1 = render(resolved, options_m1)
    assert image_m1.getpixel(lit) == (0, 0, 0)


def test_mask_false_matches_unmasked_render_and_differs_from_masked(write_design, bag, db):
    """`aod: {mask: false}` must render exactly the unmasked frame
    (identical to `aod_mask=False`), and that unmasked frame must differ
    from the masked (default) render of the same design. Must fail against
    an implementation that ignores `Face.aod_mask` in `render`, or one that
    masks regardless of it."""
    text_on = BASE + _DISC
    text_off = BASE.replace("palette:\n", "aod:\n  mask: false\npalette:\n") + _DISC

    bag_on, bag_off = Bag(), Bag()
    resolved_on = _resolved(text_on, write_design, bag_on, db)
    resolved_off = _resolved(text_off, write_design, bag_off, db)

    options = PreviewOptions(scale=1, mask_shape=False, aod=True, time=(8, 37, 0))
    image_on = render(resolved_on, options)
    image_off = render(resolved_off, options)
    image_off_explicit_unmasked = render(
        resolved_off, dc_replace(options, aod_mask=False)
    )

    assert image_off.tobytes() == image_off_explicit_unmasked.tobytes()
    assert image_on.tobytes() != image_off.tobytes()


def test_masked_render_matches_apply_directly(write_design, bag, db):
    """`render`'s own masking must be exactly `wfb.aod_mask.apply` over the
    unmasked render -- no second, drifted implementation inside
    `wfb.preview`. Must fail against a preview that reimplements the mask
    instead of calling `wfb.aod_mask.apply`."""
    resolved = _resolved(BASE + _DISC, write_design, bag, db)
    options = PreviewOptions(scale=1, mask_shape=False, aod=True, time=(8, 37, 0))
    unmasked = render(resolved, dc_replace(options, aod_mask=False))
    expected = aod_mask.apply(unmasked, 37)
    actual = render(resolved, options)
    assert actual.tobytes() == expected.tobytes()


# --------------------------------------------------------------------------
# heatmap: peak <= 25% masked, much higher unmasked


#: 12 consecutive minutes -- exactly three full 4-phase cycles, not the
#: full 1,440-minute day (root CLAUDE.md: heatmap renders 1,440 frames, so
#: a unit test must not).
_HEATMAP_MINUTES = range(0, 12)


def test_heatmap_peak_is_at_most_a_quarter_when_masked(bag, db):
    """The shipped AOD example, masked (the default): the heatmap's own
    peak share must be <= 25% by construction (plan 16). Must fail against
    a heatmap that does not apply the mask, or applies it inconsistently
    across frames."""
    resolved = _example(bag, db)
    _, peak = render_aod_heatmap(
        resolved, PreviewOptions(scale=1, mask_shape=False), minutes=_HEATMAP_MINUTES,
    )
    assert peak <= 0.25 + 1e-9


def _example_with_mask_false(write_design, bag, db, device_id="fenix847mm"):
    """The shipped AOD example's own text, with `mask: false` spliced into
    its existing face-level `aod:` block -- written through `write_design`
    (a tmp path), never back into the repo tree."""
    text = (ROOT / "examples" / "features" / "aod" / "face.yaml").read_text()
    assert "mask: false" not in text
    marker = "aod:\n  default: hide\n  dim: 0.6\n"
    assert marker in text, "fixture assumption about the example's own aod: block broke"
    text = text.replace(marker, marker.rstrip("\n") + "\n  mask: false\n")
    face = load(write_design(text), bag)
    assert face is not None, bag.render()
    device = db.get(device_id)
    return resolve(face, device, bake_fonts(face, device))


def test_heatmap_peak_is_higher_with_mask_false(write_design, bag, db):
    """The same example with `aod: {mask: false}`: the heatmap's peak must
    exceed the masked peak by a wide margin (a static pixel across all 12
    sampled minutes lights every one of them). Must fail against a heatmap
    that keeps masking even when the face opted out."""
    resolved = _example_with_mask_false(write_design, bag, db)
    _, peak_off = render_aod_heatmap(
        resolved, PreviewOptions(scale=1, mask_shape=False), minutes=_HEATMAP_MINUTES,
    )
    assert peak_off > 0.9


# --------------------------------------------------------------------------
# the burn-in lint: masked figures are about a quarter of the unmasked
# figures, and `mask: false` keeps the old message shape verbatim


#: The exact shape the message had before plan 16 slice 2 (no "with the
#: pixel mask" clause) -- `mask: false` must reproduce this verbatim.
_OLD_MESSAGE_RE = re.compile(
    r"^fenix847mm: the AOD frame lights [\d.]+% of pixels and [\d.]+% of luminance at "
    r"\d\d:\d\d \(Garmin's 10% rule, research 11 §1\.2\) -- top contributor: .+$"
)


def _burn_in_lit_fraction(resolved):
    bag = Bag()
    lint.check_aod_burn_in(resolved, bag)
    hits = [d for d in bag.items if d.code == "aod-burn-in"]
    assert hits, bag.render()
    match = re.search(r"lights ([\d.]+)% of pixels", hits[0].message)
    assert match, hits[0].message
    return float(match.group(1)) / 100.0, hits[0].message


def test_burn_in_masked_lit_fraction_is_about_a_quarter_of_unmasked(write_design, bag, db):
    """The shipped example's masked lit fraction must sit at roughly 1/4 of
    the `mask: false` figure (a band, not an exact ratio, since sampling
    two clock times and 4 phases does not reduce to a clean 4x on real
    geometry). Must fail against a lint that does not apply the mask at
    all when scoring (the ratio would then be ~1.0)."""
    resolved_on = _example(bag, db)
    lit_on, message_on = _burn_in_lit_fraction(resolved_on)
    assert "with the pixel mask" in message_on

    resolved_off = _example_with_mask_false(write_design, bag, db)
    lit_off, message_off = _burn_in_lit_fraction(resolved_off)

    assert "with the pixel mask" not in message_off
    assert _OLD_MESSAGE_RE.match(message_off), message_off

    ratio = lit_on / lit_off
    assert 0.15 <= ratio <= 0.35, (lit_on, lit_off, ratio)
