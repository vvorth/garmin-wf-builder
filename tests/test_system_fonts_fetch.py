"""`wfb/fonts/fetch_system.py` -- registry-driven fetch/cache, offline.

Everything here builds a small fake `registry.json` plus fake archive/direct
font bytes in `tmp_path`, points the module at them with
`monkeypatch.setattr(fetch_system, "REGISTRY_PATH", ...)`, and drives it
through a monkeypatched `_download` hook, so no test ever touches the
network -- the real registry's archives are megabytes and pinned to the one
real releases, not to anything a test can fabricate.  `tests/conftest.py`
also sets `WFB_OFFLINE=1` for the whole session as a second line of defence,
overridden per test here where a test needs the online path.
"""

from __future__ import annotations

import hashlib
import io
import json
import zipfile
from pathlib import Path

import pytest

from wfb.fonts import fetch_system

ARCHIVE_URL = "https://example.invalid/roboto.zip"
DIRECT_URL = "https://example.invalid/bebas.ttf"


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _zip_bytes(members: dict[str, bytes], *, nested: bool = False,
                macosx_junk: bool = False) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as archive:
        for name, content in members.items():
            path = f"roboto-unhinted/{name}" if nested else name
            archive.writestr(path, content)
            if macosx_junk:
                archive.writestr(f"__MACOSX/._{name}", b"resource-fork junk")
    return buf.getvalue()


def _archive_members() -> dict[str, bytes]:
    return {
        "RobotoCondensed-Bold.ttf": b"fake condensed bold ttf bytes",
        "Roboto-Black.ttf": b"fake black ttf bytes",
        "LICENSE": b"fake Apache-2.0 licence text",
    }


DIRECT_BYTES = b"fake bebas neue ttf bytes"


def _registry(archive_members: dict[str, bytes]) -> dict:
    """One archive source with two members (exercises the "download once,
    materialise every member" path, and font-key aliasing: `bionic-
    substitute` shares the `roboto-black` source, the same way the real
    registry's substitute keys share a real family's source) plus one
    direct-file source (no `member`, the whole download is the font)."""
    return {
        "version": 1,
        "comment": "fake registry for tests",
        "sources": {
            "roboto-condensed-bold": {
                "url": ARCHIVE_URL,
                "member": "RobotoCondensed-Bold.ttf",
                "sha256": _sha(archive_members["RobotoCondensed-Bold.ttf"]),
                "size": len(archive_members["RobotoCondensed-Bold.ttf"]),
                "license": "Apache-2.0",
                "license_url": f"{ARCHIVE_URL} (member: LICENSE)",
            },
            "roboto-black": {
                "url": ARCHIVE_URL,
                "member": "Roboto-Black.ttf",
                "sha256": _sha(archive_members["Roboto-Black.ttf"]),
                "size": len(archive_members["Roboto-Black.ttf"]),
                "license": "Apache-2.0",
                "license_url": f"{ARCHIVE_URL} (member: LICENSE)",
            },
            "bebas-neue-regular": {
                "url": DIRECT_URL,
                "sha256": _sha(DIRECT_BYTES),
                "size": len(DIRECT_BYTES),
                "license": "OFL-1.1",
                "license_url": "https://example.invalid/OFL.txt",
            },
        },
        "fonts": {
            "roboto-condensed-bold": {"source": "roboto-condensed-bold", "match": "exact", "note": ""},
            "bionic-substitute": {"source": "roboto-black", "match": "substitute", "note": ""},
            "bebas-neue-regular": {"source": "bebas-neue-regular", "match": "exact", "note": ""},
        },
        "names": {
            "RobotoCondensed-Bold": "roboto-condensed-bold",
            "BebasNeueRegular": "bebas-neue-regular",
        },
        "patterns": [
            {"regex": "BIONIC", "key": "bionic-substitute", "note": "bionic substitute"},
        ],
        "faces": {
            "Bebas Neue Bold": "bebas-neue-regular",
        },
        "unmapped": [],
    }


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    """Every test gets its own registry file, install dir, cache dir and a
    clear "no URL attempted yet" set -- `_attempted_urls` is a module-level
    global that would otherwise leak between tests in the same session."""
    registry_path = tmp_path / "registry.json"
    monkeypatch.setattr(fetch_system, "REGISTRY_PATH", registry_path)
    monkeypatch.setattr(fetch_system, "DEFAULT_DEST", tmp_path / "install")
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache-home"))
    monkeypatch.setattr(fetch_system, "_attempted_urls", set())
    fetch_system._font_index.cache_clear()
    # tests/conftest.py sets WFB_OFFLINE=1 for the whole session so no other
    # test ever reaches the network by accident; the network-path tests here
    # override it back off explicitly (test_offline_never_calls_the_downloader
    # sets it again on purpose).
    monkeypatch.delenv("WFB_OFFLINE", raising=False)
    return registry_path


