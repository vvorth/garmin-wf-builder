"""What a GUI editor over the YAML can rely on: pipeline latency, whether a
re-dump round-trips, and whether a span-based text patch moves an element.

Backs docs/research/26-gui-editor.md. Host-side only: no Garmin toolchain,
no simulator, but the installed device files (`tools/setup-env.sh`).

Run from the repository root:
    ./.venv/bin/python docs/research/probes/gui-editor/probe.py

Prints results and writes results.txt next to this file. Every example face
except examples/dashboard (the user's playground) is used; the patch
experiment writes a throwaway `.gui-probe.yaml` beside each face (so relative
font paths still resolve) and deletes it again.
"""
from __future__ import annotations

import difflib
import glob
import io
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, ".")

from ruamel.yaml import YAML  # noqa: E402
from ruamel.yaml.nodes import MappingNode, ScalarNode, SequenceNode  # noqa: E402

from wfb import migrate, preview  # noqa: E402
from wfb.build import load, resolve_all, select_devices  # noqa: E402
from wfb.devices import DeviceDatabase  # noqa: E402
from wfb.diagnostics import Bag  # noqa: E402
from wfb.layout import ResolvedFace  # noqa: E402
from wfb.units import Length  # noqa: E402

DEVICE = "fenix8solar47mm"
LATENCY_FACES = [
    "examples/features/progress/face.yaml",
    "examples/features/styles/face.yaml",
    "examples/features/vector-text/face.yaml",
    "examples/showcase/face.yaml",
]
FACES = sorted(f for f in glob.glob("examples/**/face.yaml", recursive=True)
               if "examples/dashboard/" not in f)
OUT: list[str] = []


def say(line: str = "") -> None:
    print(line)
    OUT.append(line)


def changed_lines(a: str, b: str) -> list[str]:
    return [line for line in difflib.unified_diff(a.splitlines(), b.splitlines(), lineterm="", n=0)
            if line[:1] in "+-" and line[:3] not in ("+++", "---")]


def resolve(db: DeviceDatabase, path: Path) -> ResolvedFace | None:
    bag = Bag()
    face = load(path, bag)
    if face is None:
        return None
    devices = select_devices(face, db, bag, [DEVICE])
    if not devices:
        return None
    resolved, _ = resolve_all(face, devices, bag)
    return resolved.get(DEVICE)


# -- 1. latency of the in-process pipeline ------------------------------------

def latency(db: DeviceDatabase) -> None:
    say(f"## 1. in-process pipeline latency on {DEVICE}, 2x, ms (run 0 is cold)")
    say(f"{'face':<42} {'lines':>5} {'run':>3} {'load':>6} {'resolve':>8} {'render':>7} {'total':>6}")
    for design in LATENCY_FACES:
        path = Path(design)
        lines = len(path.read_text(encoding="utf-8").splitlines())
        for run in range(4):
            bag = Bag()
            a = time.perf_counter()
            face = load(path, bag)
            b = time.perf_counter()
            assert face is not None, design
            resolved, _ = resolve_all(face, select_devices(face, db, bag, [DEVICE]), bag)
            c = time.perf_counter()
            preview.render(resolved[DEVICE], preview.PreviewOptions(scale=2))
            d = time.perf_counter()
            say(f"{design:<42} {lines:>5} {run:>3} {(b - a) * 1e3:>6.0f} {(c - b) * 1e3:>8.0f} "
                f"{(d - c) * 1e3:>7.0f} {(d - a) * 1e3:>6.0f}")
    say()


# -- 2. does a ruamel load/dump round-trip byte for byte? ---------------------

