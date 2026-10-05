#!/usr/bin/env python3
"""Dump what the Python compiler produces at every stage boundary, as JSON,
for the TypeScript port in ts/ to be compared against (`npm run parity`).

    ./.venv/bin/python tools/oracle.py                       # every stage, every design
    ./.venv/bin/python tools/oracle.py --stage spans data    # only these stages
    ./.venv/bin/python tools/oracle.py --design examples/showcase/face

Writes `.cache/oracle/` (gitignored):

- `index.json`: the designs, their devices, the stages dumped, and the
  commit and tool versions they came from;
- `<design>/<stage>.json` for a stage of the whole design;
- `<design>/<device>/<stage>.json` for a stage per device, and
  `<design>/<device>/preview.png`.

A design is every `*.yaml` under `examples/`, `tests/fixtures/` and
`ts/test/cases/`, named by its path without the suffix, as
`tools/snapshot.py` names them. `ts/test/cases/` holds YAML edge cases the
faces do not exercise (empty values, block scalars, comment placement, no
final newline, invalid text). They are not faces, so only their text stages
say much. A design
the compiler refuses is still a valid case: its `diagnostics-load` says why,
and the later stages are absent.

Its devices are its own `targets:`, resolved together as `wfb build` would,
and `fenix847mm`, the AMOLED target, when installed and not already a
target. That device is resolved on its own, as `wfb build -d fenix847mm`
would. `project` comes from the targets alone.

Stages, in pipeline order:

| stage | scope | what |
|---|---|---|
| `nodes` | design | the composed node tree the edit engine reads (`wfb.edit.spans.compose`): each node's kind, tag, start and end marks (index, line, column), a scalar's style and value, a collection's flow style |
| `spans` | design | `wfb.edit.spans.SpanIndex`: every entry's path and key, value and end offsets |
| `patches` | design | the editor's operations replayed on the text (`tools/oracle_patches.py`): each call's arguments and outcome |
| `load-cases` | design | seeded broken variants of the design and each load pass's diagnostics on them (`tools/oracle_cases.py`) |
| `data` | design | the parsed YAML, mappings as `[key, value]` pairs (`spans.ordered`) |
| `lowered` | design | the document after the schema and `wfb.lower` |
| `desugared` | design | the document after `wfb.desugar` |
| `face` | design | the IR (`wfb.build.load`'s `Face`) |
| `diagnostics-load` | design | every diagnostic `load` reported |
| `diagnostics-lint` | design | every diagnostic device selection, `resolve_all` and lint reported, per device set: `targets`, and `fenix847mm` alone |
| `fonts` | device | each baked font: metrics, glyph boxes, and the sheet's bytes |
| `layout` | device | the `ResolvedFace`: every placed element and box |
| `draw` | device | each layer's `jsonform` ops and fonts |
| `preview` | device | `wfb.preview.render` with default options: `preview.png` and its hash |
| `project` | design | every generated file (`wfb.emit.project.generate`): text, or a hash for binaries |

Values are JSON by one generic walk (`to_json`):
- a dataclass is an object of its fields, in declaration order;
- an enum is its value;
- a path is a string relative to the repository;
- a set is a sorted list;
- an image is `{"$image": sha256, "mode", "size"}`;
- a YAML timestamp (ruamel resolves `2026-10-05` to a date even under
  YAML 1.2) is `{"$timestamp": isoformat}`;
- a `Device` is `{"$device": id}`;
- a `Face` below the top is `{"$face": name}`.

The TypeScript side keeps these field names (snake_case), so a dump
compares with no mapping.
"""

from __future__ import annotations

import argparse
import base64
import datetime
import enum
import hashlib
import json
import math
import shutil
import subprocess
import sys
import tempfile
from dataclasses import fields, is_dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from PIL import Image  # noqa: E402

