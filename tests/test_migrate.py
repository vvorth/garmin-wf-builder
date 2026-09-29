"""`wfb migrate`: format 1 -> format 2 (plan 22 §3.4, §4).

Each row of the migration table has a test comparing the migrated document's
*data* with the v2 spelling; comment, quoting and layout survival have their
own tests below, on the text.
"""

from __future__ import annotations

import io
import re
import textwrap
from pathlib import Path

import pytest
from ruamel.yaml import YAML

from wfb.diagnostics import Bag
from wfb.migrate import migrate_text

from helpers import ROOT, run_cli

HEADER = """\
format: 1
face: {id: 7f3c1e92-4a5b-4d81-9e6f-2b0c8d4a1f57, name: Test}
targets: [fenix8solar47mm]
"""


def _data(text: str):
    return YAML(typ="safe", pure=True).load(io.StringIO(text))


def migrate(text: str, *, fragment: str | None = None) -> str:
    bag = Bag()
    result = migrate_text(textwrap.dedent(text), Path("face.yaml"), bag, fragment=fragment)
    assert result is not None, bag.render()
    return result.text


def refusals(text: str, *, fragment: str | None = None) -> list[str]:
    bag = Bag()
    result = migrate_text(textwrap.dedent(text), Path("face.yaml"), bag, fragment=fragment)
    assert result is None
    return [d.message for d in bag.errors]


def element(v1_body: str) -> dict:
    """Migrate one element given as a list item under `elements:`, and
    return its v2 body."""
    text = HEADER + "elements:\n" + textwrap.indent(textwrap.dedent(v1_body), "  ")
    data = _data(migrate(text))
    (name, body), = data["elements"].items()
    return body


# --------------------------------------------------------------------------
# top level


def test_format_targets_and_resources_regroup():
    out = _data(migrate(HEADER + """\
fonts:
  big: {source: a.ttf, size: 10%r, if_unavailable: error}
palette:
  red: "#FF0000"
hands:
  h:
    hour: {color: palette.red, parts: [{shape: line, to: {dy: -40%r}}]}
elements:
  - {id: x, type: text, text: hi}
"""))
    assert out["format"] == 2
    assert out["build"] == {"targets": ["fenix8solar47mm"]}
    assert "targets" not in out and "fonts" not in out and "palette" not in out
    assert out["resources"]["fonts"] == {"big": {"source": "a.ttf", "size": "10%r",
                                                 "unsupported": "error"}}
    assert out["resources"]["palette"] == {"red": "#FF0000"}
    assert out["resources"]["hand_sets"]["h"]["hour"] == {
        "color": "color.red", "parts": [{"type": "line", "to": {"dy": "-40%r"}}]}


def test_color_scheme_becomes_theme_schemes():
    out = _data(migrate(HEADER + """\
palette: {black: "#000000", white: "#FFFFFF"}
color_scheme:
  dark: {label: Dark, colors: {bg: palette.black, fg: "#FFFFFF"}}
elements:
  - {id: x, type: text, text: hi, color: config.colors.fg}
"""))
    assert "color_scheme" not in out
    assert out["theme"] == {"schemes": {"dark": {"label": "Dark", "colors": {
        "bg": "color.black", "fg": "#FFFFFF"}}}}
    assert out["elements"]["x"]["color"] == "color.fg"


def test_face_wide_defaults():
    out = _data(migrate(HEADER + """\
antialias: true
min_1px: false
aod: {default: show, dim: 0.5, mask: false}
elements:
  - {id: x, type: text, text: hi}
"""))
    assert out["defaults"] == {"antialias": True, "min_1px": False, "aod": "show"}
    assert out["aod"] == {"dim": 0.5, "mask": False}
    assert "antialias" not in out


def test_an_aod_block_with_only_a_default_is_removed():
    out = _data(migrate(HEADER + "aod: {default: show}\nelements:\n"
                        "  - {id: x, type: text, text: hi}\n"))
    assert out["defaults"] == {"aod": "show"}
    assert "aod" not in out