def _write_registry(path: Path, registry: dict) -> None:
    path.write_text(json.dumps(registry), encoding="utf-8")


class _CountingDownloader:
    def __init__(self, by_url: dict[str, bytes]):
        self.by_url = by_url
        self.calls: list[str] = []

    def __call__(self, url: str) -> bytes:
        self.calls.append(url)
        return self.by_url[url]


def _explosive_downloader(url: str) -> bytes:  # pragma: no cover - only ever called on failure
    raise AssertionError(f"downloader should not have been called (url={url!r})")


# ---------------------------------------------------------------------------
# resolve() -- pure, offline
# ---------------------------------------------------------------------------


def test_resolve_prefers_exact_name_over_pattern_over_face(_isolated):
    _write_registry(_isolated, _registry(_archive_members()))

    # "RobotoCondensed-Bold" is an exact `names` hit -- even though its own
    # content would also match no pattern here, this proves names wins first.
    assert fetch_system.resolve("RobotoCondensed-Bold") == "roboto-condensed-bold"

    # "FNT_BIONIC_COND_30" hits no exact name, but matches the "BIONIC" pattern.
    assert fetch_system.resolve("FNT_BIONIC_COND_30") == "bionic-substitute"

    # A name with no name/pattern hit falls through to the face table.
    assert fetch_system.resolve("SomeOpaqueToken", face="Bebas Neue Bold") == "bebas-neue-regular"

    # Nothing matches at all.
    assert fetch_system.resolve("SomeOpaqueToken") is None


def test_resolve_order_name_beats_pattern_beats_face(_isolated):
    """A synthetic registry where all three layers disagree on the same
    string, proving the resolver's priority is name > pattern > face, not
    incidental to which layer real names happen to hit."""
    registry = _registry(_archive_members())
    registry["names"]["conflict"] = "roboto-condensed-bold"
    registry["patterns"].insert(0, {"regex": "^conflict$", "key": "bionic-substitute", "note": ""})
    registry["faces"]["conflict-face"] = "bebas-neue-regular"
    _write_registry(_isolated, registry)

    assert fetch_system.resolve("conflict", face="conflict-face") == "roboto-condensed-bold"
    assert fetch_system.resolve("unmatched-name", face="conflict-face") == "bebas-neue-regular"
    assert fetch_system.resolve("unmatched-name") is None


# ---------------------------------------------------------------------------
# ensure() / install() -- the network + cache path
# ---------------------------------------------------------------------------


def test_good_hash_installs_and_aliases_the_shared_source(_isolated):
    members = _archive_members()
    zip_bytes = _zip_bytes(members)
    _write_registry(_isolated, _registry(members))
    downloader = _CountingDownloader({ARCHIVE_URL: zip_bytes})
    fetch_system._download = downloader  # type: ignore[assignment]

    path = fetch_system.ensure("roboto-condensed-bold")

    assert path == fetch_system.cache_dir() / "roboto-condensed-bold.ttf"
    assert path.read_bytes() == members["RobotoCondensed-Bold.ttf"]
    # bionic-substitute shares the roboto-black source: one archive download
    # must materialise it too, not just the key that was actually requested.
    aliased = fetch_system.cache_dir() / "bionic-substitute.ttf"
    assert aliased.is_file()
    assert aliased.read_bytes() == members["Roboto-Black.ttf"]
    assert downloader.calls == [ARCHIVE_URL]
    # A licence file lands alongside, named by source id.
    assert (fetch_system.cache_dir() / "roboto-condensed-bold.LICENSE.txt").is_file()


