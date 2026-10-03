"""`wfb studio`'s colour schemes: each edit changes every place a scheme or
role is written, as one patch (`wfb.edit.schemes`)."""

from __future__ import annotations

from pathlib import Path

import pytest

from wfb import starters
from wfb.diagnostics import Bag
from wfb.edit import Refused, SpanIndex
from wfb.edit.gate import load_text
from wfb.lint import run_design
from wfb.studio.bundle import Bundle, from_path
from wfb.studio.document import Studio
from wfb.studio.store import Store

ROOT = Path(__file__).resolve().parent.parent
SHOWCASE = ROOT / "examples/showcase/face.yaml"


@pytest.fixture
def studio(tmp_path, db):
    s = Studio(Store(tmp_path / "state"), db, scratch=tmp_path / "scratch")
    yield s
    s.close()


def new(studio, text=None):
    return studio.create(Bundle("T", text or starters.instantiate("minimal", "T")), "new")


def showcase(studio):
    bundle, moved = from_path(SHOWCASE)
    return studio.create(bundle, "open", moved)


def edit(doc, **op):
    doc.edit(op, doc.version)


def data(doc):
    return SpanIndex(doc.text).data


def switchable(studio):
    doc = new(studio)
    edit(doc, op="make_switchable", names=["bg", "text"], scheme="dark")
    return doc


def test_colours_made_switchable_keep_their_names_and_a_style_picks_them(studio):
    doc = switchable(studio)
    d = data(doc)
    assert d["resources"]["palette"] == {"dim": "#AAAAAA"}
    assert d["theme"] == {"schemes": {"dark": {"colors": {"bg": "#000000", "text": "#FFFFFF"}}}}
    assert d["config"]["style"] == {"default": "dark", "choices": {"dark": {"scheme": "dark"}}}
    assert d["elements"]["clock"]["color"] == "color.text"         # no reference changed
    # written in block style, as an author would
    assert "theme:\n  schemes:\n    dark:\n      colors:\n        bg: \"#000000\"\n" in doc.text
    assert doc.analysis().face is not None


def test_a_scheme_is_added_renamed_and_deleted_with_its_styles(studio):
    doc = switchable(studio)
    edit(doc, op="add_scheme", name="light")
    d = data(doc)
    assert d["theme"]["schemes"]["light"] == {"colors": {"bg": "#000000", "text": "#FFFFFF"}}
    assert d["config"]["style"]["choices"]["light"] == {"scheme": "light"}
    edit(doc, op="rename_scheme", name="light", to="day")
    assert data(doc)["config"]["style"]["choices"]["light"] == {"scheme": "day"}
    edit(doc, op="delete_scheme", name="day")
    assert set(data(doc)["theme"]["schemes"]) == {"dark"}
    assert set(data(doc)["config"]["style"]["choices"]) == {"dark"}


def test_a_new_scheme_on_a_face_with_layouts_gets_a_style_per_layout(studio):
    doc = showcase(studio)
    edit(doc, op="add_scheme", name="mint", like="navy")
    choices = data(doc)["config"]["style"]["choices"]
    assert {k: v for k, v in choices.items() if k.endswith("_mint")} == {
        "analog_mint": {"layout": "analog", "scheme": "mint"},
        "digital_mint": {"layout": "digital", "scheme": "mint"},
        "roman_mint": {"layout": "roman", "scheme": "mint"},
    }
    assert data(doc)["theme"]["schemes"]["mint"]["colors"] == \
        data(doc)["theme"]["schemes"]["navy"]["colors"]


def test_a_role_is_added_renamed_and_deleted_in_every_scheme(studio):
    doc = switchable(studio)
    edit(doc, op="add_scheme", name="light")
    edit(doc, op="add_role", name="hot", value="#ff5500")
    assert [s["colors"]["hot"] for s in data(doc)["theme"]["schemes"].values()] == ["#FF5500"] * 2
    edit(doc, op="rename_role", name="text", to="ink")
    assert all("ink" in s["colors"] and "text" not in s["colors"]
               for s in data(doc)["theme"]["schemes"].values())
    assert data(doc)["elements"]["clock"]["color"] == "color.ink"
    edit(doc, op="delete_role", name="hot")
    assert all("hot" not in s["colors"] for s in data(doc)["theme"]["schemes"].values())


def test_removing_the_schemes_keeps_one_schemes_colours_and_drops_scheme_only_styles(studio):
    doc = switchable(studio)
    edit(doc, op="add_scheme", name="light")
    edit(doc, op="remove_theme", keep="dark")
    d = data(doc)
    assert "theme" not in d and "config" not in d
    assert d["resources"]["palette"] == {"dim": "#AAAAAA", "bg": "#000000", "text": "#FFFFFF"}
    assert doc.analysis().face is not None


def test_removing_the_showcases_schemes_keeps_every_layout_style_and_warns_of_the_copies(studio):
    doc = showcase(studio)
    before = data(doc)["config"]["style"]["choices"]
    edit(doc, op="remove_theme", keep="dark")
    d = data(doc)
    choices = d["config"]["style"]["choices"]
    assert list(choices) == list(before)
    assert all("scheme" not in c and c["layout"] == before[k]["layout"] for k, c in choices.items())
    assert d["config"]["style"]["default"] == "digital_dark"
    palette = d["resources"]["palette"]
    assert (palette["bg"], palette["fg"], palette["notify"]) == ("#000000", "#FFFFFF", "#000000")
    lints = Bag()
    run_design(doc.analysis().face, lints)
    assert sorted(x.message.split(":")[0] for x in lints.items if x.code == "duplicate-style") == [
        "config.style.choices.analog_crimson", "config.style.choices.analog_light",
        "config.style.choices.digital_light", "config.style.choices.roman_crimson"]


def test_scheme_refusals_leave_the_face_alone(studio):
    doc = switchable(studio)
    before = (doc.text, doc.version)
    with pytest.raises(Refused, match="dim names a colour already"):
        edit(doc, op="rename_role", name="text", to="dim")
    with pytest.raises(Refused, match="only scheme"):
        edit(doc, op="delete_scheme", name="dark")
    with pytest.raises(Refused, match="used by"):
        edit(doc, op="delete_role", name="text")
    with pytest.raises(Refused, match="is a palette colour"):
        edit(doc, op="add_role", name="dim", value="#FFFFFF")
    with pytest.raises(Refused, match="has schemes already"):
        edit(doc, op="make_switchable", names=["dim"], scheme="other")
    with pytest.raises(Refused, match="no scheme called"):
        edit(doc, op="remove_theme", keep="nope")
    assert (doc.text, doc.version) == before
    doc = new(studio)
    with pytest.raises(Refused, match="not a palette colour"):
        edit(doc, op="make_switchable", names=["nope"], scheme="dark")


def test_a_role_with_no_style_to_pick_its_scheme_says_so_in_the_authors_words(tmp_path):
    text = starters.instantiate("minimal", "T").replace("    color: color.text\n",
                                                         "    color: color.fg\n")
    text += "\ntheme:\n  schemes:\n    dark:\n      colors: { fg: \"#FFFFFF\" }\n"
    path = tmp_path / "face.yaml"
    path.write_text(text)
    errors = load_text(path, text).errors
    assert [e.message for e in errors] == [
        "color: color.fg is a role of 'theme: schemes:', but no 'config: style:' entry "
        "picks a scheme"]
