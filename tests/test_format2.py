"""Format 2: its schema, `wfb/lower.py`, colour resolution, `text:`
templates, the reserved vocabulary, and diagnostics named in format 2's own
terms.
"""

from __future__ import annotations

import json
import re
import textwrap
from typing import Any

import pytest

from wfb import validate, yamlsrc
from wfb.build import load
from wfb.diagnostics import Bag

from helpers import ROOT

HEADER = """\
format: 2
face: {id: 7f3c1e92-4a5b-4d81-9e6f-2b0c8d4a1f57, name: Test}
build: {targets: [fenix8solar47mm]}
"""


def design(body: str) -> str:
    return HEADER + textwrap.dedent(body)


def errors(text: str, write_design) -> list:
    bag = Bag()
    assert load(write_design(text), bag) is None, bag.render()
    return bag.errors


def accepted(text: str, write_design):
    bag = Bag()
    face = load(write_design(text), bag)
    assert face is not None, bag.render()
    return face, bag


# --------------------------------------------------------------------------
# the schema


def test_the_v2_schema_is_a_valid_draft_2020_12_schema():
    from jsonschema import Draft202012Validator

    Draft202012Validator.check_schema(validate.load_schema(validate.SCHEMA_PATH))


def test_every_v2_def_is_referenced():
    text = validate.SCHEMA_PATH.read_text(encoding="utf-8")
    schema = json.loads(text)
    unreferenced = [name for name in schema["$defs"] if f'#/$defs/{name}"' not in text]
    assert unreferenced == []


def test_v2_element_types():
    assert validate.ELEMENT_TYPES == (
        "group", "rectangle", "circle", "line", "arc", "ellipse", "polygon", "text",
        "gauge", "icon", "graph", "data", "hands", "pattern")


def test_the_v2_schema_describes_nothing_in_format_1_terms():
    removed = re.compile(
        r"when_absent|vertical_align|if_unavailable|icon_size|icon_position|icon_gap|"
        r"icon_color|icon_for|low_power|complication_slot|color_scheme|rounded_rectangle|"
        r"palette\.|config\.colors|config\.accent_color|config\.data_color|config\.data\b|"
        r"'shape: |static: true")

    def walk(node: Any, path: str) -> list[str]:
        found: list[str] = []
        if isinstance(node, dict):
            for key, value in node.items():
                if key == "description" and isinstance(value, str) and removed.search(value):
                    found.append(f"{path}: {removed.search(value).group(0)}")
                else:
                    found += walk(value, f"{path}/{key}")
        elif isinstance(node, list):
            for index, value in enumerate(node):
                found += walk(value, f"{path}/{index}")
        return found

    assert walk(validate.load_schema(validate.SCHEMA_PATH), "") == []


# --------------------------------------------------------------------------
# lowering


def test_a_bare_compass_alias_loads_as_a_string(write_design):
    """`N` is `false` to a YAML 1.1 reader; wfb's loader is YAML 1.2."""
    bag = Bag()
    doc = yamlsrc.load(write_design("align: N\nanchor: SW\n"), bag)
    assert doc is not None
    assert doc.data == {"align": "N", "anchor": "SW"}


@pytest.mark.parametrize("align, h, v", [
    ("N", None, "top"), ("NE", "right", "top"), ("E", "right", None),
    ("SE", "right", "bottom"), ("S", None, "bottom"), ("SW", "left", "bottom"),
    ("W", "left", None), ("NW", "left", "top"), ("top_left", "left", "top"),
    ("center", "center", None), ("bottom", None, "bottom"),
])
def test_align_and_its_compass_aliases(align, h, v, write_design):
    face, _ = accepted(design(f"""\
        elements:
          dot: {{type: circle, radius: 3, at: {{anchor: {align}}}, align: {align}}}
        """), write_design)
    (dot,) = face.elements
    assert (dot.align, dot.vertical_align) == (h or "center", v or "center")


