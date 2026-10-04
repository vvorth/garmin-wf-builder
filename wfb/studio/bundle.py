"""A face as the editor moves it in and out: a design's text plus the files
it references, opened by upload and saved by download.

The format is a `.zip` with the face at its root (`face.yaml` by
convention) and its files beneath it, `assets/` by convention, or a plain
`.yaml` when the face references no file.  The only file a design
references is a baked font's `resources.fonts.<name>.source`, relative to
the design (the schema's `bakedFont`).

Every path in a bundle is checked before anything is extracted: no
absolute path, no `..`, no link, and the uncompressed sizes within limits
(a zip bomb declares them honestly or fails the read).
"""

from __future__ import annotations

import io
import re
import stat
import zipfile
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any

from ..edit.spans import Path as AuthorPath
from ..edit.spans import index_for

#: The design's name inside a bundle and in every document's directory.
FACE = "face.yaml"
#: Where an asset added in the editor goes.
ASSETS = "assets"

MAX_UPLOAD_BYTES = 32 * 1024 * 1024
MAX_UNPACKED_BYTES = 64 * 1024 * 1024
MAX_ENTRIES = 512

#: Archive litter a desktop zip tool adds; skipped, never refused.
_LITTER = re.compile(r"(^|/)(__MACOSX/|\.DS_Store$|Thumbs\.db$)")


class BundleError(ValueError):
    """An upload that cannot be opened; the message says why, for the author."""


@dataclass
class Bundle:
    """A face's text, its display name and its files, by bundle-relative
    POSIX path (the design itself not among them)."""

    name: str
    text: str
    files: dict[str, bytes] = field(default_factory=dict)


@dataclass(frozen=True)
class Reference:
    """One file a design names: the font, the author path of its `source:`
    value, and the value as written."""

    font: str
    path: AuthorPath
    value: str

    @property
    def inside(self) -> str | None:
        """The bundle-relative path it names, or ``None`` when it points
        outside the bundle (absolute, or climbing out with `..`)."""
        return inside(self.value)


def inside(value: str) -> str | None:
    """``value`` as a normalised bundle-relative path, or ``None`` when it
    would leave the bundle."""
    if not value or "\\" in value or value.startswith("/") or re.match(r"^[A-Za-z]:", value):
        return None
    parts: list[str] = []
    for part in PurePosixPath(value).parts:
        if part == "..":
            if not parts:
                return None
            parts.pop()
        elif part != ".":
            parts.append(part)
    return "/".join(parts) or None


def references(text: str) -> list[Reference]:
    """Every file ``text`` references, in document order.  A text that does
    not parse references nothing (the gate reports why it does not)."""
    try:
        index = index_for(text)
    except ValueError:
        return []
    data: Any = index.data
    fonts = data.get("resources", {}).get("fonts", {}) if isinstance(data, dict) else {}
    out = []
    if isinstance(fonts, dict):
        for name, spec in fonts.items():
            if isinstance(spec, dict) and isinstance(spec.get("source"), str):
                out.append(Reference(str(name), ("resources", "fonts", str(name), "source"),
                                     spec["source"]))
    return out


def missing(text: str, files: dict[str, Any]) -> list[Reference]:
    """The references whose file the bundle does not hold."""
    return [r for r in references(text) if r.inside is None or r.inside not in files]


# -- in -------------------------------------------------------------------------------

def display_name(filename: str, text: str | None = None) -> str:
    """The face's own `face: name:` when ``text`` has one, the file's stem
    otherwise."""
    if text is not None:
        try:
            data = index_for(text).data
        except ValueError:
            data = None
        face = data.get("face") if isinstance(data, dict) else None
        if isinstance(face, dict) and isinstance(face.get("name"), str) and face["name"].strip():
            return str(face["name"]).strip()
    stem = PurePosixPath(filename.replace("\\", "/")).name
    for suffix in (".zip", ".yaml", ".yml"):
        if stem.lower().endswith(suffix):
            stem = stem[: -len(suffix)]
    return stem or "face"


def _decode(data: bytes, what: str) -> str:
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise BundleError(f"{what} is not UTF-8 text") from None


def read_upload(filename: str, data: bytes) -> Bundle:
    """An uploaded `.yaml`/`.yml` or `.zip`, checked and unpacked."""
    if len(data) > MAX_UPLOAD_BYTES:
        raise BundleError(f"the upload is over {MAX_UPLOAD_BYTES // (1024 * 1024)} MB")
    lower = filename.lower()
    if lower.endswith((".yaml", ".yml")):
        text = _decode(data, filename)
        return Bundle(display_name(filename, text), text)
    if lower.endswith(".zip"):
        bundle = _read_zip(display_name(filename), data)
        bundle.name = display_name(filename, bundle.text)
        return bundle
    raise BundleError(f"{filename!r} is neither a .yaml nor a .zip")


