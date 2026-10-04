"""`antialias:` -- the primitive half (`Dc.setAntiAlias` for `shape`/`progress`/
`graph`/`hands`).

`tests/test_antialias.py` covers the format surface and the font-baking half
Task A shipped: the top-level default, per-element inheritance, the `text`
rejection, and `wfb.icons.font_key`. This file covers what reads
`Element.resolved_antialias` on a primitive-drawing element
(`wfb.layout.is_antialiased_primitive`) and turns it
into a guarded `Dc.setAntiAlias` call --

* the guarded helper, named anything but `setAntiAlias`
  (`docs/research/probes/antialias/README.md` 3);
* where the calls land -- `onUpdate` (both branches), `onPartialUpdate`,
  and `renderStatic` (both its call sites);
* a face that never turns this on for a primitive-drawing element
  generates exactly what it did before this feature existed;
* `antialias-dither`, the suppressible 64-colour-palette lint.

Every guard below was watched fail before it was believed, the same
discipline `test_static.py` and `test_visibility.py` use.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from wfb.diagnostics import Bag, Severity
from tests.helpers import load_face as _face, with_resources

ROOT = Path(__file__).resolve().parent.parent

HEAD = """format: 2
face:
  id: 7f3c1e92-4a5b-4d81-9e6f-2b0c8d4a1f57
  name: Test
build:
  targets: [fenix8solar47mm, fenix8solar51mm, fr955]
resources:
  palette:
    bg: "#000000"
    fg: "#FFFFFF"
"""

BACKGROUND = """  background:
    type: rectangle
    at: {anchor: center}
    size: {width: 100%, height: 100%}
    color: color.bg
"""

RING = """  ring:
    type: circle
    filled: false
    at: {anchor: center}
    radius: 40%r
    thickness: 4px
    color: color.fg
"""


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


# -- nothing used means nothing emitted ----------------------------------


def test_no_antialias_anywhere_emits_nothing(write_design, db, tmp_path):
    """Neither `antialias:` used at all: no helper, no calls, no mentions."""
    design = f"{HEAD}elements:\n{BACKGROUND}{RING}"
    text = _view_text(design, write_design, db, tmp_path)
    assert "antialias" not in text.lower()
    assert "AntiAlias" not in text


def test_face_default_true_but_every_shape_overrides_back_to_false_emits_nothing(
    write_design, db, tmp_path
):
    """The other "nothing emitted" case: the face default is `true`, but nothing actually
    draws anti-aliased once every `shape`/`progress` element overrides it
    back.  `resolved_antialias` already folds the override in, so this must
    be indistinguishable from never mentioning `antialias:` at all."""
    design = (
        f"{HEAD}defaults: {{antialias: true}}\nelements:\n"
        + BACKGROUND.rstrip("\n") + "\n    antialias: false\n"
        + RING.rstrip("\n") + "\n    antialias: false\n"
    )
    text = _view_text(design, write_design, db, tmp_path)
    assert "antialias" not in text.lower()
    assert "AntiAlias" not in text


def test_a_face_with_nothing_antialiased_matches_a_design_that_never_mentions_the_key(
    write_design, db, tmp_path
):
    """The strongest form of "nothing used, nothing emitted": byte-identical output, not just "no mentions"."""
    plain = f"{HEAD}elements:\n{BACKGROUND}{RING}"
    explicit_false = f"{HEAD}defaults: {{antialias: false}}\nelements:\n{BACKGROUND}{RING}"
    assert (
        _view_text(plain, write_design, db, tmp_path)
        == _view_text(explicit_false, write_design, db, tmp_path)
    )


# -- the guarded helper ---------------------------------------------------


def test_the_helper_is_never_named_setantialias(write_design, db, tmp_path):
    """Probe 3: a same-named private method shadows Dc's own and `monkeyc`
    warns about it on every target.  Pinned here so nobody "simplifies" the
    name back."""
    design = f"{HEAD}defaults: {{antialias: true}}\nelements:\n{BACKGROUND}{RING}"
    text = _view_text(design, write_design, db, tmp_path)
    assert "function applyAntiAlias(dc as Dc, on as Boolean) as Void" in text
    assert "function setAntiAlias(" not in text


def test_the_helper_guards_with_has_setantialias(write_design, db, tmp_path):
    design = f"{HEAD}defaults: {{antialias: true}}\nelements:\n{BACKGROUND}{RING}"
    text = _view_text(design, write_design, db, tmp_path)
    assert "if (dc has :setAntiAlias) {" in text
    assert "dc.setAntiAlias(on);" in text


def test_the_helper_is_not_emitted_when_nothing_calls_it(write_design, db, tmp_path):
    design = f"{HEAD}elements:\n{BACKGROUND}{RING}"
    text = _view_text(design, write_design, db, tmp_path)
    assert "applyAntiAlias" not in text


# -- entry points and per-element overrides ------------------------------


def test_face_default_true_resets_in_onupdate_with_no_override_calls(
    write_design, db, tmp_path
):
    """Neither element overrides, so the only call is the one at the top of
    `onUpdate` -- nothing per element, since both already sit at the default."""
    design = f"{HEAD}defaults: {{antialias: true}}\nelements:\n{BACKGROUND}{RING}"
    text = _view_text(design, write_design, db, tmp_path)
    assert text.count("applyAntiAlias(dc, true);") == 1
    assert "applyAntiAlias(dc, false);" not in text
    on_update = text.split("function onUpdate(dc as Dc) as Void")[1].split("\n\n")[0]
    assert "applyAntiAlias(dc, true);" in on_update


def test_an_element_overriding_false_under_a_true_default_toggles_around_its_own_draw(
    write_design, db, tmp_path
):
    design = (
        f"{HEAD}defaults: {{antialias: true}}\nelements:\n"
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
        f"{HEAD}defaults: {{antialias: false}}\nelements:\n{BACKGROUND}"
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


HANDS = """resources:
  hand_sets:
    simple:
      hour:
        color: color.fg
        parts:
          - {type: polygon, points: [{dx: -3%r, dy: 6%r}, {dy: -44%r}, {dx: 3%r, dy: 6%r}]}
