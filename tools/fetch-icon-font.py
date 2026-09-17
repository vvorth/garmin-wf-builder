#!/usr/bin/env python3
"""Download the Nerd Fonts "Symbols Only" icon font that `icon:` elements use.

The font is not committed to this repository: this script fetches the pinned
release, checks every byte against the hashes below, and installs the font
and its licence into ``wfb/assets/icons/`` (or the directory given as the
first argument).  Re-running it is cheap: files that already match are left
alone and nothing is downloaded.

Standard library only, so it runs before the virtualenv exists and in the
Docker build stage, which installs no packages.  ``urllib`` honours
``https_proxy`` and the system trust store.

    python3 tools/fetch-icon-font.py [DEST_DIR]

``WFB_NERD_FONTS_BASE_URL`` overrides the download host, for a mirror.
"""

from __future__ import annotations

import hashlib
import io
import os
import sys
import tarfile
import time
import urllib.request
from pathlib import Path

VERSION = "v3.5.1"
ARCHIVE = "NerdFontsSymbolsOnly.tar.xz"
ARCHIVE_SHA256 = "01172f37db8543edb102e5cb5c64101c9f4686630804d49b419aa07b23a69996"
BASE_URL = os.environ.get(
    "WFB_NERD_FONTS_BASE_URL",
    "https://github.com/ryanoasis/nerd-fonts/releases/download",
)

#: Archive member -> (installed name, SHA-256).
FILES = {
    "SymbolsNerdFont-Regular.ttf": (
        "SymbolsNerdFont-Regular.ttf",
        "2839f0a572d4559f3f17a6fb74b8772e183f0c0a47150998ab194932cad55829",
    ),
    "LICENSE": (
        "LICENSE-nerd-fonts.txt",
        "84a7a98c82140fb12c37fe42b93805baa16024cb3e5acc599b7ffe612c55d847",
    ),
}

DEFAULT_DEST = Path(__file__).resolve().parent.parent / "wfb" / "assets" / "icons"


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def installed(dest: Path) -> bool:
    """Is every file already present with the pinned content?"""
    for name, digest in FILES.values():
        path = dest / name
        if not path.is_file() or sha256(path.read_bytes()) != digest:
            return False
    return True


def download(url: str, attempts: int = 3) -> bytes:
    for attempt in range(1, attempts + 1):
        try:
            with urllib.request.urlopen(url, timeout=120) as response:
                return response.read()
        except OSError as exc:
            if attempt == attempts:
                raise
            print(f"  attempt {attempt} failed ({exc}); retrying", flush=True)
            time.sleep(2 * attempt)
    raise AssertionError("unreachable")


def main() -> int:
    dest = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_DEST
    if installed(dest):
        print(f"icon font {VERSION} already installed in {dest}")
        return 0

    url = f"{BASE_URL}/{VERSION}/{ARCHIVE}"
    print(f"fetching {url}", flush=True)
    try:
        data = download(url)
    except OSError as exc:
        print(f"error: could not download the icon font: {exc}", file=sys.stderr)
        return 1
    if sha256(data) != ARCHIVE_SHA256:
        print(f"error: {ARCHIVE} does not match its pinned SHA-256", file=sys.stderr)
        return 1

    dest.mkdir(parents=True, exist_ok=True)
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:xz") as archive:
        for member, (name, digest) in FILES.items():
            content = archive.extractfile(member).read()
            if sha256(content) != digest:
                print(f"error: {member} does not match its pinned SHA-256",
                      file=sys.stderr)
                return 1
            partial = dest / f".{name}.partial"
            partial.write_bytes(content)
            partial.replace(dest / name)
    print(f"installed icon font {VERSION} into {dest}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
