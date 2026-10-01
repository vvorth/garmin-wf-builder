"""A gauge's automatic scale per complication type: `wfb.complications.SCALE`,
its Python twin, the generated `SlotScale` module and `runtime-lib/WfbScale.mc`.

The figures are checked against the sources the table cites; the VO2 max
ends against the derived table recorded in research 24 §7.1, typed here
independently rather than recomputed by the code under test.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

from wfb import complications
from wfb.complications import (
    SCALE, heart_rate_scale, ranges_scale, scale_for, vo2max_ends, vo2max_scale,
)
from wfb.emit.monkeyc.slot_scale import slot_scale_text

ROOT = Path(__file__).parent.parent

#: research 24 §7.1's derived ends, (min, max) per age decade 20-29 .. 70-79.
DERIVED = {
    "male": [(37.1, 60.0), (36.0, 58.5), (33.8, 57.2), (31.2, 53.3), (27.8, 50.2), (25.2, 46.3)],
    "female": [(31.6, 54.1), (30.1, 51.7), (28.9, 49.4), (26.4, 44.8), (24.1, 41.2), (22.3, 40.3)],
}

GOALS = {"stepGoal": 8000, "floorsClimbedGoal": 10, "activeMinutesWeekGoal": 150, "pushGoal": 3000}
ZONES = (95, 114, 133, 152, 171, 190)


def _scale(name, **kw):
    args = {"goals": GOALS, "heart_rate_zones": ZONES, "sex": "male", "age": 35} | kw
    return scale_for(name, **args)


# --------------------------------------------------------------------------
# the table


def test_every_scaled_name_is_a_real_type():
    assert set(SCALE) <= set(complications.TYPES)


@pytest.mark.parametrize("name", ["battery", "pulse_ox", "solar_input", "sleep_score",
                                  "body_battery", "stress"])
def test_percent_types_run_0_to_100(name):
    assert _scale(name) == (0.0, 100.0)


@pytest.mark.parametrize("name, bands", [
    ("body_battery", (26.0, 51.0, 76.0)),  # 0-25 low ... 76-100 very high
    ("stress", (26.0, 51.0, 76.0)),        # 0-25 rest ... 76-100 high
    ("sleep_score", (60.0, 80.0, 90.0)),   # poor, fair from 60, good 80, excellent 90
])
def test_garmins_band_lower_bounds(name, bands):
    assert SCALE[name].bands == bands


@pytest.mark.parametrize("name, goal", [
    ("steps", 8000), ("floors_climbed", 10), ("intensity_minutes", 150), ("wheelchair_pushes", 3000),
])
def test_a_goal_type_runs_to_its_goal(name, goal):
    assert _scale(name) == (0.0, float(goal))


@pytest.mark.parametrize("goal", [None, 0])
def test_an_unset_goal_has_no_scale(goal):
    assert _scale("steps", goals={"stepGoal": goal}) is None
    assert _scale("steps", goals={}) is None


def test_sunrise_and_sunset_run_over_one_day():
    assert _scale("sunrise") == _scale("sunset") == (0.0, 86400.0)


@pytest.mark.parametrize("name", ["calories", "altitude", "notification_count", "recovery_time",
                                  "date", "current_weather", "training_status",
                                  "race_predictor_5k", "weekly_run_distance"])
def test_a_type_without_a_documented_limit_has_no_scale(name):
    assert _scale(name) is None


# --------------------------------------------------------------------------
# heart rate, VO2 max, an app's ranges


def test_heart_rate_runs_from_zone_1_minimum_to_zone_5_maximum():
    assert _scale("heart_rate") == (95.0, 190.0)


@pytest.mark.parametrize("zones", [None, (95, 114, 133, 152, 171), (190, 114, 133, 152, 171, 95)])
def test_unusable_zones_have_no_scale(zones):
    assert heart_rate_scale(zones) is None


@pytest.mark.parametrize("sex", ["male", "female"])
def test_vo2max_ends_match_the_derived_table(sex):
    for decade, expected in enumerate(DERIVED[sex]):
        assert vo2max_scale(sex, 20 + decade * 10) == expected
        assert vo2max_scale(sex, 29 + decade * 10) == expected


def test_vo2max_ends_extend_by_the_inner_bands_average_width():
    # male 20-29: Fair 41.7, Superior 55.4, width (55.4 - 41.7) / 3 = 4.5667
    assert vo2max_ends(41.7, 55.4) == (37.1, 60.0)


@pytest.mark.parametrize("sex, age", [
    (None, 35), ("unspecified", 35), ("male", None), ("male", 19), ("male", 80), ("female", 5),
])
def test_vo2max_hides_without_a_row(sex, age):
    assert vo2max_scale(sex, age) is None
    assert _scale("vo2max_run", sex=sex, age=age) is None


def test_cycling_vo2max_uses_the_same_table():
    assert _scale("vo2max_bike") == _scale("vo2max_run") == (36.0, 58.5)


@pytest.mark.parametrize("ranges, expected", [
    ((0, 24, 33, 41, 50, 53), (0.0, 53.0)),  # the SDK's own <range> example
    ((10, 20), (10.0, 20.0)),
    (None, None), ((5,), None), ((50, 10), None),
])
def test_an_app_complication_scales_by_its_own_ranges(ranges, expected):
    assert ranges_scale(ranges) == expected


# --------------------------------------------------------------------------
# the generated module


def test_only_scaled_names_get_a_case():
    text = slot_scale_text(["steps", "date", "current_weather"], False, "h")
    assert "COMPLICATION_TYPE_STEPS:" in text
    assert "COMPLICATION_TYPE_DATE" not in text
    assert "COMPLICATION_TYPE_INVALID" not in text
    assert "VO2MAX_ENDS" not in text and "WfbScale.heartRate" not in text


def test_a_module_without_goals_reads_no_activity_monitor():
    text = slot_scale_text(["battery"], False, "h")
    assert "ActivityMonitor" not in text


def test_a_goal_field_is_guarded():
    """`pushGoal` is missing on fenix8solar47mm and fr955 alike."""
    text = slot_scale_text(["wheelchair_pushes"], False, "h")
    assert "WfbScale.upTo((info has :pushGoal) ? info.pushGoal : null);" in text


def test_any_choice_scales_an_app_complication_by_its_ranges():
    text = slot_scale_text(["battery"], True, "h")
    assert "case Complications.COMPLICATION_TYPE_INVALID:\n" in text
    assert "return WfbScale.ranges(c);" in text


def _emitted_ends() -> list[float]:
    text = slot_scale_text(["vo2max_run"], False, "h")
    match = re.search(r"const VO2MAX_ENDS = \[([^\]]*)\]", text)
    assert match is not None
    return [float(x) for x in match.group(1).split(",")]


def test_the_watch_reads_the_same_vo2max_ends_as_the_twin():
    """`WfbScale.vo2max` indexes `(first + (age - 20) / 10) * 2`, with `first`
    0 for female rows and 6 for male; that index into the emitted array
    must land on the twin's ends for every age it accepts."""
    source = (ROOT / "runtime-lib" / "WfbScale.mc").read_text(encoding="utf-8")
    assert "var i = (first + (age - 20) / 10) * 2;" in source
    assert "first = 0;" in source and "first = 6;" in source
    ends = _emitted_ends()
    for sex, first in (("female", 0), ("male", 6)):
        for age in complications.VO2MAX_AGES:
            i = (first + (age - 20) // 10) * 2
            assert (ends[i], ends[i + 1]) == vo2max_scale(sex, age), (sex, age)


# --------------------------------------------------------------------------
# a real build


_MANIFEST = """<?xml version="1.0"?>
<iq:manifest version="3" xmlns:iq="http://www.garmin.com/xml/connectiq">
    <iq:application id="5c0a1e4f8b2d4e6f9a1b2c3d4e5f6a7b" type="watchface"
                    name="@Strings.AppName" entry="ScaleApp"
                    launcherIcon="@Drawables.LauncherIcon" minApiLevel="3.1.0">
        <iq:products>
            <iq:product id="fenix8solar47mm"/>
            <iq:product id="fenix8solar51mm"/>
            <iq:product id="fr955"/>
        </iq:products>
        <iq:permissions>
            <iq:uses-permission id="ComplicationSubscriber"/>
            <iq:uses-permission id="UserProfile"/>
        </iq:permissions>
        <iq:languages><iq:language>eng</iq:language></iq:languages>
        <iq:barrels/>
    </iq:application>
</iq:manifest>
"""

_APP = """import Toybox.Application;
import Toybox.Complications;
import Toybox.Graphics;
import Toybox.Lang;
import Toybox.WatchUi;

class ScaleApp extends Application.AppBase {
    function initialize() {
        AppBase.initialize();
    }

    function getInitialView() as [Views] or [Views, InputDelegates] {
        return [new ScaleView()];
    }
}

class ScaleView extends WatchUi.WatchFace {
    function initialize() {
        WatchFace.initialize();
    }

    function onUpdate(dc as Dc) as Void {
        var id = new Complications.Id(Complications.COMPLICATION_TYPE_STEPS);
        var c = Complications.getComplication(id);
        var t = id.getType();
        var scale = (t != null) ? SlotScale.scale(t, c) : null;
        dc.drawText(0, 0, Graphics.FONT_XTINY, (scale != null) ? scale[1].toString() : "-",
            Graphics.TEXT_JUSTIFY_LEFT);
    }
}
"""


@pytest.mark.slow
@pytest.mark.parametrize("device", ["fenix8solar47mm", "fenix8solar51mm", "fr955"])
def test_slot_scale_compiles_warning_free(tmp_path, toolchain, device):
    """Every case at once (every type, and an app's complication), with
    `WfbScale`, under `-l 3`: the goal guards, the zone read, the VO2 max
    table and `ranges` all typecheck."""
    (tmp_path / "source").mkdir()
    (tmp_path / "resources" / "strings").mkdir(parents=True)
    (tmp_path / "resources" / "drawables").mkdir(parents=True)
    (tmp_path / "manifest.xml").write_text(_MANIFEST, encoding="utf-8")
    (tmp_path / "monkey.jungle").write_text("project.manifest = manifest.xml\n", encoding="utf-8")
    (tmp_path / "resources" / "strings" / "strings.xml").write_text(
        '<strings><string id="AppName">Scale</string></strings>', encoding="utf-8")
    icon = ROOT / "docs" / "research" / "probes" / "complication-ranges" / "resources" / "drawables"
    for name in ("launcher_icon.png", "drawables.xml"):
        (tmp_path / "resources" / "drawables" / name).write_bytes((icon / name).read_bytes())
    (tmp_path / "source" / "ScaleApp.mc").write_text(_APP, encoding="utf-8")
    (tmp_path / "source" / "SlotScale.mc").write_text(
        slot_scale_text(complications.TYPES, True, "test"), encoding="utf-8")
    (tmp_path / "source" / "WfbScale.mc").write_bytes(
        (ROOT / "runtime-lib" / "WfbScale.mc").read_bytes())

    result = subprocess.run(
        [str(toolchain.monkeyc), "-f", str(tmp_path / "monkey.jungle"), "-d", device,
         "-o", str(tmp_path / "scale.prg"), "-y", str(toolchain.key), "-w", "-l", "3"],
        capture_output=True, text=True, timeout=600,
    )
    output = result.stdout + result.stderr
    assert result.returncode == 0, output
    assert "BUILD SUCCESSFUL" in output, output
    assert "WARNING" not in output and "ERROR" not in output, output
