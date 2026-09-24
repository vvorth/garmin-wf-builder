"""Unit tests for `tools/snapshot.py`'s pure parts: text normalisation,
image hashing, and `diff` on small hand-made snapshot directories.

This deliberately never runs the tool's `save`/`compare` commands (those
drive the real CLI across every example and take minutes -- the tool's own
module docstring explains why it lives outside the pytest suite). Loaded by
file path, since `tools/` is not a package and the module's name
(`snapshot`) is generic enough that importing it by name would risk
shadowing something on `sys.path`.
"""

from __future__ import annotations

import importlib.util
import io
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


def _load_snapshot_module():
    spec = importlib.util.spec_from_file_location("wfb_snapshot_tool", ROOT / "tools" / "snapshot.py")
    module = importlib.util.module_from_spec(spec)
    # `dataclasses.dataclass` looks its own module up via `sys.modules`, so the
    # module must be registered there before `exec_module` runs.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


snap = _load_snapshot_module()


# ---------------------------------------------------------------------------
# normalize_text
# ---------------------------------------------------------------------------


def test_out_dir_is_replaced():
    text = snap.normalize_text("generated  /tmp/xyz123/showcase\n", key="build/x/targets",
                               out_dir="/tmp/xyz123")
    assert "<OUT>" in text
    assert "/tmp/xyz123" not in text


def test_repo_root_is_replaced():
    text = snap.normalize_text(f"{snap.ROOT}/schema/wfb-face-1.schema.json", key="cli/schema",
                               out_dir=None)
    assert text == "<ROOT>/schema/wfb-face-1.schema.json"


def test_home_dir_is_replaced():
    text = snap.normalize_text(f"{snap._HOME}/.Garmin/ConnectIQ/Devices", key="cli/doctor",
                               out_dir=None)
    assert text == "<HOME>/.Garmin/ConnectIQ/Devices"


def test_timing_is_normalised_but_other_numbers_are_not():
    text = snap.normalize_text(
        "build succeeded -- 2 warnings, 1 note in 4.63s\n"
        "note: the static content buffers 67,600 B (6.4%)\n",
        key="build/x/targets", out_dir=None,
    )
    assert "in <T>s" in text
    assert "4.63s" not in text
    # Real content -- byte counts and percentages -- must survive untouched.
    assert "67,600 B" in text
    assert "6.4%" in text


def test_uuid_is_normalised_only_in_new_cases():
    uuid = "a1b2c3d4-e5f6-7890-abcd-ef1234567890"
    new_text = snap.normalize_text(f"id: {uuid}\n", key="cli/new-minimal/color-never", out_dir=None)
    assert "<UUID>" in new_text
    assert uuid not in new_text

    other_text = snap.normalize_text(f"id: {uuid}\n", key="build/examples/showcase/face/targets",
                                     out_dir=None)
    assert other_text == f"id: {uuid}\n"


# ---------------------------------------------------------------------------
# image hashing
# ---------------------------------------------------------------------------


def _make_png_bytes(pixels, *, size=(4, 4), mode="RGB", compress_level=0):
    from PIL import Image

    image = Image.new(mode, size)
    image.putdata(pixels)
    buf = io.BytesIO()
    image.save(buf, format="PNG", compress_level=compress_level)
    return buf.getvalue()


def test_identical_pixels_hash_the_same_despite_different_png_encoding():
    pixels = [(i % 256, (i * 3) % 256, (i * 7) % 256) for i in range(16)]
    raw_a = _make_png_bytes(pixels, compress_level=0)
    raw_b = _make_png_bytes(pixels, compress_level=9)
    assert raw_a != raw_b  # different encoder settings really do produce different bytes

    kind_a, _, digest_a = snap.classify_image(raw_a)
    kind_b, _, digest_b = snap.classify_image(raw_b)
    assert kind_a == kind_b == "image"
    assert digest_a == digest_b