def test_config_colour_axes_style_and_slots():
    out = _data(migrate(HEADER + """\
palette: {red: {value: "#FF0000", label: Red}, amber: "#FFAA00"}
color_scheme:
  dark: {colors: {bg: "#000000"}}
config:
  accent_color: {default: palette.red, choices: [palette.red, {color: "#00FF00", label: Green}]}
  data_color: {default: "#FFAA00", choices: any}
  style:
    default: d
    choices: {d: {label: D, colors: dark}}
  data:
    left:
      label: Left
      default: complication.steps
      choices:
        - complication.steps
        - {type: complication.calories, icon: none}
        - {type: complication.heart_rate, glyph: "U+F21E"}
elements:
  - id: x
    type: complication_slot
    slot: config.data.left
    color: config.accent_color
    icon_color: config.data_color
    icon_size: 9%r
"""))
    config = out["config"]
    assert config["accent_color"] == {"default": "color.red", "choices": [
        "color.red", {"color": "#00FF00", "label": "Green"}]}
    assert config["data_color"] == {"default": "#FFAA00", "choices": "any"}
    assert config["style"]["choices"]["d"] == {"label": "D", "scheme": "dark"}
    assert "data" not in config
    assert config["slots"]["left"] == {"label": "Left", "default": "steps", "choices": [
        "steps", {"type": "calories", "icon": "none"},
        {"type": "heart_rate", "icon": "U+F21E"}]}
    slot = out["elements"]["x"]
    assert slot["type"] == "data"
    assert slot["slot"] == "left"
    assert slot["color"] == "color.accent"
    assert slot["icon"] == {"size": "9%r", "color": "color.data"}


# --------------------------------------------------------------------------
# references inside expressions


@pytest.mark.parametrize("v1, v2", [
    ("palette.red", "color.red"),
    ("config.colors.fg", "color.fg"),
    ("config.accent_color", "color.accent"),
    ("config.data_color", "color.data"),
    ("activity.steps > 9000 ? config.accent_color : palette.dim",
     "activity.steps > 9000 ? color.accent : color.dim"),
    # a string literal and a longer name are never touched
    ("x == 'palette.red' ? palette.red : palette.red_dark",
     "x == 'palette.red' ? color.red : color.red_dark"),
    ("palette.red.x", "palette.red.x"),
])
def test_expression_references(v1, v2):
    body = element(f"- id: x\n  type: shape\n  shape: circle\n  radius: 1\n  color: \"{v1}\"\n")
    assert body["color"] == v2


def test_references_in_every_expression_key():
    body = element("""\
- id: x
  type: progress
  style: bar
  size: {width: 10, height: 2}
  value: "palette.a"
  max: "palette.b"
  color: palette.c
  track_color: config.colors.d
  visible: "palette.e == palette.f"
  bands: [{to: 0.5, color: palette.g}]
  when_absent: fallback
  fallback: palette.h
  aod: {color: palette.i, track_color: palette.j, visible: "palette.k != palette.l"}
""")
    assert body["value"] == "color.a"
    assert body["max"] == "color.b"
    assert body["color"] == "color.c"
    assert body["track_color"] == "color.d"
    assert body["visible"] == "color.e == color.f"
    assert body["bands"] == [{"to": 0.5, "color": "color.g"}]
    assert body["absent"] == {"value": "color.h"}
    assert body["aod"] == {"color": "color.i", "track_color": "color.j",
                           "visible": "color.k != color.l"}


def test_outline_references():
    body = element("""\
- id: x
  type: text
  text: hi
  outline: palette.a
  aod: {outline: {color: config.colors.b, width: 1}}
""")
    assert body["outline"] == "color.a"
    assert body["aod"]["outline"] == {"color": "color.b", "width": 1}


# --------------------------------------------------------------------------
# every element


