#!/usr/bin/env python3
"""Extract a per-device capability database from the Connect IQ SDK's offline docs.

Source of truth: ``$CIQ_SDK/doc/docs/Device_Reference/<id>.html``, which ships
inside the SDK zip and is therefore version-pinned to the SDK release (9.2.0).

This is Phase 0 research instrumentation, not framework code. It exists to
produce the capability matrix; the eventual ``devices/`` package will likely
prefer the richer ``compiler.json`` / ``simulator.json`` files that the SDK
Manager downloads per device, which we do not currently have (they sit behind
an authenticated Garmin endpoint -- see docs/research/03-toolchain.md).

Usage:
    python3 tools/research/extract_device_db.py --sdk ~/ciq/sdks/9.2.0 \
        --out docs/research/data
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from html import unescape
from pathlib import Path
from typing import Any

TAG_RE = re.compile(r"<[^>]+>")
ROW_RE = re.compile(r"<tr[^>]*>(.*?)</tr>", re.S)
CELL_RE = re.compile(r"<t[dh][^>]*>(.*?)</t[dh]>", re.S)
# A section is a bold paragraph label immediately preceding its table.
SECTION_RE = re.compile(r"<p[^>]*>\s*<strong[^>]*>(.*?)</strong>\s*</p>", re.S)
TABLE_RE = re.compile(r"<table[^>]*>.*?</table>", re.S)
TITLE_RE = re.compile(r'<h1[^>]*class="title[^"]*"[^>]*>(.*?)</h1>', re.S)


def text(fragment: str) -> str:
    """Strip tags and collapse whitespace."""
    return re.sub(r"\s+", " ", unescape(TAG_RE.sub(" ", fragment))).strip()


def table_rows(table_html: str) -> list[list[str]]:
    rows = []
    for row in ROW_RE.findall(table_html):
        cells = [text(c) for c in CELL_RE.findall(row)]
        if any(cells):
            rows.append(cells)
    return rows


def as_int(value: str) -> int | None:
    try:
        return int(value.replace(",", ""))
    except (ValueError, AttributeError):
        return None


def parse_bool(value: str) -> bool | None:
    low = value.strip().lower()
    return {"true": True, "false": False}.get(low)


def split_sections(html: str) -> list[tuple[str, str]]:
    """Return [(label, table_html)] plus a leading ('', table) for the unlabelled
    attribute table that opens every device page."""
    out: list[tuple[str, str]] = []
    tables = [(m.start(), m.group(0)) for m in TABLE_RE.finditer(html)]
    labels = [(m.start(), text(m.group(1))) for m in SECTION_RE.finditer(html)]

    for pos, tbl in tables:
        # the nearest bold label that appears before this table
        preceding = [(lp, lab) for lp, lab in labels if lp < pos]
        label = preceding[-1][1] if preceding else ""
        # ...but only if no other table sits between that label and this one
        if preceding:
            lp = preceding[-1][0]
            if any(lp < op < pos for op, _ in tables):
                label = ""
        out.append((label, tbl))
    return out


def parse_device(path: Path) -> dict[str, Any]:
    html = path.read_text(encoding="utf-8", errors="replace")
    dev: dict[str, Any] = {
        "id": path.stem,
        "source": f"doc/docs/Device_Reference/{path.name}",
    }

    title = TITLE_RE.search(html)
    if title:
        dev["name"] = text(title.group(1))

    fonts_by_lang: dict[str, Any] = {}
    field_layouts: dict[str, Any] = {}
    pending_langs: list[str] = []

    # Language lists appear as a bare paragraph between Fonts tables.
    lang_blocks = re.findall(
        r"<p[^>]*>\s*<strong[^>]*>\s*Languages\s*</strong>\s*</p>(.*?)(?=<p[^>]*>\s*<strong)",
        html,
        re.S,
    )
    lang_queue = [
        [t for t in text(b).split() if re.fullmatch(r"[a-z]{3}", t)] for b in lang_blocks
    ]

    for label, tbl in split_sections(html):
        rows = table_rows(tbl)
        if not rows:
            continue
        header = [c.lower() for c in rows[0]]

        if not label and "attribute" in header:
            for r in rows[1:]:
                if len(r) >= 2:
                    dev.setdefault("attributes", {})[r[0]] = r[1]

        elif label == "App Types" or "memory limit" in " ".join(header):
            limits = {}
            for r in rows[1:]:
                if len(r) >= 2:
                    limits[r[0]] = {
                        "memory_limit_bytes": as_int(r[1]),
                        "notes": r[2] if len(r) > 2 else "",
                    }
            dev["app_types"] = limits

        elif label.endswith("Layout"):
            field_layouts[label] = [
                dict(zip(rows[0], r)) for r in rows[1:] if len(r) == len(rows[0])
            ]

        elif label == "Fonts" or "font symbol" in " ".join(header):
            langs = lang_queue.pop(0) if lang_queue else pending_langs
            entry: dict[str, Any] = {"fixed": {}, "scalable": {}}
            for r in rows[1:]:
                if len(r) < 4:
                    continue
                symbol, face, size, font_file = r[0], r[1], r[2], r[3]
                rec = {"face": face, "font": font_file}
                if size.strip().lower() == "scalable":
                    entry["scalable"][symbol] = rec
                else:
                    entry["fixed"][symbol] = {**rec, "size_px": as_int(size)}
            key = ",".join(langs) if langs else "default"
            fonts_by_lang[key] = entry

    if fonts_by_lang:
        dev["fonts"] = fonts_by_lang
    if field_layouts:
        dev["data_field_layouts"] = field_layouts

    # Normalise the handful of attributes we care about most.
    attrs = dev.get("attributes", {})
    norm: dict[str, Any] = {}
    if "Screen Shape" in attrs:
        norm["screen_shape"] = attrs["Screen Shape"]
    if "Screen Size" in attrs:
        m = re.match(r"(\d+)\s*x\s*(\d+)", attrs["Screen Size"])
        if m:
            norm["screen_width"] = int(m.group(1))
            norm["screen_height"] = int(m.group(2))
    if "Display Colors" in attrs:
        norm["display_colors"] = as_int(attrs["Display Colors"])
    if "Touch" in attrs:
        norm["touch"] = parse_bool(attrs["Touch"])
    if "Buttons" in attrs:
        norm["buttons"] = [b.strip() for b in attrs["Buttons"].split(",") if b.strip()]
    wf = dev.get("app_types", {}).get("Watch Face", {})
    if wf:
        norm["watchface_memory_bytes"] = wf.get("memory_limit_bytes")
    dev["normalized"] = norm
    return dev


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sdk", default=os.environ.get("CIQ_SDK", ""))
    ap.add_argument("--out", default="docs/research/data")
    args = ap.parse_args()

    ref = Path(args.sdk).expanduser() / "doc" / "docs" / "Device_Reference"
    if not ref.is_dir():
        print(f"error: no Device_Reference at {ref}", file=sys.stderr)
        return 1

    out = Path(args.out).expanduser()
    (out / "devices").mkdir(parents=True, exist_ok=True)

    devices = []
    for path in sorted(ref.glob("*.html")):
        if path.stem.lower() == "overview":
            continue
        dev = parse_device(path)
        (out / "devices" / f"{dev['id']}.json").write_text(
            json.dumps(dev, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        devices.append(dev)

    index = [
        {"id": d["id"], "name": d.get("name", ""), **d.get("normalized", {})}
        for d in devices
    ]
    (out / "devices-index.json").write_text(
        json.dumps(index, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(f"parsed {len(devices)} devices -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
