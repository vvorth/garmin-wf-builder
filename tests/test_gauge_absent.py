"""`absent: hide` on a gauge keeps its value-independent drawing.

While the value (or max) is absent, an arc or bar gauge still draws its
track, a `segments` gauge every cell unlit, and a `scale` gauge its track
and bands; only what the value places -- the fill, the lit cells, the
pointer -- is left out. A needle has nothing that does not depend on the
value, so it hides whole, and a nullable colour still hides everything.
`wfb.kinds.progress.keeps_track` is the one definition both the generated
code and the preview read.
"""

from __future__ import annotations

import pytest

from tests.helpers import load_face as _face
from wfb.build import build as real_build
from wfb.diagnostics import Bag
from wfb.emit import generate
from wfb.emit.resources import bake_fonts
from wfb.kinds import progress
from wfb.layout import resolve
from wfb.preview import PreviewOptions, render

DEVICE = "fenix8solar47mm"
TRACK = (85, 85, 85)
FILL = (255, 170, 0)
BAND = (0, 170, 0)

HEAD = """format: 2
face:
  id: 7f3c1e92-4a5b-4d81-9e6f-2b0c8d4a1f57
  name: Test
build:
  targets: [fenix8solar47mm, fr955]
resources:
  palette:
    bg: "#000000"
    fill: "#FFAA00"
    track: "#555555"
    band: "#00AA00"
elements:
"""

ARC = """  gauge:
    type: gauge
    style: arc
    value: heart_rate.current
    max: 200
    at: {anchor: center}
    radius: 80%r
    thickness: 8%r
    start_angle: 0deg
    sweep: 360deg
    color: color.fill
    track_color: color.track
    absent: hide
"""

BAR = """  gauge:
    type: gauge
    style: bar
    value: heart_rate.current
    max: 200
    at: {anchor: center}
    size: {width: 60%, height: 10%}
    color: color.fill
    track_color: color.track
    absent: hide
"""

SEGMENTS = """  gauge:
    type: gauge
    style: segments
    value: heart_rate.current
    max: 200
    at: {anchor: center}
    size: {width: 60%, height: 10%}
    count: 5
    gap: 4px
    color: color.fill
    track_color: color.track
    absent: hide
"""

SCALE = """  gauge:
    type: gauge
    style: scale
    value: heart_rate.current
    max: 200
    at: {anchor: center}
    radius: 70%r
    thickness: 4%r
    start_angle: 240deg
    sweep: 240deg
    color: color.fill
    track_color: color.track
    bands: [{to: 0.5, color: color.band}]
    absent: hide
"""

NEEDLE = """  gauge:
    type: gauge
    style: needle
    value: heart_rate.current
    max: 200
    at: {anchor: center}
    start_angle: 240deg
    sweep: 240deg
    color: color.fill
    needle:
      - {type: line, at: {dy: 5%r}, to: {dy: -70%r}, thickness: 4px}
    absent: hide
"""

STYLES = {"arc": ARC, "bar": BAR, "segments": SEGMENTS, "scale": SCALE, "needle": NEEDLE}


def _colors(text, write_design, db, heart_rate):
    face = _face(HEAD + text, write_design, Bag())
    device = db.get(DEVICE)
    resolved = resolve(face, device, bake_fonts(face, device))
    image = render(resolved, PreviewOptions(scale=1, mask_shape=False, quantise=False,
                                            sample={"heart_rate.current": heart_rate}))
    return {color for _, color in image.convert("RGB").getcolors(1 << 20)}


def _method(text, write_design, db):
    face = _face(HEAD + text, write_design, Bag())
    devices = [db.get(DEVICE)]
    files = generate(face, devices, write_design(HEAD + text).parent / "out",
                     {d.id: bake_fonts(face, d) for d in devices}).files()
    view = next(body for name, body in files.items() if name.endswith("View.mc"))
    return view.split("private function drawGauge")[1].split("\n    }\n")[0]


# -- the preview ---------------------------------------------------------------