def test_list_form_becomes_mapping_form_recursively():
    out = _data(migrate(HEADER + """\
elements:
  - id: g
    type: group
    children:
      - {id: a, type: text, text: hi}
      - id: b
        type: group
        children:
          - {id: c, type: text, text: yo}
"""))
    g = out["elements"]["g"]
    assert list(g["children"]) == ["a", "b"]
    assert g["children"]["b"]["children"] == {"c": {"type": "text", "text": "yo"}}
    assert "id" not in g["children"]["a"]


def test_static_flag_moves_into_the_scope_static_block():
    out = _data(migrate(HEADER + """\
static:
  bg: {type: shape, shape: rectangle, size: {width: 100%, height: 100%}}
elements:
  - {id: a, type: text, text: hi}
  - {id: s1, type: shape, shape: circle, radius: 3, static: true}
  - {id: b, type: text, text: yo, static: false}
  - {id: s2, type: shape, shape: circle, radius: 4, static: true}
layouts:
  l:
    elements:
      - {id: s3, type: shape, shape: circle, radius: 5, static: true}
      - {id: c, type: text, text: x}
"""))
    assert list(out["static"]) == ["bg", "s1", "s2"]
    assert out["static"]["s1"] == {"type": "circle", "radius": 3}
    assert list(out["elements"]) == ["a", "b"]
    assert out["elements"]["b"] == {"type": "text", "text": "yo"}
    assert list(out["layouts"]["l"]["static"]) == ["s3"]
    assert list(out["layouts"]["l"]["elements"]) == ["c"]


def test_static_block_is_created_before_elements():
    text = migrate(HEADER + "elements:\n  - {id: s, type: shape, shape: circle, "
                   "radius: 3, static: true}\n  - {id: a, type: text, text: hi}\n")
    out = _data(text)
    assert list(out)[-2:] == ["static", "elements"]


@pytest.mark.parametrize("modes, expected", [
    ("[active]", {}),
    ("[active, low_power]", {"sleep_update": True}),
    ("[low_power, active]", {"sleep_update": True}),
])
def test_modes(modes, expected):
    body = element(f"- {{id: x, type: text, text: hi, modes: {modes}}}\n")
    assert {k: v for k, v in body.items() if k not in ("type", "text")} == expected


@pytest.mark.parametrize("h, v, expected", [
    ("left", None, "left"),
    (None, "top", "top"),
    ("left", "top", "top_left"),
    ("right", "bottom", "bottom_right"),
    ("center", "bottom", "bottom"),
    ("right", "center", "right"),
    ("center", "center", "center"),
])
def test_align(h, v, expected):
    keys = ""
    if h:
        keys += f", align: {h}"
    if v:
        keys += f", vertical_align: {v}"
    body = element(f"- {{id: x, type: text, text: hi{keys}}}\n")
    assert body["align"] == expected
    assert "vertical_align" not in body


def test_if_unavailable_becomes_unsupported():
    body = element("- {id: x, type: text, text: hi, if_unavailable: hide}\n")
    assert body["unsupported"] == "hide"


@pytest.mark.parametrize("v1, v2", [
    ("when_absent: hide", "hide"),
    ("when_absent: placeholder, placeholder: '--'", "--"),
    ("when_absent: fallback, fallback: 'palette.x'", {"value": "color.x"}),
    ("when_absent: fallback, fallback: 0", {"value": 0}),
])
def test_absent(v1, v2):
    body = element(f"- {{id: x, type: text, value: activity.steps, {v1}}}\n")
    assert body["absent"] == v2
    assert not {"when_absent", "placeholder", "fallback"} & set(body)


def test_aod_block_kind_renames():
    body = element("""\
- id: x
  type: complication_slot
  slot: config.data.s
  icon_size: 9%r
  icon_color: palette.a
  aod: {icon_color: palette.b, color: palette.c}
""")
    assert body["aod"] == {"icon": {"color": "color.b"}, "color": "color.c"}


# --------------------------------------------------------------------------
# per kind


