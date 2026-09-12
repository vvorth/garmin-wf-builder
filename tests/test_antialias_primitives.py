"""`antialias:` -- the primitive half (`Dc.setAntiAlias` for `shape`/`progress`).

`tests/test_antialias.py` covers the format surface and the font-baking half
Task A shipped: the top-level default, per-element inheritance, the `text`
rejection, and `wfb.icons.font_key`. This file covers what reads
`Element.resolved_antialias` on a `shape` or `progress` element and turns it
into a guarded `Dc.setAntiAlias` call --

* R1: the guarded helper, named anything but `setAntiAlias`
  (`docs/research/probes/antialias/README.md` 3);
* R2: where the calls land -- `onUpdate` (both branches), `onPartialUpdate`,
  and `renderStatic` (both its call sites);
* R3: a face that never turns this on for a `shape`/`progress` element
  generates exactly what it did before this feature existed;
* R4: `antialias-dither`, the suppressible 64-colour-palette lint.

Every guard below was watched fail before it was believed, the same
discipline `test_static.py` and `test_visibility.py` use.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.test_diagnostics import load
from wfb.diagnostics import Bag, Severity

ROOT = Path(__file__).resolve().parent.parent

HEAD = """format: 1
face:
  id: 7f3c1e92-4a5b-4d81-9e6f-2b0c8d4a1f57
  name: Test
targets: [fenix8solar47mm, fenix8solar51mm, fr955]
palette:
  bg: "#000000"
  fg: "#FFFFFF"
"""

BACKGROUND = """  - id: background
    type: shape
    shape: rectangle
    at: {anchor: center}
    size: {width: 100%, height: 100%}
    color: palette.bg
"""

RING = """  - id: ring
    type: shape
    shape: circle
    filled: false
    at: {anchor: center}
    radius: 40%r
    thickness: 4px
    color: palette.fg
