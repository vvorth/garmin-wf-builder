"""monkeyc's string-label collision: detection, the IconGlyphs rewrite, and
the build error for what cannot be rewritten (`wfb/emit/strhash.py`)."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.test_diagnostics import load
from wfb import icons
from wfb.build import build
from wfb.emit import project as project_module
from wfb.emit import strhash
from wfb.emit.project import generate
from wfb.emit.resources import bake_fonts

ROOT = Path(__file__).resolve().parent.parent

SLOT_DESIGN = """
format: 1
face: {{id: 7f3c1e92-4a5b-4d81-9e6f-2b0c8d4a1f57, name: Test}}
targets: [fenix8solar47mm]
palette: {{bg: "#000000", fg: "#FFFFFF"}}
config:
  data:
    top:
      default: complication.weekly_run_distance
      choices: {choices}
elements:
  - id: top_reading
    type: complication_slot
    slot: config.data.top
    at: {{anchor: center}}
    icon_size: 8%r
    color: palette.fg
    lint: {{allow: [config-unsupported], reason: test}}
"""

COLLIDING = "[complication.weekly_run_distance, complication.current_temperature]"
CLEAN = "[complication.weekly_run_distance, complication.steps]"


def _project(write_design, bag, db, tmp_path, choices: str):
    face = load(write_design(SLOT_DESIGN.format(choices=choices)), bag)
    assert face is not None, bag.render()
    device = db.get("fenix8solar47mm")
    return generate(face, [device], tmp_path, {device.id: bake_fonts(face, device)})


def test_java_string_hash_matches_java():
    # Values from java.lang.String.hashCode().
    assert strhash.java_string_hash("") == 0
    assert strhash.java_string_hash("hello") == 99162322
    assert strhash.java_string_hash("polygenelubricants") == -2147483648


def test_the_reproduced_collision_is_the_label_monkeyc_printed():
    """The real build failed with "Redefinition of label (data) str___1798574"."""
    distance = icons.CATALOG["distance"].codepoint
    temperature = icons.CATALOG["temperature"].codepoint
    assert strhash.java_string_hash(distance) == 1798574
    assert strhash.java_string_hash(temperature) == 1798574


def test_string_literals_skip_comments_and_chars():
    source = '''
    // a "commented" string
    /* and "another" */
    var c = '"';
    var s = "a\\"b";  // trailing "comment"
    var t = "x";
    '''
    assert strhash.string_literals(source) == ['a"b', "x"]


def test_colliding_glyphs_are_built_at_runtime(write_design, bag, db, tmp_path):
    project = _project(write_design, bag, db, tmp_path, COLLIDING)
    glyphs = project.files()["source/IconGlyphs.mc"]
    assert 'case "distance": return (0xf08f0).toChar().toString();' in glyphs
    assert 'case "temperature": return (0xf050f).toChar().toString();' in glyphs
    assert project.string_collisions == []


def test_without_the_rewrite_the_collision_is_reported(write_design, bag, db, tmp_path,
                                                        monkeypatch):
    """The contrast for the test above: the rewrite is what removes it."""
    original = project_module.monkeyc.emit_icon_glyphs
    monkeypatch.setattr(project_module.monkeyc, "emit_icon_glyphs",
                        lambda face, via_char=frozenset(): original(face))
    project = _project(write_design, bag, db, tmp_path, COLLIDING)
    assert [c.hash for c in project.string_collisions] == [1798574]


def test_no_collision_leaves_every_glyph_a_literal(write_design, bag, db, tmp_path):
    project = _project(write_design, bag, db, tmp_path, CLEAN)
    glyphs = project.files()["source/IconGlyphs.mc"]
    assert "toChar" not in glyphs
    assert project.string_collisions == []


def test_an_unfixable_collision_is_a_build_error(write_design, bag, db, tmp_path):
    """Two static icons put both colliding glyphs in the view as literals,
    where nothing rewrites them: report it instead of letting monkeyc crash."""
    design = write_design("""
format: 1
face: {id: 7f3c1e92-4a5b-4d81-9e6f-2b0c8d4a1f57, name: Test}
targets: [fenix8solar47mm]
palette: {bg: "#000000", fg: "#FFFFFF"}
elements:
  - {id: a, type: icon, icon: distance, size: 10%r, at: {anchor: center, dx: -20%}, color: palette.fg}
  - {id: b, type: icon, icon: temperature, size: 10%r, at: {anchor: center, dx: 20%}, color: palette.fg}
""")
    result = build(design, output=tmp_path / "out", bag=bag, db=db, compile_prg=False)
    assert result is None
    errors = [d for d in bag.items if d.code == "string-label"]
    assert len(errors) == 1
    assert "str___1798574" in errors[0].message
    assert "<U+F08F0>" in errors[0].message and "<U+F050F>" in errors[0].message


@pytest.mark.parametrize("example", sorted(p.parent.name for p in (ROOT / "examples").glob("*/face.yaml")))
def test_no_example_has_a_string_label_collision(example, bag, db, tmp_path):
    face = load(ROOT / "examples" / example / "face.yaml", bag)
    if face is None:
        pytest.skip(f"{example} does not load: {bag.render()}")
    device = db.get(face.targets[0]) if face.targets[0] in db.ids() else db.get("fenix8solar47mm")
    project = generate(face, [device], tmp_path, {device.id: bake_fonts(face, device)})
    assert project.string_collisions == []