def test_one_changed_pixel_hashes_differently():
    pixels = [(0, 0, 0)] * 16
    raw_a = _make_png_bytes(pixels)
    changed = list(pixels)
    changed[5] = (255, 255, 255)
    raw_b = _make_png_bytes(changed)

    _, _, digest_a = snap.classify_image(raw_a)
    _, _, digest_b = snap.classify_image(raw_b)
    assert digest_a != digest_b


def test_load_artifact_classifies_png_as_image_and_text_as_text(tmp_path):
    png_path = tmp_path / "a.png"
    png_path.write_bytes(_make_png_bytes([(1, 2, 3)] * 16))
    kind, _, _ = snap.load_artifact(png_path, key="preview/x/default", out_dir=None)
    assert kind == "image"

    text_path = tmp_path / "manifest.xml"
    text_path.write_text("<manifest/>\n", encoding="utf-8")
    kind, stored, _ = snap.load_artifact(text_path, key="build/x/targets", out_dir=None)
    assert kind == "text"
    assert stored == b"<manifest/>\n"

    binary_path = tmp_path / "key.der"
    binary_path.write_bytes(b"\xff\xd8\xff\x00binary")
    kind, stored, digest = snap.load_artifact(binary_path, key="build/x/targets", out_dir=None)
    assert kind == "binary"
    assert stored == b"\xff\xd8\xff\x00binary"


# ---------------------------------------------------------------------------
# diff, on small hand-made snapshot directories
# ---------------------------------------------------------------------------