"""


def _face(text, write_design, bag):
    face = load(write_design(text), bag)
    assert face is not None, bag.render()
    return face


def _view_text(text, write_design, db, tmp_path):
    """The generated `<Entry>View.mc` text for one design, one build."""
    from wfb.emit import generate
    from wfb.emit.resources import bake_fonts

    face = _face(text, write_design, Bag())
    devices = [db.get(d) for d in face.targets if d in db.ids()]
    assert len(devices) == 3, "this gate is about all three targets"
    baked = {d.id: bake_fonts(face, d) for d in devices}
    files = generate(face, devices, tmp_path, baked).files()
    (view_path,) = [p for p in files if p.endswith("View.mc")]
    return files[view_path]


# -- R3: nothing used means nothing emitted ----------------------------------


def test_no_antialias_anywhere_emits_nothing(write_design, db, tmp_path):
    """Neither `antialias:` used at all: no helper, no calls, no mentions."""
    design = f"{HEAD}elements:\n{BACKGROUND}{RING}"
    text = _view_text(design, write_design, db, tmp_path)
    assert "antialias" not in text.lower()
    assert "AntiAlias" not in text


def test_face_default_true_but_every_shape_overrides_back_to_false_emits_nothing(
    write_design, db, tmp_path
):
    """R3's other zero case: the face default is `true`, but nothing actually
    draws anti-aliased once every `shape`/`progress` element overrides it
    back.  `resolved_antialias` already folds the override in, so this must
    be indistinguishable from never mentioning `antialias:` at all."""
    design = (
        f"{HEAD}antialias: true\nelements:\n"
        + BACKGROUND.rstrip("\n") + "\n    antialias: false\n"
        + RING.rstrip("\n") + "\n    antialias: false\n"
    )
    text = _view_text(design, write_design, db, tmp_path)
    assert "antialias" not in text.lower()
    assert "AntiAlias" not in text


def test_a_face_with_nothing_antialiased_matches_a_design_that_never_mentions_the_key(
    write_design, db, tmp_path
):
    """The strongest form of R3: byte-identical output, not just "no mentions"."""
    plain = f"{HEAD}elements:\n{BACKGROUND}{RING}"
    explicit_false = f"{HEAD}antialias: false\nelements:\n{BACKGROUND}{RING}"
    assert (
        _view_text(plain, write_design, db, tmp_path)
        == _view_text(explicit_false, write_design, db, tmp_path)
    )


# -- R1: the guarded helper ---------------------------------------------------


def test_the_helper_is_never_named_setantialias(write_design, db, tmp_path):
    """Probe 3: a same-named private method shadows Dc's own and `monkeyc`
    warns about it on every target.  Pinned here so nobody "simplifies" the
    name back."""
    design = f"{HEAD}antialias: true\nelements:\n{BACKGROUND}{RING}"
    text = _view_text(design, write_design, db, tmp_path)
    assert "function applyAntiAlias(dc as Dc, on as Boolean) as Void" in text
    assert "function setAntiAlias(" not in text


def test_the_helper_guards_with_has_setantialias(write_design, db, tmp_path):
    design = f"{HEAD}antialias: true\nelements:\n{BACKGROUND}{RING}"
    text = _view_text(design, write_design, db, tmp_path)
    assert "if (dc has :setAntiAlias) {" in text
    assert "dc.setAntiAlias(on);" in text


def test_the_helper_is_not_emitted_when_nothing_calls_it(write_design, db, tmp_path):
    design = f"{HEAD}elements:\n{BACKGROUND}{RING}"
    text = _view_text(design, write_design, db, tmp_path)
    assert "applyAntiAlias" not in text


# -- R2: entry points and per-element overrides ------------------------------


def test_face_default_true_resets_in_onupdate_with_no_override_calls(
    write_design, db, tmp_path
):
    """Neither element overrides, so the only call is the one at the top of
    `onUpdate` -- nothing per element, since both already sit at the default."""
    design = f"{HEAD}antialias: true\nelements:\n{BACKGROUND}{RING}"
    text = _view_text(design, write_design, db, tmp_path)
    assert text.count("applyAntiAlias(dc, true);") == 1
    assert "applyAntiAlias(dc, false);" not in text
    on_update = text.split("function onUpdate(dc as Dc) as Void")[1].split("\n\n")[0]
    assert "applyAntiAlias(dc, true);" in on_update


def test_an_element_overriding_false_under_a_true_default_toggles_around_its_own_draw(
    write_design, db, tmp_path
):
    design = (
        f"{HEAD}antialias: true\nelements:\n"
        + BACKGROUND.rstrip("\n") + "\n    antialias: false\n"
        + RING
    )
    text = _view_text(design, write_design, db, tmp_path)
    draw_background = text.split("private function drawBackground")[1].split("\n\n")[0]
    assert "applyAntiAlias(dc, false);" in draw_background
    assert "applyAntiAlias(dc, true);" in draw_background  # restored
    draw_ring = text.split("private function drawRing")[1].split("\n\n")[0]
    assert "applyAntiAlias" not in draw_ring  # already at the default


def test_an_element_overriding_true_under_a_false_default_toggles_around_its_own_draw(
    write_design, db, tmp_path
):
    design = (
        f"{HEAD}antialias: false\nelements:\n{BACKGROUND}"
        + RING.rstrip("\n") + "\n    antialias: true\n"
        + "    lint: {allow: [antialias-dither], reason: test}\n"
    )
    text = _view_text(design, write_design, db, tmp_path)
    draw_background = text.split("private function drawBackground")[1].split("\n\n")[0]
    assert "applyAntiAlias" not in draw_background
    draw_ring = text.split("private function drawRing")[1].split("\n\n")[0]
    assert "applyAntiAlias(dc, true);" in draw_ring
    assert "applyAntiAlias(dc, false);" in draw_ring  # restored to the face default
    on_update = text.split("function onUpdate(dc as Dc) as Void")[1].split("\n\n")[0]
    assert "applyAntiAlias(dc, false);" in on_update  # the face default, reset once


def test_text_and_icon_never_emit_antialias_calls(write_design, db, tmp_path):
    """Only `shape` and `progress` draw primitives; `text`/`icon` draw
    glyphs, whose anti-aliasing is the font-baking half Task A already
    shipped, so their own draw methods must stay untouched even when the face
    default is `true`."""
    design = (
        f"{HEAD}antialias: true\nelements:\n{BACKGROUND}"
        "  - id: clock\n"
        "    type: text\n"
        "    value: time.clock\n"
        '    format: "{:%H:%M}"\n'
        "    font: FONT_SMALL\n"
        "    at: {anchor: center}\n"
        "    color: palette.fg\n"
        "  - id: an_icon\n"
        "    type: icon\n"
        "    icon: steps\n"
        "    at: {anchor: center, dy: 30%}\n"
        "    size: 20px\n"
        "    color: palette.fg\n"
    )
    text = _view_text(design, write_design, db, tmp_path)
    draw_clock = text.split("private function drawClock")[1].split("\n\n")[0]
    draw_icon = text.split("private function drawAnIcon")[1].split("\n\n")[0]
    assert "AntiAlias" not in draw_clock
    assert "AntiAlias" not in draw_icon


def test_onpartialupdate_resets_the_face_default(write_design, db, tmp_path):
    design = (
        f"{HEAD}antialias: true\nelements:\n"
        + BACKGROUND.rstrip("\n") + "\n    modes: [active]\n"
        + "  - id: clock\n"
        "    type: text\n"
        "    value: time.clock\n"
        '    format: "{:%H:%M}"\n'
        "    font: FONT_SMALL\n"
        "    at: {anchor: center}\n"
        "    color: palette.fg\n"
        "    modes: [active, low_power]\n"
        + RING.rstrip("\n") + "\n    modes: [low_power]\n"
        "    lint: {allow: [antialias-dither], reason: test}\n"
    )
    text = _view_text(design, write_design, db, tmp_path)
    assert "function onPartialUpdate(dc as Dc) as Void" in text
    partial = text.split("function onPartialUpdate(dc as Dc) as Void")[1]
    assert "applyAntiAlias(dc, true);" in partial.split("\n\n")[0]


def test_renderstatic_resets_the_face_default_once_for_both_call_sites(
    write_design, db, tmp_path
):
    design = (
        f"{HEAD}antialias: true\nstatic:\n"
        "  backdrop:\n"
        "    type: shape\n"
        "    shape: rectangle\n"
        "    at: {anchor: center}\n"
        "    size: {width: 100%, height: 100%}\n"
        "    color: palette.bg\n"
        "    antialias: false\n"
        "  bezel:\n"
        "    type: shape\n"
        "    shape: circle\n"
        "    filled: false\n"
        "    at: {anchor: center}\n"
        "    radius: 40%r\n"
        "    thickness: 4px\n"
        "    color: palette.fg\n"
        '    lint: {allow: [antialias-dither], reason: "test"}\n'
        "elements:\n"
        "  clock:\n"
        "    type: text\n"
        "    value: time.clock\n"
        '    format: "{:%H:%M}"\n'
        "    font: FONT_SMALL\n"
        "    at: {anchor: center}\n"
        "    color: palette.fg\n"
    )
    text = _view_text(design, write_design, db, tmp_path)
    render_static = text.split("private function renderStatic")[1].split(
        "private function draw"
    )[0]
    assert render_static.count("applyAntiAlias(dc, true);") == 1
    draw_backdrop = text.split("private function drawBackdrop")[1].split("\n\n")[0]
    assert "applyAntiAlias(dc, false);" in draw_backdrop
    assert "applyAntiAlias(dc, true);" in draw_backdrop
    draw_bezel = text.split("private function drawBezel")[1].split("\n\n")[0]
    assert "applyAntiAlias" not in draw_bezel  # inherits the default, no toggle


# -- R4: antialias-dither -----------------------------------------------------


def _resolved(text, write_design, db, device_id="fenix8solar47mm"):
    from wfb.emit.resources import bake_fonts
    from wfb.layout import resolve

    face = _face(text, write_design, Bag())
    device = db.get(device_id)
    return resolve(face, device, bake_fonts(face, device))


def test_antialias_dither_fires_on_a_64_colour_device(write_design, db):
    """Watched fail first: strip the `lint: {allow: [...]}` line and the
    warning appears -- the unsuppressed shape below the comment shows it."""
    from wfb import lint

    design = f"{HEAD}antialias: true\nelements:\n{BACKGROUND}{RING}"
    resolved = _resolved(design, write_design, db)
    assert resolved.device.display_colors == 64
    bag = Bag()
    lint.check_antialias_palette(resolved, bag)
    warnings = [d for d in bag.items if d.code == "antialias-dither"]
    assert len(warnings) == 1, bag.render()
    assert warnings[0].severity == Severity.WARNING
    assert "ring" in warnings[0].notes[1] or "background" in warnings[0].notes[1]


def test_antialias_dither_is_suppressible(write_design, db):
    """The same design as above, with the real `lint: {allow: [...]}}` an
    author would write -- the warning must vanish, not merely downgrade."""
    from wfb import lint

    design = (
        f"{HEAD}antialias: true\nelements:\n"
        + BACKGROUND.rstrip("\n")
        + '\n    lint: {allow: [antialias-dither], reason: "accepted tradeoff"}\n'
        + RING
    )
    resolved = _resolved(design, write_design, db)
    bag = Bag()
    lint.check_antialias_palette(resolved, bag)
    assert not [d for d in bag.items if d.code == "antialias-dither"], bag.render()


def test_antialias_dither_does_not_fire_when_nothing_is_antialiased(write_design, db):
    from wfb import lint

    design = f"{HEAD}elements:\n{BACKGROUND}{RING}"
    resolved = _resolved(design, write_design, db)
    bag = Bag()
    lint.check_antialias_palette(resolved, bag)
    assert not [d for d in bag.items if d.code == "antialias-dither"], bag.render()


def test_antialias_dither_does_not_fire_on_a_non_64_colour_device(write_design, db, monkeypatch):
    from wfb import lint
    from wfb.devices import Device

    design = f"{HEAD}antialias: true\nelements:\n{BACKGROUND}{RING}"
    resolved = _resolved(design, write_design, db)
    monkeypatch.setattr(Device, "display_colors", property(lambda self: 256))
    bag = Bag()
    lint.check_antialias_palette(resolved, bag)
    assert not [d for d in bag.items if d.code == "antialias-dither"], bag.render()


def test_antialias_dither_is_registered_as_suppressible(write_design):
    """A guard against the exact Bug 1 shape CLAUDE.md records twice already:
    a code advertised as suppressible that never actually routes through
    `_emit`."""
    from wfb import lint

    assert "antialias-dither" in lint.SUPPRESSIBLE
    assert "antialias-dither" in lint.ALL_CODES


# -- real toolchain: warning-free, several scenarios in one pass ------------

DESIGN_DEFAULT_ON_NO_OVERRIDE = f"""{HEAD}antialias: true
elements:
{BACKGROUND.rstrip(chr(10))}
    lint: {{allow: [antialias-dither], reason: "test: default true, no overrides"}}
{RING}"""

DESIGN_BOTH_OVERRIDE_DIRECTIONS = f"""{HEAD}antialias: true
elements:
{BACKGROUND.rstrip(chr(10))}
    antialias: false
  - id: soft_ring
    type: shape
    shape: circle
    filled: false
    at: {{anchor: center, dy: -20%}}
    radius: 20%r
    thickness: 4px
    color: palette.fg
    lint: {{allow: [antialias-dither], reason: "test: true under true, no-op"}}
  - id: crisp_ring
    type: shape
    shape: circle
    filled: false
    at: {{anchor: center, dy: 20%}}
    radius: 20%r
    thickness: 4px
    color: palette.fg
    antialias: false
