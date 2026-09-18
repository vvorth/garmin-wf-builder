"""wfb/fonts/registry.json resolves every system-font name in scope.

Scope (plan 09 R0, section 3): every
``(face, font)`` pair in the *default* language's ``fixed`` and ``scalable``
tables of every device in ``docs/research/data/devices/*.json`` (164 devices
at the time this was written -- ``wfb.devices.Device.system_fonts`` reads
this same ``fonts["default"]["fixed"]`` key, see ``wfb/devices.py``), plus
every ``filename`` in the ``fontSet == "ww"`` entry of every *installed*
device's ``~/.Garmin/ConnectIQ/Devices/<id>/simulator.json`` (13 devices when
this was written; skipped entirely if the directory does not exist -- device
definitions are the user's licensed copy, not committed, per ``CLAUDE.md``
§2).

No network: this only reads the registry and the two data sources above.
Resolution order matches the registry's own docstring (its top-level
``comment``): ``names`` (exact) -> ``patterns`` (ordered, first match wins)
-> ``faces`` (last resort, only available for the scraped source, which
carries a ``face`` column; the installed ``simulator.json`` ``filename``s do
not). A name that resolves none of those three ways must instead appear,
explicitly, in the registry's ``unmapped`` list (keyed by ``face`` or by
``name``) -- so this test can tell "the registry forgot this name" apart
from "a human already decided this name stays unmapped, and said why."
"""

from __future__ import annotations

import glob
import json
import os
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
REGISTRY_PATH = ROOT / "wfb" / "fonts" / "registry.json"
SCRAPED_DEVICES = ROOT / "docs" / "research" / "data" / "devices"
SIMULATOR_ROOTS = (
    Path.home() / ".Garmin" / "ConnectIQ" / "Devices",
    Path.home() / "Library" / "Application Support" / "Garmin" / "ConnectIQ" / "Devices",
)


@pytest.fixture(scope="module")
def registry() -> dict:
    return json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))


class Resolver:
    """The same three-layer lookup the registry's own comment documents."""

    def __init__(self, registry: dict):
        self.names: dict[str, str] = registry["names"]
        self.patterns: list[tuple[re.Pattern, str]] = [
            (re.compile(p["regex"]), p["key"]) for p in registry["patterns"]
        ]
        self.faces: dict[str, str] = registry["faces"]
        self.unmapped_faces = {u["face"] for u in registry["unmapped"] if "face" in u}
        self.unmapped_names = {u["name"] for u in registry["unmapped"] if "name" in u}

    def resolve(self, name: str, face: str | None = None) -> str | None:
        if name in self.names:
            return self.names[name]
        for regex, key in self.patterns:
            if regex.search(name):
                return key
        if face is not None and face in self.faces:
            return self.faces[face]
        return None

    def is_deliberately_unmapped(self, name: str, face: str | None) -> bool:
        if face is not None and face in self.unmapped_faces:
            return True
        return name in self.unmapped_names


@pytest.fixture(scope="module")
def resolver(registry: dict) -> Resolver:
    return Resolver(registry)


def _scraped_default_pairs() -> list[tuple[str, str, str, str]]:
    """``(device_id, table, face, font)`` for every default-language entry."""
    pairs = []
    for path in sorted(glob.glob(str(SCRAPED_DEVICES / "*.json"))):
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        default = data.get("fonts", {}).get("default", {})
        for table in ("fixed", "scalable"):
            for symbol, entry in default.get(table, {}).items():
                face = entry.get("face", "")
                font = entry.get("font", "")
                if font:
                    pairs.append((data["id"], table, face, font))
    return pairs


def _installed_ww_filenames() -> list[tuple[str, str]]:
    """``(device_id, filename)`` for every installed device's ``ww`` font set."""
    for root in SIMULATOR_ROOTS:
        if root.is_dir():
            break
    else:
        return []
    out = []
    for device_id in sorted(os.listdir(root)):
        sim_path = root / device_id / "simulator.json"
        if not sim_path.is_file():
            continue
        sim = json.loads(sim_path.read_text(encoding="utf-8"))
        for entry in sim.get("fonts", []):
            if entry.get("fontSet") != "ww":
                continue
            for font in entry.get("fonts", []):
                out.append((device_id, font["filename"]))
    return out


# ---------------------------------------------------------------------------
# structural checks on the registry itself
# ---------------------------------------------------------------------------


def test_registry_has_the_documented_top_level_shape(registry):
    for key in ("version", "comment", "sources", "fonts", "names", "patterns", "faces", "unmapped"):
        assert key in registry, f"registry.json is missing top-level key {key!r}"
    assert isinstance(registry["version"], int)
    assert registry["comment"]


def test_every_font_key_references_a_real_source(registry):
    for key, info in registry["fonts"].items():
        source_id = info["source"]
        assert source_id in registry["sources"], f"font {key!r} references missing source {source_id!r}"
        assert info["match"] in ("exact", "family", "substitute", "none")


