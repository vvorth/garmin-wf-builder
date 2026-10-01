"""What a single draw program (one lowering, several backends) would have
to cover, and what a per-element (layered) editor preview would cost.

Backs docs/research/27-draw-program.md. Host-side only: no Garmin
toolchain, but the installed device files (`tools/setup-env.sh`).

Run from the repository root:
    ./.venv/bin/python docs/research/probes/draw-program/probe.py

Prints results and writes results.txt next to this file. Every example face
except examples/dashboard (the user's playground) is used.

1. per-element preview cost: each drawn element alone through today's
   `Renderer.render_element`, warm, at 2x;
2. cross-element coupling: what in each face is *not* one element drawing
   itself (group rings, static buffer, layouts, slots, overrides, aod);
3. the generated code's drawing vocabulary: every `dc.*` and barrel call,
   and the control flow around them, in `wfb build --no-compile` output;
4. whether today's renderer already yields a per-element list of concrete
   drawing calls: every Pillow call each element makes, recorded through a
   proxy around `Renderer.draw` and `Renderer.image`.
"""

from __future__ import annotations

import glob
import re
import statistics
import subprocess
import sys
import tempfile
import time
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[4]))

from PIL import Image, ImageDraw  # noqa: E402

from wfb import kinds, preview  # noqa: E402
from wfb.build import load, resolve_all, select_devices  # noqa: E402
from wfb.devices import DeviceDatabase  # noqa: E402
from wfb.diagnostics import Bag  # noqa: E402
from wfb.ir import slot_of  # noqa: E402
from wfb.ir.rings import ring_groups  # noqa: E402

DEVICE = "fenix8solar47mm"
OUT: list[str] = []
FACES = sorted(p for p in glob.glob("examples/**/face.yaml", recursive=True)
               if not p.startswith("examples/dashboard/"))


def say(line: str = "") -> None:
    print(line)
    OUT.append(line)


def resolve(db: DeviceDatabase, path: str):
    bag = Bag()
    face = load(Path(path), bag)
    if face is None:
        return None
    devices = select_devices(face, db, bag, [DEVICE])
    if not devices:
        return None
    resolved, _ = resolve_all(face, devices, bag)
    return resolved.get(DEVICE)


def renderer_for(resolved):
    """A `Renderer` seeded exactly as `preview.render` seeds one (default
    style, sample values), on a blank 2x canvas."""
    values = dict(preview.SAMPLE)
    for name, color in resolved.face.palette.items():
        values.setdefault(f"palette.{name}", color.value)
    for name, entry in resolved.face.config.items():
        values.setdefault(f"config.{name}", entry.default.value)
    entry = preview._resolve_style_entry(resolved.face, None)
    if entry is not None and entry.colors is not None:
        for role, color in resolved.face.color_scheme[entry.colors].colors.items():
            values.setdefault(f"config.colors.{role}", color.value)
    scale = 2
    image = Image.new("RGB", (resolved.device.width * scale, resolved.device.height * scale))
    return preview.Renderer(resolved, ImageDraw.Draw(image), image, scale, values,
                            preview.PreviewOptions(scale=scale)), entry


def per_element(db: DeviceDatabase) -> None:
    say(f"## 1. one element alone through Renderer.render_element, {DEVICE}, 2x, ms (min of 5 warm runs)")
    say(f"{'face':<44} {'n':>3} {'median':>7} {'p90':>6} {'max':>6} {'sum':>6}  slowest")
    every: list[tuple[float, str, str]] = []
    for path in FACES:
        resolved = resolve(db, path)
        if resolved is None:
            say(f"{path:<44} (does not resolve on {DEVICE})")
            continue
        renderer, entry = renderer_for(resolved)
        active = entry.layout if entry is not None else None
        times: list[tuple[float, str, str]] = []
        for placed in resolved.shown_items:
            if placed.kind == "group" or "active" not in placed.element.modes:
                continue
            if placed.element.layout is not None and placed.element.layout != active:
                continue
            best = float("inf")
            for _ in range(6):
                a = time.perf_counter()
                renderer.render_element(placed)
                best = min(best, time.perf_counter() - a)
            times.append((best * 1e3, placed.id, placed.kind))
        if not times:
            continue
        ms = sorted(t for t, _, _ in times)
        slow = max(times)
        p90 = ms[min(len(ms) - 1, int(0.9 * len(ms)))]
        say(f"{path:<44} {len(ms):>3} {statistics.median(ms):>7.2f} {p90:>6.2f} {ms[-1]:>6.2f} "
            f"{sum(ms):>6.1f}  {slow[1]} ({slow[2]})")
        every += [(t, f"{path}:{i}", k) for t, i, k in times]
    allms = sorted(t for t, _, _ in every)
    say(f"all {len(allms)} elements: median {statistics.median(allms):.2f} ms, "
        f"p90 {allms[int(0.9 * len(allms))]:.2f}, p99 {allms[int(0.99 * len(allms))]:.2f}, "
        f"max {allms[-1]:.2f}")
    by_kind: dict[str, list[float]] = {}
    for t, _, k in every:
        by_kind.setdefault(k, []).append(t)
    say("by kind (median / max ms, count): " + "; ".join(
        f"{k} {statistics.median(v):.2f}/{max(v):.2f} ({len(v)})" for k, v in sorted(by_kind.items())))
    say()


