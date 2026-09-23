"""The command line, and the environment check an unfamiliar caller starts with."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
ENTRY = ROOT / "wfb.py"


def run(*args: str, cwd: Path | None = None, python: str | None = None):
    """Invoke the entry point the way an outside caller would: by path."""
    return subprocess.run(
        [python or sys.executable, str(ENTRY), *args],
        capture_output=True, text=True, cwd=str(cwd or ROOT), check=False,
    )


def test_doctor_reports_a_working_environment(db):
    result = run("doctor")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "ready" in result.stdout


def test_doctor_names_what_is_missing_rather_than_failing_obscurely(tmp_path):
    """An unfamiliar caller's first command has to explain itself."""
    import os

    env = dict(os.environ, WFB_DEVICES=str(tmp_path / "nothing-here"), HOME=str(tmp_path))
    env.pop("CIQ_SDK", None)
    result = subprocess.run(
        [sys.executable, str(ENTRY), "doctor"],
        capture_output=True, text=True, env=env, cwd=str(ROOT), check=False,
    )
    assert result.returncode == 1
    assert "not ready" in result.stdout
    # It must say *why* the devices cannot simply be downloaded, or the caller
    # will burn a round trying.
    assert "401" in result.stdout
    assert "Connect IQ SDK" in result.stdout


def test_doctor_tells_a_container_user_to_mount_the_fonts(tmp_path):
    """`vendor/` never reaches the image (.dockerignore), so inside the
    container the host advice -- copy into vendor/fonts/ -- cannot work; the
    only way in is a mount at $WFB_FONTS.  On the host the advice is unchanged.
    (conftest sets WFB_NO_GARMIN_FONTS=1, so no Garmin fonts are found here.)"""
    import os

    def doctor(**extra):
        env = dict(os.environ, WFB_FONTS=str(tmp_path / "fonts"))
        env.pop("WFB_CONTAINER", None)
        env.update(extra)
        return subprocess.run(
            [sys.executable, str(ENTRY), "doctor"],
            capture_output=True, text=True, env=env, cwd=str(ROOT), check=False,
        ).stdout

    in_container = doctor(WFB_CONTAINER="1")
    assert f"-v <SDK Manager's Fonts dir>:{tmp_path / 'fonts'}:ro" in in_container
    assert "vendor/fonts/" not in in_container

    on_host = doctor()
    assert "vendor/fonts/" in on_host
    assert ":ro" not in on_host


def test_the_entry_point_works_from_an_unrelated_directory(tmp_path, db):
    """The commonest way to reach this tool is an absolute path from elsewhere."""
    result = run("devices", cwd=tmp_path)
    assert result.returncode == 0, result.stderr
    assert "fenix8solar47mm" in result.stdout


def test_the_entry_point_finds_its_own_interpreter(tmp_path, db):
    """`python3 wfb.py` must work even when that python lacks the dependencies.

    An arbitrary agent reaches for whatever python is on PATH; making that work
    is cheaper than explaining virtualenvs in every set of instructions.
    """
    bare = "/usr/bin/python3"
    if not Path(bare).exists():
        pytest.skip("no system python to test against")
    probe = subprocess.run(
        [bare, "-c", "import ruamel.yaml"], capture_output=True, check=False
    )
    if probe.returncode == 0:
        pytest.skip("the system python already has the dependencies")
    result = run("devices", cwd=tmp_path, python=bare)
    assert result.returncode == 0, result.stderr
    assert "fenix8solar47mm" in result.stdout


def test_new_lists_its_templates():
    result = run("new", "--list")
    assert result.returncode == 0
    assert "dashboard" in result.stdout and "minimal" in result.stdout


def test_new_refuses_to_overwrite(tmp_path):
    (tmp_path / "taken.yaml").write_text("existing", encoding="utf-8")
    result = run("new", "Taken", "-o", str(tmp_path / "taken.yaml"))
    assert result.returncode == 1
    assert "already exists" in result.stderr
    assert (tmp_path / "taken.yaml").read_text(encoding="utf-8") == "existing"


