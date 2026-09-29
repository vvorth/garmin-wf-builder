"""What every key a `group` accepts does to its members (`wfb.ir.model.
GROUP_KEYS`).  A group draws nothing, so a key it accepts that reaches no
member is silently ignored -- `sleep_update:` (which also broke the build:
`onPartialUpdate` with no clip constants), `z:` and `lint:` all were."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from wfb.ir.model import GROUP_KEYS

from tests.helpers import find, lint_text, load_errors, load_face, resolve_text

SCHEMA = Path(__file__).resolve().parent.parent / "schema" / "wfb-face-2.schema.json"

_BASE = """
format: 2
face:
  id: 7f3c1e92-4a5b-4d81-9e6f-2b0c8d4a1f57
  name: Test
build:
  targets: [fr955]
resources:
  palette:
    bg: "#000000"
    fg: "#FFFFFF"
    dim: "#555555"
elements:
  background:
    type: rectangle
    at: {anchor: center}
    size: {width: 100%, height: 100%}
    color: color.bg
"""


def test_every_group_key_has_a_policy():
    """The guard: a key added to `groupElement` without deciding what it
    does to members fails here, not silently in a design."""
    schema = json.loads(SCHEMA.read_text())
    keys = set(schema["$defs"]["groupElement"]["properties"])
    assert keys == set(GROUP_KEYS), (
        f"schema-only: {sorted(keys - set(GROUP_KEYS))}, "
        f"table-only: {sorted(set(GROUP_KEYS) - keys)}")


def test_sleep_update_reaches_every_member(write_design, bag, db):
    face = load_face(_BASE + """
  g:
    type: group
    sleep_update: true
    children:
      a: {type: circle, at: {anchor: center}, radius: 5px, color: color.fg}
      inner:
        type: group
        children:
          b: {type: circle, at: {anchor: center, dx: 20px}, radius: 5px, color: color.fg}
      c: {type: circle, at: {anchor: center, dx: -20px}, radius: 5px, color: color.fg,
          sleep_update: false}
""", write_design, bag)
    modes = {e.id: e.modes for e in face.walk()}
    assert modes["a"] == modes["b"] == ("active", "low_power")
    assert modes["c"] == ("active",)  # an explicit false opts out
    assert modes["background"] == ("active",)


def test_a_sleep_update_group_gets_a_clip(write_design, bag, db):
    """The build failure: `onPartialUpdate` emitted with no member in the
    low-power clip, so no `LOW_POWER_CLIP_*` constants to set it from."""
    _, resolved = resolve_text(_BASE + """
  g:
    type: group
    sleep_update: true
    children:
      a: {type: circle, at: {anchor: center}, radius: 5px, color: color.fg}
""", write_design, bag, db, "fr955")
    clip = resolved.clip_for("low_power")
    box = find(resolved, "a").box
    assert clip is not None and clip.union(box) == clip


def test_a_kind_that_refuses_sleep_update_refuses_an_inherited_one(write_design):
    errors = load_errors(_BASE + """
  g:
    type: group
    sleep_update: true
    children:
      ticks:
        type: pattern
        pattern: radial
        at: {anchor: center}
        count: 4
        step: 90deg
        color: color.fg
        parts:
          - {type: circle, at: {dy: -50%r}, radius: 3px}
""", write_design)
    assert [e.code for e in errors] == ["pattern"], errors
    assert "inherits 'sleep_update: true' from group 'g'" in errors[0].message


def test_z_reaches_every_member(write_design, bag):
    face = load_face(_BASE + """
  g:
    type: group
    z: 10
    children:
      a: {type: circle, at: {anchor: center}, radius: 5px, color: color.fg}
      b: {type: circle, at: {anchor: center}, radius: 3px, color: color.fg, z: -1}
  later: {type: circle, at: {anchor: center}, radius: 2px, color: color.fg}
""", write_design, bag)
    assert [e.id for e in face.draw_order()] == ["b", "background", "later", "a"]


def test_lint_allow_reaches_every_member(write_design, db):
    text = _BASE + """
  g:
    type: group
    LINT
    children:
      faint: {type: circle, at: {anchor: center}, radius: 20px, color: color.dim}
"""
    plain = lint_text(text.replace("LINT", ""), write_design, db, "fr955")
    allowed = lint_text(text.replace(
        "LINT", 'lint: {allow: [contrast], reason: "a quiet backdrop disc"}'),
        write_design, db, "fr955")
    assert [d.code for d in plain.items if d.code == "contrast"] == ["contrast"]
    assert not [d for d in allowed.items if d.code == "contrast"], allowed.render()


def test_a_bad_code_on_a_group_is_reported_once(write_design, bag):
    """Inherited, but validated only where it is written -- one error, not
    one per member (`tests/CLAUDE.md`)."""
    from wfb import lint

    face = load_face(_BASE + """
  g:
    type: group
    lint: {allow: [no-such-code], reason: "typo"}
    children:
      a: {type: circle, at: {anchor: center}, radius: 5px, color: color.fg}
      b: {type: circle, at: {anchor: center}, radius: 3px, color: color.fg}
""", write_design, bag)
    lint.run_design(face, bag)
    assert len([d for d in bag.items if "no-such-code" in d.message]) == 1, bag.render()


@pytest.mark.slow
def test_a_sleep_update_group_compiles(write_design, db, tmp_path, toolchain):
    """The original failure was `monkeyc`'s: `Undefined symbol
    ':LOW_POWER_CLIP_X'`."""
    from wfb.build import build as real_build
    from wfb.diagnostics import Bag

    bag = Bag()
    result = real_build(write_design(_BASE + """
  seconds:
    type: group
    at: {anchor: center, dy: 14%}
    size: {width: 20%, height: 8%}
    sleep_update: true
    children:
      secs:
        type: text
        text: "{time.second:02d}"
        font: FONT_XTINY
        at: {anchor: center}
        color: color.fg
"""), output=tmp_path, bag=bag, db=db, toolchain=toolchain)
    assert result is not None, bag.render()
    assert bag.ok(), bag.render()
