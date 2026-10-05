"""Every example YAML's span index as ruamel sees it (wfb.edit.spans), and
its data, for yaml.mjs to compare with the `yaml` package.

    ./.venv/bin/python docs/research/probes/typescript-stack/dump_spans.py > spans.json
"""
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, ".")
from wfb.edit.spans import SpanIndex, ordered, parse  # noqa: E402

out = {}
for face in sorted(Path("examples").rglob("*.yaml")):
    text = face.read_text(encoding="utf-8")
    try:
        index = SpanIndex(text)
    except Exception:  # not a face
        continue
    t = time.perf_counter()
    data = parse(text)
    ms = (time.perf_counter() - t) * 1000
    out[str(face)] = {
        "data": json.loads(json.dumps(ordered(data), default=str)),
        "ruamel_ms": round(ms, 1),
        "entries": [{"path": [str(p) for p in e.path], "key": e.key.start_mark.index,
                     "value": e.value.start_mark.index, "value_end": index.value_end(e)}
                    for e in index.entries()],
    }
json.dump(out, sys.stdout)