"""

DESIGN_STATIC = f"""{HEAD}antialias: true
static:
  backdrop:
    type: shape
    shape: rectangle
    at: {{anchor: center}}
    size: {{width: 100%, height: 100%}}
    color: palette.bg
    antialias: false
  bezel:
    type: shape
    shape: circle
    filled: false
    at: {{anchor: center}}
    radius: 40%r
    thickness: 3px
    color: palette.fg
    lint: {{allow: [antialias-dither], reason: "test: static subtree anti-aliased"}}
elements:
  clock:
    type: text
    value: time.clock
    format: "{{:%H:%M}}"
    font: FONT_NUMBER_MEDIUM
    at: {{anchor: center}}
    color: palette.fg
"""

DESIGN_LOW_POWER = f"""{HEAD}antialias: true
elements:
{BACKGROUND.rstrip(chr(10))}
    antialias: false
    modes: [active]
  - id: clock
    type: text
    value: time.clock
    format: "{{:%H:%M}}"
    font: FONT_NUMBER_MEDIUM
    at: {{anchor: center}}
    color: palette.fg
    modes: [active, low_power]
  - id: sleep_ring
    type: shape
    shape: circle
    filled: false
    at: {{anchor: center}}
    radius: 30%r
    thickness: 4px
    color: palette.fg
    modes: [low_power]
    lint: {{allow: [antialias-dither], reason: "test: low_power element exercises onPartialUpdate"}}
