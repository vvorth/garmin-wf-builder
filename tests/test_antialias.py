"""`antialias:` -- the format surface and IR resolution (font baking's half).

Two entirely separate SDK mechanisms share this one key (`docs/research/
probes/antialias/README.md`): a *resource* attribute for a bitmap font, and a
runtime `Dc.setAntiAlias` call for a primitive. This file covers the first --
the top-level default, per-element inheritance, the `text` rejection, and the
icon-font plumbing (`wfb.icons.font_key`, `wfb.emit.resources.icon_font_specs`).
Primitive anti-aliasing is a later, separate piece of work: `shape` and
`progress` accept and resolve `antialias:` here (so that work has something to
read), but nothing yet emits `setAntiAlias` for either -- see
`docs/limitations.md`.

Every guard below was watched fail before it was believed, named in its own
docstring, the same discipline `test_static.py` and `test_visibility.py` use.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.test_diagnostics import load
from wfb import icons
from wfb.diagnostics import Bag
from wfb.units import Length

ROOT = Path(__file__).resolve().parent.parent
FONT = ROOT / "examples" / "slice" / "assets" / "OpenSans-Regular.ttf"

HEAD = f"""format: 1
face:
  id: 7f3c1e92-4a5b-4d81-9e6f-2b0c8d4a1f57
  name: Test
targets: [fenix8solar47mm]
palette:
  bg: "#000000"
  fg: "#FFFFFF"
fonts:
  clock:
    source: {FONT}
    size: 18%r
"""

BACKGROUND = """  - id: background
    type: shape
    shape: rectangle
    at: {anchor: center}
    size: {width: 100%, height: 100%}
    color: palette.bg
"""


def design(top: str, elements: str) -> str:
    return f"{HEAD}{top}elements:\n{BACKGROUND}{elements}"


# -- R1: the face-wide default -----------------------------------------------


def test_antialias_defaults_to_false(write_design, bag):
    face = load(write_design(design("", "")), bag)
    assert face is not None, bag.render()
    assert face.antialias is False


def test_a_declared_face_default_is_recorded(write_design, bag):
    face = load(write_design(design("antialias: true\n", "")), bag)
    assert face is not None, bag.render()
    assert face.antialias is True


# -- R2: per-element resolution and inheritance ------------------------------

ICON = """  - id: probe
    type: icon
    icon: heart
    size: 20%r
    at: {anchor: center}
    color: palette.fg
"""


def test_an_icon_with_no_antialias_follows_the_face_default(write_design, bag):
    """Absence means inherit, all the way up to the face default -- not `False`
    outright, or a face-wide `antialias: true` would reach nothing."""
    face = load(write_design(design("antialias: true\n", ICON)), bag)
    assert face is not None, bag.render()
    probe = next(e for e in face.walk() if e.id == "probe")
    assert probe.antialias is None  # the author wrote nothing
    assert probe.resolved_antialias is True  # but the face default reaches it


def test_an_elements_own_antialias_wins_over_the_face_default(write_design, bag):
    on_icon = ICON.replace("color: palette.fg\n", "color: palette.fg\n    antialias: false\n")
    face = load(write_design(design("antialias: true\n", on_icon)), bag)
    assert face is not None, bag.render()
    probe = next(e for e in face.walk() if e.id == "probe")
    assert probe.antialias is False
    assert probe.resolved_antialias is False


GROUP = """  - id: dial
    type: group
    antialias: true
    children:
      - id: inner
        type: icon
        icon: heart
        size: 20%r
        at: {anchor: center}
        color: palette.fg
      - id: inner_override
        type: icon
        icon: flame
        size: 20%r
        at: {anchor: center}
        color: palette.fg
        antialias: false
"""


def test_a_groups_antialias_is_the_default_for_its_subtree(write_design, bag):
    face = load(write_design(design("", GROUP)), bag)
    assert face is not None, bag.render()
    inner = next(e for e in face.walk() if e.id == "inner")
    assert inner.antialias is None  # inherited, not written
    assert inner.resolved_antialias is True  # from the group, not the (false) face default


def test_a_childs_own_antialias_wins_outright_over_its_group(write_design, bag):
    """Not a conjunction the way `visible:` is -- the child's own `false`
    beats the group's `true` outright, rather than the two combining."""
    face = load(write_design(design("", GROUP)), bag)
    assert face is not None, bag.render()
    overridden = next(e for e in face.walk() if e.id == "inner_override")
    assert overridden.antialias is False
    assert overridden.resolved_antialias is False


NESTED_GROUP = """  - id: outer
    type: group
    antialias: true
    children:
      - id: inner_group
        type: group
        children:
          - id: leaf
            type: icon
            icon: heart
            size: 20%r
            at: {anchor: center}
            color: palette.fg
"""


def test_an_inner_group_with_no_antialias_passes_the_outer_default_through(write_design, bag):
    """A group that declares no `antialias:` of its own must still relay
    whatever default reaches it down to its own children -- not stop at
    `None` and leave the leaf to fall back to the face default instead."""
    face = load(write_design(design("", NESTED_GROUP)), bag)
    assert face is not None, bag.render()
    leaf = next(e for e in face.walk() if e.id == "leaf")
    assert leaf.resolved_antialias is True


SHAPE_AND_PROGRESS = """  - id: ring
    type: progress
    style: arc
    value: activity.steps
    max: activity.step_goal
    when_absent: hide
    radius: 40%r
    thickness: 6px
    start_angle: 0
    sweep: 300
    color: palette.fg
    antialias: true
  - id: deco
    type: shape
    shape: circle
    at: {anchor: center}
    radius: 10%r
    color: palette.fg
    antialias: true
"""