def test_new_gives_every_face_its_own_id(tmp_path):
    """Two faces sharing an id are one app to the watch: installing the second
    replaces the first."""
    import re

    ids = []
    for name in ("One", "Two"):
        path = tmp_path / f"{name}.yaml"
        assert run("new", name, "-o", str(path)).returncode == 0
        ids.append(re.search(r"id: (\S+)", path.read_text(encoding="utf-8")).group(1))
    assert ids[0] != ids[1]
    assert "__UUID__" not in ids


def test_schema_path_points_at_a_real_file():
    result = run("schema", "--path")
    assert result.returncode == 0
    assert Path(result.stdout.strip()).exists()


# -- `wfb fonts` ------------------------------------------------------------


def _header_line(stdout: str, device_id: str) -> str:
    """The one line in ``stdout`` that starts a device's own paragraph --
    ``"<id> (...)"`` -- never a mention of the id somewhere inside another
    device's data (a file stem, a face name, ...)."""
    for line in stdout.splitlines():
        if line.startswith(f"{device_id} ("):
            return line
    raise AssertionError(f"no header line for {device_id!r} in:\n{stdout}")


def _device_block(stdout: str, device_id: str) -> str:
    """The lines of ``stdout`` from a device's own header up to (not
    including) the next blank line -- one device's paragraph in the summary
    view, isolated so an assertion cannot accidentally match a sibling
    device's block instead."""
    lines = stdout.splitlines()
    start = next(i for i, line in enumerate(lines) if line.startswith(f"{device_id} ("))
    end = next((i for i in range(start + 1, len(lines)) if not lines[i].strip()), len(lines))
    return "\n".join(lines[start:end])


def test_fonts_summary_lists_every_device_with_its_own_gates(db, device):
    """Every installed id appears, and the golden device's own block -- not
    just the whole output -- names one of its real scalable faces alongside
    a `vector text:` line naming `drawRadialText`.  A bare `"scalable" in
    stdout` check would also pass on a `scalable: none` line, so this reads
    the actual face name and the actual gate name out of that one block."""
    result = run("fonts", "--color", "never")
    assert result.returncode == 0, result.stderr
    for device_id in db.ids():
        assert _header_line(result.stdout, device_id)

    block = _device_block(result.stdout, device.id)
    assert "vector text:" in block
    assert "drawRadialText" in block
    assert any(face in block for face in device.scalable_faces)


def test_fonts_detailed_positional_shows_only_that_device(db, device):
    result = run("fonts", device.id, "--color", "never")
    assert result.returncode == 0, result.stderr
    assert "Scalable (vector) fonts" in result.stdout
    for face in device.scalable_faces:
        assert face in result.stdout
    for metric in device.system_fonts.values():
        assert metric.symbol in result.stdout
    for other_id in db.ids():
        if other_id != device.id:
            assert f"{other_id} (" not in result.stdout


def test_fonts_dash_d_shows_only_that_device(db, device):
    """The old version of this test only asserted a face name the summary
    view also prints, so it would have passed even with `-d` silently
    ignored.  Asserting the detailed-only marker and the absence of any
    other device's header proves `-d` actually selected the detailed view
    for the right device."""
    result = run("fonts", "-d", device.id, "--color", "never")
    assert result.returncode == 0, result.stderr
    assert "Scalable (vector) fonts" in result.stdout
    for face in device.scalable_faces:
        assert face in result.stdout
    for other_id in db.ids():
        if other_id != device.id:
            assert f"{other_id} (" not in result.stdout


def test_fonts_positional_and_dash_d_both_print(db, device):
    others = [d for d in db.ids() if d != device.id]
    if not others:
        pytest.skip("only one device installed")
    other_id = others[0]
    result = run("fonts", device.id, "-d", other_id, "--color", "never")
    assert result.returncode == 0, result.stderr
    assert _header_line(result.stdout, device.id)
    assert _header_line(result.stdout, other_id)


def test_fonts_duplicate_device_name_prints_once(device):
    result = run("fonts", device.id, "-d", device.id, "--color", "never")
    assert result.returncode == 0, result.stderr
    headers = [line for line in result.stdout.splitlines() if line.startswith(f"{device.id} (")]
    assert len(headers) == 1


