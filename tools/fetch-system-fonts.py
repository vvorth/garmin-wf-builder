#!/usr/bin/env python3
"""Prefetch the free stand-ins for Garmin's system fonts that the given
devices need (`docs/plans/09-system-font-metrics.md`, R1).

Each device's needed font *names* come from its installed
`simulator.json`'s `ww` font set when the device definitions are installed,
else from the scraped default-language table in
`docs/research/data/devices/<id>.json` (`wfb/fonts/fetch_system.py`'s
`device_needed_names`). Each name is resolved to a `wfb/fonts/registry.json`
font-key (`resolve`) and downloaded/hash-checked/cached
(`wfb/fonts/fetch_system.py`'s `install`), landing in `wfb/assets/system-fonts/`
by default. Re-running it is cheap: a key already installed is left alone
and nothing is downloaded for it.

Loads `wfb/fonts/fetch_system.py` **by file path**, not by importing the
`wfb` package, so this script runs with the plain system `python3` -- before
`.venv` exists and in the Docker build stage, neither of which has Pillow or
any other dependency installed. `tools/fetch-icon-font.py` is the same shape.

    python3 tools/fetch-system-fonts.py [--device ID ...] [--all] [DEST]

With no `--device`, prefetches for this project's three build targets
(`fetch_system.DEFAULT_TARGET_DEVICES`). `--all` prefetches for every device
`docs/research/data/devices/` has a scraped file for, not just the three
targets. `WFB_FONTS_MIRROR` overrides every source URL's host, for a mirror
(`wfb/fonts/fetch_system.py`'s `_mirrored`).

This tool never installs Garmin's own font files -- those are the user's
licensed copy at `vendor/fonts/` (`tools/setup-env.sh` copies them in) -- it
only says which needed names that root already covers, so the registry
download for those names is visibly redundant, not silently wasted.
"""

from __future__ import annotations

import argparse
import importlib.util
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
MODULE_PATH = REPO_ROOT / "wfb" / "fonts" / "fetch_system.py"


def _load_fetch_system():
    spec = importlib.util.spec_from_file_location("fetch_system", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def main(argv: list[str] | None = None) -> int:
    fetch_system = _load_fetch_system()

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--device", action="append", dest="devices", metavar="ID",
                         help="prefetch only this device's fonts (repeatable); "
                              f"default: {', '.join(fetch_system.DEFAULT_TARGET_DEVICES)}")
    parser.add_argument("--all", action="store_true",
                         help="prefetch fonts for every scraped device, not just the targets")
    parser.add_argument("dest", nargs="?", type=Path, default=None,
                         help="install directory (default: wfb/assets/system-fonts)")
    args = parser.parse_args(argv)

    dest = args.dest or fetch_system.DEFAULT_DEST

    if args.all:
        device_ids = fetch_system.all_scraped_device_ids()
    else:
        device_ids = args.devices or list(fetch_system.DEFAULT_TARGET_DEVICES)

    fonts_root = fetch_system.garmin_font_root()
    if fonts_root is not None:
        print(f"Garmin font root: {fonts_root}")
    else:
        print("Garmin font root: not found (registry-only; see `wfb doctor`)")

    # name -> (font-key, one example device that needs it), for reporting.
    needed: dict[str, tuple[str, str | None]] = {}
    garmin_covered = 0
    for device_id in device_ids:
        for name, face in fetch_system.device_needed_names(device_id):
            if fonts_root is not None and fetch_system.garmin_font_file(name, fonts_root) is not None:
                garmin_covered += 1
                continue
            key = fetch_system.resolve(name, face)
            if key is not None and key not in needed:
                needed[key] = (name, face)

    if not needed:
        print(f"nothing to prefetch for {', '.join(device_ids)}")
        return 0

    print(f"prefetching {len(needed)} font(s) for {', '.join(device_ids)} into {dest}")
    if garmin_covered:
        print(f"  ({garmin_covered} needed name(s) already covered by the Garmin font root, skipped)")

    results = fetch_system.install(sorted(needed), dest)
    for key in sorted(needed):
        status = "ok" if results.get(key) else "FAILED"
        print(f"  {status:6} {key}  ({needed[key][0]})")

    failed = [key for key, ok in results.items() if not ok]
    if failed:
        print(f"error: {len(failed)} font(s) could not be fetched (see notes above)", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