@pytest.mark.parametrize("style", ["arc", "bar", "segments", "scale"])
def test_an_absent_gauge_draws_its_track_and_nothing_the_value_places(
        style, write_design, db):
    present = _colors(STYLES[style], write_design, db, 100)
    absent = _colors(STYLES[style], write_design, db, None)
    assert FILL in present, "the premise: the fill (or pointer) draws while present"
    assert TRACK in absent
    assert FILL not in absent
    if style == "scale":
        assert BAND in absent


def test_an_absent_needle_draws_nothing(write_design, db):
    assert FILL in _colors(NEEDLE, write_design, db, 100)
    assert _colors(NEEDLE, write_design, db, None) <= {(0, 0, 0)}


def test_absent_segments_with_no_track_draw_nothing(write_design, db):
    text = SEGMENTS.replace("    track_color: color.track\n", "")
    assert _colors(text, write_design, db, None) <= {(0, 0, 0)}


def test_a_nullable_colour_still_hides_the_whole_gauge(write_design, db):
    """The track is value-independent, not colour-independent: a colour
    reading an absent source has nothing to draw with."""
    text = ARC.replace("    track_color: color.track\n",
                       "    track_color: \"heart_rate.current > 100 ? color.band : color.track\"\n")
    assert _colors(text, write_design, db, None) <= {(0, 0, 0)}


# -- the generated code ------------------------------------------------------------


@pytest.mark.parametrize("style", ["arc", "bar", "segments", "scale"])
def test_the_track_draws_before_the_value_guard_and_nothing_returns_early(
        style, write_design, db):
    """No early `return` for the value: a return inside the drawing would
    also skip an `antialias:` override's restore after it."""
    method = _method(STYLES[style], write_design, db)
    assert "return;" not in method
    guard = "if (heartRateCurrent != null)"
    assert guard in method
    track = method.index("Palette.TRACK")
    assert track < method.index(guard) or style == "segments"
    if style == "segments":
        assert "var lit = 0;" in method
    if style == "scale":
        assert method.index("Palette.BAND") < method.index(guard)


def test_an_absent_needle_still_returns_early(write_design, db):
    method = _method(NEEDLE, write_design, db)
    assert "if (heartRateCurrent == null)" in method and "return;" in method


def test_a_nullable_colour_still_guards_the_whole_method(write_design, db):
    text = ARC.replace("    track_color: color.track\n",
                       "    track_color: \"heart_rate.current > 100 ? color.band : color.track\"\n")
    method = _method(text, write_design, db)
    assert "if (heartRateCurrent == null)" in method and "return;" in method


def test_the_generated_doc_says_the_track_still_draws(write_design, db):
    face = _face(HEAD + ARC, write_design, Bag())
    devices = [db.get(DEVICE)]
    files = generate(face, devices, write_design(HEAD + ARC).parent / "out",
                     {d.id: bake_fonts(face, d) for d in devices}).files()
    view = next(body for name, body in files.items() if name.endswith("View.mc"))
    assert "When the value is absent: hide -- the track still draws." in view


def test_codegen_and_preview_read_one_definition(write_design, db):
    """The view's guard choice goes through the kind (`draws_while_absent`),
    the preview's through `keeps_track`: the two must agree for every style."""
    for style, text in STYLES.items():
        element = _face(HEAD + text, write_design, Bag()).elements[0]
        assert progress.KIND.draws_while_absent(element) == progress.keeps_track(element)
        assert progress.keeps_track(element) == (style != "needle"), style


# -- the real compiler -------------------------------------------------------------


@pytest.mark.slow
def test_every_style_compiles_warning_free_while_keeping_its_track(
        write_design, db, tmp_path, toolchain):
    """The value-dependent drawing reads the locals inside their own null
    check: `monkeyc` must narrow them there, under the strict typecheck."""
    text = HEAD
    for index, style in enumerate(("arc", "bar", "segments", "scale")):
        text += STYLES[style].replace("  gauge:\n", f"  gauge{index}:\n", 1) \
            + "    antialias: true\n" \
            + ("    lint: {allow: [antialias-dither, contrast, safe-area, off-screen, "
               "static-overlap], reason: \"a test design\"}\n")
    bag = Bag()
    result = real_build(write_design(text), output=tmp_path, bag=bag, db=db,
                        toolchain=toolchain)
    assert result is not None, bag.render()
    assert not [d for d in bag.items if d.severity.value in ("warning", "error")], bag.render()
