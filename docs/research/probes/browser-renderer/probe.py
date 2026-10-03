"""Research 29 probe: what a browser renderer of `wfb.draw.jsonform` would
have to draw, what it would save, and how far a rule-free redraw of a
handle drag gets.

Run from the repo root:  PYTHONPATH=. .venv/bin/python \
    docs/research/probes/browser-renderer/probe.py > .../results.txt

Every example face but examples/dashboard, on fr955 at the editor's 2x.
"""

from __future__ import annotations

import base64
import io
import json
import statistics
import sys
import tempfile
import time
from collections import Counter
from pathlib import Path

from wfb import preview
from wfb.devices import DeviceDatabase
from wfb.draw.jsonform import to_json
from wfb.draw.layers import layers
from wfb.edit import View, resize, turn
from wfb.edit.gate import load_text
from wfb.layout import resolve
from wfb.studio.bundle import from_path
from wfb.studio.document import FrameKey, Studio
from wfb.studio.drag import handles
from wfb.studio.store import Store

ROOT = Path(__file__).resolve().parents[4]
DEVICE = "fr955"
SCALE = 2
FACES = sorted(p for p in (ROOT / "examples").rglob("face.yaml") if "dashboard" not in p.parts)


def ms(t0: float) -> float:
    return (time.perf_counter() - t0) * 1000


def element_json(resolved, element_id, options):
    entry = preview._resolve_style_entry(resolved.face, options.style)
    values = preview.sample_values(resolved, options, entry)
    renderer = preview.new_renderer(resolved, options, values, (0, 0, 0), None)
    for placed in preview.frame_items(resolved, options, entry):
        if placed.id == element_id and renderer.shows(placed):
            return to_json(renderer, placed)[0]
    return None


def numbers(ops):
    """Every number in an op list, with where it is: (path, const or None, value)."""
    out = []

    def walk(v, path):
        if isinstance(v, dict) and "const" in v and "value" in v:
            out.append((path, v["const"], v["value"] + v["add"]))
        elif isinstance(v, dict):
            for k, x in v.items():
                walk(x, path + (k,))
        elif isinstance(v, list):
            for i, x in enumerate(v):
                walk(x, path + (i,))
        elif isinstance(v, (int, float)) and not isinstance(v, bool):
            out.append((path, None, v))
    walk(ops, ())
    return out


def section_a(db):
    """What the JSON holds, its size against the layer PNGs, and its cost."""
    print("## A. Op vocabulary and payload, per face (fr955, 2x)\n")
    print("| face | layers | ops | text (baked/system/vector) | glyph | JSON KB | layer PNGs KB | layers ms | of which to_json ms |")
    print("|---|---:|---:|---|---:|---:|---:|---:|---:|")
    kinds = Counter()
    device = db.get(DEVICE)
    totals = Counter()
    for face_path in FACES:
        loaded = load_text(face_path, face_path.read_text())
        if loaded.face is None or DEVICE not in [d for d in (loaded.face.targets or [])]:
            # every example names its targets; build on fr955 regardless
            pass
        if loaded.face is None:
            continue
        from wfb.emit.resources import bake_fonts
        fonts = bake_fonts(loaded.face, device)
        resolved = resolve(loaded.face, device, fonts)
        options = preview.PreviewOptions(scale=SCALE)
        t0 = time.perf_counter()
        stack = layers(resolved, options)
        total = ms(t0)
        # to_json alone, once more, for its share
        entry = preview._resolve_style_entry(resolved.face, options.style)
        values = preview.sample_values(resolved, options, entry)
        t1 = time.perf_counter()
        for placed in preview.frame_items(resolved, options, entry):
            r = preview.new_renderer(resolved, options, values, (0, 0, 0), None)
            if r.shows(placed):
                to_json(r, placed)
        json_ms = ms(t1)
        nops = 0
        text = Counter()
        glyph = 0
        js = 0
        png = 0
        for layer in stack:
            payload = {"ops": layer.ops or [],
                       "fonts": {k: [v.baked, v.metric.symbol if v.metric else None, v.vector]
                                 for k, v in (layer.fonts or {}).items()}}
            js += len(json.dumps(payload, separators=(",", ":")))
            ink = layer.image.getchannel("A").getbbox()
            if ink:
                buf = io.BytesIO()
                layer.image.crop(ink).save(buf, format="PNG", compress_level=1)
                png += len(base64.b64encode(buf.getvalue()))
            for op in layer.ops or []:
                nops += 1
                kinds[op["op"]] += 1
                if op["op"] == "text":
                    ref = layer.fonts[op["font"]]
                    text["vector" if ref.vector else "baked" if ref.baked else "system"] += 1
                elif op["op"] == "glyph":
                    glyph += 1
        totals.update(ops=nops, js=js, png=png, **text, glyph=glyph)
        name = str(face_path.parent.relative_to(ROOT / "examples"))
        print(f"| {name} | {len(stack)} | {nops} | {text['baked']}/{text['system']}/{text['vector']} | "
              f"{glyph} | {js / 1024:.1f} | {png / 1024:.1f} | {total:.0f} | {json_ms:.0f} |")
    print(f"\nTotals: {totals['ops']} ops; text baked {totals['baked']}, system {totals['system']}, "
          f"vector {totals['vector']}; glyph {totals['glyph']}; JSON {totals['js'] / 1024:.0f} KB "
          f"against layer PNGs {totals['png'] / 1024:.0f} KB.\n")
    print("Op kinds over the corpus:\n")
    for k, n in kinds.most_common():
        print(f"- `{k}`: {n}")
    print()