def test_fonts_device_without_vector_fonts_says_so_and_skips_the_table(db):
    from wfb.devices import Device

    candidates = [d for d in db.ids() if not db.get(d).has_symbol(Device.VECTOR_FONT_SYMBOL)]
    if not candidates:
        pytest.skip("every installed device publishes vector fonts")
    target = candidates[0]
    result = run("fonts", target, "--color", "never")
    assert result.returncode == 0, result.stderr
    assert "Graphics.getVectorFont: not available on this device" in result.stdout
    scalable_section = result.stdout.split("Scalable (vector) fonts")[1].split("System fonts")[0]
    assert "Face Name" not in scalable_section


def test_fonts_unknown_device_prints_nothing_even_with_a_valid_name_first(device):
    result = run("fonts", device.id, "non_existent_device_xyz", "--color", "never")
    assert result.returncode == 1
    assert "unknown device 'non_existent_device_xyz'" in result.stderr
    assert result.stdout == ""


def test_fonts_help():
    result = run("fonts", "--help")
    assert result.returncode == 0
    assert "list fonts available per device" in result.stdout


def test_print_device_fonts_detailed_reports_curve_unavailable(monkeypatch, capsys, device):
    """`getVectorFont` present but neither draw symbol is. No verified device
    has this split (the three symbols move together, per `Device.VECTOR_
    FONT_SYMBOL`'s own note), but nothing in the SDK promises it, so it is
    driven from a monkeypatched `has_symbol` on a real device."""
    from wfb import cli
    from wfb.devices import Device

    real_has_symbol = type(device).has_symbol

    def fake_has_symbol(self, qualified):
        if qualified in (Device.DRAW_RADIAL_TEXT_SYMBOL, Device.DRAW_ANGLED_TEXT_SYMBOL):
            return False
        return real_has_symbol(self, qualified)

    monkeypatch.setattr(type(device), "has_symbol", fake_has_symbol)
    assert device.has_symbol(Device.VECTOR_FONT_SYMBOL) is True

    cli._print_device_fonts_detailed(device)
    out = capsys.readouterr().out
    assert "yes, but curve: (radial/angled text) is unavailable" in out
    assert "yes (available)" not in out


def test_print_device_fonts_detailed_skips_fonts_for_non_watchface_device(monkeypatch, capsys, device):
    from wfb import cli

    monkeypatch.setattr(type(device), "supports_watchface", property(lambda self: False))

    cli._print_device_fonts_detailed(device)
    out = capsys.readouterr().out
    assert "cannot run a watch face" in out
    assert "Scalable" not in out
    assert "System fonts" not in out


def test_print_all_device_fonts_summary_skips_fonts_for_non_watchface_device(monkeypatch, capsys,
                                                                             db, device):
    from wfb import cli

    monkeypatch.setattr(type(device), "supports_watchface", property(lambda self: False))

    cli._print_all_device_fonts_summary(db)
    out = capsys.readouterr().out
    block = _device_block(out, device.id)
    assert "cannot run a watch face" in block
    assert "vector text:" not in block


# -- `wfb sources` / `wfb complications` -------------------------------------
#
# These invoke the real entry point as a subprocess, same as every other test
# in this file, so they exercise the whole import chain (wfb.cli -> wfb.build
# -> wfb.lint -> wfb.ir -> wfb.catalog) rather than just wfb/catalog.py or
# wfb/cli.py in isolation. tests/test_catalog.py covers the catalogue's own
# data shape (all 42 complication.* sources, launch_complication, cast, the
# renamed-source table) without needing that whole chain to import cleanly.


def test_sources_has_no_refresh_tier_flag():
    """D2: the tier concept is gone outright -- `wfb sources` must not print
    a "slow tier"/"event tier" flag for anything, weather and complications
    included."""
    result = run("sources")
    assert result.returncode == 0, result.stderr
    assert "tier" not in result.stdout


def test_sources_lists_all_42_complication_sources():
    result = run("sources")
    assert result.returncode == 0, result.stderr
    assert "complication.body_battery" in result.stdout
    assert "complication.sleep_score" in result.stdout
    assert result.stdout.count("complication.") >= 42


def test_sources_shows_the_auto_hold_target_for_a_source_that_has_one():
    result = run("sources")
    assert result.returncode == 0, result.stderr
    assert "on_hold: auto -> heart_rate" in result.stdout


def test_sources_does_not_list_a_renamed_path():
    """The nine old complication-backed paths (body_battery.current and
    friends) are gone from the catalogue, not just renamed in place --
    `wfb sources` must not still advertise the old spelling."""
    result = run("sources")
    assert result.returncode == 0, result.stderr
    assert "body_battery.current" not in result.stdout
    assert "device.next_calendar_event" not in result.stdout


