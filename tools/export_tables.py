#!/usr/bin/env python3
"""Export the compiler's data tables to JSON for the TypeScript port.

    ./.venv/bin/python tools/export_tables.py          # write ts/src/data/*.json
    ./.venv/bin/python tools/export_tables.py --check  # exit 1 when they differ

The tables (the data-source catalogue and its readers, the complication
types, the icon catalogue) are data, transcribed from the SDK's docs with
their citations in `source_ref` and `doc` fields. While both compilers
exist, wfb/ holds them and ts/ reads this export, so neither can drift:
`tests/test_ts.py` runs `--check`. Each file is written with sorted
formatting so a change reads as a small diff.
"""

from __future__ import annotations

import enum
import json
import sys
from dataclasses import fields, is_dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from wfb import catalog, complications, icon_catalog  # noqa: E402

OUT = ROOT / "ts" / "src" / "data"


def plain(value: Any) -> Any:
    if isinstance(value, enum.Enum):
        return value.value
    if is_dataclass(value) and not isinstance(value, type):
        return {f.name: plain(getattr(value, f.name)) for f in fields(value)}
    if isinstance(value, dict):
        return {str(k): plain(v) for k, v in value.items()}
    if isinstance(value, (set, frozenset)):
        return sorted(plain(v) for v in value)
    if isinstance(value, (list, tuple)):
        return [plain(v) for v in value]
    return value


def tables() -> dict[str, Any]:
    return {
        "catalog.json": {
            "readers": plain(catalog.READERS),
            "sources": plain(dict(catalog.CATALOG)),
            "renamed_sources": plain(catalog.RENAMED_SOURCES),
            "weather_condition_sources": plain(catalog.WEATHER_CONDITION_SOURCES),
            "watchface_permissions": plain(catalog.WATCHFACE_PERMISSIONS),
        },
        "complications.json": {
            "types": plain(dict(complications.TYPES)),
            "exit_to_api_level": complications.EXIT_TO_API_LEVEL,
            "exit_to_permission": complications.EXIT_TO_PERMISSION,
            "unit_suffix": plain(complications.UNIT_SUFFIX),
            "categories": plain(complications.CATEGORIES),
            "presentation": plain(complications.PRESENTATION),
            "short_length": complications.SHORT_LENGTH,
            "reading": plain(complications.READING),
            "count_unit": plain(complications.COUNT_UNIT),
            "worded": plain(complications.WORDED),
            "weather_condition_text": plain(complications.WEATHER_CONDITION_TEXT),
            "unknown_condition": complications.UNKNOWN_CONDITION,
            "training_status_short": plain(complications.TRAINING_STATUS_SHORT),
            "widest": plain(complications._WIDEST),
            "scale": plain(complications.SCALE),
            "vo2max_ages": [complications.VO2MAX_AGES.start, complications.VO2MAX_AGES.stop],
            "vo2max_ratings": plain(complications.VO2MAX_RATINGS),
        },
        "icons.json": {
            "catalog": plain(icon_catalog.CATALOG),
        },
    }


def render(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=1) + "\n"


def main(argv: list[str]) -> int:
    check = "--check" in argv
    stale = []
    for name, value in tables().items():
        path = OUT / name
        text = render(value)
        if check:
            if not path.exists() or path.read_text(encoding="utf-8") != text:
                stale.append(name)
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
    if stale:
        print("stale: " + ", ".join(stale) + " -- run ./.venv/bin/python tools/export_tables.py",
              file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
