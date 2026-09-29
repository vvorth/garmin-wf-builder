"""`wfb build --profile` (`wfb.emit.monkeyc.profile`): the active frame times
one entry per frame, drawn ``reps`` times, and draws the readings; the build
reports each entry's code from the `.prg.debug.xml`."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from wfb.build import method_code_sizes
from wfb.emit.monkeyc import profile as profile_mod

from tests.helpers import generate_for_targets

PROFILE_FACE = Path(__file__).resolve().parent.parent / "examples/features/profile/face.yaml"
GROUP_FIXTURE = Path(__file__).parent / "fixtures" / "outline_group" / "face.yaml"


def _files(path: Path, tmp_path: Path, profile: int | None):
    from wfb.build import load
    from wfb.devices import DeviceDatabase
    from wfb.diagnostics import Bag
    from wfb.emit import generate

    bag = Bag()
    face = load(path, bag)
    assert face is not None, bag.render()
    db = DeviceDatabase.discover()
    devices = [db.get(d) for d in face.targets if d in db.ids()]
    return generate(face, devices, tmp_path, profile=profile).files()


def _view(files) -> str:
    return next(body for name, body in files.items() if name.endswith("View.mc"))


def test_every_entry_is_timed_and_the_baseline_is_entry_0(tmp_path, db):
    view = _view(_files(GROUP_FIXTURE, tmp_path, 7))
    timed = re.findall(r"if \(_profNext == (\d+)\) \{\n\s+var t0 = System\.getTimer\(\);\n"
                       r"\s+for \(var r = 0; r < 7; r\+\+\)", view)
    count = int(re.search(r"_profMs as Array<Number> = \[([0, ]+)\]", view).group(1).count("0"))
    assert [int(i) for i in timed] == list(range(count))
    # the baseline times an empty loop and has no untimed branch
    baseline = view[view.index("if (_profNext == 0)"):view.index("if (_profNext == 1)")]
    assert "else" not in baseline and "draw" not in baseline


def test_a_group_ring_pass_is_an_entry_of_its_own(tmp_path, db):
    view = _view(_files(GROUP_FIXTURE, tmp_path, 7))
    assert "5 badge.ring" in view  # the field doc lists the entries by index
    ring = view[view.index("if (_profNext == 5)"):view.index("if (_profNext == 6)")]
    assert ring.count("ringDisc(") == 2 and ring.count("ringRate(") == 2  # timed, and not


def test_profiling_draws_static_content_live(tmp_path, db):
    """So a static element is timed like any other."""
    view = _view(_files(GROUP_FIXTURE, tmp_path, 7))
    assert "_staticBuffer" not in view and "renderStatic" not in view
    assert "drawPlate(dc);" in view


def test_the_layout_carries_one_anchor_per_entry(tmp_path, db):
    files = _files(GROUP_FIXTURE, tmp_path, 7)
    layout = files["source-fr955/Layout.mc"]
    view = _view(files)
    count = int(re.search(r"_profMs as Array<Number> = \[([0, ]+)\]", view).group(1).count("0"))
    for name in ("PROF_X", "PROF_Y", "PROF_LAYOUT"):
        values = re.search(rf"const {name} as Array<Number> = \[([^\]]*)\]", layout).group(1)
        assert len(values.split(",")) == count


def test_only_the_layout_on_screen_is_timed_and_shown(tmp_path, db):
    view = _view(_files(PROFILE_FACE, tmp_path, 10))
    assert "while (Layout.PROF_LAYOUT[next] != -1 && Layout.PROF_LAYOUT[next] != _configLayout)" \
        in view
    assert "Layout.PROF_LAYOUT[k] == _configLayout" in view


def test_without_profile_nothing_is_instrumented(tmp_path, db):
    view = _view(_files(GROUP_FIXTURE, tmp_path, None))
    assert "_prof" not in view and "PROF_" not in view and "getTimer" not in view


def test_method_code_sizes_reads_the_debug_xml(tmp_path):
    debug = tmp_path / "x.prg.debug.xml"
    debug.write_text(
        '<functionEntry accessMode="private" endPc="268440241" '
        'name="&lt;globals/FooView/&lt;&gt;drawDisc&gt;" parent="FooView" startPc="268440173">\n'
        '<functionEntry accessMode="public" name="&lt;init&gt;" parent="Palette">\n'
        '<functionEntry accessMode="public" endPc="20" name="&lt;init&gt;" parent="Rez" '
        'startPc="1">\n')
    assert method_code_sizes(debug) == {"FooView.drawDisc": 69, "Rez.<init>": 20}


def test_the_code_report_totals_each_layout(tmp_path, bag, db):
    from tests.helpers import resolve_design

    resolved = resolve_design(PROFILE_FACE, bag, db, "fr955")
    plan = profile_mod.plan_for(resolved, 10)
    view = f"{resolved.face.entry}View"
    sizes = {f"{view}.drawDiscPlain": 36, f"{view}.drawDiscRing1": 69,
             f"{view}.ringBadgeRing1Icon": 10, f"{view}.ringBadgeRing1Value": 20}
    lines = profile_mod.code_report(plan, resolved.face, sizes)
    assert any(re.fullmatch(r"disc_ring1\s+69 B", line) for line in lines)
    assert any(re.fullmatch(r"badge_ring1\.ring\s+30 B", line) for line in lines)
    assert any(re.fullmatch(r"layout plain\s+36 B", line) for line in lines)


@pytest.mark.slow
def test_the_profile_face_compiles_profiled_warning_free(db, tmp_path, toolchain):
    from wfb.build import build as real_build
    from wfb.diagnostics import Bag

    bag = Bag()
    result = real_build(PROFILE_FACE, output=tmp_path, bag=bag, db=db, toolchain=toolchain,
                        profile=10)
    assert result is not None, bag.render()
    assert bag.ok(), bag.render()
    assert not [d for d in bag.items if d.severity.value == "warning"], bag.render()