from wfb import build as build_mod  # noqa: E402
from wfb import desugar, lower, preview, validate, yamlsrc  # noqa: E402
from wfb.devices import Device, DeviceDatabase  # noqa: E402
from wfb.diagnostics import Bag  # noqa: E402
from ruamel.yaml.nodes import MappingNode, Node, ScalarNode, SequenceNode  # noqa: E402

from wfb.edit.spans import Refused, SpanIndex, compose, ordered  # noqa: E402
from wfb.ir import build as build_ir  # noqa: E402
from wfb.ir.model import Face  # noqa: E402

OUT = ROOT / ".cache" / "oracle"
#: The AMOLED target every design is also resolved on.
AMOLED = "fenix847mm"
DESIGN_STAGES = ("nodes", "spans", "patches", "load-cases", "data", "lowered", "desugared", "face", "diagnostics-load",
                 "diagnostics-lint", "project")
DEVICE_STAGES = ("fonts", "layout", "draw", "preview")
STAGES = DESIGN_STAGES + DEVICE_STAGES
#: Bumped when the dump's shape changes, so parity refuses a stale cache.
FORMAT = 4


def to_json(value: Any, *, top: bool = True, seen: tuple[int, ...] = ()) -> Any:
    """``value`` as plain JSON, by the rules in the module docstring."""
    if value is None or isinstance(value, (bool, str)):
        return value
    if isinstance(value, enum.Enum):
        return to_json(value.value, top=False, seen=seen)
    if isinstance(value, int):
        return int(value)
    if isinstance(value, float):
        if math.isnan(value) or math.isinf(value):
            return {"$float": repr(value)}
        return float(value)
    if isinstance(value, Path):
        try:
            return value.resolve().relative_to(ROOT).as_posix()
        except ValueError:
            return value.as_posix()
    if isinstance(value, Image.Image):
        return {"$image": hashlib.sha256(value.tobytes()).hexdigest(),
                "mode": value.mode, "size": list(value.size)}
    if isinstance(value, Device):
        return {"$device": value.id}
    if isinstance(value, Face) and not top:
        return {"$face": value.name}
    if isinstance(value, (datetime.date, datetime.datetime)):
        return {"$timestamp": value.isoformat()}
    if isinstance(value, (bytes, bytearray)):
        return {"$bytes": hashlib.sha256(value).hexdigest(), "length": len(value)}
    if id(value) in seen:
        return {"$cycle": type(value).__name__}
    inner = seen + (id(value),)
    if is_dataclass(value) and not isinstance(value, type):
        return {f.name: to_json(getattr(value, f.name), top=False, seen=inner)
                for f in fields(value)}
    if isinstance(value, dict):
        return {str(to_json(k, top=False, seen=inner)): to_json(v, top=False, seen=inner)
                for k, v in value.items()}
    if isinstance(value, (set, frozenset)):
        items = [to_json(v, top=False, seen=inner) for v in value]
        return sorted(items, key=lambda v: json.dumps(v, sort_keys=True))
    if isinstance(value, (list, tuple)):
        return [to_json(v, top=False, seen=inner) for v in value]
    raise TypeError(f"oracle: no JSON form for {type(value).__name__}")


def mark(m: Any) -> list[int]:
    return [m.index, m.line, m.column]


def node_json(node: Node) -> dict[str, Any]:
    """A composed node as the edit engine reads it."""
    out: dict[str, Any] = {"kind": "", "tag": node.tag, "start": mark(node.start_mark),
                           "end": mark(node.end_mark)}
    if isinstance(node, ScalarNode):
        out.update(kind="scalar", style=node.style, value=node.value)
    elif isinstance(node, SequenceNode):
        out.update(kind="sequence", flow=bool(node.flow_style),
                   items=[node_json(v) for v in node.value])
    elif isinstance(node, MappingNode):
        out.update(kind="mapping", flow=bool(node.flow_style),
                   pairs=[[node_json(k), node_json(v)] for k, v in node.value])
    else:
        raise TypeError(f"oracle: unknown node {type(node).__name__}")
    return out