@pytest.mark.parametrize("shape", ["rectangle", "circle", "line", "arc", "ellipse", "polygon"])
def test_shape_becomes_its_own_type(shape):
    body = element(f"- {{id: x, type: shape, shape: {shape}}}\n")
    assert body == {"type": shape}


def test_rounded_rectangle_becomes_rectangle():
    body = element("- {id: x, type: shape, shape: rounded_rectangle, corner_radius: 3}\n")
    assert body == {"type": "rectangle", "corner_radius": 3}


def test_literal_text_doubles_braces():
    body = element("- {id: x, type: text, text: 'a {b} c'}\n")
    assert body["text"] == "a {{b}} c"


@pytest.mark.parametrize("value, fmt, template", [
    ("time.hour", None, "{time.hour}"),
    ("time.hour", "{:02d}", "{time.hour:02d}"),
    ("activity.steps / 1000.0", "{:.1f}k", "{activity.steps / 1000.0:.1f}k"),
    ("time.clock", "{:%H:%M}", "{time.clock:%H:%M}"),
    ("a > 0 ? a : 0", "{:d}", "{(a > 0 ? a : 0):d}"),
    ("a > 0 ? a : 0", None, "{(a > 0 ? a : 0)}"),
    ("(a ? b : c)", None, "{(a ? b : c)}"),
    ("activity.distance", "{:.1f} {unit}", "{activity.distance:.1f} {unit}"),
    ("x", "{{{:d}}}", "{{{{{x:d}}}}}"),
    ("x", "}{:d}", "}}{x:d}"),
    ("x", "{}", "{x}"),
])
def test_value_and_format_become_one_template(value, fmt, template):
    keys = f'value: "{value}"' + (f', format: "{fmt}"' if fmt else "")
    body = element(f"- {{id: x, type: text, {keys}}}\n")
    assert body["text"] == template
    assert "value" not in body and "format" not in body


def test_text_aod_format_becomes_a_template_on_the_elements_own_expression():
    body = element("""\
- id: x
  type: text
  value: time.clock
  format: "{:%H:%M}"
  aod: {format: "{:%H %M}"}
""")
    assert body["text"] == "{time.clock:%H:%M}"
    assert body["aod"] == {"text": "{time.clock:%H %M}"}


def test_group_aod_format_keeps_an_empty_placeholder():
    body = element("""\
- id: g
  type: group
  aod: {format: "{:d}"}
  children:
    - {id: x, type: text, value: time.hour}
""")
    assert body["aod"] == {"text": "{:d}"}


def test_icon():
    assert element("- {id: x, type: icon, icon: heart}\n")["icon"] == "heart"
    body = element("- {id: x, type: icon, glyph: 'U+F21E'}\n")
    assert body["icon"] == "U+F21E" and "glyph" not in body
    body = element("- {id: x, type: icon, icon_for: weather.condition}\n")
    assert body["icon"] == {"for": "weather.condition"} and "icon_for" not in body


def test_complication_slot_icon_keys_group():
    body = element("""\
- id: x
  type: complication_slot
  slot: config.data.s
  icon_size: 9%r
  icon_position: top
  icon_gap: 1%r
  icon_color: palette.a
  when_absent: placeholder
  placeholder: "--"
""")
    assert body == {"type": "data", "slot": "s", "absent": "--", "icon": {
        "size": "9%r", "position": "top", "gap": "1%r", "color": "color.a"}}


def test_progress_becomes_gauge_with_needle_parts():
    body = element("""\
- id: x
  type: progress
  style: needle
  value: battery.level
  max: 100
  start_angle: 0
  sweep: 90
  needle: [{shape: line, to: {dy: -10}, color: palette.a}]
  when_absent: hide
""")
    assert body["type"] == "gauge"
    assert body["needle"] == [{"type": "line", "to": {"dy": -10}, "color": "color.a"}]
    assert body["absent"] == "hide"