def test_direct_file_source_installs_without_extraction(_isolated):
    _write_registry(_isolated, _registry(_archive_members()))
    downloader = _CountingDownloader({DIRECT_URL: DIRECT_BYTES})
    fetch_system._download = downloader  # type: ignore[assignment]

    path = fetch_system.ensure("bebas-neue-regular")

    assert path is not None
    assert path.read_bytes() == DIRECT_BYTES
    assert downloader.calls == [DIRECT_URL]


def test_bad_archive_hash_refuses_and_leaves_nothing_behind(_isolated):
    """A corrupted/garbage download -- not a valid zip at all -- must refuse
    cleanly rather than half-install some members."""
    _write_registry(_isolated, _registry(_archive_members()))
    fetch_system._download = lambda url: b"not actually a zip file"  # type: ignore[assignment]

    result = fetch_system.ensure("roboto-condensed-bold")

    assert result is None
    assert not (fetch_system.cache_dir() / "roboto-condensed-bold.ttf").exists()
    assert not (fetch_system.cache_dir() / "bionic-substitute.ttf").exists()


def test_bad_member_hash_refuses_and_leaves_nothing_behind(_isolated):
    """A valid zip, but one member's content does not match its pinned
    hash: the whole group refuses, including the member that *would* have
    verified -- matching the old module's all-or-nothing archive install."""
    members = _archive_members()
    tampered = dict(members)
    tampered["Roboto-Black.ttf"] = b"tampered bytes, wrong hash now"
    zip_bytes = _zip_bytes(tampered)
    _write_registry(_isolated, _registry(members))  # hashes pinned to the *original* bytes
    fetch_system._download = lambda url: zip_bytes  # type: ignore[assignment]

    result = fetch_system.ensure("roboto-condensed-bold")

    assert result is None
    assert not (fetch_system.cache_dir() / "roboto-condensed-bold.ttf").exists()
    assert not (fetch_system.cache_dir() / "bionic-substitute.ttf").exists()


def test_second_run_downloads_nothing(_isolated):
    members = _archive_members()
    zip_bytes = _zip_bytes(members)
    _write_registry(_isolated, _registry(members))
    fetch_system._download = _CountingDownloader({ARCHIVE_URL: zip_bytes})  # type: ignore[assignment]

    first = fetch_system.ensure("roboto-condensed-bold")
    assert first is not None

    fetch_system._download = _explosive_downloader  # type: ignore[assignment]
    second = fetch_system.ensure("roboto-condensed-bold")
    assert second == first

    # A sibling key aliasing the same archive is also already satisfied.
    assert fetch_system.ensure("bionic-substitute") is not None


def test_offline_never_calls_the_downloader(_isolated, monkeypatch):
    _write_registry(_isolated, _registry(_archive_members()))
    monkeypatch.setenv("WFB_OFFLINE", "1")
    calls: list[str] = []

    def recording(url: str) -> bytes:
        calls.append(url)
        raise AssertionError("downloader should not have been called")

    fetch_system._download = recording  # type: ignore[assignment]

    result = fetch_system.ensure("roboto-condensed-bold")

    # The point of WFB_OFFLINE is not merely a `None` result (a failed
    # download also returns `None`, since `ensure` never raises) but that
    # the downloader is never reached at all.
    assert result is None
    assert calls == []


def test_ensure_downloads_once_when_online(_isolated, monkeypatch):
    members = _archive_members()
    zip_bytes = _zip_bytes(members)
    _write_registry(_isolated, _registry(members))
    monkeypatch.delenv("WFB_OFFLINE", raising=False)
    downloader = _CountingDownloader({ARCHIVE_URL: zip_bytes})
    fetch_system._download = downloader  # type: ignore[assignment]

    path = fetch_system.ensure("roboto-condensed-bold")

    assert path is not None
    assert len(downloader.calls) == 1


