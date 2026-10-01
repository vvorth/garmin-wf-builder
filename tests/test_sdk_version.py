"""The SDK version is recorded, not pinned (ADR 0009 §4): the device
reference records the SDK it was extracted from, a build warns when it
compiles with another, and the build directory records what built it."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

from wfb.build import BUILD_INFO, Toolchain, _write_build_info, check_sdk
from wfb.devices import reference_sdk_version
from wfb.diagnostics import Bag

from tests.helpers import ROOT


def _sdk(tmp_path: Path, version: str) -> Toolchain:
    sdk = tmp_path / "sdk"
    (sdk / "bin").mkdir(parents=True)
    (sdk / "bin" / "version.txt").write_text(f"{version}\n", encoding="utf-8")
    (sdk / "doc" / "docs" / "Device_Reference").mkdir(parents=True)
    return Toolchain(sdk, tmp_path / "key.der")


def _reference(tmp_path: Path, version: str | None) -> Path:
    devices = tmp_path / "ref" / "devices"
    devices.mkdir(parents=True)
    if version is not None:
        (devices.parent / "sdk-version.txt").write_text(f"{version}\n", encoding="utf-8")
    return devices


def test_the_reference_reads_back_its_sdk(tmp_path):
    assert reference_sdk_version(_reference(tmp_path, "9.2.0")) == "9.2.0"
    assert reference_sdk_version(tmp_path / "nowhere" / "devices") is None


def test_a_reference_from_another_sdk_warns(tmp_path):
    bag = Bag()
    assert check_sdk(_sdk(tmp_path, "9.3.0"), bag, _reference(tmp_path, "9.2.0")) == "9.3.0"
    (warning,) = bag.items
    assert (warning.severity.value, warning.code) == ("warning", "sdk")
    assert "extracted from SDK 9.2.0" in warning.message
    assert "compiles with SDK 9.3.0" in warning.message


def test_a_reference_from_the_same_sdk_says_nothing(tmp_path):
    bag = Bag()
    check_sdk(_sdk(tmp_path, "9.2.0"), bag, _reference(tmp_path, "9.2.0"))
    assert bag.items == []


def test_a_reference_that_records_no_sdk_is_a_note(tmp_path):
    bag = Bag()
    check_sdk(_sdk(tmp_path, "9.2.0"), bag, _reference(tmp_path, None))
    (note,) = bag.items
    assert (note.severity.value, note.code) == ("note", "sdk")


def test_the_extractor_records_the_sdk_release(tmp_path):
    toolchain = _sdk(tmp_path, "9.4.1")
    out = tmp_path / "out"
    subprocess.run([sys.executable, str(ROOT / "tools" / "extract-device-reference.py"),
                    "--sdk", str(toolchain.sdk), "--out", str(out)], check=True,
                   capture_output=True)
    assert (out / "sdk-version.txt").read_text(encoding="utf-8") == "9.4.1\n"
    # an explicit release wins over (or stands in for) bin/version.txt
    subprocess.run([sys.executable, str(ROOT / "tools" / "extract-device-reference.py"),
                    "--sdk", str(toolchain.sdk), "--sdk-version", "9.5.0", "--out", str(out)],
                   check=True, capture_output=True)
    assert (out / "sdk-version.txt").read_text(encoding="utf-8") == "9.5.0\n"


def test_the_build_directory_records_what_built_it(tmp_path):
    result = SimpleNamespace(
        sdk_version="9.2.0", output_dir=tmp_path,
        devices=[SimpleNamespace(id="fr955"), SimpleNamespace(id="fenix8solar47mm")],
        products={"fr955": tmp_path / "face-fr955.prg"})
    _write_build_info(result)
    info = json.loads((tmp_path / BUILD_INFO).read_text(encoding="utf-8"))
    assert info["sdk"] == "9.2.0"
    assert info["devices"] == ["fr955", "fenix8solar47mm"]
    assert info["products"] == ["face-fr955.prg"]
    assert "device_reference_sdk" in info
