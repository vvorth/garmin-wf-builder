#!/usr/bin/env python3
"""Build a feature x device capability matrix from the SDK's offline API docs.

Garmin documents per-method "Supported Devices" lists as product *names*
(e.g. "fenix(r) 8 Solar 47mm"). The device database keyed by product *id* comes
from Device_Reference. This script joins the two by name so we can answer
"is symbol X usable on device id Y" mechanically instead of by guesswork.

Phase 0 research instrumentation. Usage:

    python3 tools/research/build_capability_matrix.py \
        --sdk ~/ciq/sdks/9.2.0 --data docs/research/data
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from html import unescape
from pathlib import Path

TAG_RE = re.compile(r"<[^>]+>")

# (label, doc path relative to doc/, symbol) -- the features that drive the
# framework's design decisions.
FEATURES = [
    ("onPartialUpdate", "Toybox/WatchUi/WatchFace.html", "onPartialUpdate"),
    ("onPowerBudgetExceeded", "Toybox/WatchUi/WatchFaceDelegate.html", "onPowerBudgetExceeded"),
    ("onPress (hold)", "Toybox/WatchUi/WatchFaceDelegate.html", "onPress"),
    ("onTap", "Toybox/WatchUi/WatchFaceDelegate.html", "onTap"),
    ("setSelectedComplication", "Toybox/WatchUi/WatchFaceDelegate.html", "setSelectedComplication"),
    ("onWatchFaceConfigEdited", "Toybox/WatchUi/WatchFaceDelegate.html", "onWatchFaceConfigEdited"),
    ("getComplicationDrawable", "Toybox/WatchUi/WatchFaceDelegate.html", "getComplicationDrawable"),
    ("getVectorFont", "Toybox/Graphics.html", "getVectorFont"),
    ("setAntiAlias", "Toybox/Graphics/Dc.html", "setAntiAlias"),
    ("drawRadialText", "Toybox/Graphics/Dc.html", "drawRadialText"),
    ("drawAngledText", "Toybox/Graphics/Dc.html", "drawAngledText"),
    ("setBlendMode", "Toybox/Graphics/Dc.html", "setBlendMode"),
]


def text(fragment: str) -> str:
    return re.sub(r"\s+", " ", unescape(TAG_RE.sub("\n", fragment))).strip()


def normalize(name: str) -> str:
    """Fold a product name to a comparable key.

    Device_Reference titles and API "Supported Devices" entries use the same
    marketing names but differ in registered-trademark marks and spacing.
    """
    s = unescape(name).lower()
    s = s.replace("®", "").replace("™", "")
    s = s.replace("–", "-").replace("—", "-")
    s = re.sub(r"[^a-z0-9/+]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def method_sections(html: str) -> dict[str, str]:
    """Split an API page into {method_name: section_html}."""
    out: dict[str, str] = {}
    # Method detail blocks are h3/h4 anchors followed by the signature.
    parts = re.split(r'<h[34][^>]*>', html)
    for part in parts[1:]:
        sig = text(part[:400]).split("\n")
        name = None
        for line in sig:
            m = re.match(r"([A-Za-z_][A-Za-z0-9_]*)\s*\(", line.strip())
            if m:
                name = m.group(1)
                break
        if name:
            out.setdefault(name, "")
            out[name] += part
    return out


def parse_feature(sdk: Path, doc_rel: str, symbol: str):
    path = sdk / "doc" / doc_rel
    if not path.is_file():
        return None
    html = path.read_text(encoding="utf-8", errors="replace")
    secs = method_sections(html)
    sec = secs.get(symbol)
    if sec is None:
        return None

    since = None
    m = re.search(r"Since:.{0,200}?API Level\s*([\d.]+)", text(sec), re.S)
    if m:
        since = m.group(1)

    devices = None
    dm = re.search(r"Supported Devices:(.*?)(?:Since:|$)", sec, re.S)
    if dm:
        names = [
            text(li) for li in re.findall(r"<li[^>]*>(.*?)</li>", dm.group(1), re.S)
        ]
        if not names:
            names = [n.strip() for n in text(dm.group(1)).split("\n") if n.strip()]
        devices = [n for n in names if n]
    return {"since": since, "devices": devices}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sdk", required=True)
    ap.add_argument("--data", default="docs/research/data")
    args = ap.parse_args()

    sdk = Path(args.sdk).expanduser()
    data = Path(args.data).expanduser()
    index = json.loads((data / "devices-index.json").read_text(encoding="utf-8"))

    by_norm = {}
    for d in index:
        by_norm.setdefault(normalize(d.get("name", "")), d["id"])

    matrix = {}
    for label, rel, symbol in FEATURES:
        info = parse_feature(sdk, rel, symbol)
        if info is None:
            matrix[label] = {"error": f"symbol {symbol} not found in {rel}"}
            continue
        entry = {"since": info["since"], "symbol": symbol, "doc": rel}
        if info["devices"] is None:
            entry["scope"] = "all devices (no explicit list)"
            entry["device_ids"] = None
        else:
            ids, unmatched = [], []
            for name in info["devices"]:
                key = normalize(name)
                if key in by_norm:
                    ids.append(by_norm[key])
                else:
                    unmatched.append(name)
            entry["scope"] = f"{len(info['devices'])} devices listed"
            entry["device_ids"] = sorted(set(ids))
            entry["unmatched_names"] = unmatched
        matrix[label] = entry

    (data / "capability-matrix.json").write_text(
        json.dumps(matrix, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    targets = ["fenix8solar47mm", "fenix8solar51mm", "fr955"]
    print(f"{'feature':26s} {'since':8s} {'scope':22s} " + " ".join(f"{t:16s}" for t in targets))
    print("-" * 110)
    for label, e in matrix.items():
        if "error" in e:
            print(f"{label:26s} {e['error']}")
            continue
        cells = []
        for t in targets:
            if e["device_ids"] is None:
                cells.append("yes")
            else:
                cells.append("yes" if t in e["device_ids"] else "NO")
        print(
            f"{label:26s} {str(e['since']):8s} {e['scope']:22s} "
            + " ".join(f"{c:16s}" for c in cells)
        )
    unm = {k: v.get("unmatched_names") for k, v in matrix.items() if v.get("unmatched_names")}
    if unm:
        print("\nunmatched product names (name-join gaps):")
        for k, v in unm.items():
            print(f"  {k}: {len(v)} e.g. {v[:3]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