def coupling(db: DeviceDatabase) -> None:
    say("## 2. cross-element coupling per face (elements, not counting groups)")
    say(f"{'face':<44} {'elems':>5} {'ringgrp':>7} {'inring':>6} {'outline':>7} {'static':>6} "
        f"{'layout':>6} {'slot':>4} {'overr':>5} {'aod':>4} {'kinds'}")
    totals: Counter[str] = Counter()
    faces_using: Counter[str] = Counter()
    for path in FACES:
        resolved = resolve(db, path)
        if resolved is None:
            continue
        face = resolved.face
        elements = [e for e in face.walk() if e.kind != "group"]
        rings = ring_groups(face.elements)
        in_ring = {i for r in rings for i in r.ids}
        row = Counter({
            "elems": len(elements),
            "ringgrp": len(rings),
            "inring": sum(1 for e in elements if e.id in in_ring),
            "outline": sum(1 for e in elements if getattr(e, "outline", None) is not None),
            "static": sum(1 for e in elements if e.static_root is not None),
            "layout": sum(1 for e in elements if e.layout is not None),
            "slot": sum(1 for e in elements if slot_of(e) is not None or e.kind == "complication_slot"),
            "overr": sum(1 for e in elements if e.overrides),
            "aod": sum(1 for e in elements if e.aod is not None),
        })
        kc = Counter(e.kind for e in elements)
        say(f"{path:<44} " + " ".join(f"{row[k]:>{w}}" for k, w in (
            ("elems", 5), ("ringgrp", 7), ("inring", 6), ("outline", 7), ("static", 6),
            ("layout", 6), ("slot", 4), ("overr", 5), ("aod", 4)))
            + "  " + ",".join(f"{k}:{n}" for k, n in sorted(kc.items())))
        totals.update(row)
        for k, v in row.items():
            if v and k != "elems":
                faces_using[k] += 1
        for k, n in kc.items():
            totals[f"kind:{k}"] += n
            faces_using[f"kind:{k}"] += 1
    say("totals: " + ", ".join(f"{k} {v}" for k, v in sorted(totals.items())))
    say("faces using: " + ", ".join(f"{k} {v}" for k, v in sorted(faces_using.items())))
    say()


DC = re.compile(r"\bdc\.(\w+)\(")
BARREL = re.compile(r"\b(Wfb\w+)\.(\w+)\(")
FLOW = re.compile(r"^\s*(if|for|while|switch)\b|\belse\b")


def vocabulary() -> None:
    say("## 3. drawing vocabulary of the generated code (wfb build --no-compile, own targets)")
    dc: Counter[str] = Counter()
    barrel: Counter[str] = Counter()
    flow: Counter[str] = Counter()
    draw_fns = 0
    lines = 0
    with tempfile.TemporaryDirectory() as tmp:
        for i, path in enumerate(FACES):
            out = Path(tmp) / str(i)
            subprocess.run([sys.executable, "wfb.py", "--color", "never", "build", "--no-compile",
                            "-o", str(out), path], capture_output=True, check=False)
            for mc in out.rglob("source/*View.mc"):
                text = mc.read_text()
                lines += text.count("\n")
                draw_fns += len(re.findall(r"function draw\w+\(", text))
                dc.update(DC.findall(text))
                barrel.update(f"{m}.{f}" for m, f in BARREL.findall(text))
                for line in text.splitlines():
                    m = FLOW.search(line)
                    if m:
                        flow[m.group(1) or "else"] += 1
    say(f"{len(FACES)} faces, {lines} view lines, {draw_fns} draw<Id> functions")
    say(f"dc.* ({len(dc)} distinct): " + ", ".join(f"{k} {v}" for k, v in dc.most_common()))
    say(f"barrel ({len(barrel)} distinct): " + ", ".join(f"{k} {v}" for k, v in barrel.most_common()))
    say("control flow: " + ", ".join(f"{k} {v}" for k, v in flow.most_common()))
    say()


class Recorder:
    """Forwards every attribute to the wrapped Pillow object, counting the
    calls made through it."""

    def __init__(self, inner, log: Counter, prefix: str) -> None:
        object.__setattr__(self, "_inner", inner)
        object.__setattr__(self, "_log", log)
        object.__setattr__(self, "_prefix", prefix)

    def __getattr__(self, name):
        value = getattr(self._inner, name)
        if callable(value):
            def call(*a, **k):
                self._log[f"{self._prefix}.{name}"] += 1
                return value(*a, **k)
            return call
        return value


def recorded(db: DeviceDatabase) -> None:
    say("## 4. Pillow calls each element makes through today's Renderer (default frame)")
    calls: Counter[str] = Counter()
    per_kind: dict[str, Counter[str]] = {}
    elements = 0
    for path in FACES:
        resolved = resolve(db, path)
        if resolved is None:
            continue
        renderer, entry = renderer_for(resolved)
        active = entry.layout if entry is not None else None
        for placed in resolved.shown_items:
            if placed.kind == "group" or "active" not in placed.element.modes:
                continue
            if placed.element.layout is not None and placed.element.layout != active:
                continue
            log: Counter[str] = Counter()
            draw, image = renderer.draw, renderer.image
            renderer.draw = Recorder(draw, log, "draw")
            renderer.image = Recorder(image, log, "image")
            try:
                renderer.render_element(placed)
            finally:
                renderer.draw, renderer.image = draw, image
            elements += 1
            calls.update(log)
            per_kind.setdefault(placed.kind, Counter()).update(set(log))
    say(f"{elements} elements; calls: " + ", ".join(f"{k} {v}" for k, v in calls.most_common()))
    for kind, c in sorted(per_kind.items()):
        say(f"  {kind}: elements using each call: " + ", ".join(f"{k} {v}" for k, v in c.most_common()))
    say()


def main() -> None:
    db = DeviceDatabase.discover()
    resolve(db, FACES[0])  # import and first-resolve costs out of the timings
    per_element(db)
    coupling(db)
    vocabulary()
    recorded(db)
    Path(__file__).with_name("results.txt").write_text("\n".join(OUT) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