"""

def _draw_main_hands(view: str) -> str:
    """`drawMainHands`, whole: a hands draw method has blank lines between
    its hands, so the `"\\n\\n"` slice the other tests use would stop at the
    first one."""
    return view.split("private function drawMainHands")[1].split("\n    }\n")[0]


HANDS_ELEMENT = """  main_hands:
    type: hands
    set: simple
    at: {anchor: center}
"""


def test_a_hands_element_alone_turning_antialias_on_emits_the_helper_and_toggles(
    write_design, db, tmp_path
):
    """`type: hands` accepts `antialias:` and the lint counts it, so the
    "is the feature used at all" gate must count it too.  Watched fail first:
    with `PlacedHands` missing from `_antialias_default`, this design lints
    `antialias-dither` against `main_hands` yet emits no `applyAntiAlias` at
    all -- the key silently did nothing."""
    design = (
        f"{with_resources(HEAD, HANDS)}elements:\n{BACKGROUND}"
        + HANDS_ELEMENT
        + "    antialias: true\n"
        + "    lint: {allow: [antialias-dither], reason: test}\n"
    )
    text = _view_text(design, write_design, db, tmp_path)
    assert "function applyAntiAlias(dc as Dc, on as Boolean) as Void" in text
    draw_hands = _draw_main_hands(text)
    assert "applyAntiAlias(dc, true);" in draw_hands
    assert "applyAntiAlias(dc, false);" in draw_hands  # restored to the face default
    assert draw_hands.index("applyAntiAlias(dc, true);") < draw_hands.index("WfbGeom.fillRotated")
    on_update = text.split("function onUpdate(dc as Dc) as Void")[1].split("\n\n")[0]
    assert "applyAntiAlias(dc, false);" in on_update  # the face default, reset once
    draw_background = text.split("private function drawBackground")[1].split("\n\n")[0]
    assert "applyAntiAlias" not in draw_background


def test_a_hands_element_overriding_false_under_a_true_default_toggles(
    write_design, db, tmp_path
):
    """The other direction: every shape is soft, the hands stay crisp."""
    design = (
        f"{with_resources(HEAD, HANDS)}defaults: {{antialias: true}}\nelements:\n"
        + BACKGROUND.rstrip("\n")
        + "\n    lint: {allow: [antialias-dither], reason: test}\n"
        + HANDS_ELEMENT
        + "    antialias: false\n"
    )
    text = _view_text(design, write_design, db, tmp_path)
    draw_hands = _draw_main_hands(text)
    assert "applyAntiAlias(dc, false);" in draw_hands
    assert "applyAntiAlias(dc, true);" in draw_hands  # restored


def test_text_and_icon_never_emit_antialias_calls(write_design, db, tmp_path):
    """Only `shape` and `progress` draw primitives; `text`/`icon` draw
    glyphs, whose anti-aliasing is the font-baking half Task A already
    shipped, so their own draw methods must stay untouched even when the face
    default is `true`."""
    design = (
        f"{HEAD}defaults: {{antialias: true}}\nelements:\n{BACKGROUND}"
        "  clock:\n"
        "    type: text\n"
        '    text: "{time.clock:%H:%M}"\n'
        "    font: FONT_SMALL\n"
        "    at: {anchor: center}\n"
        "    color: color.fg\n"
        "  an_icon:\n"
        "    type: icon\n"
        "    icon: steps\n"
        "    at: {anchor: center, dy: 30%}\n"
        "    size: 20px\n"
        "    color: color.fg\n"
    )
    text = _view_text(design, write_design, db, tmp_path)
    draw_clock = text.split("private function drawClock")[1].split("\n\n")[0]
    draw_icon = text.split("private function drawAnIcon")[1].split("\n\n")[0]
    assert "AntiAlias" not in draw_clock
    assert "AntiAlias" not in draw_icon


def test_onpartialupdate_resets_the_face_default(write_design, db, tmp_path):
    design = (
        f"{HEAD}defaults: {{antialias: true}}\nelements:\n"
        + BACKGROUND
        + """  clock:
    type: text
    text: "{time.clock:%H:%M}"
    font: FONT_SMALL
    at: {anchor: center}
    color: color.fg
    sleep_update: true