def round_trip() -> None:
    say("## 2. ruamel round-trip load -> dump, byte-identical?")
    plain = tuned = 0
    worst: list[tuple[int, str, list[str]]] = []
    for design in FACES:
        text = Path(design).read_text(encoding="utf-8")
        y = YAML()
        out = io.StringIO()
        y.dump(y.load(text), out)
        plain += out.getvalue() == text
        # Tuned the way `wfb migrate` tunes it: the file's own sequence
        # indent, quotes preserved, no line folding.
        indent, offset = migrate._guess_sequence_indent(text)
        y = YAML()
        y.preserve_quotes = True
        y.width = 4096
        y.indent(mapping=2, sequence=indent or 2, offset=offset or 0)
        out = io.StringIO()
        y.dump(y.load(text), out)
        diff = changed_lines(text, out.getvalue())
        tuned += not diff
        worst.append((len(diff), design, diff[:2]))
    say(f"default YAML():                       {plain}/{len(FACES)} byte-identical")
    say(f"tuned (quotes, indent, width 4096):  {tuned}/{len(FACES)} byte-identical")
    say("changed lines after the tuned dump (-old/+new), smallest and largest:")
    worst.sort()
    for count, design, sample in worst[:2] + worst[-2:]:
        say(f"  {count:>4}  {design}  {sample}")
    say()


# -- 3. span-based patch: move each element's at.dy by +10 of its own unit ----

def dy_scalars(node: object, key: str | None = None):
    """(element id, the `dy` scalar node) for every element-shaped mapping
    -- one with `type:` -- whose cartesian `at:` has a `dy`."""
    if isinstance(node, MappingNode):
        keys = {k.value: v for k, v in node.value if isinstance(k, ScalarNode)}
        at = keys.get("at")
        if key and "type" in keys and isinstance(at, MappingNode):
            sub = {k.value: v for k, v in at.value if isinstance(k, ScalarNode)}
            if isinstance(sub.get("dy"), ScalarNode) and "angle" not in sub:
                yield key, sub["dy"]
        for k, v in node.value:
            yield from dy_scalars(v, k.value if isinstance(k, ScalarNode) else None)
    elif isinstance(node, SequenceNode):
        for v in node.value:
            yield from dy_scalars(v, None)


def span_patch(db: DeviceDatabase) -> None:
    say("## 3. span-based patch: at.dy += 10 (author's own unit), up to 3 elements per face")
    edits = one_line = moved = 0
    units: dict[str, int] = {}
    for design in FACES:
        path = Path(design)
        text = path.read_text(encoding="utf-8")
        root = YAML().compose(io.StringIO(text))
        before = resolve(db, path)
        for element_id, scalar in list(dy_scalars(root))[:3]:
            start, end = scalar.start_mark.index, scalar.end_mark.index
            raw = text[start:end]
            try:
                length = Length.parse(scalar.value)
            except Exception:
                continue
            unit = "" if length.unit == "px" and "px" not in raw else length.unit
            new = f"{length.value + 10:g}{unit}"
            if raw[:1] in "\"'":
                new = raw[0] + new + raw[0]
            patched = text[:start] + new + text[end:]
            edits += 1
            units[length.unit] = units.get(length.unit, 0) + 1
            one_line += len(changed_lines(text, patched)) == 2
            probe = path.with_name(".gui-probe.yaml")
            probe.write_text(patched, encoding="utf-8")
            try:
                after = resolve(db, probe)
            finally:
                probe.unlink()
            if before is None or after is None:
                say(f"  {design} {element_id}: did not resolve")
                continue
            old = {p.id: p for p in before.items}[element_id]
            new_placed = {p.id: p for p in after.items}[element_id]
            dy = new_placed.center[1] - old.center[1]
            if dy > 0 and new_placed.center[0] == old.center[0]:
                moved += 1
            else:
                say(f"  {design} {element_id}: {raw!r} -> {new!r} moved {dy}px")
    say(f"faces: {len(FACES)}   edits: {edits}   by unit: {units}")
    say(f"diff is exactly one changed line:          {one_line}/{edits}")
    say(f"element moved down on {DEVICE}, x kept:  {moved}/{edits}")


def main() -> None:
    db = DeviceDatabase.discover()
    latency(db)
    round_trip()
    span_patch(db)
    Path(__file__).with_name("results.txt").write_text("\n".join(OUT) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