def test_color_resolution(write_design):
    face, _ = accepted(design("""\
        resources: {palette: {red: "#FF0000", white: "#FFFFFF"}}
        theme:
          schemes: {dark: {colors: {fg: color.white}}}
        config:
          style: {default: d, choices: {d: {scheme: dark}}}
          accent_color: {default: color.red, choices: [color.red]}
          data_color: {default: "#00AAFF", choices: any, role: highlight}
        elements:
          a: {type: circle, radius: 3, color: color.fg}
          b: {type: circle, radius: 3, color: color.accent}
          c: {type: circle, radius: 3, color: color.highlight}
          d: {type: circle, radius: 3, color: color.red}
        """), write_design)
    texts = [e.color.text for e in face.elements]
    assert texts == ["config.colors.fg", "config.accent_color", "config.data_color",
                     "palette.red"]


def test_an_unknown_colour_suggests_a_near_one(write_design):
    found = errors(design("""\
        resources: {palette: {white: "#FFFFFF"}}
        elements:
          a: {type: circle, radius: 3, color: color.whit}
        """), write_design)
    assert [d.message for d in found] == ["unknown colour 'color.whit'"]
    assert "color.white" in found[0].notes[0]


def test_a_role_where_a_build_time_colour_is_needed(write_design):
    found = errors(design("""\
        resources: {palette: {white: "#FFFFFF"}}
        theme:
          schemes: {dark: {colors: {fg: color.white}}}
        config:
          style: {default: d, choices: {d: {scheme: dark}}}
          accent_color: {default: color.fg, choices: any}
        elements:
          a: {type: circle, radius: 3, color: color.accent}
        """), write_design)
    assert len(found) == 1
    assert "'color.fg' is a colour role" in found[0].message


def test_a_name_that_is_both_a_swatch_and_a_role_is_an_error_at_both(write_design):
    found = errors(design("""\
        resources: {palette: {fg: "#FFFFFF"}}
        theme:
          schemes: {dark: {colors: {fg: "#FFFFFF"}}}
        config:
          style: {default: d, choices: {d: {scheme: dark}}}
        elements:
          a: {type: circle, radius: 3, color: color.fg}
        """), write_design)
    assert [d.message for d in found] == ["'color.fg' is both a palette swatch and a colour role"] * 2
    assert {d.span.line for d in found} == {4, 6}


def test_a_scheme_role_named_like_an_axis_role(write_design):
    found = errors(design("""\
        theme:
          schemes: {dark: {colors: {accent: "#FFFFFF"}}}
        config:
          style: {default: d, choices: {d: {scheme: dark}}}
          accent_color: {default: "#FF0000", choices: any}
        elements:
          a: {type: circle, radius: 3, color: color.accent}
        """), write_design)
    assert len(found) == 1
    assert "both a 'theme:' scheme role and the role 'config: accent_color:' binds" \
        in found[0].message


@pytest.mark.parametrize("text, message", [
    ("{time.hour}{time.minute}", "several placeholders in one text are not implemented yet"),
    ("{time.hour", "a '{' with no closing '}'"),
    ("a } b", "a single '}' outside a placeholder"),
    ("{unit}", "'{unit}' needs a placeholder"),
    ("{}", "the placeholder has no expression"),
    ("{time.hour > 12 ? 1 : 2}", "a ternary inside a placeholder must be parenthesised"),
])
def test_template_errors(text, message, write_design):
    found = errors(design(f"""\
        elements:
          t: {{type: text, text: "{text}"}}
        """), write_design)
    assert len(found) == 1
    assert message in found[0].message
    assert found[0].message.startswith("text: ")


def test_a_literal_template_is_the_text_with_its_braces_undoubled(write_design):
    face, _ = accepted(design("""\
        elements:
          t: {type: text, text: "{{a}} b"}
        """), write_design)
    assert face.elements[0].literal == "{a} b"


def test_an_expression_error_points_into_the_template(write_design):
    text = design("""\
        elements:
          t: {type: text, text: "Steps {activity.stepz:d}"}
        """)
    found = errors(text, write_design)
    assert len(found) == 1
    assert found[0].message.startswith("text: unknown data source 'activity.stepz'")
    line = text.splitlines()[found[0].span.line - 1]
    assert line[found[0].span.col - 1:].startswith("activity.stepz")


def test_an_aod_template_must_read_the_elements_own_expression(write_design):
    found = errors(design("""\
        defaults: {aod: show}
        elements:
          t: {type: text, text: "{time.hour:02d}", aod: {text: "{time.minute:02d}"}}
        """), write_design)
    assert len(found) == 1
    assert "aod.text: the placeholder must read the element's own expression" in found[0].message