def test_ensure_gives_up_after_one_failed_attempt_per_url(_isolated, monkeypatch):
    _write_registry(_isolated, _registry(_archive_members()))
    monkeypatch.delenv("WFB_OFFLINE", raising=False)
    calls = []

    def failing(url: str) -> bytes:
        calls.append(url)
        raise OSError("network is unreachable")

    fetch_system._download = failing  # type: ignore[assignment]

    assert fetch_system.ensure("roboto-condensed-bold") is None
    assert fetch_system.ensure("bionic-substitute") is None  # shares the same URL
    assert calls == [ARCHIVE_URL]  # not retried for the sibling key


def test_ensure_returns_none_for_an_unknown_key(_isolated):
    _write_registry(_isolated, _registry(_archive_members()))
    assert fetch_system.ensure("no-such-font") is None


def test_install_writes_into_the_given_destination(_isolated, tmp_path):
    members = _archive_members()
    zip_bytes = _zip_bytes(members)
    _write_registry(_isolated, _registry(members))
    fetch_system._download = _CountingDownloader({ARCHIVE_URL: zip_bytes, DIRECT_URL: DIRECT_BYTES})  # type: ignore[assignment]

    dest = tmp_path / "prefetch-dest"
    results = fetch_system.install(
        ["roboto-condensed-bold", "bionic-substitute", "bebas-neue-regular"], dest
    )

    assert results == {"roboto-condensed-bold": True, "bionic-substitute": True,
                        "bebas-neue-regular": True}
    assert (dest / "roboto-condensed-bold.ttf").read_bytes() == members["RobotoCondensed-Bold.ttf"]
    assert (dest / "bionic-substitute.ttf").read_bytes() == members["Roboto-Black.ttf"]
    assert (dest / "bebas-neue-regular.ttf").read_bytes() == DIRECT_BYTES
    assert (dest / "roboto-condensed-bold.LICENSE.txt").is_file()


def test_nested_and_macosx_junk_members_are_still_found(_isolated):
    members = _archive_members()
    zip_bytes = _zip_bytes(members, nested=True, macosx_junk=True)
    _write_registry(_isolated, _registry(members))
    fetch_system._download = lambda url: zip_bytes  # type: ignore[assignment]

    path = fetch_system.ensure("roboto-condensed-bold")

    assert path is not None
    assert path.read_bytes() == members["RobotoCondensed-Bold.ttf"]


# ---------------------------------------------------------------------------
# cache_dir() / path_for() / tier_for()
# ---------------------------------------------------------------------------


def test_cache_dir_honours_xdg_cache_home(_isolated, tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "somewhere-else"))
    assert fetch_system.cache_dir() == tmp_path / "somewhere-else" / "wfb" / "fonts"


def test_cache_dir_defaults_under_home_cache(_isolated, monkeypatch):
    monkeypatch.delenv("XDG_CACHE_HOME", raising=False)
    assert fetch_system.cache_dir() == Path.home() / ".cache" / "wfb" / "fonts"


def test_path_for_prefers_install_location_over_cache(_isolated):
    _write_registry(_isolated, _registry(_archive_members()))

    assert fetch_system.path_for("roboto-condensed-bold") is None

    cache_path = fetch_system.cache_dir() / "roboto-condensed-bold.ttf"
    cache_path.parent.mkdir(parents=True)
    cache_path.write_bytes(b"cached bytes")
    assert fetch_system.path_for("roboto-condensed-bold") == cache_path
    assert fetch_system.tier_for("roboto-condensed-bold") == "cached"

    install_path = fetch_system.DEFAULT_DEST / "roboto-condensed-bold.ttf"
    install_path.parent.mkdir(parents=True)
    install_path.write_bytes(b"installed bytes")
    assert fetch_system.path_for("roboto-condensed-bold") == install_path
    assert fetch_system.tier_for("roboto-condensed-bold") == "installed"


# ---------------------------------------------------------------------------
# Garmin font root discovery (plan 09 R1b)
# ---------------------------------------------------------------------------