def test_complications_lists_all_42_types():
    result = run("complications")
    assert result.returncode == 0, result.stderr
    assert "42 complication types" in result.stdout
    assert "body_battery" in result.stdout
    assert "sleep_score" in result.stdout
    assert "invalid" not in result.stdout


def test_complications_mentions_on_hold_auto():
    result = run("complications")
    assert result.returncode == 0, result.stderr
    assert "on_hold: auto" in result.stdout


def test_series_lists_all_fifteen_series():
    result = run("series")
    assert result.returncode == 0, result.stderr
    assert "heart_rate" in result.stdout
    assert "daily_precipitation_chance" in result.stdout
    from wfb import series as series_catalog

    for name in series_catalog.names():
        assert name in result.stdout


def test_series_names_no_sensor_history_or_solar_series():
    result = run("series")
    assert result.returncode == 0, result.stderr
    assert "solar" not in result.stdout.lower()
    assert "pressure" not in result.stdout.lower()
    assert "body_battery" not in result.stdout.lower()
    assert "stress" not in result.stdout.lower()


def test_series_shows_the_documented_maximum_for_activity_history():
    result = run("series")
    assert result.returncode == 0, result.stderr
    line = next(l for l in result.stdout.splitlines() if l.strip().startswith("steps "))
    assert "max 7" in line


# -- `wfb help` -------------------------------------------------------------


def test_bare_help_matches_the_help_flag():
    """`wfb help` with no topic is another spelling of `wfb --help` -- same
    text, but exit 0 rather than --help's own exit 0 too (unlike bare `wfb`
    with no command at all, which is a usage error and exits 2)."""
    via_help = run("help")
    via_flag = run("--help")
    assert via_help.returncode == 0
    assert via_flag.returncode == 0
    assert via_help.stdout == via_flag.stdout


def test_bare_command_is_still_a_usage_error():
    result = run()
    assert result.returncode == 2


def test_leading_help_topic_matches_the_commands_own_help_flag():
    """`wfb help build` == `wfb build --help`."""
    via_topic = run("help", "build")
    via_flag = run("build", "--help")
    assert via_topic.returncode == 0
    assert via_flag.returncode == 0
    assert via_topic.stdout == via_flag.stdout


def test_trailing_help_word_matches_the_commands_own_help_flag():
    """`wfb build help` -- help as the trailing word after the command,
    rewritten to `--help` before argparse ever sees it -- also matches."""
    via_trailing = run("build", "help")
    via_flag = run("build", "--help")
    assert via_trailing.returncode == 0
    assert via_trailing.stdout == via_flag.stdout


def test_help_rejects_an_unknown_topic_and_lists_real_commands():
    result = run("help", "nope")
    assert result.returncode == 1
    assert "no such command 'nope'" in result.stderr
    assert "build" in result.stderr and "validate" in result.stderr


def test_every_command_help_is_sourced_from_its_own_docstring():
    """The single-source-of-truth guarantee: nothing hand-duplicates a
    command's help text as a separate string anywhere -- `_command()` reads
    it straight from the handler's docstring, and this pins that down so a
    future edit cannot quietly reintroduce a diverging help= string."""
    import inspect

    from wfb.cli import _parser, _subparsers

    parser = _parser()
    for name, subparser in _subparsers(parser).items():
        handler = subparser.get_default("handler")
        assert handler is not None, name
        doc = inspect.getdoc(handler)
        assert doc, f"{name} has no docstring to source help from"
        assert subparser.description == doc, name


def test_parse_preview_time_accepts_hh_mm_and_hh_mm_ss():
    from wfb.cli import _parse_preview_time

    assert _parse_preview_time("10:09") == (10, 9, 0)
    assert _parse_preview_time("10:09:42") == (10, 9, 42)


@pytest.mark.parametrize("bad", ["25:00", "10:60", "10", "10:09:60", "abc", "10:09:42:00"])
def test_parse_preview_time_rejects_anything_else(bad):
    from wfb.cli import _parse_preview_time

    assert _parse_preview_time(bad) is None