def test_hands_set():
    body = element("- {id: x, type: hands, hands: classic}\n")
    assert body == {"type": "hands", "set": "classic"}


def test_pattern_parts():
    body = element("""\
- id: x
  type: pattern
  pattern: radial
  count: 12
  when_absent: hide
  parts:
    - {shape: rectangle, align: left, vertical_align: top, color: palette.a}
    - shape: text
      value: "(copy + 11) % 12 + 1"
      format: "{:02d}"
      if_unavailable: hide
    - {shape: text, text: "{"}
""")
    assert body["absent"] == "hide"
    assert body["parts"] == [
        {"type": "rectangle", "align": "top_left", "color": "color.a"},
        {"type": "text", "text": "{(copy + 11) % 12 + 1:02d}", "unsupported": "hide"},
        {"type": "text", "text": "{{"},
    ]


def test_two_spellings_of_one_key_are_left_for_the_compiler_to_name():
    """Format 1 already refuses these; overwriting one with the other would
    turn an invalid file into a valid one."""
    body = element("- {id: x, type: text, text: hi, value: time.hour}\n")
    assert body["text"] == "hi" and body["value"] == "time.hour"
    body = element("- {id: x, type: icon, icon: heart, icon_for: weather.condition}\n")
    assert body["icon"] == "heart" and body["icon_for"] == "weather.condition"


def test_a_static_group_named_static_is_the_static_block():
    """`- id: static, type: group, static: true` is format 1's long spelling
    of the `static:` block itself."""
    out = _data(migrate(HEADER + """\
elements:
  - id: static
    type: group
    static: true
    children:
      - {id: bg, type: shape, shape: circle, radius: 3}
  - {id: a, type: text, text: hi}
"""))
    assert out["static"] == {"bg": {"type": "circle", "radius": 3}}
    assert list(out["elements"]) == ["a"]


def test_refuses_a_static_element_named_static_that_is_not_a_bare_group():
    messages = refusals(HEADER + """\
elements:
  - {id: static, type: shape, shape: circle, radius: 3, static: true}
""")
    assert len(messages) == 1 and "would collide" in messages[0]


# --------------------------------------------------------------------------
# refusals (§4): each one leaves the file untouched


def test_refuses_a_static_flag_nested_in_a_group():
    messages = refusals(HEADER + """\
elements:
  - id: g
    type: group
    children:
      - {id: s, type: shape, shape: circle, radius: 3, static: true}
""")
    assert len(messages) == 1
    assert "nested inside a group" in messages[0]


def test_refuses_a_static_flag_inside_a_static_block():
    messages = refusals(HEADER + """\
static:
  - {id: s, type: shape, shape: circle, radius: 3, static: true}
elements:
  - {id: a, type: text, text: hi}
""")
    assert len(messages) == 1
    assert "inside a 'static:' block" in messages[0]


@pytest.mark.parametrize("modes", ["[low_power]", "[always_on]", "[active, always_on]"])
def test_refuses_other_modes(modes):
    messages = refusals(HEADER + f"elements:\n  - {{id: a, type: text, text: hi, modes: {modes}}}\n")
    assert len(messages) == 1
    assert "no format 2 spelling" in messages[0]


def test_refuses_a_palette_name_that_is_a_scheme_role():
    messages = refusals(HEADER + """\
palette: {bg: "#000000", fg: "#FFFFFF"}
color_scheme:
  dark: {colors: {bg: palette.bg, fg: palette.fg}}
elements:
  - {id: a, type: text, text: hi}
""")
    assert sorted(messages) == [
        "the palette entry 'bg' has the same name as a 'color_scheme:' role",
        "the palette entry 'fg' has the same name as a 'color_scheme:' role",
    ]


def test_refuses_a_palette_name_that_is_an_axis_role():
    messages = refusals(HEADER + """\
palette: {accent: "#FF0000"}
config:
  accent_color: {default: palette.accent, choices: [palette.accent]}
elements:
  - {id: a, type: text, text: hi}
""")
    assert messages == ["the palette entry 'accent' has the same name as the role "
                        "'config: accent_color:' binds"]


