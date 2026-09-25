"""Plan 19 A5: one view and one delegate serve every target, so nothing in
them may follow whichever device happens to come first.

`wfb.build` resolves each target once and `generate` reuses those faces;
every per-device need is decided over the whole build (`Guards`, the
icon-glyph union); and each shared source is emitted from every target and
compared, so a per-device fact leaking into one is a build error.
"""

from __future__ import annotations

import pytest

from wfb import lint
from wfb.availability import compute_guards
from wfb.build import build, load, resolve_all
from wfb.diagnostics import Bag
from wfb.emit import generate, monkeyc
from wfb.emit import project as project_mod

HEAD = """format: 1
face:
  id: 7f3c1e92-4a5b-4d81-9e6f-2b0c8d4a1f57
  name: Test
targets: [fenix8solar47mm, fr955]
palette:
  bg: "#000000"
  fg: "#FFFFFF"
elements:
  - id: background
    type: shape
    shape: rectangle
    at: {anchor: center}
    size: {width: 100%, height: 100%}
    color: palette.bg
"""

CLOCK = """  - id: clock
    type: text
    value: time.clock
    format: "{:%H:%M}"
    font: FONT_NUMBER_MEDIUM
    at: {anchor: center}
    color: palette.fg
"""

LOW_POWER = HEAD + CLOCK + "    modes: [active, low_power]\n"

MIXED = ["fenix847mm", "fr955"]  # AMOLED first: the old "device 0" trap


def _devices(db, ids):
    missing = [i for i in ids if i not in db.ids()]
    if missing:
        pytest.skip(f"not installed: {', '.join(missing)}")
    return [db.get(i) for i in ids]


def _resolved(write_design, db, text, ids):
    bag = Bag()
    face = load(write_design(text), bag)
    assert face is not None, bag.render()
    devices = _devices(db, ids)
    resolved, _ = resolve_all(face, devices, bag)
    return face, devices, resolved, bag


def test_generate_reuses_the_resolved_faces_it_is_given(write_design, db, tmp_path,
                                                        monkeypatch):
    face, devices, resolved, _ = _resolved(write_design, db, HEAD + CLOCK,
                                           ["fenix8solar47mm", "fr955"])

    def no_second_resolve(*args, **kwargs):
        raise AssertionError("generate resolved a device it was handed")

    monkeypatch.setattr(project_mod, "resolve", no_second_resolve)
    project = generate(face, devices, tmp_path, resolved=resolved)
    assert project.resolved == resolved
    assert not project.divergences


def test_partial_update_is_decided_over_every_target_not_the_first(write_design, db, tmp_path):
    """A `low_power` design with an AMOLED target first. The lint rejects
    this build (`partial-update`), so `generate` is called directly: before
    A5 the view took `onPartialUpdate` from device 0 alone, and fr955 --
    which runs it -- got none."""
    face, devices, resolved, _ = _resolved(write_design, db, LOW_POWER, MIXED)
    project = generate(face, devices, tmp_path, resolved=resolved)
    view = project.generated_text()["source/TestView.mc"]
    assert "function onPartialUpdate(" in view
    assert "function onPowerBudgetExceeded(" in view
    assert not project.divergences


@pytest.mark.parametrize("ids, expected", [
    (["fenix847mm"], True),
    (["fenix847mm", "fr955"], False),
    (["fr955"], False),
])
def test_compute_guards_partial_update_unsupported(write_design, db, ids, expected):
    bag = Bag()
    face = load(write_design(LOW_POWER), bag)
    assert face is not None, bag.render()
    guards = compute_guards(face, _devices(db, ids))
    assert guards.partial_update_unsupported is expected


def test_an_all_amoled_build_emits_no_partial_update(write_design, db, tmp_path):
    face, devices, resolved, _ = _resolved(write_design, db, LOW_POWER, ["fenix847mm"])
    view = generate(face, devices, tmp_path, resolved=resolved).generated_text()["source/TestView.mc"]
    assert "onPartialUpdate" not in view


def test_the_shared_view_names_no_device(write_design, db, tmp_path):
    face, devices, resolved, _ = _resolved(write_design, db, HEAD + CLOCK,
                                           ["fenix8solar47mm", "fr955"])
    view = generate(face, devices, tmp_path, resolved=resolved).generated_text()["source/TestView.mc"]
    assert "fenix8solar47mm" not in view
    assert "fr955" not in view


def test_a_per_device_fact_in_the_view_fails_the_build(write_design, db, tmp_path, monkeypatch):
    """Drive the divergence check red: a view that leaks its device id
    comes out differently per target, and the build refuses it."""
    real = monkeyc.emit_view

    def leaky(resolved, guards=None):
        source = real(resolved, guards)
        return monkeyc.SourceFile(source.path, source.text + f"// {resolved.device.id}\n")

    monkeypatch.setattr(monkeyc, "emit_view", leaky)
    path = write_design(HEAD + CLOCK)
    _devices(db, ["fenix8solar47mm", "fr955"])
    bag = Bag()
    result = build(path, output=tmp_path / "out", bag=bag, db=db, compile_prg=False)
    assert result is None
    error = next(d for d in bag.errors if d.code == "shared-source")
    assert "source/TestView.mc" in error.message
    assert "fenix8solar47mm" in error.message and "fr955" in error.message
    assert any("// fenix8solar47mm" in note for note in error.notes)


def test_the_same_build_passes_without_the_leak(write_design, db, tmp_path):
    path = write_design(HEAD + CLOCK)
    _devices(db, ["fenix8solar47mm", "fr955"])
    bag = Bag()
    result = build(path, output=tmp_path / "out", bag=bag, db=db, compile_prg=False)
    assert result is not None, bag.render()
    assert "shared-source" not in {d.code for d in bag.items}


@pytest.mark.parametrize("ids, noted", [
    (["fenix847mm", "fr955"], ["fr955"]),
    (["fenix847mm", "fenix8solar47mm", "fr955"], ["fenix8solar47mm", "fr955"]),
    (["fenix847mm"], None),
    (["fenix8solar47mm", "fr955"], None),
])
def test_a_mixed_display_build_notes_the_aod_code_on_mip_targets(write_design, db, ids, noted):
    _, _, resolved, _ = _resolved(write_design, db, HEAD + CLOCK, ids)
    bag = Bag()
    lint.check_shared_view_targets(resolved, bag)
    notes = [d for d in bag.items if d.code == "shared-view"]
    if noted is None:
        assert notes == []
        return
    assert len(notes) == 1
    assert notes[0].message.endswith(", ".join(noted))
    assert notes[0].severity.value == "note"
