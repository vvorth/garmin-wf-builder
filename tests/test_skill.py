"""The `watchface-from-image` skill.

A skill is instructions a model follows without supervision, so the failure mode
is silent: a wrong command or an invalid example produces a confidently wrong
design.  These tests keep the skill honest against the tool it drives.
"""

from __future__ import annotations

import re
import uuid
from pathlib import Path

import pytest

from tests.test_diagnostics import load
from wfb import icons, lint
from wfb.cli import TEMPLATE_DIR
from wfb.emit.resources import bake_fonts
from wfb.ir import SYSTEM_FONTS
from wfb.layout import resolve

SKILL = Path(__file__).resolve().parent.parent / ".claude/skills/watchface-from-image/SKILL.md"


@pytest.fixture(scope="module")
def text() -> str:
    if not SKILL.exists():
        pytest.skip("the skill is not installed")
    return SKILL.read_text(encoding="utf-8")


def yaml_blocks(text: str) -> list[str]:
    return re.findall(r"```yaml\n(.*?)```", text, re.S)


def test_frontmatter_is_present_and_describes_when_to_use(text):
    assert text.startswith("---\n")
    front = text.split("---", 2)[1]
    assert "name: watchface-from-image" in front
    # The description is what a model matches against, so it has to name the
    # situation rather than the mechanism.
    assert "description:" in front
    assert "watch face" in front.lower()


def test_the_reference_card_is_a_valid_design(text, tmp_path, bag, db):
    """Anyone following the skill copies this block, so it must actually work."""
    card = next(b for b in yaml_blocks(text) if "format: 1" in b and "elements:" in b)
    # The fonts: block references an asset the reader supplies; drop it as an
    # author would when using built-in fonts only.
    card = re.sub(r"fonts:.*?\n\nelements:", "elements:", card, flags=re.S)
    card = card.replace("<uuid>", str(uuid.uuid4()))

    design = tmp_path / "card.yaml"
    design.write_text(card, encoding="utf-8")
    face = load(design, bag)
    assert face is not None, bag.render()
    lint.check_permissions(face, bag)
    for device_id in face.targets:
        if device_id in db.ids():
            device = db.get(device_id)
            resolve(face, device, bake_fonts(face, device, device.minor_radius))
    assert bag.ok(), bag.render()


def test_every_font_the_card_names_exists(text):
    for name in re.findall(r"\b(FONT_[A-Z_]+)\b", text):
        assert name in SYSTEM_FONTS, f"{name} is not a system font"


def test_every_icon_the_card_names_exists(text):
    line = next(l for l in text.splitlines() if "icon: heart" in l)
    named = re.findall(r"\b(heart|steps|flame)\b", line)
    for name in named:
        assert icons.get(name) is not None


def test_templates_it_tells_you_to_use_exist(text):
    for name in re.findall(r"wfb new [^\n]*-t (\w+)", text):
        assert (TEMPLATE_DIR / f"{name}.yaml").exists(), f"no template {name!r}"


def test_commands_it_names_are_real(text):
    """A skill that tells a model to run a command that does not exist wastes a
    round and teaches it to distrust the instructions."""
    from wfb.cli import _parser

    known = set(_parser()._subparsers._group_actions[0].choices)
    used = set(re.findall(r"(?:^|\s)wfb (\w+)", text))
    unknown = used - known - {"schema"}
    assert not unknown, f"the skill names commands that do not exist: {unknown}"


def test_it_insists_on_the_feedback_loop(text):
    """The loop is what makes the output trustworthy rather than plausible.

    If these steps ever become optional the skill produces designs that look
    right and are not, which is the failure this whole approach exists to avoid.
    """
    assert "wfb validate" in text
    assert "wfb preview" in text
    assert "not optional" in text.lower()


def test_it_warns_against_pixel_offsets(text):
    """The one mistake the compiler cannot catch: px is legal and wrong."""
    assert "%r" in text
    assert re.search(r"[Nn]ever write a bare pixel offset", text)


def test_it_tells_the_model_not_to_invent_data_sources(text):
    assert "wfb sources" in text
    assert re.search(r"[Nn]ever bind a data source that is not in", text)
