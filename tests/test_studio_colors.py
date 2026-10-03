"""`wfb studio`'s colours: a picked colour becomes a named swatch, the
editor's own swatches follow their value and go when unused, and the
colour axes are edited as explicit lists (`wfb.edit.colors`)."""

from __future__ import annotations

import pytest
from starlette.testclient import TestClient

from wfb import starters
from wfb.edit import Refused, SpanIndex
from wfb.edit.colors import automatic_name, is_automatic, user_names
from wfb.studio.app import create_app
from wfb.studio.bundle import Bundle
from wfb.studio.document import Studio
from wfb.studio.store import Store


@pytest.fixture
def studio(tmp_path, db):
    s = Studio(Store(tmp_path / "state"), db, scratch=tmp_path / "scratch")
    yield s
    s.close()


def new(studio, text=None):
    return studio.create(Bundle("T", text or starters.instantiate("minimal", "T")), "new")


def palette(doc):
    return SpanIndex(doc.text).data["resources"]["palette"]


def color_of(doc, element):
    return SpanIndex(doc.text).data["elements"][element]["color"]


def pick(doc, element, value):
    doc.edit({"op": "use_color", "path": ["elements", element, "color"], "value": value},
             doc.version)


def test_the_editor_names_a_colour_after_its_value():
    assert automatic_name("#ff5500") == "international_orange"
    assert automatic_name("#FF8000") == "cFF8000"
    assert is_automatic("cFF8000", "#FF8000") and is_automatic("red_2", "#FF0000")
    assert not is_automatic("accent", "#FF0000") and not is_automatic("cFF8000_dim", "#FF8000")


def test_one_of_the_64_is_added_under_its_name_with_its_label(studio):
    doc = new(studio)
    pick(doc, "clock", "#FF0000")
    assert color_of(doc, "clock") == "color.red"
    assert palette(doc)["red"] == {"value": "#FF0000", "label": "Red"}
    assert doc.history()["states"][0]["label"] == "set elements.clock.color to color.red (adds red)"


def test_a_custom_colour_is_a_c_swatch_and_one_of_the_64_keeps_its_name(studio):
    doc = new(studio)
    pick(doc, "clock", "#FF8000")
    assert color_of(doc, "clock") == "color.cFF8000" and palette(doc)["cFF8000"] == "#FF8000"
    pick(doc, "seconds", "#ff5500")
    assert color_of(doc, "seconds") == "color.international_orange"


def test_a_colour_the_palette_holds_is_reused_whatever_its_name(studio):
    doc = new(studio)
    before = dict(palette(doc))
    pick(doc, "clock", "#000")
    assert color_of(doc, "clock") == "color.bg" and palette(doc) == before


def test_a_name_taken_by_another_colour_or_a_role_gets_a_suffix(studio):
    text = starters.instantiate("minimal", "T").replace(
        '    dim: "#AAAAAA"\n', '    dim: "#AAAAAA"\n    red: "#CC0000"\n')
    doc = new(studio, text)
    pick(doc, "clock", "#FF0000")
    assert color_of(doc, "clock") == "color.red_2"
    text = starters.instantiate("minimal", "T") + (
        "\nconfig:\n  accent_color:\n    role: red\n    default: color.bg\n"
        "    choices: [color.bg, color.text]\n")
    doc = new(studio, text)
    pick(doc, "clock", "#FF0000")
    assert color_of(doc, "clock") == "color.red_2"


def test_an_automatic_swatch_goes_with_its_last_user_and_an_authors_never(studio):
    doc = new(studio)
    pick(doc, "clock", "#FF8000")
    pick(doc, "seconds", "#FF8000")
    assert "dim" in palette(doc)            # the author's own, now unused, stays
    pick(doc, "clock", "#FF0000")
    assert "cFF8000" in palette(doc)        # seconds still uses it
    pick(doc, "seconds", "#FF0000")
    assert "cFF8000" not in palette(doc)
    assert "dim" in palette(doc)


def test_an_automatic_swatch_follows_its_value_label_and_all(studio):
    doc = new(studio)
    pick(doc, "clock", "#FF0000")
    doc.edit({"op": "set_swatch", "name": "red", "value": "#AA0000"}, doc.version)
    assert color_of(doc, "clock") == "color.bright_red"
    assert palette(doc)["bright_red"] == {"value": "#AA0000", "label": "Bright Red"}
    doc.edit({"op": "set_swatch", "name": "bright_red", "value": "#123456"}, doc.version)
    assert color_of(doc, "clock") == "color.c123456"
    assert palette(doc)["c123456"] == {"value": "#123456"}