def test_shape_and_progress_accept_and_resolve_antialias(write_design, bag):
    """Plumbing for the primitive (`Dc.setAntiAlias`) half of this feature,
    which is a separate, later piece of work (docs/limitations.md) -- nothing
    consumes this yet, but it must parse, validate and resolve so that work
    has something to read off the element."""
    face = load(write_design(design("", SHAPE_AND_PROGRESS)), bag)
    assert face is not None, bag.render()
    ring = next(e for e in face.walk() if e.id == "ring")
    deco = next(e for e in face.walk() if e.id == "deco")
    assert ring.resolved_antialias is True
    assert deco.resolved_antialias is True


# -- R3: `antialias:` on `text` is a build error -----------------------------

TEXT_CUSTOM_FONT = """  - id: t
    type: text
    value: time.clock
    format: "{:%H:%M}"
    font: font.clock
    color: palette.fg
    antialias: true
"""

TEXT_SYSTEM_FONT = """  - id: t
    type: text
    text: "12:00"
    font: FONT_MEDIUM
    color: palette.fg
    antialias: true
"""


def test_antialias_on_text_with_a_custom_font_names_that_font(write_design, bag):
    """The note must point at the actual font this element references, not a
    generic 'use fonts: instead'."""
    face = load(write_design(design("", TEXT_CUSTOM_FONT)), bag)
    assert face is None
    hits = [d for d in bag.errors if d.code == "text-antialias"]
    assert hits, bag.render()
    assert "not accepted on a 'text' element" in hits[0].message
    assert any("fonts: clock: antialias:" in note for note in hits[0].notes), hits[0].notes


def test_antialias_on_text_with_a_system_font_names_that_font(write_design, bag):
    face = load(write_design(design("", TEXT_SYSTEM_FONT)), bag)
    assert face is None
    hits = [d for d in bag.errors if d.code == "text-antialias"]
    assert hits, bag.render()
    assert any("FONT_MEDIUM" in note for note in hits[0].notes), hits[0].notes


def test_without_the_guard_antialias_on_text_would_build_silently(write_design, bag, monkeypatch):
    """Proves the guard is load-bearing: with `_reject_text_antialias` disarmed,
    the same design that test_antialias_on_text_with_a_custom_font_names_that_font
    rejects instead builds without a word -- the exact silent-gap shape
    CLAUDE.md warns this project has already shipped twice.
    """
    from wfb import ir

    monkeypatch.setattr(ir.Builder, "_reject_text_antialias", lambda self, node, element: None)
    face = load(write_design(design("", TEXT_CUSTOM_FONT)), bag)
    assert face is not None, bag.render()
    assert not any(d.code == "text-antialias" for d in bag.errors)


# -- R5: a font with no `antialias:` of its own follows the face default ----


def test_a_font_with_no_antialias_follows_the_face_default(write_design, bag):
    face = load(write_design(design("antialias: true\n", "")), bag)
    assert face is not None, bag.render()
    assert face.fonts["clock"].antialias is True


def test_a_fonts_own_antialias_wins_over_the_face_default(write_design, bag):
    head = HEAD.replace("size: 18%r\n", "size: 18%r\n    antialias: false\n")
    text = f"{head}antialias: true\nelements:\n{BACKGROUND}"
    face = load(write_design(text), bag)
    assert face is not None, bag.render()
    assert face.fonts["clock"].antialias is False


# -- R4: `wfb.icons.font_key` must incorporate anti-aliasing -----------------


def test_font_key_default_is_unchanged_by_the_new_parameter():
    """The default (`antialias=False`) must produce exactly the pre-existing
    key string, or every design that never mentions `antialias:` would rebake
    under a new resource name -- the golden-file stability this whole session
    is required to preserve."""
    heart = icons.CATALOG["heart"].codepoint
    length = Length.parse("8%r")
    assert icons.font_key(length, heart) == icons.font_key(length, heart, False)


def test_font_key_distinguishes_antialiasing():
    heart = icons.CATALOG["heart"].codepoint
    length = Length.parse("8%r")
    plain = icons.font_key(length, heart, False)
    smooth = icons.font_key(length, heart, True)
    assert plain != smooth
    assert plain == icons.font_key(length, heart)  # False is still the default


def test_two_icons_same_size_and_glyph_collide_without_the_antialias_key(write_design, bag, db):
    """Reproduces the bug R4 exists to prevent: two icons agreeing on `size:`
    and glyph but not on `antialias:` used to fold into one font resource,
    and the one built second would silently overwrite the sheet the other one
    needed -- shown here by calling the *pre-fix* two-argument form directly.
    """
    from wfb.emit.resources import icon_font_specs

    both = ICON.replace(
        "    color: palette.fg\n",
        "    color: palette.fg\n    antialias: false\n",
    ) + ICON.replace(
        "  - id: probe\n", "  - id: probe2\n"
    ).replace(
        "    color: palette.fg\n",
        "    color: palette.fg\n    antialias: true\n",
    )
    face = load(write_design(design("", both)), bag)
    assert face is not None, bag.render()
    device = db.get("fenix8solar47mm")

    # The fixed behaviour: two distinct resources, one per antialias setting.
    specs = icon_font_specs(face, device)
    assert len(specs) == 2, specs

    # The pre-fix behaviour, reproduced directly: calling font_key without the
    # antialias argument collapses both elements onto the same key.
    plain = next(e for e in face.walk() if e.id == "probe")
    smooth = next(e for e in face.walk() if e.id == "probe2")
    assert icons.font_key(plain.size, plain.codepoint) == icons.font_key(
        smooth.size, smooth.codepoint
    )
