#!/usr/bin/env python3
"""Reproduce the em/ascent/descent/height metric model from plan 09 §2, and
check the scraped ``size_px`` against a from-scratch prediction, using the
*actual* downloaded TTFs' ``hhea``/``head`` tables.

Two checks, both read-only and offline (the TTFs must already be on disk --
this script does not download anything):

1. **35-entry reproduction.** Every entry across every ``fontSet`` (``ww``,
   ``apac_vie``, ``apac_jpn``, ...) of every *installed*
   ``~/.Garmin/ConnectIQ/Devices/<id>/simulator.json`` that carries
   ``ascent``/``descent``/``height`` *and* whose ``filename`` is one of the
   four Roboto-family files this project actually has TTFs for
   (``RobotoCondensed-Bold``, ``RobotoCondensed-Regular``, ``Roboto-Black``,
   ``Roboto-Condensed_0``). For each, predict::

       em = size_pt * ppi / 72
       predicted_ascent  = round(em * hhea_ascent  / unitsPerEm)
       predicted_descent = round(em * -hhea_descent / unitsPerEm)   # hhea descent is negative
       predicted_height  = round(em * (hhea_ascent - hhea_descent) / unitsPerEm)

   and compare against the device file's own ``ascent``/``descent``/``height``.
   docs/research/10-system-fonts.md cites this script's output as reproducing
   plan 09 §2's preliminary "35 entries, 20 exact, rest off by 1-2 px, mostly
   apac_vie" result.

2. **size_px cross-check.** For every ``ww`` entry (across the 13 locally
   installed devices) that has both a point ``size`` and the device has a
   top-level ``ppi``, and whose ``filename`` resolves (via
   ``wfb/fonts/registry.json``) to a font-key backed by an actually-downloaded
   TTF, compares the *scraped* ``docs/research/data/devices/<id>.json``
   ``size_px`` for the matching ``FONT_*`` symbol against
   ``round(em * (asc - desc) / upm)`` computed from that TTF -- independent of
   whatever ``height``/``ascent``/``descent`` the device file itself reports.

Usage::

    ./.venv/bin/python tools/research/font_metric_check.py --fonts-dir DIR

``DIR`` must contain the extracted TTFs named exactly as their device
``filename`` + ``.ttf`` for the four Roboto-family files above (case-sensitive,
e.g. ``RobotoCondensed-Bold.ttf``). Neither the fonts nor any cache directory
are committed to the repository (licensing -- see
docs/research/10-system-fonts.md); re-download with the ``sources`` in
``wfb/fonts/registry.json`` to reproduce.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
REGISTRY_PATH = ROOT / "wfb" / "fonts" / "registry.json"
SCRAPED_DEVICES = ROOT / "docs" / "research" / "data" / "devices"
SIMULATOR_ROOTS = (
    Path.home() / ".Garmin" / "ConnectIQ" / "Devices",
    Path.home() / "Library" / "Application Support" / "Garmin" / "ConnectIQ" / "Devices",
)

# device simulator.json filename -> the TTF basename to load for it
ROBOTO_FAMILY_FILES = {
    "RobotoCondensed-Bold": "RobotoCondensed-Bold.ttf",
    "RobotoCondensed-Regular": "RobotoCondensed-Regular.ttf",
    "Roboto-Black": "Roboto-Black.ttf",
    # apac_vie's "Roboto-Condensed_0" has identical hhea to RobotoCondensed-Bold/
    # Regular in the v2.138 release (1900/-500/2048 for all three); Bold is used
    # since fenix5/8-era vie devices' number faces are bold everywhere else.
    "Roboto-Condensed_0": "RobotoCondensed-Bold.ttf",
}


def find_devices_root() -> Path | None:
    for root in SIMULATOR_ROOTS:
        if root.is_dir():
            return root
    return None


def load_hhea(path: Path) -> tuple[int, int, int]:
    """``(unitsPerEm, hhea_ascent, hhea_descent)`` -- ``hhea_descent`` as-signed
    (negative) exactly as it sits in the font, matching plan 09 §2's own sign
    convention.
    """
    from fontTools.ttLib import TTFont  # local import: only needed for this script

    font = TTFont(str(path))
    upm = font["head"].unitsPerEm
    hhea = font["hhea"]
    return upm, hhea.ascent, hhea.descent


def name_to_symbol(name: str) -> str:
    """``xtiny`` -> ``FONT_XTINY``, ``numberHot`` -> ``FONT_NUMBER_HOT``, etc.

    Best-effort camelCase splitter; only used to join a ``ww`` entry back to
    its scraped ``FONT_*`` row for the size_px cross-check (check 2). A miss
    here just means that one entry is skipped, not a wrong answer -- see the
    "skipped (no scraped symbol)" tally in the report.
    """
    base = name
    if base.startswith("system") and base != "system":
        base = base[len("system"):]
        base = base[0].lower() + base[1:]
    s = re.sub(r"(?<!^)(?=[A-Z])", "_", base).upper()
    return "FONT_" + s


def check_35_entries(devices_root: Path, fonts_dir: Path) -> None:
    print("=" * 70)
    print("Check 1: reproduce plan 09 §2's ascent/descent/height model")
    print("=" * 70)

    hhea_cache: dict[str, tuple[int, int, int]] = {}
    for basename in set(ROBOTO_FAMILY_FILES.values()):
        path = fonts_dir / basename
        if not path.is_file():
            print(f"MISSING TTF: {path} -- cannot run this check")
            return
        hhea_cache[basename] = load_hhea(path)

    rows = []
    for device_id in sorted(os.listdir(devices_root)):
        sim_path = devices_root / device_id / "simulator.json"
        if not sim_path.is_file():
            continue
        sim = json.loads(sim_path.read_text(encoding="utf-8"))
        ppi = sim.get("ppi")
        if not ppi:
            continue
        for entry in sim.get("fonts", []):
            font_set = entry.get("fontSet")
            for f in entry.get("fonts", []):
                filename = f.get("filename")
                if filename not in ROBOTO_FAMILY_FILES:
                    continue
                if not all(k in f for k in ("ascent", "descent", "height", "size")):
                    continue
                rows.append((device_id, font_set, filename, ppi, f["size"], f["ascent"], f["descent"], f["height"]))

    print(f"N = {len(rows)} entries (expected 35)")
    exact = 0
    off_by = []
    for device_id, font_set, filename, ppi, size_pt, asc, desc, height in rows:
        upm, hhea_asc, hhea_desc = hhea_cache[ROBOTO_FAMILY_FILES[filename]]
        em = size_pt * ppi / 72.0
        pred_asc = round(em * hhea_asc / upm)
        pred_desc = round(em * (-hhea_desc) / upm)
        pred_height = round(em * (hhea_asc - hhea_desc) / upm)
        diff = (pred_asc - asc, pred_desc - desc, pred_height - height)
        if diff == (0, 0, 0):
            exact += 1
        else:
            off_by.append((device_id, font_set, filename, size_pt, ppi, round(em, 3), diff))

    print(f"exact: {exact}  off-by-1-2px: {len(off_by)}")
    from collections import Counter

    by_font_set = Counter(r[1] for r in off_by)
    print("off entries by fontSet:", dict(by_font_set))
    for row in off_by:
        print("  ", row)


def check_size_px(devices_root: Path, fonts_dir: Path) -> None:
    print()
    print("=" * 70)
    print("Check 2: scraped size_px vs round(em*(asc-desc)/upm), ww entries only")
    print("=" * 70)

    registry = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
    names = registry["names"]
    patterns = [(re.compile(p["regex"]), p["key"]) for p in registry["patterns"]]

    # Only the font-keys actually backed by a TTF this script has on disk
    # (the exact Roboto-family releases) can be metric-checked; substitutes
    # for proprietary faces (Bionic, Chronos, ...) are skipped on purpose --
    # comparing against a *different* font's metrics would not test the
    # em/ppi model, only how similar the substitute happens to be.
    checkable_keys = {
        "roboto-condensed-bold": "RobotoCondensed-Bold.ttf",
        "roboto-condensed-regular": "RobotoCondensed-Regular.ttf",
        "roboto-condensed-medium": "RobotoCondensed-Medium.ttf",
        "roboto-black": "Roboto-Black.ttf",
        "roboto-regular": "Roboto-Regular.ttf",
        "roboto-medium": "Roboto-Medium.ttf",
        "roboto-bold": "Roboto-Bold.ttf",
        "roboto-light": "Roboto-Light.ttf",
        "roboto-italic": "Roboto-Italic.ttf",
    }

    def resolve(name: str) -> str | None:
        if name in names:
            return names[name]
        for rx, key in patterns:
            if rx.search(name):
                return key
        return None

    exact = 0
    off_by = []
    skipped_no_scrape = 0
    skipped_no_ttf = 0

    for device_id in sorted(os.listdir(devices_root)):
        sim_path = devices_root / device_id / "simulator.json"
        if not sim_path.is_file():
            continue
        sim = json.loads(sim_path.read_text(encoding="utf-8"))
        ppi = sim.get("ppi")
        if not ppi:
            continue
        scraped_path = SCRAPED_DEVICES / f"{device_id}.json"
        scraped_fixed = {}
        if scraped_path.is_file():
            scraped = json.loads(scraped_path.read_text(encoding="utf-8"))
            scraped_fixed = scraped.get("fonts", {}).get("default", {}).get("fixed", {})

        for entry in sim.get("fonts", []):
            if entry.get("fontSet") != "ww":
                continue
            for f in entry.get("fonts", []):
                if "size" not in f:
                    continue
                filename = f["filename"]
                key = resolve(filename)
                if key not in checkable_keys:
                    skipped_no_ttf += 1
                    continue
                symbol = name_to_symbol(f["name"])
                if symbol not in scraped_fixed:
                    skipped_no_scrape += 1
                    continue
                scraped_size_px = scraped_fixed[symbol].get("size_px")
                if scraped_size_px is None:
                    skipped_no_scrape += 1
                    continue

                ttf_path = fonts_dir / checkable_keys[key]
                if not ttf_path.is_file():
                    skipped_no_ttf += 1
                    continue
                upm, hhea_asc, hhea_desc = load_hhea(ttf_path)
                em = f["size"] * ppi / 72.0
                predicted = round(em * (hhea_asc - hhea_desc) / upm)
                diff = predicted - scraped_size_px
                if diff == 0:
                    exact += 1
                else:
                    off_by.append((device_id, f["name"], symbol, filename, round(em, 3), predicted, scraped_size_px, diff))

    print(f"exact: {exact}  off: {len(off_by)}  skipped (no downloaded TTF for that face): {skipped_no_ttf}  skipped (no scraped FONT_* symbol): {skipped_no_scrape}")
    for row in off_by:
        print("  ", row)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--fonts-dir", required=True, type=Path, help="directory containing the extracted Roboto-family TTFs")
    args = parser.parse_args()

    devices_root = find_devices_root()
    if devices_root is None:
        print("note: no ~/.Garmin/ConnectIQ/Devices installed -- nothing to check", file=sys.stderr)
        return 1

    check_35_entries(devices_root, args.fonts_dir)
    check_size_px(devices_root, args.fonts_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