def test_an_aod_template_may_leave_the_placeholder_empty(write_design):
    face, _ = accepted(design("""\
        defaults: {aod: show}
        elements:
          t: {type: text, text: "{time.hour:02d}", aod: {text: "{:d}h"}}
        """), write_design)
    assert face.elements[0].aod.format == "{:d}h"


# --------------------------------------------------------------------------
# reserved vocabulary: friendly errors, never "unknown key"


@pytest.mark.parametrize("snippet, message", [
    ("elements:\n  a: {type: circle, radius: 3, effects: {shadow: {color: '#000000'}}}\n",
     "'effects:' (a drop shadow and the like) is reserved"),
    ("elements:\n  a: {use: card, with: {width: 30%r}}\n", "components"),
    ("resources:\n  components: {card: {params: {}, body: {}}}\n"
     "elements:\n  a: {type: circle, radius: 3}\n", "components are reserved"),
    ("elements:\n  a: {type: circle, radius: 3, color: [{when: 'x', value: '#000000'}, "
     "{else: '#FFFFFF'}]}\n", "'when:' rule lists are reserved"),
    ("config: {slots: {s: {default: steps, choices: any}}}\n"
     "elements:\n  a: {type: data, slot: s, arrange: row}\n",
     "a data element's own parts"),
    ("resources:\n  hand_sets:\n    h: {hour: {parts: [{type: line, to: {dy: -40%r}, "
     "outline: '#000000'}]}}\nelements:\n  a: {type: hands, set: h}\n",
     "'outline:' on a hand, needle or pattern part other than text is reserved"),
])
def test_reserved_keys(snippet, message, write_design):
    found = errors(design(snippet), write_design)
    reserved = [d for d in found if d.code == "reserved"]
    assert reserved and message in reserved[0].message
    assert not [d for d in found if "unknown key" in d.message]


def test_several_placeholders_are_reserved(write_design):
    found = errors(design("elements:\n  t: {type: text, text: '{time.hour}:{time.minute}'}\n"),
                   write_design)
    assert [d.code for d in found] == ["reserved"]


def test_a_format_1_key_in_a_format_2_file_names_its_replacement(write_design):
    found = errors(design("""\
        elements:
          t: {type: text, text: "{time.hour}", when_absent: hide}
        """), write_design)
    assert len(found) == 1
    assert any("'when_absent:' is format 1; format 2 writes 'absent:'" in n
               for n in found[0].notes)


# --------------------------------------------------------------------------
# diagnostics name the key the author wrote

#: Format 1 key names, and format 1 references, a format 2 author never
#: wrote: none may appear in a diagnostic about a format 2 file.
V1_TERMS = re.compile(
    r"\b(when_absent|vertical_align|if_unavailable|icon_size|icon_position|icon_gap|"
    r"icon_color|icon_for|low_power|complication_slot|color_scheme|rounded_rectangle)\b"
    r"|\bmodes\b|palette\.\w|config\.colors|config\.data\b|"
    r"'placeholder'|placeholder:|'fallback'|fallback:|'glyph'|glyph:|"
    r"shape: |'shape'|type: shape|type: progress|'progress'|static: true|'hands'|hands:")