def test_preview_reports_a_clean_error_for_a_bad_time(db):
    """`wfb preview --time` gives one readable error, not an uncaught
    ValueError from inside the renderer."""
    result = run("preview", "examples/features/analog/face.yaml", "--time", "not-a-time",
                 "-d", "fenix8solar47mm", "-o", "build/preview")
    assert result.returncode == 1
    assert "not-a-time" in result.stderr
    assert "HH:MM" in result.stderr


def test_preview_renders_a_device_that_is_not_a_target(db, tmp_path):
    """`wfb preview -d` takes any installed device, like `wfb build -d`."""
    if "fenix7pro" not in db.ids():
        pytest.skip("fenix7pro is not installed")
    result = run("preview", "examples/features/sun/face.yaml", "-d", "fenix7pro",
                 "-o", str(tmp_path), "--color", "never")
    assert result.returncode == 0, result.stderr
    assert (tmp_path / "fenix7pro.png").exists()
    assert "not one of this design's targets" in result.stdout + result.stderr


def run_binary(*args: str, cwd: Path | None = None):
    """`run`, but without text decoding: `-o -` puts PNG bytes on stdout."""
    return subprocess.run(
        [sys.executable, str(ENTRY), *args],
        capture_output=True, cwd=str(cwd or ROOT), check=False,
    )


PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


@pytest.mark.parametrize("marker", ["-", "--"])
def test_preview_writes_one_png_to_stdout(db, marker):
    """`wfb preview -o -` (or `-o --`, which argparse would otherwise eat as
    the end-of-options separator) puts the image itself on stdout and nothing
    else, so it can be piped: `wfb preview face.yaml -o -- | chafa`."""
    from PIL import Image
    import io

    result = run_binary("preview", "examples/features/sun/face.yaml", "-o", marker)
    assert result.returncode == 0, result.stderr.decode()
    assert result.stdout.startswith(PNG_MAGIC)
    # Exactly one image, although the design lists three targets -- a second
    # PNG concatenated onto the stream would make the pipe's decoder guess.
    assert result.stdout.count(PNG_MAGIC) == 1
    image = Image.open(io.BytesIO(result.stdout))
    image.load()
    assert image.format == "PNG"


def test_preview_to_stdout_picks_the_device_from_d(db):
    """The one image is the device `-d` named, not the first target."""
    from PIL import Image
    import io

    def size(*extra: str) -> tuple[int, int]:
        result = run_binary("preview", "examples/features/sun/face.yaml", "-o", "-",
                            "--scale", "1", *extra)
        assert result.returncode == 0, result.stderr.decode()
        return Image.open(io.BytesIO(result.stdout)).size

    # fenix8solar51mm is 280x280 and is *not* this design's first target, so a
    # run that ignored -d would come back at the 47mm's 260x260.
    assert size() == (260, 260)
    assert size("-d", "fenix8solar51mm") == (280, 280)


def test_preview_quiet_silences_stdout_but_still_writes(db, tmp_path):
    """`-q` is for scripts: the PNGs still land, stdout stays empty, and
    diagnostics are untouched because they were always on stderr."""
    result = run("preview", "examples/features/sun/face.yaml", "-q",
                 "-o", str(tmp_path), "--color", "never")
    assert result.returncode == 0, result.stderr
    assert result.stdout == ""
    assert (tmp_path / "fenix8solar47mm.png").exists()


def test_preview_heatmap_goes_to_stdout_too(db, tmp_path):
    """`--heatmap -o -` once wrote `./-/<device>--heatmap.png` instead: the
    heatmap had its own output branch that ran before the stdout check.
    Every mode now shares one sink, so this covers the whole class."""
    from PIL import Image
    import io

    design = ROOT / "examples" / "features" / "aod" / "face.yaml"
    result = run_binary("preview", str(design), "-d", "fenix847mm", "--heatmap",
                        "--scale", "1", "-o", "-", cwd=tmp_path)
    assert result.returncode == 0, result.stderr.decode()
    assert result.stdout.count(PNG_MAGIC) == 1
    assert Image.open(io.BytesIO(result.stdout)).size == (454, 454)
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("extra, named", [
    (["--time", "10:00", "--minute", "5"], "--time and --minute"),
    (["--heatmap", "--minute", "5"], "--minute and --heatmap"),
    (["--heatmap", "--time", "10:00"], "--time and --heatmap"),
    (["--style", "x", "--all-styles"], "--style and --all-styles"),
    (["--heatmap", "--all-styles"], "--all-styles"),
    (["--minute", "1440"], "--minute 1440"),
])
def test_preview_rejects_conflicting_flags(db, extra, named):
    result = run("preview", "examples/features/sun/face.yaml", "-o", "--", *extra)
    assert result.returncode == 1
    assert named in result.stderr


