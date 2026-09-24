"""Format specs: the Monkey C they compile to, and their widest rendering."""

import pytest

from wfb import formatting
from wfb.catalog import Type, get
from wfb.emit import usage


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


# -- dates ------------------------------------------------------------------


def test_date_emission_reads_the_gregorian_fields():
    """Under FORMAT_MEDIUM the weekday and month are already localised strings."""
    code = formatting.emit("{:%a %e %b}", "", Type.DATE)
    assert code == 'date.day_of_week + " " + date.day.format("%d") + " " + date.month'


def test_date_and_time_codes_do_not_overlap():
    """`%M` is minute and `%m` is month: using one where the other belongs
    renders nonsense rather than failing, so the two tables stay separate."""
    with pytest.raises(formatting.FormatError):
        formatting.parse_time("%M", formatting.DATE_CODES)
    with pytest.raises(formatting.FormatError):
        formatting.parse_time("%b", formatting.TIME_CODES)


def test_a_percent_in_the_literal_text_is_not_a_time_code():
    """`{:.0f}%` renders a battery percentage and has nothing to do with strftime."""
    assert formatting.is_time_spec("{:.0f}%") is False
    assert formatting.is_time_spec("{:%H:%M}") is True
    assert formatting.emit("{:.0f}%", "battery", Type.FLOAT) == 'battery.format("%.0f") + "%"'


def test_a_date_needs_the_whole_alphabet_in_a_subsetted_font():
    """The weekday and month are chosen by the firmware, so a subset built from
    one day's rendering would drop glyphs on most other days."""
    glyphs = formatting.glyphs("{:%a %e %b}", None, Type.DATE)
    assert set("JanFebMarAprMayJunJulAugSepOctNovDec") <= glyphs
    assert set("MonTueWedThuFriSatSun") <= glyphs


def test_numeric_month_reads_the_short_reader_not_the_medium_one():
    """`%m` cannot read ``date.month`` at all -- under FORMAT_MEDIUM (the
    `date` reader) it is a localised String ("Sep"), with no numeric form.
    The zero-padded Number has to come from `date_short` (FORMAT_SHORT),
    cast `as Number` the same way `date.weekday` already is. This is the
    bug: the broken implementation emitted `date.month.format("%02d")`,
    which fails `monkeyc` outright (`Cannot find symbol ':format' on type
    '$.Toybox.Lang.String'`)."""
    code = formatting.emit("{:%m}", "", Type.DATE)
    assert code == '(dateShort.month as Number).format("%02d")'
    assert "date.month.format" not in code


def test_numeric_month_honours_the_date_short_kwarg():
    code = formatting.emit("{:%m}", "", Type.DATE, date="d", date_short="ds")
    assert code == '(ds.month as Number).format("%02d")'


def test_other_date_codes_are_unaffected_by_the_month_fix():
    """Every other DATE_CODES entry still reads off `date` alone -- `%m` is
    the only one needing a second reader."""
    code = formatting.emit("{:%a %d %e %b %Y %y %%}", "", Type.DATE)
    assert "dateShort" not in code
    assert code == (
        'date.day_of_week + " " + date.day.format("%02d") + " " '
        '+ date.day.format("%d") + " " + date.month + " " '
        '+ date.year.format("%04d") + " " + (date.year % 100).format("%02d") '
        '+ " " + "%"'
    )


@pytest.mark.parametrize("spec,extra", [
    ("{:%m}", ("date.weekday",)),
    ("{:%Y-%m-%d}", ("date.weekday",)),
    ("{:%a %e %b}", ()),
    ("{:%Y}", ()),
])
def test_extra_paths_flags_only_date_specs_using_percent_m(spec, extra):
    """The single source of truth `wfb.emit.monkeyc.readplan.ReadPlan`
    consults to know a `%m` spec needs the `date_short` reader-local
    declared and passed as a parameter -- `emit` and this helper read
    the same `DATE_CODES` row, so the two cannot drift apart."""
    assert formatting.extra_paths(spec, Type.DATE) == extra


# -- width estimation -------------------------------------------------------


def test_zero_precision_prints_no_decimal_point():
    assert formatting.widest("{:.0f}%", get("system.battery"), Type.FLOAT) == "888%"


def test_scaling_a_source_shrinks_its_digit_count():
    """`activity.steps / 1000` cannot reach five digits, and pretending it can
    makes the overflow lint warn about text that will never be drawn."""
    unscaled = formatting.widest("{:.1f}k", get("activity.steps"), Type.NUMBER)
    scaled = formatting.widest("{:.1f}k", get("activity.steps"), Type.NUMBER, 0.001)
    assert unscaled == "88888.8k"
    assert scaled == "88.8k"


def test_every_time_or_date_code_is_correctly_barrel_scanned():
    """Plan 19 A3 superseded `Code.helper`/`formatting.helpers`, which this
    test used to check for internal consistency (plan 18 item 9), with
    `wfb.emit.usage.barrel_modules` scanning the actual generated text
    instead. The same protection, aimed at the new function: for every code
    with an `emit`, whether its own compiled Monkey C calls into `WfbTime`
    is exactly what the scanner finds when handed that text alone -- so a
    future code that starts (or stops) calling `WfbTime` cannot silently
    carry a dead barrel file or fail with `Undefined symbol` at build time
    without a codegen test noticing here first."""
    readers = formatting.Readers()
    for table in (formatting.TIME_CODES, formatting.DATE_CODES):
        for name, code in table.items():
            if code.emit is None:
                continue
            text = code.emit(readers)
            calls_wfbtime = "WfbTime." in text
            assert ("WfbTime.mc" in usage.barrel_modules([text])) is calls_wfbtime, name


def test_barrel_modules_reads_only_the_codes_a_spec_uses():
    assert usage.barrel_modules([formatting.emit("{:%H:%M}", "clock", Type.TIME)]) == set()
    assert (usage.barrel_modules([formatting.emit("{:%I:%M %p}", "clock", Type.TIME)])
            == {"WfbTime.mc"})