def test_an_authors_swatch_keeps_its_name_when_its_value_changes(studio):
    doc = new(studio)
    doc.edit({"op": "set_swatch", "name": "dim", "value": "#555555"}, doc.version)
    assert palette(doc)["dim"] == "#555555" and color_of(doc, "seconds") == "color.dim"


def test_the_rename_reaches_only_the_whole_name(studio):
    text = starters.instantiate("minimal", "T").replace(
        '    dim: "#AAAAAA"\n',
        '    dim: "#AAAAAA"\n    cFF8000: "#FF8000"\n    cFF8000_dim: "#AA5500"\n').replace(
        "    color: color.dim\n",
        '    color: "time.second > 30 ? color.cFF8000 : color.cFF8000_dim"\n')
    doc = new(studio, text)
    doc.edit({"op": "set_swatch", "name": "cFF8000", "value": "#FF5500"}, doc.version)
    assert color_of(doc, "seconds") == \
        "time.second > 30 ? color.international_orange : color.cFF8000_dim"
    assert set(palette(doc)) >= {"international_orange", "cFF8000_dim"}
    assert "cFF8000" not in palette(doc)


def test_remove_unused_keeps_what_the_launcher_icon_reads(studio):
    doc = new(studio)
    pick(doc, "seconds", "#FF0000")
    doc.edit({"op": "add_swatch", "value": "#123456"}, doc.version)
    doc.edit({"op": "remove_unused"}, doc.version)
    assert set(palette(doc)) == {"bg", "text", "red"}     # dim and c123456 gone
    with pytest.raises(Refused, match="every colour in the palette is in use"):
        doc.edit({"op": "remove_unused"}, doc.version)


def test_a_colour_already_held_is_not_added_twice(studio):
    doc = new(studio)
    with pytest.raises(Refused, match="already, as bg"):
        doc.edit({"op": "add_swatch", "value": "#000000"}, doc.version)


def test_refusals_leave_the_face_alone(studio):
    text = starters.instantiate("minimal", "T") + (
        "\ntheme:\n  schemes:\n    dark:\n      colors: { ink: \"#FFFFFF\" }\n"
        "\nconfig:\n  style:\n    default: d\n    choices: { d: { scheme: dark } }\n")
    doc = new(studio, text)
    before = (doc.text, doc.version)
    with pytest.raises(Refused, match="color.dim"):
        doc.edit({"op": "remove", "path": ["resources", "palette", "dim"]}, doc.version)
    with pytest.raises(Refused, match="both a palette swatch and a colour role"):
        doc.edit({"op": "rename", "path": ["resources", "palette", "dim"], "to": "ink",
                  "prefix": "color."}, doc.version)
    with pytest.raises(Refused, match="no colour called"):
        doc.edit({"op": "set_swatch", "name": "nope", "value": "#000000"}, doc.version)
    with pytest.raises(Refused, match="is not a colour"):
        pick(doc, "clock", "orange-ish")
    assert (doc.text, doc.version) == before


def test_the_panel_says_who_uses_each_colour(studio, db):
    doc = new(studio)
    by_name = {p["name"]: p for p in doc.summary()["globals"]["palette"]}
    assert by_name["bg"]["used_by"] == ["background"]
    assert by_name["dim"]["used_by"] == ["seconds"] and not by_name["dim"]["automatic"]
    assert by_name["bg"]["launcher"]
    assert user_names(SpanIndex(doc.text), "nope") == []


def test_the_colour_axes_are_written_as_lists(studio):
    doc = new(studio)
    doc.edit({"op": "set", "path": ["config"],
              "value": {"accent_color": {"default": "color.text",
                                         "choices": ["color.text", "color.dim"]}}}, doc.version)
    axes = doc.summary()["globals"]["axes"]
    assert axes["accent_color"] == {"default": "color.text", "choices": ["color.text", "color.dim"],
                                    "raw": ["color.text", "color.dim"], "role": "accent",
                                    "own_role": False}
    assert axes["data_color"] is None
    assert "accent" in doc.summary()["globals"]["roles"]
    doc.edit({"op": "set", "path": ["config", "accent_color", "choices"],
              "value": ["color.text", "color.dim", "color.bg"]}, doc.version)
    assert doc.summary()["globals"]["axes"]["accent_color"]["choices"][-1] == "color.bg"
    with pytest.raises(Refused):
        doc.edit({"op": "set", "path": ["config", "accent_color", "default"],
                  "value": "color.nope"}, doc.version)


def test_the_vocabulary_names_the_64(studio):
    client = TestClient(create_app(studio))
    mip = client.get("/api/vocabulary").json()["mip"]
    assert len(mip) == 64 and mip[0] == {"name": "white", "value": "#FFFFFF", "label": "White"}