def test_preview_to_stdout_refuses_to_watch(db):
    """`--watch` would write a PNG per re-render into one stream."""
    result = run("preview", "examples/features/sun/face.yaml", "-o", "--", "--watch")
    assert result.returncode == 1
    assert "--watch" in result.stderr


#: `FONT_NUMBER_HOT` on `fenix8solar47mm` resolves to `Bionic_semibold`
#: (`docs/plans/12-preview-font-fidelity.md` §1.1's own worked example),
#: which the registry's `names` table maps to the `bionic-substitute`
#: stand-in -- match `"substitute"`, a different family entirely, not a
#: free release of Bionic itself (`tests/test_font_registry.py`) -- which
#: is what makes it a reliable way to force the R1.2 warning at the CLI
#: layer without depending on which symbols happen to be `exact`-matched
#: today.
_FONT_WARNING_DESIGN = """
format: 1
face:
  id: 8f4c1e92-4a5b-4d81-9e6f-2b0c8d4a1f58
  name: FontWarningTest
targets: [fenix8solar47mm]
palette:
  bg: "#000000"
  fg: "#FFFFFF"
elements:
  - id: label
    type: text
    text: "88"
    font: FONT_NUMBER_HOT
    align: center
    vertical_align: center
    at: {anchor: center}
    color: palette.fg
"""


def _require_bionic_substitute():
    from wfb.fonts import fetch_system

    if fetch_system.path_for("bionic-substitute") is None:
        pytest.skip("bionic-substitute.ttf is not installed at wfb/assets/system-fonts/")


def test_preview_warns_about_a_stand_in_font_even_with_dash_o(db, tmp_path):
    """R1.2/R1.4: with no Garmin font root (conftest's session-wide
    `WFB_NO_GARMIN_FONTS=1`, inherited by the subprocess), `FONT_NUMBER_HOT`
    draws with the free `bionic-substitute` stand-in instead of Bionic
    itself -- the warning must reach stderr even under `-o -`, which R1.4
    says silences stdout *progress* only, never a correctness warning."""
    _require_bionic_substitute()
    design = tmp_path / "face.yaml"
    design.write_text(_FONT_WARNING_DESIGN, encoding="utf-8")
    result = run_binary("preview", str(design), "-d", "fenix8solar47mm", "-o", "-")
    assert result.returncode == 0, result.stderr.decode()
    stderr = result.stderr.decode()
    assert "warning:" in stderr
    assert "Bionic" in stderr
    assert "bionic-substitute.ttf" in stderr
    assert "wfb doctor" in stderr


def test_preview_fonts_flag_silences_the_warning(db, tmp_path):
    """R1.5: `--fonts DIR` reaches every `fallback.system_face` call this
    renderer makes, the same way `wfb doctor --fonts` already reaches its
    own report.  Pointing it at a directory holding a file named exactly
    like the device's own `Bionic_semibold` stem makes `fetch_system.locate`
    report a `"garmin"` match (decided by name and location, not content --
    the bytes here are `tests/fixtures/slice/assets/OpenSans-Regular.ttf`,
    not Garmin's own), so the same design that just warned above now draws
    silently."""
    _require_bionic_substitute()
    design = tmp_path / "face.yaml"
    design.write_text(_FONT_WARNING_DESIGN, encoding="utf-8")
    font_root = tmp_path / "fonts"
    font_root.mkdir()
    stand_in = ROOT / "tests" / "fixtures" / "slice" / "assets" / "OpenSans-Regular.ttf"
    (font_root / "Bionic_semibold.ttf").write_bytes(stand_in.read_bytes())

    result = run_binary("preview", str(design), "-d", "fenix8solar47mm", "-o", "-",
                        "--fonts", str(font_root))
    assert result.returncode == 0, result.stderr.decode()
    assert "warning:" not in result.stderr.decode()