def test_garmin_font_root_discovery_order(_isolated, tmp_path, monkeypatch):
    repo_root = tmp_path / "repo"
    home = tmp_path / "home"
    (repo_root).mkdir()
    home.mkdir()
    monkeypatch.setattr(fetch_system, "_REPO_ROOT", repo_root)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    monkeypatch.delenv("WFB_FONTS", raising=False)
    monkeypatch.delenv("APPDATA", raising=False)

    # Nothing exists anywhere yet.
    assert fetch_system.garmin_font_root() is None

    # 3. vendor/fonts/ (repo-relative), non-empty.
    vendor_fonts = repo_root / "vendor" / "fonts"
    vendor_fonts.mkdir(parents=True)
    (vendor_fonts / "SomeFont.ttf").write_bytes(b"x")
    assert fetch_system.garmin_font_root() == vendor_fonts

    # 2. WFB_FONTS outranks vendor/fonts/.
    env_fonts = tmp_path / "env-fonts"
    env_fonts.mkdir()
    (env_fonts / "SomeFont.ttf").write_bytes(b"x")
    monkeypatch.setenv("WFB_FONTS", str(env_fonts))
    assert fetch_system.garmin_font_root() == env_fonts

    # 1. an explicit override outranks WFB_FONTS.
    override_fonts = tmp_path / "override-fonts"
    override_fonts.mkdir()
    (override_fonts / "SomeFont.ttf").write_bytes(b"x")
    assert fetch_system.garmin_font_root(override_fonts) == override_fonts

    monkeypatch.delenv("WFB_FONTS", raising=False)
    (vendor_fonts / "SomeFont.ttf").unlink()
    vendor_fonts.rmdir()

    # 4. ~/.Garmin/ConnectIQ/Fonts (Linux).
    linux_fonts = home / ".Garmin" / "ConnectIQ" / "Fonts"
    linux_fonts.mkdir(parents=True)
    (linux_fonts / "SomeFont.ttf").write_bytes(b"x")
    assert fetch_system.garmin_font_root() == linux_fonts


def test_garmin_font_root_appdata_only_when_set(_isolated, tmp_path, monkeypatch):
    repo_root = tmp_path / "repo"
    home = tmp_path / "home"
    repo_root.mkdir()
    home.mkdir()
    monkeypatch.setattr(fetch_system, "_REPO_ROOT", repo_root)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    monkeypatch.delenv("WFB_FONTS", raising=False)
    monkeypatch.delenv("APPDATA", raising=False)

    assert fetch_system.garmin_font_root() is None

    appdata = tmp_path / "appdata"
    windows_fonts = appdata / "Garmin" / "ConnectIQ" / "Fonts"
    windows_fonts.mkdir(parents=True)
    (windows_fonts / "SomeFont.ttf").write_bytes(b"x")
    monkeypatch.delenv("APPDATA", raising=False)
    assert fetch_system.garmin_font_root() is None  # not consulted without APPDATA set

    monkeypatch.setenv("APPDATA", str(appdata))
    assert fetch_system.garmin_font_root() == windows_fonts


def test_garmin_font_file_is_case_insensitive_and_ttf_otf_only(_isolated, tmp_path):
    root = tmp_path / "fonts"
    sub = root / "nested"
    sub.mkdir(parents=True)
    (root / "RobotoCondensed-Bold.ttf").write_bytes(b"x")
    (sub / "SomeOtf.OTF").write_bytes(b"x")
    (root / "SomeOtf.cft").write_bytes(b"x")

    assert fetch_system.garmin_font_file("robotocondensed-bold", root) == root / "RobotoCondensed-Bold.ttf"
    assert fetch_system.garmin_font_file("ROBOTOCONDENSED-BOLD", root) == root / "RobotoCondensed-Bold.ttf"
    # found recursively, and .otf (any case) counts as usable
    assert fetch_system.garmin_font_file("someotf", root) == sub / "SomeOtf.OTF"


def test_cft_is_reported_but_never_returned_as_a_usable_font(_isolated, tmp_path):
    root = tmp_path / "fonts"
    root.mkdir()
    (root / "BitmapFont.cft").write_bytes(b"x")

    assert fetch_system.garmin_font_file("BitmapFont", root) is None
    assert fetch_system.garmin_cft_file("BitmapFont", root) == root / "BitmapFont.cft"