def section_b(db):
    """Where a released drag's time goes, in the studio as it runs."""
    print("## B. A release's time, split (in-process, warm, best of 3)\n")
    print("| face | drag total | of which load (parse, schema, IR) | of which resolve | commit + rest | frame | layers |")
    print("|---|---:|---:|---:|---:|---:|---:|")
    import wfb.edit.gate as gate_mod
    import wfb.edit.geometry as geometry_mod
    import wfb.layout as layout_mod
    tmp = Path(tempfile.mkdtemp())
    studio = Studio(Store(tmp / "state"), db, scratch=tmp / "scratch")
    timers = Counter()
    real_load, real_resolve = gate_mod.load_text, layout_mod.resolve

    def timed_load(*a, **k):
        t0 = time.perf_counter(); r = real_load(*a, **k); timers["load"] += ms(t0); return r

    def timed_resolve(*a, **k):
        t0 = time.perf_counter(); r = real_resolve(*a, **k); timers["resolve"] += ms(t0); return r

    gate_mod.load_text = geometry_mod.load_text = timed_load
    layout_mod.resolve = timed_resolve
    try:
        for name in ("features/progress", "showcase", "features/vector-text"):
            path = ROOT / "examples" / name / "face.yaml"
            bundle, moved = from_path(path)
            doc = studio.create(bundle, "open", moved)
            device = doc.summary()["targets"][0]
            key = FrameKey(device)
            frame = doc.frame(key)
            target = [i for i in frame["items"] if i["drawn"]][-1]["id"]
            best = None
            for i in range(3):
                timers.clear()
                t0 = time.perf_counter()
                doc.drag(target, {"kind": "move", "dx": 1 if i % 2 == 0 else -1, "dy": 0},
                         device, "auto", doc.version)
                drag = ms(t0)
                load, res = timers["load"], timers["resolve"]
                t1 = time.perf_counter(); doc.frame(key); fr = ms(t1)
                t2 = time.perf_counter(); doc.layers(key); ly = ms(t2)
                row = (drag, load, res, drag - load - res, fr, ly)
                if best is None or row[0] < best[0]:
                    best = row
            d, l, r, rest, fr, ly = best
            print(f"| {name} ({device}) | {d:.0f} | {l:.0f} | {r:.0f} | {rest:.0f} | {fr:.0f} | {ly:.0f} |")
    finally:
        gate_mod.load_text = geometry_mod.load_text = real_load
        layout_mod.resolve = real_resolve
        studio.close()
    print()