"""
        + RING.rstrip("\n") + "\n    sleep_update: true\n"
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
        f"""{HEAD}defaults: {{antialias: true}}
static:
  backdrop:
    type: rectangle
    at: {{anchor: center}}
    size: {{width: 100%, height: 100%}}
    color: color.bg
    antialias: false
  bezel:
    type: circle
    filled: false
    at: {{anchor: center}}
    radius: 40%r
    thickness: 4px
    color: color.fg
    lint: {{allow: [antialias-dither], reason: "test"}}
elements:
  clock:
    type: text
    text: "{{time.clock:%H:%M}}"
    font: FONT_SMALL
    at: {{anchor: center}}
    color: color.fg
"""
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


# -- antialias-dither -----------------------------------------------------


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

    design = f"{HEAD}defaults: {{antialias: true}}\nelements:\n{BACKGROUND}{RING}"
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
        f"{HEAD}defaults: {{antialias: true}}\nelements:\n"
        + BACKGROUND.rstrip("\n")
        + '\n    lint: {allow: [antialias-dither], reason: "accepted tradeoff"}\n'
        + RING
    )
    resolved = _resolved(design, write_design, db)
    bag = Bag()
    lint.check_antialias_palette(resolved, bag)
    assert not [d for d in bag.items if d.code == "antialias-dither"], bag.render()


@pytest.mark.parametrize("kind", ["graph", "hands"])
def test_antialias_dither_counts_every_element_the_emitter_antialiases(kind, write_design, db):
    """A `graph` or `hands` element as the *only* anti-aliased one: the
    emitter toggles `Dc.setAntiAlias` around both, so the lint must see both.
    Watched fail first for `graph`: `check_antialias_palette` once kept its
    own tuple, which omitted `PlacedGraph`, while the emitter's omitted
    `PlacedHands` -- both now read `wfb.layout.is_antialiased_primitive`."""
    from wfb import lint

    element = {
        "graph": (
            """  soft:
    type: graph
    series: heart_rate
    range: 4h
    style: line
    color: color.fg
    at: {anchor: center}
    size: {width: 60%, height: 20%}