def _read_zip(name: str, data: bytes) -> Bundle:
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        raise BundleError("the upload is not a readable .zip") from None
    with archive:
        infos = [i for i in archive.infolist() if not _LITTER.search(i.filename)]
        if len(infos) > MAX_ENTRIES:
            raise BundleError(f"the bundle has {len(infos)} entries; at most {MAX_ENTRIES}")
        if sum(i.file_size for i in infos) > MAX_UNPACKED_BYTES:
            raise BundleError(
                f"the bundle unpacks to over {MAX_UNPACKED_BYTES // (1024 * 1024)} MB")
        entries: dict[str, zipfile.ZipInfo] = {}
        for info in infos:
            if stat.S_ISLNK(info.external_attr >> 16):
                raise BundleError(f"{info.filename} is a link; a bundle holds plain files only")
            if info.is_dir():
                continue
            path = inside(info.filename)
            if path is None:
                raise BundleError(f"{info.filename} points outside the bundle")
            entries[path] = info
        entries = _unwrapped(entries)
        faces = [p for p in entries if "/" not in p and p.lower().endswith((".yaml", ".yml"))]
        if not faces:
            raise BundleError("the bundle has no .yaml at its root")
        if len(faces) > 1:
            if FACE not in faces:
                raise BundleError("the bundle has more than one .yaml at its root: "
                                  + ", ".join(sorted(faces)) + f"; name the face {FACE}")
            faces = [FACE]
        face = faces[0]
        files: dict[str, bytes] = {}
        for path, info in entries.items():
            if path == face:
                continue
            files[path] = archive.read(info)
        text = _decode(archive.read(entries[face]), face)
    return Bundle(name, text, files)


def _unwrapped(entries: dict[str, zipfile.ZipInfo]) -> dict[str, zipfile.ZipInfo]:
    """A zip of a folder (`myface/face.yaml`, what a desktop "compress"
    makes) read as the folder's contents."""
    if any("/" not in p for p in entries):
        return entries
    tops = {p.split("/", 1)[0] for p in entries}
    if len(tops) != 1:
        return entries
    return {p.split("/", 1)[1]: info for p, info in entries.items()}


def from_path(design: Path) -> tuple[Bundle, dict[str, str]]:
    """A design on disk and the files it references, read as an upload
    would be.

    A referenced file inside the design's directory keeps its relative
    path; one outside it is copied under `assets/`.  The second value maps
    each such reference's written value to the path it now has, for the
    caller to patch as a recorded change.  A missing file is left missing."""
    if design.suffix.lower() == ".zip":
        return read_upload(design.name, design.read_bytes()), {}
    text = _decode(design.read_bytes(), design.name)
    bundle = Bundle(display_name(design.name, text), text)
    moved: dict[str, str] = {}
    for ref in references(text):
        source = (design.parent / ref.value).resolve()
        if not source.is_file():
            continue
        path = ref.inside
        if path is None:
            path = _free(bundle.files, f"{ASSETS}/{source.name}")
            moved[ref.value] = path
        bundle.files[path] = source.read_bytes()
    return bundle, moved


def _free(files: dict[str, Any], path: str) -> str:
    """``path``, or ``stem-2.ext`` and so on when it is taken."""
    if path not in files:
        return path
    p = PurePosixPath(path)
    n = 2
    while f"{p.parent}/{p.stem}-{n}{p.suffix}" in files:
        n += 1
    return f"{p.parent}/{p.stem}-{n}{p.suffix}"


def asset_path(files: dict[str, Any], filename: str) -> str:
    """Where an asset the author adds is stored: under `assets/`, by its
    own base name, renamed when taken."""
    base = PurePosixPath(filename.replace("\\", "/")).name
    if not base or base in (".", ".."):
        raise BundleError(f"{filename!r} is not a file name")
    return _free(files, f"{ASSETS}/{base}")


# -- out ------------------------------------------------------------------------------

def to_zip(bundle: Bundle) -> bytes:
    """The bundle as a `.zip`, the face at its root as `face.yaml`."""
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(FACE, bundle.text)
        for path in sorted(bundle.files):
            archive.writestr(path, bundle.files[path])
    return out.getvalue()
