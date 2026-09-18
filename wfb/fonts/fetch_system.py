"""``wfb/fonts/registry.json``-driven fetch/cache for Garmin's system fonts.

Garmin's own system-font files are proprietary and cannot be downloaded
(``docs/research/10-system-fonts.md``), so this module fetches and caches
**free stand-ins**: ``wfb/fonts/registry.json`` maps every system-font name
this project knows about (an ``exact``/``family``/``substitute`` match, or
deliberately ``none``) to a pinned, hash-checked, freely-licensed TTF. See
``docs/plans/09-system-font-metrics.md`` (R1, R1b) and
``docs/research/10-system-fonts.md`` for the mapping rationale.

**Standard library only, and no import of the ``wfb`` package or of
Pillow.** That is what lets ``tools/fetch-system-fonts.py`` load this file
directly (``importlib.util.spec_from_file_location``) and run it before the
virtualenv exists, in the Docker build stage, and in ``wfb doctor`` without
ever needing a rasteriser just to check what is installed. ``urllib``
honours ``https_proxy`` and the system trust store, exactly like
``tools/fetch-icon-font.py``, whose shape this module follows.

Three groups of functionality:

* **Name resolution** (:func:`resolve`) -- pure, reads only ``registry.json``.
* **Fetch/cache** (:func:`path_for`, :func:`ensure`, :func:`install`) -- a
  font-key's TTF, downloaded on demand into
  ``${XDG_CACHE_HOME:-~/.cache}/wfb/fonts/<key>.ttf``, or found already
  installed at ``wfb/assets/system-fonts/<key>.ttf`` (what a prefetch fills).
  ``WFB_OFFLINE=1`` stops any of this from ever reaching the network --
  ``tests/conftest.py`` sets it for the whole test session.
* **Garmin's own font files** (:func:`garmin_font_root`,
  :func:`garmin_font_file`, :func:`garmin_cft_file`) -- the user's own
  licensed copy of Garmin's real fonts, which rank above the registry when
  present (plan 09 R1b). :func:`locate` puts all of the above together into
  the one lookup Step B calls.

    python3 tools/fetch-system-fonts.py [--device ID ...] [--all] [DEST]

``WFB_FONTS_MIRROR`` overrides every source URL's scheme+host (for a
mirror that reproduces the same paths); see :func:`_mirrored`.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import re
import sys
import time
import urllib.request
import zipfile
from functools import lru_cache
from pathlib import Path
from typing import Iterable
from urllib.parse import urlsplit, urlunsplit

_HERE = Path(__file__).resolve().parent
_REPO_ROOT = _HERE.parent.parent

#: The registry this whole module is driven by. A module-level path (rather
#: than a hard-coded read inside every function) so tests can point it at a
#: fake registry with ``monkeypatch.setattr``.
REGISTRY_PATH = _HERE / "registry.json"

#: Where a prefetch (``tools/fetch-system-fonts.py``, ``setup-env.sh``, the
#: Dockerfile) installs to, and the first place `path_for`/`ensure` look.
DEFAULT_DEST = _REPO_ROOT / "wfb" / "assets" / "system-fonts"

#: This project's three build targets (root ``CLAUDE.md`` §1) -- also the
#: default device set ``tools/fetch-system-fonts.py`` prefetches fonts for.
DEFAULT_TARGET_DEVICES = ("fenix8solar47mm", "fenix8solar51mm", "fr955")

_SCRAPED_DEVICES = _REPO_ROOT / "docs" / "research" / "data" / "devices"

#: Mirrors ``wfb.devices.DEFAULT_DEVICE_ROOTS``. Duplicated, not imported --
#: this module must stay stdlib-only and loadable by file path before the
#: ``wfb`` package (or Pillow) is installed.
_DEFAULT_DEVICE_ROOTS = (
    Path.home() / ".Garmin" / "ConnectIQ" / "Devices",
    Path.home() / "Library" / "Application Support" / "Garmin" / "ConnectIQ" / "Devices",
)

_registry_cache: dict[Path, dict] = {}

#: URLs already attempted (successfully or not) this process, so an archive
#: shared by several font-keys is downloaded at most once even when several
#: sibling keys each call :func:`ensure` -- and a failed download is not
#: retried for every subsequent glyph a build measures.
_attempted_urls: set[str] = set()


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _note(message: str) -> None:
    print(f"note: {message}", file=sys.stderr)


def _registry() -> dict:
    if REGISTRY_PATH not in _registry_cache:
        _registry_cache[REGISTRY_PATH] = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
    return _registry_cache[REGISTRY_PATH]


def _keys_by_source(registry: dict) -> dict[str, list[str]]:
    """source-id -> every font-key that uses it. Several keys can share one
    source (every ``*-substitute`` key points at a real family's source), so
    downloading a source once must materialise all of them."""
    out: dict[str, list[str]] = {}
    for key, info in registry.get("fonts", {}).items():
        out.setdefault(info["source"], []).append(key)
    return out


# ---------------------------------------------------------------------------
# name resolution -- pure, no filesystem beyond registry.json, no network
# ---------------------------------------------------------------------------


def resolve(name: str, face: str | None = None) -> str | None:
    """``name`` (a ``simulator.json`` ``filename`` or a scraped ``font``) ->
    a registry font-key, or ``None``.

    Resolution order -- an exact ``names`` hit, then the first matching
    (ordered) ``patterns`` regex, then, only when ``face`` is given, the
    ``faces`` table -- is the same order ``tests/test_font_registry.py``'s
    own ``Resolver`` checks the committed registry against; this is the
    "real" implementation the schema's own docstring documents.
    """
    registry = _registry()
    names = registry.get("names", {})
    if name in names:
        return names[name]
    for entry in registry.get("patterns", []):
        if re.search(entry["regex"], name):
            return entry["key"]
    if face is not None:
        faces = registry.get("faces", {})
        if face in faces:
            return faces[face]
    return None


# ---------------------------------------------------------------------------
# cache / install locations -- no network
# ---------------------------------------------------------------------------


def cache_dir() -> Path:
    """``${XDG_CACHE_HOME:-~/.cache}/wfb/fonts`` -- the runtime cache
    :func:`ensure` downloads into."""
    base = os.environ.get("XDG_CACHE_HOME")
    root = Path(base) if base else Path.home() / ".cache"
    return root / "wfb" / "fonts"


def path_for(key: str) -> Path | None:
    """Where ``key``'s TTF already is, installed or cached. Never touches
    the network -- that is :func:`ensure`'s job. Checks the install
    location (:data:`DEFAULT_DEST`, what a prefetch fills) before the
    runtime cache."""
    for base in (DEFAULT_DEST, cache_dir()):
        candidate = base / f"{key}.ttf"
        if candidate.is_file():
            return candidate
    return None


def tier_for(key: str) -> str | None:
    """``"installed"``, ``"cached"``, or ``None`` -- like :func:`path_for`
    but names *which* of the two locations held ``key``, for ``wfb
    doctor``."""
    if (DEFAULT_DEST / f"{key}.ttf").is_file():
        return "installed"
    if (cache_dir() / f"{key}.ttf").is_file():
        return "cached"
    return None


# ---------------------------------------------------------------------------
# downloading
# ---------------------------------------------------------------------------


def _mirrored(url: str) -> str:
    """``url`` with its scheme+host swapped for ``WFB_FONTS_MIRROR``, if
    set -- e.g. an internal mirror that reproduces the same paths
    (``github.com/...`` -> ``mirror.example/...``). Documented in
    ``docs/container.md``/``docs/lore/toolchain.md``; left unset, every URL
    is used exactly as pinned in ``registry.json``."""
    mirror = os.environ.get("WFB_FONTS_MIRROR")
    if not mirror:
        return url
    parsed = urlsplit(url)
    mirror_parsed = urlsplit(mirror if "//" in mirror else f"//{mirror}")
    return urlunsplit((mirror_parsed.scheme or parsed.scheme, mirror_parsed.netloc,
                        parsed.path, parsed.query, parsed.fragment))


def _default_download(url: str, attempts: int = 3) -> bytes:
    for attempt in range(1, attempts + 1):
        try:
            with urllib.request.urlopen(_mirrored(url), timeout=120) as response:
                return response.read()
        except OSError:
            if attempt == attempts:
                raise
            time.sleep(2 * attempt)
    raise AssertionError("unreachable")


#: Swappable hook -- tests monkeypatch this name directly
#: (``monkeypatch.setattr(fetch_system, "_download", fake)``) rather than
#: threading a ``downloader`` parameter through every call.
_download = _default_download


def _extract_member(data: bytes, member: str) -> bytes:
    """``member``'s bytes out of the zip archive ``data``.

    Matches by exact archive path first, then by basename, so a member name
    like ``RobotoCondensed-Bold.ttf`` still resolves when the real release
    zip nests everything under a version subdirectory; ``__MACOSX/``
    resource-fork junk is skipped either way (the same shape the earlier
    Roboto-only fetch module used). Raises ``ValueError`` if ``member`` is
    nowhere in the archive, or lets ``zipfile.BadZipFile`` propagate if
    ``data`` is not a zip at all -- the two ways a corrupted download fails.
    """
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        infos = [i for i in archive.infolist() if not i.is_dir()]
        for info in infos:
            if info.filename == member:
                return archive.read(info)
        basename = member.rsplit("/", 1)[-1]
        for info in infos:
            if "__MACOSX" in info.filename.split("/"):
                continue
            if info.filename.rsplit("/", 1)[-1] == basename:
                return archive.read(info)
    raise ValueError(f"archive does not contain {member!r}")


def _write_atomic(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_name(f".{path.name}.partial")
    partial.write_bytes(data)
    partial.replace(path)


def _license_text(source: dict) -> str:
    lines = [source.get("license", "unknown license")]
    if source.get("license_url"):
        lines.append(f"license: {source['license_url']}")
    lines.append(f"font source: {source['url']}")
    return "\n".join(lines) + "\n"


def _materialise_group(registry: dict, url: str, data: bytes) -> dict[str, bytes]:
    """Every source sharing ``url``'s verified bytes, keyed by source id.

    All-or-nothing: raises before returning anything if any member in the
    group fails its pinned SHA-256 (or is missing from the archive), so a
    caller never has to unwind a partial write -- one bad entry refuses the
    whole download rather than silently installing the rest. A source with
    no ``member`` is a direct single-file download: ``data`` itself is
    checked and used as-is.
    """
    out: dict[str, bytes] = {}
    for source_id, source in registry.get("sources", {}).items():
        if source["url"] != url:
            continue
        member = source.get("member")
        content = _extract_member(data, member) if member else data
        if sha256(content) != source["sha256"]:
            raise ValueError(f"{source_id!r} does not match its pinned SHA-256")
        out[source_id] = content
    return out


def ensure(key: str) -> Path | None:
    """:func:`path_for` (``key``), downloading into the runtime cache first
    if nothing is there yet.

    **Never raises.** An unknown key, ``WFB_OFFLINE=1``, a network failure
    or a hash mismatch each return ``None`` -- the network/hash failures
    also print one ``note:`` line to stderr -- so a caller falls back to
    Pillow's bundled face rather than failing a build over a font it can
    live without. At most one download attempt is made per *URL* per
    process: an archive shared by several font-keys (the Roboto release,
    DejaVu) is downloaded once and every font-key that needs a member of it
    is written out in the same pass, so a sibling key's own ``ensure`` call
    afterwards is a cache hit, never a second download -- and a failed
    download is not retried for every subsequent glyph a build measures.
    """
    try:
        registry = _registry()
        fonts = registry.get("fonts", {})
        if key not in fonts:
            return None

        cached = path_for(key)
        if cached is not None:
            return cached

        if os.environ.get("WFB_OFFLINE") == "1":
            return None

        source_id = fonts[key]["source"]
        sources = registry.get("sources", {})
        if source_id not in sources:
            _note(f"font {key!r} references unknown source {source_id!r}")
            return None
        url = sources[source_id]["url"]

        if url in _attempted_urls:
            # Either the download already succeeded (this key is a cache
            # miss only because it aliases a source that failed its own
            # check) or it already failed -- either way, do not retry.
            return path_for(key)
        _attempted_urls.add(url)

        try:
            data = _download(url)
        except OSError as exc:
            _note(f"could not download {url} for font {key!r} ({exc}); "
                  "falling back to a substitute face")
            return None

        try:
            materialised = _materialise_group(registry, url, data)
        except (ValueError, zipfile.BadZipFile) as exc:
            _note(f"{url} did not verify ({exc}); font {key!r} not installed")
            return None

        dest = cache_dir()
        reverse = _keys_by_source(registry)
        for materialised_source_id, content in materialised.items():
            for aliased_key in reverse.get(materialised_source_id, ()):
                _write_atomic(dest / f"{aliased_key}.ttf", content)
            _write_atomic(
                dest / f"{materialised_source_id}.LICENSE.txt",
                _license_text(sources[materialised_source_id]).encode("utf-8"),
            )

        return path_for(key)
    except Exception as exc:  # noqa: BLE001 -- must never raise into a build/preview
        _note(f"unexpected error fetching font {key!r} ({exc}); "
              "falling back to a substitute face")
        return None


def install(keys: Iterable[str], dest: os.PathLike | str) -> dict[str, bool]:
    """Prefetch every key in ``keys`` into ``dest``
    (``tools/fetch-system-fonts.py``, ``setup-env.sh``, the Dockerfile).

    Calls :func:`ensure` for each key first -- which is what actually
    reaches the network, and already deduplicates an archive shared by
    several keys -- then copies the verified bytes, and the source's
    licence file, from wherever ``ensure`` placed them into ``dest``.
    Returns ``{key: True/False}``; a ``False`` entry has already had its
    reason printed to stderr by ``ensure`` (or, for an unknown key, is
    simply absent from the registry).
    """
    dest_path = Path(dest)
    registry = _registry()
    result: dict[str, bool] = {}
    for key in keys:
        source_path = ensure(key)
        if source_path is None:
            result[key] = False
            continue
        try:
            target = dest_path / f"{key}.ttf"
            if target.resolve() != source_path.resolve():
                _write_atomic(target, source_path.read_bytes())
            source_id = registry["fonts"][key]["source"]
            license_src = source_path.with_name(f"{source_id}.LICENSE.txt")
            if license_src.is_file():
                license_dst = dest_path / license_src.name
                if license_dst.resolve() != license_src.resolve():
                    _write_atomic(license_dst, license_src.read_bytes())
            result[key] = True
        except OSError as exc:
            _note(f"could not install font {key!r} into {dest_path} ({exc})")
            result[key] = False
    return result


# ---------------------------------------------------------------------------
# Garmin's own font files (docs/plans/09-system-font-metrics.md R1b)
# ---------------------------------------------------------------------------


def garmin_font_root(override: os.PathLike | str | None = None) -> Path | None:
    """The Garmin SDK Manager's own ``Fonts`` directory. The first existing,
    non-empty candidate wins, in this order (plan 09 R1b.2, mirroring
    ``wfb.devices.DEFAULT_DEVICE_ROOTS``'s own shape):

    1. ``override`` (a CLI ``--fonts``);
    2. ``WFB_FONTS``;
    3. ``<repo>/vendor/fonts/`` (gitignored -- the user's own licensed copy,
       ``vendor/devices/``'s sibling);
    4. ``~/.Garmin/ConnectIQ/Fonts`` (Linux);
    5. ``~/Library/Application Support/Garmin/ConnectIQ/Fonts`` (macOS);
    6. ``%APPDATA%\\Garmin\\ConnectIQ\\Fonts`` (Windows, only when
       ``APPDATA`` is set).

    ``None`` if none of them exist or all are empty -- this whole lookup is
    optional; the registry (:func:`ensure`) and Pillow's own fallback both
    still work without it.
    """
    candidates: list[Path] = []
    if override:
        candidates.append(Path(override))
    env = os.environ.get("WFB_FONTS")
    if env:
        candidates.append(Path(env))
    candidates.append(_REPO_ROOT / "vendor" / "fonts")
    candidates.append(Path.home() / ".Garmin" / "ConnectIQ" / "Fonts")
    candidates.append(Path.home() / "Library" / "Application Support" / "Garmin" / "ConnectIQ" / "Fonts")
    appdata = os.environ.get("APPDATA")
    if appdata:
        candidates.append(Path(appdata) / "Garmin" / "ConnectIQ" / "Fonts")
    for path in candidates:
        if path.is_dir() and any(path.iterdir()):
            return path
    return None


@lru_cache(maxsize=8)
def _font_index(root: Path) -> dict[str, list[Path]]:
    """Case-insensitive file stem -> every file under ``root`` with that
    stem, built once per root and cached -- :func:`garmin_font_file`/
    :func:`garmin_cft_file` are called once per system-font name a build
    resolves, and walking the whole Fonts directory (potentially hundreds
    of files) for each one would be wasteful.
    """
    index: dict[str, list[Path]] = {}
    for path in root.rglob("*"):
        if path.is_file():
            index.setdefault(path.stem.lower(), []).append(path)
    return index


def garmin_font_file(name: str, root: Path) -> Path | None:
    """A ``.ttf``/``.otf`` under ``root`` (searched recursively) whose file
    stem matches ``name`` case-insensitively.

    Generic on purpose: the exact mapping from a ``simulator.json``
    ``filename`` to the file actually on disk inside Garmin's own Fonts
    directory is unresearched (plan 09 R1b.4), deferred until
    ``vendor/fonts/`` is populated and can be inspected. Only these two
    extensions are usable as a font today; a ``.cft`` match is reported
    separately (:func:`garmin_cft_file`) but never returned here --
    decoding that format is also deferred (R1b.5).
    """
    for path in _font_index(root).get(name.lower(), ()):
        if path.suffix.lower() in (".ttf", ".otf"):
            return path
    return None


def garmin_cft_file(name: str, root: Path) -> Path | None:
    """A ``.cft`` under ``root`` matching ``name`` -- reported for
    diagnostics (``wfb doctor``) but never treated as a usable font: `.cft`
    is a Garmin bitmap-font container format, and decoding it is deferred
    (plan 09 R1b.5) until a device's Fonts directory can be inspected."""
    for path in _font_index(root).get(name.lower(), ()):
        if path.suffix.lower() == ".cft":
            return path
    return None


def locate(name: str, face: str | None = None,
           *, fonts_root: os.PathLike | str | None = None) -> tuple[Path | None, str]:
    """The one top-level lookup Step B calls for a real font file behind a
    system-font name: the Garmin font root first (match ``"garmin"``, which
    outranks even an ``exact`` registry match -- it is the device's own
    file), then the registry (:func:`ensure`, downloading/caching on
    demand), else ``(None, "none")`` -- Pillow's bundled face is the
    caller's own fallback in that case. ``fonts_root`` is passed straight to
    :func:`garmin_font_root` (a CLI ``--fonts`` override).
    """
    root = garmin_font_root(fonts_root)
    if root is not None:
        found = garmin_font_file(name, root)
        if found is not None:
            return found, "garmin"

    key = resolve(name, face)
    if key is not None:
        path = ensure(key)
        if path is not None:
            match = _registry()["fonts"][key]["match"]
            return path, match

    return None, "none"


# ---------------------------------------------------------------------------
# what a device needs (docs/plans/09-system-font-metrics.md R1.3)
# ---------------------------------------------------------------------------


def _installed_devices_root(override: os.PathLike | str | None = None) -> Path | None:
    """Mirrors ``wfb.devices.DeviceDatabase.discover``'s search order,
    without importing ``wfb`` (this module must stay stdlib-only)."""
    candidates: list[Path] = []
    if override:
        candidates.append(Path(override))
    env = os.environ.get("WFB_DEVICES")
    if env:
        candidates.append(Path(env))
    candidates.extend(_DEFAULT_DEVICE_ROOTS)
    for path in candidates:
        if path.is_dir() and any(path.iterdir()):
            return path
    return None


def device_needed_names(device_id: str,
                         *, devices_root: os.PathLike | str | None = None,
                         ) -> list[tuple[str, str | None]]:
    """Every ``(name, face)`` pair ``device_id`` needs a system font for --
    ``name`` first (a ``simulator.json`` ``filename`` or scraped ``font``,
    what :func:`resolve`/:func:`garmin_font_file` take), ``face`` second
    (``None`` from the installed path, which carries no ``face`` column).

    Prefers the installed device's own ``simulator.json`` ``ww`` font set;
    falls back to the scraped default-language ``fixed`` table
    (``docs/research/data/devices/<id>.json``) when the device is not
    installed, or has no ``ww`` entries. Never touches the network. Order is
    the device's own table order, first occurrence of a repeated name kept.
    """
    root = _installed_devices_root(devices_root)
    if root is not None:
        sim_path = root / device_id / "simulator.json"
        if sim_path.is_file():
            sim = json.loads(sim_path.read_text(encoding="utf-8"))
            seen: set[str] = set()
            names: list[tuple[str, str | None]] = []
            for block in sim.get("fonts", []):
                if block.get("fontSet") != "ww":
                    continue
                for entry in block.get("fonts", []):
                    name = entry.get("filename")
                    if name and name not in seen:
                        seen.add(name)
                        names.append((name, None))
            if names:
                return names

    scraped_path = _SCRAPED_DEVICES / f"{device_id}.json"
    if scraped_path.is_file():
        data = json.loads(scraped_path.read_text(encoding="utf-8"))
        fixed = data.get("fonts", {}).get("default", {}).get("fixed", {})
        seen = set()
        out: list[tuple[str, str | None]] = []
        for entry in fixed.values():
            name = entry.get("font")
            if name and name not in seen:
                seen.add(name)
                out.append((name, entry.get("face")))
        return out

    return []


def all_scraped_device_ids() -> list[str]:
    """Every device id ``docs/research/data/devices/*.json`` has a file for
    (164 at the time plan 09's research was written) -- what ``--all`` in
    ``tools/fetch-system-fonts.py`` prefetches fonts for."""
    return sorted(path.stem for path in _SCRAPED_DEVICES.glob("*.json"))