def section_c(db):
    """For every size, radius and angle handle in the corpus: the JSON
    before, with only the handle's own constant(s) changed, against the JSON
    the server places after the real edit."""
    print("## C. A handle drag redrawn from the JSON alone\n")
    device = db.get(DEVICE)
    options = preview.PreviewOptions(scale=SCALE)
    tally = Counter()
    misses = []
    for face_path in FACES:
        text = face_path.read_text()
        try:
            view = View(face_path, text, device)
        except Exception:
            continue
        for placed in view.resolved.items:
            for h in handles(placed):
                if h["kind"] == "end":
                    continue
                before = element_json(view.resolved, placed.id, options)
                if not before:
                    continue
                try:
                    if h["kind"] == "size":
                        conv = resize(view, placed.id, tuple(h["key"]), 6)
                    else:
                        degrees = (h["start"] if h["key"] == "start_angle" else h["sweep"]) + 12
                        conv = turn(view, placed.id, h["key"], degrees)
                except Exception as exc:
                    tally["refused"] += 1
                    continue
                if not conv.landed:
                    tally["not landed"] += 1
                    continue
                loaded = load_text(face_path, conv.patch.text)
                after_resolved = view.place(loaded)
                after = element_json(after_resolved, placed.id, options)
                label = ".".join(h["key"]) if isinstance(h["key"], list) else h["key"]
                tally[f"{h['kind']} {label}"] += 0
                if after is None or [o["op"] for o in after] != [o["op"] for o in before]:
                    tally["ops changed shape"] += 1
                    misses.append((face_path.parent.name, placed.id, label, "op list changed shape"))
                    continue
                nb, na = numbers(before), numbers(after)
                changed = [(b, a) for b, a in zip(nb, na) if b[2] != a[2]]
                consts = {b[1] for b, _ in changed if b[1] is not None}
                literal = [b for b, _ in changed if b[1] is None]
                suffix = {"size.width": ("_WIDTH",), "size.height": ("_HEIGHT",),
                          "radius": ("_RADIUS",), "start_angle": ("_START",),
                          "sweep": ("_SWEEP",)}.get(label, ())
                own = {c for c in consts if c.endswith(suffix)}
                shifted = {c for c in consts if c.endswith(("_X", "_Y"))}
                other = consts - own - shifted
                if literal:
                    verdict = "literal values change (computed from the constant)"
                elif other:
                    verdict = "other constants change: " + ", ".join(sorted(other))
                elif shifted and h.get("gain", 1) == 1:
                    verdict = "position moves although the edge handle does not imply it"
                elif not own and not shifted:
                    verdict = "nothing named changes"
                else:
                    verdict = None
                key = f"{h['kind']} {label}"
                if verdict is None:
                    tally[key + ": exact from the named constant" + (" + the alignment shift" if shifted else "")] += 1
                else:
                    tally[key + ": " + verdict.split(":")[0]] += 1
                    misses.append((face_path.parent.name, placed.id, label, verdict))
    print("| handle: result | count |\n|---|---:|")
    for k, n in sorted(tally.items()):
        if n:
            print(f"| {k} | {n} |")
    print("\nNot predictable from the named constant alone (first 25):\n")
    for m in misses[:25]:
        print(f"- {m[0]} `{m[1]}` {m[2]}: {m[3]}")
    print()


def section_d(db):
    """The server's load of an edited face, split by stage: what a browser
    renderer cannot remove, since every edit is still checked by it."""
    from wfb import desugar, lower, validate, yamlsrc
    from wfb.build import build_ir
    from wfb.diagnostics import Bag
    print("## D. The load a release pays, by stage (warm, best of 5, ms)\n")
    print("| face | parse | schema | lower + desugar | IR | total |")
    print("|---|---:|---:|---:|---:|---:|")
    for name in ("features/progress", "showcase", "features/vector-text"):
        path = ROOT / "examples" / name / "face.yaml"
        text = path.read_text()
        best = None
        for _ in range(5):
            bag = Bag()
            t0 = time.perf_counter(); doc = yamlsrc.load(path, bag, text); a = ms(t0)
            t0 = time.perf_counter(); validate.validate(doc, bag); b = ms(t0)
            t0 = time.perf_counter(); lower.lower(doc, bag); desugar.desugar(doc, bag); c = ms(t0)
            t0 = time.perf_counter(); build_ir(doc, bag); d = ms(t0)
            row = (a, b, c, d)
            if best is None or sum(row) < sum(best):
                best = row
        a, b, c, d = best
        print(f"| {name} | {a:.0f} | {b:.0f} | {c:.0f} | {d:.0f} | {a + b + c + d:.0f} |")
    print()


if __name__ == "__main__":
    db = DeviceDatabase.discover()
    which = sys.argv[1:] or ["a", "b", "c", "d"]
    print("# Research 29 probe results\n")
    for s in which:
        {"a": section_a, "b": section_b, "c": section_c, "d": section_d}[s](db)