def test_every_source_sha256_is_64_hex_characters(registry):
    hex_digits = set("0123456789abcdef")
    for source_id, info in registry["sources"].items():
        sha = info["sha256"]
        assert len(sha) == 64, f"source {source_id!r} sha256 {sha!r} is not 64 characters"
        assert set(sha.lower()) <= hex_digits, f"source {source_id!r} sha256 {sha!r} is not hex"
        assert isinstance(info["size"], int) and info["size"] > 0
        assert info["url"], f"source {source_id!r} has no url"
        assert info["url"] != "main" and "/main/" not in info["url"], (
            f"source {source_id!r} url looks pinned to a moving branch, not a tag/commit"
        )
        assert info.get("license"), f"source {source_id!r} has no license"


def test_every_name_and_pattern_and_face_key_is_a_real_font(registry):
    fonts = set(registry["fonts"])
    for name, key in registry["names"].items():
        assert key in fonts, f"names[{name!r}] points at unknown font {key!r}"
    for entry in registry["patterns"]:
        assert entry["key"] in fonts, f"pattern {entry['regex']!r} points at unknown font {entry['key']!r}"
    for face, key in registry["faces"].items():
        assert key in fonts, f"faces[{face!r}] points at unknown font {key!r}"


def test_unmapped_entries_each_have_a_reason(registry):
    for entry in registry["unmapped"]:
        assert "face" in entry or "name" in entry, f"unmapped entry {entry!r} has neither face nor name"
        assert entry.get("reason"), f"unmapped entry {entry!r} has no reason"


# ---------------------------------------------------------------------------
# coverage: every name in scope resolves, or is explicitly unmapped
# ---------------------------------------------------------------------------


def test_every_scraped_default_face_font_pair_resolves_or_is_unmapped(resolver):
    pairs = _scraped_default_pairs()
    assert len(pairs) > 400, "sanity check: expected hundreds of scraped (face, font) rows"
    forgotten = []
    for device_id, table, face, font in pairs:
        key = resolver.resolve(font, face)
        if key is None and not resolver.is_deliberately_unmapped(font, face):
            forgotten.append((device_id, table, face, font))
    assert not forgotten, (
        f"{len(forgotten)} scraped (face, font) pairs neither resolve nor are listed as "
        f"unmapped, e.g. {forgotten[:10]}"
    )


def test_every_installed_ww_filename_resolves_or_is_unmapped(resolver):
    filenames = _installed_ww_filenames()
    if not filenames:
        pytest.skip("no ~/.Garmin/ConnectIQ/Devices installed")
    forgotten = []
    for device_id, filename in filenames:
        key = resolver.resolve(filename, face=None)
        if key is None and not resolver.is_deliberately_unmapped(filename, face=None):
            forgotten.append((device_id, filename))
    assert not forgotten, (
        f"{len(forgotten)} installed ww filenames neither resolve nor are listed as "
        f"unmapped, e.g. {forgotten[:10]}"
    )


def test_resolution_order_is_name_then_pattern_then_face(registry):
    """A name present in more than one layer must prefer the earliest one.

    This does not assert on the real registry's content (which layer a real
    name happens to hit is incidental); it proves the *resolver* -- the same
    one the coverage tests above use -- actually honours the documented
    priority, with a synthetic registry built to force all three layers to
    disagree.
    """
    fake = {
        "names": {"exact-hit": "key-from-name"},
        "patterns": [{"regex": "^exact-hit$", "key": "key-from-pattern"}, {"regex": "^pattern-hit$", "key": "key-from-pattern"}],
        "faces": {"some-face": "key-from-face"},
        "unmapped": [],
    }
    r = Resolver(fake)
    assert r.resolve("exact-hit", face="some-face") == "key-from-name"
    assert r.resolve("pattern-hit", face="some-face") == "key-from-pattern"
    assert r.resolve("unknown-name", face="some-face") == "key-from-face"
    assert r.resolve("unknown-name", face=None) is None


def test_a_face_only_present_in_the_scalable_table_can_stay_unmapped(registry):
    """The plan explicitly allows CJK/Thai/Arabic/Hebrew/Armenian-only faces,
    which appear only in the multi-script `scalable` table, to stay unmapped
    because default-language measurement never uses them. Pin a couple down
    by name so a future edit that quietly deletes them is caught here rather
    than only by the aggregate coverage test above.
    """
    unmapped_faces = {u["face"] for u in registry["unmapped"] if "face" in u}
    for face in ("Noto Sans SC", "Noto Naskh Arabic", "Noto Sans Hebrew", "Noto Sans Armenian", "Pridi"):
        assert face in unmapped_faces, f"{face!r} is expected to be a documented, deliberate non-mapping"


def test_a_substitute_match_says_so(registry):
    """Bionic is proprietary; its stand-in must be labelled a substitute, not exact."""
    bionic_key = registry["faces"]["Bionic"]
    assert registry["fonts"][bionic_key]["match"] in ("substitute", "family")
