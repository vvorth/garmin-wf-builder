"""Several placeholders in one `text:` template: one reading per
placeholder, drawn concatenated, and the element absent when any reading
is (`wfb.template.segments`, `Text.more`)."""

from __future__ import annotations

import re
import textwrap

import pytest

from wfb.build import build as real_build, load
from wfb.diagnostics import Bag
from wfb.emit.resources import bake_fonts
from wfb.layout import resolve
from wfb.preview import PreviewOptions, render

from tests.helpers import generate_for_targets

HEADER = """\
format: 2
face: {id: 7f3c1e92-4a5b-4d81-9e6f-2b0c8d4a1f57, name: Test}
build: {targets: [fenix8solar47mm, fr955]}
resources:
  palette: {bg: "#000000", fg: "#FFFFFF"}
"""

TWO = """\
elements:
  t:
    type: text
    text: "HR {heart_rate.current:d} / {activity.steps:d} st"
    font: FONT_SMALL
    at: {anchor: center}
    color: color.fg
    absent: "--"
"""


def design(body: str) -> str:
    return HEADER + textwrap.dedent(body)


def _errors(text: str, write_design) -> list:
    bag = Bag()
    assert load(write_design(text), bag) is None, bag.render()
    return bag.errors


def _face(text: str, write_design):
    bag = Bag()
    face = load(write_design(text), bag)
    assert face is not None, bag.render()
    return face


def _view(text: str, write_design, tmp_path) -> str:
    project = generate_for_targets(write_design(text), tmp_path / "out")
    return next(body for name, body in project.files().items() if name.endswith("View.mc"))


def test_each_placeholder_is_a_reading_with_the_text_after_it(write_design):
    face = _face(design("""\
        elements:
          t: {type: text, text: "<{time.clock:%H}h{activity.steps:05d}!>", at: {anchor: center},
              absent: hide}
        """), write_design)
    (element,) = face.elements
    assert element.format == "<{:%H}h"
    assert [(v.shown, spec) for v, spec in element.segments()] == [
        ("time.clock", "<{:%H}h"), ("activity.steps", "{:05d}!>")]


def test_the_device_draws_the_readings_concatenated_under_one_guard(write_design, tmp_path):
    view = _view(design(TWO), write_design, tmp_path)
    method = re.search(r"private function drawT\(.*?\n    }\n", view, re.S)
    assert method is not None
    body = method.group(0)
    assert 'var text = "--";' in body
    assert "if (heartRateCurrent != null && activitySteps != null) {" in body
    assert ('text = "HR " + heartRateCurrent.format("%d") + " / " '
            '+ activitySteps.format("%d") + " st";') in body


def _render(write_design, db, sample):
    bag = Bag()
    face = load(write_design(design(TWO)), bag)
    assert face is not None, bag.render()
    device = db.get("fenix8solar47mm")
    resolved = resolve(face, device, bake_fonts(face, device))
    image = render(resolved, PreviewOptions(scale=1, mask_shape=False, sample=sample))
    return list(image.get_flattened_data())


def test_the_preview_draws_the_later_reading_and_is_absent_when_any_reading_is(
        write_design, db):
    present = _render(write_design, db, {"heart_rate.current": 72, "activity.steps": 100})
    more_steps = _render(write_design, db, {"heart_rate.current": 72, "activity.steps": 9900})
    no_heart = _render(write_design, db, {"heart_rate.current": None, "activity.steps": 100})
    no_steps = _render(write_design, db, {"heart_rate.current": 72, "activity.steps": None})
    assert present != more_steps  # the second reading is bound
    assert no_steps == no_heart != present  # either absence draws the '--'


def test_a_later_nullable_reading_needs_absent(write_design):
    found = _errors(design("""\
        elements:
          t: {type: text, text: "{time.clock:%H} {heart_rate.current:d}", at: {anchor: center}}
        """), write_design)
    assert len(found) == 1
    assert "'heart_rate.current' can be absent, so 'absent:' is required" in found[0].message


def test_a_later_reading_s_format_is_checked(write_design):
    found = _errors(design("""\
        elements:
          t: {type: text, text: "{activity.steps:d} {time.clock}", at: {anchor: center},
              absent: hide}
        """), write_design)
    assert len(found) == 1
    assert "needs a strftime-style format" in found[0].message


@pytest.mark.parametrize("extra, message", [
    ("absent: {value: 0}", "'absent: {value:}' substitutes the reading of a text with one "
                           "placeholder, and this text has 2"),
    ("absent: hide\n    units: auto", "'units:' converts the reading of a text with one "
                                      "placeholder, and this text has 2"),
    ("absent: hide\n    aod: {text: \"{activity.steps:d}\"}",
     "aod.text: restyling a text with several placeholders is not implemented yet"),
])
def test_what_speaks_of_one_reading_is_refused_beside_several(extra, message, write_design):
    body = ("elements:\n  t:\n    type: text\n"
            "    text: \"{activity.steps:d}/{activity.distance:d}\"\n"
            "    at: {anchor: center}\n    " + extra + "\n")
    found = _errors(HEADER + body, write_design)
    assert [d.message for d in found if message in d.message], [d.message for d in found]


@pytest.mark.parametrize("text, message", [
    ("{activity.steps:d} {} x", "the placeholder has no expression"),
    ("{activity.steps:d} {unit}{activity.distance:d}", "'{unit}' labels the reading"),
])
def test_template_errors_cover_every_placeholder(text, message, write_design):
    found = _errors(design(f"""\
        elements:
          t: {{type: text, text: "{text}", at: {{anchor: center}}, absent: hide}}
        """), write_design)
    assert len(found) == 1
    assert message in found[0].message


def test_a_pattern_text_part_still_reads_one_placeholder(write_design):
    found = _errors(design("""\
        elements:
          p:
            type: pattern
            pattern: radial
            at: {anchor: center}
            count: 12
            color: color.fg
            parts:
              - {type: text, text: "{copy}{copy}", at: {dy: -40%r}}
        """), write_design)
    assert any("only a 'text' element's own 'text:' takes several placeholders"
               in d.message for d in found), [d.message for d in found]


@pytest.mark.slow
def test_several_readings_compile_warning_free(write_design, db, tmp_path, toolchain):
    text = design("""\
        elements:
          clock:
            type: text
            text: "{time.clock:%H}h{time.clock:%M}"
            at: {anchor: center, dy: -20%r}
            color: color.fg
          hr:
            type: text
            text: "HR {heart_rate.current:d} / {activity.steps:d} st"
            at: {anchor: center}
            color: color.fg
            absent: "--"
          date:
            type: text
            text: "{date.today:%a} {date.today:%m}"
            at: {anchor: center, dy: 20%r}
            color: color.fg
            absent: hide
        """)
    bag = Bag()
    result = real_build(write_design(text), output=tmp_path, bag=bag, db=db,
                        toolchain=toolchain)
    assert result is not None, bag.render()
    assert not [d for d in bag.items if d.severity.value in ("warning", "error")], bag.render()
