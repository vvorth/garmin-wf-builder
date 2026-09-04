#!/usr/bin/env python3
"""Download and unpack the Connect IQ SDK, then strip it to the compiler.

Run at image build time (see the Dockerfile).  Written in Python rather than
curl/wget so the SDK stage needs no package installs: the base image already has
an interpreter, and ``urllib`` picks up ``https_proxy`` and the system trust
store without any extra plumbing.

The full SDK is 309 MB.  ``doc/``, ``resources/`` and ``samples/`` are
documentation; ``share/`` and the simulator, ERA, MonkeyMotion, the language
server and the FIT graph tool are GUI and analysis programs the container does
not run.  What is left -- the compiler, its API database and the resource XSD --
is about 26 MB and builds every target correctly.
"""

from __future__ import annotations

import os
import shutil
import stat
import sys
import urllib.request
import zipfile
from pathlib import Path

#: Whole trees that are documentation or simulator assets.
PRUNE_TREES = ("doc", "samples", "resources", "share")

#: Programs in bin/ that need a display or are not part of building a face.
PRUNE_BIN = (
    "simulator", "connectiq", "connectiq.bat",
    "monkeymotion", "monkeygraph", "monkeygraph.bat",
    "era", "era.bat", "era.jar",
    "LanguageServer.jar", "fit-graph.jar",
    "shell", "mdd", "mdd.bat", "extdata",
    "barrelbuild", "barrelbuild.bat", "barreltest", "barreltest.bat",
    "monkeydoc", "monkeydoc.bat", "monkeym", "monkeym.bat",
)

#: Launchers that must be executable.  zipfile does not preserve the mode bits.
EXECUTABLE = ("monkeyc", "monkeydo")


def main() -> int:
    url = sys.argv[1]
    destination = Path(sys.argv[2] if len(sys.argv) > 2 else "/opt/ciq")
    archive_path = Path("/tmp/connectiq-sdk.zip")

    print(f"fetching {url}", flush=True)
    with urllib.request.urlopen(url, timeout=600) as response:
        with archive_path.open("wb") as out:
            shutil.copyfileobj(response, out)
    print(f"fetched {archive_path.stat().st_size // (1024 * 1024)} MB", flush=True)

    destination.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive_path) as archive:
        archive.extractall(destination)
    archive_path.unlink()

    for tree in PRUNE_TREES:
        shutil.rmtree(destination / tree, ignore_errors=True)
    for html in destination.glob("*.html"):
        html.unlink()

    binaries = destination / "bin"
    for name in PRUNE_BIN:
        target = binaries / name
        if target.is_dir():
            shutil.rmtree(target, ignore_errors=True)
        elif target.exists():
            target.unlink()

    for name in EXECUTABLE:
        target = binaries / name
        if not target.exists():
            raise SystemExit(f"the SDK archive has no bin/{name}")
        target.chmod(target.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

    # `monkeyc` regenerates bin/default.jungle from the installed device list on
    # every invocation, and it *replaces* the file rather than truncating it --
    # so the directory itself has to be writable, not just the file.  The image
    # gives the default uid ownership of the tree; the entrypoint falls back to a
    # writable copy when the container is run as some other user.
    jungle = binaries / "default.jungle"
    if jungle.exists():
        jungle.chmod(0o664)

    size = sum(f.stat().st_size for f in destination.rglob("*") if f.is_file())
    print(f"pruned SDK is {size // (1024 * 1024)} MB", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