def _write_snapshot(root: Path, cases: dict, *, env=None):
    """A minimal on-disk snapshot: `cases` maps a case key to
    {artifact name: (kind, text-or-bytes)}; exit is always 0 unless a case's
    value dict carries its own "__exit__" entry."""
    root.mkdir(parents=True, exist_ok=True)
    (root / "cases").mkdir(exist_ok=True)
    manifest_cases = {}
    for key, artifacts in cases.items():
        exit_code = artifacts.pop("__exit__", 0)
        case_dir = root / "cases" / key
        case_dir.mkdir(parents=True, exist_ok=True)
        entry_artifacts = {}
        for name, (kind, content) in artifacts.items():
            dest = case_dir / name
            dest.parent.mkdir(parents=True, exist_ok=True)
            if isinstance(content, str):
                data = content.encode("utf-8")
            else:
                data = content
            dest.write_bytes(data)
            import hashlib
            entry_artifacts[name] = {"kind": kind, "sha256": hashlib.sha256(data).hexdigest()}
        manifest_cases[key] = {"exit": exit_code, "artifacts": entry_artifacts}
    manifest = {"version": 1, "created": "2026-01-01T00:00:00Z", "python": "3.11",
                "env": env or {"WFB_NO_GARMIN_FONTS": None, "WFB_FONTS": None},
                "cases": manifest_cases}
    (root / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")


def test_diff_identical_snapshots_exits_zero(tmp_path, capsys):
    cases = {"build/x/targets": {"stdout": ("text", "build succeeded\n")}}
    _write_snapshot(tmp_path / "a", {k: dict(v) for k, v in cases.items()})
    _write_snapshot(tmp_path / "b", {k: dict(v) for k, v in cases.items()})

    rc = snap.do_diff(tmp_path / "a", tmp_path / "b")
    out = capsys.readouterr().out
    assert rc == 0
    assert "1 unchanged, 0 changed, 0 added, 0 removed" in out


def test_diff_changed_text_reports_unified_diff_and_exits_one(tmp_path, capsys):
    _write_snapshot(tmp_path / "a", {
        "build/x/targets": {"stdout": ("text", "line one\nline two\nline three\n")},
    })
    _write_snapshot(tmp_path / "b", {
        "build/x/targets": {"stdout": ("text", "line one\nCHANGED\nline three\n")},
    })

    rc = snap.do_diff(tmp_path / "a", tmp_path / "b")
    out = capsys.readouterr().out
    assert rc == 1
    assert "0 unchanged, 1 changed, 0 added, 0 removed" in out
    assert "build/x/targets" in out
    assert "-line two" in out
    assert "+CHANGED" in out


def test_diff_reports_added_and_removed_cases(tmp_path, capsys):
    _write_snapshot(tmp_path / "a", {
        "build/x/targets": {"stdout": ("text", "ok\n")},
        "build/y/targets": {"stdout": ("text", "ok\n")},
    })
    _write_snapshot(tmp_path / "b", {
        "build/x/targets": {"stdout": ("text", "ok\n")},
        "build/z/targets": {"stdout": ("text", "ok\n")},
    })

    rc = snap.do_diff(tmp_path / "a", tmp_path / "b")
    out = capsys.readouterr().out
    assert rc == 1
    assert "+ build/z/targets" in out
    assert "- build/y/targets" in out


def test_diff_only_filter_restricts_both_sides(tmp_path, capsys):
    _write_snapshot(tmp_path / "a", {
        "build/x/targets": {"stdout": ("text", "ok\n")},
        "build/y/targets": {"stdout": ("text", "ok\n")},
    })
    _write_snapshot(tmp_path / "b", {
        "build/x/targets": {"stdout": ("text", "ok\n")},
    })

    # Without a filter, "y" is reported removed.
    rc_all = snap.do_diff(tmp_path / "a", tmp_path / "b")
    assert rc_all == 1

    # Filtered to "x" alone, both sides agree and there is nothing to report.
    rc_filtered = snap.do_diff(tmp_path / "a", tmp_path / "b", only=["build/x"])
    out = capsys.readouterr().out
    assert rc_filtered == 0
    assert "1 unchanged, 0 changed, 0 added, 0 removed" in out


def test_diff_warns_on_env_mismatch_but_does_not_fail(tmp_path, capsys):
    _write_snapshot(tmp_path / "a", {"build/x/targets": {"stdout": ("text", "ok\n")}},
                    env={"WFB_NO_GARMIN_FONTS": "1", "WFB_FONTS": None})
    _write_snapshot(tmp_path / "b", {"build/x/targets": {"stdout": ("text", "ok\n")}},
                    env={"WFB_NO_GARMIN_FONTS": None, "WFB_FONTS": None})

    rc = snap.do_diff(tmp_path / "a", tmp_path / "b")
    captured = capsys.readouterr()
    assert rc == 0
    assert "different env" in captured.err


def test_diff_created_timestamp_never_participates(tmp_path, capsys):
    # Two snapshots with different "created" but identical cases must diff clean.
    _write_snapshot(tmp_path / "a", {"build/x/targets": {"stdout": ("text", "ok\n")}})
    _write_snapshot(tmp_path / "b", {"build/x/targets": {"stdout": ("text", "ok\n")}})
    manifest_path = tmp_path / "b" / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["created"] = "2099-12-31T23:59:59Z"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    rc = snap.do_diff(tmp_path / "a", tmp_path / "b")
    assert rc == 0


def test_image_artifact_diff_reports_pixel_count_and_bbox(tmp_path, capsys):
    pixels_a = [(0, 0, 0)] * 16
    pixels_b = list(pixels_a)
    pixels_b[5] = (255, 255, 255)
    _write_snapshot(tmp_path / "a", {
        "preview/x/default": {"a.png": ("image", _make_png_bytes(pixels_a))},
    })
    _write_snapshot(tmp_path / "b", {
        "preview/x/default": {"a.png": ("image", _make_png_bytes(pixels_b))},
    })

    rc = snap.do_diff(tmp_path / "a", tmp_path / "b")
    out = capsys.readouterr().out
    assert rc == 1
    assert "pixels differ: 1 px changed" in out


def test_the_command_list_is_the_one_naming_build_not_the_color_choices():
    """`wfb --help`'s usage line lists `--color {auto,always,never}` before
    the command choices; taking the first `{...}` read the colours as
    commands."""
    usage = ("usage: wfb [-h] [--color {auto,always,never}] [--version]\n"
             "           {build,validate,preview,help}\n")
    assert snap.parse_commands(usage) == ["build", "validate", "preview", "help"]
    assert snap.parse_commands("no lists here") is None