#: One erroneous format 2 design per moved or renamed key.
MESSAGE_CASES = {
    "absent-missing": "elements:\n  t: {type: text, text: '{heart_rate.current:d}'}\n",
    "absent-placeholder-on-gauge":
        "elements:\n  g: {type: gauge, style: bar, size: {width: 10, height: 2}, "
        "value: battery.level, max: heart_rate.current}\n",
    "absent-unreachable":
        "elements:\n  t: {type: text, text: '{time.hour:d}', absent: '--'}\n",
    "absent-pattern":
        "elements:\n  p: {type: pattern, pattern: radial, count: 4, "
        "color: \"heart_rate.current > 100 ? '#FF0000' : '#FFFFFF'\", "
        "parts: [{type: circle, radius: 2}]}\n",
    "data-icon-gap":
        "config: {slots: {s: {default: steps, choices: any}}}\n"
        "elements:\n  d: {type: data, slot: s, icon: {size: 9%r, gap: -2px}}\n",
    "data-icon-color-nullable":
        "config: {slots: {s: {default: steps, choices: any}}}\n"
        "elements:\n  d: {type: data, slot: s, icon: {size: 9%r, color: "
        "\"heart_rate.current > 1 ? '#FF0000' : '#FFFFFF'\"}}\n",
    "data-unknown-slot":
        "config: {slots: {s: {default: steps, choices: any}}}\n"
        "elements:\n  d: {type: data, slot: t}\n",
    "data-format": "config: {slots: {s: {default: steps, choices: any}}}\n"
                   "elements:\n  d: {type: data, slot: s, format: '{:d}'}\n",
    "data-in-layout":
        "config:\n  slots: {s: {default: steps, choices: any}}\n"
        "  style: {default: a, choices: {a: {layout: l}}}\n"
        "layouts:\n  l:\n    elements:\n      d: {type: data, slot: s}\n",
    "data-default-not-in-choices":
        "config: {slots: {s: {default: steps, choices: [calories]}}}\n"
        "elements:\n  d: {type: data, slot: s}\n",
    "icon-for": "elements:\n  i: {type: icon, icon: {for: activity.steps}}\n",
    "icon-bad-glyph": "elements:\n  i: {type: icon, icon: 'U+10FFFF'}\n",
    "align-on-polygon":
        "elements:\n  p: {type: polygon, points: [{dx: 0}, {dx: 1}, {dy: 1}], align: top}\n",
    "align-on-line": "elements:\n  l: {type: line, to: {dx: 5}, align: left}\n",
    "radius-on-rectangle":
        "elements:\n  r: {type: rectangle, size: {width: 5, height: 5}, radius: 3}\n",
    "rectangle-no-size": "elements:\n  r: {type: rectangle}\n",
    "circle-no-radius": "elements:\n  c: {type: circle}\n",
    "filled-arc": "elements:\n  a: {type: arc, radius: 5, filled: true}\n",
    "unsupported-not-applicable": "elements:\n  c: {type: circle, radius: 3, unsupported: hide}\n",
    "unsupported-baked-font":
        f"resources: {{fonts: {{f: {{source: {ROOT}/tests/fixtures/slice/assets/"
        "OpenSans-Regular.ttf, size: 10px, unsupported: hide}}}\n"
        "elements:\n  t: {type: text, text: hi, font: font.f}\n",
    "sleep-update-amoled":
        "elements:\n  t: {type: text, text: '{time.second}', sleep_update: true}\n",
    "hands-unknown-set": "elements:\n  h: {type: hands, set: nope}\n",
    "hand-part-ellipse":
        "resources:\n  hand_sets:\n    h: {hour: {parts: [{type: ellipse, size: {width: 2, height: 4}}]}}\n"
        "elements:\n  a: {type: hands, set: h}\n",
    "hand-part-rectangle-radius":
        "resources:\n  hand_sets:\n    h: {hour: {parts: [{type: rectangle, size: {width: 2, height: 4}, radius: 1}]}}\n"
        "elements:\n  a: {type: hands, set: h}\n",
    "pattern-part-rectangle-align-on-line":
        "elements:\n  p: {type: pattern, pattern: radial, count: 4, "
        "parts: [{type: line, to: {dy: -5}, align: top}]}\n",
    "pattern-text-part-reads-data":
        "elements:\n  p: {type: pattern, pattern: radial, count: 4, "
        "parts: [{type: text, text: '{time.hour}'}]}\n",
    "scheme-roles-differ":
        "theme:\n  schemes:\n    a: {colors: {fg: '#FFFFFF'}}\n    b: {colors: {bg: '#000000'}}\n"
        "config: {style: {default: x, choices: {x: {scheme: a}, y: {scheme: b}}}}\n"
        "elements:\n  c: {type: circle, radius: 3}\n",
    "style-unknown-scheme":
        "theme:\n  schemes:\n    a: {colors: {fg: '#FFFFFF'}}\n"
        "config: {style: {default: x, choices: {x: {scheme: nope}}}}\n"
        "elements:\n  c: {type: circle, radius: 3}\n",
    "style-some-without-scheme":
        "theme:\n  schemes:\n    a: {colors: {fg: '#FFFFFF'}}\n"
        "config: {style: {default: x, choices: {x: {scheme: a}, y: {label: Y}}}}\n"
        "elements:\n  c: {type: circle, radius: 3}\n",
    "static-reads-data":
        "static:\n  t: {type: text, text: '{time.hour}'}\n"
        "elements:\n  c: {type: circle, radius: 3}\n",
    "static-hands":
        "resources:\n  hand_sets:\n    h: {hour: {parts: [{type: line, to: {dy: -40%r}}]}}\n"
        "static:\n  a: {type: hands, set: h}\n",
    "static-sleep-update":
        "static:\n  c: {type: circle, radius: 3, sleep_update: true}\n",
    "static-id-collision":
        "static:\n  c: {type: circle, radius: 3}\n"
        "elements:\n  static: {type: circle, radius: 3}\n",
    "gauge-style-keys":
        "elements:\n  g: {type: gauge, style: arc, size: {width: 5, height: 5}, "
        "value: battery.level, max: 100}\n",
    "gauge-segments-needs-count":
        "elements:\n  g: {type: gauge, style: segments, radius: 40, thickness: 3, "
        "start_angle: 0, sweep: 90, value: battery.level, max: 100}\n",
    "text-units-not-a-quantity":
        "elements:\n  t: {type: text, text: '{time.hour} {unit}', units: auto}\n",
    "text-antialias": "elements:\n  t: {type: text, text: hi, antialias: true}\n",
    "on-hold-auto-literal": "elements:\n  t: {type: text, text: hi, on_hold: auto}\n",
    "graph-min-max":
        "elements:\n  g: {type: graph, series: heart_rate, range: 4h, "
        "size: {width: 10, height: 5}, min: 10, max: 5}\n",
    "curve-on-baked": "elements:\n  t: {type: text, text: hi, curve: {style: angled, angle: 10}}\n",
    "overrides": "elements:\n  c: {type: circle, radius: 3, overrides: {fr955: {radius: 4}}}\n",
    "aod-font-on-pattern":
        "defaults: {aod: show}\n"
        "elements:\n  p: {type: pattern, pattern: radial, count: 4, "
        "parts: [{type: circle, radius: 2}], aod: {font: FONT_TINY}}\n",
    "visible-not-boolean": "elements:\n  c: {type: circle, radius: 3, visible: activity.steps}\n",
    "color-nullable-text":
        "elements:\n  t: {type: text, text: hi, color: \"heart_rate.current > 1 ? '#FF0000' : '#FFFFFF'\"}\n",
    "palette-dither":
        "resources: {palette: {odd: '#123456'}}\n"
        "elements:\n  c: {type: circle, radius: 3, color: color.odd}\n",
    "scheme-role-dither":
        "theme:\n  schemes:\n    a: {colors: {ink: '#123456'}}\n"
        "config: {style: {default: x, choices: {x: {scheme: a}}}}\n"
        "elements:\n  c: {type: circle, radius: 3, color: color.ink}\n",
    "config-unsupported":
        "resources: {palette: {red: '#FF0000'}}\n"
        "config:\n  accent_color: {default: color.red, choices: any}\n"
        "  slots: {s: {default: steps, choices: any}}\n"
        "elements:\n  c: {type: circle, radius: 3, color: color.accent}\n"
        "  d: {type: data, slot: s, color: color.red}\n",
}


def _messages(text: str, write_design, db) -> list:
    from wfb.build import resolve_all, select_devices

    bag = Bag()
    face = load(write_design(text), bag)
    if face is not None:
        # fenix5 has neither the native config editor nor the settings menu.
        wanted = [d for d in ("fenix8solar47mm", "fenix847mm", "fenix5") if d in db.ids()]
        devices = select_devices(face, db, bag, wanted)
        resolve_all(face, devices, bag)
    return bag.items


@pytest.mark.parametrize("name", sorted(MESSAGE_CASES))
def test_diagnostics_name_format_2_keys(name, write_design, db):
    items = _messages(design(MESSAGE_CASES[name]), write_design, db)
    assert [d for d in items if d.severity.value in ("error", "warning")], \
        "the case must produce a diagnostic to be worth checking"
    leaks = []
    for d in items:
        for text in [d.message, *d.notes]:
            match = V1_TERMS.search(text)
            if match:
                leaks.append(f"[{d.code}] {match.group(0)!r} in: {text}")
    assert leaks == []
