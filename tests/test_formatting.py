"""Format specs: the Monkey C they compile to, and their widest rendering."""

import pytest

from wfb import formatting
from wfb.catalog import Type, get


@pytest.mark.parametrize("spec,value,code", [
    ("{:d}", "n", 'n.format("%d")'),
    ("{:02d}", "n", 'n.format("%02d")'),
    ("{:.1f}", "x", 'x.format("%.1f")'),
    ("{}", "n", "n.toString()"),
    ("{:d} steps", "n", 'n.format("%d") + " steps"'),
])
def test_numeric_emission(spec, value, code):
    assert formatting.emit(spec, value, Type.NUMBER) == code


def test_float_formatted_as_an_integer_is_converted():
    assert formatting.emit("{:d}", "x", Type.FLOAT) == 'x.toNumber().format("%d")'


def test_time_emission_uses_the_barrel_for_device_settings():
    """`%h` follows DeviceSettings.is24Hour -- the framework owns that, not the author."""
    code = formatting.emit("{:%h:%M}", "", Type.TIME)
    assert "WfbTime.displayHour(clock.hour, settings.is24Hour)" in code
    assert 'clock.min.format("%02d")' in code


def test_explicit_24_hour_does_not_consult_settings():
    code = formatting.emit("{:%H:%M}", "", Type.TIME)
    assert "is24Hour" not in code
    assert 'clock.hour.format("%02d")' in code


def test_meridiem_and_12_hour():
    code = formatting.emit("{:%I:%M %p}", "", Type.TIME)
    assert "WfbTime.hour12" in code and "WfbTime.meridiem" in code


def test_unknown_time_code_is_rejected_and_lists_the_valid_ones():
    with pytest.raises(formatting.FormatError) as excinfo:
        formatting.emit("{:%Q}", "", Type.TIME)
    assert "%H" in str(excinfo.value)


def test_a_format_without_a_field_is_rejected():
    with pytest.raises(formatting.FormatError):
        formatting.parse("no field here")


@pytest.mark.parametrize("spec,expected", [
    ("{:%H:%M}", "23:59"),
    ("{:%h:%M %p}", "23:59 AM"),
])
def test_widest_time_rendering(spec, expected):
    assert formatting.widest(spec, None, Type.TIME) == expected


def test_widest_uses_the_sources_real_range():
    """Steps reach five digits; heart rate reaches three.  The lint depends on this."""
    assert formatting.widest("{:d}", get("activity.steps"), Type.NUMBER) == "88888"
    assert formatting.widest("{:d}", get("heart_rate.current"), Type.NUMBER) == "888"


def test_unknown_range_falls_back_and_says_so():
    assert formatting.digits_are_known(get("activity.steps")) is True
    assert formatting.digits_are_known(None) is False


def test_glyph_set_covers_digits_and_separators():
    glyphs = formatting.glyphs("{:%h:%M}", None, Type.TIME)
    assert set("0123456789:") <= glyphs
    assert "." in formatting.glyphs("{:.1f}", None, Type.FLOAT)
    assert "-" in formatting.glyphs("{:d}", get("activity.steps"), Type.NUMBER)