"""


@pytest.mark.slow
@pytest.mark.parametrize(
    "design",
    [
        DESIGN_DEFAULT_ON_NO_OVERRIDE,
        DESIGN_BOTH_OVERRIDE_DIRECTIONS,
        DESIGN_STATIC,
        DESIGN_LOW_POWER,
    ],
    ids=["default-on", "both-override-directions", "static-subtree", "low-power"],
)
def test_antialias_scenarios_compile_warning_free(design, write_design, tmp_path, bag, db):
    """Real `monkeyc`, all three targets, asserted against the bag rather than
    a proxy for it -- `wfb/build.py` turns each `WARNING:` line into a bag
    diagnostic (CLAUDE.md's own on_hold precedent for exactly this gap: every
    other test here inspects generated *text*, and text passing does not mean
    the real compiler is silent).
    """
    from wfb.build import Toolchain, build

    toolchain = Toolchain.discover()
    if toolchain is None or not toolchain.key.exists():
        pytest.skip("no Connect IQ SDK or developer key")
    design_path = write_design(design)
    result = build(design_path, output=tmp_path / "build", bag=bag, db=db, toolchain=toolchain)
    assert result is not None, bag.render()
    assert result.products, "nothing was compiled"
    assert len(result.products) == 3, "this gate is about all three targets"
    complaints = [d for d in bag.items if d.severity.value in ("error", "warning")]
    assert not complaints, bag.render()