def designs(only: list[str]) -> list[Path]:
    paths = sorted([*ROOT.glob("examples/**/*.yaml"), *ROOT.glob("tests/fixtures/**/*.yaml"),
                    *ROOT.glob("ts/test/cases/**/*.yaml")])
    found = [p for p in paths if not only or design_id(p) in only]
    missing = set(only) - {design_id(p) for p in found}
    if missing:
        raise SystemExit(f"oracle: no such design: {', '.join(sorted(missing))}")
    return found


def design_id(path: Path) -> str:
    return path.relative_to(ROOT).with_suffix("").as_posix()


def write(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


def diagnostics(bag: Bag, start: int = 0) -> list[Any]:
    return [to_json(d) for d in bag.items[start:]]


def dump_design(path: Path, stages: set[str], db: DeviceDatabase) -> dict[str, Any]:
    """Every requested stage for one design; returns its index entry."""
    out = OUT / design_id(path)
    text = path.read_text(encoding="utf-8")
    entry: dict[str, Any] = {"id": design_id(path), "path": path.relative_to(ROOT).as_posix(),
                             "devices": [], "stages": []}

    def done(stage: str, value: Any, where: Path = out) -> None:
        write(where / f"{stage}.json", value)
        if stage not in entry["stages"]:
            entry["stages"].append(stage)

    if "nodes" in stages:
        try:
            root = compose(text)
            done("nodes", None if root is None else node_json(root))
        except Refused as exc:
            done("nodes", {"$error": "yaml", "message": str(exc)})

    if "spans" in stages:
        try:
            index = SpanIndex(text)
            done("spans", [{"path": list(e.path), "key": e.key.start_mark.index,
                            "value": e.value.start_mark.index, "end": index.value_end(e)}
                           for e in index.entries()])
        except Exception as exc:  # the span index refuses what YAML refuses
            done("spans", {"$error": str(exc)})

    if "patches" in stages:
        from oracle_patches import battery
        done("patches", battery(text, to_json))

    if "load-cases" in stages:
        from oracle_cases import cases
        done("load-cases", cases(path, text, design_id(path), to_json))

    # `wfb.build.load`, unrolled so each boundary can be dumped.
    bag = Bag()
    doc = yamlsrc.load(path, bag, text)
    if doc is not None and "data" in stages:
        done("data", to_json(ordered(doc.data)))
    face = None
    if doc is not None and validate.validate(doc, bag) and lower.lower(doc, bag):
        if "lowered" in stages:
            done("lowered", to_json(ordered(doc.data)))
        if desugar.desugar(doc, bag):
            if "desugared" in stages:
                done("desugared", to_json(ordered(doc.data)))
            face = build_ir(doc, bag)
    if "face" in stages and face is not None:
        done("face", to_json(face))
    if "diagnostics-load" in stages:
        done("diagnostics-load", diagnostics(bag))
    if face is None or not (stages & {"diagnostics-lint", "project", *DEVICE_STAGES}):
        return entry

    # The design's own targets resolve together, as `wfb build` would: they
    # give `project`. The AMOLED target, when not one of them, resolves on
    # its own, as `wfb build -d fenix847mm` would, so a design that cannot
    # build there still has its targets' project.
    sets = [("targets", list(face.targets))]
    if AMOLED in db.ids() and AMOLED not in face.targets:
        sets.append((AMOLED, [AMOLED]))
    lint_diagnostics: dict[str, Any] = {}
    resolved: dict[str, Any] = {}
    baked: dict[str, Any] = {}
    project_set: tuple[list[Device], dict[str, Any], Bag] | None = None
    for name, wanted in sets:
        set_bag = Bag()
        devices = build_mod.select_devices(face, db, set_bag, wanted)
        got, fonts = build_mod.resolve_all(face, devices, set_bag) if devices else ({}, {})
        lint_diagnostics[name] = diagnostics(set_bag)
        resolved.update(got)
        baked.update(fonts)
        if name == "targets":
            project_set = (devices, got, set_bag)
    if "diagnostics-lint" in stages:
        done("diagnostics-lint", lint_diagnostics)
    entry["devices"] = list(resolved)

    for device_id, result in resolved.items():
        where = out / device_id
        if "fonts" in stages:
            fonts = {}
            for name, font in baked.get(device_id, {}).items():
                value = to_json(font)
                if font.sheet is not None:
                    value["sheet"] = {"mode": font.sheet.mode, "size": list(font.sheet.size),
                                      "bytes": base64.b64encode(font.sheet.tobytes()).decode()}
                fonts[name] = value
            done("fonts", fonts, where)
        if "layout" in stages:
            done("layout", to_json(result), where)
        if "draw" in stages:
            from wfb.draw.layers import layers
            stack = layers(result, preview.PreviewOptions(), paint_all=False)
            done("draw", [{"id": layer.id, "kind": layer.kind, "ops": layer.ops,
                           "fonts": to_json(layer.fonts, top=False)} for layer in stack], where)
        if "preview" in stages:
            image = preview.render(result, preview.PreviewOptions())
            where.mkdir(parents=True, exist_ok=True)
            image.save(where / "preview.png")
            done("preview", {"png": "preview.png", "mode": image.mode, "size": list(image.size),
                             "sha256": hashlib.sha256(image.tobytes()).hexdigest()}, where)

    if "project" in stages and project_set is not None and project_set[1] and project_set[2].ok():
        from wfb.emit.project import generate
        from wfb.emit.project import write as write_project
        devices, got, _ = project_set
        with tempfile.TemporaryDirectory() as tmp:
            project = generate(face, devices, Path(tmp) / "project", resolved=got)
            write_project(project)
            files = {}
            for file in sorted((Path(tmp) / "project").rglob("*")):
                if not file.is_file():
                    continue
                data = file.read_bytes()
                rel = file.relative_to(Path(tmp) / "project").as_posix()
                try:
                    files[rel] = {"text": data.decode("utf-8")}
                except UnicodeDecodeError:
                    files[rel] = {"sha256": hashlib.sha256(data).hexdigest(), "length": len(data)}
            done("project", files)
    return entry


def git_revision() -> str:
    try:
        rev = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True,
                             text=True, check=True).stdout.strip()
        dirty = subprocess.run(["git", "status", "--porcelain", "--", "wfb"], cwd=ROOT,
                               capture_output=True, text=True, check=True).stdout.strip()
        return rev + ("+dirty" if dirty else "")
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--stage", nargs="+", choices=STAGES, default=list(STAGES))
    parser.add_argument("--design", nargs="+", default=[], help="design ids, e.g. examples/showcase/face")
    args = parser.parse_args(argv)
    stages = set(args.stage)

    paths = designs(args.design)
    if not args.design and stages == set(STAGES) and OUT.exists():
        shutil.rmtree(OUT)
    db = DeviceDatabase.discover()
    index_path = OUT / "index.json"
    index: dict[str, Any] = {}
    if index_path.exists():
        index = json.loads(index_path.read_text(encoding="utf-8"))
        if index.get("format") != FORMAT:
            index = {}
    entries = {e["id"]: e for e in index.get("designs", [])}
    for path in paths:
        print(f"oracle: {design_id(path)}", file=sys.stderr)
        entry = dump_design(path, stages, db)
        old = entries.get(entry["id"], {"stages": []})
        entry["stages"] = sorted(set(old["stages"]) | set(entry["stages"]),
                                 key=STAGES.index)
        entry["devices"] = entry["devices"] or old.get("devices", [])
        entries[entry["id"]] = entry
    import PIL
    import ruamel.yaml
    write(index_path, {
        "format": FORMAT,
        "revision": git_revision(),
        "python": sys.version.split()[0],
        "pillow": PIL.__version__,
        "ruamel.yaml": ruamel.yaml.__version__,
        "designs": [entries[k] for k in sorted(entries)],
    })
    return 0


if __name__ == "__main__":
    sys.exit(main())