def test_garmin_file_beats_the_registry_in_locate(_isolated, tmp_path):
    members = _archive_members()
    zip_bytes = _zip_bytes(members)
    _write_registry(_isolated, _registry(members))
    fetch_system._download = _CountingDownloader({ARCHIVE_URL: zip_bytes})  # type: ignore[assignment]

    fonts_root = tmp_path / "garmin-fonts"
    fonts_root.mkdir()
    (fonts_root / "RobotoCondensed-Bold.ttf").write_bytes(b"the real garmin file")

    path, match = fetch_system.locate("RobotoCondensed-Bold", fonts_root=fonts_root)

    assert match == "garmin"
    assert path == fonts_root / "RobotoCondensed-Bold.ttf"
    assert path.read_bytes() == b"the real garmin file"
    # the registry must never even have been reached for this name.
    assert fetch_system._download.calls == []  # type: ignore[attr-defined]


def test_locate_falls_through_to_the_registry_when_no_garmin_root(_isolated, monkeypatch):
    members = _archive_members()
    zip_bytes = _zip_bytes(members)
    _write_registry(_isolated, _registry(members))
    fetch_system._download = _CountingDownloader({ARCHIVE_URL: zip_bytes})  # type: ignore[assignment]
    monkeypatch.delenv("WFB_OFFLINE", raising=False)

    path, match = fetch_system.locate("RobotoCondensed-Bold", fonts_root=None)

    assert match == "exact"
    assert path is not None
    assert path.read_bytes() == members["RobotoCondensed-Bold.ttf"]


def test_locate_reports_none_when_nothing_resolves(_isolated, monkeypatch):
    _write_registry(_isolated, _registry(_archive_members()))
    monkeypatch.setenv("WFB_OFFLINE", "1")

    path, match = fetch_system.locate("TotallyUnknownFontName", fonts_root=None)

    assert path is None
    assert match == "none"


# ---------------------------------------------------------------------------
# device_needed_names()
# ---------------------------------------------------------------------------


def test_device_needed_names_prefers_installed_simulator_json(_isolated, tmp_path):
    devices_root = tmp_path / "Devices"
    device_dir = devices_root / "sometestdevice"
    device_dir.mkdir(parents=True)
    (device_dir / "simulator.json").write_text(json.dumps({
        "fonts": [
            {"fontSet": "ww", "fonts": [
                {"filename": "RobotoCondensed-Bold", "name": "xtiny", "size": 6.4, "type": "ttf"},
                {"filename": "RobotoCondensed-Bold", "name": "tiny", "size": 8.7, "type": "ttf"},
            ]},
            {"fontSet": "apac_jpn", "fonts": [
                {"filename": "Kosugi-Regular", "name": "xtiny", "size": 6.4, "type": "ttf"},
            ]},
        ],
    }), encoding="utf-8")

    names = fetch_system.device_needed_names("sometestdevice", devices_root=devices_root)

    # de-duplicated, ww only, no face (simulator.json carries none).
    assert names == [("RobotoCondensed-Bold", None)]


def test_device_needed_names_falls_back_to_scraped_table(_isolated, tmp_path, monkeypatch):
    scraped_dir = tmp_path / "scraped"
    scraped_dir.mkdir()
    monkeypatch.setattr(fetch_system, "_SCRAPED_DEVICES", scraped_dir)
    (scraped_dir / "sometestdevice.json").write_text(json.dumps({
        "id": "sometestdevice",
        "fonts": {"default": {"fixed": {
            "FONT_XTINY": {"face": "Roboto Condensed", "font": "RobotoCondensed-Bold", "size_px": 21},
            "FONT_TINY": {"face": "Roboto Condensed", "font": "RobotoCondensed-Bold", "size_px": 29},
        }}},
    }), encoding="utf-8")

    names = fetch_system.device_needed_names(
        "sometestdevice", devices_root=tmp_path / "no-such-devices-root"
    )

    assert names == [("RobotoCondensed-Bold", "Roboto Condensed")]


def test_device_needed_names_unknown_device_is_empty(_isolated, tmp_path, monkeypatch):
    monkeypatch.setattr(fetch_system, "_SCRAPED_DEVICES", tmp_path / "no-such-dir")
    assert fetch_system.device_needed_names(
        "nope", devices_root=tmp_path / "also-no-such-dir"
    ) == []