def test_refuses_a_scheme_role_named_like_an_axis_role():
    messages = refusals(HEADER + """\
color_scheme:
  dark: {colors: {data: "#000000"}}
config:
  data_color: {default: "#FF0000", choices: any}
elements:
  - {id: a, type: text, text: hi}
""")
    assert len(messages) == 1
    assert "'data' collides" in messages[0]


@pytest.mark.parametrize("fmt", ["{:d}{:d}", "no field"])
def test_refuses_a_format_it_cannot_write_as_one_placeholder(fmt):
    messages = refusals(HEADER + f'elements:\n  - {{id: a, type: text, value: x, format: "{fmt}"}}\n')
    assert len(messages) == 1
    assert "template" in messages[0]


def test_refuses_the_placeholder_text_hide():
    messages = refusals(HEADER + "elements:\n  - {id: a, type: text, value: x, "
                        "when_absent: placeholder, placeholder: hide}\n")
    assert len(messages) == 1


def test_a_refusal_writes_nothing(tmp_path):
    design = tmp_path / "face.yaml"
    original = HEADER + "elements:\n  - {id: a, type: text, text: hi, modes: [low_power]}\n"
    design.write_text(original)
    proc = run_cli("migrate", "--in-place", str(design))
    assert proc.returncode == 1
    assert "error[migrate]" in proc.stderr
    assert design.read_text() == original


# --------------------------------------------------------------------------
# idempotence, layout survival, fragments


def test_a_v2_file_passes_through_unchanged():
    once = migrate(HEADER + "elements:\n  - {id: a, type: text, value: x, format: '{:d}'}\n")
    bag = Bag()
    twice = migrate_text(once, Path("face.yaml"), bag)
    assert twice is not None and not twice.changed
    assert twice.text == once


def test_comments_quotes_and_order_survive():
    text = migrate("""\
# header comment
format: 1   # the version
face: { id: 7f3c1e92-4a5b-4d81-9e6f-2b0c8d4a1f57, name: "Test" }
targets: [fenix8solar47mm]

# the palette
palette:
  red: "#FF0000"  # red

elements:
  # the clock
  - id: clock       # a clock
    type: text
    value: time.clock
    format: "{:%H:%M}" # hours and minutes
    color: palette.red

  - id: dot
    type: shape
    shape: circle
    radius: 2
    vertical_align: top
    align: left

  - id: after
    type: text
    text: 'single'
""")
    assert text.startswith("# header comment\nformat: 2   # the version\n")
    assert 'face: { id: 7f3c1e92-4a5b-4d81-9e6f-2b0c8d4a1f57, name: "Test" }' in text
    assert "# the palette\nresources:\n  palette:\n" in text
    assert 'red: "#FF0000"  # red' in text
    assert re.search(r"  # the clock\n  clock: +# a clock\n", text)
    assert 'text: "{time.clock:%H:%M}" # hours and minutes' in text
    assert "    align: top_left\n\n  after:\n" in text
    assert "text: 'single'" in text


def test_a_multi_line_quoted_string_keeps_its_lines():
    text = migrate(HEADER + """\
palette: {a: "#FFFFFF"}
elements:
  - id: x
    type: text
    text: hi
    lint:
      allow: [overlap]
      reason: "a long reason that the author
        wrapped by hand"
  - id: y
    type: text
    value: 'copy == 0 ? "A" :
      "B"'
""")
    assert 'reason: "a long reason that the author\n        wrapped by hand"' in text
    assert "text: '{(copy == 0 ? \"A\" :\n      \"B\")}'" in text


def test_a_folded_expression_stays_folded():
    text = migrate(HEADER + """\
elements:
  - id: y
    type: text
    value: >-
      copy == 0 ? "A" :
      "B"
""")
    assert 'text: >-\n      {(copy == 0 ? "A" :\n      "B")}' in text
    assert _data(text)["elements"]["y"]["text"] == '{(copy == 0 ? "A" : "B")}'


