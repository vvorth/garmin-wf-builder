"""Length, angle and box arithmetic -- the core of the coordinate model."""

import math

import pytest

from wfb.units import ANCHORS, Angle, Axis, Box, IntBox, Length, UnitError


@pytest.mark.parametrize(
    "raw,value,unit",
    [
        ("12px", 12.0, "px"), (12, 12.0, "px"), (-4.5, -4.5, "px"),
        ("30%", 30.0, "%"), ("38%r", 38.0, "%r"), ("1.5pt", 1.5, "pt"),
        ("  -4 % ", -4.0, "%"),
    ],
)
def test_length_parsing(raw, value, unit):
    length = Length.parse(raw)
    assert (length.value, length.unit) == (value, unit)


@pytest.mark.parametrize("raw", ["banana", "12em", True, None, "%"])
def test_length_rejects_nonsense(raw):
    with pytest.raises(UnitError):
        Length.parse(raw)


def test_percent_resolves_per_axis():
    box = Box(0, 0, 200, 100)
    assert Length.parse("50%").resolve(box=box, axis=Axis.X, minor_radius=50) == 100
    assert Length.parse("50%").resolve(box=box, axis=Axis.Y, minor_radius=50) == 50
    # MINOR takes the smaller dimension, so a radius stays circular.
    assert Length.parse("50%").resolve(box=box, axis=Axis.MINOR, minor_radius=50) == 50


def test_percent_r_resolves_against_the_minor_radius_not_the_box():
    """This is what keeps a round design circular on a non-square screen."""
    square = Box(0, 0, 260, 260)
    wide = Box(0, 0, 400, 260)
    length = Length.parse("50%r")
    assert length.resolve(box=square, axis=Axis.X, minor_radius=130) == 65
    assert length.resolve(box=wide, axis=Axis.X, minor_radius=130) == 65


def test_pt_needs_a_font_in_scope():
    with pytest.raises(UnitError):
        Length.parse("2pt").resolve(box=Box(0, 0, 10, 10), axis=Axis.X, minor_radius=5)
    assert Length.parse("2pt").resolve(
        box=Box(0, 0, 10, 10), axis=Axis.X, minor_radius=5, font_px=30
    ) == 60


@pytest.mark.parametrize(
    "author,garmin",
    [(0, 90), (90, 0), (180, 270), (270, 180), (45, 45), (360, 90)],
)
def test_author_angles_convert_to_garmin(author, garmin):
    """Author: 12 o'clock = 0, clockwise.  Garmin: 3 o'clock = 0, counter-clockwise."""
    assert Angle.parse(f"{author}deg").to_garmin() == pytest.approx(garmin)


def test_angle_units():
    assert Angle.parse("0.25turn").degrees == 90
    assert Angle.parse(f"{math.pi}rad").degrees == pytest.approx(180)


def test_every_anchor_lands_inside_its_box():
    box = Box(10, 20, 100, 50)
    for name in ANCHORS:
        x, y = box.anchor_point(name)
        assert box.left <= x <= box.right
        assert box.top <= y <= box.bottom
    assert box.anchor_point("center") == (60, 45)
    assert box.anchor_point("bottom_right") == (110, 70)


def test_unknown_anchor_names_the_valid_ones():
    with pytest.raises(UnitError) as excinfo:
        Box(0, 0, 1, 1).anchor_point("middle")
    assert "center" in str(excinfo.value)


def test_intbox_union_and_clamp():
    a, b = IntBox(0, 0, 10, 10), IntBox(20, 5, 10, 10)
    assert a.union(b) == IntBox(0, 0, 30, 15)
    assert IntBox(-5, -5, 20, 20).clamp_to(10, 10) == IntBox(0, 0, 10, 10)
    assert a.area == 100
