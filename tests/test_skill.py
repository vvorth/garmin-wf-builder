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

ROOT = Path(__file__).resolve().parent.parent
#: The canonical, model-agnostic instructions.
SKILL = ROOT / "skills" / "watchface-builder.md"
#: A thin Claude Code adapter that points at them.
ADAPTER = ROOT / ".claude/skills/watchface-from-image/SKILL.md"


@pytest.fixture(scope="module")
def text() -> str:
    if not SKILL.exists():
        pytest.skip("the skill is not installed")
    return SKILL.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def adapter() -> str:
    if not ADAPTER.exists():
        pytest.skip("the Claude Code adapter is not installed")
    return ADAPTER.read_text(encoding="utf-8")


def yaml_blocks(text: str) -> list[str]:
    return re.findall(r"```yaml\n(.*?)```", text, re.S)


def test_the_skill_needs_no_frontmatter(text):
    """It has to be usable by a model with no harness conventions at all.

    Anything that only works because a particular runner parses a header is a
    portability bug, not a feature.
    """
    assert not text.startswith("---\n")


def test_the_adapter_points_at_the_canonical_instructions(adapter):
    """Two copies of a procedure drift.  The adapter must delegate, not restate."""
    assert "skills/watchface-builder.md" in adapter
    # If it starts restating the procedure, it has begun to drift.
    assert len(adapter.splitlines()) < 60, "the adapter is growing its own copy"


def test_the_adapter_declares_when_to_use_it(adapter):
    assert adapter.startswith("---\n")
    front = adapter.split("---", 2)[1]
    assert "name: watchface-from-image" in front
    # The description is what a model matches against, so it must name the
    # situation rather than the mechanism.
    assert "description:" in front and "watch face" in front.lower()


def test_it_bootstraps_the_environment_before_anything_else(text):
    """A portable skill cannot assume it starts anywhere in particular."""
    assert "wfb doctor" in text
    # doctor's three verdicts each need an instruction attached.
    for verdict in ("ready", "partial", "not ready"):
        assert verdict in text


def test_it_handles_a_model_that_cannot_see_images(text):
    """Not every model has vision, and one that lacks it must not pretend."""
    assert "cannot see images" in text


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
    """The reference card's `icon: heart # a | b | c` comment lists the whole
    catalogue.  If a name drifts from wfb/icons.py, this line rots silently."""
    line = next(l for l in text.splitlines() if "icon: heart" in l)
    listed = line.split("#", 1)[1]
    named = set(re.findall(r"[a-z_]+", listed))
    for name in named:
        assert icons.get(name) is not None, f"{name!r} in the skill's icon list is not in the catalogue"
    assert named == set(icons.names()), (
        f"the skill's icon comment ({named}) has drifted from the catalogue ({set(icons.names())})"
    )


def test_templates_it_tells_you_to_use_exist(text):
    for name in re.findall(r"wfb new [^\n]*-t (\w+)", text):
        assert (TEMPLATE_DIR / f"{name}.yaml").exists(), f"no template {name!r}"


def test_commands_it_names_are_real(text):
    """A skill that names a command that does not exist wastes a round and
    teaches the model to distrust the rest of the instructions."""
    from wfb.cli import _parser

    known = set(_parser()._subparsers._group_actions[0].choices)
    used = set(re.findall(r"(?:^|\s)wfb (\w+)", text))
    unknown = used - known
    assert not unknown, f"the skill names commands that do not exist: {unknown}"


def test_it_insists_on_the_feedback_loop(text):
    """The loop is what makes the output trustworthy rather than plausible.

    If these steps ever become optional the skill produces designs that look
    right and are not, which is the failure this whole approach exists to avoid.
    Matched loosely on purpose -- the wording may change, the insistence may not.
    """
    assert "wfb validate" in text
    assert "wfb preview" in text
    assert re.search(r"(do not skip|not optional|mandatory)", text, re.I), (
        "nothing in the skill makes validate and preview non-negotiable"
    )


def test_it_warns_against_pixel_offsets(text):
    """The one mistake the tools cannot catch: px is legal, and silently wrong
    on every device but the one it was written for."""
    assert "%r" in text
    assert re.search(r"never write a bare pixel offset", text, re.I)


def test_it_tells_the_model_not_to_invent_data_sources(text):
    """The other error the tools cannot catch: a real path bound to the wrong
    thing, or a plausible path that does not exist."""
    assert "wfb sources" in text
    assert re.search(r"never bind a data source that is not", text, re.I)