def test_a_one_key_mapping_in_a_flow_list_keeps_its_braces():
    """ruamel writes `[{dy: 1}]` as `[dy: 1]` by default -- the same data,
    but not what the author wrote."""
    text = migrate(HEADER + "hands:\n  h:\n    hour:\n      parts:\n"
                   "        - {shape: polygon, points: [{dx: 1}, {dy: -4}, {dx: 3}]}\n"
                   "elements:\n  - {id: a, type: hands, hands: h}\n")
    assert "points: [{dx: 1}, {dy: -4}, {dx: 3}]" in text


def test_an_escape_in_a_double_quoted_scalar_survives():
    """ruamel reads `"\\uF09B"` as the character and would write it back raw,
    which most editors show as a blank box."""
    text = migrate(HEADER + 'elements:\n  - id: a\n    type: text\n'
                   '    text: "\\uF09B"   # a glyph\n')
    assert 'text: "\\uF09B"   # a glyph' in text
    assert _data(text)["elements"]["a"]["text"] == "\uf09b"


def test_the_schema_modeline_is_updated():
    text = migrate("# yaml-language-server: $schema=../schema/wfb-face-1.schema.json\n"
                   + HEADER + "elements:\n  - {id: a, type: text, text: hi}\n")
    assert text.startswith("# yaml-language-server: $schema=../schema/wfb-face-2.schema.json\n")


def test_fragment_without_format_is_migrated_as_format_1():
    out = _data(migrate("""\
palette: {a: "#FFFFFF"}
elements:
  - {id: x, type: shape, shape: circle, radius: 1, color: palette.a}
"""))
    assert "format" not in out
    assert out["resources"]["palette"] == {"a": "#FFFFFF"}
    assert out["elements"]["x"] == {"type": "circle", "radius": 1, "color": "color.a"}


def test_elements_fragment():
    out = _data(migrate("""\
- id: x
  type: text
  value: time.hour
  format: "{:02d}"
- {id: y, type: shape, shape: circle, radius: 1}
""", fragment="elements"))
    assert out == {"x": {"type": "text", "text": "{time.hour:02d}"},
                   "y": {"type": "circle", "radius": 1}}


def test_element_fragment():
    out = _data(migrate("""\
type: text
value: time.hour
when_absent: hide
""", fragment="element"))
    assert out == {"type": "text", "text": "{time.hour}", "absent": "hide"}


# --------------------------------------------------------------------------
# the CLI and the corpus


def test_cli_prints_check_and_in_place(tmp_path):
    design = tmp_path / "face.yaml"
    design.write_text(HEADER + "elements:\n  - {id: a, type: text, text: hi}\n")
    proc = run_cli("migrate", str(design))
    assert proc.returncode == 0 and proc.stdout.startswith("format: 2\n")
    proc = run_cli("migrate", "--check", str(design))
    assert proc.returncode == 1 and "would migrate" in proc.stdout
    proc = run_cli("migrate", "--in-place", str(design))
    assert proc.returncode == 0 and design.read_text().startswith("format: 2\n")
    assert run_cli("migrate", "--check", str(design)).returncode == 0


def _corpus() -> list[Path]:
    return sorted([*ROOT.glob("examples/**/*.yaml"), *ROOT.glob("wfb/templates/*.yaml"),
                   *ROOT.glob("tests/fixtures/**/*.yaml")])


@pytest.mark.parametrize("path", _corpus(), ids=lambda p: str(p.relative_to(ROOT)))
def test_every_example_template_and_fixture_is_format_2_already(path):
    """The corpus was migrated with this tool; running it again is a no-op."""
    bag = Bag()
    result = migrate_text(path.read_text(encoding="utf-8"), path, bag)
    assert result is not None, bag.render()
    assert not result.changed