"""
        ),
        "hands": HANDS_ELEMENT.replace("main_hands", "soft"),
    }[kind]
    head = with_resources(HEAD, HANDS) if kind == "hands" else HEAD
    design = f"{head}elements:\n{BACKGROUND}{element}    antialias: true\n"
    resolved = _resolved(design, write_design, db)
    bag = Bag()
    lint.check_antialias_palette(resolved, bag)
    warnings = [d for d in bag.items if d.code == "antialias-dither"]
    assert len(warnings) == 1, bag.render()
    assert "soft" in warnings[0].notes[1]


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

    design = f"{HEAD}defaults: {{antialias: true}}\nelements:\n{BACKGROUND}{RING}"
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

DESIGN_DEFAULT_ON_NO_OVERRIDE = f"""{HEAD}defaults: {{antialias: true}}
elements:
{BACKGROUND.rstrip(chr(10))}
    lint: {{allow: [antialias-dither], reason: "test: default true, no overrides"}}
{RING}"""

DESIGN_BOTH_OVERRIDE_DIRECTIONS = f"""{HEAD}defaults: {{antialias: true}}
elements:
{BACKGROUND.rstrip(chr(10))}
    antialias: false
  soft_ring:
    type: circle
    filled: false
    at: {{anchor: center, dy: -20%}}
    radius: 20%r
    thickness: 4px
    color: color.fg
    lint: {{allow: [antialias-dither], reason: "test: true under true, no-op"}}
  crisp_ring:
    type: circle
    filled: false
    at: {{anchor: center, dy: 20%}}
    radius: 20%r
    thickness: 4px
    color: color.fg
    antialias: false
"""

DESIGN_STATIC = f"""{HEAD}defaults: {{antialias: true}}
static:
  backdrop:
    type: rectangle
    at: {{anchor: center}}
    size: {{width: 100%, height: 100%}}
    color: color.bg
    antialias: false
  bezel:
    type: circle
    filled: false
    at: {{anchor: center}}
    radius: 40%r
    thickness: 3px
    color: color.fg
    lint: {{allow: [antialias-dither], reason: "test: static subtree anti-aliased"}}
elements:
  clock:
    type: text
    text: "{{time.clock:%H:%M}}"
    font: FONT_NUMBER_MEDIUM
    at: {{anchor: center}}
    color: color.fg
"""

DESIGN_LOW_POWER = f"""{HEAD}defaults: {{antialias: true}}
elements:
{BACKGROUND.rstrip(chr(10))}
    antialias: false
  clock:
    type: text
    text: "{{time.clock:%H:%M}}"
    font: FONT_NUMBER_MEDIUM
    at: {{anchor: center}}
    color: color.fg
    sleep_update: true
  sleep_ring:
    type: circle
    filled: false
    at: {{anchor: center}}
    radius: 30%r
    thickness: 4px
    color: color.fg
    sleep_update: true
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
def test_antialias_scenarios_compile_warning_free(design, write_design, tmp_path, bag, db, toolchain):
    """Real `monkeyc`, all three targets, asserted against the bag rather than
    a proxy for it -- `wfb/build.py` turns each `WARNING:` line into a bag
    diagnostic (CLAUDE.md's own on_hold precedent for exactly this gap: every
    other test here inspects generated *text*, and text passing does not mean
    the real compiler is silent).
    """
    from wfb.build import build

    design_path = write_design(design)
    result = build(design_path, output=tmp_path / "build", bag=bag, db=db, toolchain=toolchain)
    assert result is not None, bag.render()
    assert result.products, "nothing was compiled"
    assert len(result.products) == 3, "this gate is about all three targets"
    complaints = [d for d in bag.items if d.severity.value in ("error", "warning")]
    assert not complaints, bag.render()
